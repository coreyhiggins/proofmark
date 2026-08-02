"""Charts, drawn as plain SVG with no dependencies.

REBUILT after looking at the first version running in the real window. It drew
two unlabelled squiggles in a box: no axis, no gridlines, no reference marks,
nothing to read a value against. Technically the right shape, and useless.

What it now draws, and why each piece is there:

- **A labelled scale.** Gridlines at readable percentages, so "down a bit" is
  a number instead of an impression. A chart with no axis is decoration.
- **The starting line, marked.** Everything below it is a loss. That single
  rule tells you more at a glance than any label.
- **The benchmark, drawn first and softer**, so the eye reads the strategy
  against it rather than beside it.
- **The line drawn on**, left to right, over about a second. Motion is not
  decoration here: watching the strategy fall away from the benchmark lands
  differently from seeing two finished lines.

Three charts, chosen because they answer the questions a rules-based trader
actually has. A candlestick chart with indicator overlays answers a different
question, the one a discretionary trader asks, and a system that decides by
rules has already answered it.
"""

from __future__ import annotations

from typing import Sequence

WIDTH = 720
HEIGHT = 260
UNDERWATER_HEIGHT = 190

# Room on the left for the scale labels, and at the bottom for the time axis.
PAD_L, PAD_R, PAD_T, PAD_B = 54, 16, 18, 26

# Above this many points, straight-line segments fall below a pixel and the
# browser is asked to draw geometry nobody can see.
MAX_POINTS = 900

# Nice round steps, in percent, for the gridlines.
STEPS = (1, 2, 5, 10, 20, 25, 50, 100, 200, 500)


def _downsample(values: Sequence[float], limit: int = MAX_POINTS) -> list[float]:
    """Keep the shape, drop the redundancy.

    Takes the value furthest from each bucket's mean, so a spike or a crash
    survives. An earlier version measured against the bucket's FIRST value,
    which looked equivalent and was not: when the crash was first, every calm
    value scored further from it and the crash was the one thing dropped. A
    90% single-bar loss vanished from the picture entirely.
    """
    if len(values) <= limit:
        return list(values)

    step = len(values) / limit
    out: list[float] = []
    for i in range(limit):
        chunk = values[int(i * step):max(int((i + 1) * step), int(i * step) + 1)]
        if not chunk:
            continue
        mean = sum(chunk) / len(chunk)
        out.append(max(chunk, key=lambda v: abs(v - mean)))
    return out


def _rebase(values: Sequence[float]) -> list[float]:
    """Express a series as growth from its own start, so two can share an axis."""
    base = values[0] if values and values[0] else 1.0
    return [v / base for v in values]


def _nice_step(span: float, target_lines: int = 4) -> float:
    """Pick a round gridline interval that yields roughly ``target_lines``."""
    raw = (span * 100) / max(target_lines, 1)
    for step in STEPS:
        if step >= raw:
            return step / 100
    return STEPS[-1] / 100


def _y(value: float, lo: float, hi: float, height: int) -> float:
    inner = height - PAD_T - PAD_B
    return PAD_T + inner - ((value - lo) / (hi - lo or 1)) * inner


def _path(values: Sequence[float], lo: float, hi: float, height: int) -> str:
    if len(values) < 2:
        return ""
    inner_w = WIDTH - PAD_L - PAD_R
    step = inner_w / (len(values) - 1)
    return "M" + "L".join(
        f"{PAD_L + i * step:.2f},{_y(v, lo, hi, height):.2f}" for i, v in enumerate(values)
    )


def _grid(lo: float, hi: float, height: int, baseline: float = 1.0) -> str:
    """Horizontal rules at round percentages, labelled, plus the starting line."""
    parts: list[str] = []
    step = _nice_step(hi - lo)

    # Walk outward from the baseline so the starting line is always on-grid.
    level = baseline
    while level > lo:
        level -= step
    while level <= hi:
        if lo <= level <= hi:
            y = _y(level, lo, hi, height)
            pct = (level - baseline) * 100
            is_base = abs(level - baseline) < 1e-9
            parts.append(
                f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{WIDTH - PAD_R}" y2="{y:.1f}" '
                f'class="{"base" if is_base else "grid"}"/>'
            )
            # "+0%" reads as a typo. The baseline is where you started.
            label = "0%" if is_base else f"{pct:+.0f}%"
            parts.append(
                f'<text x="{PAD_L - 8}" y="{y + 3.5:.1f}" '
                f'class="tick{" tick-base" if is_base else ""}" text-anchor="end">{label}</text>'
            )
        level += step
    return "".join(parts)


