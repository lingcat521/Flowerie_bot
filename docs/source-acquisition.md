# 源码获取状态（Source Acquisition）

> 任务书 §二-A/§20 要求：为每个客户端维护获取状态；**拿不到源码必须如实标注**，禁止用「模型记忆」或别的客户端实现代替。本文件记录本轮实际执行的获取动作与结果（核对时间 2026-09-25，2026-09-26 复核 HEAD）。
> 获取方式：`git clone --depth 1`（浅克隆，不拉历史），失败重试 2 次后记录原因。本地目录 `~/proto_src/`（工作区之外，不进入仓库）。

## 汇总（HEAD 为本地实测值）

| 项目 | 仓库 | 本地目录 | HEAD | 体积 | 文件数 | 状态 |
| :--- | :--- | :--- | :--- | ---: | ---: | :--- |
| NapCatQQ | NapNeko/NapCatQQ | `NapCatQQ` | `0b4cfe6` | 46M | 1020 | **SOURCE_OBTAINED**（已逆向）|
| SnowLuma | SnowLuma/SnowLuma | `SnowLuma` | `fe245d8` | 46M | 1103 | **SOURCE_OBTAINED**（未调查）|
| Lagrange.Core | LagrangeDev/Lagrange.Core | `Lagrange.Core` | `20c2ba0` | 4.9M | 730 | **SOURCE_OBTAINED**（Milky 面已逆向）|
| LagrangeV2 | LagrangeDev/LagrangeV2 | `LagrangeV2` | `7011cdf` | 4.7M | 672 | **SOURCE_OBTAINED**（Milky 面已逆向）|
| Lagrange.Milky（实现）| **内嵌于** Lagrange.Core / LagrangeV2 的 `Lagrange.Milky/` | 同上 | 同上 | — | 119 .cs | **SOURCE_OBTAINED（内嵌，非独立仓库）** |
| Lagrange.Milky.Document | LagrangeDev/Lagrange.Milky.Document | `Milky-doc` | `98e96e5` | 318K | 18 | **DOCUMENTATION_ONLY** |
| LLBot | LLOneBot/LuckyLilliaBot | `LLBot` | `9f374f6` | 129M | 1086 | **SOURCE_OBTAINED**（已逆向）|
| NoneBot2 | nonebot/nonebot2 | `NoneBot2` | `4510ce2` | 8.9M | 657 | **SOURCE_OBTAINED**（未调查）|
| NoneBot2 OneBot 适配器 | nonebot/adapter-onebot | `adapter-onebot` | `58bb487` | 1.6M | 83 | **SOURCE_OBTAINED**（未调查）|
| OneBot 11 规范 | botuniverse/onebot-11 | `OneBot11-spec` | `d4456ee` | 267K | 21 | **SOURCE_OBTAINED** |
| Milky 协议规范 | SaltifyDev/milky（`protocol/src/ir/api/*.ts`）| `Milky-spec` | `151dd90` | 1.2M | 86 | **SOURCE_OBTAINED**（第 2 次尝试成功）|
| go-cqhttp | Mrs4s/go-cqhttp | `go-cqhttp` | `a5923f1` | 1.5M | 121 | **SOURCE_OBTAINED**（已逆向）|
| Kovi | ThriceCola/Kovi | `Kovi` | `9decea5` | 1.1M | 114 | **SOURCE_OBTAINED**（未调查）|
| Koishi | koishijs/koishi | `Koishi` | `5525cfd` | 1.4M | 186 | **SOURCE_OBTAINED**（未调查）|
| milky-python-sdk | notnotype/milky-python-sdk | `milky-python-sdk` | `805b194` | 1.5M | 182 | **SOURCE_OBTAINED**（未调查）|
| ROneBot | RTAkland/ROneBot | `ROneBot` | `b39550f` | 2.7M | 368 | **SOURCE_OBTAINED**（未调查）|
| OneBot 12 规范 | botuniverse/onebot（`specs/`）| `onebot` | `d533f0f` | — | — | **SOURCE_OBTAINED**（第 4 次尝试；前 3 个候选仓库 ls-remote 失败）|
| Lagrange.Doc | LagrangeDev/Lagrange.Doc | `Lagrange.Doc` | `3a76e60` | — | — | **DOCUMENTATION_ONLY**（官方文档，页面自称过时；HEAD 见 C5 更正）|
| Lagrange.OneBot | LagrangeDev/Lagrange.OneBot | —— | —— | — | — | **SOURCE_UNAVAILABLE**（HTTP 404，见 C4）|
| OpenShamrock | whitechi73/OpenShamrock | —— | —— | — | — | **SOURCE_UNAVAILABLE**（账号与仓库均不存在，见下）|

