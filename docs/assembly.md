# 组装与烧录指南 — AI Agent Status Companion

## 1. 准备工作

### 需要安装的软件

| 软件 | 下载链接 | 用途 |
|------|----------|------|
| Arduino IDE 2.x | https://www.arduino.cc/en/software | 编译烧录 ESP32 |
| Python 3.11+ | https://www.python.org/ | 运行主机中间件 |
| Mosquitto MQTT | https://mosquitto.org/download/ | MQTT Broker (可选，可用公共 broker) |
| OpenSCAD (可选) | https://openscad.org/ | 预览/导出 3D 外壳 |

### Arduino IDE 配置

1. 打开 Arduino IDE → File → Preferences
2. Additional Boards Manager URLs 添加：
   ```
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   ```
3. Tools → Board → Boards Manager → 搜索 "esp32" → 安装 "esp32 by Espressif Systems"

### 安装 Arduino 库

Tools → Manage Libraries → 搜索并安装：

| 库名 | 作者 |
|------|------|
| PubSubClient | Nick O'Leary |
| ArduinoJson | Benoît Blanchon |
| Adafruit NeoPixel | Adafruit |
| Adafruit SSD1306 | Adafruit |
| Adafruit GFX Library | Adafruit |

---

## 2. 硬件组装

### 步骤

1. **焊接/连接 OLED**
   - ESP32 GND → OLED GND
   - ESP32 3.3V → OLED VCC
   - ESP32 GPIO21 → OLED SDA
   - ESP32 GPIO22 → OLED SCL

2. **焊接/连接 WS2812B LED**
   - ESP32 GND → LED GND
   - ESP32 5V/VIN → LED VCC（并联 100μF 电容）
   - ESP32 GPIO16 → 330Ω 电阻 → LED DIN

3. **固定到外壳**
   - OLED 对准面板窗口，用热熔胶或螺丝固定
   - LED 对准 LED 孔
   - ESP32 用尼龙柱或热熔胶固定
   - 盖板闭合

---

## 3. 烧录固件

1. 打开 `firmware/agent-status-companion/agent-status-companion.ino`
2. **修改 WiFi 凭据**（第 46-47 行）：
   ```cpp
   #define WIFI_SSID        "你的WiFi名"
   #define WIFI_PASS        "你的WiFi密码"
   ```
3. **修改 MQTT Broker**（第 52 行，默认用公共 broker 测试）：
   ```cpp
   #define MQTT_BROKER      "broker.emqx.io"  // 或用你自己的 Mosquitto
   ```
4. 选择 Board: `ESP32 Dev Module`
5. 选择正确的 COM 口
6. 点击 Upload（→ 箭头）
7. 烧录完成后打开 Serial Monitor (115200 baud)，查看连接日志

**预期输出：**
```
[WiFi] 连接中: YourWiFiSSID
[WiFi] 已连接! IP: 192.168.1.100
[MQTT] 连接中: broker.emqx.io:1883
[MQTT] 已连接!
[MAIN] Agent Status Companion 就绪
```

---

## 4. 运行主机中间件

```bash
cd host/

# 创建虚拟环境 (可选)
python -m venv venv
source venv/Scripts/activate  # Windows
# source venv/bin/activate    # Linux/Mac

# 安装依赖
pip install -r requirements.txt

# 启动 (默认配置)
python -m src.main

# 自定义 MQTT broker
python -m src.main --broker 192.168.1.50 --port 1883

# 同时启动 Web 面板
python -m src.main --web-port 8080
```

打开浏览器访问 `http://localhost:8080` 查看仪表盘。

---

## 5. 验证端到端

1. ESP32 上电，确认 OLED 显示 "Agent Status Companion" 启动画面
2. 启动 Python 主机中间件
3. 观察 OLED 显示状态变化（Idle → Working → Idle）
4. LED 颜色随状态变化（绿/蓝/橙/红）
5. 打开 Web 面板 `http://localhost:8080` 确认实时数据

### 模拟 Agent 状态 (无需真实 Agent)

```bash
# 手动发送测试状态到 MQTT
mosquitto_pub -h broker.emqx.io -t "agent/status" -m '{"status":"working","agent_name":"hermes","model":"deepseek-v4","task":"分析代码中...","context_len":8192,"cum_time":"2.5h","cpu_percent":45.2,"mem_mb":512.0}'

mosquitto_pub -h broker.emqx.io -t "agent/status" -m '{"status":"idle","agent_name":"hermes","model":"","task":"","context_len":0,"cum_time":"2.8h","cpu_percent":2.1,"mem_mb":128.0}'
```

---

## 常见问题

| 问题 | 解决方案 |
|------|----------|
| OLED 不显示 | 检查 I2C 地址 (使用 I2C Scanner 确认)，确认接线 |
| LED 不亮 | 检查 5V 供电，LED 数据线方向 |
| WiFi 连不上 | 确认 SSID/密码，ESP32 只支持 2.4GHz WiFi |
| MQTT 连不上 | 检查 broker 地址，确认网络可达 |
| 烧录失败 | 按住 BOOT 按钮再插 USB，松开后点击 Upload |
