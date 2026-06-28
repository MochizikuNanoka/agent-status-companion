# -*- coding: utf-8 -*-
"""
Hermes Agent 监控器模块（完全重写 — 任务书_2 版本）

多级降级数据源：
  Primary:   agent.log 实时日志文件监控
  Fallback 1: `hermes status` 子进程调用
  Fallback 2: psutil 进程监控（原方案）
  Simulate:  --simulate 模式，循环切换 IDLE/WORKING/WAITING

支持 Windows / Linux / Mac 跨平台路径处理。
"""

import os
import re
import time
import json
import logging
import subprocess
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Callable

from .status_model import StatusMessage, AgentStatus

logger = logging.getLogger(__name__)


# ============================================================
# 日志解析相关常量
# ============================================================

# agent.log 中 API call 行的正则模式
# 示例: 2026-06-29 06:29:04,461 INFO [20260629_055232_7126c1] agent.conversation_loop: API call #60: model=deepseek-v4-pro provider=deepseek in=65171 out=718 total=65889 latency=6.9s cache=64256/65171 (99%)
_LOG_API_CALL_PATTERN = re.compile(
    r'\[(?P<session_id>\d{8}_\d{6}_[a-f0-9]+)\].*?'
    r'API call #\d+:\s*'
    r'model=(?P<model>[^\s]+)'
    r'(?:\s+provider=(?P<provider>[^\s]+))?'
    r'(?:\s+in=\d+)?'
    r'(?:\s+out=\d+)?'
    r'\s+total=(?P<context_len>\d+)'
)

# 判断是否为最近有效调用的时间阈值（秒）
_RECENT_CALL_THRESHOLD = 300  # 5 分钟内认为活跃


def _get_sessions_dir(log_path: Path) -> Path:
    """
    根据日志目录推断 sessions 目录路径

    agent.log 在 <base>/logs/agent.log，
    sessions 目录在 <base>/sessions/。
    """
    base = log_path.parent if log_path.name == "logs" else log_path
    return base / "sessions"


