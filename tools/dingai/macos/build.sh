#!/bin/bash
# DingAI 构建脚本:编译 → 组装 .app → 签名
# 签名策略:优先用本地证书 "DingAI Dev"(没有则试 "AnnoOverlay Dev")(身份稳定,重编译不丢屏幕录制授权);
#           证书未导入时回退 ad-hoc(每次重编译 TCC 身份漂移,需重新授权)
set -euo pipefail
cd "$(dirname "$0")"

swiftc -O -swift-version 5 -o DingAI DingAI.swift

APP="DingAI.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp DingAI "$APP/Contents/MacOS/"
cp Info.plist "$APP/Contents/"

if codesign --force --sign "DingAI Dev" "$APP" >/dev/null 2>&1; then
    echo "OK: 固定证书签名 → $APP (重编译不再丢授权)"
elif codesign --force --sign "AnnoOverlay Dev" "$APP" >/dev/null 2>&1; then
    echo "OK: 沿用 AnnoOverlay Dev 证书 → $APP (bundle id 变更后屏幕录制仍需重新授权)"
else
    codesign --force --sign - "$APP" >/dev/null 2>&1
    echo "OK: ad-hoc 签名 → $APP (提示:导入自签 DingAI Dev 证书后重跑可固定身份)"
fi
