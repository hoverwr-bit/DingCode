# DingCode Tutorial / 教程

A hands-on guide for a developer who found this repo. Every command, flag, path, and UI string below is copied from the code and docs in this repository (`README.md`, `tools/dingcode/ARCHITECTURE.md`, `tools/dingcode/docs/PRD.md`, `macos/DingCode.swift`, `core/bridge.py`, `core/runs_api.py`, `handoff.py`, `web/record/src/`). Steps that are implemented but not yet verified on real devices are marked **[Unverified / 未验证]** and collected at the end.

本指南面向在 GitHub 上找到本仓库的开发者。所有命令、参数、路径和界面文字都来自仓库里的代码与文档。已实现但未在真机上验证的步骤会标 **[Unverified / 未验证]**，并在文末汇总。

---

## 0. What you need / 需要什么

**English**

- **Python 3** — the CLI, MCP server, Python core (`core/`, `handoff.py`), the Linux client, and the team server use the Python standard library only. No `pip install`.
- **macOS build**: macOS 14+ and the Xcode command-line toolchain (`swiftc`). `macos/build.sh` compiles `DingCode.swift` with `-target $(uname -m)-apple-macos14.0` and links AppKit, Carbon, ScreenCaptureKit, Vision, UserNotifications, etc.
- **Windows build**: .NET SDK 8. `windows/DingCodeWin.csproj` targets `net8.0-windows10.0.19041` with `UseWPF` and `UseWindowsForms`.
- **node/npm** — only if you want to rebuild the record page UI. `web/record/dist/` ships prebuilt and is used at runtime; rebuild with `bash tools/dingcode/scripts/build-record.sh` (it runs `npm install` then `npm run build`).
- **Linux (optional)**: X11 or XWayland for the interactive toolbar; optional `grim` (Wayland still capture), `tesseract` (OCR), and the AT-SPI bus (anchors). `python3 tools/dingcode/linux/dingcode_linux.py --check` prints what is available.

**中文**

- **Python 3** — CLI、MCP 服务器、Python 核心（`core/`、`handoff.py`）、Linux 客户端和团队服务器只用标准库，无需 `pip install`。
- **macOS 构建**：macOS 14+ 和 Xcode 命令行工具（`swiftc`）。`macos/build.sh` 用 `-target $(uname -m)-apple-macos14.0` 编译 `DingCode.swift`，链接 AppKit、Carbon、ScreenCaptureKit、Vision、UserNotifications 等框架。
- **Windows 构建**：.NET SDK 8。`windows/DingCodeWin.csproj` 目标是 `net8.0-windows10.0.19041`，打开 `UseWPF` 和 `UseWindowsForms`。
- **node/npm** — 只在需要重新构建记录页时用。运行时用的是仓库里预构建好的 `web/record/dist/`；重建执行 `bash tools/dingcode/scripts/build-record.sh`（内部运行 `npm install` 和 `npm run build`）。
- **Linux（可选）**：交互工具栏需要 X11 或 XWayland；可选 `grim`（Wayland 静态截图）、`tesseract`（OCR）、AT-SPI 总线（控件锚点）。`python3 tools/dingcode/linux/dingcode_linux.py --check` 会打印哪些可用。

---

## 1. Get the code, run the tests / 拿代码，跑测试

**English**

```sh
git clone https://github.com/hoverwr-bit/DingCode.git
cd DingCode/tools/dingcode
python3 core/test_runs_api.py    # record-page bridge API (starts a real bridge on an ephemeral port)
python3 core/test_core.py        # schema, layout, sync, redact, …
python3 handoff_test.py          # CLI, MCP, autofix, scope, revert
```

`scripts/test.sh` also exists and runs `python3 -m unittest core.test_core handoff_test` from the package root (`cd tools/dingcode && sh scripts/test.sh`). The web annotation layer has its own node checks: `node web/anno-layout.test.js`, `node web/anno-source.test.js`, `node web/anno-i18n.test.js`, plus `node --check web/anno.js`. On GitHub Actions, `.github/workflows/dingcode.yml` runs the Python tests, the node checks, `dotnet build` on Windows, and `build.sh` on macOS.

**中文**

```sh
git clone https://github.com/hoverwr-bit/DingCode.git
cd DingCode/tools/dingcode
python3 core/test_runs_api.py    # 记录页桥 API（会在临时端口起一个真实 bridge）
python3 core/test_core.py        # 模式、标签布局、同步、脱敏等
python3 handoff_test.py          # CLI、MCP、自动修复、范围检查、撤回
```

仓库里还有 `scripts/test.sh`，它在包根目录运行 `python3 -m unittest core.test_core handoff_test`（`cd tools/dingcode && sh scripts/test.sh`）。网页批注层另有 node 检查：`node web/anno-layout.test.js`、`node web/anno-source.test.js`、`node web/anno-i18n.test.js`，以及 `node --check web/anno.js`。GitHub Actions 的 `.github/workflows/dingcode.yml` 会跑 Python 单测、node 检查、Windows 的 `dotnet build` 和 macOS 的 `build.sh`。

---

## 2. Build and start the app / 构建并启动

**English**

macOS (14+):

```sh
cd tools/dingcode/macos && ./build.sh
cp -R DingCode.app /Applications/        # run from tools/dingcode/macos
open /Applications/DingCode.app
```

`build.sh` signs with a local **DingCode Dev** identity when present, else **DingAI Dev**, else **AnnoOverlay Dev**, else ad-hoc. The first pin attempt asks for **Screen Recording** permission (System Settings → Privacy & Security → Screen Recording). The bundle id is `io.github.dingcode.mac` (`macos/Info.plist`); changing it means granting that permission again. DingCode is a menu-bar app — no Dock window.

Windows:

```sh
cd tools/dingcode/windows && dotnet build
```

Run the built `DingCode` executable; it lives in the tray. Linux: `python3 tools/dingcode/linux/dingcode_linux.py` (X11/XWayland).

