# DingCode

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**DingCode pins visual annotations onto any app or web page and hands your AI coding agent machine-readable JSON — not "fix the button in the top left".**

DingCode is a local-first annotation and handoff tool for AI coding agents. Drop pins on a live overlay — the app underneath keeps working — and Esc exports structured JSON with app, window, and pixel coordinates, nearby OCR text, and, inside a browser, the DOM element under the pin, next to a screenshot taken when the session ends. One handoff prompt or MCP call passes all of it to Claude Code, Codex, or any other agent, which can then fix each pin and report back. Everything runs on your machine: screenshots and notes stay on disk, and the only network is your own loopback bridge plus opt-in team upload or release checks. The CLI, MCP server, and Python core are covered by unit tests in CI; several desktop UI paths are implemented but have not yet been through real-device acceptance — see [tools/dingcode/docs/PRD.md](tools/dingcode/docs/PRD.md).

**中文：把屏幕批注钉给 AI 编程代理的本地工具。**

DingCode 在任何应用或网页上打「钉子」，导出机器可读的 JSON：应用、窗口、像素坐标、附近 OCR 文本，浏览器里还有钉子所在的 DOM 元素，并附上一张会话结束时截取的屏幕图。一条交接提示词或一次 MCP 调用就能交给 Claude Code、Codex 等代理逐颗修复。全部在本地运行：截图和笔记留在磁盘上，只有本机回环桥接，以及可选的团队上传和更新检查才会联网。CLI、MCP 服务器和 Python 核心有单元测试覆盖；部分桌面界面路径已实现但还没做过真机验收，见 [tools/dingcode/docs/PRD.md](tools/dingcode/docs/PRD.md)。

Languages are Chinese, English, and Vietnamese (`DINGCODE_LANG=zh|en|vi`). Signing, notarization, and packaged releases are described in `tools/dingcode/RELEASE.md`. An update check runs only when `DINGCODE_UPDATE=1`.

## Features

- **Live overlay annotation** on macOS (menu-bar app, `⌥⌘A`), Windows (`Ctrl+Alt+A`), and Linux X11: pins, arrows, boxes, ellipse, spotlight, and text, with the app underneath still usable; the screenshot is taken when the session ends, so pin coordinates match the PNG.
- **Structured JSON export** (`dingcode-desktop-v1`): `x_px`/`y_px`, `window_nx`/`window_ny`, `ocr_nearby`, optional window and page info, pin type (`bug`/`change`/`question`) and status (`open`/`ai-fixed`/`confirmed`).
- **In-page annotation**: `web/anno.js` pins anchor to DOM elements and follow scrolling; the Chrome/Edge extension injects the same script and talks to the desktop app on `127.0.0.1:8763`.
- **CLI and MCP handoff**: `dingcode prompt` builds the handoff prompt; `dingcode mcp` speaks MCP on stdio (`dingcode_handoff`, `dingcode_list_pins`, `dingcode_mark_fixed` with a verification PNG) for Claude Code, Codex, and Cursor.
- **Auto-fix with per-round revert**: after Send, the Mac app runs a headless agent (Claude Code or Codex engine) in the bound project folder; each round is snapshotted to `~/.dingcode/runs/` and can be reverted if it changes paths outside the folder.
- **Session record page** (`web/record`, Vue 3, served by the bridge under `/app`): per-pin history, note edit, rerun (next round), and per-pin three-way revert — implemented in `core/runs_api.py`.
- **Release review**: `dingcode release open/publish` gates publishing on every pin being reviewed; rejects and overrides land in `releases/audit.jsonl`, and rollback points at the previous release.
- **Session collision warnings** (CLI, team board, desktop banners) and a **scope check** that warns about paths outside `.dingcode/scope.txt` and can reject out-of-scope changes.
- **Optional self-hosted team server**: accounts, projects, pins, comments, and a review board (SQLite, Docker); no telemetry.
- **Voice notes and step recording** (local whisper.cpp transcription, `sop.md` + `repro.json`) — implemented, not yet verified on real devices.
- **Languages**: Chinese, English, and Vietnamese (`DINGCODE_LANG=zh|en|vi`).
- **Local-first, no telemetry**: notes and screenshots are written to disk on your machine; the bridge listens on `127.0.0.1` only, and the update check runs only when `DINGCODE_UPDATE=1`.

