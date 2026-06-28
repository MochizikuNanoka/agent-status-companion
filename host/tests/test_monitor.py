# -*- coding: utf-8 -*-
"""Hermes 监控器测试（适配任务书_2：日志解析、模拟模式、新字段名）"""

import json
import time
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, PropertyMock

from src.status_model import StatusMessage, AgentStatus
from src.hermes_monitor import (
    HermesMonitor,
    _LOG_API_CALL_PATTERN,
    _now_iso,
)


# ============================================================
# 日志解析正则测试
# ============================================================

class TestLogParsingRegex:
    """agent.log API call 行正则解析测试"""

    def test_parse_api_call_line(self):
        """解析完整的 API call 日志行"""
        line = (
            "2026-06-29 06:29:04,461 INFO [20260629_055232_7126c1] "
            "agent.conversation_loop: API call #60: "
            "model=deepseek-v4-pro provider=deepseek "
            "in=65171 out=718 total=65889 latency=6.9s cache=64256/65171 (99%)"
        )
        m = _LOG_API_CALL_PATTERN.search(line)
        assert m is not None
        assert m.group("session_id") == "20260629_055232_7126c1"
        assert m.group("model") == "deepseek-v4-pro"
        assert m.group("provider") == "deepseek"
        assert m.group("context_len") == "65889"

    def test_parse_api_call_without_provider(self):
        """解析没有 provider 字段的日志行"""
        line = (
            "2026-06-29 07:00:00,000 INFO [20260629_070000_abc123] "
            "agent.conversation_loop: API call #1: "
            "model=gpt-4o in=100 out=50 total=150"
        )
        m = _LOG_API_CALL_PATTERN.search(line)
        assert m is not None
        assert m.group("session_id") == "20260629_070000_abc123"
        assert m.group("model") == "gpt-4o"
        assert m.group("provider") is None  # 可选的 provider
        assert m.group("context_len") == "150"

    def test_parse_claude_model(self):
        """解析 Claude 模型名（含点号和横线）"""
        line = (
            "2026-06-29 08:00:00,000 INFO [20260629_080000_def456] "
            "agent.conversation_loop: API call #5: "
            "model=claude-sonnet-4-20250514 provider=anthropic "
            "in=5000 out=1000 total=6000"
        )
        m = _LOG_API_CALL_PATTERN.search(line)
        assert m is not None
        assert m.group("model") == "claude-sonnet-4-20250514"
        assert m.group("provider") == "anthropic"
        assert m.group("context_len") == "6000"

    def test_no_match_on_other_log_lines(self):
        """非 API call 行不应匹配"""
        lines = [
            "2026-06-29 06:29:04,461 INFO [20260629_055232_7126c1] agent.conversation_loop: Starting loop",
            "2026-06-29 06:29:04,461 DEBUG [20260629_055232_7126c1] tool.executor: Running tool: bash",
            "2026-06-29 06:29:04,461 INFO agent.hermes: Hermes Agent v0.1.0 starting",
        ]
        for line in lines:
            assert _LOG_API_CALL_PATTERN.search(line) is None


# ============================================================
# 模拟模式测试
# ============================================================

class TestSimulateMode:
    """模拟模式功能测试"""

    def test_simulate_returns_status_message(self):
        monitor = HermesMonitor(simulate=True)
        status = monitor.get_status()
        assert isinstance(status, StatusMessage)
        assert status.agent == "hermes"

    def test_simulate_cycles_through_statuses(self):
        """模拟模式在足够时间后应覆盖所有状态"""
        monitor = HermesMonitor(simulate=True)
        # 保存原始 time.monotonic，模拟时间流逝
        original_monotonic = time.monotonic
        call_count = [0]

        def fake_monotonic():
            call_count[0] += 1
            # 每次调用推进 3 秒，8 秒一个周期
            return original_monotonic() + (call_count[0] * 3)

        with patch("src.hermes_monitor.time.monotonic", side_effect=fake_monotonic):
            statuses_seen = set()
            for _ in range(12):
                s = monitor.get_status()
                statuses_seen.add(s.status)

        # 应覆盖所有三个状态（IDLE, WORKING, WAITING）
        assert AgentStatus.IDLE in statuses_seen, f"缺少 IDLE, 看到: {statuses_seen}"
        assert AgentStatus.WORKING in statuses_seen, f"缺少 WORKING, 看到: {statuses_seen}"
        assert AgentStatus.WAITING in statuses_seen, f"缺少 WAITING, 看到: {statuses_seen}"

    def test_simulate_uses_new_fields(self):
        monitor = HermesMonitor(simulate=True)
        status = monitor.get_status()
        data = status.model_dump()
        assert "agent" in data
        assert "task_summary" in data
        assert "timestamp" in data
        assert "agent_name" not in data
        assert "task" not in data

    def test_simulate_has_iso_timestamp(self):
        monitor = HermesMonitor(simulate=True)
        status = monitor.get_status()
        assert "T" in status.timestamp
        assert len(status.timestamp) == 19


