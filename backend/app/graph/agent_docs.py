import os
from pathlib import Path
from typing import Dict, List, Optional

DOC_NAMES = ["SOUL.md", "HEAD.md", "PLANNING.md", "TOOLS.md", "WORKFLOW.md", "TASKS.md"]

def find_docs_directory() -> Optional[Path]:
    """
    Search candidate paths for the docs/agents directory.
    """
    candidates = [
        # Relative to this file: backend/app/graph/agent_docs.py -> root/docs/agents
        Path(__file__).resolve().parent.parent.parent.parent / "docs" / "agents",
        Path.cwd() / "docs" / "agents",
        Path.cwd().parent / "docs" / "agents",
        Path(os.environ.get("WORKSPACE_ROOT", "")) / "docs" / "agents"
    ]
    for p in candidates:
        if p.exists() and p.is_dir():
            return p
    return None

def load_all_agent_docs() -> str:
    """
    Loads all agent identity, policy, and tool documentation files
    (SOUL, HEAD, PLANNING, TOOLS, WORKFLOW, TASKS).
    """
    docs_dir = find_docs_directory()
    if not docs_dir:
        return ""
    
    loaded = []
    for doc_name in DOC_NAMES:
        doc_path = docs_dir / doc_name
        if doc_path.exists():
            try:
                content = doc_path.read_text(encoding="utf-8").strip()
                loaded.append(f"=== AGENT GUIDANCE: {doc_name} ===\n{content}\n")
            except Exception as e:
                print(f"Error reading {doc_name}: {e}")
                
    return "\n".join(loaded)

def get_agent_doc(name: str) -> Optional[str]:
    """
    Loads a specific agent document by filename (e.g., 'SOUL.md').
    """
    docs_dir = find_docs_directory()
    if not docs_dir:
        return None
    doc_path = docs_dir / name
    if doc_path.exists():
        try:
            return doc_path.read_text(encoding="utf-8").strip()
        except Exception:
            return None
    return None
