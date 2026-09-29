/**
 * The single place the UI turns run events into run state.
 *
 * Every component reads `RunView`; nothing else interprets events. Pure and
 * framework-free so it can be unit tested with plain event fixtures.
 *
 * It shows *progress* ("Creating index.html"), never model reasoning:
 * `thought_generated` and `agent_thinking` are deliberately ignored.
 * It accepts both the current event names and the legacy ones the old graph
 * still emits (`tool_call_started`, `validation_result`, `browser_opened`, ...).
 */

import type { Artifact, RuntimeEvent } from "./types";

// --- state ------------------------------------------------------------------

export type RunPhase =
  | "idle"
  | "starting"
  | "running"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

export type StepKind =
  | "understand"
  | "memory"
  | "tool"
  | "file"
  | "command"
  | "preview"
  | "verify"
  | "worker"
  | "permission";

export type StepStatus = "running" | "done" | "failed";

export interface ProgressStep {
  id: string;
  kind: StepKind;
  label: string;
  status: StepStatus;
  detail?: string;
  /** For matching a later result event to this step. */
  callId?: string;
  tool?: string;
  path?: string;
  command?: string;
}

/** One shape for artifacts, whether announced live or read from the result. */
export interface ArtifactView {
  id: string;
  filename: string;
  mimeType: string | null;
  size: number;
  /** Relative to the API base, e.g. /api/runs/run_x/artifacts/art_y. */
  url: string | null;
  previewable: boolean;
  action?: string;
}

export interface PermissionRequest {
  requestId: string;
  tool: string;
  permission: string;
  summary: string;
  risk: string;
}

export interface WorkerState {
  current: string | null;
  previous: string | null;
  reason: string | null;
  switches: number;
}

export interface RunError {
  message: string;
  type: string;
  node?: string;
}

export interface RunView {
  runId: string | null;
  phase: RunPhase;
  objective: string;
  inputMode: "text" | "voice";
  lastSeq: number;
  steps: ProgressStep[];
  artifacts: ArtifactView[];
  /** A preview the agent actually opened (browser_action / browser_opened). */
  previewUrl: string | null;
  /** The agent asked to preview a workspace file by path, not by URL. */
  previewPath: string | null;
  /** Last HTML file written -- a fallback preview when none was announced. */
  lastHtmlPath: string | null;
  permission: PermissionRequest | null;
  worker: WorkerState;
  memoryApplied: string[];
  verification: { valid: boolean; reason: string } | null;
  reply: string;
  error: RunError | null;
}

export const initialRunView: RunView = {
  runId: null,
  phase: "idle",
  objective: "",
  inputMode: "text",
  lastSeq: 0,
  steps: [],
  artifacts: [],
  previewUrl: null,
  previewPath: null,
  lastHtmlPath: null,
  permission: null,
  worker: { current: null, previous: null, reason: null, switches: 0 },
  memoryApplied: [],
  verification: null,
  reply: "",
  error: null,
};

// --- actions ----------------------------------------------------------------

export type RunAction =
  | { type: "reset" }
  | { type: "start"; objective: string; inputMode: "text" | "voice" }
  | { type: "dispatched"; runId: string }
  | { type: "event"; event: RuntimeEvent }
  | { type: "result_artifacts"; artifacts: Artifact[] }
  | { type: "client_error"; message: string; errorType?: string };

// --- labels -----------------------------------------------------------------

function basename(path: string): string {
  const parts = path.replace(/\\/g, "/").split("/").filter(Boolean);
  return parts[parts.length - 1] || path;
}

function clip(text: string, max = 60): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function toolLabel(tool: string, path?: string, command?: string): string {
  const t = tool.toLowerCase();
  const name = path ? basename(path) : "";
  if (/(create|write)_?file/.test(t)) return name ? `Creating ${name}` : "Creating a file";
  if (/(edit|update|patch|append)_?file/.test(t)) return name ? `Editing ${name}` : "Editing a file";
  if (/read_?file/.test(t)) return name ? `Reading ${name}` : "Reading a file";
  if (/delete_?file/.test(t)) return name ? `Deleting ${name}` : "Deleting a file";
  if (/(copy|move|rename)_?file/.test(t)) return name ? `Moving ${name}` : "Moving a file";
  if (/list_?(files|directory)|directory_tree/.test(t)) return "Looking through files";
  if (/search_?files|grep/.test(t)) return "Searching files";
  if (/(run_?command|terminal|execute_?command|shell)/.test(t))
    return command ? `Running ${clip(command, 48)}` : "Running a command";
  if (/(preview|browser|screenshot)/.test(t)) return "Opening preview";
  if (/(web_?search|search_?web)/.test(t)) return "Searching the web";
  if (/^http|fetch|request/.test(t)) return "Calling a web API";
  if (/^github/.test(t)) return "Working on GitHub";
  if (/^git/.test(t)) return "Working with Git";
  if (/install/.test(t)) return "Installing packages";
  return `Using ${t.replace(/_/g, " ")}`;
}

