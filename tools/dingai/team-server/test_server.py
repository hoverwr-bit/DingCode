import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

os.environ["DINGAI_TEAM_ROOT"] = ""  # replaced per test before import side effects
import dingai_team_server as server


class ServerTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        os.environ["DINGAI_TEAM_ROOT"] = self._td.name
        os.environ["DINGAI_TEAM_ADMIN_TOKEN"] = "test-admin-token"
        os.environ.pop("DINGAI_TEAM_REQUIRE_AUTH", None)
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.port = httpd.server_address[1]
        self.thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        self.base = "http://127.0.0.1:%d" % self.port

    def req(self, method, path, body=None, token=None, content_type="application/json"):
        data = None
        headers = {}
        if token:
            headers["Authorization"] = "Bearer " + token
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            headers["Content-Type"] = content_type
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=5) as resp:
                raw = resp.read()
                if not raw:
                    return resp.status, None
                try:
                    return resp.status, json.loads(raw.decode())
                except ValueError:
                    return resp.status, raw
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                parsed = json.loads(raw.decode() or "null")
            except ValueError:
                parsed = raw
            return exc.code, parsed

    def test_note_becomes_filterable_pins(self):
        code, _ = self.req("POST", "/api/note", {
            "project": "app",
            "screenshot": "shot.png",
            "machine": "ci",
            "user": "dev",
            "app": {"name": "Demo"},
            "pins": [
                {"id": 1, "x_px": 10, "y_px": 20, "pin_type": "bug", "note": "overlaps", "ocr_nearby": "Save"},
                {"id": 2, "x_px": 30, "y_px": 40, "pin_type": "question", "status": "open"},
            ],
        })
        self.assertEqual(code, 200)
        code, pins = self.req("GET", "/api/pins?project=app&type=bug")
        self.assertEqual(code, 200)
        self.assertEqual(len(pins), 1)
        self.assertEqual(pins[0]["note"], "overlaps")
        code, created = self.req("POST", "/api/users", {"name": "ada", "role": "member"}, token="test-admin-token")
        self.assertEqual(code, 200)
        code, _ = self.req("POST", "/api/pins/by-note/%s/1/status" % pins[0]["note_id"],
                           {"status": "ai-fixed", "project": "app", "comment": "patched"}, token=created["token"])
        self.assertEqual(code, 200)
        code, again = self.req("GET", "/api/pins?status=ai-fixed")
        self.assertEqual(again[0]["status"], "ai-fixed")
        code, detail = self.req("GET", "/api/pins/%s" % again[0]["id"])
        self.assertEqual(detail["comments"][0]["body"], "patched")
        code, _ = self.req("POST", "/api/pins/by-note/%s/1/status" % pins[0]["note_id"],
                           {"status": "open", "project": "app"}, token=created["token"])
        self.assertEqual(code, 409)

    def test_require_auth_blocks_anonymous_notes(self):
        os.environ["DINGAI_TEAM_REQUIRE_AUTH"] = "1"
        code, _ = self.req("POST", "/api/note", {"pins": [{"id": 1, "x_px": 1, "y_px": 1}]})
        self.assertEqual(code, 401)
        code, body = self.req("POST", "/api/note", {"pins": [{"id": 1, "x_px": 1, "y_px": 1}]}, token="test-admin-token")
        self.assertEqual(code, 200)
        self.assertTrue(body["id"])

    def test_release_review_override_and_archive(self):
        code, opened = self.req("POST", "/api/releases", {
            "version": "1.0", "tag": "v1.0", "project": "erp", "rules": "smallest change",
            "diff_summary": "1 file changed", "head": "abc",
            "commits": ["abc"],
            "scope_warnings": [{"kind": "size", "detail": "9 files, 10 lines"}],
            "pins": [{"note_id": "note-a", "pin_id": "1", "note": "gap", "x_px": 10, "y_px": 12, "project": "erp"}],
        })
        self.assertEqual(code, 200)
        rel_id = opened["id"]
        code, page = self.req("GET", "/release/%s/" % rel_id)
        self.assertEqual(code, 200)
        code, blocked = self.req("POST", "/api/releases/%s/publish" % rel_id, {})
        self.assertEqual(code, 409)
        code, decided = self.req("POST", "/api/releases/%s/decide" % rel_id, {"pin": "note-a:1", "decision": "reject"})
        self.assertEqual(code, 200)
        code, denied = self.req("POST", "/api/releases/%s/publish" % rel_id, {"override": "not an admin"})
        self.assertEqual(code, 409)
        code, published = self.req("POST", "/api/releases/%s/publish" % rel_id, {"override": "known reject"}, token="test-admin-token")
        self.assertEqual(code, 200)
        code, frozen = self.req("POST", "/api/releases/%s/decide" % rel_id, {"pin": "note-a:1", "decision": "approve"}, token="test-admin-token")
        self.assertEqual(code, 409)
        code, rows = self.req("GET", "/api/releases?q=v1.0")
        self.assertEqual(rows[0]["id"], rel_id)
        code, zipped = self.req("GET", "/api/releases/%s/export?format=zip" % rel_id)
        self.assertEqual(code, 200)

    def test_session_collision_shows_a_banner(self):
        code, first = self.req("POST", "/api/sessions", {
            "agent": "codex", "repo": "/repos/erp", "branch": "main", "project": "erp",
            "pins": ["note:1"], "paths": ["src/erp"], "ports": ["8080"], "head": "aaa",
        })
        self.assertEqual(code, 200)
        self.assertEqual(first["warnings"], [])
        code, second = self.req("POST", "/api/sessions", {
            "agent": "claude", "repo": "/repos/erp", "branch": "main", "project": "portal",
            "pins": ["note:1"], "paths": ["src/erp/app.py"], "ports": ["8080"],
            "pin_projects": {"note:1": "erp"}, "head": "aaa",
        })
        self.assertEqual(code, 200)
        kinds = {item["kind"] for item in second["warnings"]}
        self.assertIn("same-branch", kinds)
        self.assertIn("pin", kinds)
        code, notices = self.req("GET", "/api/notices")
        self.assertEqual(code, 200)
        self.assertIn("Two sessions share", notices["banners"][0]["text"])
        code, queued = self.req("POST", "/api/sessions/%s/choose" % second["id"], {"choice": "queue"})
        self.assertEqual(code, 200)
        self.assertEqual(queued["status"], "queued")
        code, page = self.req("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(b"banner", page)

    def test_admin_issues_a_license_key(self):
        from core import edition
        code, body = self.req("POST", "/api/license/issue",
                              {"edition": "pro", "expires": "29990101"},
                              token="test-admin-token")
        self.assertEqual(code, 200)
        self.assertEqual(edition.parse_key(body["key"]), ("pro", "29990101"))
        # 未认证不能签发（_auth_admin：无 token 一律 401，不允许 anonymous 越权）
        code, _ = self.req("POST", "/api/license/issue", {"edition": "pro", "expires": "29990101"})
        self.assertEqual(code, 401)
        # 参数不合法
        code, _ = self.req("POST", "/api/license/issue", {"edition": "nope", "expires": "29990101"},
                           token="test-admin-token")
        self.assertEqual(code, 400)

    def test_license_issue_verify_activate_seats_revoke(self):
        from core import edition
        # 签发（带 2 席位）并登记
        code, body = self.req("POST", "/api/license/issue",
                              {"edition": "team", "expires": "29990101", "seats": 2},
                              token="test-admin-token")
        self.assertEqual(code, 200)
        key = body["key"]
        self.assertEqual(edition.parse_key(key), ("team", "29990101"))
        # 列表（管理员）含此密钥预览；viewer 拒绝
        code, rows = self.req("GET", "/api/licenses", token="test-admin-token")
        self.assertEqual(code, 200)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["seats"], 2)
        code, _ = self.req("GET", "/api/licenses")
        self.assertEqual(code, 401)
        # 在线核验与席位占用
        code, v = self.req("GET", "/api/license/verify?key=" + key)
        self.assertEqual((code, v["ok"]), (200, True))
        for machine in ("mac-a", "mac-b"):
            code, a = self.req("POST", "/api/license/activate", {"key": key, "machine": machine})
            self.assertEqual((code, a["ok"]), (200, True))
        code, a = self.req("POST", "/api/license/activate", {"key": key, "machine": "mac-c"})
        self.assertEqual(a["ok"], False)
        self.assertIn("seats", a["error"])
        code, v = self.req("GET", "/api/license/verify?key=" + key)
        self.assertFalse(v["ok"])
        # 幂等：重复激活同一机器不重复占座
        code, a = self.req("POST", "/api/license/activate", {"key": key, "machine": "mac-a"})
        self.assertTrue(a["ok"])
        # 吊销后核验与激活均拒绝
        code, rows = self.req("GET", "/api/licenses", token="test-admin-token")
        code, r = self.req("POST", "/api/licenses/revoke", {"id": rows[0]["id"]}, token="test-admin-token")
        self.assertTrue(r["ok"])
        code, v = self.req("GET", "/api/license/verify?key=" + key)
        self.assertEqual(v["error"], "revoked")
        code, a = self.req("POST", "/api/license/activate", {"key": key, "machine": "mac-d"})
        self.assertFalse(a["ok"])
        # 坏密钥
        code, v = self.req("GET", "/api/license/verify?key=DGA1-pro-99991231-deadbeefdeadbeef")
        self.assertFalse(v["ok"])

    def test_client_online_verify_against_server(self):
        """客户端 core.edition.verify_online 在线复核：通过 → 吊销后反映 revoked。"""
        from core import edition
        code, body = self.req("POST", "/api/license/issue",
                              {"edition": "pro", "expires": "29990101"},
                              token="test-admin-token")
        self.assertEqual(code, 200)
        key = body["key"]
        result = edition.verify_online({"server_url": self.base}, key=key, timeout=5)
        self.assertTrue(result["online"])
        self.assertTrue(result["ok"])
        code, rows = self.req("GET", "/api/licenses", token="test-admin-token")
        code, r = self.req("POST", "/api/licenses/revoke", {"id": rows[0]["id"]}, token="test-admin-token")
        self.assertTrue(r["ok"])
        result = edition.verify_online({"server_url": self.base}, key=key, timeout=5)
        self.assertTrue(result["online"])
        self.assertEqual(result.get("error"), "revoked")


if __name__ == "__main__":
    unittest.main()
