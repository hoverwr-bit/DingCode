import json
import os
import tempfile
import unittest
from pathlib import Path

from core.diff import compare_png, write_diff
from core.export import EXPORTERS, export_note, register_exporter
from core.guide import sop_markdown, write_bundle
from core.layout import layout_callouts
from core.redact import decode_png, encode_png, pixelate_png, redact_note, redact_text
from core.voice import transcribe
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


class ExportTests(unittest.TestCase):
    def test_markdown_checklist_and_github_stays_local_without_a_token(self):
        note = {"pins": [{"pin_type": "bug", "status": "open", "note": "Save fails", "source": {"file": "src/Save.tsx", "line": 12}}]}
        with tempfile.TemporaryDirectory() as tmp:
            saved = export_note("markdown", note, tmp)
            text = Path(saved["path"]).read_text(encoding="utf-8")
            self.assertIn("- [ ] bug: Save fails (src/Save.tsx:12)", text)
            old = {key: os.environ.pop(key, None) for key in ("GITHUB_TOKEN", "GH_TOKEN", "DINGAI_GITHUB_REPO")}
            try:
                posted = export_note("github", note, tmp)
            finally:
                for key, value in old.items():
                    if value is not None:
                        os.environ[key] = value
            self.assertFalse(posted["posted"])
            self.assertTrue(posted["path"].endswith("github-issue.md"))
        self.assertIn("markdown", EXPORTERS)
        self.assertIn("github", EXPORTERS)

        def jira(note, dest, options):
            return {"ok": True, "exporter": "jira"}

        register_exporter("jira", jira)
        self.assertEqual(export_note("jira", {}, ".")["exporter"], "jira")
        missing = export_note("feishu", {}, ".")
        self.assertFalse(missing["ok"])


class DiffTests(unittest.TestCase):
    def test_identical_images_have_no_change_and_a_changed_pixel_is_marked(self):
        png = encode_png(2, 1, bytes([10, 10, 10, 10, 10, 10]))
        same = compare_png(png, png)
        self.assertEqual(same["changed_ratio"], 0)
        other = encode_png(2, 1, bytes([10, 10, 10, 250, 10, 10]))
        changed = compare_png(png, other)
        self.assertGreater(changed["changed_ratio"], 0)
        with tempfile.TemporaryDirectory() as tmp:
            before = Path(tmp) / "before.png"
            after = Path(tmp) / "after.png"
            before.write_bytes(png)
            after.write_bytes(other)
            info = write_diff(before, after, Path(tmp) / "out")
            self.assertTrue(info["ok"])
            self.assertTrue((Path(tmp) / "out" / "side-by-side.png").is_file())
            self.assertTrue((Path(tmp) / "out" / "overlay.png").is_file())


class GuideTests(unittest.TestCase):
    def test_sop_and_repro_bundle(self):
        text = sop_markdown([{"note": "Open the order", "shot": "step-1.png"}, {"text": "Save"}])
        self.assertIn("1. Open the order", text)
        self.assertIn("![](step-1.png)", text)
        self.assertIn("2. Save", text)
        with tempfile.TemporaryDirectory() as tmp:
            bundle = write_bundle(tmp, [{"note": "Open", "shot": "step-1.png", "png": b"\x89PNG"}])
            self.assertEqual(bundle["schema"], "dingai-steps-v1")
            self.assertTrue((Path(tmp) / "sop.md").is_file())
            self.assertEqual((Path(tmp) / "step-1.png").read_bytes(), b"\x89PNG")


class VoiceTests(unittest.TestCase):
    def test_transcribe_uses_a_local_binary_for_zh_en_vi(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = os.path.join(tmp, "whisper-cli")
            with open(binary, "w", encoding="utf-8") as fh:
                fh.write("#!/bin/sh\nprintf '%s' \"$6\"\n")
            os.chmod(binary, 0o755)
            wav = os.path.join(tmp, "in.wav")
            with open(wav, "wb") as fh:
                fh.write(b"RIFF")
            old = {key: os.environ.get(key) for key in ("DINGAI_WHISPER", "DINGAI_WHISPER_MODEL", "DINGAI_WHISPER_LANG")}
            os.environ["DINGAI_WHISPER"] = binary
            os.environ["DINGAI_WHISPER_MODEL"] = wav
            os.environ["DINGAI_WHISPER_LANG"] = "vi"
            try:
                self.assertEqual(transcribe(wav), "vi")
                self.assertEqual(transcribe(wav, lang="en"), "en")
                self.assertEqual(transcribe(wav, lang="zh"), "zh")
                self.assertEqual(transcribe(wav, lang="fr"), "zh")
                self.assertEqual(transcribe(os.path.join(tmp, "missing.wav")), "")
            finally:
                for key, value in old.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
