#!/bin/sh
# Java 插件的入口包装：JVM 不是可执行文件，用 3 行脚本把 entry 变成"能直接跑的东西"
exec java -cp "$(dirname "$0")" Plugin
