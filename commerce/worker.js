// DingCode 专业版授权 Worker：落地页 + Lemon Squeezy webhook + 密钥在线核验。
// 密钥算法与 tools/dingai/core/edition.py 逐字节一致（改一处必须同步另一处）。

const BUY_URL = "https://dingcode.lemonsqueezy.com/buy/pro-lifetime"; // ← 换成你的 checkout 链接

const HTML = `<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DingCode — 给写代码的 AI 用的钉</title>
<style>
body{margin:0;font:16px/1.7 -apple-system,"PingFang SC",sans-serif;background:#0b1220;color:#e2e8f0}
.wrap{max-width:820px;margin:0 auto;padding:64px 24px}
h1{font-size:34px;margin:0 0 8px}
p.sub{color:#94a3b8;margin:0 0 36px}
table{width:100%;border-collapse:collapse;margin:24px 0;font-size:14px}
td,th{padding:10px 12px;border-bottom:1px solid #1e293b;text-align:left}
th{color:#94a3b8;font-weight:500}
.yes{color:#4ade80}.no{color:#475569}
.cta{display:inline-block;background:#2563eb;color:#fff;text-decoration:none;padding:13px 34px;border-radius:8px;font-size:16px;margin-top:12px}
.price{color:#fbbf24;font-size:20px}
.foot{margin-top:48px;color:#475569;font-size:13px}
</style>
</head>
<body>
<div class="wrap">
<h1>DingCode</h1>
<p class="sub">在屏幕上钉一下，coding agent 拿到机器可读的 JSON。</p>
<table>
<tr><th></th><th>Community 免费</th><th>Pro 专业版</th></tr>
<tr><td>定位钉 + JS 描述复制</td><td class="yes">✓</td><td class="yes">✓</td></tr>
<tr><td>箭头 / 方框 / 椭圆 / 聚光 / 文字</td><td class="no">—</td><td class="yes">✓</td></tr>
<tr><td>范围检查 + 回退 / 发布评审</td><td class="no">—</td><td class="yes">✓</td></tr>
<tr><td>agent 工作流 + 钉过直接执行 + 驾驶台</td><td class="no">—</td><td class="yes">✓</td></tr>
<tr><td>macOS / Windows / Linux / 网页 全端可用</td><td class="yes">✓</td><td class="yes">✓</td></tr>
</table>
<p class="price">终身版 <span id="buy">购买后密钥自动发到邮箱</span></p>
<a class="cta" href="${BUY_URL}">购买 Pro 终身版</a>
<p class="foot">macOS 用户也可以在 App Store 免费下载、内购解锁（同一套密钥体系）。<br>
开源仓库：<a style="color:#60a5fa" href="https://github.com/hoverwr-bit/DingCode">github.com/hoverwr-bit/DingCode</a></p>
</div>
</body>
</html>`;

// ---- DGA1 密钥：与 core/edition.py issue_key 等价 ----
async function issueKey(edition, yyyymmdd, secret) {
  const payload = `DGA1|${edition}|${yyyymmdd}`;
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(payload)));
  let hex = "";
  for (let i = 0; i < 8; i++) hex += sig[i].toString(16).padStart(2, "0");
  return `DGA1-${edition}-${yyyymmdd}-${hex}`;
}

async function verifyLemonSqueezy(rawBody, signature, secret) {
  if (!signature || !secret) return false;
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const expect = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(rawBody)));
  const got = new Uint8Array(signature.length / 2);
  for (let i = 0; i < got.length; i++) got[i] = parseInt(signature.substr(i * 2, 2), 16);
  if (got.length !== expect.length) return false;
  let diff = 0;
  for (let i = 0; i < got.length; i++) diff |= got[i] ^ expect[i];
  return diff === 0;
}

async function sendMail(to, subject, text) {
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${RESEND_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ from: MAIL_FROM, to, subject, text }),
  });
  return res.ok;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/") {
      return new Response(HTML, { headers: { "Content-Type": "text/html; charset=utf-8" } });
    }

    // Lemon Squeezy webhook：order_paid → 签发密钥 + 发邮件
    if (request.method === "POST" && url.pathname === "/webhook/lemonsqueezy") {
      const raw = await request.text();
      const ok = await verifyLemonSqueezy(
        raw, request.headers.get("X-Signature") || "", env.LS_WEBHOOK_SECRET);
      if (!ok) return new Response("bad signature", { status: 401 });
      let event;
      try { event = JSON.parse(raw); } catch { return new Response("bad json", { status: 400 }); }
      const name = event.meta?.event_name || "";
      if (name !== "order_created" && name !== "order_paid") {
        return new Response("ignored", { status: 200 });
      }
      const attrs = event.data?.attributes || {};
      const email = attrs.user_email || attrs.customer_email || "";
      if (!email) return new Response("no email", { status: 400 });
      const variant = String(event.data?.relationships?.variant?.data?.id || "");
      // 可选：按 variant 区分版本，变体元数据里存到期日
      let expires = "99991231"; // 终身版
      if (attrs.variant_name && /year/i.test(attrs.variant_name)) {
        const d = new Date(Date.now() + 365 * 86400e3);
        expires = `${d.getUTCFullYear()}${String(d.getUTCMonth() + 1).padStart(2, "0")}${String(d.getUTCDate()).padStart(2, "0")}`;
      }
      const key = await issueKey("pro", expires, env.LICENSE_SECRET);
      await env.LICENSES.put(`key:${key}`, JSON.stringify({ email, variant, issued_at: Date.now(), revoked: false }));
      await env.LICENSES.put(`email:${email}`, key);
      const mailOk = await sendMail(email,
        "你的 DingCode Pro 密钥",
        `感谢购买 DingCode Pro。\n\n密钥：${key}\n\n使用方式（任一）：\n`
        + `1. 命令行临时解锁：DINGAI_LICENSE=${key} python3 tools/dingai/handoff.py edition\n`
        + `2. 写入 ~/DingAI/license.json：{"key": "${key}"}\n`
        + `3. 网页端：localStorage['dingai-license'] = '${key}'\n\n`
        + `到期日：${expires === "99991231" ? "终身" : expires}\n`);
      return new Response(JSON.stringify({ ok: true, mailed: mailOk }), { status: 200 });
    }

    // 在线核验：客户端可选调用；退款吊销的抓手
    if (request.method === "GET" && url.pathname === "/api/license/verify") {
      const key = url.searchParams.get("key") || "";
      const record = await env.LICENSES.get(`key:${key}`, "json");
      if (!record) return Response.json({ ok: false, error: "unknown key" }, { status: 404 });
      if (record.revoked) return Response.json({ ok: false, error: "revoked" }, { status: 403 });
      return Response.json({ ok: true, email: record.email, expires: key.split("-")[2] });
    }

    return new Response("not found", { status: 404 });
  },
};
