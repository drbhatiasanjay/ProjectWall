from __future__ import annotations

import threading
import time
from collections import deque

import httpx

from .alerts import EmailAlerter
from .config import WallConfig
from .manager import ProcessManager

# Backoff (seconds) between successive restart attempts while self-healing.
_RESTART_BACKOFFS = (2.0, 8.0, 20.0)


class HealthMonitor:
    """Background self-healing watcher.

    Every `check_interval_s` it inspects each project the user wants running
    (`ProcessManager.desired_running()`):

      * crashed (desired but process gone)  -> heal
      * running but failing its health URL `unhealthy_threshold` times -> heal

    Heal = restart up to len(_RESTART_BACKOFFS) times with backoff. If the
    project recovers, a "healed" event is recorded (no alert). If every
    restart fails, a "heal_failed" event is recorded and a deduplicated
    email alert is sent.

    A ring buffer of the most recent events is exposed via `events()` for the
    dashboard's ops panel.
    """

    def __init__(
        self,
        mgr: ProcessManager,
        cfg: WallConfig,
        alerter: EmailAlerter,
        log=None,
        check_interval_s: float = 60.0,
        unhealthy_threshold: int = 3,
        probe_timeout_s: float = 5.0,
        event_buffer: int = 50,
        restart_backoffs: tuple[float, ...] = _RESTART_BACKOFFS,
    ):
        self.mgr = mgr
        self.cfg = cfg
        self.alerter = alerter
        self._log = log or (lambda _m: None)
        self.check_interval_s = check_interval_s
        self.unhealthy_threshold = unhealthy_threshold
        self.probe_timeout_s = probe_timeout_s
        self._backoffs = restart_backoffs
        self._fail_counts: dict[str, int] = {}
        self._events: deque[dict] = deque(maxlen=event_buffer)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="wall-health-monitor"
        )

    # ---- lifecycle -----------------------------------------------------
    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)

    # ---- introspection -------------------------------------------------
    def events(self) -> list[dict]:
        with self._lock:
            return list(self._events)

    def _record(self, project: str, kind: str, detail: str) -> None:
        evt = {"ts": time.time(), "project": project, "kind": kind, "detail": detail}
        with self._lock:
            self._events.append(evt)
        self._log(f"[monitor] {project}: {kind} — {detail}")

    # ---- probing -------------------------------------------------------
    def _is_healthy(self, project_id: str) -> bool:
        if not self.mgr.is_running(project_id):
            return False
        project = self.cfg.get(project_id)
        url = project.rendered_health() if project else None
        if not url:
            return True  # running with no health URL — process liveness is enough
        try:
            resp = httpx.get(
                url, timeout=self.probe_timeout_s, follow_redirects=True
            )
            return resp.status_code < 500
        except httpx.HTTPError:
            return False

    # ---- healing -------------------------------------------------------
    def _heal(self, project_id: str) -> bool:
        for attempt, wait in enumerate(self._backoffs, start=1):
            self._record(
                project_id,
                "restart",
                f"attempt {attempt}/{len(self._backoffs)}",
            )
            try:
                self.mgr.start(project_id)
            except Exception as exc:  # noqa: BLE001
                self._record(project_id, "restart_error", str(exc))
            if self._stop.wait(wait):
                return False  # shutting down
            if self._is_healthy(project_id):
                self._record(
                    project_id, "healed", f"recovered after {attempt} restart(s)"
                )
                return True
        self._record(
            project_id,
            "heal_failed",
            f"{len(self._backoffs)} restarts failed",
        )
        self.alerter.send(
            subject=f"{project_id} DOWN — auto-heal failed",
            body=(
                f"Project '{project_id}' is down and {len(self._backoffs)} "
                f"automatic restart attempts failed.\n\n"
                f"Last 20 log lines:\n"
                + "\n".join(self.mgr.tail(project_id, n=20))
            ),
            dedup_key=f"heal_failed:{project_id}",
        )
        return False

    # ---- main loop -----------------------------------------------------
    def _tick(self) -> None:
        for project_id in self.mgr.desired_running():
            if self._stop.is_set():
                return
            if not self.mgr.is_running(project_id):
                self._record(project_id, "crash", "process exited unexpectedly")
                self._heal(project_id)
                continue
            project = self.cfg.get(project_id)
            url = project.rendered_health() if project else None
            if not url:
                self._fail_counts.pop(project_id, None)
                continue
            if self._is_healthy(project_id):
                self._fail_counts.pop(project_id, None)
                continue
            n = self._fail_counts.get(project_id, 0) + 1
            self._fail_counts[project_id] = n
            self._record(
                project_id,
                "unhealthy",
                f"health check failed ({n}/{self.unhealthy_threshold})",
            )
            if n >= self.unhealthy_threshold:
                self._fail_counts.pop(project_id, None)
                self._heal(project_id)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:  # noqa: BLE001 — monitor must never die
                self._log(f"[monitor] tick error: {exc}")
            self._stop.wait(self.check_interval_s)