**源码区累计 17 个仓库**（表内 `——` 三行不是克隆：内嵌实现与两个不可得仓库）；第一批 10 + 第二批 5 + 第三批 1（OneBot 12 规范）+ 第四批 1（Lagrange.Doc）。获取总量约 361M（第一批口径）。

## 失败与异常（如实记录）

### 1. Lagrange.Milky 独立仓库不存在 —— 但实现源码已取得（状态更正）

```text
git ls-remote --heads https://github.com/LagrangeDev/Lagrange.Milky.git
→ fatal: could not read Username for https://github.com: No such device or address   (exit 128)
```

该组织公开仓库列表中也没有名为 Lagrange.Milky 的仓库（只有 Lagrange.Milky.Document）。**原判定**「AUTH_REQUIRED / 仓库不存在 → 实现层源码无法获取」**已更正**：实现内嵌在 `Lagrange.Core` 与 `LagrangeV2` 的 `Lagrange.Milky/`（119 个 .cs，含 Api/Handler、Segment、Event；两份副本布局不同，见 protocol-reverse-engineering.md §6.1）→ 状态为 **SOURCE_OBTAINED（内嵌）**。教训：找不到同名独立仓库 ≠ 没有实现源码，应在同名组织的主仓库里搜关键词（`git ls-files | grep -i milky` 命中 128 个文件）；但独立仓库不存在这点仍如实保留。

### 2. 首次获取脚本自身失败（不是网络问题）

第一次运行把 git 的错误输出重定向到 `/tmp/...`，而**本环境没有 `/tmp`** → 重定向失败、`git` 根本没被执行，脚本把 9 个项目全报成 `SOURCE_UNAVAILABLE`。**这是脚本 bug，不是网络失败**，已改为写入 `$HOME/clone_errors/` 后重跑；记录在此以免被误读为「网络不可用」。

### 3. Milky-spec 首次 clone 失败（临时网络错误）

`fatal: unable to access https://github.com/SaltifyDev/milky.git/: Recv failure: Software caused connection abort` —— 第二次重试成功（`151dd90`），属临时 `NETWORK_FAILED`（已恢复）。

### 4. OpenShamrock：两轮尝试，上游账号与仓库均已不存在

| 动作 | 结果 |
| :--- | :--- |
| `git clone / ls-remote whitechi73/OpenShamrock` | `fatal: could not read Username`（未克隆成功）|
| `git ls-remote OpenShamrock/OpenShamrock` | 同上 |
| `GET /repos/whitechi73/OpenShamrock`（带 token）| **HTTP 404** |
| `GET /repos/whitechi73/OpenShamrock/releases`（带 token）| HTTP 404 |
| `GET /users/whitechi73`（带 token）| 404 Not Found |
| `GET /search/repositories?q=OpenShamrock in:name` | 仅第三方分支（★0-4，共 5 个）|

**结论**：不是鉴权问题 —— **上游账号与仓库均已不存在**。状态保持 `SOURCE_UNAVAILABLE`，Android 端 OneBot11 的字段差异继续标 `[UNKNOWN]`，不做任何声称（任务书 §20/§22）。

## 未执行的动作（明确声明）

- **没有运行任何第三方构建/安装脚本**（任务书 §17）：NapCat 的构建链、LLBot 的 npm 脚本、SnowLuma/Lagrange 的构建链一律**只做静态阅读**；
- 没有执行任何下载来的二进制；没有为获取源码修改系统权限，没有读取任何凭据或 SSH key；没有使用第三方镜像（官方仓库均可用）。

## C4. Lagrange.OneBot 的实现源码**不可得** —— 此前文档写错了

