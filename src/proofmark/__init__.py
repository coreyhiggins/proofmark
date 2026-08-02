"""proofmark: a backtest engine whose defaults make self-deception expensive.

A proof mark is the stamp struck into metal certifying it survived testing.
The stamp is worth something only because the test could fail.

The core has no dependencies and runs on plain sequences of mappings, so you
can point it at whatever engine you already use.
"""

from .guards import Finding, Severity, Verdict, check, format_verdict
from .lookahead import LookaheadReport, assert_no_lookahead, check_lookahead
from .metrics import Metrics, equity_drawdown, summarise

__version__ = "0.1.0"

__all__ = [
    "Finding",
    "LookaheadReport",
    "Metrics",
    "Severity",
    "Verdict",
    "assert_no_lookahead",
    "check",
    "check_lookahead",
    "equity_drawdown",
    "format_verdict",
    "summarise",
]
