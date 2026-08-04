"""Equity and commodity bars with no account, no key and no dependency.

The reference design trades index and commodity exposure alongside crypto, and
every route to that data was gated. Alpaca needs API keys even to read a price,
and its free tier serves IEX only, which is a small fraction of what actually
traded. Stooq now sits behind a JavaScript proof-of-work check. Everything else
wants an email address at minimum.

So this uses the public chart endpoint that most open-source finance tooling
already runs on. It needs nothing installed and nothing signed up for, which
matters more than it sounds: a tool whose flagship system cannot fetch a single
bar until the user creates a brokerage account is a tool nobody evaluates.

WHAT IS HONESTLY WRONG WITH THIS.

- **It is not a documented API.** It can change shape or start refusing without
  notice, and when it does, this file breaks. That is the price of free.
- **Adjustments.** These are split-adjusted but the endpoint's dividend handling
  is not something to take on faith. For a dividend-paying ETF held for months,
  a total-return figure computed from these bars understates reality.
- **It is not a data licence.** Fine for a person checking their own ideas.
  Anyone building something commercial on it needs a real provider, and this
  docstring is where they should find that out.

None of that makes it useless. It makes it a starting point that should be
replaced before anyone trusts a number from it with real money, which is a
sentence that belongs on far more free data than carries it.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from .data import Universe

ENDPOINT = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

# Intervals the endpoint serves, mapped from the names used everywhere else in
# this project. There is no four hour bar, which is why the shipped equities
# system runs daily rather than on the reference design's 4h commodities.
INTERVALS = {
    "5m": ("5m", "60d"), "15m": ("15m", "60d"), "30m": ("30m", "60d"),
    "1h": ("1h", "730d"), "1d": ("1d", "5y"), "1wk": ("1wk", "10y"),
}

TIMEOUT = 30


def supported(timeframe: str) -> bool:
    return timeframe in INTERVALS


def fetch(symbol: str, *, timeframe: str = "1d", limit: int = 1000) -> Universe:
    """Bars for one symbol. Raises ValueError with something a person can act on."""
    if timeframe not in INTERVALS:
        raise ValueError(
            f"{timeframe} is not available without a paid data feed. "
            f"Free intervals are {', '.join(sorted(INTERVALS))}."
        )
    interval, span = INTERVALS[timeframe]
    url = f"{ENDPOINT.format(symbol=symbol)}?range={span}&interval={interval}"

    request = urllib.request.Request(url, headers={
        # Identifies the tool rather than pretending to be a browser. If the
        # endpoint ever decides to refuse this, that is a decision to respect
        # rather than something to work around.
        "User-Agent": "Mozilla/5.0 (compatible; proofmark/0.2; +https://github.com/coreyhiggins/proofmark)",
    })

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as err:
        raise ValueError(
            f"the price feed refused the request for {symbol} ({err.code}). "
            "This is a free public endpoint and it is allowed to say no."
        ) from None
    except (urllib.error.URLError, TimeoutError, ValueError) as err:
        raise ValueError(f"could not reach the price feed for {symbol}: {err}") from None

    bars = _to_bars(payload, symbol)
    if not bars:
        raise ValueError(
            f"no bars came back for {symbol}. Check the ticker: this feed wants "
            "BTC-USD rather than BTC/USD, and plain tickers like SPY for stocks."
        )

    return Universe(
        bars=bars[-limit:],
        symbol=symbol,
        venue_id="public",
        timeframe=timeframe,
        source="public chart endpoint, no key",
        # The same truth as any live listing: what is quoted today is what
        # survived. Stated here so it reaches the guards rather than being
        # something a reader is expected to remember.
        delisted_included=False,
        notes=[
            "Undocumented public endpoint. It can change or refuse without "
            "notice, and it is not a data licence. Replace it with a real "
            "provider before trusting a number from it with money.",
        ],
    )


def _to_bars(payload: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
    """Pull OHLCV out, dropping any bar with a hole in it.

    The endpoint returns nulls for bars it has no data for, typically halts and
    the odd gap. Carrying a null through would produce a NaN somewhere much
    later and much harder to trace, and interpolating one would invent a price
    that never traded.
    """
    try:
        result = payload["chart"]["result"][0]
        stamps = result["timestamp"]
        quote = result["indicators"]["quote"][0]
    except (KeyError, IndexError, TypeError):
        return []

    bars: list[dict[str, Any]] = []
    for i, stamp in enumerate(stamps):
        row = [quote[k][i] for k in ("open", "high", "low", "close")]
        if any(v is None for v in row):
            continue
        volume = quote.get("volume", [None] * len(stamps))[i]
        bars.append({
            "timestamp": int(stamp) * 1000,
            "open": float(row[0]), "high": float(row[1]),
            "low": float(row[2]), "close": float(row[3]),
            "volume": float(volume or 0.0),
        })
    return bars
