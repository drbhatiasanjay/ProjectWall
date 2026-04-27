"""End-to-end tests — boot the real CLI via uvicorn subprocess, drive it over HTTP.

Exercises the same code path that `launch.bat` / `ProjectWall.vbs` use,
so a green run here is a strong signal that the zero-UI launcher works.
"""
from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from pathlib import Path

import httpx

from tests.conftest import free_port, wait_for_port, wait_for_port_free


def test_e2e_dashboard_reachable(wall_server: tuple[str, subprocess.Popen]) -> None:
    base, _ = wall_server
    resp = httpx.get(f"{base}/", timeout=5.0)
    assert resp.status_code == 200
    assert "ProjectWall" in resp.text
    assert "Dummy Server" in resp.text


def test_e2e_projects_api(wall_server: tuple[str, subprocess.Popen]) -> None:
    base, _ = wall_server
    resp = httpx.get(f"{base}/api/projects", timeout=5.0)
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()["projects"]]
    assert "dummy" in ids


def test_e2e_start_stop_cycle(
    wall_server: tuple[str, subprocess.Popen], dummy_port: int
) -> None:
    base, _ = wall_server
    with httpx.Client(base_url=base, timeout=10.0) as client:
        start = client.post("/api/projects/dummy/start")
        assert start.status_code == 200, start.text
        assert start.json()["running"] is True

        assert wait_for_port("127.0.0.1", dummy_port, timeout_s=8.0)

        health = client.get("/api/health").json()
        assert health["results"]["dummy"]["ok"] is True

        stop = client.post("/api/projects/dummy/stop")
        assert stop.status_code == 200
        assert stop.json()["running"] is False

        assert wait_for_port_free("127.0.0.1", dummy_port, timeout_s=8.0)


def test_e2e_server_shuts_down_managed_procs_on_exit(
    dummy_config: Path, log_dir: Path, tmp_path: Path
) -> None:
    """When `wall serve` is killed, its lifespan must stop child processes."""
    port = free_port()
    dummy_port_override = free_port()

    # Rewrite config to use a freshly-picked dummy port so nothing from prior
    # fixture leaks into this test.
    import yaml
    data = yaml.safe_load(dummy_config.read_text())
    data["projects"][0]["port"] = dummy_port_override
    fresh_cfg = tmp_path / "projects_fresh.yml"
    fresh_cfg.write_text(yaml.safe_dump(data))

    root = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    env["WALL_CONFIG"] = str(fresh_cfg)
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
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )
    try:
        assert wait_for_port("127.0.0.1", port, timeout_s=20.0)
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10.0) as c:
            r = c.post("/api/projects/dummy/start")
            assert r.status_code == 200
            assert wait_for_port("127.0.0.1", dummy_port_override, timeout_s=8.0)
    finally:
        proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=15)
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)

    # After the wall server exits, the managed dummy server must be torn down.
    assert wait_for_port_free("127.0.0.1", dummy_port_override, timeout_s=15.0), (
        "child process leaked after wall serve exited"
    )
