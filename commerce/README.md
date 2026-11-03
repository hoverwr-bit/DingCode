# DingCode 专业版 — Cloudflare 授权服务

零服务器跑通「网页购买 → 自动发密钥」。与 App Store 内购（macOS 端）共用同一套 `DGA1` 密钥体系。

## 架构

```
用户点购买 ──→ Lemon Squeezy 收银台（信用卡/PayPal，代扣 VAT）
      │order_paid webhook
      ▼
Cloudflare Worker (本目录) ── 验签 → 签发 DGA1 密钥 → KV 存档 → Resend 发邮件
      │
      ▼
用户邮箱收到密钥 → 写入 ~/DingAI/license.json → handoff.py edition 显示 pro
```

## 文件

| 文件 | 作用 |
|---|---|
| `worker.js` | Worker 全部逻辑：落地页 + webhook + 在线核验 |
| `wrangler.toml` | 部署配置（KV binding、secrets 名称） |
| `test-worker.js` | 本地用 Node 内置 mock 跑 webhook 验签 + 密钥算法一致性测试 |

## 部署步骤

1. **装 CLI 并登录**

   ```bash
   npm i -g wrangler && wrangler login
   ```

2. **建 KV（存已发密钥，用于吊销/核验）**

   ```bash
   wrangler kv namespace create LICENSES
   # 把返回的 id 填进 wrangler.toml 的 kv_namespaces
   ```

3. **配 secrets（都不要写进仓库）**

   ```bash
   wrangler secret put LICENSE_SECRET     # DGA1 HMAC 密钥，必须与客户端验证侧一致
   wrangler secret put LS_WEBHOOK_SECRET  # Lemon Squeezy → Settings → Webhooks 里生成的 signing secret
   wrangler secret put RESEND_API_KEY     # resend.com 的 API key（发件用）
   wrangler secret put MAIL_FROM          # 例如 "DingCode <keys@yourdomain.com>"
   ```

4. **部署**

   ```bash
   wrangler deploy
   ```

5. **Lemon Squeezy 侧**
   - 建 Product（如 “DingCode Pro — 全平台终身版”），拿到 checkout permalink
   - Settings → Webhooks → 添加 `https://<你的worker>.workers.dev/webhook/lemonsqueezy`，
     事件勾 `order_created`，复制 signing secret 到第 3 步
   - 把 worker.js 里 `BUY_URL` 常量换成你的 checkout 链接

6. **自托管团队客户**：不必走这套。他们自己的 team-server 设 `DINGAI_LICENSE_SECRET`
   后用 `POST /api/license/issue` 自行签发，密钥算法与本 Worker 完全一致。

## 密钥算法（与 core/edition.py 逐字节一致）

```
key  = DGA1-<edition>-<yyyymmdd>-<hmac16>
hmac16 = HMAC-SHA256(LICENSE_SECRET, "DGA1|<edition>|<yyyymmdd>") 的前 8 字节 hex
```

改 `LICENSE_SECRET` 后旧密钥即刻失效——用于泄漏应急。默认终身版到期日 `99991231`。

## 测试

```bash
node test-worker.js    # 不依赖网络，验证算法与 Python 版一致 + 验签逻辑
```

生产冒烟：下单测试商品 → 看 Worker 日志 `wrangler tail` → 邮箱收密钥 →
`DINGAI_LICENSE=<key> python3 tools/dingai/handoff.py edition` 应显示 pro。
