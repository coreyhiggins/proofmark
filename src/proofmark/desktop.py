"""A real window, not a browser tab.

Opening someone's default browser at a localhost port is the tell that a
"desktop app" is a script wearing a coat. You get a URL bar, a tab strip,
their bookmarks, and whatever else they had open, none of which belongs to
this program.

So the same local server runs on a background thread and a native window
points at it. On Windows that window is Edge WebView2, which ships with the
operating system, so this is a thin binding rather than a bundled browser
engine.

Both routes stay available on purpose. ``proofmark app`` is the window,
``proofmark gui`` serves the page for anyone who would rather use their own
browser or reach it over an SSH tunnel from a server.
"""

from __future__ import annotations

import os
import socket
import threading
import time

WIDTH, HEIGHT = 1080, 860
MIN_WIDTH, MIN_HEIGHT = 720, 620

# Matches the page's dark background, because a white flash before first paint
# is the cheapest possible way to look unfinished.
BACKGROUND = "#12100E"


def free_port(preferred: int = 8765) -> int:
    """Take the usual port, or any free one.

    Refusing to start because something else holds 8765 is not an acceptable
    outcome for a program someone double-clicked. They have no way to diagnose
    it and no reason to care.
    """
    for port in (preferred, 8766, 8767, 8768):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def start_server(port: int, state_path: str | None = None, timeout: float = 10.0) -> None:
    """Run the server on a daemon thread and wait until it accepts.

    Showing a window at a socket that is not listening yet produces a
    connection error on a program that did nothing wrong.
    """
    from .gui import serve

    threading.Thread(
        target=lambda: serve(port=port, open_browser=False, state_path=state_path),
        daemon=True,
    ).start()

    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise RuntimeError("the local server did not start")


def run_window(state_path: str | None = None, port: int | None = None) -> int:
    """Open proofmark in its own window. Returns a process exit code.

    Falls back to the standard state path when given none. The packaged .exe is
    launched by double-click and so never receives arguments; without this it
    would open with a live view permanently unable to start anything, which is
    every Windows user's first impression of it.
    """
    if state_path is None:
        from .cli import default_state_path

        state_path = str(default_state_path())

    port = port or free_port()
    url = f"http://127.0.0.1:{port}/"

    try:
        start_server(port, state_path=state_path)
    except RuntimeError as err:
        print(f"Could not start: {err}")
        return 1

    # A build server has no display, so the release job needs a way to prove
    # the binary starts and serves without asking it to draw a window. This is
    # that switch, and it is the same code path either way up to this line.
    if os.environ.get("PROOFMARK_NO_WINDOW"):
        print(f"proofmark serving at {url} (window suppressed)")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        return 0

    try:
        import webview
    except ImportError:
        print("proofmark")
        print()
        print("  The window needs one extra piece that is not installed:")
        print()
        print("      pip install 'proofmark[desktop]'")
        print()
        print(f"  Opening in your browser instead: {url}")
        print("  Press Ctrl+C to stop.")
        import webbrowser

        webbrowser.open(url)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            print()
        return 0

    webview.create_window(
        "proofmark", url,
        width=WIDTH, height=HEIGHT,
        min_size=(MIN_WIDTH, MIN_HEIGHT),
        background_color=BACKGROUND,
    )

    try:
        webview.start()
    except Exception as err:  # noqa: BLE001
        # A frozen app has nowhere to print a traceback anyone will read, and a
        # window that simply vanishes tells them nothing at all.
        print(f"Something went wrong opening the window: {err}")
        print(f"You can still use it in a browser: proofmark gui")
        return 1
    return 0
