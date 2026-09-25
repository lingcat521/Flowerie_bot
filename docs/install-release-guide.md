# 其他平台构建产物使用说明（Linux / macOS / Termux）

> Windows exe 见 [install-release-windows.md](install-release-windows.md)。
> 官方 Release 资产（**v2.2.2 起每个版本都齐套**，最新为 `v2.2.6`）包含各平台：
> `builtin`（单文件）/ `portable.zip`（目录版，解压即用）；Termux 走源码包。

---

## 一、Linux（x64 / arm64）

### 资产
| 文件 | 说明 |
| --- | --- |
| `Flowerie_bot-linux-x64-builtin` / `linux-arm64-builtin` | 单文件（无依赖，直接跑）|
| `Flowerie_bot-linux-*-portable.zip` | 目录版（解压即用）|

### 运行
```bash
# 单文件版
chmod +x Flowerie_bot-linux-x64-builtin
./Flowerie_bot-linux-x64-builtin

# 目录版
unzip Flowerie_bot-linux-x64-portable.zip && cd Flowerie_bot-linux-x64-portable
./Flowerie_bot-linux-x64-portable
```

### 首次启动
自动在**当前目录**生成 `.env` 完整模板 → 编辑两个必填项：
```ini
DEEPSEEK_API_KEY=sk-你的真实Key
BOT_QQ=你的机器人QQ号
```
改完再运行。

### 注（构建信息）
- 在 **glibc** 发行版（Ubuntu/Debian/CentOS）上构建；**Alpine 等 musl 发行版可能不兼容**——用源码方式跑（见 Termux 一节的 `pip install` 思路）
- 若无 systemd，可用 `nohup ./Flowerie_bot-linux-x64-builtin &` 后台运行（日志在 `logs/bot.log`）

---

## 二、macOS（arm64 / Apple Silicon）

### 资产
- `Flowerie_bot-macos-arm64-builtin` / `macos-arm64-portable.zip`

### 运行
```bash
# 首次：解除 quarantine（否则 macOS 阻止运行）
xattr -d com.apple.quarantine Flowerie_bot-macos-arm64-builtin

# 运行
chmod +x Flowerie_bot-macos-arm64-builtin
./Flowerie_bot-macos-arm64-builtin
```

### 首次启动
同上：同目录生成 `.env` 模板 → 填 `DEEPSEEK_API_KEY` / `BOT_QQ` → 重启。

> ⚠️ **Intel Mac（x64）**：官方资产**只提供 arm64 构建**（历代如此）——请用源码运行（克隆仓库 → `pip install -r requirements.txt` → `python main.py`）。
> 若遇到“已损坏/无法打开”提示：`xattr -d com.apple.quarantine <文件>` 后重试。

---

## 三、Termux（Android）

### 资产与约定
- `Flowerie_bot-termux-source.tar.gz` —— **源码包**（含 `build-termux.sh`）：GitHub 跑不了 Android，**必须在你手机 Termux 内构建**（这本来就是正确姿势）。

### 安装
```bash
pkg update && pkg install python git
git clone https://github.com/lingcat521/Flowerie_bot.git   # 或解压上面的源码包
cd Flowerie_bot && bash build-termux.sh                      # 一键构建（自动装依赖 + 配好 Termux 用户仓库源）
python main.py                                               # 首次运行自动生成 .env 模板
```
> 手写 pip 依赖（镜像源怎么选、`pydantic-core` 预编译包、SSL 重置与 `lxml` 编译报错排查）
> 见专用文档 **[Termux 专用安装](install-termux.md)** —— **部署细节以那份为准**，本节只保留与 Release 资产相关的约定。

### NapCat（Android 端）
- NapCat 建议**同机运行**：反向 WS → `ws://127.0.0.1:3001`（Termux 与 App 同机网络互通）
- 换设备跑 NapCat：.env 里 `WS_HOST=127.0.0.1` 改为 NapCat 设备 IP，并在防火墙放行

### 常驻后台（免锁屏断连）
```bash
# 方式 A：tmux
pkg install tmux && tmux new -s flowerie 'python main.py'
# 方式 B：Termux:Boot + termux-wake-lock
termux-wake-lock
./run.sh
```

---

## 四、通用首次配置（所有平台一致）
1. **.env 模板**已自动生成（`DEEPSEEK_API_KEY` 占位 → 填真实值；`BOT_QQ` 必填）
2. **NapCat**：WS `127.0.0.1:3001`（或 .env 改）→ 面板显示“已连接”
3. **Web UI**：`http://127.0.0.1:8080` 注册管理员 → 配置/人格/群昵称/日志/连通性测试
4. **测试**：群里 `@花璃` → 必回；发图可识别（`VISION_ENABLED` 可关）

## 五、常见问题（跨平台）
| 现象 | 处理 |
| --- | --- |
| 闪退/报错看不清 | 终端运行看日志；错误信息会提示（如占位 key）|
| 端口占用（3001/8080/3000）| 编辑 .env 端口 + NapCat 同步；Web UI 改 `WEB_UI_PORT` |
| NapCat 连不上 | token 两边一致；WS_HOST 用 127.0.0.1（同机）|
| 群里不回复 | 先 @ 测试 → 看 `logs/bot.log` 的 `message_send_failed` |
| 数据目录 | 运行目录下 `data/`（SQLite/昵称/规则）与 `logs/` |

> 各平台**功能完全一致**（同一份 Python 源码 + PyInstaller 打包）；差异只在启动方式与少数系统兼容点。
