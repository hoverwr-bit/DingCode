#!/bin/sh
# web/record/dist 的一次性开发机构建（设计 20261025：运行时零 npm）。
# dist/ 随包发布并入库，node_modules/ 不入库（web/record/.gitignore）。
set -e
cd "$(dirname "$0")/../web/record"
npm install
npm run build
echo "built web/record/dist"
