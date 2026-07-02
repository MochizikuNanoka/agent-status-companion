"""
Hermes → ESP32 实时桥接 (进程内回调 → UDP 广播)
=================================================
挂载到 AIAgent 的 thinking_callback / clarify_callback 上，
在 TUI 更新颜文字的同时推送状态到 ESP32 —— 毫秒级实时。
"""
import socket, json, time
from datetime import datetime, timezone

UDP_IP = "192.168.0.255"
UDP_PORT = 8888

_sock = None
_state = {"status": "idle", "last_sent": 0, "last_key": ""}


def _get_sock():
    global _sock
    if _sock is None:
        _sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    return _sock


def _send(data):
    """发 UDP，10Hz 限速"""
    now = time.time()
    key = f"{data['status']}|{data.get('kaomoji','')}"
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
    """包装 thinking_callback: 透传原回调 + 发 UDP"""

    def wrapper(text: str):
        if original_callback:
            original_callback(text)

        if text and text.strip():
            # 提取颜文字 (如 "(◔_◔) pondering..." → kaomoji="(◔_◔)")
            kaomoji = text.split(" ")[0] if " " in text else text[:6]
            _send({"status": "working", "kaomoji": kaomoji,
                   "timestamp": datetime.now(timezone.utc).isoformat()})
        else:
            _send({"status": "idle",
                   "timestamp": datetime.now(timezone.utc).isoformat()})

    return wrapper


def wrap_clarify(original_callback):
    """包装 clarify_callback: 透传原回调 + 发 UDP"""

    def wrapper(*args, **kwargs):
        if original_callback:
            original_callback(*args, **kwargs)
        _send({"status": "waiting",
               "timestamp": datetime.now(timezone.utc).isoformat()})

    return wrapper
