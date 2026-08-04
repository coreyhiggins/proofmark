"""Optional local writing help, and a template that works when it is absent.

Three jobs, none of which touch a decision:

- Write the two daily messages in readable English instead of a template.
- Turn a strategy described in words into a system file you can then check.
- Explain a failed check in the reader's own terms.

WHAT IT IS NOT ALLOWED TO DO.

It never chooses a trade, never sizes one, never sets a limit, and never sees
a price it could form a view about. It reports what already happened and what
the rules already did. Every prompt in this file forbids prediction and advice
in as many words, and every output is labelled as written by a model.

That is not squeamishness. The research this project was built on found no
demonstrated edge from language models in trading, and a summary that drifts
into "looks like it is turning" is exactly the failure that finding predicts.
Describing is useful. Advising is the thing with no evidence behind it.

WHY OLLAMA, AND WHY THE MODEL IS DISCOVERED RATHER THAN NAMED.

Local, free, no key, no account, and the user's data never leaves the machine,
which matters when the data is a record of their money. The model is whatever
they happen to have: this asks Ollama what is installed and picks the largest,
so a machine with a 12B answers with a 12B and a machine with a 3B answers with
a 3B, and neither needs a setting.

THE FALLBACK IS THE NORMAL CASE.

Most people will have no model at all. Everything here returns a templated
answer when that happens, and says which it gave. A feature that breaks when
the optional part is missing was never optional.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")

# Long enough for a small model on a cold start, short enough that a wedged
# server does not hold up a trading loop. The loop treats a miss as a template.
TIMEOUT = 90

# Nothing about this is a decision, so the model is asked to be dull and exact.
SYSTEM = (
    "You write short, plain status notes about an automated trading program "
    "that has already finished acting. You are describing a record.\n"
    "Rules you must follow:\n"
    "- Never predict, forecast, or say what a market might do.\n"
    "- Never advise, suggest a change, or recommend an action.\n"
    "- Never call a result good or bad. Report it.\n"
    "- Use only the numbers given to you. Do not invent any.\n"
    "- No hype, no encouragement, no emoji, no exclamation marks.\n"
    "- Short sentences. Plain words. No em dashes.\n"
)


@dataclass
class Reply:
    text: str
    model: str = ""

    @property
    def written_by_model(self) -> bool:
        return bool(self.model)

    @property
    def credit(self) -> str:
        return f"Written by {self.model}, running on this machine." if self.model else ""


def installed_models() -> list[tuple[str, int]]:
    """Every model Ollama has, largest first. Empty if it is not running."""
    try:
        with urllib.request.urlopen(f"{HOST}/api/tags", timeout=5) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return []

    found = [
        (str(m.get("name", "")), int(m.get("size", 0)))
        for m in payload.get("models") or []
        if m.get("name")
    ]
    # Largest first. Not a quality measure, but on one person's machine it is a
    # reliable enough proxy, and it means nobody has to configure anything.
    return sorted(found, key=lambda pair: pair[1], reverse=True)


# Above this, a model answers slowly enough to matter on a machine that is also
# running a trading loop. Picking the outright largest chose a 24GB model over a
# 7.6GB one that answers in seconds, for the job of restating five numbers in
# better English. Quality past a point buys nothing here.
COMFORTABLE_BYTES = 12_000_000_000


def available() -> str:
    """The model this machine would use, or an empty string.

    The largest one that still answers quickly, reaching for something bigger
    only when there is nothing else installed.
    """
    models = installed_models()
    if not models:
        return ""
    comfortable = [m for m in models if m[1] <= COMFORTABLE_BYTES]
    return (comfortable[0] if comfortable else models[-1])[0]


def ask(prompt: str, *, model: str = "", temperature: float = 0.2) -> Reply:
    """One turn. Returns an empty Reply rather than raising, always.

    A low temperature on purpose: this is asked to restate numbers, and a model
    being creative with somebody's account balance is the one behaviour that
    would make this worse than the template it replaces.
    """
    chosen = model or available()
    if not chosen:
        return Reply("")

    # think=False matters more than it looks. A reasoning model spends the whole
    # token budget thinking and returns an EMPTY response field, so without this
    # the feature falls back to templates on exactly the machines carrying the
    # best models. Verified against a local gemma4: empty every time with
    # thinking on, correct every time with it off.
    payload = _generate(chosen, prompt, temperature, think=False)
    if payload is None:
        # An older server may not know the field. Try again without it, and read
        # the thinking channel, which is where such a model puts its answer.
        payload = _generate(chosen, prompt, temperature, think=None)
    if payload is None:
        return Reply("")

    text = str(payload.get("response") or payload.get("thinking") or "").strip()
    if not text:
        return Reply("")
    return Reply(_clean(text), model=chosen)


def _generate(model: str, prompt: str, temperature: float,
              *, think: bool | None) -> dict | None:
    body: dict = {
        "model": model,
        "prompt": prompt,
        "system": SYSTEM,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": 400},
    }
    if think is not None:
        body["think"] = think

    request = urllib.request.Request(
        f"{HOST}/api/generate", data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def _clean(text: str) -> str:
    """Strip the tics that make model output look like model output.

    The dash replacement is not cosmetic here. This project bans them in its own
    writing, and a model that has read the whole internet reaches for them
    constantly, so text that arrives with them would be visibly not ours.
    """
    text = text.replace("—", ", ").replace("–", "-")
    for fence in ("```", "**"):
        text = text.replace(fence, "")
    lines = [line.rstrip() for line in text.splitlines()]
    # Models like to open with "Here is a summary:". Drop a lead-in that only
    # announces the thing the reader is already looking at.
    while lines and lines[0].lower().rstrip(":").startswith(
        ("here is", "here's", "sure", "certainly", "of course", "summary")
    ):
        lines.pop(0)
    return "\n".join(lines).strip()


def rewrite_digest(title: str, templated: str, *, model: str = "") -> Reply:
    """Say the same numbers in better English. Falls back to the template."""
    reply = ask(
        "Rewrite this status note so a person who does not trade can read it. "
        "Keep every number exactly as written. Two or three sentences. Do not "
        "add anything that is not here.\n\n"
        f"Title: {title}\n{templated}",
        model=model,
    )
    return reply if reply.text else Reply(templated)


def explain_refusal(summary: str, findings: list[str], *, model: str = "") -> Reply:
    """Put a failed check in the reader's words, without softening it."""
    joined = "\n".join(f"- {f}" for f in findings[:8])
    reply = ask(
        "An automated check refused to approve a trading system. Explain why in "
        "two or three plain sentences, for someone who is not a programmer. Do "
        "not soften it, do not suggest fixes, and do not say whether the system "
        "is good.\n\n"
        f"Verdict: {summary}\nFindings:\n{joined}",
        model=model,
    )
    return reply if reply.text else Reply(summary)


def draft_system(description: str, *, model: str = "") -> Reply:
    """Turn a described strategy into something a person can check and edit.

    Returns prose describing which built-in rules and markets fit, NOT a config
    written straight to disk. A model quietly authoring the thing that trades
    your money, with nobody reading it in between, is the one shape of this
    feature worth refusing.
    """
    reply = ask(
        "Someone described a trading strategy in their own words. Say which of "
        "these built-in rule sets is closest, and on which markets and bar "
        "sizes. Do not invent rule names. Do not say whether the strategy is "
        "any good. If the description is too vague to match, say what is "
        "missing.\n\n"
        "Available rules:\n"
        "- ema-cross: buys when a 9 bar average crosses above a 21 bar average\n"
        "- rsi-dip: buys when RSI falls under 30, sells once it passes 55\n"
        "- breakout: buys a 20 bar high, sells a 20 bar low\n"
        "- buy-and-hold: buys once and never trades again\n\n"
        f"Their description:\n{description}",
        model=model,
    )
    return reply if reply.text else Reply(
        "No local model is installed, so this one needs you. Pick the rule set "
        "closest to your strategy from the four above, then edit the system "
        "file directly."
    )
