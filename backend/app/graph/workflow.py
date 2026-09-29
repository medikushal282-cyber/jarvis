# =============================================================================
# RETIRED — legacy reference only (branch agent/core, 2026-09-29)
#
# This file contains the old multi-agent DAG pipeline:
#   Orchestrator -> Researcher -> Executor -> Validator -> Recovery
#
# It is NO LONGER called by any active API route. The canonical execution
# path is:
#   JarvisBrain.run(request, emit) -> run_agent(request, emit, memory_ctx)
#   File: backend/app/agent/brain.py + backend/app/agent/loop.py
#
# This file is kept as a reference implementation only. Do not add new
# callers. See docs/agent/AUDIT.md §4 for the full retirement decision.
# =============================================================================

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

from app.attachments import get_attachment_manager, AttachmentStatus, Attachment
from app.vision import get_vision_service

nodes = {
    "orchestrator": orchestrator_node,
    "researcher": researcher_node,
    "executor": executor_node,
    "validator": validator_node,
    "recovery": recovery_node
}

def classify_attachment_query(objective: str) -> str:
    """
    Classifies user intent regarding conversation attachments:
    - 'METADATA': User is asking what file/image was sent, filename, size, dimensions.
    - 'VISUAL': User is asking for visual description, scene, objects, actions, what is happening.
    - 'OTHER': General query.
    """
    obj = objective.strip().lower()

    metadata_patterns = [
        r"what (image|file|picture|photo|attachment) did i (send|upload|attach)",
        r"what (was|is) the (image|file|picture|photo|attachment) (i sent|i uploaded|i attached)",
        r"what is the (filename|file name|name of the (file|image|photo|picture))",
        r"what('?s| is) (the )?(filename|file name)",
        r"what (file|attachment) is this",
        r"show (me )?(the )?metadata",
        r"what is the (size|filesize|mime|type|format) of",
        r"how (big|large) is the (file|image)",
        r"^what image\??$",
        r"^what file\??$"
    ]
    if any(re.search(p, obj) for p in metadata_patterns):
        return "METADATA"

    visual_patterns = [
        r"what is happening in (this|the) (image|picture|photo)",
        r"what('?s| is) happening in (this|the) (image|picture|photo)",
        r"what is (this|the) (image|picture|photo) (about|showing)",
        r"what does (this|the) (image|picture|photo) (show|contain|look like)",
        r"describe (this|the) (image|picture|photo)",
        r"what (do you see|can you see|is visible|is in) (in|on) (this|the) (image|picture|photo)",
        r"what (is|are) in (this|the) (image|picture|photo)",
        r"who is in (this|the) (image|picture|photo)",
        r"what does (this|the) (image|picture|photo) (show|contain|look like)",
        r"analyze (this|the) (image|picture|photo)",
        r"explain (this|the) (image|picture|photo)",
        r"tell me about (this|the) (image|picture|photo)",
        r"inspect (this|the) (image|picture|photo)",
        r"what text is in (this|the) (image|picture|photo)",
        r"read (the )?text in (this|the) (image|picture|photo)",
        r"look at (this|the) (image|picture|photo)"
    ]
    if any(re.search(p, obj) for p in visual_patterns):
        return "VISUAL"

    return "OTHER"

