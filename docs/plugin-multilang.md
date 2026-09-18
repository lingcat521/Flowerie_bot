# 任意语言插件：13 种语言最小实现（照抄即可）

> 不想用 Python / Node？**任何能读写 stdin/stdout 的语言都能写花璃插件**。
> 本文每种语言都给出**完整可运行的最小实现**，与 CI 实测夹具（tests/plugins/multilang/）逐字一致，复制就能用。
>
> Python / Node 的写法见 [plugin-developer-guide.md](plugin-developer-guide.md)（§25 / §26），
> SDK 模式（flowerie_sdk）见 [sdk.md](sdk.md)。

---

## 0. 三分钟看懂协议（exec 模式）

花璃会拉起你的进程，然后用 **JSON-Lines** 与它通信（一行一个 JSON，UTF-8）：

```text
花璃 → 插件（stdin）  {"id":1,"method":"initialize","params":{}}
插件 → 花璃（stdout）  {"id":1,"result":{"ok":true,"api_version":"1"}}

花璃 → 插件（stdin）  {"id":2,"method":"event","params":{"event":{...}}}
插件 → 花璃（stdout）  {"id":2,"result":{"actions":[{"type":"send_group_msg","params":{...}}]}}
```

**只有四个方法**：

| 方法 | 你要回什么 | 什么时候来 |
| :--- | :--- | :--- |
| initialize | {"result":{"ok":true,"api_version":"1"}} | 启动握手，回完才算就绪 |
| event | {"result":{"actions":[…]}} | 有群消息 / 通知时（动作清单见 plugin-developer-guide §Action） |
| health | {"result":{"ok":true}} | 心跳探活 |
| shutdown | {"result":{"ok":true}} | 退出前（回完再退） |

**四条铁律**（照做就不会踩坑）：

1. **一行一个 JSON，写完立刻 flush** —— 缓冲住就等于花璃永远收不到，插件“没反应”九成是这个原因
2. **收到必须回**，id 原样带回（不要自己造 id）
3. **出错回** {"id":N,"error":"原因"}，别让进程崩（崩了会按保护级别被重启或禁用）
4. **stdout 只能有协议 JSON**：日志、调试、编译器警告一律走 stderr，否则污染协议

---

## 1. 目录结构与 manifest

```text
plugins/my_plugin/
├── manifest.json      # 必需：声明 runtime=exec 与 entry
├── plugin.rb          # 你的源码（编译型语言这里是编译产物）
└── run.sh             # 可选：编译型 / 需要包装的语言用它当 entry
```

manifest.json（exec 模式）字段：

| 字段 | 必填 | 说明 |
| :--- | :--- | :--- |
| id | ✅ | 唯一标识（[a-z0-9_]，建议带语言前缀如 ml_go） |
| name / version / author / description | ✅ | 展示信息 |
| runtime | ✅ | 固定 "exec"（任意语言模式） |
| entry | ✅ | 可执行文件名；编译型填产物（如 plugin），JVM / .NET / TS 填 run.sh |
| api_version | ✅ | 当前填 "1" |
| permissions | ✅ | 动作权限白名单，没有动作就写 []（见 plugin-developer-guide §权限） |

**run.sh 只做一件事**：把标准输入输出原样转给真正的运行时，例如

```bash
#!/usr/bin/env bash
exec java -cp . Plugin        # JVM：必须 exec，否则信号与退出码传不下去
```

---

## 2. 逐语言最小实现

### 2.1 C

| 构建 | entry | 备注 |
| :--- | :--- | :--- |
| gcc -O2 -o plugin plugin.c | plugin | 编译产物 plugin 直接当入口 |

**manifest.json**

```json
{
  "id": "ml_c",
  "name": "Multilang C Plugin",
  "version": "1.0.0",
  "author": "flowerie",
  "description": "任意语言插件示例：C（编译产物直接作为插件进程）",
  "runtime": "exec",
  "entry": "plugin",
  "api_version": "1",
  "permissions": []
}
```

**plugin.c**

