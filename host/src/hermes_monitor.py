# -*- coding: utf-8 -*-
"""
Hermes Agent 监控器模块

通过 psutil 查找 hermes.exe 进程，
并读取日志文件获取当前使用的模型和任务信息。
"""

import os
import re
import logging
from pathlib import Path
from typing import Optional

import psutil

from .status_model import StatusMessage, AgentStatus

logger = logging.getLogger(__name__)


class HermesMonitor:
    """
    Hermes Agent 进程监控器

    定期检查 Hermes Agent 进程状态，
    读取日志获取模型和任务信息。
    """

    # 提取模型名称的正则模式
    _MODEL_PATTERN = re.compile(
        r'(?:model|Model|MODEL)[=:\s]+"?([a-zA-Z0-9_./\-]+)"?'
    )
    # 提取任务描述的正则模式
    _TASK_PATTERN = re.compile(
        r'(?:task|Task|TASK|request|Request)[=:\s]+"?([^"\n]+)"?'
    )
    # 提取上下文字数的正则模式
    _CTX_PATTERN = re.compile(
        r'(?:context|Context|ctx|tokens?)[=:\s]+"?(\d+)"?'
    )

    def __init__(self, log_path: Optional[Path] = None, log_file: str = "hermes.log"):
        """
        初始化监控器

        Args:
            log_path: Hermes 日志目录路径
            log_file: 日志文件名
        """
        self.log_path = Path(log_path) if log_path else (
            Path.home() / "AppData" / "Local" / "hermes" / "logs"
        )
        self.log_file = log_file
        self._last_status: Optional[AgentStatus] = None
        self._last_task: Optional[str] = None

    def get_status(self) -> StatusMessage:
        """
        获取当前 Agent 状态

        扫描进程列表查找 hermes.exe，
        如果找到则分析日志获取详细信息。

        Returns:
            StatusMessage 当前状态消息
        """
        hermes_process = self._find_hermes_process()

        if hermes_process is None:
            # 进程不存在 → IDLE
            return StatusMessage(
                status=AgentStatus.IDLE,
                agent_name="hermes",
                task="未检测到 Hermes Agent 进程",
            )

        # 获取进程 CPU/内存
        try:
            cpu_percent = hermes_process.cpu_percent(interval=0.1)
            mem_info = hermes_process.memory_info()
            mem_mb = mem_info.rss / (1024 * 1024)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            cpu_percent = 0.0
            mem_mb = 0.0

        # 读取日志获取模型/任务
        model, task, context_len = self._parse_log()

        # 根据 task 判断状态
        status = self._infer_status(task)

        return StatusMessage(
            status=status,
            agent_name="hermes",
            model=model,
            task=task,
            context_len=context_len,
            cpu_percent=round(cpu_percent, 1),
            mem_mb=round(mem_mb, 1),
        )

    def _find_hermes_process(self) -> Optional[psutil.Process]:
        """
        查找 hermes.exe 进程

        Returns:
            psutil.Process 对象，未找到返回 None
        """
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                name = proc.info.get("name", "") or ""
                exe = proc.info.get("exe", "") or ""
                if "hermes" in name.lower() or "hermes" in exe.lower():
                    return proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    def _parse_log(self) -> tuple[Optional[str], Optional[str], int]:
        """
        解析 Hermes 日志文件

        读取最新的日志行，提取 model、task 和 context_len。

        Returns:
            (model, task, context_len) 元组
        """
        log_file_path = self.log_path / self.log_file

        if not log_file_path.exists():
            logger.debug("日志文件不存在: %s", log_file_path)
            return (None, None, 0)

        try:
            # 读取最后 100 行（约 4KB）
            with open(log_file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[-100:]
        except Exception as e:
            logger.warning("读取日志文件失败: %s", e)
            return (None, None, 0)

        content = "\n".join(lines)

        model = self._extract_first(self._MODEL_PATTERN, content)
        task = self._extract_first(self._TASK_PATTERN, content)
        context_len = self._extract_int(self._CTX_PATTERN, content)

        return (model, task, context_len)

    def _infer_status(self, task: Optional[str]) -> AgentStatus:
        """
        根据任务信息推断 Agent 状态

        Args:
            task: 当前任务描述

        Returns:
            AgentStatus 枚举值
        """
        if not task:
            return AgentStatus.IDLE

        task_lower = task.lower()

        # 等待状态关键词
        waiting_keywords = [
            "等待", "waiting", "thinking", "思考",
            "running tool", "执行工具", "tool call",
        ]
        for kw in waiting_keywords:
            if kw in task_lower:
                return AgentStatus.WAITING

        # 错误状态关键词
        error_keywords = [
            "错误", "error", "失败", "failed",
            "exception", "异常",
        ]
        for kw in error_keywords:
            if kw in task_lower:
                return AgentStatus.ERROR

        return AgentStatus.WORKING

    @staticmethod
    def _extract_first(pattern: re.Pattern, text: str) -> Optional[str]:
        """提取第一个匹配的值"""
        match = pattern.search(text)
        return match.group(1).strip() if match else None

    @staticmethod
    def _extract_int(pattern: re.Pattern, text: str) -> int:
        """提取第一个匹配的整数"""
        match = pattern.search(text)
        return int(match.group(1)) if match else 0
