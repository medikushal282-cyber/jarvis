# Runtime — Voice Pipeline

**Owner:** Farhan · **Package:** `backend/app/runtime/voice/`

JARVIS should not feel like a REST API. It should feel like *"JARVIS, do this."*
This layer is the microphone-to-speaker loop. It knows nothing about what the
agent does with the transcript.

---

## 1. Pipeline

```
  Microphone
      |  MediaRecorder / AudioWorklet, 16 kHz mono
      v
  VAD (client)                  detects speech start/end, trims silence
      |
      v
  POST /api/voice/transcribe    multipart audio  ->  Transcript
      |
      v
  POST /api/sessions/{id}/runs  { objective: transcript.text, input_mode: "voice" }
      |
      v
  AgentRunner  ...  events  ...  RunOutcome.reply
      |
      v
  POST /api/voice/synthesize    { text }  ->  audio/mpeg
      |
      v
  Speaker
```

The two backend contracts, and nothing more:

```python
@dataclass
class Transcript:
    text: str
    language: str | None
    duration_s: float
    confidence: float | None
    segments: list[dict] | None      # optional word/segment timings

class SpeechToText(Protocol):
    async def transcribe(self, audio: bytes, *, mime: str,
                         language: str | None = None) -> Transcript: ...

class TextToSpeech(Protocol):
    async def synthesize(self, text: str, *, voice: str | None = None,
                         fmt: str = "mp3") -> bytes: ...
```

Both are Protocols with swappable implementations, because the provider choice
below may need to change under demo conditions and nothing else should care.

---

## 2. Provider choices

### STT — Groq Whisper, server-side

Groq hosts Whisper on an OpenAI-compatible transcription endpoint and it is very
fast, which matters more than accuracy here: the gap between "stop talking" and
"JARVIS starts working" is the thing an audience feels.

- Endpoint shape: `POST https://api.groq.com/openai/v1/audio/transcriptions`,
  multipart, `model` + `file`.
