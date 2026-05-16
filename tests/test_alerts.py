from __future__ import annotations

from project_wall.alerts import EmailAlerter


def test_disabled_without_credentials(monkeypatch) -> None:
    monkeypatch.delenv("WALL_SMTP_USER", raising=False)
    monkeypatch.delenv("WALL_SMTP_PASSWORD", raising=False)
    a = EmailAlerter()
    assert a.enabled is False
    # send() is a no-op (returns False) when disabled — never raises
    assert a.send("subject", "body") is False


def test_dedup_suppresses_repeat_within_window() -> None:
    a = EmailAlerter(dedup_window_s=1000)
    a.user, a.password = "u@gmail.com", "app-pw"  # mark enabled
    assert a.enabled is True
    assert a.send("first", "b", dedup_key="k1") is True
    # same key within window -> suppressed
    assert a.send("again", "b", dedup_key="k1") is False
    # different key -> allowed
    assert a.send("other", "b", dedup_key="k2") is True
    # no key -> never deduped
    assert a.send("nokey", "b") is True
    assert a.send("nokey", "b") is True


def test_dedup_window_zero_never_suppresses() -> None:
    a = EmailAlerter(dedup_window_s=0)
    a.user, a.password = "u@gmail.com", "app-pw"
    assert a.send("s", "b", dedup_key="k") is True
    assert a.send("s", "b", dedup_key="k") is True
