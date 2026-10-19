"""Pluggable pin exporters. Markdown and GitHub ship now. Jira and Feishu register later.

GitHub posting uses GITHUB_TOKEN (or GH_TOKEN) and DINGAI_GITHUB_REPO. Without
those, the issue body is written locally and nothing is sent.
"""

import json
import os
import urllib.request
from pathlib import Path

EXPORTERS = {}


def register_exporter(name, fn):
    EXPORTERS[name] = fn
    return fn


def export_note(name, note, dest, options=None):
    fn = EXPORTERS.get(name)
    if fn is None:
        return {"ok": False, "error": "unknown exporter: %s" % name, "available": sorted(EXPORTERS)}
    return fn(note, dest, options or {})


def checklist(note):
    lines = ["# DingAI checklist", ""]
    for pin in (note or {}).get("pins") or []:
        mark = "x" if pin.get("status") == "confirmed" else " "
        title = (pin.get("note") or pin.get("ocr_nearby") or "pin").replace("\n", " ")
        kind = pin.get("pin_type") or "bug"
        source = pin.get("source") or {}
        loc = ""
        if isinstance(source, dict) and source.get("file"):
            loc = " (%s:%s)" % (source.get("file"), source.get("line") or 1)
        lines.append("- [%s] %s: %s%s" % (mark, kind, title, loc))
    annotations = (note or {}).get("annotations") or []
    for item in annotations:
        mark = "x" if item.get("status") == "confirmed" else " "
        source = item.get("source") or {}
        loc = ""
        if isinstance(source, dict) and source.get("file"):
            loc = " (%s:%s)" % (source.get("file"), source.get("line") or 1)
        lines.append("- [%s] %s: %s%s" % (mark, item.get("pinType") or "bug", item.get("comment") or "pin", loc))
    return "\n".join(lines).rstrip() + "\n"


def _dest_file(dest, filename):
    path = Path(dest)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_dir() or str(dest).endswith(("/", os.sep)):
        path.mkdir(parents=True, exist_ok=True)
        path = path / filename
    return path


def export_markdown(note, dest, options=None):
    path = _dest_file(dest, "dingai-checklist.md")
    path.write_text(checklist(note), encoding="utf-8")
    return {"ok": True, "posted": False, "path": str(path), "exporter": "markdown"}


def export_github(note, dest, options=None):
    options = options or {}
    body = checklist(note)
    title = options.get("title") or "DingAI pins"
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    repo = os.environ.get("DINGAI_GITHUB_REPO") or options.get("repo") or ""
    if not token or not repo or "/" not in repo:
        path = _dest_file(dest, "github-issue.md")
        path.write_text("# %s\n\n%s" % (title, body), encoding="utf-8")
        return {"ok": True, "posted": False, "path": str(path), "exporter": "github"}
    payload = json.dumps({"title": title, "body": body}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/issues" % repo,
        data=payload,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "User-Agent": "dingai",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "posted": False, "error": str(exc), "exporter": "github"}
    return {"ok": True, "posted": True, "url": data.get("html_url") or "", "exporter": "github"}


register_exporter("markdown", export_markdown)
register_exporter("github", export_github)
