"""Run a system over history and decide whether it may go live.

This is the file that makes this project something other than another trading
bot. The reference design has markets, rules and risk controls, and no answer
at all to "how would I know if this works". Here, that question has to be
answered before the thing is allowed to run.

WHAT THE CHECK ACTUALLY DOES.

Runs the exact system over as much history as the venue will serve, then puts
the result through the same guards that a pasted equity curve goes through: the
impossible Sharpe, the zero drawdown, the perfect win rate, the costless run,
the search dressed up as a test, and losing to buying once and holding.

TRIALS ARE COUNTED, WHICH IS THE PART PEOPLE SKIP.

Every market in a system is a variant that was chosen. A five-market system
where each market's rules were picked from four options is not one test, it is
a selection, and the guards are told the number so they can say so. A system
someone has re-run twenty times with different settings is a search, and the
fingerprint changing on every edit is exactly how that becomes countable.

FAILING IS A RESULT, NOT AN ERROR.

A disqualified system is the check working. The verdict is recorded either way,
because "this was tested and it failed" is more useful than no record at all,
and because the gate needs something to point at when it refuses.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from .engine import PortfolioRun, run_portfolio
from .guards import Severity, check, format_verdict
from .metrics import summarise
from .systems import System, Verification


@dataclass
class Segment:
    """One slice of history, run on its own."""

    index: int
    bars: int
    trades: int
    total_return: float
    benchmark_return: float
    halted: bool = False

    @property
    def beat_holding(self) -> bool:
        return self.total_return > self.benchmark_return


def verify(
    system: System,
    bars: Mapping[str, Sequence[dict]],
    *,
    trials: int | None = None,
    windows: int = 4,
) -> tuple[Verification, PortfolioRun]:
    """Run the system over history and judge it. Returns the verdict and the run."""
    run = run_portfolio(
        list(system.markets), bars,
        starting_cash=system.starting_cash,
        sizing=system.sizing,
        limits=system.limits,
    )

    if len(run.equity) < 2:
        return Verification(
            fingerprint=system.fingerprint, at=time.time(), passed=False,
            summary="not enough history came back to judge anything",
        ), run

    # Closed round trips AND anything still open. Checking only closed trades
    # reported "took no trades" for a system that had bought and was still
    # holding, which is the opposite of the truth and would have refused the
    # simplest system anyone could write.
    if not run.portfolio.trades and not run.portfolio.holdings:
        # Not a dishonest result, just an empty one, and the guards are built to
        # catch dishonesty rather than inactivity. Clearing a system that never
        # traded would mean the gate opened on no evidence at all.
        return Verification(
            fingerprint=system.fingerprint, at=time.time(), passed=False,
            summary="took no trades over this history, so there is nothing to judge",
            benchmark_return=run.benchmark_return, bars=len(run.equity),
        ), run

    pnls = [t.pnl for t in run.portfolio.trades]
    result = summarise(run.equity, pnls)

    verdict = check(
        result,
        # Each market's rules were chosen from the built-in set. Counting that
        # is the difference between reporting a test and reporting a search.
        trials=trials if trials is not None else max(1, len(system.markets)),
        costs_applied=run.portfolio.costs_paid,
        # NOT False, and this took a closed gate to work out. The survivorship
        # guard is fatal because a cross-sectional backtest that dropped dead
        # assets is measuring a universe that never existed. A system trading
        # five named instruments has no universe: it makes no claim about all
        # coins or all stocks, so the guard fires outside its domain and
        # disqualifies every system that could ever be written, permanently.
        #
        # The bias is real at the selection level and is stated below instead,
        # because a gate nothing can pass teaches people to route around it.
        delisted_included=None,
        benchmark_return=run.benchmark_return,
    )

    findings = [f"{f.severity.value}: {f.detail}" for f in verdict.findings]
    findings.append(
        "warn: these instruments were chosen today, knowing which ones survived. "
        f"{', '.join(m.symbol for m in system.markets)} are not a random sample "
        "of what a person could have picked at the start of this history, and no "
        "backtest can correct for the ones you would have chosen instead."
    )
    fatal = [f for f in verdict.findings if f.severity is Severity.FATAL]

    # A run that stopped itself is not a run over this history, and reporting
    # its return as though it were is the same class of error as omitting costs.
    # Found the hard way: a system halted 6% in produced zero trades and zero
    # complaints for the other 94%, and read as rules that never fired.
    if run.halted_at is not None:
        share = run.halted_at / max(len(run.equity), 1)
        findings.insert(0, (
            f"fatal: stopped itself {share:.0%} of the way through this history "
            f"and took no further positions. {run.breach.detail if run.breach else ''}"
        ))

    slices = segments(system, bars, windows=windows) if windows > 1 else []
    consistency = stability(slices)
    if consistency:
        # A warning rather than a disqualification. One window out of four is a
        # bad sign and not a lie, and the guards are for lies.
        findings.append(f"warn: {consistency}")

    if run.halted_at is not None:
        summary = (
            f"halted {run.halted_at / max(len(run.equity), 1):.0%} in, so this "
            "measures a system that switched off rather than one that ran"
        )
    elif fatal:
        summary = fatal[0].detail
    elif findings:
        summary = f"nothing disqualifying, {len(findings)} thing(s) worth knowing"
    else:
        summary = "nothing the guards object to"

    return Verification(
        fingerprint=system.fingerprint,
        at=time.time(),
        # A halted run cannot clear the gate whatever the guards say about the
        # arithmetic, because the arithmetic describes a stopped system.
        passed=verdict.reportable and run.halted_at is None,
        summary=summary,
        findings=findings,
        total_return=run.total_return,
        benchmark_return=run.benchmark_return,
        trades=len(run.portfolio.trades),
        bars=len(run.equity),
        halted_at=run.halted_at,
        halt_reason=run.breach.detail if run.breach else "",
        windows=[
            [s.index, s.total_return, s.benchmark_return, s.trades, s.halted]
            for s in slices
        ],
        stability=consistency or "",
    ), run


def split_by_time(
    bars: Mapping[str, Sequence[dict]], windows: int,
) -> list[dict[str, list[dict]]]:
    """Cut every market at the same instants, into ``windows`` contiguous spans.

    By time, not by index. Splitting each symbol's list into equal counts would
    put a 4-hour commodity's window three months away from a 15-minute index's
    window with the same number, and the correlation rules would be reasoning
    across dates that never overlapped.
    """
    stamps = [float(b.get("timestamp", 0)) for series in bars.values() for b in series]
    if not stamps or windows < 2:
        return [{k: list(v) for k, v in bars.items()}]

    first, last = min(stamps), max(stamps)
    if last <= first:
        return [{k: list(v) for k, v in bars.items()}]

    span = (last - first) / windows
    out: list[dict[str, list[dict]]] = []
    for i in range(windows):
        low = first + span * i
        high = last + 1 if i == windows - 1 else first + span * (i + 1)
        out.append({
            symbol: [b for b in series if low <= float(b.get("timestamp", 0)) < high]
            for symbol, series in bars.items()
        })
    return out


def segments(
    system: System,
    bars: Mapping[str, Sequence[dict]],
    *,
    windows: int = 4,
) -> list[Segment]:
    """Run the system separately on each slice of history.

    NOT walk-forward in the parameter-fitting sense, and the distinction is
    worth keeping straight. Classic walk-forward fits on one window and measures
    on the next, which needs an optimiser to fit something. These systems have
    fixed rules, so there is nothing to fit and nothing to carry forward.

    What there is instead is a selection: somebody chose these markets, these
    rules and these settings, all at once, after seeing the whole period. The
    question that answers is not "do the parameters hold up" but "did this work
    in more than one stretch, or did a single lucky window carry the headline".

    Each window starts with a fresh account and no halt, so a stop in window one
    cannot silence window four. That is deliberate: the point is to see each
    stretch on its own terms.
    """
    out: list[Segment] = []
    for i, slice_ in enumerate(split_by_time(bars, windows), start=1):
        if sum(len(v) for v in slice_.values()) < 30:
            continue
        run = run_portfolio(
            list(system.markets), slice_,
            starting_cash=system.starting_cash,
            sizing=system.sizing, limits=system.limits,
        )
        if len(run.equity) < 2:
            continue
        out.append(Segment(
            index=i,
            bars=len(run.equity),
            trades=len(run.portfolio.trades),
            total_return=run.total_return,
            benchmark_return=run.benchmark_return,
            halted=run.halted_at is not None,
        ))
    return out


def stability(windows: Sequence[Segment]) -> str | None:
    """The one sentence the windows are worth, or None if there are too few.

    Deliberately reports rather than judges. Two winning windows out of four is
    not a verdict, and inventing a threshold to turn it into one would be the
    arbitrary-number habit this project exists to complain about.
    """
    if len(windows) < 2:
        return None

    won = [w for w in windows if w.beat_holding]
    profitable = [w for w in windows if w.total_return > 0]
    halted = [w for w in windows if w.halted]

    parts = [
        f"beat holding in {len(won)} of {len(windows)} windows",
        f"made money in {len(profitable)}",
    ]
    if halted:
        parts.append(f"stopped itself in {len(halted)}")

    sentence = ", ".join(parts) + "."
    if len(windows) >= 3 and not won:
        sentence += (
            " It did not beat holding in a single window, so the headline is "
            "not a run of bad luck inside a system that works."
        )
    elif len(windows) >= 3 and len(won) == 1:
        sentence += (
            " A result carried by one window out of several is the shape of "
            "something fitted to a stretch of history rather than something "
            "that works."
        )
    return sentence


def fetch_history(
    system: System,
    *,
    limit: int = 1000,
    fetch: Callable[..., object] | None = None,
) -> dict[str, list[dict]]:
    """Pull bars for every market in a system, dropping the forming candle.

    The still-forming bar is dropped here as well as in the live loop. A
    verification that included it would be judging a system on a price that had
    not finished happening, which is the same lookahead the property test
    exists to catch, arriving through the back door.
    """
    if fetch is None:
        fetch = _fetch_for(system.venue)

    out: dict[str, list[dict]] = {}
    for market in system.markets:
        universe = fetch(system.venue, market.symbol, timeframe=market.timeframe,
                         limit=limit)
        bars = list(universe.bars)
        out[market.symbol] = bars[:-1] if bars else []
    return out


def _fetch_for(venue: str):
    """Pick the fetcher for a venue, matching the signature the callers use."""
    if venue == "public":
        from .public_data import fetch as public_fetch

        def adapter(_venue, symbol, *, timeframe="1d", limit=1000):
            return public_fetch(symbol, timeframe=timeframe, limit=limit)

        return adapter

    from .data import fetch_ohlcv

    return fetch_ohlcv


def explain(verification: Verification) -> str:
    """The verdict as a person would say it."""
    if verification.passed:
        head = "Cleared to run."
    else:
        head = "Not cleared to run."

    lines = [
        head,
        f"  over {verification.bars} steps and {verification.trades} trades",
        f"  returned {verification.total_return:+.1%} against "
        f"{verification.benchmark_return:+.1%} for buying and holding",
        f"  {verification.summary}",
    ]
    if verification.halted_at is not None:
        lines.insert(1, f"  it stopped itself: {verification.halt_reason}")

    if verification.windows:
        lines += ["", "  window by window"]
        for index, ret, bench, trades, halted in verification.windows:
            mark = "  stopped" if halted else ""
            lines.append(
                f"    {index}  {ret:+7.1%} against {bench:+7.1%} holding, "
                f"{trades} trades{mark}"
            )
    if verification.stability:
        lines += ["", f"  {verification.stability}"]

    if verification.findings:
        lines.append("")
        lines += [f"  {f}" for f in verification.findings]
    if verification.passed and not verification.beat_holding:
        lines += [
            "",
            "  Passing the checks is not the same as being worth running. This "
            "one finished behind doing nothing.",
        ]
    return "\n".join(lines)
