"""Idle auto-shutdown tests.

Drives the daemon watcher in `ProcessManager` with sub-second thresholds
so the test stays under a few seconds while still exercising the real loop.
"""
from __future__ import annotations

import time
from pathlib import Path

from project_wall.config import WallConfig
from project_wall.manager import ProcessManager
from tests.conftest import wait_for_port, wait_for_port_free


def _build_manager(
    cfg: WallConfig,
    log_dir: Path,
    *,
    project_idle_min: float | None = None,
    default_idle_min: float | None = None,
    check_interval_s: float = 0.2,
) -> ProcessManager:
    """Mutates the supplied config in place, returns a fresh manager."""
    if default_idle_min is not None:
        cfg.defaults.idle_shutdown_min = default_idle_min
    cfg.projects[0].idle_shutdown_min = project_idle_min
    return ProcessManager(cfg, log_dir, idle_check_interval_s=check_interval_s)


def test_idle_watcher_stops_silent_project(
    loaded_config: WallConfig, log_dir: Path, dummy_port: int
) -> None:
    # 0.05 min = 3 s threshold; http.server stays silent so its
    # last_activity_at never advances past the launch marker.
    mgr = _build_manager(loaded_config, log_dir, project_idle_min=0.05)
    try:
        mgr.start("dummy")
        assert wait_for_port("127.0.0.1", dummy_port, timeout_s=8.0)

        # Wait long enough for: threshold (3s) + watcher poll (0.2s) + stop overhead.
        assert wait_for_port_free("127.0.0.1", dummy_port, timeout_s=12.0), (
            "watcher should have auto-stopped the silent project"
        )
        assert not mgr.is_running("dummy")
    finally:
        mgr.shutdown()


def test_idle_watcher_keeps_active_project_running(
    loaded_config: WallConfig, log_dir: Path, dummy_port: int
) -> None:
    mgr = _build_manager(loaded_config, log_dir, project_idle_min=0.05)
    try:
        mgr.start("dummy")
        assert wait_for_port("127.0.0.1", dummy_port, timeout_s=8.0)

        # Simulate continuous activity by bumping last_activity_at every 0.5s
        # for longer than the idle threshold. Watcher should never trigger.
        deadline = time.time() + 5.0
        while time.time() < deadline:
            mgr._states["dummy"].last_activity_at = time.time()
            time.sleep(0.5)

        assert mgr.is_running("dummy"), "active project must not be auto-stopped"
    finally:
        mgr.shutdown()


def test_idle_watcher_disabled_when_threshold_zero(
    loaded_config: WallConfig, log_dir: Path, dummy_port: int
) -> None:
    mgr = _build_manager(loaded_config, log_dir, project_idle_min=0)
    try:
        mgr.start("dummy")
        assert wait_for_port("127.0.0.1", dummy_port, timeout_s=8.0)
        time.sleep(2.0)
        assert mgr.is_running("dummy"), "threshold=0 means never auto-stop"
    finally:
        mgr.shutdown()


def test_idle_watcher_uses_defaults_when_project_unset(
    loaded_config: WallConfig, log_dir: Path, dummy_port: int
) -> None:
    # Project leaves idle_shutdown_min unset (None) → fall back to defaults.
    mgr = _build_manager(
        loaded_config,
        log_dir,
        project_idle_min=None,
        default_idle_min=0.05,
    )
    try:
        mgr.start("dummy")
        assert wait_for_port("127.0.0.1", dummy_port, timeout_s=8.0)
        assert wait_for_port_free("127.0.0.1", dummy_port, timeout_s=12.0)
    finally:
        mgr.shutdown()


def test_idle_threshold_resolution(loaded_config: WallConfig, log_dir: Path) -> None:
    mgr = _build_manager(loaded_config, log_dir, project_idle_min=None, default_idle_min=99)
    try:
        # Project unset → uses defaults
        assert mgr._threshold_minutes(loaded_config.projects[0]) == 99
        # Project explicit → wins
        loaded_config.projects[0].idle_shutdown_min = 7
        assert mgr._threshold_minutes(loaded_config.projects[0]) == 7
        # Project explicit zero → wins (disabled)
        loaded_config.projects[0].idle_shutdown_min = 0
        assert mgr._threshold_minutes(loaded_config.projects[0]) == 0
    finally:
        mgr.shutdown()


def test_shutdown_stops_idle_thread(loaded_config: WallConfig, log_dir: Path) -> None:
    mgr = _build_manager(loaded_config, log_dir, project_idle_min=None, default_idle_min=99)
    assert mgr._idle_thread.is_alive()
    mgr.shutdown()
    mgr._idle_thread.join(timeout=2.0)
    assert not mgr._idle_thread.is_alive()