function doneLabel(label: string): string {
  const map: Array<[RegExp, string]> = [
    [/^Creating /, "Created "],
    [/^Editing /, "Edited "],
    [/^Reading /, "Read "],
    [/^Deleting /, "Deleted "],
    [/^Moving /, "Moved "],
    [/^Running /, "Ran "],
    [/^Opening preview/, "Opened preview"],
    [/^Searching the web/, "Searched the web"],
    [/^Searching files/, "Searched files"],
    [/^Looking through files/, "Looked through files"],
    [/^Verifying result/, "Verified result"],
    [/^Understanding request/, "Understood request"],
  ];
  for (const [re, replacement] of map) {
    if (re.test(label)) return label.replace(re, replacement);
  }
  return label;
}

/** `to_worker` per the contract, or the name in the gateway's message. */
function workerName(d: Record<string, any>): string | null {
  if (d.to_worker) return String(d.to_worker);
  const match = /worker to (.+?)\.*\s*$/i.exec(String(d.message ?? ""));
  return match ? match[1].trim() : null;
}

function reasonText(reason: string): string {
  const r = reason.toLowerCase();
  if (r.includes("rate")) return "Rate limited";
  if (r.includes("timeout")) return "Timed out";
  if (r.includes("fail") || r.includes("error")) return "Worker failed";
  return reason;
}

function errorText(err: unknown): string {
  if (!err) return "";
  if (typeof err === "string") return err;
  if (typeof err === "object") {
    const e = err as Record<string, unknown>;
    return String(e.message ?? e.detail ?? e.code ?? JSON.stringify(e));
  }
  return String(err);
}

// --- artifact normalisation ---------------------------------------------------

const PREVIEWABLE = /^(text\/|image\/|application\/(json|pdf))/;

/** The public contract from `artifact_created` (INTERFACES.md 3.6). */
function fromAnnounced(data: Record<string, any>): ArtifactView | null {
  const id = data.artifact_id;
  if (!id) return null;
  return {
    id,
    filename: data.filename ?? id,
    mimeType: data.mime_type ?? null,
    size: Number(data.size ?? 0),
    url: data.secure_url ?? null,
    previewable: Boolean(data.preview_supported),
  };
}

/** A RunResult artifact, from `/api/runs/{id}/result`. */
export function fromResultArtifact(a: Artifact): ArtifactView {
  const mime = a.mime ?? null;
  return {
    id: a.id,
    filename: a.name,
    mimeType: mime,
    size: a.bytes ?? 0,
    url: a.type === "url" ? a.url ?? null : a.preview_url ?? null,
    previewable: a.type === "url" || (mime ? PREVIEWABLE.test(mime) : false),
    action: a.action,
  };
}

function mergeArtifacts(existing: ArtifactView[], incoming: ArtifactView[]): ArtifactView[] {
  const byId = new Map(existing.map((a) => [a.id, a]));
  for (const a of incoming) {
    const prev = byId.get(a.id);
    byId.set(a.id, prev ? { ...a, ...prev, action: prev.action ?? a.action } : a);
  }
  return Array.from(byId.values());
}

// --- step helpers ---------------------------------------------------------------

function addStep(steps: ProgressStep[], step: ProgressStep): ProgressStep[] {
  return [...steps, step];
}

type StepPatch = Partial<ProgressStep> | ((step: ProgressStep) => Partial<ProgressStep>);

function updateStep(
  steps: ProgressStep[],
  match: (s: ProgressStep) => boolean,
  patch: StepPatch,
): { steps: ProgressStep[]; found: boolean } {
  // Most recent match wins: a file can be touched more than once.
  for (let i = steps.length - 1; i >= 0; i -= 1) {
    if (match(steps[i])) {
      const next = steps.slice();
      const change = typeof patch === "function" ? patch(steps[i]) : patch;
      next[i] = { ...steps[i], ...change };
      return { steps: next, found: true };
    }
  }
  return { steps, found: false };
}

const finish = (step: ProgressStep): Partial<ProgressStep> => ({
  status: "done",
  label: doneLabel(step.label),
});

