"""ProjectWall ops cron — run from Windows Task Scheduler every ~15 min.

Three jobs, "like real ops":

  1. Liveness  — GET the dashboard. If the wall itself is down, relaunch
                 ProjectWall.vbs and email an incident.
  2. Update    — `git fetch` then count commits behind origin/<branch>.
                 Write logs/.update_available so the dashboard can show an
                 "update available" banner; email once per new revision.
  3. Digest    — pull /api/projects; email a summary if any project is
                 down or errored (deduped per day).

Standalone: only depends on stdlib + project_wall.alerts/version.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from project_wall.alerts import EmailAlerter  # noqa: E402
from project_wall.version import UPDATE_FLAG_NAME  # noqa: E402

WALL_BASE = "http://127.0.0.1:8765"
LOG_DIR = ROOT / "logs"
CRON_LOG = LOG_DIR / "wall_cron.log"


def _log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CRON_LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _get_json(path: str, timeout: float = 5.0):
    try:
        with urllib.request.urlopen(WALL_BASE + path, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), *args],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def check_liveness(alerter: EmailAlerter) -> bool:
    if _get_json("/api/version") is not None or _get_json("/") is not None:
        _log("liveness: wall UP")
        return True
    _log("liveness: wall DOWN — relaunching")
    vbs = ROOT / "ProjectWall.vbs"
    try:
        subprocess.Popen(
            ["wscript.exe", str(vbs)], cwd=str(ROOT),
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
        )
    except OSError as exc:
        _log(f"liveness: relaunch failed: {exc}")
    alerter.send(
        subject="ProjectWall was DOWN — auto-restarted",
        body=f"The dashboard at {WALL_BASE} was unreachable. "
             f"ProjectWall.vbs was relaunched at {time.ctime()}.",
        dedup_key="wall_down",
    )
    return False


def check_update(alerter: EmailAlerter) -> None:
    branch = _git("rev-parse", "--abbrev-ref", "HEAD") or "master"
    if _git("fetch", "origin", branch) is None:
        _log("update: git fetch failed/skipped")
        return
    behind_raw = _git("rev-list", "--count", f"HEAD..origin/{branch}")
    behind = int(behind_raw) if behind_raw and behind_raw.isdigit() else 0
    latest = _git("rev-parse", f"origin/{branch}")
    flag = LOG_DIR / UPDATE_FLAG_NAME
    if behind > 0:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        flag.write_text(
            json.dumps(
                {"behind_by": behind, "latest_sha": latest, "checked_at": time.time()}
            ),
            encoding="utf-8",
        )
        _log(f"update: {behind} commit(s) behind origin/{branch}")
        alerter.send(
            subject=f"Update available — {behind} commit(s) behind",
            body=f"ProjectWall is {behind} commit(s) behind origin/{branch} "
                 f"(latest {latest}). Run: git pull && restart the wall.",
            dedup_key=f"update:{latest}",
        )
    else:
        flag.unlink(missing_ok=True)
        _log(f"update: up to date with origin/{branch}")


def check_digest(alerter: EmailAlerter) -> None:
    data = _get_json("/api/projects")
    if not data:
        return
    bad = []
    for p in data.get("projects", []):
        st = p.get("state", {})
        if st.get("error") or (st.get("crash_tail") and not st.get("running")):
            bad.append(f"  {p['id']}: {st.get('error') or 'crashed'}")
    if bad:
        _log(f"digest: {len(bad)} project(s) need attention")
        alerter.send(
            subject=f"{len(bad)} project(s) need attention",
            body="Projects reporting errors or crashes:\n\n" + "\n".join(bad),
            dedup_key="digest:" + time.strftime("%Y-%m-%d"),
        )
    else:
        _log("digest: all projects healthy")


def main() -> int:
    alerter = EmailAlerter(log=_log)
    if check_liveness(alerter):
        check_digest(alerter)
    check_update(alerter)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
