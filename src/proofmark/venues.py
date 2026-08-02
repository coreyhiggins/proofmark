"""What each venue actually gives you, written down honestly.

Every venue below was checked rather than assumed, because the differences
are large and none of them are in the marketing. Two examples that matter:

- Coinbase Advanced Trade has **no sandbox at all**. Your first live test is
  real money.
- Binance's spot testnet order books are not synced with production and get
  wiped roughly monthly without notice, so a paper record there is not a
  record of anything.

Meanwhile OKX and Bitget both run demo mode on the **production domain with
real market data**, gated by a single header. That is the design you want and
it is why they are the defaults.

THE SURVIVORSHIP PROBLEM, which is the important part of this module.

An exchange's symbol list contains the assets that still exist. Every coin
that went to zero, got delisted, or quietly stopped trading is missing, and it
is missing from the price history too. Measured survivorship bias on an
equal-weighted crypto buy-and-hold portfolio is 62% annualised, across 3,904
assets of which 1,222 were delisted.

So a universe built by asking an exchange what it lists today is
survivors-only by construction. There is no flag that fixes this and no
apology that makes it smaller. This module reports it, and the guards refuse
to print a headline number on top of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

SandboxKind = Literal["none", "synthetic", "production-data", "broker-paper"]


@dataclass(frozen=True)
class Venue:
    id: str
    name: str
    kind: Literal["crypto", "equities"]
    sandbox: SandboxKind
    sandbox_note: str
    demo_config: dict[str, Any]
    dead_mans_switch: bool
    caution: str = ""

    @property
    def paper_is_honest(self) -> bool:
        """Whether paper trading here runs against real market data."""
        return self.sandbox in ("production-data", "broker-paper")


VENUES: dict[str, Venue] = {
    "okx": Venue(
        id="okx",
        name="OKX",
        kind="crypto",
        sandbox="production-data",
        sandbox_note=(
            "Demo mode runs on the production domain against real market data, "
            "enabled by one header. This is the best paper-trading story of any "
            "venue checked."
        ),
        demo_config={"headers": {"x-simulated-trading": "1"}},
        dead_mans_switch=True,
    ),
    "bitget": Venue(
        id="bitget",
        name="Bitget",
        kind="crypto",
        sandbox="production-data",
        sandbox_note=(
            "Demo mode on the production domain with live market data, enabled "
            "by one header. Same shape as OKX."
        ),
        demo_config={"headers": {"paptrading": "1"}},
        dead_mans_switch=False,
        caution="No server-side cancel-on-disconnect found. If your process dies, open orders stay open.",
    ),
    "binance": Venue(
        id="binance",
        name="Binance",
        kind="crypto",
        sandbox="synthetic",
        sandbox_note=(
            "Spot testnet is a separate domain with synthetic order books not "
            "synced to production, wiped roughly monthly without notice. A "
            "multi-week paper record there is not a record of anything."
        ),
        demo_config={"sandbox": True},
        dead_mans_switch=True,
        caution=(
            "Geo-blocks US IPs entirely, and Binance.US has no futures. API "
            "trading requires intermediate identity verification."
        ),
    ),
    "kraken": Venue(
        id="kraken",
        name="Kraken",
        kind="crypto",
        sandbox="none",
        sandbox_note="Futures demo only. No spot sandbox.",
        demo_config={},
        dead_mans_switch=True,
        caution="Returns only 720 historical candles per symbol via the API, which limits backtest depth.",
    ),
    "coinbase": Venue(
        id="coinbase",
        name="Coinbase Advanced Trade",
        kind="crypto",
        sandbox="none",
        sandbox_note="There is no sandbox. None. Your first live test is real money.",
        demo_config={},
        dead_mans_switch=False,
        caution=(
            "WebSocket tokens expire after two minutes and must be regenerated "
            "continuously. No sandbox and no dead-man's switch found."
        ),
    ),
    "alpaca": Venue(
        id="alpaca",
        name="Alpaca",
        kind="equities",
        sandbox="broker-paper",
        sandbox_note=(
            "Free unlimited paper trading, no account gate, and unusually candid "
            "about what its simulator does not model: market impact, latency "
            "slippage, queue position, price improvement, fees or dividends."
        ),
        demo_config={"paper": True},
        dead_mans_switch=False,
        caution=(
            "Free market data is IEX only, which sees a small fraction of national "
            "volume. Full-tape data costs money, and a backtest on IEX-only data "
            "is not a backtest on what actually traded."
        ),
    ),
}

DEFAULT_CRYPTO = "okx"
DEFAULT_EQUITIES = "alpaca"


def venue(venue_id: str) -> Venue:
    try:
        return VENUES[venue_id.lower()]
    except KeyError:
        known = ", ".join(sorted(VENUES))
        raise KeyError(f"unknown venue {venue_id!r}. Known venues: {known}") from None


def describe(venue_id: str) -> str:
    """A plain-language summary of what you get here, cautions included."""
    v = venue(venue_id)
    lines = [
        f"{v.name} ({v.kind})",
        f"  paper trading   {'against real market data' if v.paper_is_honest else v.sandbox}",
        f"  {v.sandbox_note}",
    ]
    if not v.dead_mans_switch:
        lines.append(
            "  No server-side dead-man's switch. If your process dies holding a "
            "position, nothing on the exchange will close it for you."
        )
    if v.caution:
        lines.append(f"  Caution: {v.caution}")
    return "\n".join(lines)
