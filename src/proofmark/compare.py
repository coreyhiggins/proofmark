"""Comparing several strategies, with doing nothing as one of the candidates.

Two ideas here, both borrowed from a public writeup that tested twelve famous
strategies against Bitcoin. Its headline was about the one that won. Its
actual finding, in its own table, was that **eleven of twelve lost to buying
once and holding**.

That is the number a person needs, and almost nobody prints it.

WHY BUY AND HOLD IS A ROW AND NOT A FOOTNOTE.

Putting the benchmark in a separate chart lets a reader skip it. Putting it in
the same table, with the same columns, sorted among the strategies, makes the
comparison unavoidable. If doing nothing ranks third, the reader sees doing
nothing ranked third.

WIN RATE IS NOT EDGE, AND THE SAME TABLE PROVES IT.

In that writeup the winning strategy won **34.8%** of its trades. A strategy
winning **79.4%** made less than a quarter as much. Consumers reliably believe
a high win rate means a good strategy, and one sorted table disproves it
faster than any explanation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .metrics import Metrics

HOLD = "buy and hold"

# A win rate above this, in a strategy that still lost, is the clearest single
# example of why win rate is not edge.
HIGH_WIN_RATE = 0.65


@dataclass
class Entry:
    name: str
    total_return: float
    max_drawdown: float
    trades: int
    win_rate: float | None
    is_benchmark: bool = False


@dataclass
class Leaderboard:
    entries: list[Entry]
    benchmark_return: float

    @property
    def ranked(self) -> list[Entry]:
        return sorted(self.entries, key=lambda e: e.total_return, reverse=True)

    @property
    def strategies(self) -> list[Entry]:
        return [e for e in self.entries if not e.is_benchmark]

    @property
    def beaten_by_holding(self) -> list[Entry]:
        return [e for e in self.strategies if e.total_return < self.benchmark_return]

    @property
    def headline(self) -> str:
        """The one sentence worth putting above everything else."""
        lost = len(self.beaten_by_holding)
        total = len(self.strategies)
        if not total:
            return "nothing to compare"
        if lost == 0:
            return f"All {total} beat doing nothing."
        if lost == total:
            return f"All {total} lost to doing nothing."
        return f"{lost} of {total} lost to doing nothing."

    def win_rate_lesson(self) -> str | None:
        """Point at the pair that shows win rate is not edge, if one exists.

        Returns ``None`` when the data does not demonstrate it. Inventing the
        lesson when the numbers do not support it would be the same dishonesty
        this library exists to catch.
        """
        rated = [e for e in self.strategies if e.win_rate is not None and e.trades >= 5]
        if len(rated) < 2:
            return None

        best = max(rated, key=lambda e: e.total_return)
        most_wins = max(rated, key=lambda e: e.win_rate or 0)

        if best.name == most_wins.name:
            return None
        if (most_wins.win_rate or 0) <= (best.win_rate or 0):
            return None

        return (
            f"{best.name} won {best.win_rate:.1%} of its trades and returned "
            f"{best.total_return:.1%}. {most_wins.name} won {most_wins.win_rate:.1%} "
            f"and returned {most_wins.total_return:.1%}. Win rate is how often you "
            "are right. It says nothing about how much you make when you are, or "
            "lose when you are not."
        )


def leaderboard(
    results: Sequence[tuple[str, Metrics]],
    benchmark_return: float,
    *,
    benchmark_drawdown: float = 0.0,
) -> Leaderboard:
    """Build a ranked table with the benchmark sitting in it as a candidate."""
    entries = [
        Entry(
            name=name,
            total_return=m.total_return,
            max_drawdown=m.max_drawdown,
            trades=m.trades,
            win_rate=m.win_rate,
        )
        for name, m in results
    ]
    entries.append(Entry(
        name=HOLD,
        total_return=benchmark_return,
        max_drawdown=benchmark_drawdown,
        trades=1,
        win_rate=None,
        is_benchmark=True,
    ))
    return Leaderboard(entries=entries, benchmark_return=benchmark_return)


def format_leaderboard(board: Leaderboard) -> str:
    lines = [board.headline, ""]
    lines.append(f"  {'':>2}  {'strategy':<26}{'return':>9}{'max dd':>9}{'trades':>8}{'win rate':>10}")

    for position, entry in enumerate(board.ranked, start=1):
        marker = ">" if entry.is_benchmark else " "
        win = f"{entry.win_rate:.1%}" if entry.win_rate is not None else "-"
        lines.append(
            f"{marker} {position:>2}  {entry.name:<26}{entry.total_return:>8.1%}"
            f"{entry.max_drawdown:>8.1%}{entry.trades:>8}{win:>10}"
        )

    lesson = board.win_rate_lesson()
    if lesson:
        lines += ["", "  " + lesson]

    if board.beaten_by_holding:
        lines += [
            "",
            "  Every strategy below the marked row cost money against doing nothing.",
            "  Trading was worse than not trading.",
        ]

    return "\n".join(lines)
