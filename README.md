# Agent Status Companion

ESP32 桌面伴侣硬件 — 实时显示 AI Agent 状态（RGB LED + OLED 屏幕）。

## 架构

```
┌──────────────┐    MQTT/Serial     ┌──────────────┐
│ Python 中间件 │ ────────────────→  │ ESP32 固件    │
│ (监控 Agent)  │   JSON Status     │ (LED + OLED) │
└──────────────┘                    └──────────────┘
        │
        ├── psutil 监控进程
        ├── 读取 Hermes 日志
        └── Web 面板 (FastAPI)
```

## 快速开始

```bash
# 1. 安装 Python 依赖
cd host && pip install -r requirements.txt

# 2. 启动中间件 (使用公共 MQTT broker 测试)
python -m src.main

# 3. 打开 Web 面板
# → http://localhost:8080

# 4. 烧录固件到 ESP32
# 用 Arduino IDE 打开 firmware/agent-status-companion/agent-status-companion.ino
# 修改 WiFi 凭据 → 编译上传
```

## 项目结构

```
agent-status-companion/
├── firmware/
│   └── agent-status-companion/
│       └── agent-status-companion.ino   # ESP32 固件
├── host/
│   ├── requirements.txt
│   ├── src/
│   │   ├── config.py          # 配置管理
│   │   ├── status_model.py    # 数据模型
│   │   ├── mqtt_publisher.py  # MQTT 发布
│   │   ├── hermes_monitor.py  # Agent 监控
│   │   ├── aggregator.py      # 状态聚合
│   │   └── main.py            # CLI 入口
│   ├── web/
│   │   ├── app.py             # FastAPI 服务
│   │   └── static/
│   │       └── index.html     # 仪表盘
│   └── tests/
│       ├── test_mqtt.py
│       └── test_monitor.py
├── hardware/
│   ├── schematics/
│   │   └── wiring.md          # 接线图
│   └── enclosure/
│       └── case.scad          # 3D 外壳
└── docs/
    ├── plan.md                # 实施计划
    └── assembly.md            # 组装指南
```

## 硬件成本

| 元件 | 价格 |
|------|------|
| ESP32 DevKit | ¥15-25 |
| SSD1306 OLED | ¥8-12 |
| WS2812B LED | ¥1-3 |
| 其他 (电阻/电容/线材) | ¥3-5 |
| **总计** | **¥30-55** |

## 状态映射

| Agent 状态 | LED 颜色 | OLED 显示 |
|-----------|---------|-----------|
| IDLE (空闲) | 绿色 | "空闲" |
| WORKING (工作中) | 蓝色呼吸 | 当前任务 |
| WAITING (等待) | 橙色 | "等待中..." |
| ERROR (错误) | 红色闪烁 | 错误信息 |

## 通信协议

JSON over MQTT topic `agent/status`:

```json
{
  "status": "working",
  "agent_name": "hermes",
  "model": "deepseek-v4",
  "task": "分析 agent-status-companion 代码",
  "context_len": 8192,
  "cum_time": "2.5h",
  "cpu_percent": 45.2,
  "mem_mb": 512.0
}
```
