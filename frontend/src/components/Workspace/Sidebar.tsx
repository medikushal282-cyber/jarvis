"use client";

/** Workspaces and their sessions. Backed by `useSessions`. */

import React, { useState } from "react";

import type { SessionsHandle } from "@/lib/runtime/useSessions";

interface SidebarProps {
  sessions: SessionsHandle;
  width: number;
  busy: boolean;
  onNewSession: () => void;
}

const Sidebar: React.FC<SidebarProps> = ({ sessions: s, width, busy, onNewSession }) => {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");

  const submitWorkspace = async () => {
    if (!name.trim()) return;
    await s.createWorkspace(name);
    setName("");
    setCreating(false);
  };

  return (
    <aside
      className="z-20 flex flex-shrink-0 select-none flex-col justify-between bg-fra-sidebar text-white"
      style={{ width }}
    >
      <div className="dark-scroll flex-1 overflow-y-auto p-3">
        <button
          type="button"
          disabled={busy}
          onClick={onNewSession}
          className="mb-5 flex w-full items-center justify-center space-x-2 border-2 border-black bg-fra-yellow px-3 py-2 text-[12px] font-extrabold text-fra-black shadow-brutal transition-all hover:bg-fra-yellow-hover disabled:cursor-not-allowed disabled:opacity-60"
        >
          <span className="text-base font-black leading-none">+</span>
          <span>New Session</span>
        </button>

        {s.error && (
          <div className="mb-3 border border-red-800 bg-red-950 px-2 py-1.5 font-mono text-[10px] text-red-300">
            {s.error}
          </div>
        )}

        <div className="mb-2 flex items-center justify-between px-1 font-mono text-[10px] font-bold uppercase tracking-wider text-neutral-500">
          <span>Workspaces</span>
          <button
            type="button"
            onClick={() => setCreating((v) => !v)}
            className="text-[12px] font-bold leading-none text-fra-yellow hover:text-white"
            title="New workspace"
          >
            +
          </button>
        </div>

        {creating && (
          <div className="mb-2 flex items-center space-x-1 px-1">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void submitWorkspace();
                if (e.key === "Escape") setCreating(false);
              }}
              placeholder="Workspace name..."
              autoFocus
              className="flex-1 border border-neutral-700 bg-neutral-900 px-1.5 py-1 font-mono text-[10px] text-white focus:border-fra-yellow focus:outline-none"
            />
            <button
              type="button"
              onClick={() => void submitWorkspace()}
              className="border border-black bg-fra-yellow px-1.5 py-1 text-[10px] font-bold text-black"
            >
              Go
            </button>
          </div>
        )}

        <div className="space-y-0.5 font-mono text-[10px]">
          {s.workspaces.map((ws) => {
            const active = ws.id === s.workspaceId;
            return (
              <div key={ws.id}>
                <div className="group flex items-center justify-between">
                  <button
                    type="button"
                    onClick={() => s.selectWorkspace(ws.id)}
                    className={`flex flex-1 items-center justify-between rounded px-2 py-1.5 text-left transition-colors ${
                      active ? "bg-neutral-800 text-fra-yellow" : "text-neutral-300 hover:bg-neutral-900 hover:text-white"
                    }`}
                  >
                    <span className="truncate font-bold">{ws.name}</span>
                    <span className="rounded bg-neutral-800 px-1 text-[8px] text-neutral-400">
                      {ws.session_count ?? 0}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      if (window.confirm(`Delete workspace "${ws.name}" and everything in it?`)) {
                        void s.deleteWorkspace(ws.id);
                      }
                    }}
                    className="ml-1 px-1 text-[9px] font-bold text-red-400 opacity-0 hover:text-red-300 group-hover:opacity-100"
                    title="Delete workspace"
                  >
                    &#10005;
                  </button>
                </div>

                {active && (
                  <div className="space-y-0.5 py-1 pl-3">
                    {s.sessions.map((session) => (
                      <div
                        key={session.id}
                        className={`group flex cursor-pointer items-center justify-between rounded px-2 py-1 ${
                          session.id === s.sessionId
                            ? "bg-neutral-800 text-fra-yellow"
                            : "text-neutral-400 hover:bg-neutral-900 hover:text-white"
                        }`}
                        onClick={() => !busy && s.selectSession(session.id)}
                        title={session.title}
                      >
                        <span className="truncate">{session.title || "Untitled"}</span>
                        <div className="flex items-center space-x-1">
                          <span className="text-[8px] text-neutral-600">{session.turn_count}</span>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              void s.deleteSession(session.id);
                            }}
                            className="text-[9px] font-bold text-red-400 opacity-0 hover:text-red-300 group-hover:opacity-100"
                            title="Archive session"
                          >
                            &#10005;
                          </button>
                        </div>
                      </div>
                    ))}
                    {s.sessions.length === 0 && (
                      <div className="px-2 py-1 italic text-neutral-600">No sessions yet</div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
          {!s.loading && s.workspaces.length === 0 && !s.error && (
            <div className="px-2 py-1 italic text-neutral-600">
              No workspaces yet. Your first run creates one.
            </div>
          )}
        </div>
      </div>

      <div className="flex-shrink-0 border-t-2 border-fra-black bg-neutral-950 p-3">
        <div className="border border-neutral-800 p-2 font-mono text-[9px] uppercase leading-tight tracking-wider text-neutral-400">
          <span className="mb-1 block font-bold text-white">&quot;SMALL EXECUTIONS COMPOUND INTO BIG THINGS.&quot;</span>
        </div>
      </div>
    </aside>
  );
};

export default Sidebar;
