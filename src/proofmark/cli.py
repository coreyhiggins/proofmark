"""Command line entry point.

``proofmark check results.csv`` for people who live in a terminal.
``proofmark gui`` for people who do not.
"""

from __future__ import annotations

import argparse
import csv
import os
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


def _serve_headless(args) -> int:
    """Run a saved system forever with no window.

    A daily loss limit implies something running unattended, so the app-only
    version was never going to be enough: a limit that applies only while a
    window happens to be open is not a limit.
    """
    from .limits import HaltFile
    from .runner import DEFAULT_POLL_SECONDS, run_system_once
    from .systems import Store

    state_path = Path(args.state) if args.state else default_state_path()
    store = Store(state_path.parent)
    system = {s.name: s for s in store.all()}.get(args.system)
    if system is None:
        print(f"  no system called {args.system!r}")
        print(f"  available: {', '.join(s.name for s in store.all())}")
        return 1

    allowed, why = store.may_run(system)
    if not allowed:
        print(f"  refused: {why}")
        return 1

    every = args.every or DEFAULT_POLL_SECONDS
    halt_path = state_path.parent / "halt"
    log_path = state_path.parent / "log" / (system.name + ".jsonl")

    print()
    print(f"  {system.name}: {', '.join(system.symbols)} on {system.venue}")
    print(f"  paper only, checking every {every}s")
    print(f"  state {state_path}")
    print(f"  log   {log_path}")
    print(f"  stop it any time by creating {halt_path}")
    print()

    while True:
        try:
            run = run_system_once(system, state_path)
            flag = "  HALTED" if HaltFile(halt_path).active else ""
            print(
                f"  {time.strftime('%H:%M:%S')}  {run.equity[-1]:,.2f}  "
                f"{run.total_return:+.2%} against {run.benchmark_return:+.2%} holding"
                + flag
            )
        except KeyboardInterrupt:
            print("  stopped")
            return 0
        except Exception as err:  # noqa: BLE001
            print(f"  {time.strftime('%H:%M:%S')}  cycle failed: {err}")
        if args.once:
            return 0
        try:
            time.sleep(every)
        except KeyboardInterrupt:
            print("  stopped")
            return 0


def _autostart(args) -> int:
    """Add or remove a login shortcut on Windows.

    A file in the Startup folder rather than a scheduled task or a service: no
    elevation, no installer, and the user can see it and delete it in Explorer.
    A trading bot that can only be switched off by an administrator is worse
    than one that does not start itself.
    """
    if os.name != "nt":
        print("  autostart is Windows only for now.")
        print("  Elsewhere, run 'proofmark serve <system>' from a systemd unit,")
        print("  a launchd plist, or a terminal you leave open.")
        return 1

    startup = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"
    link = startup / "proofmark.cmd"

    if args.remove:
        link.unlink(missing_ok=True)
        print(f"  removed {link}")
        return 0

    if not args.system:
        print("  name a system, or pass --remove")
        return 1

    exe = Path(sys.executable)
    if exe.name.lower().startswith("proofmark"):
        command = f'"{exe}" serve {args.system}'
    else:
        command = f'"{exe}" -m proofmark serve {args.system}'

    startup.mkdir(parents=True, exist_ok=True)
    link.write_text("@echo off\r\n" + command + "\r\n", encoding="utf-8")

    print(f"  {args.system} will start when you log in")
    print(f"  {link}")
    print("  delete that file, or run 'proofmark autostart --remove', to stop")
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

    watch = sub.add_parser(
        "serve",
        help="run a saved system with no window, for leaving on",
        description="Headless. No window, no browser, just the loop and the log. "
                    "This is what you leave running.",
    )
    watch.add_argument("system", help="name of a saved system")
    watch.add_argument("--state", default=None)
    watch.add_argument("--every", type=int, default=None)
    watch.add_argument("--once", action="store_true")

    auto = sub.add_parser(
        "autostart",
        help="start a system when you log in, or stop doing that",
    )
    auto.add_argument("system", nargs="?", help="system to run at login")
    auto.add_argument("--remove", action="store_true")

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

    if args.command == "serve":
        return _serve_headless(args)

    if args.command == "autostart":
        return _autostart(args)

    # Always resolve a state path for the window, even when the file does not
    # exist yet. Without one the live view has nowhere to write, so its start
    # button has to be disabled, and a new user meets a dead control on the
    # first screen they open.
    state = None
    if args.command in ("app", "gui"):
        state = args.state or str(default_state_path())

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
