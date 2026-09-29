"""Scripted runner + Phase 0 contract tests.

The scripted runner is what the interface is built against before the real
brain emits everything, so these check that it honours the same contract the
real one must: run_started first, one terminal event last, and working links
in every artifact it announces.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.runtime.events import catalog

TERMINAL = ("run_completed", "run_failed", "run_cancelled")


def read_events(client, run_id):
    """Drain a run's SSE stream the way a browser onmessage sees it."""
    out = []
    with client.stream("GET", f"/api/runs/{run_id}/events") as stream:
        for line in stream.iter_lines():
            if not line.startswith("data:"):
                continue
            envelope = json.loads(line.split(":", 1)[1])
            if envelope["event"] in ("stream_ready", "heartbeat"):
                continue
            out.append(envelope)
            if envelope["event"] in TERMINAL:
                break
    return out


class ScriptedTestCase(unittest.TestCase):
    ENV = {
        "JARVIS_AGENT": "scripted",
        "JARVIS_SCRIPTED_DELAY_MS": "0",
        "JARVIS_SUMMARIZE_ASYNC": "0",
    }

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis_scripted_"))
        self._saved = {k: os.environ.get(k) for k in [*self.ENV, "JARVIS_SANDBOX_ROOT"]}
        os.environ.update(self.ENV)
        os.environ["JARVIS_SANDBOX_ROOT"] = str(self.tmp)
        self.client = TestClient(app)
        res = self.client.post("/api/sessions", json={"workspace_id": "demo", "title": "t"})
        self.session_id = res.json()["session"]["id"]

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_objective(self, objective, **extra):
        res = self.client.post(
            f"/api/sessions/{self.session_id}/runs",
            json={"objective": objective, **extra},
        )
        self.assertEqual(res.status_code, 200, res.text)
        run_id = res.json()["run_id"]
        return run_id, read_events(self.client, run_id)


class TestWebsiteScenario(ScriptedTestCase):
    def test_full_event_vocabulary_in_order(self):
        run_id, events = self.run_objective("Create an ecommerce website and display it")
        names = [e["event"] for e in events]

        self.assertEqual(names[0], "run_started")
        self.assertEqual(names[-1], "run_completed")
        self.assertEqual(sum(n in TERMINAL for n in names), 1, "exactly one terminal event")
        for expected in ("memory_recalled", "memory_applied", "tool_started", "file_created",
                         "worker_switching", "browser_action", "artifact_created",
                         "verification_completed", "memory_recorded"):
            self.assertIn(expected, names)
        # The worker switch happens mid-run: work continues after it.
        self.assertLess(names.index("worker_switching"), names.index("artifact_created"))
        self.assertEqual([e["seq"] for e in events], sorted(e["seq"] for e in events))

    def test_artifact_link_in_the_event_actually_serves_the_file(self):
        run_id, events = self.run_objective("Build a website")
        artifact = next(e["data"] for e in events if e["event"] == "artifact_created")

        self.assertEqual(
            set(artifact),
            {"artifact_id", "filename", "mime_type", "size", "preview_supported", "secure_url"},
        )
        self.assertNotIn("path", artifact, "the public contract carries no filesystem path")

        res = self.client.get(artifact["secure_url"])
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIn("Northwind Goods", res.text)
        self.assertIn("sandbox", res.headers.get("content-security-policy", ""))

    def test_result_ids_match_the_announced_artifact(self):
        run_id, events = self.run_objective("Build a website")
        announced = next(e["data"]["artifact_id"] for e in events if e["event"] == "artifact_created")
        result = self.client.get(f"/api/runs/{run_id}/result").json()
        self.assertIn(announced, [a["id"] for a in result["artifacts"]])
        # Stable across rebuilds: asking again yields the same ids.
        again = self.client.get(f"/api/runs/{run_id}/result").json()
        self.assertEqual([a["id"] for a in result["artifacts"]], [a["id"] for a in again["artifacts"]])

    def test_files_land_in_the_sandbox_not_the_repository(self):
        self.run_objective("Build a website")
        self.assertTrue((self.tmp / "demo" / "scripted_demo" / "index.html").is_file())
        repo_root = Path(__file__).resolve().parents[2]
        self.assertFalse((repo_root / "scripted_demo").exists())


class TestOtherScenarios(ScriptedTestCase):
    def test_question_uses_no_tools(self):
        _, events = self.run_objective("What is 2 + 2?")
        names = [e["event"] for e in events]
        self.assertNotIn("tool_started", names)
        self.assertEqual(events[-1]["data"]["reply"], "That's 4.")

    def test_missing_file_fails_the_tool_not_the_run(self):
        run_id, events = self.run_objective("Read missing.txt")
        names = [e["event"] for e in events]
        self.assertIn("tool_failed", names)
        self.assertEqual(names[-1], "run_completed")
        result = self.client.get(f"/api/runs/{run_id}/result").json()
        self.assertEqual(result["errors"][0]["type"], "ToolFailed")

    def test_crash_becomes_run_failed(self):
        run_id, events = self.run_objective("crash please")
        self.assertEqual(events[-1]["event"], "run_failed")
        self.assertIn("scripted crash", events[-1]["data"]["message"])
        self.assertEqual(self.client.get(f"/api/runs/{run_id}").json()["status"], "failed")


class TestExecutionMode(ScriptedTestCase):
    def test_turbo_reaches_the_brain_and_the_run_record(self):
        run_id, events = self.run_objective("What is 2 + 2?", execution_mode="turbo")
        self.assertEqual(events[0]["data"]["execution_mode"], "turbo")
        self.assertEqual(self.client.get(f"/api/runs/{run_id}").json()["execution_mode"], "turbo")

    def test_defaults_to_normal(self):
        run_id, events = self.run_objective("What is 2 + 2?")
        self.assertEqual(events[0]["data"]["execution_mode"], "normal")

    def test_rejects_unknown_modes(self):
        res = self.client.post(
            f"/api/sessions/{self.session_id}/runs",
            json={"objective": "x", "execution_mode": "unrestricted"},
        )
        self.assertEqual(res.status_code, 400)


class TestPermissionNames(unittest.TestCase):
    def test_old_approval_names_arrive_as_permission_events(self):
        self.assertEqual(catalog.canonical("approval_required"), "permission_required")
        self.assertEqual(catalog.canonical("approval_requested"), "permission_required")
        self.assertEqual(catalog.canonical("approval_granted"), "permission_granted")
        self.assertEqual(catalog.canonical("approval_rejected"), "permission_denied")

    def test_new_events_are_known(self):
        for name in ("permission_required", "permission_granted", "permission_denied",
                     "worker_switching", "artifact_created"):
            self.assertTrue(catalog.is_known(name), name)


if __name__ == "__main__":
    unittest.main()
