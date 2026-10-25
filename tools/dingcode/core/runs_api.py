"""Read-only HTTP endpoints for the session record page (design M1).

Served by core.bridge under /api/* and /app/*. Everything here is GET-only
(bridge answers POST with 405 until M2) and expects the caller to be the page
itself on loopback: bridge enforces the Host header and the self origin before
dispatching, so no CORS headers are needed on any response. handoff.py is
imported lazily so a bridge start never pays for it and no import cycle
appears.

/api/session   mint a client/token (same exposure as GET /ping, kept for M2 writes)
/api/sessions  list runs/ sessions that have a status.json
/api/runs/{sid}            result_payload from handoff (merged pins + rounds)
/api/runs/{sid}/rounds/{n} summary + manifest digest for one round
/api/runs/{sid}/rounds/{n}/files/{name}  raw round file, name whitelisted
/api/runs/{sid}/note       raw runs note.json
/api/runs/{sid}/pins/{pid} one pin: merged state + per-round history

/app, /app/*   the prebuilt SPA in web/record/dist (suffix whitelist,
               explicit Content-Type, nosniff, realpath traversal guard)
"""

import json
import os
import re

from core.paths import env

_SID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

ROUND_FILES = {
    "summary.json": "application/json; charset=utf-8",
    "manifest.json": "application/json; charset=utf-8",
    "diff.patch": "text/x-diff; charset=utf-8",
    "pre.diff": "text/x-diff; charset=utf-8",
}

RAW_LIMIT = 8 << 20  # same body cap bridge reads

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}


def dist_root():
    override = env("DINGCODE_RECORD_DIST", default="") or ""
    if override:
        return override
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, "web", "record", "dist")


