"""Tests for the risk layer: portfolio, sizing and limits.

Weighted towards the failures that cost money rather than the ones that raise
exceptions. A sizing bug does not crash, it just quietly puts four times too
much into a position, and the only thing that catches it is an assertion about
the arithmetic.
"""

from __future__ import annotations

import pytest

from proofmark.limits import (
    DEFAULT_GROUPS, Breach, HaltFile, Limits, blocked_reason, check_limits,
)
from proofmark.portfolio import Portfolio
from proofmark.sizing import Sizing, atr, position_size, stop_price, true_range


def _bars(closes, high_pad=1.0, low_pad=1.0):
    return [
        {"timestamp": 1_700_000_000_000 + i * 3_600_000,
         "open": c, "high": c + high_pad, "low": c - low_pad,
         "close": c, "volume": 1.0}
        for i, c in enumerate(closes)
    ]


# ------------------------------------------------------------- portfolio ----

def test_a_position_cannot_cost_more_than_the_cash_available():
    p = Portfolio(cash=1000.0, fee=0.001, slippage=0.0)
    assert p.buy("SPY", price=100.0, quantity=50) is None   # 5000 > 1000
    assert p.cash == 1000.0
    assert not p.holds("SPY")


def test_buying_a_symbol_already_held_is_refused_not_averaged():
    """Averaging in moves the entry price, which silently invalidates the stop
    distance the position was sized against."""
    p = Portfolio(cash=10_000.0, slippage=0.0)
    first = p.buy("SPY", price=100.0, quantity=10, stop=95.0)
    again = p.buy("SPY", price=90.0, quantity=10, stop=85.0)
    assert first is not None and again is None
    assert p.holdings["SPY"].entry == 100.0
    assert p.holdings["SPY"].stop == 95.0


def test_equity_counts_cash_and_positions_together():
    p = Portfolio(cash=10_000.0, fee=0.0, slippage=0.0)
    p.buy("SPY", price=100.0, quantity=50)
    assert p.equity({"SPY": 100.0}) == pytest.approx(10_000.0)
    assert p.equity({"SPY": 110.0}) == pytest.approx(10_500.0)


def test_a_position_with_no_quote_is_held_at_cost_not_dropped():
    """The safer of two wrong answers. Dropping it makes the account look like
    it just lost the whole position."""
    p = Portfolio(cash=10_000.0, fee=0.0, slippage=0.0)
    p.buy("SPY", price=100.0, quantity=50)
    assert p.equity({}) == pytest.approx(10_000.0)


def test_round_trip_pnl_includes_the_cost_of_both_sides():
    p = Portfolio(cash=10_000.0, fee=0.01, slippage=0.0)
    p.buy("SPY", price=100.0, quantity=50)
    trade = p.sell("SPY", price=100.0)
    assert trade is not None
    # Flat price, two 1% fees on 5,000 notional.
    assert trade.pnl == pytest.approx(-100.0, abs=1.0)
    assert trade.won is False


def test_stops_are_checked_against_the_low_not_the_close():
    """A stop that only triggers on closes is a hope, and the difference shows
    up on exactly the bars it existed to protect against."""
    p = Portfolio(cash=10_000.0, slippage=0.0)
    p.buy("SPY", price=100.0, quantity=50, stop=95.0)
    assert p.stopped_out({"SPY": 96.0}) == []
    assert p.stopped_out({"SPY": 94.0}) == ["SPY"]


def test_risk_falls_to_zero_once_the_stop_is_above_entry():
    p = Portfolio(cash=10_000.0, slippage=0.0)
    holding = p.buy("SPY", price=100.0, quantity=50, stop=105.0)
    assert holding.risk(110.0) == pytest.approx(250.0)
    assert holding.risk(104.0) == 0.0


# ---------------------------------------------------------------- sizing ----

def test_risk_sizing_loses_exactly_the_configured_fraction_at_the_stop():
    """The whole point of the mode. If this number drifts, the number the user
    configured is not the number they are risking."""
    policy = Sizing(mode="risk", risk_per_trade=0.01, max_position=1.0)
    quantity = position_size(100_000.0, 100_000.0, price=100.0, policy=policy, stop=98.0)
    loss_at_stop = quantity * (100.0 - 98.0)
    assert loss_at_stop == pytest.approx(1000.0)   # 1% of 100k


