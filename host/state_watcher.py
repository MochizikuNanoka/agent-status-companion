#!/usr/bin/env python3
"""
Hermes Agent 状态监控后端 v2
Reads hermes_state.json (written by esp32-companion plugin) and displays/forwards agent status.

Usage:
  python state_watcher.py              # 终端面板（持续刷新）
  python state_watcher.py --json       # JSON 行输出
  python state_watcher.py --once       # 单次查询后退出
  python state_watcher.py --udp        # UDP 广播 → ESP32 桌面伴侣

状态文件: %LOCALAPPDATA%/hermes/hermes_state.json
数据来源: esp32-companion Hermes 插件（plugin hooks）
"""

import json
import os
import socket
import sys
import time
from pathlib import Path

# ── ANSI ───────────────────────────────────────────────────────────────
C = {
    "reset": "\033[0m",      "bold": "\033[1m",      "dim": "\033[2m",
    "thinking": "\033[38;5;226m",  "working": "\033[38;5;46m",
    "waiting": "\033[38;5;208m",   "idle": "\033[38;5;245m",
}

ICON = {"thinking": "(..*)", "working": "(>_<)", "waiting": "(o_o)", "idle": "(^-^)"}

# ── State file ─────────────────────────────────────────────────────────

def state_file():
    return Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "hermes_state.json"

def read_state():
    sf = state_file()
    if not sf.exists():
        return None
    try:
        return json.loads(sf.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

def fmt_dur(s):
    if s < 60:       return f"{int(s)}s"
    h, r = divmod(int(s), 3600)
    m, sec = divmod(r, 60)
    if h:            return f"{h}h{m:02d}m"
    return f"{m}m{sec:02d}s"

# ── Display format (terminal) ──────────────────────────────────────────

def display_pretty(st):
    s = st.get("status", "idle")
    print(f"\n{C['bold']}╔══════ Hermes Agent ══════╗{C['reset']}")
    print(f"{C['bold']}║{C['reset']} {ICON[s]} {C.get(s,'')}{C['bold']}{s.upper():<14}{C['reset']}{C['bold']}║{C['reset']}")
    print(f"{C['bold']}╠══════════════════════════╣{C['reset']}")
    print(f"{C['bold']}║{C['reset']} Model: {st.get('model','?'):<18}{C['bold']}║{C['reset']}")
    print(f"{C['bold']}║{C['reset']} Tool:  {(st.get('tool_name','') or '-'):<18}{C['bold']}║{C['reset']}")
    print(f"{C['bold']}║{C['reset']} Turns: {st.get('iteration',0):>3} calls{' '*9}{C['bold']}║{C['reset']}")
    print(f"{C['bold']}║{C['reset']} Up:    {fmt_dur(st.get('session_duration_s',0)):<18}{C['bold']}║{C['reset']}")
    print(f"{C['bold']}╚══════════════════════════╝{C['reset']}")
    print(f"  {C['dim']}{st.get('updated_at','?')}{C['reset']}\n")

def display_json(st):
    print(json.dumps(st, ensure_ascii=False))

# ── ESP32 display format ───────────────────────────────────────────────

def _fmt_ctx(kb):
    """Format context length for compact display."""
    if kb >= 1000:
        return f"{kb/1000:.0f}k"
    return f"{kb/1:.0f}"

def build_esp32_display(st):
    """Convert plugin state JSON → ESP32 display JSON.

    ESP32 firmware expects: oled_line1, oled_line2, lcd_line1, ctx_display,
    status, model, cum_time, context_len.
    """
    status = st.get("status", "idle")
    model = st.get("model", "?")
    tool = st.get("tool_name", "") or ""
    dur = fmt_dur(st.get("session_duration_s", 0))

    # Kaomoji + status label
    short = {"thinking": "Think", "working": "Busy", "waiting": "Wait", "idle": "Zzzz"}
    kaomoji = ICON.get(status, "(._.)")
    label = short.get(status, status)

    # OLED (64×32, 4 lines of 10 chars)
    oled_line1 = model[:10]                          # model name
    oled_line2 = f"{kaomoji} {label}"                # kaomoji + status

    # LCD 1602 (16×2)
    lcd_line1 = f"{kaomoji} {label:<10}"             # "(>_<) Busy     "
    if tool:
        ctx_display = f"{dur} {tool[:6]}"              # "5m30s termin"
    else:
        ctx_display = dur                              # "5m30s"

    return {
        "status":      status,
        "agent":       "hermes",
        "model":       model,
        "task_summary": tool,
        "context_len":  st.get("context_len", 0),
        "cum_time":    dur,
        "cpu_percent":  0,
        "mem_mb":       0,
        "timestamp":   st.get("updated_at", ""),
        # ESP32 显示专用字段
        "oled_line1": oled_line1,
        "oled_line2": oled_line2,
        "lcd_line1":  lcd_line1,
        "ctx_display": ctx_display,
    }

# ── UDP broadcast ──────────────────────────────────────────────────────

def udp_send(data, host="255.255.255.255", port=8888):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.1)
        sock.sendto(json.dumps(data, ensure_ascii=False).encode(), (host, port))
        sock.close()
    except Exception:
        pass

# ── Main ───────────────────────────────────────────────────────────────

def watch(*, once=False, json_mode=False, udp_mode=False):
    if once:
        st = read_state()
        if st is None:
            print("No state file. Is esp32-companion plugin enabled?", file=sys.stderr)
            sys.exit(1)
        if json_mode:
            display_json(st)
        else:
            display_pretty(st)
        return

    last_status = None
    last_iter = -1
    if not json_mode and not udp_mode:
        print(f"{C['dim']}Watching {state_file()}... Ctrl+C to exit{C['reset']}")

    while True:
        st = read_state()
        if st is None:
            time.sleep(1)
            continue

        cur_status = st.get("status", "idle")
        cur_iter = st.get("iteration", 0)

        if cur_status != last_status or cur_iter != last_iter:
            if udp_mode:
                esp32_data = build_esp32_display(st)
                udp_send(esp32_data)
                # Also print locally so user sees what's being sent
                icon = ICON.get(cur_status, "?")
                print(f"  UDP → {icon} {cur_status.upper():<8} {esp32_data['oled_line1']}")
            elif json_mode:
                display_json(st)
            else:
                display_pretty(st)
            last_status = cur_status
            last_iter = cur_iter

        time.sleep(0.3)


if __name__ == "__main__":
    watch(
        once="--once" in sys.argv,
        json_mode="--json" in sys.argv,
        udp_mode="--udp" in sys.argv,
    )
