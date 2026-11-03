"""Opt-in publish: local files, a shared folder, or the team server."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from core.schema import normalize_note


def settings_path():
    return Path.home() / "DingAI" / "settings.json"


def load_settings(path=None):
    data = {}
    file = Path(path) if path else settings_path()
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    mode = os.environ.get("DINGAI_MODE") or data.get("mode") or "local"
    if mode not in ("local", "folder", "server"):
        mode = "local"
    share = os.environ.get("DINGAI_SHARE_DIR") or data.get("share_dir") or ""
    server = os.environ.get("DINGAI_TEAM_URLS") or os.environ.get("ANNO_TEAM_URLS") or data.get("server_url") or ""
    if "," in server:
        server = server.split(",")[0].strip()
    token = os.environ.get("DINGAI_TEAM_TOKEN") or data.get("token") or ""
    project = os.environ.get("DINGAI_PROJECT_NAME") or data.get("project") or "inbox"
    if mode == "local" and share:
        mode = "folder"
    if mode == "local" and server:
        mode = "server"
    return {"mode": mode, "share_dir": share, "server_url": server.rstrip("/"), "token": token, "project": project}


def _atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _pin_name(note_id, pin_id):
    safe = str(note_id).replace("/", "-")
    return "%s--%s.json" % (safe, pin_id)


def safe_project(name):
    text = str(name or "inbox").replace("\\", "-").replace("/", "-").strip(" .")
    return text or "inbox"


def publish_folder(root, note, png_bytes=None):
    note = normalize_note(note)
    project = safe_project(note["project"])
    note["project"] = project
    note_id = note.get("file") or note.get("id") or "note"
    base = Path(root) / "projects" / project
    _atomic_write(base / "notes" / (str(note_id) + ".json"), json.dumps(note, ensure_ascii=False, indent=2))
    shot = note.get("screenshot") or ""
    if png_bytes and shot:
        dest = base / "shots" / os.path.basename(shot)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(png_bytes)
        os.replace(tmp, dest)
    pins = []
    for pin in note["pins"]:
        row = dict(pin)
        row["note_id"] = note_id
        row["project"] = project
        row["screenshot"] = shot
        name = _pin_name(note_id, pin.get("id"))
        _atomic_write(base / "pins" / name, json.dumps(row, ensure_ascii=False, indent=2))
        pins.append(name)
    return {"project": project, "note_id": note_id, "pins": pins}


def list_folder_pins(root, project=None):
    base = Path(root) / "projects"
    rows = []
    if not base.exists():
        return rows
    projects = [base / project] if project else [p for p in base.iterdir() if p.is_dir()]
    for proj in projects:
        pin_dir = proj / "pins"
        if not pin_dir.is_dir():
            continue
        for path in sorted(pin_dir.glob("*.json")):
            try:
                rows.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    return rows


def folder_set_status(root, project, note_id, pin_id, status, verification=None, comment=None, actor="agent"):
    path = Path(root) / "projects" / project / "pins" / _pin_name(note_id, pin_id)
    if not path.exists():
        return None
    row = json.loads(path.read_text(encoding="utf-8"))
    row["status"] = status
    if comment:
        row.setdefault("comments", []).append({"author": actor, "body": comment})
    if verification:
        dest = Path(root) / "projects" / project / "shots" / ("verify-%s-%s.png" % (note_id, pin_id))
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".tmp")
        tmp.write_bytes(verification)
        os.replace(tmp, dest)
        row["verification"] = dest.name
    _atomic_write(path, json.dumps(row, ensure_ascii=False, indent=2))
    return row


def _request(url, data=None, token=None, content_type="application/json"):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = None
    if data is not None and not isinstance(data, (bytes, bytearray)):
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = content_type
    elif isinstance(data, (bytes, bytearray)):
        body = data
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    if not raw:
        return 200, {}
    try:
        return 200, json.loads(raw.decode("utf-8"))
    except ValueError:
        return 200, raw


def publish_server(base, note, png_bytes=None, token=""):
    note = normalize_note(note)
    code, body = _request(base.rstrip("/") + "/api/note", note, token=token)
    if code != 200:
        return {"ok": False, "status": code, "body": body}
    shot = note.get("screenshot") or ""
    if png_bytes and shot:
        _request(base.rstrip("/") + "/api/shot/" + os.path.basename(shot), png_bytes, token=token, content_type="image/png")
    return {"ok": True, "body": body}


def publish_note(note, png_bytes=None, settings=None):
    cfg = settings or load_settings()
    note = dict(note)
    note["project"] = note.get("project") or cfg["project"]
    if cfg["mode"] == "folder" and cfg["share_dir"]:
        return {"mode": "folder", **publish_folder(cfg["share_dir"], note, png_bytes)}
    if cfg["mode"] == "server" and cfg["server_url"]:
        return {"mode": "server", **publish_server(cfg["server_url"], note, png_bytes, cfg["token"])}
    return {"mode": "local"}


def list_pins(project=None, settings=None):
    cfg = settings or load_settings()
    project = safe_project(project or cfg["project"])
    if cfg["mode"] == "folder" and cfg["share_dir"]:
        rows = list_folder_pins(cfg["share_dir"], project)
        for row in rows:
            shot = os.path.basename(str(row.get("screenshot") or ""))
            if shot:
                row["screenshot_path"] = str(Path(cfg["share_dir"]) / "projects" / safe_project(row.get("project") or project) / "shots" / shot)
        return {"ok": True, "mode": "folder", "pins": rows}
    if cfg["mode"] == "server" and cfg["server_url"]:
        query = urllib.parse.urlencode({"project": project})
        code, body = _request(cfg["server_url"] + "/api/pins?" + query, token=cfg["token"])
        return {"ok": code == 200, "mode": "server", "pins": body if isinstance(body, list) else []}
    return {"ok": True, "mode": "local", "pins": []}


def set_pin_status(project, note_id, pin_id, status, verification=None, comment=None, settings=None, actor="agent"):
    cfg = settings or load_settings()
    project = safe_project(project)
    if cfg["mode"] == "folder" and cfg["share_dir"]:
        row = folder_set_status(cfg["share_dir"], project, note_id, pin_id, status, verification, comment, actor)
        return {"ok": row is not None, "pin": row}
    if cfg["mode"] == "server" and cfg["server_url"]:
        base = "%s/api/pins/by-note/%s/%s" % (
            cfg["server_url"], urllib.parse.quote(str(note_id), safe=""), urllib.parse.quote(str(pin_id), safe=""))
        payload = {"status": status, "project": project, "comment": comment or ""}
        code, body = _request(base + "/status", payload, token=cfg["token"])
        if verification:
            query = urllib.parse.urlencode({"project": project})
            _request(base + "/verification?" + query, verification, token=cfg["token"], content_type="image/png")
        return {"ok": code == 200, "status": code, "body": body}
    return {"ok": False, "error": "local-only"}
