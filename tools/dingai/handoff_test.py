import io
import os
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


if __name__ == "__main__":
    unittest.main()
