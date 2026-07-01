# -*- coding: utf-8 -*-
"""
Hermes → ESP32 UDP 推送
读 agent.log → 解析状态 → UDP 广播到 ESP32
"""
import sys, re, os, json, time, socket
from pathlib import Path
from datetime import datetime, timezone

# 找 agent.log
log_paths = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "hermes/logs/agent.log",
    Path.home() / ".hermes/logs/agent.log",
]
log_file = next((p for p in log_paths if p.exists()), None)
if not log_file:
    print("找不到 agent.log!"); sys.exit(1)

# UDP 配置
UDP_IP = "192.168.0.255"  # 广播
UDP_PORT = 8888

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

print(f"→ 监控 {log_file}")
print(f"→ UDP 广播 {UDP_IP}:{UDP_PORT}\n")

MODEL_RE = re.compile(r'model=([\w./-]+)')
TOTAL_RE = re.compile(r'total=(\d+)')

model = "unknown"
ctx_len = 0
last_status = None



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
    found_recent_api = False
    found_clarify = False

    for line in reversed(lines):
        m = MODEL_RE.search(line)
        if m: model = m.group(1)
        t = TOTAL_RE.search(line)
        if t: ctx_len = int(t.group(1))
        
        # 最近 5 秒有 API call → working
        if "agent.conversation_loop" in line:
            try:
                ts_str = line.split(",")[0].strip()
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                if (datetime.now() - ts).total_seconds() < 8:
                    found_recent_api = True
            except:
                found_recent_api = True
        
        # clarify 调用 → 标记为等待状态
        if "tool clarify" in line or "clarify completed" in line:
            found_clarify = True
            break  # 最近的操作是 clarify，不再往前看

    if found_recent_api:
        status = "working"
    elif found_clarify:
        # 最近操作是 clarify → 等待用户回复
        status = "waiting"

    # 上下文使用率
    max_ctx = 1000000  # 1M
    ctx_pct = min(100, int(ctx_len / max_ctx * 100))
    ctx_display = f"{ctx_len/1024:.1f}K" if ctx_len >= 1024 else str(ctx_len)
    cum = f"{ctx_pct}%"

    return {
        "status": status,
        "agent": "hermes",
        "model": model,
        "task_summary": "",
        "context_len": ctx_len,
        "cum_time": cum,
        "ctx_display": ctx_display,
        "cpu_percent": 0,
        "mem_mb": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

debounce_status = None
debounce_time = 0

try:
    while True:
        data = get_status()
        current = data["status"]
        now = time.time()
        
        # 防抖: A→B→A 在 0.5 秒内 → 忽略中间的 B
        if current != last_status:
            if debounce_status and debounce_status != current and now - debounce_time < 0.5:
                # 快速来回切换，忽略
                pass
            else:
                if debounce_status != current:
                    debounce_status = current
                    debounce_time = now
                icon = {"idle":"😴","working":"🔥","waiting":"⏳","error":"💥"}.get(current,"❓")
                print(f"{icon} [{current.upper()}] model={model} ctx={ctx_len//1024}K {data['cum_time']}")
                last_status = current

        msg = json.dumps(data, ensure_ascii=False)
        sock.sendto(msg.encode("utf-8"), (UDP_IP, UDP_PORT))
        time.sleep(1)

except KeyboardInterrupt:
    print("\n已停止")
finally:
    sock.close()
