# 实战部署指南 — 从 Wokwi 迁移到真实 ESP32

> 硬件已接好：OLED (SDA→21, SCL→22, VCC→3V3, GND→GND)，RGB LED (GPIO4)

---

## 1. 烧录固件

### 方式 A: PlatformIO（推荐）

```bash
cd firmware/agent-status-companion/

# 编译
pio run

# 烧录 + 打开串口监视器
pio run -t upload -t monitor
```

### 方式 B: Arduino IDE

1. 打开 `firmware/agent-status-companion/agent-status-companion.ino`
2. **修改 WiFi 凭据**（文件内搜索 `WIFI_SSID` / `WIFI_PASS`）:
   ```cpp
   #define WIFI_SSID    "你的WiFi名"
   #define WIFI_PASS    "你的WiFi密码"
   ```
3. 选择 Board: `ESP32 Dev Module`
4. 选择端口: 插入 ESP32 后的 COM 口
5. 点击 Upload (→)

### 烧录失败解决

- **按住 BOOT 按钮** → 插入 USB → 松开按钮 → 点击 Upload
- 确认驱动已装: CP210x 或 CH340 驱动
- 尝试其他 USB 线（部分线仅充电无数据）

---

## 2. 验证硬件（Serial Monitor）

烧录完成后，**不要拔 USB**，打开串口监视器（115200 baud）。

### 预期启动输出

```
╔══════════════════════════════════════════╗
║  Agent Status Companion — ESP32 固件     ║
║  Hardware Ready                          ║
╚══════════════════════════════════════════╝
[HW] RGB LED 引脚: GPIO4
[HW] OLED I2C:     SDA=21, SCL=22
[HW] I2C 总线初始化完成
[OLED] 正在初始化 SSD1306 (0x3C)... 成功!
[LED] WS2812B 初始化完成 (GPIO4)
[WiFi] 连接中 SSID: YourWiFiSSID
[WiFi] 连接成功!
[WiFi] IP 地址: 192.168.1.100
[MQTT] Broker: broker.emqx.io:1883
========================================
[SYSTEM] 固件启动完成
========================================
```

### OLED 应显示

- 启动画面: "HERMES Status Companion Hardware Ready"
- 然后: 模型名、任务、上下文长度、CPU/内存进度条
- LED: 绿色常亮 (Idle)

---

## 3. Serial 命令调试

在串口监视器中发送以下命令测试硬件（**不需 MQTT/Hermes**）：

| 命令 | 效果 |
|------|------|
| `test:idle` | LED 变绿，OLED 显示 Idle |
| `test:working` | LED 蓝色呼吸，OLED 显示 Working + 模拟数据 |
| `test:waiting` | LED 橙色呼吸，OLED 显示 Waiting |
| `test:error` | LED 红色闪烁，OLED 显示 Error |
| `status` | 打印完整状态 |
| `help` | 显示帮助 |

**先跑这几个命令确认硬件全正常再继续。**

---

## 4. 启动主机中间件（连接真实 Hermes）

```bash
# 终端 1: 主机中间件
cd host/
python -m src.main --broker broker.emqx.io

# 输出:
# Hermes Agent 状态监控中间件
# MQTT: broker.emqx.io:1883 → agent/status
# Web:  http://0.0.0.0:8080
```

此时观察 ESP32 的 Serial 输出，会看到 `[MQTT] 收到消息` 和解析后的状态。

### Web 面板

浏览器打开 `http://localhost:8080`，深色仪表盘实时显示：

- 状态灯（脉冲动画）
- Agent 名称 + 模型
- 当前任务
- 上下文长度 + 累计时间
- CPU / 内存进度条

---

## 5. 端到端测试（完整链路）

```bash
# 终端 1: 主机中间件（真实 Hermes 模式）
cd host/
python -m src.main --broker broker.emqx.io

# 终端 2: 手动发送测试状态（模拟 Hermes 工作）
# 需要 mosquitto_pub 工具，或用 simulation/test_script.py
cd simulation/
python test_script.py --broker broker.emqx.io --loop
```

### 验证清单

- [ ] Serial 输出 "Hardware Ready"
- [ ] OLED 显示欢迎画面
- [ ] LED 初始绿色
- [ ] Serial 命令 `test:idle` → LED 绿
- [ ] Serial 命令 `test:working` → LED 蓝色呼吸
- [ ] Serial 命令 `test:error` → LED 红闪
- [ ] MQTT 消息触发 OLED 更新
- [ ] Web 面板实时更新
- [ ] Hermes 工作中 → LED 蓝, OLED 显示模型+任务

---

## 6. 常见问题排查

### OLED 不显示

| 检查项 | 方法 |
|--------|------|
| 接线正确 | SDA→21, SCL→22, VCC→3.3V, GND→GND |
| I2C 地址正确 | SSD1306 通常是 0x3C（有些是 0x3D） |
| Serial 输出 | 看 `[OLED]` 开头的日志 |
| 用 I2C Scanner 确认 | 烧录 I2C Scanner 例程扫描地址 |

### LED 不亮

| 检查项 | 方法 |
|--------|------|
| 接线 | DIN→GPIO4, VCC→5V(VIN), GND→GND |
| 方向 | WS2812B 数据有方向（DIN 接 GPIO） |
| 供电 | 5V 供电（VIN 引脚），不要用 3.3V |
| 测试 | Serial 发送 `test:working`，应有蓝光 |

### MQTT 连不上

| 检查项 | 方法 |
|--------|------|
| WiFi 连接 | Serial 查看 `[WiFi] IP 地址:` |
| 2.4GHz | ESP32 不支持 5GHz WiFi |
| Broker 可达 | `ping broker.emqx.io` |
| 换 broker | 改为本地 Mosquitto: `#define MQTT_BROKER "192.168.1.xxx"` |

### Serial 输出乱码

- **波特率**: 确认设为 115200
- **换行符**: 确认设为 "Newline" 或 "Both NL & CR"
- Arduino IDE: 右下角确认波特率
- PlatformIO: `monitor_speed = 115200`

### hermes_monitor.py 不工作

| 检查项 | 方法 |
|--------|------|
| Hermes 在运行 | 确认有 hermes 进程或 agent.log 在更新 |
| 模拟模式测试 | `python -m src.main --simulate` |
| 查看日志 | 中间件自身的输出日志 |

### 烧录失败

| 问题 | 解决 |
|------|------|
| "Connecting..." 超时 | 按住 BOOT → 插 USB → 松开 BOOT → 点 Upload |
| 端口不出现 | 安装 CP210x 驱动: https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers |
| 权限问题 (Linux) | `sudo usermod -a -G dialout $USER` 后重新登录 |

---

## 7. 从真实硬件切回 Wokwi

如需返回 Wokwi 开发：

```bash
# PlatformIO
pio run -e esp32dev-wokwi

# Arduino IDE
# 在代码顶部添加:
#define WOKWI
```

Wokwi 模式下自动使用 GPIO16（LED），跳过真实 WiFi。
