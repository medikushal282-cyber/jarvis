import os
import yaml
import time
from typing import Dict, Any, Optional

class OKFManager:
    """
    Manages Open Knowledge Format (OKF) durable knowledge layers.
    Stores knowledge in structured YAML frontmatter + Markdown files.
    """
    def __init__(self, storage_dir: Optional[str] = None):
        if not storage_dir:
            app_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            storage_dir = os.path.join(os.path.dirname(app_dir), "data", "knowledge")
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)

    def _get_user_dir(self, user_id: str) -> str:
        d = os.path.join(self.storage_dir, user_id)
        os.makedirs(d, exist_ok=True)
        return d

    def _get_project_dir(self, user_id: str, project_id: str) -> str:
        d = os.path.join(self._get_user_dir(user_id), "projects", project_id)
        os.makedirs(d, exist_ok=True)
        return d

    def _read_okf_file(self, filepath: str) -> Dict[str, Any]:
        """
        Reads an OKF file and parses frontmatter and markdown body.
        Returns {"metadata": dict, "content": str}
        """
        if not os.path.exists(filepath):
            return {"metadata": {}, "content": ""}

        with open(filepath, "r", encoding="utf-8") as f:
            raw = f.read()

        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                try:
                    metadata = yaml.safe_load(parts[1]) or {}
                    content = parts[2].strip()
                    return {"metadata": metadata, "content": content}
                except yaml.YAMLError:
                    pass
        
        # Fallback if no frontmatter or parsing failed
        return {"metadata": {}, "content": raw.strip()}

    def _write_okf_file(self, filepath: str, metadata: Dict[str, Any], content: str):
        """
        Writes data to an OKF file.
        """
        metadata["last_updated"] = time.time()
        frontmatter = yaml.dump(metadata, sort_keys=False).strip()
        
        payload = f"---\n{frontmatter}\n---\n\n{content}\n"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(payload)

    def get_user_knowledge(self, user_id: str, topic: str = "preferences") -> Dict[str, Any]:
        """
        Retrieves global user knowledge.
        Example topics: 'preferences', 'goals', 'constraints'
        """
        filepath = os.path.join(self._get_user_dir(user_id), f"{topic}.md")
        return self._read_okf_file(filepath)

    def update_user_knowledge(self, user_id: str, topic: str, content: str, metadata: Optional[Dict[str, Any]] = None):
        """
        Updates global user knowledge.
        """
        filepath = os.path.join(self._get_user_dir(user_id), f"{topic}.md")
        meta = metadata or {}
        meta["topic"] = topic
        self._write_okf_file(filepath, meta, content)

    def get_project_knowledge(self, user_id: str, project_id: str, topic: str = "overview") -> Dict[str, Any]:
        """
        Retrieves project-specific knowledge.
        Example topics: 'overview', 'architecture', 'decisions'
        """
        filepath = os.path.join(self._get_project_dir(user_id, project_id), f"{topic}.md")
        return self._read_okf_file(filepath)

    def update_project_knowledge(self, user_id: str, project_id: str, topic: str, content: str, metadata: Optional[Dict[str, Any]] = None):
        """
        Updates project-specific knowledge.
        """
        filepath = os.path.join(self._get_project_dir(user_id, project_id), f"{topic}.md")
        meta = metadata or {}
        meta["topic"] = topic
        meta["project_id"] = project_id
        self._write_okf_file(filepath, meta, content)
