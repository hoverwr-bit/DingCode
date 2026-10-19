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
    sys.stderr.write("unknown command: %s\n" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
