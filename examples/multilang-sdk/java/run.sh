#!/bin/sh
# minimal_java 的入口（manifest: runtime=exec / entry=run.sh）：exec javac 产物。
# 产物不存在或 java 不可用时**报错并非零退出**，不静默成功。
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
CLASSES_DIR="$HERE/.build/classes"
MAIN_CLASS="MinimalPlugin"

if [ ! -f "$CLASSES_DIR/$MAIN_CLASS.class" ]; then
  echo "run.sh: 构建产物不存在：$CLASSES_DIR/$MAIN_CLASS.class（请先在本目录执行 sh build.sh）" >&2
  exit 1
fi

JAVA_BIN="${JAVA_BIN:-java}"
if ! command -v "$JAVA_BIN" >/dev/null 2>&1; then
  echo "run.sh: 找不到 java 可执行文件（JAVA_BIN=$JAVA_BIN）" >&2
  exit 1
fi

exec "$JAVA_BIN" -Dfile.encoding=UTF-8 -cp "$CLASSES_DIR" "$MAIN_CLASS"

