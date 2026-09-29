"""Phase 4: locating, capturing and publishing artifacts."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.runtime.results.artifacts import locate, public_result
from app.runtime.results.builder import build_result


def ev(seq, event, data):
    return {"seq": seq, "event": event, "run_id": "run_art01", "ts": f"2026-09-29T11:00:{seq:02d}.000Z", "data": data}


ANNOUNCED = {
    "artifact_id": "art_lohit01", "filename": "report.md", "mime_type": "text/markdown",
    "size": 120, "preview_supported": True,
    "url": "/api/artifacts/art_lohit01/content", "download_url": "/api/artifacts/art_lohit01/download",
}


class TestOneFileOneCard(unittest.TestCase):
    def test_announcement_after_the_file_event_merges(self):
        r = build_result([
            ev(1, "file_created", {"path": "docs/report.md", "bytes": 100}),
            ev(2, "artifact_created", ANNOUNCED),
        ])
        self.assertEqual(len(r["artifacts"]), 1)
        art = r["artifacts"][0]
        self.assertEqual(art["id"], "art_lohit01")
        self.assertEqual(art["preview_url"], "/api/artifacts/art_lohit01/content")
        self.assertEqual(art["bytes"], 120)

    def test_announcement_before_the_file_event_merges(self):
        r = build_result([
            ev(1, "artifact_created", ANNOUNCED),
            ev(2, "file_created", {"path": "docs/report.md", "bytes": 100}),
        ])
        self.assertEqual(len(r["artifacts"]), 1)
        self.assertEqual(r["artifacts"][0]["id"], "art_lohit01")
        self.assertEqual(r["artifacts"][0]["path"], "docs/report.md")

    def test_announcement_alone_is_a_card(self):
        r = build_result([ev(1, "artifact_created", ANNOUNCED)])
        self.assertEqual([a["name"] for a in r["artifacts"]], ["report.md"])


class TestPublicShape(unittest.TestCase):
    def test_no_paths_reach_the_browser(self):
        r = build_result([
            ev(1, "file_created", {"path": "C:/Users/someone/project/secret/app.py", "bytes": 5}),
            ev(2, "file_created", {"path": "site/index.html", "bytes": 9}),
        ])
        pub = public_result(r)
        text = json.dumps(pub)
        self.assertNotIn("C:/Users", text)
        self.assertNotIn('"path"', text)
        self.assertEqual(pub["files_created"], ["app.py", "site/index.html"])
        html = next(a for a in pub["artifacts"] if a["filename"] == "index.html")
        self.assertEqual(
            {k: html[k] for k in ("artifact_id", "filename", "mime_type", "size", "preview_supported")},
            {"artifact_id": html["id"], "filename": "index.html", "mime_type": "text/html",
             "size": 9, "preview_supported": True},
        )
        self.assertTrue(html["secure_url"].startswith("/api/runs/"))
        self.assertTrue(html["download_url"].endswith("?download=1"))


class TestLocate(unittest.TestCase):
    def setUp(self):
        self.a = Path(tempfile.mkdtemp()).resolve()
        self.b = Path(tempfile.mkdtemp()).resolve()
        (self.b / "site").mkdir()
        (self.b / "site" / "index.html").write_text("hi", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.a, ignore_errors=True)
        shutil.rmtree(self.b, ignore_errors=True)

    def test_finds_the_file_in_whichever_root_holds_it(self):
        roots = [self.a, self.b]
        self.assertEqual(locate("ws", "site/index.html", roots), self.b / "site" / "index.html")
        self.assertEqual(locate("ws", str(self.b / "site" / "index.html"), roots), self.b / "site" / "index.html")

    def test_refuses_anything_outside_the_roots(self):
        outside = Path(tempfile.mkdtemp()).resolve()
        try:
            (outside / "x.txt").write_text("x", encoding="utf-8")
            self.assertIsNone(locate("ws", str(outside / "x.txt"), [self.a, self.b]))
            self.assertIsNone(locate("ws", "../" + outside.name + "/x.txt", [self.a]))
        finally:
            shutil.rmtree(outside, ignore_errors=True)


class TestCaptureAndServe(unittest.TestCase):
    """End to end through the API with the scripted brain."""

    ENV = {"JARVIS_AGENT": "scripted", "JARVIS_SCRIPTED_DELAY_MS": "0", "JARVIS_SUMMARIZE_ASYNC": "0"}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis_art_")).resolve()
        self._saved = {k: os.environ.get(k) for k in [*self.ENV, "JARVIS_SANDBOX_ROOT"]}
        os.environ.update(self.ENV)
        os.environ["JARVIS_SANDBOX_ROOT"] = str(self.tmp)
        self.client = TestClient(app)
        sid = self.client.post("/api/sessions", json={"workspace_id": "arts"}).json()["session"]["id"]
        self.run_id = self.client.post(f"/api/sessions/{sid}/runs", json={"objective": "Build a site"}).json()["run_id"]
        self.session_id = sid
        with self.client.stream("GET", f"/api/runs/{self.run_id}/events") as stream:
            for line in stream.iter_lines():
                if '"event": "run_completed"' in line:
                    break

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def artifact(self):
        return self.client.get(f"/api/runs/{self.run_id}/artifacts").json()["artifacts"][0]

    def test_serves_the_version_this_run_made_after_an_overwrite(self):
        art = self.artifact()
        (self.tmp / "arts" / "scripted_demo" / "index.html").write_text("CHANGED LATER", encoding="utf-8")
        res = self.client.get(art["secure_url"])
        self.assertEqual(res.status_code, 200)
        self.assertIn("Northwind Goods", res.text)
        self.assertNotIn("CHANGED LATER", res.text)

    def test_download_is_an_attachment_named_after_the_file(self):
        res = self.client.get(self.artifact()["download_url"])
        self.assertEqual(res.status_code, 200)
        self.assertIn('attachment; filename="index.html"', res.headers["content-disposition"])

    def test_no_api_response_carries_a_filesystem_path(self):
        root = str(self.tmp)
        for url in (f"/api/runs/{self.run_id}", f"/api/runs/{self.run_id}/result",
                    f"/api/runs/{self.run_id}/artifacts", f"/api/sessions/{self.session_id}",
                    f"/api/sessions/{self.session_id}/artifacts"):
            with self.subTest(url=url):
                body = self.client.get(url).text
                self.assertNotIn(root.replace("\\", "\\\\"), body)
                self.assertNotIn('"path"', body)


if __name__ == "__main__":
    unittest.main()