```c
/* 最小「任意语言插件」示例：C 实现 Plugin API v1（stdin/stdout JSON-Lines）
 * 编译：gcc -O2 -o plugin plugin.c        （entry 指向编译产物 plugin）
 * 说明：这里用 strstr/strtol 取值——最小实现，不引入任何 JSON 库。 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static long extract_id(const char *line) {
    const char *p = strstr(line, "\"id\":");
    if (!p) return -1;
    return strtol(p + 5, NULL, 10);
}

static int has_method(const char *line, const char *method) {
    char pat[64];
    snprintf(pat, sizeof(pat), "\"method\": \"%s\"", method);
    if (strstr(line, pat)) return 1;
    snprintf(pat, sizeof(pat), "\"method\":\"%s\"", method);
    return strstr(line, pat) != NULL;
}

int main(void) {
    char line[65536];
    while (fgets(line, sizeof(line), stdin)) {
        long id = extract_id(line);
        if (id < 0) continue;
        if (has_method(line, "initialize")) {
            printf("{\"id\":%ld,\"result\":{\"ok\":true,\"api_version\":\"1\"}}\n", id);
        } else if (has_method(line, "event")) {
            printf("{\"id\":%ld,\"result\":{\"actions\":[{\"type\":\"test\",\"message\":\"c-ok\"}]}}\n", id);
        } else if (has_method(line, "health") || has_method(line, "shutdown")) {
            printf("{\"id\":%ld,\"result\":{\"ok\":true}}\n", id);
        } else {
            printf("{\"id\":%ld,\"error\":\"unknown method\"}\n", id);
        }
        fflush(stdout);
    }
    return 0;
}
```

### 2.2 C++

| 构建 | entry | 备注 |
| :--- | :--- | :--- |
| g++ -O2 -std=c++17 -o plugin plugin.cpp | plugin | 同 C，注意 C++17 |

**manifest.json**

```json
{
  "id": "ml_cpp",
  "name": "Multilang C++ Plugin",
  "version": "1.0.0",
  "author": "flowerie",
  "description": "任意语言插件示例：C++（编译产物直接作为插件进程）",
  "runtime": "exec",
  "entry": "plugin",
  "api_version": "1",
  "permissions": []
}
```

**plugin.cpp**

```cpp
// 最小「任意语言插件」示例：C++ 实现 Plugin API v1（stdin/stdout JSON-Lines）
// 编译：g++ -O2 -std=c++17 -o plugin plugin.cpp
#include <iostream>
#include <regex>
#include <string>

int main() {
    std::ios::sync_with_stdio(false);
    const std::regex id_re("\"id\":\\s*([0-9]+)");
    const std::regex method_re("\"method\":\\s*\"([a-z_]+)\"");
    std::string line;
    while (std::getline(std::cin, line)) {
        std::smatch m;
        if (!std::regex_search(line, m, id_re)) continue;
        const std::string id = m[1];
        std::string method;
        if (std::regex_search(line, m, method_re)) method = m[1];

        if (method == "initialize") {
            std::cout << "{\"id\":" << id << ",\"result\":{\"ok\":true,\"api_version\":\"1\"}}" << std::endl;
        } else if (method == "event") {
            std::cout << "{\"id\":" << id
                      << ",\"result\":{\"actions\":[{\"type\":\"test\",\"message\":\"cpp-ok\"}]}}" << std::endl;
        } else if (method == "health" || method == "shutdown") {
            std::cout << "{\"id\":" << id << ",\"result\":{\"ok\":true}}" << std::endl;
        } else {
            std::cout << "{\"id\":" << id << ",\"error\":\"unknown method\"}" << std::endl;
        }
    }
    return 0;
}
```

### 2.3 Go

| 构建 | entry | 备注 |
| :--- | :--- | :--- |
| go build -o plugin main.go | plugin | 静态二进制，拷到服务器就能跑 |

**manifest.json**

```json
{
  "id": "ml_go",
  "name": "Multilang Go Plugin",
  "version": "1.0.0",
  "author": "flowerie",
  "description": "任意语言插件示例：Go（编译产物直接作为插件进程）",
  "runtime": "exec",
  "entry": "plugin",
  "api_version": "1",
  "permissions": []
}
```

**main.go**

