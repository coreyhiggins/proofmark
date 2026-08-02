"""End to end: walk-forward a strategy, then write a report you can open.

Run it:

    python examples/walk_forward_report.py

It writes ``walk-forward-report.html`` next to itself. Open that in a browser.

The strategy here is a deliberately mediocre moving-average crossover on
synthetic data. It is not a suggestion, and it is not supposed to work. It
exists so the report has something honest to show, which turns out to be the
more useful demonstration: the shape you should expect from a real strategy is
closer to this than to anything with a smooth rising line.
"""

from __future__ import annotations

import random
from pathlib import Path

from proofmark.charts import buy_and_hold, equity_chart, underwater_chart
from proofmark.guards import check, format_verdict
from proofmark.walkforward import format_walk_forward, walk_forward


def synthetic_bars(n: int = 3000, seed: int = 11) -> list[dict]:
    """A random walk with drift and regime changes. No edge is hidden in here."""
    rng = random.Random(seed)
    price = 100.0
    bars = []
    for i in range(n):
        drift = 0.0004 if (i // 400) % 2 == 0 else -0.0003
        price *= 1 + drift + rng.gauss(0, 0.012)
        price = max(price, 1.0)
        bars.append({"timestamp": i, "open": price, "close": price * (1 + rng.gauss(0, 0.001))})
    return bars


def optimise(train: list[dict]) -> tuple[dict, int]:
    """Pick the crossover pair that did best in-sample, and report the count.

    Returning the trial count is not optional politeness. It is what lets the
    guards know a search happened, and 24 candidates in each of 6 windows is a
    144-trial search rather than a 24-trial one.
    """
    candidates = [(f, s) for f in (5, 10, 20, 30) for s in (50, 80, 120, 160, 200, 250) if f < s]
    best, best_return = candidates[0], float("-inf")

    for fast, slow in candidates:
        equity, _ = run(train, {"fast": fast, "slow": slow})
        total = equity[-1] / equity[0] - 1 if equity[0] else 0
        if total > best_return:
            best, best_return = (fast, slow), total

    return {"fast": best[0], "slow": best[1]}, len(candidates)


def run(bars: list[dict], params: dict) -> tuple[list[float], list[float]]:
    """Long when the fast average is above the slow one, flat otherwise.

    Decides on bars strictly before ``t`` and executes at ``t``'s open, which
    is the convention ``check_lookahead(executes_at="open")`` enforces.
    """
    fast, slow = params["fast"], params["slow"]
    equity, pnls = [10_000.0], []
    entry = None

    for t in range(1, len(bars)):
        window = bars[:t]
        if len(window) < slow:
            equity.append(equity[-1])
            continue

        f = sum(b["close"] for b in window[-fast:]) / fast
        s = sum(b["close"] for b in window[-slow:]) / slow
        price = bars[t]["open"]

        if entry is None and f > s:
            entry = price
        elif entry is not None and f <= s:
            # 0.1% round-trip cost. A backtest with no costs is not a backtest.
            pnls.append(equity[-1] * ((price / entry) - 1 - 0.001))
            entry = None

        held = (price / entry) if entry else 1.0
        equity.append(equity[-1] * (1 + (held - 1) * 0.02))

    return equity, pnls


def main() -> None:
    bars = synthetic_bars()
    result = walk_forward(bars, optimise, run, windows=6, train_frac=0.6)

    print(format_walk_forward(result))
    print()

    metrics = result.metrics
    verdict = check(
        metrics,
        trials=result.total_trials,
        costs_applied=abs(sum(result.trade_pnls)) * 0.001,
        # Synthetic single-symbol data: there is no universe to survive.
        delisted_included=True,
    )
    print(format_verdict(verdict))

    # Shade the out-of-sample stretches on the equity curve. Each window
    # contributes the segment its optimiser never saw.
    spans, cursor = [], 0
    for window in result.windows:
        length = window.test_end - window.train_end
        spans.append((cursor, cursor + length))
        cursor += length

    hold = buy_and_hold(bars, starting=result.equity[0])
    html = f"""<!doctype html><meta charset="utf-8">
<title>walk-forward report</title>
<style>
 body{{max-width:44rem;margin:0 auto;padding:4rem 1.5rem;background:#fbf9f5;color:#1c1a17;
 font:17px/1.65 "Iowan Old Style",Palatino,Georgia,serif}}
 h1{{font:600 1.5rem/1.1 system-ui,sans-serif;letter-spacing:.14em;text-transform:uppercase;
 border-bottom:2px solid #1c1a17;padding-bottom:.8rem}}
 h2{{font:11px/1.4 system-ui,sans-serif;letter-spacing:.13em;text-transform:uppercase;color:#645e55;
 border-bottom:1px solid #1c1a17;padding-bottom:.7rem;margin-top:3rem}}
 pre{{font:12px/1.6 ui-monospace,Menlo,monospace;white-space:pre-wrap;color:#645e55}}
 .chart{{width:100%;margin-top:1rem}} .chart .subject{{fill:none;stroke:#1c1a17;stroke-width:1.6}}
 .chart .bench{{fill:none;stroke:#645e55;stroke-width:1.2;stroke-dasharray:4 3}}
 .chart .zero{{stroke:#ded7ca}} .chart .oos{{fill:#1c1a17;opacity:.05}}
 .chart .underwater{{fill:#8c2015;fill-opacity:.16;stroke:#8c2015;stroke-width:1.2}}
 .chart-caption{{font:11px/1.5 system-ui,sans-serif;color:#645e55}}
</style>
<h1>Walk-forward report</h1>
<p>A mediocre moving-average crossover on synthetic data, shown out-of-sample.
Shaded bands are stretches the optimiser had never seen.</p>
<h2>Account value against buy and hold</h2>
{equity_chart(result.equity, hold, windows=spans)}
<h2>Below the previous peak</h2>
{underwater_chart(result.equity)}
<h2>Windows</h2><pre>{format_walk_forward(result)}</pre>
<h2>Determination</h2><pre>{format_verdict(verdict)}</pre>
"""

    out = Path(__file__).with_name("walk-forward-report.html")
    out.write_text(html, encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
