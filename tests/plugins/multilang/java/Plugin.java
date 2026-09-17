// 最小「任意语言插件」示例：Java 实现 Plugin API v1（stdin/stdout JSON-Lines）
// 编译：javac Plugin.java      入口：run.sh（exec java -cp <dir> Plugin）
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.io.PrintWriter;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class Plugin {
    private static final Pattern ID_RE = Pattern.compile("\"id\":\\s*([0-9]+)");
    private static final Pattern METHOD_RE = Pattern.compile("\"method\":\\s*\"([a-z_]+)\"");

    public static void main(String[] args) throws IOException {
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in));
        PrintWriter out = new PrintWriter(new OutputStreamWriter(System.out), true);
        String line;
        while ((line = in.readLine()) != null) {
            Matcher idm = ID_RE.matcher(line);
            if (!idm.find()) continue;
            String id = idm.group(1);
            Matcher mm = METHOD_RE.matcher(line);
            String method = mm.find() ? mm.group(1) : "";
            switch (method) {
                case "initialize":
                    out.println("{\"id\":" + id + ",\"result\":{\"ok\":true,\"api_version\":\"1\"}}");
                    break;
                case "event":
                    out.println("{\"id\":" + id
                            + ",\"result\":{\"actions\":[{\"type\":\"test\",\"message\":\"java-ok\"}]}}");
                    break;
                case "health":
                case "shutdown":
                    out.println("{\"id\":" + id + ",\"result\":{\"ok\":true}}");
                    break;
                default:
                    out.println("{\"id\":" + id + ",\"error\":\"unknown method\"}");
            }
        }
    }
}