```go
// 最小「任意语言插件」示例：Go 实现 Plugin API v1（stdin/stdout JSON-Lines）
// 编译：go build -o plugin main.go
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
)

type request struct {
	ID     int             `json:"id"`
	Method string          `json:"method"`
	Params json.RawMessage `json:"params"`
}

func main() {
	sc := bufio.NewScanner(os.Stdin)
	sc.Buffer(make([]byte, 1024*1024), 8*1024*1024)
	out := bufio.NewWriter(os.Stdout)

	for sc.Scan() {
		var req request
		if err := json.Unmarshal(sc.Bytes(), &req); err != nil {
			continue
		}
		switch req.Method {
		case "initialize":
			fmt.Fprintf(out, "{\"id\":%d,\"result\":{\"ok\":true,\"api_version\":\"1\"}}\n", req.ID)
		case "event":
			fmt.Fprintf(out, "{\"id\":%d,\"result\":{\"actions\":[{\"type\":\"test\",\"message\":\"go-ok\"}]}}\n", req.ID)
		case "health", "shutdown":
			fmt.Fprintf(out, "{\"id\":%d,\"result\":{\"ok\":true}}\n", req.ID)
		default:
			fmt.Fprintf(out, "{\"id\":%d,\"error\":\"unknown method\"}\n", req.ID)
		}
		out.Flush()
	}
}
```

### 2.4 Rust

| 构建 | entry | 备注 |
| :--- | :--- | :--- |
| rustc -O -o plugin main.rs | plugin | 不依赖任何 crate（免 cargo 联网） |

**manifest.json**

```json
{
  "id": "ml_rust",
  "name": "Multilang Rust Plugin",
  "version": "1.0.0",
  "author": "flowerie",
  "description": "任意语言插件示例：Rust（编译产物直接作为插件进程）",
  "runtime": "exec",
  "entry": "plugin",
  "api_version": "1",
  "permissions": []
}
```

**main.rs**

```rust
// 最小「任意语言插件」示例：Rust 实现 Plugin API v1（stdin/stdout JSON-Lines）
// 编译：rustc -O -o plugin main.rs   （不依赖任何 crate，避免 cargo 联网）
use std::io::{self, BufRead, Write};

fn extract_id(line: &str) -> Option<u64> {
    let idx = line.find("\"id\":")? + 5;
    let digits: String = line[idx..]
        .chars()
        .skip_while(|c| c.is_whitespace())
        .take_while(|c| c.is_ascii_digit())
        .collect();
    digits.parse::<u64>().ok()
}

fn has_method(line: &str, method: &str) -> bool {
    line.contains(&format!("\"method\": \"{}\"", method))
        || line.contains(&format!("\"method\":\"{}\"", method))
}

fn main() {
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut out = stdout.lock();
    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => break,
        };
        let id = match extract_id(&line) {
            Some(v) => v,
            None => continue,
        };
        if has_method(&line, "initialize") {
            let _ = writeln!(out, "{{\"id\":{},\"result\":{{\"ok\":true,\"api_version\":\"1\"}}}}", id);
        } else if has_method(&line, "event") {
            let _ = writeln!(
                out,
                "{{\"id\":{},\"result\":{{\"actions\":[{{\"type\":\"test\",\"message\":\"rust-ok\"}}]}}}}",
                id
            );
        } else if has_method(&line, "health") || has_method(&line, "shutdown") {
            let _ = writeln!(out, "{{\"id\":{},\"result\":{{\"ok\":true}}}}", id);
        } else {
            let _ = writeln!(out, "{{\"id\":{},\"error\":\"unknown method\"}}", id);
        }
        let _ = out.flush();
    }
}
```

### 2.5 Java

| 构建 | entry | 备注 |
| :--- | :--- | :--- |
| javac Plugin.java | run.sh | JVM 产物不是可执行文件，用 run.sh 包装 |

**manifest.json**

```json
{
  "id": "ml_java",
  "name": "Multilang Java Plugin",
  "version": "1.0.0",
  "author": "flowerie",
  "description": "任意语言插件示例：Java（run.sh 包装 exec java -cp）",
  "runtime": "exec",
  "entry": "run.sh",
  "api_version": "1",
  "permissions": []
}
```

