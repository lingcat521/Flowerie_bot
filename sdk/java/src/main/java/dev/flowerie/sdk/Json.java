package dev.flowerie.sdk;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 极简 JSON 编解码（Plugin Protocol v1 需要的最小集合；**不引入任何第三方库**）。
 *
 * <p>为什么自己写：Java SDK 要"零依赖"——插件作者不该为了写一个 Flowerie 插件去拉 Gson/Jackson。
 * 支持 object / array / string / number / bool / null；解析失败抛 {@link JsonException}。
 */
public final class Json {

    private Json() {
    }

    /** 解析失败。 */
    public static class JsonException extends RuntimeException {
        public JsonException(String message) {
            super(message);
        }
    }

    /** 解析一个完整 JSON 文本 → Map / List / String / Double / Boolean / null。 */
    public static Object parse(String text) {
        Parser parser = new Parser(text);
        parser.skipWs();
        Object value = parser.value();
        parser.skipWs();
        if (!parser.atEnd()) {
            throw new JsonException("JSON 尾部有多余内容");
        }
        return value;
    }

    /** 序列化（整数不带小数点：跨语言比对时 1 与 1.0 不等价）。 */
    public static String dump(Object value) {
        StringBuilder out = new StringBuilder();
        write(value, out);
        return out.toString();
    }

    /** 语言无关类型校验（§十九，Plugin-to-Plugin 边界专用）：只允许 null / Boolean / Number /
     * String / List / Map（键必须是 String）。
     *
     * <p>为什么必须显式校验：{@link #dump} 遇到不认识的 Java 对象会退化成 {@code toString()}
     * —— 那正是跨语言边界上最危险的「悄悄序列化」。插件间通信的参数/返回值在这里被**拒绝**，
     * 由 SDK 映射成 SERIALIZATION_ERROR（§十九/§二十）。深度上限 32、NaN/Infinity 一律拒绝。
     */
    public static void checkJsonValue(Object value, String path) {
        checkValue(value, (path == null || path.isEmpty()) ? "value" : path, 0);
    }

    private static void checkValue(Object value, String path, int depth) {
        if (depth > 32) {
            throw new JsonException("嵌套层级过深（>32）: " + path);
        }
        if (value == null || value instanceof Boolean || value instanceof String) {
            return;
        }
        if (value instanceof Number) {
            double d = ((Number) value).doubleValue();
            if (Double.isNaN(d) || Double.isInfinite(d)) {
                throw new JsonException("NaN/Infinity 不能跨语言传输（JSON 无此类型）: " + path);
            }
            return;
        }
        if (value instanceof Map) {
            for (Map.Entry<?, ?> entry : ((Map<?, ?>) value).entrySet()) {
                if (!(entry.getKey() instanceof String)) {
                    throw new JsonException("对象键必须是字符串: " + path);
                }
                checkValue(entry.getValue(), path + "." + entry.getKey(), depth + 1);
            }
            return;
        }
        if (value instanceof List) {
            int index = 0;
            for (Object item : (List<?>) value) {
                checkValue(item, path + "[" + index + "]", depth + 1);
                index++;
            }
            return;
        }
        throw new JsonException("语言内部对象不能跨插件边界: " + value.getClass().getName()
                + "（" + path + "；只允许 null/boolean/number/string/array/object）");
    }

    @SuppressWarnings("unchecked")
    private static void write(Object value, StringBuilder out) {
        if (value == null) {
            out.append("null");
        } else if (value instanceof String) {
            writeString((String) value, out);
        } else if (value instanceof Boolean) {
            out.append(((Boolean) value) ? "true" : "false");
        } else if (value instanceof Number) {
            double d = ((Number) value).doubleValue();
            if (d == Math.rint(d) && Math.abs(d) < 1e15) {
                out.append((long) d);
            } else {
                out.append(d);
            }
        } else if (value instanceof Map) {
            out.append('{');
            boolean first = true;
            for (Map.Entry<String, Object> entry : ((Map<String, Object>) value).entrySet()) {
                if (!first) {
                    out.append(',');
                }
                first = false;
                writeString(entry.getKey(), out);
                out.append(':');
                write(entry.getValue(), out);
            }
            out.append('}');
        } else if (value instanceof List) {
            out.append('[');
            boolean first = true;
            for (Object item : (List<Object>) value) {
                if (!first) {
                    out.append(',');
                }
                first = false;
                write(item, out);
            }
            out.append(']');
        } else {
            writeString(String.valueOf(value), out);
        }
    }

