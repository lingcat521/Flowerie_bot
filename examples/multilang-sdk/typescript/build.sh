#!/bin/sh
# 最小 TypeScript 插件的构建（任务书《插件测试》§十三）：Node >= 22.6 直接跑 TS，否则用 tsc 编译。
set -e
EX_DIR="$(cd "$(dirname "$0")" && pwd)"
SDK_DIR="$EX_DIR/../../../sdk/typescript"
BUILD="$EX_DIR/.build"
rm -rf "$BUILD"
mkdir -p "$BUILD"
cp "$SDK_DIR/flowerie_sdk.ts" "$BUILD/flowerie_sdk.ts"
sed 's#\.\./\.\./\.\./sdk/typescript/flowerie_sdk\.ts#./flowerie_sdk.ts#' \
  "$EX_DIR/src/index.ts" > "$BUILD/index.ts"

NODE_MAJOR="$(node -e 'process.stdout.write(String(process.versions.node.split(".")[0]))' 2>/dev/null || echo 0)"
if [ "${FLOWERIE_FORCE_TSC:-0}" != "1" ] && [ "$NODE_MAJOR" -ge 22 ] 2>/dev/null; then
  echo "build ok: $BUILD/index.ts（node $NODE_MAJOR 直接执行 TS）"
  exit 0
fi
command -v tsc >/dev/null 2>&1 || { echo "需要 Node >= 22.6 或 tsc" >&2; exit 1; }
sed 's/\.ts"/"/g' "$BUILD/index.ts" > "$BUILD/index_cjs.ts"
set -- "$BUILD/index_cjs.ts" "$BUILD/flowerie_sdk.ts"
if ! node -e 'require.resolve("@types/node/package.json")' >/dev/null 2>&1; then
  cp "$SDK_DIR/shims/node.d.ts" "$BUILD/node.d.ts"
  set -- "$@" "$BUILD/node.d.ts"
fi
if ! tsc "$@" --target es2022 --module node16 --moduleResolution node16 --outDir "$BUILD/js" >&2; then
  tsc "$@" --target es2022 --module commonjs --outDir "$BUILD/js" >&2
fi
echo "build ok: $BUILD/js/index_cjs.js"

