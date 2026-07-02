"""
Hermes → ESP32 实时桥接 (进程内回调 → UDP 广播)
=================================================
- thinking_callback → working/idle (毫秒级)
- agent.clarify_callback 包装 → waiting (clarify 工具调用即刻触发)
- 模型名和上下文直接从 agent 对象读取
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
    if _agent is None:
        return "unknown", 0
    model = getattr(_agent, "model", "unknown") or "unknown"
    tokens = getattr(_agent, "session_total_tokens", 0)
    return model, tokens


def set_agent(agent):
    global _agent
    _agent = agent
    # 包装 clarify_callback：clarify 工具调用时立刻推 waiting
    _orig = getattr(agent, "clarify_callback", None)
    if _orig:
        def _clarify_wrapped(question, choices):
            model, ctx = _read_agent()
            _send({"status": "waiting",
                   "model": model, "context_len": ctx,
                   "timestamp": datetime.now(timezone.utc).isoformat()})
            return _orig(question, choices)
        agent.clarify_callback = _clarify_wrapped


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

    return wrapper
