"""A local, zero-dependency window onto the guards.

Someone who runs a trading bot is not necessarily someone who wants to import
a Python module to find out whether their results are trustworthy. This is the
same checks behind a page: paste a column of numbers, get a plain answer.

Design constraints, in order:

- **Zero dependencies.** ``http.server`` and one HTML string. Adding Flask to
  show a table would break the promise that makes the library adoptable.
- **Local only.** Binds to 127.0.0.1. It reads nothing from disk, writes
  nothing, and makes no outbound request. Your equity curve stays on your
  machine, which matters because that curve is a record of your money.
- **Plain language.** The library says ``search-without-correction``. The page
  says you tested 200 variants and picked the best one, which is not the same
  as finding something that works.
"""

from __future__ import annotations

import http.server
import json
import socketserver
import threading
import webbrowser
from pathlib import Path
from typing import Any

import time

from .charts import equity_chart, price_chart, underwater_chart
from .compare import leaderboard_from_rows, parse_rows
from .live import alerts, read_state
from .livepage import LIVE_PAGE
from .page import PAGE
from .guards import Severity, check
from .metrics import summarise

# Column names people actually use, in the order we prefer them.
EQUITY_NAMES = ("equity", "balance", "nav", "value", "portfolio_value", "total", "close")
PNL_NAMES = ("pnl", "profit", "trade_pnl", "profit_abs", "realized_pnl", "result")

# The page itself lives in page.py so this file is only the server.



