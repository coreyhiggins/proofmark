"""How much to buy, which is the question most retail systems never ask.

Before this file, ``buy`` spent every available dollar on every entry. That is
not an aggressive sizing policy, it is the absence of one, and it is the single
most common reason a strategy that backtests fine destroys a real account: one
bad entry at full size undoes twenty good ones at full size.

THE THREE MODES, AND WHY RISK IS THE DEFAULT.

- ``fixed_fraction``: a set percentage of equity per position. Simple, and it
  ignores how far away the exit is, so a tight stop and a wide stop consume the
  same capital while risking wildly different amounts.
- ``fixed_notional``: a flat cash amount. What people actually use while
  learning, and worth supporting for that reason alone.
- ``risk``: size so that being stopped out costs a fixed percentage of equity.
  The default, because it is the only one of the three where the number you
  configure is the number you actually risk.

WHAT "SIZING ADJUSTED TO VOLATILITY SO RISK STAYS CONSTANT" MEANS.

It means risk sizing with a stop distance derived from volatility, and it is
worth being precise because the phrase is usually repeated without its
mechanism. A quiet market gives a tight stop, so the same 1% of equity buys a
larger position. A violent market gives a wide stop and a smaller one. The
capital deployed swings around; the amount at risk does not.

A stop pinned at a literal fixed percentage from entry does NOT do this: with
the distance constant, risk sizing reduces to a constant fraction of equity and
there is nothing left for volatility to adjust. Both are offered because people
ask for the fixed one by name, and ATR is the default because it is the one
that does what the sentence claims.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

Mode = Literal["risk", "fixed_fraction", "fixed_notional"]
StopSource = Literal["atr", "percent"]

# A cap that sits above every mode. Without it a misconfigured policy, or a
# stop distance that rounds to nearly nothing in a quiet market, puts the whole
# account into one position and calls it correct.
DEFAULT_MAX_POSITION = 0.25

# Bars of history for the volatility estimate. Fourteen is the convention and
# the convention is fine; what matters is that it is long enough not to react
# to a single bar and short enough to notice a regime change.
ATR_PERIOD = 14


@dataclass(frozen=True)
class Sizing:
    mode: Mode = "risk"

    # Fraction of equity risked per position under ``risk`` mode. One percent
    # is the figure most disciplined systems land on, and the arithmetic is why:
    # it takes a hundred consecutive full losses to be wiped out.
    risk_per_trade: float = 0.01

    # Used by fixed_fraction and fixed_notional respectively.
    fraction: float = 0.10
    notional: float = 1000.0

    stop_source: StopSource = "atr"
    atr_multiple: float = 2.0
    stop_percent: float = 0.02

    max_position: float = DEFAULT_MAX_POSITION

    def __post_init__(self) -> None:
        if not 0 < self.max_position <= 1:
            raise ValueError("max_position must be a fraction above 0 and at most 1")
        if self.risk_per_trade <= 0 or self.risk_per_trade > 0.5:
            raise ValueError("risk_per_trade must be above 0 and at most 0.5")
        if self.atr_multiple <= 0 or self.stop_percent <= 0:
            raise ValueError("stop distance settings must be above zero")


def true_range(bars: Sequence[dict]) -> float:
    """The last bar's true range.

    Uses the previous close, not just the bar's own high minus low, so an
    overnight gap counts as the movement it was. Ignoring gaps is how an
    equities system ends up with stops sized for a market that never closes.
    """
    if not bars:
        return 0.0
    last = bars[-1]
    high, low = float(last["high"]), float(last["low"])
    if len(bars) < 2:
        return high - low
    previous_close = float(bars[-2]["close"])
    return max(high - low, abs(high - previous_close), abs(low - previous_close))


def atr(bars: Sequence[dict], period: int = ATR_PERIOD) -> float | None:
    """Average true range, or None when there is not enough history.

    None rather than a guess. A volatility estimate from three bars is a number
    with no information in it, and sizing a position from one is worse than
    refusing to trade until there is enough data.
    """
    if len(bars) < period + 1:
        return None
    ranges = [true_range(bars[: i + 1]) for i in range(len(bars) - period, len(bars))]
    return sum(ranges) / len(ranges)


def stop_price(bars: Sequence[dict], policy: Sizing) -> float | None:
    """Where the stop goes for an entry at the last close."""
    if not bars:
        return None
    price = float(bars[-1]["close"])

    if policy.stop_source == "percent":
        return price * (1 - policy.stop_percent)

    value = atr(bars)
    if value is None or value <= 0:
        return None
    return price - value * policy.atr_multiple


def position_size(
    equity: float,
    cash: float,
    price: float,
    *,
    policy: Sizing,
    stop: float | None = None,
    whole_units: bool = False,
) -> float:
    """Quantity to buy, after every cap. Zero means do not take the trade.

    Returning zero rather than raising is deliberate: "the account is too small
    to take this trade at this stop distance" is a normal outcome that a live
    engine has to survive quietly, several times a day, without stopping.
    """
    if price <= 0 or equity <= 0 or cash <= 0:
        return 0.0

    if policy.mode == "risk":
        if stop is None or stop >= price:
            return 0.0
        quantity = (equity * policy.risk_per_trade) / (price - stop)
    elif policy.mode == "fixed_fraction":
        quantity = (equity * policy.fraction) / price
    else:
        quantity = policy.notional / price

    # The cap, then what is actually affordable. Order matters: capping after
    # the cash check would let a large account exceed its own position limit.
    quantity = min(quantity, (equity * policy.max_position) / price)
    quantity = min(quantity, cash / (price * (1 + 0.01)))  # headroom for costs

    if whole_units:
        quantity = float(int(quantity))

    return max(0.0, quantity)
