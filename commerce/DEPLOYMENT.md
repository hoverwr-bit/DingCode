# DingCode 商业部署档案（2026-11-03）

> 本文件记录网页售卖渠道（Lemon Squeezy + Cloudflare Worker）的生产部署状态，
> 供任何新对话/新协作者直接接续。改动部署后请同步更新本文件。

## 渠道总览

| 渠道 | 状态 | 说明 |
|---|---|---|
| App Store 内购（macOS） | 🟡 商品已建，待协议与发布 | owner 告知 IAP 商品已建；本地编译、签名及 App Store 解锁记录识别通过，Paid Apps 协议、沙盒测试和上传仍待核验 |
| Lemon Squeezy 网页买断 | 🟡 Worker 与结账链接已部署，店铺审核中 | 商品与 webhook 仍为 test 模式；已建商品的名称、价格、变体状态仍需在 dashboard 修正 |
| 团队版 team-server | ✅ 已交付 | 自托管，见 `tools/dingai/team-server/`，密钥算法与本 Worker 一致 |

## 账号与 ID

- **GitHub**：`hoverwr-bit/DingCode`（已公开，main 为完整代码）
- **Lemon Squeezy 店铺**：`hoverwr` / slug `dingcode`，store id **514040**，
  国家 Viet Nam，货币 VND，管理员 hoverwr@gmail.com，登录入口 https://app.lemonsqueezy.com
- **Cloudflare**：账户 id `4d281c74832e1586c16f544421fe24a7`，
  workers.dev 子域名 `dingcode.workers.dev`
- **Resend**：免费版，发件人暂用 `DingCode Pro <onboarding@resend.dev>`

## 已部署组件

- **Worker**：`https://dingcode-licenses.dingcode.workers.dev`
  - `GET /` 落地页已接真实 checkout：`https://dingcode.lemonsqueezy.com/checkout/buy/120504ba-8720-4256-ad88-d988a5057035`
  - 2026-11-03 重新部署，Version ID `64b7deaf-0d7c-4ae5-9239-d92db33d8d2b`；线上已核验新链接且旧占位链接消失
  - `POST /webhook/lemonsqueezy` LS webhook，验签 → 签发 DGA1 → KV → Resend 发邮件
  - `GET /api/license/verify?key=` 在线核验/吊销抓手
- **KV namespace**：`LICENSES` = `94b4b293ca29400d89fecb1a8c1231d5`
- **Webhook**：LS webhook id **148809**，事件 `order_created`，
  URL `https://dingcode-licenses.dingcode.workers.dev/webhook/lemonsqueezy`。
  ⚠️ 当前 **test 模式**（随店铺未激活）；店铺激活后需在 LS 侧重建/切换为 live。

## 密钥体系（重要）

- DGA1 生产密钥（LICENSE_SECRET）：已同时写入
  ① Worker secret `LICENSE_SECRET`、② `tools/dingai/core/edition.py` 的 `_DEFAULT_SECRET`（main）。
  两个必须保持一致，改一处必须同步另一处。
- 算法三方一致（Python / Node / Worker），回归测试：`node commerce/test-worker.js`
  （需在仓库目录内跑，依赖 `../tools/dingai`）。

## 凭据存放（本机，不进 git）

统一备份在 owner 本机任务工作区（权限 600）：
`/Users/ice/Documents/kimi/tasks/2026-11-03/10-01-01-3a177ace/secrets/`

| 文件 | 内容 |
|---|---|
| `license_secret` | DGA1 HMAC 生产密钥（hex64，与 edition.py 相同） |
| `ls_webhook_secret` | LS webhook 验签密钥（≤40 字符限制） |
| `ls_api_key` | Lemon Squeezy API key（店铺级权限） |
| `cf_api_token` | Cloudflare API Token（Edit Cloudflare Workers 模板） |
| `resend_api_key` | Resend API key（`re_…`） |

使用方式：`export CLOUDFLARE_API_TOKEN=$(cat …/secrets/cf_api_token)` 后可直接跑 wrangler。
⚠️ 这些文件只存在于 owner 本机；如需在 mini 上操作，先 scp 过去。

## 剩余清单（按序）

1. **修正已建 LS 商品**（网页 API 不支持写商品，只能 dashboard）：当前 product id `1498304`、
   variant id `2333468`，名称 `dingcode`、variant `Default`、价格 **₫99,999**、variant `pending`，
   product `published` 且为 test 模式。改成名 “DingCode Pro — 全平台终身版”，one-time，
   variant “终身版” **₫399,000**，variant Status=Live/Published。
2. ✅ **接入 checkout 并重新部署 Worker**：已完成，见上方 Version ID；`node commerce/test-worker.js`
   已全部通过（测试现为 Python 验签显式注入同一个测试 secret，避免与生产默认 secret 混用）。
3. **店铺激活**：后台已显示 “Your application has been received and will be reviewed as soon as possible”，
   需等审核通过；然后把 webhook 148809 切到 live 模式（或在 live 下重建 webhook，注意
   LS webhook secret ≤40 字符，改后要同步 `wrangler secret put LS_WEBHOOK_SECRET`）。
4. **提现**：Settings → Payout 已登记 Vietcombank 账户（CITAD `01203001`，
   账号 `1070997571`，户名 `WANG GANG`）；本次未能登录复核绑定状态。
5. 真实下单测试（可用 LS test mode 的 100% off 测试商品）：走一遍
   下单 → 收邮件 → `DINGAI_LICENSE=<key> python3 tools/dingai/handoff.py edition` 显示 pro。
6. **App Store 渠道**（与网页渠道独立）：owner 告知 IAP 商品 `dev.dingcode.pro.lifetime` 已建；
   仍须在 App Store Connect 核验 Paid Apps 协议、商品审核信息与沙盒账号，并完成发布构建和上传。
   macOS 端 StoreKit 解锁写 `~/DingAI/license.json` 的 `{"edition":"pro","source":"appstore"}` 记录；
   2026-11-03 已验证该记录能被 `handoff.py edition` 识别为 pro。本机 `swiftc` 编译、签名和
   `codesign --verify` 已通过，但只有 Command Line Tools、没有完整 Xcode，尚不能产出 App Store 上传包。

## 常用运维命令

```bash
cd <repo>/commerce
export CLOUDFLARE_API_TOKEN=$(cat <secrets>/cf_api_token)
npx wrangler deploy                  # 部署
npx wrangler tail                    # 实时日志
npx wrangler kv key list --namespace-id=94b4b293ca29400d89fecb1a8c1231d5 --remote   # 已发密钥
npx wrangler kv key get "email:<买家邮箱>" --namespace-id=94b4b293ca29400d89fecb1a8c1231d5 --remote
# 吊销某 key：把该 key 的 KV 记录 revoked 改 true（wrangler kv key put）
```

注意：`wrangler kv key get/list` 必须加 `--remote`，否则读的是本地空数据。
