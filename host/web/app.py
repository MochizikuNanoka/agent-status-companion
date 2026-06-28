# -*- coding: utf-8 -*-
"""
FastAPI Web 面板模块

提供状态仪表盘的 HTTP API 和 WebSocket 实时推送。
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

# src 在包外，需要特殊处理
try:
    from ..src.status_model import StatusMessage
except ImportError:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.status_model import StatusMessage

logger = logging.getLogger(__name__)

# FastAPI 应用实例
app = FastAPI(
    title="Hermes Agent Status Dashboard",
    description="实时查看 Hermes Agent 运行状态",
    version="1.0.0",
)

# 全局引用：启动时由 start_web_server 注入
_aggregator = None
_web_sockets: list[WebSocket] = []


# ---- API 路由 ----

@app.get("/api/status", response_model=StatusMessage)
async def get_status():
    """
    获取当前状态快照

    Returns:
        StatusMessage JSON 格式的当前状态
    """
    if _aggregator is None:
        return StatusMessage(status="idle", agent_name="hermes", task="服务未就绪")
    latest = _aggregator.get_latest_status()
    if latest is None:
        return StatusMessage(status="idle", agent_name="hermes", task="等待首次轮询")
    return latest


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket 实时状态推送

    客户端连接后，服务端在状态变更时自动推送。
    """
    await websocket.accept()
    _web_sockets.append(websocket)
    logger.info("WebSocket 客户端已连接 (共 %d 个)", len(_web_sockets))

    try:
        # 发送当前状态作为初始消息
        if _aggregator:
            latest = _aggregator.get_latest_status()
            if latest:
                await websocket.send_text(latest.model_dump_json())

        # 保持连接，等待关闭
        while True:
            try:
                data = await websocket.receive_text()
                # 客户端发来的心跳/ping，可选处理
                if data == "ping":
                    await websocket.send_text("pong")
            except WebSocketDisconnect:
                break
    except Exception as e:
        logger.debug("WebSocket 连接异常: %s", e)
    finally:
        if websocket in _web_sockets:
            _web_sockets.remove(websocket)
        logger.info("WebSocket 客户端已断开 (剩余 %d 个)", len(_web_sockets))


# ---- 静态页面 ----

# 获取 host/web/static 目录路径
_STATIC_DIR = Path(__file__).parent / "static"


@app.get("/", response_class=HTMLResponse)
async def index():
    """仪表盘首页"""
    index_path = _STATIC_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>仪表盘页面未找到</h1>", status_code=404)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """网站图标"""
    favicon_path = _STATIC_DIR / "favicon.ico"
    if favicon_path.exists():
        return FileResponse(favicon_path)
    return HTMLResponse(status_code=204)


# ---- 广播函数 ----

async def broadcast_status(message: StatusMessage) -> None:
    """
    向所有连接的 WebSocket 客户端广播状态

    Args:
        message: 状态消息
    """
    payload = message.model_dump_json()
    dead_sockets: list[WebSocket] = []

    for ws in _web_sockets:
        try:
            await ws.send_text(payload)
        except Exception:
            dead_sockets.append(ws)

    # 清理断开的连接
    for ws in dead_sockets:
        if ws in _web_sockets:
            _web_sockets.remove(ws)

    if dead_sockets:
        logger.debug("清理了 %d 个断开的 WebSocket", len(dead_sockets))


def _on_status_change(message: StatusMessage) -> None:
    """
    状态变更回调（由聚合器在后台线程调用）

    使用 asyncio.run_coroutine_threadsafe 在事件循环中执行广播。
    """
    import asyncio
    loop = _get_event_loop()
    if loop and loop.is_running():
        asyncio.run_coroutine_threadsafe(broadcast_status(message), loop)


def _get_event_loop():
    """获取当前运行的事件循环"""
    try:
        import asyncio
        return asyncio.get_event_loop()
    except RuntimeError:
        return None


# ---- 服务器启动 ----

def start_web_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    aggregator=None,
) -> None:
    """
    启动 FastAPI Web 服务器（阻塞）

    通过 uvicorn 运行，并在启动后注册聚合器的状态回调。

    Args:
        host: 绑定地址
        port: 监听端口
        aggregator: StatusAggregator 实例
    """
    global _aggregator

    # 注入聚合器引用
    _aggregator = aggregator
    if _aggregator:
        _aggregator.subscribe(_on_status_change)

    import uvicorn

    logger.info("启动 Web 面板: http://%s:%d", host, port)
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=True,
    )
