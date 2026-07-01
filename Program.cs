using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using YamlDotNet.Serialization;
using YamlDotNet.Serialization.NamingConventions;

// ── 加载配置 ──────────────────────────────────────────
var cfgPath = Path.Combine(AppContext.BaseDirectory, "config.yaml");
// 也尝试当前目录（开发时）
if (!File.Exists(cfgPath))
    cfgPath = Path.Combine(Directory.GetCurrentDirectory(), "config.yaml");
if (!File.Exists(cfgPath))
{
    Console.WriteLine("找不到 config.yaml!");
    return 1;
}

var yaml = File.ReadAllText(cfgPath);
var deserializer = new DeserializerBuilder()
    .WithNamingConvention(UnderscoredNamingConvention.Instance)
    .Build();
var cfg = deserializer.Deserialize<Config>(yaml);

// ── 找 agent.log ──────────────────────────────────────
var logPaths = new[]
{
    Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                 "hermes", "logs", "agent.log"),
    Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
                 ".hermes", "logs", "agent.log"),
};
var logFile = logPaths.FirstOrDefault(File.Exists);
if (logFile == null)
{
    Console.WriteLine("找不到 agent.log!");
    return 1;
}

// ── UDP 广播 ──────────────────────────────────────────
using var udp = new UdpClient();
udp.EnableBroadcast = true;
var endpoint = new IPEndPoint(IPAddress.Parse(cfg.Udp.Broadcast), cfg.Udp.Port);

var timeout = cfg.Monitor.WorkingTimeout;
var maxCtx = cfg.Monitor.MaxContext;
const int pollMs = 50;

// ── 正则 ──────────────────────────────────────────────
var modelRe = new Regex(@"model=([\w./-]+)");
var totalRe = new Regex(@"total=(\d+)");

// ── 持久状态 ──────────────────────────────────────────
var model = "unknown";
long ctxLen = 0;

var sessionFile = Path.Combine(AppContext.BaseDirectory, ".session_start.txt");
if (!File.Exists(sessionFile))
    sessionFile = Path.Combine(Directory.GetCurrentDirectory(), ".session_start.txt");
var sessionStart = File.Exists(sessionFile)
    ? DateTime.Parse(File.ReadAllText(sessionFile).Trim())
    : DateTime.Now;
if (!File.Exists(sessionFile))
    File.WriteAllText(sessionFile, sessionStart.ToString("O"));

// 防抖
string? debouncePending = null;
DateTime debounceSince = DateTime.MinValue;
var lastStatus = "idle";
var lastSentKey = "";

// ── 辅助方法 ──────────────────────────────────────────
string Fmt(string template, Dictionary<string, string> vars)
{
    var result = template;
    foreach (var (k, v) in vars) result = result.Replace($"{{{k}}}", v);
    return result;
}

string GetKaomoji(string status) =>
    cfg.Kaomoji.TryGetValue(status, out var k) ? k :
    cfg.Kaomoji.GetValueOrDefault("unknown", "(?_?)");

string GetStatusShort(string status) =>
    cfg.StatusShort.TryGetValue(status, out var s) ? s :
    cfg.StatusShort.GetValueOrDefault("unknown", "???");

string BuildPayload(string status)
{
    var ctxPct = (int)Math.Min(100, ctxLen * 100.0 / maxCtx);
    var ctxK = ctxLen >= 1024 ? $"{ctxLen / 1024.0:F1}K" : ctxLen.ToString();
    var kaomoji = GetKaomoji(status);
    var sshort = GetStatusShort(status);

    var vars = new Dictionary<string, string>
    {
        ["model"] = model, ["status"] = status, ["status_short"] = sshort,
        ["ctx_pct"] = $"{ctxPct}%", ["ctx_k"] = ctxK, ["kaomoji"] = kaomoji,
    };

    var obj = new Dictionary<string, object>
    {
        ["status"] = status,
        ["agent"] = "hermes",
        ["model"] = model,
        ["context_len"] = ctxLen,
        ["cum_time"] = Fmt(cfg.Display.OledLine2, vars)[..Math.Min(16, Fmt(cfg.Display.OledLine2, vars).Length)],
        ["task_summary"] = "",
        ["cpu_percent"] = 0, ["mem_mb"] = 0,
        ["timestamp"] = DateTime.UtcNow.ToString("O"),
        ["ctx_display"] = Fmt(cfg.Display.LcdLine2, vars)[..Math.Min(16, Fmt(cfg.Display.LcdLine2, vars).Length)],
        ["oled_line1"] = Fmt(cfg.Display.OledLine1, vars),
        ["lcd_line1"] = Fmt(cfg.Display.LcdLine1, vars)[..Math.Min(16, Fmt(cfg.Display.LcdLine1, vars).Length)],
    };
    return JsonSerializer.Serialize(obj);
}

