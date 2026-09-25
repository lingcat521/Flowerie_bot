# ADR-006：多实例（Instances, not Singletons）

- **状态**：已实施（首版）｜**日期**：2026-08-09｜**对应 Gate**：S

## 要回答的问题

任务书 Gate S 要求同时存在 **OneBot11 #1、OneBot11 #2、Milky #1** 三个实例，
每个实例独立连接 / 独立配置 / 独立生命周期 / 独立发送 / 独立接收，硬性指标
**Instance Cross-talk = 0**，并且不得依赖 `current_protocol` / `current_ws` / `global_adapter`
这类"全局当前值"。

这是真实风险：一个机器人框架最常见的退化就是"全局当前协议 + 全局当前连接"——
第二个实例一连上，第一个实例的事件就被路由到错误的解析器，或者消息从别的连接发出去。
这类 bug 在单实例部署下永远看不到。

## 决策

### 1. 没有全局态，注册表是普通对象（`src/adapters/instance.py`）

```text
InstanceRegistry            ← 普通对象：谁持有谁负责生命周期（不是模块级单例）
   └── AdapterInstance(id)  ← 自己的解析器 / 描述符 / 通道 / 配置 / 发送记录 / 收件计数
```

- **解析器**：每个实例一个（`make_parser(protocol, bot_qq)`，组合根唯一入口）；
  即使两个实例都是 OneBot11，也是两个解析器对象（`is not` 有测试钉住）；
- **发送出口**：每个实例自己的通道。**未接线通道的实例发送时明确失败**，绝不借用别的实例的通道
  —— 这正是串台最常见的来源；
- **配置**：每个实例持有自己的 config 对象（协议、Bot QQ、接口地址都从它读）；
- **发送记录 / 收件计数**：属于实例自己，跨实例不可见。

`make_instance()` 只在**传入 session** 时才构造动作通道（懒 import
`src.transport.action_channels`），因此不装 aiohttp 也能装配实例（多实例语义与网络库解耦）。

### 2. 注册表语义：显式、可预期

| 操作 | 行为 |
| :--- | :--- |
| `register` | 重名 → `ValueError`（**不做**静默覆盖——静默覆盖会让"第二个实例"凭空顶掉第一个） |
| `get` | 缺失 → `KeyError`（不返回 None：调用方必须处理"实例不存在"，而不是对着 None 调用） |
| `find` | 缺失 → `None`（需要探测时用这个） |
| `ids` / `all` | 稳定排序输出（日志与 Dashboard 可复现） |
| `connect_all` / `disconnect_all` | 批量生命周期（返回成功数） |
| `snapshot` | 每实例状态（协议/Bot QQ/state/收件数/发送数/能力 id），**不含消息内容** |

### 3. Cross-talk = 0 是**测出来**的，不是声明的

`tests/test_multi_instance.py` 用三个真解析器 + 三个独立假通道并发跑：

- 每实例 20 轮：解析带自己标记的事件 → 经自己的通道发送同样的标记；
- 断言每个通道收到的**每一条**消息都以本实例 id 开头（跨实例标记出现即失败）；
- 断言解析结果按各实例自己的 Bot QQ 判定 `is_mentioned`（同一个 @10001 消息：
  #1 为 True、#2 为 False）——证明"配置"确实是**各自的**；
- 断言可变状态不共享（`channel.posts` / `instance.sent` 都是不同对象）；
- 断开 #2 后：#2 发送明确失败且通道无记录，#1/#3 照常收发。

### 4. 单例是静态禁止的

一条测试扫 `src/` 全部 Python 文件，用 **AST** 收集真正被引用的名字（变量/属性名 +
非文档字符串的字面量，因此 `getattr(obj, "current_protocol")` 也逃不掉），
断言 `current_protocol` / `current_ws` / `global_adapter` 出现 **0 次**。
另有反向对照（正则确实抓得到这些词）与"模块级不得有可变状态"的 AST 检查，
避免"扫描永远为空"的假绿。

## 被否决的方案

1. **类属性/模块级 registry 单例**（`InstanceRegistry.instance()`）：方便，但把"实例集合"
   变成隐式全局依赖，测试之间互相污染 —— 与 Gate S 的硬性要求直接冲突；
2. **按协议查找（`find_by_protocol("onebot")`）作为主接口**：两个 OneBot11 实例时语义不成立，
   必然退化成"取第一个" = 隐式单例；主接口必须是实例 id；
3. **共享解析器**（两个 OneBot11 实例复用一个 parser）：parser 持有 `bot_qq`（决定 `is_mentioned`），
   共享必然串台；故每实例一个；
4. **未接线时回落到"最近活跃通道"**：这是把串台写成特性的典型做法，明确拒绝 —— 宁可发送失败。

## 诚实边界

| 未做到 | 说明 |
| :--- | :--- |
| 生产启动未改为多实例 | `main.py` 目前仍是"单配置单连接"（本仓库的部署形态就是一个 QQ 号）；`InstanceRegistry` 已就绪，多账号/多协议并存的启动改造是独立动作 |
| 无实机验证 | 三个实例的连接都是进程内状态机；真实"两个 OneBot 客户端同时连"仍需实机（G5/G6 BLOCKED） |
| 未覆盖跨实例资源竞争 | 例如两个实例同时写同一个存档目录；当前 `config` 各自独立即可回避，但没有专门的隔离测试 |

## 复现方式

```bash
python3 -m pytest tests/test_multi_instance.py -q     # 7 项（3 并存 + 并发隔离 + 生命周期 + 注册表 + 2 项静态）
```
