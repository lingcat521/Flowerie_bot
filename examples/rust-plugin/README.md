# Rust 示例插件（Protocol v1）

```bash
# 依赖：rustc ≥ 1.70（仅编译器，不需要 cargo、不联网）
cp -r examples/rust-plugin /path/to/plugins/     # 需同时带上 sdk/rust（run.sh 用相对路径引用）
# Web UI「插件」页启用 + 批准 send_message / read_message
```

| 项 | 说明 |
| :--- | :--- |
| SDK | `sdk/rust/src/{lib.rs,json.rs}`（零 crate 依赖；自带极简 JSON 编解码，不拉 serde）|
| 协议 | `initialize / event / health / shutdown` + 14 个可选方法（含 `plugin.call` / `plugin.event` / `plugin.cancel`）|
| 语义 | `text=ping` → `send_message{message:"pong"}`；`status` hook 读 storage 计数器；`expose("get_status")` + `comm_call` / `comm_emit` / `comm_cancel` hook |
| 验证 | `python3 -m pytest tests/test_plugin_sdk_contract.py -q`（真起 rustc 编译产物走协议）|
