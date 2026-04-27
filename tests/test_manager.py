from __future__ import annotations

import time

import pytest

from project_wall.manager import ProcessManager
from tests.conftest import wait_for_port, wait_for_port_free


def test_start_binds_port(manager: ProcessManager, dummy_port: int) -> None:
    state = manager.start("dummy")
    assert state.error is None, state.error
    assert state.pid is not None
    assert manager.is_running("dummy")
    assert wait_for_port("127.0.0.1", dummy_port, timeout_s=8.0)


def test_start_is_idempotent_for_running_project(manager: ProcessManager) -> None:
    first = manager.start("dummy")
    pid = first.pid
    second = manager.start("dummy")
    assert second.pid == pid  # same process, no restart


def test_stop_releases_port(manager: ProcessManager, dummy_port: int) -> None:
    manager.start("dummy")
    assert wait_for_port("127.0.0.1", dummy_port, timeout_s=8.0)
    state = manager.stop("dummy")
    assert state.pid is None
    assert state.exit_code is not None
    assert wait_for_port_free("127.0.0.1", dummy_port, timeout_s=8.0)
    assert not manager.is_running("dummy")


def test_is_running_false_before_start(manager: ProcessManager) -> None:
    assert not manager.is_running("dummy")


def test_unknown_project_raises(manager: ProcessManager) -> None:
    with pytest.raises(KeyError):
        manager.start("ghost")
    with pytest.raises(KeyError):
        manager.stop("ghost")


def test_log_tail_captures_launch_header(manager: ProcessManager) -> None:
    manager.start("dummy")
    # Let the log writer thread pick up the launch marker.
    time.sleep(0.5)
    lines = manager.tail("dummy", n=50)
    assert any("[wall] launching" in line for line in lines)


def test_all_states_returns_entry_per_project(manager: ProcessManager) -> None:
    states = manager.all_states()
    assert set(states.keys()) == {"dummy"}


def test_stop_when_not_running_is_safe(manager: ProcessManager) -> None:
    state = manager.stop("dummy")
    assert state.pid is None