The desktop apps write notes and screenshots under `~/DingCode` (`notes/`, `shots/`); set `DINGCODE_OUTPUT_DIR` (a path relative to your home directory; legacy fallback `ANNO_OUTPUT_DIR`) to move them. The Python tools (CLI, bridge, `data_home`) honor `DINGCODE_HOME` instead, which overrides both the `~/DingCode` data directory and the `~/.dingcode` config directory. Config and auto-fix runs live in `~/.dingcode`. If `~/DingCode` is missing and `~/DingAI` exists, it is renamed once.

**中文**

macOS（14+）：

```sh
cd tools/dingcode/macos && ./build.sh
cp -R DingCode.app /Applications/        # 在 tools/dingcode/macos 下执行
open /Applications/DingCode.app
```

`build.sh` 优先用本机 **DingCode Dev** 证书签名，其次 **DingAI Dev**、**AnnoOverlay Dev**，都没有就 ad-hoc。第一次打钉会请求「屏幕录制」权限（系统设置 → 隐私与安全性 → 屏幕录制）。Bundle id 是 `io.github.dingcode.mac`（`macos/Info.plist`）；改了它就要重新授权一次。DingCode 是菜单栏应用，没有 Dock 窗口。

Windows：

```sh
cd tools/dingcode/windows && dotnet build
```

运行编译出的 `DingCode` 可执行文件，它常驻托盘。Linux：`python3 tools/dingcode/linux/dingcode_linux.py`（X11/XWayland）。

桌面客户端把笔记和截图写到 `~/DingCode`（`notes/`、`shots/`）；可用 `DINGCODE_OUTPUT_DIR`（相对主目录的路径，旧回退 `ANNO_OUTPUT_DIR`）改到别处。Python 工具（CLI、桥、`data_home`）认的是 `DINGCODE_HOME`：它会同时覆盖 `~/DingCode` 数据目录和 `~/.dingcode` 配置目录。配置和自动修复的运行记录在 `~/.dingcode`。若 `~/DingCode` 不存在而 `~/DingAI` 存在，会把旧目录改名一次。

---

## 3. Who listens where: 8763 and 8764 / 端口与进程

**English**

- **macOS**: `DingCode.app` itself owns `127.0.0.1:8763` (`BridgeServer`, an `NWListener` in `DingCode.swift`). Port choice: `--port N` argument > `DINGCODE_APP_PORT` > 8763. This listener handles the pin-sync endpoints `/ping`, `/pending`, `/events`, `/answer`, `/track`, `/voice`.
  If the app can find `handoff.py` (`DINGCODE_CLI`, then an app-relative path, then `~/.local/bin`, `/opt/homebrew/bin`, `~/.npm-global/bin`, `~/.claude/local`, `/usr/local/bin`, then a login-shell `command -v dingcode`), it spawns an internal Python bridge: `handoff.py bridge --port 8764` (`--bridge-port N` > `DINGCODE_INTERNAL_PORT` > 8764), wrapped in a `/bin/sh` watchdog that kills the child if the app dies. The app then **forwards** `/app`, `/app/…` and `/api/…` from 8763 to that internal bridge, preserving Host and Origin; request bodies over 1 MiB get 413, responses over 32 MiB are dropped, more than 16 concurrent forwards get 503, and an unreachable upstream gives 502 (timeout 504). `/api/desktop` is answered 501 by the app itself.
- **Windows**: only the native `PageBridge` on `127.0.0.1:8763` (`/ping`, `/pending`, `/answer`, `/voice`). No forwarding, no 8764 — unless you start `handoff.py bridge` yourself.
- **Linux**: the session starts `core/bridge.py` on `127.0.0.1:8763`; you can also run `python3 tools/dingcode/linux/dingcode_linux.py bridge`.
- **Standalone Python bridge**: `python3 -m core.bridge [--port N]` or `python3 handoff.py bridge [--port N]`. Default port: `DINGCODE_BRIDGE_PORT`, else `port` in `~/.dingcode/config.json`, else 8763.

The record page (section 6) is served by the **Python** bridge at `/app/`, so through the Mac app you use `http://127.0.0.1:8763/app/` (forwarded); direct to a standalone bridge it is whatever port you gave it.

**中文**

- **macOS**：`DingCode.app` 自己占 `127.0.0.1:8763`（`DingCode.swift` 里的 `BridgeServer`，`NWListener`）。端口优先级：命令行 `--port N` > `DINGCODE_APP_PORT` > 8763。这个监听负责钉子同步的 `/ping`、`/pending`、`/events`、`/answer`、`/track`、`/voice`。
  如果 App 能找到 `handoff.py`（顺序：`DINGCODE_CLI`、App 相对路径、`~/.local/bin`、`/opt/homebrew/bin`、`~/.npm-global/bin`、`~/.claude/local`、`/usr/local/bin`，最后登录 shell 的 `command -v dingcode`），就会再拉一个内部 Python 桥：`handoff.py bridge --port 8764`（优先级 `--bridge-port N` > `DINGCODE_INTERNAL_PORT` > 8764），外面包了一层 `/bin/sh` 看护，App 被杀时 1 秒内带走 python。App 会把 `/app`、`/app/…`、`/api/…` 从 8763 **原样转发**到内部桥（保留 Host 和 Origin）：请求体超 1 MiB 返回 413，响应超 32 MiB 丢弃，并发超 16 返回 503，上游连不上 502（超时 504）。`/api/desktop` 由 App 自己回 501。
- **Windows**：只有原生 `PageBridge` 监听 `127.0.0.1:8763`（`/ping`、`/pending`、`/answer`、`/voice`）。没有转发，也没有 8764 —— 除非你自己启动 `handoff.py bridge`。
- **Linux**：会话会在 `127.0.0.1:8763` 启动 `core/bridge.py`；也可单独运行 `python3 tools/dingcode/linux/dingcode_linux.py bridge`。
- **独立 Python 桥**：`python3 -m core.bridge [--port N]` 或 `python3 handoff.py bridge [--port N]`。默认端口：`DINGCODE_BRIDGE_PORT`，否则 `~/.dingcode/config.json` 的 `port`，否则 8763。

