"""One pool of money across several markets.

The engine used to hold one symbol, one strategy, and one position containing
every available dollar. That is fine for watching a single rule and useless for
the thing people actually want, which is several markets with different rules
and a risk budget shared between them.

WHY THIS IS A SEPARATE FILE FROM THE RUNNER.

Sizing and limits are both expressed in terms of total equity, not per-symbol
cash. A drawdown limit that only sees one symbol is not a drawdown limit. So
the account has to be the thing that knows about every position at once, and
the runner becomes the thing that walks bars and asks it questions.

WHAT IS DELIBERATELY NOT HERE.

No shorting, no leverage, no margin, no pyramiding into an existing position.
Every one of those is a way for a paper run to disagree with a real account,
and none of them is reachable before a person has learned something from the
simple version.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass
class Holding:
    """One open position.

    ``stop`` is the price at which the rules give up on it. It is set at entry
    and never widened, because a stop that moves away from you under pressure
    is the single most expensive habit in retail trading and an engine should
    not make it possible.
    """

    symbol: str
    quantity: float
    entry: float
    stop: float | None = None
    opened_at: int = 0

    def value(self, price: float) -> float:
        return self.quantity * price

    def unrealised(self, price: float) -> float:
        return (price - self.entry) * self.quantity

    def risk(self, price: float) -> float:
        """What is still on the table if the stop is hit from here.

        Zero once the stop sits above entry, because at that point the position
        cannot lose money and should stop consuming the risk budget.
        """
        if self.stop is None:
            return self.value(price)
        return max(0.0, (price - self.stop) * self.quantity)


@dataclass
class Trade:
    """A completed round trip, which is the only kind that has a real result."""

    symbol: str
    entry: float
    exit: float
    quantity: float
    costs: float
    opened_at: int
    closed_at: int
    reason: str = ""

    @property
    def pnl(self) -> float:
        return (self.exit - self.entry) * self.quantity - self.costs

    @property
    def won(self) -> bool:
        return self.pnl > 0


@dataclass
class Portfolio:
    """Cash plus open positions, priced together.

    Long only, one position per symbol. A second buy in a symbol already held
    is refused rather than averaged in: averaging changes the entry price, which
    silently invalidates the stop distance the position was sized against.
    """

    cash: float
    fee: float = 0.001
    slippage: float = 0.0005
    holdings: dict[str, Holding] = field(default_factory=dict)
    trades: list[Trade] = field(default_factory=list)
    costs_paid: float = 0.0

    def holds(self, symbol: str) -> bool:
        return symbol in self.holdings

    def equity(self, prices: Mapping[str, float]) -> float:
        """Total account value. Positions with no quoted price are held at cost.

        Falling back to entry rather than dropping the position is the safer of
        the two wrong answers: a missing quote should not make the account look
        like it just gained the value of that holding.
        """
        total = self.cash
        for symbol, holding in self.holdings.items():
            total += holding.value(prices.get(symbol, holding.entry))
        return total

    def exposure(self, prices: Mapping[str, float]) -> float:
        """Fraction of equity currently at market rather than in cash."""
        total = self.equity(prices)
        if total <= 0:
            return 0.0
        invested = sum(
            h.value(prices.get(s, h.entry)) for s, h in self.holdings.items()
        )
        return invested / total

    def buy(
        self,
        symbol: str,
        price: float,
        quantity: float,
        *,
        stop: float | None = None,
        index: int = 0,
    ) -> Holding | None:
        """Open a position of a given size. Returns None if it cannot happen.

        The size comes from the caller, because deciding it needs the whole
        account and a volatility estimate, and an account object that reaches
        for market data to size a trade is an account object doing two jobs.
        """
        if quantity <= 0 or price <= 0 or self.holds(symbol):
            return None

        fill = price * (1 + self.slippage)
        gross = quantity * fill
        cost = gross * self.fee
        if gross + cost > self.cash + 1e-9:
            return None

        self.cash -= gross + cost
        self.costs_paid += cost
        holding = Holding(symbol=symbol, quantity=quantity, entry=fill,
                          stop=stop, opened_at=index)
        self.holdings[symbol] = holding
        return holding

    def sell(self, symbol: str, price: float, *, index: int = 0,
             reason: str = "") -> Trade | None:
        holding = self.holdings.pop(symbol, None)
        if holding is None:
            return None

        fill = price * (1 - self.slippage)
        gross = holding.quantity * fill
        cost = gross * self.fee

        self.cash += gross - cost
        self.costs_paid += cost
        trade = Trade(
            symbol=symbol, entry=holding.entry, exit=fill,
            quantity=holding.quantity,
            # Both sides of the round trip, so a trade's pnl is what actually
            # landed in the account rather than the gross move.
            costs=cost + holding.entry * holding.quantity * self.fee,
            opened_at=holding.opened_at, closed_at=index, reason=reason,
        )
        self.trades.append(trade)
        return trade

    def stopped_out(self, prices: Mapping[str, float]) -> list[str]:
        """Symbols whose stop has been touched, checked against the low.

        Checked on the bar's low rather than its close. A stop that only
        triggers on closes is not a stop, it is a hope, and the difference
        shows up precisely on the days it was supposed to protect you.
        """
        return [
            symbol for symbol, holding in self.holdings.items()
            if holding.stop is not None and prices.get(symbol, holding.entry) <= holding.stop
        ]

    @property
    def consecutive_losses(self) -> int:
        streak = 0
        for trade in reversed(self.trades):
            if trade.won:
                break
            streak += 1
        return streak
