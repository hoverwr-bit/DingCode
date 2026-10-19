#!/usr/bin/env python3
# dingai_team_server.py — DingAI 团队看板 v0.1(归集+看板,自托管,无账号)
# 部署: 任意主机, 环境变量 DINGAI_TEAM_HOST / DINGAI_TEAM_PORT
#       (兼容 ANNO_TEAM_HOST / ANNO_TEAM_PORT, 默认 127.0.0.1:8050)
# API:
#   POST /api/note        JSON body(dingai-desktop-v1, 兼容 anno-desktop-v1)→ 存 notes/ + ledger.jsonl,返回 {"id":...}
#   POST /api/shot/<file> binary body(png)→ 存 shots/
#   GET  /api/notes?limit=200  账本列表
#   GET  /api/note/<file>      单条 JSON 全文
#   GET  /api/shot/<file>      截图
#   GET  /                    看板页(列表+截图标注重绘)
# 内网信任模型:仅监听内网,无鉴权,标识=machine/user 字段

import json, os, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path.home() / "anno-team"
NOTES = ROOT / "notes"; SHOTS = ROOT / "shots"
LEDGER = ROOT / "ledger.jsonl"
for d in (NOTES, SHOTS):
    d.mkdir(parents=True, exist_ok=True)

BOARD_HTML = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>DingAI 团队看板 · </title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 body{margin:0;font-family:-apple-system,"PingFang SC",sans-serif;background:#f4f5f7;color:#1c1e21}
 header{background:#1c2430;color:#fff;padding:10px 18px;display:flex;gap:14px;align-items:center}
 header b{font-size:15px} header span{opacity:.75;font-size:12px}
 main{display:flex;height:calc(100vh - 44px)}
 #list{width:340px;overflow-y:auto;border-right:1px solid #e2e4e8;background:#fff}
 .note{padding:10px 14px;border-bottom:1px solid #f0f1f3;cursor:pointer}
 .note:hover{background:#f7f9fc}.note.on{background:#eef3fb;border-left:3px solid #2b6cb0}
 .note .t{font-size:13px;font-weight:600}.note .m{font-size:11px;color:#777;margin-top:3px}
 #detail{flex:1;overflow:auto;padding:14px}
 #meta{font-size:12px;color:#555;margin-bottom:8px}
 #wrap{position:relative;display:inline-block;max-width:100%}
 canvas{position:absolute;left:0;top:0;pointer-events:none}
 h2{margin:0;font-size:14px}
 .tags span{display:inline-block;background:#e8eefb;color:#2b4f8b;border-radius:4px;padding:1px 7px;font-size:11px;margin-right:6px}
</style></head><body>
<header><b>📌 DingAI 团队看板</b><span id="cnt"></span><span style="margin-left:auto;font-size:12px;opacity:.6">DingAI team v0.1 · 自托管</span></header>
<main><div id="list"></div><div id="detail"><div id="meta">左侧选择一条批注</div><div id="wrap"><img id="shot"><canvas id="cv"></canvas></div></div></main>
<script>
let notes=[];
async function load(){
  notes = await (await fetch('/api/notes?limit=300')).json();
  document.getElementById('cnt').textContent = notes.length + ' 条';
  const L = document.getElementById('list');
  L.innerHTML = notes.map((n,i)=>`<div class="note" data-i="${i}">
    <div class="t">${esc(n.app||'?')} · ${n.pin_count}钉${n.arrow_count?' '+n.arrow_count+'箭':''}${n.box_count?' '+n.box_count+'框':''}</div>
    <div class="m">${n.ts} · ${esc(n.user)}@${esc(n.machine)}${n.note0?' · ✎'+esc(n.note0):''}</div></div>`).join('');
  L.querySelectorAll('.note').forEach(el=>el.onclick=()=>show(+el.dataset.i, el));
}
function esc(s){return (s??'').toString().replace(/[<>&"]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c]))}
async function show(i, el){
  document.querySelectorAll('.note').forEach(n=>n.classList.remove('on')); el.classList.add('on');
  const n = notes[i];
  const d = await (await fetch('/api/note/'+n.file)).json();
  const img = document.getElementById('shot'), cv = document.getElementById('cv');
  img.onload = ()=>draw(d);
  img.src = '/api/shot/'+d.screenshot;
  document.getElementById('meta').innerHTML =
    `<h2>${esc(d.app?.name||'?')} ${d.window?.title?'· '+esc(d.window?.title):''}</h2>
     <div class="tags" style="margin:6px 0"><span>${esc(d.machine||'')}</span><span>${esc(d.user||'')}</span><span>${d.ts||''}</span><span>${d.platform||''}</span></div>`+
    (d.pins||[]).map(p=>`<div style="font-size:12px;color:#333;margin:2px 0">⌗${p.id} (${p.x_px},${p.y_px})${p.note?' ✎'+esc(p.note):''}${p.window?' · '+esc(p.window.owner):''}${p.ocr_nearby?' · ocr: '+esc(p.ocr_nearby.slice(0,60)):''}</div>`).join('');
}
function draw(d){
  const img=document.getElementById('shot'), cv=document.getElementById('cv'), g=cv.getContext('2d');
  cv.width=img.naturalWidth; cv.height=img.naturalHeight;
  g.clearRect(0,0,cv.width,cv.height);
  (d.pins||[]).forEach(p=>{
    g.strokeStyle='rgba(255,60,60,.85)';g.lineWidth=Math.round(cv.width/900)+1;g.setLineDash([12,9]);
    g.beginPath();g.moveTo(0,p.y_px);g.lineTo(cv.width,p.y_px);g.moveTo(p.x_px,0);g.lineTo(p.x_px,cv.height);g.stroke();g.setLineDash([]);
    g.fillStyle='#fff';g.beginPath();g.arc(p.x_px,p.y_px,9,0,7);g.fill();
    g.fillStyle='red';g.beginPath();g.arc(p.x_px,p.y_px,6,0,7);g.fill();
    g.font='bold 22px sans-serif';const t=`⌗${p.id}${p.note?' '+p.note.slice(0,20):''}`;
    g.fillStyle='rgba(0,0,0,.8)';g.fillRect(p.x_px+14,p.y_px-30,g.measureText(t).width+14,30);
    g.fillStyle='#fff';g.fillText(t,p.x_px+21,p.y_px-9);
  });
  (d.arrows||[]).forEach(a=>{
    g.strokeStyle=g.fillStyle='red';g.lineWidth=Math.round(cv.width/900)*a.width+2;
    g.beginPath();g.moveTo(a.from_px[0],a.from_px[1]);g.lineTo(a.to_px[0],a.to_px[1]);g.stroke();
    const [x1,y1]=a.from_px,[x2,y2]=a.to_px,ang=Math.atan2(y2-y1,x2-x1),h=14+a.width*3;
    g.beginPath();g.moveTo(x2,y2);
    g.lineTo(x2-h*Math.cos(ang-.42),y2-h*Math.sin(ang-.42));
    g.lineTo(x2-h*Math.cos(ang+.42),y2-h*Math.sin(ang+.42));g.closePath();g.fill();
  });
  (d.boxes||[]).forEach(b=>{
    const[x,y,w,h]=b.rect_px;g.strokeStyle='red';g.fillStyle='rgba(255,60,60,.15)';g.lineWidth=2+b.width;
    g.fillRect(x,y,w,h);g.strokeRect(x,y,w,h);
  });
}
load(); setInterval(load, 15000);
</script></body></html>"""


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

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            return self._send(200, BOARD_HTML, "text/html; charset=utf-8")
        if self.path.startswith("/api/notes"):
            limit = 300
            if "limit=" in self.path:
                try: limit = int(self.path.split("limit=")[1].split("&")[0])
                except ValueError: pass
            rows = []
            if LEDGER.exists():
                lines = LEDGER.read_text().strip().splitlines()[-limit:]
                rows = [json.loads(l) for l in reversed(lines)]
            return self._send(200, json.dumps(rows, ensure_ascii=False))
        if self.path.startswith("/api/note/"):
            f = self.path.rsplit("/", 1)[1]
            p = NOTES / os.path.basename(f)
            if p.exists():
                return self._send(200, p.read_text())
            return self._send(404, '{"error":"not found"}')
        if self.path.startswith("/api/shot/"):
            f = self.path.rsplit("/", 1)[1]
            p = SHOTS / os.path.basename(f)
            if p.exists():
                return self._send(200, p.read_bytes(), "image/png")
            return self._send(404, b"", "text/plain")
        self._send(404, '{"error":"bad path"}')

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        if self.path == "/api/note":
            try:
                d = json.loads(body)
            except Exception:
                return self._send(400, '{"error":"bad json"}')
            fid = f"anno-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
            d["file"] = fid + ".json"
            (NOTES / d["file"]).write_text(json.dumps(d, ensure_ascii=False, indent=1))
            note0 = next((p.get("note", "") for p in d.get("pins", []) if p.get("note")), "")
            row = {"file": d["file"], "ts": time.strftime("%m-%d %H:%M"),
                   "machine": d.get("machine"), "user": d.get("user"),
                   "app": (d.get("app") or {}).get("name"),
                   "pin_count": d.get("pin_count", 0), "arrow_count": d.get("arrow_count", 0),
                   "box_count": d.get("box_count", 0), "note0": note0}
            with LEDGER.open("a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            return self._send(200, json.dumps({"id": fid, "shot_name": d.get("screenshot")}))
        if self.path.startswith("/api/shot/"):
            name = os.path.basename(self.path)
            if not name.endswith(".png"):
                return self._send(400, '{"error":"png only"}')
            (SHOTS / name).write_bytes(body)
            return self._send(200, '{"ok":true}')
        self._send(404, '{"error":"bad path"}')


if __name__ == "__main__":
    print("DingAI team server on %s:%s, root = %s" % (os.environ.get("DINGAI_TEAM_HOST", os.environ.get("ANNO_TEAM_HOST","127.0.0.1")), os.environ.get("DINGAI_TEAM_PORT", os.environ.get("ANNO_TEAM_PORT","8050")), ROOT))
    ThreadingHTTPServer((os.environ.get("DINGAI_TEAM_HOST", os.environ.get("ANNO_TEAM_HOST","127.0.0.1")), int(os.environ.get("DINGAI_TEAM_PORT", os.environ.get("ANNO_TEAM_PORT","8050")))), Handler).serve_forever()
