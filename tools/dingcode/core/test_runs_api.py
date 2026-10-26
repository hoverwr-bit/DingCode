"""Tests for the record page surface (core/runs_api.py): M1 reads, M2 writes.

Starts a real bridge on an ephemeral port against a temp DINGCODE_HOME and a
temp dist dir, then drives it with raw http.client so Host and Origin headers
are under test control. M2 write tests patch runs_api.spawn_autofix so a rerun
request never starts a real engine process.

Run: python3 ./core/test_runs_api.py  (or python3 -m core.test_runs_api)
"""

import hashlib
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import bridge  # noqa: E402
from core import runs_api  # noqa: E402

SID = "case-1"
SID2 = "case-2"
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
# 源 note 文件（M2 改批注/重跑都以它为准），status.json 的 note 字段指向它。
SOURCE_NOTE = {
    "pins": [
        {"id": "p1", "status": "open", "note": "这个按钮改成蓝色"},
        {"id": "p2", "status": "confirmed", "note": "已确认"},
    ]
}


class RunsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp(prefix="dingcode-runs-")
        cls.dist = tempfile.mkdtemp(prefix="dingcode-dist-")
        os.environ["DINGCODE_HOME"] = cls.home
        os.environ["DINGCODE_RECORD_DIST"] = cls.dist
        cls.source_note = os.path.join(cls.home, "source-notes", "case-1.json")
        os.makedirs(os.path.dirname(cls.source_note))
        cls._write(cls.source_note, SOURCE_NOTE)
        run = os.path.join(cls.home, "runs", SID)
        round1 = os.path.join(run, "round-1")
        os.makedirs(round1)
        cls._write(os.path.join(run, "status.json"), {
            "status": "done", "round": 1, "summary_line": "修复了 1 颗钉",
            "note": cls.source_note, "finished": "2026-10-25T10:00:00Z",
        })
        cls._write(os.path.join(run, "note.json"), NOTE)
        cls._write(os.path.join(round1, "summary.json"), SUMMARY)
        cls._write(os.path.join(round1, "manifest.json"), MANIFEST)
        # newline=""：磁盘字节固定 LF，否则 Windows 文本模式写出 CRLF，
        # 服务的 diff 就不再是 DIFF 原文。
        with open(os.path.join(round1, "diff.patch"), "w", encoding="utf-8", newline="") as fh:
            fh.write(DIFF)
        with open(os.path.join(round1, "pre.diff"), "w", encoding="utf-8", newline="") as fh:
            fh.write(DIFF)
        with open(os.path.join(cls.dist, "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<!doctype html><html><body>record</body></html>")
        cls._fixture_case2()
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

    @classmethod
    def _fixture_case2(cls):
        """逐颗撤回（M3）的夹具：一颗 pin_only 轮，带 pre/、post/ 和 files_sha256。"""
        cls.folder2 = os.path.join(cls.home, "proj-case2")
        os.makedirs(cls.folder2)
        run = os.path.join(cls.home, "runs", SID2)
        round1 = os.path.join(run, "round-1")
        os.makedirs(os.path.join(round1, "pre"))
        os.makedirs(os.path.join(round1, "post"))
        base = b"l1\nl2\nl3\n"
        pinned = b"l1\nX\nl3\n"
        with open(os.path.join(round1, "pre", "a.txt"), "wb") as fh:
            fh.write(base)
        with open(os.path.join(round1, "post", "a.txt"), "wb") as fh:
            fh.write(pinned)
        cls._write(os.path.join(run, "status.json"), {
            "status": "done", "round": 1, "summary_line": "修复了 1 颗钉",
            "note": cls.source_note, "folder": cls.folder2,
            "finished": "2026-10-26T10:00:00Z",
        })
        cls._write(os.path.join(round1, "summary.json"), {
            "pins": [{
                "id": "p1", "status": "fixed", "summary_zh": "改了 a.txt 第 2 行",
                "files": ["a.txt"], "pin_only": True, "pin": "p1", "rerun": 1,
            }]
        })
        cls._write(os.path.join(round1, "manifest.json"), {
            "kind": "copy", "folder": cls.folder2, "copied": ["a.txt"],
            "files_sha256": {"a.txt": {
                "pre": hashlib.sha256(base).hexdigest(),
                "post": hashlib.sha256(pinned).hexdigest(),
            }},
        })

    def request(self, path, method="GET", headers=None, data=b""):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            merged = {"Host": "127.0.0.1:%d" % self.port}
            merged.update(headers or {})
            for key, value in merged.items():
                conn.putheader(key, value)
            conn.endheaders()
            if data:
                conn.send(data)
            resp = conn.getresponse()
            body = resp.read()
            headers_out = dict((k.lower(), v) for k, v in resp.getheaders())
            return resp.status, body, headers_out
        finally:
            conn.close()

    @property
    def self_origin(self):
        return "http://127.0.0.1:%d" % self.port

    def post_write(self, path, obj, origin="self"):
        """POST with JSON body; origin "self" by default, None = no Origin header."""
        headers = {}
        if origin == "self":
            headers["Origin"] = self.self_origin
        elif origin:
            headers["Origin"] = origin
        data = json.dumps(obj).encode("utf-8")
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(data))
        return self.request(path, method="POST", headers=headers, data=data)

    def creds(self):
        status, body, _ = self.request("/api/session")
        self.assertEqual(status, 200)
        data = json.loads(body)
        return {"client": data["client"], "token": data["token"]}

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
        # 只读路径不吃 POST：POST 只属于两个写路由，其余 /api 404，/app 405。
        status, _, _ = self.request("/api/sessions", method="POST",
                                    headers={"Content-Length": "0"})
        self.assertEqual(status, 404)
        status, _, headers = self.request("/app/", method="POST",
                                          headers={"Content-Length": "0"})
        self.assertEqual(status, 405)
        self.assertEqual(headers.get("allow"), "GET")

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

    # -- M2 写接口 ----------------------------------------------------------

    def test_write_requires_self_origin(self):
        creds = self.creds()
        payload = {**creds, "confirm": "p1", "note": "x"}
        # 无 Origin 的本地客户端只读：写必须来自页面自身的同源请求。
        status, _, _ = self.post_write(
            "/api/runs/%s/pins/p1/note" % SID, payload, origin=None)
        self.assertEqual(status, 403)
        # 外域 Origin 在 bridge 层就被拒。
        status, _, _ = self.post_write(
            "/api/runs/%s/pins/p1/note" % SID, payload,
            origin="http://evil.example")
        self.assertEqual(status, 403)

    def test_write_requires_client_token(self):
        # 缺 client/token → 401。
        status, body, _ = self.post_write(
            "/api/runs/%s/pins/p1/note" % SID, {"confirm": "p1", "note": "x"})
        self.assertEqual(status, 401)
        self.assertIn("client", json.loads(body)["error"])
        # 错 token → 401。
        status, _, _ = self.post_write(
            "/api/runs/%s/pins/p1/note" % SID,
            {"client": 999, "token": "nope", "confirm": "p1", "note": "x"})
        self.assertEqual(status, 401)

    def test_write_confirm_mismatch_403(self):
        creds = self.creds()
        status, body, _ = self.post_write(
            "/api/runs/%s/pins/p1/note" % SID,
            {**creds, "confirm": "p2", "note": "x"})
        self.assertEqual(status, 403)
        self.assertIn("confirm", json.loads(body)["error"])

    def test_write_bad_pid_400(self):
        creds = self.creds()
        # %2e%2e 不被解码成 ..，但包含 % 不满足 pid 白名单。
        status, _, _ = self.post_write(
            "/api/runs/%s/pins/%%2e%%2e/note" % SID,
            {**creds, "confirm": "..", "note": "x"})
        self.assertEqual(status, 400)
        status, _, _ = self.post_write(
            "/api/runs/%s/pins/%%20/rerun" % SID,
            {**creds, "confirm": "%20"})
        self.assertEqual(status, 400)

    def test_write_bad_json_and_too_large(self):
        creds = self.creds()
        status, _, _ = self.request(
            "/api/runs/%s/pins/p1/note" % SID, method="POST",
            headers={"Origin": self.self_origin, "Content-Type": "application/json",
                     "Content-Length": "5"},
            data=b"not{json")
        self.assertEqual(status, 400)
        status, _, _ = self.post_write(
            "/api/runs/%s/pins/p1/note" % SID,
            {**creds, "confirm": "p1", "note": "长" * 40000})
        self.assertEqual(status, 413)

    def test_note_edit_saves_to_source_note(self):
        creds = self.creds()
        status, body, _ = self.post_write(
            "/api/runs/%s/pins/p1/note" % SID,
            {**creds, "confirm": "p1", "note": "改成绿色并加大字号"})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["ok"])
        self.assertEqual(data["note"], "改成绿色并加大字号")
        with open(self.source_note, encoding="utf-8") as fh:
            after = json.load(fh)
        self.assertEqual(after["pins"][0]["note"], "改成绿色并加大字号")
        self.assertEqual(after["pins"][1]["note"], "已确认")  # 别的钉不动
        # P-20261026-DB-04: 版本由 git 管，改批注不再产生 .bak。
        self.assertFalse(os.path.exists(self.source_note + ".bak"))
        # runs/note.json 不被手改。
        status, body, _ = self.request("/api/runs/%s/note" % SID)
        self.assertEqual(json.loads(body)["pins"][0]["note"], "这个按钮改成蓝色")

    def test_note_edit_validations(self):
        creds = self.creds()
        status, _, _ = self.post_write(
            "/api/runs/%s/pins/p1/note" % SID,
            {**creds, "confirm": "p1", "note": 123})
        self.assertEqual(status, 400)
        status, _, _ = self.post_write(
            "/api/runs/%s/pins/p1/note" % SID,
            {**creds, "confirm": "p1", "note": "超" * 3000})
        self.assertEqual(status, 400)
        status, _, _ = self.post_write(
            "/api/runs/%s/pins/zz/note" % SID, {**creds, "confirm": "zz", "note": "x"})
        self.assertEqual(status, 404)

    def test_rerun_enqueues_round(self):
        creds = self.creds()
        captured = []
        original = runs_api.spawn_autofix
        runs_api.spawn_autofix = lambda sid, n, pid, fb="": captured.append((sid, n, pid, fb))
        try:
            status, body, _ = self.post_write(
                "/api/runs/%s/pins/p1/rerun" % SID,
                {**creds, "confirm": "p1", "feedback": "再宽一点"})
        finally:
            runs_api.spawn_autofix = original
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["ok"])
        self.assertEqual(data["round"], 2)  # 已有 round-1，重跑入队 round-2
        self.assertEqual(captured, [(SID, 2, "p1", "再宽一点")])

    def test_rerun_validations(self):
        creds = self.creds()
        captured = []
        original = runs_api.spawn_autofix
        runs_api.spawn_autofix = lambda *a: captured.append(a)
        try:
            # 已确认的钉不重跑（open_pins_note 语义）。
            status, _, _ = self.post_write(
                "/api/runs/%s/pins/p2/rerun" % SID, {**creds, "confirm": "p2"})
            self.assertEqual(status, 400)
            # 不存在的钉 404。
            status, _, _ = self.post_write(
                "/api/runs/%s/pins/zz/rerun" % SID, {**creds, "confirm": "zz"})
            self.assertEqual(status, 404)
            self.assertEqual(captured, [])
            # 已有运行在进行 → 409。
            status_path = os.path.join(self.home, "runs", SID, "status.json")
            with open(status_path, encoding="utf-8") as fh:
                old = fh.read()
            self._write(status_path, {"status": "running", "round": 2})
            try:
                status, _, _ = self.post_write(
                    "/api/runs/%s/pins/p1/rerun" % SID, {**creds, "confirm": "p1"})
                self.assertEqual(status, 409)
            finally:
                with open(status_path, "w", encoding="utf-8") as fh:
                    fh.write(old)
        finally:
            runs_api.spawn_autofix = original
        self.assertEqual(captured, [])

    # -- M3 逐颗撤回 ---------------------------------------------------------

    def _case2_file(self, text):
        path = os.path.join(self.folder2, "a.txt")
        # newline=""：字节与 post 快照完全一致（Windows 文本模式会 \n→\r\n，
        # sha256 对不上就会走合并路径而不是快路径）。
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return path

    def _case2_summary(self):
        path = os.path.join(self.home, "runs", SID2, "round-1", "summary.json")
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def test_revert_success_restores_the_pin_before(self):
        creds = self.creds()
        path = self._case2_file("l1\nX\nl3\n")  # 磁盘 == post → 快路径
        status, body, _ = self.post_write(
            "/api/runs/%s/pins/p1/revert" % SID2, {**creds, "confirm": "p1"})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["ok"])
        self.assertEqual(data["restored"], ["a.txt"])
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "l1\nl2\nl3\n")  # 写回改前字节
        self.assertTrue(self._case2_summary().get("reverted"))

    def test_revert_conflict_is_409_and_disk_untouched(self):
        creds = self.creds()
        path = self._case2_file("l1\nZ\nl3\n")  # 后续轮改了同一行 → 同 hunk 冲突
        status, body, _ = self.post_write(
            "/api/runs/%s/pins/p1/revert" % SID2, {**creds, "confirm": "p1"})
        self.assertEqual(status, 409)
        data = json.loads(body)
        self.assertFalse(data["ok"])
        self.assertEqual(data["conflicts"], ["a.txt"])
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "l1\nZ\nl3\n")  # 磁盘未动
        self.assertNotIn("reverted", self._case2_summary())
        with open(os.path.join(self.home, "runs", SID2, "status.json"), encoding="utf-8") as fh:
            self.assertNotIn("reverted_pin", json.load(fh))

    def test_revert_rejections(self):
        creds = self.creds()
        path = self._case2_file("l1\nX\nl3\n")
        # 无 Origin（本地客户端）只读：写必须来自页面同源。
        status, _, _ = self.post_write(
            "/api/runs/%s/pins/p1/revert" % SID2, {**creds, "confirm": "p1"}, origin=None)
        self.assertEqual(status, 403)
        # 外域 Origin 在 bridge 层就被拒。
        status, _, _ = self.post_write(
            "/api/runs/%s/pins/p1/revert" % SID2, {**creds, "confirm": "p1"},
            origin="http://evil.example")
        self.assertEqual(status, 403)
        # 缺/错 client+token → 401。
        status, _, _ = self.post_write(
            "/api/runs/%s/pins/p1/revert" % SID2, {"confirm": "p1"})
        self.assertEqual(status, 401)
        status, _, _ = self.post_write(
            "/api/runs/%s/pins/p1/revert" % SID2, {"client": 999, "token": "x", "confirm": "p1"})
        self.assertEqual(status, 401)
        # confirm 不是这个钉 → 403。
        status, _, _ = self.post_write(
            "/api/runs/%s/pins/p1/revert" % SID2, {**creds, "confirm": "p2"})
        self.assertEqual(status, 403)
        # 非法 pid → 400。
        status, _, _ = self.post_write(
            "/api/runs/%s/pins/%%2e%%2e/revert" % SID2, {**creds, "confirm": ".."})
        self.assertEqual(status, 400)
        # 没有可撤回 pin_only 轮的钉 → 404。
        status, _, _ = self.post_write(
            "/api/runs/%s/pins/p2/revert" % SID2, {**creds, "confirm": "p2"})
        self.assertEqual(status, 404)
        # 全部拒绝路径磁盘都不动。
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "l1\nX\nl3\n")

    def test_revert_refuses_while_running(self):
        creds = self.creds()
        status_path = os.path.join(self.home, "runs", SID2, "status.json")
        with open(status_path, encoding="utf-8") as fh:
            old = fh.read()
        self._write(status_path, {"status": "running", "round": 1, "note": self.source_note,
                                  "folder": self.folder2})
        try:
            status, _, _ = self.post_write(
                "/api/runs/%s/pins/p1/revert" % SID2, {**creds, "confirm": "p1"})
            self.assertEqual(status, 409)
        finally:
            with open(status_path, "w", encoding="utf-8") as fh:
                fh.write(old)

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

    def test_static_windows_style_traversal_rejected(self):
        # Windows 风格反斜杠穿越（M5）：反斜杠与编码 %5C 都不许绕过守卫，绝不能 200。
        for path in ("/app/..\\core\\bridge.py", "/app/..\\..\\windows\\Program.cs",
                     "/app/%2e%2e%5ccore%5cbridge.py"):
            status, _, _ = self.request(path)
            self.assertNotEqual(status, 200, path)

    def test_note_edit_busy_returns_409(self):
        # Windows 场景：note 被编辑器/杀软占用 → os.replace 抛 PermissionError，
        # 接口返回 409 而不是崩掉 handler 线程。
        with open(self.source_note, encoding="utf-8") as fh:
            before = fh.read()
        creds = self.creds()
        with mock.patch("core.runs_api.os.replace", side_effect=PermissionError(13, "busy")):
            status, body, _ = self.post_write(
                "/api/runs/%s/pins/p1/note" % SID,
                {**creds, "confirm": "p1", "note": "占用时也要优雅失败"})
        self.assertEqual(status, 409)
        self.assertIn("busy", json.loads(body)["error"])
        # 失败不落脏数据：源 note 不变，也没有残留 .tmp。
        with open(self.source_note, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), before)
        self.assertFalse(os.path.exists(self.source_note + ".tmp"))


if __name__ == "__main__":
    unittest.main()
