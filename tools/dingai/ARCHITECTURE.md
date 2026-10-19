# DingAI architecture

DingAI is one tool inside AI-toolbox. Each desktop client is still one program with its own UI toolkit. They share the JSON contract in this file.

`core/` is a Python standard-library package for the pieces that would otherwise be copied into a third language with nothing to test: the note schema (including pin type and status), label placement, and team sync (HTTP and a shared folder). The Linux client and `handoff.py` import it. The macOS and Windows apps do not embed Python; they write the same field names in their existing JSON builders. That split is deliberate: a Swift or C# rewrite onto a new runtime would be a second architecture. Do not add a package, framework, or UI toolkit beyond this.

## Layout

| Path | Role |
|---|---|
| `macos/DingAI.swift` | Menu-bar app. Models, localhost bridge, capture, overlay, and JSON export live in this one file. |
| `macos/build.sh`, `macos/Info.plist` | Build and bundle. Bundle id `io.github.dingai.mac`. Minimum macOS 14. |
| `windows/Program.cs`, `windows/DingAIWin.csproj` | Same desktop contract on WPF. One source file, namespace `DingAIWin`. |
| `web/anno.js` | One IIFE injected into a page. No build step. |
| `linux/dingai_linux.py` | Linux session. X11 toolbar, Wayland still capture when `grim` exists, AT-SPI anchors, Tesseract OCR. Imports `core/`. |
| `core/` | Schema, label placement, folder sync, team HTTP client. Standard library only. |
| `team-server/dingai_team_server.py` | Opt-in team server. Standard library and SQLite. Same process serves the old note API and the account API. |
| `probes/*.swift` | One-off diagnostics. Not part of the app. |

## macOS

`DingAI.swift` is an AppKit app (`NSApplication` + `AnnoController` as delegate). A Carbon hotkey (`⌥⌘A`) calls `begin` / `finish`. `begin` records the previous frontmost app, the screen under the cursor, and on-screen windows. In the default live session it opens a clear `AnnotationWindow` immediately and captures with ScreenCaptureKit only in `finish`, so the JSON image matches the pin coordinates at export. `⌥⌘P` or holding ⌥ sets `ignoresMouseEvents`; `scrollWheel` posts the event through to the app underneath. Pins remember an AX element, a scroll-bar sample, or a web-bridge key and are updated from the existing timer/`BridgeServer` path. `shotArrived` still builds the overlay; `AnnotationView` draws the marks.

Interaction stays on the view: `mouseDown` / `mouseDragged` / `mouseUp`, `keyDown` for Esc, ⌘Z, and Delete, and a `DragBar` of `NSButton`s built in `installToolBar`. Toolbar tags are modes: 20 select, 21 arrow, 22 box, 23 ellipse, 24 spotlight, 25 text. Select hit-tests in `hitItem` / `hitHandle` and moves or resizes the existing record. Coordinates are converted only in `ptToPx` / `pxToPt` (view points, bottom-left, to image pixels, top-left). Marks are an `ActionItem` enum (`.pin`, `.arrow`, `.box`, `.text`) held in an array. Undo removes the last item.

The page bridge is `BridgeServer`, a hand-written HTTP/1.1 listener on `127.0.0.1:8763` (`NWListener`). Pages `GET /ping`, `GET /pending` or `GET /events`, and `POST /answer`. Failures are logged and ignored; a dead bridge does not block pinning. Team upload reads `~/DingAI/settings.json` (`mode`, `share_dir`, `server_url`, `token`, `project`), overridden by `DINGAI_MODE`, `DINGAI_SHARE_DIR`, `DINGAI_TEAM_URLS` (fallback `ANNO_TEAM_URLS`), and `DINGAI_TEAM_TOKEN`. Missing settings stay local. Keys B/C/Q set the selected pin's type (`bug`, `change`, `question`). There is no other network.

Errors use `try?`, empty results, and `NSLog`. The app does not crash the pinning flow because OCR, capture, or the bridge failed.

## Windows

`Program.cs` mirrors the macOS session: tray icon, `Ctrl+Alt+A`, `AnnoCanvas` mouse handlers, the same JSON fields. The default session is live: the overlay is clear, hold Alt to pass clicks through, and the screenshot is taken in `Finish` after the window hides. UI Automation (`AutomationElement.FromPoint`) supplies the pin anchor. `DINGAI_LIVE=0` keeps the frozen screenshot. Window hit-testing walks `WinCands` front to back. OCR uses the Windows.Media.Ocr API. There is no page bridge on Windows. Team upload and the shared folder read `~/DingAI/settings.json`, overridden by `DINGAI_MODE`, `DINGAI_SHARE_DIR`, `DINGAI_TEAM_URLS`, and `DINGAI_TEAM_TOKEN`. Pin type is `bug`, `change`, or `question` (keys B/C/Q). Labels use the same placement rule as `core/layout.py`.