记录页（第 6 节）由 **Python** 桥在 `/app/` 提供，所以经 Mac App 访问是 `http://127.0.0.1:8763/app/`（转发过去）；直连独立桥就是你启动时给的端口。

---

## 4. Place pins, write a note / 打钉、写笔记

**English**

macOS: press **⌥⌘A** (menu item 「DingCode 开始批注  ⌥⌘A」) on the display under the pointer. The overlay is click-through by default: the scroll wheel reaches the app underneath, hold **⌥** to click it, and **⌥⌘P** (「交互穿透  ⌥⌘P」) locks that mode. Click to drop a pin, drag for an arrow/box, ⌘Z undoes the last item. Press **B / C / Q** to set the next pin's type: `bug`, `change`, `question`. A pin opens a note field (「输入文字，回车确认，Esc 取消」— Return confirms, Esc skips). Press **Esc** or the toolbar button 「完成✓」to finish. **At that moment** the app captures the screen, so pin pixel coordinates match the PNG, and writes:

- the note JSON: `~/DingCode/notes/<note id>.json`
- the screenshot: `~/DingCode/shots/`

The note uses `schema: "dingcode-desktop-v1"`, `tool: "dingcode"`. Each entry in `pins[]` carries `id`, `x_px`/`y_px` (screenshot pixels, top-left origin), `ocr_nearby`, optional `note`, optional `window` `{owner, title}`, `window_nx`/`window_ny`, optional `page` (the DOM element reported by a browser running the page bridge), optional `source` on a dev build. Optional `pin_type` is `bug` (default), `change`, `question`; optional `status` is `open` (default), `ai-fixed`, `confirmed`. `arrows[]` use `from_px`/`to_px`; `boxes[]` use `rect_px` and optional `shape` (`rect`, `ellipse`, `spotlight`).

Windows: **Ctrl+Alt+A** starts the live session (hold **Alt** to click underneath; `DINGCODE_LIVE=0` freezes the screenshot first, as the older build did). Same B / C / Q and Esc flow, same JSON fields. Linux: press **p** then click to pin, **a** / **r** / **s** plus two clicks for arrow / box / spotlight, **Esc** exports under `~/DingCode/linux`.

**中文**

macOS：在指针所在的屏幕按 **⌥⌘A**（菜单项「DingCode 开始批注  ⌥⌘A」）。叠层默认点击穿透：滚轮直达下层应用，按住 **⌥** 可点击下层，**⌥⌘P**（「交互穿透  ⌥⌘P」）锁定该模式。单击落钉，拖拽画箭头/框，⌘Z 撤销上一笔。按 **B / C / Q** 把下一颗钉的类型设为 `bug`、`change`、`question`。落钉会出现备注框（「输入文字，回车确认，Esc 取消」）。按 **Esc** 或工具栏的「完成✓」结束。**此时**才截屏，所以钉子的像素坐标与 PNG 一致，并写出：

- 笔记 JSON：`~/DingCode/notes/<笔记 id>.json`
- 截图：`~/DingCode/shots/`

笔记用 `schema: "dingcode-desktop-v1"`、`tool: "dingcode"`。`pins[]` 每项含 `id`、`x_px`/`y_px`（截图像素，左上角原点）、`ocr_nearby`、可选 `note`、可选 `window` `{owner, title}`、`window_nx`/`window_ny`、可选 `page`（浏览器页桥报告的 DOM 元素）、开发构建下可选 `source`。可选 `pin_type` 为 `bug`（默认）、`change`、`question`；可选 `status` 为 `open`（默认）、`ai-fixed`、`confirmed`。`arrows[]` 用 `from_px`/`to_px`；`boxes[]` 用 `rect_px` 加可选 `shape`（`rect`、`ellipse`、`spotlight`）。

Windows：**Ctrl+Alt+A** 开始实时会话（按住 **Alt** 点击下层；`DINGCODE_LIVE=0` 则先冻住截图）。B / C / Q、Esc 流程和 JSON 字段与 Mac 相同。Linux：按 **p** 后点击落钉，**a** / **r** / **s** 加两次点击画箭头 / 框 / 聚光，**Esc** 导出到 `~/DingCode/linux`。

---

## 5. Hand off to an agent / 交接给代理

**English**

`dingcode` is `handoff.py`: `tools/dingcode/dingcode` is a one-line shell wrapper around `python3 handoff.py`. Everything below can also be typed as `python3 tools/dingcode/dingcode …`.

```sh
python3 tools/dingcode/dingcode prompt <note.json>   # handoff prompt (rules + note JSON) to stdout
```

MCP setup (the server is `dingcode mcp` on stdio; newline-delimited JSON, or Content-Length frames for older clients):

- Claude Code: `claude mcp add -s user dingcode -- dingcode mcp`
- Codex: in `~/.codex/config.toml` — `[mcp_servers.dingcode]`, `command = "dingcode"`, `args = ["mcp"]`
- Cursor: in `~/.cursor/mcp.json` — `"mcpServers": { "dingcode": { "command": "dingcode", "args": ["mcp"] } }`

Tools: `dingcode_handoff` (first tool), `dingcode_list_pins`, `dingcode_mark_fixed` (accepts a verification PNG), `dingcode_scope_check`, `dingcode_reject`. Old `dingai_*` names still route to the new tools.

CLI equivalents and the auto-fix chain:

```sh
python3 tools/dingcode/dingcode mark-fixed <note_id> <pin_id> [verify.png]
python3 tools/dingcode/dingcode scope        # diff working tree vs .dingcode/last-handoff.json
python3 tools/dingcode/dingcode reject       # restore out-of-scope paths (HEAD unchanged only)
python3 tools/dingcode/dingcode bind <target> <folder>
python3 tools/dingcode/dingcode config engine claude|codex
python3 tools/dingcode/dingcode config auto on|off
python3 tools/dingcode/dingcode autofix <note.json|session> [--round N] [--feedback text] [--pin id]
python3 tools/dingcode/dingcode result <session>
python3 tools/dingcode/dingcode revert <session> [round]
```

