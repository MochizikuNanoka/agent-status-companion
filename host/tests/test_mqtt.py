# -*- coding: utf-8 -*-
"""MQTT 发布者和状态模型测试（适配任务书_2 新字段名）"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock

from src.status_model import StatusMessage, AgentStatus


class TestStatusMessage:
    """StatusMessage 数据模型测试（新字段名）"""

    def test_create_idle_status(self):
        msg = StatusMessage(status=AgentStatus.IDLE)
        assert msg.status == AgentStatus.IDLE
        assert msg.agent == "hermes"
        assert msg.task_summary is None

    def test_create_working_status(self):
        msg = StatusMessage(
            status=AgentStatus.WORKING,
            model="deepseek-v4",
            task_summary="分析代码",
            context_len=8192,
            cum_time="2.5h",
            cpu_percent=45.2,
            mem_mb=512.0,
        )
        assert msg.status == AgentStatus.WORKING
        assert msg.model == "deepseek-v4"
        assert msg.task_summary == "分析代码"
        assert msg.context_len == 8192

    def test_timestamp_is_iso_format(self):
        msg = StatusMessage(status=AgentStatus.IDLE)
        # ISO 8601 格式：YYYY-MM-DDTHH:MM:SS
        assert "T" in msg.timestamp
        assert len(msg.timestamp) == 19  # e.g. 2026-06-29T06:30:00

    def test_json_serialization_uses_new_fields(self):
        msg = StatusMessage(status=AgentStatus.WAITING, task_summary="等待用户输入")
        data = msg.model_dump_json()
        parsed = json.loads(data)
        assert parsed["status"] == "waiting"
        assert parsed["task_summary"] == "等待用户输入"
        assert "agent" in parsed
        assert "timestamp" in parsed
        # 旧字段名不应出现
        assert "agent_name" not in parsed
        assert "task" not in parsed

    def test_json_deserialization(self):
        data = '{"status":"error","agent":"test","model":"gpt-4","task_summary":"崩溃了","context_len":0,"cum_time":"1h","timestamp":"2026-06-28T15:30:00","cpu_percent":0,"mem_mb":0}'
        msg = StatusMessage.model_validate_json(data)
        assert msg.status == AgentStatus.ERROR
        assert msg.agent == "test"
        assert msg.task_summary == "崩溃了"
        assert msg.timestamp == "2026-06-28T15:30:00"

    def test_status_enum_values(self):
        assert AgentStatus.IDLE.value == "idle"
        assert AgentStatus.WORKING.value == "working"
        assert AgentStatus.WAITING.value == "waiting"
        assert AgentStatus.ERROR.value == "error"


class TestMqttPublisher:
    """MqttPublisher 发布者测试"""

    @patch("src.mqtt_publisher.mqtt")
    def test_connect(self, mock_mqtt):
        from src.mqtt_publisher import MqttPublisher
        pub = MqttPublisher(broker="localhost")
        pub.connect()
        mock_mqtt.Client.assert_called_once()

    @patch("src.mqtt_publisher.mqtt")
    def test_publish_json_uses_new_fields(self, mock_mqtt):
        mock_client = MagicMock()
        mock_mqtt.Client.return_value = mock_client

        from src.mqtt_publisher import MqttPublisher
        pub = MqttPublisher(broker="localhost")
        pub._client = mock_client
        pub._connected = True  # 模拟已连接状态

        msg = StatusMessage(status=AgentStatus.WORKING, model="test")
        pub.publish(msg)

        mock_client.publish.assert_called_once()
        kwargs = mock_client.publish.call_args.kwargs
        payload = json.loads(kwargs["payload"])
        assert kwargs["topic"] == "agent/status"
        assert payload["status"] == "working"
        assert payload["model"] == "test"
        # 验证新字段名
        assert "agent" in payload
        assert "task_summary" in payload
        assert "timestamp" in payload
        assert "agent_name" not in payload
        assert "task" not in payload

    @patch("src.mqtt_publisher.mqtt")
    def test_will_message_uses_new_fields(self, mock_mqtt):
        """验证遗嘱消息使用了新字段名"""
        from src.mqtt_publisher import MqttPublisher
        pub = MqttPublisher(broker="localhost")
        # 检查 will_set 调用参数
        will_set_call = pub._client.will_set.call_args
        assert will_set_call is not None
        will_kwargs = will_set_call.kwargs if will_set_call.kwargs else {}
        will_payload_str = will_kwargs.get("payload", "")
        if isinstance(will_payload_str, str):
            will_payload = json.loads(will_payload_str)
            assert will_payload["agent"] == "hermes"
            assert will_payload["task_summary"] == "disconnected"
            assert will_payload["status"] == "offline"
            assert "agent_name" not in will_payload
            assert "task" not in will_payload

    @patch("src.mqtt_publisher.mqtt")
    def test_publish_idle_status(self, mock_mqtt):
        mock_client = MagicMock()
        mock_mqtt.Client.return_value = mock_client

        from src.mqtt_publisher import MqttPublisher
        pub = MqttPublisher(broker="localhost")
        pub._client = mock_client
        pub._connected = True  # 模拟已连接状态

        msg = StatusMessage(status=AgentStatus.IDLE)
        pub.publish(msg)

        mock_client.publish.assert_called_once()
        payload = json.loads(mock_client.publish.call_args.kwargs["payload"])
        assert payload["status"] == "idle"
        assert payload["agent"] == "hermes"
