"""The double-click entry point.

A frozen build of this is what someone installs when they do not want a
terminal at all. It starts the local server, opens their browser, and stays
running until they close the window it printed into.

Why this file exists separately from ``cli.py``: a frozen binary has no
argument parser in front of it, no shell to report an exception into, and no
obvious way to stop. All three need handling, and none of them are the CLI's
problem.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
import webbrowser


def _free_port(preferred: int = 8765) -> int:
    """Take the usual port, or any free one.

    Failing to start because something else holds 8765 is not an acceptable
    outcome for a double-click app. The person who opened it has no way to
    diagnose that and no reason to care.
    """
    for port in (preferred, 8766, 8767, 8768):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def main() -> int:
    from proofmark.gui import serve

    port = _free_port()
    url = f"http://127.0.0.1:{port}/"

    print("proofmark")
    print()
    print(f"  Opening {url} in your browser.")
    print("  Everything stays on this machine. Nothing is uploaded.")
    print()
    print("  Close this window when you are finished.")
    print()

    # Open the browser slightly after the server is listening, otherwise the
    # first request can land before the socket is bound and the user sees a
    # connection error on a tool that did nothing wrong.
    threading.Thread(
        target=lambda: (time.sleep(0.6), webbrowser.open(url)),
        daemon=True,
    ).start()

    try:
        serve(port=port, open_browser=False)
    except OSError as err:
        print(f"  Could not start: {err}")
        print()
        input("  Press Enter to close.")
        return 1
    except Exception as err:  # noqa: BLE001
        # A frozen app has nowhere to print a traceback that anyone will read,
        # and a window that vanishes tells them nothing at all.
        print(f"  Something went wrong: {err}")
        print()
        input("  Press Enter to close.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
