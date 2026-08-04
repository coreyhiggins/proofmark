"""Several markets, several timeframes, one account, one set of limits.

The single-symbol engine walks a list of bars. That does not survive contact
with the thing people actually want, which is mean reversion on 15m indices
alongside a breakout on 1h Bitcoin and trend following on 4h commodities. Those
bar lists do not line up, so there is no shared index to walk.

THE MERGED TIMELINE.

Every bar from every symbol becomes an event, and the events are processed in
timestamp order. When a symbol's bar arrives, only that symbol acts. Everything
else is marked at its most recent close.

This is the only honest way to do it. Iterating symbol by symbol would let a
4-hour commodity see Monday's close while a 15-minute index is still on
Monday's open, and the correlation and exposure rules would be reasoning about
an account that never existed at any single moment.

THE FILL RULE IS UNCHANGED AND STILL PER SYMBOL.

Decide at the close of a symbol's bar, fill at the open of that symbol's next
bar. Merging timelines does not weaken it: each symbol's pending signal waits
for that symbol's next bar, not for wall-clock time.

GAPS THROUGH A STOP ARE FILLED AT THE OPEN, NOT AT THE STOP.

If a market opens below the stop, the stop did not get you out at the stop. It
got you out lower. An engine that fills gaps at the stop price reports losses
that are smaller than the ones that happened, which is the most flattering lie
a backtest can tell about a risk control.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .limits import Breach, Halt, Limits, blocked_reason, check_limits, session_start
from .live import Decision, Mark
from .portfolio import Portfolio, Trade
from .sizing import Sizing, position_size, stop_price
from .strategies import Signal, get_strategy


@dataclass(frozen=True)
class Market:
    """One symbol, the rules it trades under, and what a bar means for it."""

    symbol: str
    strategy: str = "ema-cross"
    timeframe: str = "1h"
    whole_units: bool = False


@dataclass
class PortfolioRun:
    equity: list[float] = field(default_factory=list)
    benchmark: list[float] = field(default_factory=list)
    stamps: list[float] = field(default_factory=list)
    closes: dict[str, list[float]] = field(default_factory=dict)
    marks: dict[str, list[Mark]] = field(default_factory=dict)
    decisions: list[Decision] = field(default_factory=list)
    refusals: list[tuple[float, str, str]] = field(default_factory=list)
    breach: Breach | None = None
    halted_at: int | None = None
    portfolio: Portfolio | None = None

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


def _timeline(bars: Mapping[str, Sequence[dict]]) -> list[tuple[float, str, int]]:
    """Every bar from every symbol, in the order they became known.

    Ties are broken by symbol name so a run is deterministic. Two symbols
    printing a bar at the same instant is normal on aligned timeframes, and
    without a stable tiebreak the exposure rule would let whichever symbol
    happened to sort first take the last available slot on some runs and not
    others.
    """
    events = [
        (float(bar.get("timestamp", 0)), symbol, index)
        for symbol, series in bars.items()
        for index, bar in enumerate(series)
    ]
    events.sort(key=lambda e: (e[0], e[1]))
    return events


def run_portfolio(
    markets: Sequence[Market],
    bars: Mapping[str, Sequence[dict]],
    *,
    starting_cash: float = 10_000.0,
    sizing: Sizing | None = None,
    limits: Limits | None = None,
    fee: float = 0.001,
    slippage: float = 0.0005,
    since_index: int = 0,
    halt: Halt | None = None,
) -> PortfolioRun:
    """Walk every market together and return what the account did.

    Deterministic and offline: the same bars always produce the same run, which
    is what lets the live loop replay everything on each poll rather than carry
    mutable position state across network calls.

    ``halt`` is passed in rather than discovered, because whether the system is
    stopped is a fact that lives outside this function. A halt blocks new
    entries and never blocks an exit.
    """
    sizing = sizing or Sizing()
    limits = limits or Limits()
    by_symbol = {m.symbol: m for m in markets}
    rules = {m.symbol: get_strategy(m.strategy) for m in markets}

    account = Portfolio(cash=starting_cash, fee=fee, slippage=slippage)
    run = PortfolioRun(portfolio=account)
    run.closes = {m.symbol: [] for m in markets}
    run.marks = {m.symbol: [] for m in markets}

    pending: dict[str, Signal] = {}
    last_close: dict[str, float] = {}
    hold_units: dict[str, float] = {}
    slice_each = starting_cash / max(len(by_symbol), 1)
    session_open_equity: float | None = None
    session_boundary = 0.0
    halted = halt is not None
    silenced: set[str] = set()

    events = _timeline({s: bars[s] for s in by_symbol if s in bars})

    for step, (stamp, symbol, index) in enumerate(events):
        market = by_symbol[symbol]
        series = bars[symbol]
        bar = series[index]
        open_price = float(bar["open"])
        low_price = float(bar["low"])
        close_price = float(bar["close"])
        seconds = stamp / 1000 if stamp > 1e11 else stamp

        # 1. Yesterday's decision trades at today's open, before today's close
        #    is visible to anything.
        signal = pending.pop(symbol, None)
        if signal is not None:
            if signal.action == "sell" and account.holds(symbol):
                trade = account.sell(symbol, open_price, index=step, reason=signal.reason)
                _record(run, symbol, step, "sell", open_price, seconds, signal.reason)
            elif signal.action == "buy" and not account.holds(symbol):
                # Re-checked HERE, at the fill, not only where the signal was
                # generated. Signals are made at one bar's close and filled at
                # the next bar's open, so three correlated symbols signalling in
                # the same window all saw an empty book, all passed the cap, and
                # all opened. The exposure rule silently did nothing, which is
                # the worst way for a risk control to fail.
                refusal = blocked_reason(symbol, account, last_close, limits)
                if halted:
                    run.refusals.append((seconds, symbol, "halted, so no new entries"))
                elif refusal:
                    run.refusals.append((seconds, symbol, refusal))
                else:
                    stop = signal.stop
                    quantity = position_size(
                        account.equity(last_close), account.cash, open_price,
                        policy=sizing, stop=stop, whole_units=market.whole_units,
                    )
                    if quantity > 0 and account.buy(
                        symbol, open_price, quantity, stop=stop, index=step
                    ):
                        _record(run, symbol, step, "buy", open_price, seconds, signal.reason)

        # 2. Stops, before anything else looks at this bar. A gap through the
        #    stop fills at the open, which is where it actually would have.
        holding = account.holdings.get(symbol)
        if holding is not None and holding.stop is not None and low_price <= holding.stop:
            exit_price = min(open_price, holding.stop)
            gapped = open_price < holding.stop
            account.sell(symbol, exit_price, index=step, reason="stop")
            _record(
                run, symbol, step, "sell", exit_price, seconds,
                f"stopped out at {exit_price:,.2f}"
                + (", gapped through the stop" if gapped else ""),
            )

        last_close[symbol] = close_price
        run.closes[symbol].append(close_price)

        # The benchmark buys every market once, equally weighted, and then does
        # nothing. Computed whether or not anyone asked for it.
        if symbol not in hold_units and open_price > 0:
            hold_units[symbol] = slice_each / open_price

        equity = account.equity(last_close)
        run.equity.append(equity)
        # A symbol that has not printed its first bar yet is still holding its
        # share as cash. Counting only the symbols bought so far made the
        # benchmark start at one third of the capital and climb as the others
        # initialised, which showed up on real data as buy-and-hold returning
        # 200% over three hundred bars. The line was pure initialisation.
        run.benchmark.append(sum(
            hold_units[s] * last_close[s] if s in hold_units else slice_each
            for s in by_symbol
        ))
        run.stamps.append(seconds)

        # 3. Session boundary, for the daily loss limit. An explicit offset,
        #    because "today" is not obvious on a market that never closes and a
        #    limit that resets at the wrong hour hands you a fresh budget in the
        #    middle of the session that was going badly.
        boundary = session_start(seconds, limits.session_offset_hours)
        if boundary != session_boundary:
            session_boundary = boundary
            session_open_equity = equity

        # 4. Limits, evaluated only over activity since the halt was cleared.
        if not halted:
            breach = check_limits(
                account, run.equity, limits,
                since_index=since_index, session_equity_open=session_open_equity,
            )
            if breach is not None:
                halted = True
                run.breach = breach
                run.halted_at = step
                run.decisions.append(Decision(
                    time=seconds, symbol="", action="halt", reason=breach.detail,
                ))

        # 5. Decide. Exits stay available while halted; entries do not.
        #
        #    The warmup is the longer of what the rules need and what the
        #    sizing policy needs. Using only the strategy's own figure meant
        #    every entry signalled before the volatility estimate was ready got
        #    refused and logged as a complaint, which is noise for most rules
        #    and total silence for any rule that signals early and rarely.
        strategy = rules[symbol]
        if index + 1 >= max(strategy.warmup, _sizing_warmup(sizing)):
            decision = strategy.decide(series[: index + 1])
            if decision.action == "sell" and account.holds(symbol):
                pending[symbol] = decision
            elif decision.action == "buy" and not account.holds(symbol) and halted:
                # Logged, once per symbol, because the silent version was a real
                # problem: a system halted at 6% of its history went on to
                # produce zero trades and zero refusals for the other 94%, and
                # read as rules that simply never fired. The reported return
                # described a system that had switched itself off.
                if symbol not in silenced:
                    silenced.add(symbol)
                    run.refusals.append((
                        seconds, symbol,
                        "halted, so entries are blocked from here on. Everything "
                        "after this point is a stopped system, not a running one.",
                    ))
            elif decision.action == "buy" and not account.holds(symbol) and not halted:
                stop = stop_price(series[: index + 1], sizing)
                refusal = blocked_reason(symbol, account, last_close, limits)
                if refusal:
                    run.refusals.append((seconds, symbol, refusal))
                elif stop is None:
                    run.refusals.append((
                        seconds, symbol,
                        "not enough history yet to measure volatility, so there is "
                        "no honest stop distance to size against",
                    ))
                else:
                    pending[symbol] = Signal(decision.action, decision.reason, stop=stop)

    return run


def _sizing_warmup(sizing: Sizing) -> int:
    """Bars needed before the sizing policy can produce an honest stop."""
    from .sizing import ATR_PERIOD

    return ATR_PERIOD + 1 if sizing.stop_source == "atr" else 1


def _record(run: PortfolioRun, symbol: str, step: int, side: str,
            price: float, when: float, reason: str) -> None:
    run.marks[symbol].append(Mark(index=len(run.closes[symbol]), side=side, price=price))
    run.decisions.append(Decision(time=when, symbol=symbol, action=side, reason=reason))