**Plugin.java**

```java
// 最小「任意语言插件」示例：Java 实现 Plugin API v1（stdin/stdout JSON-Lines）
// 编译：javac Plugin.java      入口：run.sh（exec java -cp <dir> Plugin）
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.io.PrintWriter;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class Plugin {
    private static final Pattern ID_RE = Pattern.compile("\"id\":\\s*([0-9]+)");
    private static final Pattern METHOD_RE = Pattern.compile("\"method\":\\s*\"([a-z_]+)\"");

    public static void main(String[] args) throws IOException {
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in));
        PrintWriter out = new PrintWriter(new OutputStreamWriter(System.out), true);
        String line;
        while ((line = in.readLine()) != null) {
            Matcher idm = ID_RE.matcher(line);
            if (!idm.find()) continue;
            String id = idm.group(1);
            Matcher mm = METHOD_RE.matcher(line);
            String method = mm.find() ? mm.group(1) : "";
            switch (method) {
                case "initialize":
                    out.println("{\"id\":" + id + ",\"result\":{\"ok\":true,\"api_version\":\"1\"}}");
                    break;
                case "event":
                    out.println("{\"id\":" + id
                            + ",\"result\":{\"actions\":[{\"type\":\"test\",\"message\":\"java-ok\"}]}}");
                    break;
                case "health":
                case "shutdown":
                    out.println("{\"id\":" + id + ",\"result\":{\"ok\":true}}");
                    break;
                default:
                    out.println("{\"id\":" + id + ",\"error\":\"unknown method\"}");
            }
        }
    }
}
```

**run.sh**

```bash
#!/bin/sh
# Java 插件的入口包装：JVM 不是可执行文件，用 3 行脚本把 entry 变成"能直接跑的东西"
exec java -cp "$(dirname "$0")" Plugin
```

### 2.6 Kotlin

| 构建 | entry | 备注 |
| :--- | :--- | :--- |
| kotlinc plugin.kt -include-runtime -d plugin.jar | run.sh | 同 JVM，run.sh 里 java -jar |

**manifest.json**

```json
{
  "id": "ml_kotlin",
  "name": "Multilang Kotlin Plugin",
  "version": "1.0.0",
  "author": "flowerie",
  "description": "任意语言插件示例：Kotlin（run.sh 包装 java -jar）",
  "runtime": "exec",
  "entry": "run.sh",
  "api_version": "1",
  "permissions": []
}
```

**plugin.kt**

```kotlin
// 最小「任意语言插件」示例：Kotlin 实现 Plugin API v1（stdin/stdout JSON-Lines）
// 编译：kotlinc plugin.kt -include-runtime -d plugin.jar   入口：run.sh（exec java -jar plugin.jar）
import java.io.PrintWriter

val ID_RE = Regex("\"id\":\\s*([0-9]+)")
val METHOD_RE = Regex("\"method\":\\s*\"([a-z_]+)\"")

fun main() {
    val out = PrintWriter(System.out, true)
    while (true) {
        val line = readLine() ?: break
        val id = ID_RE.find(line)?.groupValues?.get(1) ?: continue
        val method = METHOD_RE.find(line)?.groupValues?.get(1) ?: ""
        val payload: String = when (method) {
            "initialize" -> "{\"id\":$id,\"result\":{\"ok\":true,\"api_version\":\"1\"}}"
            "event" -> "{\"id\":$id,\"result\":{\"actions\":[{\"type\":\"test\",\"message\":\"kotlin-ok\"}]}}"
            "health", "shutdown" -> "{\"id\":$id,\"result\":{\"ok\":true}}"
            else -> "{\"id\":$id,\"error\":\"unknown method\"}"
        }
        out.println(payload)
    }
}
```

**run.sh**

```bash
#!/bin/sh
# Kotlin 插件的入口包装：跑编译好的 fat-jar（测试/构建阶段先 kotlinc 生成 plugin.jar）
exec java -jar "$(dirname "$0")/plugin.jar"
```

### 2.7 C# / .NET

| 构建 | entry | 备注 |
| :--- | :--- | :--- |
| dotnet build -c Release | run.sh | dotnet run 会打印启动信息，run.sh 必须只转发行协议 |

