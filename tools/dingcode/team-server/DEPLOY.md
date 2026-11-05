# DingCode team server

The process speaks HTTP and stores SQLite, notes, and screenshots under `DINGCODE_TEAM_ROOT` (default `~/anno-team`). It does not phone home.

## One command

From this directory, with Docker:

```
export DINGCODE_TEAM_ADMIN_TOKEN='choose-a-long-token'
docker compose up --build -d
```

The compose file makes the token mandatory: without `DINGCODE_TEAM_ADMIN_TOKEN` set, compose refuses to start (`must be set`). It also publishes the port on loopback only (`127.0.0.1:8050:8050`); the process still listens on `0.0.0.0` inside the container.

Without Docker:

```
export DINGCODE_TEAM_HOST=127.0.0.1
export DINGCODE_TEAM_PORT=8050
export DINGCODE_TEAM_REQUIRE_AUTH=1
export DINGCODE_TEAM_ADMIN_TOKEN='choose-a-long-token'
python3 dingcode_team_server.py
```

If `DINGCODE_TEAM_ADMIN_TOKEN` is unset, the first launch prints a random admin token once. It is not written into the repository. Create more users with `POST /api/users` as that admin. Roles are `admin`, `member`, and `viewer`.

By default the server sends no CORS headers, so browsers can only call it from the page it serves itself. To let another origin (for example `https://board.example.com`) call the API from a browser, set `DINGCODE_TEAM_CORS_ORIGINS` to a comma-separated list of exact origins, e.g. `export DINGCODE_TEAM_CORS_ORIGINS='https://board.example.com'`. The server then echoes the request's `Origin` back only when it exactly matches an entry — it never sends `*`.

Clients opt in with `DINGCODE_TEAM_URLS=http://127.0.0.1:8050` and `DINGCODE_TEAM_TOKEN`. Leave both empty to stay local. A shared folder uses `DINGCODE_SHARE_DIR` instead of a server.

## HTTPS

Terminate TLS in a reverse proxy on the same host and keep the Python process on `127.0.0.1`. Do not commit certificates or private keys.

Caddy:

```
team.example.com {
  reverse_proxy 127.0.0.1:8050
}
```

nginx:

```
server {
  listen 443 ssl;
  server_name team.example.com;
  ssl_certificate     /etc/dingcode/fullchain.pem;
  ssl_certificate_key /etc/dingcode/privkey.pem;
  location / {
    proxy_pass http://127.0.0.1:8050;
  }
}
```

Set `DINGCODE_TEAM_REQUIRE_AUTH=1` whenever the port is reachable beyond localhost. The image defaults to that. The compose file publishes `127.0.0.1:8050` only; to expose the server to others, put the TLS proxy in front of it, or deliberately change the ports mapping in `compose.yaml` to something like `- "8050:8050"`.
