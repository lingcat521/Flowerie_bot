// 最小「任意语言插件」示例：Rust 实现 Plugin API v1（stdin/stdout JSON-Lines）
// 编译：rustc -O -o plugin main.rs   （不依赖任何 crate，避免 cargo 联网）
use std::io::{self, BufRead, Write};

fn extract_id(line: &str) -> Option<u64> {
    let idx = line.find("\"id\":")? + 5;
    let digits: String = line[idx..]
        .chars()
        .skip_while(|c| c.is_whitespace())
        .take_while(|c| c.is_ascii_digit())
        .collect();
    digits.parse::<u64>().ok()
}

fn has_method(line: &str, method: &str) -> bool {
    line.contains(&format!("\"method\": \"{}\"", method))
        || line.contains(&format!("\"method\":\"{}\"", method))
}

fn main() {
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut out = stdout.lock();
    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => break,
        };
        let id = match extract_id(&line) {
            Some(v) => v,
            None => continue,
        };
        if has_method(&line, "initialize") {
            let _ = writeln!(out, "{{\"id\":{},\"result\":{{\"ok\":true,\"api_version\":\"1\"}}}}", id);
        } else if has_method(&line, "event") {
            let _ = writeln!(
                out,
                "{{\"id\":{},\"result\":{{\"actions\":[{{\"type\":\"test\",\"message\":\"rust-ok\"}}]}}}}",
                id
            );
        } else if has_method(&line, "health") || has_method(&line, "shutdown") {
            let _ = writeln!(out, "{{\"id\":{},\"result\":{{\"ok\":true}}}}", id);
        } else {
            let _ = writeln!(out, "{{\"id\":{},\"error\":\"unknown method\"}}", id);
        }
        let _ = out.flush();
    }
}

