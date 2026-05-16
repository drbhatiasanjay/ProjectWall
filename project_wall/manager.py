from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import Project, WallConfig
from .logging_ import ProjectLog
from .winjob import WindowsJob


@dataclass
class RunState:
    pid: int | None = None
    started_at: float | None = None
    last_activity_at: float | None = None
    exit_code: int | None = None
    command: list[str] = field(default_factory=list)
    error: str | None = None
    crash_tail: list[str] = field(default_factory=list)


class ProcessManager:
    def __init__(
        self,
        cfg: WallConfig,
        log_dir: Path,
        idle_check_interval_s: float = 1.0,
    ):
        self.cfg = cfg
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._procs: dict[str, subprocess.Popen] = {}
        self._states: dict[str, RunState] = {p.id: RunState() for p in cfg.projects}
        self._logs: dict[str, ProjectLog] = {
            p.id: ProjectLog(self.log_dir / f"{p.id}.log") for p in cfg.projects
        }
        self._lock = threading.RLock()
        self._job = WindowsJob()
        # Projects the user explicitly started and has not explicitly stopped.
        # The health monitor self-heals only these — idle/user stops opt out.
        self._desired_running: set[str] = set()

        self._idle_check_interval_s = idle_check_interval_s
        self._idle_stop_event = threading.Event()
        self._idle_thread = threading.Thread(
            target=self._idle_watcher_loop, daemon=True, name="wall-idle-watcher"
        )
        self._idle_thread.start()

    def _load_dotenv(self, project: Project) -> dict[str, str]:
        """Read project/.env (if present) and return a dict of KEY=VALUE pairs.

        Minimal parser: ignores blank lines and `#` comments; strips surrounding
        single/double quotes from values; tolerates `export KEY=VALUE` prefix.
        Malformed lines are silently skipped — we never want a bad .env to
        prevent a project from starting.
        """
        env_path = Path(project.path) / ".env"
        if not env_path.is_file():
            return {}
        loaded: dict[str, str] = {}
        try:
            for raw in env_path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export "):].lstrip()
                key, sep, value = line.partition("=")
                if not sep:
                    continue
                key = key.strip()
                if not key:
                    continue
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                loaded[key] = value
        except OSError:
            return {}
        return loaded

    def _resolve_exe(self, project: Project, argv: list[str]) -> list[str]:
        if not argv:
            return argv
        head = argv[0]
        candidate = Path(project.path) / head
        if candidate.exists() and os.access(candidate, os.X_OK):
            return [str(candidate), *argv[1:]]
        if sys.platform == "win32":
            # shutil.which on Windows can return extensionless bash scripts that
            # CreateProcess can't run. Prefer .exe, then wrap .cmd/.bat in cmd.exe.
            for suffix in (".exe", ".cmd", ".bat"):
                w = shutil.which(head + suffix)
                if w:
                    if suffix in (".cmd", ".bat"):
                        return ["cmd.exe", "/c", w, *argv[1:]]
                    return [w, *argv[1:]]
        which = shutil.which(head)
        if which:
            return [which, *argv[1:]]
        return argv

    def _stream(self, pid_key: str, stream, log: ProjectLog) -> None:
        state = self._states[pid_key]
        try:
            for raw in iter(stream.readline, ""):
                if not raw:
                    break
                log.write(raw.rstrip("\n"))
                state.last_activity_at = time.time()
        except (ValueError, OSError):
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def start(self, project_id: str) -> RunState:
        with self._lock:
            project = self.cfg.get(project_id)
            if project is None:
                raise KeyError(f"Unknown project: {project_id}")
            state = self._states[project_id]
            if self.is_running(project_id):
                return state

            argv = self._resolve_exe(project, project.rendered_command())
            if not argv:
                state.error = "No command configured"
                return state

            cwd = Path(project.path)
            if not cwd.exists():
                state.error = f"Project path not found: {cwd}"
                return state

            log = self._logs[project_id]
            log.write(f"[wall] launching {' '.join(argv)} in {cwd}")

            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

            dotenv = self._load_dotenv(project)
            child_env = {**os.environ, **dotenv} if dotenv else None
            if dotenv:
                log.write(f"[wall] loaded {len(dotenv)} vars from .env")

            try:
                proc = subprocess.Popen(
                    argv,
                    cwd=str(cwd),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    text=True,
                    bufsize=1,
                    creationflags=creationflags,
                    env=child_env,
                )
            except (FileNotFoundError, OSError) as exc:
                state.error = f"Start failed: {exc}"
                log.write(f"[wall] start failed: {exc}")
                return state

            self._procs[project_id] = proc
            self._desired_running.add(project_id)
            state.pid = proc.pid
            state.started_at = time.time()
            state.last_activity_at = state.started_at
            state.exit_code = None
            state.error = None
            state.command = argv
            state.crash_tail = []

            if not self._job.assign(proc.pid):
                log.write(
                    "[wall] warning: could not attach to job object "
                    "— child may survive forced parent termination"
                )

            threading.Thread(
                target=self._stream,
                args=(project_id, proc.stdout, log),
                daemon=True,
            ).start()
            return state

    def stop(self, project_id: str, timeout: float = 10.0) -> RunState:
        with self._lock:
            state = self._states.get(project_id)
            proc = self._procs.get(project_id)
            if state is None:
                raise KeyError(f"Unknown project: {project_id}")
            # An explicit stop (user, idle-watcher, or shutdown) opts the
            # project out of self-healing until it is started again.
            self._desired_running.discard(project_id)
            if proc is None or proc.poll() is not None:
                state.pid = None
                return state

            log = self._logs[project_id]
            log.write("[wall] stopping")
            try:
                if sys.platform == "win32":
                    proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
                else:
                    proc.terminate()
            except (OSError, ValueError):
                pass

        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

        with self._lock:
            state.exit_code = proc.returncode
            state.pid = None
            self._procs.pop(project_id, None)
            self._logs[project_id].write(f"[wall] stopped (exit={proc.returncode})")
            return state

    def is_running(self, project_id: str) -> bool:
        proc = self._procs.get(project_id)
        if proc is None:
            return False
        alive = proc.poll() is None
        if not alive:
            state = self._states[project_id]
            state.exit_code = proc.returncode
            state.pid = None
            # Unexpected exit (not via stop()) with non-zero code — capture
            # the last 20 log lines so the UI can show why it crashed without
            # the user having to open the log stream.
            if proc.returncode not in (None, 0):
                state.crash_tail = self._logs[project_id].tail(20)
            self._procs.pop(project_id, None)
        return alive

    def state(self, project_id: str) -> RunState:
        self.is_running(project_id)
        return self._states[project_id]

    def all_states(self) -> dict[str, RunState]:
        return {pid: self.state(pid) for pid in self._states}

    def desired_running(self) -> set[str]:
        """Project IDs the user wants up — the self-heal candidate set."""
        with self._lock:
            return set(self._desired_running)

    def tail(self, project_id: str, n: int = 100) -> list[str]:
        return self._logs[project_id].tail(n)

    def _threshold_minutes(self, project: Project) -> float:
        if project.idle_shutdown_min is not None:
            return float(project.idle_shutdown_min)
        return float(self.cfg.defaults.idle_shutdown_min)

    def _idle_watcher_loop(self) -> None:
        while not self._idle_stop_event.is_set():
            try:
                self._check_idle_and_collect_targets()
            except Exception:
                pass
            self._idle_stop_event.wait(self._idle_check_interval_s)

    def _check_idle_and_collect_targets(self) -> None:
        now = time.time()
        to_stop: list[tuple[str, float]] = []
        with self._lock:
            for project in self.cfg.projects:
                if not self.is_running(project.id):
                    continue
                threshold_min = self._threshold_minutes(project)
                if threshold_min <= 0:
                    continue
                state = self._states[project.id]
                if state.last_activity_at is None:
                    continue
                idle_s = now - state.last_activity_at
                if idle_s > threshold_min * 60:
                    to_stop.append((project.id, threshold_min))

        # Stop outside the lock — stop() blocks on proc.wait() up to 10s and
        # would otherwise serialize all start/stop calls behind the watcher.
        for pid, threshold in to_stop:
            self._logs[pid].write(
                f"[wall] auto-stopping (idle > {threshold:g} min)"
            )
            try:
                self.stop(pid)
            except Exception:
                pass

    def shutdown(self) -> None:
        self._idle_stop_event.set()
        for pid in list(self._procs.keys()):
            try:
                self.stop(pid)
            except Exception:
                pass
        if self._idle_thread.is_alive():
            self._idle_thread.join(timeout=2.0)
        for log in self._logs.values():
            log.close()
        self._job.close()
