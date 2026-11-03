"""Release review and the read-only archive. Standard library only."""

import json
import os
import shutil
import time
import zipfile
from pathlib import Path


def releases_root(root):
    path = Path(root) / "releases"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _audit(root, row):
    path = releases_root(root) / "audit.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def pin_key(note_id, pin_id):
    return "%s:%s" % (note_id, pin_id)


def safe_release_id(rel_id):
    text = str(rel_id or "")
    if not text.startswith("rel-"):
        return False
    return text.replace("-", "").isalnum()


def safe_file_name(name):
    text = str(name or "")
    return bool(text) and text == os.path.basename(text) and ".." not in text


def _release_file(root, rel_id):
    return releases_root(root) / rel_id / "release.json"


def load_release(root, rel_id):
    if not safe_release_id(rel_id):
        return None
    path = _release_file(root, rel_id)
    if not path.is_file():
        return None
    data = _read(path)
    return data if isinstance(data, dict) else None


def list_releases(root):
    base = releases_root(root)
    rows = []
    for folder in sorted(base.iterdir()):
        path = folder / "release.json"
        if not path.is_file():
            continue
        try:
            rel = _read(path)
        except (OSError, ValueError):
            continue
        rows.append({
            "id": rel.get("id"),
            "status": rel.get("status"),
            "version": rel.get("version") or "",
            "tag": rel.get("tag") or "",
            "project": rel.get("project") or "",
            "published_at": rel.get("published_at") or "",
            "created_at": rel.get("created_at") or "",
        })
    return rows


def _crop_style(x_px, y_px):
    left = max(0, int(x_px or 0) - 120)
    top = max(0, int(y_px or 0) - 80)
    return left, top


def review_html(rel):
    def esc(value):
        return (str("" if value is None else value)
                .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))

    def shot(name, x_px, y_px, label):
        if not name:
            return "<p class='m'>no %s screenshot</p>" % esc(label)
        left, top = _crop_style(x_px, y_px)
        return "<div class='crop'><img src='%s' style='margin-left:-%dpx;margin-top:-%dpx' alt='%s'></div>" % (
            esc(name), left, top, esc(label))

    blocks = []
    for pin in rel.get("pins") or []:
        blocks.append(
            "<section><h2>%s</h2><p>%s</p><p class='m'>decision: %s · reviewer: %s · anchor %s,%s</p>"
            "<div class='pair'><div><b>before</b>%s</div><div><b>after</b>%s</div></div></section>"
            % (
                esc(pin.get("key")), esc(pin.get("note")),
                esc(pin.get("decision") or "unreviewed"), esc(pin.get("reviewer")),
                esc(pin.get("x_px")), esc(pin.get("y_px")),
                shot(pin.get("before"), pin.get("x_px"), pin.get("y_px"), "before"),
                shot(pin.get("after"), pin.get("x_px"), pin.get("y_px"), "after"),
            )
        )
    warnings = "".join("<li>%s</li>" % esc(item.get("detail") or item.get("kind")) for item in rel.get("scope_warnings") or [])
    overrides = "".join(
        "<li>%s %s: %s</li>" % (esc(item.get("at")), esc(item.get("actor")), esc(item.get("reason")))
        for item in rel.get("overrides") or []
    )
    commits = "".join("<li><code>%s</code></li>" % esc(item) for item in rel.get("commits") or [])
    restores = ""
    if rel.get("restores"):
        restores = "<p>Rollback of %s. Restores %s. The published archive is unchanged.</p>" % (
            esc(rel.get("rollback_of")), esc(rel.get("restores")))
    return (
        "<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'><title>DingAI %s</title>"
        "<style>body{font-family:-apple-system,sans-serif;margin:24px;background:#f6f7f9;color:#1c1e21}"
        "section{background:#fff;padding:12px 16px;margin:12px 0;border:1px solid #e2e4e8}"
        ".pair{display:flex;gap:16px}.crop{width:240px;height:160px;overflow:hidden;border:1px solid #ddd;background:#111}"
        "pre{white-space:pre-wrap;background:#f4f5f7;padding:8px}.m{color:#666;font-size:13px}</style></head><body>"
        "<h1>%s</h1><p class='m'>%s · version %s · tag %s · head %s · %s</p>%s"
        "<h2>Diff</h2><pre>%s</pre><h2>Commits</h2><ul>%s</ul>"
        "<h2>Scope warnings</h2><ul>%s</ul><h2>Handoff rules</h2><pre>%s</pre>"
        "<h2>Approved by</h2><p>%s</p><h2>Overrides</h2><ul>%s</ul>%s</body></html>"
    ) % (
        esc(rel.get("id")), esc(rel.get("id")), esc(rel.get("status")), esc(rel.get("version")),
        esc(rel.get("tag")), esc(rel.get("head")), esc(rel.get("published_at") or rel.get("created_at")),
        restores, esc(rel.get("diff_summary")), commits or "<li>none</li>",
        warnings or "<li>none</li>", esc(rel.get("rules")),
        esc(", ".join(rel.get("approvers") or []) or "pending"),
        overrides or "<li>none</li>", "\n".join(blocks),
    )