## Quick start

1. **Build the desktop app.** macOS 14+: `cd tools/dingcode/macos && ./build.sh`, then copy `DingCode.app` to `/Applications` and grant Screen Recording. Windows: `cd tools/dingcode/windows && dotnet build`. Linux (X11): `python3 tools/dingcode/linux/dingcode_linux.py` (`--check` shows what is available).
2. **Annotate.** `⌥⌘A` (macOS) or `Ctrl+Alt+A` (Windows) starts a live session; drop pins (B / C / Q set bug / change / question) and press Esc to write the JSON note and screenshot under `~/DingCode`. In a browser, load `tools/dingcode/web/anno.js` or install the Chrome/Edge extension.
3. **Connect your agent.** `claude mcp add -s user dingcode -- dingcode mcp`, or add `dingcode mcp` to `~/.codex/config.toml` / `~/.cursor/mcp.json`. No MCP client? Paste the handoff prompt from `python3 tools/dingcode/dingcode prompt <note.json>`.
4. **(Optional) Let the agent fix the pins.** `python3 tools/dingcode/dingcode bind <url-or-window> <project-folder>`, pick the engine with `dingcode config engine claude|codex`, and Send runs the headless fix; `dingcode result <session>` and `dingcode revert <session>` review or undo a round.
5. **(Optional) Share with a team.** Self-host the board: `docker compose -f tools/dingcode/team-server/compose.yaml up --build -d` (see [tools/dingcode/team-server/DEPLOY.md](tools/dingcode/team-server/DEPLOY.md)).

Tutorial: [tools/dingcode/docs/TUTORIAL.md](tools/dingcode/docs/TUTORIAL.md)

Keywords: UI annotation, pin comments, visual feedback for AI coding agents, AI coding agent handoff, Claude Code, Codex, MCP, vibe coding, local-first, no telemetry, open source, MIT, macOS, Windows, Linux, Vue

DingCode drops pins on any app or web page and exports JSON: app, window, pixel coordinates, nearby OCR text and, inside a browser, the DOM element and field under the pin. Paste that into Claude Code, Codex or any other agent.

## Layout / 目录

| Path | What |
|---|---|
| `tools/dingcode/macos/` | DingCode menu-bar app (Swift, AppKit, ScreenCaptureKit, Vision). Live overlay: the app underneath stays usable; the screenshot is taken when you finish |
| `tools/dingcode/windows/` | DingCode. Live overlay by default, UI Automation anchors, same JSON contract |
| `tools/dingcode/linux/` | Linux session. X11 toolbar, optional grim / Tesseract / AT-SPI |
| `tools/dingcode/handoff.py` | The `dingcode` CLI and stdio MCP server: handoff prompt, pins, mark-fixed, autofix, scope, release, sessions |
| `tools/dingcode/web/anno.js` | In-page annotation layer. Pins anchor to DOM elements and follow scrolling. Localhost bridge to the desktop app |
| `tools/dingcode/web/record/` | Vue 3 session record page, served by the bridge under `/app` (per-pin history, edit, rerun, revert) |
| `tools/dingcode/core/` | Python standard library: note schema, label placement, folder and server sync. Used by Linux and `handoff.py` |
| `tools/dingcode/team-server/` | Optional self-hosted board. Accounts, SQLite, Docker. No telemetry |
| `tools/dingcode/probes/` | Diagnostic probes (display, capture, OCR, red-pixel scans) |

## Build / 构建

