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

## Install on Windows

```powershell
irm https://raw.githubusercontent.com/coreyhiggins/proofmark/main/install.ps1 -OutFile install.ps1
notepad install.ps1
powershell -ExecutionPolicy Bypass -File install.ps1
```

Three lines rather than one, deliberately. Piping a script straight into a
shell teaches people to run code they have not read, and the next thing they
pipe might not be this.

It needs **no administrator rights**, installs into your own user folder, adds
itself to **your** PATH rather than the machine's, and puts a shortcut in the
Start Menu. Uninstalling is one command, printed at the end.

Then open it from the Start Menu, or:

```powershell
proofmark app        # its own window, no browser
proofmark gui        # serve the page for your own browser instead
proofmark update     # check for and install a newer version
```

All of it is free. No account, no service, no paid tier. Updates come from the
public GitHub releases API and only when you ask, because a tool that phones
home on startup has decided for you what your machine talks to.

<details>
<summary><strong>The Windows warning you will see, and why</strong></summary>

The first time you run it, Windows says **"Windows protected your PC"**. Click
**More info**, then **Run anyway**.

That appears because the file is not code-signed. A certificate costs a few
hundred dollars a year and needs a registered identity, and we have not spent
it. It is also **exactly** the warning you should heed for a file you were not
expecting, so the honest answer is that this is what unsigned looks like and
you should decide accordingly.

If you would rather not, install with `pip` below and read the source you are
running.

</details>

## macOS and Linux

```bash
curl -fsSL https://raw.githubusercontent.com/coreyhiggins/proofmark/main/install.sh -o install.sh
less install.sh
sh install.sh
```

macOS refuses to open an unsigned binary until you right-click and choose Open.

## On a server

```bash
docker run --rm -p 127.0.0.1:8765:8765 proofmark
```

Publishing to `127.0.0.1` keeps it off the public internet. There is a systemd
unit in [`deploy/`](deploy/) with the sandboxing flags set. The page has **no
authentication**, so reach it over a tunnel rather than exposing it:

```bash
ssh -N -L 8765:127.0.0.1:8765 you@your-server
```

## Install as a library

```bash
pip install "proofmark @ git+https://github.com/coreyhiggins/proofmark"
```

The core has **no dependencies**. Guards, metrics and the lookahead detector
run on plain sequences of mappings, so you can point them at whatever engine
you already use rather than migrating to this one.

Exchange and data adapters live behind extras: `proofmark[crypto]`,
`proofmark[equities]`.

## Run it live, on paper

```bash
proofmark run --symbol BTC/USDT --timeframe 1h --strategy ema-cross
```

Real prices, imaginary money. proofmark never holds a key that could place an
order, and there is no flag that changes that.

```
  paper trading BTC/USDT 1h on okx
  strategy      ema-cross
  costs         0.100% fee and 0.050% slippage, per side

  12:32:30  account 9,654.34  return -3.46%  holding -4.02%  difference +0.56%
```

The same run is available in the app under **Watch a live run**, where you can
start it from a form instead of a terminal. It draws the price with the entries
and exits marked, the account against buying once and holding, and the drawdown,
and it runs the guards over the live curve as it goes.

Three rules decide whether this is honest, and all three are in the engine
rather than in your discipline:

- **Decisions are made on a closed bar and filled at the next bar's open**, so
  nothing can trade at a price it has already seen. This is the same convention
  `check_lookahead` property-tests, and the built-in strategies are tested
  against it.
- **The still-forming candle is dropped on every poll.** An exchange returns the
  current bar with a close that is just the last trade. Reading it is the most
  common reason a live bot beats its backtest and then bleeds in production.
- **Fees and slippage come off both sides of every fill.** A costless paper run
  is a fantasy generator, and the guards would call it disqualifying anyway.

Buy and hold is tracked from the first bar whether or not you ask, because the
runs where nobody asks are the runs where it matters.

### Rules you can run without writing any Python

```bash
proofmark run --list-strategies
```

| name | what it does |
| --- | --- |
| `ema-cross` | Buys when a 9 bar average crosses above a 21 bar average, sells on the way back. |
| `rsi-dip` | Buys when RSI drops under 30, sells once it recovers past 55. |
| `breakout` | Buys a 20 bar high, sells a 20 bar low. |
| `buy-and-hold` | Buys once on the first bar and never trades again. The thing to beat. |

None of these is a recommendation and none is expected to make money. They are
the textbook rules everyone tries first, included so the tool can show you what
they actually do. Buy and hold is a runnable strategy rather than only a dashed
line, so the benchmark runs under identical fees and the same fill rule and
there is nothing left to argue about.

Market data needs `pip install 'proofmark[crypto]'`. The Windows installer
bundles it.

## A system is a file, and nothing runs until it has been checked

A system is every market, rule, size and limit written down together. Two ship,
and both work with no account and no API key.

```bash
proofmark app                    # pick a system, check it, run it
proofmark serve crypto-three     # no window, for leaving on
proofmark autostart crypto-three # start it when you log in
```

**Nothing runs until it has passed a check.** A system carries a fingerprint
over every value that changes what it decides. Running it over history records
a verdict against that fingerprint, and going live needs a passing verdict with
a matching one. Verify a system, widen the stop, and the fingerprint changes,
so the verification stops applying and the gate closes again.

The check is not one pass over all of history, because that is the number a
system was chosen to produce. It also runs the system separately on each slice
and reports every one:

```
  window by window
    1    +2.0% against   -0.8% holding, 3 trades
    2    +0.4% against   +2.8% holding, 0 trades
    3    +1.2% against   -0.1% holding, 2 trades
    4    +0.1% against   -1.8% holding, 9 trades

  beat holding in 3 of 4 windows, made money in 4.
```

It reports rather than judges. Two winning windows out of four is not a verdict,
and inventing a threshold to make it one would be the arbitrary-number habit
this project exists to complain about.

### The risk layer

- **Position sizing** by risk per trade, off a stop distance taken from
  volatility. A quiet market gives a tight stop, so the same 1% buys a larger
  position. The capital deployed moves; the amount at risk does not. Fixed
  fraction and fixed notional are there too, with a hard cap above all three.
- **Daily loss, maximum drawdown and losing streak** limits, each evaluated from
  the bar the halt was last cleared at rather than the start of the run.
- **Exposure caps** by declared correlation group, so two index positions block
  a third risk-on trade. Declared and not estimated: rolling correlations
  converge on one in the crash where the rule matters most.
- **A kill switch that is a file.** It survives a restart, it works with the app
  closed, and anything on the machine can pull it.
- **Halted means no new entries, and exits always run.** A halt that blocks
  everything traps you in the position that caused it.

### The log and the alerts

An append-only JSONL file, one object per line, never rewritten. The live loop
replays the whole history every poll, so every event carries a stable identity
and the journal reads back what is on disk at startup. Two identical cycles
leave the log the same length.

Alerts go to a Discord webhook and a desktop notification, both optional and
neither fatal. A webhook that times out must not stop a trading loop.

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
- It does not claim any strategy is profitable. The built-in rules exist so
  you can watch what they do, and most of them lose to buying and holding.
- It will not make a bad strategy good. It will make a bad strategy legible.
- Passing every guard is not evidence a strategy works. It only means the
  obvious ways of fooling yourself have been ruled out.

## Status

Usable. The guards, the metrics, the lookahead detector, the multi-market
paper engine, the risk layer, the verification gate, the log and the alerts are
all in and tested.

Live execution against a real account is not, and will not be until the paper
path has been boring for a long time. Nothing here holds a key that can place
an order, and there is no setting that changes that.

## License

MIT
