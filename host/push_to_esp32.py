# -*- coding: utf-8 -*-
"""
Hermes → ESP32 UDP 推送
文件指针跟踪 + 50ms readline() → 接近 TUI 实时性，零外部依赖

如果安装了 esp32_bridge（进程内回调），自动切换为补充模式：
只推送模型名/上下文/会话时间，状态由桥接实时推送。
"""
import sys, re, os, json, time, socket, yaml
from pathlib import Path
from datetime import datetime, timezone

# ── 检测 ESP32 桥接是否已安装 ──────────────────────────
BRIDGE_INSTALLED = False
try:
    hermes_src = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes/hermes-agent"
    bridge_file = hermes_src / "agent/esp32_bridge.py"
    cli_py = hermes_src / "cli.py"
    if bridge_file.exists():
        BRIDGE_INSTALLED = True
except Exception:
    pass

if not BRIDGE_INSTALLED:
    print("=" * 55)
    print("  ⚡ 推荐安装 ESP32 实时桥接（毫秒级事件推送）")
    print("=" * 55)
    print("  当前：50ms 轮询 agent.log（约 50ms 延迟）")
    print("  桥接：进程内回调 → 0ms 延迟，能看到思考颜文字")
    print()
    print("  安装只需一步：")
    src_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes/hermes-agent"
    print(f"  1. 复制 agent/esp32_bridge.py 到 Hermes 源码：")
    print(f"     cp host/../agent/esp32_bridge.py \"{src_dir / 'agent/'}\"")
    print(f"  2. 修改 cli.py 注入回调（见 README）")
    print("=" * 55)
    print()

# ── 加载配置 ──────────────────────────────────────────
cfg_path = Path(__file__).parent / "config.yaml"
with open(cfg_path, 'r', encoding='utf-8') as f:
    cfg = yaml.safe_load(f)

# ── 找 agent.log ──────────────────────────────────────
log_paths = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "hermes/logs/agent.log",
    Path.home() / ".hermes/logs/agent.log",
]
LOG_FILE = next((p for p in log_paths if p.exists()), None)
if not LOG_FILE:
    print("找不到 agent.log!")
    sys.exit(1)

# ── UDP 广播 ──────────────────────────────────────────
UDP_IP = cfg["udp"]["broadcast"]
UDP_PORT = cfg["udp"]["port"]
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

TIMEOUT = cfg["monitor"]["working_timeout"]  # 判定 working 的超时 (秒)
MAX_CTX = cfg["monitor"]["max_context"]
POLL_MS = 0.05  # 50ms 轮询 — 足够实时，不费 CPU

# ── 正则 ──────────────────────────────────────────────
MODEL_RE = re.compile(r'model=([\w./-]+)')
TOTAL_RE = re.compile(r'total=(\d+)')

# ── 持久状态 ──────────────────────────────────────────
model = "unknown"
ctx_len = 0

# 会话累计时间（防重启丢失）
SESSION_FILE = Path(__file__).parent / ".session_start.txt"
if SESSION_FILE.exists():
    session_start = datetime.fromisoformat(SESSION_FILE.read_text(encoding='utf-8').strip())
else:
    session_start = datetime.now()
    SESSION_FILE.write_text(session_start.isoformat(), encoding='utf-8')

# 防抖：避免状态快速 A→B→A 抖动
debounce = {"pending": None, "since": 0}
last_status = "idle"
last_sent_key = ""

# ── 显示格式化 ────────────────────────────────────────
def fmt(template, vars):
    result = template
    for k, v in vars.items():
        result = result.replace("{" + k + "}", str(v))
    return result

def build_payload(status):
    """构造发给 ESP32 的 JSON"""
    ctx_pct = min(100, int(ctx_len / MAX_CTX * 100))
    ctx_k = f"{ctx_len/1024:.1f}K" if ctx_len >= 1024 else str(ctx_len)
    kaomoji = cfg["kaomoji"].get(status, cfg["kaomoji"]["unknown"])
    sshort = cfg["status_short"].get(status, cfg["status_short"]["unknown"])

    fmt_vars = {
        "model": model, "status": status, "status_short": sshort,
        "ctx_pct": f"{ctx_pct}%", "ctx_k": ctx_k, "kaomoji": kaomoji,
    }
    return {
        "status": status,
        "agent": "hermes",
        "model": model,
        "context_len": ctx_len,
        "cum_time": fmt(cfg["display"]["oled_line3"], fmt_vars)[:16],
        "task_summary": "",
        "cpu_percent": 0, "mem_mb": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ctx_display": fmt(cfg["display"]["lcd_line2"], fmt_vars)[:16],
        "oled_line1": fmt(cfg["display"]["oled_line1"], fmt_vars),
        "oled_line2": fmt(cfg["display"]["oled_line2"], fmt_vars),
        "lcd_line1": fmt(cfg["display"]["lcd_line1"], fmt_vars)[:16],
    }