## Linux

`dingai_linux.py` is one Python program. A small X11 toolbar grabs the pointer to drop a pin, or two clicks for an arrow, box, or spotlight, so the app underneath keeps working. The screenshot is taken when the session ends. Anchors come from AT-SPI over the session bus (`busctl`) when that bus is up. OCR shells out to the `tesseract` binary. On Wayland, a still capture uses `grim` when it is installed; the interactive toolbar needs X11 or XWayland. Export, placement, and sync go through `core/`. Failures in capture, OCR, or AT-SPI are skipped and written into the note as empty fields.

## Web

`anno.js` is a single IIFE. It bails out if `window.ANNO_V7` is set or `?qa=1`. UI nodes are marked `data-annotation-ui` and created with the local `el()` helper. Styles are one injected stylesheet. State is the `annos` array, persisted under `localStorage` key `anno-v7:` + path. Pins store an element key (`sec:`, `id:`, `ding:`, or `free:`) plus `anchor.dx/dy` and are redrawn on scroll (capture phase) and resize. Toolbar tools are `select`, `point`, `arrow`, `box`, `ellipse`, `spot`, and `text`, stored on each annotation's `mark`. Comment callouts and the hover card are placed by `layoutCallouts` (the marked block in this file; the same rule is inlined in `DingAI.swift`). The bridge client polls `127.0.0.1:8763` and subscribes with `EventSource`. Copy uses `navigator.clipboard` and falls back to a textarea. The modal stores `pinType` (`bug`, `change`, `question`) and `status` (`open` until a desktop or team client changes it). The page does not read `settings.json`; publishing stays on the desktop clients.

On a dev build, a pin records `source` `{framework, component, file, line, column}`. The lookup walks React fiber `_debugSource`, Vue `type.__file`, Svelte `__svelte_meta`, and inspector attributes (`data-insp-path`, `data-source-file`). A generated position is mapped with the script's source map when one is already in memory (`window.__DINGAI_SOURCE_MAPS`). The walk is local and returns nothing on a production build that has stripped those fields. The bridge answer includes the same object, and the macOS JSON copies it to `pins[].source`.

## Team server

`dingai_team_server.py` serves `ThreadingHTTPServer`. `POST /api/note` still stores a JSON body, `POST /api/shot/<file>` stores a PNG, and `GET /` is the board. Paths are sanitized with `os.path.basename`. SQLite (`sqlite3`) holds users, projects, pins, and comments under `DINGAI_TEAM_ROOT` (default `~/anno-team`). Tokens are random bearer tokens, stored only as SHA-256. Roles are `admin`, `member`, and `viewer`. The first launch creates an admin and prints the token once, unless `DINGAI_TEAM_ADMIN_TOKEN` is already set. `DINGAI_TEAM_REQUIRE_AUTH=1` rejects anonymous note upload; the default stays open so older clients keep working. Host and port come from `DINGAI_TEAM_HOST` / `DINGAI_TEAM_PORT`, falling back to `ANNO_TEAM_*`, then `127.0.0.1:8050`. The process speaks HTTP. TLS belongs in a reverse proxy; see `team-server/DEPLOY.md`. There is no telemetry.

Shared-folder sync, used when there is no server, writes one JSON file per pin under `<dir>/projects/<project>/pins/` with a temp file and `os.replace`. Screenshots sit next to the note id. Clients choose `local`, `folder`, or `server` in `~/DingAI/settings.json` (`mode`, `share_dir`, `server_url`, `project`). Environment variables override the file. Missing settings mean local-only.

## JSON contract

Desktop notes use `schema: "dingai-desktop-v1"` and `tool: "dingai"`. `schema_compat` is `anno-desktop-v1`. Existing fields stay:

- `pins[]`: `id`, `x_px`, `y_px` (screenshot pixels, top-left origin), `ocr_nearby`, optional `note`, optional `window` `{owner, title}`, optional `window_nx` / `window_ny`, optional `page` from the bridge. Optional `pin_type` is `bug` (default), `change`, or `question`. Optional `status` is `open` (default), `ai-fixed`, or `confirmed`. Optional `assignee`. Optional `source` `{framework, component, file, line, column}` from a web dev build.
- `arrows[]`: `id`, `from_px`, `to_px`, `color`, `width`.
- `boxes[]`: `id`, `rect_px` `[x, y, w, h]`, `color`, `width`, optional `shape` (`rect`, `ellipse`, or `spotlight`), optional `note`.
- `labels[]` (optional): `id`, `x_px`, `y_px`, `w_px`, `h_px`, `text`, `color`. Web text is a `mark.type` of `text` on the existing annotation, not this array.
- Counts, `screen`, `window`, `app`, `screenshot`, `screen_capture_ok`.

