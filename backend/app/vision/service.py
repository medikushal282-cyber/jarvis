import os
import logging
from typing import Dict, Any, Optional, Tuple, List
from pydantic import BaseModel
from app.attachments.model import Attachment, AttachmentStatus

logger = logging.getLogger(__name__)

# Known vision-capable models by provider
VISION_CAPABLE_MODELS = {
    "groq": [
        "llama-3.2-11b-vision-preview",
        "llama-3.2-90b-vision-preview",
        "meta-llama/llama-3.2-11b-vision-instruct",
        "meta-llama/llama-3.2-90b-vision-instruct"
    ],
    "openai": [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo"
    ],
    "anthropic": [
        "claude-3-5-sonnet-20241022",
        "claude-3-haiku-20240307",
        "claude-3-opus-20240229"
    ],
    "ollama": [
        "llava",
        "bakllava",
        "llama3.2-vision",
        "minicpm-v"
    ]
}


class VisionAnalysisResult(BaseModel):
    success: bool
    description: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    error_code: Optional[str] = None
    message: str
    dimensions: Optional[Tuple[int, int]] = None
    mime_type: Optional[str] = None


class VisionService:
    """
    Dedicated vision processing service.
    Owns visual understanding by sending real image pixels/base64 to vision-capable models.
    NEVER relies on filename semantics to guess image contents.
    """

    def resolve_vision_model(
        self,
        preferred_model: Optional[str] = None,
        preferred_provider: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Resolves the best available vision-capable model and provider.
        """
        # If explicitly passed a vision model
        if preferred_model and preferred_provider:
            prov = preferred_provider.lower()
            mod = preferred_model.lower()
            if prov in VISION_CAPABLE_MODELS:
                for vm in VISION_CAPABLE_MODELS[prov]:
                    if vm in mod or mod in vm:
                        return preferred_model, preferred_provider

        # Check Groq Vision
        if os.environ.get("GROQ_API_KEY"):
            return "llama-3.2-11b-vision-preview", "groq"

        # Check OpenAI Vision
        if os.environ.get("OPENAI_API_KEY"):
            return "gpt-4o-mini", "openai"

        # Check Anthropic Vision
        if os.environ.get("ANTHROPIC_API_KEY"):
            return "claude-3-5-sonnet-20241022", "anthropic"

        return None, None

    def analyze_image(
        self,
        attachment: Attachment,
        prompt: str = "Please inspect the visual content of this image. Describe what you see in detail (objects, persons, text, scene, colors, layout, and actions).",
        model: Optional[str] = None,
        provider: Optional[str] = None
    ) -> VisionAnalysisResult:
        """
        Performs real visual analysis on the provided image attachment.
        """
        # 1. Attachment integrity checks
        if attachment.status == AttachmentStatus.EMPTY_FILE or attachment.size == 0:
            return VisionAnalysisResult(
                success=False,
                error_code="EMPTY_FILE",
                message=f"Cannot access image data: attachment '{attachment.filename}' is empty (0 bytes). JARVIS cannot infer or guess what an empty image contains.",
                mime_type=attachment.mime_type
            )

        if attachment.status == AttachmentStatus.INACCESSIBLE or (not attachment.data_url and not attachment.raw_bytes):
            return VisionAnalysisResult(
                success=False,
                error_code="INACCESSIBLE",
                message=f"Cannot access image data: attachment '{attachment.filename}' has no accessible content reference.",
                mime_type=attachment.mime_type
            )

        if attachment.status == AttachmentStatus.CORRUPTED:
            return VisionAnalysisResult(
                success=False,
                error_code="CORRUPTED",
                message=f"Cannot analyze image: '{attachment.filename}' contains invalid or corrupted image data.",
                mime_type=attachment.mime_type
            )

        if not attachment.is_image:
            return VisionAnalysisResult(
                success=False,
                error_code="NON_IMAGE",
                message=f"Attachment '{attachment.filename}' is of type '{attachment.mime_type}', which is not a recognized image format.",
                mime_type=attachment.mime_type
            )

        data_url = attachment.get_base64_data_url()
        if not data_url:
            return VisionAnalysisResult(
                success=False,
                error_code="NO_IMAGE_DATA",
                message=f"Failed to generate base64 image URL for '{attachment.filename}'.",
                mime_type=attachment.mime_type
            )

        # 2. Resolve vision-capable model
        vision_model, vision_provider = self.resolve_vision_model(model, provider)
        if not vision_model or not vision_provider:
            return VisionAnalysisResult(
                success=False,
                error_code="VISION_UNAVAILABLE",
                message="Visual analysis is currently unavailable because no vision-capable model (Groq Vision, OpenAI GPT-4o, or Claude 3.5 Sonnet) has an active API key. JARVIS will not guess or hallucinate the image contents from its filename.",
                dimensions=attachment.dimensions,
                mime_type=attachment.mime_type
            )

        # 3. Call Vision LLM with image payload
        try:
            import litellm

            # Format litellm model string
            litellm_model = vision_model
            if vision_provider == "groq" and not litellm_model.startswith("groq/"):
                litellm_model = f"groq/{litellm_model}"
            elif vision_provider == "openai" and not litellm_model.startswith("openai/"):
                litellm_model = f"openai/{litellm_model}"
            elif vision_provider == "anthropic" and not litellm_model.startswith("anthropic/"):
                litellm_model = f"anthropic/{litellm_model}"

            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "You are JARVIS's visual perception engine. "
                                "Analyze the actual visual content and pixels in the image carefully and accurately. "
                                "Describe what is genuinely visible (objects, people, scene, background, text, colors, activity). "
                                "Do NOT assume or infer content based on any hypothetical filename. "
                                f"\n\nUser Question: {prompt}"
                            )
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": data_url
                            }
                        }
                    ]
                }
            ]

            response = litellm.completion(
                model=litellm_model,
                messages=messages,
                temperature=0.2,
                max_tokens=1000
            )

            description = response.choices[0].message.content or ""
            return VisionAnalysisResult(
                success=True,
                description=description.strip(),
                model=vision_model,
                provider=vision_provider,
                message="Visual analysis completed successfully.",
                dimensions=attachment.dimensions,
                mime_type=attachment.mime_type
            )

        except Exception as e:
            logger.error(f"Vision model execution failed: {e}", exc_info=True)
            error_str = str(e)
            if "Invalid API Key" in error_str or "invalid_api_key" in error_str:
                return VisionAnalysisResult(
                    success=False,
                    error_code="INVALID_API_KEY",
                    message="Visual analysis failed due to an invalid vision API key. JARVIS will not hallucinate image contents.",
                    dimensions=attachment.dimensions,
                    mime_type=attachment.mime_type
                )
            return VisionAnalysisResult(
                success=False,
                error_code="VISION_EXECUTION_ERROR",
                message=f"Visual analysis failed: {error_str}",
                dimensions=attachment.dimensions,
                mime_type=attachment.mime_type
            )


# Global singleton instance
_vision_service = VisionService()


def get_vision_service() -> VisionService:
    return _vision_service