def test_a_wider_stop_buys_less_so_the_risk_stays_constant():
    """This is what 'sizing adjusted to volatility' actually means."""
    # Risk kept small so neither result runs into the cash or position caps;
    # this is testing the ratio the stop distance produces, nothing else.
    policy = Sizing(mode="risk", risk_per_trade=0.001, max_position=1.0)
    tight = position_size(100_000.0, 100_000.0, price=100.0, policy=policy, stop=99.0)
    wide = position_size(100_000.0, 100_000.0, price=100.0, policy=policy, stop=95.0)
    assert tight > wide
    # Five times the stop distance, one fifth the position, same money at risk.
    assert tight == pytest.approx(wide * 5.0)
    assert tight * 1.0 == pytest.approx(wide * 5.0)


def test_risk_sizing_refuses_the_trade_when_there_is_no_usable_stop():
    policy = Sizing(mode="risk")
    assert position_size(10_000.0, 10_000.0, price=100.0, policy=policy, stop=None) == 0.0
    assert position_size(10_000.0, 10_000.0, price=100.0, policy=policy, stop=101.0) == 0.0


def test_the_position_cap_beats_every_mode():
    """A stop that rounds to nearly nothing in a quiet market would otherwise
    put the whole account into one trade and call it correct."""
    policy = Sizing(mode="risk", risk_per_trade=0.01, max_position=0.25)
    quantity = position_size(10_000.0, 10_000.0, price=100.0, policy=policy, stop=99.99)
    assert quantity * 100.0 == pytest.approx(2500.0)


def test_size_never_exceeds_the_cash_on_hand():
    policy = Sizing(mode="fixed_notional", notional=50_000.0, max_position=1.0)
    quantity = position_size(1000.0, 1000.0, price=10.0, policy=policy)
    assert quantity * 10.0 <= 1000.0


def test_whole_units_round_down_never_up():
    policy = Sizing(mode="fixed_notional", notional=1050.0, max_position=1.0)
    assert position_size(10_000.0, 10_000.0, 100.0, policy=policy, whole_units=True) == 10.0


def test_atr_is_none_until_there_is_enough_history_to_mean_anything():
    assert atr(_bars(list(range(100, 105)))) is None
    assert atr(_bars([100.0] * 40)) is not None


def test_true_range_counts_an_overnight_gap():
    """Ignoring gaps is how an equities system ends up with stops sized for a
    market that never closes."""
    gapped = [
        {"open": 100, "high": 101, "low": 99, "close": 100},
        {"open": 120, "high": 121, "low": 119, "close": 120},
    ]
    assert true_range(gapped) == pytest.approx(21.0)   # 121 - 100, not 121 - 119


def test_a_calmer_market_produces_a_tighter_atr_stop():
    calm = stop_price(_bars([100.0] * 40, high_pad=0.5, low_pad=0.5), Sizing())
    wild = stop_price(_bars([100.0] * 40, high_pad=5.0, low_pad=5.0), Sizing())
    assert calm > wild


def test_percent_stops_do_not_react_to_volatility_at_all():
    """Documented so nobody 'fixes' it later: this is the mode's actual
    behaviour, and the reason it is not the default."""
    policy = Sizing(stop_source="percent", stop_percent=0.02)
    calm = stop_price(_bars([100.0] * 40, high_pad=0.5, low_pad=0.5), policy)
    wild = stop_price(_bars([100.0] * 40, high_pad=5.0, low_pad=5.0), policy)
    assert calm == wild == pytest.approx(98.0)


def test_nonsense_sizing_settings_are_refused_at_construction():
    with pytest.raises(ValueError):
        Sizing(max_position=1.5)
    with pytest.raises(ValueError):
        Sizing(risk_per_trade=0)
    with pytest.raises(ValueError):
        Sizing(atr_multiple=-1)


# ---------------------------------------------------------------- limits ----

def test_drawdown_limit_fires_on_the_high_water_mark_not_the_start():
    breach = check_limits(Portfolio(cash=0), [100, 130, 100], Limits(max_drawdown=0.20))
    assert breach is not None and breach.code == "max-drawdown"


def test_daily_loss_is_measured_from_the_session_open():
    limits = Limits(daily_loss=0.03, max_drawdown=None, consecutive_losses=None)
    assert check_limits(Portfolio(cash=0), [100, 98], limits, session_equity_open=100) is None
    breach = check_limits(Portfolio(cash=0), [100, 96], limits, session_equity_open=100)
    assert breach is not None and breach.code == "daily-loss"


