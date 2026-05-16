from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPDATE_FLAG_NAME = ".update_available"


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def current_revision() -> dict:
    """Local HEAD: full sha, short sha, ISO-8601 commit date, branch."""
    sha = _git("rev-parse", "HEAD")
    return {
        "sha": sha,
        "short_sha": sha[:7] if sha else None,
        "committed_at": _git("log", "-1", "--format=%cI"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
    }


def update_status(log_dir: Path) -> dict:
    """Read the cron-written update flag. Absent => up to date / unknown.

    Flag file `<log_dir>/.update_available` is JSON:
      {"behind_by": int, "latest_sha": str, "checked_at": float}
    """
    flag = Path(log_dir) / UPDATE_FLAG_NAME
    if not flag.is_file():
        return {"update_available": False}
    try:
        data = json.loads(flag.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"update_available": False}
    behind = int(data.get("behind_by", 0) or 0)
    return {
        "update_available": behind > 0,
        "behind_by": behind,
        "latest_sha": data.get("latest_sha"),
        "checked_at": data.get("checked_at"),
    }


def version_payload(log_dir: Path) -> dict:
    return {**current_revision(), **update_status(log_dir)}
