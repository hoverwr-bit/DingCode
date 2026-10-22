"""Active handoff sessions and soft locks. Standard library only."""

import json
import os
import subprocess
import time
from pathlib import Path

LOCK_SECONDS = 4 * 60 * 60


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _later(seconds):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + seconds))


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _norm(path):
    if not path:
        return ""
    try:
        return os.path.realpath(path)
    except OSError:
        return os.path.abspath(path)


def _paths_overlap(left, right):
    a = str(left or "").replace("\\", "/").strip("/")
    b = str(right or "").replace("\\", "/").strip("/")
    if not a or not b:
        return False
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def _alive(session):
    if session.get("status") not in ("active", "queued"):
        return False
    expires = session.get("expires_at") or ""
    return not expires or expires >= _now()


def sessions_dir(root):
    path = Path(root) / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def locks_dir(root):
    path = Path(root) / "locks"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_sessions(root, include_ended=False):
    rows = []
    base = sessions_dir(root)
    for path in sorted(base.glob("*.json")):
        try:
            row = _read(path)
        except (OSError, ValueError):
            continue
        if include_ended or _alive(row):
            rows.append(row)
    return rows


def load_session(root, session_id):
    path = sessions_dir(root) / ("%s.json" % session_id)
    if not path.is_file():
        return None
    try:
        return _read(path)
    except (OSError, ValueError):
        return None


def _save_session(root, session):
    _write(sessions_dir(root) / ("%s.json" % session["id"]), session)


def _git(repo, args):
    try:
        proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def git_head(repo):
    if not repo or not os.path.isdir(repo):
        return ""
    text = _git(repo, ["rev-parse", "HEAD"])
    return (text or "").strip()


def banner_text(warnings):
    lines = []
    for item in warnings or []:
        kind = item.get("kind")
        others = ", ".join(item.get("sessions") or [])
        if kind == "same-branch":
            lines.append("Two sessions share %s %s: %s" % (item.get("repo") or "a repo", item.get("branch") or "", others))
        elif kind == "overlap":
            lines.append("Overlapping files %s with %s" % (", ".join(item.get("paths") or []), others))
        elif kind == "pin":
            lines.append("Pin %s is also claimed by %s" % (", ".join(item.get("pins") or []), others))
        elif kind == "wrong-window":
            lines.append("Pin %s belongs to %s but this session is on %s" % (item.get("pin"), item.get("pin_project"), item.get("session_project")))
        elif kind == "target":
            lines.append("%s %s is also used by %s" % (item.get("what"), item.get("value"), others))
        elif kind == "stale":
            lines.append("Working tree moved from %s to %s" % ((item.get("recorded") or "")[:12], (item.get("current") or "")[:12]))
        else:
            lines.append(item.get("detail") or kind or "session warning")
    return " · ".join(line.strip() for line in lines if line.strip())


def write_notices(root, warnings):
    text = banner_text(warnings)
    payload = {"at": _now(), "banners": [{"level": "warn", "text": text, "warnings": warnings}] if text else []}
    _write(Path(root) / "notices.json", payload)
    return payload


def read_notices(root):
    path = Path(root) / "notices.json"
    if not path.is_file():
        return {"banners": []}
    try:
        data = _read(path)
    except (OSError, ValueError):
        return {"banners": []}
    return data if isinstance(data, dict) else {"banners": []}


def detect(session, others, current_head=None):
    warnings = []
    repo = _norm(session.get("repo"))
    branch = session.get("branch") or ""
    same = []
    for other in others:
        if other.get("id") == session.get("id") or not _alive(other):
            continue
        if repo and _norm(other.get("repo")) == repo and branch and other.get("branch") == branch:
            same.append(other["id"])
    if same:
        warnings.append({"kind": "same-branch", "repo": session.get("repo") or "", "branch": branch, "sessions": same})
    overlaps = {}
    for path in session.get("paths") or []:
        owners = []
        for other in others:
            if other.get("id") == session.get("id") or not _alive(other):
                continue
            if any(_paths_overlap(path, item) for item in other.get("paths") or []):
                owners.append(other["id"])
        if owners:
            overlaps[path] = owners
    for path, owners in overlaps.items():
        warnings.append({"kind": "overlap", "paths": [path], "sessions": owners})
    my_pins = [str(pin) for pin in session.get("pins") or []]
    claimed = {}
    for pin in my_pins:
        owners = []
        for other in others:
            if other.get("id") == session.get("id") or not _alive(other):
                continue
            if pin in [str(item) for item in other.get("pins") or []]:
                owners.append(other["id"])
        if owners:
            claimed[pin] = owners
    for pin, owners in claimed.items():
        warnings.append({"kind": "pin", "pins": [pin], "sessions": owners})
    project = session.get("project") or ""
    for pin, owner_project in (session.get("pin_projects") or {}).items():
        if project and owner_project and owner_project != project:
            warnings.append({
                "kind": "wrong-window", "pin": str(pin),
                "pin_project": owner_project, "session_project": project,
            })
    for kind, field in (("service", "services"), ("port", "ports"), ("database", "databases"), ("deploy", "deploys")):
        for value in session.get(field) or []:
            owners = []
            for other in others:
                if other.get("id") == session.get("id") or not _alive(other):
                    continue
                if str(value) in [str(item) for item in other.get(field) or []]:
                    owners.append(other["id"])
            if owners:
                warnings.append({"kind": "target", "what": kind, "value": str(value), "sessions": owners})
    recorded = session.get("head") or ""
    if current_head is None and repo:
        current_head = git_head(repo)
    if recorded and current_head and recorded != current_head:
        movers = []
        for other in others:
            if other.get("id") == session.get("id") or not _alive(other):
                continue
            if _norm(other.get("repo")) == repo and other.get("head") == current_head:
                movers.append(other["id"])
        warnings.append({"kind": "stale", "recorded": recorded, "current": current_head, "sessions": movers})
    return warnings


