"""Tests for the guards and the lookahead detector.

The important half is the false-positive half. A guard that fires on an honest
backtest gets switched off within a day, and then the real findings go unread
too.
"""

from __future__ import annotations

import math

import pytest

from proofmark.guards import Severity, check
from proofmark.lookahead import assert_no_lookahead, check_lookahead
from proofmark.metrics import equity_drawdown, sortino, summarise


# ------------------------------------------------------------------ metrics --

def test_drawdown_is_measured_from_equity_not_realised_pnl():
    # Underwater the whole way, then recovers. Realised-PnL drawdown would be
    # zero here because the position never closes at a loss.
    equity = [100.0, 80.0, 60.0, 90.0, 110.0]
    assert equity_drawdown(equity) == pytest.approx(0.4)


def test_sortino_is_none_with_no_losing_bars():
    assert sortino([0.01, 0.02, 0.03]) is None


def test_no_metric_ever_returns_a_sentinel():
    # The failure this exists to prevent: -100.0 printed as a headline number.
    equity = [100.0 * (1.01 ** i) for i in range(50)]
    result = summarise(equity, trade_pnls=[1.0] * 10)
    for value in (result.sharpe, result.sortino, result.calmar, result.profit_factor):
        assert value is None or math.isfinite(value)
        assert value != -100.0


# ------------------------------------------------------------------- guards --

def _clean_result():
    """A believable losing-and-winning strategy that should pass every guard."""
    equity = [100.0]
    for step in [1.01, 0.98, 1.02, 0.97, 1.03, 0.99, 1.01] * 12:
        equity.append(equity[-1] * step)
    pnls = [1.0, -0.8, 1.2, -0.5] * 10
    return summarise(equity, pnls)


def test_FALSE_POSITIVE_an_honest_backtest_is_reportable():
    verdict = check(_clean_result(), trials=1, costs_applied=42.0, delisted_included=True)
    assert verdict.reportable, verdict.fatal
    assert not verdict.fatal


def test_zero_drawdown_suppresses_the_report():
    equity = [100.0 + i for i in range(50)]  # only ever goes up
    verdict = check(summarise(equity, [1.0] * 10), costs_applied=1.0, delisted_included=True)
    assert not verdict.reportable
    assert any(f.code == "zero-drawdown" for f in verdict.fatal)


def test_perfect_win_rate_suppresses_the_report():
    equity = [100.0, 90.0, 120.0, 110.0, 130.0]
    verdict = check(summarise(equity, [1.0] * 45), costs_applied=1.0, delisted_included=True)
    assert any(f.code == "perfect-win-rate" for f in verdict.fatal)


def test_zero_costs_with_trades_suppresses_the_report():
    verdict = check(_clean_result(), costs_applied=0.0, delisted_included=True)
    assert any(f.code == "no-costs-applied" for f in verdict.fatal)


def test_a_large_search_suppresses_the_report():
    verdict = check(_clean_result(), trials=200, costs_applied=1.0, delisted_included=True)
    assert any(f.code == "search-without-correction" for f in verdict.fatal)


def test_a_small_search_warns_but_still_reports():
    verdict = check(_clean_result(), trials=5, costs_applied=1.0, delisted_included=True)
    assert verdict.reportable
    assert any(f.code == "multiple-testing" for f in verdict.findings)


def test_survivors_only_universe_suppresses_the_report():
    verdict = check(_clean_result(), costs_applied=1.0, delisted_included=False)
    assert any(f.code == "survivors-only" for f in verdict.fatal)


def test_unstated_survivorship_warns_rather_than_assuming():
    verdict = check(_clean_result(), costs_applied=1.0, delisted_included=None)
    assert verdict.reportable
    assert any(f.code == "survivorship-unknown" for f in verdict.findings)


def test_undefined_ratios_are_warned_not_printed():
    equity = [100.0 * (1.01 ** i) for i in range(40)]
    verdict = check(summarise(equity, [1.0, -1.0] * 20), costs_applied=1.0, delisted_included=True)
    codes = {f.code for f in verdict.findings}
    assert "undefined-sortino" in codes or "undefined-calmar" in codes


# ---------------------------------------------------------------- lookahead --

def _bars(n: int = 60) -> list[dict[str, float]]:
    out = []
    price = 100.0
    for i in range(n):
        price *= 1.01 if i % 3 else 0.99
        out.append({
            "timestamp": i,
            "open": price,
            "high": price * 1.02,
            "low": price * 0.98,
            "close": price * 1.005,
            "volume": 1000.0 + i,
        })
    return out


def honest_strategy(bars):
    """Decides using only bars strictly before t, executed at t's open."""
    decisions = []
    for t in range(len(bars)):
        window = bars[max(0, t - 5):t]
        if len(window) < 5:
            decisions.append("flat")
            continue
        avg = sum(b["close"] for b in window) / len(window)
        decisions.append("long" if window[-1]["close"] > avg else "flat")
    return decisions


def leaky_strategy(bars):
    """Peeks at the next bar. This is the bug, written deliberately."""
    decisions = []
    for t in range(len(bars)):
        if t + 1 >= len(bars):
            decisions.append("flat")
            continue
        decisions.append("long" if bars[t + 1]["close"] > bars[t]["close"] else "flat")
    return decisions


def same_bar_close_strategy(bars):
    """Uses bar t's own close. Legal at close, illegal at open."""
    return ["long" if b["close"] > b["open"] else "flat" for b in bars]


def test_FALSE_POSITIVE_an_honest_strategy_is_clean():
    report = check_lookahead(honest_strategy, _bars(), executes_at="open")
    assert report.clean, str(report)


def test_a_peeking_strategy_is_caught():
    report = check_lookahead(leaky_strategy, _bars(), executes_at="open")
    assert not report.clean
    assert len(report.leaks) > 10


def test_execution_timing_changes_what_counts_as_the_future():
    bars = _bars()
    # Using this bar's close is fine if you execute at this bar's close...
    assert check_lookahead(same_bar_close_strategy, bars, executes_at="close").clean
    # ...and is lookahead if you execute at this bar's open.
    assert not check_lookahead(same_bar_close_strategy, bars, executes_at="open").clean


def test_assert_helper_raises_on_a_leak():
    with pytest.raises(AssertionError, match="LOOKAHEAD"):
        assert_no_lookahead(leaky_strategy, _bars())


def test_a_strategy_returning_the_wrong_shape_is_rejected():
    with pytest.raises(ValueError, match="one decision per bar"):
        check_lookahead(lambda bars: ["flat"], _bars())


def test_the_detector_is_deterministic():
    bars = _bars()
    first = check_lookahead(leaky_strategy, bars, seed=7)
    second = check_lookahead(leaky_strategy, bars, seed=7)
    assert [l.bar for l in first.leaks] == [l.bar for l in second.leaks]
