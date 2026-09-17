// 最小「任意语言插件」示例：TypeScript 实现 Plugin API v1（stdin/stdout JSON-Lines）
// 编译：tsc plugin.ts --target es2019 --module commonjs   -> plugin.js
// 入口：plugin.js（用 node 跑；发布时把编译产物一起打进 ZIP 即可）
import * as readline from "readline";

const ID_RE = /"id":\s*(\d+)/;
const METHOD_RE = /"method":\s*"([a-z_]+)"/;

const rl = readline.createInterface({ input: process.stdin, terminal: false });
rl.on("line", (line: string) => {
  const idm = ID_RE.exec(line);
  if (!idm) return;
  const id = idm[1];
  const mm = METHOD_RE.exec(line);
  const method = mm ? mm[1] : "";
  let payload: string;
  switch (method) {
    case "initialize":
      payload = `{"id":${id},"result":{"ok":true,"api_version":"1"}}`;
      break;
    case "event":
      payload = `{"id":${id},"result":{"actions":[{"type":"test","message":"typescript-ok"}]}}`;
      break;
    case "health":
    case "shutdown":
      payload = `{"id":${id},"result":{"ok":true}}`;
      break;
    default:
      payload = `{"id":${id},"error":"unknown method"}`;
  }
  process.stdout.write(payload + "
");
});

