from typing import Dict, Any, Optional
from app.tools.base import Tool, ToolResult, ToolContext
from app.attachments import get_attachment_manager
from app.vision import get_vision_service


class AnalyzeImageTool(Tool):
    name = "analyze_image"
    description = (
        "Performs visual perception and inspection on a user-provided image attachment using a vision-capable model. "
        "Inspects actual pixels to identify objects, scene, people, text, colors, and layout. "
        "Never guesses content from the filename."
    )
    category = "vision"
    required_permission = "vision.analyze"
    parameters = {
        "type": "object",
        "properties": {
            "attachment_id": {
                "type": "string",
                "description": "ID of the image attachment to inspect."
            },
            "prompt": {
                "type": "string",
                "description": "Specific visual inspection question or instruction (e.g. 'What is happening in this image?')."
            }
        },
        "required": ["attachment_id"]
    }

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        attachment_id = arguments.get("attachment_id", "").strip()
        prompt = arguments.get("prompt", "Describe what is happening in this image in detail.")

        if not attachment_id:
            return ToolResult(
                success=False,
                tool=self.name,
                error={
                    "code": "MISSING_ATTACHMENT_ID",
                    "message": "Argument 'attachment_id' is required to analyze an image."
                }
            )

        manager = get_attachment_manager()
        attachment = manager.get_attachment(attachment_id)

        if not attachment:
            return ToolResult(
                success=False,
                tool=self.name,
                error={
                    "code": "ATTACHMENT_NOT_FOUND",
                    "message": f"Attachment with ID '{attachment_id}' was not found in conversation attachments. Do not look in workspace filesystem files."
                }
            )

        vision = get_vision_service()
        res = vision.analyze_image(attachment=attachment, prompt=prompt)

        if not res.success:
            return ToolResult(
                success=False,
                tool=self.name,
                error={
                    "code": res.error_code or "VISION_ERROR",
                    "message": res.message
                },
                metadata={
                    "filename": attachment.filename,
                    "mime_type": res.mime_type,
                    "dimensions": list(res.dimensions) if res.dimensions else None
                }
            )

        return ToolResult(
            success=True,
            tool=self.name,
            data={
                "description": res.description,
                "model": res.model,
                "provider": res.provider,
                "attachment_id": attachment_id,
                "filename": attachment.filename,
                "mime_type": res.mime_type,
                "dimensions": list(res.dimensions) if res.dimensions else None
            },
            metadata={
                "visual_inspection": True
            }
        )


class GetAttachmentInfoTool(Tool):
    name = "get_attachment_info"
    description = (
        "Retrieves metadata (filename, MIME type, size, dimensions, processing status) for conversation attachments. "
        "Returns metadata ONLY without performing visual analysis or guessing image content."
    )
    category = "vision"
    required_permission = "attachment.read"
    parameters = {
        "type": "object",
        "properties": {
            "attachment_id": {
                "type": "string",
                "description": "Optional attachment ID. If omitted, returns metadata for all attachments in the current session."
            }
        }
    }

    def execute(self, arguments: Dict[str, Any], context: Optional[ToolContext] = None) -> ToolResult:
        attachment_id = arguments.get("attachment_id", "").strip()
        manager = get_attachment_manager()

        if attachment_id:
            att = manager.get_attachment(attachment_id)
            if not att:
                return ToolResult(
                    success=False,
                    tool=self.name,
                    error={
                        "code": "ATTACHMENT_NOT_FOUND",
                        "message": f"Attachment '{attachment_id}' not found in active session attachments."
                    }
                )
            return ToolResult(
                success=True,
                tool=self.name,
                data=att.get_metadata()
            )

        # List all attachments
        session_id = context.session_id if context else None
        if session_id:
            atts = manager.get_attachments_for_session(session_id)
        else:
            atts = manager.list_all_attachments()

        return ToolResult(
            success=True,
            tool=self.name,
            data={
                "count": len(atts),
                "attachments": [a.get_metadata() for a in atts]
            }
        )
