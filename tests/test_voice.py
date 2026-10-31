from __future__ import annotations

from collections.abc import Callable

import pytest

from ghosts import voice
from ghosts.schema import TIERS, FactSheet
from ghosts.verify import SPECS
from ghosts.voice import build_prompt, clean_story, generate_story


class FakeClient:
    """Records each request and replies with a canned story. No network, no Ollama."""

    def __init__(self, reply: str = "A quiet story.") -> None:
        self.reply = reply
        self.calls: list[tuple[str, str, int | None]] = []

    def generate(self, prompt: str, *, system: str = "", seed: int | None = None) -> str:
        self.calls.append((prompt, system, seed))
        return self.reply


# --- the prompt -------------------------------------------------------------------------------


def test_prompt_contains_every_fact(sheet: FactSheet) -> None:
    prompt = build_prompt(sheet, "young")
    for text in (
        sheet.name,
        sheet.body,
        sheet.launched,
        sheet.arrived or "",
        sheet.ended or "",
        sheet.last_contact or "",
        sheet.status,
        sheet.purpose,
        sheet.fun_fact,
        *sheet.discoveries,
        *sheet.how_it_worked,
    ):
        assert text in prompt


def test_prompt_leaves_out_sources_and_the_verifier(sheet: FactSheet) -> None:
    prompt = build_prompt(sheet, "older")
    assert "https://" not in prompt
    assert sheet.verified_by is not None and sheet.verified_by not in prompt


def test_prompt_states_the_accuracy_and_safety_rules(sheet: FactSheet) -> None:
    prompt = build_prompt(sheet, "young")
    assert "ONLY the facts" in prompt
    assert "Do not use quotation marks" in prompt
    assert "Never frighten" in prompt
    assert "Output only the story." in prompt


def test_prompt_skips_missing_optional_dates(make_sheet: Callable[..., FactSheet]) -> None:
    prompt = build_prompt(make_sheet(arrived=None, last_contact=None), "young")
    assert "Arrived:" not in prompt
    assert "Last contact:" not in prompt


def test_the_two_levels_ask_for_different_stories(sheet: FactSheet) -> None:
    young, older = build_prompt(sheet, "young"), build_prompt(sheet, "older")
    assert "ages 7 to 9" in young and "ages 14 to 18" in older
    assert young != older
    assert "ages 9 to 10" not in young and "ages 12 to 14" not in older
    for level, prompt in (("young", young), ("older", older)):
        spec = SPECS[level]
        assert f"between {spec.min_words + 10} and {spec.max_words - 10} words" in prompt


@pytest.mark.parametrize("tier", ["resting", "restless", "lost"])
def test_every_tier_has_a_gentle_note(make_sheet: Callable[..., FactSheet], tier: str) -> None:
    assert voice._TIER_NOTES[tier] in build_prompt(make_sheet(tier=tier), "young")


def test_dates_are_requested_in_words_with_an_example_from_this_sheet(sheet: FactSheet) -> None:
    prompt = build_prompt(sheet, "young")
    assert "Write dates in words" in prompt
    assert "2003-07-07 is written July 7, 2003." in prompt
    assert "1977-09-05" not in prompt  # no other machine's date is baked into the prompt


def test_a_partial_launch_date_gets_the_rule_without_an_example(
    make_sheet: Callable[..., FactSheet],
) -> None:
    prompt = build_prompt(make_sheet(launched="1970-01"), "young")
    assert "Write dates in words" in prompt
    assert "For example" not in prompt


def test_every_tier_in_the_schema_has_a_prompt_note() -> None:
    assert set(voice._TIER_NOTES) == set(TIERS)


def test_retry_prompt_lists_the_problems(sheet: FactSheet) -> None:
    first = build_prompt(sheet, "young")
    retry = build_prompt(sheet, "young", ["the number 777 is not in the fact sheet"])
    assert "rejected" not in first
    assert "rejected" in retry
    assert "- the number 777 is not in the fact sheet" in retry
    assert retry.endswith("Output only the story.")


def test_prompt_rejects_an_unknown_level(sheet: FactSheet) -> None:
    with pytest.raises(ValueError, match="unknown reading level"):
        build_prompt(sheet, "toddler")


# --- cleaning the model's reply ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("  A story.  ", "A story."),
        ("Line one.\n\nLine   two.", "Line one. Line two."),
        ("```\nA story.\n```", "A story."),
        ("```text\nA story.\n```", "A story."),
        ("Story: A story.", "A story."),
        ("Ghost story: A story.", "A story."),
        ('"A story."', "A story."),
        ("“A story.”", "A story."),
        ('He said "hi" and "bye"', 'He said "hi" and "bye"'),
        ('"One." "Two."', '"One." "Two."'),
        ('"', '"'),
    ],
)
def test_clean_story(raw: str, clean: str) -> None:
    assert clean_story(raw) == clean


# --- generating a draft -----------------------------------------------------------------------


def test_generate_story_sends_prompt_system_and_seed(sheet: FactSheet) -> None:
    client = FakeClient('"I am Test Rover."')
    text = generate_story(client, sheet, "young")
    assert text == "I am Test Rover."
    [(prompt, system, seed)] = client.calls
    assert prompt == build_prompt(sheet, "young")
    assert system == voice.SYSTEM
    assert seed == voice.BASE_SEED


def test_the_seed_can_be_chosen(sheet: FactSheet) -> None:
    client = FakeClient()
    generate_story(client, sheet, "young", seed=100)
    generate_story(client, sheet, "young", ["a problem"], seed=100)
    assert [call[2] for call in client.calls] == [100, 101]


def test_the_retry_uses_a_different_seed_and_the_problems(sheet: FactSheet) -> None:
    client = FakeClient()
    generate_story(client, sheet, "older", ["too short: 3 words (at least 60)"])
    prompt, _, seed = client.calls[0]
    assert seed == voice.BASE_SEED + 1
    assert "too short: 3 words" in prompt


def test_generate_story_is_not_reached_with_a_bad_level(sheet: FactSheet) -> None:
    client = FakeClient()
    with pytest.raises(ValueError, match="unknown reading level"):
        generate_story(client, sheet, "toddler")
    assert client.calls == []
