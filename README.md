# Agent Status Companion

ESP32 桌面硬件伴侣 — 实时显示 Hermes Agent 运行状态（OLED + LCD 双屏）。

## 效果

```
OLED (64×32)          LCD 1602 (16×2)
┌──────────┐          ┌──────────────────┐
│deepseek-v4│          │(◔_◔) Busy        │
│Ctx: 29%   │          │294.5K/1M         │
└──────────┘          └──────────────────┘
```

状态自动切换：idle → working → waiting，颜文字和颜色跟 Hermes TUI 同步。

## 工作原理

```
Hermes CLI 运行中 → agent.log → push_to_esp32.py → UDP广播 → ESP32 → OLED + LCD
                                ↑ 50ms 文件指针跟踪          ↑ 192.168.0.255:8888
```

## 快速开始

### 1. 烧录固件（首次）

```bash
export PATH="$PATH:$HOME/.platformio/penv/Scripts"
cd firmware/agent-status-companion
pio run -t upload -e esp32dev
```

### 2. 启动推送

```bash
cd host
python push_to_esp32.py
```

终端会打印实时状态，ESP32 的 OLED 和 LCD 同步显示。

### 3. 自定义显示

编辑 `host/config.yaml`，改颜文字、显示格式、状态简称，无需重烧固件：

```yaml
kaomoji:
  idle: "(^_^)"
  working: "(◔_◔)"
  waiting: "(◕‿◕✿)"

display:
  oled_line1: "{model}"
  oled_line2: "Ctx: {ctx_pct}"
  lcd_line1: "{kaomoji} {status_short}"
  lcd_line2: "{ctx_k}/1M"
```

## 硬件

| 组件 | 规格 | 引脚 |
|------|------|------|
| ESP32 | DevKit CH340 | COM3 |
| OLED | SSD1306 64×32 I2C 0x3C | SDA=21, SCL=22 |
| LCD | 1602A 16×2 并行 4-bit | RS=12, EN=14, D4=26, D5=25, D6=33, D7=32 |
| LED | WS2812B | GPIO4 (暂禁用) |

## JSON 协议

```json
{
  "status": "working",
  "agent": "hermes",
  "model": "deepseek-v4-pro",
  "context_len": 294898,
  "cum_time": "5h30m",
  "timestamp": "2026-07-02T...",
  "oled_line1": "deepseek-v4-pro",
  "lcd_line1": "(◔_◔) Busy",
  "ctx_display": "294.5K/1M"
}
```

## 项目结构

```
agent-status-companion/
├── firmware/agent-status-companion/
│   ├── src/agent-status-companion.ino   # ESP32 固件
│   └── platformio.ini                   # PlatformIO 配置
├── host/
│   ├── push_to_esp32.py                 # 主推送脚本（唯一入口）
│   └── config.yaml                      # 显示配置（改颜文字/格式）
├── simulation/
│   └── wokwi/                           # Wokwi 模拟器
├── hardware/
│   ├── schematics/wiring.md             # 接线图
│   └── enclosure/                       # 3D 外壳 (OpenSCAD)
└── docs/
```

## 技术要点

- **50ms 实时跟踪**：文件指针 `readline()` + 读增量，不用轮询
- **0.5s 状态防抖**：消除 working↔idle 快速切换导致的 OLED 闪烁
- **会话时间持久化**：`.session_start.txt` 防重启丢失
- **哑终端架构**：固件只渲染，格式在 `config.yaml` 定义
- **UDP 广播**：无需知道 ESP32 IP，无需 broker，比串口/MQTT 可靠
