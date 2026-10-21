#!/bin/bash
# DingCode 构建脚本:编译 → 组装 .app → 签名
# 签名策略:优先 "DingCode Dev",再 "DingAI Dev",再 "AnnoOverlay Dev"(身份稳定,重编译不丢屏幕录制授权);
#           证书未导入时回退 ad-hoc(每次重编译 TCC 身份漂移,需重新授权)
set -euo pipefail
cd "$(dirname "$0")"

# Swift 6 defaults the binary to the SDK (minos 28 on the current toolchain). Pin 14.0,
# matching LSMinimumSystemVersion, or LaunchServices refuses to open the app (-10825).
swiftc -O -swift-version 5 -target "$(uname -m)-apple-macos14.0" -o DingCode DingCode.swift \
  -framework AppKit -framework AVFoundation -framework AudioToolbox -framework Carbon \
  -framework UserNotifications -framework Vision -framework ScreenCaptureKit -framework ApplicationServices

APP="DingCode.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp DingCode "$APP/Contents/MacOS/"
cp Info.plist "$APP/Contents/"
cp ../i18n/strings.json "$APP/Contents/Resources/strings.json"

if codesign --force --sign "DingCode Dev" "$APP" >/dev/null 2>&1; then
    echo "OK: 固定证书签名 → $APP (重编译不再丢授权)"
elif codesign --force --sign "DingAI Dev" "$APP" >/dev/null 2>&1; then
    echo "OK: 沿用 DingAI Dev 证书 → $APP (bundle id 变更后屏幕录制仍需重新授权)"
elif codesign --force --sign "AnnoOverlay Dev" "$APP" >/dev/null 2>&1; then
    echo "OK: 沿用 AnnoOverlay Dev 证书 → $APP (bundle id 变更后屏幕录制仍需重新授权)"
else
    codesign --force --sign - "$APP" >/dev/null 2>&1
    echo "OK: ad-hoc 签名 → $APP (提示:导入自签 DingCode Dev 证书后重跑可固定身份)"
fi
