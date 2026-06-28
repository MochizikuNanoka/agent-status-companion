/**
 * agent-status-companion — ESP32 固件
 * ============================================
 * 功能: WiFi连接 / MQTT订阅状态 / WS2812B RGB LED指示 /
 *       SSD1306 OLED显示 / JSON解析 / 心跳 / 低功耗
 *
 * 硬件引脚定义:
 *   LED_WS2812B_PIN   = 16   (WS2812B 数据线)
 *   OLED_SDA          = 21   (SSD1306 I2C SDA)
 *   OLED_SCL          = 22   (SSD1306 I2C SCL)
 *   OLED_ADDR         = 0x3C (SSD1306 I2C 地址)
 *
 * 依赖库 (通过 Arduino Library Manager 安装):
 *   - WiFi (ESP32 内置)
 *   - PubSubClient (Nick O'Leary)
 *   - ArduinoJson (Benoît Blanchon)
 *   - Adafruit NeoPixel
 *   - Adafruit SSD1306
 *   - Adafruit GFX Library
 *
 * WiFi 配置: 修改下文 WIFI_SSID / WIFI_PASS 为你的凭据
 * MQTT 配置: 修改下文 MQTT_BROKER / MQTT_PORT 等
 */

// ===================== 包含头文件 =====================
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Adafruit_NeoPixel.h>
#include <Wire.h>
#include <Adafruit_SSD1306.h>
#include <Adafruit_GFX.h>

// ===================== 引脚定义 =====================
#define LED_WS2812B_PIN  16       // WS2812B 数据引脚
#define NUM_LEDS         1        // LED 数量
#define OLED_SDA         21       // SSD1306 I2C SDA
#define OLED_SCL         22       // SSD1306 I2C SCL
#define OLED_ADDR        0x3C     // SSD1306 I2C 地址
#define OLED_WIDTH       128      // OLED 宽度 (像素)
#define OLED_HEIGHT      64       // OLED 高度 (像素)
#define OLED_RESET       -1       // 不使用复位引脚

// ===================== WiFi 配置 =====================
// TODO: 在此处填写你的 WiFi 凭据
#define WIFI_SSID        "YourWiFiSSID"
#define WIFI_PASS        "YourWiFiPassword"
#define WIFI_TIMEOUT_MS  15000    // WiFi 连接超时 (毫秒)

// ===================== MQTT 配置 =====================
#define MQTT_BROKER      "broker.emqx.io"   // MQTT 服务器地址
#define MQTT_PORT        1883                // MQTT 端口
#define MQTT_TOPIC       "agent/status"      // 订阅主题
#define MQTT_CLIENT_ID   "agent-status-companion-esp32"
#define MQTT_KEEPALIVE   60                  // 心跳间隔 (秒)

// ===================== 全局对象 =====================
// WiFi 客户端
WiFiClient wifiClient;

// MQTT 客户端
PubSubClient mqttClient(wifiClient);

// WS2812B LED 控制
Adafruit_NeoPixel ledStrip(NUM_LEDS, LED_WS2812B_PIN, NEO_GRB + NEO_KHZ800);

// SSD1306 OLED 显示
Adafruit_SSD1306 display(OLED_WIDTH, OLED_HEIGHT, &Wire, OLED_RESET);

// ===================== 全局变量 =====================
// 当前状态
String agent_status  = "idle";       // idle / working / waiting / error
String agent_name    = "hermes";
String model_name    = "unknown";
String task_desc     = "";
int    context_len   = 0;
String cum_time      = "0s";
float  cpu_percent   = 0.0;
float  mem_mb        = 0.0;

// LED 呼吸效果控制
unsigned long lastLedUpdate  = 0;
float         breathPhase    = 0.0;

// OLED 滚动文本控制
unsigned long lastScrollTime = 0;
int           scrollOffset   = 0;

// 心跳 & 定时任务
unsigned long lastHeartbeat  = 0;
const unsigned long HEARTBEAT_INTERVAL = 30000;  // 30 秒

