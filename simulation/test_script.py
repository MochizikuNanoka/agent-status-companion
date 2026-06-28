#!/usr/bin/env python3
"""
agent-status-companion 测试脚本

通过 MQTT 发送模拟的 Agent 状态 JSON 消息，测试 ESP32 固件的
状态解析、LED 指示和 OLED 显示功能。

支持的状态转换序列:
    IDLE → WORKING → WAITING → ERROR → IDLE

用法:
    python test_script.py
    python test_script.py --broker broker.emqx.io --port 1883 --topic agent/status
    python test_script.py --broker localhost --delay 3
"""

import argparse
import json
import time
import random
import sys

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("错误: 需要 paho-mqtt 库。请运行: pip install paho-mqtt")
    sys.exit(1)


# ============ 默认配置 ============
DEFAULT_BROKER = "broker.emqx.io"
DEFAULT_PORT = 1883
DEFAULT_TOPIC = "agent/status"
DEFAULT_DELAY = 5  # 每条消息之间的间隔(秒)
DEFAULT_CLIENT_ID = "agent-status-test-script"


def build_status_payload(
    status: str = "idle",
    agent: str = "hermes",
    model: str = "deepseek-v4-flash",
    task_summary: str = "",
    context_len: int = 0,
    cum_time: str = "0s",
    cpu_percent: float = 0.0,
    mem_mb: float = 0.0,
    timestamp: str = "",
) -> str:
    """
    构建新版 JSON 状态消息。

    新 JSON 格式:
    {
        "status":       "idle" | "working" | "waiting" | "error",
        "agent":        "hermes",           // 原 agent_name
        "model":        "deepseek-v4-flash",
        "task_summary": "正在分析代码...",   // 原 task
        "context_len":  8192,
        "cum_time":     "5m 23s",
        "cpu_percent":  45.2,
        "mem_mb":       128.5,
        "timestamp":    "2026-06-29T12:34:56Z"
    }
    """
    payload = {
        "status": status,
        "agent": agent,
        "model": model,
        "task_summary": task_summary,
        "context_len": context_len,
        "cum_time": cum_time,
        "cpu_percent": cpu_percent,
        "mem_mb": mem_mb,
    }
    if timestamp:
        payload["timestamp"] = timestamp
    else:
        # 默认使用当前时间
        payload["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    return json.dumps(payload, ensure_ascii=False)


def on_connect(client, userdata, flags, reason_code, properties=None):
    """MQTT 连接回调"""
    if reason_code == 0:
        print(f"[MQTT] ✓ 已连接到 {userdata['broker']}:{userdata['port']}")
    else:
        print(f"[MQTT] ✗ 连接失败, 返回码: {reason_code}")
        sys.exit(1)


def on_publish(client, userdata, mid, reason_code=None, properties=None):
    """MQTT 发布回调"""
    print(f"[MQTT] ✓ 消息已发布 (mid={mid})")


def main():
    parser = argparse.ArgumentParser(
        description="agent-status-companion 状态模拟测试脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s
  %(prog)s --broker broker.emqx.io --port 1883
  %(prog)s --broker localhost --topic test/agent/status --delay 2
        """,
    )
    parser.add_argument(
        "--broker",
        default=DEFAULT_BROKER,
        help=f"MQTT broker 地址 (默认: {DEFAULT_BROKER})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"MQTT 端口 (默认: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--topic",
        default=DEFAULT_TOPIC,
        help=f"MQTT 主题 (默认: {DEFAULT_TOPIC})",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        help=f"每条消息间隔秒数 (默认: {DEFAULT_DELAY})",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="循环发送状态序列",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("  agent-status-companion 状态模拟测试")
    print("=" * 60)
    print(f"  Broker:  {args.broker}:{args.port}")
    print(f"  Topic:   {args.topic}")
    print(f"  间隔:    {args.delay}s")
    print(f"  循环:    {'是' if args.loop else '否'}")
    print("=" * 60)
    print()

    # 创建 MQTT 客户端
    client = mqtt.Client(
        client_id=DEFAULT_CLIENT_ID,
        protocol=mqtt.MQTTv311,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    client.user_data_set({"broker": args.broker, "port": args.port})
    client.on_connect = on_connect
    client.on_publish = on_publish

    # 连接 broker
    print(f"[MQTT] 正在连接到 {args.broker}:{args.port}...")
    try:
        client.connect(args.broker, args.port, keepalive=60)
        client.loop_start()
    except Exception as e:
        print(f"[MQTT] ✗ 连接失败: {e}")
        sys.exit(1)

    # 等待连接建立
    time.sleep(1)
    print()

    # ========== 状态测试序列 ==========
    test_sequence = [
        # (status, agent, model, task_summary, context_len, cum_time, cpu, mem)
        {
            "status": "idle",
            "agent": "hermes",
            "model": "deepseek-v4-flash",
            "task_summary": "",
            "context_len": 0,
            "cum_time": "0s",
            "cpu_percent": 2.1,
            "mem_mb": 64.0,
        },
        {
            "status": "working",
            "agent": "hermes",
            "model": "deepseek-v4-flash",
            "task_summary": "正在分析用户请求中的代码片段...",
            "context_len": 4096,
            "cum_time": "12s",
            "cpu_percent": 78.5,
            "mem_mb": 256.3,
        },
        {
            "status": "working",
            "agent": "hermes",
            "model": "deepseek-v4-flash",
            "task_summary": "正在生成项目架构设计方案，包含模块拆分和数据流设计...",
            "context_len": 8192,
            "cum_time": "1m 23s",
            "cpu_percent": 92.1,
            "mem_mb": 384.7,
        },
        {
            "status": "waiting",
            "agent": "hermes",
            "model": "deepseek-v4-flash",
            "task_summary": "等待用户确认配置参数",
            "context_len": 8192,
            "cum_time": "2m 05s",
            "cpu_percent": 12.3,
            "mem_mb": 320.0,
        },
        {
            "status": "error",
            "agent": "hermes",
            "model": "deepseek-v4-flash",
            "task_summary": "API 响应超时，正在重试第 3 次",
            "context_len": 4096,
            "cum_time": "3m 47s",
            "cpu_percent": 5.0,
            "mem_mb": 192.5,
        },
        {
            "status": "idle",
            "agent": "hermes",
            "model": "deepseek-v4-flash",
            "task_summary": "",
            "context_len": 0,
            "cum_time": "4m 12s",
            "cpu_percent": 3.2,
            "mem_mb": 80.0,
        },
    ]

    iteration = 0
    try:
        while True:
            iteration += 1
            print(f"\n{'─' * 60}")
            print(f"  第 {iteration} 轮状态测试")
            print(f"{'─' * 60}")

            for i, state in enumerate(test_sequence):
                status = state["status"]
                payload = build_status_payload(
                    status=status,
                    agent=state["agent"],
                    model=state["model"],
                    task_summary=state["task_summary"],
                    context_len=state["context_len"],
                    cum_time=state["cum_time"],
                    cpu_percent=state["cpu_percent"],
                    mem_mb=state["mem_mb"],
                )

                emoji_map = {
                    "idle": "🟢",
                    "working": "🔵",
                    "waiting": "🟡",
                    "error": "🔴",
                }
                emoji = emoji_map.get(status, "⚪")

                print(f"\n{emoji}  [{i+1}/{len(test_sequence)}] 状态: {status.upper()}")
                print(f"   发送内容: {payload}")

                result = client.publish(args.topic, payload, qos=1)
                if result.rc == mqtt.MQTT_ERR_SUCCESS:
                    print(f"   ✓ 已发布 (mid={result.mid})")
                else:
                    print(f"   ✗ 发布失败 (rc={result.rc})")

                time.sleep(args.delay)

            if not args.loop:
                print(f"\n{'=' * 60}")
                print("  全状态序列测试完成!")
                print(f"{'=' * 60}")
                break

    except KeyboardInterrupt:
        print(f"\n\n[!] 用户中断测试")
    finally:
        client.loop_stop()
        client.disconnect()
        print("[MQTT] 已断开连接")
        print("测试结束。")


if __name__ == "__main__":
    main()
