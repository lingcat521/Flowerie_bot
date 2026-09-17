#!/usr/bin/env lua
-- 最小「任意语言插件」示例：Lua 实现 Plugin API v1（stdin/stdout JSON-Lines）
io.stdout:setvbuf("line")   -- 逐行刷新，协议要求即时响应

for line in io.lines() do
  local id = line:match('"id":%s*(%d+)')
  local method = line:match('"method":%s*"([a-z_]+)"')
  if id and method then
    if method == "initialize" then
      io.write('{"id":' .. id .. ',"result":{"ok":true,"api_version":"1"}}\n')
    elseif method == "event" then
      io.write('{"id":' .. id .. ',"result":{"actions":[{"type":"test","message":"lua-ok"}]}}\n')
    elseif method == "health" or method == "shutdown" then
      io.write('{"id":' .. id .. ',"result":{"ok":true}}\n')
    else
      io.write('{"id":' .. id .. ',"error":"unknown method"}\n')
    end
  end
end