def equity_chart(
    equity: Sequence[float],
    benchmark: Sequence[float] | None = None,
    *,
    benchmark_label: str = "buy and hold",
    windows: Sequence[tuple[int, int]] | None = None,
    animate: bool = True,
) -> str:
    """Equity against a benchmark, both rebased to their own starting value."""
    if len(equity) < 2:
        return ""

    strategy = _downsample(_rebase(equity))
    series = [strategy]

    bench: list[float] | None = None
    if benchmark and len(benchmark) >= 2:
        rebased = _rebase(benchmark)
        n = len(strategy)
        bench = [rebased[min(int(i * len(rebased) / n), len(rebased) - 1)] for i in range(n)]
        series.append(bench)

    lo = min(min(s) for s in series)
    hi = max(max(s) for s in series)
    # Always keep the starting line in view. A chart that crops it hides
    # whether the account is up or down, which is the first thing to know.
    lo, hi = min(lo, 1.0), max(hi, 1.0)
    pad = (hi - lo) * 0.12 or 0.05
    lo, hi = lo - pad, hi + pad

    parts = [
        f'<svg viewBox="0 0 {WIDTH} {HEIGHT}" width="100%" height="{HEIGHT}" '
        f'role="img" aria-label="Account value over time compared with {benchmark_label}" '
        'class="chart">'
    ]

    if windows:
        inner_w = WIDTH - PAD_L - PAD_R
        for j, (start, end) in enumerate(windows):
            if end <= start or j % 2:
                continue
            x1 = PAD_L + (start / max(len(equity) - 1, 1)) * inner_w
            x2 = PAD_L + (end / max(len(equity) - 1, 1)) * inner_w
            parts.append(
                f'<rect x="{x1:.1f}" y="{PAD_T}" width="{x2 - x1:.1f}" '
                f'height="{HEIGHT - PAD_T - PAD_B}" class="oos"/>'
            )

    parts.append(_grid(lo, hi, HEIGHT))

    draw = ' class="subject drawn"' if animate else ' class="subject"'

    # Both lines end near each other whenever the strategy tracks the market,
    # which is most of the time, and two labels stacked on the same pixel is
    # unreadable exactly when the comparison matters most. Push them apart.
    y_sub = _y(strategy[-1], lo, hi, HEIGHT)
    y_ben = _y(bench[-1], lo, hi, HEIGHT) if bench else None
    sub_label_y, ben_label_y = y_sub + 16, (y_ben - 7) if y_ben is not None else 0.0
    if y_ben is not None and abs(sub_label_y - ben_label_y) < 15:
        # Whichever line finished higher gets the label above.
        if y_sub <= y_ben:
            sub_label_y, ben_label_y = y_sub - 8, y_ben + 17
        else:
            sub_label_y, ben_label_y = y_sub + 17, y_ben - 8

    if bench:
        parts.append(f'<path d="{_path(bench, lo, hi, HEIGHT)}" class="bench"/>')
        parts.append(
            f'<text x="{WIDTH - PAD_R}" y="{ben_label_y:.1f}" '
            f'class="tag bench-tag" text-anchor="end">{benchmark_label}</text>'
        )
    parts.append(f'<path d="{_path(strategy, lo, hi, HEIGHT)}"{draw}/>')
    parts.append(
        f'<text x="{WIDTH - PAD_R}" y="{sub_label_y:.1f}" '
        f'class="tag subject-tag" text-anchor="end">your strategy</text>'
    )

    parts.append(
        f'<text x="{PAD_L}" y="{HEIGHT - 8}" class="tick">start</text>'
        f'<text x="{WIDTH - PAD_R}" y="{HEIGHT - 8}" class="tick" text-anchor="end">'
        f'{len(equity)} steps</text>'
    )
    parts.append("</svg>")

    final = strategy[-1] - 1
    caption = f"strategy {final:+.1%}"
    if bench:
        gap = final - (bench[-1] - 1)
        caption += (
            f" &nbsp;&middot;&nbsp; {benchmark_label} {bench[-1] - 1:+.1%}"
            f" &nbsp;&middot;&nbsp; difference {gap:+.1%}"
        )

    return "".join(parts) + f'<p class="chart-caption">{caption}</p>'


