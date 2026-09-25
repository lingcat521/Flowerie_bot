#!/bin/sh
# Go 示例插件入口（runtime=exec：入口文件即进程）。
# 构建产物放到临时目录，避免污染仓库；GOCACHE 默认用 HOME 下的缓存。
set -e
cd "$(dirname "$0")"
BUILD_DIR="${FLOWERIE_GO_BUILD_DIR:-$(mktemp -d)}"
export GOFLAGS="-mod=mod"
go build -o "$BUILD_DIR/plugin" .
exec "$BUILD_DIR/plugin"
