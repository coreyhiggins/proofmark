"""proofmark: a backtest engine whose defaults make self-deception expensive.

A proof mark is the stamp struck into metal certifying it survived testing.
The stamp is worth something only because the test could fail.

The core has no dependencies and runs on plain sequences of mappings, so you
can point it at whatever engine you already use.
"""

from .charts import buy_and_hold, equity_chart, underwater_chart
from .guards import Finding, Severity, Verdict, check, format_verdict
from .lookahead import LookaheadReport, assert_no_lookahead, check_lookahead
from .live import Decision, Position, State, read_state, write_state
from .metrics import Metrics, equity_drawdown, summarise
from .venues import VENUES, describe, venue
from .walkforward import WalkForwardResult, format_walk_forward, walk_forward

# `data` is not imported here. It reaches for ccxt, which lives behind an
# extra, and a core import that fails on a missing optional dependency would
# make the zero-dependency promise false in the most annoying way possible.
# Import it yourself: `from proofmark.data import fetch_ohlcv`.

__version__ = "0.2.0"

__all__ = [
    "VENUES",
    "Decision",
    "Finding",
    "LookaheadReport",
    "Metrics",
    "Position",
    "Severity",
    "State",
    "Verdict",
    "WalkForwardResult",
    "assert_no_lookahead",
    "buy_and_hold",
    "describe",
    "equity_chart",
    "format_walk_forward",
    "read_state",
    "underwater_chart",
    "venue",
    "walk_forward",
    "write_state",
    "check",
    "check_lookahead",
    "equity_drawdown",
    "format_verdict",
    "summarise",
]
