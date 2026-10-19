#!/usr/bin/env python3
"""DingAI handoff: rules on the prompt, plus one MCP server.

No third-party packages. `dingai` and this file are the same program.

  python3 handoff.py rules
  python3 handoff.py latest                 # newest local note, pins as JSON
  python3 handoff.py prompt [note.json]     # stdin when the path is omitted and stdin is a pipe
  python3 handoff.py baseline [project]
  python3 handoff.py scope [project]
  python3 handoff.py reject [project]
  python3 handoff.py pins [project]         # shared folder or team server
  python3 handoff.py mark-fixed <note_id> <pin_id> [verify.png]
  python3 handoff.py export markdown <note.json> <dest>
  python3 handoff.py export github <note.json> <dest>
  python3 handoff.py verify <before.png> <after.png> <outdir>
  python3 handoff.py confirm <note_id> <pin_id>
  python3 handoff.py reopen <note_id> <pin_id>
  python3 handoff.py update                 # only contacts GitHub when DINGAI_UPDATE=1
  python3 handoff.py mcp                    # stdio: one JSON-RPC message per line, or Content-Length
  python3 handoff.py mcp-http [--port 8764] # POST /mcp on 127.0.0.1, no SSE
"""

import base64
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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


def screenshot_tool_schema():
    return {
        "name": "dingai_screenshot",
        "description": "Return the PNG for a pin, or the newest local note when no pin is named.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "note_id": {"type": "string"},
                "pin_id": {"type": "string"},
                "uri": {"type": "string", "description": "dingai://screenshot/<note_id>/<pin_id>"},
            },
        },
    }


PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")
MCP_SESSION = "dingai"


def output_root():
    env = os.environ.get("DINGAI_OUTPUT_DIR", "").strip() or os.environ.get("ANNO_OUTPUT_DIR", "").strip()
    home = os.path.expanduser("~")
    if not env:
        return os.path.join(home, "DingAI")
    if os.path.isabs(env):
        return env
    return os.path.join(home, env)


def newest_local_note():
    notes = os.path.join(output_root(), "notes")
    if not os.path.isdir(notes):
        return "", None
    files = [os.path.join(notes, name) for name in os.listdir(notes) if name.endswith(".json")]
    if not files:
        return "", None
    files.sort(key=lambda path: (os.path.getmtime(path), path))
    path = files[-1]
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return path, None
    return path, data if isinstance(data, dict) else None


def resolve_screenshot(note, note_path=""):
    if not isinstance(note, dict):
        return ""
    name = str(note.get("screenshot") or "")
    if not name:
        return ""
    root = output_root()
    base = os.path.basename(name)
    candidates = []
    if os.path.isabs(name):
        candidates.append(name)
    candidates.append(os.path.join(root, "shots", base))
    if note_path:
        parent = os.path.dirname(note_path)
        candidates.append(os.path.join(parent, base))
        candidates.append(os.path.join(os.path.dirname(parent), "shots", base))
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return ""


def latest_pins_json():
    path, note = newest_local_note()
    if note is not None:
        pins = note.get("pins")
        return {
            "ok": True,
            "mode": "local",
            "note": path,
            "screenshot": resolve_screenshot(note, path),
            "pins": pins if isinstance(pins, list) else [],
        }
    return list_agent_pins()


def write_export_bundle(note_text, png_bytes=None, dest_root=None):
    root = dest_root or os.path.join(output_root(), "export")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    folder = os.path.join(root, stamp)
    os.makedirs(folder, exist_ok=True)
    prompt = prompt_for(note_text or "")
    with open(os.path.join(folder, "prompt.txt"), "w", encoding="utf-8") as fh:
        fh.write(prompt)
    body = note_text or ""
    if body and not body.endswith("\n"):
        body += "\n"
    with open(os.path.join(folder, "note.json"), "w", encoding="utf-8") as fh:
        fh.write(body)
    if png_bytes:
        with open(os.path.join(folder, "screenshot.png"), "wb") as fh:
            fh.write(png_bytes)
    return folder