def _json(handler, decision, code, obj):
    handler._write(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8", decision)


def _error(handler, decision, code, message):
    _json(handler, decision, code, {"ok": False, "error": message})


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data


def _read_capped(path, limit=RAW_LIMIT):
    try:
        size = os.path.getsize(path)
    except OSError:
        return None, "missing"
    if size > limit:
        return None, "too large"
    try:
        with open(path, "rb") as fh:
            return fh.read(), None
    except OSError:
        return None, "missing"


def handle(handler, path, query, decision):
    if path == "/app" or path.startswith("/app/"):
        serve_static(handler, path, decision)
        return
    if path == "/api/session":
        client, token = handler.server.state.register()
        _json(handler, decision, 200, {
            "app": "dingcode-bridge",
            "compat": "anno-bridge",
            "version": 1,
            "client": client,
            "token": token,
        })
        return
    if path == "/api/sessions":
        list_sessions(handler, decision)
        return
    match = re.fullmatch(r"/api/runs/([^/]+)", path)
    if match:
        run_payload(handler, decision, match.group(1))
        return
    match = re.fullmatch(r"/api/runs/([^/]+)/rounds/(\d+)", path)
    if match:
        round_detail(handler, decision, match.group(1), int(match.group(2)))
        return
    match = re.fullmatch(r"/api/runs/([^/]+)/rounds/(\d+)/files/([^/]+)", path)
    if match:
        round_file(handler, decision, match.group(1), int(match.group(2)), match.group(3))
        return
    match = re.fullmatch(r"/api/runs/([^/]+)/note", path)
    if match:
        run_note(handler, decision, match.group(1))
        return
    match = re.fullmatch(r"/api/runs/([^/]+)/pins/([^/]+)", path)
    if match:
        pin_history(handler, decision, match.group(1), match.group(2))
        return
    _error(handler, decision, 404, "not found")


def _check_sid(handler, decision, sid):
    if not _SID.match(sid or ""):
        _error(handler, decision, 400, "bad session id")
        return False
    return True


def list_sessions(handler, decision):
    import handoff

    root = os.path.join(handoff.dot_dir(), "runs")
    sessions = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        names = []
    for name in names:
        if not _SID.match(name):
            continue
        status = handoff.read_run_status(name)
        if not status:
            continue
        sessions.append({
            "session": name,
            "status": status.get("status") or "",
            "round": status.get("round") or 0,
            "summary_line": status.get("summary_line") or "",
            "finished": status.get("finished") or "",
            "note": status.get("note") or "",
        })
    sessions.sort(key=lambda item: (item["finished"], item["session"]), reverse=True)
    _json(handler, decision, 200, {"ok": True, "sessions": sessions})


def run_payload(handler, decision, sid):
    import handoff

    if not _check_sid(handler, decision, sid):
        return
    payload = handoff.result_payload(sid)
    if not payload.get("ok"):
        _error(handler, decision, 404, "no such session")
        return
    _json(handler, decision, 200, payload)


def round_detail(handler, decision, sid, round_n):
    import handoff

    if not _check_sid(handler, decision, sid):
        return
    dest = handoff.round_dir(sid, round_n)
    summary = _load_json(os.path.join(dest, "summary.json"))
    manifest = _load_json(os.path.join(dest, "manifest.json"))
    if summary is None and manifest is None:
        _error(handler, decision, 404, "no such round")
        return
    _json(handler, decision, 200, {
        "ok": True,
        "session": sid,
        "round": round_n,
        "summary": summary or {},
        "manifest": {
            "kind": (manifest or {}).get("kind") or "",
            "head": (manifest or {}).get("head") or "",
            "folder": (manifest or {}).get("folder") or "",
            "reverted": bool((summary or {}).get("reverted")),
            "files_sha256": sorted(((manifest or {}).get("files_sha256") or {}).keys()),
        },
    })


def round_file(handler, decision, sid, round_n, name):
    import handoff

    if not _check_sid(handler, decision, sid):
        return
    content_type = ROUND_FILES.get(name)
    if not content_type:
        _error(handler, decision, 404, "file not allowed")
        return
    path = os.path.join(handoff.round_dir(sid, round_n), name)
    data, why = _read_capped(path)
    if data is None:
        _error(handler, decision, 413 if why == "too large" else 404, why)
        return
    handler._write(200, data, content_type, decision, [("X-Content-Type-Options", "nosniff")])


def run_note(handler, decision, sid):
    import handoff

    if not _check_sid(handler, decision, sid):
        return
    path = os.path.join(handoff.run_dir(sid), "note.json")
    data, why = _read_capped(path)
    if data is None:
        _error(handler, decision, 404, "no note")
        return
    handler._write(200, data, "application/json; charset=utf-8", decision,
                   [("X-Content-Type-Options", "nosniff")])


def pin_history(handler, decision, sid, pid):
    import handoff

    if not _check_sid(handler, decision, sid):
        return
    if not _PIN.match(pid or ""):
        _error(handler, decision, 400, "bad pin id")
        return
    target = str(pid)
    pin = None
    for merged in handoff.merged_pins(sid):
        if str(merged.get("id")) == target:
            pin = merged
            break
    rounds = []
    for round_n in handoff.round_numbers(sid):
        for entry in handoff.load_round_summary(sid, round_n):
            if not isinstance(entry, dict) or str(entry.get("id")) != target:
                continue
            rounds.append({
                "round": round_n,
                "status": entry.get("status") or "",
                "summary_zh": entry.get("summary_zh") or "",
                "diff": entry.get("diff") or "",
                "pin_only": bool(entry.get("pin_only")),
                "rerun": entry.get("rerun"),
                "reverted": bool(entry.get("reverted")),
                "stale": bool(entry.get("stale")),
            })
    if pin is None and not rounds:
        _error(handler, decision, 404, "no such pin")
        return
    _json(handler, decision, 200, {
        "ok": True,
        "session": sid,
        "pin_id": target,
        "pin": pin,
        "rounds": rounds,
    })


def serve_static(handler, path, decision):
    root = os.path.realpath(dist_root())
    rel = path[len("/app"):].lstrip("/")
    if rel in ("", "index.html"):
        rel = "index.html"
    full = os.path.realpath(os.path.join(root, rel))
    if full != root and not full.startswith(root + os.sep):
        handler._write(403, "forbidden", "text/plain; charset=utf-8", decision)
        return
    ext = os.path.splitext(full)[1].lower()
    content_type = STATIC_TYPES.get(ext)
    if not content_type:
        _error(handler, decision, 404, "not found")
        return
    data, why = _read_capped(full)
    if data is None:
        _error(handler, decision, 413 if why == "too large" else 404, "not found")
        return
    handler._write(200, data, content_type, decision, [
        ("X-Content-Type-Options", "nosniff"),
        ("Cache-Control", "no-store"),
    ])
