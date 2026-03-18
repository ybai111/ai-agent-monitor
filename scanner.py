"""
Claude 实例扫描器：从进程列表和本地文件中提取所有 Claude 实例信息
"""

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ClaudeInstance:
    """一个 Claude 实例的完整信息"""
    pid: int
    user: str
    type: str  # "cursor" | "cli-interactive" | "cli-oneshot" | "cli-api" | "cli-login"
    model: str = ""
    cwd: str = ""
    prompt: str = ""  # one-shot 的 prompt 内容
    session_id: str = ""
    permission_mode: str = ""
    cpu_percent: float = 0.0
    mem_mb: int = 0
    started_at: str = ""
    uptime: str = ""
    version: str = ""
    status: str = "running"  # "running" | "completed" | "failed" | "cancelled"
    # 从 web manager DB 补充的任务信息
    task_id: str = ""
    task_status: str = ""  # web manager 任务状态
    task_output_preview: str = ""  # 输出前 100 字符

    @property
    def project_name(self) -> str:
        """从 cwd 提取项目名"""
        if not self.cwd:
            return "?"
        return Path(self.cwd).name

    @property
    def type_label(self) -> str:
        labels = {
            "cursor": "Cursor",
            "cli-interactive": "CLI",
            "cli-oneshot": "CLI →",
            "cli-api": "API",
            "cli-login": "Login",
        }
        return labels.get(self.type, self.type)

    @property
    def prompt_short(self) -> str:
        """截断的 prompt 摘要"""
        if not self.prompt:
            return ""
        # 去掉首尾引号
        p = self.prompt.strip("'\"")
        return p[:60] + "..." if len(p) > 60 else p


def scan_instances() -> list[ClaudeInstance]:
    """扫描当前机器上所有 Claude 实例"""
    instances = []

    # 遍历 /proc 找所有 claude 进程
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        try:
            # 读命令行
            cmdline_path = f"/proc/{pid}/cmdline"
            with open(cmdline_path, "rb") as f:
                cmdline_raw = f.read()
            cmdline_parts = cmdline_raw.decode("utf-8", errors="replace").split("\x00")
            cmdline = " ".join(cmdline_parts)

            # 只关心 claude 相关进程
            if not _is_claude_process(cmdline_parts):
                continue

            # 读取进程信息
            stat = _read_proc_stat(pid)
            instance = ClaudeInstance(
                pid=pid,
                user=_get_user(pid),
                type=_detect_type(cmdline, cmdline_parts),
                cpu_percent=stat.get("cpu", 0.0),
                mem_mb=stat.get("mem_mb", 0),
                started_at=stat.get("start_time", ""),
                uptime=stat.get("uptime", ""),
            )

            # 工作目录
            try:
                instance.cwd = os.readlink(f"/proc/{pid}/cwd")
            except (PermissionError, FileNotFoundError):
                pass

            # 从命令行提取参数
            _extract_args(instance, cmdline, cmdline_parts)

            instances.append(instance)

        except (PermissionError, FileNotFoundError, ProcessLookupError):
            continue

    # 补充 web manager 任务信息
    _enrich_from_web_manager(instances)

    # 按用户 + 类型排序
    instances.sort(key=lambda i: (i.user, i.type, -i.pid))
    return instances


def _enrich_from_web_manager(instances: list[ClaudeInstance]):
    """从外部任务 DB 读取任务状态，补充到对应实例。

    支持环境变量 CLAUDE_MONITOR_TASK_DB 指定 SQLite 数据库路径。
    数据库需包含 tasks 表（字段: id, prompt, status, output, created_at, started_at, finished_at）。
    """
    db_path = os.environ.get("CLAUDE_MONITOR_TASK_DB", "")
    if not db_path:
        # 尝试默认位置（同级 claude_web_manager 项目）
        default = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "claude_web_manager", "data", "tasks.db",
        )
        if os.path.exists(default):
            db_path = default
    if not db_path or not os.path.exists(db_path):
        return

    import sqlite3
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        conn.close()
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return

    tasks = [dict(r) for r in rows]

    # 对每个 cli-api 实例，通过 prompt 匹配任务
    for inst in instances:
        if inst.type != "cli-api" or not inst.prompt:
            continue
        prompt_head = inst.prompt[:50]
        for task in tasks:
            if task["prompt"][:50] == prompt_head:
                inst.task_id = task["id"]
                inst.task_status = task["status"]
                output = task.get("output", "") or ""
                inst.task_output_preview = output[:100] + "..." if len(output) > 100 else output
                break


def get_recent_tasks(limit: int = 20) -> list[dict]:
    """从外部任务 DB 读取最近任务（含已完成的）"""
    db_path = os.environ.get("CLAUDE_MONITOR_TASK_DB", "")
    if not db_path:
        default = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "claude_web_manager", "data", "tasks.db",
        )
        if os.path.exists(default):
            db_path = default
    if not db_path or not os.path.exists(db_path):
        return []

    import sqlite3
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return []


