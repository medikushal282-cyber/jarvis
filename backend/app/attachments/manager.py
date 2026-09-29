import os
import uuid
import base64
import mimetypes
import logging
from typing import Dict, Any, List, Optional, Tuple
from app.attachments.model import Attachment, AttachmentStatus, IMAGE_MIME_PREFIXES

logger = logging.getLogger(__name__)

# Magic byte signatures for image formats
IMAGE_MAGIC_SIGNATURES = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"RIFF", "image/webp"),  # Starts with RIFF and has WEBP
]


def detect_mime_type_from_bytes(data: bytes, fallback_filename: str = "") -> str:
    """Detects MIME type using magic byte inspection first, then fallback to filename."""
    if not data:
        return "application/octet-stream"

    # 1. Magic bytes check
    for magic, mime in IMAGE_MAGIC_SIGNATURES:
        if data.startswith(magic):
            if magic == b"RIFF" and len(data) >= 12:
                if data[8:12] == b"WEBP":
                    return "image/webp"
                continue
            return mime

    # SVG check
    if data.strip().startswith(b"<svg") or b"<svg" in data[:500]:
        return "image/svg+xml"

    # 2. Extension check
    if fallback_filename:
        guessed, _ = mimetypes.guess_type(fallback_filename)
        if guessed:
            return guessed

    return "application/octet-stream"


def inspect_image_dimensions(raw_bytes: bytes) -> Optional[Tuple[int, int]]:
    """Extracts width and height of an image safely using Pillow."""
    if not raw_bytes:
        return None
    try:
        from PIL import Image
        import io
        with Image.open(io.BytesIO(raw_bytes)) as img:
            return img.size
    except Exception:
        return None


