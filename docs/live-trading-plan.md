# Plan: from paper engine to a system you would trust with money

Written against a nine-item requirement list from a real prospective user. It is
a professional trading-system checklist, and the most informative thing about it
is what it does not contain: **no AI anywhere**. The person who has to run this
is asking for disciplined execution and hard limits, not prediction.

## Where things actually stand

| # | Asked for | Status | Notes |
|---|---|---|---|
| 1 | One clearly defined strategy | **Partial** | Four built-in rule sets exist and are lookahead-tested. None of them is *his* strategy, and nobody has written his down. |
| 2 | Historical backtester | **Partial** | `replay()`, `walk_forward()` and the guards are the engine and they work. There is no user-facing flow: the check page takes numbers you paste, not a strategy and a date range. |
| 3 | Real-time data feed | **Have** | ccxt REST poll of closed candles, once a minute. Correct for bar-based rules and honest about the forming bar. It is not a websocket tick feed, and it should not be one for this kind of strategy. |
| 4 | Daily-loss and drawdown limits | **Missing** | `State.halted` is a field the live page renders and nothing anywhere sets. The protocol is there, the enforcement is not. |
| 5 | Position sizing | **Missing** | `Paper.buy` spends 100% of cash on every entry. That is not a sizing policy, it is the absence of one. |
| 6 | Broker order manager | **Missing** | Deliberately. No key that can place an order touches this code today. |
| 7 | Duplicate-order protection | **Missing** | Only has meaning once 6 exists. |
| 8 | Kill switch | **Partial** | The Stop button ends the polling loop. It does not flatten an open position, does not persist, and does not survive a restart. A kill switch that forgets it was pulled is not one. |
| 9 | Complete logs and alerts | **Partial** | The last 40 decisions live in a JSON file that gets rewritten every cycle. There is no append-only history and no alert of any kind. |

Two solid, three partial, four absent.

## The ordering argument

The four missing items are not equally valuable, and the order they get built in
matters more than the list suggests.

**Items 4, 5, 8 and 9 are what stop a bot from destroying an account. Item 6 is
what lets it destroy one faster.** A system with an order manager and no
position sizing is strictly more dangerous than no system at all, because it
executes a mistake at machine speed and with total conviction.

So the build order is not the list order. It is:

1. **Position sizing** (5), because every other risk control is expressed in
   terms of it.
2. **Loss and drawdown limits** (4), which need sizing to be meaningful and need
   `halted` to actually get set.
3. **Kill switch** (8), which is the manual version of 4 and shares its machinery.
4. **Durable logs and alerts** (9), because you cannot diagnose 1 to 3 without them.
5. **Backtester flow** (2), which is mostly surfacing an engine that already exists.
6. **Broker order manager** (6) and **duplicate protection** (7), last, and only
   after the above have been boring for a while.

Everything in steps 1 to 5 improves the paper engine too, so none of it is
speculative work waiting on a decision about real money.

## What each piece actually means

### 5. Position sizing

Not one policy. At least:

- **Fixed fraction**: risk a set percentage of equity per position.
- **Risk-based**: size so that hitting the stop costs exactly X% of the account.
  This is the one that makes stops and sizing a single decision instead of two,
  and it is what most people mean when they say the words.
- **Fixed notional**: a flat dollar amount, which is what people actually use
  while they are still learning.

The sizing policy has to be applied identically in backtest and live, or the
backtest is measuring a different system than the one running.

### 4. Daily-loss and drawdown limits

Three separate limits that get conflated:

- **Daily loss**: realised plus unrealised loss since the session boundary.
  Needs an explicit timezone, or "today" is ambiguous and the limit resets at
  the wrong moment.
- **Maximum drawdown**: distance below the equity high water mark, across the
  whole run, not the day.
- **Consecutive losses**: often the earliest signal that the market regime
  changed under the strategy.

Each sets `halted` with a reason, and halted has to mean *no new entries* while
still allowing exits, or the limit traps you in the position that triggered it.

### 8. Kill switch

Must do three things the current Stop button does not:

- Flatten open positions, not just stop deciding.
- Persist, so a restart does not quietly resume trading.
- Be reachable when the app is not open. A kill switch you can only press from
  a window you have closed is decorative.

### 9. Logs and alerts

- **Append-only log file**, one line per decision, order, fill, rejection and
  limit breach, with the inputs that produced it. The current rolling 40-entry
  state file is a display buffer, not a record.
- **Alerts** on: halted, limit breached, order rejected, position opened or
  closed, and the feed going silent. Delivery via Discord webhook is the
  cheapest thing that works and needs no account.

### 6 and 7. The broker

This is the item that changes what this project is, and it carries the problems
the other eight do not:

- **Reconciliation.** The engine currently recomputes the whole run from scratch
  on every poll, which is what makes it immune to state-drift bugs. Against a
  real broker that stops being safe: the broker holds the truth about positions
  and the engine has to reconcile with it rather than assume.
- **Partial fills**, rejections, and orders that sit unfilled.
- **Idempotency** is item 7. Client-assigned order IDs, so a retry after a
  timeout cannot open a second position.
