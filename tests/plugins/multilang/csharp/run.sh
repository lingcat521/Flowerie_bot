#!/bin/sh
# C# 插件的入口包装：dotnet 项目不是可执行文件，用脚本把 entry 变成"能直接跑的东西"
exec dotnet run --project "$(dirname "$0")" --nologo -v quiet
