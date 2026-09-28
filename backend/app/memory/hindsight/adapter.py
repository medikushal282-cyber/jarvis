from typing import List, Dict, Any, Optional
from .client import HindsightClient

class HindsightAdapter:
    """
    Adapts JARVIS concepts to Hindsight experiential memory.
    """
    def __init__(self, client: Optional[HindsightClient] = None):
        self.client = client or HindsightClient()

    def record_execution_experience(
        self,
        user_id: str,
        objective: str,
        summary: str,
        status: str,
        project_id: Optional[str] = None,
        session_id: Optional[str] = None,
        error_msg: Optional[str] = None
    ) -> str:
        """
        Records an execution summary as an experience.
        """
        content = summary
        if error_msg:
            content += f"\nEncountered Error: {error_msg}"
            
        metadata = {
            "type": "execution",
            "objective": objective,
            "status": status,
        }
        if project_id:
            metadata["project_id"] = project_id
        if session_id:
            metadata["session_id"] = session_id

        return self.client.store_experience(user_id, content, metadata)

    def record_observation(
        self,
        user_id: str,
        observation: str,
        source_experience_id: Optional[str] = None,
        project_id: Optional[str] = None
    ) -> str:
        """
        Records a derived observation (e.g. a recurring pattern).
        """
        metadata = {
            "type": "observation",
        }
        if source_experience_id:
            metadata["source_experience_id"] = source_experience_id
        if project_id:
            metadata["project_id"] = project_id

        return self.client.store_experience(user_id, observation, metadata)

    def recall_relevant_experiences(
        self,
        user_id: str,
        objective: str,
        project_id: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Retrieves past relevant experiences.
        """
        filters = {"type": "execution"}
        if project_id:
            filters["project_id"] = project_id

        return self.client.search(user_id, objective, limit=limit, filters=filters)

    def recall_observations(
        self,
        user_id: str,
        objective: str,
        project_id: Optional[str] = None,
        limit: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Retrieves relevant observations.
        """
        filters = {"type": "observation"}
        if project_id:
            filters["project_id"] = project_id

        return self.client.search(user_id, objective, limit=limit, filters=filters)
