import io
import json
import os
import subprocess
import tempfile
import unittest

os.environ.setdefault("DINGAI_SESSIONS", "0")

import handoff


class HandoffTests(unittest.TestCase):
    def test_default_rules_cover_the_owner_list(self):
        text = handoff.DEFAULT_RULES
        for phrase in ("smallest change", "ARCHITECTURE", "pinned element", "dependencies", "verified"):
            self.assertIn(phrase, text)

    def test_project_file_overrides_the_home_file(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as project:
            os.makedirs(os.path.join(home, "DingCode"))
            os.makedirs(os.path.join(project, ".dingcode"))
            with open(os.path.join(home, "DingCode", "handoff-rules.md"), "w", encoding="utf-8") as fh:
                fh.write("home rule\n")
            with open(os.path.join(project, ".dingcode", "handoff-rules.md"), "w", encoding="utf-8") as fh:
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
        self.assertEqual(init["result"]["serverInfo"]["name"], "dingcode")
        listed = handoff.handle_rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(listed["result"]["tools"][0]["name"], "dingcode_handoff")
        called = handoff.handle_rpc({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "dingcode_handoff", "arguments": {"note": "{\"pins\":[]}"}},
        })
        body = called["result"]["content"][0]["text"]
        self.assertIn("smallest change", body)
        self.assertIn('{"pins":[]}', body)
        aliased = handoff.handle_rpc({
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "dingai_handoff", "arguments": {"note": "{\"pins\":[]}"}},
        })
        self.assertIn('{"pins":[]}', aliased["result"]["content"][0]["text"])
        self.assertIsNone(handoff.handle_rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_framing_roundtrip(self):
        handoff._NDJSON[0] = False
        raw = io.BytesIO()
        handoff.write_message({"jsonrpc": "2.0", "id": 1, "method": "ping"}, raw)
        self.assertTrue(raw.getvalue().startswith(b"Content-Length:"))
        raw.seek(0)
        msg = handoff.read_message(raw)
        self.assertEqual(msg["method"], "ping")
        reply = handoff.handle_rpc(msg)
        self.assertEqual(reply["result"], {})

    def test_ndjson_initialize_and_tools_list(self):
        handoff._NDJSON[0] = False
        stdin = io.BytesIO(
            b'{"jsonrpc":"2.0","id":1,"method":"initialize"}\n'
            b'{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n'
        )
        stdout = io.BytesIO()
        try:
            handoff.serve_mcp(stdin, stdout)
            lines = [line for line in stdout.getvalue().split(b"\n") if line]
            self.assertEqual(len(lines), 2)
            self.assertFalse(any(line.startswith(b"Content-Length") for line in lines))
            init = json.loads(lines[0])
            listed = json.loads(lines[1])
            self.assertEqual(init["id"], 1)
            self.assertEqual(init["result"]["serverInfo"]["name"], "dingcode")
            names = [tool["name"] for tool in listed["result"]["tools"]]
            self.assertIn("dingcode_handoff", names)
            self.assertEqual(listed["id"], 2)
        finally:
            handoff._NDJSON[0] = False

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
                    "params": {"name": "dingcode_list_pins", "arguments": {}},
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
                self.assertEqual(names["result"]["tools"][0]["name"], "dingcode_handoff")
                self.assertIn("dingcode_mark_fixed", [tool["name"] for tool in names["result"]["tools"]])
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
        self.git(root, "config", "user.name", "DingCode")
        os.makedirs(os.path.join(root, "src"))
        os.makedirs(os.path.join(root, ".dingcode"))
        with open(os.path.join(root, "src", "app.txt"), "w", encoding="utf-8") as fh:
            fh.write("start\n")
        with open(os.path.join(root, ".dingcode", "scope.txt"), "w", encoding="utf-8") as fh:
            fh.write("src/\n")
        self.git(root, "add", "src", ".dingcode")
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
