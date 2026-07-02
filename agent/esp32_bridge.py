"""
Hermes → ESP32 实时桥接 (进程内回调 → UDP 广播)
=================================================
挂在 thinking_callback 上，在 TUI 更新颜文字的同时推送 working/idle。
模型名和上下文直接从 agent 对象读取（准确，不依赖日志）。
waiting 状态和格式化显示由 push_to_esp32.py 补充。
"""
import socket, json, time
from datetime import datetime, timezone

UDP_IP = "192.168.0.255"
UDP_PORT = 8888

_sock = None
_agent = None
_state = {"status": "idle", "last_sent": 0, "last_key": ""}


def _get_sock():
    global _sock
    if _sock is None:
        _sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    return _sock


def set_agent(agent):
    global _agent
    _agent = agent


def _send(data):
    now = time.time()
    key = f"{data['status']}|{data.get('kaomoji','')}|{data.get('context_len',0)}"
    if key == _state["last_key"] and now - _state["last_sent"] < 0.1:
        return
    _state["last_key"] = key
    _state["last_sent"] = now
    try:
        msg = json.dumps(data, ensure_ascii=False)
        _get_sock().sendto(msg.encode("utf-8"), (UDP_IP, UDP_PORT))
    except Exception:
        pass


def wrap_thinking(original_callback):
    def wrapper(text: str):
        if original_callback:
            original_callback(text)

        model = getattr(_agent, "model", "unknown") or "unknown" if _agent else "unknown"
        ctx = getattr(_agent, "session_total_tokens", 0) if _agent else 0

        if text and text.strip():
            kaomoji = text.split(" ")[0] if " " in text else text[:6]
            _send({"status": "working", "kaomoji": kaomoji,
                   "model": model, "context_len": ctx,
                   "timestamp": datetime.now(timezone.utc).isoformat()})
        else:
            _send({"status": "idle",
                   "model": model, "context_len": ctx,
                   "timestamp": datetime.now(timezone.utc).isoformat()})

    return wrapper