# ── 日志行解析 ────────────────────────────────────────
def parse_line(line):
    """从一行日志中提取模型名、上下文长度、时间戳。
    返回 (timestamp, is_api_call, is_clarify)"""
    global model, ctx_len

    m = MODEL_RE.search(line)
    if m:
        model = m.group(1)
    t = TOTAL_RE.search(line)
    if t:
        ctx_len = int(t.group(1))

    ts = None
    is_api = False
    is_clarify = False

    if "agent.conversation_loop" in line:
        is_api = True
        try:
            ts_str = line.split(",")[0].strip()
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        except:
            pass

    if "tool clarify" in line or "clarify completed" in line:
        is_clarify = True

    return ts, is_api, is_clarify

# ── 状态判定 + 防抖 ──────────────────────────────────
def determine_status(now):
    """基于最近一次 API 调用时间判定状态，带 0.5s 防抖"""
    global last_status, last_api_time, last_was_clarify

    if last_was_clarify:
        raw = "waiting"  # clarify 完成立即切 waiting，不等超时
    elif last_api_time is None:
        raw = "idle"
    elif (now - last_api_time).total_seconds() < TIMEOUT:
        raw = "working"
    else:
        raw = "idle"

    # 防抖：状态变更必须保持 0.5s 才生效
    if raw != last_status:
        if debounce["pending"] != raw:
            debounce["pending"] = raw
            debounce["since"] = now
        elif (now - debounce["since"]).total_seconds() >= 0.5:
            return raw  # 确认切换
        return last_status  # 还在防抖窗口内，保持不变
    else:
        debounce["pending"] = None  # 回到原状态，取消待定
        return last_status

# ── 主循环 ────────────────────────────────────────────
print(f"⚡ 实时模式: {LOG_FILE}")
print(f"→ UDP {UDP_IP}:{UDP_PORT}")
print(f"→ 轮询 {POLL_MS*1000:.0f}ms  超时 {TIMEOUT}s  最大上下文 {MAX_CTX//1000}K")
if BRIDGE_INSTALLED:
    print("→ 🔗 ESP32 桥接已激活（思考状态由进程内回调推送）")
else:
    print("→ 文件指针跟踪 + 防抖 0.5s（安装桥接可获毫秒级状态）")
print()

last_api_time = None
last_was_clarify = False

# 打开文件，跳到末尾（不读历史数据）
with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
    f.seek(0, 2)  # SEEK_END

    try:
        while True:
            line = f.readline()
            if line:
                ts, is_api, is_clarify = parse_line(line)
                if is_api and ts:
                    last_api_time = ts
                if is_clarify:
                    last_was_clarify = True
                elif is_api:
                    last_was_clarify = False  # 新一轮 API call，清除 waiting
            else:
                time.sleep(POLL_MS)

            # 每次循环都判定状态并推送（50ms 间隔）
            now = datetime.now()
            if BRIDGE_INSTALLED:
                # 桥接负责 working/idle，push 脚本只负责 waiting + 格式化
                raw = determine_status(now)
                if raw == "idle":
                    continue  # 让桥接处理，不覆盖
                status = raw
            else:
                status = determine_status(now)

            # 只在状态或内容变化时打印 + 推送
            data = build_payload(status)
            key = f"{status}|{data['ctx_display']}"
            if key != last_sent_key:
                elapsed = now - session_start
                hours = int(elapsed.total_seconds() // 3600)
                mins = int((elapsed.total_seconds() % 3600) // 60)
                cum = f"{hours}h{mins:02d}m"
                print(f"[{status.upper():7s}] {data['lcd_line1']} | {data['ctx_display']} | {cum}")
                last_sent_key = key

            msg = json.dumps(data, ensure_ascii=False)
            sock.sendto(msg.encode("utf-8"), (UDP_IP, UDP_PORT))

    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        sock.close()
