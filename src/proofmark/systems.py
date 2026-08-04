"""A system is a file, not a form.

Five boxes in a dialog is a setting. A named, saved, readable definition of
every market, rule, size and limit is a system: you can diff it, send it to
someone, keep two of them and compare, and know exactly what produced a result
six months later.

THE VERIFICATION GATE, WHICH IS THE POINT OF THIS FILE.

The reference design this was built against has no way to know whether it
works. It has markets, rules and risk controls, and nothing anywhere that could
tell its owner the whole thing is fitted to noise.

So a system carries a **fingerprint**: a hash of every value that changes its
behaviour. Running it over history records a verdict against that fingerprint.
Going live checks for a passing verdict with a **matching** fingerprint.

The matching part is the whole mechanism. Verify a system, widen the stop, and
the fingerprint changes, so the verification no longer applies and the gate
closes again. Without that you get the usual outcome: something was verified
once, months ago, and nobody can say what it was.

WHAT IS DELIBERATELY NOT IN THE FINGERPRINT.

Starting cash and the alert webhook. Neither changes what the system decides,
and including them would force a re-verification every time someone changed the
size of their paper account, which teaches people to treat the gate as a
nuisance to click past.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Sequence

from .engine import Market
from .limits import DEFAULT_GROUPS, Limits
from .sizing import Sizing


@dataclass
class System:
    name: str
    description: str = ""
    markets: list[Market] = field(default_factory=list)
    sizing: Sizing = field(default_factory=Sizing)
    limits: Limits = field(default_factory=Limits)

    # Not part of the fingerprint. See the module docstring.
    starting_cash: float = 10_000.0
    venue: str = "okx"

    @property
    def symbols(self) -> list[str]:
        return [m.symbol for m in self.markets]

    @property
    def fingerprint(self) -> str:
        """A hash of everything that changes what this system decides.

        Sorted keys and a fixed float format, so the same system always hashes
        the same way regardless of dict ordering or how a number was typed.
        """
        payload = {
            "markets": sorted(
                [m.symbol, m.strategy, m.timeframe, m.whole_units] for m in self.markets
            ),
            "sizing": {k: _round(v) for k, v in sorted(asdict(self.sizing).items())},
            "limits": {
                k: (_round(v) if not isinstance(v, dict) else dict(sorted(v.items())))
                for k, v in sorted(asdict(self.limits).items())
            },
            "venue": self.venue,
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "venue": self.venue,
            "starting_cash": self.starting_cash,
            "markets": [asdict(m) for m in self.markets],
            "sizing": asdict(self.sizing),
            "limits": {k: v for k, v in asdict(self.limits).items()},
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "System":
        limits_raw = dict(raw.get("limits") or {})
        limits_raw.setdefault("groups", dict(DEFAULT_GROUPS))
        return cls(
            name=str(raw.get("name", "unnamed")),
            description=str(raw.get("description", "")),
            venue=str(raw.get("venue", "okx")),
            starting_cash=float(raw.get("starting_cash", 10_000.0)),
            markets=[Market(**m) for m in raw.get("markets") or []],
            sizing=Sizing(**(raw.get("sizing") or {})),
            limits=Limits(**limits_raw),
        )


def _round(value: Any) -> Any:
    return round(value, 10) if isinstance(value, float) else value


# --------------------------------------------------------------- verdicts --

@dataclass
class Verification:
    """What happened when a system was run over history."""

    fingerprint: str
    at: float
    passed: bool
    summary: str
    findings: list[str] = field(default_factory=list)
    total_return: float = 0.0
    benchmark_return: float = 0.0
    trades: int = 0
    bars: int = 0

    @property
    def beat_holding(self) -> bool:
        return self.total_return > self.benchmark_return


class Store:
    """Systems and their verifications, on disk under one directory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    # -- systems

    def path_for(self, name: str) -> Path:
        return self.root / "systems" / f"{_slug(name)}.json"

    def save(self, system: System) -> Path:
        path = self.path_for(system.name)
        _write_json(path, system.to_dict())
        return path

    def load(self, name: str) -> System | None:
        try:
            raw = json.loads(self.path_for(name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        try:
            return System.from_dict(raw)
        except (TypeError, ValueError):
            return None

    def all(self) -> list[System]:
        """Every saved system, with the built-ins filling in any that are absent.

        Built-ins are not written to disk until something changes them, so a
        fresh install has working systems without a setup step and an edited
        one is never silently reverted by an upgrade.
        """
        found: dict[str, System] = {}
        for system in builtin_systems():
            found[system.name] = system
        directory = self.root / "systems"
        if directory.is_dir():
            for path in sorted(directory.glob("*.json")):
                try:
                    system = System.from_dict(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, ValueError, TypeError):
                    continue
                found[system.name] = system
        return list(found.values())

    # -- verifications

    def _verdict_path(self, name: str) -> Path:
        return self.root / "verified" / f"{_slug(name)}.json"

    def record(self, system: System, verification: Verification) -> None:
        _write_json(self._verdict_path(system.name), asdict(verification))

    def verification(self, system: System) -> Verification | None:
        """The recorded verdict, but only if it describes THIS system.

        A fingerprint mismatch returns None rather than a stale pass. Widening
        a stop after verifying produces a different system, and reporting the
        old verdict for it is the exact failure this gate exists to prevent.
        """
        try:
            raw = json.loads(self._verdict_path(system.name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if raw.get("fingerprint") != system.fingerprint:
            return None
        try:
            return Verification(**raw)
        except TypeError:
            return None

    def may_run(self, system: System) -> tuple[bool, str]:
        """Whether this system is cleared to run live, and why not if it is not."""
        verification = self.verification(system)
        if verification is None:
            return False, (
                "This system has not been run over history yet, or it has been "
                "edited since it was. Run the check first."
            )
        if not verification.passed:
            return False, f"The last run over history was disqualified: {verification.summary}"
        return True, ""


def _slug(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in name.lower())
    return safe.strip("-") or "system"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# -------------------------------------------------------------- built-ins --

def builtin_systems() -> list[System]:
    """The two that ship.

    The five-market one is the reference design, translated into instruments a
    retail account can actually hold: you cannot buy "the S&P 500", you buy an
    ETF that tracks it. It needs Alpaca keys and it only trades during market
    hours, which is worth knowing before comparing it to a claim about trading
    continuously.

    The crypto one exists because the five-market one cannot run until somebody
    supplies keys, and an app whose only system is unusable on install is an app
    nobody gets past the first screen of.
    """
    return [
        System(
            name="reference-five",
            description=(
                "Five markets, three approaches: mean reversion on the equity "
                "indices, momentum on Bitcoin, trend following on the commodities. "
                "Index and commodity exposure is through ETFs, because a retail "
                "account cannot hold an index directly. Daily bars, on a free "
                "public feed that needs no account. The intraday version of this "
                "needs a paid data provider."
            ),
            venue="public",
            markets=[
                Market("SPY", "rsi-dip", "1d", whole_units=True),
                Market("QQQ", "rsi-dip", "1d", whole_units=True),
                Market("BTC-USD", "breakout", "1d"),
                Market("GLD", "ema-cross", "1d", whole_units=True),
                Market("USO", "ema-cross", "1d", whole_units=True),
            ],
            sizing=Sizing(mode="risk", risk_per_trade=0.01, atr_multiple=2.0,
                          max_position=0.25),
            limits=Limits(daily_loss=0.03, max_drawdown=0.15, consecutive_losses=5,
                          max_per_group=2, max_positions=5, max_exposure=0.90,
                          session_offset_hours=-5.0),
        ),
        System(
            name="crypto-three",
            description=(
                "The same three approaches on markets that need no broker account "
                "and never close. Runs the moment it is installed."
            ),
            venue="okx",
            markets=[
                Market("BTC/USDT", "breakout", "1h"),
                Market("ETH/USDT", "ema-cross", "15m"),
                Market("SOL/USDT", "rsi-dip", "4h"),
            ],
            sizing=Sizing(mode="risk", risk_per_trade=0.01, atr_multiple=2.0,
                          max_position=0.25),
            limits=Limits(daily_loss=0.03, max_drawdown=0.15, consecutive_losses=5,
                          max_per_group=2, max_positions=3, max_exposure=0.90),
        ),
    ]


def requirements(system: System) -> list[str]:
    """What is missing before this system can fetch a single bar."""
    missing: list[str] = []
    if system.venue == "alpaca":
        if not (os.environ.get("ALPACA_API_KEY") and os.environ.get("ALPACA_API_SECRET")):
            missing.append(
                "Alpaca API keys. Free with a paper account, and needed even to "
                "read prices. Set ALPACA_API_KEY and ALPACA_API_SECRET."
            )
        missing.append(
            "Alpaca's free market data is IEX only, which sees a small fraction "
            "of national volume. A backtest on it is not a backtest on what "
            "actually traded."
        )
    if system.venue == "public":
        # Not a blocker, and it should still be on the screen. Free data that
        # nobody warns you about is how a number gets trusted further than it
        # deserves.
        missing.append(
            "Prices come from a free public endpoint with no account behind it. "
            "It can change or refuse without notice, and it is not a data "
            "licence. Replace it with a real provider before trusting a number "
            "from it with money."
        )
    return missing
