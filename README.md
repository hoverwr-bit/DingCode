# AI-toolbox

A toolbox of local helpers for AI coding agents. The first tool is **DingAI** (formerly AnnoOverlay / anno): point at the screen, and the agent receives machine-readable JSON instead of a one-line description.

**给写代码的 AI 用的本地工具箱。** 第一件工具是 **DingAI**（原 AnnoOverlay / anno）：在屏幕上点一下，智能体拿到的是机器可读的 JSON，而不是一句「改左上角那个按钮」。

DingAI drops pins on any app or web page and exports JSON: app, window, pixel coordinates, nearby OCR text and, inside a browser, the DOM element and field under the pin. Paste that into Claude Code, Codex or any other agent.

## Layout / 目录

| Path | What |
|---|---|
| `tools/dingai/macos/` | DingAI menu-bar app (Swift, AppKit, ScreenCaptureKit, Vision). Live overlay: the app underneath stays usable; the screenshot is taken when you finish |
| `tools/dingai/windows/` | DingAIWin, same JSON contract |
| `tools/dingai/web/anno.js` | In-page annotation layer. Pins anchor to DOM elements and follow scrolling. Localhost bridge to the desktop app |
| `tools/dingai/team-server/` | Optional self-hosted collector and board. No authentication — trusted network only |
| `tools/dingai/probes/` | Diagnostic probes (display, capture, OCR, red-pixel scans) |

## Build / 构建

- macOS 14+: `cd tools/dingai/macos && ./build.sh`  
  Signs with a local **DingAI Dev** identity if present, otherwise **AnnoOverlay Dev**, otherwise ad-hoc. Needs Screen Recording. Changing the bundle id to `io.github.dingai.mac` means granting that permission again.
- Windows: `cd tools/dingai/windows && dotnet build`
- Web: load `tools/dingai/web/anno.js`. Enable with `?anno=1`, `window.ANNO_V7_ADMIN = true`, or `window.ANNO_ADMIN_CHECK()`.
- Team server: `python3 tools/dingai/team-server/dingai_team_server.py`

## Annotating

`⌥⌘A` starts a session on the display under the pointer. The desktop stays live: the scroll wheel goes through to the app, hold ⌥ to click it, and `⌥⌘P` locks that click-through. Pins in a browser follow the element reported by the page bridge; other pins follow the Accessibility element when that permission is granted. Esc writes JSON and a PNG taken at that moment.

## Desktop ↔ page bridge

The macOS app listens on `127.0.0.1:8763` only. A page that has loaded `anno.js` answers `elementFromPoint` so a desktop pin landing in a browser can record the DOM field. Nothing else is contacted unless team upload is configured.

## Configuration / 配置

| Env var | Used by | Default |
|---|---|---|
| `DINGAI_OUTPUT_DIR` (fallback `ANNO_OUTPUT_DIR`) | macOS, path relative to home; Windows, under the user profile | `DingAI` |
| `DINGAI_TEAM_URLS` (fallback `ANNO_TEAM_URLS`) | macOS, comma-separated team server URLs | empty = no upload |
| `DINGAI_TEAM_HOST` / `DINGAI_TEAM_PORT` (fallback `ANNO_TEAM_*`) | team server | `127.0.0.1` / `8050` |

## Handoff rules

Every clipboard export is a prompt: the handoff rules, then the JSON note. The note on disk keeps the same rules in `handoff_rules`. Edit them per project in `.dingai/handoff-rules.md` (set `DINGAI_PROJECT`, or put the project path in `~/DingAI/project.txt`). A user-wide file is `~/DingAI/handoff-rules.md`. On a page, set `window.DINGAI_HANDOFF_RULES` or `localStorage['dingai-handoff-rules']`.

```
python3 tools/dingai/handoff.py prompt notes/anno.json
python3 tools/dingai/handoff.py mcp
```

The defaults ask the coding agent for a minimal change, to follow the project's architecture file, to stay on the pinned element, to justify new dependencies, and to explain how the diff was verified.

## JSON contract

Desktop notes use `schema: "dingai-desktop-v1"` and `tool: "dingai"`. The field set matches the previous `anno-desktop-v1` contract (`schema_compat` records that name): `pins[].x_px` / `y_px` are screenshot pixels with a top-left origin, plus `window_nx` / `window_ny`, `ocr_nearby`, optional `note`, optional `window`, and optional `page` from the browser bridge. Arrows use `from_px` / `to_px`. Boxes use `rect_px`.

## License

MIT
