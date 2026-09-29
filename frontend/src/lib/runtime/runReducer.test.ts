import { describe, expect, it } from "vitest";

import { initialRunView, isActive, runReducer, type RunAction, type RunView } from "./runReducer";
import type { RuntimeEvent } from "./types";

let seq = 0;
function ev(event: string, data: Record<string, unknown> = {}): RunAction {
  seq += 1;
  const envelope: RuntimeEvent = {
    seq,
    event,
    run_id: "run_test",
    node: "agent",
    ts: new Date().toISOString(),
    data,
  };
  return { type: "event", event: envelope };
}

function play(...actions: RunAction[]): RunView {
  return actions.reduce(runReducer, runReducer(initialRunView, {
    type: "start",
    objective: "Build a site",
    inputMode: "text",
  }));
}

const labels = (v: RunView) => v.steps.map((s) => `${s.status}:${s.label}`);

describe("a full run (the scripted website scenario)", () => {
  seq = 0;
  const view = play(
    { type: "dispatched", runId: "run_test" },
    ev("run_started", { objective: "Build a site" }),
    ev("memory_recalled", { hits: [{ id: "exp_1" }] }),
    ev("memory_applied", { how: "Kept styles inline." }),
    ev("tool_started", { tool: "create_file", call_id: "c1", args: { path: "scripted_demo/index.html" } }),
    ev("file_created", { path: "scripted_demo/index.html", bytes: 900 }),
    ev("tool_completed", { tool: "create_file", call_id: "c1", ok: true }),
    ev("worker_switching", { from_worker: "groq-primary", to_worker: "groq-secondary", reason: "rate_limited" }),
    ev("tool_started", { tool: "preview_site", call_id: "c2" }),
    ev("browser_action", { action: "open", url: "/api/runs/run_test/artifacts/art_1" }),
    ev("artifact_created", {
      artifact_id: "art_1", filename: "index.html", mime_type: "text/html",
      size: 900, preview_supported: true, secure_url: "/api/runs/run_test/artifacts/art_1",
    }),
    ev("tool_completed", { tool: "preview_site", call_id: "c2", ok: true }),
    ev("verification_started", { target: "index.html" }),
    ev("verification_completed", { valid: true, reason: "Renders" }),
    ev("memory_recorded", { experience_id: "exp_9" }),
    ev("run_completed", { status: "completed", reply: "Done. Your storefront is ready." }),
  );

  it("ends completed with the reply", () => {
    expect(view.phase).toBe("completed");
    expect(view.reply).toBe("Done. Your storefront is ready.");
    expect(isActive(view)).toBe(false);
  });

  it("shows plain-language progress, in order, all finished", () => {
    expect(labels(view)).toEqual([
      "done:Understood request",
      "done:Recalled 1 past experience",
      "done:Applying what it learned",
      "done:Created index.html",
      "done:Switching worker… continuing",
      "done:Opened preview",
      "done:Verified result",
      "done:Saved this run to memory",
    ]);
  });

  it("does not duplicate a file the tool step already shows", () => {
    expect(view.steps.filter((s) => s.path === "scripted_demo/index.html")).toHaveLength(1);
  });

  it("keeps the memory evidence, the worker, the preview and the artifact", () => {
    expect(view.memoryApplied).toEqual(["Kept styles inline."]);
    expect(view.worker).toMatchObject({ current: "groq-secondary", previous: "groq-primary", switches: 1 });
    expect(view.previewUrl).toBe("/api/runs/run_test/artifacts/art_1");
    expect(view.artifacts).toEqual([
      expect.objectContaining({ id: "art_1", filename: "index.html", previewable: true }),
    ]);
    expect(view.verification).toEqual({ valid: true, reason: "Renders" });
  });
});

describe("safety of the view", () => {
  it("never turns model reasoning into a step", () => {
    seq = 0;
    const view = play(
      ev("run_started"),
      ev("thought_generated", { thought: "internal chain of thought" }),
      ev("agent_thinking", { summary: "Because the user wants..." }),
    );
    expect(JSON.stringify(view)).not.toContain("chain of thought");
    expect(JSON.stringify(view)).not.toContain("Because the user");
  });

  it("ignores an event it has already seen (replay after reconnect)", () => {
    seq = 0;
    const runStarted = ev("run_started");
    const started = ev("tool_started", { tool: "read_file", call_id: "c1", args: { path: "a.txt" } });
    const view = play(runStarted, started, started);
    expect(view.steps.filter((s) => s.kind === "tool")).toHaveLength(1);
  });
});

