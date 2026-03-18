# Claude Monitor

A terminal dashboard for monitoring all active Claude Code instances on your machine.

Detects Claude CLI sessions, Cursor plugin instances, and API-driven tasks in real time. Shows who's running what, resource usage, task status, and session history.

## Screenshot

```
┌─ Claude Monitor ──────────────────────────────────────────────┐
│ 6 instances (2 Cursor + 4 CLI) | 3 users | RAM 1.8GB | Load 4.5 │
├─ Active Instances ────────────────────────────────────────────┤
│   USER        TYPE    MODEL  PROJECT              TASK        │
│ ● baiyuhu     Cursor  opus   work_detection/      -           │
│ ● baiyuhu     API     -      claude_web_manager/  生成封面... │
│ ● sunyifan    CLI     -      my-project/          (interactive)│
│ ● zhouyinhong Cursor  opus   nature-chat/         -           │
├─ Task History ────────────────────────────────────────────────┤
│ ✓ completed  给AI装技能包...           3m20s  03-17 07:08     │
│ ✓ completed  今日GitHub热榜精选        1m10s  03-17 06:55     │
│ ✗ failed     weekly --publish          0m5s   03-17 06:30     │
└───────────────────────────────────────────────────────────────┘
```

## Features

- **Instance detection** — Scans `/proc` to find all Claude processes (CLI, Cursor plugin, API calls)
- **Rich info extraction** — User, model (opus/sonnet), project directory, current prompt, permission mode, memory usage, uptime
- **Task history** — Shows completed/failed/running tasks with duration (requires external task database)
- **Auto refresh** — Updates every 3 seconds
- **Process management** — Kill a selected instance with `k`
- **Multi-user** — Sees all users' Claude instances on shared machines

## Requirements

- **Linux** (reads `/proc` filesystem)
- Python 3.10+
- `textual` and `rich` packages

## Install

```bash
git clone https://github.com/baiyuhu/claude-monitor.git
cd claude-monitor
pip install -r requirements.txt
```

## Usage

```bash
python app.py
```

### Keyboard Shortcuts

| Key   | Action          |
|-------|-----------------|
| `q`   | Quit            |
| `r`   | Force refresh   |
| `k`   | Kill selected   |
| `Tab` | Switch panel    |
| `↑/↓` | Navigate rows   |

### Task History (Optional)

Claude Monitor can display task history from an external SQLite database. Set the path via environment variable:

```bash
export CLAUDE_MONITOR_TASK_DB=/path/to/tasks.db
python app.py
```

The database should have a `tasks` table with columns: `id`, `prompt`, `status`, `output`, `created_at`, `started_at`, `finished_at`.

This is compatible with [claude_web_manager](https://github.com/baiyuhu/claude-web-manager) out of the box.

## What It Detects

| Instance Type | How It's Detected | Info Available |
|---------------|-------------------|----------------|
| **Cursor Plugin** | Binary path contains `claude-code-` | Model, version, permission mode, CWD |
| **CLI Interactive** | `claude` process without `-p` flag | CWD, uptime |
| **CLI One-shot** | `claude -p "prompt"` | Full prompt text, CWD |
| **CLI API** | `claude -p ... --output-format json` | Prompt, session ID, task status |
| **CLI Login** | `claude login` | - |

## How It Works

1. Iterates `/proc/*/cmdline` to find processes with `claude` binary
2. Parses command-line arguments to extract model, prompt, session, permissions
3. Reads `/proc/*/stat` for CPU/memory/uptime
4. Optionally queries a SQLite task database for completion status
5. Renders everything in a Textual TUI with auto-refresh

## License

MIT