**manifest.json**

```json
{
  "id": "ml_csharp",
  "name": "Multilang C# Plugin",
  "version": "1.0.0",
  "author": "flowerie",
  "description": "任意语言插件示例：C# / .NET（run.sh 包装 dotnet run）",
  "runtime": "exec",
  "entry": "run.sh",
  "api_version": "1",
  "permissions": []
}
```

**Program.cs**

```csharp
// 最小「任意语言插件」示例：C# / .NET 实现 Plugin API v1（stdin/stdout JSON-Lines）
// 运行：dotnet run --project <dir>（入口 run.sh 包装）
using System;
using System.IO;
using System.Text.RegularExpressions;

class Plugin
{
    static readonly Regex IdRe = new Regex("\"id\":\\s*([0-9]+)");
    static readonly Regex MethodRe = new Regex("\"method\":\\s*\"([a-z_]+)\"");

    static void Main()
    {
        var stdout = new StreamWriter(Console.OpenStandardOutput()) { AutoFlush = true };
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var idm = IdRe.Match(line);
            if (!idm.Success) continue;
            string id = idm.Groups[1].Value;
            var mm = MethodRe.Match(line);
            string method = mm.Success ? mm.Groups[1].Value : "";
            switch (method)
            {
                case "initialize":
                    stdout.WriteLine("{\"id\":" + id + ",\"result\":{\"ok\":true,\"api_version\":\"1\"}}");
                    break;
                case "event":
                    stdout.WriteLine("{\"id\":" + id + ",\"result\":{\"actions\":[{\"type\":\"test\",\"message\":\"csharp-ok\"}]}}");
                    break;
                case "health":
                case "shutdown":
                    stdout.WriteLine("{\"id\":" + id + ",\"result\":{\"ok\":true}}");
                    break;
                default:
                    stdout.WriteLine("{\"id\":" + id + ",\"error\":\"unknown method\"}");
                    break;
            }
        }
    }
}
```

**run.sh**

```bash
#!/bin/sh
# C# 插件的入口包装：dotnet 项目不是可执行文件，用脚本把 entry 变成"能直接跑的东西"
exec dotnet run --project "$(dirname "$0")" --nologo -v quiet
```

### 2.8 TypeScript

| 构建 | entry | 备注 |
| :--- | :--- | :--- |
| tsc plugin.ts --target es2019 --module commonjs | run.sh | tsc 产物是 .js，run.sh 里 node |

**manifest.json**

```json
{
  "id": "ml_typescript",
  "name": "Multilang TypeScript Plugin",
  "version": "1.0.0",
  "author": "flowerie",
  "description": "任意语言插件示例：TypeScript（tsc 编译后用 run.sh 包装 node）",
  "runtime": "exec",
  "entry": "run.sh",
  "api_version": "1",
  "permissions": []
}
```

**plugin.ts**

```typescript
// 最小「任意语言插件」示例：TypeScript 实现 Plugin API v1（stdin/stdout JSON-Lines）
// 编译：tsc plugin.ts --target es2019 --module commonjs   -> plugin.js
// 入口：run.sh（exec node plugin.js）
//
// 刻意做到**零 npm 依赖**：不要求插件作者先装 @types/node，
// 用 declare 自声明用到的最小接口 + require 取 readline 即可编译。
// 同时用字符串拼接而不是模板字面量，避免插值语法在不同工具链下的歧义。

declare const process: any;
declare function require(name: string): any;

const readline = require("readline");

const ID_RE = /"id":\s*(\d+)/;
const METHOD_RE = /"method":\s*"([a-z_]+)"/;

const rl = readline.createInterface({ input: process.stdin, terminal: false });
rl.on("line", (line: string) => {
  const idm = ID_RE.exec(line);
  if (!idm) return;
  const id = idm[1];
  const mm = METHOD_RE.exec(line);
  const method = mm ? mm[1] : "";
  let payload: string;
  switch (method) {
    case "initialize":
      payload = '{"id":' + id + ',"result":{"ok":true,"api_version":"1"}}';
      break;
    case "event":
      payload = '{"id":' + id + ',"result":{"actions":[{"type":"test","message":"typescript-ok"}]}}';
      break;
    case "health":
    case "shutdown":
      payload = '{"id":' + id + ',"result":{"ok":true}}';
      break;
    default:
      payload = '{"id":' + id + ',"error":"unknown method"}';
  }
  process.stdout.write(payload + "\n");
});
```

