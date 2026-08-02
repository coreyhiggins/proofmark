"""Entry point for the frozen double-click build.

The window logic lives in ``proofmark.desktop`` so the packaged app and
``proofmark app`` cannot drift apart. This file exists only because PyInstaller
wants a script, and because a frozen binary has nowhere to print a traceback
that anyone will read.
"""

from __future__ import annotations

import sys


def main() -> int:
    try:
        from proofmark.desktop import run_window
    except Exception as err:  # noqa: BLE001
        print(f"proofmark could not start: {err}")
        input("Press Enter to close.")
        return 1

    try:
        return run_window()
    except KeyboardInterrupt:
        return 0
    except Exception as err:  # noqa: BLE001
        print(f"Something went wrong: {err}")
        print()
        input("Press Enter to close.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
