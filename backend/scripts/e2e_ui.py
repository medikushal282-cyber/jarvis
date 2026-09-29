"""Browser end-to-end check of the JARVIS workspace UI.

Drives the running frontend in headless Edge against an *isolated* backend
running the scripted brain, so it never touches your real sandbox, never
calls an LLM, and never writes into the repository.

The frontend talks to :8006. This script rewrites those calls to the test
backend's port, so your own backend on :8006 can keep running.

Usage (from backend/):

    # 1. an isolated scripted backend (temp sandbox, temp worker pool)
    .venv\\Scripts\\python.exe scripts\\e2e_backend.py

    # 2. the frontend dev server on :3000 (npm run dev), then:
    .venv\\Scripts\\python.exe scripts\\e2e_ui.py [--out DIR]

Needs Microsoft Edge (Playwright drives it via channel="msedge"; no browser
download required). Exits non-zero if any check fails.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

FRONTEND = os.environ.get("E2E_FRONTEND", "http://localhost:3000")
APP_PORT = os.environ.get("E2E_APP_PORT", "8006")
TEST_PORT = os.environ.get("E2E_TEST_PORT", "8016")
PROMPT = "Tell JARVIS what to do..."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=os.path.join(tempfile.gettempdir(), "jarvis_e2e"),
                        help="directory for screenshots")
    out = Path(parser.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)

    results: list[tuple[str, bool, str]] = []
    console_errors: list[str] = []

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
        browser = p.chromium.launch(channel="msedge", headless=True)
        ctx = browser.new_context(viewport={"width": 1500, "height": 900})
        ctx.route(f"**://localhost:{APP_PORT}/**", reroute)
        ctx.route(f"**://127.0.0.1:{APP_PORT}/**", reroute)
        page = ctx.new_page()
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))
        page.on("dialog", lambda d: d.accept())

        page.goto(FRONTEND, wait_until="networkidle")
        page.wait_for_timeout(1500)
        page.screenshot(path=str(out / "1_empty.png"))
        check("empty state shows examples",
              page.get_by_text("Create an ecommerce website and display it").count() > 0)
        check("no absolute workspace path in the header", "C:\\" not in page.locator("header").inner_text())

        # A full run: memory, tools, a worker switch, a preview, an artifact.
        page.get_by_text("Create an ecommerce website and display it").first.click()
        page.get_by_role("button", name="Send").click()
        page.get_by_text("DONE", exact=True).wait_for(timeout=45000)
        page.wait_for_timeout(1500)
        page.screenshot(path=str(out / "2_website.png"))
        body = page.inner_text("body")
        for text in ["Created index.html", "Switching worker", "Applying what it learned",
                     "Recalled 1 past experience", "Verified result", "Saved this run to memory",
                     "Your storefront is ready"]:
            check(f"progress shows '{text}'", text in body)
        frame = page.locator("iframe")
        src = frame.first.get_attribute("src") if frame.count() else ""
        check("preview opened on the artifact URL", "/artifacts/" in (src or ""), src or "no iframe")
        check("artifact card listed", page.get_by_role("button", name="index.html").count() > 0)
        check("no artifact card named after a raw URL", "/api/runs/" not in page.locator("main").inner_text())
        check("sidebar lists the workspace the run created",
              "No workspaces yet" not in page.locator("aside").inner_text())
        check("no model reasoning shown", "chain of thought" not in body.lower())

        # A follow-up in the same session.
        page.get_by_placeholder(PROMPT).fill("What is 2 + 2?")
        page.keyboard.press("Enter")
        page.get_by_text("That's 4.").last.wait_for(timeout=30000)
        check("question answered in the same session", True)

        # A brain that raises.
        page.get_by_placeholder(PROMPT).fill("crash please")
        page.keyboard.press("Enter")
        page.get_by_text("FAILED", exact=True).last.wait_for(timeout=30000)
        page.wait_for_timeout(800)
        page.screenshot(path=str(out / "3_crash.png"))
        check("crash shows the error message", "scripted crash" in page.inner_text("body"))

        # Reload: the same session and its history come back.
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(2500)
        page.screenshot(path=str(out / "4_reloaded.png"))
        body = page.inner_text("body")
        check("history restored after reload",
              "What is 2 + 2?" in body and "Create an ecommerce website" in body)
        check("past run keeps its artifact", page.get_by_role("button", name="index.html").count() > 0)

        # Workers panel: add, test, pause, reorder, remove. Keys never shown.
        key = "gsk_" + "e2e" * 12 + "WXYZ"
        panel = page.locator("div.w-96")
        page.get_by_role("button", name="WORKERS").click()
        page.get_by_text("No workers yet").wait_for(timeout=10000)
        check("worker panel opens on an empty pool", True)
        page.get_by_role("button", name="+ Add Worker").click()
        page.get_by_placeholder("Stored on this machine only").fill(key)
        page.get_by_role("button", name="Test connection").click()
        page.wait_for_function("() => !document.body.innerText.includes('Testing…')", timeout=30000)
        text = panel.inner_text()
        check("connection test shows a plain reason",
              any(m in text for m in ("API key was rejected", "Couldn't reach", "Connection successful",
                                      "provider returned an error", "Rate limited", "didn't answer")),
              text[-160:])
        check("the key is never shown back", key not in page.inner_text("body"))
        page.get_by_role("button", name="Save worker").click()
        page.get_by_text("KEY ...WXYZ").wait_for(timeout=10000)
        page.screenshot(path=str(out / "5_workers.png"))
        check("saved worker shows READY with a key hint only",
              "READY" in panel.inner_text() and key not in page.inner_text("body"))
        page.get_by_role("button", name="PAUSE").click()
        page.get_by_text("DISABLED", exact=True).wait_for(timeout=10000)
        page.get_by_role("button", name="ENABLE").click()
        page.get_by_text("READY", exact=True).wait_for(timeout=10000)
        check("pause and enable work", True)
        page.get_by_role("button", name="Raise priority").click()
        page.wait_for_timeout(800)
        check("priority can be raised", "11" in panel.inner_text())
        page.get_by_role("button", name="REMOVE").click()
        page.get_by_text("No workers yet").wait_for(timeout=10000)
        check("worker can be removed", True)

        browser.close()

    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {'' if ok else detail}")
    errors = [e for e in console_errors if "favicon" not in e.lower()]
    print(f"\nconsole errors: {len(errors)}")
    for e in errors[:10]:
        print("  -", e[:200])
    print(f"screenshots: {out}")
    return 0 if all(ok for _, ok, _ in results) and not errors else 1


if __name__ == "__main__":
    sys.exit(main())
