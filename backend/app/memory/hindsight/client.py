import os
import json
import time
import uuid
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class HindsightClient:
    """
    Client for interacting with the Hindsight service.
    Currently falls back to a deterministic local JSON-based store if no URL is provided.
    """
    def __init__(self, endpoint_url: Optional[str] = None, storage_dir: Optional[str] = None):
        self.endpoint_url = endpoint_url or os.environ.get("HINDSIGHT_URL")
        
        # Local mock storage fallback
        if not storage_dir:
            app_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            storage_dir = os.path.join(os.path.dirname(app_dir), "data", "hindsight_mock")
            
        self.storage_dir = storage_dir
        if not self.endpoint_url:
            os.makedirs(self.storage_dir, exist_ok=True)
            self.db_file = os.path.join(self.storage_dir, "hindsight_db.json")
            self._ensure_db()

    def _ensure_db(self):
        if not os.path.exists(self.db_file):
            with open(self.db_file, "w", encoding="utf-8") as f:
                json.dump({"experiences": []}, f)

    def _read_db(self) -> List[Dict[str, Any]]:
        try:
            with open(self.db_file, "r", encoding="utf-8") as f:
                return json.load(f).get("experiences", [])
        except Exception as e:
            logger.error(f"Failed to read Hindsight mock DB: {e}")
            return []

    def _write_db(self, experiences: List[Dict[str, Any]]):
        try:
            with open(self.db_file, "w", encoding="utf-8") as f:
                json.dump({"experiences": experiences}, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to write Hindsight mock DB: {e}")

    def store_experience(self, user_id: str, content: str, metadata: Dict[str, Any]) -> str:
        """
        Stores an experience in Hindsight.
        """
        if self.endpoint_url:
            # TODO: Implement real HTTP POST to Hindsight
            logger.info("Real Hindsight HTTP store not fully implemented, using mock.")
            
        experiences = self._read_db()
        exp_id = f"exp_{uuid.uuid4().hex[:8]}"
        
        record = {
            "id": exp_id,
            "user_id": user_id,
            "content": content,
            "metadata": metadata,
            "timestamp": time.time()
        }
        experiences.append(record)
        self._write_db(experiences)
        return exp_id

    def search(self, user_id: str, query: str, limit: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Semantically searches for relevant experiences.
        Uses basic keyword matching for the mock implementation.
        """
        if self.endpoint_url:
            # TODO: Implement real HTTP GET to Hindsight
            logger.info("Real Hindsight HTTP search not fully implemented, using mock.")

        experiences = self._read_db()
        
        # Filter by user
        user_exps = [e for e in experiences if e.get("user_id") == user_id]
        
        # Apply metadata filters if any
        if filters:
            filtered_exps = []
            for e in user_exps:
                match = True
                for k, v in filters.items():
                    if e.get("metadata", {}).get(k) != v:
                        match = False
                        break
                if match:
                    filtered_exps.append(e)
            user_exps = filtered_exps

        # Simple keyword ranking (mocking semantic search)
        query_words = set(query.lower().split())
        scored = []
        for e in user_exps:
            content_lower = e.get("content", "").lower()
            content_words = set(content_lower.split())
            
            # 1. Exact word overlap
            score = len(query_words.intersection(content_words))
            
            # 2. Substring overlap (more forgiving for mock semantic search)
            for qw in query_words:
                if len(qw) > 3 and qw in content_lower:
                    score += 1
            
            # Boost score if objective matches slightly
            if "objective" in e.get("metadata", {}):
                obj_lower = e["metadata"]["objective"].lower()
                obj_words = set(obj_lower.split())
                score += len(query_words.intersection(obj_words)) * 2
                for qw in query_words:
                    if len(qw) > 3 and qw in obj_lower:
                        score += 2

            if score > 0 or not query:
                scored.append((score, e))

        # Sort by score descending, then timestamp descending
        scored.sort(key=lambda x: (x[0], x[1]["timestamp"]), reverse=True)
        
        # Return top N
        return [item[1] for item in scored[:limit]]