- **Models (checked against Groq's live list, 2026-09-29):**
  `whisper-large-v3-turbo`, falling back to `whisper-large-v3`.
  `distil-whisper-large-v3-en` is not offered and was removed.
- Reuse `GROQ_API_KEY`, already in `.env`.
- **Verified for real:** a spoken sentence came back as "Create numbers.text
  containing 1, 2, 3, and then read it." in 0.93 s at confidence 0.77, and
  `scripts/e2e_voice.py` drives the whole loop through the actual UI with a
  WAV file as the browser's microphone.

Why server-side rather than the browser's `SpeechRecognition` API: the Web
Speech API is Chromium-only, silently streams audio to Google, gives no
confidence data, and stops working offline. Fine as a **fallback** behind a flag
for the case where the network is bad on demo day, not as the primary.

### TTS — browser first, server second

Ship `window.speechSynthesis` first. It is zero latency, zero cost, zero
dependency, and works today. Wire the `TextToSpeech` Protocol at the same time
but leave the server implementation behind a config flag.

Upgrade path, in order of preference if there is time:
1. Groq's hosted TTS, `JARVIS_TTS_BACKEND=groq`. PlayAI is no longer offered;
   the current model is `canopylabs/orpheus-v1-english` (voices `troy`,
   `hannah`, `austin`; WAV output), now the default. **The Groq org admin must
   accept its terms once** at
   https://console.groq.com/playground?model=canopylabs%2Forpheus-v1-english
   before it will answer; until then the API returns `model_terms_required`.
2. ElevenLabs — best quality, costs money, needs another key.
3. Piper / local — offline-safe, heavier install.

A synthetic-sounding JARVIS is a smaller demo problem than a JARVIS that does
not speak because an API key expired.

---

## 3. Client-side capture

`frontend/src/components/Voice/`

- `useVoiceCapture()` — `getUserMedia`, `MediaRecorder` at 16 kHz mono, opus or
  wav, chunked.
- **VAD on the client.** Start capture on speech, stop after ~800 ms of
  silence, discard clips under ~300 ms. Energy-threshold VAD is enough; do not
  pull in a model for this. Without VAD the user has to click stop, which kills
  the "just talk to it" feeling.
- **Push-to-talk as the reliable path.** Hold space (or a mic button) to talk.
  Always-listening wake-word detection is a trap for a hackathon: it burns time
  and fails on stage in a noisy room. Build push-to-talk, add hands-free only if
  everything else is done.
- Cap a single utterance at 60 s and 25 MB; reject longer on the client with a
  clear message rather than failing in the upload.

### Barge-in

If the user starts speaking while JARVIS is talking, stop the playback
immediately and capture. Without this, talking over JARVIS produces two voices
and the demo looks broken. Implementation: the VAD is always running even during
playback; on speech detection, `audio.pause()` and start capture.

---

## 4. HTTP surface

| Method | Path | Body / Response |
| :--- | :--- | :--- |
| `POST` | `/api/voice/transcribe` | multipart `file`, optional `language`, `session_id` → `Transcript` |
| `POST` | `/api/voice/synthesize` | `{text, voice?, format?}` → audio bytes (`audio/wav` for Orpheus), or `{client_side: true, text}` when the browser speaks |
| `GET` | `/api/voice/voices` | Available voices for the active TTS backend |
| `GET` | `/api/voice/config` | `{stt_enabled, tts_enabled, tts_backend, max_utterance_s}` — so the UI degrades gracefully instead of throwing |

`POST /api/voice/turn` is a deliberate **non-goal**. Keeping transcribe and run
separate means the transcript can be shown and corrected before it is acted on,
and it keeps the voice layer from knowing anything about runs.

Limits: 25 MB body cap, allowlist of mime types (`audio/webm`, `audio/ogg`,
`audio/wav`, `audio/mp4`, `audio/mpeg`), per-user rate limit on transcribe.

---

## 5. How voice threads into sessions and events

- A voice turn is an ordinary `Turn` with `input_mode: "voice"` and an
  `audio_url` pointing at the stored clip (see [SESSIONS.md](SESSIONS.md)).
  Keeping the audio makes the demo video far easier to cut.
- The transcript, not the audio, is what reaches the agent. `RunRequest` gains
  nothing voice-specific beyond `input_mode`, which the brain may use to shorten
  its reply — spoken replies should be one or two sentences, not a wall of
  markdown.
- The runtime emits `voice_transcribed` (`{text, confidence, duration_s,
  model, language}`) on a voice run's stream, before the brain starts, so it
  may precede `run_started`. The same details are kept on the user turn's
  `metadata.voice`. Only known fields are stored.
- `voice_spoken` is in the catalog but **not emitted**: speech happens in the
  browser, which the server cannot observe. The UI's indicator (LISTENING →
  TRANSCRIBING → EXECUTING → SPEAKING → IDLE) covers it for the user.

### What JARVIS says out loud

Do not speak `RunOutcome.reply` verbatim if it contains code blocks, file paths,
or lists. Run it through a short "speakable" transform:

- Strip fenced code; say "I have written that to `app.py`" instead.
- Collapse paths to basenames.
- Cap at ~40 words; the screen has the detail, the voice has the headline.

Worth a small LLM call on the fast model if a regex version sounds wooden, but
try the regex first.

---

## 6. Failure behaviour

Every one of these has to degrade to something usable, because they will all
happen at least once on demo day.

| Failure | Behaviour |
| :--- | :--- |
| Mic permission denied | Fall back to the text box, one-line explanation, do not block the app |
| STT returns empty text | Do not start a run. Show "I did not catch that", re-arm the mic |
| STT low confidence | Show the transcript in an editable box with a confirm button |
| STT provider down | Fall back to the Web Speech API if available, else text input |
| TTS fails | Show the reply as text, silently. Never block the run on speech |
| Network drops mid-run | The SSE `Last-Event-ID` resume handles it (see [EVENTS.md](EVENTS.md)) |

---

## 7. Acceptance criteria

1. Hold the mic button, say "list the files in this workspace", release — a run
   starts with that objective and the answer is spoken.
2. Follow up with "now delete the first one" — the same session, a second run,
   and the agent has the previous turn in context.
3. Speak over JARVIS mid-reply; playback stops within ~200 ms and capture starts.
4. Deny mic permission; the app still works entirely through text.
5. Unplug the network mid-transcription; the UI shows a clear error and the
   text box still works.
6. A 3-second utterance is transcribed and dispatched in under ~1.5 s end to end
   on the demo machine.
7. A reply containing a fenced code block is not read out character by character.
