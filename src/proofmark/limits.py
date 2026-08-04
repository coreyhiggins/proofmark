"""The rules that stop a bot before it finishes destroying an account.

``State.halted`` has existed since the live view was written. The page renders
it. Nothing has ever set it. This file is what sets it.

WHY A HALT CANNOT BE DERIVED STATE.

``replay()`` recomputes the entire run from scratch on every poll. That is a
deliberate and good property: there is no incremental position state to drift
out of sync with a feed that can revise or repeat a candle.

It collides badly with halting. If a halt were computed from the equity curve,
then a limit breached on Tuesday would be recomputed and re-breached on every
poll forever, and clearing it would do nothing at all. The person would press
resume, watch it halt again immediately, and reasonably conclude the button is
broken.

So a halt is a **fact on disk** with a cleared-at timestamp, and limit
evaluation only considers activity after that timestamp.

HALTED MEANS NO NEW ENTRIES. EXITS ALWAYS RUN.

A halt that blocks everything traps you in the position that caused it, which
is the exact opposite of what a risk limit is for.

WHY THE EXPOSURE RULE USES GROUPS AND NOT A CORRELATION MATRIX.

The reference design says: with two risk-on positions already open, do not open
a third. The obvious implementation is a rolling correlation estimate, and it
is a trap. Correlations computed over a lookback are unstable, they converge on
1.0 in exactly the crash where the rule matters most, and the resulting cap
moves for reasons nobody can explain after the fact.

A declared group map is boring, legible, and correct for the thing being
prevented: an equity index, another equity index and a third risk asset are one
bet wearing three tickers, and you knew that before the data did.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from .portfolio import Portfolio, Trade

# Symbols that rise and fall together. Not exhaustive and not meant to be: the
# point is that a person can read it and disagree with it.
DEFAULT_GROUPS: dict[str, str] = {
    "SPY": "equity-index", "QQQ": "equity-index", "IWM": "equity-index",
    "VOO": "equity-index", "DIA": "equity-index",
    "GLD": "commodity", "SLV": "commodity", "USO": "commodity", "UNG": "commodity",
    "BTC/USDT": "crypto", "BTC/USD": "crypto", "ETH/USDT": "crypto", "ETH/USD": "crypto",
}


@dataclass(frozen=True)
class Limits:
    """Every limit is a fraction of equity, and every one can be switched off."""

    daily_loss: float | None = 0.03
    max_drawdown: float | None = 0.15
    consecutive_losses: int | None = 5

    # Concurrent positions allowed within one correlation group, and overall.
    max_per_group: int | None = 2
    max_positions: int | None = 5
    max_exposure: float | None = 0.90

    # "Today" is not obvious on a market that never closes, and a loss limit
    # that resets at the wrong hour is worse than none: it hands you a fresh
    # budget in the middle of the session that was going badly.
    session_offset_hours: float = 0.0

    groups: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_GROUPS))

    def group_of(self, symbol: str) -> str:
        return self.groups.get(symbol, symbol)


@dataclass
class Breach:
    code: str
    detail: str


def session_start(now: float, offset_hours: float) -> float:
    """The most recent session boundary, as an epoch timestamp."""
    shifted = now - offset_hours * 3600
    day = shifted - (shifted % 86400)
    return day + offset_hours * 3600


def check_limits(
    portfolio: Portfolio,
    equity_curve: Sequence[float],
    limits: Limits,
    *,
    since_index: int = 0,
    session_equity_open: float | None = None,
) -> Breach | None:
    """The first limit breached since ``since_index``, or None.

    ``since_index`` is the bar the halt was last cleared at, and EVERY limit is
    evaluated from there rather than from the start of the run. A bar index and
    not a timestamp, because that is what the trades and the equity curve are
    indexed by, and matching a wall clock against a bar index is a whole
    category of off-by-a-session bugs.

    Windowing all three limits matters and is easy to get half right. Resetting
    only the losing streak leaves the drawdown limit measuring from the original
    high water mark, so the system re-halts on the same breach the moment it
    resumes and the resume button looks broken.
    """
    window = equity_curve[since_index:] if since_index else list(equity_curve)

    if limits.max_drawdown is not None and len(window) >= 2:
        peak = window[0]
        worst = 0.0
        for value in window:
            peak = max(peak, value)
            if peak > 0:
                worst = min(worst, (value - peak) / peak)
        if worst <= -abs(limits.max_drawdown):
            return Breach(
                "max-drawdown",
                f"down {abs(worst):.1%} from the high water mark, against a "
                f"{limits.max_drawdown:.1%} limit",
            )

    if (limits.daily_loss is not None and session_equity_open
            and window and session_equity_open > 0):
        change = window[-1] / session_equity_open - 1
        if change <= -abs(limits.daily_loss):
            return Breach(
                "daily-loss",
                f"down {abs(change):.1%} since the session opened, against a "
                f"{limits.daily_loss:.1%} limit",
            )

    if limits.consecutive_losses is not None:
        streak = _streak(portfolio.trades, since_index)
        if streak >= limits.consecutive_losses:
            return Breach(
                "losing-streak",
                f"{streak} losing trades in a row, against a limit of "
                f"{limits.consecutive_losses}",
            )

    return None


def _streak(trades: Sequence[Trade], since_index: int) -> int:
    """Losses at the end of the list, counting only trades closed since the clear."""
    streak = 0
    for trade in reversed(trades):
        if trade.closed_at < since_index:
            break
        if trade.won:
            break
        streak += 1
    return streak


def blocked_reason(
    symbol: str,
    portfolio: Portfolio,
    prices: Mapping[str, float],
    limits: Limits,
) -> str | None:
    """Why this specific entry is not allowed right now, if it is not.

    Separate from :func:`check_limits` on purpose. These are refusals of one
    trade, not a halt of the whole system, and conflating the two would mean a
    crowded sector shut the bot down.
    """
    if limits.max_positions is not None and len(portfolio.holdings) >= limits.max_positions:
        return f"already holding {len(portfolio.holdings)} positions, the limit"

    if limits.max_per_group is not None:
        group = limits.group_of(symbol)
        held = sum(1 for s in portfolio.holdings if limits.group_of(s) == group)
        if held >= limits.max_per_group:
            others = ", ".join(s for s in portfolio.holdings if limits.group_of(s) == group)
            return (
                f"{held} {group} positions already open ({others}). These move "
                "together, so a third is one bet wearing three tickers"
            )

    if limits.max_exposure is not None and portfolio.exposure(prices) >= limits.max_exposure:
        return f"{portfolio.exposure(prices):.0%} of the account is already at market"

    return None


# --------------------------------------------------------------- the switch --

@dataclass
class Halt:
    reason: str = ""
    code: str = ""
    at: float = 0.0
    manual: bool = False


class HaltFile:
    """The kill switch, as a file rather than a button.

    A file gives three things a button in a window cannot: it survives a
    restart, it can be pulled without the app open, and anything else on the
    machine can pull it. A kill switch that forgets it was pulled, or that can
    only be reached from a window you have already closed, is decorative.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def read(self) -> Halt | None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A file that exists but cannot be parsed still means halted. This
            # is the one place in the codebase where the unreadable case must
            # fail closed rather than open.
            return Halt(reason="halt file present but unreadable", code="unreadable") \
                if self.path.exists() else None
        if not isinstance(raw, dict):
            return Halt(reason="halt file malformed", code="unreadable")
        return Halt(
            reason=str(raw.get("reason", "")),
            code=str(raw.get("code", "")),
            at=float(raw.get("at", 0)),
            manual=bool(raw.get("manual", False)),
        )

    @property
    def active(self) -> bool:
        return self.read() is not None

    def set(self, reason: str, *, code: str = "", manual: bool = False) -> Halt:
        halt = Halt(reason=reason, code=code, at=time.time(), manual=manual)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({
            "reason": halt.reason, "code": halt.code,
            "at": halt.at, "manual": halt.manual,
        })
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return halt

    def clear(self) -> float:
        """Lift the halt and return the moment it was lifted.

        That timestamp is the important part. Limit evaluation after a clear
        only looks at activity since this moment, which is what stops the same
        breach re-halting the system the instant it resumes.
        """
        self.path.unlink(missing_ok=True)
        return time.time()
