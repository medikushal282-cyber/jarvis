"""Phase 2: the approval channel and the permission flow through the API."""

import asyncio
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.runtime.approvals import ApprovalChannel
from app.runtime.events.bus import bus


def names(run_id):
    return [e["event"] for e in bus.stream(run_id).history(0)]


class TestChannel(unittest.TestCase):
    def run_async(self, coro):
        return asyncio.run(asyncio.wait_for(coro, timeout=10))

    def test_approve_resumes_the_same_run(self):
        async def scenario():
            ch = ApprovalChannel()
            task = asyncio.create_task(ch.request("run_ap1", tool="run_command",
                                                  permission="terminal.execute", summary="Execute npm install"))
            await asyncio.sleep(0.05)
            pending = ch.pending_for("run_ap1")
            self.assertEqual(len(pending), 1)
            self.assertEqual(ch.resolve("run_ap1", pending[0]["request_id"], True), "ok")
            return await task

        decision = self.run_async(scenario())
        self.assertTrue(decision.approved)
        self.assertEqual(decision.reason, "user")
        self.assertEqual(names("run_ap1"), ["permission_required", "permission_granted"])

    def test_deny(self):
        async def scenario():
            ch = ApprovalChannel()
            task = asyncio.create_task(ch.request("run_ap2", tool="delete_file",
                                                  permission="filesystem.delete", summary="Delete app.py"))
            await asyncio.sleep(0.05)
            ch.resolve("run_ap2", ch.pending_for("run_ap2")[0]["request_id"], False)
            return await task

        self.assertFalse(self.run_async(scenario()).approved)
        self.assertEqual(names("run_ap2")[-1], "permission_denied")

    def test_no_answer_is_a_deny(self):
        async def scenario():
            return await ApprovalChannel().request("run_ap3", tool="x", permission="y",
                                                   summary="z", timeout_s=0.1)

        decision = self.run_async(scenario())
        self.assertFalse(decision.approved)
        self.assertEqual(decision.reason, "timeout")

    def test_second_answer_is_refused_and_unknown_ids_are_rejected(self):
        async def scenario():
            ch = ApprovalChannel()
            task = asyncio.create_task(ch.request("run_ap4", tool="x", permission="y", summary="z"))
            await asyncio.sleep(0.05)
            rid = ch.pending_for("run_ap4")[0]["request_id"]
            results = [ch.resolve("run_ap4", rid, True), ch.resolve("run_ap4", rid, False),
                       ch.resolve("run_other", rid, True), ch.resolve("run_ap4", "req_nope", True)]
            await task
            return results

        self.assertEqual(self.run_async(scenario()), ["ok", "decided", "unknown", "unknown"])

    def test_tools_in_worker_threads_can_ask(self):
        async def scenario():
            ch = ApprovalChannel()
            ch.bind_loop(asyncio.get_running_loop())
            worker = asyncio.create_task(asyncio.to_thread(
                ch.request_sync, "run_ap5", tool="run_command", permission="terminal.execute", summary="s"))
            for _ in range(50):
                await asyncio.sleep(0.02)
                if ch.pending_for("run_ap5"):
                    break
            ch.resolve("run_ap5", ch.pending_for("run_ap5")[0]["request_id"], True)
            return await worker

        self.assertTrue(self.run_async(scenario()).approved)

    def test_blocking_ask_on_the_loop_thread_is_refused(self):
        async def scenario():
            ch = ApprovalChannel()
            ch.bind_loop(asyncio.get_running_loop())
            with self.assertRaises(RuntimeError):
                ch.request_sync("run_ap6", tool="x", permission="y", summary="z")

        self.run_async(scenario())

    def test_ending_run_denies_what_is_still_waiting(self):
        async def scenario():
            ch = ApprovalChannel()
            task = asyncio.create_task(ch.request("run_ap7", tool="x", permission="y", summary="z"))
            await asyncio.sleep(0.05)
            ch.cancel_run("run_ap7")
            return await task

        decision = self.run_async(scenario())
        self.assertFalse(decision.approved)
        self.assertEqual(decision.reason, "cancelled")


