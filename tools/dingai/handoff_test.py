import io
import os
import subprocess
import tempfile
import unittest

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