def _is_claude_process(parts: list[str]) -> bool:
    """判断是否为 Claude 进程（排除 grep 和 shell wrapper）"""
    for p in parts:
        if not p:
            continue
        # 二进制名包含 claude
        basename = os.path.basename(p)
        if basename == "claude" or basename.startswith("claude "):
            return True
        # Cursor 插件中的 claude binary
        if "claude-code" in p and "native-binary/claude" in " ".join(parts):
            return True
    return False


def _detect_type(cmdline: str, parts: list[str]) -> str:
    """检测实例类型"""
    if "cursor-server" in cmdline or "claude-code-" in cmdline:
        return "cursor"
    if "login" in parts:
        return "cli-login"
    # 检查是否有 -p 参数（one-shot 模式）
    for i, p in enumerate(parts):
        if p == "-p" and i + 1 < len(parts):
            # 带 --resume 的是 API 调用（来自 web manager 等）
            if "--resume" in cmdline or "--output-format json" in cmdline:
                return "cli-api"
            return "cli-oneshot"
    return "cli-interactive"


def _extract_args(instance: ClaudeInstance, cmdline: str, parts: list[str]):
    """从命令行参数提取详细信息"""
    for i, p in enumerate(parts):
        if p == "--model" and i + 1 < len(parts):
            instance.model = parts[i + 1]
        elif p == "--permission-mode" and i + 1 < len(parts):
            instance.permission_mode = parts[i + 1]
        elif p == "--resume" and i + 1 < len(parts):
            instance.session_id = parts[i + 1][:12] + "..."
        elif p == "-p" and i + 1 < len(parts):
            instance.prompt = parts[i + 1]

    # 提取版本号（Cursor 插件路径中含版本）
    ver_match = re.search(r"claude-code-(\d+\.\d+\.\d+)", cmdline)
    if ver_match:
        instance.version = ver_match.group(1)


def _get_user(pid: int) -> str:
    """获取进程所属用户"""
    try:
        stat_path = f"/proc/{pid}/status"
        with open(stat_path) as f:
            for line in f:
                if line.startswith("Uid:"):
                    uid = int(line.split()[1])
                    import pwd
                    return pwd.getpwuid(uid).pw_name
    except (PermissionError, FileNotFoundError, KeyError):
        pass
    return "?"


def _read_proc_stat(pid: int) -> dict:
    """读取进程 CPU/内存/启动时间"""
    result = {}
    try:
        with open(f"/proc/{pid}/stat") as f:
            fields = f.read().split()
        # RSS in pages
        rss_pages = int(fields[23])
        page_size = os.sysconf("SC_PAGE_SIZE")
        result["mem_mb"] = rss_pages * page_size // (1024 * 1024)

        # 启动时间
        clk_tck = os.sysconf("SC_CLK_TCK")
        with open("/proc/uptime") as f:
            system_uptime = float(f.read().split()[0])
        start_ticks = int(fields[21])
        start_seconds_ago = system_uptime - (start_ticks / clk_tck)
        result["uptime"] = _format_duration(start_seconds_ago)
        result["start_time"] = time.strftime(
            "%H:%M", time.localtime(time.time() - start_seconds_ago)
        )

        # CPU（粗略：utime + stime）
        utime = int(fields[13]) / clk_tck
        stime = int(fields[14]) / clk_tck
        total_cpu = utime + stime
        if start_seconds_ago > 0:
            result["cpu"] = round(total_cpu / start_seconds_ago * 100, 1)

    except (FileNotFoundError, PermissionError, IndexError, ValueError):
        pass
    return result


def _format_duration(seconds: float) -> str:
    """格式化时间长度"""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h{(s % 3600) // 60}m"
    return f"{s // 86400}d{(s % 86400) // 3600}h"


def get_session_history(home_dir: str = "") -> list[dict]:
    """读取 ~/.claude/history.jsonl 获取最近会话历史"""
    if not home_dir:
        home_dir = os.path.expanduser("~")
    history_path = os.path.join(home_dir, ".claude", "history.jsonl")
    sessions = []
    try:
        with open(history_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    sessions.append(entry)
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        pass
    return sessions[-50:]  # 最近 50 条


def get_machine_stats() -> dict:
    """获取机器整体资源"""
    stats = {}
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
            stats["load_1m"] = parts[0]
            stats["load_5m"] = parts[1]
    except FileNotFoundError:
        pass

    try:
        with open("/proc/meminfo") as f:
            mem = {}
            for line in f:
                k, v = line.split(":")
                mem[k.strip()] = int(v.strip().split()[0])
            total = mem.get("MemTotal", 1)
            avail = mem.get("MemAvailable", 0)
            stats["mem_total_gb"] = round(total / 1024 / 1024, 1)
            stats["mem_used_gb"] = round((total - avail) / 1024 / 1024, 1)
            stats["mem_percent"] = round((total - avail) / total * 100)
    except (FileNotFoundError, ValueError):
        pass

    return stats
