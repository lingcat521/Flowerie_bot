# Java 示例插件（Protocol v1）

```bash
# 依赖：JDK ≥ 11（javac + java，不需要 Maven/Gradle）
cp -r examples/java-plugin /path/to/plugins/     # 需同时带上 sdk/java（run.sh 用相对路径引用）
# Web UI「插件」页启用 + 批准 send_message / read_message
```

| 项 | 说明 |
| :--- | :--- |
| SDK | `sdk/java/src/main/java/dev/flowerie/sdk/`（零第三方依赖；自带极简 JSON 编解码）|
| 协议 | `initialize / event / health / shutdown` + 8 个可选方法 |
| 语义 | `text=ping` → `send_group_msg{message:"pong"}`；`status` hook 读 storage 计数器 |
| 验证 | `python3 -m pytest tests/test_plugin_sdk_contract.py -q`（真起 javac 编译产物走协议）|
