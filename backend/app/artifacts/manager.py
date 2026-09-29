import os
import uuid
import time
import mimetypes
import logging
from typing import Dict, Any, List, Optional
from app.artifacts.model import Artifact, ArtifactViewerType, determine_viewer_type

logger = logging.getLogger(__name__)


def get_default_artifacts_dir() -> str:
    """Returns directory path where generated artifacts are stored."""
    base = os.environ.get("JARVIS_ARTIFACTS_ROOT")
    if not base:
        base = os.path.join(os.getcwd(), "artifacts")
    os.makedirs(base, exist_ok=True)
    return os.path.abspath(base)


class ArtifactManager:
    """
    Central manager for verified user-facing artifacts (screenshots, PDFs, CSVs, markdown, code, etc.).
    Verifies that files actually exist on disk before registration.
    """

    def __init__(self):
        self._artifacts: Dict[str, Artifact] = {}
        self._session_artifacts: Dict[str, List[str]] = {}

    def register_artifact(
        self,
        file_path: str,
        filename: Optional[str] = None,
        source_tool: Optional[str] = None,
        conversation_id: Optional[str] = None,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Artifact:
        """
        Verifies and registers an artifact file.
        Raises FileNotFoundError if the file does not exist on disk.
        """
        abs_path = os.path.abspath(file_path)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"Artifact file not found at '{file_path}'. Cannot register unverified artifact.")

        file_size = os.path.getsize(abs_path)
        if file_size == 0:
            logger.warning(f"Artifact file '{file_path}' is 0 bytes.")

        resolved_filename = filename or os.path.basename(abs_path)
        mime_type, _ = mimetypes.guess_type(resolved_filename)
        if not mime_type:
            mime_type = "application/octet-stream"

        viewer_type = determine_viewer_type(resolved_filename, mime_type)
        preview_supported = viewer_type != ArtifactViewerType.UNSUPPORTED

        artifact_id = f"art_{uuid.uuid4().hex[:10]}"
        content_url = f"/api/artifacts/{artifact_id}/content"
        download_url = f"/api/artifacts/{artifact_id}/download"

        meta = metadata or {}
        # If image, extract dimensions if pillow available
        if viewer_type == ArtifactViewerType.IMAGE:
            try:
                from PIL import Image
                with Image.open(abs_path) as img:
                    meta["width"], meta["height"] = img.size
            except Exception:
                pass

        artifact = Artifact(
            artifact_id=artifact_id,
            filename=resolved_filename,
            mime_type=mime_type,
            size=file_size,
            file_path=abs_path,
            url=content_url,
            download_url=download_url,
            preview_supported=preview_supported,
            viewer_type=viewer_type,
            created_at=time.time(),
            source_tool=source_tool,
            session_id=session_id,
            conversation_id=conversation_id,
            metadata=meta
        )

        self._artifacts[artifact_id] = artifact

        if conversation_id:
            if conversation_id not in self._session_artifacts:
                self._session_artifacts[conversation_id] = []
            self._session_artifacts[conversation_id].append(artifact_id)

        logger.info(f"Registered verified artifact: {artifact_id} ({resolved_filename}, {file_size} bytes, type={viewer_type.value})")
        return artifact

    def get_artifact(self, artifact_id: str) -> Optional[Artifact]:
        return self._artifacts.get(artifact_id)

    def list_artifacts(self, conversation_id: Optional[str] = None) -> List[Artifact]:
        if conversation_id:
            ids = self._session_artifacts.get(conversation_id, [])
            return [self._artifacts[aid] for aid in ids if aid in self._artifacts]
        return list(self._artifacts.values())

    def clear(self, conversation_id: Optional[str] = None):
        if conversation_id:
            ids = self._session_artifacts.pop(conversation_id, [])
            for aid in ids:
                self._artifacts.pop(aid, None)
        else:
            self._artifacts.clear()
            self._session_artifacts.clear()


# Global singleton instance
_artifact_manager = ArtifactManager()


def get_artifact_manager() -> ArtifactManager:
    return _artifact_manager
