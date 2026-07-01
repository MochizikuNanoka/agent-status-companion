# -*- coding: utf-8 -*-
"""
状态聚合器模块

管理多个 Monitor 实例，定时轮询状态变化，
仅在状态变更时触发 MQTT 发布。
维护累计运行时间统计。
适配任务书_2 新字段名（agent/task_summary/timestamp）。
"""

import time
import logging
import threading
from typing import Optional

from .status_model import StatusMessage, AgentStatus
from .mqtt_publisher import MqttPublisher

logger = logging.getLogger(__name__)


class StatusAggregator:
    """
    状态聚合器

    定时轮询 Hermes Agent 状态，
    检测到变化时通过 MQTT 发布者发送更新。
    记录累计运行时间。
    """

    def __init__(
        self,
        monitor,
        publisher: MqttPublisher,
        poll_interval: float = 2.0,
    ):
        """
        初始化聚合器

        Args:
            monitor: HermesMonitor 实例
            publisher: MqttPublisher 实例
            poll_interval: 轮询间隔（秒）
        """
        self._monitor = monitor
        self._publisher = publisher
        self._poll_interval = poll_interval

        # 上一次发布的状态（用于检测变化）
        self._last_published: Optional[StatusMessage] = None
        # 累计工作时间统计（秒）
        self._cum_working_seconds: float = 0.0
        # 上次进入 WORKING 状态的时间戳
        self._working_start: Optional[float] = None
        # 上次轮询时是否为 WORKING
        self._was_working: bool = False

        # 运行控制
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._latest_status: Optional[StatusMessage] = None

        # 外部订阅者（如 WebSocket 广播）
        self._subscribers: list = []

    def start(self) -> None:
        """启动后台轮询线程"""
        if self._running:
            logger.warning("聚合器已在运行")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="status-aggregator",
            daemon=True,
        )
        self._thread.start()
        logger.info("状态聚合器已启动（间隔 %.1f 秒）", self._poll_interval)

    def stop(self) -> None:
        """停止轮询线程"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("状态聚合器已停止")

    def subscribe(self, callback) -> None:
        """
        注册状态变更回调

        Args:
            callback: 可调用对象，接收 StatusMessage 参数
        """
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback) -> None:
        """注销回调"""
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def get_latest_status(self) -> Optional[StatusMessage]:
        """获取最新状态快照"""
        return self._latest_status

    def get_cum_time_str(self) -> str:
        """获取累计时间格式化字符串"""
        total_sec = int(self._cum_working_seconds)
        hours = total_sec // 3600
        minutes = (total_sec % 3600) // 60
        if hours > 0:
            return f"{hours}h{minutes:02d}m"
        else:
            return f"{minutes}m"

    def _poll_loop(self) -> None:
        """轮询主循环（在后台线程中运行）"""
        while self._running:
            try:
                self._poll_once()
            except Exception as e:
                logger.error("轮询状态时出错: %s", e, exc_info=True)
            time.sleep(self._poll_interval)

    def _poll_once(self) -> None:
        """执行一次状态轮询"""
        # 获取当前状态
        current = self._monitor.get_status()

        # 更新累计工作时间
        self._update_cum_time(current)

        # 填入累计时间
        current.cum_time = self.get_cum_time_str()

        # 保存最新快照
        self._latest_status = current

        # 检测状态变化
        changed = self._has_changed(current)

        # 串口模式下每次都推送（时间会更新），MQTT 模式下仅变更时推送
        has_serial = len(self._subscribers) > 0

        if changed or has_serial:
            # 发布到 MQTT
            if self._publisher.connected and changed:
                self._publisher.publish(current)

            # 通知所有订阅者（串口每次推送）
            for callback in self._subscribers:
                try:
                    callback(current)
                except Exception as e:
                    logger.error("通知订阅者失败: %s", e)

            self._last_published = current
            logger.debug(
                "推送状态: %s | 模型=%s | 任务=%s | CPU=%.1f%% MEM=%.1fMB",
                current.status.value,
                current.model or "-",
                (current.task_summary or "-")[:40],
                current.cpu_percent,
                current.mem_mb,
            )

    def _update_cum_time(self, current: StatusMessage) -> None:
        """更新累计工作时间"""
        now = time.time()
        is_working = current.status == AgentStatus.WORKING

        if is_working and not self._was_working:
            # 开始计费
            self._working_start = now
        elif not is_working and self._was_working:
            # 停止计费
            if self._working_start is not None:
                elapsed = now - self._working_start
                self._cum_working_seconds += elapsed
                self._working_start = None
        elif is_working and self._was_working:
            # 持续工作中：实时累加
            if self._working_start is not None:
                self._cum_working_seconds += self._poll_interval

        self._was_working = is_working

    def _has_changed(self, current: StatusMessage) -> bool:
        """检测状态是否发生变化"""
        if self._last_published is None:
            return True

        return (
            current.status != self._last_published.status
            or current.model != self._last_published.model
            or current.task_summary != self._last_published.task_summary
            or abs(current.cpu_percent - self._last_published.cpu_percent) > 5.0
            or abs(current.mem_mb - self._last_published.mem_mb) > 10.0
        )
