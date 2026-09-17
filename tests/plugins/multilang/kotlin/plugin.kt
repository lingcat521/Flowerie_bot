// 最小「任意语言插件」示例：Kotlin 实现 Plugin API v1（stdin/stdout JSON-Lines）
// 编译：kotlinc plugin.kt -include-runtime -d plugin.jar   入口：run.sh（exec java -jar plugin.jar）
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.PrintWriter

val ID_RE = Regex("\"id\":\\s*([0-9]+)")
val METHOD_RE = Regex("\"method\":\\s*\"([a-z_]+)\"")

fun main() {
    val input = BufferedReader(InputStreamReader(System.`in`))
    val out = PrintWriter(System.out, true)
    while (true) {
        val line = input.readLine() ?: break
        val id = ID_RE.find(line)?.groupValues?.get(1) ?: continue
        val method = METHOD_RE.find(line)?.groupValues?.get(1) ?: ""
        when (method) {
            "initialize" -> out.println("{"id":$id,"result":{"ok":true,"api_version":"1"}}")
            "event" -> out.println("{"id":$id,"result":{"actions":[{"type":"test","message":"kotlin-ok"}]}}")
            "health", "shutdown" -> out.println("{"id":$id,"result":{"ok":true}}")
            else -> out.println("{"id":$id,"error":"unknown method"}")
        }
    }
}

