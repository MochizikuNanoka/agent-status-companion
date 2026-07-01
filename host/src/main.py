# -*- coding: utf-8 -*-
"""
CLI 入口模块

使用 argparse 解析命令行参数，
启动 MQTT 发布者、串口发布者、状态聚合器和 Web 面板。
支持优雅退出（SIGINT/SIGTERM）。
支持 --simulate 模拟模式（任务书_2）。
支持 --serial-port 串口直连（COM10↔COM11 虚拟串口）。
"""

import sys
import signal
import logging
import argparse
from typing import NoReturn

from .config import load_config
from .mqtt_publisher import MqttPublisher
from .serial_publisher import SerialPublisher
from .hermes_monitor import HermesMonitor
from .aggregator import StatusAggregator

# Web 模块在 src 包外，需要特殊处理
try:
    from ..web.app import start_web_server
except ImportError:
    import os as _os
    _web_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    import sys as _sys
    _sys.path.insert(0, _web_dir)
    from web.app import start_web_server

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Hermes Agent 状态监控中间件",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m src.main
  python -m src.main --broker 10.0.0.5 --web-port 9090
  python -m src.main --serial-port COM11            # 串口直连 ESP32
  python -m src.main --serial-port COM11 --simulate  # 串口 + 模拟模式
  python -m src.main --simulate                      # MQTT + 模拟模式
        """,
    )

    parser.add_argument("--broker", default=None, help="MQTT Broker 地址（默认: localhost）")
    parser.add_argument("--port", type=int, default=None, help="MQTT Broker 端口（默认: 1883）")
    parser.add_argument("--topic", default=None, help="MQTT 发布主题（默认: agent/status）")
    parser.add_argument("--web-port", type=int, default=None, help="Web 面板端口（默认: 8080）")
    parser.add_argument("--web-host", default=None, help="Web 面板绑定地址（默认: 0.0.0.0）")
    parser.add_argument("--poll-interval", type=float, default=None, help="状态轮询间隔（秒，默认: 2.0）")
    parser.add_argument("--log-path", default=None, help="Hermes agent.log 文件路径")
    parser.add_argument("--simulate", action="store_true", default=None, help="模拟模式")
    parser.add_argument("--serial-port", default=None, help="串口直连 ESP32（如 COM11）")
    parser.add_argument("--serial-baud", type=int, default=115200, help="串口波特率（默认: 115200）")
    parser.add_argument("--config", default=None, help="YAML 配置文件路径")
    parser.add_argument("--verbose", "-v", action="store_true", help="调试日志")

    return parser.parse_args(argv)


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    fmt = (
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        if verbose else
        "%(asctime)s [%(levelname)s] %(message)s"
    )
    logging.basicConfig(
        level=level, format=fmt, datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


class Application:
    """应用主控类 — 管理各组件生命周期"""

    def __init__(self, args: argparse.Namespace):
        self._args = args
        self._running = False
        self._config = load_config(args.config)
        self._override_config()

        # MQTT 发布者（始终创建，可选连接）
        self._publisher = MqttPublisher(
            broker=self._config.mqtt_broker,
            port=self._config.mqtt_port,
            topic=self._config.mqtt_topic,
        )

        # 串口发布者（仅当指定 --serial-port 时创建）
        self._serial_pub: SerialPublisher | None = None
        if args.serial_port:
            self._serial_pub = SerialPublisher(
                port=args.serial_port,
                baudrate=args.serial_baud,
            )

        # 监控器
        self._monitor = HermesMonitor(
            simulate=self._config.simulate,
            log_path=self._config.hermes_log_path,
        )

        # 聚合器（先连 MQTT publisher，串口通过 subscribe 挂载）
        self._aggregator = StatusAggregator(
            monitor=self._monitor,
            publisher=self._publisher,
            poll_interval=self._config.poll_interval,
        )

        # 注册串口发布者为额外订阅者
        if self._serial_pub:
            self._aggregator.subscribe(self._serial_pub.publish)

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _override_config(self) -> None:
        args = self._args
        c = self._config
        if args.broker is not None: c.mqtt_broker = args.broker
        if args.port is not None: c.mqtt_port = args.port
        if args.topic is not None: c.mqtt_topic = args.topic
        if args.web_port is not None: c.web_port = args.web_port
        if args.web_host is not None: c.web_host = args.web_host
        if args.poll_interval is not None: c.poll_interval = args.poll_interval
        if args.log_path is not None: c.hermes_log_path = args.log_path
        if args.simulate is not None: c.simulate = args.simulate

    def _signal_handler(self, signum, frame) -> None:
        signame = signal.Signals(signum).name
        logger.info("收到 %s 信号，正在优雅退出...", signame)
        self.stop()

    def start(self) -> None:
        self._running = True

        logger.info("=" * 50)
        logger.info("Hermes Agent 状态监控中间件")
        logger.info("=" * 50)
        logger.info("MQTT:    %s:%d -> %s", self._config.mqtt_broker, self._config.mqtt_port, self._config.mqtt_topic)
        if self._serial_pub:
            logger.info("Serial:  %s @ %d baud", self._args.serial_port, self._args.serial_baud)
        logger.info("Web:     http://%s:%d", self._config.web_host, self._config.web_port)
        logger.info("日志:    %s", self._config.hermes_log_path)
        logger.info("轮询:    每 %.1f 秒", self._config.poll_interval)
        if self._config.simulate:
            logger.info("模式:    模拟模式")
        logger.info("=" * 50)

        # 连接 MQTT（串口模式下如果没指定 broker 则跳过）
        if self._serial_pub and self._args.broker is None:
            logger.info("MQTT:    已跳过（串口模式，未指定 --broker）")
        else:
            self._publisher.connect()

        # 连接串口
        if self._serial_pub:
            self._serial_pub.connect()

        # 启动聚合器
        self._aggregator.start()

        # 启动 Web 服务器（后台线程，端口冲突不阻塞主流程）
        import threading
        def _start_web():
            try:
                start_web_server(
                    host=self._config.web_host,
                    port=self._config.web_port,
                    aggregator=self._aggregator,
                )
            except Exception as e:
                logger.warning("Web panel failed: %s (serial mode ok)", e)
        threading.Thread(target=_start_web, daemon=True).start()

        # 保持主线程运行
        import time
        try:
            while self._running:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    def stop(self) -> None:
        if not self._running:
            return
        logger.info("正在停止所有组件...")
        self._aggregator.stop()
        if self._publisher.connected:
            self._publisher.disconnect()
        if self._serial_pub:
            self._serial_pub.disconnect()
        self._running = False
        logger.info("已安全退出")


def main(argv: list[str] | None = None) -> NoReturn:
    args = parse_args(argv)
    setup_logging(args.verbose)
    app = Application(args)
    try:
        app.start()
    except KeyboardInterrupt:
        logger.info("用户中断")
    except Exception as e:
        logger.critical("运行时错误: %s", e, exc_info=True)
    finally:
        app.stop()
        sys.exit(0)


if __name__ == "__main__":
    main()
