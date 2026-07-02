# Agent Status Companion v2

ESP32 桌面伴侣 — 实时显示 Hermes Agent 运行状态（思考/工作/等待/空闲）。

## v2 架构

```
Hermes 内部                         外部消费者
───────────                        ──────────
esp32-companion 插件                 state_watcher.py
  ├─ pre_llm_call  ─→ thinking ─┐     ├─ 终端可视化
  ├─ pre_tool_call ─→ working   ─┤     ├─ JSON 行输出
  ├─ pre_tool_call ─→ waiting ──→ JSON ─→ state_watcher.py
  ├─ post_llm_call ─→ idle      ─┤     └─ UDP 广播 → ESP32
  ├─ on_session_start           ─┘
  └─ on_session_end

对比 v1（废弃）：
  ✗ v1: 解析 agent.log → 猜测状态 → monkey-patch cli.py
  ✓ v2: plugin hooks → 精确状态 → 零侵入 Hermes 源码
```

## 项目结构

```
├── plugin/                  # Hermes 插件（放到 ~/.hermes/plugins/esp32-companion/）
│   ├── plugin.yaml
│   └── __init__.py
├── host/
│   └── state_watcher.py     # 后端：监控状态 + 终端面板 + UDP 广播
├── firmware/                # ESP32 固件（PlatformIO + Arduino）
│   └── agent-status-companion/
│       ├── platformio.ini
│       └── src/agent-status-companion.ino
├── hardware/                # 3D 外壳 + 接线图
│   ├── enclosure/case.stl
│   └── schematics/wiring.md
├── simulation/              # ESP32 模拟器 + Wokwi
└── docs/                    # 部署文档
```

## 快速开始

### 1. 安装插件

```bash
# 复制插件到 Hermes 用户插件目录
cp -r plugin/ "$HERMES_HOME/plugins/esp32-companion/"

# 启用
hermes plugins enable esp32-companion

# 重启 Hermes 生效
hermes
```

### 2. 运行后端

```bash
# 终端可视化（持续刷新）
python host/state_watcher.py

# JSON 模式（管道给其他程序）
python host/state_watcher.py --json

# UDP 广播模式（推送到 ESP32）
python host/state_watcher.py --udp
```

### 3. 烧录 ESP32 固件（可选）

```bash
cd firmware/agent-status-companion
pio run -e esp32dev -t upload
```

## 四种状态

| 状态 | 触发条件 | 颜文字 |
|------|----------|--------|
| **thinking** | LLM 开始思考 | `(..*)` |
| **working** | 工具执行中 | `(>_<)` |
| **waiting** | clarify 等用户回复 | `(o_o)?` |
| **idle** | 空闲等待 | `(^-^)` |

## 硬件

| 元件 | 型号 | 引脚 |
|------|------|------|
| ESP32 | DevKit (CH340) | COM3 |
| OLED | SSD1306 64×32 I2C | SDA=21, SCL=22, 0x3C |
| LCD | 1602A 16×2 | RS=12, EN=14, D4-7=26-32 |
| WiFi | king / kissking | UDP 255.255.255.255:8888 |

## 技术要点

- **状态捕获**：事件驱动（非轮询），毫秒级延迟
- **后端刷新**：300ms 轮询，仅状态变化时输出
- **零侵入**：不修改 Hermes 源码，纯插件实现
- **跨平台**：Windows / macOS / Linux
