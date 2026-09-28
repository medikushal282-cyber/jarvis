"""Session store and run lifecycle tests.

Covers the criteria in docs/runtime/SESSIONS.md section 7, including the P0
path-traversal fix and the guarantee that a crashed run still produces a
persisted result.
"""

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path

from app.runtime import config
from app.runtime.events.bus import bus
from app.runtime.models import Session, Turn
from app.runtime.protocols import RunOutcome, RunRequest
from app.runtime.sessions.store import RunStore, SessionStore, WorkspaceStore


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._prev = config.sandbox_root
        config.sandbox_root = lambda: self.tmp  # type: ignore[assignment]
        self.workspaces = WorkspaceStore()
        self.sessions = SessionStore(self.workspaces)
        self.runs = RunStore(self.workspaces)

    def tearDown(self):
        config.sandbox_root = self._prev  # type: ignore[assignment]
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestWorkspaceSecurity(StoreTestCase):
    def test_traversal_name_cannot_escape(self):
        """Criterion 2: POST a workspace named ../../evil -> rejected."""
        meta = self.workspaces.create("../../evil")
        created = Path(meta["root_path"]).resolve()
        self.assertTrue(created.is_relative_to(self.tmp.resolve()))
        self.assertEqual(meta["id"], "evil")

    def test_traversal_id_cannot_delete_outside(self):
        """Criterion 3: the old code ran shutil.rmtree on unsanitised input."""
        victim = self.tmp.parent / "victim_dir"
        victim.mkdir(exist_ok=True)
        try:
            for attack in ["../victim_dir", "..", "../../", "a/../../victim_dir"]:
                with self.subTest(attack=attack), self.assertRaises(ValueError):
                    self.workspaces.delete(attack)
            self.assertTrue(victim.exists(), "victim directory must survive")
        finally:
            shutil.rmtree(victim, ignore_errors=True)

    def test_refuses_to_delete_the_root(self):
        with self.assertRaises(ValueError):
            self.workspaces.delete(".")

    def test_normal_create_and_delete(self):
        self.workspaces.create("My Project")
        self.assertTrue(self.workspaces.exists("my_project"))
        self.assertTrue(self.workspaces.delete("my_project"))
        self.assertFalse(self.workspaces.exists("my_project"))


class TestSessionStore(StoreTestCase):
    def test_create_get_roundtrip(self):
        session = self.sessions.create("ws1", "usr_a", "Deck work")
        self.sessions.invalidate(session.id)
        loaded = self.sessions.get(session.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.title, "Deck work")
        self.assertEqual(loaded.user_id, "usr_a")
        self.assertEqual(loaded.workspace_id, "ws1")

    def test_append_turn_persists(self):
        session = self.sessions.create("ws1", "usr_a")
        self.sessions.append_turn(session.id, Turn(role="user", content="hello"))
        self.sessions.invalidate(session.id)
        loaded = self.sessions.get(session.id)
        self.assertEqual(len(loaded.turns), 1)
        self.assertEqual(loaded.turns[0].content, "hello")

    def test_title_derives_from_first_user_turn(self):
        session = self.sessions.create("ws1", "usr_a")
        self.sessions.append_turn(
            session.id, Turn(role="user", content="Create an IPsec deck")
        )
        self.assertEqual(self.sessions.get(session.id).title, "Create an IPsec deck")

    def test_reads_legacy_conversation_files(self):
        """Existing sandbox/<ws>/conversations/*.json must keep working."""
        import json

        ws = self.workspaces.create("legacy_ws")
        conv_dir = Path(ws["root_path"]) / "conversations"
        conv_dir.mkdir(parents=True, exist_ok=True)
        (conv_dir / "conv_old123.json").write_text(
            json.dumps(
                {
                    "id": "conv_old123",
                    "title": "old chat",
                    "created_at": "2026-09-19T09:07:13Z",
                    "messages": [
                        {"role": "user", "content": "hi", "timestamp": "2026-09-19T09:16:16Z"},
                        {"role": "assistant", "content": "hello", "timestamp": "2026-09-19T09:16:17Z"},
                    ],
                    "context_summary": "greeting exchange",
                }
            ),
            encoding="utf-8",
        )
        loaded = self.sessions.get("conv_old123")
        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded.turns), 2)
        self.assertEqual(loaded.turns[0].content, "hi")
        self.assertEqual(loaded.context_summary, "greeting exchange")
        self.assertEqual(loaded.workspace_id, "legacy_ws")

    def test_list_filters_by_user_and_status(self):
        a = self.sessions.create("ws1", "usr_a", "A")
        self.sessions.create("ws1", "usr_b", "B")
        mine = self.sessions.list(user_id="usr_a")
        self.assertEqual([s["id"] for s in mine], [a.id])

        self.sessions.delete(a.id)
        self.assertEqual(self.sessions.list(user_id="usr_a", status="active"), [])
        self.assertEqual(len(self.sessions.list(user_id="usr_a", status="archived")), 1)

    def test_atomic_write_leaves_no_tmp_files(self):
        session = self.sessions.create("ws1", "usr_a")
        self.sessions.save(session)
        leftovers = list((self.tmp / "ws1" / "sessions").glob("*.tmp"))
        self.assertEqual(leftovers, [])


