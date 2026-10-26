"""Loopback page bridge. The session token is not a public CORS resource.

GET /ping mints a token only for an allowlisted Origin, or for a local client
that sent no Origin header. Allowed origins are the configured Chrome extension
id (DINGCODE_EXTENSION_ID, else ~/.dingcode/config.json extension_id) and the
http(s) keys in ~/.dingcode/projects.json. The response echoes that origin.
Access-Control-Allow-Private-Network is sent only then. Any other Origin,
including "null", is 403 and the body has no token. The same check covers
/pending, /answer, and /voice. /voice also requires the registered client id.

The session record page (core/runs_api.py) lives under /app and reads through
/api/*. Those paths accept only a loopback Host plus the page's own origin
(self) or a local no-Origin client, and never get CORS headers. Writes (M2)
are POST under /api/runs/... and additionally require the page's own origin —
a request with no Origin header is read-only.
"""

import json
import os
import re
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from core.paths import env

_EXT_ID = re.compile(r"^[a-p]{32}$")
_UNSAFE = re.compile(r"[\r\n\x00,]")

# DingCode.app 的公开端口：原生壳占 127.0.0.1:8763，把 /app、/api 原样转发到
# 内部 bridge（bridge 自己可能跑在其他端口）。转发保留 Host 与 Origin 头，
# 所以 Host/Origin 是壳的 8763 也视为本机页面（BK-02）。
APP_PUBLIC_PORT = 8763


def config_dir():
    """~/.dingcode, or DINGCODE_HOME when set (handoff.dot_dir 的同一套覆盖)."""
    override = env("DINGCODE_HOME", "DINGAI_HOME")
    if override:
        return override
    return os.path.join(os.path.expanduser("~"), ".dingcode")