def underwater_chart(equity: Sequence[float], *, animate: bool = True) -> str:
    """Distance below the previous peak, filled, at every moment."""
    if len(equity) < 2:
        return ""

    peak = equity[0]
    drawdowns: list[float] = []
    for value in equity:
        peak = max(peak, value)
        drawdowns.append((value - peak) / peak if peak else 0.0)

    series = _downsample(drawdowns)
    worst = min(series)
    if worst == 0:
        return ""

    height = UNDERWATER_HEIGHT
    lo, hi = worst * 1.12, 0.0
    inner_w = WIDTH - PAD_L - PAD_R
    step = inner_w / (len(series) - 1)

    points = [f"{PAD_L + i * step:.2f},{_y(v, lo, hi, height):.2f}" for i, v in enumerate(series)]
    top = _y(0.0, lo, hi, height)
    area = f"M{PAD_L},{top:.2f}L" + "L".join(points) + f"L{PAD_L + (len(series) - 1) * step:.2f},{top:.2f}Z"

    parts = [
        f'<svg viewBox="0 0 {WIDTH} {height}" width="100%" height="{height}" '
        'role="img" aria-label="Percentage below the previous peak over time" class="chart">',
        _grid(lo, hi, height, baseline=0.0),
        f'<path d="{area}" class="underwater{" grown" if animate else ""}"/>',
        f'<path d="{"M" + "L".join(points)}" class="underwater-line"/>',
        f'<text x="{PAD_L}" y="{height - 8}" class="tick">start</text>',
        f'<text x="{WIDTH - PAD_R}" y="{height - 8}" class="tick" text-anchor="end">'
        f'{len(equity)} steps</text>',
        "</svg>",
        f'<p class="chart-caption">worst {worst:.1%} below the previous peak</p>',
    ]
    return "".join(parts)


def price_chart(
    closes: Sequence[float],
    marks: Sequence[tuple[int, str, float]] = (),
    *,
    label: str = "",
    animate: bool = True,
) -> str:
    """Price over time, with the marks where the rules entered and exited.

    The one chart a person actually asks for when they say "show me what the
    bot is doing". Without it there is no way to tell a strategy correctly
    sitting out a flat market from a data feed that died, and that is the first
    question anyone has about a live run.

    Marks are drawn as triangles rather than dots because entry and exit have
    to be distinguishable in a screenshot, at a glance, in greyscale.
    """
    if len(closes) < 2:
        return ""

    # The marks index into the FULL series, so downsampling has to carry them
    # along or every arrow slides off its candle.
    series = list(closes)
    keep = len(series)
    scale = 1.0
    if keep > MAX_POINTS:
        series = _downsample(series)
        scale = (len(series) - 1) / max(keep - 1, 1)

    lo, hi = min(series), max(series)
    pad = (hi - lo) * 0.1 or (hi * 0.01 or 1.0)
    lo, hi = lo - pad, hi + pad

    inner_w = WIDTH - PAD_L - PAD_R
    step = inner_w / (len(series) - 1)

    def x_at(i: int) -> float:
        return PAD_L + min(i * scale, len(series) - 1) * step

    parts = [
        f'<svg viewBox="0 0 {WIDTH} {HEIGHT}" width="100%" height="{HEIGHT}" '
        f'role="img" aria-label="Price over time with {len(marks)} entries and exits marked" '
        'class="chart">'
    ]

    # Price levels, not percentages: on a price chart the number a person wants
    # is the price.
    span = hi - lo
    tick = _nice_step(span / max(hi, 1e-9)) * max(hi, 1e-9)
    level = lo + (tick - (lo % tick if tick else 0))
    while tick and level < hi:
        y = _y(level, lo, hi, HEIGHT)
        parts.append(
            f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{WIDTH - PAD_R}" y2="{y:.1f}" class="grid"/>'
            f'<text x="{PAD_L - 8}" y="{y + 3.5:.1f}" class="tick" text-anchor="end">'
            f'{level:,.0f}</text>'
        )
        level += tick

    path = "M" + "L".join(
        f"{PAD_L + i * step:.2f},{_y(v, lo, hi, HEIGHT):.2f}" for i, v in enumerate(series)
    )
    parts.append(f'<path d="{path}" class="price{" drawn" if animate else ""}"/>')

    for i, side, price in marks:
        x, y = x_at(i), _y(price, lo, hi, HEIGHT)
        # Buys point up from below the line, sells point down from above it, so
        # direction reads without the colour.
        if side == "buy":
            tri = f"{x:.1f},{y - 4:.1f} {x - 5:.1f},{y + 5:.1f} {x + 5:.1f},{y + 5:.1f}"
        else:
            tri = f"{x:.1f},{y + 4:.1f} {x - 5:.1f},{y - 5:.1f} {x + 5:.1f},{y - 5:.1f}"
        parts.append(f'<polygon points="{tri}" class="mark {side}"/>')

    parts.append(
        f'<text x="{PAD_L}" y="{HEIGHT - 8}" class="tick">{label or "start"}</text>'
        f'<text x="{WIDTH - PAD_R}" y="{HEIGHT - 8}" class="tick" text-anchor="end">'
        f'{len(closes)} closed bars</text>'
        "</svg>"
    )

    buys = sum(1 for _, side, _ in marks if side == "buy")
    sells = len(marks) - buys
    caption = f"last {closes[-1]:,.2f}"
    if marks:
        caption += f" &nbsp;&middot;&nbsp; {buys} entries, {sells} exits"
    else:
        caption += " &nbsp;&middot;&nbsp; no trades taken yet"
    return "".join(parts) + f'<p class="chart-caption">{caption}</p>'


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
