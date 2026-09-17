#!/usr/bin/env Rscript
# 最小「任意语言插件」示例：R 实现 Plugin API v1（stdin/stdout JSON-Lines）
con <- file("stdin", "r")
repeat {
  line <- readLines(con, n = 1, warn = FALSE)
  if (length(line) == 0) break
  id <- sub('.*"id":\\s*([0-9]+).*', '\\1', line)
  if (!grepl('"id":', line)) next
  method <- sub('.*"method":\\s*"([a-z_]+)".*', '\\1', line)
  if (!grepl('"method":', line)) method <- ""
  if (method == "initialize") {
    cat(sprintf('{"id":%s,"result":{"ok":true,"api_version":"1"}}\n', id))
  } else if (method == "event") {
    cat(sprintf('{"id":%s,"result":{"actions":[{"type":"test","message":"r-ok"}]}}\n', id))
  } else if (method == "health" || method == "shutdown") {
    cat(sprintf('{"id":%s,"result":{"ok":true}}\n', id))
  } else {
    cat(sprintf('{"id":%s,"error":"unknown method"}\n', id))
  }
  flush(stdout())
}

