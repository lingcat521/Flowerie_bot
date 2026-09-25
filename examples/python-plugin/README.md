# Python 示例插件（Protocol v1 参照实现）

```bash
cp -r examples/python-plugin /path/to/plugins/
# Web UI「插件」页启用 + 批准 send_message / read_message
```

| 项 | 说明 |
| :--- | :--- |
| 运行时 | `runtime=python`（引擎用 `python -I` 起 runner，插件在自己的进程里）|
| 语义 | `on_message`：`text=ping` → `send_message{message:"pong"}`；`status` hook 读 storage 计数器 |
| 验证 | `python3 -m pytest tests/test_plugin_sdk_contract.py -q`（与其它语言跑同一批向量）|