// ── 日志行解析 ────────────────────────────────────────
(DateTime? ts, bool isApi, bool isClarify) ParseLine(string line)
{
    var m = modelRe.Match(line);
    if (m.Success) model = m.Groups[1].Value;

    var t = totalRe.Match(line);
    if (t.Success) ctxLen = long.Parse(t.Groups[1].Value);

    DateTime? ts = null;
    var isApi = false;
    var isClarify = false;

    if (line.Contains("agent.conversation_loop"))
    {
        isApi = true;
        try
        {
            var tsStr = line.Split(',')[0].Trim();
            ts = DateTime.Parse(tsStr);
        }
        catch { }
    }

    if (line.Contains("tool clarify") || line.Contains("clarify completed"))
        isClarify = true;

    return (ts, isApi, isClarify);
}

// ── 状态判定 + 防抖 ──────────────────────────────────
string DetermineStatus(DateTime now, DateTime? lastApiTime, bool lastWasClarify)
{
    string raw;
    if (lastApiTime == null)
        raw = "idle";
    else if ((now - lastApiTime.Value).TotalSeconds < timeout)
        raw = "working";
    else if (lastWasClarify)
        raw = "waiting";
    else
        raw = "idle";

    if (raw != lastStatus)
    {
        if (debouncePending != raw)
        {
            debouncePending = raw;
            debounceSince = now;
        }
        else if ((now - debounceSince).TotalSeconds >= 0.5)
        {
            return raw;
        }
        return lastStatus;
    }
    else
    {
        debouncePending = null;
        return lastStatus;
    }
}

// ── 主循环 ────────────────────────────────────────────
Console.WriteLine($"⚡ 实时模式: {logFile}");
Console.WriteLine($"→ UDP {cfg.Udp.Broadcast}:{cfg.Udp.Port}");
Console.WriteLine($"→ 轮询 {pollMs}ms  超时 {timeout}s  最大上下文 {maxCtx / 1000}K");
Console.WriteLine("→ 文件指针跟踪 + 防抖 0.5s");
Console.WriteLine();

DateTime? lastApiTime = null;
var lastWasClarify = false;

// 跳到文件末尾，只读增量
using var fs = new FileStream(logFile, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
fs.Seek(0, SeekOrigin.End);
using var reader = new StreamReader(fs, Encoding.UTF8);

try
{
    while (true)
    {
        var line = reader.ReadLine();
        if (line != null)
        {
            var (ts, isApi, isClarify) = ParseLine(line);
            if (isApi && ts.HasValue) lastApiTime = ts;
            if (isClarify) lastWasClarify = true;
            else if (isApi) lastWasClarify = false;
        }
        else
        {
            Thread.Sleep(pollMs);
        }

        var now = DateTime.Now;
        lastStatus = DetermineStatus(now, lastApiTime, lastWasClarify);

        var data = BuildPayload(lastStatus);
        var parts = JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(data)!;
        var key = $"{lastStatus}|{parts["ctx_display"].GetString()}";

        if (key != lastSentKey)
        {
            var elapsed = now - sessionStart;
            var cum = $"{(int)elapsed.TotalHours}h{elapsed.Minutes:D2}m";
            Console.WriteLine($"[{lastStatus.ToUpper(),-7}] {parts["lcd_line1"].GetString()} | {parts["ctx_display"].GetString()} | {cum}");
            lastSentKey = key;
        }

        var bytes = Encoding.UTF8.GetBytes(data);
        udp.Send(bytes, bytes.Length, endpoint);
    }
}
catch (OperationCanceledException) { }
finally
{
    Console.WriteLine("\n已停止");
}

return 0;

// ── 配置类型 ──────────────────────────────────────────
class Config
{
    public UdpConfig Udp { get; set; } = new();
    public MonitorConfig Monitor { get; set; } = new();
    public DisplayConfig Display { get; set; } = new();
    public Dictionary<string, string> Kaomoji { get; set; } = new();
    public Dictionary<string, string> StatusShort { get; set; } = new();
}
class UdpConfig { public string Broadcast { get; set; } = ""; public int Port { get; set; } }
class MonitorConfig { public int PollInterval { get; set; } public int WorkingTimeout { get; set; } public int MaxContext { get; set; } }
class DisplayConfig { public string OledLine1 { get; set; } = ""; public string OledLine2 { get; set; } = ""; public string LcdLine1 { get; set; } = ""; public string LcdLine2 { get; set; } = ""; }
