"""
esp32-companion — Hermes plugin for real-time agent state tracking.

Tracks Hermes lifecycle via plugin hooks and writes a state JSON file:
  %LOCALAPPDATA%/hermes/hermes_state.json

States:
  thinking  — LLM is generating (pre_llm_call → post_llm_call window)
  working   — Tool is executing (pre_tool_call → post_tool_call window)
  waiting   — Hermes called clarify tool (needs user input)
  idle      — No activity (post_llm_call, on_session_start, on_session_end)

Consumers: ESP32 companion device, desktop dashboard, any watcher

Activation: hermes plugins enable esp32-companion
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

# ── State ──────────────────────────────────────────────────────────────
_lock = threading.Lock()
_state = {
    "status": "idle",           # thinking | working | waiting | idle
    "model": "",
    "session_id": "",
    "platform": "",
    "tool_name": "",            # current tool being executed
    "context_len": 0,           # from pre_llm_call
    "iteration": 0,             # tool call count this turn
    "started_at": "",           # session start ISO timestamp
    "updated_at": "",           # last update ISO timestamp
    "session_duration_s": 0.0,  # seconds since session start
    "is_first_turn": True,
}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _state_file() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "hermes_state.json"


def _write_state():
    """Write current state to JSON file atomically."""
    try:
        state_file = _state_file()
        state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = state_file.with_suffix(".tmp")
        with _lock:
            _state["updated_at"] = _now()
            # Calculate session duration
            if _state["started_at"]:
                try:
                    start = time.mktime(time.strptime(
                        _state["started_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                    _state["session_duration_s"] = time.time() - start
                except (ValueError, OSError):
                    pass
            payload = json.dumps(_state, ensure_ascii=False, indent=2)
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(state_file)
    except Exception:
        pass  # Fail silently — never crash Hermes


# ── Hook handlers ──────────────────────────────────────────────────────

def _on_pre_llm_call(*, session_id: str = "", model: str = "",
                      platform: str = "", is_first_turn: bool = False,
                      **kwargs) -> None:
    """LLM is about to start generating → thinking."""
    with _lock:
        _state["status"] = "thinking"
        _state["model"] = model
        _state["session_id"] = session_id
        _state["platform"] = platform
        _state["tool_name"] = ""
        _state["iteration"] = 0
        _state["is_first_turn"] = is_first_turn
        if not _state["started_at"]:
            _state["started_at"] = _now()
    _write_state()


def _on_pre_tool_call(*, tool_name: str = "", **kwargs) -> None:
    """Tool is about to execute → working (or waiting if clarify)."""
    with _lock:
        _state["tool_name"] = tool_name
        _state["iteration"] += 1
        if tool_name == "clarify":
            _state["status"] = "waiting"
        else:
            _state["status"] = "working"
    _write_state()


def _on_post_tool_call(*, tool_name: str = "", **kwargs) -> None:
    """Tool finished → back to thinking (LLM will process result next)."""
    # Don't change status here — LLM may immediately make another call.
    # The next pre_llm_call or post_llm_call will set the correct state.
    with _lock:
        if _state["tool_name"] == tool_name:
            _state["tool_name"] = ""
    _write_state()


def _on_post_llm_call(*, assistant_response: str = "",
                       session_id: str = "", model: str = "",
                       platform: str = "", **kwargs) -> None:
    """LLM finished generating final response → idle."""
    resp_len = len(assistant_response or "")
    with _lock:
        # If clarify was called and now we have a response, we're idle
        if _state.get("status") == "waiting":
            pass  # Stay waiting — user still needs to respond
        else:
            _state["status"] = "idle"
        _state["tool_name"] = ""
        _state["context_len"] = resp_len
    _write_state()


def _on_session_start(*, session_id: str = "", model: str = "",
                       platform: str = "", **kwargs) -> None:
    """New session created."""
    with _lock:
        _state["status"] = "idle"
        _state["session_id"] = session_id
        _state["model"] = model
        _state["platform"] = platform
        _state["tool_name"] = ""
        _state["iteration"] = 0
        _state["started_at"] = _now()
        _state["is_first_turn"] = True
    _write_state()


def _on_session_end(*, session_id: str = "", completed: bool = False,
                     interrupted: bool = False, **kwargs) -> None:
    """Session ended."""
    with _lock:
        _state["status"] = "idle"
        _state["tool_name"] = ""
    _write_state()


# ── Plugin entrypoint ──────────────────────────────────────────────────

def register(ctx) -> None:
    """Register all lifecycle hooks."""
    ctx.register_hook("pre_llm_call", _on_pre_llm_call)
    ctx.register_hook("post_llm_call", _on_post_llm_call)
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
    ctx.register_hook("post_tool_call", _on_post_tool_call)
    ctx.register_hook("on_session_start", _on_session_start)
    ctx.register_hook("on_session_end", _on_session_end)
