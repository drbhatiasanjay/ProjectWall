from __future__ import annotations

import os
import signal
import webbrowser
from threading import Thread

try:
    import pystray
    from PIL import Image, ImageDraw

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


def _make_icon() -> "Image.Image":
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Brick-style icon in ProjectWall purple
    fill = "#5865F2"
    border = "#4752C4"
    draw.rectangle([2, 2, 62, 62], fill=fill, outline=border, width=2)
    # Horizontal mortar lines
    for y in (22, 42):
        draw.line([2, y, 62, y], fill=border, width=2)
    # Vertical mortar — offset per row like real brickwork
    draw.line([32, 2, 32, 22], fill=border, width=2)
    draw.line([16, 22, 16, 42], fill=border, width=2)
    draw.line([48, 22, 48, 42], fill=border, width=2)
    draw.line([32, 42, 32, 62], fill=border, width=2)
    return img


def _quit_handler(icon: "pystray.Icon") -> None:
    icon.stop()
    # Send SIGINT to the main process so uvicorn shuts down cleanly.
    os.kill(os.getpid(), signal.CTRL_C_EVENT if os.name == "nt" else signal.SIGINT)  # type: ignore[attr-defined]


def run_tray(host: str, port: int) -> None:
    """Run the system tray icon. Blocks until the icon is stopped."""
    if not _AVAILABLE:
        return

    url = f"http://{host}:{port}/"

    menu = pystray.Menu(
        pystray.MenuItem("Open Dashboard", lambda icon, item: webbrowser.open(url), default=True),
        pystray.MenuItem("Quit ProjectWall", lambda icon, item: _quit_handler(icon)),
    )
    icon = pystray.Icon("ProjectWall", _make_icon(), "ProjectWall", menu)
    icon.run()


def start_tray_thread(host: str, port: int) -> "Thread | None":
    """Start the tray icon in a background daemon thread. Returns None if pystray is absent."""
    if not _AVAILABLE:
        return None
    t = Thread(target=run_tray, args=(host, port), daemon=True, name="wall-tray")
    t.start()
    return t
