from __future__ import annotations

from project_wall.manager import ProcessManager
from project_wall.monitor import HealthMonitor
from tests.conftest import wait_for_port


class FakeAlerter:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str | None]] = []

    def send(self, subject: str, body: str, dedup_key: str | None = None) -> bool:
        self.sent.append((subject, dedup_key))
        return True


def _monitor(manager: ProcessManager, alerter, **kw) -> HealthMonitor:
    return HealthMonitor(
        manager,
        manager.cfg,
        alerter,
        check_interval_s=0.1,
        restart_backoffs=(0.5, 0.5, 0.5),
        probe_timeout_s=2.0,
        **kw,
    )


def test_events_ring_buffer(manager: ProcessManager) -> None:
    mon = _monitor(manager, FakeAlerter(), event_buffer=3)
    for i in range(5):
        mon._record("dummy", "test", f"e{i}")
    evs = mon.events()
    assert len(evs) == 3  # capped at buffer size
    assert [e["detail"] for e in evs] == ["e2", "e3", "e4"]
    assert all({"ts", "project", "kind", "detail"} <= e.keys() for e in evs)


def test_heals_crashed_desired_project(
    manager: ProcessManager, dummy_port: int
) -> None:
    manager.start("dummy")
    assert wait_for_port("127.0.0.1", dummy_port, timeout_s=8.0)
    # Hard-kill outside of stop() -> still "desired", monitor must heal it.
    manager._procs["dummy"].kill()
    manager._procs["dummy"].wait(timeout=5)
    assert not manager.is_running("dummy")

    mon = _monitor(manager, FakeAlerter())
    mon._tick()

    assert wait_for_port("127.0.0.1", dummy_port, timeout_s=8.0)
    assert manager.is_running("dummy")
    kinds = [e["kind"] for e in mon.events()]
    assert "crash" in kinds
    assert "healed" in kinds


def test_user_stopped_project_not_healed(manager: ProcessManager) -> None:
    manager.start("dummy")
    manager.stop("dummy")  # explicit stop -> opted out of self-heal
    assert "dummy" not in manager.desired_running()

    mon = _monitor(manager, FakeAlerter())
    mon._tick()
    assert mon.events() == []  # nothing to heal


def test_heal_failed_sends_alert(manager: ProcessManager) -> None:
    manager.start("dummy")
    manager._procs["dummy"].kill()
    manager._procs["dummy"].wait(timeout=5)

    alerter = FakeAlerter()
    mon = _monitor(manager, alerter)
    # Make every restart attempt a no-op so the project never recovers.
    manager.start = lambda pid: None  # type: ignore[assignment]
    mon._tick()

    kinds = [e["kind"] for e in mon.events()]
    assert "heal_failed" in kinds
    assert any("heal failed" in s.lower() for s, _ in alerter.sent)
    assert alerter.sent[-1][1] == "heal_failed:dummy"  # dedup key
