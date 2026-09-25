#!/bin/sh
# minimal_rust 的入口（manifest.runtime=exec：entry 文件即插件进程，由引擎直接 exec）。
#
# 只 exec build.sh 的产物 .build/minimal_rust；产物不存在就报错退出 ——
# 绝不静默成功（§二：run.sh 不假装插件起来了，也不会替用户隐式编译）。
set -eu

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
BINARY="${FLOWERIE_RUST_BIN:-$PLUGIN_DIR/.build/minimal_rust}"

if [ ! -s "$BINARY" ]; then
  echo "[minimal_rust] 构建产物不存在：$BINARY" >&2
  echo "[minimal_rust] 请先在插件目录运行 ./build.sh（需要 rustc >= 1.70）" >&2
  exit 1
fi

# 执行位尽力而为：Android 的 /storage（FUSE）不保留 +x，chmod 会静默失败。
# 真 exec 不了时下面的 exec 会以非零码退出并把原因打到 stderr，不会静默成功。
chmod +x "$BINARY" 2>/dev/null || true

exec "$BINARY"
