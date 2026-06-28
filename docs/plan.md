# AI Agent Status Companion Device — 实施计划

> **For Hermes:** 按任务逐项实现，MQTT + 单 Agent(Hermes) 优先。

**目标：** 开发 ESP32 桌面伴侣硬件 + Python 主机中间件，实时显示 AI Agent 状态（三色灯 + OLED）。

**架构：** Python 中间件监控 Hermes Agent → 聚合状态 → MQTT 发布 → ESP32 订阅 → 更新 LED/OLED 显示。

**技术栈：** Python 3.11+ (paho-mqtt, FastAPI, psutil), Arduino C++ (WiFi, PubSubClient, Adafruit SSD1306, Adafruit NeoPixel), MQTT (Mosquitto broker)。

---

## Task 1: 项目基础配置

**文件：**
- `.gitignore`
- `host/requirements.txt`
- `host/pyproject.toml`

## Task 2: Python MQTT 发布者核心

**文件：**
- `host/src/config.py` — 配置管理（MQTT broker, topic, serial port）
- `host/src/mqtt_publisher.py` — MQTT 连接 + 发布 JSON 状态
- `host/src/status_model.py` — 状态数据模型（Pydantic）

## Task 3: Hermes Agent 状态监控

**文件：**
- `host/src/hermes_monitor.py` — 监控 Hermes 进程/日志，提取状态

## Task 4: 状态聚合 + 主循环

**文件：**
- `host/src/aggregator.py` — 聚合多个 Agent 状态，定时发布
- `host/src/main.py` — CLI 入口 (argparse)

## Task 5: Web 面板 (FastAPI)

**文件：**
- `host/web/app.py` — FastAPI 应用 + WebSocket 实时推送
- `host/web/static/index.html` — 仪表盘页面

## Task 6: ESP32 固件

**文件：**
- `firmware/agent-status-companion/agent-status-companion.ino` — 主固件

## Task 7: 硬件文档 + 3D 外壳

**文件：**
- `hardware/schematics/wiring.md` — 接线图
- `hardware/enclosure/case.scad` — OpenSCAD 外壳模型

## Task 8: 用户文档 + 测试

**文件：**
- `docs/assembly.md` — 组装烧录指南
- `host/tests/test_mqtt.py` — MQTT 模拟测试
- `host/tests/test_monitor.py` — 监控模拟测试
