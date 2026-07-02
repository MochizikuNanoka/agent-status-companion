# -*- coding: utf-8 -*-
"""
Hermes → ESP32 UDP 推送 (内存版)
================================
读 Hermes TUI 写入的 hermes_state.json（TUI 每次刷新时写入）
数据直接从 Agent 内存读取，不依赖日志。
"""
import sys, re, os, json, time, socket, yaml
from pathlib import Path
from datetime import datetime, timezone

# ── 加载配置 ──────────────────────────────────────────
cfg_path = Path(__file__).parent / "config.yaml"
with open(cfg_path, 'r', encoding='utf-8') as f:
    cfg = yaml.safe_load(f)

# ── 找状态文件 ────────────────────────────────────────
STATE_FILE = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes/hermes_state.json"

# ── UDP 广播 ──────────────────────────────────────────
UDP_IP = cfg["udp"]["broadcast"]
UDP_PORT = cfg["udp"]["port"]
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

MAX_CTX = cfg["monitor"]["max_context"]
POLL_MS = 0.1  # 100ms

# ── 持久状态 ──────────────────────────────────────────
last_sent_key = ""

# ── 显示格式化 ────────────────────────────────────────
def fmt(template, vars):
    result = template
    for k, v in vars.items():
        result = result.replace("{" + k + "}", str(v))
    return result

def read_state():
    """读 hermes_state.json，返回 dict 或 None"""
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def build_payload(state):
    """从 TUI 状态构造 ESP32 JSON"""
    model = state.get("model_name", "unknown")
    ctx_len = state.get("context_tokens", 0)
    status = state.get("status", "idle")
    spinner = state.get("spinner", "")

    ctx_pct = min(100, int(ctx_len / MAX_CTX * 100)) if MAX_CTX else 0
    ctx_k = f"{ctx_len/1024:.1f}K" if ctx_len >= 1024 else str(ctx_len)
    kaomoji = cfg["kaomoji"].get(status, cfg["kaomoji"]["unknown"])
    sshort = cfg["status_short"].get(status, cfg["status_short"]["unknown"])

    # 如果有 spinner 文字，从中提取颜文字
    if spinner and " " in spinner:
        spi_kaomoji = spinner.split(" ")[0]
        if len(spi_kaomoji) < 10:
            kaomoji = spi_kaomoji

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

# ── 主循环 ────────────────────────────────────────────
if not STATE_FILE.exists():
    print(f"等待 Hermes 写入状态文件...")
    print(f"  路径: {STATE_FILE}")
    print(f"  提示: Hermes CLI 启动后会自动生成")
    while not STATE_FILE.exists():
        time.sleep(1)

print(f"⚡ 内存模式: {STATE_FILE}")
print(f"→ UDP {UDP_IP}:{UDP_PORT}")
print(f"→ 数据源: TUI 状态栏快照（内存直读）")
print()

try:
    while True:
        state = read_state()
        if state is None:
            time.sleep(POLL_MS)
            continue

        data = build_payload(state)
        key = f"{data['status']}|{data['ctx_display']}"

        if key != last_sent_key:
            cum = state.get("duration", "0s")
            print(f"[{data['status'].upper():7s}] {data['lcd_line1']} | {data['ctx_display']} | {cum}")
            last_sent_key = key

        msg = json.dumps(data, ensure_ascii=False)
        sock.sendto(msg.encode("utf-8"), (UDP_IP, UDP_PORT))
        time.sleep(POLL_MS)

except KeyboardInterrupt:
    print("\n已停止")
finally:
    sock.close()