def _refresh_page(root, rel):
    folder = releases_root(root) / rel["id"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "review.html").write_text(review_html(rel), encoding="utf-8")


def _copy_shot(folder, key, side, src):
    if not src or not os.path.isfile(src):
        return ""
    name = "%s-%s.png" % (str(key).replace(":", "-").replace("/", "-"), side)
    if not safe_file_name(name):
        return ""
    shutil.copyfile(src, Path(folder) / name)
    return name


def open_release(root, pins, version="", tag="", project="", repo="", rules="", diff_summary="",
                 scope_warnings=None, head="", commits=None, parent_id="", shots=None):
    rel_id = "rel-%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), os.urandom(3).hex())
    folder = releases_root(root) / rel_id
    folder.mkdir(parents=True, exist_ok=True)
    shots = shots or {}
    clean = []
    for pin in pins or []:
        note_id = str(pin.get("note_id") or pin.get("file") or "note")
        pin_id = pin.get("pin_id") if pin.get("pin_id") is not None else pin.get("id")
        key = str(pin.get("key") or pin_key(note_id, pin_id))
        pair = shots.get(key) or {}
        entry = {
            "key": key,
            "note_id": note_id,
            "pin_id": "" if pin_id is None else str(pin_id),
            "project": pin.get("project") or project or "",
            "note": pin.get("note") or "",
            "x_px": int(pin.get("x_px") or 0),
            "y_px": int(pin.get("y_px") or 0),
            "before": _copy_shot(folder, key, "before", pair.get("before") or pin.get("before") or ""),
            "after": _copy_shot(folder, key, "after", pair.get("after") or pin.get("after") or ""),
            "decision": "",
            "reviewer": "",
            "decided_at": "",
        }
        clean.append(entry)
    rel = {
        "id": rel_id,
        "status": "draft",
        "immutable": False,
        "kind": "release",
        "version": version or "",
        "tag": tag or "",
        "project": project or "",
        "repo": repo or "",
        "head": head or "",
        "parent_id": parent_id or "",
        "created_at": _now(),
        "published_at": "",
        "rules": rules or "",
        "diff_summary": diff_summary or "",
        "commits": list(commits or []),
        "scope_warnings": list(scope_warnings or []),
        "pins": clean,
        "overrides": [],
        "approvers": [],
        "publisher": "",
        "rollback_of": "",
        "restores": "",
    }
    _write(folder / "release.json", rel)
    _refresh_page(root, rel)
    _audit(root, {"at": rel["created_at"], "action": "open", "id": rel_id, "parent_id": parent_id or ""})
    return rel


def _mutable(rel):
    return bool(rel) and not rel.get("immutable") and rel.get("status") != "published"


