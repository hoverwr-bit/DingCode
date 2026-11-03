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
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import collide as collide_lib
from core import edition as edition_lib
from core import release as release_lib

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
CREATE TABLE IF NOT EXISTS licenses (
  id INTEGER PRIMARY KEY,
  key_hash TEXT UNIQUE,
  key_preview TEXT,
  edition TEXT,
  expires TEXT,
  seats INTEGER DEFAULT 1,
  seats_used INTEGER DEFAULT 0,
  machines TEXT DEFAULT '[]',
  issued_by TEXT,
  revoked INTEGER DEFAULT 0,
  created_at TEXT,
  revoked_at TEXT
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
 <a href="/releases" style="color:#fff">Releases</a>
 <a href="/licenses" style="color:#fff">Licenses</a>
 <span id="cnt"></span>
</header>
<div id="banner" style="display:none;background:#ffe08a;color:#1c1e21;padding:8px 18px;font-size:13px"></div>
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
   try {
     const note = await (await fetch('/api/notices', {headers: headers()})).json();
     const el = document.getElementById('banner');
     const text = (note.banners || []).map(function (b) { return b.text; }).filter(Boolean).join(' · ');
     el.style.display = text ? 'block' : 'none';
     el.textContent = text;
   } catch (e) {}
   const L = document.getElementById('list');
   L.innerHTML = (rows||[]).map(p => '<div class="pin" data-id="'+p.id+'"><b>'+esc(p.pin_type)+'</b> · '+esc(p.status)+
     '<div class="m">#'+p.pin_id+' '+esc(p.project)+' · '+esc(p.assignee||'')+' · '+esc((p.note||'').slice(0,80))+'</div></div>').join('');
   L.querySelectorAll('.pin').forEach(el => el.onclick = function(){ show(el.dataset.id, el); });
 }
 async function show(id, el){
   document.querySelectorAll('.pin').forEach(n => n.classList.remove('on'));
   if (el) el.classList.add('on');
   const p = await (await fetch('/api/pins/' + id, {headers: headers()})).json();
   const shot = p.screenshot ? '<img src="/api/shot/'+encodeURIComponent(p.screenshot)+'" alt="">' : '';
   const comments = (p.comments||[]).map(c => '<div class="m"><b>'+esc(c.author)+'</b> '+esc(c.body)+'</div>').join('');
   document.getElementById('detail').innerHTML = shot +
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

LICENSES_HTML = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>DingCode licenses</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 body{margin:0;font-family:-apple-system,"PingFang SC",sans-serif;background:#f4f5f7;color:#1c1e21}
 header{background:#1c2430;color:#fff;padding:10px 18px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
 header b{font-size:15px} input,select,button{font:12px sans-serif}
 main{padding:16px;max-width:900px;margin:0 auto}
 .card{background:#fff;border:1px solid #e2e4e8;border-radius:8px;padding:14px;margin-bottom:14px}
 table{width:100%;border-collapse:collapse;font-size:12px}
 th,td{padding:7px 9px;border-bottom:1px solid #f0f1f3;text-align:left}
 th{color:#777;font-weight:500}
 .tag{display:inline-block;background:#e8eefb;border-radius:4px;padding:1px 6px;font-size:11px}
 .tag.revoked{background:#fde8e8;color:#b91c1c}
 .tag.ok{background:#e8f7ee;color:#15803d}
 .keybox{font:13px monospace;background:#f6f8fa;border:1px dashed #94a3b8;border-radius:6px;padding:10px;margin-top:8px;word-break:break-all}
 .muted{color:#777;font-size:12px}
</style></head><body>
<header>
 <b>DingCode Licenses</b>
 <input id="tok" placeholder="admin bearer token" size="28">
 <a href="/" style="color:#fff">← Board</a>
 <span id="msg" class="muted"></span>
</header>
<main>
 <div class="card">
  <b>签发新密钥</b>
  <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap">
   <select id="ed"><option value="pro">pro</option><option value="team">team</option></select>
   <input id="ex" placeholder="到期日 yyyymmdd，终身填 99991231" size="24" value="99991231">
   <input id="se" placeholder="席位" size="4" value="1">
   <button id="issue" type="button">签发</button>
  </div>
  <div id="newKey"></div>
 </div>
 <div class="card">
  <b>已签发 (<span id="cnt">0</span>)</b>
  <table><tr><th>#</th><th>密钥</th><th>版本</th><th>到期</th><th>席位</th><th>状态</th><th>签发人</th><th>时间</th><th></th></tr>
  <tbody id="rows"></tbody></table>
 </div>
</main>
<script>
 const tok = document.getElementById('tok');
 try { tok.value = sessionStorage.getItem('dingai-token') || ''; } catch (e) {}
 tok.onchange = function () { try { sessionStorage.setItem('dingai-token', tok.value); } catch (e) {} };
 function headers() { return tok.value ? {Authorization: 'Bearer ' + tok.value} : {}; }
 function esc(s){return String(s==null?'':s).replace(/[&<>"]/g, function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
 async function load(){
   const r = await fetch('/api/licenses', {headers: headers()});
   if (r.status === 403) { document.getElementById('msg').textContent = '需要管理员 token'; return; }
   const rows = await r.json();
   document.getElementById('msg').textContent = '';
   document.getElementById('cnt').textContent = rows.length;
   document.getElementById('rows').innerHTML = rows.map(function(x){
     const state = x.revoked ? '<span class="tag revoked">已吊销</span>'
       : (x.seats_used >= x.seats ? '<span class="tag revoked">席位已满</span>' : '<span class="tag ok">有效</span>');
     return '<tr><td>'+x.id+'</td><td style="font-family:monospace">'+esc(x.key_preview)+'</td><td>'+esc(x.edition)+'</td>'+
       '<td>'+esc(x.expires)+'</td><td>'+x.seats_used+'/'+x.seats+'</td><td>'+state+'</td>'+
       '<td>'+esc(x.issued_by||'')+'</td><td class="muted">'+esc(x.created_at||'')+'</td>'+
       '<td>'+(x.revoked ? '' : '<button type="button" onclick="revoke('+x.id+')">吊销</button>')+'</td></tr>';
   }).join('');
 }
 async function revoke(id){
   if (!confirm('吊销 #' + id + '？该密钥所有端立即失效。')) return;
   await fetch('/api/licenses/revoke', {method:'POST', headers:Object.assign({'Content-Type':'application/json'}, headers()), body: JSON.stringify({id:id})});
   load();
 }
 document.getElementById('issue').onclick = async function(){
   const body = {edition: document.getElementById('ed').value, expires: document.getElementById('ex').value.trim(), seats: parseInt(document.getElementById('se').value || '1', 10)};
   const r = await fetch('/api/license/issue', {method:'POST', headers:Object.assign({'Content-Type':'application/json'}, headers()), body: JSON.stringify(body)});
   const data = await r.json();
   if (!r.ok) { alert('签发失败: ' + (data.error || r.status)); return; }
   document.getElementById('newKey').innerHTML = '<div class="keybox">'+esc(data.key)+'</div><div class="muted">只显示这一次，请立即复制发给客户。</div>';
   load();
 };
 load();
</script></body></html>"""


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---- 许可证（团队版席位管理）----

def _license_preview(key):
    return key[:18] + "…" + key[-4:]


def license_issue(conn, edition, expires, seats, issued_by):
    """签发密钥并登记。密钥只在本次响应里完整出现一次，库中只存哈希。"""
    key = edition_lib.issue_key(edition, expires)
    try:
        conn.execute(
            "INSERT INTO licenses(key_hash, key_preview, edition, expires, seats, issued_by, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (sha(key), _license_preview(key), edition, expires, max(1, int(seats or 1)), issued_by, now()),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # 极小概率哈希碰撞重试由调用方处理
    return key


def license_list(conn):
    rows = conn.execute(
        "SELECT id, key_preview, edition, expires, seats, seats_used, machines, issued_by, revoked, created_at, revoked_at"
        " FROM licenses ORDER BY id DESC"
    ).fetchall()
    out = []
    for row in rows:
        machines = json.loads(row[6] or "[]")
        out.append({
            "id": row[0], "key_preview": row[1], "edition": row[2], "expires": row[3],
            "seats": row[4], "seats_used": row[5], "machines": len(machines),
            "issued_by": row[7], "revoked": bool(row[8]),
            "created_at": row[9], "revoked_at": row[10],
        })
    return out


def _license_by_key(conn, key):
    return conn.execute(
        "SELECT id, edition, expires, seats, seats_used, machines, revoked FROM licenses WHERE key_hash = ?",
        (sha(key),),
    ).fetchone()


def license_verify(conn, key):
    """客户端在线核验：HMAC 合法 + 未吊销 + 未过期 + 席位未满。"""
    edition, expires = edition_lib.parse_key(key)
    if not edition:
        return {"ok": False, "error": "bad key"}
    row = _license_by_key(conn, key)
    if row is None:
        return {"ok": False, "error": "unknown key"}
    if row[6]:
        return {"ok": False, "error": "revoked"}
    if edition_lib._expired(row[2]):
        return {"ok": False, "error": "expired", "expires": row[2]}
    if int(row[4]) >= int(row[3]):
        return {"ok": False, "error": "seats full", "seats": row[3], "seats_used": row[4]}
    return {"ok": True, "edition": row[1], "expires": row[2], "seats": row[3], "seats_used": row[4]}


def license_activate(conn, key, machine):
    """席位激活；同一 machine 重复激活幂等。返回 (ok, error)。"""
    row = _license_by_key(conn, key)
    if row is None:
        return False, "unknown key"
    machines = json.loads(row[5] or "[]")
    machine = (machine or "unknown")[:64]
    if machine in machines:
        return True, ""
    if row[6]:
        return False, "revoked"
    if edition_lib._expired(row[2]):
        return False, "expired"
    if len(machines) >= int(row[3]):
        return False, "seats full"
    machines.append(machine)
    conn.execute("UPDATE licenses SET machines = ?, seats_used = ? WHERE id = ?",
                 (json.dumps(machines), len(machines), row[0]))
    conn.commit()
    return True, ""


def license_revoke(conn, license_id):
    cur = conn.execute("UPDATE licenses SET revoked = 1, revoked_at = ? WHERE id = ? AND revoked = 0",
                       (now(), int(license_id)))
    conn.commit()
    return cur.rowcount > 0


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

    def _auth_admin(self, conn):
        """许可证管理的严格鉴权：即使未开 REQUIRE_AUTH，也必须出示管理员 token，
        不允许 anonymous 越权签发/吊销密钥。"""
        user = user_from_header(conn, self.headers.get("Authorization"))
        if user is None:
            self._send(401, '{"error":"admin token required"}')
            return None
        if ROLES.get(user["role"], 0) < ROLES["admin"]:
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
        if path == "/licenses":
            return self._send(200, LICENSES_HTML, "text/html; charset=utf-8")
        conn = connect()
        try:
            if path == "/api/license/verify":
                key = (qs.get("key") or [""])[0]
                return self._send(200, json.dumps(license_verify(conn, key)))
            if path == "/api/licenses":
                if self._auth_admin(conn) is None:
                    return
                return self._send(200, json.dumps(license_list(conn)))
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
            if path == "/api/releases" or path.startswith("/api/releases/") or path == "/releases" or path.startswith("/release/"):
                if self._auth(conn, "viewer") is None:
                    return
                if path.startswith("/release/"):
                    return self._release_page(path)
                if path == "/releases":
                    return self._send(200, release_lib.index_html(release_lib.list_releases(state_dir())), "text/html; charset=utf-8")
                return self._release_get(path, qs)
            if path == "/api/notices":
                if self._auth(conn, "viewer") is None:
                    return
                return self._send(200, json.dumps(collide_lib.read_notices(state_dir())))
            if path == "/api/sessions" or path.startswith("/api/sessions/"):
                if self._auth(conn, "viewer") is None:
                    return
                return self._sessions_get(path)
            self._send(404, '{"error":"bad path"}')
        finally:
            conn.close()

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
            if path == "/api/license/issue":
                # 团队版授权：管理员签发 DGA1 密钥并登记席位。密钥只在响应里完整出现一次。
                user = self._auth_admin(conn)
                if user is None:
                    return
                body = self._json()
                edition = (body.get("edition") or "pro").lower()
                expires = str(body.get("expires") or "").strip()
                seats = body.get("seats") or 1
                if edition not in ("pro", "team") or not (len(expires) == 8 and expires.isdigit()):
                    return self._send(400, '{"error":"edition (pro|team), expires yyyymmdd and optional seats required"}')
                key = license_issue(conn, edition, expires, seats, user["name"])
                return self._send(200, json.dumps({"edition": edition, "expires": expires,
                                                   "seats": max(1, int(seats or 1)), "key": key}))
            if path == "/api/licenses/revoke":
                user = self._auth_admin(conn)
                if user is None:
                    return
                body = self._json()
                if license_revoke(conn, body.get("id")):
                    return self._send(200, '{"ok":true}')
                return self._send(404, '{"error":"not found or already revoked"}')
            if path == "/api/license/activate":
                body = self._json()
                ok, error = license_activate(conn, str(body.get("key") or ""), str(body.get("machine") or ""))
                return self._send(200 if ok else 403, json.dumps({"ok": ok, "error": error}))
            if path.startswith("/api/pins/by-note/"):
                return self._pin_action(conn, path)
            if path.startswith("/api/pins/") and path.endswith("/status"):
                return self._status_by_row(conn, path)
            if path.startswith("/api/pins/") and path.endswith("/comments"):
                return self._comment_by_row(conn, path)
            if path == "/api/releases" or path.startswith("/api/releases/"):
                return self._release_post(conn, path)
            if path == "/api/sessions" or path.startswith("/api/sessions/"):
                return self._sessions_post(conn, path)
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


def state_dir():
    path = root_dir() / "state"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _release_methods():
    def _release_page(self, path):
        parts = [part for part in path.split("/") if part]
        if len(parts) < 2 or not release_lib.safe_release_id(parts[1]):
            return self._send(404, '{"error":"not found"}')
        if len(parts) == 2 and not path.endswith("/"):
            self.send_response(302)
            self.send_header("Location", path + "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        name = "review.html" if len(parts) == 2 else parts[2]
        if not release_lib.safe_file_name(name):
            return self._send(404, '{"error":"not found"}')
        file = state_dir() / "releases" / parts[1] / name
        if not file.is_file():
            return self._send(404, '{"error":"not found"}')
        if name.endswith(".html"):
            ctype = "text/html; charset=utf-8"
        elif name.endswith(".png"):
            ctype = "image/png"
        elif name.endswith(".json"):
            ctype = "application/json; charset=utf-8"
        else:
            ctype = "application/octet-stream"
        return self._send(200, file.read_bytes(), ctype)

    def _release_get(self, path, qs):
        parts = [part for part in path.split("/") if part]
        if parts == ["api", "releases"]:
            return self._send(200, json.dumps(release_lib.search_releases(state_dir(), (qs.get("q") or [""])[0])))
        if len(parts) == 4 and parts[3] == "export":
            fmt = (qs.get("format") or ["zip"])[0]
            dest = state_dir() / "exports"
            dest.mkdir(parents=True, exist_ok=True)
            result = release_lib.export_release(state_dir(), parts[2], fmt, str(dest))
            if not result.get("ok"):
                return self._send(404, json.dumps(result))
            ctype = "application/zip" if fmt == "zip" else "text/markdown; charset=utf-8"
            return self._send(200, Path(result["path"]).read_bytes(), ctype)
        if len(parts) == 3:
            rel = release_lib.load_release(state_dir(), parts[2])
            if not rel:
                return self._send(404, '{"error":"not found"}')
            return self._send(200, json.dumps(rel))
        return self._send(404, '{"error":"bad path"}')

    def _release_post(self, conn, path):
        user = self._auth(conn, "member")
        if user is None:
            return
        parts = [part for part in path.split("/") if part]
        try:
            body = self._json()
        except (json.JSONDecodeError, UnicodeError):
            return self._send(400, '{"error":"bad json"}')
        if parts == ["api", "releases"]:
            pins = body.get("pins") or []
            shots = {}
            for pin in pins:
                key = pin.get("key") or release_lib.pin_key(pin.get("note_id") or "note", pin.get("pin_id") if pin.get("pin_id") is not None else pin.get("id"))
                pair = {}
                for side in ("before", "after"):
                    name = os.path.basename(str(pin.get(side) or ""))
                    if name and (root_dir() / "shots" / name).is_file():
                        pair[side] = str(root_dir() / "shots" / name)
                        pin[side] = ""
                if pair:
                    shots[key] = pair
            rel = release_lib.open_release(
                state_dir(), pins, version=body.get("version") or "", tag=body.get("tag") or "",
                project=body.get("project") or "", repo=body.get("repo") or "",
                rules=body.get("rules") or "", diff_summary=body.get("diff_summary") or "",
                scope_warnings=body.get("scope_warnings") or [], head=body.get("head") or "",
                commits=body.get("commits") or [], parent_id=body.get("parent_id") or "", shots=shots,
            )
            return self._send(200, json.dumps({"ok": True, "id": rel["id"]}))
        if len(parts) == 4 and parts[3] == "decide":
            result = release_lib.decide(state_dir(), parts[2], body.get("pin") or body.get("key") or "", body.get("decision") or "", user["name"])
            code = 200 if result.get("ok") else 409
            return self._send(code, json.dumps({k: v for k, v in result.items() if k != "release"}))
        if len(parts) == 4 and parts[3] == "publish":
            admin = ROLES.get(user["role"], 0) >= ROLES["admin"]
            result = release_lib.publish(state_dir(), parts[2], actor=user["name"], admin=admin, override_reason=body.get("override") or body.get("reason") or "")
            code = 200 if result.get("ok") else 409
            return self._send(code, json.dumps({k: v for k, v in result.items() if k != "release"}))
        if len(parts) == 4 and parts[3] == "rollback":
            result = release_lib.rollback(state_dir(), parts[2], actor=user["name"])
            code = 200 if result.get("ok") else 409
            body_out = {"ok": result.get("ok"), "error": result.get("error", ""), "id": (result.get("release") or {}).get("id", ""), "restores": (result.get("release") or {}).get("restores", "")}
            return self._send(code, json.dumps(body_out))
        return self._send(404, '{"error":"bad path"}')

    return _release_page, _release_get, _release_post


Handler._release_page, Handler._release_get, Handler._release_post = _release_methods()


def _session_get(self, path):
    parts = [part for part in path.split("/") if part]
    if parts == ["api", "sessions"]:
        return self._send(200, json.dumps(collide_lib.list_sessions(state_dir())))
    return self._send(404, '{"error":"bad path"}')


def _session_post(self, conn, path):
    user = self._auth(conn, "member")
    if user is None:
        return
    parts = [part for part in path.split("/") if part]
    try:
        body = self._json()
    except (json.JSONDecodeError, UnicodeError):
        return self._send(400, '{"error":"bad json"}')
    if parts == ["api", "sessions"]:
        body = dict(body)
        body["agent"] = body.get("agent") or user["name"]
        result = collide_lib.register(state_dir(), body)
        return self._send(200, json.dumps({
            "ok": True, "id": result["session"]["id"],
            "warnings": result.get("warnings") or [], "banner": result.get("banner") or "",
        }))
    if len(parts) == 4 and parts[3] == "choose":
        result = collide_lib.choose(state_dir(), parts[2], body.get("choice") or "", actor=user["name"])
        code = 200 if result.get("ok") else 409
        return self._send(code, json.dumps({"ok": result.get("ok"), "error": result.get("error", ""), "status": (result.get("session") or {}).get("status", ""), "banner": result.get("banner") or ""}))
    if len(parts) == 4 and parts[3] == "end":
        result = collide_lib.end_session(state_dir(), parts[2])
        code = 200 if result.get("ok") else 404
        return self._send(code, json.dumps({"ok": result.get("ok"), "overlaps": result.get("overlaps") or [], "error": result.get("error", "")}))
    return self._send(404, '{"error":"bad path"}')


Handler._sessions_get = _session_get
Handler._sessions_post = _session_post


def serve():
    host = os.environ.get("DINGAI_TEAM_HOST", os.environ.get("ANNO_TEAM_HOST", "127.0.0.1"))
    port = int(os.environ.get("DINGAI_TEAM_PORT", os.environ.get("ANNO_TEAM_PORT", "8050")))
    connect().close()
    print("DingAI team server on %s:%s, root = %s" % (host, port, root_dir()))
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    serve()
