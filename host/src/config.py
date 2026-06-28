# -*- coding: utf-8 -*-
"""
配置管理模块

从环境变量读取配置，可选支持 YAML 配置文件。
所有配置项均有合理的默认值。
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AppConfig:
    """
    应用全局配置

    优先级：环境变量 > YAML 配置文件 > 默认值
    """
    # MQTT 连接配置
    mqtt_broker: str = field(default_factory=lambda: os.getenv("MQTT_BROKER", "localhost"))
    mqtt_port: int = field(
        default_factory=lambda: int(os.getenv("MQTT_PORT", "1883"))
    )
    mqtt_topic: str = field(default_factory=lambda: os.getenv("MQTT_TOPIC", "agent/status"))

    # Hermes Agent 监控配置
    hermes_log_path: Optional[Path] = field(default_factory=lambda: _default_log_path())
    hermes_log_file: str = field(default_factory=lambda: os.getenv("HERMES_LOG_FILE", "hermes.log"))

    # 轮询与 Web 配置
    poll_interval: float = field(
        default_factory=lambda: float(os.getenv("POLL_INTERVAL", "2.0"))
    )
    web_port: int = field(
        default_factory=lambda: int(os.getenv("WEB_PORT", "8080"))
    )
    web_host: str = field(default_factory=lambda: os.getenv("WEB_HOST", "0.0.0.0"))


def _default_log_path() -> Path:
    """
    获取默认的 Hermes 日志路径

    优先读取 HERMES_LOG_PATH 环境变量，
    否则使用 Windows 下的默认路径。
    """
    env_path = os.getenv("HERMES_LOG_PATH")
    if env_path:
        return Path(env_path)

    # Windows 默认路径
    return Path.home() / "AppData" / "Local" / "hermes" / "logs"


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """
    加载配置

    Args:
        config_path: 可选的 YAML 配置文件路径

    Returns:
        AppConfig 实例
    """
    # 如果提供了 YAML 配置文件，尝试加载
    if config_path:
        _try_load_yaml(config_path)

    return AppConfig()


def _try_load_yaml(config_path: str) -> None:
    """尝试从 YAML 文件加载配置（可选依赖）"""
    try:
        import yaml
        path = Path(config_path)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if data:
                # 将 YAML 值注入环境变量
                _inject_env(data)
    except ImportError:
        # yaml 不是必需依赖，静默跳过
        pass
    except Exception:
        # 忽略加载错误
        pass


def _inject_env(data: dict, prefix: str = "") -> None:
    """将字典键值注入环境变量（递归展平）"""
    for key, value in data.items():
        env_key = f"{prefix}{key.upper()}" if prefix else key.upper()
        if isinstance(value, dict):
            _inject_env(value, f"{env_key}_")
        elif value is not None:
            os.environ.setdefault(env_key, str(value))
