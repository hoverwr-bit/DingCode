# DingAI macOS 版 App Store 上架清单（专业版内购）

代码里的解锁链路（`ProStore`，StoreKit 2）已就绪，上架前需在 App Store Connect 完成：

## 一次性配置

- [ ] **Paid Apps 协议**：App Store Connect → Business → Agreements, Tax, and Banking → 签 Paid Apps 协议 + 税务 + 银行（收款前提）
- [ ] **App Record**：新建 macOS App，Bundle ID 用 `io.github.dingai.mac`（与 Info.plist 一致）
- [ ] **内购商品**：App → In-App Purchases → 新建 **Non-Consumable**，Product ID 必须是：
      `dev.dingcode.pro.lifetime`（与 `DingAI.swift` 中 `ProStore.productId` 一致）
- [ ] 商品审核信息：给审核员的演示步骤（打开 App → 菜单栏「升级专业版…」→ 看到商品）
- [ ] 沙盒测试：App Store Connect → Users and Access → Sandbox 加测试账号；Xcode 用 StoreKit 配置文件本地测

## 技术注意

- 沙盒化改造：App Store 版须开 App Sandbox。屏幕录制用 ScreenCaptureKit + `com.apple.security.device.camera`?（不需要相机；
  需要 `com.apple.security.app-sandbox` + 用户在系统设置里授予「屏幕录制」——沙盒 App 的屏幕录制权限在 macOS 14+ 走 SCContentSharingPicker 更稳，
  如审核被拒按当时回复调整）。辅助功能跟随是尽力而为项，被拒可声明移除。
- 构建要求：Xcode 26 + macOS 26 SDK（同 iOS 上传要求，见根 README 与 Apple upcoming requirements）。
- 解锁落盘：购买成功写 `~/DingAI/license.json`（container 外路径，沙盒需开 `com.apple.security.files.user-selected` 之外的
  用户目录读写 entitlement 或改用 Application Support 容器内路径——上架前需按沙盒 entitlement 实测一次，
  若写 `~/DingAI` 被沙盒拦截，改写到 `~/Library/Containers/<bundle>/Data/DingAI` 并同步改 `currentEdition()` 的查找路径）。

## 分成

加入 Small Business Program（年营收 < $100 万）后 Apple 抽 15%，否则 30%。
