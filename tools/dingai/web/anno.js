
/* DingAI web layer (anno-v7 contract, file anno.js)（261008 批注持久化：重开后保留批注）
   v7.9.1 变更：①setMode(true) 开启时加载 localStorage 既有批注（原=清空）②setMode(false) 退出只退模式
   不删数据（原=removeItem 清空）③退出确认文案同步改④清除唯一入口=面板底栏「清空」（confirm 保护）。
   261019a 变更：桥 answer 增加 title=document.title（配合 App 侧 visibility 择优修复：桌面钉
   抓错同窗后台标签页的 bug——几何校验对同窗标签同分，谁先答谁赢；现 App 只从 visible 答案里挑）。
   前序 v7.7 历史（属性化标记）：①去顶部红条②批注 UI 挂
   data-annotation-ui+stopImmediatePropagation③钉子锚定 dx/dy 滚动跟随④字段信息签⑤面板收起保留。 */
(function(){
  'use strict';
  if (window.ANNO_V7) return;
  window.ANNO_V7 = true; /* v7.9.1（261008）：修复防重入锁——原只检查不赋值，二次注入=双实例同 id 打架 */
  if (new URLSearchParams(location.search).get('qa') === '1') return;
  var LS_KEY = 'anno-v7:' + location.pathname;
  var mode = false, annos = [], seq = 0, me = 'admin';
  var oldBtn = document.getElementById('annotationLaunch');
  if (oldBtn) oldBtn.style.display = 'none';

  var css = document.createElement('style');
  css.textContent = [
    '#av7chip{position:fixed;top:10px;right:14px;z-index:99997;background:#101828;color:#fff;border:1px solid #3b4a63;border-radius:6px;padding:6px 14px;font-size:13px;cursor:pointer}',
    '#av7chip.on{background:#b91c1c;border-color:#b91c1c}',
    '#av7gx,#av7gy{display:none;position:fixed;z-index:99994;pointer-events:none;background:rgba(255,255,255,.75)}',
    '#av7gx{width:28px;height:1px;margin-left:-14px}#av7gy{width:1px;height:28px;margin-top:-14px}',
    '#av7bubble{display:none;position:fixed;z-index:99995;pointer-events:none;background:#1e293b;color:#e2e8f0;font:11px/1.5 monospace;padding:3px 7px;border-radius:4px;white-space:nowrap}',
    '.av7pin{position:absolute;z-index:99993;width:22px;height:22px;border-radius:50%;background:#dc2626;color:#fff;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4);font:bold 11px/18px sans-serif;text-align:center;cursor:pointer;padding:0}',
    '#av7panel{display:none;position:fixed;top:44px;right:14px;bottom:14px;width:380px;z-index:99996;background:#fff;border:1px solid #cbd5e1;border-radius:8px;box-shadow:0 8px 30px rgba(0,0,0,.18);flex-direction:column;font-size:13px}',
    '#av7panel.on{display:flex}',
    '#av7panel .av7head{padding:10px 14px;border-bottom:1px solid #e2e8f0;font-weight:700}',
    '#av7head button{float:right;margin-left:8px;border-radius:5px;padding:3px 12px;font-size:12px;cursor:pointer;margin-top:-2px}',
    '#av7hide{background:#f1f5f9;border:1px solid #cbd5e1}',
    '#av7exit{background:#fff;color:#b91c1c;border:1px solid #fca5a5}',
    '#av7list{flex:1;overflow:auto;padding:8px 14px}',
    '.av7item{border:1px solid #e2e8f0;border-radius:6px;padding:8px 10px;margin-bottom:8px}',
    '.av7item small{color:#64748b}',
    '.av7item .av7ops{margin-top:6px}.av7item button{margin-right:6px;font-size:12px;cursor:pointer}',
    '#av7foot{display:flex;gap:10px;padding:10px 14px;border-top:1px solid #e2e8f0}',
    '#av7foot button{flex:1;padding:8px 0;cursor:pointer;font-size:13px}',
    '#av7copy{background:#2563eb;color:#fff;border:0;border-radius:6px}',
    '#av7clear{background:#fff;color:#b91c1c;border:1px solid #fca5a5;border-radius:6px}',
    '#av7modal{display:none;position:fixed;inset:0;z-index:99998;background:rgba(15,23,42,.45)}',
    '#av7modal.on{display:flex;align-items:center;justify-content:center}',
    '#av7card{background:#fff;border-radius:10px;width:520px;max-width:92vw;padding:18px 20px;font-size:13px}',
    '#av7card h3{margin:0 0 6px;font-size:15px}',
    '#av7ctx{color:#64748b;font-size:12px;margin-bottom:10px;word-break:break-all}',
    '#av7comment{width:100%;box-sizing:border-box;min-height:88px;border:1px solid #cbd5e1;border-radius:6px;padding:8px;font:13px/1.5 sans-serif}',
    '#av7acts{display:flex;gap:10px;justify-content:flex-end;margin-top:12px}',
    '#av7save{background:#2563eb;color:#fff;border:0;border-radius:6px;padding:7px 18px;cursor:pointer}',
    '#av7cancel{background:#fff;border:1px solid #cbd5e1;border-radius:6px;padding:7px 14px;cursor:pointer}',
    '#av7panel .av7tools-row{display:flex;flex-wrap:wrap;align-items:center;gap:3px;padding:8px 14px;border-bottom:1px solid #e2e8f0;background:#f8fafc}',
    '#av7panel .av7tools-row button{min-width:28px;height:28px;border:0;border-radius:6px;background:transparent;color:#475569;font-size:14px;cursor:pointer;padding:0 4px;display:inline-flex;align-items:center;justify-content:center}',
    '#av7panel .av7tools-row button.on{background:#1768e5;color:#fff}',
    '#av7panel .av7tools-row button.on .dot{border-color:#fff}',
    '#av7panel .av7tools-row .sep{width:1px;align-self:stretch;background:#dbe2ea;margin:2px 3px}',
    '#av7panel .dot{width:14px;height:14px;border-radius:50%;display:inline-block;border:2px solid #cbd5e1}',
    '#av7panel .wd{display:inline-block;background:#475569;border-radius:2px}',
    '#av7panel .as{display:inline-block}',
    '#av7tools button.on{background:#1768e5;color:#fff}',
    '#av7marks{position:absolute;left:0;top:0;pointer-events:none;z-index:99992}',
    '#av7marks svg{position:absolute;left:0;top:0;overflow:visible}',
    '.av7arrow{stroke-width:5.5;pointer-events:auto;cursor:pointer}',
    '.av7arrow:hover{stroke:#f59e0b}',
    '.av7shape{position:absolute;pointer-events:auto;cursor:pointer;border-radius:8px}.av7spot{position:absolute;border:2.5px solid #f59e0b;border-radius:10px;box-shadow:0 0 0 9999px rgba(3,7,18,.58), 0 0 26px 4px rgba(245,158,11,.35);pointer-events:auto;cursor:pointer}',
    '.av7text{position:absolute;z-index:99993;pointer-events:auto;cursor:move;background:rgba(15,23,42,.72);color:#fff;border-radius:4px;padding:2px 6px;font:13px/20px sans-serif;white-space:nowrap}',
    '.av7handle{position:absolute;width:8px;height:8px;margin:-4px 0 0 -4px;background:#fff;border:1px solid #0f172a;z-index:99995;pointer-events:none}',
    '.av7sel{outline:1px dashed #fff;outline-offset:2px}',
    '#av7draw-preview{position:absolute;border:2px dashed #dc2626;pointer-events:none}',
    '#av7info{display:none;position:absolute;z-index:99994;background:#0f172a;color:#e2e8f0;font:12px/1.6 sans-serif;padding:8px 11px;border-radius:6px;box-shadow:0 4px 14px rgba(0,0,0,.35);pointer-events:none;max-width:380px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}'
  ].join('\n');
  document.head.appendChild(css);

  function el(tag, id, parent) { var e = document.createElement(tag); e.id = id; e.setAttribute('data-annotation-ui', 'true'); (parent || document.body).appendChild(e); return e; }
  var chip = el('button', 'av7chip'); chip.type = 'button'; chip.textContent = 'DingAI：关'; chip.style.display = 'none';
  var gx = el('div', 'av7gx'), gy = el('div', 'av7gy'), bubble = el('div', 'av7bubble'), info = el('div', 'av7info');
  var markLayer = el('div', 'av7marks');
  var tools = null, panelToolsClick = null;
  var AV_COLORS = ['#dc2626', '#f59e0b', '#16a34a', '#2563eb', '#ffffff', '#a855f7'];
  var AV_WIDTHS = [3, 5.5, 8];
  var AV_STYLES = {
    sharp:    { name: '细尖·macOS 风', kind: 'closed', hw: 3.2, hl: 1.05, dent: 0.55 },
    triangle: { name: '标准三角',      kind: 'closed', hw: 3.0, hl: 1.00, dent: 0 },
    classic:  { name: '办公经典',      kind: 'closed', hw: 2.8, hl: 0.90, dent: 0.15 },
    barbed:   { name: '深燕尾鱼叉',    kind: 'closed', hw: 3.5, hl: 1.15, dent: 0.72 },
    slim:     { name: '窄工程头',      kind: 'closed', hw: 2.4, hl: 1.35, dent: 0.35 },
    taper:    { name: '锥身流线',      kind: 'taper',  hw: 2.6, hl: 1.00 },
    open:     { name: '开放 V',        kind: 'open',   hw: 3.2, hl: 1.00 },
    dot:      { name: '线+圆点',       kind: 'dot',    hw: 3.0, hl: 1.00 }
  };
  var curTool = 'point', curColor = AV_COLORS[0], curWidth = AV_WIDTHS[1], curStyle = 'sharp';
  var selected = -1, dragSel = null, textInput = null;
  /* 一体成型箭头路径（260922d v7.9）：身+头单路径连续轮廓，圆角靠同色 stroke+round join；
     sharp=macOS 风（头宽 3.2×身宽、头长≈头宽、燕尾凹深 0.55 头长） */
  function buildArrowD(style, x1, y1, x2, y2, w) {
    w = Math.max(1, +w || 5.5);
    var dx = x2 - x1, dy = y2 - y1, L = Math.hypot(dx, dy);
    if (L < 2) return '';
    var ux = dx / L, uy = dy / L, nx = -uy, ny = ux;
    var T = AV_STYLES[style] || AV_STYLES.sharp;
    var hw = w * T.hw, hl = hw * T.hl;
    if (hl > L * 0.85) { var k = (L * 0.85) / hl; hl *= k; hw *= k; }
    if (hw > L * 0.9) hw = L * 0.9;
    var t1 = L - hl, hw2 = hw / 2, dw = w * 0.55, wh = w / 2;
    var pt = function (t, o) { return (x1 + ux * t + nx * o).toFixed(1) + ',' + (y1 + uy * t + ny * o).toFixed(1); };
    if (T.kind === 'open') {
      return 'M' + pt(0, 0) + ' L' + pt(t1 + hl * 0.35, 0)
        + ' M' + pt(t1, -hw2) + ' L' + pt(L, 0) + ' L' + pt(t1, hw2);
    }
    if (T.kind === 'dot') {
      var r = Math.max(w * 1.1, 5);
      return 'M' + pt(0, 0) + ' L' + pt(L - r * 2, 0)
        + ' M' + pt(L - r, 0).replace(',', ',') + ' m ' + (-r) + ',0 a ' + r + ',' + r + ' 0 1,0 ' + (r * 2) + ',0 a ' + r + ',' + r + ' 0 1,0 ' + (-r * 2) + ',0';
    }
    if (T.kind === 'taper') {
      var tw = w * 0.5;
      return 'M' + pt(0, -tw / 2)
        + ' L' + pt(t1, -wh)
        + ' L' + pt(t1, -hw2)
        + ' L' + pt(L, 0)
        + ' L' + pt(t1, hw2)
        + ' L' + pt(t1, wh)
        + ' L' + pt(0, tw / 2)
        + ' Z';
    }
    var dent = T.dent || 0;
    return 'M' + pt(0, -wh)
      + ' L' + pt(t1, -wh)
      + ' L' + pt(t1, -hw2)
      + (dent > 0 ? ' L' + pt(t1 + hl * dent, -dw) : '')
      + ' L' + pt(L, 0)
      + (dent > 0 ? ' L' + pt(t1 + hl * dent, dw) : '')
      + ' L' + pt(t1, hw2)
      + ' L' + pt(t1, wh)
      + ' L' + pt(0, wh)
      + ' Z';
  }




  function markerDef(mid, style, color) {
    var st = AV_STYLES[style] || AV_STYLES.sharp;
    return '<marker id="' + mid + '" markerWidth="4.8" markerHeight="3.4" refX="4.3" refY="1.7" orient="auto" markerUnits="strokeWidth" viewBox="0 0 4.8 3.4" preserveAspectRatio="xMidYMid meet">'
      + (st.open ? '<path d="' + st.d + '" fill="none" stroke="' + color + '" stroke-width="0.55"/>'
                 : '<path d="' + st.d + '" fill="' + color + '"/>') + '</marker>';
  }
  function buildTools(hostPanel) {
    var row = document.createElement('div');
    row.className = 'av7tools-row';
    row.innerHTML = '<button type="button" data-tool="select" title="选择、移动、缩放">↖</button>'
      + '<button type="button" data-tool="point" class="on" title="点选批注">📍</button>'
      + '<button type="button" data-tool="arrow" title="箭头（按住拖拽）">➷</button>'
      + '<button type="button" data-tool="box" title="方框（按住拖框，纯边框不暗化）">▭</button>'
      + '<button type="button" data-tool="ellipse" title="椭圆（按住拖框，纯边框不暗化）">◯</button>'
      + '<button type="button" data-tool="spot" title="聚光灯（按住拖框，选区外压暗）">◉</button>'
      + '<button type="button" data-tool="text" title="文字标签（单击后回车）">T</button>'
      + '<span class="sep"></span>'
      + AV_COLORS.map(function (c, i) { return '<button type="button" data-color="' + c + '" title="颜色" ' + (i === 0 ? 'class="on"' : '') + '><span class="dot" style="background:' + c + '"></span></button>'; }).join('')
      + '<span class="sep"></span>'
      + AV_WIDTHS.map(function (w, i) { return '<button type="button" data-width="' + w + '" title="粗细" ' + (i === 1 ? 'class="on"' : '') + '><span class="wd" style="height:' + (2 + i * 2) + 'px;width:16px"></span></button>'; }).join('')
      + '<span class="sep"></span>'
      + Object.keys(AV_STYLES).map(function (k, i) {
          var ic = AV_STYLES[k].kind === 'open' || AV_STYLES[k].kind === 'dot'
            ? '<path d="' + buildArrowD(k, 2, 7, 26, 7, 3) + '" fill="none" stroke="#334155" stroke-width="3" stroke-linecap="round"/>'
            : '<path d="' + buildArrowD(k, 2, 7, 26, 7, 3) + '" fill="#334155" stroke="#334155" stroke-width="1.2" stroke-linejoin="round"/>';
          return '<button type="button" data-style="' + k + '" title="' + AV_STYLES[k].name + '" ' + (i === 0 ? 'class="on"' : '') + '><svg width="30" height="14" viewBox="0 0 30 14">' + ic + '</svg></button>';
        }).join('')
      + '<span class="sep"></span>'
      + '<button type="button" data-undo="1" title="撤销上一条标记">↩</button>';
    var head = hostPanel.querySelector('.av7head');
    head.insertAdjacentElement('afterend', row);
    return row;
  }
  panelToolsClick = function (e) {
    var b = e.target.closest('button'); if (!b) return;
    e.stopPropagation();
    if (b.dataset.tool) {
      curTool = b.dataset.tool;
      tools.querySelectorAll('button[data-tool]').forEach(function (x) { x.classList.toggle('on', x === b); });
    } else if (b.dataset.color) {
      curColor = b.dataset.color;
      tools.querySelectorAll('button[data-color]').forEach(function (x) { x.classList.toggle('on', x === b); });
    } else if (b.dataset.width) {
      curWidth = +b.dataset.width;
      tools.querySelectorAll('button[data-width]').forEach(function (x) { x.classList.toggle('on', x === b); });
    } else if (b.dataset.style) {
      curStyle = b.dataset.style;
      tools.querySelectorAll('button[data-style]').forEach(function (x) { x.classList.toggle('on', x === b); });
    } else if (b.dataset.undo) {
      for (var i = annos.length - 1; i >= 0; i--) { if (annos[i].mark) { annos.splice(i, 1); saveLocal(); render(); break; } }
    }
  };
  var panel = el('aside', 'av7panel');
  panel.innerHTML = '<div class="av7head">DingAI（页面）<button type="button" id="av7exit">退出批注</button><button type="button" id="av7hide">收起</button></div><div id="av7list"></div>'
    + '<div id="av7foot"><button type="button" id="av7copy">复制 JSON</button><button type="button" id="av7clear">清空</button></div>';
  tools = buildTools(panel);
  tools.addEventListener('click', panelToolsClick);
  var modal = el('div', 'av7modal');
  modal.innerHTML = '<div id="av7card"><h3 id="av7title">添加批注</h3><div id="av7ctx"></div>'
    + '<label>问题描述（含期望结果）<textarea id="av7comment" placeholder="例：此列改为常驻左侧，并增加筛选条件"></textarea></label>'
    + '<div id="av7acts"><button type="button" id="av7cancel">取消</button><button type="button" id="av7save">保存位置批注</button></div></div>';

  var pending = null; // {key,target,geometry,anchor,field,value}
  function fmtXY(g) { return 'client(' + g.client.x + ',' + g.client.y + ') page(' + g.page.x + ',' + g.page.y + ')'; }
  function saveLocal() { try { localStorage.setItem(LS_KEY, JSON.stringify(annos)); } catch (e) {} }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function pad(n) { return (n < 10 ? '0' : '') + n; }

  var anchorSeq = 0;
  function cssEscape(s) { return (window.CSS && CSS.escape) ? CSS.escape(s) : s; }
  function anchorElOf(key) {
    if (!key) return null;
    if (key.indexOf('sec:') === 0) {
      var k = key.slice(4), hits;
      try { hits = document.querySelectorAll('[data-annotation-key="' + cssEscape(k) + '"]'); } catch (e) { return null; }
      return hits.length === 1 ? hits[0] : null;
    }
    if (key.indexOf('id:') === 0) return document.getElementById(key.slice(3)) || null;
    if (key.indexOf('ding:') === 0) return document.querySelector('[data-dingai-anchor="' + cssEscape(key.slice(5)) + '"]');
    return null;
  }
  function targetName(key) {
    var el = anchorElOf(key);
    if (!key) return '自由位置';
    if (key.indexOf('sec:') === 0) return el ? ('区块 ' + key.slice(4)) : ('区块 ' + key.slice(4) + '（未定位）');
    if (key.indexOf('id:') === 0) return el ? ('#' + key.slice(3) + ' ' + (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 24)) : key;
    if (key.indexOf('ding:') === 0) return el ? ('元素 ' + key.slice(5)) : ('元素 ' + key.slice(5) + '（未定位）');
    return '自由位置';
  }
  /* 没有 id 的节点也打上 data-dingai-anchor,这样嵌套滚动容器里钉子跟的是元素而不是当时的 page 坐标。 */
  function keyOf(t) {
    if (!t || !t.closest) return null;
    var sec = t.closest('[data-annotation-key]');
    if (sec && sec.dataset.annotationKey) return 'sec:' + sec.dataset.annotationKey;
    if (t.id && t !== document.body && t !== document.documentElement) return 'id:' + t.id;
    if (t === document.body || t === document.documentElement) return null;
    if (!t.dataset.dingaiAnchor) t.dataset.dingaiAnchor = 'd' + (++anchorSeq);
    return 'ding:' + t.dataset.dingaiAnchor;
  }
  function anchorForPage(pageX, pageY, target) {
    var key = keyOf(target);
    if (!key) return null;
    var el = anchorElOf(key);
    if (!el || !el.getClientRects().length) return null;
    var r = el.getBoundingClientRect();
    return { key: key, dx: pageX - (window.scrollX + r.left), dy: pageY - (window.scrollY + r.top) };
  }
  function resolveAnchor(a) {
    if (!a) return null;
    var el = anchorElOf(a.key);
    if (!el || !el.getClientRects().length) return null;
    var r = el.getBoundingClientRect();
    return { x: window.scrollX + r.left + a.dx, y: window.scrollY + r.top + a.dy };
  }
  /* 渲染用副本:锚点还在就跟元素走,元素没了就留点击时的页面坐标。 */
  function placedMark(mark) {
    if (!mark || !mark.anchors) return mark;
    var a1 = resolveAnchor(mark.anchors.a1);
    var a2 = resolveAnchor(mark.anchors.a2);
    var m = mark;
    if (a1) {
      var w = mark.x2 - mark.x1, h = mark.y2 - mark.y1;
      m = Object.assign({}, mark, { x1: a1.x, y1: a1.y });
      if (!a2 && mark.type !== 'arrow') m = Object.assign(m, { x2: a1.x + w, y2: a1.y + h });
    }
    if (a2) m = Object.assign({}, m, { x2: a2.x, y2: a2.y });
    return m;
  }
  /* 点击位置字段信息：优先命中所点单元格的表头列名 */
  function fieldInfoOf(t) {
    var td = t.closest('td,th');
    if (!td) return { field: t.tagName.toLowerCase(), value: (t.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60) };
    var tbl = td.closest('table'), idx = td.cellIndex, name = '';
    if (tbl) {
      var head = tbl.querySelector('thead tr') || tbl.rows[0];
      var hcell = head ? head.cells[idx] : null;
      if (hcell) name = (hcell.textContent || '').replace(/\s+/g, ' ').trim();
    }
    return { field: name || ('第' + (idx + 1) + '列'), value: (td.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60) };
  }
  function showInfo(at, field, value, extra) {
    info.innerHTML = '<b style="color:#93c5fd">' + esc(field) + '</b>：' + esc(value || '—')
      + (extra ? '<br><span style="color:#94a3b8">' + esc(extra) + '</span>' : '');
    info.style.display = 'block';
    var w = 300, h = 46;
    info.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, at.client.x + 14 + window.scrollX)) + 'px';
    info.style.top = Math.max(8 + window.scrollY, at.client.y - h - 10 < window.scrollY ? at.client.y + 16 + window.scrollY : at.client.y - h - 10 + window.scrollY) + 'px';
  }
  function hideInfo() { info.style.display = 'none'; }

  function exportV7() {
    return { page: location.pathname || 'page', version: 7.9, exportedAt: new Date().toISOString(), count: annos.length, annotations: annos };
  }
  window.ANNO_V7_EXPORT = exportV7;

  function renderMarks() {
    var spotSeen = false;
    markLayer.innerHTML = '';
    var H = Math.max(document.documentElement.scrollHeight, document.body.scrollHeight);
    markLayer.style.height = H + 'px';
    var NS = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('width', document.documentElement.scrollWidth); svg.setAttribute('height', H);
    svg.style.pointerEvents = 'none';
    markLayer.appendChild(svg);
    annos.forEach(function (a, i) {
      if (!a.mark) return;
      var mark = placedMark(a.mark);
      var selClass = i === selected ? ' av7sel' : '';
      if (mark.type === 'arrow') {
        var mc = mark.color || '#dc2626', ms = mark.style || 'sharp';
        var mw = mark.width || 5.5;
        var ln = document.createElementNS(NS, 'path');
        ln.setAttribute('d', buildArrowD(ms, mark.x1, mark.y1, mark.x2, mark.y2, mw));
        ln.setAttribute('class', 'av7arrow' + selClass);
        if (AV_STYLES[ms] && (AV_STYLES[ms].kind === 'open' || AV_STYLES[ms].kind === 'dot')) { ln.setAttribute('fill', 'none'); ln.setAttribute('stroke', mc); ln.setAttribute('stroke-width', mw); ln.setAttribute('stroke-linecap', 'round'); }
        else { ln.setAttribute('fill', mc); ln.setAttribute('stroke', mc); ln.setAttribute('stroke-width', Math.max(1.5, mw * 0.32)); }
        ln.setAttribute('stroke-linejoin', 'round'); ln.setAttribute('stroke-linecap', 'round');
        ln.setAttribute('data-annotation-ui', 'true');
        ln.addEventListener('click', function (ev) { ev.stopPropagation(); openModal({ key: a.key, geometry: a.geometry, anchor: a.anchor, mark: a.mark, field: a.field, value: a.value, existing: a }, true); });
        svg.appendChild(ln);
      } else if (a.mark.type === 'box' || a.mark.type === 'ellipse') {
        var sc = a.mark.color || '#f59e0b';
        var box = document.createElement('div');
        box.className = 'av7shape' + selClass;
        box.setAttribute('data-annotation-ui', 'true');
        box.style.borderColor = sc; box.style.borderWidth = (mark.width || 5.5) + 'px';
        if (mark.type === 'ellipse') { box.style.borderRadius = '50%'; }
        box.style.background = sc + '14';
        box.style.left = mark.x1 + 'px'; box.style.top = mark.y1 + 'px';
        box.style.width = (mark.x2 - mark.x1) + 'px'; box.style.height = (mark.y2 - mark.y1) + 'px';
        box.title = (a.field ? a.field + '：' + (a.value || '') + ' | ' : '') + (a.comment || '').slice(0, 60);
        box.addEventListener('click', function (ev) { ev.stopPropagation(); openModal({ key: a.key, geometry: a.geometry, anchor: a.anchor, mark: a.mark, field: a.field, value: a.value, existing: a }, true); });
        markLayer.appendChild(box);
      } else if (mark.type === 'text') {
        var lab = document.createElement('div');
        lab.className = 'av7text' + selClass;
        lab.setAttribute('data-annotation-ui', 'true');
        lab.textContent = mark.text || a.comment || '';
        lab.style.color = mark.color || '#fff';
        lab.style.left = mark.x1 + 'px';
        lab.style.top = mark.y1 + 'px';
        lab.style.minWidth = Math.max(24, mark.x2 - mark.x1) + 'px';
        lab.style.minHeight = Math.max(20, mark.y2 - mark.y1) + 'px';
        markLayer.appendChild(lab);
      } else {
        var sc = a.mark.color || '#f59e0b';
        var box = document.createElement('div');
        box.className = 'av7spot' + selClass;
        box.setAttribute('data-annotation-ui', 'true');
        box.style.borderColor = sc; box.style.borderWidth = (mark.width || 5.5) + 'px';
        /* 261014c:遮罩只挂第一个 spot——多聚光灯 box-shadow 9999px 叠加会让页面其余区域逐层变暗(用户报) */
        box.style.boxShadow = spotSeen ? '0 0 26px 4px ' + sc + '59' : '0 0 0 9999px rgba(3,7,18,.58), 0 0 26px 4px ' + sc + '59';
        spotSeen = true;
        box.style.left = mark.x1 + 'px'; box.style.top = mark.y1 + 'px';
        box.style.width = (mark.x2 - mark.x1) + 'px'; box.style.height = (mark.y2 - mark.y1) + 'px';
        box.title = (a.field ? a.field + '：' + (a.value || '') + ' | ' : '') + (a.comment || '').slice(0, 60);
        box.addEventListener('click', function (ev) { ev.stopPropagation(); openModal({ key: a.key, geometry: a.geometry, anchor: a.anchor, mark: a.mark, field: a.field, value: a.value, existing: a }, true); });
        markLayer.appendChild(box);
      }
    });
    if (selected >= 0 && annos[selected]) {
      handlesOf(annos[selected]).forEach(function (h) {
        var d = document.createElement('div');
        d.className = 'av7handle';
        d.setAttribute('data-annotation-ui', 'true');
        d.style.left = h.x + 'px';
        d.style.top = h.y + 'px';
        markLayer.appendChild(d);
      });
    }
  }


  /* 钉子渲染：锚定元素（点击点=元素内偏移 dx/dy）优先；元素失联才回退点击时页面坐标 */
  function render() {
    document.querySelectorAll('.av7pin').forEach(function (p) { p.remove(); });
    renderMarks();
    var seen = {};
    annos.forEach(function (a, i) {
      var off = (seen[a.key] = seen[a.key] || 0) * 6; seen[a.key]++;
      var pin = document.createElement('button');
      pin.type = 'button'; pin.className = 'av7pin'; pin.textContent = String(i + 1);
      pin.setAttribute('data-annotation-ui', 'true');
      var x = a.geometry.page.x, y = a.geometry.page.y, anchored = false;
      var ae = anchorElOf(a.key);
      if (ae && ae.getClientRects().length && a.anchor) {
        var r = ae.getBoundingClientRect();
        x = window.scrollX + r.left + a.anchor.dx; y = window.scrollY + r.top + a.anchor.dy; anchored = true;
      }
      pin.style.left = (x - 11 + off) + 'px'; pin.style.top = (y - 11 - off) + 'px';
      pin.title = (a.field ? a.field + '：' + (a.value || '') + '\n' : '') + a.comment.slice(0, 60);
      pin.addEventListener('click', function (ev) { ev.stopPropagation(); openModal({ key: a.key, geometry: a.geometry, anchor: a.anchor, field: a.field, value: a.value, existing: a }, true); });
      document.body.appendChild(pin);
    });
    var list = document.getElementById('av7list');
    list.innerHTML = annos.length ? '' : '<div style="color:#94a3b8;padding:12px 0">暂无批注。开启批注模式后点击页面任意位置。</div>';
    annos.forEach(function (a, i) {
      var it = document.createElement('div'); it.className = 'av7item';
      var ae = anchorElOf(a.key), state = ae && ae.getClientRects().length ? '已锚定' : '坐标回退';
      it.innerHTML = '<strong>A' + pad(i + 1) + '</strong> · ' + esc(a.target)
        + (a.field ? ' · <b>' + esc(a.field) + '</b>' : '')
        + '<div>' + esc(a.comment.slice(0, 120)) + '</div>'
        + '<small>' + esc(fmtXY(a.geometry)) + ' · 视口 ' + a.geometry.viewportW + ' · ' + state + '</small>'
        + '<div class="av7ops"><button type="button" data-op="loc">定位</button><button type="button" data-op="edit">编辑</button><button type="button" data-op="del">删除</button></div>';
      it.querySelector('[data-op=loc]').addEventListener('click', function () {
        var e = anchorElOf(a.key);
        if (e && e.getClientRects().length) e.scrollIntoView({ behavior: 'smooth', block: 'center' });
        else window.scrollTo(a.geometry.page.x - 200, a.geometry.page.y - 200);
      });
      it.querySelector('[data-op=edit]').addEventListener('click', function () { openModal(a, true); });
      it.querySelector('[data-op=del]').addEventListener('click', function () { annos = annos.filter(function (x) { return x !== a; }); saveLocal(); render(); });
      list.appendChild(it);
    });
  }
  /* 滚动/缩放时钉子跟元素重算（含表格内部横向滚动容器，capture 捕获） */
  var raf = 0;
  function scheduleRender() { if (!mode || raf) return; raf = requestAnimationFrame(function () { raf = 0; render(); }); }
  document.addEventListener('scroll', scheduleRender, true);
  window.addEventListener('resize', scheduleRender, { passive: true });

  function openModal(p, editing) {
    pending = p;
    document.getElementById('av7title').textContent = editing ? '编辑批注' : '添加批注';
    document.getElementById('av7ctx').textContent = targetName(p.key) + '｜' + (p.field ? p.field + '：' + (p.value || '—') + '｜' : '') + fmtXY(p.geometry) + (p.existing ? ('｜更新 ' + p.existing.id) : '');
    document.getElementById('av7comment').value = p.existing ? p.existing.comment : '';
    modal.classList.add('on');
    if (p.field !== undefined) showInfo(p.geometry, p.field, p.value, targetName(p.key));
    setTimeout(function () { document.getElementById('av7comment').focus(); }, 0);
  }
  function closeModal() { modal.classList.remove('on'); pending = null; hideInfo(); }

  document.getElementById('av7save').addEventListener('click', function () {
    var txt = document.getElementById('av7comment').value.trim();
    if (!txt) { alert('问题描述（含期望结果）必填'); return; }
    if (pending) {
      if (pending.existing) {
        pending.existing.comment = txt; /* 编辑既有条（钉子/列表进入） */
        if (pending.mark) pending.existing.mark = pending.mark;
      } else {
        /* 契约 v7.1：总是新建，不再按 key 合并 */
        annos.push({
          id: 'A' + pad(++seq), key: pending.key, target: targetName(pending.key), comment: txt,
          geometry: pending.geometry, mark: pending.mark || null, anchor: pending.anchor || null,
          field: pending.field || '', value: pending.value || '',
          free: pending.key.indexOf('free:') === 0, ts: Date.now(), by: me
        });
      }
        window.__av7Copied = false; saveLocal(); render();
    }
    closeModal();
  });
  document.getElementById('av7cancel').addEventListener('click', closeModal);
  document.getElementById('av7clear').addEventListener('click', function () {
    if (!annos.length) { alert('本页暂无批注'); return; }
    if (confirm('确定清空本页全部批注？')) { annos = []; saveLocal(); render(); }
  });
  document.getElementById('av7copy').addEventListener('click', function () {
    var text = JSON.stringify(exportV7(), null, 2);
    var done = function (ok) {
      if (ok) { window.__av7Copied = true; alert('已复制 ' + annos.length + ' 条 ✓'); }
      else {
        alert('自动复制失败：已在页面左上角弹出 JSON 全文，请手动全选复制。');
        var ta = document.createElement('textarea'); ta.value = text;
        ta.setAttribute('data-annotation-ui', 'true');
        ta.style.cssText = 'position:fixed;left:8px;top:8px;width:72vw;height:60vh;z-index:99999;font:12px/1.5 monospace';
        document.body.appendChild(ta); ta.select();
      }
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(fallbackCopy(text)); });
    } else { done(fallbackCopy(text)); }
  });
  function fallbackCopy(text) {
    var ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta);
    ta.select(); var ok = false; try { ok = document.execCommand('copy'); } catch (e) { ok = false; } ta.remove(); return ok;
  }

  function setMode(on) {
    mode = on;
    document.body.classList.toggle('anno-mode', on);
    chip.textContent = 'DingAI：' + (on ? '开' : '关'); chip.classList.toggle('on', on);
    gx.style.display = gy.style.display = bubble.style.display = 'none';
    tools.style.display = on ? 'flex' : 'none';
    hideInfo();
    if (on) {
      /* v7.9.1（261008 用户裁决）：批注持久化——开启时加载既有批注，不再清空 */
      try { annos = JSON.parse(localStorage.getItem(LS_KEY) || '[]'); } catch (e2) { annos = []; }
      seq = annos.length;
      render(); renderMarks(); panel.classList.add('on');
    }
    else {
      panel.classList.remove('on'); closeModal();
      saveLocal(); render();
      /* v7.9.1：退出只退模式，数据保留在 localStorage；清除唯一入口=底栏「清空」按钮 */
      document.querySelectorAll('.av7pin').forEach(function (p) { p.remove(); });
    }
  }
  chip.addEventListener('click', function () {
    if (!mode) setMode(true);
    else panel.classList.toggle('on'); /* 模式开启时点 chip=收起/展开面板；退出走面板「退出批注」或 ESC */
  });
  document.getElementById('av7hide').addEventListener('click', function (e) { e.stopPropagation(); panel.classList.remove('on'); });
  document.getElementById('av7exit').addEventListener('click', function (e) { e.stopPropagation(); requestExit(); });
  function requestExit() {
    /* v7.9.1：退出不清数据，提示语同步改；未复制仍提醒（交付=复制 JSON） */
    if (annos.length && !window.__av7Copied) {
      if (!confirm('退出批注模式？\n批注仍保留在本页（重新开启可见、可继续编辑）；如需交给开发请先点「复制 JSON」。')) return;
    }
    setMode(false);
  }
  document.addEventListener('keydown', function (e) {
    if ((e.key === 'Delete' || e.key === 'Backspace') && mode && selected >= 0 && !modal.classList.contains('on')) {
      var tag = e.target && e.target.tagName;
      if (tag !== 'INPUT' && tag !== 'TEXTAREA') {
        annos.splice(selected, 1);
        selected = -1;
        saveLocal(); render();
        e.preventDefault();
        return;
      }
    }
    if (e.key !== 'Escape' || !mode) return;
    if (modal.classList.contains('on')) { closeModal(); return; }
    requestExit();
  });

  document.addEventListener('mousemove', function (e) {
    if (!mode) return;
    gx.style.display = gy.style.display = bubble.style.display = 'block';
    gx.style.left = e.clientX + 'px'; gx.style.top = e.clientY + 'px';
    gy.style.left = e.clientX + 'px'; gy.style.top = e.clientY + 'px';
    bubble.textContent = 'client(' + e.clientX + ',' + e.clientY + ') page(' + (e.clientX + window.scrollX) + ',' + (e.clientY + window.scrollY) + ')';
    bubble.style.left = (e.clientX + 14 + 160 > window.innerWidth ? e.clientX - 174 : e.clientX + 14) + 'px';
    bubble.style.top = (e.clientY + 18 + 30 > window.innerHeight ? e.clientY - 34 : e.clientY + 18) + 'px';
  }, true);

  function distToSeg(px, py, x1, y1, x2, y2) {
    var dx = x2 - x1, dy = y2 - y1, len2 = dx * dx + dy * dy;
    if (len2 < 0.01) return Math.hypot(px - x1, py - y1);
    var t = ((px - x1) * dx + (py - y1) * dy) / len2;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
  }
  function placedPin(a) {
    var x = a.geometry.page.x, y = a.geometry.page.y;
    var ae = anchorElOf(a.key);
    if (ae && ae.getClientRects().length && a.anchor) {
      var r = ae.getBoundingClientRect();
      x = window.scrollX + r.left + a.anchor.dx;
      y = window.scrollY + r.top + a.anchor.dy;
    }
    return { x: x, y: y };
  }
  function handlesOf(a) {
    if (!a || !a.mark) return [];
    var m = placedMark(a.mark);
    if (m.type === 'arrow') return [{ name: 'start', x: m.x1, y: m.y1 }, { name: 'end', x: m.x2, y: m.y2 }];
    var x1 = Math.min(m.x1, m.x2), y1 = Math.min(m.y1, m.y2);
    var x2 = Math.max(m.x1, m.x2), y2 = Math.max(m.y1, m.y2);
    return [{ name: 'nw', x: x1, y: y1 }, { name: 'ne', x: x2, y: y1 }, { name: 'sw', x: x1, y: y2 }, { name: 'se', x: x2, y: y2 }];
  }
  function hitHandleAt(a, px, py) {
    var hs = handlesOf(a);
    for (var i = 0; i < hs.length; i++) if (Math.hypot(px - hs[i].x, py - hs[i].y) <= 8) return hs[i].name;
    return null;
  }
  function hitAnno(px, py) {
    for (var i = annos.length - 1; i >= 0; i--) {
      var a = annos[i];
      if (a.mark) {
        var m = placedMark(a.mark);
        if (m.type === 'arrow') {
          if (distToSeg(px, py, m.x1, m.y1, m.x2, m.y2) <= (m.width || 6) + 6) return i;
        } else {
          var l = Math.min(m.x1, m.x2) - 4, t = Math.min(m.y1, m.y2) - 4;
          var r = Math.max(m.x1, m.x2) + 4, b = Math.max(m.y1, m.y2) + 4;
          if (px >= l && px <= r && py >= t && py <= b) return i;
        }
      } else if (a.geometry && a.geometry.page) {
        var p = placedPin(a);
        if (Math.hypot(px - p.x, py - p.y) <= 14) return i;
      }
    }
    return -1;
  }
  function syncAnchors(mark) {
    if (!mark.anchors) return;
    function fix(an, x, y) {
      if (!an) return;
      var el = anchorElOf(an.key);
      if (!el || !el.getClientRects().length) return;
      var rc = el.getBoundingClientRect();
      an.dx = x - (window.scrollX + rc.left);
      an.dy = y - (window.scrollY + rc.top);
    }
    fix(mark.anchors.a1, mark.x1, mark.y1);
    fix(mark.anchors.a2, mark.x2, mark.y2);
  }
  function moveAnno(a, dx, dy) {
    if (a.mark) {
      a.mark.x1 = Math.round(a.mark.x1 + dx); a.mark.y1 = Math.round(a.mark.y1 + dy);
      a.mark.x2 = Math.round(a.mark.x2 + dx); a.mark.y2 = Math.round(a.mark.y2 + dy);
      if (a.mark.anchors) {
        if (a.mark.anchors.a1) { a.mark.anchors.a1.dx += dx; a.mark.anchors.a1.dy += dy; }
        if (a.mark.anchors.a2) { a.mark.anchors.a2.dx += dx; a.mark.anchors.a2.dy += dy; }
      }
      if (a.anchor) { a.anchor.dx += dx; a.anchor.dy += dy; }
    } else if (a.anchor) { a.anchor.dx += dx; a.anchor.dy += dy; }
    if (a.geometry && a.geometry.page) {
      a.geometry.page.x = Math.round(a.geometry.page.x + dx);
      a.geometry.page.y = Math.round(a.geometry.page.y + dy);
    }
  }
  function resizeAnno(a, handle, px, py) {
    var mark = a.mark; if (!mark) return;
    var m = placedMark(mark);
    if (mark.type === 'arrow') {
      if (handle === 'start') { mark.x1 = Math.round(px); mark.y1 = Math.round(py); mark.x2 = Math.round(m.x2); mark.y2 = Math.round(m.y2); }
      else { mark.x1 = Math.round(m.x1); mark.y1 = Math.round(m.y1); mark.x2 = Math.round(px); mark.y2 = Math.round(py); }
    } else {
      var l = Math.min(m.x1, m.x2), t = Math.min(m.y1, m.y2), r = Math.max(m.x1, m.x2), b = Math.max(m.y1, m.y2);
      if (handle === 'nw') { l = px; t = py; }
      else if (handle === 'ne') { r = px; t = py; }
      else if (handle === 'sw') { l = px; b = py; }
      else { r = px; b = py; }
      mark.x1 = Math.round(Math.min(l, r)); mark.y1 = Math.round(Math.min(t, b));
      mark.x2 = Math.round(Math.max(l, r)); mark.y2 = Math.round(Math.max(t, b));
    }
    syncAnchors(mark);
  }
  function commitWebText() {
    if (!textInput) return;
    var t = textInput.value.trim();
    var page = textInput._page, target = textInput._target;
    textInput.remove(); textInput = null;
    if (!t) return;
    var w = Math.max(48, Math.min(320, t.length * 9 + 16));
    var mk = { type: 'text', x1: Math.round(page.x), y1: Math.round(page.y), x2: Math.round(page.x + w), y2: Math.round(page.y + 26), text: t, color: curColor };
    mk.anchors = { a1: anchorForPage(mk.x1, mk.y1, target) };
    var key = keyOf(target) || ('free:' + mk.x1 + ',' + mk.y1);
    annos.push({
      id: 'A' + pad(++seq), key: key, target: targetName(key), comment: t,
      geometry: { client: { x: page.x - window.scrollX, y: page.y - window.scrollY }, page: { x: mk.x1, y: mk.y1 }, viewportW: window.innerWidth, viewportH: window.innerHeight, scrollX: window.scrollX, scrollY: window.scrollY },
      mark: mk, anchor: mk.anchors.a1, field: '', value: '',
      free: key.indexOf('free:') === 0, ts: Date.now(), by: me
    });
    selected = annos.length - 1;
    saveLocal(); render();
  }

  /* 标记绘制（260922 v7.6）：箭头/聚光灯拖拽；完成后弹批注表单；误触（<8px）丢弃 */
  var drawing = null, preview = null, suppressClick = false;
  document.addEventListener('mousedown', function (e) {
    if (!mode || drawing) return;
    if (e.target.closest && e.target.closest('#av7chip,#av7tools,#av7panel,#av7modal,#av7bar,#av7info')) return;
    var page = { x: e.clientX + window.scrollX, y: e.clientY + window.scrollY };
    if (curTool === 'select') {
      var handle = selected >= 0 && annos[selected] ? hitHandleAt(annos[selected], page.x, page.y) : null;
      if (handle) dragSel = { handle: handle, x: page.x, y: page.y };
      else {
        selected = hitAnno(page.x, page.y);
        dragSel = selected >= 0 ? { handle: null, x: page.x, y: page.y } : null;
      }
      suppressClick = true;
      render();
      e.preventDefault(); e.stopImmediatePropagation();
      return;
    }
    if (curTool === 'text') {
      if (textInput) { textInput.remove(); textInput = null; }
      textInput = document.createElement('input');
      textInput.type = 'text';
      textInput.setAttribute('data-annotation-ui', 'true');
      textInput.placeholder = '文字，回车确认';
      textInput.style.cssText = 'position:absolute;z-index:99998;width:180px;height:26px;font:13px sans-serif;border:1px solid #cbd5e1;border-radius:4px;padding:2px 6px';
      textInput.style.left = page.x + 'px'; textInput.style.top = page.y + 'px';
      textInput._page = page; textInput._target = e.target;
      textInput.addEventListener('keydown', function (ev) {
        ev.stopPropagation();
        if (ev.key === 'Enter') { commitWebText(); ev.preventDefault(); }
        else if (ev.key === 'Escape') { textInput.remove(); textInput = null; ev.preventDefault(); }
      });
      document.body.appendChild(textInput);
      textInput.focus();
      suppressClick = true;
      e.preventDefault(); e.stopImmediatePropagation();
      return;
    }
    if (curTool === 'point') return;
    if (e.target.closest && (e.target.closest('.av7pin') || e.target.closest('.av7arrow') || e.target.closest('.av7spot') || e.target.closest('.av7shape') || e.target.closest('.av7text'))) return;
    drawing = { x1: e.clientX + window.scrollX, y1: e.clientY + window.scrollY, target: e.target, moved: false };
    e.preventDefault(); e.stopImmediatePropagation();
  }, true);
  document.addEventListener('mousemove', function (e) {
    if (dragSel && selected >= 0 && annos[selected]) {
      var p = { x: e.clientX + window.scrollX, y: e.clientY + window.scrollY };
      if (dragSel.handle) resizeAnno(annos[selected], dragSel.handle, p.x, p.y);
      else moveAnno(annos[selected], p.x - dragSel.x, p.y - dragSel.y);
      dragSel.x = p.x; dragSel.y = p.y;
      render();
      return;
    }
    if (!drawing) return;
    var x2 = e.clientX + window.scrollX, y2 = e.clientY + window.scrollY;
    drawing.x2 = x2; drawing.y2 = y2; drawing.moved = true;
    if (!preview) {
      if (curTool === 'arrow') {
        var NSp = 'http://www.w3.org/2000/svg';
        preview = document.createElementNS(NSp, 'svg');
        preview.style.cssText = 'position:fixed;left:0;top:0;width:100vw;height:100vh;pointer-events:none;z-index:99994';
        var defs = document.createElementNS(NSp, 'defs');
        defs.innerHTML = markerDef('av7ahp', curStyle, curColor);
        var ln = document.createElementNS(NSp, 'path');
        ln.setAttribute('class', 'av7arrow');
        if (AV_STYLES[curStyle] && (AV_STYLES[curStyle].kind === 'open' || AV_STYLES[curStyle].kind === 'dot')) { ln.setAttribute('fill', 'none'); ln.setAttribute('stroke', curColor); ln.setAttribute('stroke-width', curWidth); ln.setAttribute('stroke-linecap', 'round'); }
        else { ln.setAttribute('fill', curColor); ln.setAttribute('stroke', curColor); ln.setAttribute('stroke-width', Math.max(1.5, curWidth * 0.32)); }
        ln.setAttribute('stroke-linejoin', 'round'); ln.setAttribute('stroke-linecap', 'round');
        preview.appendChild(ln); preview._line = ln;
        document.body.appendChild(preview);
      } else {
        preview = document.createElement('div');
        preview.style.cssText = 'position:absolute;border-radius:' + (curTool === 'ellipse' ? '50%' : '8px') + ';pointer-events:none;border:' + curWidth + 'px solid ' + curColor + ';background:' + curColor + '14;';
        markLayer.appendChild(preview);
      }
      preview.setAttribute('data-annotation-ui', 'true');
    }
    if (curTool === 'arrow') {
      preview._line.setAttribute('d', buildArrowD(curStyle, drawing.x1 - window.scrollX, drawing.y1 - window.scrollY, x2 - window.scrollX, y2 - window.scrollY, curWidth));
    } else {
      preview.style.left = Math.min(drawing.x1, x2) + 'px'; preview.style.top = Math.min(drawing.y1, y2) + 'px';
      preview.style.width = Math.abs(x2 - drawing.x1) + 'px'; preview.style.height = Math.abs(y2 - drawing.y1) + 'px';
    }
  }, true);
  document.addEventListener('mouseup', function (e) {
    if (dragSel) { dragSel = null; saveLocal(); return; }
    if (!drawing) return;
    var d = drawing; drawing = null;
    if (preview) { preview.remove(); preview = null; }
    suppressClick = true;
    if (!d.moved || d.x2 == null || Math.hypot(d.x2 - d.x1, d.y2 - d.y1) < 8) return;
    var mk = curTool === 'arrow'
      ? { type: 'arrow', x1: Math.round(d.x1), y1: Math.round(d.y1), x2: Math.round(d.x2), y2: Math.round(d.y2), color: curColor, width: curWidth, style: curStyle }
      : { type: curTool, x1: Math.round(Math.min(d.x1, d.x2)), y1: Math.round(Math.min(d.y1, d.y2)), x2: Math.round(Math.max(d.x1, d.x2)), y2: Math.round(Math.max(d.y1, d.y2)), color: curColor, width: curWidth };
    var endEl = document.elementFromPoint(e.clientX, e.clientY) || d.target;
    mk.anchors = { a1: anchorForPage(mk.x1, mk.y1, d.target), a2: anchorForPage(mk.x2, mk.y2, endEl) };
    var page = { x: Math.round((mk.x1 + mk.x2) / 2), y: Math.round((mk.y1 + mk.y2) / 2) };
    var key = keyOf(d.target) || ('free:' + page.x + ',' + page.y);
    var fi = fieldInfoOf(d.target);
    openModal({ key: key, geometry: { client: { x: page.x - window.scrollX, y: page.y - window.scrollY }, page: page, viewportW: window.innerWidth, viewportH: window.innerHeight, scrollX: window.scrollX, scrollY: window.scrollY }, mark: mk, anchor: mk.anchors.a1, field: fi.field, value: fi.value, existing: null }, false);
  }, true);

  document.addEventListener('click', function (e) {
    if (!mode) return;
    if (suppressClick) { suppressClick = false; return; }
    if ((curTool === 'select' || curTool === 'text') && e.target.closest && e.target.closest('.av7pin,.av7arrow,.av7spot,.av7shape,.av7text')) {
      e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation();
      return;
    }
    if (curTool !== 'point') return;
    if (e.target.closest && e.target.closest('#av7chip,#av7tools,#av7bar,#av7panel,#av7modal,.av7pin,#av7info,.av7arrow,.av7spot,.av7shape,.av7text')) return;
    /* stopImmediatePropagation：拦掉后注册的 outside-close 委托（MO 下钻等），标注点击不得折叠页面状态 */
    e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation();
    var client = { x: e.clientX, y: e.clientY };
    var page = { x: e.clientX + window.scrollX, y: e.clientY + window.scrollY };
    var key = keyOf(e.target) || ('free:' + page.x + ',' + page.y);
    var fi = fieldInfoOf(e.target);
    var ae = anchorElOf(key);
    var anchor = null;
    if (ae) { var r = ae.getBoundingClientRect(); anchor = { dx: page.x - (window.scrollX + r.left), dy: page.y - (window.scrollY + r.top) }; }
    openModal({ key: key, geometry: { client: client, page: page, viewportW: window.innerWidth, viewportH: window.innerHeight, scrollX: window.scrollX, scrollY: window.scrollY }, anchor: anchor, field: fi.field, value: fi.value, existing: null }, false);
  }, true);

  /* 三级管理员门（260920 全站版）：①页面自定义 ANNO_ADMIN_CHECK() 回调 ②页面自定义 window.ANNO_V7_ADMIN / 门户 annoPortalAdmin ③?anno=1 会话级解锁（公开页管理员自救通道） */
  var chipShown = false;
  function refreshAdminGate() {
    function grant(who) { me = who; if (!chipShown) { chipShown = true; chip.style.display = 'block'; } }
    if (chipShown || !document.body) return;
    if (typeof window.ANNO_ADMIN_CHECK === 'function') { try { Promise.resolve(window.ANNO_ADMIN_CHECK()).then(function (u) { if (u) grant(String(u)); }); } catch (e) {} }
    if (window.ANNO_V7_ADMIN === true) grant('admin');
    try { if (sessionStorage.getItem('annoPortalAdmin') === '1') grant('admin'); } catch (e) {}
    try {
      if (new URLSearchParams(location.search).get('anno') === '1') { sessionStorage.setItem('annoUnlocked', '1'); localStorage.setItem('annoUnlocked', '1'); }
      var unlocked = false;
      try { unlocked = sessionStorage.getItem('annoUnlocked') === '1' || localStorage.getItem('annoUnlocked') === '1'; } catch (e2) {}
      if (unlocked) grant('admin');
    } catch (e) {}
  }
  setInterval(refreshAdminGate, 3000); refreshAdminGate();
  /* 公开页免参数解锁（260921：用户实测「?anno=1 记不住」）：chip 未显示时右下角给低调 ✎ 入口，点击=本设备解锁；ANNO_HIDE_UNLOCK=true 可隐藏 */
  if (!window.ANNO_HIDE_UNLOCK) {
    var ub = document.createElement('button');
    ub.type = 'button'; ub.id = 'av7unlock';
    ub.setAttribute('data-annotation-ui', 'true');
    ub.title = '开启 DingAI（管理员）';
    ub.textContent = '✎ DingAI';
    ub.style.cssText = 'position:fixed;right:12px;bottom:12px;z-index:99992;background:#0f172acc;color:#cbd5e1;border:1px solid #334155;border-radius:8px;padding:5px 11px;font:12px sans-serif;cursor:pointer;opacity:.55';
    ub.addEventListener('mouseenter', function () { ub.style.opacity = '1'; });
    ub.addEventListener('mouseleave', function () { ub.style.opacity = '.55'; });
    ub.addEventListener('click', function () {
      try { localStorage.setItem('annoUnlocked', '1'); sessionStorage.setItem('annoUnlocked', '1'); } catch (e) {}
      ub.remove(); refreshAdminGate();
    });
    (function () {
      var put = function () { if (!chipShown && document.body && !document.getElementById('av7unlock')) document.body.appendChild(ub); else if (chipShown && document.getElementById('av7unlock')) ub.remove(); };
      setInterval(put, 3000); put();
    })();
  }
  /* 旧版批注入口压制：检测到旧实现按钮则隐藏（旧代码成死代码，不再双轨） */
  var legacyBtn = document.getElementById('btn-anno-mode');
  if (legacyBtn) legacyBtn.style.display = 'none';

  /* ===== 页内桥 anno-bridge v1（anno-bridge）=====
     桌面钉(AnnoOverlay)↔页面钉坐标同步：管理员态探测本机桥服务(127.0.0.1:8763)，
     轮询取 resolve 请求 → elementsFromPoint 反查元素 → POST answer；
     App 侧择优写入桌面钉 pin.page（key/field/value 与本页批注同源语义）。
     无桥(App 未跑)→探测失败安静、30s 低频重试；非管理员态不启动。 */
  var AV7_BRIDGE = 'http://127.0.0.1:8763';
  var av7bridge = null;   // {client, token, since, pollTimer}

  /* 视口坐标→元素描述（与批注点击同源：keyOf/fieldInfoOf/targetName 复用） */
  function describePoint(cx, cy) {
    var list = [];
    try { list = document.elementsFromPoint(cx, cy) || []; } catch (e) {}
    var t = null;
    for (var i = 0; i < list.length; i++) {
      if (!list[i].closest || !list[i].closest('[data-annotation-ui]')) { t = list[i]; break; }
    }
    if (!t) t = list[0] || document.body;
    var key = keyOf(t), fi = fieldInfoOf(t);
    var txt = (t.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60);
    var rect = t.getBoundingClientRect ? t.getBoundingClientRect() : { left: cx, top: cy };
    return {
      key: key || ('free:' + Math.round(cx + window.scrollX) + ',' + Math.round(cy + window.scrollY)),
      target: key ? targetName(key) : '自由位置',
      field: fi.field, value: fi.value, text: txt,
      anchorDx: cx - rect.left, anchorDy: cy - rect.top
    };
  }
  function av7Describe(req) {
    /* 全局点(主屏左上原点,JS screen 系)→本页视口 CSS 坐标 */
    var vpX = window.screenX, vpY = window.screenY + (window.outerHeight - window.innerHeight);
    var cx = req.gx - vpX, cy = req.gy - vpY;
    var hit = cx >= 0 && cx < window.innerWidth && cy >= 0 && cy < window.innerHeight;
    var o = {
      hit: hit,
      winScreenX: window.screenX, winScreenY: window.screenY,
      outerW: window.outerWidth, outerH: window.outerHeight,
      dpr: window.devicePixelRatio, visibility: document.visibilityState,
      title: document.title   /* 261019a 加：钉 JSON pin.page 可肉眼核对是否抓对标签页 */
    };
    if (!hit) return o;
    var d = describePoint(cx, cy);
    o.clientX = Math.round(cx); o.clientY = Math.round(cy);
    o.pageX = Math.round(cx + window.scrollX); o.pageY = Math.round(cy + window.scrollY);
    o.scrollX = Math.round(window.scrollX); o.scrollY = Math.round(window.scrollY);
    o.viewportW = window.innerWidth; o.viewportH = window.innerHeight;
    o.key = d.key; o.target = d.target; o.field = d.field; o.value = d.value; o.text = d.text;
    o.anchorKey = d.key; o.anchorDx = Math.round(d.anchorDx || 0); o.anchorDy = Math.round(d.anchorDy || 0);
    return o;
  }
  function av7Answer(req) {
    var b = av7bridge; if (!b || b.client == null) return;
    var o = av7Describe(req);
    o.client = b.client; o.token = b.token; o.reqId = req.id; o.url = location.href;
    /* text/plain=简单请求免 CORS preflight(App 手写 HTTP 不处理 OPTIONS) */
    fetch(AV7_BRIDGE + '/answer', { method: 'POST', headers: { 'Content-Type': 'text/plain' }, body: JSON.stringify(o) }).catch(function () {});
  }
  function av7Poll() {
    var b = av7bridge; if (!b || b.client == null) return;
    fetch(AV7_BRIDGE + '/pending?client=' + b.client + '&token=' + encodeURIComponent(b.token) + '&since=' + b.since, { cache: 'no-store' })
      .then(function (r) {
        if (r.status === 403) {  /* App 重启→token 变→重注册 */
          b.client = null; b.token = null;
          try { clearInterval(b.pollTimer); } catch (e) {}
          setTimeout(av7Probe, 1000);
          return null;
        }
        return r.json();
      })
      .then(function (j) {
        if (!j || !j.requests) return;
        b.since = j.seq;
        j.requests.forEach(function (rq) { av7Answer(rq); });
      })
      .catch(function () {});
  }
  function av7State(phase, extra) {
    try {
      var b = av7bridge;
      window.__AV7_BRIDGE_STATE = Object.assign({
        phase: phase, client: b ? b.client : null,
        es: b && b.es ? b.es.readyState : null,   // 0=connecting 1=open 2=closed
        since: b ? b.since : null
      }, extra || {});
    } catch (e) {}
  }
  function av7Probe() {
    var b = av7bridge; if (!b) return;
    fetch(AV7_BRIDGE + '/ping', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j || !j.token || !av7bridge) return;
        b.client = j.client; b.token = j.token; b.since = 0;
        av7State('probed');
        av7SSE();
        if (!b.pollTimer) { b.pollTimer = setInterval(av7Poll, 1500); av7Poll(); }
      })
      .catch(function () { setTimeout(av7Probe, 30000); });   /* App 未跑→安静低频重试 */
  }
  /* SSE 订阅(261014b):批注时浏览器必在后台,轮询 timer 被浏览器节流到 ~1 次/分钟,
     网络推送不受节流——SSE 是生产场景可靠通道;轮询保留为前台兜底(answer 幂等) */
  function av7SSE() {
    var b = av7bridge; if (!b || b.client == null) return;
    if (b.es) { try { b.es.close(); } catch (e) {} }
    try {
      var es = new EventSource(AV7_BRIDGE + '/events?client=' + b.client + '&token=' + encodeURIComponent(b.token));
      b.es = es;
      es.onopen = function () { av7State('sse-open'); };
      es.onmessage = function (ev) {
        try { av7State('sse-msg'); av7Answer(JSON.parse(ev.data)); } catch (e) {}
      };
      es.addEventListener('track', function (ev) {
        try {
          var msg = JSON.parse(ev.data);
          var bNow = av7bridge; if (!bNow || bNow.client == null) return;
          var positions = [];
          (msg.pins || []).forEach(function (pin) {
            var el = anchorElOf(pin.key);
            if (!el || !el.getClientRects().length) { positions.push({ id: pin.id, ok: false }); return; }
            var r = el.getBoundingClientRect();
            var chrome = window.outerHeight - window.innerHeight;
            var dx = +pin.dx || 0, dy = +pin.dy || 0;
            positions.push({
              id: pin.id, ok: true,
              screenX: window.screenX + r.left + dx,
              screenY: window.screenY + chrome + r.top + dy,
              pageX: Math.round(window.scrollX + r.left + dx),
              pageY: Math.round(window.scrollY + r.top + dy),
              scrollX: Math.round(window.scrollX), scrollY: Math.round(window.scrollY),
              clientX: Math.round(r.left + dx), clientY: Math.round(r.top + dy)
            });
          });
          if (!positions.length) return;
          fetch(AV7_BRIDGE + '/track', { method: 'POST', headers: { 'Content-Type': 'text/plain' }, body: JSON.stringify({ client: bNow.client, token: bNow.token, positions: positions }) }).catch(function () {});
        } catch (e2) {}
      });
      es.onerror = function () {
        try { es.close(); } catch (e2) {}
        if (av7bridge === b) { b.es = null; setTimeout(function () { if (av7bridge === b && b.client != null) av7SSE(); else av7Probe(); }, 3000); }
      };
    } catch (e3) { /* EventSource 不可用→纯轮询 */ }
  }
  (function av7BridgeStart() {
    setInterval(function () { if (chipShown && !av7bridge) { av7bridge = { client: null, token: null, since: 0, pollTimer: null }; av7Probe(); } }, 3000);
    if (chipShown) { av7bridge = { client: null, token: null, since: 0, pollTimer: null }; av7Probe(); }
  })();
})();

window.__AV7_BUILD='261019a';
