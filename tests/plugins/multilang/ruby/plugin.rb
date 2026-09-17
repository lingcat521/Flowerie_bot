#!/usr/bin/env ruby
# frozen_string_literal: true
# 最小「任意语言插件」示例：Ruby 实现 Plugin API v1（stdin/stdout JSON-Lines）
# 协议：收 {"id":N,"method":"initialize|event|health|shutdown","params":{...}}
#       发 {"id":N,"result":{...}} 或 {"id":N,"error":"..."}
$stdout.sync = true

STDIN.each_line do |line|
  id = line[/"id":\s*(\d+)/, 1]
  method = line[/"method":\s*"([a-z_]+)"/, 1]
  next if id.nil? || method.nil?

  case method
  when "initialize"
    puts %({"id":#{id},"result":{"ok":true,"api_version":"1"}})
  when "event"
    puts %({"id":#{id},"result":{"actions":[{"type":"test","message":"ruby-ok"}]}})
  when "health"
    puts %({"id":#{id},"result":{"ok":true}})
  when "shutdown"
    puts %({"id":#{id},"result":{"ok":true}})
  else
    puts %({"id":#{id},"error":"unknown method"})
  end
end

