"""Result builder tests.

The builder is a pure reducer, so these run with no agent, no bus and no
network -- fixture events in, RunResult out. Covers the criteria in
docs/runtime/RESULTS.md section 7.
"""

import json
import tempfile
import unittest
from pathlib import Path

from app.runtime.results.builder import ResultBuilder, build_result


def ev(seq, event, data=None, ts=None, node=""):
    return {
        "seq": seq,
        "event": event,
        "run_id": "run_demo01",
        "session_id": "ses_demo",
        "node": node,
        "ts": ts or f"2026-09-29T11:00:{seq:02d}.000Z",
        "data": data or {},
    }


HAPPY_PATH = [
    ev(1, "run_started", {"objective": "Create a presentation on IPsec",
                          "model": "openai/gpt-oss-120b", "provider": "groq"}),
    ev(2, "memory_recalled", {"query": "presentation", "hits": [
        {"id": "exp_1", "content": "pip install failed here before", "score": 0.8},
        {"id": "exp_2", "content": "user prefers dark slides", "score": 0.7},
    ]}),
    ev(3, "memory_applied", {"experience_id": "exp_1",
                             "how": "Skipped pip install; it failed on this workspace last time."}),
    ev(4, "plan_created", {"steps": [{"id": "s1", "title": "read files"}]}),
    ev(5, "file_read", {"path": "notes/a.md", "bytes": 100}),
    ev(6, "file_read", {"path": "notes/b.md", "bytes": 120}),
    ev(7, "tool_started", {"tool": "create_file", "call_id": "call_1"}),
    ev(8, "file_created", {"path": "decks/IPsec.pptx", "bytes": 482113}),
    ev(9, "tool_completed", {"tool": "create_file", "call_id": "call_1", "ok": True}),
    ev(10, "command_completed", {"command": "python build.py", "exit_code": 0,
                                 "duration_ms": 8412, "stdout": "ok"}),
    ev(11, "verification_completed", {"valid": True, "reason": "12 slides present",
                                      "checks": [{"name": "file_exists", "passed": True}]}),
    ev(12, "memory_recorded", {"experience_id": "exp_77", "summary": "built a deck"}),
    ev(13, "run_completed", {"status": "completed", "summary": "Created a 12-slide IPsec deck.",
                             "reply": "Done."}, ts="2026-09-29T11:02:41.000Z"),
]


class TestHappyPath(unittest.TestCase):
    def setUp(self):
        self.result = build_result(HAPPY_PATH)

    def test_core_fields(self):
        r = self.result
        self.assertEqual(r["status"], "completed")
        self.assertEqual(r["run_id"], "run_demo01")
        self.assertEqual(r["objective"], "Create a presentation on IPsec")
        self.assertEqual(r["summary"], "Created a 12-slide IPsec deck.")
        self.assertEqual(r["event_count"], len(HAPPY_PATH))

    def test_duration_is_computed_from_timestamps(self):
        self.assertEqual(self.result["duration_ms"], 160000)

    def test_artifacts(self):
        arts = self.result["artifacts"]
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0]["name"], "IPsec.pptx")
        self.assertEqual(arts[0]["action"], "created")
        self.assertEqual(arts[0]["bytes"], 482113)
        self.assertIn("presentationml", arts[0]["mime"])
        self.assertEqual(self.result["files_created"], ["decks/IPsec.pptx"])

    def test_actions_are_human_readable(self):
        labels = [a["label"] for a in self.result["actions"]]
        self.assertIn("Read 2 files", labels)
        self.assertIn("Created 1 file", labels)
        self.assertIn("Ran 1 command", labels)
        self.assertIn("Recalled 2 past experiences", labels)

    def test_memory_block_is_the_hindsight_evidence(self):
        mem = self.result["memory"]
        self.assertEqual(mem["recalled"], 2)
        self.assertEqual(mem["recorded"], "exp_77")
        self.assertEqual(
            mem["applied"],
            ["Skipped pip install; it failed on this workspace last time."],
        )

    def test_verification(self):
        self.assertTrue(self.result["verification"]["valid"])

    def test_no_errors(self):
        self.assertEqual(self.result["errors"], [])


class TestDedupe(unittest.TestCase):
    def test_create_then_update_twice_is_one_artifact(self):
        """Criterion 3."""
        events = [
            ev(1, "run_started", {"objective": "x"}),
            ev(2, "file_created", {"path": "app.py", "bytes": 10}),
            ev(3, "file_updated", {"path": "app.py", "bytes": 20}),
            ev(4, "file_updated", {"path": "./app.py", "bytes": 30}),
            ev(5, "run_completed", {"status": "completed"}),
        ]
        r = build_result(events)
        self.assertEqual(len(r["artifacts"]), 1)
        self.assertEqual(r["artifacts"][0]["action"], "created")
        self.assertEqual(r["artifacts"][0]["bytes"], 30)

    def test_backslash_paths_normalise(self):
        events = [
            ev(1, "file_created", {"path": "a\\b\\c.py", "bytes": 1}),
            ev(2, "file_updated", {"path": "a/b/c.py", "bytes": 2}),
        ]
        r = build_result(events)
        self.assertEqual(len(r["artifacts"]), 1)
        self.assertEqual(r["artifacts"][0]["path"], "a/b/c.py")

    def test_created_then_deleted_stays_visible(self):
        events = [
            ev(1, "file_created", {"path": "tmp.txt", "bytes": 5}),
            ev(2, "file_deleted", {"path": "tmp.txt"}),
        ]
        r = build_result(events)
        self.assertEqual(len(r["artifacts"]), 1)
        self.assertEqual(r["artifacts"][0]["action"], "deleted")
        self.assertEqual(r["files_deleted"], ["tmp.txt"])


