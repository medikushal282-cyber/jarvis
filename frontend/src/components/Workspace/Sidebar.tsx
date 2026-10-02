"use client";

/**
 * Workspaces and their chat sessions. Backed by `useSessions`.
 *
 * Full CRUD for workspaces and chat sessions with clean brutalist styling.
 */

import React, { useState } from "react";
import type { SessionsHandle } from "@/lib/runtime/useSessions";

interface SidebarProps {
  sessions: SessionsHandle;
  width: number;
  busy: boolean;
  onNewSession: () => void;
}

const Sidebar: React.FC<SidebarProps> = ({ sessions: s, width, busy, onNewSession }) => {
  // Workspace creation state
  const [creatingWs, setCreatingWs] = useState(false);
  const [newWsName, setNewWsName] = useState("");
  const [newWsDesc, setNewWsDesc] = useState("");

  // Workspace editing state
  const [editingWsId, setEditingWsId] = useState<string | null>(null);
  const [editWsName, setEditWsName] = useState("");

  // Workspace delete confirmation state
  const [confirmDeleteWsId, setConfirmDeleteWsId] = useState<string | null>(null);

  // Chat / Session editing state
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editSessionTitle, setEditSessionTitle] = useState("");

  // Chat / Session delete confirmation state
  const [confirmDeleteSessionId, setConfirmDeleteSessionId] = useState<string | null>(null);

  const handleCreateWorkspace = async () => {
    if (!newWsName.trim()) return;
    await s.createWorkspace(newWsName.trim(), newWsDesc.trim());
    setNewWsName("");
    setNewWsDesc("");
    setCreatingWs(false);
  };

  const startEditWorkspace = (ws: { id: string; name: string }) => {
    setEditingWsId(ws.id);
    setEditWsName(ws.name);
  };

  const handleSaveWorkspace = async (id: string) => {
    if (!editWsName.trim()) {
      setEditingWsId(null);
      return;
    }
    await s.renameWorkspace(id, editWsName.trim());
    setEditingWsId(null);
  };

  const startEditSession = (session: { id: string; title: string }) => {
    setEditingSessionId(session.id);
    setEditSessionTitle(session.title || "Untitled");
  };

  const handleSaveSession = async (id: string) => {
    if (!editSessionTitle.trim()) {
      setEditingSessionId(null);
      return;
    }
    await s.renameSession(id, editSessionTitle.trim());
    setEditingSessionId(null);
  };

  return (
    <aside
      className="z-20 flex flex-shrink-0 select-none flex-col justify-between bg-fra-sidebar text-white border-r border-neutral-800"
      style={{ width, minWidth: width, maxWidth: width }}
    >
      <div className="dark-scroll flex-1 overflow-y-auto p-3">
        {/* New Session Button */}
        <button
          type="button"
          disabled={busy}
          onClick={onNewSession}
          className="mb-4 flex w-full items-center justify-center space-x-2 border-2 border-black bg-fra-yellow px-3 py-2 text-[12px] font-extrabold text-fra-black shadow-brutal transition-all hover:bg-fra-yellow-hover disabled:cursor-not-allowed disabled:opacity-60"
        >
          <span className="text-base font-black leading-none">+</span>
          <span>New Session</span>
        </button>

        {s.error && (
          <div className="mb-3 border border-red-800 bg-red-950 p-2 font-mono text-[10px] text-red-300">
            {s.error}
          </div>
        )}

        {/* Workspaces Section Header */}
        <div className="mb-2 flex items-center justify-between px-1 font-mono text-[10px] font-bold uppercase tracking-wider text-neutral-400">
          <div className="flex items-center space-x-1.5">
            <svg
              width={14}
              height={14}
              style={{ width: 14, height: 14, minWidth: 14 }}
              className="text-fra-yellow"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"
              />
            </svg>
            <span>Workspaces</span>
          </div>
          <button
            type="button"
            onClick={() => setCreatingWs((v) => !v)}
            className="flex items-center space-x-1 rounded bg-neutral-800 px-1.5 py-0.5 text-[10px] font-bold text-fra-yellow hover:bg-neutral-700 hover:text-white transition-colors"
            title="Create new workspace"
          >
            <span>+</span>
            <span>Add</span>
          </button>
        </div>

        {/* Create Workspace Form */}
        {creatingWs && (
          <div className="mb-3 rounded border border-fra-yellow/40 bg-neutral-900 p-2 text-[11px] shadow-sm">
            <div className="mb-1.5 font-bold text-fra-yellow text-[10px] uppercase font-mono">
              New Workspace
            </div>
            <input
              value={newWsName}
              onChange={(e) => setNewWsName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleCreateWorkspace();
                if (e.key === "Escape") setCreatingWs(false);
              }}
              placeholder="Workspace name..."
              autoFocus
              className="w-full border border-neutral-700 bg-neutral-950 px-2 py-1 font-mono text-[11px] text-white focus:border-fra-yellow focus:outline-none mb-1.5"
            />
            <input
              value={newWsDesc}
              onChange={(e) => setNewWsDesc(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleCreateWorkspace();
                if (e.key === "Escape") setCreatingWs(false);
              }}
              placeholder="Description (optional)..."
              className="w-full border border-neutral-800 bg-neutral-950 px-2 py-1 font-mono text-[10px] text-neutral-300 focus:border-fra-yellow focus:outline-none mb-2"
            />
            <div className="flex justify-end space-x-1.5">
              <button
                type="button"
                onClick={() => setCreatingWs(false)}
                className="rounded border border-neutral-700 bg-neutral-800 px-2 py-0.5 text-[10px] text-neutral-300 hover:text-white"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void handleCreateWorkspace()}
                className="rounded border border-black bg-fra-yellow px-2 py-0.5 text-[10px] font-bold text-black hover:bg-fra-yellow-hover"
              >
                Create
              </button>
            </div>
          </div>
        )}

        {/* Workspaces List */}
        <div className="space-y-1 font-mono text-[11px]">
          {s.workspaces.map((ws) => {
            const active = ws.id === s.workspaceId;
            const isEditing = editingWsId === ws.id;
            const isDeleting = confirmDeleteWsId === ws.id;

            return (
              <div
                key={ws.id}
                className="rounded border border-transparent hover:border-neutral-800/80 transition-all"
              >
                {/* Workspace Header Row */}
                {isEditing ? (
                  <div className="flex items-center space-x-1 p-1 bg-neutral-900 border border-fra-yellow/50 rounded">
                    <input
                      value={editWsName}
                      onChange={(e) => setEditWsName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") void handleSaveWorkspace(ws.id);
                        if (e.key === "Escape") setEditingWsId(null);
                      }}
                      autoFocus
                      className="flex-1 bg-neutral-950 px-1.5 py-0.5 text-[11px] text-white border border-neutral-700 focus:border-fra-yellow focus:outline-none"
                    />
                    <button
                      type="button"
                      onClick={() => void handleSaveWorkspace(ws.id)}
                      className="bg-fra-yellow px-1.5 py-0.5 text-[10px] font-bold text-black"
                    >
                      ✓
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditingWsId(null)}
                      className="bg-neutral-800 px-1.5 py-0.5 text-[10px] text-neutral-300"
                    >
                      ✕
                    </button>
                  </div>
                ) : isDeleting ? (
                  <div className="p-1.5 bg-red-950 border border-red-700 rounded text-[10px]">
                    <div className="text-red-200 font-bold mb-1">
                      Delete workspace &quot;{ws.name}&quot;?
                    </div>
                    <div className="flex justify-end space-x-1">
                      <button
                        type="button"
                        onClick={() => setConfirmDeleteWsId(null)}
                        className="bg-neutral-800 px-1.5 py-0.5 text-neutral-300 rounded"
                      >
                        Cancel
                      </button>
                      <button
                        type="button"
                        onClick={async () => {
                          setConfirmDeleteWsId(null);
                          await s.deleteWorkspace(ws.id);
                        }}
                        className="bg-red-600 px-1.5 py-0.5 text-white font-bold rounded"
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="group flex items-center justify-between">
                    <button
                      type="button"
                      onClick={() => s.selectWorkspace(ws.id)}
                      className={`flex flex-1 items-center justify-between rounded px-2 py-1.5 text-left transition-colors ${
                        active
                          ? "bg-neutral-800 text-fra-yellow font-bold"
                          : "text-neutral-300 hover:bg-neutral-900 hover:text-white"
                      }`}
                    >
                      <span className="truncate pr-1">{ws.name}</span>
                      <span className="rounded bg-neutral-900 px-1.5 py-0.2 text-[9px] text-neutral-400 border border-neutral-800">
                        {ws.session_count ?? 0}
                      </span>
                    </button>

                    {/* Action buttons on hover */}
                    <div className="flex items-center space-x-0.5 opacity-0 group-hover:opacity-100 transition-opacity pr-1">
                      <button
                        type="button"
                        onClick={() => startEditWorkspace(ws)}
                        className="p-1 text-neutral-400 hover:text-fra-yellow"
                        title="Rename workspace"
                      >
                        <svg
                          width={12}
                          height={12}
                          style={{ width: 12, height: 12 }}
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"
                          />
                        </svg>
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmDeleteWsId(ws.id)}
                        className="p-1 text-neutral-400 hover:text-red-400"
                        title="Delete workspace"
                      >
                        <svg
                          width={12}
                          height={12}
                          style={{ width: 12, height: 12 }}
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                          />
                        </svg>
                      </button>
                    </div>
                  </div>
                )}

                {/* Sessions / Chats List when Workspace is Active */}
                {active && (
                  <div className="space-y-0.5 py-1 pl-2.5 my-0.5 border-l-2 border-fra-yellow/30 ml-1.5">
                    {s.sessions.map((session) => {
                      const isSessionActive = session.id === s.sessionId;
                      const isEditingSession = editingSessionId === session.id;
                      const isDeletingSession = confirmDeleteSessionId === session.id;

                      if (isEditingSession) {
                        return (
                          <div
                            key={session.id}
                            className="flex items-center space-x-1 p-1 bg-neutral-900 border border-fra-yellow/50 rounded"
                          >
                            <input
                              value={editSessionTitle}
                              onChange={(e) => setEditSessionTitle(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") void handleSaveSession(session.id);
                                if (e.key === "Escape") setEditingSessionId(null);
                              }}
                              autoFocus
                              className="flex-1 bg-neutral-950 px-1.5 py-0.5 text-[10px] text-white border border-neutral-700 focus:border-fra-yellow focus:outline-none"
                            />
                            <button
                              type="button"
                              onClick={() => void handleSaveSession(session.id)}
                              className="bg-fra-yellow px-1 text-[9px] font-bold text-black"
                            >
                              ✓
                            </button>
                            <button
                              type="button"
                              onClick={() => setEditingSessionId(null)}
                              className="bg-neutral-800 px-1 text-[9px] text-neutral-300"
                            >
                              ✕
                            </button>
                          </div>
                        );
                      }

                      if (isDeletingSession) {
                        return (
                          <div
                            key={session.id}
                            className="p-1 bg-red-950/80 border border-red-800 rounded text-[9px]"
                          >
                            <div className="text-red-200 truncate mb-1">Delete chat?</div>
                            <div className="flex justify-end space-x-1">
                              <button
                                type="button"
                                onClick={() => setConfirmDeleteSessionId(null)}
                                className="bg-neutral-800 px-1 text-neutral-300"
                              >
                                No
                              </button>
                              <button
                                type="button"
                                onClick={async () => {
                                  setConfirmDeleteSessionId(null);
                                  await s.deleteSession(session.id);
                                }}
                                className="bg-red-600 px-1 text-white font-bold"
                              >
                                Yes
                              </button>
                            </div>
                          </div>
                        );
                      }

                      return (
                        <div
                          key={session.id}
                          className={`group flex cursor-pointer items-center justify-between rounded px-2 py-1 transition-colors ${
                            isSessionActive
                              ? "bg-neutral-800 text-fra-yellow font-bold"
                              : "text-neutral-400 hover:bg-neutral-900 hover:text-white"
                          }`}
                          onClick={() => !busy && s.selectSession(session.id)}
                          title={session.title}
                        >
                          <span className="truncate text-[10px]">{session.title || "Untitled Chat"}</span>

                          <div className="flex items-center space-x-1">
                            <span className="text-[8px] text-neutral-500 font-mono">
                              {session.turn_count}
                            </span>

                            <div className="flex items-center space-x-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  startEditSession(session);
                                }}
                                className="p-0.5 text-neutral-400 hover:text-fra-yellow"
                                title="Rename chat"
                              >
                                <svg
                                  width={10}
                                  height={10}
                                  style={{ width: 10, height: 10 }}
                                  fill="none"
                                  viewBox="0 0 24 24"
                                  stroke="currentColor"
                                >
                                  <path
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    strokeWidth={2}
                                    d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"
                                  />
                                </svg>
                              </button>
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setConfirmDeleteSessionId(session.id);
                                }}
                                className="p-0.5 text-neutral-400 hover:text-red-400"
                                title="Delete chat"
                              >
                                <svg
                                  width={10}
                                  height={10}
                                  style={{ width: 10, height: 10 }}
                                  fill="none"
                                  viewBox="0 0 24 24"
                                  stroke="currentColor"
                                >
                                  <path
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    strokeWidth={2}
                                    d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                                  />
                                </svg>
                              </button>
                            </div>
                          </div>
                        </div>
                      );
                    })}

                    {s.sessions.length === 0 && (
                      <div className="px-2 py-1 italic text-[10px] text-neutral-600">
                        No chats yet
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}

          {!s.loading && s.workspaces.length === 0 && !s.error && (
            <div className="px-2 py-2 italic text-[10px] text-neutral-500 text-center">
              No workspaces yet. Click + Add above to create one.
            </div>
          )}
        </div>
      </div>

      {/* Footer Info */}
      <div className="flex-shrink-0 border-t border-neutral-800 bg-neutral-950 p-3">
        <div className="border border-neutral-800/80 p-2 font-mono text-[9px] uppercase leading-tight tracking-wider text-neutral-400">
          <span className="mb-1 block font-bold text-fra-yellow">
            &quot;SMALL EXECUTIONS COMPOUND INTO BIG THINGS.&quot;
          </span>
        </div>
      </div>
    </aside>
  );
};

export default Sidebar;
