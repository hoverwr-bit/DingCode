import json
import os
import tempfile
import unittest

from core.layout import layout_callouts
from core.redact import decode_png, encode_png, pixelate_png, redact_note, redact_text
from core.schema import normalize_note, normalize_pin
from core.sync import folder_set_status, list_folder_pins, publish_folder


class SchemaTests(unittest.TestCase):
    def test_unknown_type_and_status_fall_back(self):
        pin = normalize_pin({"id": 3, "x_px": 10, "y_px": 12, "pin_type": "nope", "status": "done"})
        self.assertEqual(pin["pin_type"], "bug")
        self.assertEqual(pin["status"], "open")

    def test_note_counts_pins(self):
        note = normalize_note({"platform": "linux", "pins": [{"id": 1, "x_px": 4, "y_px": 5, "pin_type": "question"}]})
        self.assertEqual(note["schema"], "dingai-desktop-v1")
        self.assertEqual(note["pin_count"], 1)
        self.assertEqual(note["pins"][0]["pin_type"], "question")
        self.assertEqual(note["pins"][0]["status"], "open")


class LayoutTests(unittest.TestCase):
    def test_prefers_the_right_and_avoids_overlap(self):
        bounds = {"x": 0, "y": 0, "w": 800, "h": 600}
        one = layout_callouts([{"id": 1, "ax": 100, "ay": 100, "w": 40, "h": 20}], [], bounds)[0]
        self.assertEqual(one["x"], 118)
        self.assertEqual(one["y"], 90)
        self.assertTrue(one["leader"])
        two = layout_callouts([
            {"id": 1, "ax": 100, "ay": 100, "w": 80, "h": 22},
            {"id": 2, "ax": 110, "ay": 100, "w": 80, "h": 22},
        ], [], bounds)
        def hits(a, b):
            x1, y1 = max(a["x"], b["x"]), max(a["y"], b["y"])
            x2, y2 = min(a["x"] + a["w"], b["x"] + b["w"]), min(a["y"] + a["h"], b["y"] + b["h"])
            return x2 > x1 and y2 > y1
        self.assertFalse(hits(two[0], two[1]))


class FolderSyncTests(unittest.TestCase):
    def test_two_writers_keep_both_pins(self):
        with tempfile.TemporaryDirectory() as root:
            note = {
                "project": "app",
                "file": "note-a",
                "screenshot": "shot.png",
                "pins": [
                    {"id": 1, "x_px": 1, "y_px": 2, "pin_type": "bug"},
                    {"id": 2, "x_px": 8, "y_px": 9, "pin_type": "change"},
                ],
            }
            publish_folder(root, note, b"\x89PNG")
            other = dict(note)
            other["file"] = "note-b"
            other["pins"] = [{"id": 1, "x_px": 3, "y_px": 4, "pin_type": "question"}]
            publish_folder(root, other)
            rows = list_folder_pins(root, "app")
            self.assertEqual(len(rows), 3)
            updated = folder_set_status(root, "app", "note-a", 1, "ai-fixed", verification=b"png", comment="checked")
            self.assertEqual(updated["status"], "ai-fixed")
            self.assertEqual(updated["comments"][0]["body"], "checked")
            with open(os.path.join(root, "projects", "app", "pins", "note-a--1.json"), encoding="utf-8") as fh:
                saved = json.loads(fh.read())
            self.assertEqual(saved["verification"], "verify-note-a-1.png")


class RedactTests(unittest.TestCase):
    def test_builtin_patterns_and_custom_names(self):
        text = redact_text(
            "a@b.co 13800138000 0901234567 (415) 555-0134 PO-4481 ¥12.50 Acme",
            names=["Acme"],
        )
        for secret in ("a@b.co", "13800138000", "0901234567", "555-0134", "PO-4481", "¥12.50", "Acme"):
            self.assertNotIn(secret, text)
        self.assertIn("[redacted]", text)

    def test_invalid_user_pattern_is_skipped(self):
        self.assertEqual(redact_text("keep", patterns=["("], names=[]), "keep")

    def test_note_and_pixels_are_redacted_locally(self):
        rgb = bytearray()
        for i in range(8 * 8):
            rgb += bytes((255, 0, 0) if i % 2 == 0 else (0, 0, 255))
        png = encode_png(8, 8, bytes(rgb))
        note, out = redact_note(
            {"pins": [{"id": 1, "ocr_nearby": "mail a@b.co", "note": "Acme"}], "labels": [{"text": "a@b.co"}]},
            png,
            [{"x": 0, "y": 0, "w": 8, "h": 8}],
            names=["Acme"],
        )
        self.assertEqual(note["pins"][0]["ocr_nearby"], "mail [redacted]")
        self.assertEqual(note["pins"][0]["note"], "[redacted]")
        self.assertTrue(note["redacted"])
        self.assertNotEqual(out, png)
        width, height, rgb = decode_png(out)
        self.assertEqual((width, height), (8, 8))
        self.assertGreater(rgb[0], 0)
        self.assertGreater(rgb[2], 0)


if __name__ == "__main__":
    unittest.main()
