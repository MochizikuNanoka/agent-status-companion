# 组装、烧录与开发指南 — AI Agent Status Companion v2

> 任务书_2 版本：真实 Hermes 连接 + Wokwi 模拟器开发 + PlatformIO

---

## 1. 开发流程（强制顺序）

```
① Wokwi 模拟器开发固件 → ② 真实 Hermes 推送数据 → ③ 模拟器接收真实数据 → ④ 烧录实体 ESP32
```

---

## 2. Wokwi 模拟器使用教程

### 2.1 在线使用（推荐）

1. 打开 https://wokwi.com/
2. 点击 "New Project" → "Import from file"
3. 导入 `simulation/wokwi/diagram.json`
4. 将 `firmware/agent-status-companion/agent-status-companion.ino` 内容粘贴到代码编辑器
5. 点击 "Start Simulation"

Wokwi 会自动识别 `#ifndef WOKWI` 条件编译，跳过实际 WiFi 连接。

### 2.2 测试 MQTT 通信

```bash
# 终端 1: 启动测试脚本（用公共 broker）
cd simulation/
python test_script.py --broker broker.emqx.io --loop

# 终端 2: 启动 Python 主机中间件（模拟模式）
cd host/
python -m src.main --simulate --broker broker.emqx.io
```

测试脚本会循环发送 IDLE → WORKING → WAITING → ERROR 状态序列，观察 Wokwi 中 OLED 和 LED 变化。

### 2.3 diagram.json 说明

```json
{
  "parts": [
    { "type": "wokwi-esp32-devkit-v1", "id": "esp32" },        // ESP32 开发板
    { "type": "wokwi-ssd1306", "id": "oled1", "attrs": {} },   // SSD1306 OLED 128x64
    { "type": "wokwi-neopixel-strip", "id": "led1", "attrs": {"pixelCount": "1"} }  // WS2812B LED
  ],
  "connections": [
    ["esp32:3.3V", "oled1:VCC", "red"],      // OLED 供电
    ["esp32:GND.1", "oled1:GND", "black"],
    ["esp32:21", "oled1:SDA", "green"],       // I2C 数据
    ["esp32:22", "oled1:SCL", "blue"],        // I2C 时钟
    ["esp32:VIN", "led1:VCC", "red"],         // LED 5V 供电
    ["esp32:GND.2", "led1:GND", "black"],
    ["esp32:16", "led1:DIN", "purple"]        // LED 数据
  ]
}
```

---

## 3. Hermes 监控实现细节

### 3.1 数据源架构

```
┌──────────────────────────────────────────────────────┐
│                   HermesMonitor                       │
│                                                      │
│  Primary:  agent.log 实时解析    ← 最高优先级         │
│    ↓ 失败                                             │
│  Fallback1: hermes status 子进程  ← CLI 调用          │
│    ↓ 失败                                             │
│  Fallback2: psutil 进程检测      ← 基础监控           │
│    ↓ 失败                                             │
│  IDLE 状态                                           │
│                                                      │
│  --simulate: 模拟模式，循环状态切换                    │
└──────────────────────────────────────────────────────┘
```

### 3.2 日志格式解析

Hermes 的 `agent.log` 中 API call 行格式：

```
2026-06-29 06:29:04,461 INFO [20260629_055232_7126c1] agent.conversation_loop: API call #60: model=deepseek-v4-pro provider=deepseek in=65171 out=718 total=65889 latency=6.9s cache=64256/65171 (99%)
```

提取字段：
| 日志字段 | StatusMessage 字段 | 正则 |
|----------|-------------------|------|
| `model=deepseek-v4-pro` | `model` | `model=([\w./-]+)` |
| `total=65889` | `context_len` | `total=(\d+)` |
| `[20260629_055232_7126c1]` | (session 追踪) | `\[(\w+)\]` |
| 最近 5s 内有新行 | `status=WORKING` | 时间戳差 |
| 最近 30s 内无新行 | `status=IDLE` | 时间戳差 |

### 3.3 hermes status 子进程

```bash
hermes status
# 输出包含:
# Model:        deepseek-v4-pro
# Provider:     DeepSeek
# Active:       1 session(s)
```

### 3.4 模拟模式

```bash
python -m src.main --simulate
```

每 8 秒自动循环：IDLE → WORKING → WAITING → IDLE，模拟真实 Agent 行为。用于无 Hermes 环境的开发和 Wokwi 测试。

---

## 4. 从模拟器迁移到实体硬件

### 步骤

1. **Wokwi 验证完成**
   - 所有状态灯颜色正确
   - OLED 显示正常（模型名、上下文长度、任务摘要）
   - MQTT 消息能正确触发更新

2. **移除 Wokwi 条件编译**
   ```cpp
   // 在 agent-status-companion.ino 中：
   // 注释掉或删除 #ifndef WOKWI / #else / #endif 块
   // 或定义 WOKWI_OFF 宏
   #define WOKWI_OFF  // 强制使用真实 WiFi
   ```

3. **配置 WiFi**
   ```cpp
   #define WIFI_SSID    "你的WiFi名"
   #define WIFI_PASS    "你的WiFi密码"
   ```

4. **烧录 ESP32**
   - 使用 Arduino IDE 或 PlatformIO:
   ```bash
   cd firmware/agent-status-companion/
   pio run -t upload
   pio device monitor
   ```

5. **启动真实 Hermes 监控**
   ```bash
   cd host/
   python -m src.main --broker <你的MQTT broker IP>
   ```

6. **验证端到端**
   - Hermes 执行任务 → OLED 显示 "Working" + 蓝色 LED
   - Hermes 空闲 → OLED 显示 "Idle" + 绿色 LED
   - 发送 MQTT 测试消息验证响应

---

## 5. PlatformIO 使用

### 安装
```bash
pip install platformio
# 或从 VS Code 扩展安装
```

### 编译 & 烧录
```bash
cd firmware/agent-status-companion/

# 编译
pio run

# 烧录 + 串口监视
pio run -t upload -t monitor

# 仅监视
pio device monitor
```

### 库依赖 (platformio.ini)
```ini
lib_deps =
    knolleary/PubSubClient @ ^2.8
    bblanchon/ArduinoJson @ ^7.0
    adafruit/Adafruit NeoPixel @ ^1.12
    adafruit/Adafruit SSD1306 @ ^2.5
    adafruit/Adafruit GFX Library @ ^1.11
```

---

## 6. 硬件接线（实体）

参考 `hardware/schematics/wiring.md`。

---

## 常见问题

| 问题 | 解决 |
|------|------|
| Wokwi OLED 不显示 | 刷新页面，确认 I2C 地址 0x3C |
| Wokwi LED 不亮 | 检查 GPIO16 连接 |
| agent.log 找不到 | Windows: `%LOCALAPPDATA%\hermes\logs\agent.log` |
| MQTT 连不上 | 检查 broker 地址，ESP32 只支持 2.4GHz WiFi |
| 烧录失败 | 按住 BOOT 再上电，松开后点击 Upload |