`window.frame_px` is in **points**, top-left, local to the annotated screen, despite the name. `window_nx` / `window_ny` divide pixel pin positions by that frame scaled into pixels.

New fields are optional and must not rename or remove these. The web export is a different object (`version: 7.9`, `annotations[]`) and stays that way.

`handoff_rules` is an optional string on both exports. Clipboard text is that string, a one-line instruction, then the JSON. A project overrides it with `.dingai/handoff-rules.md` (`DINGAI_PROJECT`, or the path in `~/DingAI/project.txt`). Otherwise `~/DingAI/handoff-rules.md` is used. The page reads `window.DINGAI_HANDOFF_RULES` or `localStorage` key `dingai-handoff-rules`. `handoff.py` is the CLI and the stdio MCP server for the same prompt. It uses the Python standard library only, because nothing else in the toolbox speaks MCP. `dingai_list_pins` and `dingai_mark_fixed` read the shared folder or the team server and can attach a verification PNG when a pin is marked ai-fixed. `dingai_handoff` stays the first tool. `handoff.py scope` (and the macOS and Windows menu item “检查本次改动”) diffs the working tree against `.dingai/last-handoff.json`, written when a note is exported. Warnings cover paths outside `.dingai/scope.txt`, dependency and lock files, new top-level names, and diffs over 400 lines or 8 files. Reject runs `git restore` on those paths and deletes untracked ones. It does nothing to history when `HEAD` has moved. The menu check is inlined in each desktop client so an installed app does not need the script.

## Release review

A batch of pins is a release. The files live in the state directory: `~/DingAI` locally, `<share>/dingai-state` for a shared folder, and `<DINGAI_TEAM_ROOT>/state` on the team server. `handoff.py release open` stores each pin, the before and after screenshots, the `git diff --stat` since the handoff baseline, the scope-check warnings, the commit SHAs, and the handoff rules then in force. The review page crops both shots around the pin's anchor. A reviewer approves or rejects each pin. `release publish` refuses while any pin is unreviewed or rejected. An admin (`DINGAI_RELEASE_ADMIN=1` locally, or an admin token on the server) can publish anyway, and the reason is appended to the release and to `releases/audit.jsonl`. Publishing marks the record immutable. Later approve or reject calls do not change it. Search reads the records. Export writes a zip or a Markdown file. Rollback creates a new draft that points at the previous release (`restores`) and does not edit the published archive. The board links to `/release/<id>/`.

## Session collisions

`handoff.py session` records each active handoff: agent, repo, branch, worktree, pins, paths, and optional services, ports, databases, and deploy targets. Building a prompt and marking a pin fixed run the same check. It warns, and does not stop the handoff, when two sessions share a repo and branch, when paths overlap, when the same pin is claimed twice, when a pin's project does not match the session's project, when a service, port, database, or deploy target overlaps, or when `HEAD` has moved since the session started. The choices are queue, isolate (a new git worktree and branch), hand the pin to the session that already owns the area, or continue. Each choice is written onto the session. Paths and pins take soft locks with an owner and an expiry of four hours. Ending a session drops its locks and writes a side-by-side diff for overlapping paths. One user can keep this in `~/DingAI` with no server. A shared folder uses `<share>/dingai-state`. The team server stores the same records under `state/` and the board shows `notices.json` as a banner. The desktop clients read `~/DingAI/notices.json` and draw the same banner without taking the click.

## Conventions for changes

- Edit the client that owns the behavior. A desktop pin bug goes in `DingAI.swift` (and `Program.cs` only when the same bug exists there). A page-scroll bug goes in `anno.js`.
- Keep the file's naming and control flow: new overlay behavior is another branch in the existing mouse and draw methods, not a new view hierarchy.
- Prefer `try?` and a skipped feature over a new error type.
- Clipboard and disk output stay local. Network remains the opt-in team upload and the loopback bridge.
- Do not add Swift packages, NuGet packages, npm packages, or Python dependencies. UI Automation on Windows is the framework assembly, not a NuGet package.
- Tests that can run without AppKit live in `core/test_core.py`, `handoff_test.py`, and `team-server/test_server.py`. The Linux client imports `core` instead of copying those functions.
