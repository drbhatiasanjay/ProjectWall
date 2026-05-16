from __future__ import annotations

import json

from project_wall.version import current_revision, update_status, version_payload


def test_current_revision_has_sha() -> None:
    rev = current_revision()
    # Running inside the ProjectWall git repo, so HEAD resolves.
    assert rev["sha"] is not None
    assert rev["short_sha"] is not None
    assert len(rev["short_sha"]) == 7
    assert rev["sha"].startswith(rev["short_sha"])


def test_update_status_absent_flag(tmp_path) -> None:
    assert update_status(tmp_path) == {"update_available": False}


def test_update_status_with_flag(tmp_path) -> None:
    (tmp_path / ".update_available").write_text(
        json.dumps({"behind_by": 3, "latest_sha": "deadbeef", "checked_at": 1.0}),
        encoding="utf-8",
    )
    st = update_status(tmp_path)
    assert st["update_available"] is True
    assert st["behind_by"] == 3
    assert st["latest_sha"] == "deadbeef"


def test_update_status_zero_behind(tmp_path) -> None:
    (tmp_path / ".update_available").write_text(
        json.dumps({"behind_by": 0}), encoding="utf-8"
    )
    assert update_status(tmp_path)["update_available"] is False


def test_update_status_malformed_flag(tmp_path) -> None:
    (tmp_path / ".update_available").write_text("not json{", encoding="utf-8")
    assert update_status(tmp_path) == {"update_available": False}


def test_version_payload_merges(tmp_path) -> None:
    payload = version_payload(tmp_path)
    assert "sha" in payload
    assert payload["update_available"] is False
