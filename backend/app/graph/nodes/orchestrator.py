import re
import json
import time
import asyncio
from pathlib import Path
from typing import List, Dict, Any

from app.events import emit
from app.llm.router import call_llm
from app.workspace.manager import get_workspace_manager
from app.graph.agent_docs import load_all_agent_docs

def load_agent_docs() -> str:
    return load_all_agent_docs()

def clean_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()

def determine_target_filename(objective: str, context: List[dict] = None) -> str:
    m = re.search(r'\b([a-zA-Z0-9_\-]+\.py)\b', objective, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    
    obj_lower = objective.lower()
    if "factorial" in obj_lower:
        return "factorial.py"
    if "fibonacci" in obj_lower:
        return "fibonacci.py"
    if "csv" in obj_lower and "json" in obj_lower:
        return "csv_to_json.py"

    if context:
        for turn in reversed(context):
            for art in turn.get("artifacts", []):
                p = art.get("path")
                if p and p.endswith(".py"):
                    return p
                    
    return "main.py"

def build_dynamic_fallback_plan(objective: str, existing_files: List[str], context: List[dict] = None) -> List[Dict[str, Any]]:
    obj_lower = objective.lower()
    steps = []

    steps.append({
        "id": "step_1",
        "description": "Inspect workspace directory to discover existing files and inputs.",
        "agent": "executor",
        "action": "LIST_DIRECTORY",
        "target": ".",
        "arguments": {"path": "."},
        "depends_on": [],
        "status": "pending",
        "reason": "Verify input files before proceeding with plan execution."
    })

    prev_step_id = "step_1"

    py_files = list(set(re.findall(r'\b([a-zA-Z0-9_\-]+\.py)\b', objective, re.IGNORECASE)))
    csv_files = list(set(re.findall(r'\b([a-zA-Z0-9_\-]+\.csv)\b', objective, re.IGNORECASE)))
    txt_files = list(set(re.findall(r'\b([a-zA-Z0-9_\-]+\.txt)\b', objective, re.IGNORECASE)))
    json_files = list(set(re.findall(r'\b([a-zA-Z0-9_\-]+\.json)\b', objective, re.IGNORECASE)))
    html_files = list(set(re.findall(r'\b([a-zA-Z0-9_\-]+\.html)\b', objective, re.IGNORECASE)))
    css_files = list(set(re.findall(r'\b([a-zA-Z0-9_\-]+\.css)\b', objective, re.IGNORECASE)))
    md_files = list(set(re.findall(r'\b([a-zA-Z0-9_\-]+\.md)\b', objective, re.IGNORECASE)))
    has_readme = bool(md_files) or "readme" in obj_lower
    readme_target = md_files[0] if md_files else "README.md"

    main_script = py_files[0] if py_files else determine_target_filename(objective, context)

    # Web static project (HTML/CSS) handling or website objective
    is_web_task = bool(html_files or css_files) or any(w in obj_lower for w in ["website", "landing page", "web page", "web app", "html", "browser", "frontend"])
    if is_web_task:
        if not html_files:
            html_files = ["index.html"]
        for html_f in html_files:
            step_id = f"step_{len(steps) + 1}"
            steps.append({
                "id": step_id,
                "description": f"Create modern HTML artifact '{html_f}'.",
                "agent": "executor",
                "action": "CREATE_FILE",
                "target": html_f,
                "arguments": {"path": html_f},
                "depends_on": [prev_step_id],
                "status": "pending",
                "reason": f"Author {html_f} structure."
            })
            prev_step_id = step_id

        for css_f in css_files:
            step_id = f"step_{len(steps) + 1}"
            steps.append({
                "id": step_id,
                "description": f"Create CSS stylesheet '{css_f}'.",
                "agent": "executor",
                "action": "CREATE_FILE",
                "target": css_f,
                "arguments": {"path": css_f},
                "depends_on": [prev_step_id],
                "status": "pending",
                "reason": f"Author {css_f} styles."
            })
            prev_step_id = step_id

        for html_f in html_files:
            step_id = f"step_{len(steps) + 1}"
            steps.append({
                "id": step_id,
                "description": f"Read and inspect HTML artifact '{html_f}'.",
                "agent": "executor",
                "action": "READ_FILE",
                "target": html_f,
                "arguments": {"path": html_f},
                "depends_on": [prev_step_id],
                "status": "pending",
                "reason": f"Inspect {html_f}."
            })
            prev_step_id = step_id

        # Agentic browser opening step
        primary_html = html_files[0]
        step_id = f"step_{len(steps) + 1}"
        steps.append({
            "id": step_id,
            "description": f"Open '{primary_html}' in browser tab and activate live preview.",
            "agent": "executor",
            "action": "OPEN_BROWSER",
            "target": primary_html,
            "arguments": {"path": primary_html},
            "depends_on": [prev_step_id],
            "status": "pending",
            "reason": f"Launch browser tab to inspect live rendering of {primary_html}."
        })
        return steps

    # Delete operation
    if "delete" in obj_lower or "remove" in obj_lower:
        steps.append({
            "id": "step_2",
            "description": f"Delete target file '{main_script}'.",
            "agent": "executor",
            "action": "DELETE_FILE",
            "target": main_script,
            "arguments": {"path": main_script},
            "depends_on": ["step_1"],
            "status": "pending",
            "reason": "Perform safe file deletion."
        })
        return steps

    # Read / show operation
    if ("show" in obj_lower or "read" in obj_lower or "view" in obj_lower) and not ("create" in obj_lower or "modify" in obj_lower or "update" in obj_lower):
        target_read = main_script if main_script != "main.py" else (csv_files[0] if csv_files else "main.py")
        steps.append({
            "id": "step_2",
            "description": f"Read and inspect file '{target_read}'.",
            "agent": "executor",
            "action": "READ_FILE",
            "target": target_read,
            "arguments": {"path": target_read},
            "depends_on": ["step_1"],
            "status": "pending",
            "reason": "Inspect file content."
        })
        return steps

    # Input data files
    input_files = csv_files + txt_files
    for inp in input_files:
        step_id = f"step_{len(steps) + 1}"
        steps.append({
            "id": step_id,
            "description": f"Verify or create input file '{inp}' in workspace.",
            "agent": "executor",
            "action": "CREATE_FILE",
            "target": inp,
            "arguments": {"path": inp},
            "depends_on": [prev_step_id],
            "status": "pending",
            "reason": f"Ensure input file {inp} exists for processing."
        })
        prev_step_id = step_id

    has_update = any(k in obj_lower for k in ["update that same file", "modify that same file", "then modify", "then update", "update script", "modify script", "update it", "modify it", "update this", "modify this", "update that", "modify that"]) or (obj_lower.startswith("update ") and "csv" not in obj_lower) or (obj_lower.startswith("modify ") and "csv" not in obj_lower)
    has_create = any(k in obj_lower for k in ["create", "make", "author"]) or (not has_update and not (re.search(r'\b(it|this|that)\b', obj_lower) or context))

    if has_create:
        script_step_id = f"step_{len(steps) + 1}"
        steps.append({
            "id": script_step_id,
            "description": f"Author target Python script '{main_script}'.",
            "agent": "executor",
            "action": "CREATE_FILE",
            "target": main_script,
            "arguments": {"path": main_script},
            "depends_on": [prev_step_id],
            "status": "pending",
            "reason": f"Create {main_script} implementation."
        })
        prev_step_id = script_step_id

        run_step_id = f"step_{len(steps) + 1}"
        steps.append({
            "id": run_step_id,
            "description": f"Execute Python script '{main_script}'.",
            "agent": "executor",
            "action": "RUN_COMMAND",
            "target": main_script,
            "arguments": {"command": f"python {main_script}"},
            "depends_on": [script_step_id],
            "status": "pending",
            "reason": f"Run {main_script}."
        })
        prev_step_id = run_step_id


    if has_update:
        upd_step_id = f"step_{len(steps) + 1}"
        steps.append({
            "id": upd_step_id,
            "description": f"Update target script '{main_script}' with new requirements.",
            "agent": "executor",
            "action": "UPDATE_FILE",
            "target": main_script,
            "arguments": {"path": main_script},
            "depends_on": [prev_step_id],
            "status": "pending",
            "reason": f"Modify {main_script} implementation."
        })
        prev_step_id = upd_step_id

        run_upd_id = f"step_{len(steps) + 1}"
        steps.append({
            "id": run_upd_id,
            "description": f"Execute updated Python script '{main_script}'.",
            "agent": "executor",
            "action": "RUN_COMMAND",
            "target": main_script,
            "arguments": {"command": f"python {main_script}"},
            "depends_on": [upd_step_id],
            "status": "pending",
            "reason": f"Run updated {main_script}."
        })
        prev_step_id = run_upd_id

    if has_readme:
        readme_step_id = f"step_{len(steps) + 1}"
        steps.append({
            "id": readme_step_id,
            "description": f"Create {readme_target} documenting project implementation and usage.",
            "agent": "executor",
            "action": "CREATE_FILE",
            "target": readme_target,
            "arguments": {"path": readme_target},
            "depends_on": [prev_step_id],
            "status": "pending",
            "reason": f"Provide complete project documentation in {readme_target}."
        })
        prev_step_id = readme_step_id

    for jf in json_files:
        val_step_id = f"step_{len(steps) + 1}"
        steps.append({
            "id": val_step_id,
            "description": f"Inspect generated output JSON file '{jf}'.",
            "agent": "executor",
            "action": "READ_FILE",
            "target": jf,
            "arguments": {"path": jf},
            "depends_on": [prev_step_id],
            "status": "pending",
            "reason": f"Verify output file {jf} content."
        })
        prev_step_id = val_step_id

    return steps

async def orchestrator_node(state: dict) -> dict:
    await emit(state["run_id"], "agent_thinking", "orchestrator", {"summary": "Analyzing objective and building action-oriented execution plan."})

    objective = state["objective"]
    context = state.get("conversation_context", [])
    ws = get_workspace_manager()

    dir_info = ws.list_directory(".")
    existing_files = [e["name"] for e in dir_info.get("entries", []) if not e.get("is_directory")]

    research_findings = state.get("research", [])
    research_summary = ""
    if research_findings:
        accepted = [r for r in research_findings if r.get("status") == "accepted"]
        if accepted:
            research_summary = "\nAccepted Knowledge Base Findings:\n" + json.dumps(accepted, indent=2)

    context_summary = ""
    session_memory = state.get("session_context_summary", "")
    if session_memory:
        context_summary += f"\n[Session Context Memory]: {session_memory}\n"
    if context:
        compact_turns = []
        for t in context[-3:]:
            role = t.get("role", "turn")
            text = t.get("content", t.get("objective", t.get("text", "")))[:250].replace("\n", " ")
            compact_turns.append(f"- {role}: {text}")
        context_summary += "\n[Recent Turns]:\n" + "\n".join(compact_turns) + "\n"

    # Inject user-attached file contents
    attachments_context = ""
    attachments = state.get("attachments", [])
    if attachments:
        attachments_context = "\n[User Attached Files]:\n"
        for att in attachments:
            name = att.get("name", "unknown")
            content = att.get("content", "")[:4000]
            attachments_context += f"--- {name} ---\n{content}\n---\n"

    agent_docs = load_agent_docs()

    system_prompt = f"""You are Fraiday's Dynamic Action Orchestrator.
Decompose the user's objective into a structured, dependency-aware plan of execution steps.

Available Controlled Actions:
- LIST_DIRECTORY: Inspect workspace files (arguments: {{"path": "."}})
- READ_FILE: Inspect existing file content (arguments: {{"path": "<filename>"}})
- CREATE_FILE: Author a new source code or configuration file (arguments: {{"path": "<filename>"}})
- UPDATE_FILE: Update an existing file (arguments: {{"path": "<filename>"}})
- DELETE_FILE: Remove a file subject to safety policy (arguments: {{"path": "<filename>"}})
- RUN_COMMAND: Execute safe command in workspace (arguments: {{"command": "<cmd>"}})
- OPEN_BROWSER: Launch website or file in browser tab for live preview (arguments: {{"path": "<filename>"}})
- INSPECT_RUNTIME: Inspect available Python runtimes

Existing Workspace Files: {json.dumps(existing_files)}
{research_summary}
{context_summary}
{attachments_context}

[Agent Documentation / Operating Manual]
{agent_docs}

Rules:
1. Every step MUST include: id, description, agent ("executor"), action, target, arguments, depends_on (list of step ids), status ("pending").
2. Ensure steps reflect true dependencies (e.g. creating input data before running script).
3. If creating HTML/web artifacts, include an OPEN_BROWSER step to preview the site.
4. You may include reasoning inside <thought>...</thought> tags, followed by the JSON object with this schema:
{{
  "steps": [
    {{
      "id": "step_1",
      "description": "...",
      "agent": "executor",
      "action": "LIST_DIRECTORY" | "READ_FILE" | "CREATE_FILE" | "UPDATE_FILE" | "DELETE_FILE" | "RUN_COMMAND" | "OPEN_BROWSER",
      "target": "<filename>",
      "arguments": {{...}},
      "depends_on": [],
      "status": "pending",
      "reason": "..."
    }}
  ]
}}"""

    user_prompt = f"Objective: {objective}"

    selected_model = state.get("model", "qwen/qwen3.8-27b")
    selected_provider = state.get("provider", "groq")

    plan_data = None
    extracted_thought = None
    try:
        response, extracted_thought = await asyncio.to_thread(
            call_llm,
            system_prompt,
            user_prompt,
            model=selected_model,
            provider=selected_provider
        )
        plan_data = json.loads(clean_json(response))
    except Exception:
        plan_data = None

    steps = []
    if plan_data and isinstance(plan_data, dict) and "steps" in plan_data:
        raw_steps = plan_data.get("steps", [])
        for i, s in enumerate(raw_steps):
            steps.append({
                "id": s.get("id", f"step_{i+1}"),
                "description": s.get("description", "Execute action step"),
                "agent": s.get("agent", "executor"),
                "action": s.get("action", "RUN_COMMAND"),
                "target": s.get("target", "main.py"),
                "arguments": s.get("arguments", {}),
                "depends_on": s.get("depends_on", []),
                "status": "pending",
                "reason": s.get("reason", "Objective requirement execution"),
                "result": None
            })
        # Sanitize depends_on to only include IDs of previous steps that exist in this plan
        valid_ids = set()
        for s in steps:
            s["depends_on"] = [dep for dep in s.get("depends_on", []) if dep in valid_ids]
            valid_ids.add(s["id"])

    if not steps:
        steps = build_dynamic_fallback_plan(objective, existing_files, context)

    # Format Antigravity-Style Thoughts
    target_files = [s.get("target") for s in steps if s.get("target") and s.get("target") != "."]
    actions = [s.get("action") for s in steps]
    
    thought_content = extracted_thought or (
        f"### 1. Objective Deconstruction & Context Understanding\n"
        f"- **Primary Goal**: `{objective}`\n"
        f"- **Engine**: `{selected_model}` via `{selected_provider.upper()}`\n"
        f"- **Discovered Workspace Assets**: {len(existing_files)} files in working directory.\n\n"
        f"### 2. Cognitive Strategy & Action Plan\n"
        f"- Sequenced **{len(steps)} operational stages**: {' -> '.join(actions)}.\n"
        f"- Target Artifacts: {', '.join(f'`{f}`' for f in target_files) if target_files else 'Workspace Root'}.\n"
        f"{'- Live Browser Integration: Configured `OPEN_BROWSER` action for live web preview.' if 'OPEN_BROWSER' in actions else '- Standard process and file CRUD execution pipeline.'}\n\n"
        f"### 3. Tool Policy & Self-Correction Hypotheses\n"
        f"- Sandboxed execution with non-destructive verification.\n"
        f"- Automated exit code and output matching via Validator agent."
    )

    thought_payload = {
        "node": "orchestrator",
        "phase": "Planning & Strategic Reasoning",
        "title": "Autonomous Strategy & Plan Formulation",
        "thought": thought_content,
        "model": selected_model,
        "provider": selected_provider,
        "timestamp": time.time()
    }
    state.setdefault("thoughts", []).append(thought_payload)
    await emit(state["run_id"], "thought_generated", "orchestrator", thought_payload)

    state["plan"] = steps
    await emit(state["run_id"], "plan_created", "orchestrator", {"steps": steps})

    state["current_step"] = "researcher"
    return state
