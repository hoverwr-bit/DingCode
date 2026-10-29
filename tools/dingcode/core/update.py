"""Opt-in update check against GitHub releases. Off unless DINGCODE_UPDATE=1.

The request is a GET of the public releases endpoint. No identifier is sent.
Nothing is downloaded or installed.
"""

import json
import urllib.request
from pathlib import Path

from core.paths import env


def current_version():
    path = Path(__file__).resolve().parents[1] / "VERSION"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def check_update():
    current = current_version()
    if env("DINGCODE_UPDATE", "DINGAI_UPDATE") != "1":
        return {"ok": True, "checked": False, "current": current}
    repo = env("DINGCODE_UPDATE_REPO", "DINGAI_UPDATE_REPO") or "hoverwr-bit/DingCode"
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/releases/latest" % repo,
        headers={"User-Agent": "dingcode", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    latest = str(data.get("tag_name") or "").lstrip("v")
    return {
        "ok": True,
        "checked": True,
        "current": current,
        "latest": latest,
        "url": data.get("html_url") or "",
        "update": bool(latest) and latest != current,
    }
