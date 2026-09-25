#!/bin/sh
# 最小 TypeScript 插件的入口（runtime=exec）：exec 构建产物；没构建过就明确报错。
set -e
EX_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$EX_DIR/.build/js/index_cjs.js" ]; then
  exec node "$EX_DIR/.build/js/index_cjs.js"
fi
if [ -f "$EX_DIR/.build/index.ts" ]; then
  exec node "$EX_DIR/.build/index.ts"
fi
echo "未构建：请先执行 build.sh" >&2
exit 1

