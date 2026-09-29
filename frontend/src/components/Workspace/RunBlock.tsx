"use client";

/**
 * One run as the user sees it: what JARVIS is doing, what it made, and what
 * it said. Renders from `RunView` only -- never from agent internals, and
 * never model reasoning.
 */

import React from "react";

import LatticeLoader from "@/components/LatticeLoader";
import type { ArtifactView, ProgressStep, RunView } from "@/lib/runtime/runReducer";

interface RunBlockProps {
  view: RunView;
  previewAvailable: boolean;
  onOpenPreview: () => void;
  onOpenArtifact: (artifact: ArtifactView) => void;
  /** Wired in Phase 2; without it the request is shown but not actionable. */
  onDecidePermission?: (requestId: string, decision: "approve" | "deny") => void;
  /** The saved assistant turn, for when the run's events carried no reply. */
  fallbackReply?: string;
}

const PHASE_CHIP: Record<RunView["phase"], { text: string; cls: string } | null> = {
  idle: null,
  starting: { text: "STARTING", cls: "bg-fra-yellow text-black animate-pulse" },
  running: { text: "WORKING", cls: "bg-fra-yellow text-black animate-pulse" },
  paused: { text: "WAITING FOR YOU", cls: "bg-black text-fra-yellow" },
  completed: { text: "DONE", cls: "bg-fra-green text-white" },
  failed: { text: "FAILED", cls: "bg-red-500 text-white" },
  cancelled: { text: "STOPPED", cls: "bg-neutral-500 text-white" },
};

