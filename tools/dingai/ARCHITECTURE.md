# DingAI architecture

DingAI is one tool inside AI-toolbox. Each client is a single self-contained program. They share a JSON contract, not a library, framework, or runtime. Change a client by editing that client's existing file and following its patterns. Do not add a shared module, a new app framework, or a dependency unless the feature cannot be done any other way; say why in the pull request.

## Layout

| Path | Role |
|---|---|
| `macos/DingAI.swift` | Menu-bar app. Models, localhost bridge, capture, overlay, and JSON export live in this one file. |
| `macos/build.sh`, `macos/Info.plist` | Build and bundle. Bundle id `io.github.dingai.mac`. Minimum macOS 14. |
| `windows/Program.cs`, `windows/DingAIWin.csproj` | Same desktop contract on WPF. One source file, namespace `DingAIWin`. |
| `web/anno.js` | One IIFE injected into a page. No build step. |
| `team-server/dingai_team_server.py` | Optional opt-in collector. Python standard library only. |
| `probes/*.swift` | One-off diagnostics. Not part of the app. |

## macOS

`DingAI.swift` is an AppKit app (`NSApplication` + `AnnoController` as delegate). A Carbon hotkey (`⌥⌘A`) calls `begin` / `finish`. `begin` records the previous frontmost app, the screen under the cursor, and on-screen windows. In the default live session it opens a clear `AnnotationWindow` immediately and captures with ScreenCaptureKit only in `finish`, so the JSON image matches the pin coordinates at export. `⌥⌘P` or holding ⌥ sets `ignoresMouseEvents`; `scrollWheel` posts the event through to the app underneath. Pins remember an AX element, a scroll-bar sample, or a web-bridge key and are updated from the existing timer/`BridgeServer` path. `shotArrived` still builds the overlay; `AnnotationView` draws the marks.

Interaction stays on the view: `mouseDown` / `mouseDragged` / `mouseUp`, `keyDown` for Esc, ⌘Z, and Delete, and a `DragBar` of `NSButton`s built in `installToolBar`. Toolbar tags are modes: 20 select, 21 arrow, 22 box, 23 ellipse, 24 spotlight, 25 text. Select hit-tests in `hitItem` / `hitHandle` and moves or resizes the existing record. Coordinates are converted only in `ptToPx` / `pxToPt` (view points, bottom-left, to image pixels, top-left). Marks are an `ActionItem` enum (`.pin`, `.arrow`, `.box`, `.text`) held in an array. Undo removes the last item.

The page bridge is `BridgeServer`, a hand-written HTTP/1.1 listener on `127.0.0.1:8763` (`NWListener`). Pages `GET /ping`, `GET /pending` or `GET /events`, and `POST /answer`. Failures are logged and ignored; a dead bridge does not block pinning. Team upload reads `DINGAI_TEAM_URLS` (fallback `ANNO_TEAM_URLS`) and skips quietly when that is empty. There is no other network.

Errors use `try?`, empty results, and `NSLog`. The app does not crash the pinning flow because OCR, capture, or the bridge failed.

## Windows

`Program.cs` mirrors the macOS session: tray icon, `Ctrl+Alt+A`, frozen screenshot, `AnnoCanvas` mouse handlers, the same JSON fields. Window hit-testing walks `WinCands` front to back. OCR uses the Windows.Media.Ocr API. There is no page bridge on Windows.

## Web

`anno.js` is a single IIFE. It bails out if `window.ANNO_V7` is set or `?qa=1`. UI nodes are marked `data-annotation-ui` and created with the local `el()` helper. Styles are one injected stylesheet. State is the `annos` array, persisted under `localStorage` key `anno-v7:` + path. Pins store an element key (`sec:`, `id:`, `ding:`, or `free:`) plus `anchor.dx/dy` and are redrawn on scroll (capture phase) and resize. Toolbar tools are `select`, `point`, `arrow`, `box`, `ellipse`, `spot`, and `text`, stored on each annotation's `mark`. Comment callouts and the hover card are placed by `layoutCallouts` (the marked block in this file; the same rule is inlined in `DingAI.swift`). The bridge client polls `127.0.0.1:8763` and subscribes with `EventSource`. Copy uses `navigator.clipboard` and falls back to a textarea.

## Team server

`dingai_team_server.py` serves `ThreadingHTTPServer`. `POST /api/note` stores a JSON body, `POST /api/shot/<file>` stores a PNG, and `GET /` is the board. Paths are sanitized with `os.path.basename`. There is no authentication; bind it to a trusted network. Host and port come from `DINGAI_TEAM_HOST` / `DINGAI_TEAM_PORT`, falling back to `ANNO_TEAM_*`, then `127.0.0.1:8050`.

## JSON contract

Desktop notes use `schema: "dingai-desktop-v1"` and `tool: "dingai"`. `schema_compat` is `anno-desktop-v1`. Existing fields stay:

- `pins[]`: `id`, `x_px`, `y_px` (screenshot pixels, top-left origin), `ocr_nearby`, optional `note`, optional `window` `{owner, title}`, optional `window_nx` / `window_ny`, optional `page` from the bridge.
- `arrows[]`: `id`, `from_px`, `to_px`, `color`, `width`.
- `boxes[]`: `id`, `rect_px` `[x, y, w, h]`, `color`, `width`, optional `shape` (`rect`, `ellipse`, or `spotlight`), optional `note`.
- `labels[]` (optional): `id`, `x_px`, `y_px`, `w_px`, `h_px`, `text`, `color`. Web text is a `mark.type` of `text` on the existing annotation, not this array.
- Counts, `screen`, `window`, `app`, `screenshot`, `screen_capture_ok`.

`window.frame_px` is in **points**, top-left, local to the annotated screen, despite the name. `window_nx` / `window_ny` divide pixel pin positions by that frame scaled into pixels.

New fields are optional and must not rename or remove these. The web export is a different object (`version: 7.9`, `annotations[]`) and stays that way.

`handoff_rules` is an optional string on both exports. Clipboard text is that string, a one-line instruction, then the JSON. A project overrides it with `.dingai/handoff-rules.md` (`DINGAI_PROJECT`, or the path in `~/DingAI/project.txt`). Otherwise `~/DingAI/handoff-rules.md` is used. The page reads `window.DINGAI_HANDOFF_RULES` or `localStorage` key `dingai-handoff-rules`. `handoff.py` is the CLI and the stdio MCP server for the same prompt. It uses the Python standard library only, because nothing else in the toolbox speaks MCP.

## Conventions for changes

- Edit the client that owns the behavior. A desktop pin bug goes in `DingAI.swift` (and `Program.cs` only when the same bug exists there). A page-scroll bug goes in `anno.js`.
- Keep the file's naming and control flow: new overlay behavior is another branch in the existing mouse and draw methods, not a new view hierarchy.
- Prefer `try?` and a skipped feature over a new error type.
- Clipboard and disk output stay local. Network remains the opt-in team upload and the loopback bridge.
- Do not add Swift packages, NuGet packages, npm packages, or Python dependencies.
- Tests that can run without AppKit belong next to the client they exercise and call that client's functions. Do not introduce a shared core for that.
