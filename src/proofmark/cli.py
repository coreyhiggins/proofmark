"""Command line entry point.

``proofmark check results.csv`` for people who live in a terminal.
``proofmark gui`` for people who do not.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
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


def default_state_path() -> Path:
    """Where a run writes its state when nobody says otherwise.

    Beside the user's own files rather than in a temp directory, because a
    paper run is a record someone may want tomorrow, and because the app has
    to be able to find it without being told.
    """
    return Path.home() / ".proofmark" / "live.json"


def _run_live(args) -> int:
    from .runner import DEFAULT_FEE, DEFAULT_POLL_SECONDS, DEFAULT_SLIPPAGE, run_forever, run_once
    from .strategies import describe_all

    if args.list_strategies:
        print()
        print(describe_all())
        print()
        return 0

    state_path = Path(args.state) if args.state else default_state_path()
    fee = DEFAULT_FEE if args.fee is None else args.fee
    slippage = DEFAULT_SLIPPAGE if args.slippage is None else args.slippage
    every = DEFAULT_POLL_SECONDS if args.every is None else args.every

    settings = dict(
        venue=args.venue, symbol=args.symbol, timeframe=args.timeframe,
        strategy=args.strategy, state_path=state_path, starting_cash=args.cash,
        fee=fee, slippage=slippage,
    )

    print()
    print(f"  paper trading {args.symbol} {args.timeframe} on {args.venue}")
    print(f"  strategy      {args.strategy}")
    print(f"  costs         {fee:.3%} fee and {slippage:.3%} slippage, per side")
    print(f"  state         {state_path}")
    print()
    print("  No order can be placed from here. Watch it with:")
    print(f"      proofmark app --state {state_path}")
    print()

    def report(run) -> None:
        gap = run.total_return - run.benchmark_return
        print(
            f"  {time.strftime('%H:%M:%S')}  "
            f"account {run.equity[-1]:,.2f}  "
            f"return {run.total_return:+.2%}  "
            f"holding {run.benchmark_return:+.2%}  "
            f"difference {gap:+.2%}"
        )

    try:
        if args.once:
            report(run_once(**settings))
            return 0
        run_forever(**settings, poll_seconds=every, on_cycle=report)
    except KeyboardInterrupt:
        print("\n  stopped")
        return 0
    except ValueError as err:
        print(f"  {err}")
        return 1
    except ImportError as err:
        # ccxt lives behind an extra, so this is the expected failure for
        # someone who installed the base package and typed the obvious command.
        print(f"  {err}")
        print("  Install the market data support with: pip install 'proofmark[crypto]'")
        return 1
    return 0


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

    app = sub.add_parser("app", help="open proofmark in its own window (recommended)")
    app.add_argument("--state", default=None,
                     help="path to a state file your bot writes, to enable the live view")

    gui = sub.add_parser("gui", help="serve the page and open it in your browser instead")
    gui.add_argument("--port", type=int, default=8765)
    gui.add_argument("--no-browser", action="store_true")
    gui.add_argument("--state", default=None,
                     help="path to a state file your bot writes, to enable the live view at /live")
    gui.add_argument("--host", default="127.0.0.1",
                     help="interface to bind. Leave this alone unless you are in a "
                          "container: the page has no password.")

    live = sub.add_parser(
        "run",
        help="run a strategy on live market data, on paper, and watch it",
        description="Paper trading against a live feed. No key is ever used that "
                    "could place an order, and there is no flag that makes one.",
    )
    live.add_argument("--symbol", default="BTC/USDT")
    live.add_argument("--venue", default="okx")
    live.add_argument("--timeframe", default="1h")
    live.add_argument("--strategy", default="ema-cross",
                      help="one of the built-in rule sets, or --list-strategies")
    live.add_argument("--cash", type=float, default=10_000.0,
                      help="starting paper balance")
    live.add_argument("--fee", type=float, default=None,
                      help="fee per side as a fraction, e.g. 0.001 for 0.1 percent")
    live.add_argument("--slippage", type=float, default=None,
                      help="assumed slippage per side as a fraction")
    live.add_argument("--every", type=int, default=None,
                      help="seconds between polls")
    live.add_argument("--state", default=None,
                      help="where to write the state file the live view reads")
    live.add_argument("--once", action="store_true",
                      help="run one cycle and exit instead of polling")
    live.add_argument("--list-strategies", action="store_true",
                      help="print the built-in rule sets and stop")

    upd = sub.add_parser("update", help="check for and install a newer version")
    upd.add_argument("--check", action="store_true", help="only report, do not install")

    venues_cmd = sub.add_parser("venues", help="what each exchange actually gives you")
    venues_cmd.add_argument("venue", nargs="?", help="one venue, or omit for all")

    args = parser.parse_args(argv)

    if args.command == "update":
        from .update import run_update
        return run_update(check_only=args.check)

    if args.command == "venues":
        from .venues import VENUES, describe
        names = [args.venue] if args.venue else sorted(VENUES)
        print()
        for name in names:
            print(describe(name))
            print()
        return 0

    if args.command == "run":
        return _run_live(args)

    # If a run is already going and nobody passed --state, watch it anyway.
    # Requiring the path means the live view is empty for the person who
    # followed the two obvious commands in order, which reads as broken.
    state = args.state if args.command in ("app", "gui") else None
    if args.command in ("app", "gui") and not state:
        default = default_state_path()
        state = str(default) if default.exists() else None

    if args.command == "app":
        from .desktop import run_window
        return run_window(state_path=state)

    if args.command == "gui":
        from .gui import serve
        serve(port=args.port, open_browser=not args.no_browser, host=args.host,
              state_path=state)
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
