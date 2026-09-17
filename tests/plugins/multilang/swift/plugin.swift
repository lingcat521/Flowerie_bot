// 最小「任意语言插件」示例：Swift 实现 Plugin API v1（stdin/stdout JSON-Lines）
// 编译：swiftc -O -o plugin plugin.swift
import Foundation

func extractId(_ line: String) -> String? {
    guard let r = line.range(of: "\"id\":") else { return nil }
    let rest = line[r.upperBound...].drop { $0 == " " }
    let digits = rest.prefix { $0.isNumber }
    return digits.isEmpty ? nil : String(digits)
}

func hasMethod(_ line: String, _ method: String) -> Bool {
    return line.contains("\"method\": \"\(method)\"") || line.contains("\"method\":\"\(method)\"")
}

while let line = readLine() {
    guard let id = extractId(line) else { continue }
    if hasMethod(line, "initialize") {
        print("{\"id\":\(id),\"result\":{\"ok\":true,\"api_version\":\"1\"}}")
    } else if hasMethod(line, "event") {
        print("{\"id\":\(id),\"result\":{\"actions\":[{\"type\":\"test\",\"message\":\"swift-ok\"}]}}")
    } else if hasMethod(line, "health") || hasMethod(line, "shutdown") {
        print("{\"id\":\(id),\"result\":{\"ok\":true}}")
    } else {
        print("{\"id\":\(id),\"error\":\"unknown method\"}")
    }
    fflush(stdout)
}

