# 网页搜索

花璃内置网页搜索，让 AI **自主**获取实时信息。四个免费引擎免 Key，可选 DeepSeek 原生搜索按 token 计费。
引擎层移植自 [dsh-free-search](https://github.com/DDDMUC/dsh-free-search) v0.9.14（MIT）的 keyless 部分。

默认**关闭**。在 Web UI「自动化」页或配置 `AI_SEARCH_ENABLED=true` 开启后，模型在需要实时信息时
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

- **当前执行顺序**显示自动编排或配置指定的顺序。凭据可用且允许付费时，自动编排会把 DeepSeek 加到链首。如果已在 `SEARCH_ENGINES` 显式配置，则保留它的位置。
- **付费搜索**开关保存后即时生效。关闭时从执行链移除 DeepSeek，包含显式配置的情况。引擎卡会区分付费关闭、Key 缺失、模板值、可用、冷却中和上次自检失败。
- **试搜**支持自动或指定优先引擎。首选引擎失败时继续回退，页面显示实际命中引擎。
- **逐引擎自检**会对执行链中的引擎发起真实搜索，并显示本次耗时与预算。免费引擎使用 `max(40, SEARCH_TIMEOUT × 4)` 秒，DeepSeek 完整模型回合的预算多 5 秒，原生搜索会计费。
- **用户状态 → DeepSeek 搜索（原生）**可以单独测试端点与凭据。请求最多等待 20 秒，输出上限 16 token。该测试无需调用搜索工具，因此不消耗搜索额度，仍可能产生模型 token 费用。

### 两个付费相关的开关（别混）

| 键 | 语义 | 关掉后 |
| :--- | :--- | :--- |
| `SEARCH_PAID_ENABLED` | **允不允许**用付费搜索（总闸） | `deepseek-native` 从执行链彻底剔除，**即使显式写进 `SEARCH_ENGINES` 也不用** |
| `SEARCH_DEEPSEEK_PRIORITY` | 允许的前提下，**是否自动排到链首** | 不自动前置，但若配置里写了就按它的位置执行 |

一句话：**PAID 是「能不能用」，PRIORITY 是「排不排前面」**。两个都开且凭据可用时，
链路才是 `deepseek-native → ddg → bing → searxng → ddg-lite`。

凭据可用性判定（避免模板值误用）：Key 长度 ≥ 20 且不含占位符特征
（`sk-original` / `sk-your-key` / `sk-test` / `changeme` / `todo`）。
`.env` 里留着模板值也不会让链路每次都去打一个必然 401 的端点。

## DeepSeek 原生搜索怎么工作

与四个免费引擎**完全不同的机制**——免费引擎是花璃抓 HTML 自己解析，
原生搜索是**模型在服务端执行**：

```
POST {SEARCH_DEEPSEEK_BASE_URL}/messages          # Anthropic 兼容协议
{
  "model": "deepseek-v4-flash",
  "messages": [{"role": "user", "content": "Perform a web search for the query: ..."}],
  "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
  "thinking": {"type": "disabled"}                  # 搜索不需要推理，省 token
}
```

解析要点（照搬 DeepSeek Harness 的实现）：

- 只认 `web_search_tool_result` 块；**没有结果块就报错**，不降级去正则刮正文
- 结果项（`web_search_result`）通常**不带摘要**——摘要在 `text` 块的 `citations[].cited_text` 里，
  按 url 建映射补齐（首次出现优先）
- `page_age` → 发布时间；按 url 去重
- 401 单独识别为「凭据无效」，不重试也不进冷却链

成本：每次搜索消耗**一个模型回合**（`max_tokens` 2048），与免费引擎的抓取成本量级不同。
## 配置项

| 变量 | 默认 | 说明 |
| :--- | :--- | :--- |
 | `AI_SEARCH_ENABLED` | `false` | AI 搜索工具开关（默认关；**Web UI「自动化」页**统一管理，与其它 AI_* 工具同列） |
 | `SEARCH_ENGINES` | `ddg,bing,searxng,ddg-lite` | 启用引擎与回退顺序（逗号分隔） |
 | `SEARCH_PAID_ENABLED` | `true` | 是否允许调用 DeepSeek 原生搜索 |
 | `SEARCH_DEEPSEEK_PRIORITY` | `true` | 自动将可用的 DeepSeek 原生搜索加入链首 |
 | `SEARCH_DEEPSEEK_BASE_URL` | `https://api.deepseek.com/anthropic/v1` | Anthropic 兼容端点 |
 | `SEARCH_DEEPSEEK_MODEL` | `deepseek-v4-flash` | 原生搜索模型 |
 | `SEARCH_DEEPSEEK_API_KEY` | 空 | 搜索专用 Key，未设置时复用聊天 Key |
 | `SEARCH_DEEPSEEK_MAX_USES` | `3` | 每个模型回合允许调用服务端搜索的次数（1–10） |
 | `SEARCH_MAX_RESULTS` | `5` | 默认结果条数（1-10） |
 | `SEARCH_TIMEOUT` | `10` | 单引擎请求超时（秒） |
 | `SEARCH_CACHE_TTL` | `5` | 结果缓存分钟数（0=禁用；最大 5） |
 | `SEARCH_SAFE_SEARCH` | `off` | 安全搜索：`off`/`moderate`/`strict`（Bing/DDG 生效） |
 | `SEARCH_BLOCKED_DOMAINS` | 空 | 结果域名黑名单（逗号分隔；命中域名的条目直接丢弃） |
 | `SEARCH_SEARXNG_INSTANCES` | 内置 6 个 | SearXNG 公共实例列表（逗号或换行分隔；留空=内置） |
 | `SEARCH_FETCH_MAX_CHARS` | `2000` | `web_fetch` 正文截断字数（1000-8000） |
 | `SEARCH_PROOF_REQUIRED` | `true` | 结果附来源 URL 要求 |

全部热更新（改完保存即生效，不用重启）。

## AI 自主选择引擎

`web_search` 工具在**配置了可用凭据**时会多一个可选参数 `engine`，枚举为全部引擎 id。
模型可以据此权衡：

```python
{"query": "DeepSeek V4 发布时间", "engine": "deepseek-native"}   # 要准确，愿意花钱
{"query": "今天天气", "engine": "bing"}                        # 省钱
{"query": "Python 3.14 新特性"}                                  # 不传 = 按配置自动挑
```

设计取舍：

- **无凭据时不暴露 `engine`**——免费引擎之间（ddg / bing / searxng）的差别对模型没有决策意义，
  让模型纠结引擎名纯属浪费 token，交给自动回退即可
- **模型传了不存在的引擎名时静默忽略**（回落自动编排），不返回错误——否则会打断对话上下文
- 插件通过平台 API 指定 `engine` 时**同样遵守 `SEARCH_PAID_ENABLED`**：付费关闭时该参数被丢弃
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
