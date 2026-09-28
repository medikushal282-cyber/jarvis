from typing import Dict, Any, Optional
from .hindsight.adapter import HindsightAdapter
from .okf.manager import OKFManager

class ContextBuilder:
    """
    Constructs the contextual memory package for JARVIS before execution.
    """
    def __init__(self, hindsight: Optional[HindsightAdapter] = None, okf: Optional[OKFManager] = None):
        self.hindsight = hindsight or HindsightAdapter()
        self.okf = okf or OKFManager()

    def build_context(
        self,
        user_id: str,
        objective: str,
        project_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Retrieves relevant experiences, observations, and structured knowledge.
        Returns a dictionary that the agent orchestration can inject into the prompt.
        """
        # 1. Get structured knowledge (OKF)
        user_prefs = self.okf.get_user_knowledge(user_id, "preferences").get("content", "")
        project_knowledge = ""
        if project_id:
            project_knowledge = self.okf.get_project_knowledge(user_id, project_id, "overview").get("content", "")

        # 2. Semantic search in Hindsight for this specific objective
        experiences = self.hindsight.recall_relevant_experiences(
            user_id=user_id,
            objective=objective,
            project_id=project_id,
            limit=3
        )
        
        observations = self.hindsight.recall_observations(
            user_id=user_id,
            objective=objective,
            project_id=project_id,
            limit=3
        )

        return {
            "user_preferences": user_prefs,
            "project_knowledge": project_knowledge,
            "relevant_experiences": [e.get("content") for e in experiences if e.get("content")],
            "relevant_observations": [o.get("content") for o in observations if o.get("content")]
        }
