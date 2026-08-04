"""Rule sets a person can run without writing any Python.

These exist so that installing proofmark and typing one command produces a real
run against a real market. Asking a non-programmer to first author a strategy
class is how a tool ends up with users who only ever read its README.

WHAT THESE ARE NOT.

They are not recommendations, and they are not expected to make money. They are
the textbook rules everyone tries first, included precisely so the tool can
show you what they actually do. The published test that this library's guards
were built around found six of seven such rules finishing behind buying once
and holding, and that result is easier to believe when you can reproduce it on
your own screen with your own symbol.

Each one reads only closed bars up to and including the current one, and
returns a decision that will be filled at the NEXT bar's open. None of them can
see the price they trade at. That property is what makes them safe to compare.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence


@dataclass(frozen=True)
class Signal:
    action: str  # "buy", "sell" or "hold"
    reason: str

    # Filled in by the engine, not by the strategy. Where the stop goes is a
    # risk decision measured from volatility, and letting each rule set invent
    # its own would mean the sizing policy could not be trusted to mean the
    # same thing across markets.
    stop: float | None = None


@dataclass(frozen=True)
class Strategy:
    name: str
    summary: str
    warmup: int
    decide: Callable[[Sequence[dict]], Signal]


HOLD = Signal("hold", "")


def _closes(bars: Sequence[dict]) -> list[float]:
    return [float(b["close"]) for b in bars]


def _ema(values: Sequence[float], span: int) -> float:
    """Exponential moving average of the whole series, most recent last."""
    k = 2 / (span + 1)
    out = values[0]
    for v in values[1:]:
        out = v * k + out * (1 - k)
    return out


def _rsi(values: Sequence[float], period: int = 14) -> float:
    """Wilder's RSI. Returns 50 when there is no movement to measure.

    Neutral rather than undefined on a flat series, because a strategy that
    crashes on a stablecoin pair is a strategy nobody can leave running.
    """
    if len(values) <= period:
        return 50.0

    gains = losses = 0.0
    for a, b in zip(values[-period - 1:-1], values[-period:]):
        change = b - a
        if change >= 0:
            gains += change
        else:
            losses -= change

    if losses == 0:
        return 100.0 if gains else 50.0
    rs = (gains / period) / (losses / period)
    return 100 - 100 / (1 + rs)


def _ema_cross(bars: Sequence[dict], fast: int = 9, slow: int = 21) -> Signal:
    closes = _closes(bars)
    if len(closes) < slow + 1:
        return HOLD

    now_fast, now_slow = _ema(closes, fast), _ema(closes, slow)
    was_fast, was_slow = _ema(closes[:-1], fast), _ema(closes[:-1], slow)

    # A cross, not a state. Buying every bar the fast line happens to be above
    # the slow one is a different strategy with a different cost profile, and
    # the difference is entirely in fees.
    if was_fast <= was_slow and now_fast > now_slow:
        return Signal("buy", f"the {fast} bar average crossed above the {slow} bar average")
    if was_fast >= was_slow and now_fast < now_slow:
        return Signal("sell", f"the {fast} bar average crossed back below the {slow} bar average")
    return HOLD


def _rsi_dip(bars: Sequence[dict], low: float = 30, high: float = 55) -> Signal:
    closes = _closes(bars)
    value = _rsi(closes)
    if value < low:
        return Signal("buy", f"RSI at {value:.0f}, below {low:.0f}")
    if value > high:
        return Signal("sell", f"RSI recovered to {value:.0f}, above {high:.0f}")
    return HOLD


def _breakout(bars: Sequence[dict], lookback: int = 20) -> Signal:
    """Buy a new high of the last ``lookback`` bars, sell a new low.

    The comparison window deliberately excludes the current bar. Including it
    means comparing a high against itself, which is true on every bar and
    produces a strategy that is always in the market and looks brilliant until
    fees are applied.
    """
    if len(bars) < lookback + 1:
        return HOLD

    window = bars[-lookback - 1:-1]
    highest = max(float(b["high"]) for b in window)
    lowest = min(float(b["low"]) for b in window)
    close = float(bars[-1]["close"])

    if close > highest:
        return Signal("buy", f"closed above the {lookback} bar high of {highest:,.2f}")
    if close < lowest:
        return Signal("sell", f"closed below the {lookback} bar low of {lowest:,.2f}")
    return HOLD


def _hold(bars: Sequence[dict]) -> Signal:
    """Be in the market. The engine refuses the duplicate, so it buys once.

    Included as a runnable strategy rather than only a dashed line, so a person
    can point the same engine, the same fees and the same fill rule at doing
    nothing. When the clever rules lose to this, they lose under identical
    conditions and there is nothing left to argue about.

    It signals on EVERY bar rather than only the first. The first-bar-only
    version looked equivalent and was not: the engine cannot size a position
    before it has enough history to measure volatility, so the single early
    signal was refused every time and this strategy never once entered the
    market. A rule that fires only in a window where entries are impossible is
    a rule that does nothing at all.
    """
    return Signal("buy", "in the market and staying there")


BUILTIN: dict[str, Strategy] = {
    "ema-cross": Strategy(
        name="ema-cross",
        summary="Buys when a 9 bar average crosses above a 21 bar average, sells on the way back.",
        warmup=22,
        decide=_ema_cross,
    ),
    "rsi-dip": Strategy(
        name="rsi-dip",
        summary="Buys when RSI drops under 30, sells once it recovers past 55.",
        warmup=15,
        decide=_rsi_dip,
    ),
    "breakout": Strategy(
        name="breakout",
        summary="Buys a 20 bar high, sells a 20 bar low.",
        warmup=21,
        decide=_breakout,
    ),
    "buy-and-hold": Strategy(
        name="buy-and-hold",
        summary="Buys once on the first bar and never trades again. The thing to beat.",
        warmup=1,
        decide=_hold,
    ),
}


def get_strategy(name: str) -> Strategy:
    try:
        return BUILTIN[name]
    except KeyError:
        raise ValueError(
            f"no strategy called {name!r}. Available: {', '.join(sorted(BUILTIN))}"
        ) from None


def describe_all() -> str:
    width = max(len(n) for n in BUILTIN)
    lines = ["  " + f"{'name'.ljust(width)}  what it does", ""]
    for name in sorted(BUILTIN):
        lines.append(f"  {name.ljust(width)}  {BUILTIN[name].summary}")
    lines += [
        "",
        "  None of these is a recommendation. They are the rules everyone tries",
        "  first, included so you can watch what they actually do against a real",
        "  market and against buying once and holding.",
    ]
    return "\n".join(lines)