def decide(root, rel_id, key, decision, reviewer=""):
    rel = load_release(root, rel_id)
    if not rel:
        return {"ok": False, "error": "not found"}
    if not _mutable(rel):
        return {"ok": False, "error": "read-only"}
    if decision not in ("approve", "reject"):
        return {"ok": False, "error": "decision must be approve or reject"}
    found = False
    for pin in rel["pins"]:
        if pin["key"] == str(key) or (pin["note_id"] and pin_key(pin["note_id"], pin["pin_id"]) == str(key)):
            pin["decision"] = decision
            pin["reviewer"] = reviewer or ""
            pin["decided_at"] = _now()
            found = True
            break
    if not found:
        return {"ok": False, "error": "pin not in release"}
    _write(_release_file(root, rel_id), rel)
    _refresh_page(root, rel)
    _audit(root, {"at": pin["decided_at"], "action": decision, "id": rel_id, "pin": str(key), "reviewer": reviewer or ""})
    return {"ok": True, "release": rel}


def blockers(rel):
    rows = []
    for pin in rel.get("pins") or []:
        if pin.get("decision") != "approve":
            rows.append({"key": pin.get("key"), "decision": pin.get("decision") or "unreviewed"})
    return rows


def publish(root, rel_id, actor="", admin=False, override_reason=""):
    rel = load_release(root, rel_id)
    if not rel:
        return {"ok": False, "error": "not found"}
    if not _mutable(rel):
        return {"ok": False, "error": "read-only"}
    blocked = blockers(rel)
    if blocked:
        reason = (override_reason or "").strip()
        if not admin or not reason:
            return {"ok": False, "error": "unreviewed or rejected pins", "blocked": blocked}
        rel["overrides"].append({
            "at": _now(), "actor": actor or "admin", "reason": reason, "blocked": blocked,
        })
        _audit(root, {"at": rel["overrides"][-1]["at"], "action": "override", "id": rel_id, "actor": actor or "admin", "reason": reason})
    rel["status"] = "published"
    rel["immutable"] = True
    rel["published_at"] = _now()
    rel["publisher"] = actor or ""
    names = []
    for pin in rel["pins"]:
        if pin.get("decision") == "approve" and pin.get("reviewer") and pin["reviewer"] not in names:
            names.append(pin["reviewer"])
    if actor and actor not in names:
        names.append(actor)
    rel["approvers"] = names
    _write(_release_file(root, rel_id), rel)
    _refresh_page(root, rel)
    _write(releases_root(root) / "current.json", {"id": rel_id, "at": rel["published_at"]})
    _audit(root, {"at": rel["published_at"], "action": "publish", "id": rel_id, "actor": actor or ""})
    return {"ok": True, "release": rel}


def search_releases(root, query):
    needle = (query or "").strip().lower()
    hits = []
    for row in list_releases(root):
        rel = load_release(root, row.get("id"))
        if not rel:
            continue
        if needle and needle not in json.dumps(rel, ensure_ascii=False).lower():
            continue
        hits.append(row)
    return hits


def export_markdown(rel):
    lines = [
        "# DingAI release %s" % rel.get("id"),
        "",
        "- status: %s" % rel.get("status"),
        "- version: %s" % (rel.get("version") or ""),
        "- tag: %s" % (rel.get("tag") or ""),
        "- created: %s" % (rel.get("created_at") or ""),
        "- published: %s" % (rel.get("published_at") or ""),
        "- head: %s" % (rel.get("head") or ""),
        "- publisher: %s" % (rel.get("publisher") or ""),
        "- approvers: %s" % ", ".join(rel.get("approvers") or []),
        "",
        "## Handoff rules",
        "",
        rel.get("rules") or "",
        "",
        "## Diff",
        "",
        "```",
        rel.get("diff_summary") or "",
        "```",
        "",
        "## Commits",
        "",
    ]
    for sha in rel.get("commits") or []:
        lines.append("- `%s`" % sha)
    if not rel.get("commits"):
        lines.append("- none")
    lines += ["", "## Scope warnings", ""]
    for item in rel.get("scope_warnings") or []:
        lines.append("- %s" % (item.get("detail") or item.get("kind")))
    if not rel.get("scope_warnings"):
        lines.append("- none")
    lines += ["", "## Overrides", ""]
    for item in rel.get("overrides") or []:
        lines.append("- %s %s: %s" % (item.get("at"), item.get("actor"), item.get("reason")))
    if not rel.get("overrides"):
        lines.append("- none")
    lines += ["", "## Pins", ""]
    for pin in rel.get("pins") or []:
        lines += [
            "### %s" % pin.get("key"),
            "",
            "- decision: %s" % (pin.get("decision") or "unreviewed"),
            "- reviewer: %s" % (pin.get("reviewer") or ""),
            "- note: %s" % (pin.get("note") or ""),
            "- anchor: %s,%s" % (pin.get("x_px"), pin.get("y_px")),
            "- before: %s" % (pin.get("before") or ""),
            "- after: %s" % (pin.get("after") or ""),
            "",
        ]
    if rel.get("restores"):
        lines += ["Rollback restores `%s`. This file does not change that archive." % rel["restores"], ""]
    return "\n".join(lines) + "\n"


