# -*- coding: utf-8 -*-
"""
串口发布者模块

将 StatusMessage 以 JSON 格式写入指定 COM 口，替代或补充 MQTT。
用于虚拟串口直连 ESP32 (COM10↔COM11 虚拟串口对) 或 USB Serial。
"""

import json
import logging
import time
from typing import Optional

import serial

from .status_model import StatusMessage

logger = logging.getLogger(__name__)


class SerialPublisher:
    """串口状态发布者 — 往 COM 口逐行写 JSON"""

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 1.0):
        """
        初始化串口发布者

        Args:
            port: COM 口名称 (如 "COM11")
            baudrate: 波特率 (默认 115200)
            timeout: 写超时 (秒)
        """
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._serial: Optional[serial.Serial] = None
        self._connected = False

    def connect(self) -> bool:
        """打开串口连接"""
        try:
            self._serial = serial.Serial(
                port=self._port,
                baudrate=self._baudrate,
                timeout=self._timeout,
                write_timeout=self._timeout,
            )
            self._connected = True
            logger.info("串口已打开: %s @ %d baud", self._port, self._baudrate)
            return True
        except serial.SerialException as e:
            logger.error("无法打开串口 %s: %s", self._port, e)
            self._connected = False
            return False

    def disconnect(self) -> None:
        """关闭串口连接"""
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._connected = False
        logger.info("串口已关闭: %s", self._port)

    def publish(self, message: StatusMessage) -> bool:
        """
        发布状态消息到串口

        Args:
            message: 状态消息对象

        Returns:
            是否成功写入
        """
        if not self._connected or not self._serial or not self._serial.is_open:
            logger.debug("串口未连接，跳过发布")
            return False

        try:
            payload = message.model_dump_json() + "\n"
            self._serial.write(payload.encode("utf-8"))
            self._serial.flush()
            logger.debug("串口已发布: %s -> %s", message.status.value, self._port)
            return True
        except serial.SerialException as e:
            logger.error("串口写入失败 (%s): %s", self._port, e)
            self._connected = False
            return False

    @property
    def connected(self) -> bool:
        """是否已连接"""
        return self._connected
