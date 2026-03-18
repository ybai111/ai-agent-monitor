"""
AI Coding Agent 扫描器：检测所有活跃的 AI 编程工具实例
支持：Claude CLI, Cursor, Antigravity, Windsurf, Trae, Aider, Copilot, Codex 等
"""

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AgentInstance:
    """一个 AI 编程工具实例"""
    pid: int
    user: str
    tool: str       # "claude-cli" | "cursor" | "antigravity" | "windsurf" | "trae" | "aider" | "copilot" | "codex" | ...
    sub_type: str    # "interactive" | "oneshot" | "api" | "login" | "server" | "extension" | "mcp"
    model: str = ""
    cwd: str = ""
    prompt: str = ""
    session_id: str = ""
    permission_mode: str = ""
    extension: str = ""  # IDE 扩展名（如 "anthropic.claude-code-2.1.77"）
    cpu_percent: float = 0.0
    mem_mb: int = 0
    started_at: str = ""
    uptime: str = ""
    version: str = ""
    # 外部任务 DB 补充
    task_id: str = ""
    task_status: str = ""
    task_output_preview: str = ""

    @property
    def project_name(self) -> str:
        if not self.cwd:
            return "?"
        return Path(self.cwd).name

    @property
    def tool_label(self) -> str:
        """显示名称"""
        labels = {
            "claude-cli": "Claude",
            "cursor": "Cursor",
            "antigravity": "AG",
            "windsurf": "Windsurf",
            "trae": "Trae",
            "aider": "Aider",
            "copilot": "Copilot",
            "codex": "Codex",
            "gk-mcp": "GK MCP",
            "unknown-ide": "IDE",
        }
        return labels.get(self.tool, self.tool)

    @property
    def type_label(self) -> str:
        labels = {
            "interactive": "交互",
            "oneshot": "单次",
            "api": "API",
            "login": "登录",
            "server": "服务",
            "extension": "扩展",
            "mcp": "MCP",
        }
        return labels.get(self.sub_type, self.sub_type)

    @property
    def prompt_short(self) -> str:
        if not self.prompt:
            return ""
        p = self.prompt.strip("'\"")
        return p[:60] + "..." if len(p) > 60 else p


# ============= 工具检测规则 =============

# IDE server 目录特征 → 工具名
_IDE_SIGNATURES = {
    ".cursor-server": "cursor",
    ".antigravity-server": "antigravity",
    ".windsurf-server": "windsurf",
    ".trae-server": "trae",
    ".vscode-server": "vscode",
}

# 扩展名前缀 → AI 工具
_EXTENSION_SIGNATURES = {
    "anthropic.claude-code": "claude-code",
    "openai.chatgpt": "codex",
    "github.copilot": "copilot",
    "saoudrizwan.claude-dev": "cline",
    "rooveterinaryinc.roo-cline": "roo-code",
    "continue.continue": "continue",
    "codeium.codeium": "codeium",
    "supermaven.supermaven": "supermaven",
    "tabbyml.vscode-tabby": "tabby",
}


def scan_instances() -> list[AgentInstance]:
    """扫描所有 AI 编程工具实例"""
    instances = []

    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmdline_raw = f.read()
            parts = cmdline_raw.decode("utf-8", errors="replace").split("\x00")
            cmdline = " ".join(parts)

            result = _classify_process(pid, cmdline, parts)
            if not result:
                continue

            stat = _read_proc_stat(pid)
            inst = AgentInstance(
                pid=pid,
                user=_get_user(pid),
                tool=result["tool"],
                sub_type=result["sub_type"],
                model=result.get("model", ""),
                prompt=result.get("prompt", ""),
                session_id=result.get("session_id", ""),
                permission_mode=result.get("permission_mode", ""),
                extension=result.get("extension", ""),
                version=result.get("version", ""),
                cpu_percent=stat.get("cpu", 0.0),
                mem_mb=stat.get("mem_mb", 0),
                started_at=stat.get("start_time", ""),
                uptime=stat.get("uptime", ""),
            )

            try:
                inst.cwd = os.readlink(f"/proc/{pid}/cwd")
            except (PermissionError, FileNotFoundError):
                pass

            instances.append(inst)

        except (PermissionError, FileNotFoundError, ProcessLookupError):
            continue

    _enrich_from_task_db(instances)
    instances.sort(key=lambda i: (i.user, i.tool, -i.pid))
    return instances


