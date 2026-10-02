/**
 * Typed HTTP client for the JARVIS runtime API.
 *
 * Every fetch in the UI should go through here, so the base URL, error
 * handling and response shapes live in one place.
 */

import type {
  Artifact,
  RunResult,
  RunSummary,
  RuntimeEvent,
  Session,
  SessionSummary,
  Transcript,
  VoiceConfig,
  WorkerSummary,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_JARVIS_API ?? "http://localhost:8006";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        ...(init?.body && !(init.body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {}),
        ...init?.headers,
      },
    });
  } catch (cause) {
    throw new ApiError(`Cannot reach JARVIS at ${API_BASE}`, 0, cause);
  }

  if (!res.ok) {
    let detail: unknown;
    try {
      detail = await res.json();
    } catch {
      detail = await res.text().catch(() => "");
    }
    const message =
      (detail as any)?.detail ?? `${init?.method ?? "GET"} ${path} failed (${res.status})`;
    throw new ApiError(String(message), res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

// --- workspaces -------------------------------------------------------------

export const workspaces = {
  list: () => request<{ workspaces: any[] }>("/api/workspaces"),
  create: (name: string, description = "") =>
    request<{ workspace: any }>("/api/workspaces", {
      method: "POST",
      body: JSON.stringify({ name, description }),
    }),
  rename: (id: string, name: string, description = "") =>
    request<{ success: boolean; workspace: any }>(`/api/workspaces/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify({ name, description }),
    }),
  remove: (id: string) =>
    request<{ deleted: string }>(`/api/workspaces/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
};

// --- sessions ---------------------------------------------------------------

export const sessions = {
  list: (workspaceId?: string, status?: string) => {
    const q = new URLSearchParams();
    if (workspaceId) q.set("workspace_id", workspaceId);
    if (status) q.set("status", status);
    const qs = q.toString();
    return request<{ sessions: SessionSummary[] }>(`/api/sessions${qs ? `?${qs}` : ""}`);
  },

  create: (workspaceId?: string, title = "New Session") =>
    request<{ session: SessionSummary }>("/api/sessions", {
      method: "POST",
      body: JSON.stringify({ workspace_id: workspaceId, title }),
    }),

  get: (id: string) => request<Session>(`/api/sessions/${encodeURIComponent(id)}`),

  rename: (id: string, title: string) =>
    request<{ session: SessionSummary }>(`/api/sessions/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),

  remove: (id: string, hard = false) =>
    request<{ deleted: string }>(
      `/api/sessions/${encodeURIComponent(id)}?hard=${hard}`,
      { method: "DELETE" },
    ),

  turns: (id: string, limit = 50) =>
    request<{ turns: any[]; total: number }>(
      `/api/sessions/${encodeURIComponent(id)}/turns?limit=${limit}`,
    ),

  context: (id: string) =>
    request<{ context_summary: string; turn_count: number; recent_turns: any[] }>(
      `/api/sessions/${encodeURIComponent(id)}/context`,
    ),

  runs: (id: string) =>
    request<{ runs: RunSummary[] }>(`/api/sessions/${encodeURIComponent(id)}/runs`),

  artifacts: (id: string) =>
    request<{ artifacts: Artifact[] }>(
      `/api/sessions/${encodeURIComponent(id)}/artifacts`,
    ),

  startRun: (
    id: string,
    body: {
      objective: string;
      model?: string;
      provider?: string;
      input_mode?: "text" | "voice";
      execution_mode?: "normal" | "turbo";
      workspace_id?: string;
      attachments?: Array<{ name: string; content: string; size?: number }>;
      audio_url?: string | null;
      voice?: { confidence?: number; duration_s?: number; model?: string; language?: string };
    },
  ) =>
    request<{ run_id: string; session_id: string; status: string }>(
      `/api/sessions/${encodeURIComponent(id)}/runs`,
      { method: "POST", body: JSON.stringify(body) },
    ),
};

// --- runs -------------------------------------------------------------------

export const runs = {
  /** Session-less convenience entry point; resolves a default session. */
  start: (body: {
    objective: string;
    model?: string;
    provider?: string;
    session_id?: string;
    workspace_id?: string;
    input_mode?: "text" | "voice";
    attachments?: Array<{ name: string; content: string; size?: number }>;
  }) =>
    request<{ run_id: string; session_id: string; status: string }>("/api/runs/", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  get: (id: string) => request<any>(`/api/runs/${encodeURIComponent(id)}`),

  result: (id: string) =>
    request<RunResult>(`/api/runs/${encodeURIComponent(id)}/result`),

  artifacts: (id: string) =>
    request<{ artifacts: Artifact[] }>(`/api/runs/${encodeURIComponent(id)}/artifacts`),

  artifactUrl: (runId: string, artifactId: string) =>
    `${API_BASE}/api/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}`,

  eventLog: (id: string, since = 0, types?: string[]) => {
    const q = new URLSearchParams({ since: String(since) });
    if (types?.length) q.set("types", types.join(","));
    return request<{ events: RuntimeEvent[]; count: number }>(
      `/api/runs/${encodeURIComponent(id)}/events/log?${q}`,
    );
  },

  cancel: (id: string) =>
    request<{ status: string }>(`/api/runs/${encodeURIComponent(id)}/cancel`, {
      method: "POST",
    }),

  approve: (id: string, decision: "approve" | "reject", requestId?: string) =>
    request<{ status: string }>(`/api/runs/${encodeURIComponent(id)}/approval`, {
      method: "POST",
      body: JSON.stringify({ decision, request_id: requestId }),
    }),
};

// --- voice ------------------------------------------------------------------

export const voice = {
  config: () => request<VoiceConfig>("/api/voice/config"),

  voices: () => request<{ voices: any[] }>("/api/voice/voices"),

  transcribe: async (
    blob: Blob,
    opts: { language?: string; sessionId?: string; workspaceId?: string } = {},
  ): Promise<Transcript> => {
    const form = new FormData();
    const ext = blob.type.includes("ogg") ? "ogg" : blob.type.includes("wav") ? "wav" : "webm";
    form.append("file", blob, `utterance.${ext}`);
    if (opts.language) form.append("language", opts.language);
    if (opts.sessionId) form.append("session_id", opts.sessionId);
    if (opts.workspaceId) form.append("workspace_id", opts.workspaceId);
    return request<Transcript>("/api/voice/transcribe", { method: "POST", body: form });
  },

  /** Returns audio bytes, or `{client_side: true}` when the browser speaks. */
  synthesize: async (
    text: string,
    opts: { voice?: string; format?: string } = {},
  ): Promise<Blob | { client_side: true; text: string }> => {
    const res = await fetch(`${API_BASE}/api/voice/synthesize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, voice: opts.voice, format: opts.format }),
    });
    if (!res.ok) {
      throw new ApiError(`Synthesis failed (${res.status})`, res.status);
    }
    const contentType = res.headers.get("content-type") ?? "";
    if (contentType.includes("application/json")) {
      return (await res.json()) as { client_side: true; text: string };
    }
    return res.blob();
  },

  speakable: (text: string) =>
    request<{ text: string }>("/api/voice/speakable", {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
};

// --- workers ----------------------------------------------------------------

export const workers = {
  list: () => request<WorkerSummary[]>("/api/workers"),

  create: (body: { provider: string; model: string; api_key: string; priority?: number; display_name?: string }) =>
    request<WorkerSummary>("/api/workers", { method: "POST", body: JSON.stringify(body) }),

  update: (
    id: string,
    body: { enabled?: boolean; priority?: number; reset_cooldown?: boolean; api_key?: string; display_name?: string },
  ) =>
    request<WorkerSummary>(`/api/workers/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  remove: (id: string) =>
    request<{ success: boolean }>(`/api/workers/${encodeURIComponent(id)}`, { method: "DELETE" }),

  test: (body: { provider: string; model: string; api_key: string }) =>
    request<{ success: boolean; message: string }>("/api/workers/test", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

export const runtimeClient = { workspaces, sessions, runs, voice, workers, API_BASE };
export default runtimeClient;
