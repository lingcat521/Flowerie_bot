# Phase 0 审计数据（附录）

本目录是 `docs/architecture/refactor-audit.md`（Phase 0 只读审计报告）的**原始机械数据**，
由审计会话中的 AST / import 图脚本直接生成，未手工修饰；正文引用时标注为 `[SCAN]`。

| 文件 | 内容 | 生成方式 |
| :--- | :--- | :--- |
| `mechanical.md` | God Class 候选（跨度/方法/属性/self 私有调用）、超长与高分支函数、单文件体量 | AST 遍历 134 个类 / 1738 个函数 |
| `scan.md` | import 图与循环依赖结论（含一次误报纠正）、完全同形重复函数、裸 `create_task`、async 内同步 IO、实例容器 | 模块级 + 函数级 AST |
| `imports.md` | 只统计**模块级** import 的循环依赖结论 + 47 处函数内延迟 import 清单 | 模块级 AST（排除函数体） |
| `perf-findings.md` | 16 个 HTTP client 新建点 + 8 处 async 内同步 IO 的**逐个判定** | AST + 人工判定 |
| `test-guard-map.md` | 模块 ↔ 测试映射（205 个测试文件 → 109 个 src 模块）+ 测试直接触碰的私有成员 | AST + 正则（按对象名前缀可靠归因） |
| `persistence-config.md` | 持久层 / 配置层 / utils 审计（`SettingsRepository` 职责域、多后端对比、双份字段清单漂移、死代码候选） | AST + 脚本比对 |

> 说明：这些数据是**只读审计**产物，不代表已完成的改动；数字对应审计时的提交（`e8ce351` 之后的 main）。

## 四份深读分片报告（子代理产出，逐条带 文件:行）

| 文件 | 范围 | 规模 |
| :--- | :--- | ---: |
| `plugins-godclass-audit.md` | 插件子系统（PluginManager / PluginApi / PluginRunner / Runtime / comm / router / permissions…） | 503 行 |
| `core-audit-phase0.md` | 消息主链路 core/ 与直接相关 services | 398 行 |
| `webui_config_audit.md` | WebUI（WebUIServer + 11 mixin + render 包）与配置域 | 555 行 |
| `services-deadcode-audit.md` | services / adapters / transport / repositories + 死代码与重复逻辑 | 545 行 |
| `deadcode-quick.md` | 父代理快速引用扫描（20 个候选的引用计数） | 25 行 |