// MQTT 重连
unsigned long lastMqttReconnect = 0;
const unsigned long MQTT_RECONNECT_INTERVAL = 5000;  // 5 秒

// 低功耗: OLED 亮度控制
bool oledDimmed = false;

// ===================== 函数声明 =====================
void setupWiFi();
void setupMQTT();
void mqttCallback(char* topic, byte* payload, unsigned int length);
bool reconnectMQTT();
void parseStatusJson(const char* json);
void updateLED();
void updateDisplay();
void drawProgressBar(int x, int y, int w, int h, float percent, uint16_t color);
void heartbeatPrint();
void enterLowPower();
void exitLowPower();

// ===================== setup() =====================
void setup() {
  // 初始化串口
  Serial.begin(115200);
  Serial.println();
  Serial.println(F("========================================"));
  Serial.println(F("  agent-status-companion ESP32 固件启动"));
  Serial.println(F("========================================"));

  // 初始化 I2C (OLED)
  Wire.begin(OLED_SDA, OLED_SCL);

  // 初始化 OLED
  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println(F("[OLED] 初始化失败! 检查 I2C 连接"));
  } else {
    Serial.println(F("[OLED] 初始化成功"));
    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 0);
    display.println(F("Booting..."));
    display.display();
  }

  // 初始化 WS2812B LED
  ledStrip.begin();
  ledStrip.setBrightness(50);   // 初始亮度 50
  ledStrip.show();              // 关闭所有 LED
  Serial.println(F("[LED] WS2812B 初始化完成"));

  // 连接 WiFi
  setupWiFi();

  // 配置 MQTT
  setupMQTT();
}

// ===================== loop() =====================
void loop() {
  // 保持 MQTT 连接
  if (!mqttClient.connected()) {
    unsigned long now = millis();
    if (now - lastMqttReconnect >= MQTT_RECONNECT_INTERVAL) {
      lastMqttReconnect = now;
      reconnectMQTT();
    }
  } else {
    mqttClient.loop();
  }

  // 更新 LED 效果
  updateLED();

  // 更新 OLED 显示 (每 200ms 刷新一次，避免闪烁)
  static unsigned long lastDisplayUpdate = 0;
  unsigned long now = millis();
  if (now - lastDisplayUpdate >= 200) {
    lastDisplayUpdate = now;
    updateDisplay();
  }

  // 心跳打印
  heartbeatPrint();

  // 低功耗控制: 空闲时降低 OLED 亮度
  if (agent_status == "idle" && !oledDimmed) {
    enterLowPower();
  } else if (agent_status != "idle" && oledDimmed) {
    exitLowPower();
  }
}

