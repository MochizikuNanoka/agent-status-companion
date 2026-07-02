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
#include <WiFiUdp.h>
#include <ArduinoJson.h>
#ifndef NO_RGB_LED
#include <Adafruit_NeoPixel.h>
#endif
#include <Wire.h>
#include <Adafruit_SSD1306.h>
#include <Adafruit_GFX.h>
#include <LiquidCrystal.h>

// ===================== 引脚定义 =====================
// 暂时禁用 RGB LED（模组到货后删除此行以恢复 LED 功能）
#define NO_RGB_LED

#define LED_WS2812B_PIN  4      // WS2812B 数据引脚 (暂时禁用 — NO_RGB_LED)
#define NUM_LEDS         1        // LED 数量
#define OLED_SDA         21       // SSD1306 I2C SDA
#define OLED_SCL         22       // SSD1306 I2C SCL
#define OLED_ADDR        0x3C     // SSD1306 I2C 地址
#define OLED_WIDTH       64       // OLED 宽度 (像素) — 0.49寸
#define OLED_HEIGHT      32       // OLED 高度 (像素)
#define OLED_RESET       -1       // 不使用复位引脚

// LCD 1602 并行引脚 (4-bit 模式)
#define LCD_RS  12
#define LCD_EN  14
#define LCD_D4  26
#define LCD_D5  25
#define LCD_D6  33
#define LCD_D7  32

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
#define MQTT_KEEPALIVE   60

// UDP 端口
#define UDP_PORT  8888                  // 心跳间隔 (秒)

// ===================== 全局对象 =====================
WiFiClient wifiClient;
WiFiUDP udp;
#ifdef NO_RGB_LED
// LED 禁用 — 空壳 stub
struct DummyNeoPixel {
    void begin() {}
    void setBrightness(int) {}
    void setPixelColor(int, uint32_t) {}
    void show() {}
    static uint32_t Color(int, int, int) { return 0; }
} ledStrip;
#else
Adafruit_NeoPixel ledStrip(NUM_LEDS, LED_WS2812B_PIN, NEO_GRB + NEO_KHZ800);
#endif
Adafruit_SSD1306 display(OLED_WIDTH, OLED_HEIGHT, &Wire, OLED_RESET);

// LCD 1602 (4-bit 模式, 16列x2行)
LiquidCrystal lcd(LCD_RS, LCD_EN, LCD_D4, LCD_D5, LCD_D6, LCD_D7);

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
String ctx_display   = "";          // 上下文显示 (如 "294.5K")
String oled_line1    = "";          // OLED 第1行 (PC端格式化)
String oled_line2    = "";          // OLED 第2行 (颜文字)
String lcd_line1_str = "";          // LCD 第1行 (PC端格式化)

// 硬件状态
bool oledOk          = false;       // OLED 是否初始化成功
bool wifiOk          = false;       // WiFi 是否连接
bool hasData         = false;       // 是否收到过 JSON 数据
int  dataVersion     = 0;           // 数据版本号，变化时更新显示
String lastJson      = "";          // 上次收到的 JSON，相同时跳过
int  lastDataVersion = -1;          // 上次显示时的版本号

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

  // === LCD 1602 初始化 ===
  lcd.begin(16, 2);
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Agent Companion");
  lcd.setCursor(0, 1);
  lcd.print("LCD Ready");
  Serial.println(F("[LCD] 1602 初始化完成 (16x2, 4-bit)"));

  // === WS2812B LED 初始化 ===
  ledStrip.begin();
  ledStrip.setBrightness(50);
  ledStrip.setPixelColor(0, ledStrip.Color(0, 255, 0));  // 绿色=硬件就绪
  ledStrip.show();
  Serial.println(F("[LED] WS2812B 初始化完成 (GPIO"));
  Serial.print(LED_WS2812B_PIN);
  Serial.println(F(")"));

  // === WiFi 连接 ===
  setupWiFi();

  // === UDP 监听 ===
  udp.begin(UDP_PORT);
  Serial.print(F("[UDP] 监听端口 "));
  Serial.println(UDP_PORT);

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

  // === UDP 数据接收 ===
  int packetSize = udp.parsePacket();
  if (packetSize) {
    char buf[512];
    int len = udp.read(buf, min(packetSize, 511));
    buf[len] = '\0';
    Serial.print(F("[UDP] 收到: "));
    Serial.println(buf);
    hasData = true;
    parseStatusJson(buf);
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
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 2);
  display.println(F("Hermes Agent"));
  display.setCursor(0, 14);
  display.println(F("Companion v2"));
  display.setCursor(0, 24);
  display.println(F("Hardware OK"));
  display.display();
  delay(1200);
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

