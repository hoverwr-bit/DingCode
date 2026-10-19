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
                return resp.status, json.loads(raw.decode() or "null") if raw else None
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


if __name__ == "__main__":
    unittest.main()