class TestRunLifecycle(StoreTestCase):
    """The service, driven by stub runners -- no LLM, no network."""

    def service(self):
        from app.runtime.sessions.service import RunService

        return RunService(self.sessions, self.runs, self.workspaces)

    def run_with(self, runner, objective="do a thing", session_id=None):
        svc = self.service()

        async def scenario():
            import app.runtime.sessions.service as service_mod

            original = service_mod.get_agent_runner
            service_mod.get_agent_runner = lambda: runner
            try:
                run = await svc.start_run(
                    objective, session_id=session_id, workspace_id="ws1"
                )
                task = service_mod._active_tasks.get(run.id)
                if task is not None:
                    try:
                        await asyncio.wait_for(asyncio.shield(task), timeout=10)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass
                return svc, run
            finally:
                service_mod.get_agent_runner = original

        return asyncio.run(scenario())

    def test_successful_run_produces_a_result_and_turns(self):
        class Good:
            async def run(self, request: RunRequest, emit) -> RunOutcome:
                emit("run_started", {"objective": request.objective})
                emit("file_created", {"path": "app.py", "bytes": 42})
                emit("run_completed", {"status": "completed", "summary": "made app.py"})
                return RunOutcome(status="completed", reply="Created app.py.")

        svc, run = self.run_with(Good())
        stored = svc.get_run(run.id, "ws1")
        self.assertEqual(stored.status, "completed")

        result = svc.get_result(run.id, "ws1")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["artifacts"]), 1)
        self.assertEqual(result["files_created"], ["app.py"])

        session = self.sessions.get(run.session_id, "ws1")
        self.assertEqual([t.role for t in session.turns], ["user", "assistant"])
        self.assertEqual(session.turns[1].content, "Created app.py.")

    def test_crashing_run_still_persists_a_result(self):
        """Criterion 5."""

        class Boom:
            async def run(self, request: RunRequest, emit) -> RunOutcome:
                emit("run_started", {"objective": request.objective})
                emit("file_created", {"path": "partial.py", "bytes": 1})
                raise ValueError("exploded mid-run")

        svc, run = self.run_with(Boom())
        stored = svc.get_run(run.id, "ws1")
        self.assertEqual(stored.status, "failed")

        result = svc.get_result(run.id, "ws1")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(result["artifacts"]), 1, "partial work survives")
        self.assertTrue(result["errors"])
        self.assertIn("exploded mid-run", result["errors"][0]["message"])

        session = self.sessions.get(run.session_id, "ws1")
        self.assertEqual(session.turns[-1].role, "assistant")

    def test_runner_that_forgets_the_terminal_event(self):
        """The runtime synthesises one rather than leaving the run hanging."""

        class Forgetful:
            async def run(self, request: RunRequest, emit) -> RunOutcome:
                emit("run_started", {"objective": request.objective})
                emit("agent_thinking", {"summary": "working"})
                return RunOutcome(status="completed", reply="silently done")

        svc, run = self.run_with(Forgetful())
        self.assertEqual(svc.get_run(run.id, "ws1").status, "completed")
        events = svc.read_events(run.id, "ws1")
        self.assertIn("run_completed", [e["event"] for e in events])

    def test_two_runs_share_a_session_and_accumulate_context(self):
        """Criterion 1: 'create a deck' then 'make slide 4 darker'."""
        seen = {}

        class Recorder:
            async def run(self, request: RunRequest, emit) -> RunOutcome:
                seen[request.objective] = list(request.conversation)
                emit("run_started", {"objective": request.objective})
                emit("run_completed", {"status": "completed", "summary": "ok"})
                return RunOutcome(status="completed", reply=f"did: {request.objective}")

        svc, first = self.run_with(Recorder(), "create a presentation")
        _, second = self.run_with(
            Recorder(), "make slide 4 darker", session_id=first.session_id
        )

        self.assertEqual(first.session_id, second.session_id)

        opening = seen["create a presentation"]
        self.assertEqual(
            [t["content"] for t in opening],
            ["create a presentation"],
            "the first run sees only its own utterance",
        )

        follow_up = seen["make slide 4 darker"]
        self.assertTrue(follow_up, "the second run must see the first")
        self.assertIn(
            "create a presentation", [t["content"] for t in follow_up]
        )
        self.assertIn("did: create a presentation", [t["content"] for t in follow_up])

    def test_everything_survives_a_restart(self):
        """Criterion 4: fresh stores, cleared bus, data still there."""

        class Good:
            async def run(self, request: RunRequest, emit) -> RunOutcome:
                emit("run_started", {"objective": request.objective})
                emit("file_created", {"path": "kept.py", "bytes": 7})
                emit("run_completed", {"status": "completed", "summary": "kept"})
                return RunOutcome(status="completed", reply="kept")

        svc, run = self.run_with(Good())

        # Simulate a process restart: new stores, no caches, no bus state.
        bus.discard(run.id)
        fresh_ws = WorkspaceStore()
        fresh_sessions = SessionStore(fresh_ws)
        fresh_runs = RunStore(fresh_ws)
        from app.runtime.sessions.service import RunService

        reborn = RunService(fresh_sessions, fresh_runs, fresh_ws)

        self.assertEqual(reborn.get_run(run.id, "ws1").status, "completed")
        self.assertEqual(len(reborn.read_events(run.id, "ws1")), 3)
        self.assertEqual(reborn.get_result(run.id, "ws1")["files_created"], ["kept.py"])
        self.assertEqual(len(fresh_sessions.get(run.session_id, "ws1").turns), 2)


if __name__ == "__main__":
    unittest.main()
