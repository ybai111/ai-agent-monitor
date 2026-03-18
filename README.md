# AI Agent Monitor

Terminal dashboard for monitoring all active AI coding agents on your machine.

Detects **Claude CLI, Cursor, Antigravity, Windsurf, Trae, Aider, Copilot, Codex** and more — showing who's running what, resource usage, and task status in real time.

## Screenshot

```
┌─ AI Agent Monitor ── Claude · Cursor · Antigravity · Windsurf ─┐
│ 7 instances (3 Claude + 2 Cursor + 1 Codex + 1 GK MCP)        │
├─ Active Instances ─────────────────────────────────────────────┤
│   USER        TOOL    TYPE  MODEL       PROJECT        MEM     │
│ ● alice       Cursor  扩展  opus        my-webapp/     328M    │
│ ● alice       Cursor  服务  [codex]     my-webapp/      47M    │
│ ● alice       Claude  API   -           api-server/    370M    │
│ ● bob         Claude  交互  -           ml-pipeline/   481M    │
│ ● charlie     Cursor  扩展  opus        chat-app/      317M    │
│ ● dave        AG      服务  -           -                -     │
├─ Task History ─────────────────────────────────────────────────┤
│ ✓ completed  给AI装技能包...           3m20s  03-17 07:08     │
│ ✗ failed     weekly --publish          0m5s   03-17 06:30     │
└────────────────────────────────────────────────────────────────┘
```

## Supported Tools

| Tool | Detection Method | Info Extracted |
|------|------------------|----------------|
| **Claude CLI** | Binary name `claude` in `/proc` | Model, prompt, session, permissions, CWD |
| **Cursor** | `.cursor-server` in process path | Extensions (Claude Code, Codex, Copilot), version |
| **Antigravity** | `.antigravity-server` in process path | Extensions, version |
| **Windsurf** | `.windsurf-server` in process path | Extensions, version |
| **Trae** | `.trae-server` in process path | Extensions, version |
| **Aider** | Binary name `aider` | Model, CWD |
| **Copilot** | `github.copilot` extension | Version |
| **Codex** | `openai.chatgpt` extension | Server status |
| **Cline / Roo Code** | Extension prefix match | Version |
| **GitKraken MCP** | `gk mcp` in cmdline | Host IDE |

## Features

- **Multi-tool detection** — Scans `/proc` for all AI coding processes across all users
- **IDE extension awareness** — Detects AI extensions inside Cursor, Antigravity, Windsurf, Trae
- **Task tracking** — Shows current prompt/task for CLI instances
- **Resource monitoring** — Memory, CPU, uptime per instance
- **Task history** — Completed/failed/running tasks with duration (optional, needs task DB)
- **Auto refresh** — Updates every 3 seconds
- **Process management** — Kill selected instance with `k`
- **Multi-user** — Works on shared development servers

## Requirements

- **Linux** (reads `/proc` filesystem)
- Python 3.10+

## Install

```bash
git clone https://github.com/yourusername/ai-agent-monitor.git
cd ai-agent-monitor
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

Set `CLAUDE_MONITOR_TASK_DB` to a SQLite database path to show task history:

```bash
export CLAUDE_MONITOR_TASK_DB=/path/to/tasks.db
python app.py
```

The DB should have a `tasks` table with: `id`, `prompt`, `status`, `output`, `created_at`, `started_at`, `finished_at`.

## How It Works

1. Scans `/proc/*/cmdline` for AI tool processes
2. Classifies by tool (Claude/Cursor/AG/...) and type (CLI/extension/server/MCP)
3. Extracts model, prompt, permissions from command-line arguments
4. Reads `/proc/*/stat` for CPU/memory/uptime
5. Optionally queries a task database for completion status
6. Renders in a Textual TUI with auto-refresh

## Adding New Tools

Edit `scanner.py`:

1. Add IDE server directory to `_IDE_SIGNATURES` (e.g. `".my-ide-server": "my-ide"`)
2. Add extension prefix to `_EXTENSION_SIGNATURES` (e.g. `"vendor.ai-ext": "my-ai"`)
3. Or add CLI detection in `_classify_process()`

## License

MIT
