"""An append-only record of everything the system did, and alerts when it matters.

The state file is a display buffer. It holds the last forty decisions, it is
rewritten in full on every cycle, and it is the only record that existed. So
the answer to "why did it buy that on Tuesday" was gone by Thursday.

This is the other kind of file: opened in append mode, never rewritten, one
JSON object per line. It survives crashes, it can be read while it is being
written, and it can be grepped by someone who has never heard of this project.

WHY LINES AND NOT A DATABASE.

A trading log is written once and read rarely, usually in a hurry, usually
after something went wrong. JSON lines can be read by a text editor on a
machine that has nothing installed. SQLite would be faster at queries nobody
runs and unreadable at the moment it matters most.

DEDUPLICATION IS THE WHOLE PROBLEM.

The live loop replays the entire history on every poll, which is what makes it
immune to state drift. It also means every cycle produces the same decisions
again. Writing them straight to the log would append the same trade sixty times
an hour. So each event carries a stable identity and the journal remembers what
it has already written.

ALERTS ARE BEST EFFORT AND NEVER FATAL.

A webhook that times out must not stop a trading loop, and a notification that
fails must not lose the log line. Everything here swallows its own errors and
returns whether it worked, because the alternative is a bot that dies because
Discord was slow.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

# Kept small on purpose. This is the set of things worth waking someone for,
# and a list that grows past it trains people to ignore all of them.
ALERT_KINDS = {"entry", "exit", "halt", "breach", "silent", "error"}

TIMEOUT = 10


def _identity(event: dict[str, Any]) -> str:
    """A stable name for an event, so a replay cannot log it twice.

    Built from what makes the event unique in the run rather than from when it
    was written: the same fill re-derived on the next poll has the same bar
    index and the same symbol, and must collapse onto the same identity.
    """
    return "|".join(str(event.get(k, "")) for k in ("kind", "symbol", "at", "index"))


@dataclass
class Journal:
    """One run's append-only log."""

    path: Path
    seen: set[str] | None = None

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        if self.seen is None:
            self.seen = self._replay_identities()

    def _replay_identities(self) -> set[str]:
        """What is already on disk, so a restart does not duplicate the history."""
        out: set[str] = set()
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        out.add(_identity(json.loads(line)))
                    except ValueError:
                        continue
        except OSError:
            pass
        return out

    def write(self, events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        """Append everything not already recorded. Returns what was new."""
        fresh = []
        for event in events:
            name = _identity(event)
            if name in self.seen:
                continue
            self.seen.add(name)
            fresh.append(event)

        if not fresh:
            return []

        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Append mode and a flush per batch. Not fsync per line: this is a log,
        # and paying a disk sync for every decision would make the loop slower
        # than the thing it is logging.
        with self.path.open("a", encoding="utf-8") as handle:
            for event in fresh:
                handle.write(json.dumps(event, separators=(",", ":")) + "\n")
            handle.flush()
        return fresh

    def tail(self, limit: int = 200) -> list[dict[str, Any]]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in lines[-limit:]:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out


def events_from_run(run, system_name: str) -> list[dict[str, Any]]:
    """Turn a run into log lines. Pure, so it can be tested without a disk."""
    out: list[dict[str, Any]] = []

    for decision in run.decisions:
        kind = {"buy": "entry", "sell": "exit", "halt": "halt"}.get(
            decision.action, "decision")
        out.append({
            "kind": kind, "system": system_name, "symbol": decision.symbol,
            "at": round(decision.time, 3), "index": "",
            "action": decision.action, "reason": decision.reason,
        })

    for stamp, symbol, reason in run.refusals:
        out.append({
            "kind": "refusal", "system": system_name, "symbol": symbol,
            "at": round(stamp, 3), "index": "", "reason": reason,
        })

    if run.breach is not None:
        out.append({
            "kind": "breach", "system": system_name, "symbol": "",
            "at": round(run.stamps[run.halted_at], 3) if run.halted_at is not None
                  and run.halted_at < len(run.stamps) else 0,
            "index": run.halted_at, "code": run.breach.code,
            "reason": run.breach.detail,
        })

    return out


# ------------------------------------------------------------------ alerts --

def notify_desktop(title: str, message: str) -> bool:
    """A Windows toast, with no dependency and no failure that matters.

    Uses PowerShell's built-in notification support rather than a package,
    because adding a dependency so the program can say "your bot stopped" is a
    poor trade. Returns False everywhere else, silently.
    """
    if os.name != "nt":
        return False

    import subprocess

    safe_title = title.replace("'", "")
    safe_message = message.replace("'", "")[:220]
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications,"
        " ContentType = WindowsRuntime] > $null;"
        "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(3);"
        f"$t.GetElementsByTagName('text')[0].AppendChild($t.CreateTextNode('{safe_title}')) > $null;"
        f"$t.GetElementsByTagName('text')[1].AppendChild($t.CreateTextNode('{safe_message}')) > $null;"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('proofmark')"
        ".Show([Windows.UI.Notifications.ToastNotification]::new($t))"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=TIMEOUT, check=False,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def notify_discord(webhook: str, title: str, message: str) -> bool:
    """Post to a Discord webhook. Returns whether it landed.

    The URL is a secret in the sense that anyone holding it can post to that
    channel, so it is never logged, never echoed back to the page, and never
    written into the state file.
    """
    if not webhook or not webhook.startswith("https://"):
        return False

    payload = json.dumps({
        "embeds": [{
            "title": title[:250],
            "description": message[:3900],
            "color": 0xD9A93C,
        }]
    }).encode("utf-8")

    request = urllib.request.Request(
        webhook, data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "proofmark/0.2"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        # Swallowed on purpose. A slow webhook must not stop a trading loop.
        return False


def announce(events: Iterable[dict[str, Any]], *, webhook: str = "",
             desktop: bool = True) -> int:
    """Send the events worth interrupting someone for. Returns how many went out."""
    sent = 0
    for event in events:
        if event.get("kind") not in ALERT_KINDS:
            continue
        title = _headline(event)
        body = str(event.get("reason") or "")
        if desktop:
            notify_desktop(title, body)
        if webhook:
            notify_discord(webhook, title, body)
        sent += 1
    return sent


def _headline(event: dict[str, Any]) -> str:
    kind = event.get("kind")
    symbol = event.get("symbol") or ""
    if kind == "entry":
        return f"Opened {symbol}"
    if kind == "exit":
        return f"Closed {symbol}"
    if kind in ("halt", "breach"):
        return "Halted"
    if kind == "silent":
        return "No heartbeat"
    return f"proofmark: {kind}"


def digest(run, system_name: str, *, morning: bool) -> tuple[str, str]:
    """The two daily messages: what is open, and how it went.

    Deliberately different. A morning message that reports yesterday's return
    is a scoreboard nobody can act on, and an evening message listing open
    positions is a to-do list at the wrong hour.
    """
    account = run.portfolio
    total = run.total_return
    gap = total - run.benchmark_return

    if morning:
        title = f"{system_name}: what is open"
        if account and account.holdings:
            lines = [
                f"{s}: {h.quantity:.4f} from {h.entry:,.2f}"
                + (f", stop {h.stop:,.2f}" if h.stop else ", no stop")
                for s, h in account.holdings.items()
            ]
        else:
            lines = ["Nothing open. The rules are waiting."]
        lines.append("")
        lines.append(f"Account {run.equity[-1]:,.2f} if there is a curve yet."
                     if run.equity else "No equity curve yet.")
        return title, "\n".join(lines)

    title = f"{system_name}: how today went"
    lines = [
        f"Account {run.equity[-1]:,.2f}" if run.equity else "No equity curve yet.",
        f"Return {total:+.2%}, holding {run.benchmark_return:+.2%}, difference {gap:+.2%}",
        f"{len(account.trades) if account else 0} closed trades, "
        f"{len(account.holdings) if account else 0} still open",
    ]
    if run.breach is not None:
        lines.append(f"HALTED: {run.breach.detail}")
    if gap < 0:
        lines.append("Behind buying and holding over this run.")
    return title, "\n".join(lines)
