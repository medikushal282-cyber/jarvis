"""HTTP-level tests for the runtime endpoints.

Runs against the real FastAPI app with the null agent runner, so there is no
LLM call, no network and no workspace mutation.
"""

import os
import shutil
import tempfile
import unittest

# Must be set before app.runtime.config is imported.
_TMP = tempfile.mkdtemp(prefix="jarvis_api_test_")
os.environ["JARVIS_SANDBOX_ROOT"] = _TMP
os.environ["JARVIS_AGENT"] = "null"
os.environ["JARVIS_SUMMARIZE_ASYNC"] = "0"
os.environ["JARVIS_SSE_HEARTBEAT_S"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


class ApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_TMP, ignore_errors=True)

    def new_session(self, title="Test Session"):
        res = self.client.post(
            "/api/sessions", json={"workspace_id": "testws", "title": title}
        )
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["session"]["id"]


class TestHealth(ApiTestCase):
    def test_health(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "healthy")


class TestWorkspaceSecurity(ApiTestCase):
    def test_traversal_name_is_rejected_or_contained(self):
        res = self.client.post("/api/workspaces", json={"name": "../../evil"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["workspace"]["id"], "evil")
        self.assertTrue(
            os.path.realpath(res.json()["workspace"]["root_path"]).startswith(
                os.path.realpath(_TMP)
            ),
            "workspace must live inside the sandbox root",
        )

    def test_traversal_delete_is_rejected(self):
        """The old code ran shutil.rmtree on an unsanitised path parameter."""
        for attack in ["..", "%2e%2e", "a%2F..%2F..%2Fb"]:
            with self.subTest(attack=attack):
                res = self.client.delete(f"/api/workspaces/{attack}")
                self.assertIn(res.status_code, (400, 404, 405), res.text)

    def test_empty_name_rejected(self):
        res = self.client.post("/api/workspaces", json={"name": "   "})
        self.assertEqual(res.status_code, 400)


class TestSessionCrud(ApiTestCase):
    def test_create_list_get_patch_delete(self):
        sid = self.new_session("My Session")

        listing = self.client.get("/api/sessions?workspace_id=testws").json()
        self.assertIn(sid, [s["id"] for s in listing["sessions"]])

        got = self.client.get(f"/api/sessions/{sid}").json()
        self.assertEqual(got["title"], "My Session")
        self.assertEqual(got["turns"], [])
        self.assertIn("messages", got, "legacy alias for the current UI")

        patched = self.client.patch(f"/api/sessions/{sid}", json={"title": "Renamed"})
        self.assertEqual(patched.json()["session"]["title"], "Renamed")

        self.assertEqual(self.client.delete(f"/api/sessions/{sid}").status_code, 200)
        self.assertEqual(
            self.client.get(f"/api/sessions/{sid}").json()["status"], "archived"
        )

    def test_missing_session_is_404(self):
        self.assertEqual(self.client.get("/api/sessions/ses_nope").status_code, 404)

    def test_malformed_session_id_is_400(self):
        res = self.client.get("/api/sessions/..")
        self.assertIn(res.status_code, (400, 404))

    def test_append_turn(self):
        sid = self.new_session()
        res = self.client.post(
            f"/api/sessions/{sid}/turns", json={"role": "user", "content": "hello"}
        )
        self.assertEqual(res.status_code, 200)
        turns = self.client.get(f"/api/sessions/{sid}/turns").json()["turns"]
        self.assertEqual(turns[0]["content"], "hello")


class TestRunFlow(ApiTestCase):
    def test_legacy_post_runs_still_works(self):
        """The current frontend posts here with no session."""
        res = self.client.post("/api/runs/", json={"objective": "say hi"})
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertTrue(body["run_id"].startswith("run_"))
        self.assertTrue(body["session_id"].startswith("ses_"))

    def test_run_inside_a_session_produces_a_result(self):
        sid = self.new_session()
        res = self.client.post(
            f"/api/sessions/{sid}/runs", json={"objective": "do a thing"}
        )
        self.assertEqual(res.status_code, 200, res.text)
        run_id = res.json()["run_id"]

        # The null runner completes immediately; the SSE stream drains it.
        with self.client.stream("GET", f"/api/runs/{run_id}/events") as stream:
            frames = []
            for line in stream.iter_lines():
                if line.startswith("event:"):
                    frames.append(line.split(":", 1)[1].strip())
                if frames and frames[-1] in ("run_completed", "run_failed"):
                    break
        self.assertIn("run_started", frames)
        self.assertIn("run_completed", frames)

        result = self.client.get(f"/api/runs/{run_id}/result")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["status"], "completed")

        log = self.client.get(f"/api/runs/{run_id}/events/log").json()
        self.assertGreaterEqual(log["count"], 3)

        run = self.client.get(f"/api/runs/{run_id}").json()
        self.assertEqual(run["status"], "completed")
        self.assertIn("state", run, "legacy alias the current UI reads")

        session = self.client.get(f"/api/sessions/{sid}").json()
        self.assertEqual([t["role"] for t in session["turns"]], ["user", "assistant"])

    def test_sse_resumes_from_last_event_id(self):
        sid = self.new_session()
        run_id = self.client.post(
            f"/api/sessions/{sid}/runs", json={"objective": "resume me"}
        ).json()["run_id"]

        with self.client.stream("GET", f"/api/runs/{run_id}/events") as s:
            for line in s.iter_lines():
                if line.startswith("event: run_completed"):
                    break

        # Reconnect as a browser would, asking for everything after seq 1.
        res = self.client.get(f"/api/runs/{run_id}/events?from_seq=1")
        self.assertEqual(res.status_code, 200)
        seqs = [
            int(l.split(":", 1)[1].strip())
            for l in res.text.splitlines()
            if l.startswith("id:")
        ]
        self.assertTrue(seqs, "resumed stream must carry event ids")
        self.assertTrue(all(s > 1 for s in seqs), f"no duplicates expected: {seqs}")

    def test_missing_run_is_404(self):
        self.assertEqual(self.client.get("/api/runs/run_nope/result").status_code, 404)

    def test_cancel_inactive_run_is_409(self):
        self.assertEqual(
            self.client.post("/api/runs/run_nope/cancel").status_code, 409
        )