- **Restart safety.** On restart the engine must ask the broker what it holds
  before it decides anything.

## Things not on the list that will bite

- **The Pattern Day Trader rule.** US equities, margin account, under $25,000:
  more than three day trades in five business days gets the account restricted
  for 90 days. A bot can trip this in one session without noticing. If he is
  trading US equities under that threshold, a day-trade counter is not optional.
- **Market hours, halts and gaps.** Crypto runs continuously; equities do not.
  Sessions, early closes, and overnight gaps that jump straight through a stop.
- **Whole versus fractional shares**, which changes sizing arithmetic.
- **Downtime backfill.** After a crash or a laptop lid closing, the engine has
  to catch up on bars it missed without acting on all of them at once.
- **Nothing runs when the app is closed.** Today the run lives in a thread inside
  the window's process. A system with daily loss limits implies something that
  runs unattended, which means a headless mode and a service.
- **A paper-to-live gate.** Refusing to enable live trading until a strategy has
  run on paper for a set period, and passed the guards, would be the single most
  proofmark-shaped feature on this whole page. It is also the one a person will
  thank you for in a year.

## The decision that has to come first

proofmark's own documentation says it is the verification layer and not the
trading engine, and that boundary is why it never holds a key that can place an
order. Item 6 crosses it.

Three ways to go:

- **A. Extend proofmark.** One product, one install. Simplest for the user, and
  it weakens the positioning: the tool that tells you when you are fooling
  yourself is now also the thing doing the trading.
- **B. Separate bot, depends on proofmark.** Keeps the honesty layer clean and
  lets the guards audit the bot from outside. Two installs, more setup, and the
  user has to understand why there are two things.
- **C. One product, execution behind an explicit gate.** Ships with live
  execution off. Requires trade-only keys, a completed paper period, and passing
  guards before it will place a single order.

C is the recommendation. It keeps one product, keeps the honesty argument
intact, and makes the gate itself a feature rather than a disclaimer.

## Decisions taken

- **Both markets.** Crypto works today; equities brings sessions, halts, whole
  versus fractional shares, and the day-trade counter. Equities-specific work is
  deferred until it is known whether real orders are in scope, because most of
  it only matters at the broker.
- **Option C.** One product. Live execution ships disabled and stays disabled
  until trade-only keys, a completed paper period and a passing verdict are all
  present.
- **Safety rails first**, which are market-neutral and improve the paper engine
  regardless of what comes back about real money.

## Wave one: the safety rails

Everything here is deterministic, testable without a network, and applies
identically in backtest and live. That last property is the requirement: a
sizing or limit rule that exists in only one of the two makes the backtest a
measurement of a different system.

### Sizing

New `sizing.py`. One policy object, three modes:

- `fraction`: a set percentage of current equity per position. The default,
  because it needs nothing else to work.
- `risk`: size so that being stopped out costs exactly X% of equity. Requires a
  stop distance, so it arrives with a configured stop percentage rather than
  waiting for strategies to start returning stops.
- `notional`: a flat cash amount, which is what people actually use early on.

`Paper.buy` currently takes no size and spends everything. It gains an explicit
amount, and the all-in path stops existing. A hard `max_position_fraction` cap
sits above all three modes so a misconfigured policy cannot go all-in by
accident.

### Limits

New `limits.py`. Three independent rules, each producing a halt with a reason:

- **Daily loss**, realised plus unrealised, measured from an explicit session
  boundary. The timezone is configuration, not an assumption: UTC for crypto,
  US Eastern for equities, and it is written into the log so a breach can be
  argued about afterwards.
- **Maximum drawdown**, from the equity high water mark across the whole run.
- **Consecutive losses**, which is usually the first sign the regime moved.

**Halted means no new entries, and exits still allowed.** A halt that blocks
everything traps you in the position that caused it.

### The interaction that will cause a bug if it is not handled

`replay()` recomputes the entire run from scratch on every poll, which is what
makes it immune to state drift. That is a good property and it collides with
halting: a limit breached yesterday gets recomputed and re-breached forever,
so clearing a halt would do nothing.

So a halt is not derived state. It is a **fact on disk** with a cleared-at
timestamp, and limit evaluation only considers activity after that timestamp.

### Kill switch

A file, not a button. `~/.proofmark/halt` existing means halted, which gives
three things the current Stop button lacks: it survives a restart, it can be
pulled without the app open, and it can be pulled by anything else on the
machine. The Stop button writes the file. Clearing it is deliberate and
separate. Flattening open positions on halt is on by default.

### Logs

Append-only JSONL, one file per run, never rewritten. One line per decision,
fill, rejection, halt and limit breach, each carrying the inputs that produced
it. The existing rolling forty-entry state file stays exactly what it is, a
display buffer.

### Alerts

Discord webhook first: no account, no keys, and it reaches a phone. Events
worth interrupting someone for are halted, limit breached, entry, exit, and the
feed going quiet. Everything else goes to the log.
