"use client";

/**
 * The JARVIS workspace.
 *
 * Deliberately thin: sessions come from `useSessions`, the live run from
 * `useRun` (events -> `runReducer` -> `RunView`), and every component renders
 * from those. Nothing here interprets events.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";

import BrowserPreview from "@/components/BrowserPreview";
import ModelSelectorModal from "@/components/ModelSelector";
import VoiceDock, { type VoiceDockHandle } from "@/components/Voice/VoiceDock";
import Composer from "@/components/Workspace/Composer";
import Conversation from "@/components/Workspace/Conversation";
import DragHandle from "@/components/Workspace/DragHandle";
import Sidebar from "@/components/Workspace/Sidebar";
import TopBar from "@/components/Workspace/TopBar";
import ContextInspector from "@/components/ContextInspector";
import { API_BASE } from "@/lib/runtime/client";
import { isActive, type ArtifactView, type RunView } from "@/lib/runtime/runReducer";
import type { Transcript } from "@/lib/runtime/types";
import { useRun } from "@/lib/runtime/useRun";
import { useSessions } from "@/lib/runtime/useSessions";

/** Transcripts below this confidence go to the text box for a check. */
const MIN_VOICE_CONFIDENCE = 0.45;

const clamp = (min: number, max: number, value: number) => Math.max(min, Math.min(max, value));
const absolute = (url: string) => (url.startsWith("/") ? `${API_BASE}${url}` : url);

async function readAttachments(files: File[]) {
  const out: Array<{ name: string; content: string; size: number }> = [];
  for (const file of files) {
    try {
      out.push({ name: file.name, content: await file.text(), size: file.size });
    } catch {
      // Binary or unreadable files are skipped rather than failing the run.
    }
  }
  return out;
}

