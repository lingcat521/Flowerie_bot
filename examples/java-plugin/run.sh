#!/bin/sh
# Java 示例插件入口（runtime=exec：入口文件即进程）。
# 用 javac 直接编译（不需要 Maven/Gradle）：把 SDK 两个源文件与示例一起编到临时目录。
set -e
EX_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="${FLOWERIE_JAVA_BUILD_DIR:-$(mktemp -d)}"
mkdir -p "$BUILD_DIR/classes"
javac -encoding UTF-8 -d "$BUILD_DIR/classes" \
  "$EX_DIR/../../../sdk/java/src/main/java/dev/flowerie/sdk/Json.java" \
  "$EX_DIR/../../../sdk/java/src/main/java/dev/flowerie/sdk/FloweriePlugin.java" \
  "$EX_DIR/src/Plugin.java"
exec java -cp "$BUILD_DIR/classes" Plugin
