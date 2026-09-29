"use client";

/**
 * JARVIS Workers: the LLM workers the gateway fails over between.
 *
 * Shows each worker's health (READY / COOLDOWN / DISABLED), lets a person
 * add, test, reorder, pause and remove workers. Keys are write-only: the API
 * returns a four-character hint and never the key itself.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, workers as workersApi } from "@/lib/runtime/client";
import type { WorkerSummary } from "@/lib/runtime/types";

const DEFAULT_MODEL: Record<string, string> = {
  groq: "llama-3.1-8b-instant",
  openai: "gpt-4o-mini",
  anthropic: "claude-3-5-haiku-20241022",
  gemini: "gemini-1.5-flash",
};

const POLL_OPEN_MS = 2000;
const POLL_CLOSED_MS = 15000;

type Health = "READY" | "COOLDOWN" | "DISABLED" | "ERROR";

function health(w: WorkerSummary): Health {
  if (w.status === "COOLDOWN") return "COOLDOWN";
  if (w.status === "DISABLED" || w.enabled === false) return "DISABLED";
  if (w.status === "ERROR") return "ERROR";
  return "READY";
}

const DOT: Record<Health, string> = {
  READY: "bg-green-500",
  COOLDOWN: "bg-amber-400",
  DISABLED: "bg-neutral-400",
  ERROR: "bg-red-500",
};

const LABEL_CLS: Record<Health, string> = {
  READY: "text-green-700",
  COOLDOWN: "text-amber-700",
  DISABLED: "text-neutral-500",
  ERROR: "text-red-700",
};

export default function WorkerPoolControl() {
  const [open, setOpen] = useState(false);
  const [workers, setWorkers] = useState<WorkerSummary[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [adding, setAdding] = useState(false);
  const [provider, setProvider] = useState("groq");
  const [model, setModel] = useState(DEFAULT_MODEL.groq);
  const [priority, setPriority] = useState(10);
  const [apiKey, setApiKey] = useState("");
  const [test, setTest] = useState<{ state: "idle" | "testing" | "ok" | "fail"; message?: string }>({ state: "idle" });
  const [saveError, setSaveError] = useState<string | null>(null);

  const panelRef = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async () => {
    try {
      setWorkers(await workersApi.list());
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof ApiError && err.status === 0 ? "Backend unreachable" : "Couldn't load workers");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), open ? POLL_OPEN_MS : POLL_CLOSED_MS);
    return () => window.clearInterval(id);
  }, [open, refresh]);

  // Close on Escape or a click outside the panel.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    const onClick = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  const resetForm = () => {
    setAdding(false);
    setApiKey("");
    setTest({ state: "idle" });
    setSaveError(null);
  };

  const change = async (w: WorkerSummary, body: Parameters<typeof workersApi.update>[1]) => {
    setBusyId(w.worker_id);
    try {
      await workersApi.update(w.worker_id, body);
      await refresh();
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (w: WorkerSummary) => {
    if (!window.confirm(`Remove ${w.provider} (${w.model})? Its key is deleted.`)) return;
    setBusyId(w.worker_id);
    try {
      await workersApi.remove(w.worker_id);
      await refresh();
    } finally {
      setBusyId(null);
    }
  };

  const runTest = async () => {
    if (!apiKey.trim()) return;
    setTest({ state: "testing" });
    try {
      const res = await workersApi.test({ provider, model, api_key: apiKey });
      setTest({ state: res.success ? "ok" : "fail", message: res.message });
    } catch (err) {
      setTest({ state: "fail", message: err instanceof ApiError ? err.message : "Test failed" });
    }
  };

  const save = async () => {
    if (!apiKey.trim()) return;
    setSaveError(null);
    try {
      await workersApi.create({ provider, model, api_key: apiKey, priority });
      resetForm();
      await refresh();
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : "Couldn't save the worker");
    }
  };

  const healths = workers.map(health);
  const badgeDot =
    workers.length === 0
      ? "bg-neutral-400"
      : healths.includes("READY")
        ? "bg-green-500"
        : healths.includes("COOLDOWN")
          ? "bg-amber-400"
          : "bg-red-500";
  const readyCount = healths.filter((h) => h === "READY").length;

  return (
    <div className="relative" ref={panelRef}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title={
          workers.length === 0
            ? "No workers configured: using the key from backend/.env"
            : `${readyCount} of ${workers.length} workers ready`
        }
        className="flex items-center space-x-2 border-2 border-fra-black bg-fra-cream-card px-2.5 py-1 font-mono text-[11px] font-black shadow-brutal transition-colors hover:bg-fra-yellow"
      >
        <span>WORKERS {workers.length || "ENV"}</span>
        <span className={`h-2 w-2 rounded-full border border-black ${badgeDot}`} aria-hidden="true" />
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-2 flex max-h-[85vh] w-96 flex-col overflow-y-auto border-2 border-fra-black bg-fra-cream-card p-2 font-mono shadow-brutal">
          <div className="mb-1 flex items-center justify-between border-b-2 border-fra-black pb-1">
            <span className="text-xs font-bold uppercase tracking-tight">JARVIS Workers</span>
            <button type="button" onClick={() => setOpen(false)} className="text-base font-bold leading-none hover:text-red-500" aria-label="Close">
              &times;
            </button>
          </div>
          <p className="mb-2 text-[10px] leading-snug text-neutral-600">
            JARVIS uses the highest-priority ready worker. If one is rate-limited it cools down and the
            same run continues on the next.
          </p>

          {loadError && (
            <div className="mb-2 border border-red-400 bg-red-50 p-1.5 text-[10px] font-bold text-red-700">{loadError}</div>
          )}

          <div className="mb-3 flex flex-col space-y-2">
            {workers.map((w) => {
              const h = health(w);
              const busy = busyId === w.worker_id;
              return (
                <div key={w.worker_id} className={`border-2 border-fra-black bg-white p-2 ${busy ? "opacity-60" : ""}`}>
                  <div className="flex items-center justify-between">
                    <div className="flex min-w-0 items-center space-x-2">
                      <span className={`h-2 w-2 flex-shrink-0 rounded-full border border-black ${DOT[h]}`} aria-hidden="true" />
                      <span className="text-[11px] font-bold uppercase">{w.provider}</span>
                      <span className="truncate text-[10px] font-bold text-neutral-800" title={w.model}>{w.model}</span>
                    </div>
                    <span className={`flex-shrink-0 text-[9px] font-bold uppercase ${LABEL_CLS[h]}`}>
                      {h}
                      {h === "COOLDOWN" && w.cooldown_remaining ? ` ${w.cooldown_remaining}s` : ""}
                    </span>
                  </div>

                  <div className="mt-1.5 flex items-center justify-between text-[9px] font-bold text-neutral-600">
                    <span>KEY {w.api_key_hint || "none"}</span>
                    <div className="flex items-center space-x-1">
                      <span>PRIORITY</span>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void change(w, { priority: (w.priority ?? 1) - 1 })}
                        className="border border-black bg-neutral-100 px-1 hover:bg-fra-yellow"
                        aria-label="Lower priority"
                      >
                        &minus;
                      </button>
                      <span className="w-5 text-center text-black">{w.priority ?? 1}</span>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void change(w, { priority: (w.priority ?? 1) + 1 })}
                        className="border border-black bg-neutral-100 px-1 hover:bg-fra-yellow"
                        aria-label="Raise priority"
                      >
                        +
                      </button>
                    </div>
                  </div>

                  {w.last_error_hint && h !== "READY" && (
                    <div className="mt-1 text-[9px] text-red-700">Last error: {w.last_error_hint}</div>
                  )}

                  <div className="mt-2 flex items-center gap-1.5 text-[9px] font-bold">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void change(w, { enabled: w.enabled === false })}
                      className="border border-black bg-white px-1.5 py-0.5 hover:bg-neutral-100"
                    >
                      {w.enabled === false ? "ENABLE" : "PAUSE"}
                    </button>
                    {h === "COOLDOWN" && (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void change(w, { reset_cooldown: true })}
                        className="border border-black bg-white px-1.5 py-0.5 hover:bg-neutral-100"
                      >
                        RESET COOLDOWN
                      </button>
                    )}
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void remove(w)}
                      className="ml-auto border border-black bg-red-500 px-1.5 py-0.5 text-white hover:bg-red-600"
                    >
                      REMOVE
                    </button>
                  </div>
                </div>
              );
            })}

            {workers.length === 0 && !loadError && (
              <div className="border border-dashed border-neutral-400 p-2 text-center text-[10px] font-bold text-gray-500">
                No workers yet. JARVIS is using the key from backend/.env.
              </div>
            )}
          </div>

          {!adding ? (
            <button
              type="button"
              onClick={() => setAdding(true)}
              className="w-full border-2 border-fra-black bg-fra-yellow py-1.5 text-[11px] font-bold uppercase shadow-brutal-sm hover:bg-yellow-400"
            >
              + Add Worker
            </button>
          ) : (
            <div className="flex flex-col space-y-2 border-2 border-fra-black bg-white p-2.5 text-[10px]">
              <label className="flex flex-col">
                <span className="text-[9px] font-bold uppercase text-neutral-600">Provider</span>
                <select
                  value={provider}
                  onChange={(e) => {
                    setProvider(e.target.value);
                    setModel(DEFAULT_MODEL[e.target.value] ?? "");
                    setTest({ state: "idle" });
                  }}
                  className="border-2 border-fra-black bg-fra-cream p-1 text-[10px] font-bold outline-none"
                >
                  <option value="groq">Groq</option>
                  <option value="openai">OpenAI</option>
                  <option value="anthropic">Anthropic</option>
                  <option value="gemini">Gemini</option>
                </select>
              </label>

              <label className="flex flex-col">
                <span className="text-[9px] font-bold uppercase text-neutral-600">Model</span>
                <input
                  type="text"
                  value={model}
                  onChange={(e) => {
                    setModel(e.target.value);
                    setTest({ state: "idle" });
                  }}
                  className="border-2 border-fra-black p-1 font-mono text-[10px] outline-none"
                />
              </label>

              <label className="flex flex-col">
                <span className="text-[9px] font-bold uppercase text-neutral-600">Priority (higher is tried first)</span>
                <input
                  type="number"
                  min={1}
                  max={100}
                  value={priority}
                  onChange={(e) => setPriority(Math.max(1, Math.min(100, parseInt(e.target.value, 10) || 1)))}
                  className="border-2 border-fra-black p-1 font-mono text-[10px] outline-none"
                />
              </label>

              <label className="flex flex-col">
                <span className="text-[9px] font-bold uppercase text-neutral-600">API key</span>
                <input
                  type="password"
                  autoComplete="off"
                  value={apiKey}
                  onChange={(e) => {
                    setApiKey(e.target.value);
                    setTest({ state: "idle" });
                  }}
                  placeholder="Stored on this machine only"
                  className="border-2 border-fra-black p-1 font-mono text-[10px] outline-none"
                />
              </label>

              {test.state !== "idle" && (
                <div
                  className={`border p-1 text-[10px] font-bold ${
                    test.state === "ok"
                      ? "border-green-400 bg-green-100 text-green-800"
                      : test.state === "testing"
                        ? "border-neutral-300 bg-neutral-100 text-neutral-700"
                        : "border-red-400 bg-red-100 text-red-800"
                  }`}
                >
                  {test.state === "testing" ? "Testing…" : test.message}
                </div>
              )}
              {saveError && (
                <div className="border border-red-400 bg-red-100 p-1 text-[10px] font-bold text-red-800">{saveError}</div>
              )}

              <div className="flex space-x-1.5 pt-1">
                <button
                  type="button"
                  onClick={() => void runTest()}
                  disabled={test.state === "testing" || !apiKey.trim()}
                  className="flex-1 border-2 border-fra-black bg-neutral-200 py-1 text-[9px] font-bold text-black hover:bg-neutral-300 disabled:opacity-50"
                >
                  Test connection
                </button>
                <button
                  type="button"
                  onClick={() => void save()}
                  disabled={!apiKey.trim() || !model.trim()}
                  className="flex-1 border-2 border-fra-black bg-fra-yellow py-1 text-[9px] font-bold text-black hover:bg-yellow-400 disabled:opacity-50"
                >
                  Save worker
                </button>
              </div>
              <button type="button" onClick={resetForm} className="mt-1 w-full text-center text-[9px] text-neutral-500 hover:text-black">
                Cancel
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
