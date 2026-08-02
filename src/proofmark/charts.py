"""Charts, drawn as plain SVG with no dependencies.

Three charts, chosen because they answer the questions a rules-based trader
actually has. A candlestick chart with indicator overlays answers a different
question, the one a discretionary trader asks, and a system that decides by
rules has already answered it.

1. **Equity against a benchmark, on the same axes.** Almost nobody draws this,
   because it usually makes the strategy look worse. That is the reason to
   draw it. A strategy that returned 40% in a period where holding returned
   55% did not make you 40%, it cost you 15%.

2. **The underwater plot.** Distance below the previous peak, at every moment.
   This is where a strategy is actually experienced. A headline return hides
   the eighteen months spent 30% down, and that stretch is what decides
   whether a real person keeps running it.

3. **Walk-forward segments, shaded.** Which parts of the curve the optimiser
   had never seen. It turns out-of-sample from a claim into something visible.

Drawing rules, consistent with the report the charts sit inside: hairline
grid, ink for the subject, a lighter dashed line for the benchmark, direct
labels rather than a legend, no gradients and no shadows. Colours come from
the page's CSS variables, so both themes work without a second palette.
"""

from __future__ import annotations

from typing import Sequence

# Wide enough for detail, short enough that three stack without scrolling.
WIDTH = 640
HEIGHT = 200
PAD_L, PAD_R, PAD_T, PAD_B = 4, 4, 12, 18

# Above this many points, straight-line segments are smaller than a pixel and
# the browser is asked to draw geometry nobody can see.
MAX_POINTS = 900


def _downsample(values: Sequence[float], limit: int = MAX_POINTS) -> list[float]:
    """Keep the shape, drop the redundancy.

    Takes the extreme of each bucket rather than the first value, so a spike
    or a crash survives. Averaging here would smooth away the drawdown that
    the chart exists to show.
    """
    if len(values) <= limit:
        return list(values)

    step = len(values) / limit
    out: list[float] = []
    for i in range(limit):
        chunk = values[int(i * step):max(int((i + 1) * step), int(i * step) + 1)]
        if not chunk:
            continue
        first = chunk[0]
        out.append(max(chunk, key=lambda v: abs(v - first)))
    return out


def _path(values: Sequence[float], lo: float, hi: float, width: int, height: int) -> str:
    if len(values) < 2:
        return ""
    span = (hi - lo) or 1.0
    inner_w = width - PAD_L - PAD_R
    inner_h = height - PAD_T - PAD_B
    step = inner_w / (len(values) - 1)

    points = [
        f"{PAD_L + i * step:.2f},{PAD_T + inner_h - ((v - lo) / span) * inner_h:.2f}"
        for i, v in enumerate(values)
    ]
    return "M" + "L".join(points)


def _rebase(values: Sequence[float]) -> list[float]:
    """Express a series as growth from its own start, so two can share an axis."""
    base = values[0] if values and values[0] else 1.0
    return [v / base for v in values]


