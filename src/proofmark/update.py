"""Checking for and installing a newer version.

Free and self-contained: the public GitHub releases API, one unauthenticated
request, and the standard library. No update service, no telemetry, no account.

Nothing here runs on its own. A tool that phones home on startup is a tool
that decided for you what your machine talks to, so this only happens when
somebody types ``proofmark update``.

REPLACING A RUNNING PROGRAM ON WINDOWS.

Windows will not let you overwrite an executable that is currently running.
The standard move is to rename the running file, which Windows does allow,
write the new one into the freed name, and clean up the leftover on the next
start. That is what happens below, and it is why an update asks you to restart
rather than swapping itself out underneath you.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__

REPO = "coreyhiggins/proofmark"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
TIMEOUT = 15


def _frozen() -> bool:
    """True when running as the packaged single-file build."""
    return getattr(sys, "frozen", False)


def _asset_pattern() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _parse(tag: str) -> tuple[int, ...]:
    """Turn 'v1.12.0' into (1, 12, 0) so 1.12 sorts above 1.9."""
    cleaned = tag.lstrip("vV").split("-")[0]
    parts = []
    for chunk in cleaned.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            break
    return tuple(parts) or (0,)


def latest_release() -> dict | None:
    """Ask GitHub what the current release is. ``None`` if it cannot be reached."""
    request = urllib.request.Request(API, headers={"User-Agent": "proofmark"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def _cleanup_previous() -> None:
    """Delete the file left behind by the last update, if it is still there."""
    if not _frozen():
        return
    stale = Path(sys.executable).with_suffix(".old")
    try:
        stale.unlink(missing_ok=True)
    except OSError:
        # Still locked, so leave it. It is harmless and the next run retries.
        pass


def run_update(check_only: bool = False) -> int:
    _cleanup_previous()

    print(f"\n  installed: {__version__}")

    release = latest_release()
    if release is None:
        print("  Could not reach GitHub. Check your connection and try again.\n")
        return 1

    tag = str(release.get("tag_name") or "")
    print(f"  latest:    {tag.lstrip('vV') or 'unknown'}")

    if _parse(tag) <= _parse(__version__):
        print("\n  You are up to date.\n")
        return 0

    print(f"\n  {tag} is available.")

    if check_only:
        print("  Run `proofmark update` to install it.\n")
        return 0

    # A pip install is pip's to manage. Overwriting site-packages behind pip's
    # back leaves it reporting a version that is not on disk.
    if not _frozen():
        print()
        print("  This copy was installed with pip, so pip should update it:")
        print()
        print('      pip install --upgrade "proofmark @ git+https://github.com/coreyhiggins/proofmark"')
        print()
        return 0

    want = _asset_pattern()
    asset = next(
        (a for a in release.get("assets") or [] if want in str(a.get("name", "")).lower()),
        None,
    )
    if asset is None:
        print(f"  That release has no build for {want}.")
        print(f"  Have a look at https://github.com/{REPO}/releases/latest\n")
        return 1

    current = Path(sys.executable)
    size_mb = round(int(asset.get("size", 0)) / 1_048_576, 1)
    print(f"  downloading {size_mb} MB")

    # Download to a temporary file first. A half-written executable that
    # someone then runs is a worse outcome than a failed update.
    fd, temp = tempfile.mkstemp(dir=str(current.parent), suffix=".new")
    os.close(fd)
    try:
        request = urllib.request.Request(
            asset["browser_download_url"], headers={"User-Agent": "proofmark"}
        )
        with urllib.request.urlopen(request, timeout=120) as response, open(temp, "wb") as out:
            shutil.copyfileobj(response, out)
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        Path(temp).unlink(missing_ok=True)
        print(f"  Download failed: {err}\n")
        return 1

    backup = current.with_suffix(".old")
    try:
        backup.unlink(missing_ok=True)
        # Windows allows renaming a running executable but not overwriting it.
        os.replace(current, backup)
        os.replace(temp, current)
        if not sys.platform.startswith("win"):
            os.chmod(current, 0o755)
    except OSError as err:
        Path(temp).unlink(missing_ok=True)
        # Put the original back if it moved but the replacement did not land.
        if backup.exists() and not current.exists():
            os.replace(backup, current)
        print(f"  Could not replace the program: {err}")
        print("  Close proofmark and try again, or download it by hand from")
        print(f"      https://github.com/{REPO}/releases/latest\n")
        return 1

    print(f"\n  Updated to {tag}. Close this window and start proofmark again.\n")
    return 0
