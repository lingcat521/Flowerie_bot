# 📱 花璃 · 安卓 (Termux) 专用安装

> 当前版本 **v2.3.0**。本文是 Termux 部署的**唯一权威步骤**（[README](../README.md) 与 [Release 资产说明](install-release-guide.md) 都指向本文）。
> 安卓与 PC 的差别：`pydantic-core` 在 Termux 没有匹配 wheel（源码编译需 Rust，极易失败），必须走 Termux 专用源拿预编译包；
> `aiohttp` / `lxml` 等仍需本地用 clang 编译，耗时数分钟属正常。

## 一、基础环境

```bash
termux-change-repo        # 1) 换源（界面里选 Tsinghua 或 USTC），否则 pkg 可能连不上
pkg update && pkg upgrade -y
pkg install python git -y
termux-setup-storage      # 可选：需要读取手机存储（/sdcard）时执行并授权
```

## 二、获取代码

```bash
git clone https://github.com/lingcat521/Flowerie_bot.git
cd Flowerie_bot
```

> 也可以解压 Release 的 `Flowerie_bot-termux-source.tar.gz` 源码包（内含 `build-termux.sh`），效果相同。

## 三、安装项目依赖（关键步骤）

必须**在项目目录内**执行。整条复制：它从安卓专用源取预编译的 `pydantic-core`，避免十几分钟的源码编译。

```bash
pip install -r requirements.txt \
  -i https://termux-user-repository.github.io/pypi/ \
  --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple \
  --only-binary pydantic-core,pydantic
```

> **一键等价脚本**：`bash build-termux.sh`（`pkg install python clang rust` → 上面这条 pip → 直接 `python main.py`）。

### 报 SSL 错误（`SSL: UNEXPECTED_EOF_WHILE_READING`、`Could not fetch URL ... tuna`）

清华源 HTTPS 偶发被重置，按顺序试：

1. 补 CA 证书后重试（最常见）：`pkg install ca-certificates -y && pkg upgrade -y`
2. 换备用 PyPI 镜像（任选其一，把 `-i` 换成下面任一源，`--only-binary` 参数保持不变）：
   ```bash
   pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ \
     --extra-index-url https://termux-user-repository.github.io/pypi/ --only-binary pydantic-core,pydantic
   pip install -r requirements.txt -i https://mirrors.ustc.edu.cn/pypi/simple/ \
     --extra-index-url https://termux-user-repository.github.io/pypi/ --only-binary pydantic-core,pydantic
   pip install -r requirements.txt -i https://pypi.org/simple/ \
     --extra-index-url https://termux-user-repository.github.io/pypi/ --only-binary pydantic-core,pydantic
   ```
3. HTTPS 握手持续被重置时，用 http + `--trusted-host` 绕过 TLS：
   ```bash
   pip install -r requirements.txt -i http://pypi.tuna.tsinghua.edu.cn/simple \
     --extra-index-url https://termux-user-repository.github.io/pypi/ \
     --trusted-host pypi.tuna.tsinghua.edu.cn --only-binary pydantic-core,pydantic
   ```

### 报 `Please make sure the libxml2 and libxslt development packages are installed`

这是 `lxml`（`python-docx` 的依赖）缺 C 库：`pkg install python-yaml clang binutils rust libxml2 libxslt -y`，装完重跑第三节的 pip 命令。

### 仍因网络问题失败（GitHub 超时等）

```bash
pkg install python-yaml clang binutils rust -y
pip install --upgrade pip
pip install -r requirements.txt        # 直接源码编译，约 10~20 分钟
```

## 四、运行

```bash
python main.py
```

首次运行会在项目根**自动生成 `.env` 完整配置模板**（171 项，带中文说明），然后因为
`DEEPSEEK_API_KEY` 仍是占位值 `sk-your-key-here` 而退出——**这是正常的**。编辑 `.env` 填两项后重启：

```ini
DEEPSEEK_API_KEY=sk-你的真实Key
BOT_QQ=你的机器人QQ号
```

```bash
python main.py          # 再次运行即正常启动
```

**后台常驻（防锁屏断连）**：

```bash
termux-wake-lock && nohup bash run.sh >/dev/null 2>&1 &   # run.sh = 崩溃自动重启的守护脚本
# 或：pkg install tmux && tmux new -s flowerie 'python main.py'
```

## 五、NapCat（QQ 协议端）与 Web UI

- NapCat 建议**同机运行**：反向 WS 填 `ws://127.0.0.1:3001`（默认 `WS_HOST`/`WS_PORT`）。
- NapCat 在另一台设备时：`.env` 把 `WS_HOST=127.0.0.1` 改成那台设备 IP，并在防火墙放行 3001。
- Web UI 默认 `http://127.0.0.1:8080/panel`（首次进注册页创建管理员）。

## 六、排查

| 现象 | 处理 |
| :--- | :--- |
| 装依赖卡在编译 / `pydantic-core` 报 Rust 错误 | 确认用了第三节的 `--only-binary pydantic-core,pydantic` 与 Termux 专用源 |
| SSL / `Could not fetch URL` / `lxml` 编译失败 | 见第三节三个子小节（证书 → 换镜像 → `libxml2 libxslt`） |
| 启动即退出并提示 Key 占位 | 正常流程：编辑 `.env` 的 `DEEPSEEK_API_KEY` / `BOT_QQ` 后重启 |
| 端口占用（3001 / 3000 / 8080） | 改 `.env` 对应端口，NapCat 同步改；Web UI 端口不能与 `WS_PORT` 相同 |
| 群里不回复 | 先 `@` 测试，再看 `logs/bot.log` 的 `message_send_failed` |

> 其余配置项、Web UI、插件与安全说明见 [配置说明](configuration.md) 与 [文档中心](README.md)。

---

[← 返回 README](../README.md)