def export_release(root, rel_id, fmt, dest):
    rel = load_release(root, rel_id)
    if not rel:
        return {"ok": False, "error": "not found"}
    folder = releases_root(root) / rel_id
    dest = Path(dest)
    if fmt == "markdown":
        if dest.is_dir() or str(dest).endswith(os.sep):
            dest.mkdir(parents=True, exist_ok=True)
            dest = dest / "release.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(export_markdown(rel), encoding="utf-8")
        return {"ok": True, "path": str(dest)}
    if fmt == "zip":
        if dest.is_dir() or str(dest).endswith(os.sep):
            dest.mkdir(parents=True, exist_ok=True)
            dest = dest / (rel_id + ".zip")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in folder.rglob("*"):
                if path.is_file():
                    zf.write(path, "%s/%s" % (rel_id, path.relative_to(folder).as_posix()))
            zf.writestr("%s/release.md" % rel_id, export_markdown(rel))
        return {"ok": True, "path": str(dest)}
    return {"ok": False, "error": "format must be zip or markdown"}


def rollback(root, rel_id, actor=""):
    rel = load_release(root, rel_id)
    if not rel:
        return {"ok": False, "error": "not found"}
    previous_id = rel.get("parent_id") or ""
    if not previous_id:
        return {"ok": False, "error": "no previous release"}
    prev = load_release(root, previous_id)
    if not prev:
        return {"ok": False, "error": "previous release missing"}
    pins = []
    for pin in prev.get("pins") or []:
        pins.append({
            "key": pin.get("key"),
            "note_id": pin.get("note_id") or "",
            "pin_id": pin.get("pin_id") or "",
            "project": pin.get("project") or "",
            "note": pin.get("note") or "",
            "x_px": pin.get("x_px") or 0,
            "y_px": pin.get("y_px") or 0,
        })
    draft = open_release(
        root, pins,
        version=prev.get("version") or "", tag=prev.get("tag") or "",
        project=prev.get("project") or "", repo=prev.get("repo") or "",
        rules=prev.get("rules") or "", diff_summary=prev.get("diff_summary") or "",
        scope_warnings=prev.get("scope_warnings") or [], head=prev.get("head") or "",
        commits=prev.get("commits") or [], parent_id=previous_id,
    )
    src = releases_root(root) / previous_id
    dst = releases_root(root) / draft["id"]
    for pin, old in zip(draft["pins"], prev.get("pins") or []):
        for side in ("before", "after"):
            name = old.get(side) or ""
            if name and safe_file_name(name) and (src / name).is_file():
                shutil.copyfile(src / name, dst / name)
                pin[side] = name
    draft["kind"] = "rollback"
    draft["rollback_of"] = rel_id
    draft["restores"] = previous_id
    _write(dst / "release.json", draft)
    _refresh_page(root, draft)
    _audit(root, {"at": _now(), "action": "rollback", "id": draft["id"], "rollback_of": rel_id, "restores": previous_id, "actor": actor or ""})
    return {"ok": True, "release": draft}


def index_html(rows):
    def esc(value):
        return (str("" if value is None else value)
                .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    items = []
    for row in rows:
        items.append("<li><a href='/release/%s/'>%s</a> %s %s %s</li>" % (
            esc(row.get("id")), esc(row.get("id")), esc(row.get("status")), esc(row.get("tag")), esc(row.get("project"))))
    body = "\n".join(items) or "<li>none</li>"
    return "<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'><title>DingAI releases</title></head><body><h1>Releases</h1><ul>%s</ul></body></html>" % body
