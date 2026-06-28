# Agent Status Companion — v2

> 任务书_2：真实 Hermes WebSocket/日志连接 + Wokwi 模拟器开发 + PlatformIO

ESP32 桌面伴侣硬件 — 实时显示 Hermes Agent 状态（RGB LED + OLED 屏幕）。

## 架构

```
┌──────────────┐  agent.log     ┌──────────────┐  MQTT JSON    ┌──────────────┐
│  Hermes      │ ────────────→  │ Python 中间件  │ ────────────→ │ ESP32 固件    │
│ (实时运行)    │  hermes status │ (监控+聚合)    │               │ (LED + OLED) │
└──────────────┘                └──────────────┘               └──────────────┘
                                       │
                                       ├── Web 面板 (FastAPI:8080)
                                       ├── Wokwi 模拟器支持
                                       └── 模拟模式 (--simulate)
```

## 快速开始

```bash
# 1. 安装 Python 依赖
cd host && pip install -r requirements.txt

# 2. 模拟模式（无需真实 Hermes）
python -m src.main --simulate

# 3. 真实 Hermes 模式
python -m src.main

# 4. Web 面板 → http://localhost:8080
```

## Wokwi 模拟器

1. 打开 https://wokwi.com/ → Import `simulation/wokwi/diagram.json`
2. 粘贴 `firmware/agent-status-companion/agent-status-companion.ino`
3. 运行测试脚本: `python simulation/test_script.py --broker broker.emqx.io --loop`

## 项目结构

```
agent-status-companion/
├── firmware/agent-status-companion/
│   ├── agent-status-companion.ino    # ESP32 固件 (Wokwi 兼容)
│   └── platformio.ini                # PlatformIO 配置
├── host/
│   ├── src/
│   │   ├── config.py                 # 配置管理
│   │   ├── status_model.py           # 数据模型 (v2 JSON)
│   │   ├── mqtt_publisher.py         # MQTT 发布
│   │   ├── hermes_monitor.py         # Hermes 监控 (日志/CLI/进程)
│   │   ├── aggregator.py             # 状态聚合
│   │   └── main.py                   # CLI 入口
│   ├── web/                          # FastAPI 面板
│   └── tests/                        # 42 项测试
├── simulation/
│   ├── wokwi/diagram.json            # Wokwi 电路图
│   ├── wokwi/project.json            # Wokwi 项目文件
│   └── test_script.py                # MQTT 测试脚本
├── hardware/                         # 接线图 + 3D 外壳
└── docs/                             # 文档
```

## JSON 协议 v2

```json
{
  "agent": "hermes",
  "status": "working",
  "model": "deepseek-v4-pro",
  "context_len": 65889,
  "cum_time": "67m",
  "task_summary": "Researching AI gadgets...",
  "timestamp": "2026-06-29T06:29:04Z",
  "cpu_percent": 45.2,
  "mem_mb": 512.0
}
```

## 状态映射

| Agent 状态 | LED 颜色 | OLED 显示 |
|-----------|---------|-----------|
| IDLE (空闲) | 绿色常亮 | Idle |
| WORKING (工作中) | 蓝色呼吸 | 当前模型+任务 |
| WAITING (等待) | 橙色呼吸 | Waiting... |
| ERROR (错误) | 红色闪烁 | Error |

## 硬件成本: ¥30-55
