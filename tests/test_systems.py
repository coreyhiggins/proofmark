"""Tests for systems, fingerprints and the verification gate.

The gate is the only thing standing between a person and running something
nobody ever checked, so these are mostly about the ways it could quietly stop
working: a stale pass surviving an edit, a cosmetic change forcing a pointless
re-run, a built-in silently overwriting an edited copy.
"""

from __future__ import annotations

import pytest

from proofmark.engine import Market
from proofmark.limits import Limits
from proofmark.sizing import Sizing
from proofmark.systems import (
    Store, System, Verification, builtin_systems, requirements,
)
from proofmark.verify import explain, verify


def _system(**kw):
    base = dict(
        name="test", markets=[Market("BTC/USDT", "breakout", "1h")],
        sizing=Sizing(), limits=Limits(),
    )
    base.update(kw)
    return System(**base)


def _bars(closes, spread=1.0):
    return [
        {"timestamp": 1_700_000_000_000 + i * 3_600_000,
         "open": c, "high": c + spread, "low": c - spread, "close": c, "volume": 1.0}
        for i, c in enumerate(closes)
    ]


def test_the_fingerprint_changes_when_behaviour_changes():
    base = _system()
    assert base.fingerprint == _system().fingerprint

    assert _system(sizing=Sizing(risk_per_trade=0.02)).fingerprint != base.fingerprint
    assert _system(limits=Limits(max_drawdown=0.10)).fingerprint != base.fingerprint
    assert _system(markets=[Market("ETH/USDT", "breakout", "1h")]).fingerprint != base.fingerprint
    assert _system(markets=[Market("BTC/USDT", "rsi-dip", "1h")]).fingerprint != base.fingerprint
    assert _system(venue="bitget").fingerprint != base.fingerprint


def test_the_fingerprint_ignores_things_that_change_nothing():
    """Otherwise changing the size of a paper account forces a re-verification,
    which teaches people the gate is a nuisance to click past."""
    base = _system()
    assert _system(starting_cash=999_999.0).fingerprint == base.fingerprint
    assert _system(description="a different note").fingerprint == base.fingerprint


def test_market_order_does_not_change_the_fingerprint():
    a = _system(markets=[Market("BTC/USDT"), Market("ETH/USDT")])
    b = _system(markets=[Market("ETH/USDT"), Market("BTC/USDT")])
    assert a.fingerprint == b.fingerprint


def test_a_system_survives_a_round_trip_through_disk(tmp_path):
    store = Store(tmp_path)
    original = builtin_systems()[0]
    store.save(original)
    loaded = store.load(original.name)
    assert loaded is not None
    assert loaded.fingerprint == original.fingerprint
    assert loaded.symbols == original.symbols


def test_editing_a_system_invalidates_its_verification(tmp_path):
    """The whole mechanism. Verify, widen the stop, and the old pass no longer
    applies to the thing you are about to run."""
    store = Store(tmp_path)
    system = _system()
    store.record(system, Verification(
        fingerprint=system.fingerprint, at=0, passed=True, summary="fine",
    ))
    assert store.may_run(system)[0] is True

    widened = _system(sizing=Sizing(atr_multiple=4.0))
    allowed, why = store.may_run(widened)
    assert allowed is False
    assert "edited" in why


def test_an_unverified_system_may_not_run(tmp_path):
    allowed, why = Store(tmp_path).may_run(_system())
    assert allowed is False and "has not been run over history" in why


def test_a_failed_verification_blocks_the_run_and_says_why(tmp_path):
    store = Store(tmp_path)
    system = _system()
    store.record(system, Verification(
        fingerprint=system.fingerprint, at=0, passed=False,
        summary="no costs were applied",
    ))
    allowed, why = store.may_run(system)
    assert allowed is False and "no costs were applied" in why


def test_builtins_are_available_before_anything_is_saved(tmp_path):
    names = [s.name for s in Store(tmp_path).all()]
    assert "reference-five" in names
    assert "crypto-three" in names


def test_an_edited_system_is_not_reverted_by_the_builtin(tmp_path):
    store = Store(tmp_path)
    edited = {s.name: s for s in builtin_systems()}["crypto-three"]
    edited.sizing = Sizing(risk_per_trade=0.005)
    store.save(edited)
    found = {s.name: s for s in store.all()}
    assert found["crypto-three"].sizing.risk_per_trade == 0.005