def test_clearing_a_halt_stops_the_same_breach_firing_again():
    """The bug this whole design exists to avoid. replay() recomputes the run
    every poll, so without a window the resume button does nothing at all."""
    curve = [100, 130, 100, 101, 102]
    limits = Limits(max_drawdown=0.20, daily_loss=None, consecutive_losses=None)
    assert check_limits(Portfolio(cash=0), curve, limits) is not None
    # Resumed at bar 2, after the drawdown that caused it.
    assert check_limits(Portfolio(cash=0), curve, limits, since_index=2) is None


def test_a_losing_streak_only_counts_trades_since_the_clear():
    p = Portfolio(cash=100_000.0, fee=0.0, slippage=0.0)
    for i in range(4):
        p.buy("SPY", price=100.0, quantity=1)
        p.sell("SPY", price=90.0, index=i)          # four losses, bars 0 to 3
    limits = Limits(consecutive_losses=3, max_drawdown=None, daily_loss=None)

    assert check_limits(p, [100, 90], limits).code == "losing-streak"
    assert check_limits(p, [100, 90], limits, since_index=3) is None


def test_a_winning_trade_breaks_the_streak():
    p = Portfolio(cash=100_000.0, fee=0.0, slippage=0.0)
    p.buy("SPY", 100.0, 1); p.sell("SPY", 90.0, index=0)
    p.buy("SPY", 100.0, 1); p.sell("SPY", 90.0, index=1)
    p.buy("SPY", 100.0, 1); p.sell("SPY", 120.0, index=2)
    limits = Limits(consecutive_losses=2, max_drawdown=None, daily_loss=None)
    assert check_limits(p, [100, 100], limits) is None


# ------------------------------------------------------------- exposure ----

def test_correlated_positions_block_a_third_risk_on_trade():
    """The reference design's example, exactly: NASDAQ and S&P already long."""
    p = Portfolio(cash=100_000.0, slippage=0.0)
    p.buy("SPY", 100.0, 10)
    p.buy("QQQ", 100.0, 10)
    limits = Limits(max_per_group=2, max_exposure=None, max_positions=None)

    reason = blocked_reason("IWM", p, {"SPY": 100.0, "QQQ": 100.0}, limits)
    assert reason is not None and "equity-index" in reason
    # A different group is unaffected. The rule is about correlation, not count.
    assert blocked_reason("GLD", p, {"SPY": 100.0, "QQQ": 100.0}, limits) is None


def test_an_unknown_symbol_is_its_own_group_rather_than_lumped_in():
    p = Portfolio(cash=100_000.0, slippage=0.0)
    p.buy("SPY", 100.0, 10)
    p.buy("QQQ", 100.0, 10)
    limits = Limits(max_per_group=2, max_exposure=None, max_positions=None)
    assert blocked_reason("WEIRD/PAIR", p, {"SPY": 100.0, "QQQ": 100.0}, limits) is None


def test_total_exposure_caps_entries_even_across_groups():
    p = Portfolio(cash=1000.0, fee=0.0, slippage=0.0)
    p.buy("SPY", 100.0, 9)      # 900 at market, 100 left in cash
    limits = Limits(max_exposure=0.80, max_per_group=None, max_positions=None)
    assert blocked_reason("GLD", p, {"SPY": 100.0}, limits) is not None


# ---------------------------------------------------------- the switch ----

def test_the_halt_survives_being_forgotten(tmp_path):
    switch = HaltFile(tmp_path / "halt")
    assert switch.active is False

    switch.set("down 20 percent", code="max-drawdown")
    # A fresh object, as after a restart. This is the property a button lacks.
    assert HaltFile(tmp_path / "halt").active is True
    assert HaltFile(tmp_path / "halt").read().code == "max-drawdown"

    switch.clear()
    assert HaltFile(tmp_path / "halt").active is False


def test_an_unreadable_halt_file_still_means_halted(tmp_path):
    """The one place in this codebase that must fail closed."""
    path = tmp_path / "halt"
    path.write_text("{ this is not json", encoding="utf-8")
    halt = HaltFile(path).read()
    assert halt is not None and halt.code == "unreadable"


def test_clear_returns_the_moment_it_was_lifted(tmp_path):
    switch = HaltFile(tmp_path / "halt")
    switch.set("manual", manual=True)
    assert switch.clear() > 0
