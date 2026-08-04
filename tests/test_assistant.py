"""Tests for the optional local writing help.

No network. Every test here either points the module at a dead host or hands it
a fake payload, because a test suite that needs a 7GB model installed is a test
suite that does not run.
"""

from __future__ import annotations

import pytest

from proofmark import assistant
from proofmark.assistant import (
    Reply, available, ask, draft_system, explain_refusal, rewrite_digest,
)


@pytest.fixture
def no_server(monkeypatch):
    """The normal case: nobody has a model installed."""
    monkeypatch.setattr(assistant, "HOST", "http://127.0.0.1:1")


def test_everything_still_works_with_no_model(no_server):
    """A feature that breaks when the optional part is missing was never
    optional. Each of these has to return the templated answer."""
    assert available() == ""
    assert ask("anything").text == ""

    digest = rewrite_digest("title", "Account 10,000. Return +2%.")
    assert digest.text == "Account 10,000. Return +2%."
    assert digest.written_by_model is False
    assert digest.credit == ""

    refusal = explain_refusal("it lost to holding", ["fatal: lost to holding"])
    assert refusal.text == "it lost to holding"

    drafted = draft_system("buy when it dips")
    assert "No local model" in drafted.text


def test_a_reasoning_model_that_answers_only_in_thinking_is_still_read(monkeypatch):
    """Verified against a real gemma4: with thinking on it spends the whole
    budget reasoning and returns an EMPTY response field. Without this the
    feature falls back to templates on exactly the machines with the best
    models on them."""
    seen = []

    def fake(model, prompt, temperature, *, think):
        seen.append(think)
        if think is False:
            return {"response": "", "thinking": "the account is up"}
        return {"response": "", "thinking": ""}

    monkeypatch.setattr(assistant, "_generate", fake)
    monkeypatch.setattr(assistant, "available", lambda: "ken:latest")

    reply = ask("summarise")
    assert reply.text == "the account is up"
    assert seen[0] is False, "the no-thinking attempt has to come first"


def test_a_server_that_rejects_the_thinking_flag_is_retried_without_it(monkeypatch):
    attempts = []

    def fake(model, prompt, temperature, *, think):
        attempts.append(think)
        return None if think is False else {"response": "fine"}

    monkeypatch.setattr(assistant, "_generate", fake)
    monkeypatch.setattr(assistant, "available", lambda: "old-model")

    assert ask("hello").text == "fine"
    assert attempts == [False, None]


def test_a_fast_model_is_preferred_over_a_merely_large_one(monkeypatch):
    """Picking the outright largest chose a 24GB model over a 7.6GB one that
    answers in seconds, for the job of restating five numbers."""
    monkeypatch.setattr(assistant, "installed_models", lambda: [
        ("sigel:latest", 23_900_000_000),
        ("ken:latest", 7_600_000_000),
        ("tiny:latest", 2_000_000_000),
    ])
    assert available() == "ken:latest"


def test_a_machine_with_only_a_huge_model_still_uses_it(monkeypatch):
    monkeypatch.setattr(assistant, "installed_models", lambda: [
        ("sigel:latest", 23_900_000_000),
    ])
    assert available() == "sigel:latest"


def test_model_output_is_stripped_of_the_dashes_this_project_bans(monkeypatch):
    monkeypatch.setattr(assistant, "_generate", lambda *a, **k: {
        "response": "Here is a summary:\nThe account rose 3% — a real move.\n**done**",
    })
    monkeypatch.setattr(assistant, "available", lambda: "any")

    text = ask("x").text
    assert "—" not in text and "–" not in text
    assert "**" not in text
    assert not text.lower().startswith("here is")


def test_a_model_written_reply_says_so():
    assert Reply("text", model="ken:latest").written_by_model is True
    assert "ken:latest" in Reply("text", model="ken:latest").credit
    assert Reply("text").written_by_model is False


def test_the_prompts_forbid_advice_in_as_many_words():
    """The guardrail is the prompt, so the prompt is the thing to assert on."""
    system = assistant.SYSTEM.lower()
    assert "never predict" in system
    assert "never advise" in system
    assert "do not invent" in system


def test_drafting_a_system_describes_rather_than_writes_to_disk(monkeypatch):
    """A model quietly authoring the thing that trades your money, with nobody
    reading it in between, is the one shape of this feature worth refusing."""
    captured = {}

    def fake(model, prompt, temperature, *, think):
        captured["prompt"] = prompt
        return {"response": "closest is rsi-dip on SPY at 1h"}

    monkeypatch.setattr(assistant, "_generate", fake)
    monkeypatch.setattr(assistant, "available", lambda: "any")

    reply = draft_system("I buy when things get oversold")
    assert "rsi-dip" in reply.text
    assert "Do not invent rule names" in captured["prompt"]
