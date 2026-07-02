"""ESP32 Status Plugin: post_tool_call 钩子检测 clarify → UDP waiting"""
import socket, json, time
from datetime import datetime, timezone

UDP_IP = "192.168.0.255"
UDP_PORT = 8888
_sock = None
_last = 0


def _send(data):
    global _last
    now = time.time()
    if now - _last < 0.5:
        return
    _last = now
    try:
        global _sock
        if _sock is None:
            _sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            _sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        msg = json.dumps(data, ensure_ascii=False)
        _sock.sendto(msg.encode("utf-8"), (UDP_IP, UDP_PORT))
    except Exception:
        pass


def _on_post_tool_call(tool_name, **kwargs):
    if tool_name == "clarify":
        _send({"status": "waiting",
               "timestamp": datetime.now(timezone.utc).isoformat()})


def register(ctx):
    ctx.register_hook("post_tool_call", _on_post_tool_call)
