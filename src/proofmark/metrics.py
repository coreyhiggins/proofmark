"""Performance metrics that refuse to lie.

Every function here returns ``None`` when a metric is genuinely undefined,
never a sentinel value that a report will happily print as a number.

That rule exists because of a real artifact. The most popular community
strategy for the most popular open source trading bot publishes an automated
backtest with every commit. One of them reads:

    Trades          45 (45 win, 0 loss)
    Win Rate        100.0%
    Max Drawdown    0.0%
    Sharpe          42.73
    Sortino/Calmar  -100.00 / -100.00

Sortino and Calmar of exactly -100.00 are a divide-by-zero sentinel, printed
as a headline metric beside a Sharpe of 42.73. Nothing in that table is a
measurement. A person scanning it sees a 100% win rate and stops reading.

So: undefined is ``None``, and :mod:`proofmark.guards` turns ``None`` and
absurd values into a suppressed report rather than a table cell.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

TRADING_DAYS = 252

# Below this many return observations, an annualised ratio is not a
# measurement. Six daily returns scaled by sqrt(252) produced a Sharpe of 4.60
# on a deliberately unremarkable equity curve during testing, which then
# tripped the implausible-Sharpe guard. The curve was fine. The ratio was
# meaningless, and a meaningless number that looks precise is exactly what
# this library exists to stop printing.
MIN_OBSERVATIONS = 30


@dataclass(frozen=True)
class Metrics:
    """A backtest result. Any field may be ``None``, meaning "undefined here"."""

    bars: int
    trades: int
    total_return: float
    max_drawdown: float
    sharpe: float | None
    sortino: float | None
    calmar: float | None
    win_rate: float | None
    profit_factor: float | None


def equity_drawdown(equity: Sequence[float]) -> float:
    """Maximum drawdown from a mark-to-market equity curve.

    Takes the equity curve sampled every bar, not realised profit at trade
    close. Computing drawdown from closed trades lets any hold-until-green
    strategy report 0% drawdown by construction: the loss is real the whole
    time the position is open, it is simply never booked. That is how a
    martingale prints a flat equity line right up until it does not.
    """
    if len(equity) < 2:
        return 0.0

    peak = equity[0]
    worst = 0.0
    for value in equity:
        if value > peak:
            peak = value
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return worst


def _annualised(returns: Sequence[float], bars_per_year: int) -> tuple[float, float]:
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    return mean * bars_per_year, math.sqrt(variance) * math.sqrt(bars_per_year)


def sharpe(returns: Sequence[float], bars_per_year: int = TRADING_DAYS) -> float | None:
    """Annualised Sharpe, or ``None`` when volatility is zero.

    Zero volatility is not an infinitely good strategy. It means the equity
    curve never moved, which is a strategy that did not trade or a bug.
    """
    if len(returns) < MIN_OBSERVATIONS:
        return None
    mean, stdev = _annualised(returns, bars_per_year)
    if stdev == 0:
        return None
    return mean / stdev


def sortino(returns: Sequence[float], bars_per_year: int = TRADING_DAYS) -> float | None:
    """Annualised Sortino, or ``None`` when there is no downside deviation.

    No losing bars means the denominator is zero. The honest answer is that
    the ratio does not exist, not that it is enormous and not that it is -100.
    """
    if len(returns) < MIN_OBSERVATIONS:
        return None
    downside = [r for r in returns if r < 0]
    if not downside:
        return None
    mean = (sum(returns) / len(returns)) * bars_per_year
    dd = math.sqrt(sum(r * r for r in downside) / len(returns)) * math.sqrt(bars_per_year)
    if dd == 0:
        return None
    return mean / dd


def calmar(total_return: float, max_dd: float, years: float,
           observations: int = MIN_OBSERVATIONS) -> float | None:
    """Annualised return over maximum drawdown, or ``None`` when undefined.

    Also ``None`` on too short a series: compounding a few days of return out
    to a full year produces an enormous figure that describes nothing.
    """
    if max_dd <= 0 or years <= 0 or observations < MIN_OBSERVATIONS:
        return None
    annualised = (1 + total_return) ** (1 / years) - 1
    return annualised / max_dd


def profit_factor(pnls: Sequence[float]) -> float | None:
    """Gross win over gross loss, or ``None`` when nothing lost."""
    losses = -sum(p for p in pnls if p < 0)
    if losses == 0:
        return None
    return sum(p for p in pnls if p > 0) / losses


def summarise(
    equity: Sequence[float],
    trade_pnls: Sequence[float],
    bars_per_year: int = TRADING_DAYS,
) -> Metrics:
    """Build a full result from an equity curve and a list of trade outcomes."""
    if len(equity) < 2:
        raise ValueError("need at least two equity points to measure anything")

    returns = [
        (equity[i] / equity[i - 1]) - 1 if equity[i - 1] else 0.0
        for i in range(1, len(equity))
    ]
    max_dd = equity_drawdown(equity)
    years = len(returns) / bars_per_year
    total = (equity[-1] / equity[0]) - 1 if equity[0] else 0.0

    wins = sum(1 for p in trade_pnls if p > 0)

    return Metrics(
        bars=len(equity),
        trades=len(trade_pnls),
        total_return=total,
        max_drawdown=max_dd,
        sharpe=sharpe(returns, bars_per_year),
        sortino=sortino(returns, bars_per_year),
        calmar=calmar(total, max_dd, years, len(returns)),
        win_rate=(wins / len(trade_pnls)) if trade_pnls else None,
        profit_factor=profit_factor(trade_pnls),
    )