def extension_id():
    forced = env("DINGCODE_EXTENSION_ID", "DINGAI_EXTENSION_ID", default="") or ""
    forced = forced.strip()
    if _EXT_ID.match(forced):
        return forced
    path = os.path.join(config_dir(), "config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    value = str(data.get("extension_id") or "").strip()
    return value if _EXT_ID.match(value) else ""


def normalize_origin(raw):
    """http(s) or chrome-extension origin, or '' when it is not one."""
    text = (raw or "").strip()
    if not text or _UNSAFE.search(text) or " " in text or "@" in text or "\\" in text:
        return ""
    if text == "null" or text == "*":
        return ""
    parsed = urlparse(text)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if not scheme or not host or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return ""
    if parsed.path not in ("", "/"):
        return ""
    if scheme == "chrome-extension":
        if not _EXT_ID.match(host):
            return ""
        return "chrome-extension://" + host
    if scheme not in ("http", "https"):
        return ""
    if parsed.port:
        return "%s://%s:%d" % (scheme, host, parsed.port)
    return "%s://%s" % (scheme, host)


def allowed_origins():
    allow = set()
    ext = extension_id()
    if ext:
        allow.add("chrome-extension://" + ext)
    path = os.path.join(config_dir(), "projects.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return allow
    bindings = data.get("bindings") if isinstance(data, dict) else None
    if not isinstance(bindings, dict):
        return allow
    for key in bindings:
        if not isinstance(key, str):
            continue
        norm = normalize_origin(key)
        if norm.startswith("http://") or norm.startswith("https://"):
            allow.add(norm)
    return allow


def classify_origin(origin, allow=None, port=None):
    """Return ('cli', None), ('self', None), ('allow', echo), or ('deny', None).

    origin is None when the request has no Origin header. That is the local
    CLI case: the token may be returned, and no CORS or private-network header
    is sent. A present Origin is echoed only when it is on the allowlist.
    A loopback origin on this service's own port (or the shell's
    APP_PUBLIC_PORT, when the native shell forwards requests here) classifies
    as "self": the record page served from /app. Same-origin requests need no
    CORS header, so "self" never gets one.
    """
    if allow is None:
        allow = allowed_origins()
    if origin is None:
        return "cli", None
    if not isinstance(origin, str) or origin == "" or _UNSAFE.search(origin):
        return "deny", None
    norm = normalize_origin(origin)
    if not norm:
        return "deny", None
    if port is not None:
        ports = port if isinstance(port, (tuple, list, set)) else (port,)
        parsed = urlparse(norm)
        if parsed.hostname in ("127.0.0.1", "localhost") and parsed.port in set(int(p) for p in ports):
            return "self", None
    if norm not in allow:
        return "deny", None
    return "allow", origin


class BridgeState:
    def __init__(self):
        self.token = secrets.token_hex(16)
        self.clients = {}
        self.next_id = 1
        self.lock = threading.Lock()

    def register(self):
        with self.lock:
            client_id = self.next_id
            self.next_id += 1
            self.clients[client_id] = self.token
            return client_id, self.token

    def client_ok(self, client_id, token):
        try:
            client_id = int(client_id)
        except (TypeError, ValueError):
            return False
        if not token:
            return False
        with self.lock:
            return self.clients.get(client_id) == token and token == self.token


class BridgeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def _origin(self):
        if "Origin" not in self.headers:
            return None
        return self.headers.get("Origin")

    def _decision(self):
        return classify_origin(self._origin(), allowed_origins(),
                               (self.server.server_address[1], APP_PUBLIC_PORT))

    def _host_ok(self):
        """DNS-rebinding guard for /api and /app: the Host must be loopback here.

        The native shell forwards /app and /api from its own public port
        (APP_PUBLIC_PORT) verbatim, Host header included, so that port counts
        as loopback too.
        """
        host = (self.headers.get("Host") or "").strip().lower()
        if not host:
            return False
        port = self.server.server_address[1]
        return host in ("127.0.0.1:%d" % port, "localhost:%d" % port,
                        "127.0.0.1:%d" % APP_PUBLIC_PORT, "localhost:%d" % APP_PUBLIC_PORT)

    def _query(self):
        parsed = urlparse(self.path)
        raw = parse_qs(parsed.query, keep_blank_values=True)
        return parsed.path, {key: values[-1] for key, values in raw.items()}

    def _write(self, code, body, content_type, decision, extra=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        kind, echo = decision
        if kind == "allow" and echo and not _UNSAFE.search(echo):
            self.send_header("Access-Control-Allow-Origin", echo)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Private-Network", "true")
        for key, value in extra or []:
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        if length <= 0:
            return b""
        return self.rfile.read(min(length, 1 << 20))

    def do_OPTIONS(self):
        decision = self._decision()
        if decision[0] == "deny":
            self._write(403, "forbidden", "text/plain; charset=utf-8", decision)
            return
        extra = [
            ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
            ("Access-Control-Allow-Headers", "Content-Type"),
            ("Access-Control-Max-Age", "86400"),
        ]
        self._write(204, b"", "text/plain", decision, extra)

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def _handle(self):
        decision = self._decision()
        if decision[0] == "deny":
            self._write(403, "forbidden", "text/plain; charset=utf-8", decision)
            return
        path, query = self._query()
        state = self.server.state
        if path == "/api" or path.startswith("/api/") or path == "/app" or path.startswith("/app/"):
            # Record-page surface: loopback Host only, and only the page itself
            # (self) or a local client with no Origin header may call it. Any
            # other Origin, even an allowlisted one, is an external site.
            if decision[0] not in ("self", "cli") or not self._host_ok():
                self._write(403, "forbidden", "text/plain; charset=utf-8", decision)
                return
            if path == "/api/desktop" or path.startswith("/api/desktop/"):
                # Desktop-only surface: handled by the app's own server, never here.
                self._write(501, "not implemented", "text/plain; charset=utf-8", decision)
                return
            if path == "/app" or path.startswith("/app/"):
                if self.command != "GET":
                    self._write(405, "method not allowed", "text/plain; charset=utf-8", decision, [("Allow", "GET")])
                    return
            elif self.command not in ("GET", "POST"):
                self._write(405, "method not allowed", "text/plain; charset=utf-8", decision, [("Allow", "GET, POST")])
                return
            from core import runs_api
            runs_api.handle(self, path, query, decision)
            return
        if self.command == "GET" and path == "/ping":
            client_id, token = state.register()
            body = json.dumps({
                "app": "dingcode-bridge",
                "compat": "anno-bridge",
                "version": 1,
                "client": client_id,
                "token": token,
            })
            self._write(200, body, "application/json; charset=utf-8", decision)
            return
        if self.command == "GET" and path == "/pending":
            if not state.client_ok(query.get("client"), query.get("token")):
                self._write(403, "forbidden", "text/plain; charset=utf-8", decision)
                return
            self._write(200, json.dumps({"seq": 0, "requests": []}), "application/json; charset=utf-8", decision)
            return
        if self.command == "POST" and path == "/answer":
            try:
                obj = json.loads(self._read_body().decode("utf-8") or "{}")
            except ValueError:
                obj = {}
            if not isinstance(obj, dict) or not state.client_ok(obj.get("client"), obj.get("token")):
                self._write(403, "forbidden", "text/plain; charset=utf-8", decision)
                return
            self._write(200, json.dumps({"ok": 1}), "application/json; charset=utf-8", decision)
            return
        if self.command == "POST" and path == "/voice":
            self._read_body()
            if not state.client_ok(query.get("client"), query.get("token")):
                self._write(403, "forbidden", "text/plain; charset=utf-8", decision)
                return
            self._write(200, "", "text/plain; charset=utf-8", decision)
            return
        self._write(404, "not found", "text/plain; charset=utf-8", decision)


class BridgeServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, handler):
        super().__init__(server_address, handler)
        self.state = BridgeState()


def make_server(port):
    return BridgeServer(("127.0.0.1", int(port)), BridgeHandler)


def config_port():
    """config.json 里的 port（M6 设置页可改，重启生效）；没写或非法返回 0。"""
    path = os.path.join(config_dir(), "config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        port = int(data.get("port") or 0)
    except (OSError, ValueError, TypeError):
        return 0
    return port if 1 <= port <= 65535 else 0


def default_port():
    # 环境变量优先（原生端显式传的端口不动），其次 config.json 的 port。
    forced = env("DINGCODE_BRIDGE_PORT", "DINGAI_BRIDGE_PORT", default="") or ""
    if forced:
        try:
            return int(forced)
        except ValueError:
            pass
    return config_port() or 8763


def serve_background(port=None):
    try:
        httpd = make_server(default_port() if port is None else port)
    except OSError:
        return None
    thread = threading.Thread(target=httpd.serve_forever, name="dingcode-bridge", daemon=True)
    thread.start()
    return httpd


def main(argv):
    port = default_port()
    args = list(argv or [])
    if "--port" in args:
        index = args.index("--port")
        if index + 1 >= len(args):
            sys.stderr.write("usage: python3 -m core.bridge [--port N]\n")
            return 2
        try:
            port = int(args[index + 1])
        except ValueError:
            sys.stderr.write("usage: python3 -m core.bridge [--port N]\n")
            return 2
    try:
        httpd = make_server(port)
    except OSError as exc:
        sys.stderr.write("bridge: %s\n" % exc)
        return 1
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
