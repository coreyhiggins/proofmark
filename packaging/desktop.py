"""Entry point for the frozen double-click build.

The window logic lives in ``proofmark.desktop`` so the packaged app and
``proofmark app`` cannot drift apart. This file exists because PyInstaller
wants a script, and because a windowed build has nowhere to print.

NO CONSOLE. The build is ``--windowed``, so there is no black terminal sitting
behind the app. That console was visible in the first build and it is the
clearest possible sign that a program is a script wearing a coat.

The cost of removing it is that ``print`` goes nowhere and a traceback would
vanish silently. So anything that escapes is written to a log file beside the
executable and shown in a message box, which is the one thing a person can act
on when a program refuses to open.
"""

from __future__ import annotations

import datetime
import sys
import traceback
from pathlib import Path


def _log_path() -> Path:
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    return base / "proofmark-error.log"


def _report(message: str) -> None:
    """Write the failure down, then say so in a way a person will see."""
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    log = _log_path()
    try:
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"\n----- {stamp}\n{message}\n")
    except OSError:
        log = None  # type: ignore[assignment]

    detail = f"proofmark could not start.\n\n{message}"
    if log:
        detail += f"\n\nWritten to:\n{log}"

    try:
        import ctypes

        # 0x10 is MB_ICONERROR. A window that simply never appears tells the
        # person nothing at all.
        ctypes.windll.user32.MessageBoxW(None, detail, "proofmark", 0x10)
    except Exception:  # noqa: BLE001
        print(detail)


def main() -> int:
    try:
        from proofmark.desktop import run_window

        return run_window()
    except KeyboardInterrupt:
        return 0
    except Exception:  # noqa: BLE001
        _report(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