describe("failures", () => {
  it("a failed tool is shown, and the run can still complete", () => {
    seq = 0;
    const view = play(
      ev("run_started"),
      ev("tool_started", { tool: "read_file", call_id: "c1", args: { path: "missing.txt" } }),
      ev("tool_failed", { tool: "read_file", call_id: "c1", error: { code: "FILE_NOT_FOUND", message: "missing.txt does not exist" } }),
      ev("run_completed", { status: "completed", reply: "It doesn't exist." }),
    );
    const step = view.steps.find((s) => s.callId === "c1")!;
    expect(step.status).toBe("failed");
    expect(step.detail).toBe("missing.txt does not exist");
    expect(view.phase).toBe("completed");
  });

  it("run_failed marks the run and any running step failed", () => {
    seq = 0;
    const view = play(
      ev("run_started"),
      ev("tool_started", { tool: "run_command", call_id: "c1", args: { command: "npm test" } }),
      ev("run_failed", { message: "boom", error_type: "RuntimeError", node: "agent" }),
    );
    expect(view.phase).toBe("failed");
    expect(view.error).toEqual({ message: "boom", type: "RuntimeError", node: "agent" });
    expect(view.steps.every((s) => s.status !== "running")).toBe(true);
  });

  it("a non-zero command exit is a failed step with the first stderr line", () => {
    seq = 0;
    const view = play(
      ev("run_started"),
      ev("command_started", { command: "pytest" }),
      ev("command_completed", { command: "pytest", exit_code: 1, stderr: "2 failed\nmore" }),
    );
    const step = view.steps.find((s) => s.kind === "command")!;
    expect(step).toMatchObject({ status: "failed", detail: "2 failed" });
  });
});

describe("permissions", () => {
  it("pauses on permission_required and resumes on a decision", () => {
    seq = 0;
    const paused = play(
      ev("run_started"),
      ev("permission_required", {
        request_id: "perm_1", tool: "run_command", permission: "terminal.execute",
        summary: "Execute npm install", risk: "medium",
      }),
    );
    expect(paused.phase).toBe("paused");
    expect(isActive(paused)).toBe(true);
    expect(paused.permission).toMatchObject({ requestId: "perm_1", summary: "Execute npm install" });

    const denied = runReducer(paused, ev("permission_denied", { request_id: "perm_1" }));
    expect(denied.phase).toBe("running");
    expect(denied.permission).toBeNull();
    expect(labels(denied)).toContain("failed:Permission denied — action not performed");
  });
});

describe("legacy event names from the old graph", () => {
  it("still produce the same view", () => {
    seq = 0;
    const view = play(
      ev("run_started"),
      ev("tool_call_started", { tool: "create_file", path: "app.py" }),
      ev("tool_call_completed", { tool: "create_file", success: true }),
      ev("validation_result", { valid: false, reason: "Syntax error" }),
      ev("browser_opened", { url: "http://localhost:8006/api/preview/default/index.html" }),
      ev("approval_required", { tool: "delete_file", reason: "Deleting app.py" }),
    );
    expect(labels(view)).toContain("done:Created app.py");
    expect(labels(view)).toContain("failed:Verification failed");
    expect(view.previewUrl).toContain("/api/preview/default/index.html");
    expect(view.permission?.summary).toBe("Deleting app.py");
  });
});

