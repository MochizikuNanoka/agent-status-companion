# -*- coding: utf-8 -*-
"""
ESP32 虚拟设备模拟器

模拟 ESP32 固件行为：从串口读取 JSON 状态消息，
打印到控制台模拟 OLED/LED 变化。
配合 COM10↔COM11 虚拟串口对使用。

用法:
    python esp32_simulator.py COM10
    python esp32_simulator.py COM10 --baud 115200
"""

import sys
import json
import time
import argparse
from datetime import datetime

import serial


# ANSI 颜色
GREEN  = "\033[92m"
BLUE   = "\033[94m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


def status_color(status: str) -> str:
    """状态对应的颜色"""
    return {
        "idle":    GREEN,
        "working": BLUE,
        "waiting": YELLOW,
        "error":   RED,
    }.get(status, RESET)


def status_icon(status: str) -> str:
    """状态图标"""
    return {
        "idle":    "🟢",
        "working": "🔵",
        "waiting": "🟡",
        "error":   "🔴",
    }.get(status, "⚪")


def print_banner():
    """打印启动横幅"""
    print(f"""
{BOLD}{CYAN}╔══════════════════════════════════════════╗
║   ESP32 Simulator — Agent Status Companion ║
║   Virtual Device (Python)                  ║
╚══════════════════════════════════════════╝{RESET}
""")


def print_status(data: dict):
    """模拟 OLED 显示"""
    status  = data.get("status", "idle")
    agent   = data.get("agent", "hermes")
    model   = data.get("model", "unknown")
    task    = data.get("task_summary", "")
    ctx     = data.get("context_len", 0)
    ctime   = data.get("cum_time", "0s")
    cpu     = data.get("cpu_percent", 0)
    mem     = data.get("mem_mb", 0)
    ts      = data.get("timestamp", "")

    color = status_color(status)
    icon  = status_icon(status)

    # 清屏 + OLED 模拟
    print(f"\n{CYAN}┌──────────────────────────────────┐{RESET}")
    print(f"{CYAN}│{RESET} {BOLD}{agent}{RESET} {icon}  {color}{status.upper()}{RESET}")
    print(f"{CYAN}│{RESET} Model: {model[:20]}")
    print(f"{CYAN}│{RESET} Task:  {task[:28]}")
    print(f"{CYAN}│{RESET} Ctx: {ctx/1024:.0f}K  Time: {ctime}")
    print(f"{CYAN}│{RESET} CPU: {cpu:.0f}%  Mem: {mem:.0f}MB")
    if ts:
        print(f"{CYAN}│{RESET} {ts[:19]}")
    print(f"{CYAN}└──────────────────────────────────┘{RESET}")

    # LED 效果模拟
    led_colors = {
        "idle":    f"{GREEN}● LED: 绿色常亮{RESET}",
        "working": f"{BLUE}● LED: 蓝色呼吸{RESET}",
        "waiting": f"{YELLOW}● LED: 橙色呼吸{RESET}",
        "error":   f"{RED}● LED: 红色闪烁{RESET}",
    }
    print(f"  {led_colors.get(status, '● LED: 未知')}")
    print()


def main():
    parser = argparse.ArgumentParser(description="ESP32 虚拟设备模拟器")
    parser.add_argument("port", help="串口名称 (如 COM10)")
    parser.add_argument("--baud", type=int, default=115200, help="波特率 (默认 115200)")
    args = parser.parse_args()

    print_banner()

    try:
        ser = serial.Serial(args.port, args.baud, timeout=1)
        print(f"{GREEN}[SIM] 串口 {args.port} 已打开 @ {args.baud} baud{RESET}")
        print(f"{CYAN}[SIM] 等待主机发送 JSON 状态消息...{RESET}")
        print(f"{CYAN}[SIM] 按 Ctrl+C 退出{RESET}")
        print()
    except serial.SerialException as e:
        print(f"{RED}[SIM] 无法打开串口 {args.port}: {e}{RESET}")
        print(f"{YELLOW}提示: 确认 {args.port} 未被其他程序占用{RESET}")
        sys.exit(1)

    line_count = 0
    try:
        while True:
            line = ser.readline()
            if not line:
                continue

            line = line.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            line_count += 1
            timestamp = datetime.now().strftime("%H:%M:%S")

            # 尝试解析 JSON
            try:
                data = json.loads(line)
                status = data.get("status", "?")
                print(f"{CYAN}[{timestamp}] #{line_count} 收到状态: {status_color(status)}{status}{RESET}")
                print_status(data)
            except json.JSONDecodeError:
                print(f"{YELLOW}[{timestamp}] 收到非 JSON: {line[:60]}{RESET}")

    except KeyboardInterrupt:
        print(f"\n{GREEN}[SIM] 模拟器已停止，共收到 {line_count} 条消息{RESET}")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
