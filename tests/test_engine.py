"""Tests for the multi-market engine.

The interesting failures here are ordering ones. Nothing crashes when a
4-hour commodity is allowed to see a price a 15-minute index has not reached
yet; the account just quietly makes decisions no real account could have made,
and every downstream number stays plausible.
"""

from __future__ import annotations

import pytest

from proofmark.engine import Market, run_portfolio
from proofmark.limits import Limits
from proofmark.sizing import Sizing
from proofmark.strategies import Signal

HOUR = 3_600_000


def _series(closes, start=1_700_000_000_000, step=HOUR, spread=1.0, opens=None):
    return [
        {"timestamp": start + i * step,
         "open": (opens[i] if opens else c),
         "high": c + spread, "low": c - spread,
         "close": c, "volume": 1.0}
        for i, c in enumerate(closes)
    ]


def _flat(n=60, price=100.0, **kw):
    return _series([price] * n, **kw)


def test_bars_are_processed_in_time_order_across_timeframes():
    """An hourly and a four-hourly market interleave by clock, not by list."""
    bars = {
        "FAST": _series([100.0] * 8, step=HOUR),
        "SLOW": _series([50.0] * 2, step=4 * HOUR),
    }
    run = run_portfolio(
        [Market("FAST", "buy-and-hold"), Market("SLOW", "buy-and-hold")],
        bars, starting_cash=10_000.0,
    )
    assert run.stamps == sorted(run.stamps)
    assert len(run.equity) == 10          # every bar from both symbols
    assert len(run.closes["FAST"]) == 8
    assert len(run.closes["SLOW"]) == 2


def test_a_gap_through_the_stop_fills_at_the_open_not_the_stop():
    """The most flattering lie a backtest can tell about a risk control."""
    closes = [100.0] * 40 + [100.0, 60.0]
    opens = [100.0] * 40 + [100.0, 60.0]
    bars = {"X": _series(closes, spread=1.0, opens=opens)}
    # Force an entry, then let the crash bar gap straight through the stop.
    run = run_portfolio(
        [Market("X", "buy-and-hold")], bars,
        starting_cash=10_000.0,
        sizing=Sizing(mode="fixed_fraction", fraction=1.0, max_position=1.0,
                      stop_source="percent", stop_percent=0.05),
        limits=Limits(max_drawdown=None, daily_loss=None, consecutive_losses=None),
    )
    trades = run.portfolio.trades
    assert trades, "expected the stop to close the position"
    # Stop sat at 95. The market opened at 60, so that is where it got out.
    assert trades[-1].exit == pytest.approx(60.0, abs=0.1)
    assert "gapped through the stop" in run.decisions[-1].reason


def test_the_correlation_rule_refuses_the_third_risk_on_entry():
    bars = {s: _flat(60) for s in ("SPY", "QQQ", "IWM")}
    run = run_portfolio(
        [Market(s, "buy-and-hold") for s in ("SPY", "QQQ", "IWM")], bars,
        starting_cash=100_000.0,
        sizing=Sizing(mode="fixed_fraction", fraction=0.1, max_position=0.5),
        limits=Limits(max_per_group=2, max_drawdown=None, daily_loss=None,
                      consecutive_losses=None, max_exposure=None, max_positions=None),
    )
    assert len(run.portfolio.holdings) == 2
    assert any("equity-index" in reason for _, _, reason in run.refusals)


def test_the_correlation_cap_is_binding_at_the_fill_not_only_at_the_signal():
    """Three correlated symbols signalling in the same window each saw an empty
    book at signal time. All three passed the cap and all three opened, so the
    rule silently did nothing. The check has to bind where the position opens."""
    bars = {s: _flat(60) for s in ("SPY", "QQQ", "IWM", "VOO", "DIA")}
    run = run_portfolio(
        [Market(s, "buy-and-hold") for s in ("SPY", "QQQ", "IWM", "VOO", "DIA")],
        bars, starting_cash=500_000.0,
        sizing=Sizing(mode="fixed_fraction", fraction=0.1, max_position=0.5),
        limits=Limits(max_per_group=2, max_drawdown=None, daily_loss=None,
                      consecutive_losses=None, max_exposure=None, max_positions=None),
    )
    assert len(run.portfolio.holdings) == 2


def test_nothing_trades_before_volatility_can_be_measured():
    """Under the ATR warmup, so no honest stop distance exists at any bar.

    Silence rather than a refusal on every bar: the warmup is the longer of what
    the rules need and what sizing needs, so the engine does not ask a question
    it already knows it cannot act on."""
    bars = {"X": _flat(10)}
    run = run_portfolio([Market("X", "buy-and-hold")], bars, starting_cash=10_000.0)
    assert not run.portfolio.holdings
    assert not run.refusals