export default function JarvisWorkspace() {
  const sessions = useSessions();
  const voiceRef = useRef<VoiceDockHandle>(null);
  /** The session the current run belongs to (it may have just been created). */
  const runSessionRef = useRef<string | null>(null);

  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<File[]>([]);
  const [model, setModel] = useState("openai/gpt-oss-120b");
  const [provider, setProvider] = useState("groq");
  const [modelPickerOpen, setModelPickerOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  /** An artifact the user chose to open; wins over the agent's preview. */
  const [openedArtifactUrl, setOpenedArtifactUrl] = useState<string | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(256);
  const [previewWidth, setPreviewWidth] = useState(440);

  const { adoptSession } = sessions;

  const onFinished = useCallback(
    (finished: RunView) => {
      if (runSessionRef.current) void adoptSession(runSessionRef.current);
      // Answer out loud only when the request was spoken.
      if (finished.inputMode === "voice") {
        const spoken =
          finished.phase === "completed"
            ? finished.reply || "Done."
            : finished.error
              ? `That didn't work. ${finished.error.message}`
              : "";
        // A speech failure never touches the run: the reply is on screen.
        if (spoken) void voiceRef.current?.speak(spoken).catch(() => undefined);
      }
    },
    [adoptSession],
  );

  const run = useRun(onFinished);
  const { view } = run;
  const busy = isActive(view);

  // A finished run belongs to its session; don't carry it into another one.
  useEffect(() => {
    if (!busy && view.phase !== "idle" && sessions.sessionId !== runSessionRef.current) {
      run.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessions.sessionId]);

  // --- preview ------------------------------------------------------------------

  const workspaceId = sessions.workspaceId ?? "default";
  const previewFor = (path: string) => {
    // An absolute path (C:\..., /home/...) is reduced to its file name; the
    // preview endpoint resolves names inside the workspace.
    const rel = /^([a-zA-Z]:)?[\\/]/.test(path) ? path.split(/[\\/]/).pop() ?? path : path;
    const encoded = rel.split(/[\\/]/).filter(Boolean).map(encodeURIComponent).join("/");
    return `${API_BASE}/api/preview/${encodeURIComponent(workspaceId)}/${encoded}`;
  };
  // During a run, only a preview the agent actually asked for is shown; the
  // last HTML file written becomes the fallback once the run has finished.
  const agentPreview = view.previewUrl
    ? absolute(view.previewUrl)
    : view.previewPath
      ? previewFor(view.previewPath)
      : !busy && view.lastHtmlPath
        ? previewFor(view.lastHtmlPath)
        : null;
  const previewUrl = openedArtifactUrl ?? agentPreview;

  const autoOpened = useRef<string | null>(null);
  useEffect(() => {
    if (agentPreview && agentPreview !== autoOpened.current) {
      autoOpened.current = agentPreview;
      setOpenedArtifactUrl(null);
      setPreviewOpen(true);
    }
  }, [agentPreview]);

  const openArtifact = useCallback((artifact: ArtifactView) => {
    if (!artifact.url) return;
    const url = absolute(artifact.url);
    if (artifact.previewable) {
      setOpenedArtifactUrl(url);
      setPreviewOpen(true);
    } else {
      window.open(url, "_blank", "noopener");
    }
  }, []);

  // --- running ------------------------------------------------------------------

  const submit = useCallback(
    async (text: string, inputMode: "text" | "voice" = "text", transcript?: Transcript) => {
      const objective = text.trim();
      if (!objective || busy) return;

      const files = await readAttachments(attachments);
      if (inputMode === "text") setInput("");
      setAttachments([]);
      setOpenedArtifactUrl(null);
      autoOpened.current = null;

      const started = await run.start({
        sessionId: sessions.sessionId,
        workspaceId: sessions.workspaceId,
        objective,
        inputMode,
        model,
        provider,
        attachments: files,
        audioUrl: transcript?.audio_url,
        voice: transcript
          ? {
              confidence: transcript.confidence ?? undefined,
              duration_s: transcript.duration_s,
              model: transcript.model,
              language: transcript.language ?? undefined,
            }
          : undefined,
      });
      if (started) {
        runSessionRef.current = started.sessionId;
        if (started.sessionId !== sessions.sessionId) void adoptSession(started.sessionId);
      }
    },
    [busy, attachments, run, sessions.sessionId, sessions.workspaceId, model, provider, adoptSession],
  );

  const handleTranscript = useCallback(
    (transcript: Transcript) => {
      const text = transcript.text?.trim();
      if (!text || transcript.empty) return;
      // A misheard instruction can still change files: let the user check it.
      if (transcript.confidence != null && transcript.confidence < MIN_VOICE_CONFIDENCE) {
        setInput(text);
        return;
      }
      void submit(text, "voice", transcript);
    },
    [submit],
  );

  const newSession = useCallback(() => {
    runSessionRef.current = null;
    run.reset();
    sessions.newSession();
    setPreviewOpen(false);
    setOpenedArtifactUrl(null);
  }, [run, sessions]);

  const workspaceName =
    sessions.workspaces.find((w) => w.id === sessions.workspaceId)?.name ?? workspaceId;

  return (
    <>
      <TopBar
        workspaceName={workspaceName}
        previewAvailable={!!previewUrl}
        previewOpen={previewOpen}
        onTogglePreview={() => setPreviewOpen((open) => !open)}
        connection={busy ? run.connection : null}
      />

      <div className="flex flex-1 overflow-hidden">
        <Sidebar sessions={sessions} width={sidebarWidth} busy={busy} onNewSession={newSession} />
        <DragHandle
          onDrag={(delta) => setSidebarWidth((w) => clamp(180, 480, w + delta))}
          className="border-r-2 border-fra-black"
        />

        <main className="flex min-w-0 flex-1 overflow-hidden bg-fra-cream">
          <section className="flex min-w-0 flex-1 flex-col overflow-hidden">
            <div className="flex-1 overflow-y-auto">
              <Conversation
                turns={sessions.turns}
                view={view}
                contextSummary={sessions.contextSummary}
                previewAvailable={!!previewUrl}
                onOpenPreview={() => {
                  setOpenedArtifactUrl(null);
                  setPreviewOpen(true);
                }}
                onOpenArtifact={openArtifact}
                onExample={(text) => setInput(text)}
              />
              {view && <ContextInspector run={view} />}
            </div>

            <Composer
              value={input}
              onChange={setInput}
              onSubmit={() => void submit(input)}
              onStop={() => void run.cancel()}
              busy={busy}
              attachments={attachments}
              onAttach={(files) => setAttachments((prev) => [...prev, ...files])}
              onRemoveAttachment={(idx) => setAttachments((prev) => prev.filter((_, i) => i !== idx))}
              model={model}
              provider={provider}
              onOpenModelPicker={() => setModelPickerOpen(true)}
              voice={
                <VoiceDock
                  ref={voiceRef}
                  sessionId={sessions.sessionId}
                  workspaceId={sessions.workspaceId}
                  disabled={busy}
                  executing={busy}
                  onTranscript={handleTranscript}
                />
              }
            />
          </section>

          {previewOpen && previewUrl && (
            <>
              <DragHandle
                onDrag={(delta) => setPreviewWidth((w) => clamp(260, 960, w - delta))}
                className="border-l-2 border-fra-black"
              />
              <section
                className="flex flex-shrink-0 flex-col overflow-hidden border-l-2 border-fra-black bg-neutral-100"
                style={{ width: previewWidth }}
              >
                <BrowserPreview
                  url={previewUrl}
                  isOpen={previewOpen}
                  onClose={() => setPreviewOpen(false)}
                  title="Preview"
                  embedded
                />
              </section>
            </>
          )}
        </main>
      </div>

      <footer className="z-30 flex h-6 flex-shrink-0 select-none items-center justify-between border-t-2 border-fra-black bg-fra-cream px-3 font-mono text-[10px]">
        <div className="flex items-center space-x-3">
          <span className="font-bold">JARVIS v1.0.0</span>
          <span>|</span>
          <span className="text-neutral-700">{workspaceName}</span>
        </div>
        <div className="font-bold uppercase tracking-widest text-neutral-800">IDEAS TODAY. EXECUTION TOMORROW.</div>
      </footer>

      <ModelSelectorModal
        isOpen={modelPickerOpen}
        onClose={() => setModelPickerOpen(false)}
        selectedModel={model}
        selectedProvider={provider}
        onSelect={(m, p) => {
          setModel(m);
          setProvider(p);
          setModelPickerOpen(false);
        }}
      />
    </>
  );
}
