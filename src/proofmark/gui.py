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
import webbrowser
from typing import Any

from .guards import Severity, check
from .metrics import summarise

# Column names people actually use, in the order we prefer them.
EQUITY_NAMES = ("equity", "balance", "nav", "value", "portfolio_value", "total", "close")
PNL_NAMES = ("pnl", "profit", "trade_pnl", "profit_abs", "realized_pnl", "result")

PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>proofmark</title>
<style>
  :root {
    color-scheme: light dark;
    --bg: #ffffff; --fg: #16191d; --muted: #5c6570; --line: #e2e6ea;
    --card: #f7f8fa; --fatal: #b4232a; --warn: #8a6100; --ok: #1a7f45;
    --accent: #2f6fdb;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #12161c; --fg: #e6edf3; --muted: #8b949e; --line: #2a3038;
      --card: #1a1f26; --fatal: #ff7b72; --warn: #d9a441; --ok: #56d364;
      --accent: #6ea8ff;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 40px 24px 80px; background: var(--bg); color: var(--fg);
    font: 15px/1.6 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  main { max-width: 720px; margin: 0 auto; }
  h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: -0.01em; }
  .sub { color: var(--muted); margin: 0 0 32px; }
  label { display: block; font-weight: 600; margin-bottom: 6px; }
  .hint { color: var(--muted); font-size: 13px; margin: 0 0 8px; font-weight: 400; }
  textarea, input[type=number] {
    width: 100%; padding: 10px 12px; border: 1px solid var(--line); border-radius: 8px;
    background: var(--bg); color: var(--fg); font: 13px/1.5 ui-monospace, Menlo, Consolas, monospace;
  }
  textarea { min-height: 132px; resize: vertical; }
  .row { display: flex; gap: 16px; flex-wrap: wrap; margin: 20px 0; }
  .row > div { flex: 1 1 180px; }
  button {
    margin-top: 24px; padding: 11px 22px; border: 0; border-radius: 8px;
    background: var(--accent); color: #fff; font-size: 15px; font-weight: 600; cursor: pointer;
  }
  button:disabled { opacity: .5; cursor: default; }
  fieldset { border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px; margin: 20px 0 0; }
  legend { font-weight: 600; padding: 0 6px; }
  fieldset label { font-weight: 400; margin: 6px 0; display: flex; gap: 8px; align-items: baseline; }
  #out { margin-top: 36px; }
  .verdict { padding: 18px 20px; border-radius: 10px; border: 1px solid var(--line); background: var(--card); }
  .verdict h2 { margin: 0 0 6px; font-size: 18px; }
  .verdict.bad h2 { color: var(--fatal); }
  .verdict.good h2 { color: var(--ok); }
  .finding { border-left: 3px solid var(--line); padding: 2px 0 2px 14px; margin: 18px 0; }
  .finding.fatal { border-left-color: var(--fatal); }
  .finding.warn { border-left-color: var(--warn); }
  .finding b { display: block; margin-bottom: 3px; }
  .finding p { margin: 0; color: var(--muted); font-size: 14px; }
  table { width: 100%; border-collapse: collapse; margin: 22px 0 0; font-size: 14px; }
  td { padding: 7px 0; border-bottom: 1px solid var(--line); }
  td:last-child { text-align: right; font-family: ui-monospace, Menlo, Consolas, monospace; }
  .err { color: var(--fatal); }
  footer { max-width: 720px; margin: 56px auto 0; color: var(--muted); font-size: 13px;
           border-top: 1px solid var(--line); padding-top: 16px; }
</style>
<main>
  <h1>proofmark</h1>
  <p class="sub">Paste your results. Find out whether the numbers are safe to believe.</p>

  <label for="equity">Account value over time</label>
  <p class="hint">One number per line, or comma separated. This is your balance at
    every step, not just when a trade closed. Paste a CSV column and it will find it.</p>
  <textarea id="equity" placeholder="10000&#10;10120&#10;9980&#10;10240"></textarea>

  <label for="pnls" style="margin-top:22px">Profit or loss per trade <span style="font-weight:400;color:var(--muted)">(optional)</span></label>
  <p class="hint">Negative numbers for losers. Used for win rate and profit factor.</p>
  <textarea id="pnls" placeholder="120&#10;-45&#10;260&#10;-30"></textarea>

  <div class="row">
    <div>
      <label for="trials">How many versions did you try?</label>
      <p class="hint">Every parameter tweak counts.</p>
      <input id="trials" type="number" min="1" value="1">
    </div>
    <div>
      <label for="costs">Total fees and slippage paid</label>
      <p class="hint">Leave blank if you did not model any.</p>
      <input id="costs" type="number" step="any" placeholder="e.g. 84.20">
    </div>
  </div>

  <fieldset>
    <legend>Did your data include assets that no longer exist?</legend>
    <label><input type="radio" name="delisted" value="yes"> Yes, delisted and bankrupt ones are in there</label>
    <label><input type="radio" name="delisted" value="no"> No, only things still trading today</label>
    <label><input type="radio" name="delisted" value="unknown" checked> I am not sure</label>
  </fieldset>

  <button id="go">Check my results</button>
  <div id="out"></div>
