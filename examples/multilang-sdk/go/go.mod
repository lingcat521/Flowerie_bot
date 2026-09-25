module minimal_go

go 1.21

require github.com/lingcat521/Flowerie_bot/sdk/go/flowerie v0.0.0

# 仓库内直接 go build 用（相对路径）。插件目录被拷到仓库外时 build.sh 会在
# .build/src/go.mod 里换成绝对路径 —— 那才是 build.sh 实际使用的模块文件。
replace github.com/lingcat521/Flowerie_bot/sdk/go/flowerie => ../../../sdk/go/flowerie
