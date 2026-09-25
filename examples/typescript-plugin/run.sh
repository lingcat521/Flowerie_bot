#!/bin/sh
# TypeScript 示例插件入口（runtime=exec：入口文件即进程）。
#
# 两种运行方式（自动选择）：
#   1. Node >= 22.6：直接执行 .ts（类型擦除），零构建；
#   2. 更老的 Node（例如 CI 上的 v20）：用 tsc 编译成 JavaScript 再跑。
#      新老 tsc 的 module/moduleResolution 组合不同，先试新规范（node16），失败再退回 commonjs。
set -e
EX_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="${FLOWERIE_TS_BUILD_DIR:-$(mktemp -d)}"
mkdir -p "$BUILD_DIR"
cp "$EX_DIR/../../sdk/typescript/flowerie_sdk.ts" "$BUILD_DIR/flowerie_sdk.ts"
# 拷到构建目录后把跨目录 import 改写成同目录（实测：GNU sed 下 [.] 字符类不匹配，必须用反斜杠转义）
sed 's#\.\./\.\./\.\./sdk/typescript/flowerie_sdk\.ts#./flowerie_sdk.ts#' "$EX_DIR/src/plugin.ts" > "$BUILD_DIR/plugin.ts"

NODE_MAJOR="$(node -e 'process.stdout.write(String(process.versions.node.split(".")[0]))' 2>/dev/null || echo 0)"

if [ "${FLOWERIE_FORCE_TSC:-0}" != "1" ] && [ "$NODE_MAJOR" -ge 22 ] 2>/dev/null; then
  exec node "$BUILD_DIR/plugin.ts"
fi

if ! command -v tsc >/dev/null 2>&1; then
  echo "[flowerie] 需要 Node >= 22.6 或 tsc（当前 node 主版本 $NODE_MAJOR）" >&2
  exit 1
fi
sed 's/\.ts"/"/g' "$BUILD_DIR/plugin.ts" > "$BUILD_DIR/plugin_cjs.ts"
if ! tsc "$BUILD_DIR/plugin_cjs.ts" "$BUILD_DIR/flowerie_sdk.ts" --target es2022 --module node16 --moduleResolution node16 --outDir "$BUILD_DIR/js" >&2; then
  tsc "$BUILD_DIR/plugin_cjs.ts" "$BUILD_DIR/flowerie_sdk.ts" --target es2022 --module commonjs --outDir "$BUILD_DIR/js" >&2
fi
exec node "$BUILD_DIR/js/plugin_cjs.js"
