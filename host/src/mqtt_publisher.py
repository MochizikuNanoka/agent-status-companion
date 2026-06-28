# -*- coding: utf-8 -*-
"""
MQTT 发布者模块

负责与 MQTT Broker 建立连接，
将 StatusMessage 以 JSON 格式发布到指定主题。
支持自动重连和遗嘱消息 (LWT)。
已适配任务书_2 新字段名（agent/task_summary/timestamp）。
"""

import json
import logging
from typing import Optional

import paho.mqtt.client as mqtt

from .status_model import StatusMessage

logger = logging.getLogger(__name__)


class MqttPublisher:
    """
    MQTT 状态发布者

    封装 paho-mqtt 客户端，提供连接管理与消息发布功能。
    """

    def __init__(
        self,
        broker: str = "localhost",
        port: int = 1883,
        topic: str = "agent/status",
        client_id: Optional[str] = None,
    ):
        """
        初始化 MQTT 发布者

        Args:
            broker: MQTT Broker 地址
            port: MQTT Broker 端口
            topic: 发布主题
            client_id: 客户端 ID（默认自动生成）
        """
        self.broker = broker
        self.port = port
        self.topic = topic
        self._client_id = client_id or f"hermes-host-{id(self):x}"

        # 创建 MQTT 客户端
        self._client = mqtt.Client(
            client_id=self._client_id,
            protocol=mqtt.MQTTv311,
        )

        # 配置遗嘱消息 (LWT) —— 离线时通知（使用新字段名）
        self._client.will_set(
            topic=self.topic,
            payload=json.dumps({
                "status": "offline",
                "agent": "hermes",
                "task_summary": "disconnected",
            }),
            qos=1,
            retain=True,
        )

        # 注册回调
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect

        self._connected = False

    def _on_connect(self, client, userdata, flags, rc) -> None:
        """连接成功/失败回调"""
        if rc == 0:
            self._connected = True
            logger.info("已连接到 MQTT Broker: %s:%d", self.broker, self.port)
        else:
            self._connected = False
            logger.error("MQTT 连接失败，返回码: %d", rc)

    def _on_disconnect(self, client, userdata, rc) -> None:
        """断开连接回调"""
        self._connected = False
        if rc != 0:
            logger.warning("MQTT 意外断开，将尝试重连 (rc=%d)", rc)
        else:
            logger.info("MQTT 正常断开")

    def connect(self) -> bool:
        """
        连接到 MQTT Broker

        Returns:
            是否成功连接
        """
        try:
            self._client.connect(self.broker, self.port, keepalive=60)
            self._client.loop_start()  # 启动后台网络循环
            logger.info("正在连接 MQTT Broker %s:%d ...", self.broker, self.port)
            return True
        except Exception as e:
            logger.error("连接 MQTT Broker 失败: %s", e)
            return False

    def disconnect(self) -> None:
        """断开 MQTT 连接"""
        self._client.loop_stop()
        self._client.disconnect()
        logger.info("MQTT 连接已关闭")

    def publish(self, message: StatusMessage) -> bool:
        """
        发布状态消息

        Args:
            message: 状态消息对象

        Returns:
            是否成功发布
        """
        if not self._connected:
            logger.debug("MQTT 未连接，跳过发布")
            return False

        try:
            payload = message.model_dump_json()  # Pydantic v2
            info = self._client.publish(
                topic=self.topic,
                payload=payload,
                qos=1,
                retain=True,
            )
            # 等待发布完成（最多 5 秒）
            info.wait_for_publish(timeout=5)
            logger.debug("已发布状态: %s -> %s", message.status.value, self.topic)
            return True
        except Exception as e:
            logger.error("发布 MQTT 消息失败: %s", e)
            return False

    @property
    def connected(self) -> bool:
        """是否已连接"""
        return self._connected