**run.sh**

```bash
#!/bin/sh
# TypeScript 插件的入口包装：tsc 产物是纯 JS（没有 shebang，不能直接 exec），用脚本包一层
exec node "$(dirname "$0")/plugin.js"
```

### 2.9 PHP

| 构建 | entry | 备注 |
| :--- | :--- | :--- |
| （无需构建） | plugin.php | shebang 脚本，注意别把警告输出到 stdout |

**manifest.json**

```json
{
  "id": "ml_php",
  "name": "Multilang PHP Plugin",
  "version": "1.0.0",
  "author": "flowerie",
  "description": "任意语言插件示例：PHP（shebang 脚本）",
  "runtime": "exec",
  "entry": "plugin.php",
  "api_version": "1",
  "permissions": []
}
```

**plugin.php**

```php
#!/usr/bin/env php
<?php
// 最小「任意语言插件」示例：PHP 实现 Plugin API v1（stdin/stdout JSON-Lines）
$in = fopen('php://stdin', 'r');
while (($line = fgets($in)) !== false) {
    if (!preg_match('/"id":\s*([0-9]+)/', $line, $m)) {
        continue;
    }
    $id = $m[1];
    $method = preg_match('/"method":\s*"([a-z_]+)"/', $line, $mm) ? $mm[1] : '';
    switch ($method) {
        case 'initialize':
            echo '{"id":' . $id . ',"result":{"ok":true,"api_version":"1"}}', PHP_EOL;
            break;
        case 'event':
            echo '{"id":' . $id . ',"result":{"actions":[{"type":"test","message":"php-ok"}]}}', PHP_EOL;
            break;
        case 'health':
        case 'shutdown':
            echo '{"id":' . $id . ',"result":{"ok":true}}', PHP_EOL;
            break;
        default:
            echo '{"id":' . $id . ',"error":"unknown method"}', PHP_EOL;
    }
    fflush(STDOUT);
}
```

### 2.10 Lua

| 构建 | entry | 备注 |
| :--- | :--- | :--- |
| （无需构建） | plugin.lua | 必须 io.stdout:setvbuf(line) |

**manifest.json**

```json
{
  "id": "ml_lua",
  "name": "Multilang Lua Plugin",
  "version": "1.0.0",
  "author": "flowerie",
  "description": "任意语言插件示例：Lua（shebang 脚本）",
  "runtime": "exec",
  "entry": "plugin.lua",
  "api_version": "1",
  "permissions": []
}
```

**plugin.lua**

```lua
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
```

### 2.11 Ruby

| 构建 | entry | 备注 |
| :--- | :--- | :--- |
| （无需构建） | plugin.rb | 必须 $stdout.sync = true |

**manifest.json**

```json
{
  "id": "ml_ruby",
  "name": "Multilang Ruby Plugin",
  "version": "1.0.0",
  "author": "flowerie",
  "description": "任意语言插件示例：Ruby（最小 Plugin API v1 实现）",
  "runtime": "exec",
  "entry": "plugin.rb",
  "api_version": "1",
  "permissions": []
}
```

**plugin.rb**

```ruby
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
```

### 2.12 Perl

| 构建 | entry | 备注 |
| :--- | :--- | :--- |
| （无需构建） | plugin.pl | 必须 $| = 1 |

**manifest.json**

```json
{
  "id": "ml_perl",
  "name": "Multilang Perl Plugin",
  "version": "1.0.0",
  "author": "flowerie",
  "description": "任意语言插件示例：Perl（最小 Plugin API v1 实现）",
  "runtime": "exec",
  "entry": "plugin.pl",
  "api_version": "1",
  "permissions": []
}
```

**plugin.pl**