class AttachmentManager:
    """
    Central manager for user-provided attachments.
    Ensures attachments are treated as input artifacts, isolated from workspace files.
    """

    def __init__(self):
        self._attachments: Dict[str, Attachment] = {}
        self._session_attachments: Dict[str, List[str]] = {}

    def ingest_attachment(
        self,
        item: Dict[str, Any],
        source: str = "upload",
        conversation_id: Optional[str] = None
    ) -> Attachment:
        """
        Ingests and validates an attachment from raw data, base64 data URL, or text.
        """
        attachment_id = item.get("attachment_id") or item.get("id") or f"att_{uuid.uuid4().hex[:12]}"
        filename = item.get("name") or item.get("filename") or "attachment"
        declared_mime = item.get("type") or item.get("mime_type")
        raw_size = item.get("size") or 0
        
        data_url = item.get("data_url")
        content = item.get("content")
        raw_bytes = item.get("raw_bytes")

        status = AttachmentStatus.READY
        error_msg = None
        decoded_bytes: Optional[bytes] = None
        text_content: Optional[str] = None

        # 1. Parse content / data_url into decoded bytes
        if data_url and isinstance(data_url, str) and data_url.startswith("data:"):
            try:
                header, b64_data = data_url.split(",", 1)
                decoded_bytes = base64.b64decode(b64_data)
                # Extract MIME from header if declared
                if ";" in header:
                    extracted_mime = header.split(";")[0].replace("data:", "").strip()
                    if extracted_mime:
                        declared_mime = extracted_mime
            except Exception as e:
                status = AttachmentStatus.CORRUPTED
                error_msg = f"Failed to decode base64 data URL: {str(e)}"
        elif raw_bytes is not None and isinstance(raw_bytes, bytes):
            decoded_bytes = raw_bytes
        elif content is not None:
            if isinstance(content, str):
                if content.startswith("data:"):
                    try:
                        header, b64_data = content.split(",", 1)
                        decoded_bytes = base64.b64decode(b64_data)
                        if ";" in header:
                            extracted_mime = header.split(";")[0].replace("data:", "").strip()
                            if extracted_mime:
                                declared_mime = extracted_mime
                    except Exception as e:
                        status = AttachmentStatus.CORRUPTED
                        error_msg = f"Failed to decode base64 content: {str(e)}"
                else:
                    text_content = content
                    # If this looks like a text file or code
                    decoded_bytes = content.encode("utf-8")
            elif isinstance(content, bytes):
                decoded_bytes = content

        # Calculate actual byte size
        actual_size = len(decoded_bytes) if decoded_bytes is not None else raw_size

        # 2. Check for 0-byte or empty attachment
        if (actual_size == 0 or (decoded_bytes is not None and len(decoded_bytes) == 0)) and not text_content:
            status = AttachmentStatus.EMPTY_FILE
            error_msg = f"Attachment '{filename}' is empty (0 bytes). Cannot access image or file content."
            actual_size = 0

        # 3. Detect and resolve actual MIME type
        detected_mime = declared_mime
        if decoded_bytes and len(decoded_bytes) > 0:
            magic_mime = detect_mime_type_from_bytes(decoded_bytes, fallback_filename=filename)
            if magic_mime != "application/octet-stream" or not detected_mime:
                detected_mime = magic_mime

        if not detected_mime:
            detected_mime, _ = mimetypes.guess_type(filename)
        if not detected_mime:
            detected_mime = "application/octet-stream"

        # 4. Handle image validation
        dimensions = None
        if status == AttachmentStatus.READY and any(detected_mime.lower().startswith(p) for p in IMAGE_MIME_PREFIXES):
            if decoded_bytes and len(decoded_bytes) > 0:
                dimensions = inspect_image_dimensions(decoded_bytes)
                if dimensions is None and not detected_mime.startswith("image/svg"):
                    # Failed to parse image structure
                    status = AttachmentStatus.CORRUPTED
                    error_msg = f"Attachment '{filename}' contains invalid or corrupted image bytes."
            else:
                status = AttachmentStatus.INACCESSIBLE
                error_msg = f"Attachment '{filename}' has image type {detected_mime} but missing raw bytes."
        elif status == AttachmentStatus.READY and not any(detected_mime.lower().startswith(p) for p in IMAGE_MIME_PREFIXES):
            # Non-image file (e.g. text/plain, json, pdf)
            if not text_content and decoded_bytes:
                try:
                    text_content = decoded_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    pass

        attachment = Attachment(
            attachment_id=attachment_id,
            filename=filename,
            mime_type=detected_mime,
            size=actual_size,
            source=source,
            data_url=data_url if data_url else (f"data:{detected_mime};base64,{base64.b64encode(decoded_bytes).decode('utf-8')}" if (decoded_bytes and status == AttachmentStatus.READY) else None),
            raw_bytes=decoded_bytes,
            text_content=text_content,
            status=status,
            dimensions=dimensions,
            error_message=error_msg,
            metadata=item.get("metadata", {})
        )

        self._attachments[attachment_id] = attachment

        if conversation_id:
            if conversation_id not in self._session_attachments:
                self._session_attachments[conversation_id] = []
            if attachment_id not in self._session_attachments[conversation_id]:
                self._session_attachments[conversation_id].append(attachment_id)

        logger.info(f"Ingested attachment {attachment_id} ({filename}, {detected_mime}, {actual_size} bytes, status={status.value})")
        return attachment

    def get_attachment(self, attachment_id: str) -> Optional[Attachment]:
        return self._attachments.get(attachment_id)

    def get_attachments_for_session(self, conversation_id: str) -> List[Attachment]:
        ids = self._session_attachments.get(conversation_id, [])
        return [self._attachments[aid] for aid in ids if aid in self._attachments]

    def list_all_attachments(self) -> List[Attachment]:
        return list(self._attachments.values())

    def clear(self, conversation_id: Optional[str] = None):
        if conversation_id:
            ids = self._session_attachments.pop(conversation_id, [])
            for aid in ids:
                self._attachments.pop(aid, None)
        else:
            self._attachments.clear()
            self._session_attachments.clear()


# Global singleton instance
_attachment_manager = AttachmentManager()


def get_attachment_manager() -> AttachmentManager:
    return _attachment_manager
