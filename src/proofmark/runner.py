"""A live paper-trading engine, with the honesty rules compiled in.

Until now proofmark could fetch candles and it could display a state file
somebody else's bot wrote, but nothing here actually ran a strategy. That gap
made the tool useless to the person it was built for: someone who wants to
watch rules run against a real market before risking anything on them.

This runs them. Paper only. It never holds an exchange key that can place an
order, and there is no flag that makes it place one.

THE FILL RULE, WHICH IS THE WHOLE THING.

Every honest backtest and every dishonest one differ mostly at this line. The
rule here is:

    decide on the close of bar t, fill at the open of bar t+1

so the decision cannot see the price it trades at. The signal is computed once,
stored as ``pending``, and executed on the next bar's open. That is the same
convention :mod:`proofmark.lookahead` property-tests for, and it is why a
strategy that behaves here behaves the same in the backtester.

The still-forming bar is dropped on every poll. An exchange returns the current
candle with a close that is simply the last trade, and a strategy that reads it
is reading a number that has not happened yet. This is the single most common
way a live bot outperforms its backtest and then bleeds money in production.

COSTS ARE APPLIED, NOT ASSUMED.

Fees and slippage come off every fill. A zero-cost paper run is a fantasy
generator, and the guards call a costless backtest disqualifying, so producing
one here and then feeding it to the guards would be a tool arguing with itself.

BUY AND HOLD IS TRACKED FROM THE FIRST BAR, ALWAYS.

Not optional, not a flag. The comparison that decides whether the run was worth
doing is computed whether or not anyone asked for it, because the runs where
nobody asks are exactly the runs where it matters.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from .live import Decision, Mark, Position, write_state
from .strategies import Signal, get_strategy

# Fees are per side and vary by venue and tier. This is a plausible retail taker
# fee, deliberately not a flattering one. Slippage is on top and is the part
# people forget: your order does not fill at the price you saw.
DEFAULT_FEE = 0.001
DEFAULT_SLIPPAGE = 0.0005

# How long to wait between polls when the caller does not say. One minute is
# short enough to notice a dead feed and long enough that no exchange will rate
# limit a single symbol.
DEFAULT_POLL_SECONDS = 60


@dataclass
class Fill:
    index: int
    side: str
    price: float
    quantity: float
    cost: float


@dataclass
class Paper:
    """A cash account that can hold one long position at a time.

    One position, long only, no leverage, no shorting. That is not a limitation
    anyone will hit before they have learned something useful, and every one of
    those features is a new way for a paper run to disagree with reality.
    """

    cash: float
    fee: float = DEFAULT_FEE
    slippage: float = DEFAULT_SLIPPAGE
    quantity: float = 0.0
    entry: float = 0.0
    fills: list[Fill] = field(default_factory=list)

    @property
    def in_market(self) -> bool:
        return self.quantity > 0

    def value(self, price: float) -> float:
        return self.cash + self.quantity * price

    def buy(self, index: int, price: float) -> Fill | None:
        if self.in_market or self.cash <= 0:
            return None
        # Slippage moves against you on both sides. Paying it only on entry is
        # the sort of half-modelled cost that makes a losing system look flat.
        fill_price = price * (1 + self.slippage)
        quantity = self.cash / (fill_price * (1 + self.fee))
        cost = quantity * fill_price * self.fee

        self.cash = 0.0
        self.quantity = quantity
        self.entry = fill_price
        fill = Fill(index, "buy", fill_price, quantity, cost)
        self.fills.append(fill)
        return fill

    def sell(self, index: int, price: float) -> Fill | None:
        if not self.in_market:
            return None
        fill_price = price * (1 - self.slippage)
        gross = self.quantity * fill_price
        cost = gross * self.fee

        fill = Fill(index, "sell", fill_price, self.quantity, cost)
        self.cash = gross - cost
        self.quantity = 0.0
        self.entry = 0.0
        self.fills.append(fill)
        return fill


@dataclass
class Run:
    """Everything one pass over the bars produced."""

    equity: list[float] = field(default_factory=list)
    benchmark: list[float] = field(default_factory=list)
    closes: list[float] = field(default_factory=list)
    marks: list[Mark] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    account: Paper | None = None

    @property
    def total_return(self) -> float:
        if len(self.equity) < 2 or not self.equity[0]:
            return 0.0
        return self.equity[-1] / self.equity[0] - 1

    @property
    def benchmark_return(self) -> float:
        if len(self.benchmark) < 2 or not self.benchmark[0]:
            return 0.0
        return self.benchmark[-1] / self.benchmark[0] - 1


def replay(
    bars: Sequence[dict],
    decide: Callable[[Sequence[dict]], Signal],
    *,
    starting_cash: float = 10_000.0,
    fee: float = DEFAULT_FEE,
    slippage: float = DEFAULT_SLIPPAGE,
    warmup: int = 50,
    symbol: str = "",
) -> Run:
    """Walk the bars once, deciding at each close and filling at the next open.

    Pure and deterministic: the same bars produce the same run, which is what
    lets the live loop simply replay everything each poll instead of carrying
    mutable position state across network calls. Reconciling incremental state
    against a feed that can revise or repeat a candle is a class of bug this
    design does not have.
    """
    account = Paper(cash=starting_cash, fee=fee, slippage=slippage)
    run = Run(account=account)

    pending: Signal | None = None
    hold_units = 0.0

    for i, bar in enumerate(bars):
        open_price = float(bar["open"])
        close_price = float(bar["close"])

        # Yesterday's decision trades at today's open, before today's close is
        # visible to anything.
        if pending is not None:
            fill = None
            if pending.action == "buy":
                fill = account.buy(i, open_price)
            elif pending.action == "sell":
                fill = account.sell(i, open_price)
            if fill is not None:
                run.marks.append(Mark(index=i, side=fill.side, price=fill.price))
                run.decisions.append(Decision(
                    time=float(bar.get("timestamp", 0)) / 1000 or time.time(),
                    symbol=symbol,
                    action=fill.side,
                    reason=pending.reason,
                ))
            pending = None

        # The benchmark buys once, on the first bar it could have, and then
        # does nothing at all. That is the thing to beat.
        if hold_units == 0.0 and open_price > 0:
            hold_units = starting_cash / open_price

        run.closes.append(close_price)
        run.equity.append(account.value(close_price))
        run.benchmark.append(hold_units * close_price)

        if i + 1 >= warmup:
            signal = decide(bars[: i + 1])
            if signal.action in ("buy", "sell"):
                # Do not queue an order the account cannot take. Otherwise the
                # decision log fills with buys that never happened and reads
                # like the strategy is trading far more than it is.
                if (signal.action == "buy") != account.in_market:
                    pending = signal

    return run


def open_positions(run: Run, symbol: str) -> list[Position]:
    account = run.account
    if account is None or not account.in_market or not run.closes:
        return []
    return [Position(
        symbol=symbol,
        quantity=account.quantity,
        entry=account.entry,
        current=run.closes[-1],
        # Paper runs on a rules exit rather than a resting stop order. Saying
        # stop=None is honest: there is no protective order at the venue, and
        # the live view is right to point that out.
        stop=None,
    )]


def run_once(
    *,
    venue: str,
    symbol: str,
    timeframe: str,
    strategy: str,
    state_path: str | Path,
    starting_cash: float = 10_000.0,
    fee: float = DEFAULT_FEE,
    slippage: float = DEFAULT_SLIPPAGE,
    limit: int = 600,
) -> Run:
    """Fetch, replay, and write the state file once."""
    from .data import fetch_ohlcv

    rules = get_strategy(strategy)
    universe = fetch_ohlcv(venue, symbol, timeframe=timeframe, limit=limit)
    bars = list(universe.bars)

    # The last candle an exchange returns is still forming. Its close is just
    # the last trade, and a strategy reading it is reading the future.
    if bars:
        bars = bars[:-1]
    if len(bars) < rules.warmup + 2:
        raise ValueError(
            f"{len(bars)} closed bars is not enough for {rules.name}, which needs "
            f"{rules.warmup + 2}. Ask for a longer history or a shorter timeframe."
        )

    run = replay(
        bars, rules.decide, starting_cash=starting_cash, fee=fee,
        slippage=slippage, warmup=rules.warmup, symbol=symbol,
    )

    write_state(
        state_path,
        mode="paper",
        equity=run.equity,
        benchmark=run.benchmark,
        closes=run.closes,
        marks=run.marks,
        positions=open_positions(run, symbol),
        decisions=run.decisions,
        label=f"{symbol} {timeframe} on {venue}",
        strategy=rules.name,
    )
    return run


def run_system_once(system, state_path: str | Path, *, store=None) -> object:
    """Fetch, run every market, and write the state file once.

    The gate is enforced HERE rather than only in the button that starts a run.
    A check that lives in the interface is a suggestion: anything that calls the
    engine another way walks straight past it, and the first thing anyone does
    with a tool like this is call it another way.
    """
    from .engine import run_portfolio
    from .limits import HaltFile
    from .systems import Store
    from .verify import fetch_history

    store = store or Store(Path(state_path).parent)
    allowed, why = store.may_run(system)
    if not allowed:
        raise PermissionError(why)

    bars = fetch_history(system, limit=600)
    thin = [s for s, series in bars.items() if len(series) < 30]
    if thin:
        raise ValueError(
            f"{', '.join(thin)} came back with almost no history, so there is "
            "nothing to measure volatility against yet."
        )

    switch = HaltFile(Path(state_path).parent / "halt")
    run = run_portfolio(
        list(system.markets), bars,
        starting_cash=system.starting_cash,
        sizing=system.sizing,
        limits=system.limits,
        halt=switch.read(),
    )

    # A limit breached during the run sets the switch, so it survives a restart
    # rather than being recomputed and forgotten on the next poll.
    if run.breach is not None and not switch.active:
        switch.set(run.breach.detail, code=run.breach.code)

    _write_system_state(run, system, state_path, switch)
    return run


def _write_system_state(run, system, state_path, switch) -> None:
    """Flatten a multi-market run into the state file the live view reads."""
    from .live import Mark, Position

    halt = switch.read()
    positions = [
        Position(symbol=s, quantity=h.quantity, entry=h.entry,
                 current=run.closes[s][-1] if run.closes.get(s) else h.entry,
                 stop=h.stop)
        for s, h in (run.portfolio.holdings if run.portfolio else {}).items()
    ]

    # The chart shows the first market. Everything else is in the tables, and
    # five stacked price charts on one page is a wall nobody reads.
    lead = system.markets[0].symbol if system.markets else ""

    write_state(
        state_path,
        mode="paper",
        equity=run.equity,
        benchmark=run.benchmark,
        closes=run.closes.get(lead, []),
        marks=run.marks.get(lead, []),
        positions=positions,
        decisions=run.decisions,
        halted=halt is not None,
        halt_reason=halt.reason if halt else "",
        label=f"{system.name}: {', '.join(system.symbols)}",
        strategy=f"{len(system.markets)} markets on {system.venue}",
    )


def run_forever(
    *,
    venue: str,
    symbol: str,
    timeframe: str,
    strategy: str,
    state_path: str | Path,
    starting_cash: float = 10_000.0,
    fee: float = DEFAULT_FEE,
    slippage: float = DEFAULT_SLIPPAGE,
    poll_seconds: int = DEFAULT_POLL_SECONDS,
    on_cycle: Callable[[Run], None] | None = None,
) -> None:
    """Poll forever, replaying the whole history each time.

    A network error is logged and slept through rather than raised. A live
    watcher that dies on the first timeout is worse than no watcher, because
    the state file simply stops updating and the page correctly reports a dead
    bot for a problem that fixed itself in ten seconds.
    """
    while True:
        try:
            run = run_once(
                venue=venue, symbol=symbol, timeframe=timeframe, strategy=strategy,
                state_path=state_path, starting_cash=starting_cash, fee=fee,
                slippage=slippage,
            )
            if on_cycle:
                on_cycle(run)
        except KeyboardInterrupt:
            raise
        except Exception as err:  # noqa: BLE001
            print(f"cycle failed, retrying in {poll_seconds}s: {err}")
        time.sleep(poll_seconds)
