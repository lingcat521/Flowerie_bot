# Windows 可执行文件使用说明（.exe）

> Flowerie 官方 Release 资产（`v2.2.2`+）：`Flowerie_bot-windows-x64-builtin.exe`（Intel/AMD）
> 或 `Flowerie_bot-windows-arm64-builtin.exe`（Arm 设备 / 越狱 Android 模拟）。

## 1. 下载与解压
- 打开 [Releases](https://github.com/lingcat521/Flowerie_bot/releases) → 选版本 → Assets → 下载对应 exe
- （可选）下载 `Flowerie_bot-windows-x64-portable.zip`（含依赖的目录版，解压即用）

## 2. 运行（⚠️ 不要双击）
exe 是**控制台程序**（无图形界面），**直接双击会在报错时一闪而过**。
正确方式——在 exe 所在目录打开 **PowerShell / cmd**：

```powershell
# 方式 A（当前目录）
.\Flowerie_bot-windows-x64-builtin.exe

# 方式 B（保持日志更好看，随时 Ctrl+C 停止）
python main.py     # 仅源码环境
```

## 3. 首次启动：自动生成 .env 模板
第一次运行会提示：

```
[startup] 未检测到 .env，已生成完整配置模板：<目录>\.env（请填入占位项后重启...）
```

程序会因为 `DEEPSEEK_API_KEY=sk-your-key-here`（占位）退出——**这是正常的**。
用记事本打开同目录的 `.env`，改这两处：

```ini
DEEPSEEK_API_KEY=sk-你的真实DeepSeekKey   # ⚠️ 必填（https://platform.deepseek.com 获取）
BOT_QQ=10001                              # ⚠️ 必填（机器人 QQ 号）
```

保存后**再次运行**。

## 4. NapCat（QQ 协议端）连接
| 项 | 默认值 |
| --- | --- |
| 反向 WS（NapCat 连入） | `127.0.0.1:3001`（.env 的 `WS_PORT`）|
| HTTP API（发送） | `127.0.0.1:3000`（.env 的 `HTTP_API_BASE`）|
| WS/HTTP token | 都为空 → NapCat 不用带 token |

- NapCat 网络配置：**启用反向 WS** → 地址 `ws://127.0.0.1:3001`；或启用 HTTP → `http://127.0.0.1:3000`
- （NapCat 只开 WS 也可以：bot 默认 `SEND_VIA_WS=auto` 自动 WS 发送）

## 5. Web UI（管理后台）
```
http://127.0.0.1:8080        # 本机
http://<电脑局域网IP>:8080   # 手机/其他设备（需 .env 设 WEB_UI_ALLOW_LAN=true）
```
- 首次登录：注册管理员账号（用户名+密码）
- 之后：配置 / 人格 / 群昵称 / 日志 / 用户状态（含连通性测试）

## 6. 常见问题
| 现象 | 处理 |
| --- | --- |
| 双击后窗口一闪没 | 用 PowerShell 运行（见第 2 节）看日志 |
| `DEEPSEEK_API_KEY 未配置或仍为占位值` | 编辑 .env 填真实 key（模板已生成） |
| `Address already in use :3001/3000/8080` | 端口被占用：改 .env 的 `WS_PORT`/`HTTP_API_BASE`/`WEB_UI_PORT`，NapCat 同步改 |
| NapCat 连不上 | 检查 NapCat 面板 WS 状态；token 两边一致；`WS_HOST=127.0.0.1` 不变 |
| 群内不回复 | ① 先 @ 测试 ② 看日志 `message_send_failed` ③ 确认 .env `BOT_QQ` 与登录 QQ 一致 |
| 防火墙弹窗 | 允许“专用网络”访问（Web UI / WS 监听需要） |
| 数据/日志位置 | `.env` 同目录 `data/`（SQLite/昵称/规则）、`logs/bot.log` |

## 7. 停止
- 运行窗口按 `Ctrl+C` 或直接关闭窗口（会优雅停机）
- 再次启动：重复第 2 节

---

> 版本对应：`desktop-builtin` = 单文件版（启动稍慢但免安装）；`portable.zip` = 目录版（启动快，解压即用）。两者功能完全一致。
