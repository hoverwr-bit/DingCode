#!/usr/bin/env python3
"""DingAI handoff: rules on the prompt, plus a stdio MCP server.

No third-party packages. The desktop and page clients copy a prompt themselves;
this script is the CLI and the MCP server (nothing else in the toolbox speaks MCP).

  python3 handoff.py rules
  python3 handoff.py prompt [note.json]     # stdin when the path is omitted
  python3 handoff.py baseline [project]
  python3 handoff.py scope [project]
  python3 handoff.py reject [project]
  python3 handoff.py pins [project]
  python3 handoff.py mark-fixed <note_id> <pin_id> [verify.png]
  python3 handoff.py verify <before.png> <after.png> <outdir>
  python3 handoff.py confirm <note_id> <pin_id>
  python3 handoff.py reopen <note_id> <pin_id>
  python3 handoff.py release open [note.json] [--version V] [--tag T]
  python3 handoff.py release decide <id> <pin> approve|reject [--reviewer name]
  python3 handoff.py release publish <id> [--override reason] [--actor name]
  python3 handoff.py release export <id> zip|markdown <dest>
  python3 handoff.py release search <query>
  python3 handoff.py release rollback <id>
  python3 handoff.py session start --agent NAME --repo PATH --branch NAME [--project P] [--pin id] [--paths a,b] [--port 8080]
  python3 handoff.py session choose <id> queue|isolate|hand|continue
  python3 handoff.py session end <id>
  python3 handoff.py session list
  python3 handoff.py mcp                    # Content-Length JSON-RPC on stdio
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

DEFAULT_RULES = """- Make the smallest change that fixes the pinned issue. Do not refactor or rewrite surrounding code.
- Follow the project's ARCHITECTURE or conventions file before adding code.
- Touch only code related to the pinned element.
- Do not add dependencies or files unless you state why.
- Explain the diff and how it was verified."""

PROMPT_LEAD = "Apply the rules above to this DingAI note. The pinned element is the only scope."

DEP_NAMES = {
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "packages.lock.json",
    "Package.swift", "Package.resolved", "go.mod", "go.sum",
    "requirements.txt", "poetry.lock", "Pipfile", "Pipfile.lock",
    "Cargo.toml", "Cargo.lock", "composer.json", "composer.lock",
    "Gemfile", "Gemfile.lock", "Podfile", "Podfile.lock",
}
LINE_LIMIT = 400
FILE_LIMIT = 8


def project_dir():
    env = os.environ.get("DINGAI_PROJECT", "").strip()
    if env:
        return env
    pointer = os.path.join(os.path.expanduser("~"), "DingAI", "project.txt")
    try:
        with open(pointer, encoding="utf-8") as fh:
            text = fh.read().strip()
    except OSError:
        return ""
    return text


def load_rules():
    paths = []
    project = project_dir()
    if project:
        paths.append(os.path.join(project, ".dingai", "handoff-rules.md"))
    paths.append(os.path.join(os.path.expanduser("~"), "DingAI", "handoff-rules.md"))
    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read().strip()
        except OSError:
            continue
        if text:
            return text
    return DEFAULT_RULES


def prompt_for(note_text, rules=None):
    body = note_text if note_text is not None else ""
    try:
        from core.sync import load_settings
        if load_settings().get("redact"):
            from core.redact import redact_text
            body = redact_text(body)
    except Exception:
        pass
    return (rules if rules is not None else load_rules()).strip() + "\n\n" + PROMPT_LEAD + "\n\n" + body


def read_note(path):
    if path:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    return sys.stdin.read()


def tool_schema():
    return {
        "name": "dingai_handoff",
        "description": "Attach the project's handoff rules to a DingAI note and return the prompt for a coding agent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "note": {"type": "string", "description": "DingAI JSON note"},
                "note_path": {"type": "string", "description": "Path to a DingAI note file"},
            },
        },
    }


def scope_tool_schema():
    return {
        "name": "dingai_scope_check",
        "description": "Compare the working tree with the handoff baseline and report files outside the pinned scope, new dependencies, new top-level modules, and large diffs.",
        "inputSchema": {"type": "object", "properties": {"project": {"type": "string"}}},
    }


def reject_tool_schema():
    return {
        "name": "dingai_reject",
        "description": "Restore the warned paths to the handoff HEAD. Refuses when HEAD has moved, and does not reset history.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "paths": {"type": "array", "items": {"type": "string"}},
            },
        },
    }


def list_tool_schema():
    return {
        "name": "dingai_list_pins",
        "description": "List DingAI pins from the shared folder or the team server. Each pin includes its note id and screenshot name.",
        "inputSchema": {"type": "object", "properties": {"project": {"type": "string"}}},
    }


def mark_tool_schema():
    return {
        "name": "dingai_mark_fixed",
        "description": "Mark a pin ai-fixed and store a verification screenshot for the team to review.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "note_id": {"type": "string"},
                "pin_id": {"type": "string"},
                "verification_path": {"type": "string"},
                "comment": {"type": "string"},
            },
            "required": ["note_id", "pin_id"],
        },
    }


def list_agent_pins(project=None):
    from core.sync import list_pins
    return list_pins(project)


def mark_fixed(arguments):
    from core.sync import load_settings, set_pin_status
    arguments = arguments or {}
    note_id = arguments.get("note_id")
    pin_id = arguments.get("pin_id")
    if not note_id or pin_id in (None, ""):
        return {"ok": False, "error": "note_id and pin_id are required"}
    blob = None
    path = arguments.get("verification_path") or ""
    if path:
        try:
            with open(path, "rb") as fh:
                blob = fh.read()
        except OSError as exc:
            return {"ok": False, "error": "could not read verification screenshot: %s" % exc}
    cfg = load_settings()
    project = arguments.get("project") or cfg["project"]
    result = set_pin_status(project, note_id, str(pin_id), "ai-fixed", blob, arguments.get("comment") or "")
    observe_fixed(note_id, pin_id)
    return result


def call_handoff(arguments):
    arguments = arguments or {}
    if arguments.get("note_path"):
        note = read_note(arguments["note_path"])
    else:
        note = arguments.get("note") or ""
    record_baseline()
    observe_note(note, arguments.get("agent") or "")
    text = prompt_for(note)
    return {"content": [{"type": "text", "text": text}]}


def git(project, args):
    try:
        proc = subprocess.run(["git", *args], cwd=project, capture_output=True, text=True)
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def baseline_path(project):
    if project:
        return os.path.join(project, ".dingai", "last-handoff.json")
    return os.path.join(os.path.expanduser("~"), "DingAI", "last-handoff.json")


def load_baseline(project=None):
    path = baseline_path(project if project is not None else project_dir())
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def record_baseline(project=None):
    project = project if project is not None else project_dir()
    if not project or not os.path.isdir(project):
        return None
    head = git(project, ["rev-parse", "HEAD"])
    if not head:
        return None
    try:
        names = [n for n in os.listdir(project) if n != ".git"]
    except OSError:
        names = []
    data = {
        "head": head.strip(),
        "project": project,
        "top_dirs": sorted(names),
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    path = baseline_path(project)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
    except OSError:
        return None
    return data


def scope_prefixes(project):
    path = os.path.join(project, ".dingai", "scope.txt")
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return None
    out = []
    for line in lines:
        text = line.split("#", 1)[0].strip()
        if text:
            out.append(text)
    return out


def is_dependency(path):
    base = os.path.basename(path)
    return base in DEP_NAMES or base.endswith(".csproj")


def parse_numstat(text):
    files = []
    total = 0
    for line in (text or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added, deleted, path = parts[0], parts[1], parts[2]
        lines = (int(added) if added.isdigit() else 0) + (int(deleted) if deleted.isdigit() else 0)
        files.append({"path": path, "lines": lines, "untracked": False})
        total += lines
    return files, total


def scope_check(project=None):
    project = project if project is not None else project_dir()
    base = load_baseline(project)
    if not project or not base or not base.get("head"):
        return {"ok": False, "error": "no baseline", "warnings": [], "reject_paths": []}
    head = (git(project, ["rev-parse", "HEAD"]) or "").strip()
    diff = git(project, ["diff", "--numstat", "--no-renames", base["head"]])
    files, total = parse_numstat(diff or "")
    seen = {item["path"] for item in files}
    others = git(project, ["ls-files", "--others", "--exclude-standard"]) or ""
    for path in others.splitlines():
        if path and path not in seen and path != ".dingai/last-handoff.json":
            files.append({"path": path, "lines": 0, "untracked": True})
    files = [item for item in files if item["path"] != ".dingai/last-handoff.json"]
    prefixes = scope_prefixes(project)
    tops = set(base.get("top_dirs") or [])
    outside, deps, modules = [], [], []
    for item in files:
        path = item["path"]
        if prefixes is not None and not any(path == p or path.startswith(p) for p in prefixes):
            outside.append(path)
        if is_dependency(path):
            deps.append(path)
        first = path.split("/", 1)[0]
        if first not in tops:
            modules.append(path)
    warnings = []
    if outside:
        warnings.append({"kind": "outside", "paths": outside, "detail": "files outside .dingai/scope.txt"})
    if deps:
        warnings.append({"kind": "dependency", "paths": deps, "detail": "dependency or lockfile changed"})
    if modules:
        warnings.append({"kind": "module", "paths": modules, "detail": "new top-level file or directory"})
    if total > LINE_LIMIT or len(files) > FILE_LIMIT:
        warnings.append({
            "kind": "size",
            "paths": [item["path"] for item in files],
            "detail": "%d files, %d lines" % (len(files), total),
        })
    reject_paths = []
    for warning in warnings:
        for path in warning["paths"]:
            if path not in reject_paths:
                reject_paths.append(path)
    return {
        "ok": not warnings,
        "head": head,
        "baseline_head": base.get("head"),
        "head_moved": head != base.get("head"),
        "files": len(files),
        "lines": total,
        "warnings": warnings,
        "reject_paths": reject_paths,
    }


def safe_path(path):
    if not path or path.startswith("/") or path.startswith("\\"):
        return False
    return ".." not in path.split("/") and ".." not in path.split("\\")


def reject_changes(paths=None, project=None):
    project = project if project is not None else project_dir()
    base = load_baseline(project)
    if not project or not base or not base.get("head"):
        return {"ok": False, "error": "no baseline"}
    head = (git(project, ["rev-parse", "HEAD"]) or "").strip()
    if head != base.get("head"):
        return {"ok": False, "error": "HEAD moved; history was not reset"}
    report = scope_check(project)
    targets = [p for p in (paths if paths is not None else report.get("reject_paths") or []) if safe_path(p)]
    if not targets:
        return {"ok": True, "restored": [], "removed": []}
    tracked = set((git(project, ["ls-files", "--"] + targets) or "").splitlines())
    restore = [p for p in targets if p in tracked]
    if restore:
        if git(project, ["restore", "--source", head, "--worktree", "--staged", "--"] + restore) is None:
            return {"ok": False, "error": "git restore failed"}
    removed = []
    for path in targets:
        if path in tracked:
            continue
        full = os.path.join(project, path)
        if os.path.isfile(full):
            os.remove(full)
            removed.append(path)
    return {"ok": True, "restored": restore, "removed": removed}


def format_scope(report):
    if report.get("error"):
        return "No handoff baseline. Export a note or run: python3 handoff.py baseline"
    lines = ["%d files, %d lines since %s" % (report.get("files", 0), report.get("lines", 0), (report.get("baseline_head") or "")[:12])]
    if report.get("head_moved"):
        lines.append("HEAD has moved. Reject will not reset history.")
    if not report.get("warnings"):
        lines.append("No scope warnings.")
    for warning in report.get("warnings") or []:
        lines.append(warning["detail"] + ":")
        for path in warning["paths"]:
            lines.append("  " + path)
    return "\n".join(lines)


def handle_rpc(msg):
    if not isinstance(msg, dict):
        return None
    method = msg.get("method")
    mid = msg.get("id")
    if method == "notifications/initialized" or mid is None and method and method.startswith("notifications/"):
        return None
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "dingai", "version": "0.1"},
        }}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": [
            tool_schema(), scope_tool_schema(), reject_tool_schema(), list_tool_schema(), mark_tool_schema()]}}
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name == "dingai_handoff":
            return {"jsonrpc": "2.0", "id": mid, "result": call_handoff(arguments)}
        if name == "dingai_scope_check":
            report = scope_check(arguments.get("project") or None)
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": format_scope(report)}], "structured": report}}
        if name == "dingai_reject":
            result = reject_changes(arguments.get("paths"), arguments.get("project") or None)
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": json.dumps(result)}], "structured": result}}
        if name == "dingai_list_pins":
            result = list_agent_pins(arguments.get("project") or None)
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": json.dumps(result)}], "structured": result}}
        if name == "dingai_mark_fixed":
            result = mark_fixed(arguments)
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": json.dumps(result)}], "structured": result}}
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown tool"}}
    if mid is None:
        return None
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}}


def read_message(stream):
    headers = {}
    while True:
        line = stream.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        decoded = line.decode("utf-8", "replace")
        if ":" not in decoded:
            continue
        key, value = decoded.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length") or "0")
    body = stream.read(length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def write_message(obj, stream):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    stream.write(("Content-Length: %d\r\n\r\n" % len(data)).encode("ascii") + data)
    stream.flush()


def serve_mcp(stdin, stdout):
    while True:
        msg = read_message(stdin)
        if msg is None:
            return
        reply = handle_rpc(msg)
        if reply is not None:
            write_message(reply, stdout)


def state_root():
    from core.sync import load_settings
    cfg = load_settings()
    if cfg["mode"] == "folder" and cfg["share_dir"]:
        return os.path.join(cfg["share_dir"], "dingai-state")
    env = os.environ.get("DINGAI_STATE_DIR", "").strip()
    if env:
        return env
    return os.path.join(os.path.expanduser("~"), "DingAI")


def _flag(argv, name):
    if name in argv:
        index = argv.index(name)
        if index + 1 < len(argv):
            return argv[index + 1]
    return ""


def open_from_note(path, version="", tag=""):
    from core.release import open_release
    try:
        note = json.loads(read_note(path) or "{}")
    except ValueError:
        note = {}
    if not isinstance(note, dict):
        note = {}
    note_id = str(note.get("file") or note.get("id") or "note")
    project = project_dir()
    report = scope_check(project) if project else {}
    base = (load_baseline(project) or {}).get("head") if project else ""
    diff = ""
    commits = []
    if project and base:
        diff = git(project, ["diff", "--stat", "--no-renames", base]) or ""
        commits = [line for line in (git(project, ["log", "--format=%H", "%s..HEAD" % base]) or "").splitlines() if line]
    parent = os.path.dirname(os.path.abspath(path)) if path else ""
    before = ""
    shot_name = str(note.get("screenshot") or "")
    if shot_name:
        for candidate in (
            os.path.join(parent, shot_name) if parent else "",
            os.path.join(os.path.expanduser("~"), "DingAI", "shots", os.path.basename(shot_name)),
        ):
            if candidate and os.path.isfile(candidate):
                before = candidate
                break
    pins = []
    shots = {}
    for pin in note.get("pins") or []:
        if not isinstance(pin, dict):
            continue
        pid = pin.get("id")
        key = "%s:%s" % (note_id, pid)
        row = dict(pin)
        row["note_id"] = note_id
        row["pin_id"] = pid
        row["key"] = key
        pins.append(row)
        after = ""
        if parent:
            verify = os.path.join(parent, "verify-%s-%s.png" % (note_id, pid))
            if os.path.isfile(verify):
                after = verify
        if before or after:
            shots[key] = {"before": before, "after": after}
    return open_release(
        state_root(), pins, version=version, tag=tag,
        project=str(note.get("project") or ""), repo=project or "",
        rules=load_rules(), diff_summary=diff,
        scope_warnings=report.get("warnings") or [],
        head=report.get("head") or "", commits=commits, shots=shots,
    )


def sessions_enabled():
    return os.environ.get("DINGAI_SESSIONS", "1") != "0"


def _csv(argv, name):
    text = _flag(argv, name)
    return [part.strip() for part in text.split(",") if part.strip()] if text else []


def mirror_notices():
    home = os.path.join(os.path.expanduser("~"), "DingAI", "notices.json")
    src = os.path.join(state_root(), "notices.json")
    if os.path.abspath(src) == os.path.abspath(home) or not os.path.isfile(src):
        return
    os.makedirs(os.path.dirname(home), exist_ok=True)
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    with open(home, "w", encoding="utf-8") as fh:
        fh.write(text)


def push_session(path, body):
    from core.sync import load_settings
    cfg = load_settings()
    if cfg["mode"] != "server" or not cfg["server_url"]:
        return None
    import urllib.request
    headers = {"Content-Type": "application/json"}
    if cfg.get("token"):
        headers["Authorization"] = "Bearer " + cfg["token"]
    req = urllib.request.Request(cfg["server_url"].rstrip("/") + path, data=json.dumps(body).encode("utf-8"), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode() or "{}")
    except Exception:
        return None


def register_observed(fields):
    if not sessions_enabled():
        return None
    from core.collide import register, write_notices
    local = register(state_root(), fields)
    remote = push_session("/api/sessions", fields)
    if remote and "warnings" in remote:
        write_notices(state_root(), remote.get("warnings") or [])
        local = remote
    mirror_notices()
    banner = (local or {}).get("banner") or ""
    if banner:
        sys.stderr.write(banner + "\n")
    return local


def observe_note(note_text, agent=""):
    if not sessions_enabled():
        return None
    try:
        note = json.loads(note_text or "")
    except ValueError:
        note = {}
    if not isinstance(note, dict):
        note = {}
    pins = []
    projects = {}
    paths = []
    for pin in note.get("pins") or []:
        if not isinstance(pin, dict):
            continue
        key = "%s:%s" % (note.get("file") or note.get("id") or "note", pin.get("id"))
        pins.append(key)
        if pin.get("project"):
            projects[key] = pin["project"]
        for path in pin.get("paths") or []:
            paths.append(path)
    repo = project_dir()
    if not repo and not pins:
        return None
    branch = ""
    if repo:
        branch = (git(repo, ["rev-parse", "--abbrev-ref", "HEAD"]) or "").strip()
    return register_observed({
        "agent": agent or os.environ.get("DINGAI_AGENT") or "handoff",
        "repo": repo,
        "branch": branch,
        "project": str(note.get("project") or ""),
        "pins": pins,
        "pin_projects": projects,
        "paths": paths,
    })


def observe_fixed(note_id, pin_id):
    if not sessions_enabled():
        return None
    from core.collide import list_sessions
    repo = project_dir()
    active = [
        row for row in list_sessions(state_root())
        if row.get("status") == "active" and (not repo or row.get("repo") == repo)
    ]
    if not active:
        return None
    session = active[-1]
    pins = [str(pin) for pin in session.get("pins") or []]
    key = "%s:%s" % (note_id, pin_id)
    if key not in pins:
        pins.append(key)
    return register_observed({
        "agent": session.get("agent") or "handoff",
        "repo": session.get("repo") or "",
        "branch": session.get("branch") or "",
        "project": session.get("project") or "",
        "pins": pins,
        "pin_projects": session.get("pin_projects") or {},
        "paths": session.get("paths") or [],
        "ports": session.get("ports") or [],
        "services": session.get("services") or [],
        "databases": session.get("databases") or [],
        "deploys": session.get("deploys") or [],
        "head": session.get("head") or "",
    })


def session_fields(argv):
    return {
        "agent": _flag(argv, "--agent") or os.environ.get("DINGAI_AGENT") or "handoff",
        "repo": _flag(argv, "--repo") or project_dir(),
        "branch": _flag(argv, "--branch"),
        "project": _flag(argv, "--project"),
        "pins": _csv(argv, "--pin"),
        "paths": _csv(argv, "--paths"),
        "services": _csv(argv, "--services"),
        "ports": _csv(argv, "--ports"),
        "databases": _csv(argv, "--databases"),
        "deploys": _csv(argv, "--deploys"),
    }


def session_main(argv):
    from core import collide
    if len(argv) < 3:
        sys.stderr.write("usage: handoff.py session start|choose|end|list\n")
        return 2
    root = state_root()
    sub = argv[2]
    if sub == "list":
        sys.stdout.write(json.dumps(collide.list_sessions(root), ensure_ascii=False) + "\n")
        return 0
    if sub == "start":
        fields = session_fields(argv)
        if not fields["branch"] and fields["repo"]:
            fields["branch"] = (git(fields["repo"], ["rev-parse", "--abbrev-ref", "HEAD"]) or "").strip()
        result = collide.register(root, fields)
        push_session("/api/sessions", fields)
        mirror_notices()
        banner = result.get("banner") or ""
        if banner:
            sys.stderr.write(banner + "\n")
        sys.stdout.write(json.dumps({"ok": True, "id": result["session"]["id"], "warnings": result.get("warnings") or []}, ensure_ascii=False) + "\n")
        return 0
    if sub == "choose":
        if len(argv) < 5:
            sys.stderr.write("usage: handoff.py session choose <id> queue|isolate|hand|continue\n")
            return 2
        result = collide.choose(root, argv[3], argv[4], actor=_flag(argv, "--actor") or "local")
        push_session("/api/sessions/%s/choose" % argv[3], {"choice": argv[4]})
        mirror_notices()
        sys.stdout.write(json.dumps({"ok": result.get("ok"), "error": result.get("error", ""), "status": (result.get("session") or {}).get("status", "")}) + "\n")
        return 0 if result.get("ok") else 1
    if sub == "end":
        if len(argv) < 4:
            sys.stderr.write("usage: handoff.py session end <id>\n")
            return 2
        result = collide.end_session(root, argv[3])
        push_session("/api/sessions/%s/end" % argv[3], {})
        mirror_notices()
        sys.stdout.write(json.dumps({"ok": result.get("ok"), "overlaps": result.get("overlaps") or [], "error": result.get("error", "")}, ensure_ascii=False) + "\n")
        return 0 if result.get("ok") else 1
    sys.stderr.write("unknown session command\n")
    return 2


def release_main(argv):
    from core import release as rel
    if len(argv) < 3:
        sys.stderr.write("usage: handoff.py release open|decide|publish|export|search|rollback\n")
        return 2
    sub = argv[2]
    root = state_root()
    if sub == "open":
        path = argv[3] if len(argv) > 3 and not str(argv[3]).startswith("--") else ""
        opened = open_from_note(path, _flag(argv, "--version"), _flag(argv, "--tag"))
        page = os.path.join(root, "releases", opened["id"], "review.html")
        sys.stdout.write(json.dumps({"ok": True, "id": opened["id"], "page": page}) + "\n")
        return 0
    if sub == "decide":
        if len(argv) < 6:
            sys.stderr.write("usage: handoff.py release decide <id> <pin> approve|reject\n")
            return 2
        result = rel.decide(root, argv[3], argv[4], argv[5], _flag(argv, "--reviewer"))
        sys.stdout.write(json.dumps({k: v for k, v in result.items() if k != "release"}) + "\n")
        return 0 if result.get("ok") else 1
    if sub == "publish":
        if len(argv) < 4:
            sys.stderr.write("usage: handoff.py release publish <id> [--override reason]\n")
            return 2
        result = rel.publish(
            root, argv[3], actor=_flag(argv, "--actor") or "local",
            admin=os.environ.get("DINGAI_RELEASE_ADMIN") == "1",
            override_reason=_flag(argv, "--override"),
        )
        sys.stdout.write(json.dumps({k: v for k, v in result.items() if k != "release"}, ensure_ascii=False) + "\n")
        return 0 if result.get("ok") else 1
    if sub == "export":
        if len(argv) < 6:
            sys.stderr.write("usage: handoff.py release export <id> zip|markdown <dest>\n")
            return 2
        result = rel.export_release(root, argv[3], argv[4], argv[5])
        sys.stdout.write(json.dumps(result) + "\n")
        return 0 if result.get("ok") else 1
    if sub == "search":
        query = argv[3] if len(argv) > 3 else ""
        sys.stdout.write(json.dumps(rel.search_releases(root, query), ensure_ascii=False) + "\n")
        return 0
    if sub == "rollback":
        if len(argv) < 4:
            sys.stderr.write("usage: handoff.py release rollback <id>\n")
            return 2
        result = rel.rollback(root, argv[3], _flag(argv, "--actor") or "local")
        body = {"ok": result.get("ok"), "error": result.get("error", ""), "id": (result.get("release") or {}).get("id", ""), "restores": (result.get("release") or {}).get("restores", "")}
        sys.stdout.write(json.dumps(body) + "\n")
        return 0 if result.get("ok") else 1
    sys.stderr.write("unknown release command\n")
    return 2


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "rules"
    if cmd in ("-h", "--help", "help"):
        sys.stdout.write(__doc__ or "")
        return 0
    if cmd == "rules":
        sys.stdout.write(load_rules() + "\n")
        return 0
    if cmd == "prompt":
        path = argv[2] if len(argv) > 2 else ""
        record_baseline()
        note = read_note(path)
        observe_note(note, "")
        sys.stdout.write(prompt_for(note))
        return 0
    if cmd == "baseline":
        saved = record_baseline(argv[2] if len(argv) > 2 else None)
        if not saved:
            sys.stderr.write("could not record a baseline\n")
            return 1
        sys.stdout.write(saved["head"] + "\n")
        return 0
    if cmd == "scope":
        report = scope_check(argv[2] if len(argv) > 2 else None)
        sys.stdout.write(format_scope(report) + "\n")
        return 0 if report.get("ok") else 1
    if cmd == "reject":
        result = reject_changes(None, argv[2] if len(argv) > 2 else None)
        sys.stdout.write(json.dumps(result) + "\n")
        return 0 if result.get("ok") else 1
    if cmd == "pins":
        sys.stdout.write(json.dumps(list_agent_pins(argv[2] if len(argv) > 2 else None), ensure_ascii=False, indent=2) + "\n")
        return 0
    if cmd == "verify":
        if len(argv) < 5:
            sys.stderr.write("usage: handoff.py verify <before.png> <after.png> <outdir>\n")
            return 2
        from core.diff import write_diff
        result = write_diff(argv[2], argv[3], argv[4])
        sys.stdout.write(json.dumps(result) + "\n")
        return 0 if result.get("ok") else 1
    if cmd in ("confirm", "reopen"):
        if len(argv) < 4:
            sys.stderr.write("usage: handoff.py %s <note_id> <pin_id>\n" % cmd)
            return 2
        from core.sync import load_settings, set_pin_status
        cfg = load_settings()
        status = "confirmed" if cmd == "confirm" else "open"
        result = set_pin_status(cfg["project"], argv[2], argv[3], status, None, "")
        sys.stdout.write(json.dumps(result) + "\n")
        return 0 if result.get("ok") else 1
    if cmd == "mark-fixed":
        if len(argv) < 4:
            sys.stderr.write("usage: handoff.py mark-fixed <note_id> <pin_id> [verify.png]\n")
            return 2
        result = mark_fixed({
            "note_id": argv[2],
            "pin_id": argv[3],
            "verification_path": argv[4] if len(argv) > 4 else "",
        })
        sys.stdout.write(json.dumps(result) + "\n")
        return 0 if result.get("ok") else 1
    if cmd == "release":
        return release_main(argv)
    if cmd == "session":
        return session_main(argv)
    if cmd == "mcp":
        serve_mcp(sys.stdin.buffer, sys.stdout.buffer)
        return 0
    sys.stderr.write("unknown command: %s\n" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
