# -*- coding: utf-8 -*-
"""MQTT 发布者和状态模型测试"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock

from src.status_model import StatusMessage, AgentStatus


class TestStatusMessage:
    """StatusMessage 数据模型测试"""

    def test_create_idle_status(self):
        msg = StatusMessage(status=AgentStatus.IDLE)
        assert msg.status == AgentStatus.IDLE
        assert msg.agent_name == "hermes"

    def test_create_working_status(self):
        msg = StatusMessage(
            status=AgentStatus.WORKING,
            model="deepseek-v4",
            task="分析代码",
            context_len=8192,
            cum_time="2.5h",
            cpu_percent=45.2,
            mem_mb=512.0,
        )
        assert msg.status == AgentStatus.WORKING
        assert msg.model == "deepseek-v4"
        assert msg.task == "分析代码"

    def test_json_serialization(self):
        msg = StatusMessage(status=AgentStatus.WAITING, task="等待用户输入")
        data = msg.model_dump_json()
        parsed = json.loads(data)
        assert parsed["status"] == "waiting"
        assert parsed["task"] == "等待用户输入"

    def test_json_deserialization(self):
        data = '{"status":"error","agent_name":"test","model":"gpt-4","task":"崩溃了","context_len":0,"cum_time":"1h","cpu_percent":0,"mem_mb":0}'
        msg = StatusMessage.model_validate_json(data)
        assert msg.status == AgentStatus.ERROR
        assert msg.task == "崩溃了"

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
    def test_publish_json(self, mock_mqtt):
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
