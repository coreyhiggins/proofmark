"""Fetching price history, and being honest about what you got.

The fetch itself is thin. The part worth having is :class:`Universe`, which
records where the data came from and whether it can support the claim you are
about to make with it.

A symbol list from a live exchange contains what still trades. Everything that
went to zero is absent, and so is its price history. That is not a caveat to
mention in a footnote, it is the difference between a 62% annualised return
and nothing, so it travels with the data and reaches the guards automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from .venues import Venue, venue as get_venue

Bar = dict[str, Any]


@dataclass
class Universe:
    """Price data plus the truth about where it came from."""

    bars: list[Bar]
    symbol: str
    venue_id: str
    timeframe: str
    source: str
    delisted_included: bool | None = None
    notes: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.bars)

    def __iter__(self):
        return iter(self.bars)

    def summary(self) -> str:
        lines = [
            f"{self.symbol} on {self.venue_id}, {self.timeframe}, "
            f"{len(self.bars)} bars from {self.source}",
        ]
        if self.delisted_included is False:
            lines.append(
                "  SURVIVORS ONLY. This came from a live listing, so assets that "
                "stopped trading are absent from the universe and from the price "
                "history. Any cross-sectional result built on it is inflated by "
                "an amount that is large rather than marginal."
            )
        lines.extend(f"  {note}" for note in self.notes)
        return "\n".join(lines)


def _require_ccxt():
    try:
        import ccxt  # noqa: PLC0415
    except ImportError:
        raise ImportError(
            "Fetching live data needs ccxt, which is not installed.\n"
            "  pip install 'proofmark[crypto]'\n"
            "The core guards, metrics and lookahead test have no dependencies "
            "and do not need this."
        ) from None
    return ccxt


def _client(v: Venue, demo: bool, credentials: dict[str, str] | None):
    ccxt = _require_ccxt()
    if not hasattr(ccxt, v.id):
        raise ValueError(f"ccxt has no exchange named {v.id!r}")

    config: dict[str, Any] = {"enableRateLimit": True}
    config.update(credentials or {})

    if demo:
        cfg = dict(v.demo_config)
        # OKX and Bitget flag demo mode with a header on the production host,
        # which is why their paper data is real. Binance swaps to a separate
        # testnet host, which is why its paper data is not.
        if "headers" in cfg:
            config.setdefault("headers", {}).update(cfg.pop("headers"))
        config.update(cfg)

    client = getattr(ccxt, v.id)(config)
    if demo and getattr(client, "urls", {}).get("test") and v.demo_config.get("sandbox"):
        client.set_sandbox_mode(True)
    return client


def fetch_ohlcv(
    venue_id: str,
    symbol: str,
    *,
    timeframe: str = "1h",
    limit: int = 1000,
    since: int | None = None,
    demo: bool = True,
    credentials: dict[str, str] | None = None,
) -> Universe:
    """Fetch candles for one symbol.

    ``demo=True`` is the default and, on OKX and Bitget, costs you nothing in
    data quality because their demo mode reads production prices.

    The returned universe is marked ``delisted_included=False``, because a live
    exchange only serves symbols it currently lists. To make a cross-sectional
    claim you need a dataset containing assets that no longer exist, and no
    exchange API will give you one.
    """
    v = get_venue(venue_id)
    client = _client(v, demo, credentials)

    raw = client.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=limit)
    bars: list[Bar] = [
        {
            "timestamp": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        }
        for row in raw
    ]

    notes: list[str] = []
    if demo and not v.paper_is_honest:
        notes.append(
            f"Demo mode on {v.name} is {v.sandbox}: {v.sandbox_note}"
        )
    if v.caution:
        notes.append(f"Caution: {v.caution}")
    if not v.dead_mans_switch:
        notes.append(
            "No server-side dead-man's switch here. If your process dies holding "
            "a position, nothing on the exchange closes it for you."
        )

    return Universe(
        bars=bars,
        symbol=symbol,
        venue_id=v.id,
        timeframe=timeframe,
        source=f"{v.name} {'demo' if demo else 'live'}",
        delisted_included=False,
        notes=notes,
    )


def from_bars(
    bars: Sequence[Bar],
    *,
    symbol: str = "unknown",
    source: str = "local file",
    delisted_included: bool | None = None,
) -> Universe:
    """Wrap data you already have.

    ``delisted_included`` stays ``None`` unless you say otherwise, and the
    guards report unknown rather than assuming the flattering answer. Pass
    ``True`` only if the dataset genuinely contains assets that stopped
    trading, which is rarer than people expect.
    """
    return Universe(
        bars=list(bars),
        symbol=symbol,
        venue_id="local",
        timeframe="unknown",
        source=source,
        delisted_included=delisted_included,
    )
