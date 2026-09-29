"""Real voice end-to-end: a spoken instruction through the actual UI.

Headless Edge is given a WAV file as its microphone. The page records it
with the VOICE button, the silence detector ends the utterance, Groq Whisper
transcribes it (a real call -- needs GROQ_API_KEY in backend/.env), and the
transcript runs as a voice request against the scripted brain.

Windows only (the test sentence is spoken by the built-in System.Speech
synthesizer). Opt-in because it uses the network and your key.

Usage (from backend/), with scripts/e2e_backend.py and `npm run dev` running:

    .venv\\Scripts\\python.exe scripts\\e2e_voice.py [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

from playwright.sync_api import sync_playwright

FRONTEND = os.environ.get("E2E_FRONTEND", "http://localhost:3000")
APP_PORT = os.environ.get("E2E_APP_PORT", "8006")
TEST_PORT = os.environ.get("E2E_TEST_PORT", "8016")
SENTENCE = "Create numbers dot text containing one, two, three, and then read it."
TRAILING_SILENCE_S = 2.5


def make_utterance(path: Path) -> None:
    """Speak SENTENCE into a WAV, then pad it with silence for the VAD."""
    raw = path.with_suffix(".raw.wav")
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$s.Rate = -1;"
        f"$s.SetOutputToWaveFile('{raw}');"
        f"$s.Speak('{SENTENCE}');"
        "$s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)
    with wave.open(str(raw), "rb") as src:
        params = src.getparams()
        frames = src.readframes(src.getnframes())
    silence = b"\x00" * int(params.framerate * TRAILING_SILENCE_S) * params.sampwidth * params.nchannels
    with wave.open(str(path), "wb") as dst:
        dst.setparams(params)
        dst.writeframes(frames + silence)
    raw.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=os.path.join(tempfile.gettempdir(), "jarvis_e2e_voice"))
    out = Path(parser.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    wav = out / "utterance.wav"
    make_utterance(wav)

    results: list[tuple[str, bool, str]] = []
    console_errors: list[str] = []
    phases_seen: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, bool(ok), detail))

    def reroute(route) -> None:
        url = (route.request.url
               .replace(f"localhost:{APP_PORT}", f"127.0.0.1:{TEST_PORT}")
               .replace(f"127.0.0.1:{APP_PORT}", f"127.0.0.1:{TEST_PORT}"))
        try:
            route.fulfill(response=route.fetch(url=url, timeout=60000))
        except Exception as exc:  # noqa: BLE001
            console_errors.append(f"reroute failed {url}: {exc}")
            route.abort()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="msedge",
            headless=True,
            args=[
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                f"--use-file-for-fake-audio-capture={wav}%noloop",
            ],
        )
        ctx = browser.new_context(viewport={"width": 1500, "height": 900}, permissions=["microphone"])
        ctx.route(f"**://localhost:{APP_PORT}/**", reroute)
        ctx.route(f"**://127.0.0.1:{APP_PORT}/**", reroute)
        page = ctx.new_page()
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

        page.goto(FRONTEND, wait_until="networkidle")
        page.wait_for_timeout(1000)
        status = page.get_by_role("status")
        check("voice status starts IDLE", status.inner_text() == "IDLE", status.inner_text())

        # Record the phases the indicator goes through.
        page.expose_function("__phase", lambda text: phases_seen.append(text))
        page.evaluate("""() => {
            const el = document.querySelector('[role=status]');
            new MutationObserver(() => window.__phase(el.innerText)).observe(el, {childList: true, subtree: true, characterData: true});
        }""")

        page.get_by_role("button", name="VOICE").click()
        page.get_by_text("DONE", exact=True).wait_for(timeout=90000)
        page.wait_for_timeout(1500)
        page.screenshot(path=str(out / "voice_done.png"))

        body = page.inner_text("main")
        check("transcript became the request", "numbers" in body.lower() and "read it" in body.lower(),
              body[:200])
        check("request is marked as spoken", "SPOKEN" in body.upper())
        for phase in ("LISTENING", "TRANSCRIBING", "EXECUTING"):
            check(f"indicator showed {phase}", phase in phases_seen, " -> ".join(phases_seen))
        check("run finished despite headless TTS", page.get_by_text("DONE", exact=True).count() > 0)

        log = page.evaluate(f"""async () => {{
            const s = await (await fetch('http://localhost:{APP_PORT}/api/sessions')).json();
            const sid = s.sessions[0].id;
            const runs = (await (await fetch(`http://localhost:{APP_PORT}/api/sessions/${{sid}}/runs`)).json()).runs;
            const rid = runs[runs.length - 1].id;
            const ev = await (await fetch(`http://localhost:{APP_PORT}/api/runs/${{rid}}/events/log`)).json();
            const run = await (await fetch(`http://localhost:{APP_PORT}/api/runs/${{rid}}`)).json();
            return {{ first: ev.events[0], mode: run.input_mode }};
        }}""")
        first = log["first"]
        check("run recorded as a voice run", log["mode"] == "voice", json.dumps(log)[:200])
        check("timeline starts with voice_transcribed", first["event"] == "voice_transcribed", first["event"])
        check("transcript confidence recorded", isinstance(first["data"].get("confidence"), (int, float)),
              json.dumps(first["data"])[:200])
        browser.close()

    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {'' if ok else detail}")
    errors = [e for e in console_errors if "favicon" not in e.lower()]
    print(f"\nphases: {' -> '.join(dict.fromkeys(phases_seen))}")
    print(f"console errors: {len(errors)}")
    for e in errors[:10]:
        print("  -", e[:200])
    print(f"artifacts: {out}")
    return 0 if all(ok for _, ok, _ in results) and not errors else 1


if __name__ == "__main__":
    sys.exit(main())
