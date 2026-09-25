# 源码获取状态（Source Acquisition）

> 任务书 §二-A/§20 要求：为每个客户端维护获取状态；**拿不到源码必须如实标注**，
> 禁止用「模型记忆」或别的客户端实现代替。本文件记录本轮实际执行的获取动作与结果。

获取方式：`git clone --depth 1`（浅克隆，不拉历史），失败重试 2 次后记录原因。
本地目录：`~/proto_src/`（工作区之外，不进入仓库）。获取时间：2026-09-25。

## 汇总

| 项目 | 仓库 | HEAD | 体积 | 文件数 | 状态 |
| :--- | :--- | :--- | ---: | ---: | :--- |
| NapCatQQ | NapNeko/NapCatQQ | `0b4cfe6` | 46M | 1020 | **SOURCE_OBTAINED** |
| SnowLuma | SnowLuma/SnowLuma | `fe245d8` | 46M | 1103 | **SOURCE_OBTAINED** |
| Lagrange.Core | LagrangeDev/Lagrange.Core | `20c2ba0` | 4.9M | 730 | **SOURCE_OBTAINED** |
| LagrangeV2 | LagrangeDev/LagrangeV2 | `7011cdf` | 4.7M | 672 | **SOURCE_OBTAINED** |
| Lagrange.Milky（实现） | **内嵌于 Lagrange.Core / LagrangeV2 的 `Lagrange.Milky/`** | 同左 | 119 .cs | — | **SOURCE_OBTAINED（实现内嵌，非独立仓库）** |
| Lagrange.Milky（文档） | LagrangeDev/Lagrange.Milky.Document | `98e96e5` | 318K | 18 | **DOCUMENTATION_ONLY** |
| LLBot | LLOneBot/LuckyLilliaBot | `9f374f6` | 129M | 1086 | **SOURCE_OBTAINED** |
| NoneBot2 | nonebot/nonebot2 | `4510ce2` | 8.9M | 657 | **SOURCE_OBTAINED** |
| NoneBot2 OneBot 适配器 | nonebot/adapter-onebot | `58bb487` | 1.6M | 83 | **SOURCE_OBTAINED** |
| OneBot 11 规范 | botuniverse/onebot-11 | `d4456ee` | 267K | 21 | **SOURCE_OBTAINED** |
| Milky 协议规范 | SaltifyDev/milky（protocol/src/ir/api/*.ts） | `151dd90` | 1.2M | 86 | **SOURCE_OBTAINED**（第 2 次尝试成功） |

总计 361M；磁盘余量：获取前 9.0G（106G 已用）。

## 失败与异常（如实记录）

### 1. Lagrange.Milky 实现仓库

```
git ls-remote --heads https://github.com/LagrangeDev/Lagrange.Milky.git
→ fatal: could not read Username for https://github.com: No such device or address   (exit 128)
```

- 该组织公开仓库列表中也不存在名为 Lagrange.Milky 的仓库（只有 Lagrange.Milky.Document）。
- **判定：AUTH_REQUIRED / 仓库不存在** → 实现层源码无法获取。
- **影响**：Milky 侧结论只能基于 **协议规范（SaltifyDev/milky 的 protocol 定义）+ 官方文档**，
  证据等级为 [DOC]，**不能**标成 [CODE]，也不能声称「已逆向 Lagrange.Milky 实现」。
- 若后续发现实现仓库真实地址（例如并入 LagrangeV2），再补状态。

### 2. 首次获取脚本自身失败（不是网络问题）

第一次运行把 git 的错误输出重定向到 `/tmp/...`，而**本环境没有 `/tmp`** → 重定向失败、
`git` 根本没被执行，脚本把 9 个项目全报成 `SOURCE_UNAVAILABLE`。
- **这是脚本 bug，不是网络失败**，已改为写入 `$HOME/clone_errors/` 后重跑；
- 记录在此，以免被误读为「网络不可用」。

### 3. Milky-spec 首次 clone 失败

```
fatal: unable to access https://github.com/SaltifyDev/milky.git/: Recv failure: Software caused connection abort
```

第二次重试成功（`151dd90`）→ 属临时网络错误 NETWORK_FAILED（已恢复）。

## 未执行的动作（明确声明）

- **没有运行任何第三方构建/安装脚本**（任务书 §17）：NapCat 的构建链、LLBot 的 npm 脚本、
  SnowLuma/Lagrange 的构建链一律**只做静态阅读**；
- 没有执行任何下载来的二进制；
- 没有为获取源码修改系统权限，没有读取任何凭据或 SSH key；
- 没有使用第三方镜像（官方仓库均可用）。

## 状态更正（第二轮）

LagrangeDev/Lagrange.Milky 这个**独立仓库**确实不存在（ls-remote exit 128），但 **Milky 的实现源码并非不可得**：
它内嵌在 Lagrange.Core 与 LagrangeV2 的 Lagrange.Milky/ 目录（119 个 .cs 文件，含 Api/Handler、Segment、Event；两份副本布局不同，见 protocol-reverse-engineering.md §6.1）。

- 更正前：AUTH_REQUIRED / 仓库不存在 → 会让人误以为 Milky 实现层没有源码；
- 更正后：**SOURCE_OBTAINED（内嵌）**，证据已记入 protocol-reverse-engineering.md §6；
- 教训：找不到同名独立仓库 ≠ 没有实现源码；应在同名组织的主仓库里搜关键词（本次 git ls-files | grep -i milky 命中 128 个文件）。

## 第二批（生态清单触发的补充获取）

| 项目 | 仓库 | HEAD | 体积 | 文件数 | 状态 |
| :--- | :--- | :--- | ---: | ---: | :--- |
| go-cqhttp | Mrs4s/go-cqhttp | a5923f1 | 1.5M | 121 | **SOURCE_OBTAINED** |
| Kovi | ThriceCola/Kovi | 9decea5 | 1.1M | 114 | **SOURCE_OBTAINED** |
| Koishi | koishijs/koishi | 5525cfd | 1.4M | 186 | **SOURCE_OBTAINED** |
| milky-python-sdk | notnotype/milky-python-sdk | 805b194 | 1.5M | 182 | **SOURCE_OBTAINED** |
| ROneBot | RTAkland/ROneBot | b39550f | 2.7M | 368 | **SOURCE_OBTAINED** |
| OpenShamrock | whitechi73/OpenShamrock | — | — | — | **SOURCE_UNAVAILABLE（原仓库不可得）** |

OpenShamrock 失败详情：

```
git clone https://github.com/whitechi73/OpenShamrock.git
→ fatal: could not read Username for https://github.com: No such device or address
```

仓库搜索（OpenShamrock in:name）只剩第三方分支/适配（★0-4），未找到官方仓库。
**影响**：安卓端 OneBot11 的字段差异在本任务中属于 [UNKNOWN]，不做任何声称。

源码区累计：15 个仓库 / 369M。
