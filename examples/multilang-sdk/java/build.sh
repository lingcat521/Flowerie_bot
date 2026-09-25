#!/bin/sh
# minimal_java 的构建脚本：用 javac 真编译「SDK 两个源文件 + 本插件」，产物落在插件目录下的 .build/。
# 零第三方依赖（不用 Maven/Gradle，不拉任何依赖）；任何一步失败都非零退出。
#
# SDK 位置解析顺序（第一个命中者胜出）：
#   1. \$FLOWERIE_JAVA_SDK_DIR              —— 直接指向 sdk/java/src/main/java
#   2. \$HERE/sdk/java/src/main/java|\$HERE/sdk —— 插件目录内自带的副本（可选）
#   3. \$FLOWERIE_SDK_DIR（sdk 根或 java 子目录）、\$FLOWERIE_REPO_ROOT/sdk/java/src/main/java
#   4. 从插件目录逐级向上找仓库根（在仓库里就地构建：examples/multilang-sdk/java -> <repo>）
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
BUILD_DIR="$HERE/.build"
CLASSES_DIR="$BUILD_DIR/classes"
SDK_MARK="dev/flowerie/sdk/FloweriePlugin.java"

fail() {
  echo "build.sh: $1" >&2
  exit 1
}

# ---------- 1. 工具链 ----------
if ! command -v javac >/dev/null 2>&1; then
  fail "找不到 javac：本机没有 JDK（BLOCKED BY ENVIRONMENT，不是插件错误）。装了 JDK 后重跑本脚本。"
fi

# ---------- 2. 定位 Java SDK 源码 ----------
looks_like_sdk() {
  [ -n "$1" ] && [ -f "$1/$SDK_MARK" ] && [ -f "$1/dev/flowerie/sdk/Json.java" ]
}

SDK_SRC=""
for candidate in \
  "${FLOWERIE_JAVA_SDK_DIR:-}" \
  "$HERE/sdk/java/src/main/java" \
  "$HERE/sdk" \
  "${FLOWERIE_SDK_DIR:-}/java/src/main/java" \
  "${FLOWERIE_SDK_DIR:-}" \
  "${FLOWERIE_REPO_ROOT:-}/sdk/java/src/main/java"
do
  if looks_like_sdk "$candidate"; then
    SDK_SRC="$candidate"
    break
  fi
done

if [ -z "$SDK_SRC" ]; then
  probe="$HERE"
  while [ "$probe" != "/" ]; do
    if looks_like_sdk "$probe/sdk/java/src/main/java"; then
      SDK_SRC="$probe/sdk/java/src/main/java"
      break
    fi
    probe=$(dirname "$probe")
  done
fi

if [ -z "$SDK_SRC" ]; then
  fail "找不到 Java SDK 源码（需要 $SDK_MARK）。已尝试：\$FLOWERIE_JAVA_SDK_DIR、\$HERE/sdk、\$FLOWERIE_SDK_DIR、\$FLOWERIE_REPO_ROOT，以及从 $HERE 向上查找仓库根。"
fi

# ---------- 3. 真编译 ----------
rm -rf "$CLASSES_DIR"
mkdir -p "$CLASSES_DIR"
if ! javac -encoding UTF-8 -d "$CLASSES_DIR" \
    "$SDK_SRC/dev/flowerie/sdk/Json.java" \
    "$SDK_SRC/dev/flowerie/sdk/FloweriePlugin.java" \
    "$HERE/src/MinimalPlugin.java"; then
  fail "javac 编译失败（SDK：$SDK_SRC）"
fi

[ -f "$CLASSES_DIR/MinimalPlugin.class" ] || fail "编译没有产出 $CLASSES_DIR/MinimalPlugin.class"
echo "build.sh: ok -> $CLASSES_DIR (sdk: $SDK_SRC)"