class HermesMonitor:
    """
    Hermes Agent 状态监控器

    提供多级降级数据源获取 Agent 状态：
    1. 实时读取 agent.log 解析 API call 信息
    2. 回退到 `hermes status` 子进程
    3. 再回退到 psutil 进程检测
    4. 模拟模式下循环生成测试状态

    用法:
        monitor = HermesMonitor()
        status = monitor.get_status()  # 同步获取
        monitor.start_tailing()        # 启动后台日志监控
    """

    def __init__(
        self,
        simulate: bool = False,
        log_path: Optional[Path] = None,
    ):
        """
        初始化监控器

        Args:
            simulate: 是否启用模拟模式（用于无 Hermes 环境的开发测试）
            log_path: agent.log 文件路径（自动检测默认值）
        """
        self._simulate = simulate

        # 确定日志路径
        if log_path:
            self._log_path = Path(log_path)
        else:
            self._log_path = _default_agent_log_path()

        self._sessions_dir = _get_sessions_dir(self._log_path)

        # 后台日志监控线程控制
        self._tailing = False
        self._tail_thread: Optional[threading.Thread] = None
        self._last_log_pos = 0  # 上次读取的文件位置

        # 状态变化回调列表
        self._callbacks: list[Callable[[StatusMessage], None]] = []

        # 模拟模式状态
        self._sim_state = 0        # 0=IDLE, 1=WORKING, 2=WAITING
        self._sim_start = time.monotonic()

        # 缓存最近解析到的日志行时间
        self._last_call_time: Optional[float] = None

        logger.debug(
            "HermesMonitor 初始化: simulate=%s, log_path=%s",
            simulate, self._log_path,
        )

    # ============================================================
    # 公开接口
    # ============================================================

    def get_status(self) -> StatusMessage:
        """
        同步获取当前 Agent 状态

        按优先级依次尝试数据源，返回完整的 StatusMessage。

        Returns:
            StatusMessage 当前状态消息
        """
        if self._simulate:
            return self._get_simulated_status()

        # Primary: 从日志文件解析
        status = self._get_status_from_log()
        if status is not None:
            return status

        # Fallback 1: hermes status 子进程
        status = self._get_status_from_subprocess()
        if status is not None:
            return status

        # Fallback 2: psutil 进程监控
        status = self._get_status_from_psutil()
        if status is not None:
            return status

        # 全部失败 → IDLE
        return StatusMessage(
            status=AgentStatus.IDLE,
            agent="hermes",
            task_summary="未检测到 Hermes Agent",
            timestamp=_now_iso(),
        )

    def start_tailing(self) -> None:
        """
        启动后台日志监控线程

        在后台持续跟踪 agent.log 新行，解析状态变化。
        适合与聚合器配合使用的实时监控模式。
        """
        if self._tailing:
            logger.warning("日志监控已在运行")
            return

        self._tailing = True
        self._tail_thread = threading.Thread(
            target=self._tail_loop,
            name="hermes-tail",
            daemon=True,
        )
        self._tail_thread.start()
        logger.info("后台日志监控已启动: %s", self._log_path)

    def stop_tailing(self) -> None:
        """停止后台日志监控线程"""
        self._tailing = False
        if self._tail_thread:
            self._tail_thread.join(timeout=3)
            self._tail_thread = None
        logger.info("后台日志监控已停止")

    def on_status_change(self, callback: Callable[[StatusMessage], None]) -> None:
        """
        注册状态变化回调

        Args:
            callback: 接收 StatusMessage 参数的可调用对象
        """
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    # ============================================================
    # 模拟模式
    # ============================================================

    def _get_simulated_status(self) -> StatusMessage:
        """
        模拟模式：循环切换 IDLE → WORKING → WAITING 状态

        每 8 秒切换一次状态，用于无 Hermes 环境的开发测试。
        """
        elapsed = time.monotonic() - self._sim_start
        cycle = int(elapsed / 8) % 3
        self._sim_state = cycle

        models = ["deepseek-v4-pro", "claude-sonnet-4-20250514", "gpt-4o-2024-11-20"]
        tasks = [
            "空闲中，等待指令...",
            "正在分析代码库并生成重构方案...",
            "等待工具返回结果...",
        ]
        statuses = [AgentStatus.IDLE, AgentStatus.WORKING, AgentStatus.WAITING]
        ctx_lens = [0, 45231, 28904]
        cpus = [2.1, 67.5, 12.3]
        mems = [180.0, 650.0, 320.0]

        idx = self._sim_state
        return StatusMessage(
            status=statuses[idx],
            agent="hermes",
            model=models[idx],
            task_summary=tasks[idx],
            context_len=ctx_lens[idx],
            cum_time=f"{int(elapsed // 60)}m",
            timestamp=_now_iso(),
            cpu_percent=cpus[idx],
            mem_mb=mems[idx],
        )

    # ============================================================
    # Primary: agent.log 实时日志解析
    # ============================================================

    def _get_status_from_log(self) -> Optional[StatusMessage]:
        """
        从 agent.log 解析当前状态

        读取日志文件末尾，查找最近的 API call 行，
        提取 model、provider、context_len 等信息。
        根据最近调用的时间推断状态（5 分钟内 → WORKING）。

        Returns:
            成功时返回 StatusMessage，失败或日志不存在时返回 None
        """
        log_file = self._get_log_file()
        if not log_file or not log_file.exists():
            logger.debug("agent.log 不存在: %s", log_file)
            return None

        try:
            # 读取最后 200 行
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[-200:]
        except Exception as e:
            logger.warning("读取 agent.log 失败: %s", e)
            return None

        # 从最后向前查找最近的 API call 行
        latest_call = None
        latest_model = None
        latest_ctx = 0
        latest_session = None
        latest_line_time: Optional[float] = None

        # 也检查是否有其他活动日志（非 API call 表示 Agent 在运行）
        has_recent_activity = False

        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue

            # 尝试解析时间戳
            ts_match = re.match(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', line)
            if ts_match:
                try:
                    line_dt = datetime.strptime(ts_match.group(1), "%Y-%m-%d %H:%M:%S")
                    line_ts = line_dt.replace(tzinfo=timezone.utc).timestamp()
                    now_ts = time.time()
                    if now_ts - line_ts <= _RECENT_CALL_THRESHOLD:
                        has_recent_activity = True
                except ValueError:
                    pass

            # 匹配 API call 行
            m = _LOG_API_CALL_PATTERN.search(line)
            if m is not None:
                latest_call = m
                latest_model = m.group("model")
                latest_ctx = int(m.group("context_len"))
                latest_session = m.group("session_id")
                # 解析行时间
                if ts_match:
                    try:
                        dt = datetime.strptime(ts_match.group(1), "%Y-%m-%d %H:%M:%S")
                        latest_line_time = dt.replace(tzinfo=timezone.utc).timestamp()
                    except ValueError:
                        latest_line_time = time.time()
                else:
                    latest_line_time = time.time()
                break  # 只取最近的一条

        if latest_call is None:
            # 没有任何 API call 行
            if has_recent_activity:
                # 有近期日志活动但无 API call → 可能是刚启动或空闲
                return StatusMessage(
                    status=AgentStatus.IDLE,
                    agent="hermes",
                    task_summary="Agent 运行中，暂无 API 调用",
                    timestamp=_now_iso(),
                )
            return None  # 无足够信息，让 fallback 处理

        # 判断是否活跃
        now_ts = time.time()
        is_active = (latest_line_time is not None
                     and (now_ts - latest_line_time) <= _RECENT_CALL_THRESHOLD)
        status = AgentStatus.WORKING if is_active else AgentStatus.IDLE

        # 尝试从 session 目录读取 task_summary
        task_summary = self._read_latest_exchange(latest_session)

        return StatusMessage(
            status=status,
            agent="hermes",
            model=latest_model,
            task_summary=task_summary,
            context_len=latest_ctx,
            timestamp=_now_iso(),
        )

    def _read_latest_exchange(self, session_id: Optional[str]) -> Optional[str]:
        """
        从 session 目录读取最新的 exchange 内容作为 task_summary

        Args:
            session_id: 形如 "20260629_055232_7126c1" 的会话 ID

        Returns:
            摘要文本，失败时返回 None
        """
        if not session_id:
            return None

        # session 目录: <base>/sessions/<session_id>/
        session_dir = self._sessions_dir / session_id
        if not session_dir.is_dir():
            logger.debug("session 目录不存在: %s", session_dir)
            return None

        try:
            # 查找最新的 exchange 文件（按修改时间排序）
            exchange_files = sorted(
                session_dir.glob("exchange*"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if not exchange_files:
                # 尝试找任何 .json 或 .md 文件
                all_files = sorted(
                    session_dir.iterdir(),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if not all_files:
                    return None
                target = all_files[0]
            else:
                target = exchange_files[0]

            # 读取内容提取前几行作为摘要
            content = target.read_text(encoding="utf-8", errors="replace")
            lines = content.strip().split("\n")
            # 取前 3 行摘要，或整个内容（如果很短）
            summary_lines = [l.strip() for l in lines[:5] if l.strip()]
            summary = " | ".join(summary_lines[:3])
            if len(summary) > 200:
                summary = summary[:200] + "..."
            return summary if summary else None

        except Exception as e:
            logger.debug("读取 session exchange 失败: %s", e)
            return None

    def _get_log_file(self) -> Optional[Path]:
        """获取 agent.log 的完整路径"""
        if self._log_path.suffix == ".log":
            return self._log_path
        return self._log_path / "agent.log"

    # ============================================================
    # Fallback 1: hermes status 子进程
    # ============================================================

    def _get_status_from_subprocess(self) -> Optional[StatusMessage]:
        """
        通过 `hermes status` 子进程获取当前状态

        运行 hermes status 和 hermes status --all 获取信息。

        Returns:
            成功时返回 StatusMessage，失败时返回 None
        """
        try:
            # 运行 hermes status
            result = subprocess.run(
                ["hermes", "status"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                logger.debug("hermes status 返回非零: %d", result.returncode)
                return None

            output = result.stdout.strip()
            if not output:
                return None

            # 尝试解析 JSON 输出
            try:
                data = json.loads(output)
                model = data.get("model")
                status_str = data.get("status", "idle")
                provider = data.get("provider")
                ctx = data.get("context_len", 0)
                task = data.get("task_summary") or data.get("task")
            except (json.JSONDecodeError, TypeError):
                # 文本输出解析
                model = self._extract_field(output, "model")
                status_str = self._extract_field(output, "status") or "idle"
                provider = self._extract_field(output, "provider")
                ctx_str = self._extract_field(output, "context_len")
                ctx = int(ctx_str) if ctx_str and ctx_str.isdigit() else 0
                task = self._extract_field(output, "task")

            # 尝试获取会话数
            sessions_info = ""
            try:
                result_all = subprocess.run(
                    ["hermes", "status", "--all"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result_all.returncode == 0:
                    sessions_info = result_all.stdout.strip()[:100]
            except Exception:
                pass

            # 映射状态字符串到枚举
            status = self._map_status_str(status_str)

            task_summary = task
            if sessions_info and not task_summary:
                task_summary = f"会话信息: {sessions_info}"

            return StatusMessage(
                status=status,
                agent="hermes",
                model=model or provider,
                task_summary=task_summary,
                context_len=ctx,
                timestamp=_now_iso(),
            )

        except FileNotFoundError:
            logger.debug("hermes 命令未找到（未安装）")
            return None
        except subprocess.TimeoutExpired:
            logger.debug("hermes status 超时")
            return None
        except Exception as e:
            logger.debug("hermes status 子进程失败: %s", e)
            return None

    # ============================================================
    # Fallback 2: psutil 进程监控（原方案）
    # ============================================================

    def _get_status_from_psutil(self) -> Optional[StatusMessage]:
        """
        通过 psutil 查找 hermes 进程，获取基本信息

        Returns:
            成功时返回 StatusMessage，未找到进程时返回 None
        """
        try:
            import psutil as psutil_module
        except ImportError:
            logger.debug("psutil 未安装")
            return None

        hermes_proc = None
        for proc in psutil_module.process_iter(["pid", "name", "exe"]):
            try:
                name = proc.info.get("name", "") or ""
                exe = proc.info.get("exe", "") or ""
                cmdline = " ".join(proc.cmdline()).lower() if hasattr(proc, 'cmdline') else ""
                if ("hermes" in name.lower()
                        or "hermes" in exe.lower()
                        or "hermes" in cmdline):
                    hermes_proc = proc
                    break
            except (psutil_module.NoSuchProcess, psutil_module.AccessDenied):
                continue

        if hermes_proc is None:
            return None

        # 获取 CPU/内存
        try:
            cpu_percent = hermes_proc.cpu_percent(interval=0.1)
            mem_info = hermes_proc.memory_info()
            mem_mb = mem_info.rss / (1024 * 1024)
        except Exception:
            cpu_percent = 0.0
            mem_mb = 0.0

        # 尝试从命令行参数中提取模型信息
        model = None
        try:
            cmdline = hermes_proc.cmdline()
            for arg in cmdline:
                if "model" in arg.lower():
                    parts = arg.split("=")
                    if len(parts) == 2:
                        model = parts[1].strip()
                        break
        except Exception:
            pass

        return StatusMessage(
            status=AgentStatus.WORKING,  # 进程存在，认为工作中
            agent="hermes",
            model=model,
            task_summary="通过进程检测到 Hermes Agent 运行中",
            context_len=0,
            timestamp=_now_iso(),
            cpu_percent=round(cpu_percent, 1),
            mem_mb=round(mem_mb, 1),
        )

    # ============================================================
    # 后台日志监控（tail 模式）
    # ============================================================

    def _tail_loop(self) -> None:
        """
        后台日志监控主循环

        持续读取 agent.log 新增行，检测到新 API call 时
        触发状态变化回调通知。
        """
        log_file = self._get_log_file()
        if not log_file:
            logger.error("无法确定 agent.log 路径")
            return

        # 等待日志文件出现
        while self._tailing and not log_file.exists():
            time.sleep(1)

        if not self._tailing:
            return

        # 初始定位到文件末尾
        try:
            self._last_log_pos = log_file.stat().st_size
        except OSError:
            self._last_log_pos = 0

        logger.info("日志 tail 开始跟踪: %s (起始位置: %d)", log_file, self._last_log_pos)

        while self._tailing:
            try:
                if not log_file.exists():
                    time.sleep(1)
                    continue

                # 获取当前文件大小
                current_size = log_file.stat().st_size

                if current_size < self._last_log_pos:
                    # 文件被截断/轮转，重新从开始读取
                    self._last_log_pos = 0
                    logger.info("日志文件已轮转，重置读取位置")

                if current_size > self._last_log_pos:
                    # 有新内容
                    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(self._last_log_pos)
                        new_lines = f.readlines()
                        self._last_log_pos = f.tell()

                    # 解析新增行
                    for line in new_lines:
                        m = _LOG_API_CALL_PATTERN.search(line)
                        if m is not None:
                            status = StatusMessage(
                                status=AgentStatus.WORKING,
                                agent="hermes",
                                model=m.group("model"),
                                task_summary=self._read_latest_exchange(
                                    m.group("session_id")
                                ),
                                context_len=int(m.group("context_len")),
                                timestamp=_now_iso(),
                            )
                            # 通知回调
                            self._notify_callbacks(status)

                time.sleep(1)

            except Exception as e:
                logger.error("日志 tail 异常: %s", e)
                time.sleep(5)

    def _notify_callbacks(self, status: StatusMessage) -> None:
        """通知所有注册的状态变化回调"""
        for cb in self._callbacks:
            try:
                cb(status)
            except Exception as e:
                logger.error("状态回调失败: %s", e)

    # ============================================================
    # 工具方法
    # ============================================================

    @staticmethod
    def _extract_field(text: str, field: str) -> Optional[str]:
        """
        从文本中提取字段值（支持 key=value 和 key: value 格式）

        Args:
            text: 输入文本
            field: 字段名

        Returns:
            字段值，未找到时返回 None
        """
        patterns = [
            re.compile(rf'{re.escape(field)}\s*=\s*"?([^"\s]+)"?'),
            re.compile(rf'{re.escape(field)}\s*:\s*"?([^"\n]+)"?'),
        ]
        for p in patterns:
            m = p.search(text)
            if m:
                return m.group(1).strip()
        return None

    @staticmethod
    def _map_status_str(s: str) -> AgentStatus:
        """将状态字符串映射为 AgentStatus 枚举"""
        s = s.strip().lower()
        mapping = {
            "idle": AgentStatus.IDLE,
            "working": AgentStatus.WORKING,
            "waiting": AgentStatus.WAITING,
            "error": AgentStatus.ERROR,
            "running": AgentStatus.WORKING,
        }
        return mapping.get(s, AgentStatus.IDLE)


# ============================================================
# 模块级辅助函数
# ============================================================

def _now_iso() -> str:
    """返回当前 UTC 时间的 ISO 8601 格式字符串"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _default_agent_log_path() -> Path:
    """
    获取默认的 agent.log 路径（跨平台）

    Windows: %LOCALAPPDATA%/hermes/logs/agent.log
    Linux:   ~/.hermes/logs/agent.log
    Mac:     ~/.hermes/logs/agent.log
    """
    env_path = os.getenv("HERMES_LOG_PATH")
    if env_path:
        p = Path(env_path)
        if p.suffix == ".log":
            return p
        return p / "agent.log"

    if os.name == "nt":
        local_appdata = os.getenv("LOCALAPPDATA",
                                  str(Path.home() / "AppData" / "Local"))
        return Path(local_appdata) / "hermes" / "logs" / "agent.log"
    else:
        return Path.home() / ".hermes" / "logs" / "agent.log"
