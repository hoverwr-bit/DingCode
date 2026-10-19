import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dingai_linux as linux


class LinuxClientTests(unittest.TestCase):
    def test_note_carries_type_status_and_spaced_labels(self):
        note = linux.build_note(
            [
                {"id": 1, "x": 100, "y": 100, "pin_type": "bug", "note": "a"},
                {"id": 2, "x": 110, "y": 100, "pin_type": "question", "note": "b"},
            ],
            800, 600, True,
        )
        self.assertEqual(note["schema"], "dingai-desktop-v1")
        self.assertEqual(note["platform"], "linux")
        self.assertEqual([p["pin_type"] for p in note["pins"]], ["bug", "question"])
        self.assertTrue(all(p["status"] == "open" for p in note["pins"]))
        self.assertEqual(len(note["labels"]), 2)
        a, b = note["labels"]
        self.assertFalse(a["x_px"] < b["x_px"] + b["w_px"] and b["x_px"] < a["x_px"] + a["w_px"] and a["y_px"] < b["y_px"] + b["h_px"] and b["y_px"] < a["y_px"] + a["h_px"])

    def test_two_clicks_record_an_arrow_and_a_box(self):
        session = linux.Session()
        session.add_mark("arrow", 10, 20, 30, 40)
        session.add_mark("box", 50, 60, 80, 90)
        session.add_mark("spotlight", 5, 6, 15, 26)
        self.assertEqual(session.arrows[0]["to_px"], [30, 40])
        self.assertEqual(session.boxes[0]["rect_px"], [50, 60, 30, 30])
        self.assertEqual(session.boxes[1]["shape"], "spotlight")

    def test_export_writes_the_prompt_bundle(self):
        session = linux.Session()
        session.add_pin(10, 20)
        with tempfile.TemporaryDirectory() as tmp:
            note = session.export(tmp)
            self.assertGreaterEqual(note["pin_count"], 1)
            prompt = Path(tmp, "prompt.txt").read_text(encoding="utf-8")
            self.assertIn("pinned element", prompt)
            bundles = list(Path(tmp, "export").iterdir())
            self.assertEqual(len(bundles), 1)
            self.assertTrue((bundles[0] / "prompt.txt").is_file())
            self.assertTrue((bundles[0] / "note.json").is_file())

    def test_x11_capture_when_display_is_open(self):
        caps = linux.capabilities()
        if not os.environ.get("DISPLAY"):
            self.assertFalse(caps["x11"])
            return
        self.assertTrue(caps["x11"])
        shot = linux.capture_x11(16, 16)
        self.assertTrue(shot[2].startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
