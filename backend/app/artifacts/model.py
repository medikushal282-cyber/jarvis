import os
import mimetypes
import uuid
from enum import Enum
from typing import Optional, Dict, Any, Tuple
from pydantic import BaseModel, Field


class ArtifactViewerType(str, Enum):
    IMAGE = "image"
    PDF = "pdf"
    MARKDOWN = "markdown"
    CODE = "code"
    CSV = "csv"
    JSON = "json"
    TEXT = "text"
    VIDEO = "video"
    UNSUPPORTED = "unsupported"


CODE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".scss", ".sql",
    ".sh", ".bash", ".ps1", ".bat", ".cmd", ".c", ".cpp", ".h", ".rs", ".go",
    ".java", ".yaml", ".yml", ".toml", ".ini", ".xml", ".dockerfile", "dockerfile"
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".ico"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".ogg", ".mov"}


def determine_viewer_type(filename: str, mime_type: str) -> ArtifactViewerType:
    fn_lower = filename.lower()
    ext = os.path.splitext(fn_lower)[1]

    if ext in IMAGE_EXTENSIONS or mime_type.startswith("image/"):
        return ArtifactViewerType.IMAGE
    if ext == ".pdf" or mime_type == "application/pdf":
        return ArtifactViewerType.PDF
    if ext == ".csv" or mime_type == "text/csv":
        return ArtifactViewerType.CSV
    if ext == ".json" or mime_type == "application/json":
        return ArtifactViewerType.JSON
    if ext in [".md", ".markdown"] or mime_type == "text/markdown":
        return ArtifactViewerType.MARKDOWN
    if ext in VIDEO_EXTENSIONS or mime_type.startswith("video/"):
        return ArtifactViewerType.VIDEO
    if ext in CODE_EXTENSIONS:
        return ArtifactViewerType.CODE
    if mime_type.startswith("text/"):
        return ArtifactViewerType.TEXT

    return ArtifactViewerType.UNSUPPORTED


class Artifact(BaseModel):
    artifact_id: str
    filename: str
    mime_type: str = "application/octet-stream"
    size: int = 0
    file_path: str
    url: str
    download_url: str
    preview_supported: bool = True
    viewer_type: ArtifactViewerType = ArtifactViewerType.UNSUPPORTED
    created_at: float = Field(default_factory=lambda: __import__("time").time())
    source_tool: Optional[str] = None
    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "size": self.size,
            "url": self.url,
            "download_url": self.download_url,
            "preview_supported": self.preview_supported,
            "viewer_type": self.viewer_type.value,
            "created_at": self.created_at,
            "source_tool": self.source_tool,
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "metadata": self.metadata
        }