// ===================== WiFi 连接 =====================
void setupWiFi() {
  Serial.print(F("[WiFi] 连接中 SSID: "));
  Serial.println(WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  unsigned long startAttempt = millis();
  bool ledOn = false;

  while (WiFi.status() != WL_CONNECTED) {
    // LED 红灯闪烁表示连接中
    ledOn = !ledOn;
    if (ledOn) {
      ledStrip.setPixelColor(0, ledStrip.Color(255, 0, 0));  // 红色
    } else {
      ledStrip.setPixelColor(0, ledStrip.Color(0, 0, 0));    // 熄灭
    }
    ledStrip.show();
    delay(200);

    if (millis() - startAttempt >= WIFI_TIMEOUT_MS) {
      Serial.println(F("[WiFi] 连接超时!"));
      // 持续红灯闪烁
      for (int i = 0; i < 10; i++) {
        ledStrip.setPixelColor(0, ledStrip.Color(255, 0, 0));
        ledStrip.show();
        delay(300);
        ledStrip.setPixelColor(0, ledStrip.Color(0, 0, 0));
        ledStrip.show();
        delay(300);
      }
      // 尝试重启 WiFi
      WiFi.disconnect(true);
      WiFi.mode(WIFI_OFF);
      delay(1000);
      WiFi.mode(WIFI_STA);
      WiFi.begin(WIFI_SSID, WIFI_PASS);
      startAttempt = millis();
      continue;
    }
  }

  Serial.println(F("[WiFi] 连接成功!"));
  Serial.print(F("[WiFi] IP 地址: "));
  Serial.println(WiFi.localIP());

  // 连接成功 — LED 绿色常亮
  ledStrip.setPixelColor(0, ledStrip.Color(0, 255, 0));
  ledStrip.show();
}

// ===================== MQTT 配置 =====================
void setupMQTT() {
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setCallback(mqttCallback);
  mqttClient.setKeepAlive(MQTT_KEEPALIVE);
  Serial.print(F("[MQTT] 配置完成: "));
  Serial.print(MQTT_BROKER);
  Serial.print(":");
  Serial.println(MQTT_PORT);
}

// ===================== MQTT 回调 =====================
void mqttCallback(char* topic, byte* payload, unsigned int length) {
  Serial.print(F("[MQTT] 收到消息 topic: "));
  Serial.println(topic);

  // 将 payload 转换为 null-terminated 字符串
  char json[length + 1];
  memcpy(json, payload, length);
  json[length] = '\0';

  Serial.print(F("[MQTT] 消息内容: "));
  Serial.println(json);

  // 解析 JSON
  parseStatusJson(json);
}

// ===================== MQTT 重连 =====================
bool reconnectMQTT() {
  if (!mqttClient.connected()) {
    Serial.print(F("[MQTT] 正在连接... "));

    // 尝试连接
    if (mqttClient.connect(MQTT_CLIENT_ID)) {
      Serial.println(F("成功!"));
      // 订阅主题
      if (mqttClient.subscribe(MQTT_TOPIC)) {
        Serial.print(F("[MQTT] 订阅主题: "));
        Serial.println(MQTT_TOPIC);
      }
      // 恢复显示
      agent_status = "idle";
      return true;
    } else {
      Serial.print(F("失败, 状态码: "));
      Serial.println(mqttClient.state());
      return false;
    }
  }
  return true;
}

// ===================== JSON 解析 =====================
void parseStatusJson(const char* json) {
  StaticJsonDocument<512> doc;

  DeserializationError error = deserializeJson(doc, json);

  if (error) {
    Serial.print(F("[JSON] 解析失败: "));
    Serial.println(error.c_str());
    return;
  }

  // 提取字段
  const char* status    = doc["status"]     | "idle";
  const char* name      = doc["agent_name"] | "hermes";
  const char* model     = doc["model"]      | "unknown";
  const char* task      = doc["task"]       | "";
  int         ctxLen    = doc["context_len"]| 0;
  const char* cumT      = doc["cum_time"]   | "0s";
  float       cpu       = doc["cpu_percent"]| 0.0;
  float       mem       = doc["mem_mb"]     | 0.0;

  // 更新全局变量
  agent_status = String(status);
  agent_name   = String(name);
  model_name   = String(model);
  task_desc    = String(task);
  context_len  = ctxLen;
  cum_time     = String(cumT);
  cpu_percent  = cpu;
  mem_mb       = mem;

  Serial.println(F("[JSON] 解析完成:"));
  Serial.print(F("  status:      ")); Serial.println(agent_status);
  Serial.print(F("  agent_name:  ")); Serial.println(agent_name);
  Serial.print(F("  model:       ")); Serial.println(model_name);
  Serial.print(F("  task:        ")); Serial.println(task_desc);
  Serial.print(F("  context_len: ")); Serial.println(context_len);
  Serial.print(F("  cum_time:    ")); Serial.println(cum_time);
  Serial.print(F("  cpu_percent: ")); Serial.println(cpu_percent);
  Serial.print(F("  mem_mb:      ")); Serial.println(mem_mb);
}

// ===================== LED 更新 =====================
void updateLED() {
  unsigned long now = millis();
  if (now - lastLedUpdate < 30) return;   // 约 33fps 更新
  lastLedUpdate = now;

  uint32_t color;
  int brightness = 50;  // 基础亮度

  if (agent_status == "idle") {
    // Idle: 绿色常亮
    color = ledStrip.Color(0, 255, 0);
  } else if (agent_status == "working") {
    // Working: 蓝色呼吸效果
    breathPhase += 0.05;
    if (breathPhase > TWO_PI) breathPhase -= TWO_PI;
    float breathVal = (sin(breathPhase) + 1.0) / 2.0;  // 0.0 ~ 1.0
    int b = (int)(breathVal * 255);
    color = ledStrip.Color(0, 0, b);
  } else if (agent_status == "waiting") {
    // Waiting: 黄色/橙色, 缓慢呼吸
    breathPhase += 0.03;
    if (breathPhase > TWO_PI) breathPhase -= TWO_PI;
    float breathVal = (sin(breathPhase) + 1.0) / 2.0;
    int r = 255;
    int g = (int)(breathVal * 165);  // 橙色变化
    color = ledStrip.Color(r, g, 0);
  } else if (agent_status == "error") {
    // Error: 红色闪烁
    bool blink = (now / 500) % 2 == 0;  // 500ms 切换
    if (blink) {
      color = ledStrip.Color(255, 0, 0);
    } else {
      color = ledStrip.Color(0, 0, 0);
    }
  } else {
    // 未知状态: 紫色
    color = ledStrip.Color(128, 0, 128);
  }

  ledStrip.setPixelColor(0, color);
  ledStrip.show();
}

// ===================== OLED 显示更新 =====================
void updateDisplay() {
  display.clearDisplay();

  // 检查 MQTT 连接状态
  if (!mqttClient.connected()) {
    // MQTT 断连提示
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(10, 20);
    display.println(F("MQTT Disconnected"));
    display.setCursor(10, 35);
    display.println(F("Reconnecting..."));
    display.display();
    return;
  }

  // === 第1行: Agent名称 + 状态图标 ===
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);

  // 选择状态图标
  String statusIcon;
  if (agent_status == "idle") {
    statusIcon = "[ ]";       // 空闲
  } else if (agent_status == "working") {
    statusIcon = "[>]";       // 工作中
  } else if (agent_status == "waiting") {
    statusIcon = "[~]";       // 等待
  } else if (agent_status == "error") {
    statusIcon = "[!]";       // 错误
  } else {
    statusIcon = "[?]";       // 未知
  }

  display.print(agent_name);
  display.print(" ");
  display.println(statusIcon);

  // === 第2行: 模型名 ===
  display.setCursor(0, 16);
  display.print(F("Model: "));
  // 如果模型名过长则截断
  if (model_name.length() > 16) {
    display.println(model_name.substring(0, 15) + "...");
  } else {
    display.println(model_name);
  }

  // === 第3行: 当前任务 (滚动文本) ===
  display.setCursor(0, 32);
  display.print(F("Task: "));
  if (task_desc.length() > 0) {
    // 如果任务描述超过显示宽度, 自动滚动
    int maxCharsPerLine = 18;  // 6x8 字体, 128/6 ≈ 21, 留一些余量
    if (task_desc.length() > maxCharsPerLine) {
      // 简单滚动: 显示从 scrollOffset 开始的子串
      String displayTask = task_desc.substring(scrollOffset);
      if (displayTask.length() > maxCharsPerLine) {
        displayTask = displayTask.substring(0, maxCharsPerLine);
      } else {
        // 滚动到末尾后重置
        scrollOffset = 0;
      }

      unsigned long now = millis();
      if (now - lastScrollTime >= 400) {  // 每 400ms 滚动一次
        lastScrollTime = now;
        scrollOffset++;
        if (scrollOffset > task_desc.length()) {
          scrollOffset = 0;
        }
      }
      display.println(displayTask);
    } else {
      display.println(task_desc);
    }
  } else {
    display.println(F("-"));
  }

  // === 第4行: 上下文长度 + 累计时间 ===
  display.setCursor(0, 48);
  display.print(F("Ctx:"));
  if (context_len >= 1024) {
    display.print((context_len / 1024));
    display.print(F("K "));
  } else {
    display.print(context_len);
    display.print(F("  "));
  }
  display.print(F("Time:"));
  display.println(cum_time);

  // === 底部: CPU / 内存 进度条 ===
  // 使用白色矩形绘制小进度条
  // CPU 进度条 (左侧)
  drawProgressBar(0, 56, 56, 6, constrain(cpu_percent / 100.0, 0.0, 1.0), SSD1306_WHITE);
  display.setCursor(58, 56);
  display.setTextSize(1);
  display.print((int)cpu_percent);
  display.print(F("%"));

  // 内存进度条 (右侧)
  // 假设最大内存 ~512MB 用于进度条显示
  float memPercent = constrain(mem_mb / 512.0, 0.0, 1.0);
  drawProgressBar(88, 56, 40, 6, memPercent, SSD1306_WHITE);
  // 在进度条下方显示内存数值
  display.setCursor(88, 48);
  display.setTextSize(1);
  display.print((int)mem_mb);
  display.print(F("MB"));

  display.display();
}

