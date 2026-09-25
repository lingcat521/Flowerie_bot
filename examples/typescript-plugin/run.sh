#!/bin/sh
# TypeScript 示例插件入口（runtime=exec：入口文件即进程）。
# Node ≥ 22.6 可直接执行 .ts（类型擦除），无需构建；
# 旧版本 node 请先编译：tsc src/plugin.ts --target es2022 --module esnext --moduleResolution bundler
#   （或直接用仓库文档里的构建脚本），再把下面这行换成 node src/plugin.js
exec node "$(dirname "$0")/src/plugin.ts"
