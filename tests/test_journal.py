"""Tests for the append-only log and the alerts.

The one that matters is deduplication. The live loop replays the whole history
on every poll, so without a stable identity per event the log grows by the
entire run every minute and every alert fires again with it.
"""

from __future__ import annotations

import json

import pytest

from proofmark.engine import Market, run_portfolio
from proofmark.journal import (
    Journal, announce, digest, events_from_run, notify_discord,
)
from proofmark.limits import Limits
from proofmark.sizing import Sizing


def _bars(closes, spread=1.2):
    return [
        {"timestamp": 1_700_000_000_000 + i * 3_600_000,
         "open": c, "high": c + spread, "low": c - spread, "close": c, "volume": 1.0}
        for i, c in enumerate(closes)
    ]


def _run(closes=None, **kw):
    closes = closes or ([100.0] * 40 + [100.0 + i * 0.4 for i in range(60)])
    settings = dict(
        starting_cash=10_000.0,
        sizing=Sizing(mode="fixed_fraction", fraction=0.5, max_position=0.5),
        limits=Limits(max_drawdown=None, daily_loss=None, consecutive_losses=None),
    )
    settings.update(kw)
    return run_portfolio([Market("X", "buy-and-hold", "1h")],
                         {"X": _bars(closes)}, **settings)


def test_replaying_the_same_run_does_not_grow_the_log(tmp_path):
    """The live loop re-derives the entire history every poll. Without stable
    identities the log gains the whole run once a minute."""
    run = _run()
    events = events_from_run(run, "test")
    assert events, "fixture must produce events"

    path = tmp_path / "log.jsonl"
    first = Journal(path).write(events)
    assert len(first) == len(events)

    # Same process, same journal object.
    same = Journal(path)
    assert same.write(events) == []

    # And after a restart, which is where a memory-only guard would fail.
    restarted = Journal(path)
    assert restarted.write(events) == []
    assert len(path.read_text(encoding="utf-8").splitlines()) == len(events)


def _wave(cycles):
    """An oscillating series, so a longer run genuinely has more crossings.

    A rising line does not work here: buy-and-hold enters once whatever its
    length, so 'longer' would produce no new events and the test would be
    asserting the wrong thing."""
    closes = [100.0] * 40
    for _ in range(cycles):
        closes += [100.0 + i for i in range(15)] + [115.0 - i for i in range(15)]
    return closes


def test_new_events_still_append_after_a_replay(tmp_path):
    path = tmp_path / "log.jsonl"
    short = run_portfolio(
        [Market("X", "ema-cross", "1h")], {"X": _bars(_wave(3))},
        starting_cash=10_000.0,
        sizing=Sizing(mode="fixed_fraction", fraction=0.5, max_position=0.5),
        limits=Limits(max_drawdown=None, daily_loss=None, consecutive_losses=None),
    )
    Journal(path).write(events_from_run(short, "test"))

    longer = run_portfolio(
        [Market("X", "ema-cross", "1h")], {"X": _bars(_wave(8))},
        starting_cash=10_000.0,
        sizing=Sizing(mode="fixed_fraction", fraction=0.5, max_position=0.5),
        limits=Limits(max_drawdown=None, daily_loss=None, consecutive_losses=None),
    )
    fresh = Journal(path).write(events_from_run(longer, "test"))
    assert fresh, "a longer run has events the first one did not"


def test_the_log_is_one_json_object_per_line(tmp_path):
    """Readable by a text editor on a machine with nothing installed."""
    path = tmp_path / "log.jsonl"
    Journal(path).write(events_from_run(_run(), "test"))
    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = json.loads(line)
        assert "kind" in parsed and "system" in parsed


def test_a_corrupt_line_does_not_stop_the_journal(tmp_path):
    """A half-written line after a crash must not make the log unusable."""
    path = tmp_path / "log.jsonl"
    path.write_text('{"kind":"entry","symbol":"X","at":1,"index":""}\n{ broken\n',
                    encoding="utf-8")
    journal = Journal(path)
    assert journal.tail()  # the good line survives
    # And the known identity was still picked up, so it will not be duplicated.
    assert journal.write([{"kind": "entry", "symbol": "X", "at": 1, "index": ""}]) == []


def test_a_breach_is_logged_with_its_reason(tmp_path):
    run = _run(
        [100.0] * 40 + [100.0 - i * 0.7 for i in range(200)],
        sizing=Sizing(mode="fixed_fraction", fraction=1.0, max_position=1.0),
        limits=Limits(max_drawdown=0.05, daily_loss=None, consecutive_losses=None),
    )
    events = events_from_run(run, "test")
    breach = [e for e in events if e["kind"] == "breach"]
    assert breach and "drawdown" in breach[0]["code"]


def test_only_the_kinds_worth_waking_someone_for_are_alerted():
    """A list that grows past this trains people to ignore all of it."""
    events = [
        {"kind": "entry", "symbol": "X", "reason": "in"},
        {"kind": "refusal", "symbol": "X", "reason": "capped"},
        {"kind": "decision", "symbol": "X", "reason": "hold"},
        {"kind": "breach", "symbol": "", "reason": "down 20%"},
    ]
    assert announce(events, webhook="", desktop=False) == 2


def test_a_dead_webhook_is_not_fatal():
    """A slow or broken webhook must never stop a trading loop."""
    assert notify_discord("", "t", "m") is False
    assert notify_discord("not-a-url", "t", "m") is False
    assert notify_discord("https://127.0.0.1:1/nope", "t", "m") is False


def test_the_two_digests_say_different_things():
    """A morning message reporting yesterday's return is a scoreboard nobody
    can act on. An evening message listing open positions is a to-do list at
    the wrong hour."""
    run = _run()
    morning_title, morning_body = digest(run, "test", morning=True)
    evening_title, evening_body = digest(run, "test", morning=False)

    assert "what is open" in morning_title
    assert "how today went" in evening_title
    assert morning_body != evening_body
    assert "Return" in evening_body
    assert "Return" not in morning_body


def test_the_morning_digest_flags_a_position_with_no_stop():
    run = _run()
    _, body = digest(run, "test", morning=True)
    if run.portfolio.holdings:
        assert "stop" in body


def test_the_evening_digest_says_when_it_is_behind_holding():
    run = _run()
    _, body = digest(run, "test", morning=False)
    if run.total_return < run.benchmark_return:
        assert "Behind buying and holding" in body
