import os
import re
import time
import asyncio
from typing import List, Dict, Any, Optional, Callable

from app.events import emit
from app.llm.router import call_llm
from app.workspace.manager import get_workspace_manager
from app.graph.controller import (
    evaluate_next_decision,
    MAX_AUTONOMOUS_ITERATIONS,
    MAX_REPLANS,
    MAX_RECOVERY_ATTEMPTS,
    DECISION_CONTINUE,
    DECISION_RECOVER,
    DECISION_REPLAN,
    DECISION_VALIDATE,
    DECISION_WAIT_FOR_APPROVAL,
    DECISION_COMPLETE,
    DECISION_FAIL
)
from app.graph.nodes.orchestrator import orchestrator_node
from app.graph.nodes.researcher import researcher_node
from app.graph.nodes.executor import executor_node
from app.graph.nodes.validator import validator_node
from app.graph.nodes.recovery import recovery_node

nodes = {
    "orchestrator": orchestrator_node,
    "researcher": researcher_node,
    "executor": executor_node,
    "validator": validator_node,
    "recovery": recovery_node
}

def is_code_execution_objective(objective: str) -> bool:
    obj_lower = objective.strip().lower()
    cleaned = re.sub(r'[^\w\s\.\-]', '', obj_lower).strip()

    # Casual greetings
    greetings = {"hi", "hello", "hey", "hola", "sup", "greetings", "good morning", "good evening", "good afternoon", "howdy"}
    if cleaned in greetings:
        return False

    # Conversational questions that are not requesting code execution or file manipulation
    conversational_patterns = [
        r'^(who|what) are you\??$',
        r'^how are you\??$',
        r'^what can you do\??$',
        r'^help\??$',
        r'^tell me (about|a joke)',
        r'^explain\b',
        r'^what is\b'
    ]
    if any(re.search(p, obj_lower) for p in conversational_patterns):
        if not any(w in obj_lower for w in ["create", "write", "code", "file", "script", "build", "run", "make", "generate"]):
            return False

    # Explicit action cues for code / agentic workflow:
    action_cues = [
        "create", "write", "build", "make", "generate", "code", "run", "execute", 
        "script", "test", "delete", "remove", "update", "modify", "refactor",
        "open", "browser", "html", "css", "python", ".py", ".html", 
        ".js", ".json", ".csv", ".txt", ".md", "list files", "dir", "inspect", "show files"
    ]
    return any(cue in obj_lower for cue in action_cues)

def sanitize_error_message(msg: str) -> str:
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if groq_key and groq_key in msg:
        msg = msg.replace(groq_key, "[REDACTED_API_KEY]")
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")
    if openrouter_key and openrouter_key in msg:
        msg = msg.replace(openrouter_key, "[REDACTED_API_KEY]")
    return msg