describe("events shaped the way the current brain sends them", () => {
  it("reads `arguments`, matches without call ids, and previews a bare path", () => {
    seq = 0;
    const view = play(
      ev("run_started"),
      ev("memory_recalled", { count: 2, hits: ["built a site", "user likes dark mode"] }),
      ev("tool_started", { tool: "create_file", arguments: { path: "shop/index.html" }, turn: 1 }),
      ev("tool_completed", { tool: "create_file", success: true, duration_ms: 5 }),
      ev("file_created", { path: "shop/index.html", bytes: 10 }),
      ev("tool_started", { tool: "open_browser", arguments: { path: "shop/index.html" } }),
      ev("browser_action", { action: "open_browser", url: "shop/index.html", path: "" }),
      ev("tool_completed", { tool: "open_browser", success: true }),
      ev("run_completed", { status: "completed", reply: "Your shop is ready.", actions_count: 2 }),
    );
    expect(labels(view)).toEqual([
      "done:Understood request",
      "done:Recalled 2 past experiences",
      "done:Created index.html",
      "done:Opened preview",
    ]);
    expect(view.previewPath).toBe("shop/index.html");
    expect(view.previewUrl).toBeNull();
    expect(view.reply).toBe("Your shop is ready.");
  });

  it("does not treat a click inside the page as opening a preview", () => {
    seq = 0;
    const view = play(ev("run_started"), ev("browser_action", { action: "click", url: "https://x.test" }));
    expect(view.previewUrl).toBeNull();
  });
});

describe("workers, as the current gateway reports them", () => {
  const announce = (w: string) =>
    ev("worker_switching", { message: `Switching execution worker to ${w}...` });

  it("does not call every LLM turn a switch", () => {
    seq = 0;
    const view = play(ev("run_started"), announce("groq (llama-3.1-8b-instant)"), ev("worker_connected"),
      announce("groq (llama-3.1-8b-instant)"), ev("worker_connected"));
    expect(view.steps.some((s) => s.kind === "worker")).toBe(false);
    expect(view.worker.current).toBe("groq (llama-3.1-8b-instant)");
    expect(view.worker.switches).toBe(0);
  });

  it("shows a real switch, with the reason from the cooldown before it", () => {
    seq = 0;
    const view = play(
      ev("run_started"),
      announce("groq (llama-3.1-8b-instant)"),
      ev("worker_cooldown", { worker_id: "w1", reason: "rate_limit", cooldown_s: 20 }),
      announce("openai (gpt-4o-mini)"),
    );
    const step = view.steps.find((s) => s.kind === "worker")!;
    expect(step.label).toBe("Switching worker… continuing");
    expect(step.detail).toBe("Rate limited — now on openai (gpt-4o-mini)");
    expect(view.worker).toMatchObject({ current: "openai (gpt-4o-mini)", previous: "groq (llama-3.1-8b-instant)", switches: 1 });
  });
});

describe("artifacts announced by the tool layer's registry", () => {
  it("accepts url / download_url in place of secure_url", () => {
    seq = 0;
    const view = play(
      ev("artifact_created", {
        artifact_id: "art_reg1", filename: "report.pdf", mime_type: "application/pdf", size: 2048,
        url: "/api/artifacts/art_reg1/content", download_url: "/api/artifacts/art_reg1/download",
        preview_supported: true, viewer_type: "pdf",
      }),
    );
    expect(view.artifacts[0]).toMatchObject({
      id: "art_reg1",
      url: "/api/artifacts/art_reg1/content",
      downloadUrl: "/api/artifacts/art_reg1/download",
      previewable: true,
    });
  });

  it("derives a download link for the runtime's own artifact URLs", () => {
    seq = 0;
    const view = play(
      ev("artifact_created", {
        artifact_id: "art_1", filename: "index.html", mime_type: "text/html", size: 1,
        preview_supported: true, secure_url: "/api/runs/run_test/artifacts/art_1",
      }),
    );
    expect(view.artifacts[0].downloadUrl).toBe("/api/runs/run_test/artifacts/art_1?download=1");
  });
});

describe("artifacts from the final result", () => {
  it("merge with announced ones without duplicates", () => {
    seq = 0;
    const announced = play(
      ev("artifact_created", {
        artifact_id: "art_1", filename: "index.html", mime_type: "text/html",
        size: 10, preview_supported: true, secure_url: "/x/art_1",
      }),
    );
    const merged = runReducer(announced, {
      type: "result_artifacts",
      artifacts: [
        { id: "art_1", type: "file", name: "index.html", action: "created", bytes: 10, mime: "text/html", preview_url: "/x/art_1" },
        { id: "art_2", type: "file", name: "data.csv", action: "created", bytes: 5, mime: "text/csv", preview_url: "/x/art_2" },
      ],
    });
    expect(merged.artifacts.map((a) => a.id)).toEqual(["art_1", "art_2"]);
    expect(merged.artifacts[0].action).toBe("created");
  });
});
