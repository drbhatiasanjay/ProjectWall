"""Browser-level E2E tests using Playwright.

Drives the actual dashboard UI in Chromium: verifies the page renders,
cards populate, Start/Stop buttons wire to the API and flip card state,
Logs button shows captured output, and no JS console errors surface.

Requires:  pip install -e .[dev]  &&  playwright install chromium
"""
from __future__ import annotations

import subprocess

from playwright.sync_api import Page, expect

from tests.conftest import wait_for_port, wait_for_port_free


def test_dashboard_renders(
    page: Page, wall_server: tuple[str, subprocess.Popen]
) -> None:
    base, _ = wall_server
    page.goto(f"{base}/")
    expect(page.locator(".brand")).to_have_text("🧱 ProjectWall")
    expect(page.locator(".card[data-id='dummy']")).to_be_visible()
    expect(page.locator(".card[data-id='dummy'] h2")).to_have_text("Dummy Server")


def test_idle_state_shown_initially(
    page: Page, wall_server: tuple[str, subprocess.Popen]
) -> None:
    base, _ = wall_server
    page.goto(f"{base}/")
    # Wait for first refresh() to complete — summary populates after API call.
    expect(page.locator("#summary")).to_contain_text("0 running")
    expect(
        page.locator(".card[data-id='dummy'] .dot")
    ).to_have_attribute("data-state", "idle")


def test_start_button_flips_card_to_running(
    page: Page, wall_server: tuple[str, subprocess.Popen], dummy_port: int
) -> None:
    base, _ = wall_server
    page.goto(f"{base}/")
    card = page.locator(".card[data-id='dummy']")
    card.locator("button.start").click()
    expect(card.locator(".dot")).to_have_attribute("data-state", "running", timeout=8000)
    expect(card.locator(".state-label")).to_contain_text("pid", timeout=8000)
    expect(page.locator("#summary")).to_contain_text("1 running")
    assert wait_for_port("127.0.0.1", dummy_port, timeout_s=8.0)


def test_stop_button_flips_card_to_stopped(
    page: Page, wall_server: tuple[str, subprocess.Popen], dummy_port: int
) -> None:
    base, _ = wall_server
    page.goto(f"{base}/")
    card = page.locator(".card[data-id='dummy']")
    card.locator("button.start").click()
    expect(card.locator(".dot")).to_have_attribute("data-state", "running", timeout=8000)
    card.locator("button.stop").click()
    expect(card.locator(".dot")).to_have_attribute("data-state", "stopped", timeout=8000)
    expect(card.locator(".state-label")).to_contain_text("exited", timeout=8000)
    assert wait_for_port_free("127.0.0.1", dummy_port, timeout_s=8.0)


def test_logs_button_reveals_output(
    page: Page, wall_server: tuple[str, subprocess.Popen]
) -> None:
    base, _ = wall_server
    page.goto(f"{base}/")
    card = page.locator(".card[data-id='dummy']")
    card.locator("button.start").click()
    expect(card.locator(".dot")).to_have_attribute("data-state", "running", timeout=8000)
    card.locator("button.logs").click()
    logview = card.locator(".logview")
    expect(logview).to_be_visible()
    expect(logview).to_contain_text("[wall]")


def test_health_probe_reflected_in_ui(
    page: Page, wall_server: tuple[str, subprocess.Popen], dummy_port: int
) -> None:
    base, _ = wall_server
    page.goto(f"{base}/")
    card = page.locator(".card[data-id='dummy']")
    card.locator("button.start").click()
    assert wait_for_port("127.0.0.1", dummy_port, timeout_s=8.0)
    # Health probe runs on a 4s auto-refresh; wait up to 10s for UI to pick it up.
    expect(card.locator(".health")).to_have_attribute("data-health", "ok", timeout=10000)


def test_no_console_errors_on_load(
    page: Page, wall_server: tuple[str, subprocess.Popen]
) -> None:
    base, _ = wall_server
    errors: list[str] = []
    page.on(
        "console",
        lambda msg: errors.append(msg.text) if msg.type == "error" else None,
    )
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(f"{base}/")
    expect(page.locator("#summary")).to_contain_text("configured")
    page.wait_for_timeout(500)
    assert errors == [], f"console errors detected: {errors}"


def test_auto_refresh_updates_summary(
    page: Page, wall_server: tuple[str, subprocess.Popen]
) -> None:
    """The dashboard polls every 4s — after clicking Start via the API
    directly (not the button), the polled summary should still flip."""
    base, _ = wall_server
    page.goto(f"{base}/")
    expect(page.locator("#summary")).to_contain_text("0 running")
    # Fire Start via fetch in the page, bypassing the button, to prove the
    # polling loop (not the click handler) reads the new state.
    page.evaluate(
        "fetch('/api/projects/dummy/start', {method: 'POST'})"
    )
    expect(page.locator("#summary")).to_contain_text("1 running", timeout=8000)
