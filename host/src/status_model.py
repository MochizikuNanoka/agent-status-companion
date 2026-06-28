# -*- coding: utf-8 -*-
"""
状态数据模型模块

定义 Agent 状态枚举和 Pydantic 消息模型（任务书_2 版本）。
字段名已更新：agent_name → agent, task → task_summary, 新增 timestamp。
"""

from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel
from typing import Optional


class AgentStatus(str, Enum):
    """Agent 运行状态枚举"""
    IDLE = "idle"          # 空闲
    WORKING = "working"    # 工作中
    WAITING = "waiting"    # 等待中（如等待工具返回）
    ERROR = "error"        # 出错


def _iso_timestamp() -> str:
    """生成当前时间的 ISO 8601 格式字符串（UTC）"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


class StatusMessage(BaseModel):
    """
    状态消息模型（任务书_2 版本）

    通过 MQTT 或 WebSocket 传递的标准状态数据结构。
    字段变更历史：
      - agent_name → agent
      - task → task_summary
      - 新增 timestamp（ISO 8601 格式，默认为当前 UTC 时间）
    """
    status: AgentStatus                         # 当前状态
    agent: str = "hermes"                       # Agent 名称（原 agent_name）
    model: Optional[str] = None                 # 当前使用的模型名
    task_summary: Optional[str] = None          # 当前任务描述（原 task）
    context_len: int = 0                        # 上下文 token 数
    cum_time: str = "0h"                        # 累计运行时间（字符串，如 "67m", "2.5h"）
    timestamp: str = _iso_timestamp()           # ISO 8601 时间戳（新增）
    cpu_percent: float = 0.0                    # CPU 使用率 (%)
    mem_mb: float = 0.0                         # 内存使用量 (MB)