def _analyse(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the guards over a parsed payload. Returns something JSON-safe."""
    equity = [float(v) for v in payload.get("equity") or []]
    if len(equity) < 2:
        return {"error": "Paste at least two account values so there is a change to measure."}
    if any(v <= 0 for v in equity):
        return {"error": "Account values must all be above zero. Check for a stray header or a blank line."}

    pnls = [float(v) for v in payload.get("pnls") or []]
    result = summarise(equity, pnls)
    benchmark = [float(v) for v in payload.get("benchmark") or []]

    # The comparison the page already draws, handed to the guards so it becomes
    # a finding rather than only a caption. Without this the page could show a
    # strategy losing 38% while holding gained 77% and say nothing about it,
    # which is exactly what it did until someone actually looked at the screen.
    benchmark_return = None
    if len(benchmark) >= 2 and benchmark[0]:
        benchmark_return = (benchmark[-1] / benchmark[0]) - 1

    delisted = {"yes": True, "no": False}.get(payload.get("delisted"), None)
    verdict = check(
        result,
        trials=max(1, int(payload.get("trials") or 1)),
        costs_applied=payload.get("costs"),
        delisted_included=delisted,
        benchmark_return=benchmark_return,
    )

    def show(value: float | None, pct: bool = False) -> str:
        if value is None:
            return "undefined"
        return f"{value:.1%}" if pct else f"{value:.2f}"

    return {
        "reportable": verdict.reportable,
        "charts": {
            "equity": equity_chart(equity, benchmark or None),
            "underwater": underwater_chart(equity),
        },
        "findings": [
            {"severity": f.severity.value, "detail": f.detail, "why": f.why}
            # Fatal first: the thing that invalidates the run should be read first.
            for f in sorted(verdict.findings, key=lambda f: f.severity is not Severity.FATAL)
        ],
        "metrics": [
            ("Steps measured", str(result.bars)),
            ("Trades", str(result.trades)),
            ("Total return", show(result.total_return, pct=True)),
            ("Worst drop from a peak", show(result.max_drawdown, pct=True)),
            ("Win rate", show(result.win_rate, pct=True)),
            ("Sharpe", show(result.sharpe)),
            ("Sortino", show(result.sortino)),
            ("Calmar", show(result.calmar)),
            ("Profit factor", show(result.profit_factor)),
        ],
    }


def _compare(payload: dict[str, Any]) -> dict[str, Any]:
    """Rank pasted strategies with buy-and-hold sitting among them as a row."""
    rows = parse_rows(str(payload.get("rows") or ""))
    if not rows:
        return {"error": "Each line needs a name and a return, separated by a comma."}

    hold = float(payload.get("hold") or 0.0)
    if abs(hold) > 3:  # entered as a percentage, same reading as the rows
        hold /= 100

    board = leaderboard_from_rows(rows, benchmark_return=hold)
    return {
        "headline": board.headline,
        "lost": bool(board.beaten_by_holding),
        "lesson": board.win_rate_lesson(),
        "entries": [
            {
                "name": e.name,
                "ret": f"{e.total_return:+.1%}",
                # A separate column, because colouring a genuine +101.6% red for
                # losing to the benchmark reads as "this lost money". It did
                # not. It gained, and still cost you 6.9 points against sitting
                # still, which is a different sentence and deserves its own one.
                "gap": "" if e.is_benchmark else f"{e.total_return - board.benchmark_return:+.1%}",
                "win": f"{e.win_rate:.1%}" if e.win_rate is not None else "-",
                "benchmark": e.is_benchmark,
                "beaten": not e.is_benchmark and e.total_return < board.benchmark_return,
                "negative": e.total_return < 0,
            }
            for e in board.ranked
        ],
    }


def _check_system(state_path: str, name: str) -> dict[str, Any]:
    """Run a system over history and record the verdict against its fingerprint.

    Synchronous on purpose. It takes seconds, it is the one thing a person
    should watch happen, and a background check that silently unlocks a button
    later is how a gate becomes something people stop reading.
    """
    from .systems import Store, requirements
    from .verify import explain, fetch_history, verify

    store = Store(Path(state_path).parent)
    system = {s.name: s for s in store.all()}.get(name)
    if system is None:
        return {"error": f"No system called {name!r}."}

    blockers = [r for r in requirements(system) if "IEX" not in r]
    if blockers:
        return {"error": blockers[0]}

    try:
        bars = fetch_history(system, limit=1000)
    except Exception as err:  # noqa: BLE001
        return {"error": f"Could not fetch history: {err}"}

    verification, run = verify(system, bars)
    store.record(system, verification)

    return {
        "passed": verification.passed,
        "summary": verification.summary,
        "findings": verification.findings,
        "explanation": explain(verification),
        "totalReturn": f"{verification.total_return:+.1%}",
        "benchmarkReturn": f"{verification.benchmark_return:+.1%}",
        "beatHolding": verification.beat_holding,
        "trades": verification.trades,
        "bars": verification.bars,
        "chart": equity_chart(run.equity, run.benchmark or None, animate=False),
    }


def _systems_payload(state_path: str | None) -> list[dict[str, Any]]:
    """Every system, with whether it is cleared to run and what it still needs."""
    if not state_path:
        return []

    from .systems import Store, requirements

    store = Store(Path(state_path).parent)
    out: list[dict[str, Any]] = []
    for system in store.all():
        allowed, why = store.may_run(system)
        verification = store.verification(system)
        out.append({
            "name": system.name,
            "description": system.description,
            "venue": system.venue,
            "markets": [
                {"symbol": m.symbol, "strategy": m.strategy, "timeframe": m.timeframe}
                for m in system.markets
            ],
            "risk": f"{system.sizing.risk_per_trade:.1%} per trade, "
                    f"{system.sizing.atr_multiple:g}x ATR stop",
            "guard": f"{system.limits.daily_loss:.0%} daily, "
                     f"{system.limits.max_drawdown:.0%} drawdown"
                     if system.limits.daily_loss and system.limits.max_drawdown else "",
            "needs": requirements(system),
            "cleared": allowed,
            "why": why,
            "verified": None if verification is None else {
                "passed": verification.passed,
                "summary": verification.summary,
                "totalReturn": f"{verification.total_return:+.1%}",
                "benchmarkReturn": f"{verification.benchmark_return:+.1%}",
                "beatHolding": verification.beat_holding,
                "trades": verification.trades,
            },
        })
    return out


def _when(stamp: float) -> str:
    """A decision's time, dated when it was not today."""
    if not stamp:
        return ""
    moment = time.localtime(stamp)
    today = time.localtime()
    if (moment.tm_year, moment.tm_yday) == (today.tm_year, today.tm_yday):
        return time.strftime("%H:%M", moment)
    return time.strftime("%b %d %H:%M", moment)


def _live_summary(state) -> list[list[str]]:
    """The four numbers worth putting above the charts.

    The gap against holding is one of them, and it is not the last one. A live
    dashboard that reports a return without the comparison is telling you the
    half of the story you already wanted to hear.
    """
    if len(state.equity) < 2 or not state.equity[0]:
        return []

    total = state.equity[-1] / state.equity[0] - 1
    rows = [
        ["Account", f"{state.equity[-1]:,.2f}"],
        ["Return", f"{total:+.1%}"],
    ]

    if len(state.benchmark) >= 2 and state.benchmark[0]:
        held = state.benchmark[-1] / state.benchmark[0] - 1
        rows.append(["Holding", f"{held:+.1%}"])
        rows.append(["Difference", f"{total - held:+.1%}"])

    peak = state.equity[0]
    worst = 0.0
    for value in state.equity:
        peak = max(peak, value)
        worst = min(worst, (value - peak) / peak if peak else 0.0)
    rows.append(["Worst drop", f"{worst:.1%}"])
    return rows


def _live_payload(path: str | None) -> dict[str, Any]:
    """Everything the live page needs, in one poll.

    The guards run over the live equity curve too, which is the point of
    putting this in proofmark rather than in a dashboard. A strategy that
    drifts into a 100% win rate or a zero drawdown in production is showing
    you the same impossibility a backtest would, and it is showing you with
    real money on the table.
    """
    from .strategies import BUILTIN

    # Sent on every poll, whether or not there is anything to watch, because
    # the start form has to be reachable from the empty state. That empty state
    # is where every new user begins.
    from .limits import HaltFile

    halt = HaltFile(Path(path).parent / "halt").read() if path else None

    control: dict[str, Any] = {
        "running": SESSION.running,
        "canStart": bool(path),
        "settings": SESSION.settings,
        "error": SESSION.error,
        "systems": _systems_payload(path),
        "halt": None if halt is None else {
            "reason": halt.reason, "code": halt.code, "manual": halt.manual,
        },
        "strategies": [
            {"name": s.name, "summary": s.summary} for s in
            sorted(BUILTIN.values(), key=lambda s: s.name)
        ],
    }

    if not path:
        return {"present": False, "control": control,
                "hint": "Started without somewhere to write results."}

    state = read_state(path)
    if state is None:
        return {
            "present": False,
            "control": control,
            "hint": "Nothing has run yet.",
        }

    verdict_findings: list[dict[str, str]] = []
    chart = ""
    if len(state.equity) >= 2:
        chart = equity_chart(state.equity, state.benchmark or None, animate=False)
        try:
            # The benchmark goes in here too. A live run that is behind buying
            # and holding is the same finding as a backtest that is, and the
            # live one is the version costing real money right now.
            bench_return = None
            if len(state.benchmark) >= 2 and state.benchmark[0]:
                bench_return = state.benchmark[-1] / state.benchmark[0] - 1
            live = check(
                summarise(state.equity, []),
                delisted_included=True,
                benchmark_return=bench_return,
            )
            verdict_findings = [
                {"severity": f.severity.value, "detail": f.detail, "why": f.why}
                for f in live.fatal
            ]
        except ValueError:
            verdict_findings = []

    # Animation off on every live chart. These redraw on a timer, and a line
    # that restarts its draw-on every few seconds is a strobe, not a flourish.
    price = ""
    if len(state.closes) >= 2:
        price = price_chart(
            state.closes,
            [(m.index, m.side, m.price) for m in state.marks],
            label=state.label,
            animate=False,
        )

    return {
        "present": True,
        "control": control,
        "mode": state.mode,
        "age": state.age,
        "stale": state.stale,
        "label": state.label,
        "strategy": state.strategy,
        "alerts": [list(a) for a in alerts(state)],
        "verdict": verdict_findings,
        "chart": chart,
        "price": price,
        "underwater": underwater_chart(state.equity, animate=False) if len(state.equity) >= 2 else "",
        "summary": _live_summary(state),
        "positions": [
            {
                "symbol": p.symbol, "quantity": p.quantity, "entry": p.entry,
                "current": p.current, "stop": p.stop, "unrealised": p.unrealised,
            }
            for p in state.positions
        ],
        "decisions": [
            {
                # A bare clock time is unreadable on a run spanning days: the
                # column reads 00:00, 01:00, 05:00, 03:00 and looks shuffled
                # when it is simply four different dates. Date it unless it
                # happened today.
                "clock": _when(d.time),
                "symbol": d.symbol, "action": d.action, "reason": d.reason,
            }
            # Newest first: the last thing it decided is the thing you came for.
            for d in reversed(state.decisions)
        ],
    }


class _Session:
    """The one paper run this process is allowed to have going.

    The packaged app is built ``--windowed``, so it has no console: a person
    who installed the .exe cannot type ``proofmark run`` and see anything at
    all. Starting the run from the page is not a convenience, it is the only
    route that exists for most of the people this is for.

    One run at a time, on purpose. Two runs writing the same state file is a
    display that flickers between two strategies, and the second most confusing
    thing a live view can do is show numbers that are each individually true.
    """

    def __init__(self) -> None:
        self.thread: threading.Thread | None = None
        self.stop = threading.Event()
        self.settings: dict[str, Any] = {}
        self.error = ""
        self.system: Any = None
        self.checking = ""

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start_system(self, state_path: str, name: str) -> str:
        """Start a saved system. Refuses anything that has not passed the check."""
        if self.running:
            return "A run is already going. Stop it before starting another."

        from .systems import Store, requirements

        store = Store(Path(state_path).parent)
        system = {s.name: s for s in store.all()}.get(name)
        if system is None:
            return f"No system called {name!r}."

        blockers = [r for r in requirements(system) if "IEX" not in r]
        if blockers:
            return blockers[0]

        allowed, why = store.may_run(system)
        if not allowed:
            return why

        self.error = ""
        self.stop.clear()
        self.system = system
        self.settings = {"symbol": ", ".join(system.symbols), "venue": system.venue,
                         "timeframe": "mixed", "strategy": system.name}
        self.thread = threading.Thread(
            target=self._system_loop, args=(state_path,), daemon=True,
            name="proofmark-system",
        )
        self.thread.start()
        return ""

    def _system_loop(self, state_path: str) -> None:
        from .runner import DEFAULT_POLL_SECONDS, run_system_once

        while not self.stop.is_set():
            try:
                run_system_once(self.system, state_path)
                self.error = ""
            except Exception as err:  # noqa: BLE001
                self.error = str(err)
            self.stop.wait(DEFAULT_POLL_SECONDS)

    def start(self, state_path: str, settings: dict[str, Any]) -> str:
        if self.running:
            return "A run is already going. Stop it before starting another."

        from .strategies import BUILTIN

        symbol = str(settings.get("symbol") or "").strip().upper()
        if not symbol:
            return "Give it a symbol, for example BTC/USDT."
        strategy = str(settings.get("strategy") or "")
        if strategy not in BUILTIN:
            return f"No strategy called {strategy!r}."

        try:
            cash = float(settings.get("cash") or 10_000)
        except (TypeError, ValueError):
            return "Starting balance has to be a number."
        if cash <= 0:
            return "Starting balance has to be above zero."

        self.error = ""
        self.stop.clear()
        self.settings = {
            "venue": str(settings.get("venue") or "okx"),
            "symbol": symbol,
            "timeframe": str(settings.get("timeframe") or "1h"),
            "strategy": strategy,
            "starting_cash": cash,
        }
        self.thread = threading.Thread(
            target=self._loop, args=(state_path,), daemon=True, name="proofmark-run",
        )
        self.thread.start()
        return ""

    def _loop(self, state_path: str) -> None:
        from .runner import DEFAULT_POLL_SECONDS, run_once

        while not self.stop.is_set():
            try:
                run_once(state_path=state_path, **self.settings)
                self.error = ""
            except Exception as err:  # noqa: BLE001
                # Surfaced on the page rather than raised. A background thread
                # that dies silently leaves a live view that simply stops
                # updating, which reads as a dead exchange rather than as the
                # typo in the symbol that it usually is.
                self.error = str(err)
            # Interruptible sleep, so stopping is immediate rather than up to a
            # poll interval away.
            self.stop.wait(DEFAULT_POLL_SECONDS)

    def halt(self) -> None:
        self.stop.set()


SESSION = _Session()


class _Handler(http.server.BaseHTTPRequestHandler):
    state_path: str | None = None

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # This page never loads anything remote and never should.
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/live":
            self._send(200, LIVE_PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/state":
            payload = json.dumps(_live_payload(self.state_path)).encode("utf-8")
            self._send(200, payload, "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        if self.path in ("/run", "/stop", "/start-system", "/check-system", "/resume"):
            self._control()
            return

        if self.path not in ("/check", "/compare"):
            self._send(404, b"not found", "text/plain")
            return

        # Bounded read. This is a local tool, but an unbounded read is an
        # unbounded read.
        length = min(int(self.headers.get("Content-Length") or 0), 8 * 1024 * 1024)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            result = _analyse(payload) if self.path == "/check" else _compare(payload)
        except (ValueError, TypeError, KeyError) as err:
            result = {"error": f"Could not read those numbers: {err}"}

        self._send(200, json.dumps(result).encode("utf-8"), "application/json")

    def _control(self) -> None:
        """Start or stop the paper run. Loopback only, and paper only."""
        if self.path == "/stop":
            SESSION.halt()
            self._send(200, json.dumps({"ok": True}).encode("utf-8"), "application/json")
            return

        if self.path == "/resume":
            # Lifting a halt is deliberate and separate from starting a run.
            # Same button for both would let someone clear a drawdown breach by
            # pressing the thing they press every morning.
            from .limits import HaltFile

            if self.state_path:
                HaltFile(Path(self.state_path).parent / "halt").clear()
            self._send(200, json.dumps({"ok": True}).encode("utf-8"), "application/json")
            return

        if self.path in ("/start-system", "/check-system"):
            length = min(int(self.headers.get("Content-Length") or 0), 64 * 1024)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                body = {}
            name = str(body.get("name") or "") if isinstance(body, dict) else ""

            if not self.state_path:
                result = {"error": "This window has nowhere to write results."}
            elif self.path == "/check-system":
                result = _check_system(self.state_path, name)
            else:
                result = {"error": SESSION.start_system(self.state_path, name)}

            self._send(200, json.dumps(result).encode("utf-8"), "application/json")
            return

        if not self.state_path:
            self._send(200, json.dumps({
                "error": "This window was started without somewhere to write results."
            }).encode("utf-8"), "application/json")
            return

        length = min(int(self.headers.get("Content-Length") or 0), 64 * 1024)
        try:
            settings = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            settings = {}

        message = SESSION.start(self.state_path, settings if isinstance(settings, dict) else {})
        self._send(200, json.dumps({"error": message}).encode("utf-8"), "application/json")

    def log_message(self, *args: Any) -> None:
        """Silence the per-request logging. The terminal is not the product."""


def serve(port: int = 8765, open_browser: bool = True, host: str = "127.0.0.1",
          state_path: str | None = None) -> None:
    """Start the local page.

    ``host`` defaults to loopback and should usually stay there. The page has
    no authentication, so binding it to a public interface publishes your
    equity curve to anyone who scans the port. Containers need 0.0.0.0 to make
    port mapping work, which is why the option exists at all, and why it
    complains when you use it.
    """
    loopback = host in ("127.0.0.1", "localhost", "::1")
    _Handler.state_path = state_path

    with socketserver.TCPServer((host, port), _Handler) as httpd:
        if loopback:
            print(f"proofmark is running at http://{host}:{port}/")
            if state_path:
                print(f"          live view at http://{host}:{port}/live")
                print(f"          watching {state_path}")
            print("Everything stays on this machine. Press Ctrl+C to stop.")
        else:
            print(f"proofmark is listening on {host}:{port}")
            print()
            print("  WARNING: this is not loopback, and the page has no password.")
            print("  Anyone who can reach this port can read your results.")
            print("  If this is a server, publish the port to 127.0.0.1 and")
            print("  reach it over an SSH tunnel instead:")
            print()
            print(f"      ssh -N -L {port}:127.0.0.1:{port} you@this-machine")
            print()

        if open_browser and loopback:
            webbrowser.open(f"http://{host}:{port}/")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
