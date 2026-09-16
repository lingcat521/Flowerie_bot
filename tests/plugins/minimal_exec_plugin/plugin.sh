#!/bin/sh
# 最小「任意语言」插件示例：POSIX shell 实现 Plugin API v1（stdin/stdout JSON-Lines）。
# 用途：证明 exec runtime 直跑入口文件 —— 主进程不依赖 Python / Node / 任何语言 runner。
#
# 协议（与 python_runner.py / node_runner.js 完全一致）：
#   收: {"id": N, "method": "initialize|event|health|shutdown", "params": {...}}
#   发: {"id": N, "result": {...}}

while IFS= read -r line; do
  id=$(printf '%s' "$line" | sed -n 's/.*"id": *\([0-9][0-9]*\).*/\1/p')
  method=$(printf '%s' "$line" | sed -n 's/.*"method": *"\([a-zA-Z_]*\)".*/\1/p')
  if [ -z "$id" ] || [ -z "$method" ]; then
    continue
  fi
  case "$method" in
    initialize)
      printf '{"id":%s,"result":{"ok":true,"api_version":"1"}}\n' "$id" ;;
    event)
      printf '{"id":%s,"result":{"actions":[{"type":"test","message":"exec-ok"}]}}\n' "$id" ;;
    health)
      printf '{"id":%s,"result":{"ok":true}}\n' "$id" ;;
    shutdown)
      printf '{"id":%s,"result":{"ok":true}}\n' "$id" ;;
    *)
      printf '{"id":%s,"error":"unknown method"}\n' "$id" ;;
  esac
done
exit 0

