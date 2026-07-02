"""Hermes Agent 状态监控 — 快捷启动器
双击运行，自动启动 UDP 广播到 ESP32 (192.168.0.100:8888)
"""
import subprocess, sys, os

WATCHER = r"D:\Desktop\AI agent\agent-status-companion\host\state_watcher.py"
ESP32_IP = "192.168.0.100"

def main():
    print("Starting Hermes Agent Monitor...")
    print(f"Target: ESP32 @ {ESP32_IP}:8888")
    print("Press Ctrl+C to stop\n")
    subprocess.run([sys.executable, WATCHER, "--udp", "--esp32-ip", ESP32_IP])

if __name__ == "__main__":
    main()
