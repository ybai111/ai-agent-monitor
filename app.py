"""
Claude Monitor — 终端看板，实时监控所有 Claude 实例 + 任务历史
"""

import time as _time

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Static, DataTable, Label, Rule, TabbedContent, TabPane
from textual.timer import Timer
from rich.text import Text

from scanner import scan_instances, get_machine_stats, get_recent_tasks, ClaudeInstance


def _status_icon(status: str) -> Text:
    """任务状态图标"""
    icons = {
        "completed": Text("✓", style="bold green"),
        "failed": Text("✗", style="bold red"),
        "running": Text("●", style="bold cyan"),
        "pending": Text("○", style="dim"),
        "cancelled": Text("—", style="dim"),
    }
    return icons.get(status, Text("?", style="dim"))


def _format_ts(ts) -> str:
    """时间戳格式化"""
    if not ts:
        return "-"
    try:
        return _time.strftime("%m-%d %H:%M", _time.localtime(float(ts)))
    except (ValueError, TypeError):
        return "-"


def _format_duration(start, end) -> str:
    """计算耗时"""
    if not start or not end:
        return "-"
    try:
        sec = float(end) - float(start)
        if sec < 0:
            return "-"
        if sec < 60:
            return f"{sec:.0f}s"
        if sec < 3600:
            return f"{sec/60:.0f}m{sec%60:.0f}s"
        return f"{sec/3600:.0f}h{(sec%3600)/60:.0f}m"
    except (ValueError, TypeError):
        return "-"


class StatsBar(Static):
    """顶部状态栏"""

    def compose(self) -> ComposeResult:
        yield Label(id="stats-label")

    def update_stats(self, instances: list[ClaudeInstance], machine: dict, tasks: list[dict]):
        label = self.query_one("#stats-label", Label)
        total_mem = sum(i.mem_mb for i in instances)
        cursor_count = sum(1 for i in instances if i.type == "cursor")
        cli_count = len(instances) - cursor_count
        users = len(set(i.user for i in instances))

        # 任务统计
        running = sum(1 for t in tasks if t.get("status") == "running")
        completed = sum(1 for t in tasks if t.get("status") == "completed")
        failed = sum(1 for t in tasks if t.get("status") == "failed")

        parts = []
        parts.append(f"[bold cyan]{len(instances)}[/] 实例")
        parts.append(f"[dim]([/]{cursor_count} Cursor + {cli_count} CLI[dim])[/]")
        parts.append(f"[dim]|[/] [bold]{users}[/] 用户")
        parts.append(f"[dim]|[/] 内存 [bold]{total_mem}[/]MB")

        if tasks:
            task_parts = []
            if running:
                task_parts.append(f"[cyan]{running} 进行中[/]")
            if completed:
                task_parts.append(f"[green]{completed} 完成[/]")
            if failed:
                task_parts.append(f"[red]{failed} 失败[/]")
            if task_parts:
                parts.append(f"[dim]|[/] 任务: {' '.join(task_parts)}")

        if machine.get("load_1m"):
            parts.append(f"[dim]|[/] Load {machine['load_1m']}")

        label.update("  ".join(parts))


class InstanceTable(DataTable):
    """活跃实例表格"""

    def on_mount(self):
        self.add_column("", key="icon", width=3)
        self.add_column("用户", key="user")
        self.add_column("类型", key="type")
        self.add_column("模型", key="model")
        self.add_column("项目", key="project")
        self.add_column("当前任务", key="task", width=40)
        self.add_column("内存", key="mem")
        self.add_column("时长", key="uptime")
        self.add_column("PID", key="pid")
        self.cursor_type = "row"
        self.zebra_stripes = True

    def refresh_data(self, instances: list[ClaudeInstance]):
        self.clear()
        for inst in instances:
            # 状态图标
            icon = Text("●", style="bold green") if inst.type != "cli-login" else Text("○", style="dim")

            # 类型
            type_styles = {
                "cursor": "bold magenta",
                "cli-api": "bold cyan",
                "cli-interactive": "bold green",
                "cli-oneshot": "bold blue",
                "cli-login": "dim",
            }
            type_text = Text(inst.type_label, style=type_styles.get(inst.type, ""))

            # 模型
            model_text = Text(inst.model or "-")
            if inst.model and "opus" in inst.model.lower():
                model_text.stylize("bold yellow")
            elif inst.model and "sonnet" in inst.model.lower():
                model_text.stylize("cyan")

            # 任务描述（优先用 prompt，其次 session_id）
            task_desc = inst.prompt_short or inst.session_id or "-"
            task_text = Text(task_desc, style="italic" if inst.type == "cli-api" else "")

            # 内存
            mem_text = Text(f"{inst.mem_mb}M")
            if inst.mem_mb > 1000:
                mem_text.stylize("bold red")
            elif inst.mem_mb > 500:
                mem_text.stylize("yellow")

            self.add_row(
                icon, inst.user, type_text, model_text,
                Text(inst.project_name), task_text,
                mem_text, inst.uptime or "-", str(inst.pid),
            )


