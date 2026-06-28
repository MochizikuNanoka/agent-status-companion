/**
 * agent-status-companion — ESP32 固件 (实战迁移版)
 * ============================================
 * 功能: WiFi连接 / MQTT订阅状态 / WS2812B RGB LED指示 /
 *       SSD1306 OLED显示 / JSON解析 / 心跳 / 低功耗 /
 *       Serial调试命令 / 硬件自检
 *
 * === 真实硬件引脚定义 ===
 *   LED_WS2812B_PIN   = 4    (WS2812B 数据线 — 实际接线)
 *   OLED_SDA          = 21   (SSD1306 I2C SDA)
 *   OLED_SCL          = 22   (SSD1306 I2C SCL)
 *   OLED_ADDR         = 0x3C (SSD1306 I2C 地址)
 *
 * === Wokwi 模拟器引脚 (模拟用) ===
 *   LED_WS2812B_PIN   = 16   (Wokwi 默认)
 *   编译时定义 WOKWI 宏自动切换
 *
 * 依赖库 (通过 Arduino Library Manager 或 PlatformIO 安装):
 *   - WiFi (ESP32 内置)
 *   - PubSubClient (Nick O'Leary)
 *   - ArduinoJson (Benoît Blanchon)
 *   - Adafruit NeoPixel
 *   - Adafruit SSD1306
 *   - Adafruit GFX Library
 *
 * WiFi 配置: 修改下文 WIFI_SSID / WIFI_PASS 为你的凭据
 * MQTT 配置: 修改下文 MQTT_BROKER / MQTT_PORT 等
 *
 * === Serial 测试命令 (115200 baud) ===
 *   发送以下文本命令测试不同状态:
 *     test:idle      — 切换到 IDLE 状态
 *     test:working   — 切换到 WORKING 状态
 *     test:waiting   — 切换到 WAITING 状态
 *     test:error     — 切换到 ERROR 状态
 *     status         — 打印当前状态
 *     help           — 显示帮助
 *
 * ===================== JSON 消息格式 (MQTT v2) =====================
 * {
 *   "status":       "idle" | "working" | "waiting" | "error",
 *   "agent":        "hermes",
 *   "model":        "deepseek-v4-pro",
 *   "task_summary": "正在分析代码...",
 *   "context_len":  65889,
 *   "cum_time":     "67m",
 *   "cpu_percent":  45.2,
 *   "mem_mb":       512.0,
 *   "timestamp":    "2026-06-29T06:29:04Z"
 * }
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
#ifdef WOKWI
  #define LED_WS2812B_PIN  16     // Wokwi 模拟器引脚
#else
  #define LED_WS2812B_PIN  4      // 真实硬件引脚 (实际接线)
#endif
#define NUM_LEDS         1        // LED 数量
#define OLED_SDA         21       // SSD1306 I2C SDA
#define OLED_SCL         22       // SSD1306 I2C SCL
#define OLED_ADDR        0x3C     // SSD1306 I2C 地址
#define OLED_WIDTH       128      // OLED 宽度 (像素)
#define OLED_HEIGHT      64       // OLED 高度 (像素)
#define OLED_RESET       -1       // 不使用复位引脚

// ===================== WiFi 配置 =====================
// TODO: 在此处填写你的 WiFi 凭据
#define WIFI_SSID        "YOUR_SSID"
#define WIFI_PASS        "YOUR_PASSWORD"
#define WIFI_TIMEOUT_MS  15000    // WiFi 连接超时 (毫秒)

// ===================== MQTT 配置 =====================
#define MQTT_BROKER      "broker.emqx.io"   // MQTT 服务器地址 (测试用公共 broker)
#define MQTT_PORT        1883                // MQTT 端口
#define MQTT_TOPIC       "agent/status"      // 订阅主题
#define MQTT_CLIENT_ID   "agent-status-companion-esp32"
#define MQTT_KEEPALIVE   60                  // 心跳间隔 (秒)

// ===================== 全局对象 =====================
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);
Adafruit_NeoPixel ledStrip(NUM_LEDS, LED_WS2812B_PIN, NEO_GRB + NEO_KHZ800);
Adafruit_SSD1306 display(OLED_WIDTH, OLED_HEIGHT, &Wire, OLED_RESET);

// ===================== 全局变量 =====================
String agent_status  = "idle";
String agent         = "hermes";
String model_name    = "unknown";
String task_desc     = "";
int    context_len   = 0;
String cum_time      = "0s";
float  cpu_percent   = 0.0;
float  mem_mb        = 0.0;
String timestamp     = "";

// 硬件状态
bool oledOk          = false;       // OLED 是否初始化成功
bool wifiOk          = false;       // WiFi 是否连接

// LED 呼吸效果
unsigned long lastLedUpdate  = 0;
float         breathPhase    = 0.0;

// OLED 滚动文本
unsigned long lastScrollTime = 0;
int           scrollOffset   = 0;

// 心跳 & 定时
unsigned long lastHeartbeat  = 0;
const unsigned long HEARTBEAT_INTERVAL = 30000;  // 30 秒

// MQTT 重连
unsigned long lastMqttReconnect = 0;
int           mqttReconnectCount = 0;
const unsigned long MQTT_RECONNECT_INTERVAL = 5000;  // 5 秒

// 低功耗
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
void processSerialCommand();
void showWelcomeScreen();
void applyTestState(const char* state);

// ===================== setup() =====================
void setup() {
  // === 串口初始化 ===
  Serial.begin(115200);
  delay(500);  // 等待串口稳定
  Serial.println();
  Serial.println(F("╔══════════════════════════════════════════╗"));
  Serial.println(F("║  Agent Status Companion — ESP32 固件     ║"));
  Serial.println(F("║  Hardware Ready                          ║"));
  Serial.println(F("╚══════════════════════════════════════════╝"));
  Serial.print(F("[HW] RGB LED 引脚: GPIO"));
  Serial.println(LED_WS2812B_PIN);
  Serial.print(F("[HW] OLED I2C:     SDA="));
  Serial.print(OLED_SDA);
  Serial.print(F(", SCL="));
  Serial.println(OLED_SCL);

  // === I2C 初始化 ===
  Wire.begin(OLED_SDA, OLED_SCL);
  Serial.println(F("[HW] I2C 总线初始化完成"));

  // === OLED 初始化 (带错误处理) ===
  Serial.print(F("[OLED] 正在初始化 SSD1306 (0x3C)... "));
  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println(F("失败!"));
    Serial.println(F("[OLED] 请检查:"));
    Serial.println(F("       1. SDA→GPIO21, SCL→GPIO22 接线"));
    Serial.println(F("       2. VCC→3.3V, GND→GND 供电"));
    Serial.println(F("       3. I2C 地址是否为 0x3C"));
    Serial.println(F("[OLED] OLED 功能已禁用，LED 功能正常"));
    oledOk = false;
  } else {
    Serial.println(F("成功!"));
    oledOk = true;
    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    showWelcomeScreen();
  }

  // === WS2812B LED 初始化 ===
  ledStrip.begin();
  ledStrip.setBrightness(50);
  ledStrip.setPixelColor(0, ledStrip.Color(0, 255, 0));  // 绿色=硬件就绪
  ledStrip.show();
  Serial.println(F("[LED] WS2812B 初始化完成 (GPIO"));
  Serial.print(LED_WS2812B_PIN);
  Serial.println(F(")"));

  // === WiFi 连接 ===
#ifdef WOKWI
  Serial.println(F("[WOKWI] 模拟模式 - 跳过 WiFi 连接"));
  wifiOk = true;  // Wokwi 模拟 WiFi 已连接
#else
  setupWiFi();
#endif

  // === MQTT 配置 ===
  setupMQTT();

  // === 启动完成 ===
  Serial.println(F("========================================"));
  Serial.println(F("[SYSTEM] 固件启动完成"));
  Serial.println(F("[SYSTEM] 可用 Serial 命令: test:idle, test:working, test:waiting, test:error, status, help"));
  Serial.println(F("========================================"));
}

// ===================== loop() =====================
void loop() {
  // === Serial 命令处理 ===
  processSerialCommand();

  // === MQTT 保持连接 ===
  if (!mqttClient.connected()) {
    unsigned long now = millis();
    if (now - lastMqttReconnect >= MQTT_RECONNECT_INTERVAL) {
      lastMqttReconnect = now;
      reconnectMQTT();
    }
  } else {
    mqttClient.loop();
  }

  // === LED 效果更新 ===
  updateLED();

  // === OLED 显示更新 ===
  static unsigned long lastDisplayUpdate = 0;
  unsigned long now = millis();
  if (now - lastDisplayUpdate >= 200) {
    lastDisplayUpdate = now;
    if (oledOk) {
      updateDisplay();
    }
  }

  // === 心跳 ===
  heartbeatPrint();

  // === 低功耗 ===
  if (agent_status == "idle" && !oledDimmed) {
    enterLowPower();
  } else if (agent_status != "idle" && oledDimmed) {
    exitLowPower();
  }
}

// ===================== OLED 欢迎画面 =====================
void showWelcomeScreen() {
  display.clearDisplay();
  display.setTextSize(2);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(20, 10);
  display.println(F("HERMES"));
  display.setTextSize(1);
  display.setCursor(10, 35);
  display.println(F("Status Companion"));
  display.setCursor(15, 50);
  display.println(F("Hardware Ready"));
  display.display();
  delay(2000);

  // 滚动动画
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(5, 28);
  display.println(F("Connecting..."));
  display.display();
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
    // 红灯闪烁 = 连接中
    ledOn = !ledOn;
    ledStrip.setPixelColor(0, ledOn ? ledStrip.Color(255, 0, 0) : ledStrip.Color(0, 0, 0));
    ledStrip.show();
    delay(200);

    if (millis() - startAttempt >= WIFI_TIMEOUT_MS) {
      Serial.println(F("[WiFi] 连接超时! 自动重试..."));
      // 快速闪烁表示失败
      for (int i = 0; i < 8; i++) {
        ledStrip.setPixelColor(0, ledStrip.Color(255, 0, 0));
        ledStrip.show(); delay(150);
        ledStrip.setPixelColor(0, ledStrip.Color(0, 0, 0));
        ledStrip.show(); delay(150);
      }
      // 重启 WiFi 模块
      WiFi.disconnect(true);
      WiFi.mode(WIFI_OFF);
      delay(1000);
      WiFi.mode(WIFI_STA);
      WiFi.begin(WIFI_SSID, WIFI_PASS);
      startAttempt = millis();
    }
  }

  wifiOk = true;
  Serial.println(F("[WiFi] 连接成功!"));
  Serial.print(F("[WiFi] IP 地址: "));
  Serial.println(WiFi.localIP());

  // 绿色常亮 = WiFi 就绪
  ledStrip.setPixelColor(0, ledStrip.Color(0, 255, 0));
  ledStrip.show();
}

// ===================== MQTT 配置 =====================
void setupMQTT() {
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setCallback(mqttCallback);
  mqttClient.setKeepAlive(MQTT_KEEPALIVE);
  Serial.print(F("[MQTT] Broker: "));
  Serial.print(MQTT_BROKER);
  Serial.print(F(":"));
  Serial.println(MQTT_PORT);
}

// ===================== MQTT 回调 =====================
void mqttCallback(char* topic, byte* payload, unsigned int length) {
  Serial.print(F("[MQTT] 收到消息 → "));

  char json[length + 1];
  memcpy(json, payload, length);
  json[length] = '\0';

  Serial.println(json);
  parseStatusJson(json);
}

// ===================== MQTT 重连 =====================
bool reconnectMQTT() {
  if (mqttClient.connected()) return true;

  mqttReconnectCount++;
  Serial.print(F("[MQTT] 第 "));
  Serial.print(mqttReconnectCount);
  Serial.print(F(" 次重连尝试... "));

  if (mqttClient.connect(MQTT_CLIENT_ID)) {
    Serial.println(F("成功!"));
    mqttReconnectCount = 0;
    if (mqttClient.subscribe(MQTT_TOPIC)) {
      Serial.print(F("[MQTT] 已订阅: "));
      Serial.println(MQTT_TOPIC);
    }
    agent_status = "idle";
    return true;
  } else {
    Serial.print(F("失败 (状态码: "));
    Serial.print(mqttClient.state());
    Serial.println(F(")"));
    return false;
  }
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

  const char* status    = doc["status"]       | "idle";
  const char* name      = doc["agent"]        | "hermes";
  const char* model     = doc["model"]        | "unknown";
  const char* task      = doc["task_summary"] | "";
  int         ctxLen    = doc["context_len"]  | 0;
  const char* cumT      = doc["cum_time"]     | "0s";
  float       cpu       = doc["cpu_percent"]  | 0.0;
  float       mem       = doc["mem_mb"]       | 0.0;
  const char* ts        = doc["timestamp"]    | "";

  agent_status = String(status);
  agent        = String(name);
  model_name   = String(model);
  task_desc    = String(task);
  context_len  = ctxLen;
  cum_time     = String(cumT);
  cpu_percent  = cpu;
  mem_mb       = mem;
  timestamp    = String(ts);

  Serial.print(F("[JSON] status=")); Serial.print(agent_status);
  Serial.print(F(" model=")); Serial.print(model_name);
  Serial.print(F(" ctx=")); Serial.print(context_len);
  Serial.print(F(" task=")); Serial.println(task_desc);
}

// ===================== Serial 命令处理 =====================
void processSerialCommand() {
  if (!Serial.available()) return;

  String cmd = Serial.readStringUntil('\n');
  cmd.trim();
  if (cmd.length() == 0) return;

  Serial.print(F("[CMD] "));
  Serial.println(cmd);

  // === test:xxx 测试状态切换 ===
  if (cmd.startsWith("test:")) {
    String state = cmd.substring(5);
    applyTestState(state.c_str());

  // === status 打印当前状态 ===
  } else if (cmd == "status") {
    Serial.println(F("=== 当前状态 ==="));
    Serial.print(F("  Agent:    ")); Serial.println(agent);
    Serial.print(F("  Status:   ")); Serial.println(agent_status);
    Serial.print(F("  Model:    ")); Serial.println(model_name);
    Serial.print(F("  Task:     ")); Serial.println(task_desc);
    Serial.print(F("  Context:  ")); Serial.println(context_len);
    Serial.print(F("  Time:     ")); Serial.println(cum_time);
    Serial.print(F("  CPU:      ")); Serial.print(cpu_percent); Serial.println(F("%"));
    Serial.print(F("  Memory:   ")); Serial.print(mem_mb); Serial.println(F(" MB"));
    Serial.print(F("  Timestamp:")); Serial.println(timestamp);
    Serial.print(F("  WiFi:     ")); Serial.println(wifiOk ? F("OK") : F("DOWN"));
    Serial.print(F("  MQTT:     "));
    Serial.println(mqttClient.connected() ? F("OK") : F("DOWN"));
    Serial.print(F("  OLED:     ")); Serial.println(oledOk ? F("OK") : F("FAIL"));

  // === help ===
  } else if (cmd == "help") {
    Serial.println(F("=== Serial 命令 ==="));
    Serial.println(F("  test:idle     — 切换到 IDLE 状态"));
    Serial.println(F("  test:working  — 切换到 WORKING 状态"));
    Serial.println(F("  test:waiting  — 切换到 WAITING 状态"));
    Serial.println(F("  test:error    — 切换到 ERROR 状态"));
    Serial.println(F("  status        — 显示当前状态"));
    Serial.println(F("  help          — 显示此帮助"));

  // === set_wifi JSON 命令 ===
  } else if (cmd.startsWith("{")) {
    StaticJsonDocument<256> doc;
    DeserializationError err = deserializeJson(doc, cmd);
    if (!err) {
      const char* c = doc["cmd"];
      if (c && strcmp(c, "set_wifi") == 0) {
        const char* ssid = doc["ssid"];
        const char* pass = doc["pass"];
        if (ssid && pass) {
          Serial.print(F("[CMD] 设置 WiFi: "));
          Serial.println(ssid);
          WiFi.disconnect();
          WiFi.begin(ssid, pass);
        }
      }
    } else {
      Serial.println(F("[CMD] 无法识别的命令，输入 help 查看帮助"));
    }
  } else {
    Serial.println(F("[CMD] 无法识别的命令，输入 help 查看帮助"));
  }
}

// ===================== 应用测试状态 =====================
void applyTestState(const char* state) {
  if (strcmp(state, "idle") == 0) {
    agent_status = "idle";
    task_desc = "TEST: Idle";
    Serial.println(F("[TEST] 切换到 IDLE"));
  } else if (strcmp(state, "working") == 0) {
    agent_status = "working";
    task_desc = "TEST: Working";
    model_name = "test-model";
    context_len = 12345;
    cpu_percent = 67.5;
    Serial.println(F("[TEST] 切换到 WORKING"));
  } else if (strcmp(state, "waiting") == 0) {
    agent_status = "waiting";
    task_desc = "TEST: Waiting for user";
    Serial.println(F("[TEST] 切换到 WAITING"));
  } else if (strcmp(state, "error") == 0) {
    agent_status = "error";
    task_desc = "TEST: Error occurred";
    Serial.println(F("[TEST] 切换到 ERROR"));
  } else {
    Serial.print(F("[TEST] 未知状态: "));
    Serial.println(state);
  }
}

// ===================== LED 更新 =====================
void updateLED() {
  unsigned long now = millis();
  if (now - lastLedUpdate < 30) return;  // ~33fps
  lastLedUpdate = now;

  uint32_t color;

  if (agent_status == "idle") {
    color = ledStrip.Color(0, 255, 0);          // 绿色常亮
  } else if (agent_status == "working") {
    breathPhase += 0.05;
    if (breathPhase > TWO_PI) breathPhase -= TWO_PI;
    int b = (int)(((sin(breathPhase) + 1.0) / 2.0) * 255);
    color = ledStrip.Color(0, 0, b);            // 蓝色呼吸
  } else if (agent_status == "waiting") {
    breathPhase += 0.03;
    if (breathPhase > TWO_PI) breathPhase -= TWO_PI;
    int g = (int)(((sin(breathPhase) + 1.0) / 2.0) * 165);
    color = ledStrip.Color(255, g, 0);           // 橙色呼吸
  } else if (agent_status == "error") {
    bool blink = (now / 500) % 2 == 0;
    color = blink ? ledStrip.Color(255, 0, 0) : ledStrip.Color(0, 0, 0);  // 红色闪烁
  } else {
    color = ledStrip.Color(128, 0, 128);         // 紫色=未知
  }

  ledStrip.setPixelColor(0, color);
  ledStrip.show();
}

// ===================== OLED 显示更新 =====================
void updateDisplay() {
  if (!oledOk) return;

  display.clearDisplay();

  // MQTT 断连提示
  if (!mqttClient.connected()) {
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(10, 20);
    display.println(F("MQTT Disconnected"));
    display.setCursor(10, 35);
    display.print(F("Retry #"));
    display.println(mqttReconnectCount);
    display.display();
    return;
  }

  // 第1行: Agent名称 + 状态图标
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);

  const char* icon;
  if (agent_status == "idle")       icon = "[ ]";
  else if (agent_status == "working") icon = "[>]";
  else if (agent_status == "waiting") icon = "[~]";
  else if (agent_status == "error")   icon = "[!]";
  else                                icon = "[?]";

  display.print(agent);
  display.print(" ");
  display.println(icon);

  // 第2行: 模型名
  display.setCursor(0, 16);
  display.print(F("Model: "));
  display.println(model_name.length() > 16 ? model_name.substring(0, 15) + "..." : model_name);

  // 第3行: 当前任务 (滚动)
  display.setCursor(0, 32);
  display.print(F("Task: "));
  if (task_desc.length() > 0) {
    int maxChars = 18;
    if (task_desc.length() > maxChars) {
      String displayTask = task_desc.substring(scrollOffset);
      if (displayTask.length() > maxChars) displayTask = displayTask.substring(0, maxChars);
      else scrollOffset = 0;
      display.println(displayTask);

      unsigned long now = millis();
      if (now - lastScrollTime >= 400) {
        lastScrollTime = now;
        scrollOffset++;
        if (scrollOffset > task_desc.length()) scrollOffset = 0;
      }
    } else {
      display.println(task_desc);
    }
  } else {
    display.println(F("-"));
  }

  // 第4行: 上下文 + 时间
  display.setCursor(0, 48);
  display.print(F("Ctx:"));
  if (context_len >= 1024) {
    display.print(context_len / 1024);
    display.print(F("K "));
  } else {
    display.print(context_len);
    display.print(F("  "));
  }
  display.print(F("Time:"));
  display.println(cum_time);

  // 底部: CPU / 内存进度条
  drawProgressBar(0, 56, 56, 6, constrain(cpu_percent / 100.0, 0.0, 1.0), SSD1306_WHITE);
  display.setCursor(58, 56);
  display.print((int)cpu_percent);
  display.print(F("%"));

  float memPct = constrain(mem_mb / 512.0, 0.0, 1.0);
  drawProgressBar(88, 56, 40, 6, memPct, SSD1306_WHITE);
  display.setCursor(88, 48);
  display.print((int)mem_mb);
  display.print(F("MB"));

  display.display();
}

// ===================== 进度条 =====================
void drawProgressBar(int x, int y, int w, int h, float percent, uint16_t color) {
  display.drawRect(x, y, w, h, color);
  int fillW = (int)(percent * (w - 2));
  if (fillW > 0) display.fillRect(x + 1, y + 1, fillW, h - 2, color);
}

// ===================== 心跳 =====================
void heartbeatPrint() {
  unsigned long now = millis();
  if (now - lastHeartbeat >= HEARTBEAT_INTERVAL) {
    lastHeartbeat = now;
    Serial.print(F("[HEARTBEAT] WiFi:"));
    Serial.print(wifiOk ? F("OK") : F("DOWN"));
    Serial.print(F(" MQTT:"));
    Serial.print(mqttClient.connected() ? F("OK") : F("DOWN"));
    Serial.print(F(" Status:"));
    Serial.print(agent_status);
    Serial.print(F(" CPU:"));
    Serial.print(cpu_percent, 1);
    Serial.print(F("% Mem:"));
    Serial.print(mem_mb, 1);
    Serial.println(F("MB"));
  }
}

// ===================== 低功耗 =====================
void enterLowPower() {
  oledDimmed = true;
  ledStrip.setBrightness(10);
  Serial.println(F("[LOWPOWER] 进入"));
}

void exitLowPower() {
  ledStrip.setBrightness(50);
  oledDimmed = false;
  Serial.println(F("[LOWPOWER] 退出"));
}
