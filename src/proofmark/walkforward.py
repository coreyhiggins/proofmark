"""Walk-forward validation, as the default way to test a strategy.

Fit on a window, measure on the window after it, never look back. Repeat. The
reported equity curve is the concatenation of segments the optimiser never
saw, so the number you read is out-of-sample by construction rather than by
your own discipline.

WHY THIS IS THE PRIMARY VERB AND SINGLE-WINDOW BACKTEST IS NOT.

The most requested feature in a 21,000-star backtesting platform, open for
three years with 115 reactions, is walk-forward validation, and it is still
not shipped. Another popular library advertises testing "hundreds of strategy
variants in mere seconds" with no mention of overfitting in that method's
documentation. Exactly one project in the survey made walk-forward its
headline API rather than an advanced option.

That ordering is the whole difference. A tool whose easy path is
``backtest()`` and whose hard path is ``walkforward()`` will produce mostly
in-sample numbers, because people use the easy path.

PARAMETER STABILITY IS REPORTED, AND IT IS THE PART NOBODY SHOWS.

If the best lookback is 5 bars in one window, 47 in the next and 12 in the
one after, the optimiser is fitting noise and the out-of-sample equity curve
is luck. That is visible for free once you have run the windows, and it is a
more honest signal than any single ratio, so it is in the result rather than
buried.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from .metrics import Metrics, summarise

Bar = Mapping[str, Any]

# Given the training bars, return the chosen parameters. The second element is
# how many candidates were evaluated to choose them, which the guards need.
Optimizer = Callable[[Sequence[Bar]], "tuple[Mapping[str, Any], int]"]

# Given test bars and chosen parameters, return (equity curve, trade pnls).
Evaluator = Callable[[Sequence[Bar], Mapping[str, Any]], "tuple[Sequence[float], Sequence[float]]"]


@dataclass
class Window:
    index: int
    train_start: int
    train_end: int
    test_end: int
    params: Mapping[str, Any]
    trials: int
    metrics: Metrics


@dataclass
class WalkForwardResult:
    """Out-of-sample performance, stitched from segments never optimised on."""

    windows: list[Window] = field(default_factory=list)
    equity: list[float] = field(default_factory=list)
    trade_pnls: list[float] = field(default_factory=list)
    anchored: bool = False

    @property
    def total_trials(self) -> int:
        """Every candidate evaluated, across every window.

        This is the number the guards care about. Optimising 40 variants in
        each of 6 windows is a 240-trial search, not a 40-trial one.
        """
        return sum(w.trials for w in self.windows)

    @property
    def metrics(self) -> Metrics:
        return summarise(self.equity, self.trade_pnls)

    def stability(self) -> dict[str, dict[str, float]]:
        """How much each chosen parameter moved between windows.

        ``variation`` is the coefficient of variation, so it compares across
        parameters on different scales. High variation means the optimiser
        picked a different answer each time it looked, which is what fitting
        noise looks like from the outside.
        """
        out: dict[str, dict[str, float]] = {}
        keys = {k for w in self.windows for k in w.params}

        for key in sorted(keys):
            values = [w.params[key] for w in self.windows if key in w.params]
            numeric = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if len(numeric) < 2:
                continue
            mean = statistics.fmean(numeric)
            stdev = statistics.pstdev(numeric)
            out[key] = {
                "mean": mean,
                "stdev": stdev,
                "variation": (stdev / abs(mean)) if mean else float("inf"),
                "min": min(numeric),
                "max": max(numeric),
            }
        return out

    def unstable_params(self, threshold: float = 0.5) -> list[str]:
        """Parameters whose spread exceeds half their mean across windows."""
        return [k for k, s in self.stability().items() if s["variation"] > threshold]


def walk_forward(
    bars: Sequence[Bar],
    optimize: Optimizer,
    evaluate: Evaluator,
    *,
    windows: int = 5,
    train_frac: float = 0.6,
    anchored: bool = False,
) -> WalkForwardResult:
    """Run walk-forward validation.

    ``anchored=True`` grows the training window from the start of the data
    instead of rolling it, which is the right choice when you believe older
    data still applies and the wrong one when the regime has changed. Rolling
    is the default because assuming a stable regime is the more flattering
    assumption, and the flattering assumption is the one that costs money.

    The returned equity curve is out-of-sample only. There is deliberately no
    way to ask this function for in-sample performance, because a number you
    cannot get is a number you cannot accidentally publish.
    """
    if not 0.1 <= train_frac <= 0.9:
        raise ValueError("train_frac must be between 0.1 and 0.9")
    if windows < 2:
        raise ValueError("walk-forward needs at least two windows to mean anything")

    # Each window trains on train_frac of its span and tests on the rest, and
    # windows tile the series without overlapping their test segments.
    span = len(bars) // windows
    if span < 20:
        raise ValueError(
            f"{len(bars)} bars across {windows} windows leaves {span} bars each, "
            "which is too few to measure. Use fewer windows or more data."
        )

    result = WalkForwardResult(anchored=anchored)
    equity: list[float] = []
    pnls: list[float] = []

    for i in range(windows):
        window_start = i * span
        train_start = 0 if anchored else window_start
        train_end = window_start + int(span * train_frac)
        test_end = window_start + span if i < windows - 1 else len(bars)

        train = bars[train_start:train_end]
        test = bars[train_end:test_end]
        if len(train) < 10 or len(test) < 5:
            continue

        params, trials = optimize(train)
        seg_equity, seg_pnls = evaluate(test, params)
        if len(seg_equity) < 2:
            continue

        # Stitch segments by carrying the running balance forward, so the
        # combined curve compounds rather than restarting at each window.
        opening = equity[-1] if equity else float(seg_equity[0])
        scale = opening / seg_equity[0] if seg_equity[0] else 1.0
        equity.extend(float(v) * scale for v in (seg_equity if not equity else seg_equity[1:]))
        pnls.extend(float(p) for p in seg_pnls)

        result.windows.append(Window(
            index=i,
            train_start=train_start,
            train_end=train_end,
            test_end=test_end,
            params=dict(params),
            trials=int(trials),
            metrics=summarise(seg_equity, seg_pnls),
        ))

    if len(result.windows) < 2:
        raise ValueError("fewer than two windows produced usable results")

    result.equity = equity
    result.trade_pnls = pnls
    return result


def format_walk_forward(result: WalkForwardResult) -> str:
    """Render the per-window table and the stability report."""
    lines = [
        f"walk-forward, {len(result.windows)} windows, "
        f"{'anchored' if result.anchored else 'rolling'}, "
        f"{result.total_trials} total trials",
        "",
        f"  {'win':>3}  {'test bars':>9}  {'return':>8}  {'max dd':>7}  params",
    ]

    for w in result.windows:
        params = ", ".join(f"{k}={v}" for k, v in sorted(w.params.items()))
        lines.append(
            f"  {w.index:>3}  {w.test_end - w.train_end:>9}  "
            f"{w.metrics.total_return:>7.1%}  {w.metrics.max_drawdown:>6.1%}  {params}"
        )

    stability = result.stability()
    if stability:
        lines += ["", "  parameter stability across windows"]
        for key, s in stability.items():
            flag = "  UNSTABLE" if s["variation"] > 0.5 else ""
            lines.append(
                f"    {key:<16} mean {s['mean']:.3g}, range {s['min']:.3g} to "
                f"{s['max']:.3g}, variation {s['variation']:.2f}{flag}"
            )

        unstable = result.unstable_params()
        if unstable:
            lines += [
                "",
                f"  {', '.join(unstable)} changed by more than half its own mean between",
                "  windows. An optimiser that picks a different answer every time it looks",
                "  is fitting noise, and the out-of-sample curve above is closer to luck",
                "  than to evidence.",
            ]

    return "\n".join(lines)
