# ProjectWall

A one-click launcher dashboard for local dev projects. Double-click, browser opens to a dashboard of every Streamlit / Vite / uvicorn project on your machine. Start, stop, tail logs, see health — no terminal juggling.

## Quick Start

**First time:**

```bash
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e .[dev]
./.venv/Scripts/python.exe -m playwright install chromium
```

**Launch (silent — no console window):**

Double-click `ProjectWall.vbs`. The server boots in the background and your browser opens to `http://127.0.0.1:8765`.

**Launch (terminal — see logs live):**

```bash
./.venv/Scripts/python.exe -m cli.wall serve
```

## Configure Projects

Edit `projects.yml`. Each entry declares how to start a project:

```yaml
defaults:
  idle_shutdown_min: 45              # auto-stop projects idle for 45 min (0 disables)

projects:
  - id: profsur
    name: ProfSurProject
    path: "c:/Users/hemas/Downloads/ProfSurProject"
    stack: streamlit
    command: ["streamlit", "run", "app.py", "--server.port", "{port}", "--server.headless", "true"]
    port: 8501
    health: "http://127.0.0.1:{port}/_stcore/health"
    live_url: "https://..."          # optional — Streamlit Cloud / Vercel / etc.
    obsidian: "obsidian://..."        # optional — link to project notes
    idle_shutdown_min: 30             # optional per-project override (0 = never)
```

`{port}` is substituted into `command` and `health` at launch.

## Idle Auto-Shutdown

A daemon thread inside `ProcessManager` polls each running project's `last_activity_at` (the latest log line streamed from its stdout). If a project goes silent for longer than its `idle_shutdown_min` threshold, it gets auto-stopped — the log captures `[wall] auto-stopping (idle > N min)` before termination.

Resolution order: per-project `idle_shutdown_min` → `defaults.idle_shutdown_min` → `45` minutes. Setting `0` disables auto-shutdown for that scope.

## Tests

```bash
./.venv/Scripts/python.exe -m pytest                     # all 40 tests (~56s)
./.venv/Scripts/python.exe -m pytest tests/test_browser.py   # Playwright only
./.venv/Scripts/python.exe -m pytest -k "not browser"         # skip browser tests
```

| File | Cases | Scope |
|------|-------|-------|
| `tests/test_config.py`  | 7 | YAML → Pydantic, port substitution, schema validation |
| `tests/test_manager.py` | 8 | Subprocess lifecycle, idempotent start, log tailing |
| `tests/test_health.py`  | 4 | Async httpx probes against a live `http.server` |
| `tests/test_api.py`     | 9 | FastAPI `TestClient` — all endpoints + 404 paths |
| `tests/test_e2e.py`     | 4 | Real `wall serve` subprocess, HTTP lifecycle, Job Object cleanup |
| `tests/test_browser.py` | 8 | Playwright/Chromium — dashboard buttons, health pill, JS console |
| `tests/test_idle_shutdown.py` | 6 | Auto-stop daemon — silent vs active project, threshold resolution, disable, thread teardown |

## CLI

```bash
wall serve [--port 8765] [--host 127.0.0.1] [--no-open-browser] [--quiet]
wall status                        # print configured projects (static)
wall up <project_id>               # start a single project (scripting)
wall down <project_id>             # stop (only works in same process — use HTTP API for running server)
```

## How the Launcher Stays Quiet

`ProjectWall.vbs` invokes `pythonw.exe` (Python's windowless Windows build) via `cmd.exe /c` with `WScript.Shell.Run(..., 0, False)` — no console flash, no terminal window. Logs redirect to `logs/wall-launcher.log` and per-project files under `logs/<project_id>.log`.

The `wall serve` command detects if `127.0.0.1:8765` is already bound. If so, it just opens the browser and exits — double-clicking the launcher twice never causes a port collision.

## Child Process Cleanup (Windows)

Every subprocess launched by `ProcessManager.start` is assigned to a Windows **Job Object** with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. If the launcher is killed from Task Manager or Windows shuts down, the kernel terminates every child in the job automatically — no orphaned Streamlit / Vite / uvicorn processes. See `project_wall/winjob.py`.

On non-Windows platforms the Job Object helper is a no-op; cleanup falls back to the explicit `ProcessManager.stop()` path.

## Project Layout

```
ProjectWall/
├── ProjectWall.vbs         ← double-click entry (silent)
├── launch.bat              ← alt entry
├── projects.yml            ← project registry
├── pyproject.toml
├── project_wall/
│   ├── config.py           ← YAML → Pydantic
│   ├── manager.py          ← subprocess + Job Object
│   ├── winjob.py           ← ctypes Windows Job Object
│   ├── health.py           ← async httpx probes
│   ├── logging_.py         ← per-project log + in-memory tail
│   ├── app.py              ← FastAPI factory + routes
│   ├── templates/index.html
│   └── static/             ← style.css + app.js (4s poll)
├── cli/
│   └── wall.py             ← Click CLI
├── logs/                   ← runtime logs
└── tests/
```

## Test-Infra Gotcha (Read Before Touching test_health.py)

`pytest-asyncio` and `pytest-playwright` leave a "running" asyncio loop bound to the main thread for the whole session. Calling `asyncio.run()` or `loop.run_until_complete()` from a sync test on the main thread raises *"Cannot run the event loop while another loop is running."*

`tests/test_health.py::_run` works around this by driving each coroutine on a fresh loop in a **side thread** — the running-loop flag is per-thread, so a worker thread is unaffected.

Do not replace `_run` with `asyncio.run`. The full suite will break the moment `tests/test_browser.py` runs in the same session.

## Deferred

- pystray tray icon (extra declared in pyproject)
- WebSocket log streaming (currently poll-based)
- Persistence of run state across server restarts
- GitHub Actions CI (needs `git init` + remote first)