def _lock_names(session):
    rows = []
    for pin in session.get("pins") or []:
        rows.append(("pin", str(pin)))
    for path in session.get("paths") or []:
        rows.append(("path", str(path).replace("\\", "/").strip("/")))
    for field, kind in (("services", "service"), ("ports", "port"), ("databases", "database"), ("deploys", "deploy")):
        for value in session.get(field) or []:
            rows.append((kind, str(value)))
    return rows


def _lock_path(root, kind, value):
    safe = "%s-%s.json" % (kind, str(value).replace("/", "-").replace(":", "-").replace(" ", "-"))
    return locks_dir(root) / safe


def take_locks(root, session):
    held = []
    for kind, value in _lock_names(session):
        path = _lock_path(root, kind, value)
        current = None
        if path.is_file():
            try:
                current = _read(path)
            except (OSError, ValueError):
                current = None
        if current and current.get("session") not in ("", session["id"]):
            if (current.get("expires_at") or "") >= _now():
                continue
        row = {
            "kind": kind, "value": value, "owner": session.get("agent") or session["id"],
            "session": session["id"], "expires_at": session.get("expires_at") or _later(LOCK_SECONDS),
        }
        _write(path, row)
        held.append({"kind": kind, "value": value})
    session["locks"] = held
    return held


def release_locks(root, session):
    for path in locks_dir(root).glob("*.json"):
        try:
            row = _read(path)
        except (OSError, ValueError):
            continue
        if row.get("session") == session.get("id"):
            path.unlink()
    session["locks"] = []


def _blank(session_id, fields):
    row = {
        "id": session_id,
        "agent": fields.get("agent") or "handoff",
        "repo": fields.get("repo") or "",
        "branch": fields.get("branch") or "",
        "worktree": fields.get("worktree") or fields.get("repo") or "",
        "project": fields.get("project") or "",
        "pins": [str(pin) for pin in fields.get("pins") or []],
        "pin_projects": {str(k): v for k, v in (fields.get("pin_projects") or {}).items()},
        "paths": list(fields.get("paths") or []),
        "services": [str(item) for item in fields.get("services") or []],
        "ports": [str(item) for item in fields.get("ports") or []],
        "databases": [str(item) for item in fields.get("databases") or []],
        "deploys": [str(item) for item in fields.get("deploys") or []],
        "head": fields.get("head") or "",
        "status": "active",
        "choice": "",
        "queued_behind": "",
        "started_at": _now(),
        "expires_at": _later(LOCK_SECONDS),
        "log": [],
        "warnings": [],
    }
    return row


def register(root, fields, current_head=None):
    fields = fields or {}
    others = list_sessions(root)
    existing = None
    for other in others:
        if other.get("agent") == (fields.get("agent") or "handoff") and _norm(other.get("repo")) == _norm(fields.get("repo")) and (other.get("branch") or "") == (fields.get("branch") or "") and other.get("status") == "active":
            existing = other
            break
    if existing:
        session = existing
        for key in ("project", "worktree", "head", "pins", "pin_projects", "paths", "services", "ports", "databases", "deploys"):
            if key in fields and fields.get(key) not in (None, "", []):
                session[key] = fields[key] if key != "pins" else [str(pin) for pin in fields[key]]
        session["expires_at"] = _later(LOCK_SECONDS)
    else:
        session_id = "ses-%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), os.urandom(3).hex())
        session = _blank(session_id, fields)
        if not session["head"] and session["repo"]:
            session["head"] = git_head(session["repo"])
    warnings = detect(session, list_sessions(root), current_head=current_head)
    session["warnings"] = warnings
    if session.get("choice") != "queue":
        take_locks(root, session)
    _save_session(root, session)
    _refresh_notices(root)
    return {"ok": True, "session": session, "warnings": warnings, "banner": banner_text(warnings)}


def _refresh_notices(root):
    warnings = []
    seen = set()
    for session in list_sessions(root):
        for item in session.get("warnings") or []:
            token = json.dumps(item, sort_keys=True)
            if token in seen:
                continue
            seen.add(token)
            warnings.append(item)
    return write_notices(root, warnings)


