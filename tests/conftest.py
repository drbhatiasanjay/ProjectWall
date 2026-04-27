from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterator

import httpx
import pytest
import yaml

from project_wall.config import WallConfig, load_config
from project_wall.manager import ProcessManager


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_port(host: str, port: int, timeout_s: float = 10.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            if s.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.1)
    return False


def wait_for_port_free(host: str, port: int, timeout_s: float = 10.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            if s.connect_ex((host, port)) != 0:
                return True
        time.sleep(0.1)
    return False


@pytest.fixture
def dummy_port() -> int:
    return free_port()


@pytest.fixture
def dummy_config(tmp_path: Path, dummy_port: int) -> Path:
    """Writes a projects.yml with one dummy project using python's http.server.

    We point `path` at the project root so the server has something to serve;
    the content served doesn't matter — only binding + responding does.
    """
    project_root = Path(__file__).resolve().parent.parent
    data = {
        "version": 1,
        "defaults": {"health_timeout_s": 5, "idle_shutdown_min": 60},
        "projects": [
            {
                "id": "dummy",
                "name": "Dummy Server",
                "category": "local",
                "color": "#00ff00",
                "icon": "🧪",
                "path": str(project_root),
                "stack": "http",
                "command": [
                    sys.executable,
                    "-m",
                    "http.server",
                    "{port}",
                    "--bind",
                    "127.0.0.1",
                ],
                "port": dummy_port,
                "health": "http://127.0.0.1:{port}/",
            }
        ],
    }
    cfg_path = tmp_path / "projects.yml"
    cfg_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return cfg_path


@pytest.fixture
def loaded_config(dummy_config: Path) -> WallConfig:
    return load_config(dummy_config)


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    d = tmp_path / "logs"
    d.mkdir()
    return d


@pytest.fixture
def manager(loaded_config: WallConfig, log_dir: Path) -> Iterator[ProcessManager]:
    mgr = ProcessManager(loaded_config, log_dir)
    try:
        yield mgr
    finally:
        mgr.shutdown()


@pytest.fixture
def http_server(dummy_port: int, tmp_path: Path) -> Iterator[str]:
    """Launches python -m http.server on a free port for the duration of a test.

    Yields the base URL. Used by health-probe tests that don't want to go
    through the manager. Kept sync so it doesn't trigger pytest-asyncio fixture
    handling (which conflicts with pytest-playwright's event-loop management
    when both plugins are loaded in the same session).
    """
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(dummy_port), "--bind", "127.0.0.1"],
        cwd=str(tmp_path),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert wait_for_port("127.0.0.1", dummy_port, timeout_s=8.0)
        yield f"http://127.0.0.1:{dummy_port}/"
    finally:
        proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=5)
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


@pytest.fixture
def wall_server(
    dummy_config: Path, log_dir: Path
) -> Iterator[tuple[str, subprocess.Popen]]:
    """Launches `wall serve --no-open-browser` as a real subprocess.

    Exercises the exact code path the production `launch.bat` / `ProjectWall.vbs`
    launcher uses. Shared between test_e2e.py (HTTP-level tests) and
    test_browser.py (Playwright UI tests).
    """
    port = free_port()
    root = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    env["WALL_CONFIG"] = str(dummy_config)
    env["WALL_LOGS"] = str(log_dir)

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "cli.wall",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-open-browser",
            "--quiet",
        ],
        cwd=str(root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
    )
    try:
        assert wait_for_port("127.0.0.1", port, timeout_s=20.0), (
            f"wall server never bound port {port}"
        )
        yield f"http://127.0.0.1:{port}", proc
    finally:
        proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=10)
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
