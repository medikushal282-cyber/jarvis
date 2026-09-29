"""The core autonomous execution loop for JARVIS.

Coordinates iterative LLM reasoning, dynamic tool selection, tool execution
via ToolRegistry, telemetry emission, and self-correction.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Set

from app.agent.prompts import build_system_prompt, build_user_prompt
from app.agent.tool_selector import select_tools_for_objective
from app.llm.router import call_llm, extract_thoughts
from app.runtime.protocols import EventEmitter, RunOutcome, RunRequest
from app.tools.base import ToolContext, ToolResult
from app.tools.registry import get_tool_registry
from app.workspace.manager import get_workspace_manager

logger = logging.getLogger(__name__)

MAX_TURNS = 15


async def run_agent_loop(
    request: RunRequest,
    emit: EventEmitter,
    memory_context: Optional[Dict[str, Any]] = None,
) -> RunOutcome:
    """Execute the autonomous multi-turn ReAct agent loop."""
    run_id = request.run_id
    objective = request.objective
    model = request.model or "openai/gpt-oss-120b"
    provider = request.provider or "groq"
    ws_root = request.workspace_root or "."

    # 1. Emit run_started lifecycle event
    emit("run_started", {
        "objective": objective,
        "model": model,
        "provider": provider,
        "workspace_id": request.workspace_id,
        "input_mode": request.input_mode,
    }, node="agent")

    # 2. Extract Memory Context & Notify
    mem = memory_context or {}
    experiences = mem.get("experiences", [])
    user_knowledge = mem.get("user_knowledge", "")
    if experiences or user_knowledge:
        emit("memory_recalled", {
            "count": len(experiences),
            "hits": [e.get("title", "") for e in experiences],
            "user_knowledge": bool(user_knowledge),
        }, node="agent")

    # 3. Resolve Workspace Runtime Info
    ws_mgr = get_workspace_manager()
    runtime_info = ws_mgr.get_runtime_info()
    python_info = f"Python {runtime_info.get('python', {}).get('version', '3.x')} ({runtime_info.get('python', {}).get('executable', 'python')})"

    # 4. Construct System Prompt & Initial User Prompt
    system_prompt = build_system_prompt(
        workspace_root=ws_root,
        python_info=python_info,
        context_memory=request.context_summary,
        hindsight_memories=experiences,
        user_knowledge=user_knowledge,
        attachments=request.attachments,
    )

    user_prompt = build_user_prompt(
        objective=objective,
        conversation_turns=request.conversation,
    )

    # State tracking across turns
    messages: List[Dict[str, Any]] = [
        {"role": "user", "content": user_prompt}
    ]
    active_tools_history: Set[str] = set()
    executed_actions_count = 0
    final_reply = ""

    tool_reg = get_tool_registry()

    for turn_idx in range(1, MAX_TURNS + 1):
        # Select focused tools based on objective & history to preserve token quota
        tool_defs = select_tools_for_objective(
            objective=objective,
            has_attachments=bool(request.attachments),
            active_tools_history=active_tools_history,
        )

        emit("agent_thinking", {
            "summary": f"Turn {turn_idx}: Analyzing objective and deciding next action."
        }, node="agent")

        # Call LLM via Router
        try:
            # We flatten messages into a compact conversational prompt if provider is basic
            current_user_content = messages[-1]["content"] if messages and messages[-1]["role"] == "user" else "Continue with next step or summarize results."
            
            # Format history for multi-turn awareness
            history_context = ""
            if len(messages) > 1:
                hist_lines = []
                for m in messages[:-1]:
                    r = m.get("role", "system").upper()
                    c = (m.get("content") or "")[:400].replace("\n", " ")
                    hist_lines.append(f"[{r}]: {c}")
                history_context = "\n### Turn History:\n" + "\n".join(hist_lines) + "\n"

            combined_user_prompt = current_user_content
            if history_context and history_context not in combined_user_prompt:
                combined_user_prompt = history_context + "\n" + current_user_content

            raw_response, extracted_thought = await asyncio.to_thread(
                call_llm,
                system_prompt,
                combined_user_prompt,
                model=model,
                provider=provider,
                tools=tool_defs,
            )
        except Exception as exc:
            logger.exception("LLM call failed in turn %d: %s", turn_idx, exc)
            emit("run_failed", {
                "error_type": "LLMExecutionError",
                "message": f"LLM provider error: {exc}",
                "node": "agent",
            }, node="agent")
            return RunOutcome(status="failed", error={"message": str(exc), "turn": turn_idx})

        # Broadcast reasoning thoughts if captured
        if extracted_thought:
            thought_payload = {
                "node": "agent",
                "phase": f"Reasoning & Planning (Turn {turn_idx})",
                "thought": extracted_thought,
                "model": model,
                "provider": provider,
                "timestamp": time.time(),
            }
            emit("thought_generated", thought_payload, node="agent")

        # Parse LLM response for Tool Calls vs Final Answer
        tool_calls = _parse_tool_calls(raw_response)

        if not tool_calls:
            # Model completed without further tool calls
            final_reply = raw_response.strip()
            break

        # Process each tool call
        for call in tool_calls:
            tool_name = call.get("name")
            tool_args = call.get("arguments", {})
            active_tools_history.add(tool_name)
            executed_actions_count += 1

            # Telemetry for tool invocation
            emit("tool_started", {
                "tool": tool_name,
                "arguments": tool_args,
                "turn": turn_idx,
            }, node="agent")

            tool_ctx = ToolContext(
                run_id=run_id,
                session_id=request.session_id,
                user_id=request.user_id,
                workspace_id=request.workspace_id,
                workspace_root=ws_root,
                emit=emit,
                approved=True,
                timeout_s=45,
            )

            # Execute tool safely in worker thread without blocking event loop
            start_t = time.time()
            res: ToolResult = await asyncio.to_thread(tool_reg.execute, tool_name, tool_args, tool_ctx)
            duration_ms = int((time.time() - start_t) * 1000)

            # Specific telemetry emissions based on tool type
            _emit_tool_specific_events(emit, tool_name, tool_args, res, duration_ms)

            # Record tool result into conversation history for LLM self-correction
            result_str = _format_tool_result_for_llm(tool_name, res)
            messages.append({"role": "assistant", "content": f"Action: Called tool `{tool_name}` with {json.dumps(tool_args)}"})
            messages.append({"role": "user", "content": f"Observation from `{tool_name}`:\n{result_str}\n\nEvaluate the result and proceed with next step or provide final response."})

    # If no final reply was generated, synthesize clean summary
    if not final_reply:
        final_reply = f"Completed execution for '{objective}' with {executed_actions_count} actions."

    # 5. Emit run_completed
    emit("run_completed", {
        "status": "completed",
        "summary": final_reply,
        "reply": final_reply,
        "actions_count": executed_actions_count,
    }, node="agent")

    return RunOutcome(
        status="completed",
        reply=final_reply,
    )


def _parse_tool_calls(response_text: str) -> List[Dict[str, Any]]:
    """Robustly parse tool calls from model output (JSON block or clean structure)."""
    calls: List[Dict[str, Any]] = []
    text = response_text.strip()

    # 1. <tool_call>...</tool_call> tag extraction (GPT-OSS / Qwen style)
    if "<tool_call>" in text:
        blocks = text.split("<tool_call>")
        for b in blocks[1:]:
            chunk = b.split("</tool_call>")[0].strip()
            try:
                parsed = json.loads(chunk)
                if isinstance(parsed, dict) and "name" in parsed:
                    calls.append({"name": parsed["name"], "arguments": parsed.get("arguments", {})})
                elif isinstance(parsed, dict) and "tool" in parsed:
                    calls.append({"name": parsed["tool"], "arguments": parsed.get("arguments", {})})
            except Exception:
                pass

    # 2. Markdown JSON block extraction
    if not calls and "```json" in text:
        blocks = text.split("```json")
        for b in blocks[1:]:
            chunk = b.split("```")[0].strip()
            try:
                parsed = json.loads(chunk)
                if isinstance(parsed, dict) and "tool" in parsed:
                    calls.append({"name": parsed["tool"], "arguments": parsed.get("arguments", {})})
                elif isinstance(parsed, dict) and "name" in parsed and "arguments" in parsed:
                    calls.append(parsed)
                elif isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, dict) and "tool" in item:
                            calls.append({"name": item["tool"], "arguments": item.get("arguments", {})})
            except Exception:
                pass

    # 3. Raw JSON string detection
    if not calls and text.startswith("{") and text.endswith("}"):
        try:
            parsed = json.loads(text)
            if "tool" in parsed:
                calls.append({"name": parsed["tool"], "arguments": parsed.get("arguments", {})})
            elif "name" in parsed and "arguments" in parsed:
                calls.append(parsed)
        except Exception:
            pass

    return calls


def _format_tool_result_for_llm(tool_name: str, res: ToolResult) -> str:
    """Format ToolResult compactly for LLM consumption."""
    if not res.success:
        err = res.error or "Unknown error"
        return f"FAILURE in `{tool_name}`: {err}"

    data = res.data or res.result or {}
    if tool_name in ("run_command", "terminal_exec"):
        stdout = data.get("stdout", "").strip()
        stderr = data.get("stderr", "").strip()
        code = data.get("exit_code", 0)
        out = f"Exit code: {code}"
        if stdout:
            out += f"\nstdout: {stdout[:1500]}"
        if stderr:
            out += f"\nstderr: {stderr[:1000]}"
        return out

    if tool_name == "read_file":
        content = data.get("content", "")
        return f"Content of {data.get('path')}:\n{content[:2000]}"

    if tool_name in ("create_file", "write_file", "update_file"):
        return f"File `{data.get('path')}` saved successfully ({data.get('bytes', 0)} bytes, {data.get('lines', 0)} lines)."

    if tool_name == "list_directory":
        entries = [e.get("name") for e in data.get("entries", [])]
        return f"Directory contents of `{data.get('path', '.')}`: {json.dumps(entries[:30])}"

    return json.dumps(data)[:1500]


def _emit_tool_specific_events(
    emit: EventEmitter,
    tool_name: str,
    args: Dict[str, Any],
    res: ToolResult,
    duration_ms: int,
) -> None:
    """Translate ToolResult into canonical event catalog emissions."""
    data = res.data or res.result or {}

    if res.success:
        emit("tool_completed", {
            "tool": tool_name,
            "duration_ms": duration_ms,
            "success": True,
        }, node="agent")
    else:
        emit("tool_failed", {
            "tool": tool_name,
            "error": res.error or "Action failed",
            "duration_ms": duration_ms,
        }, node="agent")

    # Filesystem events
    if tool_name in ("create_file", "write_file") and res.success:
        emit("file_created", {
            "path": data.get("path") or args.get("path", "file"),
            "bytes": data.get("bytes", 0),
            "lines": data.get("lines", 0),
        }, node="agent")
    elif tool_name in ("update_file", "patch_file") and res.success:
        emit("file_updated", {
            "path": data.get("path") or args.get("path", "file"),
            "bytes": data.get("bytes", 0),
            "lines": data.get("lines", 0),
        }, node="agent")
    elif tool_name == "delete_file" and res.success:
        emit("file_deleted", {
            "path": data.get("path") or args.get("path", "file"),
        }, node="agent")
    elif tool_name == "read_file" and res.success:
        emit("file_read", {
            "path": data.get("path") or args.get("path", "file"),
        }, node="agent")

    # Command execution events
    elif tool_name in ("run_command", "terminal_exec"):
        emit("command_completed", {
            "command": args.get("command", ""),
            "exit_code": data.get("exit_code", 0 if res.success else 1),
            "stdout": data.get("stdout", ""),
            "stderr": data.get("stderr", ""),
            "duration_ms": duration_ms,
        }, node="agent")

    # Browser events
    elif tool_name in ("open_browser", "browser_navigate", "browser_screenshot"):
        emit("browser_action", {
            "action": tool_name,
            "url": data.get("url") or args.get("url") or args.get("path", ""),
            "path": data.get("path", ""),
        }, node="agent")