# ============================================================
# 日志文件解析测试
# ============================================================

class TestLogParsing:
    """从 agent.log 解析状态测试"""

    @patch("src.hermes_monitor.Path.exists")
    @patch("src.hermes_monitor.Path.stat")
    def test_parse_status_from_log_with_api_call(self, mock_stat, mock_exists):
        """解析包含 API call 的日志文件"""
        mock_exists.return_value = True
        mock_stat.return_value.st_size = 99999

        log_content = (
            "2026-06-29 06:29:04,461 INFO [20260629_055232_7126c1] "
            "agent.conversation_loop: API call #60: "
            "model=deepseek-v4-pro provider=deepseek "
            "in=65171 out=718 total=65889 latency=6.9s cache=64256/65171 (99%)\n"
        )

        monitor = HermesMonitor()

        with patch.object(
            monitor, "_get_log_file",
            return_value=Path("/fake/agent.log"),
        ):
            with patch.object(monitor, "_read_latest_exchange", return_value="正在分析代码质量"):
                with patch("builtins.open") as mock_open:
                    mock_open.return_value.__enter__.return_value.readlines.return_value = log_content.split("\n")

                    status = monitor._get_status_from_log()
                    assert status is not None
                    assert status.model == "deepseek-v4-pro"
                    assert status.context_len == 65889
                    assert status.agent == "hermes"
                    assert status.task_summary == "正在分析代码质量"
                    assert status.timestamp is not None

    @patch("src.hermes_monitor.Path.exists")
    def test_log_not_found_returns_none(self, mock_exists):
        """日志文件不存在时返回 None"""
        mock_exists.return_value = False
        monitor = HermesMonitor()

        with patch.object(monitor, "_get_log_file", return_value=Path("/fake/agent.log")):
            status = monitor._get_status_from_log()
            assert status is None

    @patch("src.hermes_monitor.Path.exists")
    def test_empty_log_returns_none(self, mock_exists):
        """空日志文件返回 None"""
        mock_exists.return_value = True

        monitor = HermesMonitor()

        with patch.object(monitor, "_get_log_file", return_value=Path("/fake/agent.log")):
            with patch("builtins.open") as mock_open:
                mock_open.return_value.__enter__.return_value.readlines.return_value = []
                status = monitor._get_status_from_log()
                assert status is None


# ============================================================
# hermes status 子进程测试
# ============================================================

class TestSubprocessFallback:
    """hermes status 子进程降级测试"""

    @patch("src.hermes_monitor.subprocess.run")
    def test_hermes_status_json_output(self, mock_run):
        """解析 JSON 格式的 hermes status 输出"""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "model": "deepseek-v4-pro",
            "status": "working",
            "provider": "deepseek",
            "context_len": 65889,
        })

        def side_effect(*args, **kwargs):
            if "--all" in str(args[0]):
                return MagicMock(returncode=0, stdout="1 session active")
            return mock_result

        mock_run.side_effect = side_effect

        monitor = HermesMonitor()
        status = monitor._get_status_from_subprocess()
        assert status is not None
        assert status.model == "deepseek-v4-pro"
        assert status.status == AgentStatus.WORKING
        assert status.context_len == 65889

    @patch("src.hermes_monitor.subprocess.run")
    def test_hermes_status_not_found(self, mock_run):
        """hermes 命令不存在时返回 None"""
        mock_run.side_effect = FileNotFoundError("hermes not found")

        monitor = HermesMonitor()
        status = monitor._get_status_from_subprocess()
        assert status is None


