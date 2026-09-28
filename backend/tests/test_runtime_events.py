"""Event bus tests.

Covers the seven acceptance criteria in docs/runtime/EVENTS.md section 7.
"""

import asyncio
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from app.runtime.events import catalog
from app.runtime.events.bus import EventBus, RunStream
from app.runtime.events.emitter import RunEmitter


def drain(stream, from_seq=0, stop_on_terminal=True, timeout=5.0):
    """Collect events from a subscription, ignoring transport frames."""

    async def _run():
        out = []
        async for envelope in stream.subscribe(from_seq):
            if envelope["event"] in (catalog.STREAM_READY, catalog.HEARTBEAT):
                continue
            out.append(envelope)
            if stop_on_terminal and catalog.is_terminal(envelope["event"]):
                break
        return out

    return asyncio.wait_for(_run(), timeout=timeout)


class EventBusTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bus = EventBus()
        self.run_id = "run_test001"
        self.log = self.tmp / "events.ndjson"
        self.bus.configure_run(
            self.run_id, log_path=self.log, session_id="ses_a", user_id="usr_local"
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def stream(self):
        return self.bus.stream(self.run_id)


class TestOrderingAndEnvelope(EventBusTestCase):
    def test_seq_is_monotonic_from_one(self):
        s = self.stream()
        seqs = [s.publish("agent_thinking", {"summary": str(i)})["seq"] for i in range(5)]
        self.assertEqual(seqs, [1, 2, 3, 4, 5])

    def test_envelope_carries_identity(self):
        env = self.stream().publish("run_started", {"objective": "demo"}, node="brain")
        self.assertEqual(env["run_id"], self.run_id)
        self.assertEqual(env["session_id"], "ses_a")
        self.assertEqual(env["user_id"], "usr_local")
        self.assertEqual(env["node"], "brain")
        self.assertTrue(env["ts"].endswith("Z"))

    def test_legacy_name_is_canonicalised(self):
        env = self.stream().publish("approval_required", {"tool": "delete_file"})
        self.assertEqual(env["event"], catalog.APPROVAL_REQUESTED)


class TestFanOut(EventBusTestCase):
    def test_two_subscribers_both_see_everything(self):
        """Criterion 2: two tabs, identical complete timelines."""

        async def scenario():
            s = self.stream()
            s.publish("run_started", {"objective": "demo"})
            a = asyncio.create_task(drain(s))
            b = asyncio.create_task(drain(s))
            await asyncio.sleep(0.05)
            s.publish("file_created", {"path": "app.py", "bytes": 3})
            s.publish("run_completed", {"status": "completed"})
            return await asyncio.gather(a, b)

        got_a, got_b = asyncio.run(scenario())
        self.assertEqual(
            [(e["seq"], e["event"]) for e in got_a],
            [(e["seq"], e["event"]) for e in got_b],
        )
        self.assertEqual([e["seq"] for e in got_a], [1, 2, 3])

    def test_late_subscriber_replays_from_buffer(self):
        """Criterion 1: refresh mid-run, timeline intact, no gaps."""

        async def scenario():
            s = self.stream()
            for i in range(3):
                s.publish("agent_thinking", {"summary": f"step {i}"})
            late = asyncio.create_task(drain(s))
            await asyncio.sleep(0.05)
            s.publish("run_completed", {"status": "completed"})
            return await late

        events = asyncio.run(scenario())
        self.assertEqual([e["seq"] for e in events], [1, 2, 3, 4])

    def test_resume_from_seq_has_no_duplicates(self):
        async def scenario():
            s = self.stream()
            for i in range(5):
                s.publish("agent_thinking", {"summary": str(i)})
            resumed = asyncio.create_task(drain(s, from_seq=3))
            await asyncio.sleep(0.05)
            s.publish("run_completed", {"status": "completed"})
            return await resumed

        events = asyncio.run(scenario())
        self.assertEqual([e["seq"] for e in events], [4, 5, 6])


class TestPersistence(EventBusTestCase):
    def test_log_survives_a_fresh_reader(self):
        """Criterion 3: restart the process, timeline still readable."""
        s = self.stream()
        s.publish("run_started", {"objective": "demo"})
        s.publish("file_created", {"path": "a.py", "bytes": 1})
        s.publish("run_completed", {"status": "completed"})
        s.flush()

        reloaded = RunStream(self.run_id, log_path=self.log).read_log()
        self.assertEqual(len(reloaded), 3)
        self.assertEqual(reloaded[0]["event"], "run_started")
        self.assertEqual(reloaded[-1]["event"], "run_completed")

    def test_log_lines_are_valid_json(self):
        s = self.stream()
        s.publish("agent_thinking", {"summary": "x"})
        s.flush()
        for line in self.log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                json.loads(line)

    def test_read_log_from_seq(self):
        s = self.stream()
        for i in range(4):
            s.publish("agent_thinking", {"summary": str(i)})
        s.flush()
        tail = RunStream(self.run_id, log_path=self.log).read_log(from_seq=2)
        self.assertEqual([e["seq"] for e in tail], [3, 4])


class TestSafety(EventBusTestCase):
    def test_redacts_secret_values(self):
        """Criterion 6: an API key in a payload arrives redacted."""
        # Built rather than written out, so nothing key-shaped sits in the
        # repo for secret scanners to flag.
        fake_key = "gsk_" + "f4ke" * 8
        os.environ["GROQ_API_KEY"] = fake_key
        try:
            env = self.stream().publish(
                "agent_thinking",
                {"summary": f"used {fake_key} to call groq"},
            )
            self.assertNotIn(fake_key, json.dumps(env))
            self.assertIn("[REDACTED]", env["data"]["summary"])
        finally:
            os.environ.pop("GROQ_API_KEY", None)

    def test_redacts_secret_key_names(self):
        env = self.stream().publish(
            "tool_started",
            {"tool": "http_get", "args": {"Authorization": "Bearer abc", "url": "x"}},
        )
        self.assertEqual(env["data"]["args"]["Authorization"], "[REDACTED]")
        self.assertEqual(env["data"]["args"]["url"], "x")

    def test_truncates_huge_strings(self):
        env = self.stream().publish("agent_thinking", {"summary": "x" * 50_000})
        self.assertLess(len(env["data"]["summary"]), 20_000)

    def test_non_serialisable_payload_does_not_raise(self):
        class Weird:
            def __repr__(self):
                return "<weird>"

        env = self.stream().publish("agent_thinking", {"summary": Weird()})
        self.assertEqual(env["data"]["summary"], "<weird>")
        json.dumps(env)

    def test_emit_never_raises(self):
        emitter = RunEmitter(self.run_id, event_bus=self.bus)
        emitter.emit("agent_thinking", {"summary": "fine"})
        emitter.emit("agent_thinking", None)
        emitter.emit("totally_unknown_event", {"x": 1})
        emitter("callable_form_works", {})

    def test_emit_from_thread(self):
        """Criterion 5: emit from inside asyncio.to_thread delivers."""

        async def scenario():
            emitter = RunEmitter(self.run_id, event_bus=self.bus)
            await asyncio.to_thread(
                lambda: emitter.emit("agent_thinking", {"summary": "from thread"})
            )
            return self.stream().history()

        events = asyncio.run(scenario())
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["data"]["summary"], "from thread")


