# 📦 插件目录

**把插件放这里**（一个插件一个子文件夹）：

```
plugins/
├── my_plugin/
│   ├── manifest.json
│   └── plugin.py
└── hello/
    └── ...
```

## 两种安装方式

1. **推荐：Web UI 上传** → 「插件」页上传 ZIP（自动校验 + 解压到这里 + 默认禁用）
2. **手动**：整个文件夹放进本目录 → 重启 → Web UI「插件」页 → **批准权限 + 启用**

> 放进去只是「发现」（discovered），**批准权限 + 启用**才算真正上线。

## 说明

- 目录由配置 `PLUGIN_DIR` 控制（默认 `./plugins`）；**首次启动自动创建**，不存在时手动 `mkdir plugins` 也行
- 本目录（个人插件/代码）**被 git 忽略**：默认不提交你的插件到仓库（本 README 是唯一的占位文件）
- 新手看 [docs/quick-start.md](../docs/quick-start.md)；完整规则看 [docs/plugin-developer-guide.md](../docs/plugin-developer-guide.md) §22
