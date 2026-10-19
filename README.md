# AI-toolbox

A toolbox of local helpers for AI coding agents. The first tool is **DingAI** (formerly AnnoOverlay / anno): point at the screen, and the agent receives machine-readable JSON instead of a one-line description.

**给写代码的 AI 用的本地工具箱。** 第一件工具是 **DingAI**（原 AnnoOverlay / anno）：在屏幕上点一下，智能体拿到的是机器可读的 JSON，而不是一句「改左上角那个按钮」。

DingAI drops pins on any app or web page and exports JSON: app, window, pixel coordinates, nearby OCR text and, inside a browser, the DOM element and field under the pin. Paste that into Claude Code, Codex or any other agent.

## Layout / 目录

| Path | What |
|---|---|
| `tools/dingai/macos/` | DingAI menu-bar app (Swift, AppKit, ScreenCaptureKit, Vision). Live overlay: the app underneath stays usable; the screenshot is taken when you finish |
| `tools/dingai/windows/` | DingAIWin. Live overlay by default, UI Automation anchors, same JSON contract |
| `tools/dingai/linux/` | Linux session. X11 toolbar, optional grim / Tesseract / AT-SPI |
| `tools/dingai/web/anno.js` | In-page annotation layer. Pins anchor to DOM elements and follow scrolling. Localhost bridge to the desktop app |
| `tools/dingai/core/` | Python standard library: note schema, label placement, folder and server sync. Used by Linux and `handoff.py` |
| `tools/dingai/team-server/` | Optional self-hosted board. Accounts, SQLite, Docker. No telemetry |
| `tools/dingai/probes/` | Diagnostic probes (display, capture, OCR, red-pixel scans) |

## Build / 构建

- macOS 14+: `cd tools/dingai/macos && ./build.sh`  
  Signs with a local **DingAI Dev** identity if present, otherwise **AnnoOverlay Dev**, otherwise ad-hoc. Needs Screen Recording. Changing the bundle id to `io.github.dingai.mac` means granting that permission again.
- Windows: `cd tools/dingai/windows && dotnet build`  
  `Ctrl+Alt+A` starts a live session. Hold Alt to click the app underneath. `DINGAI_LIVE=0` freezes the screenshot first, as the older build did. B / C / Q set the next pin to bug, change, or question.
- Linux: `python3 tools/dingai/linux/dingai_linux.py` on X11 or XWayland. `--check` prints which of X11, grim, Tesseract, and the AT-SPI bus are available. Focus the toolbar, press p then click to drop a pin, or a / r / s and two clicks for an arrow, box, or spotlight. B / C / Q set the pin type. Esc exports under `~/DingAI/linux`.
- Web: load `tools/dingai/web/anno.js`, or install the Chrome/Edge extension. `bash tools/dingai/extension/pack.sh` writes `tools/dingai/extension/dist`. In `chrome://extensions` or `edge://extensions`, turn on Developer mode and choose Load unpacked. The extension injects the same page script and talks to the desktop app at `127.0.0.1:8763`. Enable with `?anno=1`, `window.ANNO_V7_ADMIN = true`, or `window.ANNO_ADMIN_CHECK()`. The note dialog has a pin type.
- Team server: see [tools/dingai/team-server/DEPLOY.md](tools/dingai/team-server/DEPLOY.md).

```
export DINGAI_TEAM_ADMIN_TOKEN='choose-a-long-token'
docker compose -f tools/dingai/team-server/compose.yaml up --build -d
```

Without Docker, from `tools/dingai/team-server`: `python3 dingai_team_server.py`. Put Caddy or nginx in front for HTTPS and leave the Python process on `127.0.0.1`. Do not commit the token or certificates.

GitHub Actions (`.github/workflows/dingai.yml`) runs the Python and page checks and builds the server image on Ubuntu, `dotnet build` on Windows, and `swiftc` on macOS.

## Annotating

`⌥⌘A` starts a session on the display under the pointer. The desktop stays live: the scroll wheel goes through to the app, hold ⌥ to click it, and `⌥⌘P` locks that click-through. Pins in a browser follow the element reported by the page bridge; other pins follow the Accessibility element when that permission is granted. B / C / Q set the selected pin to bug, change, or question. Esc writes JSON and a PNG taken at that moment. New pins start `open`. An agent can later mark one `ai-fixed`; a person confirms it on the team board.

## Desktop ↔ page bridge

The macOS app listens on `127.0.0.1:8763` only. A page that has loaded `anno.js` answers `elementFromPoint` so a desktop pin landing in a browser can record the DOM field. Nothing else is contacted unless team upload is configured.

## Configuration / 配置

Clients stay local until you opt in. `~/DingAI/settings.json` is the switch:

Local-only is the default, including when the file is missing. Folder mode:

```json
{ "mode": "folder", "share_dir": "/mnt/dingai", "project": "inbox" }
```

Server mode:

```json
{ "mode": "server", "server_url": "http://127.0.0.1:8050", "token": "paste-the-token", "project": "inbox" }
```

A shared folder is one directory on a NAS or a synced drive. Each pin is its own file under `projects/<project>/pins/`, written via a temp file and rename, so two people can add pins without clobbering each other. Screenshots sit in `shots/`. The page layer cannot read that file; publishing is done by the desktop clients.

