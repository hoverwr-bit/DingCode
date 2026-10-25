"""Tests for the read-only record page surface (core/runs_api.py).

Starts a real bridge on an ephemeral port against a temp DINGCODE_HOME and a
temp dist dir, then drives it with raw http.client so Host and Origin headers
are under test control.

Run: python3 ./core/test_runs_api.py  (or python3 -m core.test_runs_api)
"""

import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import bridge  # noqa: E402

SID = "case-1"
DIFF = "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-hello\n+world\n"
SUMMARY = {
    "pins": [
        {
            "id": "p1",
            "status": "fixed",
            "summary_zh": "改了 a.txt 第 1 行",
            "files": ["a.txt"],
            "diff": DIFF,
        }
    ]
}
MANIFEST = {"kind": "git", "head": "abc1234", "folder": "/tmp/proj",
            "files_sha256": {"a.txt": "deadbeef"}}
NOTE = {"pins": [{"id": "p1", "note": "这个按钮改成蓝色"}]}


class RunsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp(prefix="dingcode-runs-")
        cls.dist = tempfile.mkdtemp(prefix="dingcode-dist-")
        os.environ["DINGCODE_HOME"] = cls.home
        os.environ["DINGCODE_RECORD_DIST"] = cls.dist
        run = os.path.join(cls.home, "runs", SID)
        round1 = os.path.join(run, "round-1")
        os.makedirs(round1)
        cls._write(os.path.join(run, "status.json"), {
            "status": "done", "round": 1, "summary_line": "修复了 1 颗钉",
            "note": "", "finished": "2026-10-25T10:00:00Z",
        })
        cls._write(os.path.join(run, "note.json"), NOTE)
        cls._write(os.path.join(round1, "summary.json"), SUMMARY)
        cls._write(os.path.join(round1, "manifest.json"), MANIFEST)
        with open(os.path.join(round1, "diff.patch"), "w", encoding="utf-8") as fh:
            fh.write(DIFF)
        with open(os.path.join(round1, "pre.diff"), "w", encoding="utf-8") as fh:
            fh.write(DIFF)
        with open(os.path.join(cls.dist, "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<!doctype html><html><body>record</body></html>")
        cls.httpd = bridge.make_server(0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.thread.join(timeout=10)
        os.environ.pop("DINGCODE_HOME", None)
        os.environ.pop("DINGCODE_RECORD_DIST", None)
        shutil.rmtree(cls.home, ignore_errors=True)
        shutil.rmtree(cls.dist, ignore_errors=True)

    @staticmethod
    def _write(path, obj):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False)

    def request(self, path, method="GET", headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            merged = {"Host": "127.0.0.1:%d" % self.port}
            merged.update(headers or {})
            for key, value in merged.items():
                conn.putheader(key, value)
            conn.endheaders()
            resp = conn.getresponse()
            body = resp.read()
            headers_out = dict((k.lower(), v) for k, v in resp.getheaders())
            return resp.status, body, headers_out
        finally:
            conn.close()

    # -- origin / Host 门禁 ------------------------------------------------

    def test_self_origin_allowed(self):
        status, body, headers = self.request(
            "/api/sessions", headers={"Origin": "http://127.0.0.1:%d" % self.port})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["ok"])
        names = [item["session"] for item in data["sessions"]]
        self.assertIn(SID, names)
        # 同源请求不发 CORS 头。
        self.assertNotIn("access-control-allow-origin", headers)

    def test_cli_no_origin_allowed(self):
        status, body, _ = self.request("/api/runs/" + SID)
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["ok"])
        self.assertEqual(data["session"], SID)
        self.assertEqual(data["status"], "done")
        self.assertEqual(data["pins"][0]["id"], "p1")

    def test_foreign_origin_403(self):
        for origin in ("http://evil.example", "http://localhost:%d" % (self.port + 1),
                       "null"):
            status, _, _ = self.request(
                "/api/sessions", headers={"Origin": origin})
            self.assertEqual(status, 403, origin)

    def test_forged_host_403(self):
        # DNS rebinding: 外部域名解析到 127.0.0.1 时 Host 不是环回地址。
        status, _, _ = self.request("/api/sessions", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)
        status, _, _ = self.request(
            "/api/sessions",
            headers={"Host": "evil.example",
                     "Origin": "http://127.0.0.1:%d" % self.port})
        self.assertEqual(status, 403)

    def test_post_is_405(self):
        status, _, headers = self.request("/api/sessions", method="POST")
        self.assertEqual(status, 405)
        self.assertEqual(headers.get("allow"), "GET")
        status, _, _ = self.request("/app/", method="POST")
        self.assertEqual(status, 405)

    def test_bad_sid_rejected(self):
        status, _, _ = self.request("/api/runs/%2e%2e")
        self.assertEqual(status, 400)
        status, _, _ = self.request("/api/runs/x/rounds/1/files/y",
                                    headers={"Host": "127.0.0.1:%d" % self.port})
        # x 存在性检查发生在 sid 校验之前应不影响：sid "x" 合法但会话不存在。
        self.assertEqual(status, 404)

    # -- 只读端点 ----------------------------------------------------------

    def test_round_detail(self):
        status, body, _ = self.request("/api/runs/%s/rounds/1" % SID)
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["ok"])
        self.assertEqual(data["manifest"]["kind"], "git")
        self.assertEqual(data["manifest"]["head"], "abc1234")
        self.assertEqual(data["manifest"]["files_sha256"], ["a.txt"])
        self.assertFalse(data["manifest"]["reverted"])

    def test_round_files_whitelist(self):
        status, body, _ = self.request("/api/runs/%s/rounds/1/files/diff.patch" % SID)
        self.assertEqual(status, 200)
        self.assertEqual(body.decode("utf-8"), DIFF)
        for name in ("status.json", "note.json", "secret.txt", "..", "."):
            status, _, _ = self.request(
                "/api/runs/%s/rounds/1/files/%s" % (SID, name))
            self.assertEqual(status, 404, name)

    def test_note_endpoint(self):
        status, body, _ = self.request("/api/runs/%s/note" % SID)
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["pins"][0]["note"], "这个按钮改成蓝色")

    def test_pin_history(self):
        status, body, _ = self.request("/api/runs/%s/pins/p1" % SID)
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["ok"])
        self.assertEqual(data["pin_id"], "p1")
        self.assertEqual(len(data["rounds"]), 1)
        self.assertEqual(data["rounds"][0]["summary_zh"], "改了 a.txt 第 1 行")
        # 不存在的钉 404。
        status, _, _ = self.request("/api/runs/%s/pins/nope" % SID)
        self.assertEqual(status, 404)

    def test_unknown_session_404(self):
        status, _, _ = self.request("/api/runs/missing-session")
        self.assertEqual(status, 404)
        status, _, _ = self.request("/api/runs/%s/rounds/9" % SID)
        self.assertEqual(status, 404)

    # -- /app 静态服务 ------------------------------------------------------

    def test_static_index(self):
        status, body, headers = self.request("/app/")
        self.assertEqual(status, 200)
        self.assertIn(b"record", body)
        self.assertEqual(headers.get("x-content-type-options"), "nosniff")
        status, body, _ = self.request("/app")
        self.assertEqual(status, 200)
        self.assertIn(b"record", body)

    def test_static_traversal_rejected(self):
        # 未编码的 ../ 在 realpath 检查处挡下。
        status, _, _ = self.request("/app/../core/bridge.py")
        self.assertEqual(status, 403)
        status, _, _ = self.request("/app/../../etc/passwd")
        self.assertEqual(status, 403)
        # 编码后的 %2e%2e 不被解码，落入白名单后缀检查，绝不能 200。
        status, _, _ = self.request("/app/%2e%2e/core/bridge.py")
        self.assertNotEqual(status, 200)

    def test_static_suffix_whitelist(self):
        status, _, _ = self.request("/app/nope.exe")
        self.assertEqual(status, 404)
        status, _, _ = self.request("/app/missing.html")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