Auto-fix runs the engine headless in the bound folder: Claude Code via `claude -p … --permission-mode acceptEdits --allowedTools Read,Edit,Write,Glob,Grep --disallowedTools Bash,WebFetch,WebSearch`, Codex via `codex exec --sandbox workspace-write` with network access off. Max 3 rounds per session; an unbound target exits with code 3. Each round lands in `~/.dingcode/runs/<session>/round-N/` (`summary.json`, `diff.patch`, `manifest.json`, `before.png`/`after.png`); the session's `status.json`, `prompt.md`, `note.json`, `log.txt` sit in `~/.dingcode/runs/<session>/`. The session id is the note filename without extension. The macOS app's 「自动模式:开/关」menu item and `config auto on|off` control the same switch.

**中文**

`dingcode` 就是 `handoff.py`：`tools/dingcode/dingcode` 是一行 shell 包装，等价于 `python3 handoff.py`。下面的命令也可以写成 `python3 tools/dingcode/dingcode …`。

```sh
python3 tools/dingcode/dingcode prompt <note.json>   # 交接提示词（规则 + 笔记 JSON）打到 stdout
```

MCP 接入（服务器是 `dingcode mcp`，走 stdio；换行分隔 JSON，老客户端仍可用 Content-Length 帧）：

- Claude Code：`claude mcp add -s user dingcode -- dingcode mcp`
- Codex：`~/.codex/config.toml` 里加 `[mcp_servers.dingcode]`，`command = "dingcode"`，`args = ["mcp"]`
- Cursor：`~/.cursor/mcp.json` 里加 `"mcpServers": { "dingcode": { "command": "dingcode", "args": ["mcp"] } }`

工具：`dingcode_handoff`（第一个工具）、`dingcode_list_pins`、`dingcode_mark_fixed`（可附验证截图）、`dingcode_scope_check`、`dingcode_reject`。旧名 `dingai_*` 仍转到新工具。

CLI 等价命令和自动修复链：

```sh
python3 tools/dingcode/dingcode mark-fixed <note_id> <pin_id> [verify.png]
python3 tools/dingcode/dingcode scope        # 工作区与 .dingcode/last-handoff.json 对比
python3 tools/dingcode/dingcode reject       # 还原越界路径（仅 HEAD 未动时）
python3 tools/dingcode/dingcode bind <目标> <目录>
python3 tools/dingcode/dingcode config engine claude|codex
python3 tools/dingcode/dingcode config auto on|off
python3 tools/dingcode/dingcode autofix <note.json|session> [--round N] [--feedback text] [--pin id]
python3 tools/dingcode/dingcode result <session>
python3 tools/dingcode/dingcode revert <session> [round]
```

自动修复在绑定的目录里无头运行引擎：Claude Code 用 `claude -p … --permission-mode acceptEdits --allowedTools Read,Edit,Write,Glob,Grep --disallowedTools Bash,WebFetch,WebSearch`；Codex 用 `codex exec --sandbox workspace-write` 且关网络。每个会话最多 3 轮；目标未绑定退出码 3。每轮落在 `~/.dingcode/runs/<session>/round-N/`（`summary.json`、`diff.patch`、`manifest.json`、`before.png`/`after.png`）；会话级 `status.json`、`prompt.md`、`note.json`、`log.txt` 在 `~/.dingcode/runs/<session>/`。会话 id 是笔记文件名去掉扩展名。Mac 菜单的「自动模式:开/关」和 `config auto on|off` 是同一个开关。

---

## 6. The per-pin record page / 记录页

**English**

The page is the prebuilt Vue 3 SPA in `web/record/dist`, served by the Python bridge under `/app` and `/app/*` (`vite.config.mts` sets `base: "/app/"`; there is no client-side router — `App.vue` switches on the hash). Through the macOS app: **`http://127.0.0.1:8763/app/`** (forwarded to the internal bridge on 8764). Direct to a standalone bridge: `http://127.0.0.1:<port>/app/`, e.g. 8764. The setup page also shows the exact URL (「记录页地址」).

On first open, if `~/.dingcode/config.json` has no `setup_done: true`, the app forces `#/setup` (section 8). Otherwise you land on the session list (`SessionList.vue`), fed by `GET /api/sessions`; click a row to open `SessionDetail.vue`, which merges pins and rounds via `GET /api/runs/{sid}`.

Authentication: the page calls **`GET /api/session`**, which mints a `client` (integer) and `token` (string) — the same minting as `GET /ping`, and only reachable from the page itself (loopback Host + same-origin) or a local no-Origin client. The page caches one pair for its lifetime and sends `client` + `token` in every write. Reads need no token; **POST writes additionally require the page's own origin** — a request with no `Origin` header is read-only by design (the CLI is the no-Origin write path).

**中文**

记录页是 `web/record/dist` 里预构建的 Vue 3 SPA，由 Python 桥在 `/app` 和 `/app/*` 下提供（`vite.config.mts` 设置了 `base: "/app/"`；没有前端路由 —— `App.vue` 按 hash 切换）。经 macOS App 访问：**`http://127.0.0.1:8763/app/`**（转发到 8764 的内部桥）。直连独立桥：`http://127.0.0.1:<端口>/app/`，例如 8764。设置页也会显示这个地址（「记录页地址」）。

首次打开时，若 `~/.dingcode/config.json` 里没有 `setup_done: true`，页面会强制进入 `#/setup`（见第 8 节）。否则落在会话列表（`SessionList.vue`），数据来自 `GET /api/sessions`；点一行进入 `SessionDetail.vue`，由 `GET /api/runs/{sid}` 合并钉子与轮次。

