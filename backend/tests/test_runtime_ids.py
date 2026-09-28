"""Identifier and path-containment tests.

Guards the P0 fix described in docs/runtime/SESSIONS.md section 6: before it,
a workspace named "../../etc" escaped the sandbox root and DELETE on it ran
shutil.rmtree outside the project.
"""

import tempfile
import unittest
from pathlib import Path

from app.runtime.ids import (
    is_safe_segment,
    new_run_id,
    new_session_id,
    resolve_within,
    safe_slug,
    utc_now,
)


class TestSafeSlug(unittest.TestCase):
    def test_normalises_human_names(self):
        self.assertEqual(safe_slug("My Project!"), "my_project")
        self.assertEqual(safe_slug("Deal Intelligence"), "deal_intelligence")
        self.assertEqual(safe_slug("a-b_c"), "a-b_c")

    def test_strips_path_separators(self):
        # The exact shape that produced sandbox/kushal/workspace.json's
        # broken '"id": "kushal\\"'.
        self.assertEqual(safe_slug("Kushal" + chr(92)), "kushal")
        self.assertEqual(safe_slug("../../evil"), "evil")
        self.assertEqual(safe_slug("a/b/c"), "a_b_c")

    def test_rejects_empty_and_reserved(self):
        for bad in ["", "   ", "..", ".", "///", chr(92) * 3]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                safe_slug(bad)

    def test_truncates(self):
        self.assertEqual(len(safe_slug("x" * 200)), 48)

    def test_is_safe_segment(self):
        self.assertTrue(is_safe_segment("default"))
        self.assertFalse(is_safe_segment("../etc"))
        self.assertFalse(is_safe_segment(""))


class TestResolveWithin(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()

    def test_rejects_traversal(self):
        escapes = [
            "../../etc",
            ".." + chr(92) + ".." + chr(92) + "windows",
            "a/../../../b",
            "..",
            "C:/Windows",
            "C:",
        ]
        for bad in escapes:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                resolve_within(self.root, bad)

    def test_rebases_absolute_paths_under_root(self):
        # An absolute-looking path is treated as relative to the root rather
        # than rejected, so callers cannot reach outside by prefixing "/".
        result = resolve_within(self.root, "/etc/passwd")
        self.assertTrue(result.is_relative_to(self.root))
        self.assertEqual(result.relative_to(self.root).as_posix(), "etc/passwd")

    def test_allows_normal_paths(self):
        self.assertEqual(
            resolve_within(self.root, "a/b.txt"), (self.root / "a" / "b.txt").resolve()
        )
        self.assertEqual(
            resolve_within(self.root, "runs", "run_abc", "events.ndjson"),
            (self.root / "runs" / "run_abc" / "events.ndjson").resolve(),
        )

    def test_root_itself_is_allowed(self):
        self.assertEqual(resolve_within(self.root), self.root)


class TestIdentifiers(unittest.TestCase):
    def test_prefixes_and_uniqueness(self):
        self.assertTrue(new_run_id().startswith("run_"))
        self.assertTrue(new_session_id().startswith("ses_"))
        self.assertNotEqual(new_run_id(), new_run_id())

    def test_timestamp_shape(self):
        ts = utc_now()
        self.assertTrue(ts.endswith("Z"))
        self.assertIn("T", ts)


if __name__ == "__main__":
    unittest.main()
