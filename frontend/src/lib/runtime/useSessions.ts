"use client";

/**
 * Workspaces and sessions, from `/api/workspaces` and `/api/sessions`.
 *
 * Replaces the page's direct calls to the legacy `/api/sandbox/*` routes.
 * The last workspace and session are remembered per browser so a refresh
 * lands where you were; that is a convenience only, and everything still
 * works if storage is unavailable.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { sessions as sessionsApi, workspaces as workspacesApi } from "./client";
import type { SessionSummary, Turn, WorkspaceSummary } from "./types";

const STORE_KEY = "jarvis.lastPlace";

function readPlace(): { workspaceId?: string; sessionId?: string } {
  try {
    return JSON.parse(window.localStorage.getItem(STORE_KEY) || "{}");
  } catch {
    return {};
  }
}

function writePlace(place: { workspaceId: string | null; sessionId: string | null }) {
  try {
    window.localStorage.setItem(STORE_KEY, JSON.stringify(place));
  } catch {
    // Private mode or blocked storage: the app works without it.
  }
}

export interface SessionsHandle {
  workspaces: WorkspaceSummary[];
  workspaceId: string | null;
  sessions: SessionSummary[];
  sessionId: string | null;
  turns: Turn[];
  contextSummary: string;
  loading: boolean;
  error: string | null;
  selectWorkspace: (id: string) => void;
  createWorkspace: (name: string, description?: string) => Promise<void>;
  renameWorkspace: (id: string, name: string, description?: string) => Promise<void>;
  deleteWorkspace: (id: string) => Promise<void>;
  selectSession: (id: string) => void;
  renameSession: (id: string, title: string) => Promise<void>;
  /** Start fresh; the next run creates the session. */
  newSession: () => void;
  deleteSession: (id: string) => Promise<void>;
  /** A run created or used this session: make it current and reload it. */
  adoptSession: (id: string) => Promise<void>;
  reload: () => Promise<void>;
}

export function useSessions(): SessionsHandle {
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [sessionList, setSessionList] = useState<SessionSummary[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [contextSummary, setContextSummary] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const restoredRef = useRef(false);

  const loadWorkspaces = useCallback(async () => {
    try {
      const { workspaces: list } = await workspacesApi.list();
      setWorkspaces(list);
      setError(null);
      return list as WorkspaceSummary[];
    } catch (err: any) {
      setError(err?.message ?? "Can't reach the JARVIS backend.");
      return [];
    }
  }, []);

  const loadSessions = useCallback(async (wsId: string) => {
    try {
      const { sessions: list } = await sessionsApi.list(wsId, "active");
      setSessionList(list);
      return list;
    } catch {
      setSessionList([]);
      return [];
    }
  }, []);

  const loadSession = useCallback(async (id: string) => {
    try {
      const session = await sessionsApi.get(id);
      setTurns(session.turns ?? []);
      setContextSummary(session.context_summary ?? "");
    } catch {
      setTurns([]);
      setContextSummary("");
    }
  }, []);

  // First load: workspaces, then the remembered (or first) workspace.
  useEffect(() => {
    (async () => {
      const list = await loadWorkspaces();
      const place = readPlace();
      const remembered = list.find((w) => w.id === place.workspaceId);
      const initial = remembered?.id ?? list[0]?.id ?? "default";
      setWorkspaceId(initial);
      setLoading(false);
    })();
  }, [loadWorkspaces]);

  // Workspace changed: load its sessions, restoring the remembered one once.
  useEffect(() => {
    if (!workspaceId) return;
    (async () => {
      const list = await loadSessions(workspaceId);
      if (!restoredRef.current) {
        restoredRef.current = true;
        const place = readPlace();
        if (place.sessionId && list.some((s) => s.id === place.sessionId)) {
          setSessionId(place.sessionId);
          return;
        }
      }
      setSessionId(null);
      setTurns([]);
      setContextSummary("");
    })();
  }, [workspaceId, loadSessions]);

  useEffect(() => {
    if (sessionId) void loadSession(sessionId);
  }, [sessionId, loadSession]);

  // Save the place only after the restore has run: on a reload the workspace
  // is set before the session is restored, and writing then would overwrite
  // the remembered session with "none".
  useEffect(() => {
    if (workspaceId && restoredRef.current) writePlace({ workspaceId, sessionId });
  }, [workspaceId, sessionId]);

  const selectWorkspace = useCallback((id: string) => {
    restoredRef.current = true;
    setWorkspaceId(id);
  }, []);

  const createWorkspace = useCallback(async (name: string, description = "") => {
    const trimmed = name.trim();
    if (!trimmed) return;
    const { workspace } = await workspacesApi.create(trimmed, description);
    const list = await loadWorkspaces();
    if (workspace?.id) selectWorkspace(workspace.id);
    else if (list.length > 0) selectWorkspace(list[list.length - 1].id);
  }, [loadWorkspaces, selectWorkspace]);

  const renameWorkspace = useCallback(async (id: string, name: string, description = "") => {
    const trimmed = name.trim();
    if (!trimmed) return;
    await workspacesApi.rename(id, trimmed, description);
    await loadWorkspaces();
  }, [loadWorkspaces]);

  const deleteWorkspace = useCallback(async (id: string) => {
    await workspacesApi.remove(id);
    const list = await loadWorkspaces();
    if (id === workspaceId) {
      setWorkspaceId(list[0]?.id ?? "default");
    }
  }, [loadWorkspaces, workspaceId]);

  const selectSession = useCallback((id: string) => setSessionId(id), []);

  const newSession = useCallback(() => {
    setSessionId(null);
    setTurns([]);
    setContextSummary("");
  }, []);

  const renameSession = useCallback(async (id: string, title: string) => {
    const trimmed = title.trim();
    if (!trimmed) return;
    await sessionsApi.rename(id, trimmed);
    if (workspaceId) await loadSessions(workspaceId);
    if (id === sessionId) await loadSession(id);
  }, [workspaceId, sessionId, loadSessions, loadSession]);

  const deleteSession = useCallback(async (id: string) => {
    await sessionsApi.remove(id, true);
    if (workspaceId) await loadSessions(workspaceId);
    if (id === sessionId) newSession();
  }, [workspaceId, sessionId, loadSessions, newSession]);

  const adoptSession = useCallback(async (id: string) => {
    setSessionId(id);
    await loadSession(id);
    if (workspaceId) await loadSessions(workspaceId);
    // The run may have created the workspace itself (a first run in "default").
    await loadWorkspaces();
  }, [workspaceId, loadSession, loadSessions, loadWorkspaces]);

  const reload = useCallback(async () => {
    await loadWorkspaces();
    if (workspaceId) await loadSessions(workspaceId);
    if (sessionId) await loadSession(sessionId);
  }, [workspaceId, sessionId, loadWorkspaces, loadSessions, loadSession]);

  return {
    workspaces,
    workspaceId,
    sessions: sessionList,
    sessionId,
    turns,
    contextSummary,
    loading,
    error,
    selectWorkspace,
    createWorkspace,
    renameWorkspace,
    deleteWorkspace,
    selectSession,
    renameSession,
    newSession,
    deleteSession,
    adoptSession,
    reload,
  };
}

export default useSessions;
