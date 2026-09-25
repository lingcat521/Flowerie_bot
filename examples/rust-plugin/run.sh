#!/bin/sh
# Rust 示例插件入口（runtime=exec：入口文件即进程）。
# 用 rustc 直接编译（不需要 cargo / crates.io）：把 SDK 两个文件拷进临时源码树再编译。
set -e
EX_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="${FLOWERIE_RUST_BUILD_DIR:-$(mktemp -d)}"
mkdir -p "$BUILD_DIR/flowerie"
cp "$EX_DIR/../../../sdk/rust/src/lib.rs" "$BUILD_DIR/flowerie/mod.rs"
cp "$EX_DIR/../../../sdk/rust/src/json.rs" "$BUILD_DIR/flowerie/json.rs"
cp "$EX_DIR/src/main.rs" "$BUILD_DIR/main.rs"
rustc --edition 2021 -O -o "$BUILD_DIR/plugin" "$BUILD_DIR/main.rs"
exec "$BUILD_DIR/plugin"