鉴权：页面调 **`GET /api/session`** 换取 `client`（整数）和 `token`（字符串）—— 与 `GET /ping` 同一套发放逻辑，且只允许页面自身（回环 Host + 同源）或无 Origin 的本机客户端访问。页面整个生命周期缓存一对凭据，每次写操作都带上 `client` 和 `token`。读不需要 token；**POST 写入还要求页面自身 Origin** —— 无 `Origin` 头的请求按设计只读（CLI 才是无 Origin 的写通道）。

---

## 7. Edit, re-run, revert a single pin / 改批注、重跑、逐颗撤回

**English**

All three write endpoints are POSTs under `/api/runs/{sid}/pins/{pid}/…` and require the body fields `client` + `token` (from `/api/session`) and `confirm` equal to the pin id. UI strings come from `PinCard.vue` (the page is Chinese today).

- **Edit the note** — button 「编辑批注」, then 「保存批注」(「取消」 aborts). `POST …/note` with `{note, confirm: pid}`. The note is capped at 2000 chars, must be a string, and is written **into the source note JSON** under `~/DingCode/notes/` atomically (temp file + `os.replace`, no `.bak`). If another process holds the file, you get `409 "note file busy"`. `runs/note.json` in the runs directory is not rewritten.
- **Re-run this pin** — button 「重跑这颗」 with an optional 「重跑反馈（可选）」 input. The first click turns the button into 「确认重跑？」; the second fires `POST …/rerun` `{confirm: pid, feedback?}`. The server checks the session isn't already `running` (else `409 "a run is already in progress"`) and the pin isn't `confirmed` (else `400 "pin already confirmed"`), then spawns `handoff.py autofix <session> --round N+1 --pin <pid> [--feedback …]` in the background and returns the round number immediately; the page polls `status.json`. Feedback is capped at 1000 chars.
- **Revert this pin** — button 「撤回这颗」→「确认撤回？」→「已撤回」. `POST …/revert` `{confirm: pid}` calls `handoff.revert_pin`. It targets the pin's **latest non-reverted pin-only round** and does a three-way merge:
  - Fast path: if the file on disk is byte-identical to the round's `post` sha256, write back the `pre` copy (or delete the file if it was new).
  - Otherwise `git merge-file` merges (current, post, base). **Any conflict in any file aborts the whole revert with `409 {"error": "merge conflict", "conflicts": […], "round": N}` — nothing on disk changes.** The page then says: 「撤回冲突：后续轮次改动了相同区域…请先重跑这颗钉，或使用整轮回滚。」
  - Other failures: `404` with `"no pin-only round to revert for pin …"` (the pin was only ever fixed in a full round), `409` for a missing folder or missing per-pin snapshot.
  - After a successful revert, later pin-only rounds for the same pin are flagged `stale` (「基于已撤回的修改，建议重跑」), and the round is marked `reverted` (「已撤回」).

Whole-round revert stays on the CLI: `dingcode revert <session> [round]`. `dingcode result <session>` prints the summary.

**中文**

三个写接口都是 `/api/runs/{sid}/pins/{pid}/…` 下的 POST，请求体必须带 `client` + `token`（来自 `/api/session`）和等于钉子 id 的 `confirm`。界面文字来自 `PinCard.vue`（页面目前是中文）。

- **改批注** — 按钮「编辑批注」，然后「保存批注」（「取消」放弃）。`POST …/note`，body `{note, confirm: pid}`。批注上限 2000 字，必须是字符串，**原子写入 `~/DingCode/notes/` 下的源笔记 JSON**（临时文件 + `os.replace`，无 `.bak`）。文件被别的进程占用时返回 `409 "note file busy"`。runs 目录里的 `runs/note.json` 不会被改。
- **重跑这颗** — 按钮「重跑这颗」加可选输入「重跑反馈（可选）」。第一次点击变成「确认重跑？」，第二次才发 `POST …/rerun`（body `{confirm: pid, feedback?}`）。服务端先查会话不在 `running`（否则 `409 "a run is already in progress"`）、钉子不是 `confirmed`（否则 `400 "pin already confirmed"`），然后后台拉起 `handoff.py autofix <session> --round N+1 --pin <pid> [--feedback …]`，立即返回轮号；页面轮询 `status.json`。反馈上限 1000 字。
- **撤回这颗** — 按钮「撤回这颗」→「确认撤回？」→「已撤回」。`POST …/revert`（body `{confirm: pid}`）调用 `handoff.revert_pin`，目标是这颗钉**最新一个未撤回的 pin_only 轮**，做三方合并：
  - 快路径：磁盘字节等于该轮 `post` 的 sha256，直接写回 `pre` 副本（新文件则删除）。
  - 否则用 `git merge-file` 对（当前、post、base）三方合并。**任何一个文件冲突就整体放弃，返回 `409 {"error": "merge conflict", "conflicts": […], "round": N}`，磁盘零改动。** 页面提示：「撤回冲突：后续轮次改动了相同区域…请先重跑这颗钉，或使用整轮回滚。」
  - 其他失败：`404`，错误 `"no pin-only round to revert for pin …"`（这颗钉只在整轮里修过）；目录丢失或缺单钉快照返回 `409`。
  - 撤回成功后，同一颗钉更晚的 pin_only 轮会被标 `stale`（「基于已撤回的修改，建议重跑」），该轮标 `reverted`（「已撤回」）。

整轮撤回仍在 CLI：`dingcode revert <session> [round]`。`dingcode result <session>` 打印摘要。

---

## 8. First-run setup page / 首次设置页

**English**

`#/setup` (`SetupView.vue`), reached automatically on first open or via the 「设置」 link. One 「保存设置」 button writes `dispatch`, `engine`, `engine_path`, `port`, `setup_done: true` via `POST /api/config` (`confirm: "config"`); these land in `~/.dingcode/config.json`.