def test_the_free_feed_states_its_own_limits_on_every_verdict():
    """Free data that nobody warns you about is how a number gets trusted
    further than it deserves. This is not a blocker, and it is still on screen."""
    five = {s.name: s for s in builtin_systems()}["reference-five"]
    missing = requirements(five)
    assert any("free public endpoint" in m for m in missing)
    assert any("not a data licence" in m for m in missing)


def test_the_crypto_system_needs_nothing():
    three = {s.name: s for s in builtin_systems()}["crypto-three"]
    assert requirements(three) == []


def test_a_system_that_never_trades_does_not_get_cleared():
    """Not a dishonest result, just an empty one. The guards catch dishonesty,
    so nothing there would have objected, and the gate would have opened on no
    evidence at all."""
    system = _system(markets=[Market("X", "rsi-dip", "1h")])
    verification, _ = verify(system, {"X": _bars([100.0] * 80)})
    assert verification.passed is False
    assert "no trades" in verification.summary
    assert verification.fingerprint == system.fingerprint


def test_a_verification_records_the_comparison_against_holding():
    system = _system(markets=[Market("X", "buy-and-hold", "1h")])
    rising = _bars([100.0 + i for i in range(120)])
    verification, run = verify(system, {"X": rising})
    assert verification.bars == len(run.equity)
    assert verification.benchmark_return != 0.0
    assert "holding" in explain(verification)


def test_the_explanation_says_so_when_a_passing_system_still_lost_to_holding():
    verification = Verification(
        fingerprint="x", at=0, passed=True, summary="nothing objectionable",
        total_return=0.02, benchmark_return=0.30, trades=10, bars=500,
    )
    assert "behind doing nothing" in explain(verification)


def test_the_gate_is_not_a_wall(tmp_path):
    """Asserting delisted_included=False made the survivorship guard fatal on
    every system that could ever be written, so nothing could ever be cleared.
    That guard is calibrated for a cross-sectional backtest; a basket of named
    instruments makes no claim about a universe."""
    system = _system(markets=[Market("X", "buy-and-hold", "1h")])
    # Calm enough to build a volatility estimate, then a fall that takes the
    # stop out, so there is a closed trade and real costs to judge.
    closes = [100.0] * 40 + [96.0, 90.0, 84.0, 80.0] + [80.0] * 20
    verification, run = verify(system, {"X": _bars(closes, spread=1.5)})
    assert run.portfolio.trades, "fixture must produce a closed trade"

    fatal = [f for f in verification.findings if f.startswith("fatal")]
    assert not any("no longer exist" in f for f in fatal), fatal
    # The selection bias is still stated, just not as a disqualification.
    assert any("chosen today" in f for f in verification.findings)


def test_a_halted_run_cannot_clear_the_gate_and_says_where_it_stopped():
    """The bug this catches: a system halted 6% into its history produced zero
    trades and zero complaints for the other 94%, and read as rules that never
    fired. Its reported return described a system that had switched itself off."""
    system = _system(
        markets=[Market("X", "buy-and-hold", "1h")],
        sizing=Sizing(mode="fixed_fraction", fraction=1.0, max_position=1.0),
        limits=Limits(max_drawdown=0.05, daily_loss=None, consecutive_losses=None),
    )
    # Calm enough to size, then a long slide that trips the drawdown limit early.
    closes = [100.0] * 40 + [100.0 - i * 0.7 for i in range(200)]
    verification, run = verify(system, {"X": _bars(closes, spread=0.4)})

    assert run.halted_at is not None
    assert verification.passed is False
    assert "halted" in verification.summary
    assert verification.halted_at == run.halted_at
    assert "stopped itself" in verification.findings[0]
    assert "it stopped itself" in explain(verification)


def test_the_engine_says_out_loud_that_a_halt_is_blocking_entries():
    """Silence here is what made the halt invisible for 94% of a run."""
    from proofmark.engine import run_portfolio

    closes = [100.0] * 40 + [100.0 - i * 0.7 for i in range(200)]
    run = run_portfolio(
        [Market("X", "buy-and-hold", "1h")], {"X": _bars(closes, spread=0.4)},
        starting_cash=10_000.0,
        sizing=Sizing(mode="fixed_fraction", fraction=1.0, max_position=1.0),
        limits=Limits(max_drawdown=0.05, daily_loss=None, consecutive_losses=None),
    )
    blocked = [r for _, _, r in run.refusals if "halted" in r]
    assert blocked, "a halt that blocks entries has to leave a record"
    # Once per symbol, not once per bar, or the log is nothing but this.
    assert len(blocked) <= 2
