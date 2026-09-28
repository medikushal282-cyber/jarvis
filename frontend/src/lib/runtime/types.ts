/**
 * Shared types for the JARVIS runtime layer.
 *
 * Mirrors backend/app/runtime/{protocols,models}.py and
 * backend/app/runtime/events/catalog.py. See docs/runtime/EVENTS.md.
 */

// --- events -----------------------------------------------------------------

export interface RuntimeEvent<T = Record<string, any>> {
  /** Monotonic per run, starting at 1. The only ordering guarantee. */
  seq: number;
  event: string;
  run_id: string;
  session_id?: string;
  user_id?: string;
  node: string;
  ts: string;
  data: T;
}

export const TERMINAL_EVENTS = ["run_completed", "run_failed", "run_cancelled"] as const;

export function isTerminal(event: string): boolean {
  return (TERMINAL_EVENTS as readonly string[]).includes(event);
}

export function isTransport(event: string): boolean {
  return event === "stream_ready" || event === "heartbeat";
}

// --- sessions ---------------------------------------------------------------

export interface Turn {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  ts: string;
  input_mode?: "text" | "voice";
  run_id?: string | null;
  audio_url?: string | null;
  metadata?: Record<string, any>;
}

export interface SessionSummary {
  id: string;
  user_id: string;
  workspace_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  turn_count: number;
  run_count: number;
  context_summary: string;
  status: "active" | "archived";
}

export interface Session extends Omit<SessionSummary, "turn_count" | "run_count"> {
  turns: Turn[];
  /** Legacy alias the existing UI reads. */
  messages?: Turn[];
  run_ids: string[];
  runs?: RunSummary[];
}

// --- runs -------------------------------------------------------------------

export type RunStatus =
  | "pending"
  | "running"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled"
  | "rejected";

export interface RunSummary {
  id: string;
  session_id: string;
  objective: string;
  status: RunStatus;
  created_at: string;
  ended_at?: string | null;
  event_count: number;
}

// --- results ----------------------------------------------------------------

export interface Artifact {
  id: string;
  type: "file" | "url" | "image" | "data";
  name: string;
  action: "created" | "modified" | "deleted";
  path?: string;
  url?: string;
  bytes: number;
  mime?: string | null;
  created_at?: string | null;
  preview_url?: string;
  run_id?: string;
}

export interface ActionSummary {
  kind: string;
  label: string;
  count: number;
}

export interface CommandRecord {
  command: string;
  exit_code: number | null;
  duration_ms: number;
}

export interface MemoryReport {
  recalled: number;
  /** Sentences describing how recall changed behaviour. The Hindsight evidence. */
  applied: string[];
  recorded: string | null;
}

export interface VerificationReport {
  valid: boolean;
  reason: string;
  checks: Array<{ name: string; passed: boolean; detail?: string }>;
}

export interface RunError {
  type: string;
  message: string;
  node?: string;
  tool?: string;
  command?: string;
}

export interface RunResult {
  run_id: string;
  session_id: string;
  status: RunStatus;
  objective: string;
  summary: string;
  reply: string;
  model: string;
  provider: string;
  started_at: string | null;
  ended_at: string | null;
  duration_ms: number;
  actions: ActionSummary[];
  artifacts: Artifact[];
  files_created: string[];
  files_modified: string[];
  files_deleted: string[];
  urls_opened: string[];
  commands: CommandRecord[];
  plan: Array<Record<string, any>>;
  memory: MemoryReport;
  verification: VerificationReport | null;
  errors: RunError[];
  event_count: number;
  last_seq: number;
}

// --- voice ------------------------------------------------------------------

export interface VoiceConfig {
  stt_enabled: boolean;
  tts_enabled: boolean;
  tts_backend: string;
  tts_client_side: boolean;
  stt_model: string;
  max_utterance_s: number;
  max_audio_bytes: number;
  allowed_mime: string[];
}

export interface Transcript {
  text: string;
  empty: boolean;
  language?: string | null;
  duration_s?: number;
  confidence?: number | null;
  model?: string;
  audio_url?: string | null;
  message?: string;
}

export type ConnectionState =
  | "idle"
  | "connecting"
  | "live"
  | "replaying"
  | "reconnecting"
  | "closed"
  | "error";