- macOS 14+: `cd tools/dingcode/macos && ./build.sh`  
  That writes `tools/dingcode/macos/DingCode.app`. Install with `cp -R tools/dingcode/macos/DingCode.app /Applications/` (run the copy from the repo root, or `cp -R DingCode.app /Applications/` from `tools/dingcode/macos`).  
  Signs with a local **DingCode Dev** identity if present, otherwise **DingAI Dev**, otherwise **AnnoOverlay Dev**, otherwise ad-hoc. Needs Screen Recording. Changing the bundle id to `io.github.dingcode.mac` means granting that permission again.
- Windows: `cd tools/dingcode/windows && dotnet build`  
  `Ctrl+Alt+A` starts a live session. Hold Alt to click the app underneath. `DINGCODE_LIVE=0` freezes the screenshot first, as the older build did. B / C / Q set the next pin to bug, change, or question.
- Linux: `python3 tools/dingcode/linux/dingcode_linux.py` on X11 or XWayland. `--check` prints which of X11, grim, Tesseract, and the AT-SPI bus are available. Focus the toolbar, press p then click to drop a pin, or a / r / s and two clicks for an arrow, box, or spotlight. B / C / Q set the pin type. Esc exports under `~/DingCode/linux`.
- Web: load `tools/dingcode/web/anno.js`, or install the Chrome/Edge extension. `bash tools/dingcode/extension/pack.sh` writes `tools/dingcode/extension/dist`. In `chrome://extensions` or `edge://extensions`, turn on Developer mode and choose Load unpacked. The extension injects the same page script and talks to the desktop app at `127.0.0.1:8763`. Enable with `?anno=1`, `window.ANNO_V7_ADMIN = true`, or `window.ANNO_ADMIN_CHECK()`. The note dialog has a pin type.
- Team server: see [tools/dingcode/team-server/DEPLOY.md](tools/dingcode/team-server/DEPLOY.md).

```
export DINGCODE_TEAM_ADMIN_TOKEN='choose-a-long-token'
docker compose -f tools/dingcode/team-server/compose.yaml up --build -d
```

Without Docker, from `tools/dingcode/team-server`: `python3 dingcode_team_server.py`. Put Caddy or nginx in front for HTTPS and leave the Python process on `127.0.0.1`. Do not commit the token or certificates.

GitHub Actions (`.github/workflows/dingcode.yml`) runs the Python and page checks and builds the server image on Ubuntu, `dotnet build` on Windows, and `swiftc` on macOS.

## Annotating

`⌥⌘A` starts a session on the display under the pointer. The desktop stays live: the scroll wheel goes through to the app, hold ⌥ to click it, and `⌥⌘P` locks that click-through. Pins in a browser follow the element reported by the page bridge; other pins follow the Accessibility element when that permission is granted. B / C / Q set the selected pin to bug, change, or question. Esc writes JSON and a PNG taken at that moment. New pins start `open`. An agent can later mark one `ai-fixed`; a person confirms it on the team board.

## Auto-fix / 自动修复

Auto mode is on by default. After Send (Esc or 完成), the Mac app binds the target and runs a headless agent in that project. Turn it off in the menu (自动模式:关) and Send goes back to copying the handoff prompt.

The target is the page origin (`http://localhost:8090`) when a pin has a page URL, otherwise the window title, otherwise the app name. The first Send for an unbound target asks for a folder and stores it in `~/.dingcode/projects.json`.

```
python3 tools/dingcode/dingcode bind http://localhost:8090 ~/personal-hub
python3 tools/dingcode/dingcode bindings
python3 tools/dingcode/dingcode config engine claude
python3 tools/dingcode/dingcode config engine codex
python3 tools/dingcode/dingcode config auto off
python3 tools/dingcode/dingcode autofix ~/DingCode/notes/anno.json
```

The default engine is Claude Code: `claude -p "<prompt>" --permission-mode acceptEdits --allowedTools Read,Edit,Write,Glob,Grep --disallowedTools Bash,WebFetch,WebSearch`, run in the bound folder. Codex is `codex exec --sandbox workspace-write` with network access off (`sandbox_workspace_write.network_access=false`) in that folder. The menu item 引擎 switches them. Pin text is wrapped as annotation data, not as instructions. If a run changes a path outside the bound folder (including through a symlink), that round is reverted and marked failed. A Mac app does not inherit a login `PATH`; the CLI also looks in `~/.local/bin`, `/opt/homebrew/bin`, `~/.npm-global/bin`, and `~/.claude/local`. Set `DINGCODE_CLI` if the app cannot find `dingcode`.