export function formatBytes(n: number): string {
  if (!n) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

const RunBlock: React.FC<RunBlockProps> = ({
  view,
  previewAvailable,
  onOpenPreview,
  onOpenArtifact,
  onDecidePermission,
  fallbackReply,
}) => {
  const chip = PHASE_CHIP[view.phase];
  const active = view.phase === "starting" || view.phase === "running";

  return (
    <div className="flex max-w-4xl items-start">
      <div className="mr-3 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded bg-black text-sm font-bold text-white">
        J_
      </div>

      <div className="flex-1 space-y-3 border-2 border-fra-black bg-white p-4 font-mono shadow-brutal">
        {/* Status line */}
        <div className="flex items-center justify-between border-b-2 border-fra-black pb-2">
          <div className="flex items-center gap-2">
            {chip && (
              <span className={`border border-black px-1.5 py-0.5 text-[10px] font-extrabold ${chip.cls}`}>
                {chip.text}
              </span>
            )}
            {view.worker.switches > 0 && view.worker.current && (
              <span className="text-[10px] text-neutral-500" title={view.worker.reason ?? undefined}>
                on {view.worker.current}
              </span>
            )}
          </div>
          {active && (
            <LatticeLoader
              status="working"
              label="Working"
              pattern="orbit"
              grid={3}
              shape="round"
              cellSize={5}
              gap={2}
              fontSize={11}
              step={90}
              showTimer
            />
          )}
        </div>

        {/* Progress */}
        {view.steps.length > 0 && (
          <ol className="space-y-1">
            {view.steps.map((step) => (
              <StepRow key={step.id} step={step} />
            ))}
          </ol>
        )}

        {/* Permission request */}
        {view.permission && (
          <div className="border-2 border-black bg-fra-yellow/30 p-3">
            <div className="text-[10px] font-extrabold uppercase tracking-wide">JARVIS needs permission</div>
            <div className="mt-1 text-[12px] font-bold text-black">{view.permission.summary}</div>
            {view.permission.permission && (
              <div className="mt-0.5 text-[10px] text-neutral-600">
                Permission: <code>{view.permission.permission}</code>
                {view.permission.risk && <> · Risk: {view.permission.risk}</>}
              </div>
            )}
            {onDecidePermission && view.permission.requestId && (
              <div className="mt-2 flex gap-2">
                <button
                  type="button"
                  onClick={() => onDecidePermission(view.permission!.requestId, "deny")}
                  className="border-2 border-black bg-white px-3 py-1 text-[11px] font-bold shadow-brutal-sm hover:bg-neutral-100"
                >
                  Deny
                </button>
                <button
                  type="button"
                  onClick={() => onDecidePermission(view.permission!.requestId, "approve")}
                  className="border-2 border-black bg-black px-3 py-1 text-[11px] font-bold text-white shadow-brutal-sm hover:bg-neutral-800"
                >
                  Allow
                </button>
              </div>
            )}
          </div>
        )}

        {/* Reply */}
        {view.phase === "completed" && (
          <div className="whitespace-pre-wrap font-sans text-[13px] leading-relaxed text-black">
            {view.reply || fallbackReply || "Done."}
          </div>
        )}

        {/* What it made */}
        {(view.artifacts.length > 0 || previewAvailable) && view.phase !== "starting" && (
          <div className="space-y-2 border-t border-neutral-200 pt-2">
            {previewAvailable && (
              <button
                type="button"
                onClick={onOpenPreview}
                className="flex items-center gap-2 border-2 border-black bg-fra-yellow px-3 py-1.5 text-xs font-bold shadow-brutal-sm transition-colors hover:bg-black hover:text-white"
              >
                Open Preview <span aria-hidden="true">&#8599;</span>
              </button>
            )}
            {view.artifacts.length > 0 && (
              <ArtifactList artifacts={view.artifacts} onOpen={onOpenArtifact} />
            )}
          </div>
        )}

        {/* Failure */}
        {(view.phase === "failed" || view.phase === "cancelled") && view.error && (
          <div className="space-y-1 border border-red-300 bg-red-50 p-3 text-red-900">
            <div className="text-xs font-bold">{view.error.message}</div>
            {view.phase === "failed" && view.reply && view.reply !== view.error.message && (
              <div className="whitespace-pre-wrap text-[11px]">{view.reply}</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

const StepRow: React.FC<{ step: ProgressStep }> = ({ step }) => {
  const mark =
    step.status === "running" ? (
      <span className="font-bold text-amber-500 animate-pulse">&#9656;</span>
    ) : step.status === "done" ? (
      <span className="font-bold text-fra-green">&#10003;</span>
    ) : (
      <span className="font-bold text-red-500">&#10005;</span>
    );

  return (
    <li className="flex items-start gap-2 text-[12px]">
      <span className="w-3 flex-shrink-0 text-center">{mark}</span>
      <div className="min-w-0 flex-1">
        <span className={step.status === "failed" ? "text-red-700" : "text-black"}>{step.label}</span>
        {step.kind === "memory" && (
          <span className="ml-2 border border-violet-400 bg-violet-50 px-1 text-[9px] font-bold uppercase text-violet-700">
            memory
          </span>
        )}
        {step.detail && (
          <div
            className={`mt-0.5 text-[11px] ${
              step.kind === "memory" ? "italic text-violet-800" : step.status === "failed" ? "text-red-600" : "text-neutral-500"
            }`}
          >
            {step.detail}
          </div>
        )}
      </div>
    </li>
  );
};

export const ArtifactList: React.FC<{
  artifacts: ArtifactView[];
  onOpen: (artifact: ArtifactView) => void;
}> = ({ artifacts, onOpen }) => (
  <div className="flex flex-wrap gap-1.5">
    {artifacts.map((a) => (
      <button
        key={a.id}
        type="button"
        onClick={() => onOpen(a)}
        disabled={!a.url}
        title={a.previewable ? `Preview ${a.filename}` : `Download ${a.filename}`}
        className="flex items-center gap-1.5 border border-neutral-300 bg-neutral-50 px-2 py-1 text-[11px] font-bold text-neutral-800 shadow-sm transition-colors hover:border-black hover:bg-fra-yellow disabled:cursor-not-allowed disabled:opacity-50"
      >
        <span>{a.filename}</span>
        {a.size > 0 && <span className="text-[9px] font-normal text-neutral-500">{formatBytes(a.size)}</span>}
        <span className="text-[9px] text-neutral-500" aria-hidden="true">{a.previewable ? "↗" : "↓"}</span>
      </button>
    ))}
  </div>
);

export default RunBlock;
