# DingAI MCP clients

One server, two transports. Both speak the same tools: `dingai_handoff` (first), `dingai_scope_check`, `dingai_reject`, `dingai_list_pins`, `dingai_mark_fixed`, and `dingai_screenshot`. Screenshots are also MCP resources (`dingai://screenshot/<note_id>/<pin_id>`).

Replace `/ABS/PATH/tools/dingai/dingai` with the absolute path of the `dingai` script in this repo. The script uses the Python standard library only.

Stdio (the client starts the process):

```
python3 /ABS/PATH/tools/dingai/dingai mcp
```

HTTP (you start it, and it stays on loopback):

```
python3 /ABS/PATH/tools/dingai/dingai mcp-http
```

That listens on `http://127.0.0.1:8764/mcp`. It answers `POST` with one JSON body and does not open an SSE stream. `GET /mcp` returns 405. If `DINGAI_MCP_TOKEN` is set, send `Authorization: Bearer <token>`. The variable is not a secret stored in the repo.

These snippets match formats taken from each tool's own docs. This tree does not launch those clients, so a snippet is a config shape, not a live connection test. Tools that are not listed here are not claimed.

## Without MCP

Any program that can read stdin or a file can take the newest pins. Aider is the example; it is not listed as an MCP client here.

```
dingai                 # newest local pins as JSON
dingai prompt          # rules, then the newest note
dingai prompt note.json
cat note.json | dingai prompt
```

`dingai pins` still lists the shared folder or the team server. `dingai` with no arguments does not.

## Claude Code

Docs: <https://code.claude.com/docs/en/mcp> and <https://code.claude.com/docs/en/mcp-quickstart>.

Project `.mcp.json`, or `~/.claude.json`. `command` is enough for stdio (`type` is optional when `command` is set). HTTP requires `"type": "http"` (the docs also accept the alias `streamable-http`). A URL without `type` is an error. Claude Code sets `CLAUDE_PROJECT_DIR` for stdio servers.

Stdio: `claude-code.mcp.json`. HTTP: `claude-code.http.json`.

## Codex CLI

Docs: <https://learn.chatgpt.com/docs/extend/mcp> and the config reference linked from that page.

`~/.codex/config.toml` or a project `.codex/config.toml`. Stdio is `[mcp_servers.dingai]` with `command` and `args`. HTTP is the same table with `url` instead of `command`.

`codex.config.toml` has the stdio table. The HTTP form is the commented block in that file.

## Gemini CLI

Docs: <https://geminicli.com/docs/tools/mcp-server/> and the configuration reference linked from that page.

`~/.gemini/settings.json` or `.gemini/settings.json`, under `mcpServers`. Stdio is `command` / `args` / `env` / `cwd`. Streamable HTTP is `httpUrl`. `url` is the SSE transport, which this server does not speak. The docs say to avoid underscores in the server alias; `dingai` has none.

`gemini.settings.json` is the `mcpServers` object to merge. HTTP is `gemini.http.json`.

## Qwen Code

Docs: <https://qwenlm.github.io/qwen-code-docs/en/users/features/mcp/>.

`~/.qwen/settings.json` or `.qwen/settings.json`. The object matches Gemini: `command` / `args` for stdio, `httpUrl` for streamable HTTP, `url` for SSE. The CLI can also add a server with `qwen mcp add`.

`qwen.settings.json` and `qwen.http.json`.

## Kimi CLI

Docs: <https://github.com/MoonshotAI/kimi-cli/blob/main/docs/en/customization/mcp.md>.

`~/.kimi/mcp.json`, key `mcpServers`, either `command` / `args` or `url`. Also `--mcp-config-file` and `--mcp-config`.

`kimi.mcp.json` is stdio. `kimi.http.json` is the `url` form.