</main>
<footer>
  Runs entirely on your machine. Nothing you paste is uploaded, stored or sent anywhere.
  Passing every check does not mean a strategy works. It means the obvious ways of
  fooling yourself have been ruled out.
</footer>
<script>
const nums = s => (s.match(/-?\\d+(?:\\.\\d+)?(?:[eE][-+]?\\d+)?/g) || []).map(Number);

document.getElementById('go').onclick = async () => {
  const btn = document.getElementById('go');
  const out = document.getElementById('out');
  btn.disabled = true; out.innerHTML = '';

  const body = {
    equity: nums(document.getElementById('equity').value),
    pnls: nums(document.getElementById('pnls').value),
    trials: Number(document.getElementById('trials').value) || 1,
    costs: document.getElementById('costs').value === ''
      ? null : Number(document.getElementById('costs').value),
    delisted: document.querySelector('input[name=delisted]:checked').value,
  };

  try {
    const res = await fetch('/check', {method: 'POST', body: JSON.stringify(body)});
    render(await res.json());
  } catch (e) {
    out.innerHTML = '<p class="err">Could not reach the local server. Is it still running?</p>';
  }
  btn.disabled = false;
};

function render(d) {
  const out = document.getElementById('out');
  if (d.error) { out.innerHTML = `<p class="err">${d.error}</p>`; return; }

  const bad = !d.reportable;
  let html = `<div class="verdict ${bad ? 'bad' : 'good'}"><h2>${
    bad ? 'These numbers are not safe to report'
        : 'Nothing obviously wrong'}</h2><p>${
    bad ? 'At least one result here is not possible for a real strategy. Fix the cause before reading anything else on this page.'
        : 'The usual ways a backtest misleads you were checked and did not fire. That is not the same as the strategy working.'
  }</p></div>`;

  for (const f of d.findings) {
    html += `<div class="finding ${f.severity}"><b>${f.detail}</b><p>${f.why}</p></div>`;
  }

  html += '<table>';
  for (const [k, v] of d.metrics) html += `<tr><td>${k}</td><td>${v}</td></tr>`;
  out.innerHTML = html + '</table>';
}
</script>
"""


def _analyse(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the guards over a parsed payload. Returns something JSON-safe."""
    equity = [float(v) for v in payload.get("equity") or []]
    if len(equity) < 2:
        return {"error": "Paste at least two account values so there is a change to measure."}
    if any(v <= 0 for v in equity):
        return {"error": "Account values must all be above zero. Check for a stray header or a blank line."}

    pnls = [float(v) for v in payload.get("pnls") or []]
    result = summarise(equity, pnls)

    delisted = {"yes": True, "no": False}.get(payload.get("delisted"), None)
    verdict = check(
        result,
        trials=max(1, int(payload.get("trials") or 1)),
        costs_applied=payload.get("costs"),
        delisted_included=delisted,
    )

    def show(value: float | None, pct: bool = False) -> str:
        if value is None:
            return "undefined"
        return f"{value:.1%}" if pct else f"{value:.2f}"

    return {
        "reportable": verdict.reportable,
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


class _Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # This page never loads anything remote and never should.
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path not in ("/", "/index.html"):
            self._send(404, b"not found", "text/plain")
            return
        self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/check":
            self._send(404, b"not found", "text/plain")
            return

        # Bounded read. This is a local tool, but an unbounded read is an
        # unbounded read.
        length = min(int(self.headers.get("Content-Length") or 0), 8 * 1024 * 1024)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            result = _analyse(payload)
        except (ValueError, TypeError, KeyError) as err:
            result = {"error": f"Could not read those numbers: {err}"}

        self._send(200, json.dumps(result).encode("utf-8"), "application/json")

    def log_message(self, *args: Any) -> None:
        """Silence the per-request logging. The terminal is not the product."""


def serve(port: int = 8765, open_browser: bool = True) -> None:
    """Start the local page. Binds to loopback only."""
    with socketserver.TCPServer(("127.0.0.1", port), _Handler) as httpd:
        url = f"http://127.0.0.1:{port}/"
        print(f"proofmark is running at {url}")
        print("Everything stays on this machine. Press Ctrl+C to stop.")
        if open_browser:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