class TestPermissionFlowThroughTheApi(unittest.TestCase):
    ENV = {"JARVIS_AGENT": "scripted", "JARVIS_SCRIPTED_DELAY_MS": "0", "JARVIS_SUMMARIZE_ASYNC": "0"}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis_perm_"))
        self._saved = {k: os.environ.get(k) for k in [*self.ENV, "JARVIS_SANDBOX_ROOT"]}
        os.environ.update(self.ENV)
        os.environ["JARVIS_SANDBOX_ROOT"] = str(self.tmp)
        # One event loop for the whole test, as under uvicorn. Without the
        # context manager every request gets its own loop, closed when that
        # request ends -- which cancels a run that is waiting for an answer.
        self.client = TestClient(app)
        self.client.__enter__()
        self.sid = self.client.post("/api/sessions", json={"workspace_id": "perms"}).json()["session"]["id"]

    def tearDown(self):
        self.client.__exit__(None, None, None)
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_answering(self, decision=None, execution_mode="normal"):
        """Start the 'install' scenario and answer its permission request."""
        run_id = self.client.post(f"/api/sessions/{self.sid}/runs", json={
            "objective": "install the dependencies", "execution_mode": execution_mode,
        }).json()["run_id"]
        seen, statuses = [], []
        with self.client.stream("GET", f"/api/runs/{run_id}/events") as stream:
            for line in stream.iter_lines():
                if not line.startswith("data:"):
                    continue
                env = json.loads(line[5:])
                seen.append(env)
                if env["event"] == "permission_required":
                    statuses.append(self.client.get(f"/api/runs/{run_id}").json()["status"])
                    pending = self.client.get(f"/api/runs/{run_id}/permissions").json()["pending"]
                    res = self.client.post(f"/api/runs/{run_id}/permissions/{pending[0]['request_id']}",
                                           json={"decision": decision})
                    statuses.append(res.status_code)
                if env["event"] in ("run_completed", "run_failed"):
                    break
        return run_id, seen, statuses

    def test_allow_executes_the_command(self):
        run_id, seen, statuses = self.run_answering("approve")
        events = [e["event"] for e in seen]
        self.assertEqual(statuses, ["paused", 200], "run paused while waiting; answer accepted")
        self.assertIn("permission_granted", events)
        self.assertIn("command_completed", events)
        self.assertEqual(seen[-1]["data"]["reply"], "Dependencies installed: 42 packages added.")
        self.assertEqual(self.client.get(f"/api/runs/{run_id}").json()["status"], "completed")

    def test_deny_stops_the_action(self):
        _, seen, _ = self.run_answering("deny")
        events = [e["event"] for e in seen]
        self.assertIn("permission_denied", events)
        self.assertNotIn("command_completed", events)
        self.assertEqual(seen[-1]["data"]["reply"], "OK, I didn't run npm install.")

    def test_turbo_runs_without_asking(self):
        _, seen, statuses = self.run_answering(execution_mode="turbo")
        events = [e["event"] for e in seen]
        self.assertEqual(statuses, [], "no prompt in Turbo")
        self.assertNotIn("permission_required", events)
        granted = next(e for e in seen if e["event"] == "permission_granted")
        self.assertEqual(granted["data"]["reason"], "turbo")
        self.assertIn("command_completed", events)

    def test_bad_requests(self):
        run_id = self.client.post(f"/api/sessions/{self.sid}/runs",
                                  json={"objective": "What is 2 + 2?"}).json()["run_id"]
        self.assertEqual(self.client.post(f"/api/runs/{run_id}/permissions/req_nope",
                                          json={"decision": "approve"}).status_code, 404)
        self.assertEqual(self.client.post(f"/api/runs/{run_id}/permissions/req_nope",
                                          json={"decision": "maybe"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
