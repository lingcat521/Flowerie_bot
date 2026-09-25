#!/bin/sh
# minimal_rust 的构建脚本（任务书《插件测试》§二：Build 与 Load 分开验证）。
#
#   - 真编译：rustc --edition 2021（只要编译器：不用 cargo、不联网、零 crate 依赖）。
#   - 产物落在**插件目录下**的 .build/minimal_rust（不写公共缓存、不污染仓库其它位置）。
#   - 任何一步失败都非零退出（验收表里的 Build 行就是它）。
#
# SDK 源码位置按此顺序解析（插件目录被拷到仓库外时用 FLOWERIE_SDK_RUST 明示）：
#   1) $FLOWERIE_SDK_RUST / $FLOWERIE_RUST_SDK_DIR  —— 直接指向 sdk/rust
#   2) $FLOWERIE_SDK_DIR（sdk 根或 rust 子目录）
#   3) $FLOWERIE_REPO_ROOT/sdk/rust
#   4) <插件目录>/../../../sdk/rust（仓库内规范位置）
#   5) <插件目录>/sdk/rust（插件目录内自带的副本，可选）
#   6) 从插件目录逐级向上找 sdk/rust（最多 8 级）
#   7) $GITHUB_WORKSPACE/sdk/rust（CI：夹具把插件目录拷到临时目录后靠它仍能找到仓库根）
#
# 为什么需要 1–3/7：验收夹具（tests/sdk/harness.py）只把**插件目录**拷到临时目录再跑本脚本，
# 此时仓库与 SDK 都不是它的祖先 —— 用这些变量指路即可，不必把 SDK 复制进插件目录。
set -eu

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$PLUGIN_DIR/.build"
MAIN_RS="$PLUGIN_DIR/src/main.rs"
BINARY="$BUILD_DIR/minimal_rust"

if [ ! -f "$MAIN_RS" ]; then
  echo "[minimal_rust] 找不到源码：$MAIN_RS" >&2
  exit 1
fi

RUSTC="${FLOWERIE_RUSTC:-rustc}"
if ! command -v "$RUSTC" >/dev/null 2>&1; then
  echo "[minimal_rust] 本机没有 rustc：请安装 Rust >= 1.70 后重跑 build.sh（缺工具链不是构建成功）" >&2
  exit 1
fi

# ---------- 1. 定位 SDK 源码（sdk/rust/src/{lib.rs,json.rs}） ----------
has_sdk() {
  [ -n "${1:-}" ] && [ -f "$1/src/lib.rs" ] && [ -f "$1/src/json.rs" ]
}

SDK_DIR=""
for candidate in "${FLOWERIE_SDK_RUST:-}" "${FLOWERIE_RUST_SDK_DIR:-}" "${FLOWERIE_SDK_DIR:-}/rust" "${FLOWERIE_SDK_DIR:-}" "${FLOWERIE_REPO_ROOT:-}/sdk/rust" "$PLUGIN_DIR/../../../sdk/rust" "$PLUGIN_DIR/sdk/rust"; do
  if has_sdk "$candidate"; then
    SDK_DIR="$candidate"
    break
  fi
done

if [ -z "$SDK_DIR" ]; then
  PROBE="$PLUGIN_DIR"
  LEVEL=0
  while [ "$LEVEL" -lt 8 ]; do
    if has_sdk "$PROBE/sdk/rust"; then
      SDK_DIR="$PROBE/sdk/rust"
      break
    fi
    PROBE="$(dirname "$PROBE")"
    LEVEL=$((LEVEL + 1))
  done
fi

if [ -z "$SDK_DIR" ] && has_sdk "${GITHUB_WORKSPACE:-}/sdk/rust"; then
  SDK_DIR="$GITHUB_WORKSPACE/sdk/rust"
fi

if [ -z "$SDK_DIR" ]; then
  echo "[minimal_rust] 找不到 Rust SDK 源码 sdk/rust/src/{lib.rs,json.rs}。" >&2
  echo "[minimal_rust] 插件目录被拷到仓库外时请显式指定：" >&2
  echo "             FLOWERIE_SDK_RUST=/path/to/repo/sdk/rust $0" >&2
  exit 1
fi
SDK_DIR="$(cd "$SDK_DIR" && pwd)"

# ---------- 2. 真编译 ----------
# 模块布局：main.rs 里的 mod flowerie; -> src/flowerie/mod.rs（= SDK 的 lib.rs）+ src/flowerie/json.rs
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/src/flowerie"
cp "$SDK_DIR/src/lib.rs" "$BUILD_DIR/src/flowerie/mod.rs"
cp "$SDK_DIR/src/json.rs" "$BUILD_DIR/src/flowerie/json.rs"
cp "$MAIN_RS" "$BUILD_DIR/src/main.rs"

"$RUSTC" --edition 2021 -O -o "$BINARY" "$BUILD_DIR/src/main.rs"

# 编译是否成功由 rustc 的退出码决定（set -e 已保证失败即非零退出）。
# 产物只校验“存在且非空”，不拿 -x 判定：Android 的 /storage（FUSE）不保留执行位，
# chmod 会静默失败，用 -x 会把“rustc 明明编译成功”误判成构建失败。
if [ ! -s "$BINARY" ]; then
  echo "[minimal_rust] 构建结束但没有产物：$BINARY" >&2
  exit 1
fi

chmod +x "$BINARY" 2>/dev/null || true
if [ ! -x "$BINARY" ]; then
  echo "[minimal_rust] 提示：该文件系统不保留执行位，产物在本机可能无法直接 exec（CI/ext4 正常）" >&2
fi
echo "[minimal_rust] 构建成功：$BINARY（SDK: $SDK_DIR）"
