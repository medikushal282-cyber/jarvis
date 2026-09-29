"use client";

/**
 * "I tell it what I want, it does it, then I can see what it completed."
 *
 * Renders from RunResult alone -- never from agent state. That is what lets
 * the brain be rewritten without touching this file.
 *
 * Panel order is deliberate (docs/runtime/RESULTS.md section 6): summary,
 * artifacts, actions, memory, errors, timeline. The memory block is the one
 * that shows the Hindsight layer actually changing behaviour.
 */

import React, { useState } from "react";

import { runs as runsApi } from "@/lib/runtime/client";
import type { Artifact, RunResult, RunStatus } from "@/lib/runtime/types";

interface RunResultPanelProps {
  result: RunResult | null;
  loading?: boolean;
  onOpenArtifact?: (artifact: Artifact) => void;
  className?: string;
}

const STATUS_STYLE: Record<RunStatus, string> = {
  completed: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  running: "border-cyan-500/40 bg-cyan-500/10 text-cyan-300 animate-pulse",
  pending: "border-neutral-600 bg-neutral-800 text-neutral-400",
  paused: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  failed: "border-red-500/40 bg-red-500/10 text-red-300",
  cancelled: "border-neutral-600 bg-neutral-800 text-neutral-400",
  rejected: "border-neutral-600 bg-neutral-800 text-neutral-400",
};

function formatBytes(n: number): string {
  if (!n) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDuration(ms: number): string {
  if (!ms) return "";
  if (ms < 1000) return `${ms} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${Math.round(s - m * 60)}s`;
}

export const RunResultPanel: React.FC<RunResultPanelProps> = ({
  result,
  loading = false,
  onOpenArtifact,
  className = "",
}) => {
  const [showErrors, setShowErrors] = useState(false);

  if (loading && !result) {
    return (
      <div className={`animate-pulse space-y-2 p-4 ${className}`}>
        <div className="h-4 w-1/3 rounded bg-neutral-800" />
        <div className="h-3 w-2/3 rounded bg-neutral-800" />
      </div>
    );
  }

  if (!result) return null;

  const {
    status, summary, actions, artifacts, memory, errors, verification,
    duration_ms, urls_opened,
  } = result;

  const fileArtifacts = artifacts.filter((a) => a.type !== "url");
  const hasMemory = memory.recalled > 0 || memory.applied.length > 0 || memory.recorded;

  return (
    <div className={`space-y-4 text-sm ${className}`}>
      {/* 1. Summary */}
      <header className="flex flex-wrap items-center gap-2">
        <span
          className={`rounded border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${STATUS_STYLE[status]}`}
        >
          {status}
        </span>
        {duration_ms > 0 && (
          <span className="text-[11px] text-neutral-500">{formatDuration(duration_ms)}</span>
        )}
        {verification && (
          <span
            className={`text-[11px] ${verification.valid ? "text-emerald-400" : "text-red-400"}`}
            title={verification.reason}
          >
            {verification.valid ? "verified" : "verification failed"}
          </span>
        )}
      </header>

      {summary && <p className="leading-relaxed text-neutral-200">{summary}</p>}

      {/* 2. Artifacts */}
      {(fileArtifacts.length > 0 || urls_opened.length > 0) && (
        <section>
          <SectionLabel>Produced</SectionLabel>
          <ul className="space-y-1">
            {fileArtifacts.map((artifact) => (
              <li key={artifact.id}>
                <a
                  href={runsApi.artifactUrl(result.run_id, artifact.id)}
                  target="_blank"
                  rel="noreferrer"
                  onClick={(e) => {
                    if (onOpenArtifact) {
                      e.preventDefault();
                      onOpenArtifact(artifact);
                    }
                  }}
                  className="group flex items-center gap-2 rounded border border-neutral-800 bg-neutral-900/60 px-2 py-1.5 transition-colors hover:border-cyan-500/50 hover:bg-neutral-900"
                >
                  <ArtifactGlyph type={artifact.type} action={artifact.action} />
                  <span className="truncate font-mono text-[12px] text-neutral-200 group-hover:text-cyan-300">
                    {artifact.name}
                  </span>
                  <span className="ml-auto shrink-0 text-[10px] uppercase tracking-wide text-neutral-600">
                    {artifact.action}
                    {artifact.bytes ? ` · ${formatBytes(artifact.bytes)}` : ""}
                  </span>
                </a>
              </li>
            ))}
            {urls_opened.map((url) => (
              <li key={url}>
                <a
                  href={url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-2 rounded border border-neutral-800 bg-neutral-900/60 px-2 py-1.5 text-[12px] text-neutral-300 hover:border-cyan-500/50 hover:text-cyan-300"
                >
                  <span className="text-cyan-500">link</span>
                  <span className="truncate font-mono">{url}</span>
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* 3. Actions */}
      {actions.length > 0 && (
        <section>
          <SectionLabel>What it did</SectionLabel>
          <ul className="space-y-0.5">
            {actions.map((action) => (
              <li key={action.kind} className="flex items-baseline gap-2 text-[12px] text-neutral-300">
                <span className="text-neutral-600">-</span>
                {action.label}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* 4. Memory: the Hindsight evidence */}
      {hasMemory && (
        <section className="rounded border border-violet-500/25 bg-violet-500/5 p-2.5">
          <SectionLabel className="text-violet-300">Memory</SectionLabel>
          <div className="space-y-1.5">
            {memory.recalled > 0 && (
              <p className="text-[12px] text-neutral-300">
                Recalled <strong className="text-violet-300">{memory.recalled}</strong>{" "}
                past {memory.recalled === 1 ? "experience" : "experiences"}.
              </p>
            )}
            {memory.applied.map((sentence, i) => (
              <p
                key={i}
                className="border-l-2 border-violet-500/50 pl-2 text-[12px] italic text-violet-200"
              >
                {sentence}
              </p>
            ))}
            {memory.recorded && (
              <p className="text-[11px] text-neutral-500">
                Recorded this run as{" "}
                <code className="text-violet-400">{memory.recorded}</code>.
              </p>
            )}
          </div>
        </section>
      )}

      {/* 5. Errors */}
      {errors.length > 0 && (
        <section>
          <button
            type="button"
            onClick={() => setShowErrors((v) => !v)}
            className="text-[11px] font-semibold uppercase tracking-wider text-red-400 hover:text-red-300"
          >
            {errors.length} {errors.length === 1 ? "error" : "errors"}{" "}
            <span className="text-neutral-600">{showErrors ? "(hide)" : "(show)"}</span>
          </button>
          {showErrors && (
            <ul className="mt-1 space-y-1">
              {errors.map((err, i) => (
                <li
                  key={i}
                  className="rounded border border-red-500/25 bg-red-500/5 px-2 py-1 font-mono text-[11px] text-red-300"
                >
                  <span className="text-red-500">{err.type}</span>: {err.message}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
};

const SectionLabel: React.FC<{ children: React.ReactNode; className?: string }> = ({
  children,
  className = "",
}) => (
  <h4
    className={`mb-1.5 text-[10px] font-bold uppercase tracking-wider text-neutral-500 ${className}`}
  >
    {children}
  </h4>
);

const ArtifactGlyph: React.FC<{ type: string; action: string }> = ({ type, action }) => {
  const color =
    action === "deleted"
      ? "text-red-500"
      : action === "modified"
        ? "text-amber-500"
        : "text-emerald-500";
  const glyph = type === "image" ? "img" : type === "url" ? "url" : "file";
  return (
    <span className={`shrink-0 font-mono text-[10px] uppercase ${color}`}>{glyph}</span>
  );
};

export default RunResultPanel;