- **派活方式** (`dispatch`): 「自动派给 CLI」(`auto`) runs the engine on 完成 when the target is bound; 「复制提示词，我手动派」(`manual`) only copies the handoff prompt.
- **执行工具** (`engine`): a select with `claude` / `codex`, plus 「自定义命令路径」(`engine_path`) — an absolute path (supports `~`), which must be an **existing file** or the API rejects it (`400 "engine_path must be an existing file"`). Leave empty for the default command.
- **项目绑定** (`GET`/`POST /api/projects`, `confirm: "projects"`): maps a target (app name or URL, e.g. `http://localhost:8090`) to a code folder. The folder must be an existing absolute directory. The table shows 「目录不存在」/「目录存在」 plus `· git` / `· 非 git 仓库`; rows can be 「编辑」(fills the form back) and 「删除」. Same-name save = update (「更新绑定」).
- **项目提示规则（handoff-rules.md）**: per-project rules read/written via `GET`/`POST /api/projects/{name}/rules` (`confirm` = project name). Saving an empty string deletes the project file, falling back to the default rules.
- **记录页地址** (`app_url` from `GET /api/config`) and **端口** (`port`; `0` = default. The hint reads 「0 = 默认端口；改完保存，重启 DingCode 后生效。」).

`GET /api/config` returns the merged config plus `app_url`; when the request came through the app's public port the URL points back at `http://127.0.0.1:8763/app/`.

**中文**

`#/setup`（`SetupView.vue`），首次打开自动进入，或点「设置」链接。一个「保存设置」按钮把 `dispatch`、`engine`、`engine_path`、`port`、`setup_done: true` 一起 `POST /api/config`（`confirm: "config"`），写进 `~/.dingcode/config.json`。

- **派活方式**（`dispatch`）：「自动派给 CLI」（`auto`）——目标已绑定时点完成后直接跑引擎；「复制提示词，我手动派」（`manual`）——只复制交接提示词。
- **执行工具**（`engine`）：下拉选 `claude` / `codex`，加「自定义命令路径」（`engine_path`）—— 绝对路径（支持 `~`），必须是**已存在的文件**，否则接口拒绝（`400 "engine_path must be an existing file"`）。留空用默认命令。
- **项目绑定**（`GET`/`POST /api/projects`，`confirm: "projects"`）：把目标（应用名或网址，如 `http://localhost:8090`）映射到代码目录，目录必须是已存在的绝对路径。表格显示「目录不存在」/「目录存在」和 `· git` / `· 非 git 仓库`；每行可「编辑」（填回表单）和「删除」。同名保存即更新（「更新绑定」）。
- **项目提示规则（handoff-rules.md）**：通过 `GET`/`POST /api/projects/{name}/rules` 读写（`confirm` = 项目名）。存空字符串等于删掉项目文件，落回默认规则。
- **记录页地址**（`app_url`，来自 `GET /api/config`）和**端口**（`port`；`0` = 默认。提示原文：「0 = 默认端口；改完保存，重启 DingCode 后生效。」）。

`GET /api/config` 返回合并后的配置加 `app_url`；请求经 App 公开端口转发来时，地址指回 `http://127.0.0.1:8763/app/`。

---

## 9. Windows notes / Windows 说明

**English**

- Hotkey **Ctrl+Alt+A** starts the live session; hold **Alt** to click the app underneath. `DINGCODE_LIVE=0` freezes the screenshot at the start instead.
- Tray menu items (from `Program.cs`): 「DingCode 开始批注  Ctrl+Alt+A」, 「检查本次改动」, 「导出 GitHub Issue」, 「退出」; double-clicking the tray icon toggles a session.
- The Windows bridge serves `/ping`, `/pending`, `/answer`, `/voice` on `127.0.0.1:8763` — no `/events`/`/track`, and `/pending` always returns `{"seq": 0, "requests": []}`.
- Smoke test: `powershell -ExecutionPolicy Bypass -File windows\test-record.ps1 [-Python C:\path\python.exe] [-Port 8764]` — runs the three Python suites (`core\test_runs_api.py`, `core\test_core.py`, `handoff_test.py`), starts `handoff.py bridge --port 8764`, and checks `GET /app/` (looks for `id="app"` and `/app/assets/`) and `GET /api/sessions`. The script sets `PYTHONIOENCODING=utf-8` and `PYTHONUTF8=1` because the tests assert Chinese text; it is kept pure ASCII because Windows PowerShell 5.1 reads a BOM-less `.ps1` as ANSI and Chinese comments then break the parser. In your own PowerShell, `chcp 65001` / `$OutputEncoding` matter the same way when piping Chinese output.
- PRD status: the project compiled with .NET SDK 8.0.425 on a test machine and native `GET /ping` was verified there (F40/F10); the tray and overlay UI are marked 未实测 — nobody has clicked through them on a real Windows device. The native `/pending`/`/answer`/`/voice` trio was not exercised individually either.

**中文**

- 热键 **Ctrl+Alt+A** 开始实时会话；按住 **Alt** 点击下层应用。`DINGCODE_LIVE=0` 则开始时就冻住截图。
- 托盘菜单项（来自 `Program.cs`）：「DingCode 开始批注  Ctrl+Alt+A」、「检查本次改动」、「导出 GitHub Issue」、「退出」；双击托盘图标开始/结束一次会话。
- Windows 桥在 `127.0.0.1:8763` 提供 `/ping`、`/pending`、`/answer`、`/voice` —— 没有 `/events`/`/track`，且 `/pending` 恒返回 `{"seq": 0, "requests": []}`。
- 冒烟测试：`powershell -ExecutionPolicy Bypass -File windows\test-record.ps1 [-Python C:\path\python.exe] [-Port 8764]` —— 跑三个 Python 套件（`core\test_runs_api.py`、`core\test_core.py`、`handoff_test.py`），启动 `handoff.py bridge --port 8764`，检查 `GET /app/`（找 `id="app"` 和 `/app/assets/`）和 `GET /api/sessions`。脚本设置了 `PYTHONIOENCODING=utf-8` 和 `PYTHONUTF8=1`，因为测试断言中文文本；脚本本身保持纯 ASCII，因为 Windows PowerShell 5.1 会把无 BOM 的 `.ps1` 当 ANSI 读，中文注释会让解析器报错。你自己在 PowerShell 里管道传中文时，`chcp 65001` / `$OutputEncoding` 同理需要注意。
- PRD 状态：项目在测试机上用 .NET SDK 8.0.425 编译过、原生 `GET /ping` 验证过（F40/F10）；托盘和叠层界面标为未实测 —— 没人在真机上点过。原生 `/pending`/`/answer`/`/voice` 三条也没有逐条打过。

