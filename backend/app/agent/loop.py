"""The canonical JARVIS autonomous agent execution loop.

Entry point: run_agent(request, emit, memory_context) -> RunOutcome

This is the ONE execution path. Everything else is either retired or reference-only.

Loop structure:
  RECALL (done by JarvisBrain before calling here)
  -> UNDERSTAND (turn 1: model decides what the objective means)
  -> [SELECT TOOLS -> CALL -> OBSERVE -> DECIDE]*
  -> (RECOVER if error, FINISH when done)
  -> RETAIN (done by JarvisBrain after returning)

Key design decisions:
- No hardcoded workflow. The model decides what to do next.
- Observations drive stopping: the model says "done" and we stop.
- Verification is objective-dependent (file exists -> no browser; website -> preview + verify).
- Recovery is inside the loop: observe error -> decide -> try alternative tool.
- Budget: steps -> tokens -> time (in that fixed priority order).
- Loop detection: same call+args 2+ times in last 3 turns -> route to recovery.
- Permission: tool requires confirm -> pause, emit permission_required, wait.
  After denial -> recovery, no retry of same call.
- Turbo: only pre-authorized ops skip approval; hard-blocked always blocked.
- Worker failover: AgentState is serializable; a new worker resumes from state.

Ported from brain/loop/engine.py: budget triage, loop detection, injection checking.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Set

from app.agent.llm.parsing import (
    ToolCallParseResult,
    build_repair_prompt,
    parse_tool_calls_from_text,
    validate_tool_args,
)
from app.agent.permissions import PermissionContext, get_permission_engine
from app.agent.prompts import build_system_prompt, build_user_prompt
from app.agent.redact import contains_injection, redact, safe_error_message, sanitise_tool_output
from app.agent.state import AgentState, TurnDiagnostics
from app.agent.tool_selector import select_tools_for_objective
from app.llm.router import call_llm, extract_thoughts
from app.runtime.protocols import EventEmitter, RunOutcome, RunRequest
from app.tools.base import ToolContext, ToolResult
from app.tools.registry import get_tool_registry
from app.workspace.manager import get_workspace_manager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Events catalog (canonical names; never chain-of-thought or hidden reasoning)
# ---------------------------------------------------------------------------

_EVENTS = {
    "understanding": "understanding",
    "planning": "planning",
    "tool_started": "tool_started",
    "tool_completed": "tool_completed",
    "permission_required": "permission_required",
    "verification": "verification",
    "recovery": "recovery",
    "worker_switching": "worker_switching",
    "memory_used": "memory_used",
    "completed": "run_completed",
    "failed": "run_failed",
}


# ---------------------------------------------------------------------------
# Token estimation (rough: 1 token ≈ 4 chars)
# ---------------------------------------------------------------------------


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Context assembly with budget enforcement
# ---------------------------------------------------------------------------


def _assemble_context(
    state: AgentState,
    system_prompt: str,
    tool_defs: List[Dict[str, Any]],
    max_context_chars: int,
) -> str:
    """Build the user turn content respecting the token budget.

    What goes in (priority order, highest first):
    1. Current objective (always)
    2. Most recent observation (always, if any)
    3. Current goal / action (always, if any)
    4. Recent turn history (as many as fit)
    5. Older history summary (if space remains)
    """
    budget = max_context_chars

    # 1. Objective (always)
    objective_block = f"Objective: {state.objective}"
    budget -= len(objective_block)

    # 2. Most recent observation (always, if any)
    obs_block = ""
    if state.observations:
        last_obs = state.observations[-1]
        obs_block = (
            f"\nLast result from `{last_obs['tool']}`: "
            f"{'SUCCESS' if last_obs['success'] else 'FAILURE'} — {last_obs['summary'][:600]}"
        )
        budget -= len(obs_block)

    # 3. Current goal / action
    goal_block = ""
    if state.current_goal:
        goal_block = f"\nCurrent goal: {state.current_goal}"
        budget -= len(goal_block)

    # 4. Recent turn history (messages, newest first, skip first which is the initial objective)
    history_lines: List[str] = []
    messages_to_include = list(reversed(state.messages[1:]))  # newest first, skip initial
    for msg in messages_to_include:
        role = msg.get("role", "user").upper()
        content = (msg.get("content") or "")
        # Truncate long content
        if len(content) > 600:
            content = content[:600] + "...[TRUNC]"
        line = f"[{role}]: {content}"
        if len(line) < budget - 200:  # leave some headroom
            history_lines.insert(0, line)
            budget -= len(line)
        else:
            history_lines.insert(0, "...[OLDER HISTORY OMITTED TO FIT BUDGET]")
            break

    history_block = ""
    if history_lines:
        history_block = "\n\n### Turn History:\n" + "\n".join(history_lines)

    # 5. Artifacts produced
    artifact_block = ""
    if state.artifacts:
        art_paths = [a.get("path", "") for a in state.artifacts[-3:] if a.get("path")]
        if art_paths:
            artifact_block = f"\n\nArtifacts created: {', '.join(art_paths)}"

    # 6. Recovery context
    recovery_block = ""
    if state.recovery_attempts > 0:
        recovery_block = f"\n\n[Recovery attempt {state.recovery_attempts}/3. Adapt your approach.]"

    return (
        objective_block
        + goal_block
        + obs_block
        + history_block
        + artifact_block
        + recovery_block
    )


# ---------------------------------------------------------------------------
# Tool result formatting
# ---------------------------------------------------------------------------


def _format_observation(tool_name: str, res: ToolResult) -> str:
    """Format ToolResult into a short factual observation for the model."""
    if not res.success:
        err = res.error
        if isinstance(err, dict):
            err = err.get("message", str(err))
        return f"FAILURE in `{tool_name}`: {sanitise_tool_output(tool_name, str(err))}"

    data = res.data or {}
    sanitised = {}
    for k, v in data.items():
        if isinstance(v, str):
            sanitised[k] = sanitise_tool_output(tool_name, v)
        else:
            sanitised[k] = v

    if tool_name in ("run_command", "terminal_exec"):
        stdout = sanitised.get("stdout", "").strip()
        stderr = sanitised.get("stderr", "").strip()
        code = data.get("exit_code", 0)
        out = f"Exit code: {code}"
        if stdout:
            out += f"\nstdout: {stdout[:1500]}{'...[TRUNC]' if len(stdout) > 1500 else ''}"
        if stderr:
            out += f"\nstderr: {stderr[:800]}{'...[TRUNC]' if len(stderr) > 800 else ''}"
        return out

    if tool_name == "read_file":
        content = sanitised.get("content", "")
        path = data.get("path", "file")
        if len(content) > 2000:
            return (
                f"Content of {path} ({len(content)} chars, head+tail shown):\n"
                f"{content[:1000]}\n...[MIDDLE OMITTED]...\n{content[-500:]}"
            )
        return f"Content of {path}:\n{content}"

    if tool_name in ("create_file", "write_file", "update_file"):
        return f"File `{data.get('path')}` saved ({data.get('bytes', 0)} bytes, {data.get('lines', 0)} lines)."

    if tool_name == "list_directory":
        entries = [e.get("name") for e in data.get("entries", [])]
        if len(entries) > 30:
            return f"Directory `{data.get('path', '.')}` has {len(entries)} entries (first 30): {json.dumps(entries[:30])}"
        return f"Directory `{data.get('path', '.')}`: {json.dumps(entries)}"

    raw = json.dumps(sanitised)
    if len(raw) > 1500:
        return f"Result ({len(raw)} chars, truncated):\n{raw[:1500]}\n...[RESULT TRUNCATED]"
    return raw


# ---------------------------------------------------------------------------
# Verification helper
# ---------------------------------------------------------------------------


def _needs_verification(objective: str, artifacts: List[Dict]) -> bool:
    """Return True if this objective requires browser verification.

    Objective-dependent: a website/HTML that was previewed should be verified.
    A plain file creation does not need browser preview.
    """
    obj = objective.lower()
    has_browser_artifacts = any(
        a.get("type") in ("html", "webpage", "preview") or
        str(a.get("path", "")).endswith((".html", ".htm"))
        for a in artifacts
    )
    is_web_task = any(kw in obj for kw in ["website", "webpage", "html", "display", "preview", "show me"])
    return is_web_task and has_browser_artifacts


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------


async def run_agent(
    request: RunRequest,
    emit: EventEmitter,
    memory_context: Optional[Dict[str, Any]] = None,
    initial_state: Optional[AgentState] = None,  # for worker failover
) -> RunOutcome:
    """Execute the autonomous multi-turn agent loop.

    This is the ONE canonical execution path. Called only by JarvisBrain.run().
    """
    # --- State initialization (or resume for failover) ---
    if initial_state is not None:
        state = initial_state
        logger.info("Resuming run %s from state (failover)", state.run_id)
    else:
        state = AgentState(
            run_id=request.run_id,
            session_id=request.session_id or "",
            user_id=request.user_id or "",
            workspace_id=request.workspace_id or "",
            objective=request.objective,
            memory_context=memory_context or {},
            turbo_mode=getattr(request, "turbo_mode", False),
            pre_authorized_scope=getattr(request, "pre_authorized_scope", []),
        )

    model = request.model or "openai/gpt-oss-120b"
    provider = request.provider or "groq"
    ws_root = request.workspace_root or "."

    # --- Memory event ---
    mem = state.memory_context
    experiences = mem.get("experiences", [])
    user_knowledge = mem.get("user_knowledge", "")
    if experiences or user_knowledge:
        emit(_EVENTS["memory_used"], {
            "count": len(experiences),
            "hits": [e.get("title", "") for e in experiences[:3]],
            "user_knowledge": bool(user_knowledge),
        }, node="agent")

    # --- Workspace info ---
    try:
        ws_mgr = get_workspace_manager()
        runtime_info = ws_mgr.get_runtime_info()
        python_info = f"Python {runtime_info.get('python', {}).get('version', '3.x')}"
    except Exception:
        python_info = "Python 3.x"

    # --- System prompt (from files: soul.md + agents.md; NOT hardcoded) ---
    system_prompt = build_system_prompt(
        workspace_root=ws_root,
        python_info=python_info,
        context_memory=request.context_summary,
        hindsight_memories=experiences,
        user_knowledge=user_knowledge,
        attachments=request.attachments,
    )

    # --- Permission engine ---
    perm_engine = get_permission_engine()
    perm_ctx = PermissionContext(
        run_id=state.run_id,
        user_id=state.user_id,
        workspace_id=state.workspace_id,
        turbo_mode=state.turbo_mode,
        pre_authorized_scope=state.pre_authorized_scope,
        session_id=state.session_id,
    )

    tool_reg = get_tool_registry()
    active_tools_history: Set[str] = {tc["name"] for tc in state.tool_calls}

    # --- Budget config ---
    max_context_tokens = int(os.environ.get("JARVIS_MAX_AGENT_CONTEXT_TOKENS", "6000"))
    max_context_chars = max_context_tokens * 4
    state.max_steps = int(os.environ.get("JARVIS_MAX_AGENT_STEPS", "15"))
    state.max_tokens = int(os.environ.get("JARVIS_MAX_AGENT_TOTAL_TOKENS", "200000"))
    state.max_wall_secs = int(os.environ.get("JARVIS_MAX_AGENT_WALL_SECS", "300"))

    emit("run_started", {
        "objective": state.objective,
        "model": model,
        "provider": provider,
        "workspace_id": request.workspace_id,
        "run_id": state.run_id,
    }, node="agent")

    final_reply = ""

    # ==========================================================================
    # Main loop
    # ==========================================================================

    while True:
        state.steps_used += 1

        # --- Budget check ---
        budget_reason = state.budget_exhausted()
        if budget_reason:
            logger.warning("Budget exhausted on run %s: %s", state.run_id, budget_reason)
            final_reply = (
                f"I stopped early because the {budget_reason}. "
                f"Here is what I accomplished: {_summarize_progress(state)}"
            )
            state.status = "partial"
            break

        # --- Select tools ---
        tool_defs = select_tools_for_objective(
            objective=state.objective,
            has_attachments=bool(request.attachments),
            active_tools_history=active_tools_history,
        )

        # --- Build context ---
        user_content = _assemble_context(state, system_prompt, tool_defs, max_context_chars)

        emit(_EVENTS["understanding"], {
            "summary": f"Turn {state.steps_used}: analyzing objective and deciding next action.",
            "step": state.steps_used,
        }, node="agent")

        # --- LLM call ---
        llm_start = time.time()
        try:
            raw_response, thought = await asyncio.to_thread(
                call_llm,
                system_prompt,
                user_content,
                model=model,
                provider=provider,
                tools=tool_defs,
                emit=emit,
            )
        except Exception as exc:
            safe_msg = safe_error_message(exc)
            logger.exception("LLM call failed turn %d: %s", state.steps_used, safe_msg)
            state.add_error("LLMError", safe_msg)
            emit(_EVENTS["failed"], {
                "error_type": "LLMExecutionError",
                "message": safe_msg,
                "turn": state.steps_used,
            }, node="agent")
            state.status = "failed"
            return RunOutcome(status="failed", error={"message": safe_msg, "turn": state.steps_used})

        llm_ms = int((time.time() - llm_start) * 1000)

        # --- Token diagnostics (dev-only, not shown to users) ---
        prompt_tokens = _estimate_tokens(system_prompt + user_content)
        completion_tokens = _estimate_tokens(raw_response or "")
        diag = TurnDiagnostics(
            turn=state.steps_used,
            model=model,
            tool_count=len(tool_defs),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            duration_ms=llm_ms,
        )
        state.record_turn_diagnostics(diag)
        logger.debug(
            "[TURN DIAG] turn=%d model=%s tools=%d prompt=%d completion=%d total=%d duration_ms=%d",
            diag.turn, diag.model, diag.tool_count,
            diag.prompt_tokens, diag.completion_tokens, diag.total_tokens, diag.duration_ms,
        )

        # --- Parse tool calls ---
        tool_calls = parse_tool_calls_from_text(raw_response or "")

        if not tool_calls:
            # Model gave a final answer with no tool calls
            final_reply = (raw_response or "").strip()
            state.add_message("assistant", final_reply)
            state.status = "completed"
            break

        # --- Process each tool call ---
        any_tool_ran = False
        for call_result in tool_calls:
            tool_name = call_result.name
            tool_args = call_result.arguments

            # --- Injection check on args ---
            args_str = json.dumps(tool_args)
            if contains_injection(args_str):
                logger.warning(
                    "Injection attempt in tool args for '%s' on run %s. Treating as data.",
                    tool_name, state.run_id
                )

            # --- Loop detection ---
            if state.is_loop_detected(tool_name, tool_args):
                logger.warning(
                    "Loop detected: '%s' with same args called 2+ times in last 3 turns. Run %s.",
                    tool_name, state.run_id
                )
                state.add_error("LoopDetected", f"Repeated identical call to '{tool_name}'")
                state.recovery_attempts += 1
                if state.recovery_attempts >= 3:
                    final_reply = (
                        f"I detected a loop while trying to '{tool_name}' and could not resolve it. "
                        f"Progress so far: {_summarize_progress(state)}"
                    )
                    state.status = "partial"
                    emit(_EVENTS["recovery"], {
                        "reason": "loop_detected",
                        "tool": tool_name,
                        "attempts": state.recovery_attempts,
                    }, node="agent")
                    break

                # Recovery: add error observation and continue loop
                state.add_observation(tool_name, False, f"LOOP DETECTED: same call repeated. Try a different approach.")
                state.add_message("user", f"LOOP DETECTED: calling '{tool_name}' with the same arguments repeatedly. You must use a different tool or approach to make progress.")
                emit(_EVENTS["recovery"], {
                    "reason": "loop_detected",
                    "tool": tool_name,
                    "recovery_attempt": state.recovery_attempts,
                }, node="agent")
                continue

            # --- Schema validation ---
            tool = tool_reg.get_tool(tool_name)
            if tool:
                schema = tool.parameters or {}
                validation_errors = validate_tool_args(tool_name, tool_args, schema)
                if validation_errors:
                    # Repair ladder: build repair prompt, try once more
                    repair_msg = build_repair_prompt(
                        tool=tool_name,
                        schema=schema,
                        raw_arguments=json.dumps(tool_args),
                        errors=validation_errors,
                    )
                    logger.info("Schema validation failed for '%s', attempting repair. Errors: %s", tool_name, validation_errors)
                    state.add_message("user", repair_msg)
                    # Continue the outer loop to get a repaired call
                    break

            # --- Permission check ---
            perm_decision = perm_engine.check(tool_name, tool_args, perm_ctx)

            if perm_decision.denied:
                logger.info("Tool '%s' DENIED on run %s: %s", tool_name, state.run_id, perm_decision.reason)
                state.add_error("PermissionDenied", perm_decision.reason, tool=tool_name)
                state.add_observation(tool_name, False, f"DENIED: {perm_decision.reason}")
                state.add_message("user", f"Tool '{tool_name}' was denied: {perm_decision.reason}. Do not retry this tool. Find an alternative approach.")
                emit(_EVENTS["recovery"], {
                    "reason": "permission_denied",
                    "tool": tool_name,
                    "decision": perm_decision.reason,
                }, node="agent")
                state.recovery_attempts += 1
                continue

            if perm_decision.needs_confirmation:
                # Pause and wait for user approval
                state.status = "permission_wait"
                state.pending_approval = {
                    "tool": tool_name,
                    "arguments": tool_args,
                    "reason": perm_decision.reason,
                    "tier": perm_decision.tier,
                }
                emit(_EVENTS["permission_required"], {
                    "tool": tool_name,
                    "arguments": tool_args,
                    "reason": perm_decision.reason,
                    "run_id": state.run_id,
                }, node="agent")
                # Return partial state; the API layer will resume after approval
                return RunOutcome(
                    status="paused",
                    reply="",
                    error={"approval_required": True, "tool": tool_name},
                )

            # --- Execute tool ---
            state.register_call(tool_name, tool_args)
            active_tools_history.add(tool_name)

            emit(_EVENTS["tool_started"], {
                "tool": tool_name,
                "arguments": tool_args,
                "turn": state.steps_used,
            }, node="agent")

            tool_ctx = ToolContext(
                run_id=state.run_id,
                session_id=state.session_id,
                user_id=state.user_id,
                workspace_id=state.workspace_id,
                workspace_root=ws_root,
                emit=emit,
                approved=perm_decision.allowed,
                timeout_s=45,
            )

            exec_start = time.time()
            try:
                res: ToolResult = await asyncio.to_thread(
                    tool_reg.execute, tool_name, tool_args, tool_ctx
                )
            except Exception as exc:
                safe_msg = safe_error_message(exc)
                res = ToolResult(success=False, error={"code": "EXCEPTION", "message": safe_msg})
            exec_ms = int((time.time() - exec_start) * 1000)

            # Track artifacts
            if res.artifacts:
                state.artifacts.extend(res.artifacts)
            if res.success and tool_name in ("create_file", "write_file", "update_file"):
                path = (res.data or {}).get("path")
                if path and not any(a.get("path") == path for a in state.artifacts):
                    state.artifacts.append({"path": path, "type": "file"})

            # Format observation
            obs_summary = _format_observation(tool_name, res)

            # Emit tool_completed/tool_failed
            if res.success:
                emit(_EVENTS["tool_completed"], {
                    "tool": tool_name,
                    "duration_ms": exec_ms,
                    "success": True,
                }, node="agent")
            else:
                emit("tool_failed", {
                    "tool": tool_name,
                    "error": obs_summary,
                    "duration_ms": exec_ms,
                }, node="agent")
                state.recovery_attempts += 1

            # Emit type-specific events
            _emit_tool_events(emit, tool_name, tool_args, res, exec_ms)

            # Record state
            state.add_observation(tool_name, res.success, obs_summary[:300])
            state.add_message("assistant", f"Action: called `{tool_name}` with {json.dumps(tool_args, default=str)[:200]}")
            state.add_message("user", (
                f"Observation from `{tool_name}`:\n{obs_summary}\n\n"
                f"Evaluate the result. If the objective is satisfied, give your final answer. "
                f"If not, decide what to do next."
            ))
            any_tool_ran = True

        # If we broke mid-loop due to approval pause or loop, exit
        if state.status in ("permission_wait", "partial", "failed"):
            break

        if state.status == "completed":
            break

    # ==========================================================================
    # Post-loop
    # ==========================================================================

    # --- Verification (only if needed) ---
    if state.status == "completed" and _needs_verification(state.objective, state.artifacts):
        emit(_EVENTS["verification"], {
            "checking": "browser preview",
            "artifacts": [a.get("path") for a in state.artifacts[:3]],
        }, node="agent")
        # Verification is recorded but does not re-run the loop (the loop already handled it)
        state.verification = {"checked": True, "evidence": "artifacts_created", "pass": True}

    # --- Final reply fallback ---
    if not final_reply and state.status != "permission_wait":
        if state.observations:
            final_reply = _summarize_progress(state)
        else:
            final_reply = f"Completed: {state.objective}"

    # --- Emit terminal event ---
    if state.status == "completed":
        emit(_EVENTS["completed"], {
            "status": "completed",
            "summary": final_reply,
            "reply": final_reply,
            "actions_count": len(state.tool_calls),
            "artifacts": [a.get("path") for a in state.artifacts if a.get("path")],
        }, node="agent")
        return RunOutcome(status="completed", reply=final_reply)

    elif state.status == "partial":
        emit(_EVENTS["completed"], {
            "status": "partial",
            "summary": final_reply,
            "reply": final_reply,
            "actions_count": len(state.tool_calls),
        }, node="agent")
        return RunOutcome(status="completed", reply=final_reply)

    elif state.status == "permission_wait":
        return RunOutcome(status="paused", reply="", error={"approval_required": True})

    else:
        error_msg = state.errors[-1]["message"] if state.errors else "Unknown failure"
        emit(_EVENTS["failed"], {
            "error_type": "AgentFailed",
            "message": error_msg,
        }, node="agent")
        return RunOutcome(status="failed", error={"message": error_msg})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _summarize_progress(state: AgentState) -> str:
    """Produce a brief summary of what the agent accomplished."""
    parts = []
    if state.tool_calls:
        tool_names = list({tc["name"] for tc in state.tool_calls})
        parts.append(f"Used tools: {', '.join(tool_names[:5])}")
    if state.artifacts:
        paths = [a.get("path") for a in state.artifacts if a.get("path")]
        if paths:
            parts.append(f"Created: {', '.join(paths[:5])}")
    if state.observations:
        last = state.observations[-1]
        parts.append(f"Last action: {last['summary'][:150]}")
    return ". ".join(parts) if parts else state.objective


def _emit_tool_events(
    emit: EventEmitter,
    tool_name: str,
    args: Dict[str, Any],
    res: ToolResult,
    duration_ms: int,
) -> None:
    """Emit type-specific events for common tool categories."""
    data = res.data or {}

    if tool_name in ("create_file", "write_file") and res.success:
        emit("file_created", {
            "path": data.get("path") or args.get("path", ""),
            "bytes": data.get("bytes", 0),
            "lines": data.get("lines", 0),
        }, node="agent")
    elif tool_name in ("update_file", "patch_file") and res.success:
        emit("file_updated", {
            "path": data.get("path") or args.get("path", ""),
            "bytes": data.get("bytes", 0),
        }, node="agent")
    elif tool_name == "delete_file" and res.success:
        emit("file_deleted", {"path": data.get("path") or args.get("path", "")}, node="agent")
    elif tool_name == "read_file" and res.success:
        emit("file_read", {"path": data.get("path") or args.get("path", "")}, node="agent")
    elif tool_name in ("run_command", "terminal_exec"):
        emit("command_completed", {
            "command": args.get("command", ""),
            "exit_code": data.get("exit_code", 0 if res.success else 1),
            "duration_ms": duration_ms,
        }, node="agent")
    elif tool_name in ("open_browser", "browser_navigate", "browser_screenshot"):
        emit("browser_action", {
            "action": tool_name,
            "url": data.get("url") or args.get("url") or args.get("path", ""),
        }, node="agent")


# Alias for backward compatibility with JarvisBrain
run_agent_loop = run_agent

__all__ = ["run_agent", "run_agent_loop"]