_CLIP_PROCS = []


def _xclip(exe, args, data):
    try:
        proc = subprocess.Popen(
            [exe, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        proc.stdin.write(data)
        proc.stdin.close()
    except OSError:
        return False
    _CLIP_PROCS.append(proc)
    while len(_CLIP_PROCS) > 2:
        old = _CLIP_PROCS.pop(0)
        old.kill()
        try:
            old.wait(timeout=1)
        except Exception:
            pass
    return True


def offer_clipboard(prompt, png_path=""):
    """Best effort for a Linux session. xclip keeps one target per selection, so the prompt goes to the clipboard and the PNG to the primary selection."""
    exe = shutil.which("xclip")
    if not exe:
        return False
    ok = _xclip(exe, ["-selection", "clipboard", "-t", "text/plain"], (prompt or "").encode("utf-8"))
    if png_path and os.path.isfile(png_path):
        with open(png_path, "rb") as fh:
            _xclip(exe, ["-selection", "primary", "-t", "image/png"], fh.read())
    return ok


def _add_shot(items, seen, uri, name, path):
    if not uri or uri in seen or not path or not os.path.isfile(path):
        return
    seen.add(uri)
    items.append({"uri": uri, "name": name or os.path.basename(path), "mimeType": "image/png", "path": path})


def screenshot_index():
    items = []
    seen = set()
    path, note = newest_local_note()
    shot = resolve_screenshot(note, path) if note else ""
    if note and shot:
        note_id = str(note.get("file") or note.get("id") or os.path.splitext(os.path.basename(path))[0])
        _add_shot(items, seen, "dingai://screenshot/%s" % note_id, os.path.basename(shot), shot)
        for pin in note.get("pins") or []:
            if not isinstance(pin, dict) or pin.get("id") is None:
                continue
            _add_shot(
                items, seen,
                "dingai://screenshot/%s/%s" % (note_id, pin.get("id")),
                "pin-%s" % pin.get("id"),
                shot,
            )
    try:
        listed = list_agent_pins()
    except Exception:
        listed = {}
    for pin in listed.get("pins") or []:
        sp = pin.get("screenshot_path") or ""
        note_id = str(pin.get("note_id") or "note")
        _add_shot(items, seen, "dingai://screenshot/%s/%s" % (note_id, pin.get("id")), os.path.basename(sp), sp)
        _add_shot(items, seen, "dingai://screenshot/%s" % note_id, os.path.basename(sp), sp)
    return items


def find_screenshot(uri):
    for item in screenshot_index():
        if item["uri"] == uri:
            return item["path"]
    return ""


def call_screenshot(arguments):
    arguments = arguments or {}
    uri = arguments.get("uri") or ""
    note_id = arguments.get("note_id") or ""
    pin_id = arguments.get("pin_id")
    if not uri and note_id and pin_id not in (None, ""):
        uri = "dingai://screenshot/%s/%s" % (note_id, pin_id)
    elif not uri and note_id:
        uri = "dingai://screenshot/%s" % note_id
    path = find_screenshot(uri) if uri else ""
    if not path:
        note_path, note = newest_local_note()
        if note and (not note_id or str(note.get("file") or note.get("id") or "") == str(note_id)):
            path = resolve_screenshot(note, note_path)
    if not path:
        try:
            listed = list_agent_pins(arguments.get("project") or None)
        except Exception:
            listed = {}
        for pin in listed.get("pins") or []:
            if pin_id not in (None, "") and str(pin.get("id")) != str(pin_id):
                continue
            if note_id and str(pin.get("note_id") or "") != str(note_id):
                continue
            sp = pin.get("screenshot_path") or ""
            if sp and os.path.isfile(sp):
                path = sp
                break
    if not path or not os.path.isfile(path):
        return {"content": [{"type": "text", "text": "screenshot not found"}], "isError": True}
    with open(path, "rb") as fh:
        blob = base64.b64encode(fh.read()).decode("ascii")
    return {"content": [{"type": "image", "data": blob, "mimeType": "image/png"}]}


def protocol_version(msg):
    asked = (msg.get("params") or {}).get("protocolVersion")
    if asked in PROTOCOL_VERSIONS:
        return asked
    return "2024-11-05"


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
    return set_pin_status(project, note_id, str(pin_id), "ai-fixed", blob, arguments.get("comment") or "")


def call_handoff(arguments):
    arguments = arguments or {}
    if arguments.get("note_path"):
        note = read_note(arguments["note_path"])
    else:
        note = arguments.get("note") or ""
    record_baseline()
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
            "protocolVersion": protocol_version(msg),
            "capabilities": {"tools": {}, "resources": {}},
            "serverInfo": {"name": "dingai", "version": "0.1"},
        }}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": [
            tool_schema(), scope_tool_schema(), reject_tool_schema(),
            list_tool_schema(), mark_tool_schema(), screenshot_tool_schema()]}}
    if method == "resources/list":
        rows = [{"uri": item["uri"], "name": item["name"], "mimeType": "image/png"} for item in screenshot_index()]
        return {"jsonrpc": "2.0", "id": mid, "result": {"resources": rows}}
    if method == "resources/read":
        uri = ((msg.get("params") or {}).get("uri")) or ""
        found = find_screenshot(uri)
        if not found:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32002, "message": "screenshot not found"}}
        with open(found, "rb") as fh:
            blob = base64.b64encode(fh.read()).decode("ascii")
        return {"jsonrpc": "2.0", "id": mid, "result": {"contents": [{
            "uri": uri, "mimeType": "image/png", "blob": blob,
        }]}}
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
        if name == "dingai_screenshot":
            return {"jsonrpc": "2.0", "id": mid, "result": call_screenshot(arguments)}
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


