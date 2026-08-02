"""Running a strategy at several timeframes, and noticing when the sign flips.

A strategy that makes money on daily bars and loses money on four-hour bars,
over the same asset and the same window, has not found anything. It has fitted
one particular sampling of the same prices. Nothing about the market changed
between those two runs, only the grid you laid over it.

The demonstration that prompted this is public and unusually clean. A widely
shared writeup ran one mean-reversion strategy on BTC and published both:

    daily    +5.25%   profit factor 1.801
    4-hour  -11.83%   profit factor 0.636

Same rules, same asset, same window. The article presented the daily figure
and mentioned the other in passing. Either one alone is a result; together
they are the absence of one.

This is a cheap check because it needs no extra data. Aggregate the bars you
already have into slower ones and run again.

WHAT IT CANNOT TELL YOU. Agreement across timeframes is not evidence a
strategy works, only that this particular way of being wrong has been ruled
out. A strategy can be consistently overfit at every timeframe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

Bar = Mapping[str, Any]

# Given bars, return (equity curve, trade results). The same shape walk_forward
# uses, so a strategy written for one works with the other.
Evaluator = Callable[[Sequence[Bar]], "tuple[Sequence[float], Sequence[float]]"]

# 1 is the data as given. The rest are common regroupings: 4h into 12h, daily,
# and so on, depending on what the base bars are.
DEFAULT_FACTORS = (1, 2, 3, 6)

# Below this many bars a timeframe cannot say anything, and running it anyway
# produces noise that looks like disagreement.
MIN_BARS = 60


def resample(bars: Sequence[Bar], factor: int) -> list[dict[str, Any]]:
    """Aggregate every ``factor`` bars into one.

    Open is the first open, close the last close, high and low the extremes,
    volume the sum. That is the only correct way to do it, and getting it wrong
    is its own source of fake results: taking the last high, for instance,
    quietly discards the very spikes a stop would have hit.

    A trailing partial group is dropped. A half-formed bar is not a bar, and
    including it means the final decision was made on data that had not
    finished arriving, which is the lookahead bug in a different coat.
    """
    if factor < 1:
        raise ValueError("factor must be at least 1")
    if factor == 1:
        return [dict(b) for b in bars]

    out: list[dict[str, Any]] = []
    for start in range(0, len(bars) - factor + 1, factor):
        group = bars[start:start + factor]
        first = group[0]
        merged = dict(first)
        merged["open"] = first.get("open")
        merged["close"] = group[-1].get("close")

        highs = [b["high"] for b in group if b.get("high") is not None]
        lows = [b["low"] for b in group if b.get("low") is not None]
        if highs:
            merged["high"] = max(highs)
        if lows:
            merged["low"] = min(lows)

        volumes = [b.get("volume") for b in group if b.get("volume") is not None]
        if volumes:
            merged["volume"] = sum(volumes)

        out.append(merged)
    return out


@dataclass
class Run:
    factor: int
    bars: int
    total_return: float
    trades: int

    @property
    def sign(self) -> int:
        return (self.total_return > 0) - (self.total_return < 0)


@dataclass
class SweepResult:
    runs: list[Run] = field(default_factory=list)
    skipped: list[int] = field(default_factory=list)

    @property
    def signs(self) -> set[int]:
        return {r.sign for r in self.runs if r.sign != 0}

    @property
    def flips(self) -> bool:
        """True when the strategy makes money at one timeframe and loses at another."""
        return len(self.signs) > 1

    @property
    def spread(self) -> float:
        if not self.runs:
            return 0.0
        returns = [r.total_return for r in self.runs]
        return max(returns) - min(returns)


def sweep(
    bars: Sequence[Bar],
    evaluate: Evaluator,
    *,
    factors: Sequence[int] = DEFAULT_FACTORS,
    min_bars: int = MIN_BARS,
) -> SweepResult:
    """Run one strategy over several regroupings of the same bars."""
    result = SweepResult()

    for factor in factors:
        grouped = resample(bars, factor)
        if len(grouped) < min_bars:
            result.skipped.append(factor)
            continue

        equity, pnls = evaluate(grouped)
        if len(equity) < 2 or not equity[0]:
            result.skipped.append(factor)
            continue

        result.runs.append(Run(
            factor=factor,
            bars=len(grouped),
            total_return=(equity[-1] / equity[0]) - 1,
            trades=len(pnls),
        ))

    return result


def format_sweep(result: SweepResult) -> str:
    """Render the sweep, and say plainly what a flip means."""
    if not result.runs:
        return "no timeframe produced enough bars to measure"

    lines = ["timeframe sweep", "", f"  {'grouping':>9}  {'bars':>6}  {'return':>9}  {'trades':>7}"]
    for run in result.runs:
        label = "as given" if run.factor == 1 else f"{run.factor} bars in 1"
        lines.append(
            f"  {label:>9}  {run.bars:>6}  {run.total_return:>8.1%}  {run.trades:>7}"
        )

    if result.skipped:
        lines.append(f"\n  skipped {result.skipped} for too few bars after grouping")

    if result.flips:
        lines += [
            "",
            "  THE SIGN FLIPS. This strategy makes money at one grouping of these",
            "  bars and loses money at another, over the same asset and the same",
            "  window. Nothing about the market changed between those runs, only",
            "  the grid laid over it, so the result is a property of the grid.",
        ]
    elif result.spread > 0.5:
        lines += [
            "",
            f"  Returns span {result.spread:.0%} across groupings without changing sign.",
            "  Consistent in direction, but the magnitude is not something to plan on.",
        ]

    return "\n".join(lines)