```perl
#!/usr/bin/env perl
# 最小「任意语言插件」示例：Perl 实现 Plugin API v1（stdin/stdout JSON-Lines）
use strict;
use warnings;
$| = 1;    # 关闭输出缓冲（协议要求逐行即时响应）

while (my $line = <STDIN>) {
    my ($id)     = $line =~ /"id":\s*(\d+)/;
    my ($method) = $line =~ /"method":\s*"([a-z_]+)"/;
    next unless defined $id && defined $method;

    if    ($method eq 'initialize') { print qq({"id":$id,"result":{"ok":true,"api_version":"1"}}\n); }
    elsif ($method eq 'event')      { print qq({"id":$id,"result":{"actions":[{"type":"test","message":"perl-ok"}]}}\n); }
    elsif ($method eq 'health')     { print qq({"id":$id,"result":{"ok":true}}\n); }
    elsif ($method eq 'shutdown')   { print qq({"id":$id,"result":{"ok":true}}\n); }
    else                            { print qq({"id":$id,"error":"unknown method"}\n); }
}
```

### 2.13 R

| 构建 | entry | 备注 |
| :--- | :--- | :--- |
| （无需构建） | plugin.R | Rscript，输出后要 flush |

**manifest.json**

```json
{
  "id": "ml_r",
  "name": "Multilang R Plugin",
  "version": "1.0.0",
  "author": "flowerie",
  "description": "任意语言插件示例：R（shebang 脚本）",
  "runtime": "exec",
  "entry": "plugin.R",
  "api_version": "1",
  "permissions": []
}
```

**plugin.R**

```r
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
```

---

## 3. 构建与入口速查

| 语言 | 构建命令 | entry | 首次运行需要 |
| :--- | :--- | :--- | :--- |
| C | gcc -O2 -o plugin plugin.c | plugin | gcc |
| C++ | g++ -O2 -std=c++17 -o plugin plugin.cpp | plugin | g++ |
| Go | go build -o plugin main.go | plugin | go |
| Rust | rustc -O -o plugin main.rs | plugin | rustc |
| Java | javac Plugin.java | run.sh | JDK |
| Kotlin | kotlinc plugin.kt -include-runtime -d plugin.jar | run.sh | kotlinc + JDK |
| C# / .NET | dotnet build -c Release | run.sh | .NET SDK |
| TypeScript | tsc plugin.ts --target es2019 --module commonjs | run.sh | node + tsc |
| PHP | （无需构建） | plugin.php | php |
| Lua | （无需构建） | plugin.lua | lua5.4 |
| Ruby | （无需构建） | plugin.rb | ruby |
| Perl | （无需构建） | plugin.pl | perl |
| R | （无需构建） | plugin.R | Rscript（r-base-core） |

---

## 4. 排查清单（按出现频率排序）

| 症状 | 原因 | 解法 |
| :--- | :--- | :--- |
| 插件起来了但永远不回消息 | stdout 没 flush | Ruby $stdout.sync=true、Lua io.stdout:setvbuf("line")、Perl $|=1、C/C++/Go/Rust 每行后 flush |
| 花璃报协议错误 / 非法 JSON | stdout 混进了日志或编译器输出 | 日志一律走 stderr；dotnet run 这类会打印启动信息的必须用 run.sh 只转发协议 |
| 编译型插件换台机器跑不了 | 缺运行时（JVM/.NET）或架构不符 | 优先静态产物（Go / Rust / C）；否则装对应运行时 |
| 进程起来立刻退出 | run.sh 忘了 exec，或入口没有执行权限 | run.sh 用 exec；确认 chmod +x |
| 事件收得到、动作不生效 | manifest 的 permissions 没声明 | 补上对应权限（见 plugin-developer-guide §权限） |
| 中文乱码 | 没按 UTF-8 处理 | 读写都按 UTF-8 解码 |

---

## 5. 自测（不用真 QQ）

```bash
# 手动喂一行 initialize，看它回什么
echo '{"id":1,"method":"initialize","params":{}}' | ./plugin
# 期望：{"id":1,"result":{"ok":true,"api_version":"1"}}

# 仓库里有完整黑盒测试（真的拉起进程跑：握手 → 事件 → 关机）
pytest tests/test_plugin_multilang.py -q -k go
```
