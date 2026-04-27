from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import click
import uvicorn

from project_wall.config import load_config
from project_wall.manager import ProcessManager

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "projects.yml"
DEFAULT_LOG_DIR = ROOT / "logs"


def _config_path(path: str | None) -> Path:
    return Path(path or os.environ.get("WALL_CONFIG", DEFAULT_CONFIG))


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _open_browser_when_ready(host: str, port: int, timeout_s: float = 15.0) -> None:
    url = f"http://{host}:{port}/"
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _port_in_use(host, port):
            webbrowser.open(url)
            return
        time.sleep(0.25)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def cli() -> None:
    """ProjectWall — launcher dashboard for local dev projects."""


@cli.command()
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8765, type=int)
@click.option("--config", "config_path", default=None, help="Path to projects.yml")
@click.option("--reload", is_flag=True, help="Enable uvicorn auto-reload")
@click.option("--open-browser/--no-open-browser", default=True, help="Auto-open dashboard")
@click.option("--quiet", is_flag=True, help="Suppress uvicorn access logs")
def serve(
    host: str,
    port: int,
    config_path: str | None,
    reload: bool,
    open_browser: bool,
    quiet: bool,
) -> None:
    """Start the ProjectWall web dashboard and open it in the default browser.

    If the port is already bound, assumes an existing instance is running and
    just opens the browser pointed at it — safe to re-run from a shortcut.
    """
    cfg_path = _config_path(config_path)
    if not cfg_path.exists():
        click.echo(f"Config not found: {cfg_path}", err=True)
        sys.exit(2)
    os.environ.setdefault("WALL_CONFIG", str(cfg_path))
    os.environ.setdefault("WALL_LOGS", str(DEFAULT_LOG_DIR))

    if _port_in_use(host, port):
        if open_browser:
            webbrowser.open(f"http://{host}:{port}/")
        click.echo(f"ProjectWall already running on http://{host}:{port}")
        return

    if open_browser:
        threading.Thread(
            target=_open_browser_when_ready,
            args=(host, port),
            daemon=True,
        ).start()

    click.echo(f"ProjectWall serving on http://{host}:{port}")
    log_level = "warning" if quiet else "info"
    uvicorn.run(
        "project_wall.app:app",
        host=host,
        port=port,
        reload=reload,
        access_log=not quiet,
        log_level=log_level,
    )


@cli.command()
@click.option("--config", "config_path", default=None)
def status(config_path: str | None) -> None:
    """Print configured projects (static inspection; does not check running state)."""
    cfg = load_config(_config_path(config_path))
    for p in cfg.projects:
        click.echo(f"{p.icon} {p.id:<12} {p.stack:<10} port={p.port}  path={p.path}")


@cli.command()
@click.argument("project_id")
@click.option("--config", "config_path", default=None)
def up(project_id: str, config_path: str | None) -> None:
    """Start a single project (synchronous, for scripting)."""
    cfg = load_config(_config_path(config_path))
    mgr = ProcessManager(cfg, DEFAULT_LOG_DIR)
    state = mgr.start(project_id)
    if state.error:
        click.echo(f"error: {state.error}", err=True)
        sys.exit(1)
    click.echo(f"started pid={state.pid}  cmd={' '.join(state.command)}")


@cli.command()
@click.argument("project_id")
@click.option("--config", "config_path", default=None)
def down(project_id: str, config_path: str | None) -> None:
    """Stop a project by id. Only works against an in-process manager — for
    running instances, use the HTTP API against `wall serve`."""
    cfg = load_config(_config_path(config_path))
    mgr = ProcessManager(cfg, DEFAULT_LOG_DIR)
    state = mgr.stop(project_id)
    click.echo(f"stopped pid={state.pid} exit={state.exit_code}")


if __name__ == "__main__":
    cli()