此前 [client-compatibility.md](client-compatibility.md) §6.1 写的是「Lagrange.OneBot | C# | **SOURCE_OBTAINED**（同 Lagrange.Core 仓库）| 与 Lagrange.Core 同源」。本轮按任务书 §三「不得假装已经调查」复核，**这条是错的**，可复现证据：

```text
$ curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOKEN" https://api.github.com/repos/LagrangeDev/Lagrange.OneBot
404                                   # 仓库已不存在（含改名/删除）
$ curl -s -H "Authorization: Bearer $TOKEN" 'https://api.github.com/orgs/LagrangeDev/repos?per_page=100' | jq -r '.[].name'
Lagrange.Core / LagrangeV2(archived) / Lagrange.Milky.Document / Lagrange.Kritor / lagrangejs / lagrange-python / LagrangeGo / lagrange-kotlin / Lagrange.Cpp / …
# 清单里没有任何 OneBot 11 实现仓库
$ grep -ril onebot ~/proto_src/Lagrange.Core/ ~/proto_src/LagrangeV2/ --include='*.cs'
Lagrange.Core/Lagrange.Core.Runner/QrCodeHelper.cs      # 无关命中（注释）
LagrangeV2/Lagrange.Core.Runner/QrCodeHelper.cs         # 无关命中
$ git clone --depth 1 https://github.com/LagrangeDev/Lagrange.OneBot.git
fatal: could not read Username for 'https://github.com'   # 404 → git 要求凭据
```

GitHub 搜索 `Lagrange.OneBot in:name` 只有 2 个仓库：`HornCopper/Lagrange-Python.OneBot`（第三方 Python 实现）与 `LagrangeDev/Lagrange.OneBot.DatabaseShift`（数据库迁移工具，非协议实现）。**结论**：Lagrange.OneBot 的 OneBot 11 实现 = `SOURCE_UNAVAILABLE`（截至 2026-09-25）；本地 `Lagrange.Core` / `LagrangeV2` 只能证明 **Lagrange.Milky** 侧（内嵌实现），**不能**用来证明 Lagrange 的 OneBot 11 行为 —— 二者是不同协议面。因此兼容矩阵的 Lagrange（OneBot 11）列**只能**由 `[DOC]` 支撑，且必须标明 DOC。

## C5. 补充获取：`Lagrange.Doc`（官方文档仓库）＝ 仅 `[DOC]`（含 HEAD 更正）

```text
$ git clone --depth 1 https://github.com/LagrangeDev/Lagrange.Doc.git   # 成功
```

| 项 | 值 |
| :--- | :--- |
| HEAD（**2026-09-26 实测更正**）| `3a76e60` —— 本文原写 `98e96e5`（"与 Lagrange.Milky.Document 同源同提交"）**是错的**：`98e96e5` 是 `Milky-doc` 的 HEAD，两个仓库不同提交 |
| 内容 | `docs/v1/Lagrange.OneBot/{API,Segment,Config,AutoUpdate}/` 与 `docs/v1/Lagrange.Milky/` |
| 可用性**限制**（文档自己写的）| 「此文档已经过时, 请参阅 Apifox 上的 Lagrange.OneBot 文档」→ 页面只是**目录 + 指向规范**，正文很少 |
| 能给什么 | `Segment/Extend/index.md` 的 **File / Folder / Node** 字段表（字段名与类型）＝ `[DOC]` |
| 不能给什么 | 具体 JSON 构造、字段可选性、null 行为、Action 参数校验 —— 这些**必须**源码或实机，当前两者都没有 → 记 `UNKNOWN` |

## C6. 复现（重跑获取）

```bash
ls ~/proto_src                       # 应列出 17 个目录
bash ~/clone_sources.sh              # 原始获取脚本（写入 $HOME/clone_errors/ 记录失败原因）
cd ~/proto_src && for d in */; do echo "$d $(git -C "$d" rev-parse --short HEAD)"; done   # 复核本表 HEAD
```

> 获取方式与既有一致：`git clone --depth 1` 到 `~/proto_src/`（工作区之外，不入仓库）。本轮没有用任何"模型记忆"补 Lagrange.OneBot 的字段 —— 拿不到就是拿不到。

