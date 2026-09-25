# Go 示例插件（Protocol v1）

```bash
# 依赖：Go ≥ 1.21
cp -r examples/go-plugin /path/to/plugins/     # 或把 examples/ 与 sdk/ 一起拷贝（go.mod 用相对路径 replace）
# Web UI「插件」页启用 + 批准 send_message / read_message
```

| 项 | 说明 |
| :--- | :--- |
| SDK | `sdk/go/flowerie`（零第三方依赖，只用标准库）|
| 协议 | `initialize / event / health / shutdown` + 8 个可选方法 |
| 语义 | `text=ping` → `send_message{message:"pong"}`；`status` hook 读 storage 计数器 |
| 验证 | `python3 -m pytest tests/test_plugin_sdk_contract.py -q`（真起 go 进程走协议）|
