"""Command line entry point.

``proofmark check results.csv`` for people who live in a terminal.
``proofmark gui`` for people who do not.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Sequence

from .guards import check, format_verdict
from .gui import EQUITY_NAMES, PNL_NAMES
from .metrics import summarise


def _pick_column(header: Sequence[str], names: Sequence[str]) -> int | None:
    """Find a column by any of its common names, case and spacing insensitive."""
    normalised = [h.strip().lower().replace(" ", "_") for h in header]
    for name in names:
        if name in normalised:
            return normalised.index(name)
    return None


def _read_csv(path: Path) -> tuple[list[float], list[float]]:
    """Pull an equity curve and trade results out of a CSV.

    Deliberately forgiving about column names, because the alternative is
    telling someone their perfectly good export is the wrong shape.
    """
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        raise SystemExit(f"{path} is empty")

    header, body = rows[0], rows[1:]
    equity_col = _pick_column(header, EQUITY_NAMES)

    if equity_col is None:
        # No recognisable header. Treat a single-column file as the curve.
        if len(header) == 1:
            body = rows
            equity_col = 0
        else:
            raise SystemExit(
                f"Could not find an account value column in {path}.\n"
                f"Looked for: {', '.join(EQUITY_NAMES)}\n"
                f"Found: {', '.join(header)}"
            )

    pnl_col = _pick_column(header, PNL_NAMES)

    def numbers(index: int) -> list[float]:
        out = []
        for row in body:
            if index >= len(row):
                continue
            try:
                out.append(float(row[index].strip().replace(",", "").replace("$", "")))
            except ValueError:
                continue
        return out

    return numbers(equity_col), (numbers(pnl_col) if pnl_col is not None else [])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="proofmark",
        description="Find out whether a backtest result is safe to believe.",
    )
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("check", help="check a CSV of results")
    run.add_argument("path", type=Path)
    run.add_argument("--trials", type=int, default=1,
                     help="how many strategy variants were evaluated (every tweak counts)")
    run.add_argument("--costs", type=float, default=None,
                     help="total fees, spread and funding paid")
    run.add_argument("--delisted", choices=["yes", "no"], default=None,
                     help="whether the universe includes assets that no longer exist")

    gui = sub.add_parser("gui", help="open the local page in a browser")
    gui.add_argument("--port", type=int, default=8765)
    gui.add_argument("--no-browser", action="store_true")
    gui.add_argument("--state", default=None,
                     help="path to a state file your bot writes, to enable the live view at /live")
    gui.add_argument("--host", default="127.0.0.1",
                     help="interface to bind. Leave this alone unless you are in a "
                          "container: the page has no password.")

    venues_cmd = sub.add_parser("venues", help="what each exchange actually gives you")
    venues_cmd.add_argument("venue", nargs="?", help="one venue, or omit for all")

    args = parser.parse_args(argv)

    if args.command == "venues":
        from .venues import VENUES, describe
        names = [args.venue] if args.venue else sorted(VENUES)
        print()
        for name in names:
            print(describe(name))
            print()
        return 0

    if args.command == "gui":
        from .gui import serve
        serve(port=args.port, open_browser=not args.no_browser, host=args.host,
              state_path=args.state)
        return 0

    if args.command != "check":
        parser.print_help()
        return 0

    if not args.path.exists():
        raise SystemExit(f"no such file: {args.path}")

    equity, pnls = _read_csv(args.path)
    if len(equity) < 2:
        raise SystemExit("need at least two account values to measure a change")

    result = summarise(equity, pnls)
    verdict = check(
        result,
        trials=args.trials,
        costs_applied=args.costs,
        delisted_included={"yes": True, "no": False}.get(args.delisted),
    )

    def show(value: float | None, pct: bool = False) -> str:
        if value is None:
            return "undefined"
        return f"{value:.1%}" if pct else f"{value:.2f}"

    print()
    if not verdict.reportable:
        print("  THESE NUMBERS ARE NOT SAFE TO REPORT")
        print("  At least one result below is not possible for a real strategy.")
    else:
        print("  No obvious problems found.")
        print("  That is not the same as the strategy working.")
    print()

    for label, value in (
        ("steps", str(result.bars)),
        ("trades", str(result.trades)),
        ("total return", show(result.total_return, pct=True)),
        ("max drawdown", show(result.max_drawdown, pct=True)),
        ("win rate", show(result.win_rate, pct=True)),
        ("sharpe", show(result.sharpe)),
        ("sortino", show(result.sortino)),
        ("calmar", show(result.calmar)),
    ):
        print(f"  {label:<14} {value:>10}")

    print()
    print(format_verdict(verdict))
    print()

    # Non-zero when suppressed, so this can gate a pipeline.
    return 0 if verdict.reportable else 1


if __name__ == "__main__":
    sys.exit(main())
