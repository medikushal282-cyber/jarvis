"""Voice endpoints: transcribe, synthesize, config.

Deliberately no /voice/turn endpoint. Keeping transcription separate from
running means the transcript can be shown and corrected before it is acted
on, and the voice layer never learns what a run is.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.runtime import config
from app.runtime.ids import resolve_within, utc_now
from app.runtime.sessions.store import run_store, session_store, workspace_store
from app.runtime.voice.speakable import to_speakable
from app.runtime.voice.stt import TranscriptionError, get_stt
from app.runtime.voice.tts import SynthesisError, SynthesisUnsupported, get_tts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["Voice"])


class SynthesizeRequest(BaseModel):
    text: str
    voice: Optional[str] = None
    format: str = "mp3"
    speakable: bool = True


@router.get("/config")
def voice_config():
    """So the UI can degrade gracefully instead of throwing."""
    tts = get_tts()
    return {
        "stt_enabled": config.STT_ENABLED,
        "tts_enabled": config.TTS_ENABLED,
        "tts_backend": getattr(tts, "name", "browser"),
        "tts_client_side": getattr(tts, "client_side", True),
        "stt_model": config.STT_MODEL,
        "max_utterance_s": config.MAX_UTTERANCE_S,
        "max_audio_bytes": config.MAX_AUDIO_BYTES,
        "allowed_mime": sorted(config.ALLOWED_AUDIO_MIME),
    }


@router.get("/voices")
def list_voices():
    return {"voices": get_tts().voices()}


@router.post("/transcribe")
async def transcribe(
    request: Request,
    file: UploadFile = File(...),
    language: Optional[str] = Form(None),
    session_id: Optional[str] = Form(None),
    workspace_id: Optional[str] = Form(None),
):
    if not config.STT_ENABLED:
        raise HTTPException(status_code=503, detail="Speech-to-text is disabled")

    mime = (file.content_type or "").split(";")[0].strip().lower()
    if mime not in config.ALLOWED_AUDIO_MIME:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported audio type '{mime or 'unknown'}'",
        )

    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=400, detail="Empty audio upload")
    if len(audio) > config.MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Audio exceeds {config.MAX_AUDIO_BYTES // (1024 * 1024)} MB",
        )

    try:
        transcript = await get_stt().transcribe(audio, mime=mime, language=language)
    except TranscriptionError as exc:
        logger.warning("transcription failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))

    if transcript.is_empty:
        # Not an error: the user coughed. The client re-arms the mic.
        return {
            "text": "",
            "empty": True,
            "message": "No speech detected",
            "duration_s": transcript.duration_s,
        }

    audio_url = None
    if config.STORE_VOICE_CLIPS and session_id:
        audio_url = _store_clip(audio, mime, session_id, workspace_id)

    payload = transcript.to_dict()
    payload["empty"] = False
    payload["audio_url"] = audio_url
    return payload


def _store_clip(
    audio: bytes, mime: str, session_id: str, workspace_id: Optional[str]
) -> Optional[str]:
    """Keep the clip so the demo video is easy to cut. Best effort."""
    try:
        session = session_store.get(session_id, workspace_id)
        if session is None:
            return None
        ws_dir = workspace_store.dir_for(session.workspace_id)
        clips = resolve_within(ws_dir, "voice", session.id)
        clips.mkdir(parents=True, exist_ok=True)
        ext = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/wav": "wav",
               "audio/mpeg": "mp3", "audio/mp4": "mp4"}.get(mime, "bin")
        name = f"{utc_now().replace(':', '-')}.{ext}"
        (clips / name).write_bytes(audio)
        return f"/api/voice/clips/{session.id}/{name}"
    except Exception:  # noqa: BLE001 - never fail a transcription over storage
        logger.exception("could not store voice clip")
        return None


@router.get("/clips/{session_id}/{filename}")
def get_clip(session_id: str, filename: str, workspace_id: Optional[str] = None):
    from fastapi.responses import FileResponse

    try:
        session = session_store.get(session_id, workspace_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        ws_dir = workspace_store.dir_for(session.workspace_id)
        target = resolve_within(ws_dir, "voice", session.id, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not target.is_file():
        raise HTTPException(status_code=404, detail="Clip not found")
    return FileResponse(target)


@router.post("/synthesize")
async def synthesize(req: SynthesizeRequest):
    if not config.TTS_ENABLED:
        raise HTTPException(status_code=503, detail="Text-to-speech is disabled")

    text = to_speakable(req.text) if req.speakable else req.text
    if not text.strip():
        raise HTTPException(status_code=400, detail="Nothing to speak")

    try:
        speech = await get_tts().synthesize(text, voice=req.voice, fmt=req.format)
    except SynthesisUnsupported:
        # The browser backend is active: hand back the text to speak locally.
        return {"client_side": True, "text": text}
    except SynthesisError as exc:
        logger.warning("synthesis failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))

    return Response(
        content=speech.audio,
        media_type=speech.mime,
        headers={
            "X-Voice": speech.voice,
            "X-Spoken-Text": text[:200].encode("ascii", "ignore").decode(),
        },
    )


class SpeakableRequest(BaseModel):
    text: str


@router.post("/speakable")
def make_speakable(req: SpeakableRequest):
    """Expose the transform so the browser backend can use it too."""
    return {"text": to_speakable(req.text), "original_length": len(req.text)}


__all__ = ["router"]
