"""HTTP endpoints for the session record page (design M1 read, M2 write).

Served by core.bridge under /api/* and /app/*. Reads are GET-only and expect
the caller to be the page itself on loopback: bridge enforces the Host header
and the self origin before dispatching, so no CORS headers are needed on any
response. handoff.py is imported lazily so a bridge start never pays for it
and no import cycle appears.

M2 writes (POST) additionally require the page's own origin — a request with
no Origin header (local CLI) stays read-only and must use the handoff.py CLI
instead. Every write needs the three elements from the design: POST plus a
client/token minted by /api/session (checked against BridgeState.client_ok)
plus a confirm field equal to the target id in the URL. Bodies are capped and
parsed as JSON objects.

/api/session   mint a client/token (same exposure as GET /ping)
/api/sessions  list runs/ sessions that have a status.json
/api/runs/{sid}            result_payload from handoff (merged pins + rounds)
/api/runs/{sid}/rounds/{n} summary + manifest digest for one round
/api/runs/{sid}/rounds/{n}/files/{name}  raw round file, name whitelisted
/api/runs/{sid}/note       raw runs note.json
/api/runs/{sid}/pins/{pid} one pin: merged state + per-round history
POST /api/runs/{sid}/pins/{pid}/note   edit that pin's note in the source note
POST /api/runs/{sid}/pins/{pid}/rerun  spawn autofix --round N+1 --pin pid,
                                       returns the round number immediately
POST /api/runs/{sid}/pins/{pid}/revert per-pin revert (three-way merge);
                                       a merge conflict is 409 + conflict files
                                       and nothing on disk is touched

/app, /app/*   the prebuilt SPA in web/record/dist (suffix whitelist,
               explicit Content-Type, nosniff, realpath traversal guard)
"""

import json
import os
import re
import subprocess
import sys
import time

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

# M2 writes: annotation and feedback are short text, so a small cap is plenty.
POST_LIMIT = 64 << 10
NOTE_LIMIT = 2000       # handoff.PIN_TEXT_LIMIT
FEEDBACK_LIMIT = 1000   # handoff.FEEDBACK_LIMIT
MAX_RERUNS = 3          # per-pin cap, matches the global 3-round loop cap

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
    if handler.command != "GET":
        # Reads are GET-only; POST reaches exactly the two write routes below.
        match = re.fullmatch(r"/api/runs/([^/]+)/pins/([^/]+)/note", path)
        if match:
            pin_note_edit(handler, decision, match.group(1), match.group(2))
            return
        match = re.fullmatch(r"/api/runs/([^/]+)/pins/([^/]+)/rerun", path)
        if match:
            pin_rerun(handler, decision, match.group(1), match.group(2))
            return
        match = re.fullmatch(r"/api/runs/([^/]+)/pins/([^/]+)/revert", path)
        if match:
            pin_revert(handler, decision, match.group(1), match.group(2))
            return
        _error(handler, decision, 404, "not found")
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


# -- M2 写接口 -------------------------------------------------------------

def _check_pid(handler, decision, pid):
    if not _PIN.match(pid or ""):
        _error(handler, decision, 400, "bad pin id")
        return False
    return True


def _read_post(handler, decision):
    """The JSON body of a write request, or None with the error already sent."""
    try:
        length = int(handler.headers.get("Content-Length") or "0")
    except ValueError:
        length = 0
    if length > POST_LIMIT:
        _error(handler, decision, 413, "body too large")
        return None
    data = handler._read_body()
    if len(data) > POST_LIMIT:
        _error(handler, decision, 413, "body too large")
        return None
    try:
        obj = json.loads(data.decode("utf-8") or "{}")
    except ValueError:
        _error(handler, decision, 400, "bad json")
        return None
    if not isinstance(obj, dict):
        _error(handler, decision, 400, "bad json")
        return None
    return obj


def _check_write(handler, decision, body, target):
    """Design's three write elements: self origin, client/token, confirm==target."""
    if decision[0] != "self":
        # Only the page itself may write; a local no-Origin client uses the CLI.
        _error(handler, decision, 403, "self origin required")
        return False
    if not handler.server.state.client_ok(body.get("client"), body.get("token")):
        _error(handler, decision, 401, "bad client or token")
        return False
    if str(body.get("confirm") or "") != str(target):
        _error(handler, decision, 403, "confirm mismatch")
        return False
    return True


def _source_note_path(handler, decision, sid):
    import handoff

    path = handoff.read_run_status(sid).get("note") or ""
    if not path or not os.path.isfile(path):
        _error(handler, decision, 400, "source note missing")
        return ""
    return path


def _note_pin(note, pid):
    for pin in (note.get("pins") if isinstance(note, dict) else None) or []:
        if isinstance(pin, dict) and str(pin.get("id")) == str(pid):
            return pin
    return None


