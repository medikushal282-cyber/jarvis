"use client";

import React from "react";

import WorkerPoolControl from "@/components/WorkerPoolControl";
import type { ConnectionState } from "@/lib/runtime/types";

interface TopBarProps {
  workspaceName: string;
  previewAvailable: boolean;
  previewOpen: boolean;
  onTogglePreview: () => void;
  /** Only shown while a run is streaming. */
  connection: ConnectionState | null;
}

const CONNECTION: Partial<Record<ConnectionState, { text: string; cls: string }>> = {
  connecting: { text: "CONNECTING", cls: "text-neutral-500" },
  live: { text: "LIVE", cls: "text-fra-green" },
  reconnecting: { text: "RECONNECTING", cls: "text-amber-600 animate-pulse" },
  error: { text: "DISCONNECTED", cls: "text-red-600" },
};

const TopBar: React.FC<TopBarProps> = ({
  workspaceName,
  previewAvailable,
  previewOpen,
  onTogglePreview,
  connection,
}) => {
  const conn = connection ? CONNECTION[connection] : undefined;

  return (
    <header className="z-30 flex h-14 flex-shrink-0 select-none items-center justify-between border-b-2 border-fra-black bg-fra-cream px-3">
      <div className="flex items-center space-x-4">
        <span className="mr-1 bg-black px-2 py-0.5 font-sans text-2xl font-extrabold tracking-tighter text-white">
          JARVIS_
        </span>
        <div className="hidden border-l-2 border-fra-black pl-3 font-mono text-[10px] font-bold leading-tight text-neutral-800 md:block">
          <span className="text-neutral-500">WORKSPACE</span>
          <br />
          <span className="text-black">{workspaceName}</span>
        </div>
        {conn && (
          <span className={`font-mono text-[10px] font-bold ${conn.cls}`} title="Connection to the running task">
            &#9679; {conn.text}
          </span>
        )}
      </div>

      <div className="flex items-center space-x-3">
        {previewAvailable && (
          <button
            type="button"
            onClick={onTogglePreview}
            className={`flex items-center space-x-1 border-2 border-black px-2 py-0.5 text-[10px] font-black shadow-brutal-sm transition-all ${
              previewOpen ? "bg-black text-fra-yellow" : "bg-fra-yellow text-black hover:bg-yellow-400"
            }`}
          >
            <span>{previewOpen ? "Hide Preview" : "Open Preview"}</span>
          </button>
        )}
        <WorkerPoolControl />
      </div>
    </header>
  );
};

export default TopBar;