// ===================== UDP 数据接收（在 loop() 中处理） =====================

// ===================== JSON 解析 =====================
void parseStatusJson(const char* json) {
  // 和上次一样就跳过
  if (lastJson == String(json)) return;
  lastJson = String(json);

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
  const char* cd = doc["ctx_display"] | "";
  ctx_display   = String(cd);
  const char* ol1 = doc["oled_line1"] | "";
  oled_line1    = String(ol1);
  const char* lc1 = doc["lcd_line1"] | "";
  lcd_line1_str = String(lc1);
  const char* ol2 = doc["oled_line2"] | "";
  oled_line2    = String(ol2);
  dataVersion++;  // 数据已更新

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
    Serial.print(F("  MQTT:     N/A (UDP mode)"));
    Serial.println();
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
    Serial.println(F("  {JSON}        — 发送状态 JSON (Serial 直连模式)"));

  // === JSON 消息处理 (状态更新 或 set_wifi 命令) ===
  } else if (cmd.startsWith("{")) {
    StaticJsonDocument<512> doc;
    DeserializationError err = deserializeJson(doc, cmd);
    if (!err) {
      // 如果是 set_wifi 命令
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
        return;
      }
      // 否则尝试作为状态 JSON 解析 (Serial 直连模式)
      if (doc.containsKey("status")) {
        Serial.println(F("[SERIAL] 收到 JSON 状态消息"));
        hasData = true;
        parseStatusJson(cmd.c_str());
        return;
      }
    }
    Serial.println(F("[CMD] 无法识别的 JSON，输入 help 查看帮助"));
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
#ifdef NO_RGB_LED
    return;  // LED 禁用
#endif
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

  // 数据没变且无需滚动 → 跳过更新（避免闪烁）
  // 但如果模型名超长需要滚动，即使数据没变也要更新
  bool needScroll = (oled_line1.length() > 10);
  if (dataVersion == lastDataVersion && hasData && !needScroll) return;
  lastDataVersion = dataVersion;

  // No data yet? Show waiting
  if (!hasData) {
    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 2);
    display.println(F("No Data"));
    display.setCursor(0, 18);
    display.println(F("Waiting UDP..."));
    display.display();
    return;
  }

  // OLED: 模型名(超长自动滚动) + 上下文使用率
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);

  // 模型名 — 超 10 字符时滚动
  const int OLED_CHARS = 10;  // 64px / 6px per char
  if (oled_line1.length() > OLED_CHARS) {
    unsigned long now = millis();
    if (now - lastScrollTime > 400) {
      lastScrollTime = now;
      scrollOffset++;
      if (scrollOffset > oled_line1.length() - OLED_CHARS + 5)
        scrollOffset = 0;  // 末尾停顿 + 回绕
    }
    display.setCursor(0, 0);
    display.println(oled_line1.substring(scrollOffset, scrollOffset + OLED_CHARS));
  } else {
    display.setCursor(0, 0);
    display.println(oled_line1);
  }

  // 颜文字 (来自 config.yaml)
  display.setCursor(0, 8);
  display.println(oled_line2);

  // cum_time 已含 "Ctx: " 前缀 (来自 config.yaml)
  display.setCursor(0, 16);
  display.println(cum_time);

  display.display();

  // === LCD 1602 颜文字（增量更新 — 内容不变就不刷新，消除闪烁） ===
  static String lastLcdLine1 = "";
  static String lastLcdLine2 = "";
  // ctx_display 已含 "/1M" (来自 config.yaml)，固件不再追加

  if (lcd_line1_str != lastLcdLine1 || ctx_display != lastLcdLine2) {
    lastLcdLine1 = lcd_line1_str;
    lastLcdLine2 = ctx_display;
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print(lcd_line1_str);
    lcd.setCursor(0, 1);
    lcd.print(ctx_display);
  }
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