function finishUnderstanding(steps: ProgressStep[]): ProgressStep[] {
  return steps.map((s) =>
    s.kind === "understand" && s.status === "running"
      ? { ...s, status: "done" as const, label: doneLabel(s.label) }
      : s,
  );
}

function settleRunning(steps: ProgressStep[], status: StepStatus): ProgressStep[] {
  return steps.map((s) =>
    s.status === "running"
      ? { ...s, status, label: status === "done" ? doneLabel(s.label) : s.label }
      : s,
  );
}

function samePath(a?: string, b?: string): boolean {
  if (!a || !b) return false;
  const norm = (p: string) => p.replace(/\\/g, "/").replace(/^\.\//, "");
  return norm(a) === norm(b);
}

// --- reducer ------------------------------------------------------------------------

export function runReducer(state: RunView, action: RunAction): RunView {
  switch (action.type) {
    case "reset":
      return initialRunView;

    case "start":
      return {
        ...initialRunView,
        phase: "starting",
        objective: action.objective,
        inputMode: action.inputMode,
      };

    case "dispatched":
      return { ...state, runId: action.runId, phase: "running" };

    case "result_artifacts":
      return {
        ...state,
        artifacts: mergeArtifacts(state.artifacts, action.artifacts.map(fromResultArtifact)),
      };

    case "client_error":
      return {
        ...state,
        phase: "failed",
        steps: settleRunning(state.steps, "failed"),
        error: { message: action.message, type: action.errorType ?? "ClientError" },
      };

    case "event":
      return applyEvent(state, action.event);

    default:
      return state;
  }
}

function applyEvent(state: RunView, envelope: RuntimeEvent): RunView {
  const { event, data = {}, seq } = envelope;

  // Replays and reconnects can overlap; a seq we have seen is a no-op.
  if (seq > 0 && seq <= state.lastSeq) return state;
  const s: RunView = { ...state, lastSeq: seq > 0 ? seq : state.lastSeq };
  if (!s.runId && envelope.run_id) s.runId = envelope.run_id;

  const d = data as Record<string, any>;
  // The contract says `args`; the current brain sends `arguments`.
  const args = (d.args ?? d.arguments ?? {}) as Record<string, any>;

  switch (event) {
    // --- lifecycle ------------------------------------------------------------
    case "run_started":
    case "planning": {
      if (s.steps.some((x) => x.kind === "understand")) {
        return { ...s, phase: s.phase === "starting" ? "running" : s.phase };
      }
      return {
        ...s,
        phase: "running",
        steps: addStep(s.steps, {
          id: "understand",
          kind: "understand",
          label: "Understanding request",
          status: "running",
        }),
      };
    }

    case "chat_response":
      return { ...s, reply: String(d.text ?? s.reply) };

    case "run_completed": {
      const failed = d.status === "failed";
      const reply = String(d.reply || d.summary || s.reply || "");
      return {
        ...s,
        phase: failed ? "failed" : "completed",
        reply,
        steps: settleRunning(s.steps, failed ? "failed" : "done"),
        permission: null,
        error: failed ? { message: reply || "Run failed", type: "RunFailed" } : s.error,
      };
    }

    case "run_failed":
      return {
        ...s,
        phase: "failed",
        permission: null,
        steps: settleRunning(s.steps, "failed"),
        error: {
          message: String(d.message ?? d.error ?? "Run failed unexpectedly."),
          type: String(d.error_type ?? "ExecutionError"),
          node: d.node ?? envelope.node ?? undefined,
        },
      };

    case "run_cancelled":
      return {
        ...s,
        phase: "cancelled",
        permission: null,
        steps: settleRunning(s.steps, "failed"),
        error: { message: String(d.reason ?? "Run cancelled"), type: "Cancelled" },
      };

    // --- tools ----------------------------------------------------------------
    case "tool_started":
    case "tool_call_started": {
      const tool = String(d.tool ?? "tool");
      const path = args.path ?? d.path;
      const command = args.command ?? d.command;
      return {
        ...s,
        steps: addStep(finishUnderstanding(s.steps), {
          id: d.call_id ?? `step_${seq || s.steps.length}`,
          kind: "tool",
          label: toolLabel(tool, path, command),
          status: "running",
          callId: d.call_id,
          tool,
          path,
          command,
        }),
      };
    }

    case "tool_completed":
    case "tool_call_completed": {
      const tool = String(d.tool ?? "");
      const failed = d.ok === false || d.success === false;
      const { steps, found } = updateStep(
        s.steps,
        (x) =>
          x.kind === "tool" &&
          x.status === "running" &&
          (d.call_id ? x.callId === d.call_id : x.tool === tool),
        failed
          ? { status: "failed", detail: errorText(d.error ?? d.reason) || undefined }
          : finish,
      );
      return found ? { ...s, steps } : s;
    }

    case "tool_failed": {
      const tool = String(d.tool ?? "tool");
      const detail = errorText(d.error) || undefined;
      const { steps, found } = updateStep(
        s.steps,
        (x) =>
          x.kind === "tool" &&
          x.status === "running" &&
          (d.call_id ? x.callId === d.call_id : x.tool === tool),
        { status: "failed", detail },
      );
      return {
        ...s,
        steps: found
          ? steps
          : addStep(s.steps, {
              id: d.call_id ?? `step_${seq}`,
              kind: "tool",
              label: toolLabel(tool),
              status: "failed",
              detail,
              tool,
            }),
      };
    }

    // --- files ------------------------------------------------------------------
    case "file_created":
    case "file_updated":
    case "file_deleted":
    case "file_read": {
      const path = String(d.path ?? "");
      if (!path) return s;
      const verb =
        event === "file_created" ? "Created" :
        event === "file_updated" ? "Edited" :
        event === "file_deleted" ? "Deleted" : "Read";
      const isHtml = /\.html?$/i.test(path) && event !== "file_deleted" && event !== "file_read";
      const next: RunView = { ...s, lastHtmlPath: isHtml ? path : s.lastHtmlPath };

      // Already shown by the tool call that produced it: just confirm it.
      const { steps, found } = updateStep(
        next.steps,
        (x) => x.kind === "tool" && samePath(x.path, path),
        {},
      );
      if (found) return { ...next, steps };

      return {
        ...next,
        steps: addStep(finishUnderstanding(next.steps), {
          id: `file_${seq || next.steps.length}`,
          kind: "file",
          label: `${verb} ${basename(path)}`,
          status: event === "file_read" && d.success === false ? "failed" : "done",
          path,
        }),
      };
    }

    // --- commands ----------------------------------------------------------------
    case "command_started": {
      const command = String(d.command ?? "");
      const already = s.steps.some(
        (x) => x.status === "running" && x.command && x.command === command,
      );
      if (already) return s;
      return {
        ...s,
        steps: addStep(finishUnderstanding(s.steps), {
          id: `cmd_${seq || s.steps.length}`,
          kind: "command",
          label: `Running ${clip(command, 48)}`,
          status: "running",
          command,
        }),
      };
    }

    case "command_completed": {
      const command = String(d.command ?? "");
      const exit = d.exit_code;
      const ok = exit === 0 || exit === undefined || exit === null;
      const detail = ok ? undefined : String(d.stderr || `exit code ${exit}`).split("\n")[0];
      const { steps, found } = updateStep(
        s.steps,
        (x) =>
          x.status === "running" &&
          (x.kind === "command" || x.kind === "tool") &&
          (!command || x.command === command || x.kind === "command"),
        ok ? finish : { status: "failed", detail },
      );
      if (found) return { ...s, steps };
      return {
        ...s,
        steps: addStep(s.steps, {
          id: `cmd_${seq}`,
          kind: "command",
          label: `Ran ${clip(command || "a command", 48)}`,
          status: ok ? "done" : "failed",
          detail,
          command,
        }),
      };
    }

    // --- preview / artifacts ----------------------------------------------------------
    case "browser_action":
    case "browser_opened": {
      // Interactions inside a page are not "open a preview". The current
      // brain puts the tool's name in `action`, so anything else opens.
      if (event === "browser_action" && /click|type|scroll|screenshot|press|hover|fill/i.test(String(d.action ?? ""))) {
        return s;
      }
      const target = String(d.url || d.path || "").trim();
      if (!target) return s;
      // A URL is shown as-is; a bare path is a workspace file to preview.
      const isUrl = /^https?:\/\//i.test(target) || target.startsWith("/");
      const hasPreviewStep = s.steps.some((x) => x.kind === "tool" && /preview/i.test(x.label));
      return {
        ...s,
        previewUrl: isUrl ? target : s.previewUrl,
        previewPath: isUrl ? s.previewPath : target,
        steps: hasPreviewStep
          ? s.steps
          : addStep(s.steps, {
              id: `preview_${seq}`,
              kind: "preview",
              label: "Opened preview",
              status: "done",
            }),
      };
    }

    case "artifact_created": {
      const artifact = fromAnnounced(d);
      if (!artifact) return s;
      return { ...s, artifacts: mergeArtifacts(s.artifacts, [artifact]) };
    }

    // --- memory -----------------------------------------------------------------------
    case "memory_recalled": {
      const hits = Array.isArray(d.hits) ? d.hits.length : Number(d.count ?? 0);
      if (!hits) return s;
      return {
        ...s,
        steps: addStep(s.steps, {
          id: `memory_${seq}`,
          kind: "memory",
          label: `Recalled ${hits} past ${hits === 1 ? "experience" : "experiences"}`,
          status: "done",
        }),
      };
    }

    case "memory_applied": {
      const how = String(d.how ?? d.summary ?? "").trim();
      if (!how) return s;
      return {
        ...s,
        memoryApplied: [...s.memoryApplied, how],
        steps: addStep(s.steps, {
          id: `applied_${seq}`,
          kind: "memory",
          label: "Applying what it learned",
          status: "done",
          detail: how,
        }),
      };
    }

    case "memory_recorded":
      return {
        ...s,
        steps: addStep(s.steps, {
          id: `recorded_${seq}`,
          kind: "memory",
          label: "Saved this run to memory",
          status: "done",
        }),
      };

    // --- verification -------------------------------------------------------------------
    case "verification_started":
      return {
        ...s,
        steps: addStep(s.steps, {
          id: `verify_${seq}`,
          kind: "verify",
          label: "Verifying result",
          status: "running",
        }),
      };

    case "verification_completed":
    case "validation_result": {
      const valid = Boolean(d.valid);
      const reason = String(d.reason ?? "");
      const patch: Partial<ProgressStep> = valid
        ? { status: "done", label: "Verified result", detail: reason || undefined }
        : { status: "failed", label: "Verification failed", detail: reason || undefined };
      const { steps, found } = updateStep(
        s.steps,
        (x) => x.kind === "verify" && x.status === "running",
        patch,
      );
      return {
        ...s,
        verification: { valid, reason },
        steps: found
          ? steps
          : addStep(s.steps, {
              id: `verify_${seq}`,
              kind: "verify",
              label: patch.label!,
              status: patch.status!,
              detail: patch.detail,
            }),
      };
    }

    // --- permissions ---------------------------------------------------------------------
    case "permission_required":
    case "approval_required":
    case "approval_requested": {
      const request: PermissionRequest = {
        requestId: String(d.request_id ?? ""),
        tool: String(d.tool ?? ""),
        permission: String(d.permission ?? ""),
        summary: String(d.summary ?? d.reason ?? d.message ?? `Use ${d.tool ?? "a tool"}`),
        risk: String(d.risk ?? "medium"),
      };
      return {
        ...s,
        phase: "paused",
        permission: request,
        steps: addStep(s.steps, {
          id: `perm_${request.requestId || seq}`,
          kind: "permission",
          label: "Waiting for your permission",
          status: "running",
          detail: request.summary,
        }),
      };
    }

    case "permission_granted":
    case "permission_denied":
    case "approval_granted":
    case "approval_rejected": {
      const granted = event === "permission_granted" || event === "approval_granted";
      const { steps } = updateStep(
        s.steps,
        (x) => x.kind === "permission" && x.status === "running",
        granted
          ? { status: "done", label: "Permission granted" }
          : { status: "failed", label: "Permission denied — action not performed" },
      );
      return {
        ...s,
        phase: s.phase === "paused" ? "running" : s.phase,
        permission: null,
        steps,
      };
    }

    // --- workers -------------------------------------------------------------------------
    case "worker_cooldown":
    case "worker_failed":
      // Remembered as the reason for the switch that follows.
      return {
        ...s,
        worker: {
          ...s.worker,
          reason: String(d.reason ?? (event === "worker_cooldown" ? "rate_limit" : "failed")),
        },
      };

    case "worker_switching": {
      const to = workerName(d);
      const from = d.from_worker ? String(d.from_worker) : s.worker.current;
      // The current gateway announces its worker before every LLM call.
      // Only a change of worker is a switch worth showing.
      if (!to || !from || to === from) {
        return { ...s, worker: { ...s.worker, current: to ?? s.worker.current } };
      }
      const reason = d.reason ? String(d.reason) : s.worker.reason;
      return {
        ...s,
        worker: { current: to, previous: from, reason, switches: s.worker.switches + 1 },
        steps: addStep(s.steps, {
          id: `worker_${seq}`,
          kind: "worker",
          label: "Switching worker… continuing",
          status: "done",
          detail: `${reason ? `${reasonText(reason)} — now` : "Now"} on ${to}`,
        }),
      };
    }

    // Reasoning and transport events never reach the screen.
    default:
      return s;
  }
}

/** Is the run still doing something? */
export function isActive(view: RunView): boolean {
  return view.phase === "starting" || view.phase === "running" || view.phase === "paused";
}