def _classify_process(pid: int, cmdline: str, parts: list[str]) -> dict | None:
    """判断进程类型，返回分类信息或 None"""

    # --- 1. Claude CLI ---
    for p in parts:
        if not p:
            continue
        basename = os.path.basename(p)
        if basename == "claude":
            # 排除 IDE 内嵌的 claude（那些走扩展检测）
            if "cursor-server" in cmdline or "antigravity-server" in cmdline:
                break  # 交给 IDE 扩展检测
            result = {"tool": "claude-cli"}
            if "login" in parts:
                result["sub_type"] = "login"
            elif any(p == "-p" for p in parts):
                result["sub_type"] = "api" if ("--output-format" in cmdline) else "oneshot"
            else:
                result["sub_type"] = "interactive"
            _extract_claude_args(result, parts, cmdline)
            return result

    # --- 2. Aider CLI ---
    for p in parts:
        if os.path.basename(p or "") == "aider":
            result = {"tool": "aider", "sub_type": "interactive"}
            for i, arg in enumerate(parts):
                if arg == "--model" and i + 1 < len(parts):
                    result["model"] = parts[i + 1]
            return result

    # --- 3. IDE 内嵌 AI 扩展（Claude Code, Codex, Copilot 等）---
    for sig, ide_name in _IDE_SIGNATURES.items():
        if sig not in cmdline:
            continue

        # 检查是否为 AI 扩展进程
        for ext_prefix, ext_tool in _EXTENSION_SIGNATURES.items():
            if ext_prefix in cmdline:
                result = {
                    "tool": ide_name,
                    "sub_type": "extension",
                    "extension": ext_tool,
                }
                # Claude Code 扩展有额外信息
                if ext_tool == "claude-code":
                    result["sub_type"] = "extension"
                    _extract_claude_args(result, parts, cmdline)
                # Codex server
                if ext_tool == "codex" and "app-server" in cmdline:
                    result["sub_type"] = "server"
                # 版本号
                ver_match = re.search(rf"{re.escape(ext_prefix)}-([0-9.]+)", cmdline)
                if ver_match:
                    result["version"] = ver_match.group(1)
                return result

        # GitKraken MCP
        if "gk" in cmdline and "mcp" in cmdline:
            host = ""
            for i, p in enumerate(parts):
                if p.startswith("--host="):
                    host = p.split("=", 1)[1]
            return {"tool": "gk-mcp", "sub_type": "mcp", "model": host}

        # IDE server 主进程（只取 bootstrap-fork，跳过 fileWatcher 等辅助进程）
        if "bootstrap-fork" in cmdline and "--type=" not in cmdline:
            return {"tool": ide_name, "sub_type": "server"}

    return None


def _extract_claude_args(result: dict, parts: list[str], cmdline: str):
    """从 Claude 命令行提取参数"""
    for i, p in enumerate(parts):
        if p == "--model" and i + 1 < len(parts):
            result["model"] = parts[i + 1]
        elif p == "--permission-mode" and i + 1 < len(parts):
            result["permission_mode"] = parts[i + 1]
        elif p == "--resume" and i + 1 < len(parts):
            result["session_id"] = parts[i + 1][:12] + "..."
        elif p == "-p" and i + 1 < len(parts):
            result["prompt"] = parts[i + 1]
    ver_match = re.search(r"claude-code-(\d+\.\d+\.\d+)", cmdline)
    if ver_match:
        result["version"] = ver_match.group(1)


def _enrich_from_task_db(instances: list[AgentInstance]):
    """从外部任务 DB 补充状态信息"""
    db_path = os.environ.get("CLAUDE_MONITOR_TASK_DB", "")
    if not db_path:
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
    for inst in instances:
        if inst.sub_type != "api" or not inst.prompt:
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
    """从外部任务 DB 读取最近任务"""
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


def get_machine_stats() -> dict:
    """机器资源"""
    stats = {}
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
            stats["load_1m"] = parts[0]
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


# ============= 辅助函数 =============

def _get_user(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("Uid:"):
                    uid = int(line.split()[1])
                    import pwd
                    return pwd.getpwuid(uid).pw_name
    except (PermissionError, FileNotFoundError, KeyError):
        pass
    return "?"


def _read_proc_stat(pid: int) -> dict:
    result = {}
    try:
        with open(f"/proc/{pid}/stat") as f:
            fields = f.read().split()
        rss_pages = int(fields[23])
        page_size = os.sysconf("SC_PAGE_SIZE")
        result["mem_mb"] = rss_pages * page_size // (1024 * 1024)

        clk_tck = os.sysconf("SC_CLK_TCK")
        with open("/proc/uptime") as f:
            system_uptime = float(f.read().split()[0])
        start_ticks = int(fields[21])
        elapsed = system_uptime - (start_ticks / clk_tck)
        result["uptime"] = _format_duration(elapsed)
        result["start_time"] = time.strftime("%H:%M", time.localtime(time.time() - elapsed))

        utime = int(fields[13]) / clk_tck
        stime = int(fields[14]) / clk_tck
        if elapsed > 0:
            result["cpu"] = round((utime + stime) / elapsed * 100, 1)
    except (FileNotFoundError, PermissionError, IndexError, ValueError):
        pass
    return result


def _format_duration(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h{(s % 3600) // 60}m"
    return f"{s // 86400}d{(s % 86400) // 3600}h"