class TestFailureAndPartial(unittest.TestCase):
    def test_failed_run_records_the_error(self):
        events = [
            ev(1, "run_started", {"objective": "x"}),
            ev(2, "file_created", {"path": "a.py", "bytes": 1}),
            ev(3, "run_failed", {"error_type": "ValueError", "message": "boom",
                                 "node": "executor"}),
        ]
        r = build_result(events)
        self.assertEqual(r["status"], "failed")
        self.assertEqual(r["errors"][0]["type"], "ValueError")
        self.assertEqual(len(r["artifacts"]), 1, "partial artifacts survive a failure")

    def test_killed_run_still_yields_a_result(self):
        """Criterion 2: no terminal event at all."""
        events = [
            ev(1, "run_started", {"objective": "half a job"}),
            ev(2, "file_created", {"path": "a.py", "bytes": 1}),
            ev(3, "file_read", {"path": "b.py"}),
        ]
        r = build_result(events)
        self.assertEqual(r["status"], "running")
        self.assertEqual(len(r["artifacts"]), 1)
        self.assertTrue(r["summary"], "a fallback summary is generated")

    def test_failed_command_becomes_an_error(self):
        events = [
            ev(1, "command_completed", {"command": "pytest", "exit_code": 1,
                                        "stderr": "2 failed"}),
        ]
        r = build_result(events)
        self.assertEqual(r["errors"][0]["type"], "CommandFailed")
        self.assertIn("2 failed", r["errors"][0]["message"])

    def test_empty_stream(self):
        r = build_result([])
        self.assertEqual(r["status"], "running")
        self.assertEqual(r["artifacts"], [])
        self.assertEqual(r["actions"], [])


class TestIncremental(unittest.TestCase):
    def test_partial_result_available_mid_run(self):
        """Criterion 5: the panel fills in live."""
        b = ResultBuilder()
        b.add(ev(1, "run_started", {"objective": "x"}))
        b.add(ev(2, "file_created", {"path": "a.py", "bytes": 1}))
        mid = b.build()
        self.assertEqual(mid["status"], "running")
        self.assertEqual(len(mid["artifacts"]), 1)

        b.add(ev(3, "file_created", {"path": "b.py", "bytes": 2}))
        b.add(ev(4, "run_completed", {"status": "completed", "summary": "done"}))
        final = b.build()
        self.assertEqual(final["status"], "completed")
        self.assertEqual(len(final["artifacts"]), 2)

    def test_transport_events_are_ignored(self):
        b = ResultBuilder()
        b.add(ev(0, "stream_ready", {"run_id": "x"}))
        b.add(ev(0, "heartbeat", {"ts": "now"}))
        self.assertEqual(b.build()["event_count"], 0)


class TestLegacyEvents(unittest.TestCase):
    def test_legacy_names_still_fold(self):
        """The frozen graph in app/graph/ emits these."""
        events = [
            ev(1, "run_started", {"objective": "x"}),
            ev(2, "validation_result", {"valid": True, "reason": "looks right"}),
            ev(3, "browser_opened", {"url": "http://localhost:8000/preview/index.html"}),
            ev(4, "research_finding", {"text": "found a thing"}),
            ev(5, "chat_response", {"text": "hello there"}),
        ]
        r = build_result(events)
        self.assertTrue(r["verification"]["valid"])
        self.assertEqual(len(r["urls_opened"]), 1)
        self.assertEqual(r["reply"], "hello there")
        labels = [a["label"] for a in r["actions"]]
        self.assertIn("Opened 1 page", labels)
        self.assertIn("Gathered 1 research finding", labels)


class TestDeterminism(unittest.TestCase):
    def test_replaying_a_log_reproduces_the_result(self):
        """Criterion 6, modulo the generated artifact ids."""
        tmp = Path(tempfile.mkdtemp()) / "events.ndjson"
        tmp.write_text(
            "\n".join(json.dumps(e) for e in HAPPY_PATH), encoding="utf-8"
        )
        replayed = [json.loads(l) for l in tmp.read_text(encoding="utf-8").splitlines()]

        a = build_result(HAPPY_PATH)
        b = build_result(replayed)
        for art in (a["artifacts"] + b["artifacts"]):
            art.pop("id", None)
            art.pop("preview_url", None)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
