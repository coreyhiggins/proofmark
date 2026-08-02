# proofmark

A backtest engine whose defaults make self-deception expensive.

A proof mark is the stamp struck into metal certifying it survived testing.
The stamp is worth something only because the test could fail.

```python
from proofmark import check, summarise, check_lookahead

report = check_lookahead(my_strategy, bars)      # property test, every bar
result = summarise(equity_curve, trade_pnls)     # undefined stays undefined
verdict = check(result, trials=200)              # suppressed, and it says why
```

```
FATAL  search-without-correction: 200 trials is a search, not a test
       At this many variants the best result is expected to look good by
       chance alone. Use walk-forward validation and report the
       snooping-adjusted statistic, or do not report a headline number.
```

## Why this exists

The most popular community strategy for the most popular open source trading
bot publishes an automated backtest with every commit. One of them reads:

```
Trades          45 (45 win, 0 loss)
Win Rate        100.0%
Max Drawdown    0.0%
Sharpe          42.73
Sortino/Calmar  -100.00 / -100.00
```

Sortino and Calmar of exactly -100.00 are a divide-by-zero sentinel, printed
as a headline metric beside a Sharpe of 42.73. Nothing suppressed it. That
strategy publishes roughly 270 such reports per commit, across more than
26,000 commits.

Meanwhile the most requested feature in a 21,000-star backtesting platform,
open for three years with 115 reactions, is walk-forward validation. It is
still not shipped. Another popular library advertises testing "hundreds of
strategy variants in mere seconds" with no mention of overfitting anywhere in
that method's documentation.

The gap is not another engine. It is defaults that cost you something when you
fool yourself.

## What it refuses to print

`check()` returns a verdict. Fatal findings suppress the report.

| Finding | Why it is fatal |
|---|---|
| 0% max drawdown with trades | Normally drawdown measured from realised profit at trade close, which lets any hold-until-green strategy report zero by construction |
| 100% win rate | A strategy that never loses has seen the future |
| Sharpe above 4 | Essentially never a strategy. Lookahead, survivorship, or unrealistic fills |
| Zero costs applied with trades | A cost model that silently applies nothing is worse than none, because the result looks priced |
| More than 50 trials | The best of a large search is expected to look good by chance |
| Universe excludes delisted assets | See below |

Warnings print alongside the report rather than replacing it: a small search,
a thin sample, an undefined ratio, or a caller who did not say whether
delisted assets are included. Unknown is reported as unknown. The flattering
assumption is the one that costs money.

### On survivorship

Measured survivorship bias on an equal-weighted crypto buy-and-hold portfolio
is **62% annualised**, across 3,904 assets of which 1,222 were delisted. The
same study found momentum and beta effects largely disappear once delisted
returns are included.

A survivors-only universe does not produce a smaller result. It produces a
different one.

### On searching

Sullivan, Timmermann and White searched 7,846 trading rules over a century of
index data. Their best out-of-sample rule:

```
nominal p-value          0.000
snooping-adjusted        0.341
```

On futures it was 0.042 against 0.908. Same rule, same data. The difference is
entirely whether you account for having searched thousands of alternatives
before picking the winner.

So a result carries its trial count, or it is not a result.

## The lookahead property test

```python
from proofmark import assert_no_lookahead

assert_no_lookahead(my_strategy, bars, executes_at="open")
```

For every bar, it rewrites every value the strategy could not have seen,
re-runs, and asserts the decision at that bar is unchanged. If rewriting the
future changes the past, the strategy is reading it.

What counts as the future depends on when you execute, and that is the
distinction the real bugs turn on:

- `executes_at="open"` means the order fills at that bar's open, so everything
  about the bar except its open is unobservable
- `executes_at="close"` means the bar is fully observable

`open` is the default because it is stricter, and because getting this wrong
in the permissive direction is the bug being hunted. One merged fix in another
project found five portfolio optimisers leaking at once, all through a
close-to-close return that was not observable when the weights executed at
that bar's open.

Sampling detectors that ship elsewhere admit the problem in their own docs:
*"Signals that are not triggered will not have been verified. This would lead
to a false-negative, i.e. the strategy will be reported as non-biased."* This
one tests every bar by default. If you pass `sample`, the report says so.

## If you do not write Python

```bash
curl -fsSL https://raw.githubusercontent.com/coreyhiggins/proofmark/main/install.sh -o install.sh
less install.sh
sh install.sh
```

Three lines instead of one, deliberately. The installer refuses to run from a
pipe unless you pass `--yes`, because `curl | sh` teaches people to execute
code they have not read, and the next thing they pipe into a shell might not
be this. It uses no `sudo`, touches no system Python, and writes only inside
`~/.local`.

For a VPS or a dedicated server:

```bash
docker run --rm -p 127.0.0.1:8765:8765 proofmark
```

Publishing the port to `127.0.0.1` rather than `0.0.0.0` keeps it off the
public internet. There is a systemd unit in [`deploy/`](deploy/) that does the
same, with the sandboxing flags set. The page has **no authentication**, so if
you need it from another machine, tunnel rather than expose it:

```bash
ssh -N -L 8765:127.0.0.1:8765 you@your-server
```

