import os
import logging
from typing import Dict, Any, Optional
from .hindsight.adapter import HindsightAdapter
from .okf.manager import OKFManager

logger = logging.getLogger(__name__)

class ContextBuilder:
    """
    Constructs the contextual memory package for JARVIS before execution,
    respecting a strict token budget and providing graceful degradation.
    """
    def __init__(self, hindsight: Optional[HindsightAdapter] = None, okf: Optional[OKFManager] = None):
        self.hindsight = hindsight or HindsightAdapter()
        self.okf = okf or OKFManager()

    def build_context(
        self,
        user_id: str,
        objective: str,
        project_id: Optional[str] = None,
        session_id: Optional[str] = None,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Retrieves relevant experiences, observations, and structured knowledge.
        Returns a dictionary that the agent orchestration can inject into the prompt.
        """
        if max_tokens is None:
            max_tokens = int(os.environ.get("JARVIS_MEMORY_CONTEXT_TOKENS", "2000"))
        
        # Approximate budget using 4 chars per token
        max_chars = max_tokens * 4
        current_chars = 0
        
        context_payload = {
            "user_preferences": "",
            "project_knowledge": "",
            "relevant_observations": [],
            "relevant_experiences": []
        }

        # 1. Get structured knowledge (OKF) - Highest Priority
        try:
            user_prefs = self.okf.get_user_knowledge(user_id, "preferences").get("content", "")
            if user_prefs:
                if current_chars + len(user_prefs) <= max_chars:
                    context_payload["user_preferences"] = user_prefs
                    current_chars += len(user_prefs)
                else:
                    context_payload["user_preferences"] = user_prefs[:max_chars - current_chars] + "...[TRUNCATED]"
                    return context_payload
        except Exception as e:
            logger.warning(f"Failed to retrieve user OKF knowledge: {e}")

        if project_id:
            try:
                project_knowledge = self.okf.get_project_knowledge(user_id, project_id, "overview").get("content", "")
                if project_knowledge:
                    if current_chars + len(project_knowledge) <= max_chars:
                        context_payload["project_knowledge"] = project_knowledge
                        current_chars += len(project_knowledge)
                    else:
                        context_payload["project_knowledge"] = project_knowledge[:max_chars - current_chars] + "...[TRUNCATED]"
                        return context_payload
            except Exception as e:
                logger.warning(f"Failed to retrieve project OKF knowledge: {e}")

        # 2. Get Observations - Second Priority
        try:
            observations = self.hindsight.recall_observations(
                user_id=user_id,
                objective=objective,
                project_id=project_id,
                limit=5
            )
            for obs in observations:
                content = obs.get("content")
                if not content:
                    continue
                if current_chars + len(content) <= max_chars:
                    context_payload["relevant_observations"].append(content)
                    current_chars += len(content)
                else:
                    # Budget full, stop adding
                    break
        except Exception as e:
            logger.warning(f"Failed to retrieve observations: {e}")

        # 3. Get Experiences - Third Priority
        try:
            experiences = self.hindsight.recall_relevant_experiences(
                user_id=user_id,
                objective=objective,
                project_id=project_id,
                limit=5
            )
            for exp in experiences:
                content = exp.get("content")
                if not content:
                    continue
                # We can prepend status for context if it exists
                status = exp.get("metadata", {}).get("status")
                if status:
                    content = f"[{status.upper()}] {content}"
                if current_chars + len(content) <= max_chars:
                    context_payload["relevant_experiences"].append(content)
                    current_chars += len(content)
                else:
                    break
        except Exception as e:
            logger.warning(f"Failed to retrieve experiences: {e}")

        return context_payload