The prompt carries the handoff rules, the note, and the screenshot paths. It tells the agent to edit only inside the bound folder, keep the change small, not refactor, not add a framework, address each pin by id, and finish with JSON: each pin id maps to `status` (`fixed`, `not-fixed`, or `unsure`), a one-line Chinese `summary_zh` (what changed, which file and line), and `files`. Before the agent runs, DingCode records the folder without stashing: a git repo keeps `HEAD` plus `git diff` and copies of already-dirty files; any other folder is copied. After the run the menu-bar icon is idle, running, done (waiting for you), or failed. The notification looks like `1 pin fixed, 1 not fixed`. The results window shows that Chinese line, before/after shots, and the diff (green added, red removed), with 打开文件, 确认修好, and 打回并再修 for the current pin. The session stays open until every pin is confirmed. Each round is stored in `~/.dingcode/runs/<session>/round-N/` (`summary.json`, `diff.patch`, screenshots). 撤回本轮 restores that round's pre-run files.

```
python3 tools/dingcode/dingcode result <session>
python3 tools/dingcode/dingcode revert <session> [round]
```

自动模式默认开启。在 Mac 上点发送（Esc 或「完成」）之后，DingCode 把当前目标绑到一个本地项目，并在那个目录里跑无头编程代理，不用再把提示词粘贴到对话框。菜单里关掉「自动模式」后，发送恢复成原来的复制交接提示。

目标优先用页面 origin（例如 `http://localhost:8090`），没有页面地址时用窗口标题，再没有就用 App 名。某个目标第一次发送时会弹出文件夹选择，并写进 `~/.dingcode/projects.json`。

默认引擎是 Claude Code（`claude -p`，`--permission-mode acceptEdits`，工具只允许 Read、Edit、Write、Glob、Grep，并禁止 Bash、WebFetch、WebSearch）。菜单「引擎」可以改成 Codex（`codex exec --sandbox workspace-write`，并且关闭网络）。两条命令都在绑定的项目目录里执行。钉子里的文字被包在数据块里，不当成指令。如果这一轮改到了绑定目录之外（含符号链接指出去的路径），DingCode 会撤回这一轮并标为失败。提示词要求：只改这个目录里的文件、改动尽量小、不重构、不加框架、按钉子 id 处理，并用 JSON 交回每颗钉子的 `status`（fixed / not-fixed / unsure）、一句中文 `summary_zh`（改了什么、哪个文件第几行）和 `files`。开跑前先记下目录现状，不用 stash：是 git 仓库就记下提交号和 `git diff`，并复制已经改过的文件；不是仓库就把文件复制下来。菜单栏图标分空闲、进行中、待确认、失败。通知类似 `1 pin fixed, 1 not fixed`。结果窗口按钉子显示这句中文、改前/改后截图、绿增红删的差异，可以打开文件、确认修好，或写一句说明只打回这一颗。全部确认后这一轮才算结束。每一轮保存在 `~/.dingcode/runs/<session>/round-N/`（summary.json、diff.patch、截图）。「撤回本轮」把项目恢复到这一轮开始之前。`dingcode result <session>` 查看结果，`dingcode revert <session> [round]` 撤回。

## Desktop ↔ page bridge

The desktop apps listen on `127.0.0.1:8763` only. A page that has loaded `anno.js` answers `elementFromPoint` so a desktop pin landing in a browser can record the DOM field. `GET /ping` returns the session token only when the request has no `Origin` (a local client) or the `Origin` is allowlisted: `chrome-extension://` plus `DINGCODE_EXTENSION_ID` (or `extension_id` in `~/.dingcode/config.json`), and the `http`/`https` keys in `~/.dingcode/projects.json` such as `http://localhost:8090`. The response echoes that origin. `Access-Control-Allow-Private-Network` is sent only for an allowlisted origin. Any other origin, including `https://evil.example` and `null`, gets 403 and no token. `/pending`, `/answer`, and `/voice` use the same check. `/voice` also requires the client id from `/ping`. Linux starts the same bridge with the session, or `python3 tools/dingcode/linux/dingcode_linux.py bridge`. Nothing else is contacted unless team upload is configured.

