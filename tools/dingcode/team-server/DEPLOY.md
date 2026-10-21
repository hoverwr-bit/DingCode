# DingCode team server

The process speaks HTTP and stores SQLite, notes, and screenshots under `DINGCODE_TEAM_ROOT` (default `~/anno-team`). It does not phone home.

## One command

From this directory, with Docker:

```
export DINGCODE_TEAM_ADMIN_TOKEN='choose-a-long-token'
docker compose up --build -d
```

Without Docker:

```
export DINGCODE_TEAM_HOST=127.0.0.1
export DINGCODE_TEAM_PORT=8050
export DINGCODE_TEAM_REQUIRE_AUTH=1
export DINGCODE_TEAM_ADMIN_TOKEN='choose-a-long-token'
python3 dingcode_team_server.py
```

If `DINGCODE_TEAM_ADMIN_TOKEN` is unset, the first launch prints a random admin token once. It is not written into the repository. Create more users with `POST /api/users` as that admin. Roles are `admin`, `member`, and `viewer`.

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

Set `DINGCODE_TEAM_REQUIRE_AUTH=1` whenever the port is reachable beyond localhost. The image defaults to that. The compose file publishes `8050`; put the proxy in front and drop that port mapping if the host should not expose plain HTTP.
