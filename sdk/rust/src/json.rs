//! 极简 JSON 编解码（Plugin Protocol v1 需要的最小集合；**不引入任何 crate**）。
//!
//! 为什么自己写：Rust SDK 要做到"零依赖"——插件作者不该为了写一个 Flowerie 插件去拉 serde。
//! 支持 object / array / string / number / bool / null，够协议信封使用。

use std::collections::BTreeMap;
use std::fmt::Write as _;

/// JSON 值。
#[derive(Debug, Clone, PartialEq)]
pub enum Json {
    Null,
    Bool(bool),
    Num(f64),
    Str(String),
    Arr(Vec<Json>),
    Obj(BTreeMap<String, Json>),
}

impl Json {
    /// 构造对象（BTreeMap 保证键有序，便于跨语言比对）。
    pub fn obj(pairs: Vec<(&str, Json)>) -> Json {
        let mut map = BTreeMap::new();
        for (k, v) in pairs {
            map.insert(k.to_string(), v);
        }
        Json::Obj(map)
    }

    pub fn str(value: &str) -> Json {
        Json::Str(value.to_string())
    }

    pub fn num(value: i64) -> Json {
        Json::Num(value as f64)
    }

    pub fn get(&self, key: &str) -> Option<&Json> {
        match self {
            Json::Obj(map) => map.get(key),
            _ => None,
        }
    }

    pub fn as_str(&self) -> Option<&str> {
        match self {
            Json::Str(s) => Some(s.as_str()),
            _ => None,
        }
    }

    pub fn as_f64(&self) -> Option<f64> {
        match self {
            Json::Num(n) => Some(*n),
            _ => None,
        }
    }

    pub fn as_bool(&self) -> Option<bool> {
        match self {
            Json::Bool(b) => Some(*b),
            _ => None,
        }
    }

    pub fn as_arr(&self) -> Option<&Vec<Json>> {
        match self {
            Json::Arr(items) => Some(items),
            _ => None,
        }
    }

    /// 序列化：整数不带小数点（跨语言比对时 1 与 1.0 不等价）。
    pub fn dump(&self) -> String {
        let mut out = String::new();
        self.write_to(&mut out);
        out
    }

    fn write_to(&self, out: &mut String) {
        match self {
            Json::Null => out.push_str("null"),
            Json::Bool(true) => out.push_str("true"),
            Json::Bool(false) => out.push_str("false"),
            Json::Num(n) => {
                if n.fract() == 0.0 && n.abs() < 1e15 {
                    let _ = write!(out, "{}", *n as i64);
                } else {
                    let _ = write!(out, "{}", n);
                }
            }
            Json::Str(s) => write_string(s, out),
            Json::Arr(items) => {
                out.push('[');
                for (i, item) in items.iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                    }
                    item.write_to(out);
                }
                out.push(']');
            }
            Json::Obj(map) => {
                out.push('{');
                for (i, (k, v)) in map.iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                    }
                    write_string(k, out);
                    out.push(':');
                    v.write_to(out);
                }
                out.push('}');
            }
        }
    }
}

fn write_string(s: &str, out: &mut String) {
    out.push('"');
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => {
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

/// 解析一个完整 JSON 文本。
pub fn parse(text: &str) -> Result<Json, String> {
    let chars: Vec<char> = text.chars().collect();
    let mut parser = Parser { chars, pos: 0 };
    parser.skip_ws();
    let value = parser.value()?;
    parser.skip_ws();
    if parser.pos != parser.chars.len() {
        return Err("JSON 尾部有多余内容".to_string());
    }
    Ok(value)
}

struct Parser {
    chars: Vec<char>,
    pos: usize,
}

impl Parser {
    fn peek(&self) -> Option<char> {
        self.chars.get(self.pos).copied()
    }

    fn next(&mut self) -> Option<char> {
        let ch = self.peek();
        if ch.is_some() {
            self.pos += 1;
        }
        ch
    }

    fn skip_ws(&mut self) {
        while let Some(ch) = self.peek() {
            if ch == ' ' || ch == '\n' || ch == '\r' || ch == '\t' {
                self.pos += 1;
            } else {
                break;
            }
        }
    }

    fn value(&mut self) -> Result<Json, String> {
        self.skip_ws();
        match self.peek() {
            Some('{') => self.object(),
            Some('[') => self.array(),
            Some('"') => Ok(Json::Str(self.string()?)),
            Some('t') => self.literal("true", Json::Bool(true)),
            Some('f') => self.literal("false", Json::Bool(false)),
            Some('n') => self.literal("null", Json::Null),
            Some(_) => self.number(),
            None => Err("JSON 意外结束".to_string()),
        }
    }

    fn literal(&mut self, word: &str, value: Json) -> Result<Json, String> {
        for expected in word.chars() {
            if self.next() != Some(expected) {
                return Err(format!("JSON 期望 {}", word));
            }
        }
        Ok(value)
    }

    fn object(&mut self) -> Result<Json, String> {
        self.next();
        let mut map = BTreeMap::new();
        self.skip_ws();
        if self.peek() == Some('}') {
            self.next();
            return Ok(Json::Obj(map));
        }
        loop {
            self.skip_ws();
            let key = self.string()?;
            self.skip_ws();
            if self.next() != Some(':') {
                return Err("JSON 对象缺少冒号".to_string());
            }
            let value = self.value()?;
            map.insert(key, value);
            self.skip_ws();
            match self.next() {
                Some(',') => continue,
                Some('}') => break,
                _ => return Err("JSON 对象格式错误".to_string()),
            }
        }
        Ok(Json::Obj(map))
    }

    fn array(&mut self) -> Result<Json, String> {
        self.next();
        let mut items = Vec::new();
        self.skip_ws();
        if self.peek() == Some(']') {
            self.next();
            return Ok(Json::Arr(items));
        }
        loop {
            items.push(self.value()?);
            self.skip_ws();
            match self.next() {
                Some(',') => continue,
                Some(']') => break,
                _ => return Err("JSON 数组格式错误".to_string()),
            }
        }
        Ok(Json::Arr(items))
    }

    fn string(&mut self) -> Result<String, String> {
        if self.next() != Some('"') {
            return Err("JSON 期望字符串".to_string());
        }
        let mut out = String::new();
        loop {
            match self.next() {
                None => return Err("JSON 字符串未闭合".to_string()),
                Some('"') => break,
                Some('\\') => match self.next() {
                    Some('n') => out.push('\n'),
                    Some('r') => out.push('\r'),
                    Some('t') => out.push('\t'),
                    Some('"') => out.push('"'),
                    Some('\\') => out.push('\\'),
                    Some('/') => out.push('/'),
                    Some('u') => {
                        let mut code = 0u32;
                        for _ in 0..4 {
                            let ch = self.next().ok_or("JSON unicode 转义不完整")?;
                            code = code * 16 + ch.to_digit(16).ok_or("JSON unicode 转义非法")?;
                        }
                        out.push(char::from_u32(code).unwrap_or('?'));
                    }
                    _ => return Err("JSON 非法转义".to_string()),
                },
                Some(ch) => out.push(ch),
            }
        }
        Ok(out)
    }

    fn number(&mut self) -> Result<Json, String> {
        let start = self.pos;
        while let Some(ch) = self.peek() {
            if ch.is_ascii_digit() || ch == '-' || ch == '+' || ch == '.' || ch == 'e' || ch == 'E' {
                self.pos += 1;
            } else {
                break;
            }
        }
        let text: String = self.chars[start..self.pos].iter().collect();
        text.parse::<f64>().map(Json::Num).map_err(|_| format!("JSON 非法数字: {}", text))
    }
}
