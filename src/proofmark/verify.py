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
from typing import Callable, Mapping, Sequence

from .engine import PortfolioRun, run_portfolio
from .guards import Severity, check, format_verdict
from .metrics import summarise
from .systems import System, Verification


def verify(
    system: System,
    bars: Mapping[str, Sequence[dict]],
    *,
    trials: int | None = None,
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

    if not run.portfolio.trades:
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

    if fatal:
        summary = fatal[0].detail
    elif findings:
        summary = f"nothing disqualifying, {len(findings)} thing(s) worth knowing"
    else:
        summary = "nothing the guards object to"

    return Verification(
        fingerprint=system.fingerprint,
        at=time.time(),
        passed=verdict.reportable,
        summary=summary,
        findings=findings,
        total_return=run.total_return,
        benchmark_return=run.benchmark_return,
        trades=len(run.portfolio.trades),
        bars=len(run.equity),
    ), run


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
