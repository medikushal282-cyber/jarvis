"""Dynamic prompt assembly for the JARVIS autonomous agent.

Constructs compact, context-aware system and user prompts optimized for
high token efficiency (preserving the 8,000 token Groq context limit).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


SYSTEM_PROMPT_TEMPLATE = """You are JARVIS, an autonomous AI computer agent and software engineer.
You accomplish complex goals by inspecting the environment, reasoning, selecting tools, evaluating results, and self-correcting when errors occur.

### Operating Guidelines:
1. **Autonomous Execution**: Solve the user's objective end-to-end. Do not give up on failures—diagnose error output/stderr, adapt your strategy, and retry.
2. **Tool Discipline**: Use the provided tools to interact with the workspace, run commands, create/modify files, make web requests, and inspect artifacts.
3. **Artifact Production**: When creating web pages or code, ensure all referenced dependencies (CSS, JS, data files) exist and are tested.
4. **Verifiable Completion**: When the task is complete, verify the final outcome and summarize your actions concisely.

### Environment Context:
- Workspace Root: {workspace_root}
- Python Interpreter: {python_info}
{context_memory_section}
{hindsight_section}
{attachments_section}

### Response Protocol:
Before taking actions, you may include your strategic reasoning inside <thought>...</thought> tags.
When calling a tool, provide a valid tool call matching the provided JSON schema.
When your objective is completely finished, provide your final response to the user with a concise summary of what was accomplished.
"""


def build_system_prompt(
    workspace_root: str = ".",
    python_info: str = "Python 3.x",
    context_memory: str = "",
    hindsight_memories: Optional[List[Dict[str, Any]]] = None,
    user_knowledge: str = "",
    attachments: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Build a compact, token-efficient system prompt."""
    context_memory_section = ""
    if context_memory and context_memory.strip():
        context_memory_section = f"\n### Session Context Memory:\n{context_memory.strip()}\n"

    hindsight_section = ""
    memory_parts = []
    if user_knowledge and user_knowledge.strip():
        memory_parts.append(f"User Preferences: {user_knowledge.strip()}")
    if hindsight_memories:
        for m in hindsight_memories[:3]:
            title = m.get("title") or m.get("objective") or "Experience"
            summary = m.get("outcome", {}).get("summary") or m.get("summary") or ""
            if summary:
                memory_parts.append(f"- {title}: {summary}")
    if memory_parts:
        hindsight_section = "\n### Learned Knowledge & Experiences:\n" + "\n".join(memory_parts) + "\n"

    attachments_section = ""
    if attachments:
        att_lines = []
        for att in attachments:
            name = att.get("name", "attachment")
            size = att.get("size", 0)
            mime = att.get("type", "unknown")
            data_url = att.get("data_url")
            content = att.get("content")
            if data_url:
                att_lines.append(f"- Image Attachment: `{name}` ({mime}, {size} bytes, multimodal visual data attached)")
            elif content:
                snippet = content[:500].replace("\n", " ")
                att_lines.append(f"- File Attachment `{name}` ({mime}): {snippet}...")
            else:
                att_lines.append(f"- Attachment `{name}` ({mime}, {size} bytes)")
        if att_lines:
            attachments_section = "\n### Attached User Assets:\n" + "\n".join(att_lines) + "\n"

    return SYSTEM_PROMPT_TEMPLATE.format(
        workspace_root=workspace_root or ".",
        python_info=python_info or "Python 3.x",
        context_memory_section=context_memory_section,
        hindsight_section=hindsight_section,
        attachments_section=attachments_section,
    ).strip()


def build_user_prompt(
    objective: str,
    conversation_turns: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Constructs user prompt with recent turns compact transcript."""
    if not conversation_turns:
        return f"Objective: {objective}"

    compact_turns = []
    for turn in conversation_turns[-4:]:
        role = turn.get("role", "user").upper()
        content = (turn.get("content") or "")[:300].replace("\n", " ")
        compact_turns.append(f"[{role}]: {content}")

    history_str = "\n".join(compact_turns)
    return f"Recent Conversation:\n{history_str}\n\nCurrent Objective: {objective}"