## Configuration / 配置

Clients stay local until you opt in. `~/DingCode/settings.json` is the switch. If `~/DingCode` does not exist and `~/DingAI` does, the directory is renamed once. Set `DINGCODE_*`. The same name with the `DINGAI_` prefix still works when the new one is unset. A project that already has `.dingai/` keeps that folder.

Local-only is the default, including when the file is missing. Folder mode:

```json
{ "mode": "folder", "share_dir": "/mnt/dingcode", "project": "inbox" }
```

Server mode:

```json
{ "mode": "server", "server_url": "http://127.0.0.1:8050", "token": "paste-the-token", "project": "inbox" }
```

A shared folder is one directory on a NAS or a synced drive. Each pin is its own file under `projects/<project>/pins/`, written via a temp file and rename, so two people can add pins without clobbering each other. Screenshots sit in `shots/`. The page layer cannot read that file; publishing is done by the desktop clients.

| Env var | Used by | Default |
|---|---|---|
| `DINGCODE_OUTPUT_DIR` (fallback `ANNO_OUTPUT_DIR`) | macOS, path relative to home; Windows, under the user profile | `DingCode` |
| `DINGCODE_MODE` | `local`, `folder`, or `server`. Overrides `settings.json` | `local` |
| `DINGCODE_SHARE_DIR` | shared-folder root | empty |
| `DINGCODE_TEAM_URLS` (fallback `ANNO_TEAM_URLS`) | team server URL. A value selects server mode when `DINGCODE_MODE` is unset | empty = no upload |
| `DINGCODE_TEAM_TOKEN` | bearer token for that server | empty |
| `DINGCODE_PROJECT_NAME` | board or folder project | `inbox` |
| `DINGCODE_LIVE` | Windows. `0` freezes the screenshot at the start | live |
| `DINGCODE_EXTENSION_ID` | Chrome extension id allowed to call the page bridge | unset |
| `DINGCODE_TEAM_HOST` / `DINGCODE_TEAM_PORT` (fallback `ANNO_TEAM_*`) | team server bind address | `127.0.0.1` / `8050` |
| `DINGCODE_TEAM_REQUIRE_AUTH` | `1` rejects anonymous upload. The Docker image sets this | off for a local process |
| `DINGCODE_TEAM_ADMIN_TOKEN` | first admin token. If unset, the process prints one random token once | unset |
| `DINGCODE_TEAM_ROOT` | SQLite, notes, and screenshots | `~/anno-team` |

## Handoff rules

Every clipboard export is a prompt: the handoff rules, then the JSON note. The note on disk keeps the same rules in `handoff_rules`. Edit them per project in `.dingcode/handoff-rules.md` (set `DINGCODE_PROJECT`, or put the project path in `~/DingCode/project.txt`). A user-wide file is `~/DingCode/handoff-rules.md`. On a page, set `window.DINGCODE_HANDOFF_RULES` or `localStorage['dingcode-handoff-rules']`.

```
python3 tools/dingcode/dingcode prompt notes/anno.json
python3 tools/dingcode/dingcode pins
python3 tools/dingcode/dingcode mark-fixed <note_id> <pin_id> verify.png
python3 tools/dingcode/dingcode mcp
```

`dingcode` is `handoff.py`. Older MCP tool names `dingai_handoff`, `dingai_list_pins`, and the other `dingai_*` calls still run.

`pins` and `mark-fixed` are also MCP tools (`dingcode_list_pins`, `dingcode_mark_fixed`). They read the shared folder or the team server from the settings above. Marking a pin fixed stores the PNG next to the pin. The handoff prompt stays the first MCP tool.

