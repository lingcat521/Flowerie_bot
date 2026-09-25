# TypeScript 示例插件（Protocol v1）

跨语言契约测试的参与者之一：与 Python / Go / Rust / Java 示例**行为完全一致**。

```bash
# 依赖：Node ≥ 22.6（直接跑 TS）或 tsc（先编译）
cp -r examples/typescript-plugin /path/to/plugins/
# 在 Web UI「插件」页启用并批准 send_message / read_message
```

| 项 | 说明 |
| :--- | :--- |
| SDK | `sdk/typescript/flowerie_sdk.ts`（零 npm 依赖，只用 node 内置模块）|
| 协议 | `initialize / event / health / shutdown` + 8 个可选方法（storage/config/permission/context）|
| 语义 | 收到 `text=ping` → 回 `send_group_msg{message:"pong"}`；`status` hook 返回 storage 里的计数器 |
| 验证 | `python3 -m pytest tests/test_plugin_sdk_contract.py -q`（真起 node 子进程走协议）|
| 编译分支 | Node ≥ 22.6 直接跑 `.ts`；更老的 node 用 `tsc`（无 `@types/node` 时自动带上 `sdk/typescript/shims/node.d.ts`）|
