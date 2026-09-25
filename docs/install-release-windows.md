# Windows 可执行文件使用说明（.exe）

> 当前版本 **v2.3.0**。官方 Release 提供：
> `Flowerie_bot-windows-x64-builtin.exe`（Intel/AMD）与 `Flowerie_bot-windows-arm64-builtin.exe`（Arm 设备 / 越狱 Android 模拟）；
> 另有目录版 `Flowerie_bot-windows-x64-portable.zip` / `-windows-arm64-portable.zip`（解压即用）。
> 其他平台见 [install-release-guide.md](install-release-guide.md)。

## 1. 下载

打开 [Releases](https://github.com/lingcat521/Flowerie_bot/releases) → 选版本 → Assets → 下载对应文件。

- **单文件版（`*-builtin.exe`）**：免安装，启动稍慢。
- **目录版（`*-portable.zip`）**：解压出 `Flowerie_bot-windows-<arch>-portable\` 目录，里面的 `Flowerie_bot-windows-<arch>-portable.exe` 就是入口，启动更快。

两者功能完全一致。

## 2. 运行（⚠️ 不要双击）

exe 是**控制台程序**（无图形界面），直接双击时出错会一闪而过。正确方式：在 exe 所在目录打开 **PowerShell / cmd**：

```powershell
.\Flowerie_bot-windows-x64-builtin.exe
```

## 3. 首次启动：自动生成 .env 模板

第一次运行会提示：

```text
[startup] 未检测到 .env，已生成完整配置模板：<目录>\.env（请填入占位项后重启...）
```

随后因为 `DEEPSEEK_API_KEY=sk-your-key-here` 是占位值而退出——**这是正常的**。用记事本打开同目录的 `.env`，改这两处后再次运行：

```ini
DEEPSEEK_API_KEY=sk-你的真实DeepSeekKey   # ⚠️ 必填（https://platform.deepseek.com 获取）
BOT_QQ=10001                              # ⚠️ 必填（机器人 QQ 号）
```

> 模板共 171 项、带中文说明，与 Web UI 配置页同源（见 [configuration.md](configuration.md)）；只需先填这两项。

## 4. NapCat（QQ 协议端）连接

| 项 | 默认值 |
| --- | --- |
| 反向 WS（NapCat 连入） | `127.0.0.1:3001`（`.env` 的 `WS_HOST`/`WS_PORT`） |
| HTTP API（发送回退） | `127.0.0.1:3000`（`.env` 的 `HTTP_API_BASE`） |
| WS / HTTP token | 默认都为空 → NapCat 不用带 token（设置后两边必须一致） |

- NapCat 网络配置：**启用反向 WS** → `ws://127.0.0.1:3001`。
- 只开 WS 也可以：默认 `SEND_VIA_WS=auto`（WS 优先，失败回退 HTTP）。

## 5. Web UI（管理后台）

```text
http://127.0.0.1:8080          # 本机（默认只监听 127.0.0.1）
http://<电脑局域网IP>:8080      # 手机/其他设备访问：需 .env 设 WEB_UI_ALLOW_LAN=true 并重启
```

- 首次进入注册管理员账号（用户名 + 密码）；**注册页只在系统未初始化时可用**（Bootstrap Lock，见 [security.md](security.md)）。
- 之后可管理：配置 / 人格 / 群聊知识 / 群昵称 / 插件 / 外观 / 日志 / 用户状态。

## 6. 常见问题

| 现象 | 处理 |
| --- | --- |
| 双击后窗口一闪没 | 用 PowerShell 运行（见第 2 节）看报错 |
| `DEEPSEEK_API_KEY 未配置或仍为占位值` | 编辑 `.env` 填真实 Key（模板已生成） |
| `Address already in use :3001/3000/8080` | 端口被占用：改 `.env` 的 `WS_PORT` / `HTTP_API_BASE` / `WEB_UI_PORT`，NapCat 同步改 |
| NapCat 连不上 | 看 NapCat 面板 WS 状态；token 两边一致；同机保持 `WS_HOST=127.0.0.1` |
| 群里不回复 | ① 先 `@` 测试 ② 看 `logs/bot.log` 的 `message_send_failed` ③ 确认 `.env` 的 `BOT_QQ` 与登录 QQ 一致 |
| 防火墙弹窗 | 允许访问（Web UI / WS 监听需要） |
| 数据 / 日志位置 | exe 同目录的 `data\`（SQLite / 昵称 / 规则）与 `logs\bot.log` |

## 7. 停止

运行窗口按 `Ctrl+C` 或直接关闭窗口（会优雅停机）；再次启动重复第 2 节。
