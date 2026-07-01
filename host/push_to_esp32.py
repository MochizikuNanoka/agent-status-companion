# -*- coding: utf-8 -*-
"""
Hermes → ESP32 UDP 推送 (可配置版)
读 config.yaml → agent.log → 格式化 → UDP 广播
"""
import sys, re, os, json, time, socket, yaml
from pathlib import Path
from datetime import datetime, timezone

# 加载配置
cfg_path = Path(__file__).parent / "config.yaml"
with open(cfg_path, 'r', encoding='utf-8') as f:
    cfg = yaml.safe_load(f)

# 找 agent.log
log_paths = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "hermes/logs/agent.log",
    Path.home() / ".hermes/logs/agent.log",
]
log_file = next((p for p in log_paths if p.exists()), None)
if not log_file:
    print("找不到 agent.log!"); sys.exit(1)

# UDP
UDP_IP = cfg["udp"]["broadcast"]
UDP_PORT = cfg["udp"]["port"]
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

POLL = cfg["monitor"]["poll_interval"]
TIMEOUT = cfg["monitor"]["working_timeout"]
MAX_CTX = cfg["monitor"]["max_context"]

print(f"→ 监控 {log_file}")
print(f"→ UDP {UDP_IP}:{UDP_PORT}")
print(f"→ 轮询 {POLL}s  超时 {TIMEOUT}s  最大上下文 {MAX_CTX//1000}K")
print(f"→ 配置 {cfg_path}\n")

MODEL_RE = re.compile(r'model=([\w./-]+)')
TOTAL_RE = re.compile(r'total=(\d+)')

model = "unknown"
ctx_len = 0
last_sent = {}

def read_tail(path, n=8):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.readlines()[-n:]
    except:
        return []

def get_status():
    global model, ctx_len
    lines = read_tail(log_file, 8)
    status = "idle"
    found_api = False
    found_clarify = False

    for line in reversed(lines):
        m = MODEL_RE.search(line)
        if m: model = m.group(1)
        t = TOTAL_RE.search(line)
        if t: ctx_len = int(t.group(1))
        if "agent.conversation_loop" in line:
            try:
                ts_str = line.split(",")[0].strip()
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                if (datetime.now() - ts).total_seconds() < TIMEOUT:
                    found_api = True
            except:
                found_api = True
        if "tool clarify" in line or "clarify completed" in line:
            found_clarify = True
            break

    if found_api: status = "working"
    elif found_clarify: status = "waiting"

    ctx_pct = min(100, int(ctx_len / MAX_CTX * 100))
    ctx_k = f"{ctx_len/1024:.1f}K" if ctx_len >= 1024 else str(ctx_len)
    kaomoji = cfg["kaomoji"].get(status, cfg["kaomoji"]["unknown"])
    sshort = cfg["status_short"].get(status, cfg["status_short"]["unknown"])

    # 格式化各行
    fmt_vars = {
        "model": model, "status": status, "status_short": sshort,
        "ctx_pct": f"{ctx_pct}%", "ctx_k": ctx_k, "kaomoji": kaomoji,
    }

    return {
        "status": status,
        "agent": "hermes",
        "model": model,
        "context_len": ctx_len,
        "cum_time": fmt(cfg["display"]["oled_line2"], fmt_vars)[:16],
        "task_summary": "",
        "cpu_percent": 0, "mem_mb": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ctx_display": fmt(cfg["display"]["lcd_line2"], fmt_vars)[:16],
        "oled_line1": fmt(cfg["display"]["oled_line1"], fmt_vars)[:10],
        "lcd_line1": fmt(cfg["display"]["lcd_line1"], fmt_vars)[:16],
    }

def fmt(template, vars):
    result = template
    for k, v in vars.items():
        result = result.replace("{" + k + "}", str(v))
    return result

try:
    while True:
        data = get_status()
        current = data["status"]
        # 只在状态变化时打印
        key = f"{current}|{data['ctx_display']}"
        if key != last_sent.get("key"):
            print(f"[{current.upper()}] {data['lcd_line1']} | {data['ctx_display']} | {data['cum_time']}")
            last_sent["key"] = key

        msg = json.dumps(data, ensure_ascii=False)
        sock.sendto(msg.encode("utf-8"), (UDP_IP, UDP_PORT))
        time.sleep(POLL)

except KeyboardInterrupt:
    print("\n已停止")
finally:
    sock.close()
