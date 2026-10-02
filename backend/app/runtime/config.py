"""Runtime configuration: limits, feature flags, storage roots.

Everything here is overridable by environment variable so the demo machine and
CI can differ without code changes.
"""

from __future__ import annotations

import os
from pathlib import Path


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --- Storage ----------------------------------------------------------------

def project_root() -> Path:
    """Repo root: .../jarvis (this file is at backend/app/runtime/config.py)."""
    return Path(__file__).resolve().parents[3]


def sandbox_root() -> Path:
    override = os.environ.get("JARVIS_WORKSPACE_ROOT") or os.environ.get("JARVIS_SANDBOX_ROOT")
    root = Path(override).resolve() if override else project_root() / "workspace"
    root.mkdir(parents=True, exist_ok=True)
    return root


DEFAULT_WORKSPACE_ID = os.environ.get("JARVIS_DEFAULT_WORKSPACE", "default")

# --- Agent selection --------------------------------------------------------

#: "legacy" -> the existing graph in app/graph/; "core" -> Nikunj's brain;
#: "null" -> a no-op runner for tests.
#: Read at call time so the brain can be switched without a restart, and so a
#: test can select one regardless of module import order.
def agent_impl() -> str:
    return os.environ.get("JARVIS_AGENT", "core").strip().lower()


#: Snapshot at import, for display only. Never branch on this.
AGENT_IMPL = agent_impl()

DEFAULT_MODEL = os.environ.get("JARVIS_DEFAULT_MODEL", "openai/gpt-oss-120b")
DEFAULT_PROVIDER = os.environ.get("JARVIS_DEFAULT_PROVIDER", "groq")

# --- Events -----------------------------------------------------------------

EVENT_RING_SIZE = _int("JARVIS_EVENT_RING_SIZE", 1000)
EVENT_QUEUE_SIZE = _int("JARVIS_EVENT_QUEUE_SIZE", 256)
EVENT_MAX_STRING = _int("JARVIS_EVENT_MAX_STRING", 8 * 1024)
EVENT_MAX_PAYLOAD = _int("JARVIS_EVENT_MAX_PAYLOAD", 64 * 1024)
EVENT_PERSIST = _flag("JARVIS_EVENT_PERSIST", True)
EVENT_CLEANUP_DELAY_S = _int("JARVIS_EVENT_CLEANUP_DELAY_S", 60)
SSE_HEARTBEAT_S = _int("JARVIS_SSE_HEARTBEAT_S", 15)
VALIDATE_EVENTS = _flag("JARVIS_VALIDATE_EVENTS", True)

# --- Runs -------------------------------------------------------------------

RUN_TIMEOUT_S = _int("JARVIS_RUN_TIMEOUT_S", 900)
RUN_STARTED_WATCHDOG_S = _int("JARVIS_RUN_WATCHDOG_S", 30)
SUMMARIZE_ASYNC = _flag("JARVIS_SUMMARIZE_ASYNC", True)
SUMMARY_MODELS = [
    m.strip()
    for m in os.environ.get(
        "JARVIS_SUMMARY_MODELS", "llama-3.1-8b-instant,openai/gpt-oss-20b"
    ).split(",")
    if m.strip()
]

# --- Artifacts --------------------------------------------------------------

ARTIFACT_CAPTURE = _flag("JARVIS_ARTIFACT_CAPTURE", True)
ARTIFACT_MAX_BYTES = _int("JARVIS_ARTIFACT_MAX_BYTES", 10 * 1024 * 1024)

# --- Voice ------------------------------------------------------------------

STT_ENABLED = _flag("JARVIS_STT_ENABLED", True)
TTS_ENABLED = _flag("JARVIS_TTS_ENABLED", True)
#: "edge" -> High-quality neural British Butler / Jarvis voices (free, zero API key needed);
#: "groq" -> hosted Orpheus TTS; "browser" -> client-side Web Speech.
TTS_BACKEND = os.environ.get("JARVIS_TTS_BACKEND", "edge").strip().lower()
# Model ids checked against Groq's live model list on 2026-09-29.
STT_MODEL = os.environ.get("JARVIS_STT_MODEL", "whisper-large-v3-turbo")
STT_FALLBACK_MODELS = [
    m.strip()
    for m in os.environ.get("JARVIS_STT_FALLBACK_MODELS", "whisper-large-v3").split(",")
    if m.strip()
]
# Server-side TTS (JARVIS_TTS_BACKEND=groq). Orpheus needs the Groq org admin
# to accept its terms once in the Groq console before it will answer.
# Documented English voices: troy, hannah, austin. Output is WAV.
TTS_MODEL = os.environ.get("JARVIS_TTS_MODEL", "canopylabs/orpheus-v1-english")
TTS_VOICE = os.environ.get("JARVIS_TTS_VOICE", "en-GB-RyanNeural")
TTS_FORMAT = os.environ.get("JARVIS_TTS_FORMAT", "mp3")
MAX_UTTERANCE_S = _int("JARVIS_MAX_UTTERANCE_S", 60)
MAX_AUDIO_BYTES = _int("JARVIS_MAX_AUDIO_BYTES", 25 * 1024 * 1024)
SPEAKABLE_MAX_WORDS = _int("JARVIS_SPEAKABLE_MAX_WORDS", 40)
STORE_VOICE_CLIPS = _flag("JARVIS_STORE_VOICE_CLIPS", True)

ALLOWED_AUDIO_MIME = frozenset(
    {
        "audio/webm",
        "audio/ogg",
        "audio/wav",
        "audio/x-wav",
        "audio/wave",
        "audio/mp4",
        "audio/m4a",
        "audio/x-m4a",
        "audio/mpeg",
        "audio/mp3",
        "audio/flac",
    }
)

# --- Auth -------------------------------------------------------------------

AUTH_SERVICE_URL = os.environ.get("JARVIS_AUTH_URL", "").strip()
AUTH_REQUIRED = _flag("JARVIS_AUTH_REQUIRED", False)