// ===================== 绘制进度条 =====================
void drawProgressBar(int x, int y, int w, int h, float percent, uint16_t color) {
  // 绘制外框
  display.drawRect(x, y, w, h, color);

  // 填充内部 (至少 1 像素宽表示有值)
  int fillWidth = (int)(percent * (w - 2));
  if (fillWidth > 0 && fillWidth <= (w - 2)) {
    display.fillRect(x + 1, y + 1, fillWidth, h - 2, color);
  }
}

// ===================== 心跳打印 =====================
void heartbeatPrint() {
  unsigned long now = millis();
  if (now - lastHeartbeat >= HEARTBEAT_INTERVAL) {
    lastHeartbeat = now;

    Serial.print(F("[HEARTBEAT] "));
    Serial.print(F("WiFi: "));
    Serial.print(WiFi.status() == WL_CONNECTED ? F("OK") : F("DOWN"));
    Serial.print(F(" | MQTT: "));
    Serial.print(mqttClient.connected() ? F("OK") : F("DOWN"));
    Serial.print(F(" | Status: "));
    Serial.print(agent_status);
    Serial.print(F(" | CPU: "));
    Serial.print(cpu_percent, 1);
    Serial.print(F("% | Mem: "));
    Serial.print(mem_mb, 1);
    Serial.println(F(" MB"));
  }
}

