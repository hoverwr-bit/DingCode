---
name: dingcode
description: >-
  Read DingCode screen pins and hand them to the agent with the dingcode CLI.
  Use when the user mentions DingCode, a pin, an annotation, a screen note, or
  a handoff prompt. pi has no MCP client; do not look for an MCP server.
---

# DingCode

DingCode pins a spot on the screen and stores a JSON note. pi does not speak MCP. Use the `dingcode` command. From this repo, if it is not on `PATH`, run `python3 tools/dingcode/dingcode`.

## When the user wants a pin fixed

1. List pins: `dingcode pins`
2. Print the handoff prompt (rules, then the note): `dingcode prompt path/to/note.json`
   Omit the path to read a note from stdin.
3. Change only what that prompt scopes. The pinned element is the scope.
4. Check the diff: `dingcode scope`
5. After the change is verified, mark the pin: `dingcode mark-fixed <note_id> <pin_id> [verify.png]`

## Other commands

- `dingcode confirm <note_id> <pin_id>` marks a pin confirmed.
- `dingcode reopen <note_id> <pin_id>` sets it back to open.
- `dingcode rules` prints the handoff rules.

Do not start `dingcode mcp`. That server is for Claude Code, Codex, and Cursor.
