"use client";

/**
 * Subscribe to a run's event stream, resumably.
 *
 * The browser's EventSource already re-sends Last-Event-ID on reconnect, and
 * the backend sets `id:` to the event seq -- so a dropped connection resumes
 * with no gap and no duplicates. This hook adds the part EventSource does not
 * give us: a seq high-water mark that survives a full remount, so a page
 * refresh mid-run replays the timeline instead of losing it.
 *
 * See docs/runtime/EVENTS.md section 6.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { API_BASE } from "./client";
import {
  type ConnectionState,
  type RuntimeEvent,
  isTerminal,
  isTransport,
} from "./types";

const MAX_RETRIES = 6;
const BASE_BACKOFF_MS = 500;

export interface UseRunStreamOptions {
  /** Called for every non-transport event, in seq order. */
  onEvent?: (event: RuntimeEvent) => void;
  /** Called once with the terminal event. */
  onTerminal?: (event: RuntimeEvent) => void;
  /** Keep the full event list in state. Off by default for long runs. */
  collect?: boolean;
  /** Resume from this seq instead of 0. */
  fromSeq?: number;
  enabled?: boolean;
}

export interface RunStreamHandle {
  events: RuntimeEvent[];
  lastSeq: number;
  state: ConnectionState;
  error: string | null;
  /** True while replaying buffered history rather than receiving live events. */
  replaying: boolean;
  close: () => void;
  reconnect: () => void;
}

export function useRunStream(
  runId: string | null,
  options: UseRunStreamOptions = {},
): RunStreamHandle {
  const { onEvent, onTerminal, collect = false, fromSeq = 0, enabled = true } = options;

  const [events, setEvents] = useState<RuntimeEvent[]>([]);
  const [state, setState] = useState<ConnectionState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [replaying, setReplaying] = useState(false);

  const sourceRef = useRef<EventSource | null>(null);
  const lastSeqRef = useRef(fromSeq);
  const retriesRef = useRef(0);
  const closedRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Keep the callbacks in refs so a re-render does not tear down the stream.
  const onEventRef = useRef(onEvent);
  const onTerminalRef = useRef(onTerminal);
  useEffect(() => {
    onEventRef.current = onEvent;
    onTerminalRef.current = onTerminal;
  }, [onEvent, onTerminal]);

  const teardown = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    sourceRef.current?.close();
    sourceRef.current = null;
  }, []);

  const close = useCallback(() => {
    closedRef.current = true;
    teardown();
    setState("closed");
  }, [teardown]);

  const connect = useCallback(() => {
    if (!runId || closedRef.current) return;

    teardown();
    setState(lastSeqRef.current > 0 ? "reconnecting" : "connecting");

    const url = `${API_BASE}/api/runs/${encodeURIComponent(runId)}/events?from_seq=${lastSeqRef.current}`;
    const source = new EventSource(url);
    sourceRef.current = source;

    const handle = (raw: MessageEvent) => {
      let envelope: RuntimeEvent;
      try {
        envelope = JSON.parse(raw.data);
      } catch {
        return;
      }

      if (envelope.event === "stream_ready") {
        retriesRef.current = 0;
        setError(null);
        // A non-zero current_seq with nothing consumed yet means history
        // is about to be replayed.
        const current = Number(envelope.data?.current_seq ?? 0);
        setReplaying(current > lastSeqRef.current);
        setState("live");
        return;
      }

      if (envelope.event === "heartbeat") {
        setReplaying(false);
        return;
      }

      // Drop anything we have already seen; a reconnect can overlap.
      if (envelope.seq <= lastSeqRef.current) return;
      lastSeqRef.current = envelope.seq;

      if (isTransport(envelope.event)) return;

      if (collect) setEvents((prev) => [...prev, envelope]);
      onEventRef.current?.(envelope);

      if (isTerminal(envelope.event)) {
        setReplaying(false);
        onTerminalRef.current?.(envelope);
        closedRef.current = true;
        teardown();
        setState("closed");
      }
    };

    source.onmessage = handle;
    source.onopen = () => {
      retriesRef.current = 0;
      setError(null);
    };
    source.onerror = () => {
      if (closedRef.current) return;
      source.close();
      sourceRef.current = null;

      if (retriesRef.current >= MAX_RETRIES) {
        setState("error");
        setError("Lost connection to JARVIS. The run may still be going.");
        return;
      }

      const delay = BASE_BACKOFF_MS * 2 ** retriesRef.current;
      retriesRef.current += 1;
      setState("reconnecting");
      timerRef.current = setTimeout(connect, delay);
    };
  }, [runId, collect, teardown]);

  const reconnect = useCallback(() => {
    closedRef.current = false;
    retriesRef.current = 0;
    connect();
  }, [connect]);

  useEffect(() => {
    if (!runId || !enabled) {
      teardown();
      setState("idle");
      return;
    }

    closedRef.current = false;
    retriesRef.current = 0;
    lastSeqRef.current = fromSeq;
    setEvents([]);
    connect();

    return () => {
      closedRef.current = true;
      teardown();
    };
    // `connect` is stable per runId; fromSeq only seeds the first connection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, enabled]);

  return {
    events,
    lastSeq: lastSeqRef.current,
    state,
    error,
    replaying,
    close,
    reconnect,
  };
}

export default useRunStream;
