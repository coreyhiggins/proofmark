"""A property test for lookahead bias.

The idea: a decision made at time ``t`` must not change when you rewrite the
future. So rewrite the future and check.

    for each bar t:
        mutate every value the strategy could not have seen at t
        re-run
        assert the decision at t is bit-identical

This is stronger than the sampling detectors that ship elsewhere, and their
own documentation says why. One reads: "Signals that are not triggered will
not have been verified. This would lead to a false-negative, i.e. the strategy
will be reported as non-biased." A detector that reports clean when it simply
did not look is worse than no detector.

The idea is not original. It appeared as a one-off regression test in a merged
pull request, written after five portfolio optimisers were found leaking at
once: mean-variance, equal-volatility, maximum-diversification, risk-parity
and turnover-aware, all using a close-to-close return that was not observable
when the weights executed at that bar's open. The fix shipped with a test
"proving that changing the decision bar's return cannot change weights
executed at that bar's open".

That test should not be a one-off. Here it is as a primitive.

WHAT COUNTS AS THE FUTURE DEPENDS ON WHEN YOU EXECUTE, which is the part the
original bug turned on:

- ``executes_at="open"``: the order fills at bar t's open, so everything about
  bar t except its open is unobservable. Perturbation starts at bar t.
- ``executes_at="close"``: the order fills at bar t's close, so bar t is fully
  observable and perturbation starts at bar t+1.

Getting this wrong in the permissive direction is exactly the bug being
hunted, so ``open`` is the default: it is the stricter of the two.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping, Sequence

Bar = Mapping[str, Any]
Strategy = Callable[[Sequence[Bar]], Sequence[Any]]

# Fields a strategy legitimately sees before the bar completes.
OBSERVABLE_AT_OPEN = frozenset({"open", "timestamp", "date", "time", "symbol"})


@dataclass
class Leak:
    bar: int
    original: Any
    perturbed: Any

    def __str__(self) -> str:
        return (
            f"bar {self.bar}: decision changed from {self.original!r} to "
            f"{self.perturbed!r} when only future data was altered"
        )


@dataclass
class LookaheadReport:
    bars_tested: int
    leaks: list[Leak] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.leaks

    def __bool__(self) -> bool:
        return self.clean

    def __str__(self) -> str:
        if self.clean:
            return f"no lookahead detected across {self.bars_tested} bars"
        lines = [f"LOOKAHEAD: {len(self.leaks)} of {self.bars_tested} bars leak"]
        lines += [f"  {leak}" for leak in self.leaks[:10]]
        if len(self.leaks) > 10:
            lines.append(f"  ... and {len(self.leaks) - 10} more")
        return "\n".join(lines)


def _perturb(
    bars: Sequence[Bar],
    start: int,
    rng: random.Random,
    keep: frozenset[str],
) -> list[dict[str, Any]]:
    """Copy the series, rewriting every unobservable numeric field from ``start``.

    The perturbation is large and sign-flipping on purpose. A subtle nudge can
    leave a threshold-crossing strategy on the same side of its threshold, and
    the test would pass while the leak survived.
    """
    out: list[dict[str, Any]] = [dict(bar) for bar in bars]
    for i in range(start, len(out)):
        for key, value in out[i].items():
            if key in keep or not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            out[i][key] = value * rng.uniform(-3.0, 3.0) + rng.uniform(-100.0, 100.0)
    return out


def check_lookahead(
    strategy: Strategy,
    bars: Sequence[Bar],
    *,
    executes_at: Literal["open", "close"] = "open",
    sample: int | None = None,
    seed: int = 0,
) -> LookaheadReport:
    """Run the perturbation property test over a strategy.

    ``strategy`` takes the whole series and returns one decision per bar, which
    is the vectorised shape where this bug lives. An event-driven strategy that
    only ever receives data up to now cannot leak this way by construction, and
    does not need this test.

    ``sample`` limits how many bars are tested, for speed. Leaving it ``None``
    tests every bar, which is the point: a sampling detector that misses is the
    failure mode this exists to avoid. If you set it, the report says so.
    """
    if len(bars) < 3:
        raise ValueError("need at least three bars to test anything")

    rng = random.Random(seed)
    baseline = list(strategy(bars))
    if len(baseline) != len(bars):
        raise ValueError(
            f"strategy returned {len(baseline)} decisions for {len(bars)} bars; "
            "it must return exactly one decision per bar"
        )

    keep = OBSERVABLE_AT_OPEN if executes_at == "open" else frozenset()
    indices = list(range(1, len(bars) - 1))
    if sample is not None and sample < len(indices):
        indices = sorted(rng.sample(indices, sample))

    report = LookaheadReport(bars_tested=len(indices))
    for t in indices:
        start = t if executes_at == "open" else t + 1
        if start >= len(bars):
            continue

        mutated = _perturb(bars, start, rng, keep)
        decisions = list(strategy(mutated))
        if decisions[t] != baseline[t]:
            report.leaks.append(Leak(bar=t, original=baseline[t], perturbed=decisions[t]))

    return report


def assert_no_lookahead(strategy: Strategy, bars: Sequence[Bar], **kwargs: Any) -> None:
    """Raise if the strategy leaks. For use in a project's own test suite."""
    report = check_lookahead(strategy, bars, **kwargs)
    if not report.clean:
        raise AssertionError(str(report))
