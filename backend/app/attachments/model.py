import base64
import mimetypes
from enum import Enum
from typing import Optional, Dict, Any, Tuple
from pydantic import BaseModel, Field


class AttachmentStatus(str, Enum):
    READY = "READY"
    EMPTY_FILE = "EMPTY_FILE"
    INACCESSIBLE = "INACCESSIBLE"
    CORRUPTED = "CORRUPTED"
    NON_IMAGE = "NON_IMAGE"
    FAILED = "FAILED"


IMAGE_MIME_PREFIXES = ("image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp", "image/tiff", "image/svg+xml")


class Attachment(BaseModel):
    attachment_id: str
    filename: str
    mime_type: str = "application/octet-stream"
    size: int = 0
    source: str = "upload"
    data_url: Optional[str] = None
    raw_bytes: Optional[bytes] = None
    text_content: Optional[str] = None
    status: AttachmentStatus = AttachmentStatus.READY
    dimensions: Optional[Tuple[int, int]] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        arbitrary_types_allowed = True

    @property
    def is_image(self) -> bool:
        if self.status in [AttachmentStatus.EMPTY_FILE, AttachmentStatus.INACCESSIBLE, AttachmentStatus.NON_IMAGE]:
            return False
        return any(self.mime_type.lower().startswith(p) for p in IMAGE_MIME_PREFIXES)

    def get_base64_data_url(self) -> Optional[str]:
        if self.data_url:
            return self.data_url
        if self.raw_bytes:
            b64 = base64.b64encode(self.raw_bytes).decode("utf-8")
            return f"data:{self.mime_type};base64,{b64}"
        return None

    def get_metadata(self) -> Dict[str, Any]:
        """Returns file metadata ONLY without visual interpretations."""
        return {
            "attachment_id": self.attachment_id,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "size": self.size,
            "is_image": self.is_image,
            "dimensions": list(self.dimensions) if self.dimensions else None,
            "status": self.status.value,
            "source": self.source,
            "error_message": self.error_message
        }
