# 其他平台构建产物使用说明（Linux / macOS / Termux）

> 当前版本 **v2.3.0**；Windows exe 见 [install-release-windows.md](install-release-windows.md)，Termux 部署细节见 [install-termux.md](install-termux.md)。
> 官方 Release 每个版本都提供下列资产（由 `.github/workflows/compiler.yml` 在 release 创建时构建上传）：
> `Flowerie_bot-<platform>-<arch>-builtin`（单文件）/ `Flowerie_bot-<platform>-<arch>-portable.zip`（目录版，解压即用）；
> Termux 走源码包 `Flowerie_bot-termux-source.tar.gz`。

## 一、Linux（x64 / arm64）

| 文件 | 说明 |
| --- | --- |
| `Flowerie_bot-linux-x64-builtin` / `Flowerie_bot-linux-arm64-builtin` | 单文件（免安装依赖，直接跑） |
| `Flowerie_bot-linux-x64-portable.zip` / `-linux-arm64-portable.zip` | 目录版（解压即用） |

```bash
# 单文件版
chmod +x Flowerie_bot-linux-x64-builtin
./Flowerie_bot-linux-x64-builtin

# 目录版
unzip Flowerie_bot-linux-x64-portable.zip && cd Flowerie_bot-linux-x64-portable
./Flowerie_bot-linux-x64-portable
```

首次启动会在**当前目录**自动生成 `.env` 完整模板（171 项），改完两个必填项再运行：

```ini
DEEPSEEK_API_KEY=sk-你的真实Key
BOT_QQ=你的机器人QQ号
```

> - 构建在 **glibc** 发行版（Ubuntu 等）上完成；**Alpine 等 musl 发行版可能不兼容** —— 改用源码方式跑（依赖装法见 [install-termux.md](install-termux.md) 第三节的镜像思路）。
> - 无 systemd 时后台运行：`nohup ./Flowerie_bot-linux-x64-builtin &`（日志在 `logs/bot.log`）。

## 二、macOS（arm64 / Apple Silicon）

| 文件 | 说明 |
| --- | --- |
| `Flowerie_bot-macos-arm64-builtin` | 单文件 |
| `Flowerie_bot-macos-arm64-portable.zip` | 目录版 |

```bash
xattr -d com.apple.quarantine Flowerie_bot-macos-arm64-builtin   # 首次：解除 quarantine，否则被系统阻止
chmod +x Flowerie_bot-macos-arm64-builtin
./Flowerie_bot-macos-arm64-builtin
```

首次启动同上：同目录生成 `.env` 模板 → 填 `DEEPSEEK_API_KEY` / `BOT_QQ` → 再运行。

> ⚠️ **Intel Mac（x64）没有官方资产**（矩阵只构建 arm64）：请用源码运行 —— 克隆仓库 → `pip install -r requirements.txt` → `python main.py`。
> 遇到「已损坏 / 无法打开」先 `xattr -d com.apple.quarantine <文件>` 再试。

## 三、Termux（Android）

| 资产 | 说明 |
| --- | --- |
| `Flowerie_bot-termux-source.tar.gz` | 源码包（含 `build-termux.sh`）。GitHub runner 跑不了 Android，**必须在手机 Termux 内构建** |

```bash
pkg update && pkg install python git -y
git clone https://github.com/lingcat521/Flowerie_bot.git    # 或解压上面的源码包
cd Flowerie_bot && bash build-termux.sh                      # 一键：装 clang/rust + 依赖（Termux 专用源）+ 启动
```

> 镜像源怎么选、`pydantic-core` 预编译包、SSL 重置与 `lxml` 编译报错的排查，**以 [Termux 专用安装](install-termux.md) 为准**（本文只留 Release 资产相关约定）。
> NapCat 建议同机运行（反向 WS `ws://127.0.0.1:3001`）；常驻后台用 `termux-wake-lock` + `./run.sh`。

## 四、通用首次配置（所有平台一致）

1. **`.env`**：首次运行自动生成完整模板；只改 `DEEPSEEK_API_KEY`（占位值会导致启动即退出，属正常）与 `BOT_QQ` 两个必填项。
2. **NapCat**：反向 WS 指向 `127.0.0.1:3001`（`.env` 的 `WS_PORT`）→ Web UI 显示「已连接」。
3. **Web UI**：`http://127.0.0.1:8080/panel` 注册管理员 → 配置 / 人格 / 群昵称 / 日志 / 用户状态。
4. **自测**：群里 `@花璃` 必回；发图可识别（`VISION_ENABLED` 可关）。

## 五、常见问题（跨平台）

| 现象 | 处理 |
| --- | --- |
| 闪退 / 报错看不清 | 在终端运行看输出；启动校验会直接指出问题（如 Key 仍为占位值） |
| 端口占用（3001 / 3000 / 8080） | 编辑 `.env` 改 `WS_PORT` / `HTTP_API_BASE` / `WEB_UI_PORT`，NapCat 同步改（`WEB_UI_PORT` 不能等于 `WS_PORT`） |
| NapCat 连不上 | 两边 token 一致；同机时 `WS_HOST=127.0.0.1` |
| 群里不回复 | 先 `@` 测试 → 看 `logs/bot.log` 的 `message_send_failed` |
| 数据在哪 | 运行目录下 `data/`（SQLite / 昵称 / 规则）与 `logs/` |

> 各平台功能完全一致（同一份 Python 源码 + PyInstaller 打包），差异只在启动方式与少量系统兼容点。
