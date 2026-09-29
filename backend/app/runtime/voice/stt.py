"""Speech to text.

Contract: ``transcribe(audio) -> Transcript``. The caller does not care which
provider answered, and the agent never sees audio -- only the transcript.

Default backend is Groq's OpenAI-compatible transcription endpoint (fast
matters more than perfect here: the gap between "stopped talking" and "JARVIS
started working" is what an audience feels). Model ids come from config so
they can be corrected without a code change.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

from app.runtime import config

logger = logging.getLogger(__name__)


class TranscriptionError(RuntimeError):
    """Raised when no backend could produce a transcript."""


@dataclass
class Transcript:
    text: str
    language: Optional[str] = None
    duration_s: float = 0.0
    confidence: Optional[float] = None
    model: str = ""
    segments: Optional[List[Dict[str, Any]]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.text or not self.text.strip()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "language": self.language,
            "duration_s": self.duration_s,
            "confidence": self.confidence,
            "model": self.model,
            "segments": self.segments,
        }


class SpeechToText(Protocol):
    async def transcribe(
        self, audio: bytes, *, mime: str, language: Optional[str] = None
    ) -> Transcript:
        ...


def _filename_for(mime: str) -> str:
    return {
        "audio/webm": "audio.webm",
        "audio/ogg": "audio.ogg",
        "audio/wav": "audio.wav",
        "audio/x-wav": "audio.wav",
        "audio/wave": "audio.wav",
        "audio/mp4": "audio.mp4",
        "audio/m4a": "audio.m4a",
        "audio/x-m4a": "audio.m4a",
        "audio/mpeg": "audio.mp3",
        "audio/mp3": "audio.mp3",
        "audio/flac": "audio.flac",
    }.get(mime, "audio.webm")


def _confidence_from(payload: Any) -> Optional[float]:
    """Whisper reports avg_logprob per segment; fold it into a 0-1 score."""
    segments = getattr(payload, "segments", None)
    if not segments:
        return None
    try:
        import math

        logprobs = [
            s.get("avg_logprob") if isinstance(s, dict) else getattr(s, "avg_logprob", None)
            for s in segments
        ]
        usable = [lp for lp in logprobs if isinstance(lp, (int, float))]
        if not usable:
            return None
        return round(min(1.0, max(0.0, math.exp(sum(usable) / len(usable)))), 3)
    except Exception:  # noqa: BLE001
        return None


class GroqWhisperSTT:
    """Groq-hosted Whisper. Tries the configured model, then the fallbacks."""

    name = "groq"

    def __init__(self, model: Optional[str] = None):
        self.model = model or config.STT_MODEL

    def _models(self) -> List[str]:
        ordered = [self.model] + [
            m for m in config.STT_FALLBACK_MODELS if m != self.model
        ]
        return ordered

    async def transcribe(
        self, audio: bytes, *, mime: str, language: Optional[str] = None
    ) -> Transcript:
        import asyncio

        return await asyncio.to_thread(self._transcribe_sync, audio, mime, language)

    def _transcribe_sync(
        self, audio: bytes, mime: str, language: Optional[str]
    ) -> Transcript:
        try:
            from groq import Groq
        except ImportError as exc:  # pragma: no cover
            raise TranscriptionError("groq package is not installed") from exc

        client = Groq()
        filename = _filename_for(mime)
        last_error: Optional[Exception] = None

        for model in self._models():
            try:
                buffer = io.BytesIO(audio)
                buffer.name = filename
                kwargs: Dict[str, Any] = {
                    "file": (filename, buffer, mime),
                    "model": model,
                    "response_format": "verbose_json",
                }
                if language:
                    kwargs["language"] = language

                response = client.audio.transcriptions.create(**kwargs)

                text = (getattr(response, "text", "") or "").strip()
                segments = getattr(response, "segments", None)
                return Transcript(
                    text=text,
                    language=getattr(response, "language", None) or language,
                    duration_s=float(getattr(response, "duration", 0.0) or 0.0),
                    confidence=_confidence_from(response),
                    model=model,
                    segments=segments if isinstance(segments, list) else None,
                )
            except Exception as exc:  # noqa: BLE001 - try the next model
                last_error = exc
                logger.warning("STT model %s failed: %s", model, exc)
                continue

        raise TranscriptionError(
            f"no STT model succeeded (last error: {last_error})"
        ) from last_error


class NullSTT:
    """Used when STT is disabled, and in tests."""

    name = "null"

    async def transcribe(
        self, audio: bytes, *, mime: str, language: Optional[str] = None
    ) -> Transcript:
        raise TranscriptionError("speech-to-text is disabled")


def get_stt() -> SpeechToText:
    if not config.STT_ENABLED:
        return NullSTT()
    return GroqWhisperSTT()


__all__ = [
    "Transcript",
    "SpeechToText",
    "GroqWhisperSTT",
    "NullSTT",
    "TranscriptionError",
    "get_stt",
]
