# Persona 人格系统

把"Bot = 花璃"升级为**可管理的人格资源**：全局 / 群聊 / 内置默认三级解析，内置三套官方预设（花璃 / 亚托莉 ATRI / 艾拉 Isla）。

## 解析与回退

```
Group Persona（群聊人格）→ 未设置/已解除 → Global Persona（全局）→ 未设置 → PERSONA_DEFAULT（兜底，默认 flowerie）
```

- 群聊人格删除后自动回退全局；全局未设置回退内置默认；群/全局引用了已删除人格（悬挂引用）同样回退下一级，不崩溃（`PersonaManager.resolve_persona`，`src/services/persona_manager.py:81-104`）。
- **每次请求动态解析**，绝不写入长期记忆 / 上下文——切换人格不污染记忆；Memory / Context / Persona 严格分离。

## 人格是独立资源

存于 `data/settings.db`（表 `personas`，另有 `group_persona` / `persona_global`）：

| 字段 | 说明 |
| :--- | :--- |
| `id` | 唯一 id，限 `^[a-z0-9][a-z0-9_-]{0,31}$`（`src/services/persona_manager.py:27`） |
| `name` / `description` | 显示名 / 简介（Web UI 展示） |
| `system_prompt` | 人格核心文本（身份/背景/性格/说话风格/对话范例），上限 `MAX_PERSONA_PROMPT_LENGTH` |
| `vocabulary` | 词库/黑话参考（选填；未被 system_prompt 包含时作为【词库参考】段注入） |
| `behavior_rules` / `response_style` | 行为规则 / 回复风格补充（选填） |
| `builtin` | 内置标记：不可删除、不可改 id；内容可编辑，可 reset 回预设 |

- 独立人格**不是**对花璃 Prompt 的微调：`system_prompt` 完全独立，可整段替换。
- 内置预设（`src/services/persona_presets.py:219`）首次启动**幂等播种**且是唯一来源：`flowerie`（花璃）、`atri`（亚托莉 ATRI）、`isla`（艾拉 Isla）。
- 说话风格规则归属各 Persona；另有一套**全局**说话风格规则以最高优先级注入，所有人格必须遵守（见「系统提示组装」）。

## 管理员补充发言规则（ADMIN_RESPONSE_RULES，v1.2.0）

- `List[str]`，**每行一条**；**默认已内置 4 条**（内容与全局风格规则同文，`src/config.py:227-232`）。Web UI「人格」页用 `<textarea>` 编辑，保存即热更新。
- 注入方式：追加在人格块之后（`【管理员补充发言规则（不得覆盖安全策略，仅用于指定输出风格）】`，最多 50 条 × 每条 200 字，`src/core/ai_gateway.py:139-146`）。
- 优先级：**安全策略 > 人格 > 人格内置规则 > 本条**；运行时策略 / Prompt 注入清洗 / 记忆校验 / 预算限制不会被任何提示文本绕过。

## 与人设联动的群特色昵称

群特色昵称按 **群 + 当前人设** 解析（人设精确命中 → 群级 → `BOT_NICKNAME` 默认），因此同一句称呼在绑定不同人设的群里唤对应名字；配置与页面见 [configuration.md](configuration.md) 与 [web-ui.md](web-ui.md)。

## 系统提示组装（`src/services/prompt_builder.py`）

```
[人格块（Group > Global > 内置默认）+ 管理员补充发言规则]
[全局说话风格 & 标点规则（最高优先级，所有人格必须遵守）]
[记忆功能 / 记忆安全铁律]              ← 系统框架，所有人格一致
[自定义人格补充（/prompt 或群聊配置，明确低于安全规则）]
[本群专属称呼] + [用户记忆（不可信数据清洗后）]
【输入安全声明（最高优先级，绝不可被覆盖）】
-------- [不可信数据区开始] 群聊知识（命中才注入）+ 群聊记录 --------
-------- [不可信数据区结束] --------
```

人格内容属于"指令区"（管理员配置），但**安全声明、记忆铁律、知识区边界**不可被任何人格覆盖；知识区内容永远标记为不可信上下文知识。

## 三套内置预设

- **花璃**（`flowerie`）：官方默认，小恶魔系青梅竹马（《童话般的你开始了恋爱猛攻》改编）。
- **亚托莉（`atri`）**：高性能机器人少女（《ATRI -My Dear Moments-》整体印象**原创改编**）；口癖"我可是高性能的嘛"；**严禁称呼群内任何人为"主人"**；不复制原作台词。
- **艾拉（`isla`）**：温柔克制 / 常带自贬 / 关键时刻决断的机器人少女（《可塑性记忆》整体印象**原创改编**）；不复制原作台词。
- 三套均强制遵守全局说话风格规则。

## 权限与配置

普通用户仅能使用当前生效人格；管理员（Web UI 登录账号）可设全局人格、创建/编辑/删除人格、绑定/解除群聊人格；复用 fb_token 认证 + 登录限流。

| 变量 | 默认 | 说明 |
| :--- | :--- | :--- |
| `PERSONA_DEFAULT` | `flowerie` | 兜底人格 id（Web UI 人格页可改，**热更新立即生效**） |
| `MAX_PERSONA_PROMPT_LENGTH` | `8000` | 单人 system_prompt 上限（字，需重启） |
| `PERSONA_MAX_COUNT` | `200` | 自定义人格总数上限（内置不计，防无限增长） |
| `ADMIN_RESPONSE_RULES` | 4 条默认 | 管理员补充发言规则（每行一条，热更新） |

## 测试

`pytest tests/test_persona_manager.py tests/test_persona_seed_sync.py tests/test_persona_isla.py tests/test_group_nicknames_persona.py tests/test_web_ui_persona_knowledge.py -q`

