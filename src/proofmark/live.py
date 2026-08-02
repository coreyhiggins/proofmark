"""Watching a running strategy, without becoming the strategy.

proofmark is the verification layer, not the trading engine. So the live view
reads a **state file** that your bot writes, rather than connecting to an
exchange itself. Your bot keeps its own connections, its own keys and its own
logic; it writes a small JSON file whenever something happens, and this reads
it.

That boundary buys three things:

- Your existing system does not have to be rewritten to be watched. One call
  to :func:`write_state` at the end of each cycle is the whole integration.
- proofmark never holds an API key, so a bug here cannot place an order.
- There is no long-lived connection to drop, reconnect, or reconcile. A file
  either has fresh contents or it does not.

WHAT THE LIVE VIEW IS FOR, AND WHAT IT IS NOT FOR.

It is for noticing that something has broken: the bot stopped writing, the
drawdown limit is close, a position has no stop attached, or the live results
have drifted into territory the guards call impossible.

It is not for deciding trades. A rules-based system exists precisely so that a
person watching a screen does not override it at the worst moment, and a live
dashboard is the most effective device ever invented for tempting them to. The
page is built to be glanced at, not stared at, and it deliberately shows no
prices you could trade on.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# A state file older than this is treated as a dead bot rather than a quiet
# one. Most schedules are minutes; ten of them without a heartbeat means
# something stopped.
STALE_AFTER_SECONDS = 600

# Bounded so a long-running bot cannot grow the file without limit and so the
# page stays glanceable.
MAX_DECISIONS = 40
MAX_EQUITY_POINTS = 5000


@dataclass
class Position:
    symbol: str
    quantity: float
    entry: float
    current: float
    stop: float | None = None
    target: float | None = None

    @property
    def unrealised(self) -> float:
        return (self.current - self.entry) * self.quantity

    @property
    def protected(self) -> bool:
        """Whether a stop exists at all.

        An open position with no stop is the single most useful thing a live
        view can point at, because it is invisible until the day it is not.
        """
        return self.stop is not None


@dataclass
class Decision:
    """One thing the rules decided, and why.

    Rejections matter more than entries here. A bot that took no trades today
    is indistinguishable from a broken bot unless it records why it declined.
    """

    time: float
    symbol: str
    action: str
    reason: str


@dataclass
class State:
    mode: str = "paper"
    equity: list[float] = field(default_factory=list)
    positions: list[Position] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    halted: bool = False
    halt_reason: str = ""
    updated: float = field(default_factory=time.time)

    @property
    def age(self) -> float:
        return max(0.0, time.time() - self.updated)

    @property
    def stale(self) -> bool:
        return self.age > STALE_AFTER_SECONDS

    @property
    def unprotected(self) -> list[Position]:
        return [p for p in self.positions if not p.protected]


def write_state(
    path: str | Path,
    *,
    mode: str = "paper",
    equity: list[float] | None = None,
    positions: list[Position] | None = None,
    decisions: list[Decision] | None = None,
    halted: bool = False,
    halt_reason: str = "",
) -> None:
    """Write the state file. Call this at the end of every cycle.

    Written atomically: to a temporary file in the same directory, then
    renamed over the target. A reader polling the file can otherwise catch it
    half-written and show a page of nonsense, and on a live view "nonsense"
    and "something is wrong" look identical.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "mode": mode,
        "equity": (equity or [])[-MAX_EQUITY_POINTS:],
        "positions": [asdict(p) for p in (positions or [])],
        "decisions": [asdict(d) for d in (decisions or [])][-MAX_DECISIONS:],
        "halted": halted,
        "halt_reason": halt_reason,
        "updated": time.time(),
    }

    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_state(path: str | Path) -> State | None:
    """Read the state file, or ``None`` if it is missing or unreadable.

    A malformed file returns ``None`` rather than raising. The bot writing it
    is the thing that matters, and a viewer that crashes because a write was
    interrupted is a viewer that reports the wrong problem.
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None

    try:
        return State(
            mode=str(raw.get("mode", "paper")),
            equity=[float(v) for v in raw.get("equity") or []],
            positions=[
                Position(
                    symbol=str(p.get("symbol", "?")),
                    quantity=float(p.get("quantity", 0)),
                    entry=float(p.get("entry", 0)),
                    current=float(p.get("current", 0)),
                    stop=None if p.get("stop") is None else float(p["stop"]),
                    target=None if p.get("target") is None else float(p["target"]),
                )
                for p in raw.get("positions") or []
            ],
            decisions=[
                Decision(
                    time=float(d.get("time", 0)),
                    symbol=str(d.get("symbol", "")),
                    action=str(d.get("action", "")),
                    reason=str(d.get("reason", "")),
                )
                for d in raw.get("decisions") or []
            ],
            halted=bool(raw.get("halted", False)),
            halt_reason=str(raw.get("halt_reason", "")),
            updated=float(raw.get("updated", 0)),
        )
    except (TypeError, ValueError):
        return None


def alerts(state: State) -> list[tuple[str, str]]:
    """Things worth interrupting someone for, most urgent first.

    Deliberately short. A live view that raises five concerns at once trains
    people to dismiss all five, and the one that mattered goes with them.
    """
    out: list[tuple[str, str]] = []

    if state.halted:
        out.append((
            "halted",
            state.halt_reason or "The bot has stopped taking new trades.",
        ))

    if state.stale:
        minutes = int(state.age // 60)
        out.append((
            "silent",
            f"No update for {minutes} minutes. The bot may have stopped, and "
            "any open position is running without anything watching it.",
        ))

    for position in state.unprotected:
        out.append((
            "unprotected",
            f"{position.symbol} is open with no stop attached. If this process "
            "dies, nothing closes it.",
        ))

    if state.mode == "live":
        out.append((
            "live-money",
            "This is trading real money, not paper.",
        ))

    return out
