from __future__ import annotations

import os
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage


class EmailAlerter:
    """Best-effort Gmail-SMTP alerter with per-key dedup.

    Config via environment (set in ProjectWall's own .env or the shell):
      WALL_ALERT_TO        recipient address (default drbhatiasanjay@gmail.com)
      WALL_SMTP_USER       Gmail address to authenticate/send as
      WALL_SMTP_PASSWORD   Gmail App Password (NOT the account password)
      WALL_SMTP_HOST       default smtp.gmail.com
      WALL_SMTP_PORT       default 587 (STARTTLS)

    Alerting is never allowed to crash the wall: every failure is swallowed
    and reported via the optional `log` callback.
    """

    def __init__(self, log=None, dedup_window_s: float = 900.0):
        self.to_addr = os.environ.get("WALL_ALERT_TO", "drbhatiasanjay@gmail.com")
        self.user = os.environ.get("WALL_SMTP_USER", "")
        self.password = os.environ.get("WALL_SMTP_PASSWORD", "")
        self.host = os.environ.get("WALL_SMTP_HOST", "smtp.gmail.com")
        self.port = int(os.environ.get("WALL_SMTP_PORT", "587"))
        self._dedup_window_s = dedup_window_s
        self._last_sent: dict[str, float] = {}
        self._lock = threading.Lock()
        self._log = log or (lambda _msg: None)

    @property
    def enabled(self) -> bool:
        return bool(self.user and self.password)

    def _should_send(self, dedup_key: str | None) -> bool:
        if dedup_key is None:
            return True
        now = time.time()
        with self._lock:
            last = self._last_sent.get(dedup_key)
            if last is not None and (now - last) < self._dedup_window_s:
                return False
            self._last_sent[dedup_key] = now
        return True

    def send(self, subject: str, body: str, dedup_key: str | None = None) -> bool:
        """Send an alert email. Returns True if dispatched, False otherwise.

        Runs the SMTP conversation on a daemon thread so a slow/blocked mail
        server can never stall the monitor loop.
        """
        if not self.enabled:
            self._log(f"[alert] email disabled (no SMTP creds) — would send: {subject}")
            return False
        if not self._should_send(dedup_key):
            self._log(f"[alert] suppressed (dedup {dedup_key}): {subject}")
            return False

        def _worker() -> None:
            try:
                msg = EmailMessage()
                msg["Subject"] = f"[ProjectWall] {subject}"
                msg["From"] = self.user
                msg["To"] = self.to_addr
                msg.set_content(body)
                ctx = ssl.create_default_context()
                with smtplib.SMTP(self.host, self.port, timeout=20) as s:
                    s.starttls(context=ctx)
                    s.login(self.user, self.password)
                    s.send_message(msg)
                self._log(f"[alert] sent: {subject}")
            except Exception as exc:  # noqa: BLE001 — alerting must never raise
                self._log(f"[alert] send failed: {exc}")

        threading.Thread(target=_worker, daemon=True, name="wall-alert").start()
        return True