def is_code_execution_objective(objective: str) -> bool:
    obj_lower = objective.strip().lower()
    cleaned = re.sub(r'[^\w\s\.\-]', '', obj_lower).strip()

    # Attachment / image queries must not trigger code execution DAG
    if classify_attachment_query(obj_lower) in ["METADATA", "VISUAL"]:
        return False

    image_cues = ["image", "picture", "photo", "screenshot", "attachment", "what image", "what file did i"]
    if any(q in obj_lower for q in image_cues) and not any(w in obj_lower for w in ["create", "write", "build", "script", "generate code", "run_command"]):
        return False

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
        ".js", ".json", ".csv", ".txt", ".md", "list files", "dir", "inspect runtime", "show files"
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

    # Resolve all attachments for this conversation session
    attachment_mgr = get_attachment_manager()
    session_attachments = attachment_mgr.get_attachments_for_session(conversation_id) if conversation_id else []
    if not session_attachments and attachments:
        for a_dict in attachments:
            aid = a_dict.get("attachment_id") or a_dict.get("id")
            if aid:
                a_obj = attachment_mgr.get_attachment(aid)
                if a_obj and a_obj not in session_attachments:
                    session_attachments.append(a_obj)

    # --- DYNAMIC MULTIMODAL ATTACHMENT INTENT ROUTING ---
    att_intent = classify_attachment_query(objective)
    
    if att_intent == "METADATA":
        runs_db[run_id]["type"] = "chat"
        state["mode"] = "chat"
        
        if not session_attachments:
            chat_reply = "No attachments or uploaded files were found in this conversation session."
        else:
            lines = ["Here is the metadata for your uploaded attachment(s):\n"]
            for a in session_attachments:
                dims_str = f"{a.dimensions[0]}x{a.dimensions[1]}" if a.dimensions else "N/A"
                size_str = f"{a.size} bytes ({a.size / 1024:.1f} KB)" if a.size > 0 else "0 bytes (Empty)"
                lines.append(f"- **Filename**: `{a.filename}`\n  - **MIME Type**: `{a.mime_type}`\n  - **Size**: {size_str}\n  - **Dimensions**: {dims_str}\n  - **Status**: `{a.status.value}`")
            chat_reply = "\n".join(lines)
            
        chat_thought = f"Returned metadata for {len(session_attachments)} conversation attachment(s) without invoking visual perception."
        thought_payload = {
            "node": "attachment_manager",
            "phase": "Metadata Inspection",
            "title": "Attachment Metadata",
            "thought": chat_thought,
            "model": model,
            "provider": provider,
            "timestamp": time.time()
        }
        state.setdefault("thoughts", []).append(thought_payload)
        await emit(run_id, "thought_generated", "attachment_manager", thought_payload)
        await emit(run_id, "chat_response", "assistant", {"text": chat_reply, "objective": objective})
        state["final_response"] = chat_reply
        state["status"] = "completed"
        runs_db[run_id]["status"] = "completed"
        runs_db[run_id]["state"] = state
        if workspace_id and conversation_id:
            try:
                from app.api.sandbox import save_conversation_turn
                save_conversation_turn(workspace_id, conversation_id, objective, chat_reply)
            except Exception as e:
                print(f"Error persisting chat turn: {e}")
        if on_complete:
            on_complete({"role": "user", "text": objective, "reply": chat_reply})
        await emit(run_id, "run_completed", "assistant", {"status": "completed", "type": "chat", "reply": chat_reply, "summary": chat_reply})
        return

    elif att_intent == "VISUAL":
        runs_db[run_id]["type"] = "chat"
        state["mode"] = "chat"
        
        # Check if we have image attachments
        image_attachments = [a for a in session_attachments if a.is_image or a.mime_type.startswith("image/")]
        
        if not session_attachments:
            chat_reply = "No image attachments were found in this conversation session. Please upload or attach an image to analyze."
            chat_thought = "Visual analysis requested but no attachments found in conversation. Did NOT search workspace filesystem."
        elif not image_attachments:
            non_img = session_attachments[0]
            chat_reply = f"The attached file '{non_img.filename}' is of type '{non_img.mime_type}', which is not a recognized image format. Visual inspection cannot be performed on non-image files."
            chat_thought = f"Non-image attachment provided: {non_img.filename} ({non_img.mime_type})"
        else:
            target_img = image_attachments[-1]
            
            if target_img.status == AttachmentStatus.EMPTY_FILE or target_img.size == 0:
                chat_reply = f"Cannot access image data: the attachment '{target_img.filename}' is empty (0 bytes). JARVIS cannot infer or guess what an empty image contains."
                chat_thought = f"Image attachment {target_img.filename} is 0 bytes. Refusing to guess visual content."
            elif target_img.status == AttachmentStatus.INACCESSIBLE or (not target_img.data_url and not target_img.raw_bytes):
                chat_reply = f"Cannot access image data: attachment '{target_img.filename}' has no accessible content reference."
                chat_thought = f"Image attachment {target_img.filename} content is inaccessible."
            elif target_img.status == AttachmentStatus.CORRUPTED:
                chat_reply = f"Cannot analyze image: '{target_img.filename}' contains invalid or corrupted image data."
                chat_thought = f"Image attachment {target_img.filename} is corrupted."
            else:
                # Perform actual visual analysis using VisionService
                vision_service = get_vision_service()
                res = await asyncio.to_thread(
                    vision_service.analyze_image,
                    target_img,
                    prompt=objective,
                    model=model,
                    provider=provider
                )
                if res.success:
                    chat_reply = res.description
                    chat_thought = f"Visual analysis performed using {res.model} ({res.provider}) on actual image pixels. Grounded visual description generated."
                else:
                    chat_reply = f"Visual analysis unavailable: {res.message}"
                    chat_thought = f"Visual analysis failed ({res.error_code}): {res.message}"

        thought_payload = {
            "node": "vision",
            "phase": "Visual Perception",
            "title": "Multimodal Visual Inspection",
            "thought": chat_thought,
            "model": model,
            "provider": provider,
            "timestamp": time.time()
        }
        state.setdefault("thoughts", []).append(thought_payload)
        await emit(run_id, "thought_generated", "vision", thought_payload)
        await emit(run_id, "chat_response", "assistant", {"text": chat_reply, "objective": objective})
        state["final_response"] = chat_reply
        state["status"] = "completed"
        runs_db[run_id]["status"] = "completed"
        runs_db[run_id]["state"] = state
        if workspace_id and conversation_id:
            try:
                from app.api.sandbox import save_conversation_turn
                save_conversation_turn(workspace_id, conversation_id, objective, chat_reply)
            except Exception as e:
                print(f"Error persisting chat turn: {e}")
        if on_complete:
            on_complete({"role": "user", "text": objective, "reply": chat_reply})
        await emit(run_id, "run_completed", "assistant", {"status": "completed", "type": "chat", "reply": chat_reply, "summary": chat_reply})
        return

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

        # Inject attached file contents or image metadata properly
        if session_attachments:
            system_prompt += "\n\n[User Attached Files / Input Artifacts]:\n"
            for att in session_attachments:
                if att.is_image:
                    dims_str = f"{att.dimensions[0]}x{att.dimensions[1]}" if att.dimensions else "unknown"
                    system_prompt += (
                        f"--- Image Attachment: {att.filename} ---\n"
                        f"MIME: {att.mime_type} | Size: {att.size} bytes | Dimensions: {dims_str} | Status: {att.status.value}\n"
                        f"(Note: Visual content is grounded in pixels via Vision Perception. Do not guess contents from filename.)\n---\n"
                    )
                elif att.text_content:
                    content = att.text_content[:4000]
                    system_prompt += f"--- File Attachment: {att.filename} ---\n{content}\n---\n"

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