    private static void writeString(String s, StringBuilder out) {
        out.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"': out.append("\\\""); break;
                case '\\': out.append("\\\\"); break;
                case '\n': out.append("\\n"); break;
                case '\r': out.append("\\r"); break;
                case '\t': out.append("\\t"); break;
                default:
                    if (c < 0x20) {
                        out.append(String.format("\\u%04x", (int) c));
                    } else {
                        out.append(c);
                    }
            }
        }
        out.append('"');
    }

    /** 便捷：读取对象字段（非对象或字段缺失返回 null）。 */
    @SuppressWarnings("unchecked")
    public static Object get(Object value, String key) {
        if (value instanceof Map) {
            return ((Map<String, Object>) value).get(key);
        }
        return null;
    }

    /** 便捷：按 key 取字符串。 */
    public static String str(Object value, String key) {
        Object got = get(value, key);
        return got instanceof String ? (String) got : null;
    }

    /** 便捷：构造有序对象。 */
    public static Map<String, Object> obj(Object... pairs) {
        Map<String, Object> map = new LinkedHashMap<>();
        for (int i = 0; i + 1 < pairs.length; i += 2) {
            map.put(String.valueOf(pairs[i]), pairs[i + 1]);
        }
        return map;
    }

    private static final class Parser {
        private final String text;
        private int pos;

        Parser(String text) {
            this.text = text;
        }

        boolean atEnd() {
            return pos >= text.length();
        }

        void skipWs() {
            while (pos < text.length() && Character.isWhitespace(text.charAt(pos))) {
                pos++;
            }
        }

        private char peek() {
            return pos < text.length() ? text.charAt(pos) : '\0';
        }

        private char next() {
            if (pos >= text.length()) {
                throw new JsonException("JSON 意外结束");
            }
            return text.charAt(pos++);
        }

        Object value() {
            skipWs();
            char c = peek();
            switch (c) {
                case '{': return object();
                case '[': return array();
                case '"': return string();
                case 't': expect("true"); return Boolean.TRUE;
                case 'f': expect("false"); return Boolean.FALSE;
                case 'n': expect("null"); return null;
                default: return number();
            }
        }

        private void expect(String word) {
            for (int i = 0; i < word.length(); i++) {
                if (next() != word.charAt(i)) {
                    throw new JsonException("JSON 期望 " + word);
                }
            }
        }

        private Map<String, Object> object() {
            next();
            Map<String, Object> map = new LinkedHashMap<>();
            skipWs();
            if (peek() == '}') {
                next();
                return map;
            }
            while (true) {
                skipWs();
                String key = string();
                skipWs();
                if (next() != ':') {
                    throw new JsonException("JSON 对象缺少冒号");
                }
                map.put(key, value());
                skipWs();
                char c = next();
                if (c == ',') {
                    continue;
                }
                if (c == '}') {
                    return map;
                }
                throw new JsonException("JSON 对象格式错误");
            }
        }

        private List<Object> array() {
            next();
            List<Object> items = new ArrayList<>();
            skipWs();
            if (peek() == ']') {
                next();
                return items;
            }
            while (true) {
                items.add(value());
                skipWs();
                char c = next();
                if (c == ',') {
                    continue;
                }
                if (c == ']') {
                    return items;
                }
                throw new JsonException("JSON 数组格式错误");
            }
        }

        private String string() {
            if (next() != '"') {
                throw new JsonException("JSON 期望字符串");
            }
            StringBuilder out = new StringBuilder();
            while (true) {
                char c = next();
                if (c == '"') {
                    return out.toString();
                }
                if (c != '\\') {
                    out.append(c);
                    continue;
                }
                char esc = next();
                switch (esc) {
                    case 'n': out.append('\n'); break;
                    case 'r': out.append('\r'); break;
                    case 't': out.append('\t'); break;
                    case '"': out.append('"'); break;
                    case '\\': out.append('\\'); break;
                    case '/': out.append('/'); break;
                    case 'u':
                        StringBuilder hex = new StringBuilder();
                        for (int i = 0; i < 4; i++) {
                            hex.append(next());
                        }
                        out.append((char) Integer.parseInt(hex.toString(), 16));
                        break;
                    default:
                        throw new JsonException("JSON 非法转义");
                }
            }
        }

        private Double number() {
            int start = pos;
            while (pos < text.length()) {
                char c = text.charAt(pos);
                if (Character.isDigit(c) || c == '-' || c == '+' || c == '.' || c == 'e' || c == 'E') {
                    pos++;
                } else {
                    break;
                }
            }
            String raw = text.substring(start, pos);
            try {
                return Double.valueOf(raw);
            } catch (NumberFormatException e) {
                throw new JsonException("JSON 非法数字: " + raw);
            }
        }
    }
}
