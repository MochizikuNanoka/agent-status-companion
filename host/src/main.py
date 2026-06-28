# -*- coding: utf-8 -*-
"""
CLI 入口模块

使用 argparse 解析命令行参数，
启动 MQTT 发布者、状态聚合器和 Web 面板。
支持优雅退出（SIGINT/SIGTERM）。
支持 --simulate 模拟模式（任务书_2）。
"""

import sys
import signal
import logging
import argparse
from typing import NoReturn

from .config import load_config
from .mqtt_publisher import MqttPublisher
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
    """
    解析命令行参数

    Args:
        argv: 参数列表（默认使用 sys.argv[1:]）

    Returns:
        解析后的命名空间
    """
    parser = argparse.ArgumentParser(
        description="Hermes Agent 状态监控中间件",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m host.src.main
  python -m host.src.main --broker 10.0.0.5 --web-port 9090
  python -m host.src.main --topic agent/hermes/status --poll-interval 5
  python -m host.src.main --simulate                    # 模拟模式
  python -m host.src.main --simulate --log-path D:/logs/hermes/agent.log
        """,
    )

    parser.add_argument(
        "--broker",
        default=None,
        help="MQTT Broker 地址（默认: localhost）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="MQTT Broker 端口（默认: 1883）",
    )
    parser.add_argument(
        "--topic",
        default=None,
        help="MQTT 发布主题（默认: agent/status）",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=None,
        help="Web 面板端口（默认: 8080）",
    )
    parser.add_argument(
        "--web-host",
        default=None,
        help="Web 面板绑定地址（默认: 0.0.0.0）",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=None,
        help="状态轮询间隔（秒，默认: 2.0）",
    )
    parser.add_argument(
        "--log-path",
        default=None,
        help="Hermes agent.log 文件路径（默认: 自动检测）",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        default=None,
        help="启用模拟模式（循环切换 IDLE/WORKING/WAITING，用于开发测试）",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="YAML 配置文件路径",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="启用调试日志输出",
    )

    return parser.parse_args(argv)


def setup_logging(verbose: bool = False) -> None:
    """
    配置日志系统

    Args:
        verbose: 是否启用 DEBUG 级别日志
    """
    level = logging.DEBUG if verbose else logging.INFO
    fmt = (
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        if verbose else
        "%(asctime)s [%(levelname)s] %(message)s"
    )

    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )


class Application:
    """
    应用主控类

    管理各组件的生命周期：启动、运行、优雅退出。
    """

    def __init__(self, args: argparse.Namespace):
        self._args = args
        self._running = False

        # 加载配置
        self._config = load_config(args.config)

        # 命令行参数覆盖配置
        self._override_config()

        # 创建 MQTT 发布者
        self._publisher = MqttPublisher(
            broker=self._config.mqtt_broker,
            port=self._config.mqtt_port,
            topic=self._config.mqtt_topic,
        )

        # 创建监控器（支持模拟模式）
        self._monitor = HermesMonitor(
            simulate=self._config.simulate,
            log_path=self._config.hermes_log_path,
        )

        # 创建聚合器
        self._aggregator = StatusAggregator(
            monitor=self._monitor,
            publisher=self._publisher,
            poll_interval=self._config.poll_interval,
        )

        # 注册信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _override_config(self) -> None:
        """用命令行参数覆盖配置文件"""
        args = self._args
        config = self._config

        if args.broker is not None:
            config.mqtt_broker = args.broker
        if args.port is not None:
            config.mqtt_port = args.port
        if args.topic is not None:
            config.mqtt_topic = args.topic
        if args.web_port is not None:
            config.web_port = args.web_port
        if args.web_host is not None:
            config.web_host = args.web_host
        if args.poll_interval is not None:
            config.poll_interval = args.poll_interval
        if args.log_path is not None:
            config.hermes_log_path = args.log_path
        if args.simulate is not None:
            config.simulate = args.simulate

    def _signal_handler(self, signum, frame) -> None:
        """信号处理：优雅退出"""
        signame = signal.Signals(signum).name
        logger.info("收到 %s 信号，正在优雅退出...", signame)
        self.stop()

    def start(self) -> None:
        """启动所有组件"""
        self._running = True

        logger.info("=" * 50)
        logger.info("Hermes Agent 状态监控中间件")
        logger.info("=" * 50)
        logger.info("MQTT:    %s:%d -> %s", self._config.mqtt_broker, self._config.mqtt_port, self._config.mqtt_topic)
        logger.info("Web:     http://%s:%d", self._config.web_host, self._config.web_port)
        logger.info("日志:    %s", self._config.hermes_log_path)
        logger.info("轮询:    每 %.1f 秒", self._config.poll_interval)
        if self._config.simulate:
            logger.info("模式:    模拟模式（无 Hermes 环境）")
        logger.info("=" * 50)

        # 连接 MQTT
        self._publisher.connect()

        # 启动聚合器
        self._aggregator.start()

        # 启动 Web 服务器（阻塞）
        start_web_server(
            host=self._config.web_host,
            port=self._config.web_port,
            aggregator=self._aggregator,
        )

    def stop(self) -> None:
        """停止所有组件"""
        if not self._running:
            return

        logger.info("正在停止所有组件...")

        # 停止聚合器
        self._aggregator.stop()

        # 断开 MQTT
        self._publisher.disconnect()

        self._running = False
        logger.info("已安全退出")


def main(argv: list[str] | None = None) -> NoReturn:
    """
    主入口函数

    Args:
        argv: 命令行参数（默认使用 sys.argv）
    """
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