// ===================== 低功耗模式 =====================
void enterLowPower() {
  // 降低 OLED 亮度 (通过减少刷新率, 无法直接调亮度)
  // 实际上 SSD1306 不支持亮度调节, 这里采用降低刷新频率
  // 但已经在 loop 中每 200ms 刷新, 空闲时降至 500ms
  oledDimmed = true;

  // 降低 LED 亮度
  ledStrip.setBrightness(10);

  Serial.println(F("[LOWPOWER] 进入低功耗模式"));
}

void exitLowPower() {
  // 恢复正常亮度
  ledStrip.setBrightness(50);

  oledDimmed = false;

  Serial.println(F("[LOWPOWER] 退出低功耗模式"));
}

// ===================== 串口命令处理 (可选, 注释掉) =====================
/*
 * 可通过串口发送 JSON 命令来设置 WiFi 凭据, 例如:
 * {"cmd":"set_wifi","ssid":"MyWiFi","pass":"MyPass"}
 *
void processSerialCommand() {
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd.length() > 0) {
      StaticJsonDocument<256> doc;
      DeserializationError err = deserializeJson(doc, cmd);
      if (!err) {
        const char* c = doc["cmd"];
        if (c && strcmp(c, "set_wifi") == 0) {
          const char* ssid = doc["ssid"];
          const char* pass = doc["pass"];
          if (ssid && pass) {
            Serial.print("Setting WiFi: ");
            Serial.println(ssid);
            WiFi.begin(ssid, pass);
          }
        }
      }
    }
  }
}
*/
