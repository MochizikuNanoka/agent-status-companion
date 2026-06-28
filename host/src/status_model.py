# -*- coding: utf-8 -*-
"""
状态数据模型模块

定义 Agent 状态枚举和 Pydantic 消息模型。
所有状态消息使用此模型进行序列化/反序列化。
"""

from enum import Enum
from pydantic import BaseModel
from typing import Optional


class AgentStatus(str, Enum):
    """Agent 运行状态枚举"""
    IDLE = "idle"          # 空闲
    WORKING = "working"    # 工作中
    WAITING = "waiting"    # 等待中（如等待工具返回）
    ERROR = "error"        # 出错


class StatusMessage(BaseModel):
    """
    状态消息模型

    通过 MQTT 或 WebSocket 传递的标准状态数据结构。
    """
    status: AgentStatus                    # 当前状态
    agent_name: str = "hermes"             # Agent 名称
    model: Optional[str] = None            # 当前使用的模型名
    task: Optional[str] = None             # 当前任务描述
    context_len: int = 0                   # 上下文 token 数
    cum_time: str = "0h"                   # 累计运行时间
    cpu_percent: float = 0.0               # CPU 使用率 (%)
    mem_mb: float = 0.0                    # 内存使用量 (MB)
