"use client";

/**
 * One run, start to finish: dispatch it, stream its events into
 * `runReducer`, and fetch the final artifacts when it ends.
 *
 * Components read `view`; nothing else subscribes to the event stream.
 */

import { useCallback, useEffect, useReducer, useRef } from "react";

import { ApiError, runs, sessions } from "./client";
import { initialRunView, isActive, runReducer, type RunView } from "./runReducer";
import type { RuntimeEvent } from "./types";
import { useRunStream } from "./useRunStream";

export interface StartRunOptions {
  sessionId: string | null;
  workspaceId: string | null;
  objective: string;
  inputMode?: "text" | "voice";
  executionMode?: "normal" | "turbo";
  model?: string;
  provider?: string;
  attachments?: Array<{ name: string; content: string; size?: number }>;
  audioUrl?: string | null;
}

export interface RunHandle {
  view: RunView;
  /** Resolves with the session the run landed in (created if there was none). */
  start: (opts: StartRunOptions) => Promise<{ runId: string; sessionId: string } | null>;
  cancel: () => Promise<void>;
  reset: () => void;
  connection: ReturnType<typeof useRunStream>["state"];
}

export function useRun(onFinished?: (view: RunView) => void): RunHandle {
  const [view, dispatch] = useReducer(runReducer, initialRunView);

  const onEvent = useCallback((event: RuntimeEvent) => {
    dispatch({ type: "event", event });
  }, []);

  const stream = useRunStream(view.runId, { onEvent });

  // A stream that gave up reconnecting is the only client-side failure left.
  useEffect(() => {
    if (stream.state === "error" && isActive(view)) {
      dispatch({
        type: "client_error",
        message: stream.error ?? "Lost connection to JARVIS. The run may still be going.",
        errorType: "ConnectionLost",
      });
    }
    // Only react to the stream giving up, not to every view change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stream.state]);

  // End-of-run work happens once per run: artifacts from the result, then
  // the caller's hook (reload the session, speak the reply, ...).
  const finishedRef = useRef<string | null>(null);
  const onFinishedRef = useRef(onFinished);
  useEffect(() => {
    onFinishedRef.current = onFinished;
  }, [onFinished]);

  useEffect(() => {
    if (!view.runId || isActive(view) || view.phase === "idle") return;
    if (finishedRef.current === view.runId) return;
    finishedRef.current = view.runId;

    const runId = view.runId;
    const snapshot = view;
    runs
      .result(runId)
      .then((result) => {
        if (result?.artifacts?.length) {
          dispatch({ type: "result_artifacts", artifacts: result.artifacts });
        }
      })
      .catch(() => undefined)
      .finally(() => onFinishedRef.current?.(snapshot));
  }, [view]);

  const start = useCallback(async (opts: StartRunOptions) => {
    const objective = opts.objective.trim();
    if (!objective) return null;

    dispatch({ type: "start", objective, inputMode: opts.inputMode ?? "text" });
    finishedRef.current = null;

    try {
      let sessionId = opts.sessionId;
      if (!sessionId) {
        const created = await sessions.create(opts.workspaceId ?? undefined, objective.slice(0, 60));
        sessionId = created.session.id;
      }

      const res = await sessions.startRun(sessionId, {
        objective,
        model: opts.model,
        provider: opts.provider,
        input_mode: opts.inputMode ?? "text",
        execution_mode: opts.executionMode ?? "normal",
        workspace_id: opts.workspaceId ?? undefined,
        attachments: opts.attachments?.length ? opts.attachments : undefined,
        audio_url: opts.audioUrl ?? undefined,
      });

      dispatch({ type: "dispatched", runId: res.run_id });
      return { runId: res.run_id, sessionId: res.session_id };
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.status === 0
            ? "Can't reach the JARVIS backend. Is it running?"
            : err.message
          : "Couldn't start the run.";
      dispatch({ type: "client_error", message, errorType: "StartFailed" });
      return null;
    }
  }, []);

  const cancel = useCallback(async () => {
    if (!view.runId) return;
    try {
      await runs.cancel(view.runId);
    } catch {
      // 409 means it already finished; the stream will say so.
    }
  }, [view.runId]);

  const reset = useCallback(() => {
    dispatch({ type: "reset" });
    finishedRef.current = null;
  }, []);

  return { view, start, cancel, reset, connection: stream.state };
}

export default useRun;