# ============================================================
# get_status 多级降级测试
# ============================================================

class TestGetStatusMultiTier:
    """get_status 多级降级测试"""

    @patch.object(HermesMonitor, "_get_status_from_log")
    @patch.object(HermesMonitor, "_get_status_from_subprocess")
    @patch.object(HermesMonitor, "_get_status_from_psutil")
    def test_primary_log_is_used_first(
        self, mock_psutil, mock_subprocess, mock_log,
    ):
        """Primary 日志源优先使用"""
        mock_log.return_value = StatusMessage(
            status=AgentStatus.WORKING,
            agent="hermes",
            model="deepseek-v4-pro",
            task_summary="日志解析任务",
        )
        monitor = HermesMonitor()
        status = monitor.get_status()
        assert status.model == "deepseek-v4-pro"
        assert status.task_summary == "日志解析任务"
        mock_subprocess.assert_not_called()
        mock_psutil.assert_not_called()

    @patch.object(HermesMonitor, "_get_status_from_log")
    @patch.object(HermesMonitor, "_get_status_from_subprocess")
    @patch.object(HermesMonitor, "_get_status_from_psutil")
    def test_fallback_subprocess_when_log_fails(
        self, mock_psutil, mock_subprocess, mock_log,
    ):
        """日志源失败时回退到子进程"""
        mock_log.return_value = None
        mock_subprocess.return_value = StatusMessage(
            status=AgentStatus.IDLE,
            agent="hermes",
            model="claude-sonnet-4",
            task_summary="来自 hermes status",
        )
        monitor = HermesMonitor()
        status = monitor.get_status()
        assert status.model == "claude-sonnet-4"
        assert status.task_summary == "来自 hermes status"
        mock_subprocess.assert_called_once()
        mock_psutil.assert_not_called()

    @patch.object(HermesMonitor, "_get_status_from_log")
    @patch.object(HermesMonitor, "_get_status_from_subprocess")
    @patch.object(HermesMonitor, "_get_status_from_psutil")
    def test_fallback_psutil_when_all_fail(
        self, mock_psutil, mock_subprocess, mock_log,
    ):
        """所有源都失败时回退到 psutil"""
        mock_log.return_value = None
        mock_subprocess.return_value = None
        mock_psutil.return_value = StatusMessage(
            status=AgentStatus.WORKING,
            agent="hermes",
            task_summary="进程检测",
        )
        monitor = HermesMonitor()
        status = monitor.get_status()
        assert status.status == AgentStatus.WORKING
        assert status.task_summary == "进程检测"
        mock_psutil.assert_called_once()

    @patch.object(HermesMonitor, "_get_status_from_log")
    @patch.object(HermesMonitor, "_get_status_from_subprocess")
    @patch.object(HermesMonitor, "_get_status_from_psutil")
    def test_all_sources_fail_returns_idle(
        self, mock_psutil, mock_subprocess, mock_log,
    ):
        """所有数据源都失败时返回 IDLE"""
        mock_log.return_value = None
        mock_subprocess.return_value = None
        mock_psutil.return_value = None

        monitor = HermesMonitor()
        status = monitor.get_status()
        assert status.status == AgentStatus.IDLE
        assert status.agent == "hermes"


# ============================================================
# 状态模型新字段测试
# ============================================================

