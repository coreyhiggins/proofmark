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


# ------------------------------------------------------------ walk-forward --

from proofmark.walkforward import format_walk_forward, walk_forward


def _trend_bars(n=600):
    bars, price = [], 100.0
    for i in range(n):
        price *= 1.004 if (i // 40) % 2 == 0 else 0.997
        bars.append({"timestamp": i, "open": price, "close": price * 1.001})
    return bars


def _stable_opt(train):
    """Always picks the same answer. A genuinely stable parameter."""
    return {"lookback": 20}, 8


def _noisy_opt(train):
    """Picks a wildly different answer each window. This is overfitting.

    Derived from the window's start index so it is deterministic, and
    deliberately alternating so the spread is unmistakable. The first version
    of this fixture used a hash of the opening price and happened to land on
    values that were stable enough to pass, which made the test prove nothing.
    """
    window = train[0]["timestamp"] // 120
    return {"lookback": 5 if window % 2 == 0 else 90}, 40


def _evaluate(test, params):
    equity, pnls = [1000.0], []
    for i in range(1, len(test)):
        step = test[i]["close"] / test[i - 1]["close"]
        equity.append(equity[-1] * (1 + (step - 1) * 0.5))
        if i % 10 == 0:
            pnls.append(equity[-1] - equity[-10])
    return equity, pnls


def test_walk_forward_reports_out_of_sample_only():
    result = walk_forward(_trend_bars(), _stable_opt, _evaluate, windows=5)
    assert len(result.windows) == 5
    assert len(result.equity) > 100
    assert result.metrics.trades > 0


def test_total_trials_sums_across_windows():
    result = walk_forward(_trend_bars(), _noisy_opt, _evaluate, windows=5)
    assert result.total_trials == 200  # 40 candidates in each of 5 windows


def test_a_stable_parameter_is_not_flagged():
    result = walk_forward(_trend_bars(), _stable_opt, _evaluate, windows=5)
    assert result.unstable_params() == []


def test_an_unstable_parameter_is_flagged():
    result = walk_forward(_trend_bars(), _noisy_opt, _evaluate, windows=5)
    assert "lookback" in result.unstable_params()
    assert "UNSTABLE" in format_walk_forward(result)


def test_anchored_training_grows_from_the_start():
    result = walk_forward(_trend_bars(), _stable_opt, _evaluate, windows=4, anchored=True)
    assert all(w.train_start == 0 for w in result.windows)


def test_rolling_is_the_default():
    result = walk_forward(_trend_bars(), _stable_opt, _evaluate, windows=4)
    assert result.windows[-1].train_start > 0


def test_too_little_data_is_refused_rather_than_guessed_at():
    with pytest.raises(ValueError, match="too few to measure"):
        walk_forward(_trend_bars(40), _stable_opt, _evaluate, windows=5)


def test_one_window_is_refused():
    with pytest.raises(ValueError, match="at least two windows"):
        walk_forward(_trend_bars(), _stable_opt, _evaluate, windows=1)


def test_walk_forward_trials_feed_the_guards():
    result = walk_forward(_trend_bars(), _noisy_opt, _evaluate, windows=5)
    verdict = check(result.metrics, trials=result.total_trials,
                    costs_applied=1.0, delisted_included=True)
    assert not verdict.reportable
    assert any(f.code == "search-without-correction" for f in verdict.fatal)


# ------------------------------------------------------- short series ------

from proofmark.metrics import MIN_OBSERVATIONS


def test_a_short_series_reports_no_ratios_rather_than_absurd_ones():
    # Found by using the CLI: 6 daily returns scaled by sqrt(252) gave a
    # Sharpe of 4.60 on an unremarkable curve, which tripped a fatal guard.
    equity = [10000, 9800, 10100, 9950, 10300, 10150, 10400]
    result = summarise(equity, [])
    assert result.sharpe is None
    assert result.sortino is None
    assert result.calmar is None
    assert check(result, costs_applied=12.5, delisted_included=True).reportable


def test_a_long_enough_series_still_reports_ratios():
    equity = [1000.0]
    for step in [1.01, 0.99, 1.02, 0.98] * 15:
        equity.append(equity[-1] * step)
    result = summarise(equity, [])
    assert len(equity) > MIN_OBSERVATIONS
    assert result.sharpe is not None


# ------------------------------------------------------------ consumer -----

from proofmark.cli import _read_csv
from proofmark.gui import _analyse


def test_csv_column_names_are_matched_forgivingly(tmp_path):
    f = tmp_path / "r.csv"
    f.write_text("Date,Portfolio Value,Profit\n2026-01-01,\"10,000\",\n2026-01-02,$10120,120\n")
    equity, pnls = _read_csv(f)
    assert equity == [10000.0, 10120.0]
    assert pnls == [120.0]


def test_a_single_column_file_is_treated_as_the_curve(tmp_path):
    f = tmp_path / "r.csv"
    f.write_text("10000\n10120\n9980\n")
    equity, _ = _read_csv(f)
    assert equity == [10000.0, 10120.0, 9980.0]


def test_gui_rejects_a_curve_too_short_to_measure():
    assert "at least two" in _analyse({"equity": [100.0]})["error"]


def test_gui_rejects_non_positive_balances():
    assert "above zero" in _analyse({"equity": [100.0, 0.0, 50.0]})["error"]


def test_gui_returns_findings_with_fatal_first():
    payload = {"equity": [1000.0 * (1.003 ** i) for i in range(46)],
               "pnls": [2.7] * 45, "trials": 270, "costs": 0.0, "delisted": "no"}
    out = _analyse(payload)
    assert out["reportable"] is False
    assert out["findings"][0]["severity"] == "fatal"
    assert any(k == "Sortino" and v == "undefined" for k, v in out["metrics"])


# --------------------------------------------------------------- venues ----

from proofmark.data import from_bars
from proofmark.venues import VENUES, describe, venue


def test_every_venue_states_its_sandbox_truthfully():
    for v in VENUES.values():
        assert v.sandbox in ("none", "synthetic", "production-data", "broker-paper")
        assert v.sandbox_note, f"{v.id} has no sandbox note"


def test_the_venues_with_real_paper_data_are_the_defaults():
    assert venue("okx").paper_is_honest
    assert venue("bitget").paper_is_honest
    # Binance's testnet is synthetic and wiped monthly, so it is not honest paper.
    assert not venue("binance").paper_is_honest
    # Coinbase has no sandbox at all.
    assert venue("coinbase").sandbox == "none"


def test_a_venue_without_a_dead_mans_switch_says_so():
    text = describe("coinbase")
    assert "dead-man's switch" in text
    assert "real money" in text


def test_an_unknown_venue_lists_the_known_ones():
    with pytest.raises(KeyError, match="okx"):
        venue("definitely-not-an-exchange")


def test_local_data_does_not_claim_delisted_coverage():
    u = from_bars([{"close": 1.0}, {"close": 2.0}], symbol="BTC/USDT")
    assert u.delisted_included is None  # unknown, never assumed
    verdict = check(summarise([100.0, 101.0], []), delisted_included=u.delisted_included)
    assert any(f.code == "survivorship-unknown" for f in verdict.findings)


def test_a_universe_reports_survivors_only_loudly():
    u = from_bars([{"close": 1.0}], delisted_included=False)
    assert "SURVIVORS ONLY" in u.summary()


# --------------------------------------------------------------- charts ----

from proofmark.charts import buy_and_hold, equity_chart, underwater_chart


def test_the_benchmark_is_drawn_and_the_gap_is_stated():
    losing = [100.0 * (0.999 ** i) for i in range(200)]
    winning = [100.0 * (1.002 ** i) for i in range(200)]
    svg = equity_chart(losing, winning)
    assert 'class="bench"' in svg
    # The point of the chart: the shortfall is written out, not left to arithmetic.
    assert "difference -" in svg


def test_a_chart_without_a_benchmark_still_draws():
    svg = equity_chart([100.0, 110.0, 105.0, 120.0])
    assert 'class="subject"' in svg
    assert 'class="bench"' not in svg


def test_downsampling_keeps_the_crash():
    # A single catastrophic bar in a long series must survive to the picture.
    equity = [100.0] * 5000
    equity[2500] = 10.0
    svg = underwater_chart(equity)
    assert "-90.0%" in svg


def test_out_of_sample_windows_are_shaded():
    svg = equity_chart([100.0 + i for i in range(100)], windows=[(0, 30), (30, 60), (60, 100)])
    assert 'class="oos"' in svg


def test_charts_refuse_to_draw_nothing():
    assert equity_chart([100.0]) == ""
    assert underwater_chart([]) == ""


def test_buy_and_hold_tracks_the_close():
    bars = [{"close": 100.0}, {"close": 110.0}, {"close": 90.0}]
    assert buy_and_hold(bars, starting=1000.0) == [1000.0, 1100.0, 900.0]


# ----------------------------------------------------------------- live ----

import time as _time

from proofmark.gui import _live_payload
from proofmark.live import (
    STALE_AFTER_SECONDS, Decision, Position, alerts, read_state, write_state,
)


def _state_file(tmp_path, **kw):
    path = tmp_path / "state.json"
    write_state(path, **kw)
    return path


def test_state_survives_a_round_trip(tmp_path):
    path = _state_file(
        tmp_path, mode="paper", equity=[100.0, 101.0],
        positions=[Position("AAPL", 10, 150.0, 154.0, stop=145.0)],
        decisions=[Decision(_time.time(), "AAPL", "buy", "all rules passed")],
    )
    s = read_state(path)
    assert s.mode == "paper"
    assert s.positions[0].symbol == "AAPL"
    assert s.positions[0].unrealised == pytest.approx(40.0)
    assert s.decisions[0].reason == "all rules passed"


def test_a_half_written_file_reads_as_nothing(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"mode":"paper","equity":[1,2', encoding="utf-8")
    # A viewer that crashes on a torn write reports the wrong problem.
    assert read_state(path) is None
    assert read_state(tmp_path / "absent.json") is None


def test_a_position_without_a_stop_is_the_headline_alert(tmp_path):
    path = _state_file(tmp_path, positions=[Position("MSFT", 5, 400.0, 392.0)])
    assert "unprotected" in [tag for tag, _ in alerts(read_state(path))]


def test_a_silent_bot_is_reported_as_silent(tmp_path):
    path = _state_file(tmp_path, equity=[100.0, 101.0])
    state = read_state(path)
    state.updated = _time.time() - (STALE_AFTER_SECONDS + 60)
    assert state.stale
    assert "silent" in [tag for tag, _ in alerts(state)]


def test_real_money_is_always_called_out(tmp_path):
    path = _state_file(tmp_path, mode="live", equity=[100.0, 101.0])
    assert "live-money" in [tag for tag, _ in alerts(read_state(path))]


def test_a_healthy_paper_bot_raises_nothing(tmp_path):
    path = _state_file(
        tmp_path, mode="paper", equity=[100.0, 99.0, 101.0],
        positions=[Position("AAPL", 1, 10.0, 11.0, stop=9.0)],
    )
    assert alerts(read_state(path)) == []


def test_the_guards_run_over_the_live_curve_too(tmp_path):
    # A live strategy that never goes down is showing the same impossibility a
    # backtest would, with real money on the table.
    rising = [1000.0 * (1.004 ** i) for i in range(60)]
    path = _state_file(tmp_path, equity=rising)
    payload = _live_payload(str(path))
    assert payload["present"] is True
    assert payload["verdict"], "the guards said nothing about an impossible live curve"


def test_no_state_path_explains_itself_rather_than_erroring():
    out = _live_payload(None)
    assert out["present"] is False
    assert "--state" in out["hint"]


def test_decisions_come_back_newest_first(tmp_path):
    now = _time.time()
    path = _state_file(tmp_path, decisions=[
        Decision(now - 300, "OLD", "reject", "first"),
        Decision(now - 10, "NEW", "buy", "second"),
    ])
    order = [d["symbol"] for d in _live_payload(str(path))["decisions"]]
    assert order == ["NEW", "OLD"]


# -------------------------------------------------------------- desktop ----

from proofmark.desktop import free_port, start_server


def test_a_busy_port_is_stepped_over():
    import socket as _s
    holder = _s.socket()
    holder.bind(("127.0.0.1", 8765))
    holder.listen(1)
    try:
        # Refusing to start because something holds 8765 is not an acceptable
        # outcome for a program somebody double-clicked.
        assert free_port(8765) != 8765
    finally:
        holder.close()


def test_the_server_is_listening_before_a_window_would_open(tmp_path):
    import socket as _s
    port = free_port(8901)
    start_server(port)
    with _s.socket() as probe:
        assert probe.connect_ex(("127.0.0.1", port)) == 0
