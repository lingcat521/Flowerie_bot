/* 最小「任意语言插件」示例：C 实现 Plugin API v1（stdin/stdout JSON-Lines）
 * 编译：gcc -O2 -o plugin plugin.c        （entry 指向编译产物 plugin）
 * 说明：这里用 strstr/strtol 取值——最小实现，不引入任何 JSON 库。 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static long extract_id(const char *line) {
    const char *p = strstr(line, "\"id\":");
    if (!p) return -1;
    return strtol(p + 5, NULL, 10);
}

static int has_method(const char *line, const char *method) {
    char pat[64];
    snprintf(pat, sizeof(pat), "\"method\": \"%s\"", method);
    if (strstr(line, pat)) return 1;
    snprintf(pat, sizeof(pat), "\"method\":\"%s\"", method);
    return strstr(line, pat) != NULL;
}

int main(void) {
    char line[65536];
    while (fgets(line, sizeof(line), stdin)) {
        long id = extract_id(line);
        if (id < 0) continue;
        if (has_method(line, "initialize")) {
            printf("{\"id\":%ld,\"result\":{\"ok\":true,\"api_version\":\"1\"}}\n", id);
        } else if (has_method(line, "event")) {
            printf("{\"id\":%ld,\"result\":{\"actions\":[{\"type\":\"test\",\"message\":\"c-ok\"}]}}\n", id);
        } else if (has_method(line, "health") || has_method(line, "shutdown")) {
            printf("{\"id\":%ld,\"result\":{\"ok\":true}}\n", id);
        } else {
            printf("{\"id\":%ld,\"error\":\"unknown method\"}\n", id);
        }
        fflush(stdout);
    }
    return 0;
}

