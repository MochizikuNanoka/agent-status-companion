# -*- coding: utf-8 -*-
"""Hermes 监控器测试"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from status_model import StatusMessage, AgentStatus


class TestHermesMonitor:
    """Hermes 监控器测试"""

    @patch("src.hermes_monitor.psutil")
    def test_agent_not_running_returns_idle(self, mock_psutil):
        """Agent 未运行时返回 IDLE 状态"""
        from hermes_monitor import HermesMonitor

        # 模拟无进程
        mock_psutil.process_iter.return_value = []

        monitor = HermesMonitor()
        status = monitor.get_status()

        assert isinstance(status, StatusMessage)
        assert status.status == AgentStatus.IDLE
        assert status.cpu_percent == 0.0

    @patch("src.hermes_monitor.psutil")
    def test_agent_running_detects_process(self, mock_psutil):
        """Agent 运行时能检测进程"""
        from hermes_monitor import HermesMonitor

        mock_proc = MagicMock()
        mock_proc.info = {"name": "hermes.exe", "pid": 12345}
        mock_proc.cpu_percent.return_value = 45.0
        mock_psutil.process_iter.return_value = [mock_proc]

        monitor = HermesMonitor()
        status = monitor.get_status()

        assert status.status in [
            AgentStatus.IDLE,
            AgentStatus.WORKING,
            AgentStatus.WAITING,
        ]
        assert status.cpu_percent >= 0

    @patch("src.hermes_monitor.psutil")
    def test_returns_cpu_and_memory(self, mock_psutil):
        """返回正确的 CPU 和内存数据"""
        from hermes_monitor import HermesMonitor

        mock_proc = MagicMock()
        mock_proc.info = {"name": "hermes.exe", "pid": 12345}
        mock_proc.cpu_percent.return_value = 67.5
        mock_proc.memory_info.return_value = Mock(rss=256 * 1024 * 1024)
        mock_psutil.process_iter.return_value = [mock_proc]

        monitor = HermesMonitor()
        status = monitor.get_status()

        assert status.cpu_percent == 67.5
        assert status.mem_mb == pytest.approx(256.0, rel=0.1)


class TestConfig:
    """配置管理测试"""

    def test_config_defaults(self):
        from config import Config
        cfg = Config()
        assert cfg.mqtt_broker == "localhost"
        assert cfg.mqtt_port == 1883
        assert cfg.mqtt_topic == "agent/status"

    def test_config_from_env(self):
        import os
        from config import Config

        os.environ["AGENT_COMPANION_MQTT_BROKER"] = "test-broker"
        os.environ["AGENT_COMPANION_MQTT_PORT"] = "8883"

        cfg = Config()
        assert cfg.mqtt_broker == "test-broker"
        assert cfg.mqtt_port == 8883

        # 清理
        del os.environ["AGENT_COMPANION_MQTT_BROKER"]
        del os.environ["AGENT_COMPANION_MQTT_PORT"]


class TestStatusMessageVariants:
    """状态消息各种变体测试"""

    def test_all_statuses_serializable(self):
        """所有状态都能正确序列化"""
        for status in AgentStatus:
            msg = StatusMessage(status=status)
            json_str = msg.model_dump_json()
            parsed = StatusMessage.model_validate_json(json_str)
            assert parsed.status == status

    def test_partial_message_defaults(self):
        """部分字段缺失时使用默认值"""
        data = '{"status":"idle"}'
        msg = StatusMessage.model_validate_json(data)
        assert msg.agent_name == "hermes"
        assert msg.context_len == 0
        assert msg.cum_time == "0h"

    def test_large_context_length(self):
        """测试大上下文长度"""
        msg = StatusMessage(status=AgentStatus.WORKING, context_len=200000)
        assert msg.context_len == 200000
