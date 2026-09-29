"""Worker panel API tests.

The worker file is redirected to a temp path (the real backend/data/
workers.json is never touched) and LiteLLM is replaced, so nothing here
reaches the network.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

import app.llm.workers as worker_store
from app.main import app

FAKE_KEY = "gsk_" + "t3st" * 10


class WorkerApiTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis_workers_"))
        self._file = worker_store.WORKERS_FILE
        worker_store.WORKERS_FILE = str(self.tmp / "workers.json")
        self.client = TestClient(app)

    def tearDown(self):
        worker_store.WORKERS_FILE = self._file
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add(self, **overrides):
        body = {"provider": "groq", "model": "llama-3.1-8b-instant", "api_key": FAKE_KEY, "priority": 5}
        body.update(overrides)
        return self.client.post("/api/workers", json=body)


class TestKeysNeverLeave(WorkerApiTestCase):
    def test_list_and_create_never_return_the_key(self):
        created = self.add()
        self.assertEqual(created.status_code, 200, created.text)
        self.assertNotIn(FAKE_KEY, created.text)
        listed = self.client.get("/api/workers")
        self.assertNotIn(FAKE_KEY, listed.text)
        self.assertEqual(listed.json()[0]["api_key_hint"], "..." + FAKE_KEY[-4:])

    def test_raw_provider_errors_are_replaced_by_a_hint(self):
        wid = self.add().json()["worker_id"]
        worker_store.mark_worker_error(wid, f"Error code: 401 - invalid api key {FAKE_KEY}", 0)
        worker = self.client.get("/api/workers").json()[0]
        self.assertNotIn("last_error", worker)
        self.assertEqual(worker["last_error_hint"], "The API key was rejected.")
        self.assertNotIn(FAKE_KEY, str(worker))


class TestValidation(WorkerApiTestCase):
    def test_rejects_unknown_provider_and_empty_fields(self):
        self.assertEqual(self.add(provider="mystery").status_code, 400)
        self.assertEqual(self.add(api_key="   ").status_code, 400)
        self.assertEqual(self.add(model="").status_code, 400)

    def test_priority_is_clamped(self):
        self.assertEqual(self.add(priority=999).json()["priority"], 100)
        wid = self.add().json()["worker_id"]
        res = self.client.patch(f"/api/workers/{wid}", json={"priority": -3})
        self.assertEqual(res.json()["priority"], 1)

    def test_enable_disable_and_reset_cooldown(self):
        wid = self.add().json()["worker_id"]
        self.client.patch(f"/api/workers/{wid}", json={"enabled": False})
        self.assertEqual(self.client.get("/api/workers").json()[0]["status"], "DISABLED")

        self.client.patch(f"/api/workers/{wid}", json={"enabled": True})
        worker_store.mark_worker_error(wid, "429 rate_limit", 300)
        self.assertEqual(self.client.get("/api/workers").json()[0]["status"], "COOLDOWN")

        self.client.patch(f"/api/workers/{wid}", json={"reset_cooldown": True})
        self.assertNotEqual(self.client.get("/api/workers").json()[0]["status"], "COOLDOWN")

    def test_blank_key_on_update_keeps_the_existing_key(self):
        wid = self.add().json()["worker_id"]
        self.client.patch(f"/api/workers/{wid}", json={"api_key": "  "})
        self.assertEqual(worker_store.load_workers()[0]["api_key"], FAKE_KEY)


class TestConnectionTest(WorkerApiTestCase):
    def test_key_goes_to_the_call_not_the_process_environment(self):
        seen = {}

        def fake_completion(**kwargs):
            seen["kwargs"] = kwargs
            seen["env_during_call"] = os.environ.get("GROQ_API_KEY")
            return object()

        before = os.environ.get("GROQ_API_KEY")
        with mock.patch("litellm.completion", side_effect=fake_completion):
            res = self.client.post("/api/workers/test", json={
                "provider": "groq", "model": "llama-3.1-8b-instant", "api_key": FAKE_KEY,
            })
        self.assertEqual(res.json(), {"success": True, "message": "Connection successful"})
        self.assertEqual(seen["kwargs"]["api_key"], FAKE_KEY)
        self.assertEqual(seen["kwargs"]["model"], "groq/llama-3.1-8b-instant")
        self.assertEqual(seen["env_during_call"], before, "the shared environment must not change")
        self.assertEqual(os.environ.get("GROQ_API_KEY"), before)

    def test_failure_returns_a_safe_reason(self):
        boom = Exception(f"AuthenticationError: 401 Invalid API Key provided: {FAKE_KEY}")
        with mock.patch("litellm.completion", side_effect=boom):
            res = self.client.post("/api/workers/test", json={
                "provider": "groq", "model": "x", "api_key": FAKE_KEY,
            })
        body = res.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["message"], "The API key was rejected.")
        self.assertNotIn(FAKE_KEY, res.text)

    def test_gemini_gets_the_right_prefix(self):
        seen = {}
        with mock.patch("litellm.completion", side_effect=lambda **kw: seen.update(kw) or object()):
            self.client.post("/api/workers/test", json={
                "provider": "gemini", "model": "gemini-1.5-flash", "api_key": FAKE_KEY,
            })
        self.assertEqual(seen["model"], "gemini/gemini-1.5-flash")


if __name__ == "__main__":
    unittest.main()
