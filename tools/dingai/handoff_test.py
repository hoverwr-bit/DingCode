import base64
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection

import handoff


class HandoffTests(unittest.TestCase):
    def test_default_rules_cover_the_owner_list(self):
        text = handoff.DEFAULT_RULES
        for phrase in ("smallest change", "ARCHITECTURE", "pinned element", "dependencies", "verified"):
            self.assertIn(phrase, text)

    def test_project_file_overrides_the_home_file(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as project:
            os.makedirs(os.path.join(home, "DingAI"))
            os.makedirs(os.path.join(project, ".dingai"))
            with open(os.path.join(home, "DingAI", "handoff-rules.md"), "w", encoding="utf-8") as fh:
                fh.write("home rule\n")
            with open(os.path.join(project, ".dingai", "handoff-rules.md"), "w", encoding="utf-8") as fh:
                fh.write("project rule\n")
            old_home = os.environ.get("HOME")
            old_project = os.environ.get("DINGAI_PROJECT")
            os.environ["HOME"] = home
            os.environ["DINGAI_PROJECT"] = project
            try:
                self.assertEqual(handoff.load_rules(), "project rule")
                del os.environ["DINGAI_PROJECT"]
                self.assertEqual(handoff.load_rules(), "home rule")
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home
                if old_project is None:
                    os.environ.pop("DINGAI_PROJECT", None)
                else:
                    os.environ["DINGAI_PROJECT"] = old_project

    def test_prompt_wraps_the_note(self):
        text = handoff.prompt_for('{"tool":"dingai"}', "rule-a")
        self.assertTrue(text.startswith("rule-a\n"))
        self.assertIn("pinned element", text)
        self.assertTrue(text.endswith('{"tool":"dingai"}'))

    def test_mcp_lists_and_calls_the_tool(self):
        init = handoff.handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertEqual(init["result"]["serverInfo"]["name"], "dingai")
        listed = handoff.handle_rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(listed["result"]["tools"][0]["name"], "dingai_handoff")
        called = handoff.handle_rpc({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "dingai_handoff", "arguments": {"note": "{\"pins\":[]}"}},
        })
        body = called["result"]["content"][0]["text"]
        self.assertIn("smallest change", body)
        self.assertIn('{"pins":[]}', body)
        self.assertIsNone(handoff.handle_rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_framing_roundtrip(self):
        raw = io.BytesIO()
        handoff.write_message({"jsonrpc": "2.0", "id": 1, "method": "ping"}, raw)
        raw.seek(0)
        msg = handoff.read_message(raw)
        self.assertEqual(msg["method"], "ping")
        reply = handoff.handle_rpc(msg)
        self.assertEqual(reply["result"], {})

    def test_lists_and_marks_a_shared_folder_pin(self):
        import core.sync as sync
        keys = ("DINGAI_MODE", "DINGAI_SHARE_DIR", "DINGAI_TEAM_URLS", "ANNO_TEAM_URLS", "DINGAI_PROJECT_NAME")
        saved = {key: os.environ.get(key) for key in keys}
        with tempfile.TemporaryDirectory() as share:
            os.environ["DINGAI_MODE"] = "folder"
            os.environ["DINGAI_SHARE_DIR"] = share
            os.environ["DINGAI_TEAM_URLS"] = ""
            os.environ["ANNO_TEAM_URLS"] = ""
            os.environ["DINGAI_PROJECT_NAME"] = "inbox"
            try:
                sync.publish_note({
                    "file": "note-a",
                    "project": "inbox",
                    "screenshot": "anno.png",
                    "pins": [{"id": 1, "x_px": 4, "y_px": 5, "pin_type": "bug", "note": "gap"}],
                }, b"\x89PNG\r\n", sync.load_settings())
                listed = handoff.handle_rpc({
                    "jsonrpc": "2.0", "id": 4, "method": "tools/call",
                    "params": {"name": "dingai_list_pins", "arguments": {}},
                })
                pins = listed["result"]["structured"]["pins"]
                self.assertEqual(pins[0]["note_id"], "note-a")
                self.assertTrue(pins[0]["screenshot_path"].endswith("anno.png"))
                png = os.path.join(share, "verify.png")
                with open(png, "wb") as fh:
                    fh.write(b"\x89PNG\r\nverify")
                marked = handoff.mark_fixed({
                    "note_id": "note-a", "pin_id": "1", "verification_path": png, "comment": "checked",
                })
                self.assertTrue(marked["ok"])
                self.assertEqual(marked["pin"]["status"], "ai-fixed")
                self.assertEqual(marked["pin"]["verification"], "verify-note-a-1.png")
                names = handoff.handle_rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
                self.assertEqual(names["result"]["tools"][0]["name"], "dingai_handoff")
                self.assertIn("dingai_mark_fixed", [tool["name"] for tool in names["result"]["tools"]])
                self.assertIn("dingai_screenshot", [tool["name"] for tool in names["result"]["tools"]])
            finally:
                for key, value in saved.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value


class TransportTests(unittest.TestCase):
    def test_stdio_accepts_ndjson_and_content_length(self):
        stdin = io.BytesIO((json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26"},
        }) + "\n").encode("utf-8"))
        stdout = io.BytesIO()
        handoff.serve_mcp(stdin, stdout)
        stdout.seek(0)
        reply = json.loads(stdout.readline().decode("utf-8"))
        self.assertEqual(reply["result"]["protocolVersion"], "2025-03-26")
        self.assertIn("resources", reply["result"]["capabilities"])
        self.assertEqual(reply["result"]["serverInfo"]["name"], "dingai")

        framed = io.BytesIO()
        handoff.write_message({"jsonrpc": "2.0", "id": 7, "method": "ping"}, framed)
        framed.seek(0)
        out = io.BytesIO()
        handoff.serve_mcp(framed, out)
        out.seek(0)
        self.assertTrue(out.read(15).lower().startswith(b"content-length"))

    def test_http_initialize_lists_and_rejects_sse(self):
        server = handoff.make_http_server("127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        body = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        }).encode("utf-8")
        conn.request("POST", "/mcp", body=body, headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.getheader("Mcp-Session-Id"), "dingai")
        self.assertIn("application/json", resp.getheader("Content-Type"))
        payload = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(payload["result"]["serverInfo"]["name"], "dingai")
        self.assertEqual(payload["result"]["tools"] if "tools" in payload["result"] else payload["result"]["protocolVersion"], "2025-06-18")
        conn.request("GET", "/mcp")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 405)
        resp.read()
        note = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode("utf-8")
        conn.request("POST", "/mcp", body=note, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 202)
        resp.read()
        conn.request("POST", "/mcp", body=json.dumps({
            "jsonrpc": "2.0", "id": 2, "method": "tools/list",
        }).encode("utf-8"), headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        listed = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(listed["result"]["tools"][0]["name"], "dingai_handoff")
        self.assertIn("dingai_mark_fixed", [tool["name"] for tool in listed["result"]["tools"]])
        conn.close()

    def test_http_requires_the_token_when_set(self):
        old = os.environ.get("DINGAI_MCP_TOKEN")
        os.environ["DINGAI_MCP_TOKEN"] = "test-token"
        server = handoff.make_http_server("127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        try:
            conn = HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
            body = b'{"jsonrpc":"2.0","id":1,"method":"ping"}'
            conn.request("POST", "/mcp", body=body, headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            self.assertEqual(resp.status, 401)
            resp.read()
            conn.request("POST", "/mcp", body=body, headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer test-token",
            })
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            self.assertEqual(json.loads(resp.read().decode("utf-8"))["result"], {})
            conn.close()
        finally:
            if old is None:
                os.environ.pop("DINGAI_MCP_TOKEN", None)
            else:
                os.environ["DINGAI_MCP_TOKEN"] = old

    def test_latest_pins_screenshot_and_bundle(self):
        keys = ("HOME", "DINGAI_OUTPUT_DIR", "DINGAI_MODE", "DINGAI_SHARE_DIR", "DINGAI_TEAM_URLS", "ANNO_TEAM_URLS")
        saved = {key: os.environ.get(key) for key in keys}
        with tempfile.TemporaryDirectory() as home:
            os.environ["HOME"] = home
            os.environ["DINGAI_OUTPUT_DIR"] = "DingAI"
            os.environ["DINGAI_MODE"] = "local"
            os.environ["DINGAI_SHARE_DIR"] = ""
            os.environ["DINGAI_TEAM_URLS"] = ""
            os.environ["ANNO_TEAM_URLS"] = ""
            try:
                notes = os.path.join(home, "DingAI", "notes")
                shots = os.path.join(home, "DingAI", "shots")
                os.makedirs(notes)
                os.makedirs(shots)
                png = b"\x89PNG\r\n\x1a\nlocal"
                with open(os.path.join(shots, "anno.png"), "wb") as fh:
                    fh.write(png)
                note = {"file": "note-1", "screenshot": "anno.png", "pins": [{"id": 1, "note": "gap"}]}
                with open(os.path.join(notes, "a.json"), "w", encoding="utf-8") as fh:
                    json.dump(note, fh)
                payload = handoff.latest_pins_json()
                self.assertEqual(payload["mode"], "local")
                self.assertEqual(payload["pins"][0]["id"], 1)
                self.assertTrue(payload["screenshot"].endswith("anno.png"))
                folder = handoff.write_export_bundle(json.dumps(note), png, os.path.join(home, "DingAI", "export"))
                self.assertTrue(os.path.isfile(os.path.join(folder, "prompt.txt")))
                self.assertTrue(os.path.isfile(os.path.join(folder, "note.json")))
                with open(os.path.join(folder, "screenshot.png"), "rb") as fh:
                    self.assertEqual(fh.read(), png)
                with open(os.path.join(folder, "prompt.txt"), encoding="utf-8") as fh:
                    self.assertIn("pinned element", fh.read())
                listed = handoff.handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "resources/list"})
                uris = [row["uri"] for row in listed["result"]["resources"]]
                self.assertIn("dingai://screenshot/note-1/1", uris)
                read = handoff.handle_rpc({
                    "jsonrpc": "2.0", "id": 2, "method": "resources/read",
                    "params": {"uri": "dingai://screenshot/note-1/1"},
                })
                self.assertEqual(base64.b64decode(read["result"]["contents"][0]["blob"]), png)
                called = handoff.handle_rpc({
                    "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "dingai_screenshot", "arguments": {"note_id": "note-1", "pin_id": "1"}},
                })
                self.assertEqual(called["result"]["content"][0]["mimeType"], "image/png")
                script = os.path.join(os.path.dirname(__file__), "dingai")
                env = os.environ.copy()
                proc = subprocess.run([sys.executable, script], capture_output=True, env=env, check=False)
                self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
                printed = json.loads(proc.stdout.decode("utf-8"))
                self.assertEqual(printed["pins"][0]["note"], "gap")
            finally:
                for key, value in saved.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value