| Env var | Used by | Default |
|---|---|---|
| `DINGAI_OUTPUT_DIR` (fallback `ANNO_OUTPUT_DIR`) | macOS, path relative to home; Windows, under the user profile | `DingAI` |
| `DINGAI_MODE` | `local`, `folder`, or `server`. Overrides `settings.json` | `local` |
| `DINGAI_SHARE_DIR` | shared-folder root | empty |
| `DINGAI_TEAM_URLS` (fallback `ANNO_TEAM_URLS`) | team server URL. A value selects server mode when `DINGAI_MODE` is unset | empty = no upload |
| `DINGAI_TEAM_TOKEN` | bearer token for that server | empty |
| `DINGAI_PROJECT_NAME` | board or folder project | `inbox` |
| `DINGAI_LIVE` | Windows. `0` freezes the screenshot at the start | live |
| `DINGAI_TEAM_HOST` / `DINGAI_TEAM_PORT` (fallback `ANNO_TEAM_*`) | team server bind address | `127.0.0.1` / `8050` |
| `DINGAI_TEAM_REQUIRE_AUTH` | `1` rejects anonymous upload. The Docker image sets this | off for a local process |
| `DINGAI_TEAM_ADMIN_TOKEN` | first admin token. If unset, the process prints one random token once | unset |
| `DINGAI_TEAM_ROOT` | SQLite, notes, and screenshots | `~/anno-team` |

## Handoff rules

Every clipboard export is a prompt: the handoff rules, then the JSON note. The note on disk keeps the same rules in `handoff_rules`. Edit them per project in `.dingai/handoff-rules.md` (set `DINGAI_PROJECT`, or put the project path in `~/DingAI/project.txt`). A user-wide file is `~/DingAI/handoff-rules.md`. On a page, set `window.DINGAI_HANDOFF_RULES` or `localStorage['dingai-handoff-rules']`.

```
python3 tools/dingai/handoff.py prompt notes/anno.json
python3 tools/dingai/handoff.py pins
python3 tools/dingai/handoff.py mark-fixed <note_id> <pin_id> verify.png
python3 tools/dingai/handoff.py mcp
```

`pins` and `mark-fixed` are also MCP tools (`dingai_list_pins`, `dingai_mark_fixed`). They read the shared folder or the team server from the settings above. Marking a pin fixed stores the PNG next to the pin. The handoff prompt stays the first MCP tool.

The defaults ask the coding agent for a minimal change, to follow the project's architecture file, to stay on the pinned element, to justify new dependencies, and to explain how the diff was verified.

After the agent marks the pin fixed, compare the tree with the snapshot taken at export:

```
python3 tools/dingai/handoff.py scope
```

The macOS and Windows menus have the same check (“检查本次改动”). Put the paths the pin should touch in `.dingai/scope.txt`, one prefix per line. The check warns about other files, new dependencies or lockfiles, new top-level directories, and a diff over 400 lines or 8 files. Rejecting restores only those paths, and only while `HEAD` is still the snapshot. It does not reset commits. The page copy does not snapshot git; the desktop export and `handoff.py prompt` do.

## Release review

`handoff.py release open note.json` builds a review batch: each pin, the before and after shots cropped on the review page around the pin, the diff stat since the handoff baseline, the scope warnings, the commit SHAs, and the handoff rules. Approve or reject every pin before `release publish`. A rejected or unreviewed pin blocks publishing unless `DINGAI_RELEASE_ADMIN=1` and `--override` gives a reason. That reason is stored on the release and in `releases/audit.jsonl`. The published record is read-only. `release search`, `release export <id> zip|markdown <dest>`, and `release rollback <id>` read it. Rollback points at the previous release and does not edit the archive. On the team board the same pages are under Releases. The server stores them in `<DINGAI_TEAM_ROOT>/state`.

## Session collisions

`handoff.py session start` records the agent, repo, branch, pins, paths, and any services, ports, databases, or deploy targets. The same check runs when a prompt is built and when a pin is marked fixed. It warns, without stopping the handoff, about a shared repo and branch, overlapping paths, a pin claimed twice, a pin sent to the wrong project, a shared service or port or database or deploy target, and a working tree whose `HEAD` moved. `session choose <id> queue|isolate|hand|continue` queues the second session, makes a git worktree and branch, gives the pin to the session that already owns the area, or continues. Continue is written onto the session. Locks expire after four hours. `session end <id>` drops them and prints overlapping diffs. One user can keep this in `~/DingAI`. The team server stores the same records, and the board shows a yellow banner. The desktop clients read `~/DingAI/notices.json` and draw that banner. Set `DINGAI_SESSIONS=0` to skip the automatic check.

## JSON contract

Desktop notes use `schema: "dingai-desktop-v1"` and `tool: "dingai"`. The field set matches the previous `anno-desktop-v1` contract (`schema_compat` records that name): `pins[].x_px` / `y_px` are screenshot pixels with a top-left origin, plus `window_nx` / `window_ny`, `ocr_nearby`, optional `note`, optional `window`, and optional `page` from the browser bridge. Optional `pin_type` is `bug` (the default), `change`, or `question`. Optional `status` is `open` (the default), `ai-fixed`, or `confirmed`. Arrows use `from_px` / `to_px`. Boxes use `rect_px` and an optional `shape`. Page export stays `version: 7.9` and stores `pinType` and `status` on each annotation.

## License

MIT
