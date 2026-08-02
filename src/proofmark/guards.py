"""The guards. This is the part of proofmark that other backtesters do not ship.

A backtest result is a claim. These checks decide whether the claim is
reportable at all, and they run on every result rather than on request.

Three findings shaped this module, each from a real project:

1. A widely deployed strategy publishes backtests showing a 100% win rate,
   0% max drawdown and a Sharpe of 42.73, beside Sortino and Calmar of exactly
   -100.00. The -100.00 is a divide-by-zero sentinel. Nothing suppressed it.

2. The most requested feature in a 21,000-star backtesting platform, open for
   three years with 115 reactions, is walk-forward validation. It is still not
   shipped. Another popular library advertises testing "hundreds of strategy
   variants in mere seconds" with no overfitting warning in its docs at all.

3. Sullivan, Timmermann and White searched 7,846 trading rules over a century
   of index data. Their best out-of-sample rule scored a nominal p-value of
   0.000 and a snooping-adjusted p-value of 0.341. On futures it was 0.042
   against 0.908. Same rule, same data. The only difference is whether you
   account for having searched.

So a result carries the number of trials behind it, or it is not a result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .metrics import Metrics

# Above this, a Sharpe on daily bars is almost always a bug rather than a
# strategy. Renaissance's Medallion fund is the usual benchmark for what an
# extraordinary real Sharpe looks like, and it is far below this line.
IMPLAUSIBLE_SHARPE = 4.0

# Below this many trades, dispersion swamps any estimate of skill.
THIN_SAMPLE = 30


class Severity(str, Enum):
    """FATAL suppresses the report. WARN prints alongside it."""

    FATAL = "fatal"
    WARN = "warn"


@dataclass(frozen=True)
class Finding:
    severity: Severity
    code: str
    detail: str
    why: str


@dataclass
class Verdict:
    """The outcome of checking a result. Falsy when the report is suppressed."""

    findings: list[Finding] = field(default_factory=list)

    @property
    def fatal(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.FATAL]

    @property
    def reportable(self) -> bool:
        return not self.fatal

    def __bool__(self) -> bool:
        return self.reportable


def check(
    result: Metrics,
    *,
    trials: int = 1,
    costs_applied: float | None = None,
    delisted_included: bool | None = None,
    benchmark_return: float | None = None,
) -> Verdict:
    """Decide whether a backtest result may be reported.

    ``trials`` is how many strategy variants were evaluated against this data.
    ``costs_applied`` is the total paid in fees, spread and funding.
    ``delisted_included`` says whether the universe contains assets that no
    longer exist. ``None`` means the caller did not say, which is itself worth
    reporting rather than assuming the flattering answer.
    """
    out = Verdict()
    add = out.findings.append

    # ---------------------------------------------------------- impossible --

    if result.max_drawdown == 0 and result.trades > 0:
        add(Finding(
            Severity.FATAL, "zero-drawdown",
            "maximum drawdown is exactly 0% across "
            f"{result.trades} trades",
            "No strategy holding real positions has never been underwater. "
            "This is normally drawdown measured from realised profit at trade "
            "close rather than from mark-to-market equity, which lets any "
            "hold-until-green strategy report zero by construction.",
        ))

    if result.win_rate == 1.0 and result.trades > 0:
        add(Finding(
            Severity.FATAL, "perfect-win-rate",
            f"{result.trades} trades, {result.trades} wins, 0 losses",
            "A strategy that never loses has seen the future. Check for "
            "lookahead before checking anything else.",
        ))

    if result.sharpe is not None and result.sharpe > IMPLAUSIBLE_SHARPE:
        add(Finding(
            Severity.FATAL, "implausible-sharpe",
            f"Sharpe {result.sharpe:.2f}, above the plausibility bound of "
            f"{IMPLAUSIBLE_SHARPE}",
            "Sharpe ratios this high in a backtest are lookahead bias, "
            "survivorship, or unrealistic fills. They are essentially never a "
            "strategy. Find the bug before celebrating.",
        ))

    if costs_applied is not None and costs_applied <= 0 and result.trades > 0:
        add(Finding(
            Severity.FATAL, "no-costs-applied",
            f"{result.trades} trades and zero total cost",
            "A cost model that silently applies nothing is worse than no cost "
            "model, because the result looks priced. One real project fetched "
            "funding rates and discarded them for months because of timestamp "
            "jitter, and no backtest ever noticed.",
        ))

    # ----------------------------------------------------- beaten by nothing --

    if benchmark_return is not None:
        gap = result.total_return - benchmark_return
        if gap < 0:
            add(Finding(
                Severity.FATAL, "beaten-by-holding",
                f"buying once and holding returned {benchmark_return:.1%}, "
                f"against {result.total_return:.1%} here, so the strategy cost "
                f"{abs(gap):.1%}",
                "This is the comparison that decides whether a strategy was worth "
                "running, and it is the one most reports leave out. A widely shared "
                "test of twelve famous strategies against one asset found eleven of "
                "them lost to doing nothing, and the headline was about the "
                "twelfth. Trading was worse than not trading.",
            ))
        elif gap < 0.05:
            add(Finding(
                Severity.WARN, "barely-beat-holding",
                f"ahead of buying and holding by {gap:.1%}",
                "A margin this thin does not survive a fee schedule, a worse fill, "
                "or a different starting date. Treat it as a tie.",
            ))

    # ------------------------------------------------------------ undefined --

    for name, value in (("sortino", result.sortino), ("calmar", result.calmar)):
        if value is None:
            add(Finding(
                Severity.WARN, f"undefined-{name}",
                f"{name} is undefined for this result",
                "Reported as undefined rather than as a number. A sentinel "
                "value here is how a divide-by-zero ends up printed as a "
                "headline metric.",
            ))

    # ------------------------------------------------------------- searched --

    if trials > 1:
        add(Finding(
            Severity.WARN, "multiple-testing",
            f"{trials} strategy variants were evaluated against this data",
            "The best of N searches is not the same as a strategy that works. "
            "A published search over 7,846 rules produced a best rule with a "
            "nominal p-value of 0.000 and a snooping-adjusted p-value of "
            "0.341. Report the adjusted figure or report the trial count.",
        ))

    if trials > 50:
        add(Finding(
            Severity.FATAL, "search-without-correction",
            f"{trials} trials is a search, not a test",
            "At this many variants the best result is expected to look good "
            "by chance alone. Use walk-forward validation and report the "
            "snooping-adjusted statistic, or do not report a headline number.",
        ))

    # --------------------------------------------------------------- sample --

    if 0 < result.trades < THIN_SAMPLE:
        add(Finding(
            Severity.WARN, "thin-sample",
            f"{result.trades} trades is below the {THIN_SAMPLE} needed for the "
            "ratios above to mean much",
            "Dispersion dominates at this sample size. Treat the ratios as "
            "descriptive of this run, not as an estimate of future behaviour.",
        ))

    # -------------------------------------------------------- undisclosed ---

    if delisted_included is False:
        add(Finding(
            Severity.FATAL, "survivors-only",
            "the universe excludes assets that no longer exist",
            "Measured survivorship bias on an equal-weighted crypto "
            "buy-and-hold portfolio is 62% annualised, across 3,904 assets of "
            "which 1,222 were delisted. Momentum and beta effects largely "
            "disappear once delisted returns are included. A survivors-only "
            "universe does not produce a smaller result, it produces a "
            "different one.",
        ))
    elif delisted_included is None:
        add(Finding(
            Severity.WARN, "survivorship-unknown",
            "the caller did not say whether delisted assets are included",
            "Unknown is reported rather than assumed. The flattering "
            "assumption is the one that costs money.",
        ))

    return out


def format_verdict(verdict: Verdict) -> str:
    """Render findings for a terminal. Fatal first, because they suppress."""
    if not verdict.findings:
        return "no findings"

    lines: list[str] = []
    for finding in sorted(verdict.findings, key=lambda f: f.severity is not Severity.FATAL):
        marker = "FATAL" if finding.severity is Severity.FATAL else " WARN"
        lines.append(f"{marker}  {finding.code}: {finding.detail}")
        lines.append(f"        {finding.why}")
    return "\n".join(lines)