def _replace_file(tmp, path, tries=3):
    """os.replace with a short retry (handoff._replace_file semantics kept local)."""
    for attempt in range(tries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(0.05 * (attempt + 1))


def _write_note_atomic(path, note):
    """Atomic write with a one-shot .bak, per the design (core/sync.py pattern).

    Returns False when the final replace fails — on Windows os.replace raises
    PermissionError while another process holds the target open (editor, AV
    scan); the caller answers 409 instead of crashing the handler thread.
    """
    try:
        with open(path, "rb") as fh:
            original = fh.read()
    except OSError:
        original = b""
    if original:
        try:
            with open(path + ".bak", "wb") as fh:
                fh.write(original)
        except OSError:
            pass
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(note, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    try:
        _replace_file(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False
    return True


def pin_note_edit(handler, decision, sid, pid):
    import handoff

    if not _check_sid(handler, decision, sid) or not _check_pid(handler, decision, pid):
        return
    body = _read_post(handler, decision)
    if body is None:
        return
    if not _check_write(handler, decision, body, pid):
        return
    note_path = _source_note_path(handler, decision, sid)
    if not note_path:
        return
    text = body.get("note")
    if not isinstance(text, str):
        _error(handler, decision, 400, "note must be a string")
        return
    text = text.strip()
    if len(text) > NOTE_LIMIT:
        _error(handler, decision, 400, "note too long (max %d)" % NOTE_LIMIT)
        return
    try:
        note = json.loads(handoff.read_note(note_path) or "{}")
    except ValueError:
        _error(handler, decision, 400, "source note is not valid json")
        return
    pin = _note_pin(note if isinstance(note, dict) else {}, pid)
    if pin is None:
        _error(handler, decision, 404, "no such pin")
        return
    pin["note"] = text
    if not _write_note_atomic(note_path, note):
        _error(handler, decision, 409, "note file busy")
        return
    _json(handler, decision, 200, {"ok": True, "pin_id": str(pid), "note": text})


def pin_rerun(handler, decision, sid, pid):
    import handoff

    if not _check_sid(handler, decision, sid) or not _check_pid(handler, decision, pid):
        return
    body = _read_post(handler, decision)
    if body is None:
        return
    if not _check_write(handler, decision, body, pid):
        return
    if handoff.read_run_status(sid).get("status") == "running":
        _error(handler, decision, 409, "a run is already in progress")
        return
    note_path = _source_note_path(handler, decision, sid)
    if not note_path:
        return
    try:
        note = json.loads(handoff.read_note(note_path) or "{}")
    except ValueError:
        _error(handler, decision, 400, "source note is not valid json")
        return
    pin = _note_pin(note if isinstance(note, dict) else {}, pid)
    if pin is None:
        _error(handler, decision, 404, "no such pin")
        return
    # open_pins_note semantics: confirmed pins are done and never rerun.
    if pin.get("status") == "confirmed":
        _error(handler, decision, 400, "pin already confirmed")
        return
    feedback = body.get("feedback")
    feedback = feedback.strip() if isinstance(feedback, str) else ""
    if len(feedback) > FEEDBACK_LIMIT:
        feedback = feedback[:FEEDBACK_LIMIT]
    numbers = handoff.round_numbers(sid)
    round_n = (numbers[-1] + 1) if numbers else 1
    spawn_autofix(sid, round_n, str(pid), feedback)
    _json(handler, decision, 200, {"ok": True, "session": sid, "pin": str(pid), "round": round_n})


def pin_revert(handler, decision, sid, pid):
    """逐颗撤回：冲突 409 + 冲突文件列表，磁盘与元数据零改动（设计 §3）。"""
    import handoff

    if not _check_sid(handler, decision, sid) or not _check_pid(handler, decision, pid):
        return
    body = _read_post(handler, decision)
    if body is None:
        return
    if not _check_write(handler, decision, body, pid):
        return
    if handoff.read_run_status(sid).get("status") == "running":
        _error(handler, decision, 409, "a run is already in progress")
        return
    result = handoff.revert_pin(sid, str(pid))
    if result.get("ok"):
        _json(handler, decision, 200, result)
        return
    error = result.get("error") or ""
    if error == "merge conflict":
        _json(handler, decision, 409, {
            "ok": False,
            "error": "merge conflict",
            "conflicts": result.get("conflicts") or [],
            "round": result.get("round"),
        })
        return
    _error(handler, decision, 404 if "no pin-only round" in error else 409, error)


def _spawn_autofix(session, round_n, pid, feedback=""):
    """Run the normal autofix chain in the background; SPA polls status.json."""
    import handoff

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    argv = [handoff.python_exe(), os.path.join(root, "handoff.py"),
            "autofix", session, "--round", str(round_n), "--pin", pid]
    if feedback:
        argv += ["--feedback", feedback]
    os.makedirs(handoff.run_dir(session), exist_ok=True)
    log = open(os.path.join(handoff.run_dir(session), "log.txt"), "a", encoding="utf-8")
    try:
        subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    finally:
        log.close()


spawn_autofix = _spawn_autofix


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