class TestStatusMessageNewFields:
    """任务书_2 新字段名验证"""

    def test_agent_field_replaces_agent_name(self):
        msg = StatusMessage(status=AgentStatus.IDLE)
        assert hasattr(msg, "agent")
        assert not hasattr(msg, "agent_name")

    def test_task_summary_field_replaces_task(self):
        msg = StatusMessage(status=AgentStatus.WORKING)
        assert hasattr(msg, "task_summary")
        assert not hasattr(msg, "task")

    def test_timestamp_field_exists(self):
        msg = StatusMessage(status=AgentStatus.IDLE)
        assert hasattr(msg, "timestamp")
        assert isinstance(msg.timestamp, str)
        assert len(msg.timestamp) > 0

    def test_all_statuses_serializable_with_new_fields(self):
        """所有状态使用新字段时都能正确序列化"""
        for status in AgentStatus:
            msg = StatusMessage(status=status)
            json_str = msg.model_dump_json()
            assert '"agent"' in json_str
            assert '"task_summary"' in json_str
            assert '"timestamp"' in json_str
            assert '"agent_name"' not in json_str
            assert '"task"' not in json_str
            # 反序列化应正常工作
            parsed = StatusMessage.model_validate_json(json_str)
            assert parsed.status == status
            assert parsed.agent == "hermes"

    def test_partial_message_defaults_with_new_fields(self):
        """部分字段缺失时使用默认值（新字段名）"""
        data = '{"status":"idle"}'
        msg = StatusMessage.model_validate_json(data)
        assert msg.agent == "hermes"
        assert msg.context_len == 0
        assert msg.cum_time == "0h"
        assert msg.task_summary is None

    def test_large_context_length(self):
        """测试大上下文长度"""
        msg = StatusMessage(status=AgentStatus.WORKING, context_len=200000)
        assert msg.context_len == 200000


# ============================================================
# 辅助函数测试
# ============================================================

class TestHelperFunctions:
    """辅助函数测试"""

    def test_now_iso_format(self):
        ts = _now_iso()
        assert "T" in ts
        assert len(ts) == 19  # YYYY-MM-DDTHH:MM:SS

    def test_extract_field_from_text(self):
        """从文本中提取字段值"""
        monitor = HermesMonitor(simulate=True)
        # 测试 key=value 格式
        assert monitor._extract_field("model=deepseek-v4-pro", "model") == "deepseek-v4-pro"
        # 测试 key: value 格式
        assert monitor._extract_field('status: "working"', "status") == "working"
        # 不存在的字段
        assert monitor._extract_field("hello world", "model") is None

    def test_map_status_str(self):
        """状态字符串到枚举映射"""
        monitor = HermesMonitor(simulate=True)
        assert monitor._map_status_str("working") == AgentStatus.WORKING
        assert monitor._map_status_str("idle") == AgentStatus.IDLE
        assert monitor._map_status_str("waiting") == AgentStatus.WAITING
        assert monitor._map_status_str("error") == AgentStatus.ERROR
        assert monitor._map_status_str("running") == AgentStatus.WORKING
        # 未知字符串映射为 IDLE
        assert monitor._map_status_str("unknown") == AgentStatus.IDLE


# ============================================================
# 回调与线程测试
# ============================================================

class TestCallbacks:
    """状态变化回调测试"""

    def test_on_status_change_registers_callback(self):
        monitor = HermesMonitor(simulate=True)
        callback = MagicMock()
        monitor.on_status_change(callback)
        assert callback in monitor._callbacks

    def test_multiple_callbacks(self):
        monitor = HermesMonitor(simulate=True)
        cb1 = MagicMock()
        cb2 = MagicMock()
        monitor.on_status_change(cb1)
        monitor.on_status_change(cb2)
        assert len(monitor._callbacks) == 2

    def test_duplicate_callback_not_added(self):
        monitor = HermesMonitor(simulate=True)
        callback = MagicMock()
        monitor.on_status_change(callback)
        monitor.on_status_change(callback)
        assert len(monitor._callbacks) == 1


# ============================================================
# start_tailing / stop_tailing 测试
# ============================================================

class TestTailing:
    """后台日志监控线程测试"""

    def test_start_tailing_creates_thread(self):
        monitor = HermesMonitor(simulate=True)
        monitor.start_tailing()
        assert monitor._tailing is True
        assert monitor._tail_thread is not None
        assert monitor._tail_thread.is_alive()
        monitor.stop_tailing()

    def test_stop_tailing_joins_thread(self):
        monitor = HermesMonitor(simulate=True)
        monitor.start_tailing()
        monitor.stop_tailing()
        assert monitor._tailing is False

    def test_start_tailing_twice_no_error(self):
        monitor = HermesMonitor(simulate=True)
        monitor.start_tailing()
        monitor.start_tailing()  # 第二次应不报错
        monitor.stop_tailing()
