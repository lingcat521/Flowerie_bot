#!/bin/sh
# Kotlin 插件的入口包装：跑编译好的 fat-jar（测试/构建阶段先 kotlinc 生成 plugin.jar）
exec java -jar "$(dirname "$0")/plugin.jar"