async def execute_run_task(
    run_id: str,
    objective: str,
    runs_db: dict,
    recent_context: Optional[List[Dict[str, Any]]] = None,
    session_context_summary: Optional[str] = None,
    workspace_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    on_complete: Optional[Callable[[Dict[str, Any]], None]] = None,
    model: Optional[str] = "qwen/qwen3.8-27b",
    provider: Optional[str] = "groq",
    attachments: Optional[List[Dict[str, Any]]] = None
):
    from app.workspace.manager import get_workspace_manager, active_workspace_id
    if workspace_id:
        active_workspace_id.set(workspace_id)
    ws = get_workspace_manager()
    ws_info = {
        "workspace_id": ws.workspace_id,
        "name": ws.name,
        "root_path": ws.root_path
    }

    state = {
        "run_id": run_id,
        "objective": objective,
        "model": model or "qwen/qwen3.8-27b",
        "provider": provider or "groq",
        "workspace": ws_info,
        "workspace_id": workspace_id,
        "conversation_id": conversation_id,
        "session_context_summary": session_context_summary or "",
        "conversation_context": recent_context or [],
        "plan": [],
        "thoughts": [],
        "current_step": "orchestrator",
        "research": [],
        "tool_calls": [],
        "observations": [],
        "artifacts": [],
        "attachments": attachments or [],
        "validation_results": [],
        "status": "started",
        "error": None,
        "retry_count": 0,
        # Human-in-the-loop approval state
        "approval_required": False,
        "approval_status": "none",
        "approval_request": None,
        "autonomous_iteration_count": 0,
        "replan_count": 0,
        "recovery_attempts": 0
    }
    
    runs_db[run_id]["status"] = "running"
    runs_db[run_id]["state"] = state

    await emit(run_id, "context_loaded", "orchestrator", {
        "workspace": ws_info,
        "workspace_id": workspace_id,
        "conversation_id": conversation_id,
        "conversation_turns": len(state["conversation_context"]),
        "context_summary": session_context_summary or "",
        "objective": objective
    })

    # --- DYNAMIC INTENT ROUTING: CONVERSATIONAL VS FULL AGENTIC DAG ---
    if not is_code_execution_objective(objective):
        runs_db[run_id]["type"] = "chat"
        state["mode"] = "chat"

        from app.graph.agent_docs import load_all_agent_docs
        agent_docs = load_all_agent_docs()

        system_prompt = "You are JARVIS, an advanced autonomous AI computer agent and software engineering orchestrator.\n"
        if agent_docs:
            system_prompt += f"\n[Foundational Directives & Agent Identity (SOUL, HEAD, TOOLS, WORKFLOW)]:\n{agent_docs}\n"
        if session_context_summary:
            system_prompt += f"\n[Session Context Memory]:\n{session_context_summary}\n"
        if recent_context:
            system_prompt += "\n[Recent Chat History]:\n"
            for turn in recent_context[-3:]:
                r = turn.get("role", "user")
                c = turn.get("content", "")[:180]
                system_prompt += f"{r.upper()}: {c}\n"

        system_prompt += (
            "\nRespond naturally, directly, and concisely as JARVIS. "
            "Maintain conversational continuity with the user's ongoing session context and past experiences. "
            "Do NOT output JSON plans, tool steps, or markdown fences when answering conversational queries."
        )

        # Inject attached file contents so the LLM can see them
        if attachments:
            system_prompt += "\n\n[User Attached Files]:\n"
            for att in attachments:
                name = att.get('name', 'unknown')
                content = att.get('content', '')[:4000]  # Cap at 4k chars per file
                system_prompt += f"--- {name} ---\n{content}\n---\n"

        try:
            chat_reply, chat_thought = await asyncio.to_thread(
                call_llm,
                system_prompt,
                objective,
                model=model,
                provider=provider
            )
        except Exception as e:
            chat_reply = f"Error processing request with {model} ({provider}): {sanitize_error_message(str(e))}"
            chat_thought = f"LLM error: {str(e)}"

        if chat_thought:
            thought_payload = {
                "node": "chat",
                "phase": "Conversational Intent",
                "title": "Natural Language Response",
                "thought": chat_thought,
                "model": model,
                "provider": provider,
                "timestamp": time.time()
            }
            state.setdefault("thoughts", []).append(thought_payload)
            await emit(run_id, "thought_generated", "chat", thought_payload)

        await emit(run_id, "chat_response", "assistant", {
            "text": chat_reply,
            "objective": objective
        })

        state["final_response"] = chat_reply
        state["status"] = "completed"
        runs_db[run_id]["status"] = "completed"
        runs_db[run_id]["state"] = state

        # Persist conversation turn to session memory
        if workspace_id and conversation_id:
            try:
                from app.api.sandbox import save_conversation_turn
                save_conversation_turn(workspace_id, conversation_id, objective, chat_reply)
            except Exception as e:
                print(f"Error persisting chat turn: {e}")

        if on_complete:
            on_complete({"role": "user", "text": objective, "reply": chat_reply})

        await emit(run_id, "run_completed", "assistant", {
            "status": "completed",
            "type": "chat",
            "reply": chat_reply,
            "summary": chat_reply
        })
        return

    try:
        while state["current_step"] != "end":
            state["autonomous_iteration_count"] += 1

            # Bounded Autonomous Control Decision
            decision, decision_reason = evaluate_next_decision(state)

            if decision == DECISION_FAIL:
                state["status"] = "failed"
                await emit(run_id, "agent_thinking", "controller", {"summary": f"Autonomous Controller Limit: {decision_reason}"})
                break

            if decision == DECISION_WAIT_FOR_APPROVAL:
                state["approval_required"] = True
                await emit(run_id, "agent_thinking", "controller", {"summary": decision_reason})
                break

            if decision == DECISION_REPLAN:
                state["replan_count"] += 1
                await emit(run_id, "agent_thinking", "controller", {"summary": f"Autonomous Re-Plan ({state['replan_count']}/{MAX_REPLANS}): {decision_reason}"})
                state["current_step"] = "orchestrator"
            elif decision == DECISION_RECOVER:
                state["current_step"] = "recovery"
            elif decision == DECISION_VALIDATE:
                if state["current_step"] not in ["validator", "end"]:
                    state["current_step"] = "validator"

            current_node_name = state["current_step"]
            if current_node_name not in nodes:
                break

            node_fn = nodes[current_node_name]
            await emit(run_id, "node_started", current_node_name, {"step": current_node_name})

            state = await node_fn(state)

            data = {"next": state["current_step"]}
            if current_node_name == "orchestrator":
                data["plan"] = state.get("plan")
            elif current_node_name == "researcher":
                data["research"] = state.get("research")
            elif current_node_name == "executor":
                data["observations"] = state.get("observations", [])[-3:]
                data["artifacts"] = state.get("artifacts", [])
            elif current_node_name == "validator":
                data["validation_results"] = state.get("validation_results", [])[-1:]

            await emit(run_id, "node_completed", current_node_name, data)
            runs_db[run_id]["state"] = state

            # Pause the run when a destructive action requires human approval.
            if (
                state.get("approval_required") is True
                and state.get("approval_status") == "pending"
            ):
                runs_db[run_id]["status"] = "paused"

                await emit(
                    run_id,
                    "approval_required",
                    "executor",
                    {
                        "status": "pending",
                        "request": state.get("approval_request")
                    }
                )

                return

            if current_node_name == "validator" and state["current_step"] == "end":
                break

        last_val = state.get("validation_results", [{}])[-1] if state.get("validation_results") else {}
        is_final_valid = last_val.get("valid", False) if last_val else True
        if state.get("status") == "failed" or not is_final_valid:
            runs_db[run_id]["status"] = "failed"
            await emit(run_id, "run_failed", node="validator", data={"message": last_val.get("reason", "Validation failed")})
        else:
            runs_db[run_id]["status"] = "completed"
            summary_msg = f"Task completed successfully: {objective}"
            if state.get("artifacts"):
                art_paths = [a.get("path", "") for a in state["artifacts"] if a.get("path")]
                if art_paths:
                    summary_msg += f"\n\nArtifacts Generated:\n" + "\n".join(f"- `{p}`" for p in art_paths)
            proc_obs = [o for o in state.get("observations", []) if o.get("stdout")]
            if proc_obs:
                latest_stdout = proc_obs[-1].get("stdout", "").strip()
                if latest_stdout:
                    summary_msg += f"\n\nOutput:\n```\n{latest_stdout}\n```"
            await emit(run_id, "run_completed", data={"final_status": "completed", "summary": summary_msg})

        # Persist execution run summary into session conversation
        if workspace_id and conversation_id:
            try:
                from app.api.sandbox import save_conversation_turn
                summary_msg = f"Task completed: {objective}"
                if state.get("artifacts"):
                    art_paths = [a.get("path", "") for a in state["artifacts"] if a.get("path")]
                    if art_paths:
                        summary_msg += f"\nArtifacts: {', '.join(art_paths)}"
                save_conversation_turn(
                    workspace_id,
                    conversation_id,
                    objective,
                    summary_msg,
                    {"run_id": run_id, "status": runs_db[run_id]["status"], "artifacts": state.get("artifacts", [])}
                )
            except Exception as e:
                print(f"Error saving execution turn: {e}")

        if on_complete:
            on_complete({
                "run_id": run_id,
                "objective": objective,
                "artifacts": state.get("artifacts", []),
                "observations": state.get("observations", [])[-2:] if state.get("observations") else [],
                "validation": state.get("validation_results", [])[-1:] if state.get("validation_results") else []
            })
        
    except Exception as e:
        runs_db[run_id]["status"] = "failed"
        current_node_name = state.get("current_step", "unknown")
        safe_msg = sanitize_error_message(str(e))
        error_payload = {
            "error_type": type(e).__name__,
            "message": safe_msg,
            "node": current_node_name
        }
        runs_db[run_id]["state"]["error"] = error_payload
        await emit(run_id, "run_failed", node=current_node_name, data=error_payload)