class TestBackpressureAndCleanup(EventBusTestCase):
    def test_slow_subscriber_does_not_stall_publisher(self):
        """Criterion 4: a flood neither stalls the run nor exhausts memory."""

        async def scenario():
            s = self.stream()
            started = asyncio.Event()

            async def slow():
                async for _ in s.subscribe(0):
                    started.set()
                    await asyncio.sleep(10)  # never drains

            task = asyncio.create_task(slow())
            await asyncio.sleep(0.05)
            for i in range(5000):
                s.publish("agent_thinking", {"summary": str(i)})
            task.cancel()
            return s.seq

        seq = asyncio.run(asyncio.wait_for(scenario(), timeout=20))
        self.assertEqual(seq, 5000)

    def test_ring_buffer_is_bounded(self):
        s = self.stream()
        for i in range(3000):
            s.publish("agent_thinking", {"summary": str(i)})
        self.assertLessEqual(len(s._ring), 1000)

    def test_replay_past_the_ring_falls_back_to_the_log(self):
        s = self.stream()
        for i in range(2000):
            s.publish("agent_thinking", {"summary": str(i)})
        s.flush()
        full = s.history()
        self.assertEqual(len(full), 2000)
        self.assertEqual(full[0]["seq"], 1)
        self.assertEqual([e["seq"] for e in full], list(range(1, 2001)))

    def test_cleanup_removes_the_stream(self):
        async def scenario():
            s = self.stream()
            s.publish("run_completed", {"status": "completed"})
            self.assertIsNotNone(self.bus.get(self.run_id))
            await self.bus.cleanup_later(self.run_id, delay=0)
            return self.bus.get(self.run_id)

        self.assertIsNone(asyncio.run(scenario()))

    def test_concurrent_runs_do_not_lose_events(self):
        """Criterion 7: 5 concurrent runs, 200 events each, no loss."""

        async def scenario():
            run_ids = [f"run_c{i}" for i in range(5)]
            for rid in run_ids:
                self.bus.configure_run(rid, log_path=self.tmp / f"{rid}.ndjson")

            async def produce(rid):
                emitter = RunEmitter(rid, event_bus=self.bus)
                for i in range(200):
                    emitter.emit("agent_thinking", {"summary": f"{rid}:{i}"})
                    if i % 50 == 0:
                        await asyncio.sleep(0)
                emitter.emit("run_completed", {"status": "completed"})

            await asyncio.gather(*(produce(r) for r in run_ids))
            return {r: self.bus.stream(r).seq for r in run_ids}

        counts = asyncio.run(scenario())
        for rid, seq in counts.items():
            self.assertEqual(seq, 201, f"{rid} lost events")


class TestLegacyShim(unittest.TestCase):
    def test_await_emit_still_works(self):
        """The ~100 call sites in app/graph/ must keep working untouched."""
        from app.events import emit, emit_nowait
        from app.runtime.events.bus import bus as global_bus

        async def scenario():
            await emit("run_shim01", "agent_thinking", "executor", {"summary": "hi"})
            emit_nowait("run_shim01", "file_created", "executor", {"path": "a.py"})
            return global_bus.stream("run_shim01").history()

        events = asyncio.run(scenario())
        self.assertEqual([e["event"] for e in events], ["agent_thinking", "file_created"])
        self.assertEqual(events[0]["node"], "executor")
        global_bus.discard("run_shim01")


if __name__ == "__main__":
    unittest.main()