## MCP

`dingcode mcp` speaks MCP on stdio. A client that sends one JSON object per line (Claude Code, Codex, Cursor) gets newline-delimited replies. A client that sends `Content-Length` frames still gets that framing. Put `dingcode` on `PATH`, or call `python3 tools/dingcode/dingcode mcp`.

Claude Code:

```
claude mcp add -s user dingcode -- dingcode mcp
```

Codex (`~/.codex/config.toml`):

```
[mcp_servers.dingcode]
command = "dingcode"
args = ["mcp"]
```

Cursor (`~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "dingcode": {
      "command": "dingcode",
      "args": ["mcp"]
    }
  }
}
```

pi has no MCP client. This repo ships [skills/dingcode/SKILL.md](skills/dingcode/SKILL.md). Point pi at that skill and it uses the `dingcode` CLI (`prompt`, `pins`, `mark-fixed`, `scope`).

The defaults ask the coding agent for a minimal change, to follow the project's architecture file, to stay on the pinned element, to justify new dependencies, and to explain how the diff was verified.

After the agent marks the pin fixed, compare the tree with the snapshot taken at export:

```
python3 tools/dingcode/dingcode scope
```

The macOS and Windows menus have the same check (“检查本次改动”). Put the paths the pin should touch in `.dingcode/scope.txt`, one prefix per line. The check warns about other files, new dependencies or lockfiles, new top-level directories, and a diff over 400 lines or 8 files. Rejecting restores only those paths, and only while `HEAD` is still the snapshot. It does not reset commits. The page copy does not snapshot git; the desktop export and `handoff.py prompt` do.

## Release review

`handoff.py release open note.json` builds a review batch: each pin, the before and after shots cropped on the review page around the pin, the diff stat since the handoff baseline, the scope warnings, the commit SHAs, and the handoff rules. Approve or reject every pin before `release publish`. A rejected or unreviewed pin blocks publishing unless `DINGCODE_RELEASE_ADMIN=1` and `--override` gives a reason. That reason is stored on the release and in `releases/audit.jsonl`. The published record is read-only. `release search`, `release export <id> zip|markdown <dest>`, and `release rollback <id>` read it. Rollback points at the previous release and does not edit the archive. On the team board the same pages are under Releases. The server stores them in `<DINGCODE_TEAM_ROOT>/state`.

## Session collisions

`handoff.py session start` records the agent, repo, branch, pins, paths, and any services, ports, databases, or deploy targets. The same check runs when a prompt is built and when a pin is marked fixed. It warns, without stopping the handoff, about a shared repo and branch, overlapping paths, a pin claimed twice, a pin sent to the wrong project, a shared service or port or database or deploy target, and a working tree whose `HEAD` moved. `session choose <id> queue|isolate|hand|continue` queues the second session, makes a git worktree and branch, gives the pin to the session that already owns the area, or continues. Continue is written onto the session. Locks expire after four hours. `session end <id>` drops them and prints overlapping diffs. One user can keep this in `~/DingCode`. The team server stores the same records, and the board shows a yellow banner. The desktop clients read `~/DingCode/notices.json` and draw that banner. Set `DINGCODE_SESSIONS=0` to skip the automatic check.

## JSON contract

Desktop notes use `schema: "dingcode-desktop-v1"` and `tool: "dingcode"`. The field set matches the previous `anno-desktop-v1` contract (`schema_compat` records that name): `pins[].x_px` / `y_px` are screenshot pixels with a top-left origin, plus `window_nx` / `window_ny`, `ocr_nearby`, optional `note`, optional `window`, and optional `page` from the browser bridge. Optional `pin_type` is `bug` (the default), `change`, or `question`. Optional `status` is `open` (the default), `ai-fixed`, or `confirmed`. Arrows use `from_px` / `to_px`. Boxes use `rect_px` and an optional `shape`. Page export stays `version: 7.9` and stores `pinType` and `status` on each annotation.

## License

MIT
