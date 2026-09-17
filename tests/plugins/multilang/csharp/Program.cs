// 最小「任意语言插件」示例：C# / .NET 实现 Plugin API v1（stdin/stdout JSON-Lines）
// 运行：dotnet run --project <dir>（入口 run.sh 包装）
using System;
using System.IO;
using System.Text.RegularExpressions;

class Plugin
{
    static readonly Regex IdRe = new Regex("\"id\":\\s*([0-9]+)");
    static readonly Regex MethodRe = new Regex("\"method\":\\s*\"([a-z_]+)\"");

    static void Main()
    {
        var stdout = new StreamWriter(Console.OpenStandardOutput()) { AutoFlush = true };
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var idm = IdRe.Match(line);
            if (!idm.Success) continue;
            string id = idm.Groups[1].Value;
            var mm = MethodRe.Match(line);
            string method = mm.Success ? mm.Groups[1].Value : "";
            switch (method)
            {
                case "initialize":
                    stdout.WriteLine("{\"id\":" + id + ",\"result\":{\"ok\":true,\"api_version\":\"1\"}}");
                    break;
                case "event":
                    stdout.WriteLine("{\"id\":" + id + ",\"result\":{\"actions\":[{\"type\":\"test\",\"message\":\"csharp-ok\"}]}}");
                    break;
                case "health":
                case "shutdown":
                    stdout.WriteLine("{\"id\":" + id + ",\"result\":{\"ok\":true}}");
                    break;
                default:
                    stdout.WriteLine("{\"id\":" + id + ",\"error\":\"unknown method\"}");
                    break;
            }
        }
    }
}

