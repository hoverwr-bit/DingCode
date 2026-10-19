#!/usr/bin/env python3
"""DingAI handoff: rules on the prompt, plus a stdio MCP server.

No third-party packages. The desktop and page clients copy a prompt themselves;
this script is the CLI and the MCP server (nothing else in the toolbox speaks MCP).

  python3 handoff.py rules
  python3 handoff.py prompt [note.json]     # stdin when the path is omitted
  python3 handoff.py mcp                    # Content-Length JSON-RPC on stdio
"""

import json
import os
import sys

DEFAULT_RULES = """- Make the smallest change that fixes the pinned issue. Do not refactor or rewrite surrounding code.
- Follow the project's ARCHITECTURE or conventions file before adding code.
- Touch only code related to the pinned element.
- Do not add dependencies or files unless you state why.
- Explain the diff and how it was verified."""

PROMPT_LEAD = "Apply the rules above to this DingAI note. The pinned element is the only scope."


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


def call_handoff(arguments):
    arguments = arguments or {}
    if arguments.get("note_path"):
        note = read_note(arguments["note_path"])
    else:
        note = arguments.get("note") or ""
    text = prompt_for(note)
    return {"content": [{"type": "text", "text": text}]}


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
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": [tool_schema()]}}
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        if name != "dingai_handoff":
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown tool"}}
        return {"jsonrpc": "2.0", "id": mid, "result": call_handoff(params.get("arguments"))}
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
        sys.stdout.write(prompt_for(read_note(path)))
        return 0
    if cmd == "mcp":
        serve_mcp(sys.stdin.buffer, sys.stdout.buffer)
        return 0
    sys.stderr.write("unknown command: %s\n" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