class TaskTable(DataTable):
    """任务历史表格（来自 claude_web_manager DB）"""

    def on_mount(self):
        self.add_column("", key="icon", width=3)
        self.add_column("状态", key="status")
        self.add_column("任务", key="prompt", width=50)
        self.add_column("耗时", key="duration")
        self.add_column("时间", key="time")
        self.add_column("ID", key="id")
        self.cursor_type = "row"
        self.zebra_stripes = True

    def refresh_data(self, tasks: list[dict]):
        self.clear()
        for t in tasks:
            status = t.get("status", "?")
            icon = _status_icon(status)

            # 状态文字
            status_styles = {
                "completed": "bold green",
                "failed": "bold red",
                "running": "bold cyan",
                "pending": "dim",
                "cancelled": "dim",
            }
            status_text = Text(status, style=status_styles.get(status, ""))

            # prompt 截断
            prompt = t.get("prompt", "")[:60]
            if len(t.get("prompt", "")) > 60:
                prompt += "..."

            # 耗时
            duration = _format_duration(t.get("started_at"), t.get("finished_at"))

            # 时间
            ts = _format_ts(t.get("created_at"))

            self.add_row(
                icon, status_text, prompt, duration, ts, t.get("id", "")[:8],
            )


class ClaudeMonitor(App):
    """Claude 实例监控看板"""

    CSS = """
    Screen {
        background: $surface;
    }
    #stats-bar {
        height: 3;
        padding: 0 2;
        background: $boost;
    }
    #stats-bar Label {
        width: 100%;
        content-align: left middle;
        padding: 1 0;
    }
    #instances-section {
        height: 1fr;
        min-height: 10;
    }
    #instances-section .section-title {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    #tasks-section {
        height: 1fr;
        min-height: 10;
    }
    #tasks-section .section-title {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    InstanceTable, TaskTable {
        height: 1fr;
    }
    #detail-bar {
        height: 3;
        padding: 0 2;
        background: $boost;
    }
    """

    BINDINGS = [
        ("q", "quit", "退出"),
        ("r", "refresh", "刷新"),
        ("k", "kill_selected", "终止"),
        ("tab", "focus_next", "切换面板"),
    ]

    TITLE = "Claude Monitor"
    SUB_TITLE = "实例 + 任务追踪"

    def compose(self) -> ComposeResult:
        yield Header()
        yield StatsBar(id="stats-bar")
        with Vertical(id="instances-section"):
            yield Static("[bold]活跃实例[/]", classes="section-title")
            yield InstanceTable(id="instance-table")
        yield Rule()
        with Vertical(id="tasks-section"):
            yield Static("[bold]任务历史[/] [dim](claude_web_manager)[/]", classes="section-title")
            yield TaskTable(id="task-table")
        yield Static(id="detail-bar")
        yield Footer()

    def on_mount(self):
        self.action_refresh()
        self.set_interval(3.0, self.action_refresh)

    def action_refresh(self):
        instances = scan_instances()
        machine = get_machine_stats()
        tasks = get_recent_tasks(limit=15)

        self.query_one(StatsBar).update_stats(instances, machine, tasks)
        self.query_one(InstanceTable).refresh_data(instances)
        self.query_one(TaskTable).refresh_data(tasks)

        # 详情栏
        detail = self.query_one("#detail-bar", Static)
        if instances:
            projects = sorted(set(i.project_name for i in instances if i.project_name != "?"))
            detail.update(f"  [dim]活跃项目:[/] {', '.join(projects) or '-'}")
        else:
            detail.update("  [dim]当前没有活跃的 Claude 实例[/]")

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        """选中行时显示详情"""
        table = event.data_table
        row_data = table.get_row(event.row_key)
        if not row_data:
            return

        detail = self.query_one("#detail-bar", Static)

        if isinstance(table, InstanceTable):
            pid = str(row_data[-1])
            for inst in scan_instances():
                if str(inst.pid) == pid:
                    parts = [f"  [bold]PID {inst.pid}[/]"]
                    if inst.cwd:
                        parts.append(f"[dim]CWD:[/] {inst.cwd}")
                    if inst.version:
                        parts.append(f"[dim]v{inst.version}[/]")
                    if inst.prompt:
                        parts.append(f"\n  [dim]任务:[/] {inst.prompt[:120]}")
                    detail.update("  ".join(parts))
                    break

        elif isinstance(table, TaskTable):
            task_id = str(row_data[-1])
            for t in get_recent_tasks(limit=20):
                if t.get("id", "")[:8] == task_id:
                    output = (t.get("output") or t.get("error") or "(无输出)")[:150]
                    detail.update(f"  [bold]{t['id']}[/] [dim]|[/] {output}")
                    break

    def action_kill_selected(self):
        """终止选中的实例进程"""
        table = self.query_one(InstanceTable)
        if table.has_focus and table.cursor_row is not None:
            row_data = table.get_row_at(table.cursor_row)
            if row_data:
                pid = row_data[-1]
                import os, signal
                try:
                    os.kill(int(str(pid)), signal.SIGTERM)
                    self.notify(f"已发送 SIGTERM 到 PID {pid}", severity="warning")
                    self.set_timer(1.0, self.action_refresh)
                except (ProcessLookupError, PermissionError) as e:
                    self.notify(f"无法终止: {e}", severity="error")


def main():
    app = ClaudeMonitor()
    app.run()


if __name__ == "__main__":
    main()
