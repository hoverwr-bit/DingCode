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


class ReleaseTests(unittest.TestCase):
    def test_review_blocks_publish_until_an_admin_override_and_then_stays_read_only(self):
        from core.release import decide, export_release, load_release, open_release, publish, rollback, search_releases
        import zipfile
        with tempfile.TemporaryDirectory() as root:
            before = os.path.join(root, "before.png")
            after = os.path.join(root, "after.png")
            with open(before, "wb") as fh:
                fh.write(b"\x89PNG-before")
            with open(after, "wb") as fh:
                fh.write(b"\x89PNG-after")
            first = open_release(
                root,
                [{"note_id": "note-a", "pin_id": 1, "x_px": 200, "y_px": 100, "note": "gap", "project": "erp"}],
                version="1", tag="v1", project="erp", rules="smallest change",
                diff_summary=" src/erp/app.py | 2 +-",
                scope_warnings=[{"kind": "outside", "detail": "files outside .dingai/scope.txt", "paths": ["src/other.py"]}],
                head="abc123", commits=["abc123"],
                shots={"note-a:1": {"before": before, "after": after}},
            )
            with open(os.path.join(root, "releases", first["id"], "review.html"), encoding="utf-8") as fh:
                page = fh.read()
            self.assertIn("gap", page)
            self.assertIn("files outside .dingai/scope.txt", page)
            self.assertIn("src/erp/app.py", page)
            self.assertIn("smallest change", page)
            self.assertIn("margin-left:-80px", page)
            self.assertIn("margin-top:-20px", page)
            self.assertTrue(os.path.isfile(os.path.join(root, "releases", first["id"], first["pins"][0]["before"])))
            blocked = publish(root, first["id"], actor="ada", admin=False)
            self.assertFalse(blocked["ok"])
            self.assertEqual(blocked["blocked"][0]["decision"], "unreviewed")
            decide(root, first["id"], "note-a:1", "reject", "sam")
            still = publish(root, first["id"], actor="ada", admin=True, override_reason="")
            self.assertFalse(still["ok"])
            published = publish(root, first["id"], actor="ada", admin=True, override_reason="ship the known reject")
            self.assertTrue(published["ok"])
            self.assertEqual(published["release"]["overrides"][0]["reason"], "ship the known reject")
            self.assertTrue(published["release"]["immutable"])
            with open(os.path.join(root, "releases", "audit.jsonl"), encoding="utf-8") as fh:
                audit = fh.read()
            self.assertIn("ship the known reject", audit)
            again = decide(root, first["id"], "note-a:1", "approve", "ada")
            self.assertEqual(again["error"], "read-only")
            saved = load_release(root, first["id"])
            self.assertEqual(saved["pins"][0]["decision"], "reject")
            second = open_release(root, [], version="2", tag="v2", parent_id=first["id"], rules="smallest change", head="def456")
            publish(root, second["id"], actor="ada", admin=True)
            back = rollback(root, second["id"], actor="ada")
            self.assertTrue(back["ok"])
            self.assertEqual(back["release"]["restores"], first["id"])
            self.assertEqual(back["release"]["status"], "draft")
            self.assertEqual(load_release(root, first["id"])["status"], "published")
            self.assertTrue(back["release"]["pins"][0]["before"])
            found = search_releases(root, "v1")
            self.assertTrue(any(row["id"] == first["id"] for row in found))
            dest = os.path.join(root, "out")
            os.makedirs(dest)
            exported = export_release(root, first["id"], "zip", dest)
            self.assertTrue(exported["ok"])
            with zipfile.ZipFile(exported["path"]) as zf:
                names = zf.namelist()
                self.assertTrue(any(name.endswith("release.md") for name in names))
                self.assertTrue(any(name.endswith(".png") for name in names))
                text = zf.read([name for name in names if name.endswith("release.md")][0]).decode("utf-8")
            self.assertIn("smallest change", text)
            self.assertIn("abc123", text)
            md = export_release(root, first["id"], "markdown", os.path.join(dest, "one.md"))
            with open(md["path"], encoding="utf-8") as fh:
                self.assertTrue(fh.read().startswith("# DingAI release"))


class CollisionTests(unittest.TestCase):
    def test_warns_for_shared_work_and_records_the_choice(self):
        import subprocess
        from core.collide import choose, end_session, list_sessions, load_session, read_notices, register
        with tempfile.TemporaryDirectory() as root:
            first = register(root, {
                "agent": "codex", "repo": "/repos/erp", "branch": "main", "project": "erp",
                "pins": ["note:1"], "pin_projects": {"note:1": "erp"}, "paths": ["src/erp"],
                "ports": ["8080"], "databases": ["erp"], "deploys": ["erp-prod"], "services": ["erp-api"],
                "head": "aaa",
            }, current_head="aaa")
            self.assertEqual(first["warnings"], [])
            second = register(root, {
                "agent": "claude", "repo": "/repos/erp", "branch": "main", "project": "portal",
                "pins": ["note:1"], "pin_projects": {"note:2": "erp"}, "paths": ["src/erp/app.py"],
                "ports": ["8080"], "head": "aaa",
            }, current_head="bbb")
            kinds = {item["kind"] for item in second["warnings"]}
            self.assertIn("same-branch", kinds)
            self.assertIn("overlap", kinds)
            self.assertIn("pin", kinds)
            self.assertIn("wrong-window", kinds)
            self.assertIn("target", kinds)
            self.assertIn("stale", kinds)
            self.assertIn("Two sessions share", read_notices(root)["banners"][0]["text"])
            queued = choose(root, second["session"]["id"], "queue", actor="ada")
            self.assertEqual(queued["session"]["status"], "queued")
            self.assertTrue(queued["session"]["log"])
            self.assertEqual(queued["session"]["locks"], [])
            continued = choose(root, second["session"]["id"], "continue", actor="ada")
            self.assertEqual(continued["session"]["log"][-1]["choice"], "continue")
            handed = choose(root, second["session"]["id"], "hand", actor="ada")
            owner = load_session(root, first["session"]["id"])
            self.assertIn("note:1", owner["pins"])
            self.assertNotIn("note:1", handed["session"]["pins"])
            ended = end_session(root, first["session"]["id"], differ=lambda path, left, right: "left %s\nright %s\n%s" % (left, right, path))
            self.assertTrue(ended["overlaps"])
            self.assertIn("src/erp", ended["overlaps"][0]["diff"])
            self.assertEqual(len([row for row in list_sessions(root) if row["id"] == first["session"]["id"]]), 0)

    def test_isolate_creates_a_worktree(self):
        import subprocess
        from core.collide import choose, register
        with tempfile.TemporaryDirectory() as root:
            repo = os.path.join(root, "repo")
            os.makedirs(repo)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "dingai@example.com"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "DingAI"], cwd=repo, check=True, capture_output=True)
            with open(os.path.join(repo, "app.txt"), "w", encoding="utf-8") as fh:
                fh.write("start\n")
            subprocess.run(["git", "add", "app.txt"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True, capture_output=True)
            opened = register(root, {"agent": "codex", "repo": repo, "branch": "main", "paths": ["app.txt"]})
            isolated = choose(root, opened["session"]["id"], "isolate", actor="ada")
            self.assertTrue(isolated["session"]["isolate"]["ok"])
            self.assertTrue(os.path.isdir(isolated["session"]["isolate"]["path"]))
            self.assertTrue(isolated["session"]["branch"].startswith("dingai/"))


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
