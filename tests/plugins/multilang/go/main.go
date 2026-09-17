// 最小「任意语言插件」示例：Go 实现 Plugin API v1（stdin/stdout JSON-Lines）
// 编译：go build -o plugin main.go
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
)

type request struct {
	ID     int             `json:"id"`
	Method string          `json:"method"`
	Params json.RawMessage `json:"params"`
}

func main() {
	sc := bufio.NewScanner(os.Stdin)
	sc.Buffer(make([]byte, 1024*1024), 8*1024*1024)
	out := bufio.NewWriter(os.Stdout)

	for sc.Scan() {
		var req request
		if err := json.Unmarshal(sc.Bytes(), &req); err != nil {
			continue
		}
		switch req.Method {
		case "initialize":
			fmt.Fprintf(out, "{\"id\":%d,\"result\":{\"ok\":true,\"api_version\":\"1\"}}\n", req.ID)
		case "event":
			fmt.Fprintf(out, "{\"id\":%d,\"result\":{\"actions\":[{\"type\":\"test\",\"message\":\"go-ok\"}]}}\n", req.ID)
		case "health", "shutdown":
			fmt.Fprintf(out, "{\"id\":%d,\"result\":{\"ok\":true}}\n", req.ID)
		default:
			fmt.Fprintf(out, "{\"id\":%d,\"error\":\"unknown method\"}\n", req.ID)
		}
		out.Flush()
	}
}

