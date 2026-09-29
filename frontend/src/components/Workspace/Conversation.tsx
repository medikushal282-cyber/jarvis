"use client";

/**
 * The session's turns, with the live run rendered in place.
 *
 * The run currently in `view` replaces its assistant turn (or trails the
 * history until the server has recorded it), so there is one source of truth
 * for what the run did. Past runs show their reply and their artifacts.
 */

import React, { useEffect, useRef } from "react";

import { fromResultArtifact, type ArtifactView, type RunView } from "@/lib/runtime/runReducer";
import type { Turn } from "@/lib/runtime/types";

import RunBlock, { ArtifactList } from "./RunBlock";

interface ConversationProps {
  turns: Turn[];
  view: RunView;
  contextSummary: string;
  previewAvailable: boolean;
  onOpenPreview: () => void;
  onOpenArtifact: (artifact: ArtifactView) => void;
  onDecidePermission?: (requestId: string, decision: "approve" | "deny") => void;
  onExample: (text: string) => void;
}

const EXAMPLES = [
  "Create an ecommerce website and display it",
  "Create numbers.txt containing 1, 2, 3 and then read it",
  "What can you do in this workspace?",
];

const Conversation: React.FC<ConversationProps> = ({
  turns,
  view,
  contextSummary,
  previewAvailable,
  onOpenPreview,
  onOpenArtifact,
  onDecidePermission,
  onExample,
}) => {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length, view.steps.length, view.phase, view.permission]);

  const renderRunBlock = (fallbackReply?: string) => (
    <RunBlock
      view={view}
      previewAvailable={previewAvailable}
      onOpenPreview={onOpenPreview}
      onOpenArtifact={onOpenArtifact}
      onDecidePermission={onDecidePermission}
      fallbackReply={fallbackReply}
    />
  );

  const liveRunId = view.runId;
  const hasLiveRun = view.phase !== "idle";
  const recordedUser = hasLiveRun && !!liveRunId && turns.some((t) => t.role === "user" && t.run_id === liveRunId);
  const recordedReply = hasLiveRun && !!liveRunId && turns.some((t) => t.role === "assistant" && t.run_id === liveRunId);

  if (turns.length === 0 && !hasLiveRun) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center font-mono">
        <div className="bg-black px-3 py-1 text-2xl font-extrabold tracking-tighter text-white">JARVIS_</div>
        <p className="max-w-md text-[12px] text-neutral-600">
          Tell JARVIS what you want done, by typing or with the voice button. It works in this
          workspace and shows you what it did.
        </p>
        <div className="flex max-w-xl flex-wrap justify-center gap-2">
          {EXAMPLES.map((text) => (
            <button
              key={text}
              type="button"
              onClick={() => onExample(text)}
              className="border-2 border-black bg-white px-3 py-1.5 text-[11px] font-bold shadow-brutal-sm hover:bg-fra-yellow"
            >
              {text}
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4 p-4">
      {contextSummary && (
        <div className="flex items-start gap-2.5 border-2 border-fra-black bg-white p-3 font-mono text-[11px] shadow-brutal">
          <span className="flex-shrink-0 border border-black bg-fra-yellow px-1.5 py-0.5 text-[9px] font-extrabold uppercase">
            Session memory
          </span>
          <span className="flex-1 leading-relaxed text-black">{contextSummary}</span>
        </div>
      )}

      {turns.map((turn) => {
        if (turn.role === "assistant" && hasLiveRun && turn.run_id === liveRunId) {
          return <React.Fragment key={turn.id}>{renderRunBlock(turn.content)}</React.Fragment>;
        }
        if (turn.role === "user") return <UserBubble key={turn.id} turn={turn} />;
        return <AssistantTurn key={turn.id} turn={turn} onOpenArtifact={onOpenArtifact} />;
      })}

      {/* The live run before the server has recorded it */}
      {hasLiveRun && !recordedUser && (
        <UserBubble turn={{ id: "pending", role: "user", content: view.objective, ts: "", input_mode: view.inputMode }} />
      )}
      {hasLiveRun && !recordedReply && renderRunBlock()}

      <div ref={endRef} />
    </div>
  );
};

const UserBubble: React.FC<{ turn: Turn }> = ({ turn }) => (
  <div className="ml-auto flex max-w-3xl justify-end">
    <div className="max-w-[80%] border-2 border-fra-black bg-white p-3 font-mono text-[12px] text-black shadow-brutal">
      <div className="whitespace-pre-wrap">{turn.content}</div>
      <div className="mt-1 flex items-center gap-2 text-[8px] text-neutral-400">
        {turn.input_mode === "voice" && <span className="font-bold uppercase">spoken</span>}
        {turn.ts && <span>{new Date(turn.ts).toLocaleTimeString()}</span>}
      </div>
    </div>
  </div>
);

const AssistantTurn: React.FC<{ turn: Turn; onOpenArtifact: (a: ArtifactView) => void }> = ({
  turn,
  onOpenArtifact,
}) => {
  const raw = (turn.metadata?.artifacts ?? []) as any[];
  const artifacts = raw.filter((a) => a && a.id).map(fromResultArtifact);
  const failed = turn.metadata?.status === "failed";

  return (
    <div className="flex max-w-3xl justify-start">
      <div className="mr-2 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded bg-black text-[10px] font-bold text-white">
        J_
      </div>
      <div
        className={`max-w-[80%] space-y-2 border p-3 font-mono text-[12px] ${
          failed ? "border-red-300 bg-red-50 text-red-900" : "border-neutral-300 bg-neutral-50 text-neutral-800"
        }`}
      >
        <div className="whitespace-pre-wrap">{turn.content}</div>
        {artifacts.length > 0 && <ArtifactList artifacts={artifacts} onOpen={onOpenArtifact} />}
        {turn.ts && <div className="text-[8px] text-neutral-400">{new Date(turn.ts).toLocaleTimeString()}</div>}
      </div>
    </div>
  );
};

export default Conversation;
