#!/bin/sh
# minimal_go 的构建脚本（任务书《插件测试》§二：Build 与 Load 分开验证）。
#
#   - 真编译：go build。GOFLAGS=-mod=mod，GOPROXY=off —— 零第三方依赖是**可验证**的：
#     任何需要下载的依赖都会直接失败，而不是悄悄联网拉包。
#   - 产物落在**插件目录下**的 .build/plugin（不写公共缓存、不污染仓库其它位置）。
#   - 任何一步失败都非零退出（验收表里的 Build 行就是它）。
#
# SDK 源码位置按此顺序解析（插件目录被拷到仓库外时用 FLOWERIE_SDK_GO 明示）：
#   1) $FLOWERIE_SDK_GO
#   2) $FLOWERIE_REPO_ROOT/sdk/go/flowerie
#   3) <插件目录>/../../../sdk/go/flowerie（仓库内规范位置）
#   4) 从插件目录逐级向上找 sdk/go/flowerie
#   5) $GITHUB_WORKSPACE/sdk/go/flowerie（CI）
#
# 编译在 .build/src 里进行：那份临时 go.mod 用**绝对路径** replace SDK，因此插件目录
# 被整体拷到任何位置（只带这 5 个文件）都能构建；仓库内的 go.mod 则保持相对路径
# replace，方便直接在插件目录里 go build。
set -eu

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$PLUGIN_DIR/.build"
STAGE_DIR="$BUILD_DIR/src"
SDK_MODULE="github.com/lingcat521/Flowerie_bot/sdk/go/flowerie"

if ! command -v go >/dev/null 2>&1; then
  echo "[minimal_go] 本机没有 go 工具链：请安装 Go >= 1.21 后重跑 build.sh（缺工具链不是构建成功）" >&2
  exit 1
fi

# ---------- 1. 定位 SDK 源码 ----------
SDK_DIR=""
if [ -n "${FLOWERIE_SDK_GO:-}" ] && [ -f "${FLOWERIE_SDK_GO}/plugin.go" ]; then
  SDK_DIR="$FLOWERIE_SDK_GO"
fi
if [ -z "$SDK_DIR" ] && [ -n "${FLOWERIE_REPO_ROOT:-}" ] \
   && [ -f "${FLOWERIE_REPO_ROOT}/sdk/go/flowerie/plugin.go" ]; then
  SDK_DIR="$FLOWERIE_REPO_ROOT/sdk/go/flowerie"
fi
if [ -z "$SDK_DIR" ] && [ -f "$PLUGIN_DIR/../../../sdk/go/flowerie/plugin.go" ]; then
  SDK_DIR="$PLUGIN_DIR/../../../sdk/go/flowerie"
fi
if [ -z "$SDK_DIR" ]; then
  PROBE="$PLUGIN_DIR"
  LEVEL=0
  while [ "$LEVEL" -lt 8 ]; do
    if [ -f "$PROBE/sdk/go/flowerie/plugin.go" ]; then
      SDK_DIR="$PROBE/sdk/go/flowerie"
      break
    fi
    PROBE="$(dirname "$PROBE")"
    LEVEL=$((LEVEL + 1))
  done
fi
if [ -z "$SDK_DIR" ] && [ -n "${GITHUB_WORKSPACE:-}" ] \
   && [ -f "${GITHUB_WORKSPACE}/sdk/go/flowerie/plugin.go" ]; then
  SDK_DIR="$GITHUB_WORKSPACE/sdk/go/flowerie"
fi
if [ -z "$SDK_DIR" ]; then
  echo "[minimal_go] 找不到 SDK 源码 sdk/go/flowerie/plugin.go。" >&2
  echo "[minimal_go] 插件目录被拷到仓库外时请显式指定：" >&2
  echo "             FLOWERIE_SDK_GO=/path/to/repo/sdk/go/flowerie $0" >&2
  exit 1
fi
SDK_DIR="$(cd "$SDK_DIR" && pwd)"

# ---------- 2. 生成临时模块并真编译 ----------
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"
cp "$PLUGIN_DIR/main.go" "$STAGE_DIR/main.go"
cat > "$STAGE_DIR/go.mod" <<GOMOD
module minimal_go_build

go 1.21

require $SDK_MODULE v0.0.0

replace $SDK_MODULE => $SDK_DIR
GOMOD

# 环境变量被裁剪（没有 HOME）时也要能构建：给 GOCACHE 一个临时兜底。
if [ -z "${HOME:-}" ] && [ -z "${GOCACHE:-}" ]; then
  GOCACHE="$(mktemp -d)/go-build-cache"
  export GOCACHE
fi

(
  cd "$STAGE_DIR"
  GOFLAGS="-mod=mod" GOPROXY=off GOWORK=off CGO_ENABLED=0 \
    go build -trimpath -o "$BUILD_DIR/plugin" .
)

if [ ! -x "$BUILD_DIR/plugin" ]; then
  echo "[minimal_go] 构建结束但没有可执行产物：$BUILD_DIR/plugin" >&2
  exit 1
fi
echo "[minimal_go] 构建成功：$BUILD_DIR/plugin（SDK: $SDK_DIR）"