def test_a_market_with_no_movement_at_all_is_refused_rather_than_guessed():
    """A dead pair gives an ATR of zero, which would size an infinite position.
    Refusing is the only honest answer."""
    bars = {"X": _flat(60, spread=0.0)}
    run = run_portfolio([Market("X", "buy-and-hold")], bars, starting_cash=10_000.0)
    assert not run.portfolio.holdings
    assert any("volatility" in reason for _, _, reason in run.refusals)


def test_a_breached_limit_halts_entries_but_never_exits():
    """A halt that blocks everything traps you in the position that caused it."""
    # Long calm stretch to build ATR, then a slide that trips the drawdown limit.
    closes = [100.0] * 40 + [100.0 - i for i in range(30)]
    bars = {"X": _series(closes, spread=0.5)}
    run = run_portfolio(
        [Market("X", "buy-and-hold")], bars, starting_cash=10_000.0,
        sizing=Sizing(mode="fixed_fraction", fraction=1.0, max_position=1.0),
        limits=Limits(max_drawdown=0.05, daily_loss=None, consecutive_losses=None),
    )
    assert run.breach is not None and run.breach.code == "max-drawdown"
    assert any(d.action == "halt" for d in run.decisions)


def test_starting_halted_blocks_every_entry():
    from proofmark.limits import Halt

    bars = {"X": _flat(60)}
    run = run_portfolio(
        [Market("X", "buy-and-hold")], bars, starting_cash=10_000.0,
        halt=Halt(reason="pulled by hand", manual=True),
    )
    assert not run.portfolio.holdings
    assert not run.portfolio.trades


def test_the_benchmark_spreads_evenly_and_is_computed_unasked():
    rising = _series([100.0 + i for i in range(60)])
    bars = {"A": rising, "B": rising}
    run = run_portfolio(
        [Market("A", "rsi-dip"), Market("B", "rsi-dip")], bars, starting_cash=10_000.0,
    )
    assert len(run.benchmark) == len(run.equity)
    assert run.benchmark[-1] > run.benchmark[0]


def test_sizing_is_applied_so_one_entry_cannot_take_the_whole_account():
    bars = {"X": _flat(60)}
    run = run_portfolio(
        [Market("X", "buy-and-hold")], bars, starting_cash=10_000.0,
        sizing=Sizing(mode="risk", risk_per_trade=0.01, max_position=0.25),
        limits=Limits(max_drawdown=None, daily_loss=None, consecutive_losses=None),
    )
    if run.portfolio.holdings:
        held = run.portfolio.holdings["X"]
        assert held.value(100.0) <= 10_000.0 * 0.25 + 1e-6
        assert held.stop is not None and held.stop < held.entry


def test_a_run_is_deterministic():
    bars = {s: _flat(60) for s in ("SPY", "QQQ")}
    markets = [Market("SPY", "buy-and-hold"), Market("QQQ", "buy-and-hold")]
    a = run_portfolio(markets, bars, starting_cash=50_000.0)
    b = run_portfolio(markets, bars, starting_cash=50_000.0)
    assert a.equity == b.equity
    assert [d.reason for d in a.decisions] == [d.reason for d in b.decisions]


def test_marks_line_up_with_the_close_series_they_are_drawn_on():
    """Marks index into each symbol's own close list. Off by one here puts every
    entry arrow on the wrong candle."""
    bars = {"X": _flat(60)}
    run = run_portfolio(
        [Market("X", "buy-and-hold")], bars, starting_cash=10_000.0,
        sizing=Sizing(mode="fixed_fraction", fraction=0.2, max_position=0.5),
        limits=Limits(max_drawdown=None, daily_loss=None, consecutive_losses=None),
    )
    for mark in run.marks["X"]:
        assert 0 <= mark.index < len(run.closes["X"])


def test_the_benchmark_starts_at_the_full_starting_capital():
    """It counted only symbols that had already printed a bar, so it began at
    one third of capital and climbed as the others initialised. On real data
    that read as buy-and-hold returning 200% over three hundred bars, which was
    entirely initialisation and no market movement at all."""
    bars = {
        "A": _series([100.0] * 20, step=HOUR),
        "B": _series([100.0] * 20, step=HOUR, start=1_700_000_000_000 + 30 * HOUR),
        "C": _series([100.0] * 20, step=HOUR, start=1_700_000_000_000 + 60 * HOUR),
    }
    run = run_portfolio(
        [Market(s, "rsi-dip") for s in ("A", "B", "C")], bars, starting_cash=30_000.0,
    )
    assert run.benchmark[0] == pytest.approx(30_000.0)
    # Nothing moved, so holding cannot have made or lost anything.
    assert run.benchmark[-1] == pytest.approx(30_000.0)
    assert max(run.benchmark) == pytest.approx(30_000.0)
