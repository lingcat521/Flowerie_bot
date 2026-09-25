#!/bin/sh
# TypeScript 示例插件入口（runtime=exec：入口文件即进程）。
#
# 两种运行方式（自动选择）：
#   1. Node ≥ 22.6：直接执行 .ts（类型擦除），零构建；
#   2. 更老的 Node（例如 CI 上的 v20）：用 tsc 编译成 CommonJS 再跑
#      —— 编译前把 ".ts" 扩展名去掉，让 tsc 产出 require("./flowerie_sdk") 能解析到 .js。
set -e
EX_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="${FLOWERIE_TS_BUILD_DIR:-$(mktemp -d)}"
mkdir -p "$BUILD_DIR"
cp "$EX_DIR/../../sdk/typescript/flowerie_sdk.ts" "$BUILD_DIR/flowerie_sdk.ts"
# 拷到构建目录后，把跨目录的相对 import 改写成同目录（否则路径失效）
sed 's#\.\./\.\./\.\./sdk/typescript/flowerie_sdk\.ts#./flowerie_sdk.ts#' \
    "$EX_DIR/src/plugin.ts" > "$BUILD_DIR/plugin.ts"

NODE_MAJOR="$(node -e 'process.stdout.write(String(process.versions.node.split(".")[0]))' 2>/dev/null || echo 0)"

if [ "${FLOWERIE_FORCE_TSC:-0}" != "1" ] && [ "$NODE_MAJOR" -ge 22 ] 2>/dev/null; then
  exec node "$BUILD_DIR/plugin.ts"
fi

# 回退：tsc 编译（CI 的 runner 镜像自带 tsc）
if ! command -v tsc >/dev/null 2>&1; then
  echo "[flowerie] 需要 Node >= 22.6 或 tsc（当前 node 主版本 ${NODE_MAJOR}）" >&2
  exit 1
fi
sed 's/\.ts"/"/g' "$BUILD_DIR/plugin.ts" > "$BUILD_DIR/plugin_cjs.ts"
tsc "$BUILD_DIR/plugin_cjs.ts" "$BUILD_DIR/flowerie_sdk.ts" \
    --target es2022 --module commonjs --moduleResolution node --outDir "$BUILD_DIR/js" >&2
exec node "$BUILD_DIR/js/plugin_cjs.js"