---

## 10. Troubleshooting / 排障

**English**

- **Port conflicts (8763/8764).** See who holds a port: `lsof -i :8763` (and `lsof -i :8764`). On macOS, if 8763 is taken the app logs `anno-bridge: port 8763 unavailable, bridge disabled` and pinning works without the page bridge; a standalone Python bridge prints the `OSError` (`bridge: …`) and exits 1. You can move either side: the app's public port via `--port`/`DINGCODE_APP_PORT`, the internal bridge via `--bridge-port`/`DINGCODE_INTERNAL_PORT`, the standalone bridge via `dingcode bridge --port N`, `DINGCODE_BRIDGE_PORT`, or `port` in `~/.dingcode/config.json` (0 resets to default; restart to apply).
- **403 / "bad client or token" on a write.** The body must be a JSON object; `client` must be the integer minted by `/api/session` (or `/ping`), `token` the matching string, and `confirm` must equal the target id (`client_ok` compares both against the server's state). The macOS app's `/answer` additionally requires `reqId` to be a JSON integer. Writes also require the page's own origin — a request with no `Origin` header gets `403 "self origin required"` (by design: use the CLI instead).
- **403 `forbidden` on `/ping` or the `/api/*` surface.** Origin rules: a request with no `Origin` counts as a local CLI client; `Origin: null`, `*`, or any non-allowlisted origin is denied and the body contains no token. Allowlisted origins are the configured Chrome extension id (`DINGCODE_EXTENSION_ID` or `extension_id` in `~/.dingcode/config.json`, 32 chars `a`–`p`) and the `http(s)` keys under `bindings` in `~/.dingcode/projects.json`. `/api/*` and `/app/*` additionally require a loopback `Host` — `127.0.0.1:<port>` or `localhost:<port>` on either the bridge's own port or the app's public port 8763; anything else is 403. Loopback origins on those two ports count as "self" (the page itself).
- **502 from `http://127.0.0.1:8763/api/config` (or any `/api/`, `/app/` path).** The macOS app forwards those paths to the internal bridge on 8764; if the Python bridge isn't running (e.g. `handoff.py` wasn't found — the app then logs `dingcode: handoff.py not found, /app forwarding disabled` and sets `forwardEnabled = false`, or the child died), the forward fails with 502 (504 on timeout). Fix: make sure `dingcode`/`handoff.py` is findable (`DINGCODE_CLI` helps) and restart the app.
- **Screen Recording permission lost after a rebuild.** The stable signing identity keeps the TCC grant; ad-hoc signing drifts every rebuild. `build.sh` prefers **DingCode Dev**, then DingAI Dev / AnnoOverlay Dev; if you ended up ad-hoc, or changed the bundle id to `io.github.dingcode.mac` variants, re-grant the permission in System Settings.
- **Windows PowerShell encoding.** Chinese test output needs UTF-8: `windows/test-record.ps1` sets `PYTHONIOENCODING=utf-8` / `PYTHONUTF8=1` for child processes, and the script itself must stay ASCII-only for PowerShell 5.1. If you see mojibake, check the console code page (`chcp 65001`).

**中文**

- **端口冲突（8763/8764）。** 查看谁占用：`lsof -i :8763`（和 `lsof -i :8764`）。macOS 上 8763 被占时，App 记录 `anno-bridge: port 8763 unavailable, bridge disabled`，打钉照常、只是没有页桥；独立 Python 桥会打印 `OSError`（`bridge: …`）并以退出码 1 结束。两边都可以换端口：App 公开端口用 `--port`/`DINGCODE_APP_PORT`，内部桥用 `--bridge-port`/`DINGCODE_INTERNAL_PORT`，独立桥用 `dingcode bridge --port N`、`DINGCODE_BRIDGE_PORT` 或 `~/.dingcode/config.json` 的 `port`（0 = 回默认，重启生效）。
- **写入返回 403 / "bad client or token"。** body 必须是 JSON 对象；`client` 必须是 `/api/session`（或 `/ping`）发放的整数，`token` 是配对字符串，`confirm` 必须等于目标 id（服务端用 `client_ok` 校验）。macOS App 的 `/answer` 还要求 `reqId` 是 JSON 整数。写入还要求页面自身 Origin —— 无 `Origin` 头的请求得到 `403 "self origin required"`（设计如此：请改用 CLI）。
- **`/ping` 或 `/api/*` 返回 403 `forbidden`。** Origin 规则：无 `Origin` 头视为本机 CLI；`Origin: null`、`*` 或不在白名单的一律拒绝，正文不含 token。白名单是配置的 Chrome 扩展 id（`DINGCODE_EXTENSION_ID` 或 `~/.dingcode/config.json` 的 `extension_id`，32 位 `a`–`p`）和 `~/.dingcode/projects.json` 里 `bindings` 的 `http(s)` 键。`/api/*` 和 `/app/*` 还要求 `Host` 是回环 —— 桥自身端口或 App 公开端口 8763 上的 `127.0.0.1:<port>` / `localhost:<port>`，其余 403。这两个端口上的回环 Origin 视为 "self"（页面本身）。
- **`http://127.0.0.1:8763/api/config`（或任何 `/api/`、`/app/` 路径）返回 502。** macOS App 把这些路径转发到 8764 的内部桥；如果 Python 桥没起来（比如没找到 `handoff.py` —— App 会记 `dingcode: handoff.py not found, /app forwarding disabled` 并置 `forwardEnabled = false`；或子进程退出了），转发就 502（超时 504）。修复：确保能找到 `dingcode`/`handoff.py`（可设 `DINGCODE_CLI`），重启 App。
- **重编译后「屏幕录制」权限丢了。** 稳定的签名身份能保住 TCC 授权；ad-hoc 每次重编译身份都变。`build.sh` 优先 **DingCode Dev**，其次 DingAI Dev / AnnoOverlay Dev；如果落到 ad-hoc，或改了 bundle id `io.github.dingcode.mac`，需要到系统设置里重新授权。
- **Windows PowerShell 编码。** 中文测试输出需要 UTF-8：`windows/test-record.ps1` 给子进程设置了 `PYTHONIOENCODING=utf-8` / `PYTHONUTF8=1`，脚本本身必须保持纯 ASCII（PowerShell 5.1）。看到乱码先查控制台代码页（`chcp 65001`）。

