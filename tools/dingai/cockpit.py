#!/usr/bin/env python3
"""DingCode 驾驶台 (cockpit): 本地管理台，只监听 127.0.0.1。

  python3 cockpit.py [--port 8764]

功能（专业版）：
  - 总览：版本、会话冲突横幅、当前工作流
  - 钉：本机/共享目录/团队服务器的钉子列表与状态
  - 发布：评审、发布、回退（对应 handoff.py release）
  - 工作流：查看/编辑 .dingai/workflow.json，钉过直接执行
"""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PAGE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>DingCode 驾驶台</title>
<style>
body{margin:0;font:14px/1.6 -apple-system,"PingFang SC",sans-serif;background:#0b1220;color:#e2e8f0}
header{padding:14px 22px;background:#101828;border-bottom:1px solid #1e293b;display:flex;gap:16px;align-items:center}
header b{font-size:17px}
.badge{padding:2px 10px;border-radius:99px;font-size:12px;background:#14532d;color:#86efac}
.badge.community{background:#7c2d12;color:#fdba74}
nav{display:flex;gap:4px;padding:10px 22px 0}
nav button{background:none;border:0;color:#94a3b8;padding:8px 14px;cursor:pointer;font-size:14px;border-bottom:2px solid transparent}
nav button.on{color:#fff;border-bottom-color:#2563eb}
main{padding:18px 22px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid #1e293b;vertical-align:top}
th{color:#94a3b8;font-weight:500}
.card{background:#111a2e;border:1px solid #1e293b;border-radius:10px;padding:14px 16px;margin-bottom:16px}
button.act{background:#2563eb;color:#fff;border:0;border-radius:6px;padding:4px 12px;cursor:pointer;font-size:12px;margin-right:6px}
button.warn{background:#b45309}
button.danger{background:#b91c1c}
textarea{width:100%;box-sizing:border-box;background:#0b1220;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:8px;font:12px/1.5 monospace;min-height:140px}
.banner{background:#713f12;color:#fde68a;padding:8px 14px;border-radius:8px;margin-bottom:14px}
.muted{color:#64748b;font-size:12px}
h4{margin:0 0 8px}
pre{white-space:pre-wrap;font:12px/1.5 monospace;background:#0b1220;padding:10px;border-radius:6px;max-height:300px;overflow:auto}
</style>
</head>
<body>
<header><b>DingCode 驾驶台</b><span id="edition" class="badge">…</span><span id="mode" class="muted"></span></header>
<nav>
 <button data-tab="overview" class="on">总览</button>
 <button data-tab="pins">钉</button>
 <button data-tab="releases">发布</button>
 <button data-tab="workflow">工作流</button>
</nav>
<main>
<div id="bannerHost"></div>
<section id="tab-overview"></section>
<section id="tab-pins" style="display:none"></section>
<section id="tab-releases" style="display:none"></section>
<section id="tab-workflow" style="display:none"></section>
</main>
<script>
var TABS=['overview','pins','releases','workflow'];
function tab(name){TABS.forEach(function(t){document.getElementById('tab-'+t).style.display=t===name?'':'none';});
 document.querySelectorAll('nav button').forEach(function(b){b.classList.toggle('on',b.dataset.tab===name);});}
document.querySelectorAll('nav button').forEach(function(b){b.onclick=function(){tab(b.dataset.tab);load(b.dataset.tab);};});
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
function api(path,opts){return fetch(path,opts||{}).then(function(r){return r.json();});}
function load(name){
 if(name==='overview')api('/api/state').then(function(s){
  var ed=s.edition||{};
  var b=document.getElementById('edition');b.textContent=ed.edition||'?';
  b.className='badge '+(ed.edition==='community'?'community':'');
  document.getElementById('mode').textContent='同步模式: '+s.sync_mode+' · 项目: '+s.project;
  document.getElementById('bannerHost').innerHTML=s.banner?'<div class="banner">'+esc(s.banner)+'</div>':'';
  var h='<div class="card"><h4>版本与功能</h4><div class="muted">来源: '+esc(ed.source||'—')+'</div><div style="margin-top:8px">'+
   (ed.features||[]).map(function(f){return '<span class="badge" style="margin-right:6px">'+esc(f)+'</span>';}).join('')+'</div></div>';
  h+='<div class="card"><h4>会话 ('+s.sessions.length+')</h4>'+(s.sessions.length?'<table><tr><th>agent</th><th>repo</th><th>branch</th><th>pins</th><th>状态</th></tr>'+
   s.sessions.map(function(x){return '<tr><td>'+esc(x.agent)+'</td><td>'+esc(x.repo)+'</td><td>'+esc(x.branch)+'</td><td>'+esc((x.pins||[]).join(', '))+'</td><td>'+esc(x.status)+'</td></tr>';}).join('')+'</table>':'<div class="muted">无活动会话</div>')+'</div>';
  document.getElementById('tab-overview').innerHTML=h;});
 if(name==='pins')api('/api/pins').then(function(s){
  var rows=s.pins||[];
  document.getElementById('tab-pins').innerHTML='<div class="card"><h4>钉 ('+rows.length+') · '+esc(s.mode)+'</h4>'+
   (rows.length?'<table><tr><th>pin</th><th>类型</th><th>状态</th><th>备注</th><th>截图</th></tr>'+
   rows.map(function(p){return '<tr><td>'+esc(p.note_id||'')+':'+esc(p.pin_id!==undefined?p.pin_id:'')+'</td><td>'+esc(p.pin_type||'bug')+'</td><td>'+esc(p.status||'open')+'</td><td>'+esc(p.note||'')+'</td><td>'+esc(p.screenshot||'')+'</td></tr>';}).join('')+'</table>':'<div class="muted">暂无钉。在桌面端或页面落钉后刷新。</div>')+'</div>';});
 if(name==='releases')api('/api/releases').then(function(s){
  var rows=s.releases||[];
  document.getElementById('tab-releases').innerHTML='<div class="card"><h4>发布 ('+rows.length+')</h4>'+
   (rows.length?'<table><tr><th>版本</th><th>状态</th><th>钉</th><th>时间</th><th>操作</th></tr>'+
   rows.map(function(r){return '<tr><td>'+esc(r.version||r.id)+'</td><td>'+esc(r.status)+'</td><td>'+(r.pins||[]).length+'</td><td>'+esc(r.opened_at||'')+'</td><td>'+
    (r.status==='draft'?'<button class="act" onclick="pub(\\''+r.id+'\\')">发布</button>':'')+
    '<button class="act danger" onclick="rb(\\''+r.id+'\\')">回退</button></td></tr>';}).join('')+'</table>':'<div class="muted">暂无发布记录。handoff.py release open 创建。</div>')+'</div>';});
 if(name==='workflow')api('/api/workflow').then(function(s){
  document.getElementById('tab-workflow').innerHTML='<div class="card"><h4>工作流 · '+esc(s.path||'(default)')+'</h4>'+
   '<textarea id="wf">'+esc(JSON.stringify(s.workflow,null,2))+'</textarea>'+
   '<div style="margin-top:10px"><button class="act" onclick="saveWf()">保存</button>'+
   '<button class="act warn" onclick="runWf()">粘贴 note JSON 并执行</button></div>'+
   '<div style="margin-top:10px"><textarea id="note" placeholder=\'{"pins":[...]} 留空则从 ~/DingAI 取最新 note\'></textarea></div>'+
   '<pre id="runOut" style="display:none"></pre></div>';});
}
function pub(id){if(!confirm('发布 '+id+' ?'))return;api('/api/release/publish',{method:'POST',body:JSON.stringify({id:id})}).then(function(){load('releases');});}
function rb(id){if(!confirm('回退 '+id+' ?将基于上一发布创建回退草稿。'))return;api('/api/release/rollback',{method:'POST',body:JSON.stringify({id:id})}).then(function(){load('releases');});}
function saveWf(){api('/api/workflow',{method:'POST',body:document.getElementById('wf').value}).then(function(r){alert(r.ok?'已保存':'保存失败: '+(r.error||''));});}
function runWf(){var note=document.getElementById('note').value;
 api('/api/run',{method:'POST',body:JSON.stringify({note:note})}).then(function(r){
  var out=document.getElementById('runOut');out.style.display='block';
  out.textContent=JSON.stringify(r,null,2);});}
load('overview');
</script>
</body></html>"""


def _json(handler, obj, status=200):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def local_notes_pins():
    """本机 ~/DingAI 下的桌面 note → pins（local 模式没有 folder/server 列表可用）。"""
    import glob
    rows = []
    for path in sorted(glob.glob(os.path.join(os.path.expanduser("~"), "DingAI", "*.json"))):
        name = os.path.basename(path)
        if name in ("settings.json", "notices.json", "project.txt", "last-handoff.json"):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                note = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(note, dict) or not isinstance(note.get("pins"), list):
            continue
        note_id = str(note.get("file") or note.get("id") or os.path.splitext(name)[0])
        for pin in note["pins"]:
            if isinstance(pin, dict):
                rows.append({
                    "note_id": note_id, "pin_id": pin.get("id"),
                    "pin_type": pin.get("pin_type") or "bug",
                    "status": pin.get("status") or "open",
                    "note": pin.get("note") or "",
                    "screenshot": note.get("screenshot") or "",
                })
    return rows


def build_state():
    import handoff
    from core import collide, edition, release as rel, sync
    cfg = sync.load_settings()
    state_root = handoff.state_root()
    pins = sync.list_pins(cfg["project"])
    rows = pins.get("pins") or []
    mode = pins.get("mode") or "local"
    if mode == "local":
        rows = local_notes_pins()
    releases = rel.search_releases(state_root, "")
    sessions = collide.list_sessions(state_root)
    banner = ""
    notices = os.path.join(state_root, "notices.json")
    try:
        with open(notices, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            banner = "；".join(str(w.get("detail") or w) for w in data[:3])
    except (OSError, ValueError):
        pass
    return {
        "edition": edition.describe(),
        "sync_mode": cfg["mode"],
        "project": cfg["project"],
        "banner": banner,
        "pins": rows,
        "mode": mode,
        "releases": releases,
        "sessions": sessions,
        "workflow": handoff.load_workflow(),
        "workflow_path": handoff.workflow_path() or "(default)",
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _body(self):
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            return json.loads(raw)
        except ValueError:
            return {"raw": raw}

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/state":
            state = build_state()
            _json(self, {k: state[k] for k in ("edition", "sync_mode", "project", "banner", "sessions")})
            return
        if path == "/api/pins":
            _json(self, {k: build_state()[k] for k in ("pins", "mode")})
            return
        if path == "/api/releases":
            _json(self, {"releases": build_state()["releases"]})
            return
        if path == "/api/workflow":
            state = build_state()
            _json(self, {"workflow": state["workflow"], "path": state["workflow_path"]})
            return
        _json(self, {"error": "not found"}, 404)

    def do_POST(self):
        from core import release as rel
        import handoff
        path = urlparse(self.path).path
        body = self._body()
        root = handoff.state_root()
        if path == "/api/release/publish":
            result = rel.publish(root, str(body.get("id") or ""), actor="cockpit",
                                 admin=os.environ.get("DINGAI_RELEASE_ADMIN") == "1")
            _json(self, {k: v for k, v in result.items() if k != "release"})
            return
        if path == "/api/release/rollback":
            result = rel.rollback(root, str(body.get("id") or ""), actor="cockpit")
            _json(self, {k: v for k, v in result.items() if k != "release"})
            return
        if path == "/api/workflow":
            data = body.get("workflow", body)
            _json(self, handoff.save_workflow(data))
            return
        if path == "/api/run":
            note = str(body.get("note") or "").strip()

            def work():
                if not note:
                    import glob
                    files = sorted(glob.glob(os.path.join(os.path.expanduser("~"), "DingAI", "*.json")))
                    files = [f for f in files if os.path.basename(f) not in
                             ("settings.json", "notices.json", "project.txt", "last-handoff.json")]
                    if files:
                        with open(files[-1], encoding="utf-8") as fh:
                            return handoff.run_workflow(fh.read())
                    return {"ok": False, "error": "no note provided and no local note found"}
                return handoff.run_workflow(note)

            box = {}
            thread = threading.Thread(target=lambda: box.update(result=work()))
            thread.start()
            thread.join(timeout=60)
            if thread.is_alive():
                _json(self, {"ok": False, "error": "run timed out in cockpit (still running in background is not supported)"})
                return
            _json(self, box.get("result") or {"ok": False, "error": "no result"})
            return
        _json(self, {"error": "not found"}, 404)


def main(argv):
    from core import edition
    try:
        edition.require("cockpit")
    except Exception as exc:
        sys.stderr.write("%s\n" % exc)
        return 1
    port = 8764
    if "--port" in argv:
        index = argv.index("--port")
        if index + 1 < len(argv):
            port = int(argv[index + 1])
    host = os.environ.get("DINGAI_COCKPIT_HOST", "127.0.0.1")
    server = ThreadingHTTPServer((host, port), Handler)
    sys.stderr.write("DingCode cockpit (pro) on http://%s:%d\n" % (host, port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