class _Pushback:
    def __init__(self, first, stream):
        self._first = first
        self._stream = stream

    def readline(self):
        if self._first is not None:
            line, self._first = self._first, None
            return line
        return self._stream.readline()

    def read(self, n):
        return self._stream.read(n)


def _write_ndjson(obj, stream):
    stream.write(json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n")
    stream.flush()


def serve_mcp(stdin, stdout):
    """MCP stdio. A leading Content-Length header keeps the old framing; otherwise one JSON object per line."""
    first = stdin.readline()
    if not first:
        return
    if first.lstrip()[:14].lower() == b"content-length":
        wrapped = _Pushback(first, stdin)
        while True:
            msg = read_message(wrapped)
            if msg is None:
                return
            reply = handle_rpc(msg)
            if reply is not None:
                write_message(reply, stdout)
        return
    line = first
    while line:
        text = line.decode("utf-8", "replace").strip()
        if text:
            try:
                msg = json.loads(text)
            except ValueError:
                msg = None
            if isinstance(msg, dict):
                reply = handle_rpc(msg)
                if reply is not None:
                    _write_ndjson(reply, stdout)
        line = stdin.readline()


class McpHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s\n" % (fmt % args))

    def _path_ok(self):
        return self.path.split("?", 1)[0] in ("/mcp", "/")

    def _authorized(self):
        token = os.environ.get("DINGAI_MCP_TOKEN", "")
        if not token:
            return True
        return self.headers.get("Authorization", "") == "Bearer " + token

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, Accept, Mcp-Session-Id, MCP-Protocol-Version")
        self.send_header("Access-Control-Expose-Headers", "Mcp-Session-Id")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, DELETE, OPTIONS")

    def _wants_json(self):
        accept = self.headers.get("Accept", "")
        if not accept:
            return True
        return "application/json" in accept or "*/*" in accept

    def _send(self, code, body=b"", content_type="application/json", session=False):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if session:
            self.send_header("Mcp-Session-Id", self.headers.get("Mcp-Session-Id") or MCP_SESSION)
        self._cors()
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def do_OPTIONS(self):
        if not self._path_ok():
            self._send(404, b"")
            return
        self._send(204, b"")

    def do_GET(self):
        if not self._path_ok():
            self._send(404, b"")
            return
        if not self._authorized():
            self._send(401, b'{"error":"unauthorized"}')
            return
        self.send_response(405)
        self.send_header("Allow", "POST, DELETE, OPTIONS")
        self.send_header("Content-Length", "0")
        self._cors()
        self.end_headers()

    def do_DELETE(self):
        if not self._path_ok():
            self._send(404, b"")
            return
        if not self._authorized():
            self._send(401, b'{"error":"unauthorized"}')
            return
        self._send(204, b"")

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length else b""
        if not self._path_ok():
            self._send(404, b"")
            return
        if not self._authorized():
            self._send(401, b'{"error":"unauthorized"}')
            return
        if not self._wants_json():
            self._send(406, b'{"error":"application/json only"}')
            return
        try:
            msg = json.loads(raw.decode("utf-8") or "null")
        except ValueError:
            self._send(400, b'{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"parse error"}}')
            return
        reply = handle_rpc(msg) if isinstance(msg, dict) else None
        if reply is None:
            self._send(202, b"")
            return
        body = json.dumps(reply, ensure_ascii=False).encode("utf-8")
        self._send(200, body, session=True)


def make_http_server(host, port):
    return ThreadingHTTPServer((host, port), McpHandler)


def serve_http(host="127.0.0.1", port=8764):
    if host not in ("127.0.0.1", "::1"):
        sys.stderr.write("mcp-http listens on loopback only\n")
        return 1
    server = make_http_server(host, port)
    sys.stderr.write("dingai mcp-http http://%s:%s/mcp\n" % (host, server.server_address[1]))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "rules"
    if cmd in ("-h", "--help", "help"):
        sys.stdout.write(__doc__ or "")
        return 0
    if cmd == "update":
        from core.update import check_update
        try:
            result = check_update()
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        sys.stdout.write(json.dumps(result) + "\n")
        return 0 if result.get("ok") else 1
    if cmd == "rules":
        sys.stdout.write(load_rules() + "\n")
        return 0
    if cmd == "latest":
        sys.stdout.write(json.dumps(latest_pins_json(), ensure_ascii=False, indent=2) + "\n")
        return 0
    if cmd == "prompt":
        path = argv[2] if len(argv) > 2 else ""
        record_baseline()
        if not path and sys.stdin.isatty():
            path, _note = newest_local_note()
            if not path:
                sys.stderr.write("no local note\n")
                return 1
        sys.stdout.write(prompt_for(read_note(path)))
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
    if cmd == "export":
        if len(argv) < 5:
            sys.stderr.write("usage: handoff.py export <markdown|github|name> <note.json> <dest>\n")
            return 2
        from core.export import export_note
        try:
            note = json.loads(read_note(argv[3]) or "{}")
        except ValueError:
            note = {}
        result = export_note(argv[2], note, argv[4])
        sys.stdout.write(json.dumps(result) + "\n")
        return 0 if result.get("ok") else 1
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
    if cmd == "mcp":
        serve_mcp(sys.stdin.buffer, sys.stdout.buffer)
        return 0
    if cmd == "mcp-http":
        host, port = "127.0.0.1", 8764
        index = 2
        while index < len(argv):
            if argv[index] == "--host" and index + 1 < len(argv):
                host = argv[index + 1]
                index += 2
            elif argv[index] == "--port" and index + 1 < len(argv):
                port = int(argv[index + 1])
                index += 2
            else:
                sys.stderr.write("usage: handoff.py mcp-http [--host 127.0.0.1] [--port 8764]\n")
                return 2
        return serve_http(host, port)
    sys.stderr.write("unknown command: %s\n" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