Or download a build from
[Releases](https://github.com/coreyhiggins/proofmark/releases) and double-click
it. No Python, no terminal.

> **These builds are not code-signed.** Windows SmartScreen will warn you, and
> macOS will refuse to open it until you right-click and choose Open. That is
> what an unsigned binary looks like, not a sign anything is wrong, and you
> should treat every unsigned binary from the internet with exactly that
> suspicion. If you would rather not, use `pip` or the installer above, where
> you can read what you are running.

If you already have Python:

```bash
pip install proofmark
proofmark gui
```

That opens a page in your browser. Paste your account balance over time, say
how many versions you tried, and it tells you in plain language whether the
numbers are safe to believe.

It runs entirely on your machine. Nothing you paste is uploaded, stored or
sent anywhere, because an equity curve is a record of your money.

There is a terminal version too, which exits non-zero when a result is
suppressed so it can gate a pipeline:

```bash
proofmark check results.csv --trials 40 --costs 84.20 --delisted yes
```

It is forgiving about column names. `equity`, `balance`, `nav`, `value`,
`portfolio_value` all work, currency symbols and thousands separators are
stripped, and a single-column file is read as the curve.

## Install

```bash
pip install proofmark
```

The core has **no dependencies**. Guards, metrics and the lookahead detector
run on plain sequences of mappings, so you can point them at whatever engine
you already use rather than migrating to this one.

Exchange and data adapters live behind extras: `proofmark[crypto]`,
`proofmark[equities]`.

## Walk-forward is the primary verb

```python
from proofmark.walkforward import walk_forward, format_walk_forward

result = walk_forward(bars, optimize=my_optimizer, evaluate=my_backtest, windows=5)
print(format_walk_forward(result))
```

Fit on a window, measure on the window after it, never look back. The returned
equity curve is the concatenation of segments the optimiser never saw, so the
number is out-of-sample by construction rather than by your own discipline.
There is deliberately no way to ask this function for in-sample performance. A
number you cannot get is a number you cannot accidentally publish.

Trials sum across windows and feed the guards automatically. Optimising 40
variants in each of 6 windows is a 240-trial search, not a 40-trial one.

**Parameter stability is reported, and it is the part nobody shows:**

```
  parameter stability across windows
    lookback         mean 47.5, range 5 to 90, variation 0.89  UNSTABLE

  lookback changed by more than half its own mean between windows. An
  optimiser that picks a different answer every time it looks is fitting
  noise, and the out-of-sample curve above is closer to luck than to evidence.
```

If the best lookback is 5 bars in one window and 90 in the next, the optimiser
is not finding a parameter. It is finding whatever fit the noise in front of
it. That is visible for free once the windows have run, and it is a more
honest signal than any single ratio.

## Exchanges, and what each one actually gives you

```bash
proofmark venues
```

The differences between venues are large and none of them are in the
marketing, so they are written down:

| Venue | Paper trading | Worth knowing |
|---|---|---|
| **OKX** | Real production data, one header | Best paper story checked. Has a server-side dead-man's switch |
| **Bitget** | Real production data, one header | Same shape as OKX. No dead-man's switch |
| Binance | Synthetic, wiped roughly monthly | Order books not synced to production. Geo-blocks US IPs |
| Kraken | Futures demo only | Only 720 historical candles per symbol via the API |
| Coinbase | **None at all** | Your first live test is real money |
| **Alpaca** | Free, unlimited, no account gate | Free data is IEX only, a fraction of national volume |

OKX and Bitget are the defaults because demo mode there runs on the production
domain against real prices. That is the only arrangement where a paper record
is a record of anything.

### The part that matters more than the venue

A symbol list from a live exchange contains what still trades. Everything that
went to zero is missing, and so is its price history. So any universe built by
asking an exchange what it lists today is **survivors-only by construction**,
and `fetch_ohlcv` marks it that way, which means the guards refuse to print a
headline number on top of it.

There is no flag that fixes this. It is a property of where the data came
from, and the only real fix is a dataset that includes assets which stopped
existing.

## On the AI part

There is an evidence base on putting a language model in the trading loop, and
it says not to.

A KDD 2026 paper re-ran the two leading academic LLM trading agents over 20
years with real fees and found neither generates statistically significant
alpha, all p-values above 0.34. The only forward-only publicly logged LLM
trading experiment lost half its capital. A review of 77 studies found 1 of 19
qualifying papers models transaction costs and 0 of 19 reach the top
reproducibility tier. The most-cited paper claiming a language model beats
analysts was withdrawn by its own authors.

The two largest LLM trading repositories on GitHub have more than 158,000
stars between them. One now says in its README that it should be treated as a
research scaffold and "not as a strategy with a fixed, replicable return". The
other says plainly: "the system does not actually make any trades".

There is also a structural problem with testing them at all. A frontier model
recalls exact historical index closes to under 1% error for dates inside its
training window, and both masking identifiers and instructing it to respect
historical boundaries fail. A language model backtest over a period the model
has seen is not a backtest.

So in proofmark a model may read filings and summarise what happened. It never
decides a trade, and the rules that do are deterministic and testable.

## What this does not do

- It does not tell you what to buy, and it is not investment advice.
- It does not claim any strategy is profitable. It has no strategies.
- It will not make a bad strategy good. It will make a bad strategy legible.
- Passing every guard is not evidence a strategy works. It only means the
  obvious ways of fooling yourself have been ruled out.

## Status

Early. The core is the guards, the metrics and the lookahead detector, which
are the parts with a real gap. Execution adapters, walk-forward and the
research layer come next.

## License

MIT