class ScopeTests(unittest.TestCase):
    def git(self, cwd, *args):
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

    def repo(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = tmp.name
        self.git(root, "init", "-q")
        self.git(root, "config", "user.email", "dingai@example.com")
        self.git(root, "config", "user.name", "DingAI")
        os.makedirs(os.path.join(root, "src"))
        os.makedirs(os.path.join(root, ".dingai"))
        with open(os.path.join(root, "src", "app.txt"), "w", encoding="utf-8") as fh:
            fh.write("start\n")
        with open(os.path.join(root, ".dingai", "scope.txt"), "w", encoding="utf-8") as fh:
            fh.write("src/\n")
        self.git(root, "add", "src", ".dingai")
        self.git(root, "commit", "-q", "-m", "init")
        saved = handoff.record_baseline(root)
        self.assertTrue(saved and saved["head"])
        return root

    def test_warns_and_reject_restores_uncommitted_files(self):
        root = self.repo()
        with open(os.path.join(root, "package.json"), "w", encoding="utf-8") as fh:
            fh.write("{}\n")
        with open(os.path.join(root, "src", "app.txt"), "w", encoding="utf-8") as fh:
            fh.write("changed\n")
        os.makedirs(os.path.join(root, "fresh"))
        with open(os.path.join(root, "fresh", "new.txt"), "w", encoding="utf-8") as fh:
            fh.write("x\n")
        report = handoff.scope_check(root)
        kinds = {item["kind"] for item in report["warnings"]}
        self.assertIn("outside", kinds)
        self.assertIn("dependency", kinds)
        self.assertIn("module", kinds)
        self.assertFalse(report["head_moved"])
        result = handoff.reject_changes(None, root)
        self.assertTrue(result["ok"])
        with open(os.path.join(root, "src", "app.txt"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "changed\n")
        self.assertFalse(os.path.exists(os.path.join(root, "package.json")))
        self.assertFalse(os.path.exists(os.path.join(root, "fresh", "new.txt")))

    def test_reject_refuses_when_head_moved(self):
        root = self.repo()
        with open(os.path.join(root, "src", "app.txt"), "w", encoding="utf-8") as fh:
            fh.write("committed\n")
        self.git(root, "add", "src/app.txt")
        self.git(root, "commit", "-q", "-m", "later")
        result = handoff.reject_changes(None, root)
        self.assertFalse(result["ok"])
        self.assertIn("HEAD moved", result["error"])
        with open(os.path.join(root, "src", "app.txt"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "committed\n")

    def test_reject_restores_a_tracked_file_outside_scope(self):
        root = self.repo()
        with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as fh:
            fh.write("note\n")
        self.git(root, "add", "README.md")
        result = handoff.reject_changes(None, root)
        self.assertTrue(result["ok"])
        self.assertIn("README.md", result["restored"])
        self.assertFalse(os.path.exists(os.path.join(root, "README.md")))

    def test_size_warning(self):
        root = self.repo()
        for i in range(9):
            with open(os.path.join(root, "src", "f%d.txt" % i), "w", encoding="utf-8") as fh:
                fh.write("z\n")
        report = handoff.scope_check(root)
        self.assertIn("size", {item["kind"] for item in report["warnings"]})


if __name__ == "__main__":
    unittest.main()
