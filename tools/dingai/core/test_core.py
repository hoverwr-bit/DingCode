import json
import os
import tempfile
import unittest

from core.layout import layout_callouts
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
            audit = open(os.path.join(root, "releases", "audit.jsonl"), encoding="utf-8").read()
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
            self.assertTrue(open(md["path"], encoding="utf-8").read().startswith("# DingAI release"))


if __name__ == "__main__":
    unittest.main()
