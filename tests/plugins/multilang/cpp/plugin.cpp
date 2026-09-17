// 最小「任意语言插件」示例：C++ 实现 Plugin API v1（stdin/stdout JSON-Lines）
// 编译：g++ -O2 -std=c++17 -o plugin plugin.cpp
#include <iostream>
#include <regex>
#include <string>

int main() {
    std::ios::sync_with_stdio(false);
    const std::regex id_re("\"id\":\\s*([0-9]+)");
    const std::regex method_re("\"method\":\\s*\"([a-z_]+)\"");
    std::string line;
    while (std::getline(std::cin, line)) {
        std::smatch m;
        if (!std::regex_search(line, m, id_re)) continue;
        const std::string id = m[1];
        std::string method;
        if (std::regex_search(line, m, method_re)) method = m[1];

        if (method == "initialize") {
            std::cout << "{\"id\":" << id << ",\"result\":{\"ok\":true,\"api_version\":\"1\"}}" << std::endl;
        } else if (method == "event") {
            std::cout << "{\"id\":" << id
                      << ",\"result\":{\"actions\":[{\"type\":\"test\",\"message\":\"cpp-ok\"}]}}" << std::endl;
        } else if (method == "health" || method == "shutdown") {
            std::cout << "{\"id\":" << id << ",\"result\":{\"ok\":true}}" << std::endl;
        } else {
            std::cout << "{\"id\":" << id << ",\"error\":\"unknown method\"}" << std::endl;
        }
    }
    return 0;
}

