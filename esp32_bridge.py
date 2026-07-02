"""
Hermes → ESP32 实时桥接 (进程内回调 → UDP 广播)
=================================================
挂载到 AIAgent 的 callback 上，在 TUI 更新状态的同时推送：
- thinking_callback → working/idle + 颜文字
- clarify_callback → waiting
同时直接读取 agent.model / agent.session_total_tokens（准确，不依赖日志）
"""
import socket, json, time
from datetime import datetime, timezone

UDP_IP = "192.168.0.255"
UDP_PORT = 8888

_sock = None
_agent = None  # AIAgent 实例引用
_state = {"status": "idle", "last_sent": 0, "last_key": ""}


def _get_sock():
    global _sock
    if _sock is None:
        _sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    return _sock


def set_agent(agent):
    """cli.py 在创建 AIAgent 后调用，让桥接能读内部状态"""
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


def _read_agent():
    """从 agent 对象读取模型名和上下文（准确，不依赖日志）"""
    if _agent is None:
        return "unknown", 0
    model = getattr(_agent, "model", "unknown") or "unknown"
    tokens = getattr(_agent, "session_total_tokens", 0)
    return model, tokens


def wrap_thinking(original_callback):
    def wrapper(text: str):
        if original_callback:
            original_callback(text)

        model, ctx = _read_agent()
        if text and text.strip():
            kaomoji = text.split(" ")[0] if " " in text else text[:6]
            _send({"status": "working", "kaomoji": kaomoji,
                   "model": model, "context_len": ctx,
                   "timestamp": datetime.now(timezone.utc).isoformat()})
        else:
            _send({"status": "idle",
                   "model": model, "context_len": ctx,
                   "timestamp": datetime.now(timezone.utc).isoformat()})


def wrap_clarify(original_callback):
    def wrapper(*args, **kwargs):
        if original_callback:
            original_callback(*args, **kwargs)
        model, ctx = _read_agent()
        _send({"status": "waiting",
               "model": model, "context_len": ctx,
               "timestamp": datetime.now(timezone.utc).isoformat()})