async def resume_approved_run(
    run_id: str,
    decision: str,
    runs_db: dict
):
    run = runs_db.get(run_id)

    if not run:
        raise ValueError("Run not found")

    state = run.get("state", {})

    if run.get("status") != "paused":
        raise ValueError("Run is not waiting for approval")

    if not state.get("approval_required"):
        raise ValueError("Run has no pending approval request")

    if state.get("approval_status") != "pending":
        raise ValueError("Approval request is no longer pending")

    approval_request = state.get("approval_request") or {}

    if decision == "reject":
        state["approval_required"] = False
        state["approval_status"] = "rejected"
        state["status"] = "completed"

        state.setdefault("observations", []).append({
            "tool": approval_request.get("tool"),
            "path": approval_request.get("path"),
            "status": "rejected",
            "message": "User rejected the destructive action.",
            "exit_code": 0
        })

        run["state"] = state
        run["status"] = "completed"

        await emit(
            run_id,
            "approval_rejected",
            "executor",
            {
                "status": "rejected",
                "request": approval_request
            }
        )

        await emit(
            run_id,
            "run_completed",
            data={
                "final_status": "rejected"
            }
        )

        return state

    if decision != "approve":
        raise ValueError("Decision must be 'approve' or 'reject'")

    if approval_request.get("tool") != "delete_file":
        raise ValueError("Unsupported approval action")

    target_file = approval_request.get("path")

    if not target_file:
        raise ValueError("Approval request is missing the target path")

    from app.workspace.tools import execute_tool

    await emit(
        run_id,
        "approval_granted",
        "executor",
        {
            "status": "approved",
            "request": approval_request
        }
    )

    await emit(
        run_id,
        "tool_call_started",
        "executor",
        {
            "tool": "delete_file",
            "path": target_file,
            "approved": True
        }
    )

    del_res = await asyncio.to_thread(
        execute_tool,
        "delete_file",
        path=target_file,
        approved=True
    )

    await emit(
        run_id,
        "tool_call_completed",
        "executor",
        del_res
    )

    if not del_res.get("success"):
        state["approval_required"] = False
        state["approval_status"] = "approved"
        state["status"] = "failed"
        state["error"] = {
            "error_type": "DeleteFailed",
            "message": del_res.get("error", "Approved deletion failed."),
            "node": "executor"
        }

        run["state"] = state
        run["status"] = "failed"

        await emit(
            run_id,
            "run_failed",
            "executor",
            state["error"]
        )

        return state

    state["approval_required"] = False
    state["approval_status"] = "approved"
    state["approval_request"] = None

    state.setdefault("observations", []).append({
        "tool": "delete_file",
        "path": target_file,
        "status": "deleted",
        "exit_code": 0
    })

    await emit(
        run_id,
        "file_deleted",
        "executor",
        {
            "path": target_file,
            "status": "deleted"
        }
    )

    state["current_step"] = "validator"
    state["status"] = "running"
    run["state"] = state
    run["status"] = "running"

    # Resume the remaining workflow from the validator.
    while state["current_step"] != "end":
        current_node_name = state["current_step"]

        if current_node_name not in nodes:
            break

        node_fn = nodes[current_node_name]

        await emit(
            run_id,
            "node_started",
            current_node_name,
            {
                "step": current_node_name
            }
        )

        state = await node_fn(state)

        data = {
            "next": state["current_step"]
        }

        if current_node_name == "validator":
            data["validation_results"] = state.get(
                "validation_results",
                []
            )[-1:]

        elif current_node_name == "recovery":
            data["observations"] = state.get(
                "observations",
                []
            )[-3:]

        await emit(
            run_id,
            "node_completed",
            current_node_name,
            data
        )

        run["state"] = state

    run["state"] = state
    run["status"] = "completed"

    await emit(
        run_id,
        "run_completed",
        data={
            "final_status": "completed"
        }
    )

    return state