class TestArtifactSecurity(ApiTestCase):
    def test_artifact_traversal_is_rejected(self):
        """Criterion 4 in docs/runtime/RESULTS.md."""
        sid = self.new_session()
        run_id = self.client.post(
            f"/api/sessions/{sid}/runs", json={"objective": "x"}
        ).json()["run_id"]

        # A bare ".." is normalised out of the URL by the client and never
        # reaches the handler, so these are the encoded forms that do.
        for attack in [
            "..%2F..%2F..%2Fetc%2Fpasswd",
            "%2e%2e%2f%2e%2e%2fetc",
            "..%5C..%5Cwindows",
            "art_nope",
        ]:
            with self.subTest(attack=attack):
                res = self.client.get(f"/api/runs/{run_id}/artifacts/{attack}")
                self.assertIn(res.status_code, (400, 404), res.text)

    def test_poisoned_artifact_path_cannot_escape_the_workspace(self):
        """The stored path is re-checked even though we generated it."""
        from app.runtime.ids import resolve_within
        from app.runtime.sessions.store import workspace_store

        ws_dir = workspace_store.dir_for("testws")
        for rel in ["../../../etc/passwd", "..\..\windows\system32", "C:/Windows"]:
            with self.subTest(rel=rel), self.assertRaises(ValueError):
                resolve_within(ws_dir, rel)


class TestVoice(ApiTestCase):
    def test_config_is_always_available(self):
        """The UI reads this to degrade instead of throwing."""
        body = self.client.get("/api/voice/config").json()
        self.assertIn("stt_enabled", body)
        self.assertIn("tts_backend", body)
        self.assertIn("max_utterance_s", body)
        self.assertIn("audio/webm", body["allowed_mime"])

    def test_rejects_unsupported_audio_type(self):
        res = self.client.post(
            "/api/voice/transcribe",
            files={"file": ("a.txt", b"not audio", "text/plain")},
        )
        self.assertEqual(res.status_code, 415)

    def test_rejects_empty_audio(self):
        res = self.client.post(
            "/api/voice/transcribe",
            files={"file": ("a.webm", b"", "audio/webm")},
        )
        self.assertEqual(res.status_code, 400)

    def test_speakable_transform(self):
        res = self.client.post(
            "/api/voice/speakable",
            json={"text": "Done. I wrote:\n```python\nprint(1)\n```\nSee `decks/2026/IPsec.pptx`."},
        )
        spoken = res.json()["text"]
        self.assertNotIn("```", spoken)
        self.assertNotIn("decks/2026", spoken)
        self.assertIn("IPsec.pptx", spoken)


if __name__ == "__main__":
    unittest.main()
