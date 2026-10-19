#!/usr/bin/env python3
# DingAI team server. Stdlib HTTP + SQLite. No telemetry.
# Legacy: POST /api/note, POST /api/shot/<file>, GET /api/notes, GET /api/note/<file>, GET /api/shot/<file>
# Accounts: bearer tokens, roles admin | member | viewer, projects, pin status, comments.
# Auth is opt-in. Set DINGAI_TEAM_REQUIRE_AUTH=1 before exposing the port.
# TLS is a reverse proxy; see DEPLOY.md. Do not commit tokens or certificates.

import hashlib
import json
import os
import secrets
import sqlite3
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PIN_TYPES = ("bug", "change", "question")
PIN_STATUSES = ("open", "ai-fixed", "confirmed")
ROLES = {"viewer": 1, "member": 2, "admin": 3}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE,
  role TEXT,
  token_hash TEXT UNIQUE,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS notes (
  id TEXT PRIMARY KEY,
  project_id INTEGER,
  body TEXT,
  screenshot TEXT,
  created_at TEXT,
  user_name TEXT
);
CREATE TABLE IF NOT EXISTS pins (
  id INTEGER PRIMARY KEY,
  project_id INTEGER,
  note_id TEXT,
  pin_id INTEGER,
  x_px INTEGER,
  y_px INTEGER,
  pin_type TEXT,
  status TEXT,
  note TEXT,
  assignee TEXT,
  ocr TEXT,
  created_at TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS comments (
  id INTEGER PRIMARY KEY,
  pin_row INTEGER,
  author TEXT,
  body TEXT,
  created_at TEXT
);
"""

BOARD_HTML = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>DingAI team</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 body{margin:0;font-family:-apple-system,"PingFang SC",sans-serif;background:#f4f5f7;color:#1c1e21}
 header{background:#1c2430;color:#fff;padding:10px 18px;display:flex;gap:10px;align-items:center}
 header b{font-size:15px} input,select,button{font:12px sans-serif}
 main{display:flex;height:calc(100vh - 48px)}
 #list{width:360px;overflow:auto;background:#fff;border-right:1px solid #e2e4e8}
 .pin{padding:10px 12px;border-bottom:1px solid #f0f1f3;cursor:pointer}
 .pin.on{background:#eef3fb} .m{color:#777;font-size:11px;margin-top:3px}
 #detail{flex:1;overflow:auto;padding:14px}
 img{max-width:100%;height:auto} textarea{width:100%;min-height:64px}
 .tag{display:inline-block;background:#e8eefb;border-radius:4px;padding:1px 6px;margin-right:4px;font-size:11px}
</style></head><body>
<header>
 <b>DingAI team</b>
 <input id="tok" placeholder="bearer token" size="28">
 <select id="st"><option value="">status</option><option>open</option><option>ai-fixed</option><option>confirmed</option></select>
 <select id="ty"><option value="">type</option><option>bug</option><option>change</option><option>question</option></select>
 <button id="go" type="button">Refresh</button>
 <span id="cnt"></span>
</header>
<main><div id="list"></div><div id="detail">Select a pin.</div></main>
<script>
 const tok = document.getElementById('tok');
 try { tok.value = sessionStorage.getItem('dingai-token') || ''; } catch (e) {}
 tok.onchange = function () { try { sessionStorage.setItem('dingai-token', tok.value); } catch (e) {} };
 function headers() { return tok.value ? {Authorization: 'Bearer ' + tok.value} : {}; }
 function esc(s){return String(s==null?'':s).replace(/[&<>"]/g, function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
 async function load(){
   const q = new URLSearchParams();
   if (document.getElementById('st').value) q.set('status', document.getElementById('st').value);
   if (document.getElementById('ty').value) q.set('type', document.getElementById('ty').value);
   const rows = await (await fetch('/api/pins?' + q.toString(), {headers: headers()})).json();
   document.getElementById('cnt').textContent = (rows.length || 0) + ' pins';
   const L = document.getElementById('list');
   L.innerHTML = (rows||[]).map(p => '<div class="pin" data-id="'+p.id+'"><b>'+esc(p.pin_type)+'</b> · '+esc(p.status)+
     '<div class="m">#'+p.pin_id+' '+esc(p.project)+' · '+esc(p.assignee||'')+' · '+esc((p.note||'').slice(0,80))+'</div></div>').join('');
   L.querySelectorAll('.pin').forEach(el => el.onclick = function(){ show(el.dataset.id, el); });
 }
 async function show(id, el){
   document.querySelectorAll('.pin').forEach(n => n.classList.remove('on'));
   if (el) el.classList.add('on');
   const p = await (await fetch('/api/pins/' + id, {headers: headers()})).json();
   const before = p.screenshot ? '<figure><figcaption>before</figcaption><img src="/api/shot/'+encodeURIComponent(p.screenshot)+'" alt=""></figure>' : '';
   const after = p.verification ? '<figure><figcaption>after</figcaption><img src="/api/shot/'+encodeURIComponent(p.verification)+'" alt=""></figure>' : '';
   const over = p.verification ? '<figure><figcaption>overlay</figcaption><img src="/api/diff/'+p.id+'" alt=""></figure>' : '';
   const comments = (p.comments||[]).map(c => '<div class="m"><b>'+esc(c.author)+'</b> '+esc(c.body)+'</div>').join('');
   document.getElementById('detail').innerHTML = before + after + over +
     '<p><span class="tag">'+esc(p.pin_type)+'</span><span class="tag">'+esc(p.status)+'</span> '+esc(p.note||'')+'</p>' +
     '<p class="m">'+p.x_px+','+p.y_px+' · '+esc(p.ocr||'')+'</p>' + comments +
     '<p><button type="button" data-s="ai-fixed">Mark AI-fixed</button> <button type="button" data-s="confirmed">Confirm</button> <button type="button" data-s="open">Reopen</button></p>' +
     '<textarea id="cmt"></textarea><button id="send" type="button">Comment</button>';
   document.querySelectorAll('#detail button[data-s]').forEach(b => b.onclick = async function(){
     await fetch('/api/pins/' + id + '/status', {method:'POST', headers:Object.assign({'Content-Type':'application/json'}, headers()), body: JSON.stringify({status: b.dataset.s})});
     load(); show(id);
   });
   document.getElementById('send').onclick = async function(){
     await fetch('/api/pins/' + id + '/comments', {method:'POST', headers:Object.assign({'Content-Type':'application/json'}, headers()), body: JSON.stringify({body: document.getElementById('cmt').value})});
     show(id);
   };
 }
 document.getElementById('go').onclick = load;
 load();
</script></body></html>"""


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def verification_name(row):
    name = "verify-%s-%s.png" % (row["note_id"], row["pin_id"])
    if (root_dir() / "shots" / name).is_file():
        return name
    return ""


def root_dir():
    env = os.environ.get("DINGAI_TEAM_ROOT")
    return Path(env) if env else Path.home() / "anno-team"


def sha(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def connect():
    root = root_dir()
    root.mkdir(parents=True, exist_ok=True)
    (root / "notes").mkdir(exist_ok=True)
    (root / "shots").mkdir(exist_ok=True)
    conn = sqlite3.connect(root / "dingai.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.execute("INSERT OR IGNORE INTO projects(name, created_at) VALUES ('inbox', ?)", (now(),))
    if conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"] == 0:
        provided = os.environ.get("DINGAI_TEAM_ADMIN_TOKEN")
        token = provided or secrets.token_urlsafe(24)
        conn.execute(
            "INSERT INTO users(name, role, token_hash, created_at) VALUES (?,?,?,?)",
            ("admin", "admin", sha(token), now()),
        )
        if provided:
            print("DingAI admin uses DINGAI_TEAM_ADMIN_TOKEN", flush=True)
        else:
            print("DingAI admin token (shown once, not written to the repo):", token, flush=True)
    conn.commit()
    return conn


def project_id(conn, name):
    name = name or "inbox"
    row = conn.execute("SELECT id FROM projects WHERE name=?", (name,)).fetchone()
    if row:
        return row["id"]
    conn.execute("INSERT INTO projects(name, created_at) VALUES (?,?)", (name, now()))
    conn.commit()
    return conn.execute("SELECT id FROM projects WHERE name=?", (name,)).fetchone()["id"]


def user_from_header(conn, header):
    if not header or not header.startswith("Bearer "):
        return None
    token = header.split(" ", 1)[1].strip()
    if not token:
        return None
    return conn.execute("SELECT id, name, role FROM users WHERE token_hash=?", (sha(token),)).fetchone()


def pin_public(row, project_name):
    return {
        "id": row["id"],
        "project": project_name,
        "note_id": row["note_id"],
        "pin_id": row["pin_id"],
        "x_px": row["x_px"],
        "y_px": row["y_px"],
        "pin_type": row["pin_type"],
        "status": row["status"],
        "note": row["note"],
        "assignee": row["assignee"],
        "ocr": row["ocr"],
        "screenshot": row["screenshot"] if "screenshot" in row.keys() else "",
        "updated_at": row["updated_at"],
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(time.strftime("%m-%d %H:%M:%S"), self.address_string(), fmt % args)

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _json(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(n) if n else b""
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _auth(self, conn, need="viewer"):
        user = user_from_header(conn, self.headers.get("Authorization"))
        if user is None:
            if os.environ.get("DINGAI_TEAM_REQUIRE_AUTH") == "1":
                self._send(401, '{"error":"auth required"}')
                return None
            return {"id": 0, "name": "anonymous", "role": "member"}
        if ROLES.get(user["role"], 0) < ROLES[need]:
            self._send(403, '{"error":"forbidden"}')
            return None
        return user

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        if path in ("/", "/index.html"):
            return self._send(200, BOARD_HTML, "text/html; charset=utf-8")
        conn = connect()
        try:
            if path == "/api/notes":
                if self._auth(conn, "viewer") is None:
                    return
                limit = int((qs.get("limit") or ["300"])[0] or 300)
                rows = conn.execute(
                    "SELECT n.id, n.screenshot, n.created_at, n.user_name, p.name AS project FROM notes n JOIN projects p ON p.id=n.project_id ORDER BY n.created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                out = [{"file": r["id"] + ".json", "ts": r["created_at"], "user": r["user_name"], "app": r["project"], "pin_count": 0, "arrow_count": 0, "box_count": 0} for r in rows]
                return self._send(200, json.dumps(out))
            if path.startswith("/api/note/"):
                if self._auth(conn, "viewer") is None:
                    return
                name = os.path.basename(path)
                file = root_dir() / "notes" / name
                if file.exists():
                    return self._send(200, file.read_text(encoding="utf-8"))
                return self._send(404, '{"error":"not found"}')
            if path.startswith("/api/diff/"):
                if self._auth(conn, "viewer") is None:
                    return
                overlay = self._overlay(conn, os.path.basename(path))
                if overlay:
                    return self._send(200, overlay, "image/png")
                return self._send(404, b"", "text/plain")
            if path.startswith("/api/shot/"):
                name = os.path.basename(path)
                file = root_dir() / "shots" / name
                if file.exists():
                    return self._send(200, file.read_bytes(), "image/png")
                return self._send(404, b"", "text/plain")
            if path == "/api/projects":
                if self._auth(conn, "viewer") is None:
                    return
                rows = conn.execute("SELECT name, created_at FROM projects ORDER BY name").fetchall()
                return self._send(200, json.dumps([dict(r) for r in rows]))
            if path == "/api/pins":
                if self._auth(conn, "viewer") is None:
                    return
                return self._send(200, json.dumps(self._pin_list(conn, qs)))
            if path.startswith("/api/pins/") and path.count("/") == 3:
                if self._auth(conn, "viewer") is None:
                    return
                row_id = path.split("/")[-1]
                return self._pin_detail(conn, row_id)
            self._send(404, '{"error":"bad path"}')
        finally:
            conn.close()

    def _overlay(self, conn, row_id):
        row = conn.execute(
            "SELECT pins.note_id, pins.pin_id, notes.screenshot FROM pins LEFT JOIN notes ON notes.id=pins.note_id WHERE pins.id=?",
            (row_id,),
        ).fetchone()
        if not row:
            return b""
        before_name = row["screenshot"] or ""
        after_name = verification_name(row)
        if not before_name or not after_name:
            return b""
        try:
            from core.diff import compare_png
            before = (root_dir() / "shots" / os.path.basename(before_name)).read_bytes()
            after = (root_dir() / "shots" / after_name).read_bytes()
            result = compare_png(before, after)
        except (OSError, ImportError):
            return b""
        return result["overlay"] if result else b""

    def _pin_list(self, conn, qs):
        sql = "SELECT pins.*, projects.name AS project, notes.screenshot FROM pins JOIN projects ON projects.id=pins.project_id LEFT JOIN notes ON notes.id=pins.note_id WHERE 1=1"
        args = []
        if qs.get("project"):
            sql += " AND projects.name=?"
            args.append(qs["project"][0])
        if qs.get("status"):
            sql += " AND pins.status=?"
            args.append(qs["status"][0])
        if qs.get("type"):
            sql += " AND pins.pin_type=?"
            args.append(qs["type"][0])
        if qs.get("assignee"):
            sql += " AND pins.assignee=?"
            args.append(qs["assignee"][0])
        sql += " ORDER BY pins.updated_at DESC LIMIT 500"
        rows = []
        for row in conn.execute(sql, args):
            item = pin_public(row, row["project"])
            item["screenshot"] = row["screenshot"] or ""
            item["verification"] = verification_name(row)
            rows.append(item)
        return rows

    def _pin_detail(self, conn, row_id):
        row = conn.execute(
            "SELECT pins.*, projects.name AS project, notes.screenshot FROM pins JOIN projects ON projects.id=pins.project_id LEFT JOIN notes ON notes.id=pins.note_id WHERE pins.id=?",
            (row_id,),
        ).fetchone()
        if not row:
            return self._send(404, '{"error":"not found"}')
        item = pin_public(row, row["project"])
        item["screenshot"] = row["screenshot"] or ""
        item["verification"] = verification_name(row)
        comments = conn.execute("SELECT author, body, created_at FROM comments WHERE pin_row=? ORDER BY id", (row["id"],)).fetchall()
        item["comments"] = [dict(c) for c in comments]
        return self._send(200, json.dumps(item))

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        conn = connect()
        try:
            if path == "/api/note":
                user = self._auth(conn, "member")
                if user is None:
                    return
                try:
                    data = self._json()
                except (json.JSONDecodeError, UnicodeError):
                    return self._send(400, '{"error":"bad json"}')
                return self._save_note(conn, data, user)
            if path.startswith("/api/shot/"):
                user = self._auth(conn, "member")
                if user is None:
                    return
                name = os.path.basename(path)
                if not name.endswith(".png"):
                    return self._send(400, '{"error":"png only"}')
                n = int(self.headers.get("Content-Length", 0) or 0)
                (root_dir() / "shots" / name).write_bytes(self.rfile.read(n))
                return self._send(200, '{"ok":true}')
            if path == "/api/projects":
                user = self._auth(conn, "admin")
                if user is None:
                    return
                body = self._json()
                name = (body.get("name") or "").strip()
                if not name:
                    return self._send(400, '{"error":"name required"}')
                project_id(conn, name)
                return self._send(200, json.dumps({"name": name}))
            if path == "/api/users":
                user = self._auth(conn, "admin")
                if user is None:
                    return
                body = self._json()
                name = (body.get("name") or "").strip()
                role = body.get("role") or "member"
                if role not in ROLES or not name:
                    return self._send(400, '{"error":"bad user"}')
                token = secrets.token_urlsafe(24)
                conn.execute(
                    "INSERT INTO users(name, role, token_hash, created_at) VALUES (?,?,?,?)",
                    (name, role, sha(token), now()),
                )
                conn.commit()
                return self._send(200, json.dumps({"name": name, "role": role, "token": token}))
            if path.startswith("/api/pins/by-note/"):
                return self._pin_action(conn, path)
            if path.startswith("/api/pins/") and path.endswith("/status"):
                return self._status_by_row(conn, path)
            if path.startswith("/api/pins/") and path.endswith("/comments"):
                return self._comment_by_row(conn, path)
            self._send(404, '{"error":"bad path"}')
        finally:
            conn.close()

    def _save_note(self, conn, data, user):
        project = data.get("project") or "inbox"
        pid = project_id(conn, project)
        note_id = "anno-%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), uuid.uuid4().hex[:6])
        data = dict(data)
        data["file"] = note_id + ".json"
        (root_dir() / "notes" / data["file"]).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        shot = os.path.basename(str(data.get("screenshot") or ""))
        conn.execute(
            "INSERT INTO notes(id, project_id, body, screenshot, created_at, user_name) VALUES (?,?,?,?,?,?)",
            (note_id, pid, json.dumps(data, ensure_ascii=False), shot, now(), user["name"]),
        )
        for pin in data.get("pins") or []:
            kind = pin.get("pin_type") if pin.get("pin_type") in PIN_TYPES else "bug"
            status = pin.get("status") if pin.get("status") in PIN_STATUSES else "open"
            conn.execute(
                "INSERT INTO pins(project_id, note_id, pin_id, x_px, y_px, pin_type, status, note, assignee, ocr, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (pid, note_id, int(pin.get("id") or 0), int(pin.get("x_px") or 0), int(pin.get("y_px") or 0),
                 kind, status, pin.get("note") or "", pin.get("assignee") or "", pin.get("ocr_nearby") or "", now(), now()),
            )
        conn.commit()
        ledger = root_dir() / "ledger.jsonl"
        row = {"file": data["file"], "ts": time.strftime("%m-%d %H:%M"), "machine": data.get("machine"),
               "user": data.get("user"), "app": (data.get("app") or {}).get("name"),
               "pin_count": data.get("pin_count", len(data.get("pins") or [])),
               "arrow_count": data.get("arrow_count", 0), "box_count": data.get("box_count", 0),
               "note0": next((p.get("note") or "" for p in data.get("pins") or [] if p.get("note")), "")}
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return self._send(200, json.dumps({"id": note_id, "shot_name": shot}))

    def _find_pin(self, conn, note_id, pin_id, project):
        return conn.execute(
            "SELECT pins.* FROM pins JOIN projects ON projects.id=pins.project_id WHERE pins.note_id=? AND pins.pin_id=? AND projects.name=?",
            (note_id, int(pin_id), project or "inbox"),
        ).fetchone()

    def _apply_status(self, conn, row, status, user):
        if status not in PIN_STATUSES:
            self._send(400, '{"error":"bad status"}')
            return False
        current = row["status"]
        role = ROLES.get(user["role"], 0)
        allowed = {
            ("open", "ai-fixed"): 2,
            ("ai-fixed", "confirmed"): 2,
            ("open", "confirmed"): 3,
            ("ai-fixed", "open"): 3,
            ("confirmed", "open"): 3,
        }
        need = allowed.get((current, status))
        if need is None or role < need:
            self._send(409, '{"error":"status change refused"}')
            return False
        conn.execute("UPDATE pins SET status=?, updated_at=? WHERE id=?", (status, now(), row["id"]))
        conn.commit()
        return True

    def _pin_action(self, conn, path):
        # /api/pins/by-note/<note>/<pin>/status|comments|verification
        parts = path.strip("/").split("/")
        if len(parts) != 6:
            return self._send(404, '{"error":"bad path"}')
        _, _, _, note_id, pin_id, action = parts
        if action == "status":
            user = self._auth(conn, "member")
            if user is None:
                return
            body = self._json()
            row = self._find_pin(conn, note_id, pin_id, body.get("project") or "inbox")
            if not row:
                return self._send(404, '{"error":"not found"}')
            if body.get("assignee") is not None and ROLES.get(user["role"], 0) >= 2:
                conn.execute("UPDATE pins SET assignee=?, updated_at=? WHERE id=?", (body.get("assignee") or "", now(), row["id"]))
                conn.commit()
            if not self._apply_status(conn, row, body.get("status"), user):
                return
            if body.get("comment"):
                conn.execute("INSERT INTO comments(pin_row, author, body, created_at) VALUES (?,?,?,?)", (row["id"], user["name"], body["comment"], now()))
                conn.commit()
            return self._send(200, '{"ok":true}')
        if action == "comments":
            user = self._auth(conn, "member")
            if user is None:
                return
            body = self._json()
            row = self._find_pin(conn, note_id, pin_id, body.get("project") or "inbox")
            if not row:
                return self._send(404, '{"error":"not found"}')
            conn.execute("INSERT INTO comments(pin_row, author, body, created_at) VALUES (?,?,?,?)", (row["id"], user["name"], body.get("body") or "", now()))
            conn.commit()
            return self._send(200, '{"ok":true}')
        if action == "verification":
            user = self._auth(conn, "member")
            if user is None:
                return
            n = int(self.headers.get("Content-Length", 0) or 0)
            blob = self.rfile.read(n)
            project = parse_qs(urlparse(self.path).query).get("project", ["inbox"])[0]
            row = self._find_pin(conn, note_id, pin_id, project)
            if not row:
                return self._send(404, '{"error":"not found"}')
            name = "verify-%s-%s.png" % (note_id, pin_id)
            (root_dir() / "shots" / name).write_bytes(blob)
            if row["status"] == "open":
                self._apply_status(conn, row, "ai-fixed", user)
            return self._send(200, json.dumps({"ok": True, "screenshot": name}))
        return self._send(404, '{"error":"bad path"}')

    def _status_by_row(self, conn, path):
        user = self._auth(conn, "member")
        if user is None:
            return
        row_id = path.split("/")[3]
        row = conn.execute("SELECT * FROM pins WHERE id=?", (row_id,)).fetchone()
        if not row:
            return self._send(404, '{"error":"not found"}')
        body = self._json()
        if not self._apply_status(conn, row, body.get("status"), user):
            return
        return self._send(200, '{"ok":true}')

    def _comment_by_row(self, conn, path):
        user = self._auth(conn, "member")
        if user is None:
            return
        row_id = path.split("/")[3]
        body = self._json()
        conn.execute("INSERT INTO comments(pin_row, author, body, created_at) VALUES (?,?,?,?)", (row_id, user["name"], body.get("body") or "", now()))
        conn.commit()
        return self._send(200, '{"ok":true}')


def serve():
    host = os.environ.get("DINGAI_TEAM_HOST", os.environ.get("ANNO_TEAM_HOST", "127.0.0.1"))
    port = int(os.environ.get("DINGAI_TEAM_PORT", os.environ.get("ANNO_TEAM_PORT", "8050")))
    connect().close()
    print("DingAI team server on %s:%s, root = %s" % (host, port, root_dir()))
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    serve()