Kimi Code CLI is a different product. Its docs are <https://moonshotai.github.io/kimi-code/en/customization/mcp> and <https://www.kimi.com/code/docs/en/kimi-code-cli/customization/mcp.html>. Config files are `~/.kimi-code/mcp.json` and `.kimi-code/mcp.json`. `command` is stdio. `url` with no `transport` is HTTP. `transport: "sse"` is the legacy stream, which this server does not speak.

`kimi-code.mcp.json` is stdio. `kimi-code.http.json` sets `url` and does not set `transport`.

## OpenCode

Current docs (v1): <https://opencode.ai/docs/mcp-servers/>.

`opencode.json` at `~/.config/opencode/opencode.json` or in the project. `mcp.<name>.type` is `local` with a `command` array, or `remote` with `url`. The v1 examples set `enabled` to true.

`opencode.v1.json` is local. `opencode.v1.http.json` is `type: "remote"`.

V2 docs: <https://opencode.ai/v2/docs/mcp-servers/>.

The key is `mcp.servers.<name>`. Local is still `type: "local"` and a `command` array. The flag is `disabled`, not `enabled`. Remote is `type: "remote"` and `url`.

`opencode.v2.json` is local. `opencode.v2.http.json` is `type: "remote"`.

## Cline

Docs: <https://github.com/cline/cline/blob/main/docs/mcp/mcp-overview.mdx> and <https://docs.cline.bot/getting-started/config>.

File: `~/.cline/data/settings/cline_mcp_settings.json` (override with `CLINE_MCP_SETTINGS_PATH`). Stdio is `command` and `args`. A remote server must set `"type": "streamableHttp"` plus `url`. Omitting `type` selects the legacy SSE transport, which this server does not speak. An older doc path `~/.cline/mcp.json` was corrected in Cline issue 11671; use the data/settings path.

`cline.mcp.json` and `cline.http.json`.

## GitHub Copilot CLI

Docs: <https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers>.

`~/.copilot/mcp-config.json` (`COPILOT_HOME` overrides the directory). A project can also use `.mcp.json` or `.github/mcp.json`. The CLI does not read `.vscode/mcp.json`. Local servers use `"type": "local"` with `command`, `args`, and `tools`. HTTP uses `"type": "http"` with `url` and optional `headers`. `copilot mcp add` writes the same file.

`copilot.mcp.json` and `copilot.http.json`.

## Claude Desktop

Docs: <https://modelcontextprotocol.io/docs/2026-07-28/develop/connect-local-servers>.

`claude_desktop_config.json`, key `mcpServers`, `command` and `args`. macOS: `~/Library/Application Support/Claude/`. Windows: `%APPDATA%\Claude\`. That page does not list a Linux path. VS Code's MCP discovery docs name `$XDG_CONFIG_HOME/Claude/claude_desktop_config.json` or `~/.config/Claude/` on Linux (<https://code.visualstudio.com/docs/agents/reference/mcp-configuration>). The snippet here is the local command form from the MCP page. That page does not document an HTTP entry for Claude Desktop, so none is shipped.

`claude-desktop.json`.

## Cursor

Docs: <https://cursor.com/docs/mcp>.

`~/.cursor/mcp.json` and a project `.cursor/mcp.json`, key `mcpServers`. Published examples use `command` and `args` for stdio and `url` for HTTP. `${env:NAME}` and `${workspaceFolder}` interpolate. The field table says `type` is required for stdio; the published examples omit it. These snippets follow the examples.

`cursor.mcp.json` and `cursor.http.json`.

## VS Code

Docs: <https://code.visualstudio.com/docs/agents/reference/mcp-configuration>.

`.vscode/mcp.json` uses a top-level `servers` object (not `mcpServers`). Stdio needs `"type": "stdio"`, `command`, and `args`. HTTP needs `"type": "http"` and `url`. A portable `.mcp.json` uses `mcpServers` instead. Copilot CLI does not read the VS Code file; use the Copilot snippet above for that CLI.

`vscode.mcp.json` and `vscode.http.json` match `.vscode/mcp.json`. `vscode.portable.mcp.json` is the portable `.mcp.json` shape (`mcpServers`, with `type`).