def equity_chart(
    equity: Sequence[float],
    benchmark: Sequence[float] | None = None,
    *,
    benchmark_label: str = "buy and hold",
    windows: Sequence[tuple[int, int]] | None = None,
) -> str:
    """Equity against a benchmark, both rebased to their own starting value.

    ``windows`` shades out-of-sample walk-forward segments as (start, end)
    index pairs into the equity series.
    """
    if len(equity) < 2:
        return ""

    strategy = _downsample(_rebase(equity))
    series = [strategy]

    bench: list[float] | None = None
    if benchmark and len(benchmark) >= 2:
        # Resample the benchmark onto the strategy's x-axis so the lines are
        # comparable even when the two were sampled at different rates.
        rebased = _rebase(benchmark)
        n = len(strategy)
        bench = [rebased[min(int(i * len(rebased) / n), len(rebased) - 1)] for i in range(n)]
        series.append(bench)

    lo = min(min(s) for s in series)
    hi = max(max(s) for s in series)
    pad = (hi - lo) * 0.08 or 0.05
    lo, hi = lo - pad, hi + pad

    parts = [
        f'<svg viewBox="0 0 {WIDTH} {HEIGHT}" width="100%" height="{HEIGHT}" '
        f'role="img" aria-label="Account value over time compared with {benchmark_label}" '
        'preserveAspectRatio="none" class="chart">'
    ]

    # Shade the out-of-sample windows first so lines draw on top.
    if windows:
        inner_w = WIDTH - PAD_L - PAD_R
        for j, (start, end) in enumerate(windows):
            if end <= start:
                continue
            x1 = PAD_L + (start / max(len(equity) - 1, 1)) * inner_w
            x2 = PAD_L + (end / max(len(equity) - 1, 1)) * inner_w
            if j % 2 == 0:
                parts.append(
                    f'<rect x="{x1:.1f}" y="{PAD_T}" width="{x2 - x1:.1f}" '
                    f'height="{HEIGHT - PAD_T - PAD_B}" class="oos"/>'
                )

    # The line where the account is exactly where it started. Everything below
    # it is a loss, and that is worth a rule of its own.
    if lo < 1.0 < hi:
        y = PAD_T + (HEIGHT - PAD_T - PAD_B) * (1 - (1.0 - lo) / (hi - lo))
        parts.append(f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{WIDTH - PAD_R}" y2="{y:.1f}" class="zero"/>')

    if bench:
        parts.append(f'<path d="{_path(bench, lo, hi, WIDTH, HEIGHT)}" class="bench"/>')
    parts.append(f'<path d="{_path(strategy, lo, hi, WIDTH, HEIGHT)}" class="subject"/>')

    parts.append("</svg>")

    final_strategy = strategy[-1] - 1
    caption = f"strategy {final_strategy:+.1%}"
    if bench:
        caption += f" &nbsp;&middot;&nbsp; {benchmark_label} {bench[-1] - 1:+.1%}"
        gap = final_strategy - (bench[-1] - 1)
        caption += f" &nbsp;&middot;&nbsp; difference {gap:+.1%}"

    return "".join(parts) + f'<p class="chart-caption">{caption}</p>'


def underwater_chart(equity: Sequence[float]) -> str:
    """Distance below the previous peak, filled, at every moment."""
    if len(equity) < 2:
        return ""

    peak = equity[0]
    drawdowns: list[float] = []
    for value in equity:
        peak = max(peak, value)
        drawdowns.append((value - peak) / peak if peak else 0.0)

    series = _downsample(drawdowns)
    worst = min(series) or -0.01
    height = 140
    inner_h = height - PAD_T - PAD_B
    inner_w = WIDTH - PAD_L - PAD_R
    step = inner_w / (len(series) - 1)

    # Zero sits at the top: every point hangs below its own high-water mark.
    points = [
        f"{PAD_L + i * step:.2f},{PAD_T + (v / worst) * inner_h:.2f}"
        for i, v in enumerate(series)
    ]
    area = (
        f"M{PAD_L},{PAD_T}L" + "L".join(points)
        + f"L{PAD_L + (len(series) - 1) * step:.2f},{PAD_T}Z"
    )

    return (
        f'<svg viewBox="0 0 {WIDTH} {height}" width="100%" height="{height}" '
        f'role="img" aria-label="Percentage below the previous peak over time" '
        'preserveAspectRatio="none" class="chart">'
        f'<line x1="{PAD_L}" y1="{PAD_T}" x2="{WIDTH - PAD_R}" y2="{PAD_T}" class="zero"/>'
        f'<path d="{area}" class="underwater"/>'
        "</svg>"
        f'<p class="chart-caption">worst {worst:.1%} below the previous peak</p>'
    )


def buy_and_hold(bars: Sequence[dict], starting: float = 1.0) -> list[float]:
    """The benchmark: what holding from the first bar to the last would have done.

    This is the comparison a strategy has to beat to have been worth running,
    and it is the one most backtests quietly omit.
    """
    closes = [float(b["close"]) for b in bars if b.get("close")]
    if not closes:
        return []
    base = closes[0]
    return [starting * (c / base) for c in closes]
