#!/usr/bin/env python3
"""
Hermes Agent 状态监控后端 v2
Reads hermes_state.json (written by esp32-companion plugin) and displays agent status.

Usage:
  python state_watcher.py              # 终端可视化（默认，持续刷新）
  python state_watcher.py --json       # JSON 行输出（管道给其他程序）
  python state_watcher.py --once       # 单次查询后退出
  python state_watcher.py --udp        # UDP 广播模式（推送到 ESP32）

状态文件: %LOCALAPPDATA%/hermes/hermes_state.json
数据来源: esp32-companion Hermes 插件（plugin hooks，非 monkey-patch）
"""

import json
import os
import socket
import sys
import time
from pathlib import Path

# ── ANSI colors ────────────────────────────────────────────────────────
C = {
    "reset": "\033[0m",
    "bold":  "\033[1m",
    "dim":   "\033[2m",
    "thinking": "\033[38;5;226m",  # yellow
    "working":  "\033[38;5;46m",   # green
    "waiting":  "\033[38;5;208m",  # orange
    "idle":     "\033[38;5;245m",  # gray
}

ICON = {
    "thinking": "(..*)  ",
    "working":  "(>_<)  ",
    "waiting":  "(o_o)? ",
    "idle":     "(^-^)  ",
}

# ── State file ─────────────────────────────────────────────────────────

def state_file() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "hermes_state.json"


def read_state() -> dict | None:
    sf = state_file()
    if not sf.exists():
        return None
    try:
        return json.loads(sf.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    h, r = divmod(int(seconds), 3600)
    m, s = divmod(r, 60)
    if h:
        return f"{h}h{m:02d}m"
    return f"{m}m{s:02d}s"


# ── Display modes ──────────────────────────────────────────────────────

def display_pretty(state: dict):
    status = state.get("status", "idle")
    color = C.get(status, "")
    icon = ICON.get(status, "")

    print(f"\n{C['bold']}╔══════ Hermes Agent ══════╗{C['reset']}")
    print(f"{C['bold']}║{C['reset']} {icon}{color}{C['bold']}{status.upper():<15}{C['reset']}{C['bold']}║{C['reset']}")
    print(f"{C['bold']}╠══════════════════════════╣{C['reset']}")
    model = state.get("model", "?")
    tool = state.get("tool_name", "") or "-"
    print(f"{C['bold']}║{C['reset']} Model: {model:<18}{C['bold']}║{C['reset']}")
    print(f"{C['bold']}║{C['reset']} Tool:  {tool:<18}{C['bold']}║{C['reset']}")
    print(f"{C['bold']}║{C['reset']} Turns: {state.get('iteration', 0):>3} calls{'>15'}{C['bold']}║{C['reset']}")
    dur = format_duration(state.get("session_duration_s", 0))
    print(f"{C['bold']}║{C['reset']} Uptime:{dur:>17}{C['bold']}║{C['reset']}")
    print(f"{C['bold']}╚══════════════════════════╝{C['reset']}")
    print(f"  {C['dim']}{state.get('updated_at', '?')}{C['reset']}\n")


def display_json(state: dict):
    print(json.dumps(state, ensure_ascii=False))


# ── UDP broadcast ──────────────────────────────────────────────────────

def udp_broadcast(state: dict, host: str = "255.255.255.255", port: int = 8888):
    """Send state as JSON over UDP broadcast (for ESP32 companion device)."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.1)
        data = json.dumps(state, ensure_ascii=False).encode("utf-8")
        sock.sendto(data, (host, port))
        sock.close()
    except Exception:
        pass


# ── Main loop ──────────────────────────────────────────────────────────

def watch(*, once: bool = False, json_mode: bool = False, udp_mode: bool = False,
          udp_host: str = "255.255.255.255", udp_port: int = 8888):
    if once:
        state = read_state()
        if state is None:
            print("No state file. Is esp32-companion plugin enabled?", file=sys.stderr)
            sys.exit(1)
        if json_mode:
            display_json(state)
        else:
            display_pretty(state)
        return

    last_status = None
    last_iteration = -1
    if not json_mode and not udp_mode:
        print(f"{C['dim']}Watching {state_file()}... Ctrl+C to exit{C['reset']}")

    while True:
        state = read_state()
        if state is None:
            time.sleep(1)
            continue

        current_status = state.get("status", "idle")
        current_iter = state.get("iteration", 0)

        if current_status != last_status or current_iter != last_iteration:
            if udp_mode:
                udp_broadcast(state, udp_host, udp_port)
            elif json_mode:
                display_json(state)
            else:
                display_pretty(state)
            last_status = current_status
            last_iteration = current_iter

        time.sleep(0.3)


if __name__ == "__main__":
    watch(
        once="--once" in sys.argv,
        json_mode="--json" in sys.argv,
        udp_mode="--udp" in sys.argv,
    )