---

## Unverified items / 未验证事项

Marked **[Unverified / 未验证]** above or worth calling out. Source: `docs/PRD.md` (feature table F01–F42, status vocabulary 已实测/已完成/未实测/未做) and what cannot be confirmed from code alone.

上文标注 **[Unverified / 未验证]** 或需要特别说明的事项。依据是 `docs/PRD.md`（功能表 F01–F42，状态词 已实测/已完成/未实测/未做）以及仅凭代码无法确认的部分。

1. **macOS overlay, menu-bar icon states, system notifications, and the result window** (确认修好 / 打回并再修 / 打开文件 / 撤回本轮, F01, F16–F18, F29): implemented in `DingCode.swift`, PRD marks them 未实测 — never clicked through on a real Mac.
   **macOS 叠层、菜单栏图标状态、系统通知、结果窗口**（确认修好 / 打回并再修 / 打开文件 / 撤回本轮，F01、F16–F18、F29）：代码在 `DingCode.swift`，PRD 标未实测。
2. **The folder picker on the first Send for an unbound target** (F13, partial): the headless bind/auto-fix path is 已实测, the picker UI is not.
   **未绑定目标第一次发送时弹出的文件夹选择面板**（F13 部分）：无头绑定/自动修复路径已实测，弹窗界面未实测。
3. **macOS `/app` + `/api` forwarding end-to-end on a real device**: implemented in `DingCode.swift` (forward, 1 MiB / 32 MiB / 16-connection caps, 502/503/504) and covered by Python unit/subprocess tests, but no PRD real-device acceptance of the full `8763 → 8764` path in a browser.
   **macOS `/app` + `/api` 转发的真机端到端**：转发与上限（1 MiB / 32 MiB / 16 并发、502/503/504）在 `DingCode.swift` 实现，Python 有单测/子进程测试，但没有 PRD 层面在真机浏览器里对 `8763 → 8764` 全链路的验收。
4. **The record page UI on a real browser** (`web/record`): the API layer is covered by `core/test_runs_api.py` and `dist/` is prebuilt, but the SPA itself (list → detail → edit/rerun/revert flows) has no real-device acceptance record in the PRD (the PRD predates M1–M6).
   **记录页 UI 的真机浏览**（`web/record`）：API 层有 `core/test_runs_api.py` 覆盖，`dist/` 已预构建，但 SPA 本身（列表 → 详情 → 改批注/重跑/撤回流程）在 PRD 里没有真机验收记录（PRD 早于 M1–M6）。
5. **Windows tray and overlay UI** (F02): 未实测 — compiled with .NET SDK 8.0.425 and native `GET /ping` verified, the rest not; and the current source has not been re-compiled on that machine after the fixes (F40).
   **Windows 托盘和叠层界面**（F02）：未实测 —— 用 SDK 8.0.425 编译并验证过 `GET /ping`，其余没有；修复后的源码也未在该机复编（F40）。
6. **Chrome/Edge extension** (F04/F05): `node --check` passes, never loaded via 「加载已解压」 in a real browser.
   **Chrome/Edge 扩展**（F04/F05）：`node --check` 通过，没有在真浏览器里「加载已解压」过。
7. **MCP `initialize`/`tools/list` in Claude Code, Codex, or Cursor's UI** (F24): stdio behavior has unit tests; no "Connected" acceptance in any client UI.
   **在 Claude Code / Codex / Cursor 界面里确认 MCP 已连接**（F24）：stdio 行为有单测，没有客户端界面的「已连接」验收。
8. **Linux interactive toolbar on a real desktop** (F03): `linux.test_linux` passes; the toolbar session has not had real-device acceptance.
   **Linux 交互工具栏在真实桌面上**（F03）：`linux.test_linux` 通过，工具栏会话没有真机验收。
9. **Voice notes (whisper.cpp) and step-recording keys/buttons** (F26, F27): implemented, never run with a real microphone and model.
   **语音（whisper.cpp）和步骤录制的按键/按钮**（F26、F27）：已实现，没用真实麦克风和模型跑过。
10. **Team server deployment per `team-server/DEPLOY.md`** (F35): tests pass in-tree; never deployed to a reachable machine.
    **团队服务器按 `team-server/DEPLOY.md` 部署**（F35）：树内测试通过，没有部署到可达机器。
11. **The step-by-step commands in this tutorial were not each executed end-to-end** — before publishing, the three Python suites (`core/test_runs_api.py`, `core/test_core.py`, `handoff_test.py`) were run and passed (39 and 18 tests; `handoff_test.py` exit 0), but the remaining commands (building the apps, UI flows) were not run individually; all commands are taken from the sources named throughout (`build.sh`, `handoff.py`, `bridge.py`, `runs_api.py`, the Vue sources, and the scripts).
    **本教程的分步命令未逐条端到端执行** —— 发布前已运行并通过三个 Python 套件（`core/test_runs_api.py`、`core/test_core.py`、`handoff_test.py`，分别为 39、18 个测试，`handoff_test.py` 退出码 0），其余命令（构建应用、界面流程）未逐条运行；所有命令均取自文中所注来源（`build.sh`、`handoff.py`、`bridge.py`、`runs_api.py`、Vue 源码和脚本）。