def choose(root, session_id, choice, actor="", current_head=None):
    session = load_session(root, session_id)
    if not session:
        return {"ok": False, "error": "not found"}
    choice = choice or ""
    if choice not in ("queue", "isolate", "hand", "continue"):
        return {"ok": False, "error": "choice must be queue, isolate, hand, or continue"}
    session["choice"] = choice
    session["log"].append({"at": _now(), "choice": choice, "actor": actor or session.get("agent") or ""})
    if choice == "queue":
        others = [other["id"] for other in list_sessions(root) if other["id"] != session_id and other.get("status") == "active"]
        session["status"] = "queued"
        session["queued_behind"] = others[0] if others else ""
        release_locks(root, session)
    elif choice == "continue":
        session["status"] = "active"
    elif choice == "hand":
        _hand_off(root, session)
        session["status"] = "active"
    elif choice == "isolate":
        isolated = isolate(session)
        session["isolate"] = isolated
        if isolated.get("ok"):
            session["branch"] = isolated.get("branch") or session.get("branch")
            session["worktree"] = isolated.get("path") or session.get("worktree")
            session["status"] = "active"
            session["warnings"] = detect(session, list_sessions(root), current_head=current_head)
            take_locks(root, session)
        else:
            session["status"] = "active"
    if choice != "isolate":
        session["warnings"] = detect(session, list_sessions(root), current_head=current_head)
    _save_session(root, session)
    _refresh_notices(root)
    return {"ok": True, "session": session, "warnings": session.get("warnings") or [], "banner": banner_text(session.get("warnings") or [])}


def _hand_off(root, session):
    owners = {}
    for item in session.get("warnings") or []:
        if item.get("kind") not in ("overlap", "pin", "target"):
            continue
        for owner in item.get("sessions") or []:
            owners.setdefault(owner, {"pins": [], "paths": []})
            owners[owner]["pins"].extend(item.get("pins") or [])
            owners[owner]["paths"].extend(item.get("paths") or [])
    moved = []
    for owner, payload in owners.items():
        other = load_session(root, owner)
        if not other:
            continue
        for pin in payload["pins"]:
            if pin not in [str(item) for item in other.get("pins") or []]:
                other.setdefault("pins", []).append(str(pin))
            if str(pin) in [str(item) for item in session.get("pins") or []]:
                session["pins"] = [item for item in session["pins"] if str(item) != str(pin)]
                moved.append(str(pin))
        other.setdefault("log", []).append({"at": _now(), "choice": "received", "from": session["id"], "pins": payload["pins"]})
        _save_session(root, other)
        take_locks(root, other)
    session["handed"] = moved
    release_locks(root, session)
    take_locks(root, session)


def isolate(session):
    repo = session.get("repo") or ""
    branch = "dingcode/%s" % session["id"]
    if not repo or not os.path.isdir(os.path.join(repo, ".git")) and not os.path.isfile(os.path.join(repo, ".git")):
        return {"ok": False, "error": "not a git checkout", "branch": branch, "command": "git worktree add -b %s <dest>" % branch}
    dest = os.path.join(os.path.dirname(_norm(repo)), ".dingcode-worktrees", session["id"])
    if os.path.isdir(dest):
        return {"ok": True, "branch": branch, "path": dest}
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    try:
        proc = subprocess.run(["git", "worktree", "add", "-b", branch, dest], cwd=repo, capture_output=True, text=True)
    except OSError as exc:
        return {"ok": False, "error": str(exc), "branch": branch, "path": dest}
    if proc.returncode != 0:
        return {"ok": False, "error": (proc.stderr or proc.stdout or "git worktree failed").strip(), "branch": branch, "path": dest}
    return {"ok": True, "branch": branch, "path": dest}


def end_session(root, session_id, differ=None):
    session = load_session(root, session_id)
    if not session:
        return {"ok": False, "error": "not found"}
    session["status"] = "ended"
    session["ended_at"] = _now()
    release_locks(root, session)
    report = merge_check(root, session, differ=differ)
    session["overlaps"] = report.get("overlaps") or []
    _save_session(root, session)
    _refresh_notices(root)
    folder = Path(root) / "overlaps"
    folder.mkdir(parents=True, exist_ok=True)
    _write(folder / ("%s.json" % session_id), report)
    return {"ok": True, "session": session, "overlaps": report.get("overlaps") or []}


def merge_check(root, session, differ=None):
    overlaps = []
    repo = session.get("repo") or ""
    for other in list_sessions(root, include_ended=True):
        if other.get("id") == session.get("id"):
            continue
        if _norm(other.get("repo")) != _norm(repo):
            continue
        shared = []
        for path in session.get("paths") or []:
            if any(_paths_overlap(path, item) for item in other.get("paths") or []):
                shared.append(path)
        if not shared:
            continue
        for path in shared:
            if differ:
                diff = differ(path, session.get("head") or "", other.get("head") or "")
            else:
                diff = ""
                if repo and session.get("head") and other.get("head"):
                    diff = _git(repo, ["diff", "--no-color", session["head"], other["head"], "--", path]) or ""
            overlaps.append({
                "path": path,
                "left": session.get("head") or "",
                "right": other.get("head") or "",
                "other": other.get("id"),
                "diff": diff,
            })
    return {"ok": True, "session": session.get("id"), "overlaps": overlaps}
