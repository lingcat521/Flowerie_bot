#!/bin/sh
# minimal_go 的入口（manifest.runtime=exec：entry 文件即插件进程，由引擎直接 exec）。
#
# 只 exec build.sh 的产物 .build/plugin；产物不存在就报错退出 ——
# 绝不静默成功（§二：run.sh 不假装插件起来了，也不会替用户隐式编译）。
set -eu

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
BINARY="${FLOWERIE_GO_BIN:-$PLUGIN_DIR/.build/plugin}"

if [ ! -x "$BINARY" ]; then
  echo "[minimal_go] 构建产物不存在或不可执行：$BINARY" >&2
  echo "[minimal_go] 请先在插件目录运行 ./build.sh（需要 Go >= 1.21）" >&2
  exit 3
fi

exec "$BINARY"
