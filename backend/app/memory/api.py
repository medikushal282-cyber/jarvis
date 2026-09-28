from typing import Dict, Any, Optional

from .context_builder import ContextBuilder
from .extractor import MemoryExtractor
from .hindsight.adapter import HindsightAdapter
from .okf.manager import OKFManager

# Singletons for the subsystem
_hindsight_adapter = HindsightAdapter()
_okf_manager = OKFManager()
_context_builder = ContextBuilder(hindsight=_hindsight_adapter, okf=_okf_manager)
_extractor = MemoryExtractor()

def build_context(
    user_id: str,
    objective: str,
    project_id: Optional[str] = None,
    session_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Builds a contextual memory package for JARVIS prior to execution.
    """
    return _context_builder.build_context(
        user_id=user_id,
        objective=objective,
        project_id=project_id,
        session_id=session_id
    )

def record_experience(
    user_id: str,
    objective: str,
    execution_state: Dict[str, Any],
    project_id: Optional[str] = None,
    session_id: Optional[str] = None
) -> str:
    """
    Extracts and records experiential memory from a completed execution state.
    """
    summary = _extractor.extract_experience(objective, execution_state)
    status = execution_state.get("status", "unknown")
    error = execution_state.get("error")
    
    return _hindsight_adapter.record_execution_experience(
        user_id=user_id,
        objective=objective,
        summary=summary,
        status=status,
        project_id=project_id,
        session_id=session_id,
        error_msg=error
    )

def record_observation(
    user_id: str,
    observation: str,
    source_experience_id: Optional[str] = None,
    project_id: Optional[str] = None
) -> str:
    """
    Records a derived observation (e.g. from repeated failures/patterns).
    """
    return _hindsight_adapter.record_observation(
        user_id=user_id,
        observation=observation,
        source_experience_id=source_experience_id,
        project_id=project_id
    )

def get_user_knowledge(user_id: str, topic: str = "preferences") -> Dict[str, Any]:
    """
    Retrieves durable, structured user knowledge (OKF).
    """
    return _okf_manager.get_user_knowledge(user_id, topic)

def update_user_knowledge(user_id: str, topic: str, content: str, metadata: Optional[Dict[str, Any]] = None):
    """
    Updates structured user knowledge (OKF).
    """
    _okf_manager.update_user_knowledge(user_id, topic, content, metadata)

def get_project_knowledge(user_id: str, project_id: str, topic: str = "overview") -> Dict[str, Any]:
    """
    Retrieves durable, structured project knowledge (OKF).
    """
    return _okf_manager.get_project_knowledge(user_id, project_id, topic)

def update_project_knowledge(user_id: str, project_id: str, topic: str, content: str, metadata: Optional[Dict[str, Any]] = None):
    """
    Updates structured project knowledge (OKF).
    """
    _okf_manager.update_project_knowledge(user_id, project_id, topic, content, metadata)
