"""Text to speech.

Default backend is ``browser``: the client speaks via ``speechSynthesis``, so
there is zero latency, zero cost and nothing to break on demo day. The server
backend is wired behind the same Protocol and enabled with
``JARVIS_TTS_BACKEND=groq``.

A synthetic-sounding JARVIS is a smaller demo problem than a silent one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

from app.runtime import config

logger = logging.getLogger(__name__)


class SynthesisError(RuntimeError):
    """Raised when no backend could produce audio."""


class SynthesisUnsupported(SynthesisError):
    """The active backend synthesises on the client, not here."""


@dataclass
class Speech:
    audio: bytes
    mime: str
    voice: str
    model: str = ""

    @property
    def size(self) -> int:
        return len(self.audio)


class TextToSpeech(Protocol):
    async def synthesize(
        self, text: str, *, voice: Optional[str] = None, fmt: Optional[str] = None
    ) -> Speech:
        ...

    def voices(self) -> List[Dict[str, Any]]:
        ...


class BrowserTTS:
    """No-op server side; the client owns synthesis."""

    name = "browser"
    client_side = True

    async def synthesize(
        self, text: str, *, voice: Optional[str] = None, fmt: Optional[str] = None
    ) -> Speech:
        raise SynthesisUnsupported(
            "TTS runs in the browser; call window.speechSynthesis on the client"
        )

    def voices(self) -> List[Dict[str, Any]]:
        return []


class GroqTTS:
    """Groq-hosted TTS. Model and voice ids come from config."""

    name = "groq"
    client_side = False

    def __init__(self, model: Optional[str] = None, voice: Optional[str] = None):
        self.model = model or config.TTS_MODEL
        self.default_voice = voice or config.TTS_VOICE

    async def synthesize(
        self, text: str, *, voice: Optional[str] = None, fmt: Optional[str] = None
    ) -> Speech:
        import asyncio

        return await asyncio.to_thread(
            self._sync, text, voice or self.default_voice, fmt or config.TTS_FORMAT
        )

    def _sync(self, text: str, voice: str, fmt: str) -> Speech:
        try:
            from groq import Groq
        except ImportError as exc:  # pragma: no cover
            raise SynthesisError("groq package is not installed") from exc

        try:
            client = Groq()
            response = client.audio.speech.create(
                model=self.model, voice=voice, input=text, response_format=fmt
            )
            audio = getattr(response, "read", lambda: None)()
            if audio is None:
                audio = getattr(response, "content", None)
            if not audio:
                raise SynthesisError("TTS backend returned no audio")
            return Speech(
                audio=audio,
                mime={"mp3": "audio/mpeg", "wav": "audio/wav"}.get(fmt, f"audio/{fmt}"),
                voice=voice,
                model=self.model,
            )
        except SynthesisError:
            raise
        except Exception as exc:  # noqa: BLE001
            if "model_terms_required" in str(exc):
                raise SynthesisError(
                    f"The Groq org admin must accept the terms for {self.model} in the Groq console first"
                ) from exc
            raise SynthesisError(f"TTS failed: {exc}") from exc

    def voices(self) -> List[Dict[str, Any]]:
        return [{"id": self.default_voice, "name": self.default_voice, "model": self.model}]


class EdgeTTS:
    """Microsoft Edge Neural TTS: free, ultra-high quality, zero latency British Butler voices."""

    name = "edge"
    client_side = False

    def __init__(self, voice: Optional[str] = None):
        self.default_voice = voice or getattr(config, "TTS_VOICE", "en-GB-RyanNeural")

    async def synthesize(
        self, text: str, *, voice: Optional[str] = None, fmt: Optional[str] = None
    ) -> Speech:
        v = voice or self.default_voice
        try:
            import edge_tts
            communicate = edge_tts.Communicate(text, v)
            chunks = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    chunks.append(chunk["data"])
            audio = b"".join(chunks)
            if not audio:
                raise SynthesisError("Edge TTS returned empty audio stream")
            return Speech(
                audio=audio,
                mime="audio/mpeg",
                voice=v,
                model="edge-neural",
            )
        except Exception as exc:
            logger.warning("Edge TTS synthesis error: %s", exc)
            raise SynthesisError(f"Edge TTS failed: {exc}") from exc

    def voices(self) -> List[Dict[str, Any]]:
        return [
            {"id": "en-GB-RyanNeural", "name": "Ryan (British Butler / Formal)", "gender": "Male", "locale": "en-GB"},
            {"id": "en-GB-ThomasNeural", "name": "Thomas (British Gentleman)", "gender": "Male", "locale": "en-GB"},
            {"id": "en-GB-ArthurNeural", "name": "Arthur (British Distinguished)", "gender": "Male", "locale": "en-GB"},
            {"id": "en-GB-SoniaNeural", "name": "Sonia (British Female)", "gender": "Female", "locale": "en-GB"},
        ]


def get_tts() -> TextToSpeech:
    if not config.TTS_ENABLED:
        return BrowserTTS()
    backend = getattr(config, "TTS_BACKEND", "edge").lower()
    if backend == "edge":
        return EdgeTTS()
    if backend == "groq":
        return GroqTTS()
    if backend == "browser":
        return BrowserTTS()
    return EdgeTTS()


__all__ = [
    "Speech",
    "TextToSpeech",
    "BrowserTTS",
    "GroqTTS",
    "EdgeTTS",
    "SynthesisError",
    "SynthesisUnsupported",
    "get_tts",
]
