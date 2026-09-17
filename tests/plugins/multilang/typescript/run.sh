#!/bin/sh
# TypeScript 插件的入口包装：tsc 产物是纯 JS（没有 shebang，不能直接 exec），用脚本包一层
exec node "$(dirname "$0")/plugin.js"

