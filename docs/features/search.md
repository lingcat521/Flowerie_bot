# 网页搜索（原生免 key 引擎）

花璃内置网页搜索（v2.15.0），让 AI **自主**获取实时信息——不用配 API key、不用接 MCP。
引擎层移植自 [dsh-free-search](https://github.com/DDDMUC/dsh-free-search) v0.9.14（MIT）的 keyless 部分。

默认**关闭**。在 Web UI「网页搜索」页或配置 `AI_SEARCH_ENABLED=true` 开启后，模型在需要实时信息时
可自行调用 `web_search`（搜索）与 `web_fetch`（抓正文）两个工具，与 MCP 工具共用同一套额度与安全边界。

## 工作机制

- **模型自主判断**是否需要搜索——不是每条消息都搜。提示词里会注入使用须知（贵、慢、结果不可信）。
- **4 个免 key 引擎**：DuckDuckGo HTML / DuckDuckGo Lite / Bing / SearXNG（6 个公共实例轮询）
- **失败感知回退**：按 `SEARCH_ENGINES` 顺序串行；transient 错误同引擎重试一次，403/429 反爬冷却 60 秒，
  整条链总预算 30 秒（防止各引擎超时累加到分钟级）
- **Bing 反爬适配**：`ck/a` 跳转链接自动解包；「无结果返回无关缓存页」用查询词重叠度识别后判 0 结果继续回退
- **结果是不可信外部输入**：过 `sanitize_untrusted_text` 消毒 + 条数/长度硬上限（10 条 / 2000 字符）

## Web UI「网页搜索」页

抽屉里的「网页搜索」tab 提供：

- 引擎状态卡片（启用/停用一目了然）
- **试搜**：用当前配置跑一次真实搜索，直接看结果
- **逐引擎自检**：手动按钮，逐个测引擎连通性（不自动跑，避免给公共实例压力）

## 配置项

| 变量 | 默认 | 说明 |
 | :--- | :--- | :--- |
 | `AI_SEARCH_ENABLED` | `false` | AI 搜索工具开关（默认关；模型自主调用 web_search/web_fetch） |
 | `SEARCH_ENGINES` | `ddg,bing,searxng,ddg-lite` | 启用引擎与回退顺序（逗号分隔） |
 | `SEARCH_MAX_RESULTS` | `5` | 默认结果条数（1-10） |
 | `SEARCH_TIMEOUT` | `10` | 单引擎请求超时（秒） |
 | `SEARCH_CACHE_TTL` | `5` | 结果缓存分钟数（0=禁用；最大 5） |
 | `SEARCH_SAFE_SEARCH` | `off` | 安全搜索：`off`/`moderate`/`strict`（Bing/DDG 生效） |
 | `SEARCH_BLOCKED_DOMAINS` | 空 | 结果域名黑名单（逗号分隔；命中域名的条目直接丢弃） |
 | `SEARCH_SEARXNG_INSTANCES` | 内置 6 个 | SearXNG 公共实例列表（逗号或换行分隔；留空=内置） |
 | `SEARCH_FETCH_MAX_CHARS` | `2000` | `web_fetch` 正文截断字数（1000-8000） |
 | `SEARCH_PROOF_REQUIRED` | `true` | 结果附来源 URL 要求 |

全部热更新（改完保存即生效，不用重启）。

## 安全边界

- **默认关**：与 QQ空间/群管理/记忆工具一样，`AI_*` 开关默认 false
- **SSRF 防线**：`web_fetch` 复用 `validate_mcp_server_url`——回环/私网/链路本地/保留地址一律拒绝
- **额度共享**：搜索占用 `MCP_MAX_TOOL_CALLS` 的同一逻辑请求配额（含 reply 工具），不能绕过
- **不可信数据**：结果消毒 + 截断；Web UI 试搜结果纯文本转义渲染（防 XSS）

## 注意

- 免 key 引擎是**抓取公开页面**，上游改版会失效；引擎挂了会在搜索 tab 的自检里暴露
- Termux/代理出口 IP 可能被 Bing 间歇性反爬（返回空 SERP）——这是出口 IP 问题，重试会更糟，
  代码里**不做**重试，直接回退到下一个引擎
- SearXNG 公共实例有限流，列表可以在配置里换成你信任的实例
