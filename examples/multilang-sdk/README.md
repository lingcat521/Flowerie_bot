# 多语言 SDK 最小化插件（任务书《插件测试》）

每种语言一个极简插件，**只依赖该语言 SDK**，用来证明「开发者真的可以用这个 SDK 写出一个能运行的插件」。

| 语言 | 目录 | 插件 id | 构建 | 入口 |
| :--- | :--- | :--- | :--- | :--- |
| Python | `python/` | `minimal_py` | 无需构建（仓库自带 runner）| `plugin.py` |
| TypeScript | `typescript/` | `minimal_ts` | `build.sh`（node≥22.6 直接跑 TS，否则 tsc + shim）| `run.sh` |
| Go | `go/` | `minimal_go` | `build.sh`（临时模块 + `go build`，`GOPROXY=off` 证明零第三方依赖）| `run.sh` |
| Rust | `rust/` | `minimal_rust` | `build.sh`（`rustc --edition 2021 -O`）| `run.sh` |
| Java | `java/` | `minimal_java` | `build.sh`（`javac` SDK + 插件）| `run.sh` |

- 契约（暴露哪些方法、`/sdk@<自己>` 命令、动作形状、错误探针）：`docs/plugin-sdk-minimal-test.md`
- 实测入口：`tests/sdk/`（真仓库 + 真引擎公开面 + 真插件进程；Build 与 Load 分开验证）
- 任务书里的 `plugin.call("minimal.go", …)` 在本仓库写作 `plugin.call("minimal_go", …)`
  （插件 id 只允许小写字母/数字/下划线/短横线）。

```bash
# 单独构建 / 单独运行（不经引擎）
cd examples/multilang-sdk/go && sh build.sh && sh run.sh
# 跑实测（本机缺工具链的语言会 skip 并打印原因，CI 上五种语言全跑）
pytest -q -s tests/sdk/
```

> Go 目录不在仓库里保留 `go.mod`：`build.sh` 在 `.build/src` 生成临时模块（绝对路径 replace SDK），
> 这样插件目录可以整体拷到任意位置构建，也不会给仓库引入新的 Go 依赖图。
