from __future__ import annotations

from collections.abc import Callable, Sequence

import pytest

from ghosts.llm import LLMError
from ghosts.schema import TIERS, FactSheet
from ghosts.verify import (
    LEVELS,
    ORIGIN_MODEL,
    ORIGIN_TEMPLATE,
    SPECS,
    _parse_number_phrase,
    check_story,
    facts_for,
    resolve_story,
    template_story,
)

# Written to pass for the "Test Rover" sheet in conftest.py: every number, month, name and
# quoted phrase below comes from that sheet.
YOUNG = (
    "I am Test Rover. I rolled across Mars on six wheels. I looked for clues that water once "
    "flowed there. I found tiny round pebbles in the soil. I was built to last 90 days. But I "
    "worked for almost 15 years! Then a big dust storm came. I stopped talking. Now I rest on a "
    "dusty plain."
)
OLDER = (
    "I am Test Rover, and I spent my years rolling across Mars on six wheels. I was built to "
    "last 90 days, yet I kept working for almost 15 years. My job was to look for clues that "
    'water once flowed on Mars, and I found tiny round pebbles nicknamed "blueberries" in the '
    "soil. I also found layered rocks that formed in ancient water. In a big dust storm I "
    "stopped talking, and now I rest on a dusty plain. Thank you for lighting a candle for me."
)


def problems(sheet: FactSheet, text: str, level: str = "older", **kwargs: bool) -> list[str]:
    return list(check_story(sheet, text, level, **kwargs).problems)


def mentions(found: list[str], fragment: str) -> bool:
    return any(fragment in item for item in found)


# --- a good story passes ----------------------------------------------------------------------


def test_good_young_story_passes(sheet: FactSheet) -> None:
    assert problems(sheet, YOUNG, "young") == []


def test_good_older_story_passes(sheet: FactSheet) -> None:
    assert problems(sheet, OLDER, "older") == []


def test_spelled_out_numbers_are_fine_when_the_sheet_has_the_value(sheet: FactSheet) -> None:
    text = YOUNG.replace("15 years", "fifteen years").replace("90 days", "ninety days")
    assert problems(sheet, text, "young") == []


def test_months_from_the_date_fields_are_allowed(sheet: FactSheet) -> None:
    text = YOUNG + " I began my trip in July 2003 and last spoke in June."
    assert not mentions(problems(sheet, text, "young", check_style=False), "month")


def test_unknown_level_is_an_error(sheet: FactSheet) -> None:
    with pytest.raises(ValueError, match="unknown reading level"):
        check_story(sheet, YOUNG, "toddler")


@pytest.mark.parametrize("text", ["", "   \n"])
def test_empty_story_fails(sheet: FactSheet, text: str) -> None:
    assert problems(sheet, text) == ["the story is empty"]


# --- numbers and dates ------------------------------------------------------------------------


@pytest.mark.parametrize("wrong", ["120 days", "16 years", "1,000 wheels", "3.5 days"])
def test_invented_digit_numbers_are_caught(sheet: FactSheet, wrong: str) -> None:
    text = YOUNG + f" I rolled for {wrong}."
    assert mentions(problems(sheet, text, "young", check_style=False), "is not in the fact sheet")


@pytest.mark.parametrize("word", ["three", "twenty", "hundred", "thousands", "twice"])
def test_invented_number_words_are_caught(sheet: FactSheet, word: str) -> None:
    text = YOUNG + f" I found {word} rocks."
    assert mentions(problems(sheet, text, "young", check_style=False), f"'{word}'")


def test_one_is_not_treated_as_a_number_word(sheet: FactSheet) -> None:
    text = YOUNG + " No one forgot me one bit."
    assert not mentions(problems(sheet, text, "young", check_style=False), "number")


def test_a_month_the_sheet_never_mentions_is_caught(sheet: FactSheet) -> None:
    text = YOUNG + " I landed in March."
    assert mentions(problems(sheet, text, "young", check_style=False), "month March")


def test_may_is_only_a_month_before_a_number(sheet: FactSheet) -> None:
    verb = YOUNG + " May we always remember."
    month = YOUNG + " I woke on May 5."
    assert not mentions(problems(sheet, verb, "young", check_style=False), "month")
    assert mentions(problems(sheet, month, "young", check_style=False), "month May")


# --- names and quotes -------------------------------------------------------------------------


def test_an_invented_name_mid_sentence_is_caught(sheet: FactSheet) -> None:
    text = YOUNG + " My friend Spirit waved at me."
    assert mentions(problems(sheet, text, "young", check_style=False), "'Spirit'")


def test_an_invented_two_word_name_starting_a_sentence_is_caught(sheet: FactSheet) -> None:
    text = YOUNG + " Doctor Rivera cheered for me."
    found = problems(sheet, text, "young", check_style=False)
    assert mentions(found, "'Doctor'") and mentions(found, "'Rivera'")


def test_names_from_the_sheet_and_the_sky_are_fine(sheet: FactSheet) -> None:
    text = YOUNG + " The Sun was kind to Test Rover, and Earth was far away."
    assert not mentions(problems(sheet, text, "young", check_style=False), "name")


def test_a_possessive_of_a_known_name_is_fine(sheet: FactSheet) -> None:
    text = YOUNG + " Mars's sky was my roof."
    assert not mentions(problems(sheet, text, "young", check_style=False), "name")


def test_a_phrase_quoted_from_the_sheet_is_fine(sheet: FactSheet) -> None:
    text = YOUNG + ' The pebbles were called "Blueberries," you see.'
    assert not mentions(problems(sheet, text, "young", check_style=False), "quotation")


@pytest.mark.parametrize("curly", [False, True])
def test_an_invented_quotation_is_caught(sheet: FactSheet, curly: bool) -> None:
    said = "“We did it!”" if curly else '"We did it!"'
    text = YOUNG + f" The team said {said}"
    assert mentions(problems(sheet, text, "young", check_style=False), "quotation")


def test_an_unmatched_quotation_mark_is_caught(sheet: FactSheet) -> None:
    text = YOUNG + ' I said "hello.'
    assert mentions(problems(sheet, text, "young", check_style=False), "unmatched")


# --- tone, markup and grounding ---------------------------------------------------------------


@pytest.mark.parametrize("word", ["crashed", "died", "Death", "terrifying", "blood"])
def test_frightening_words_are_caught(sheet: FactSheet, word: str) -> None:
    text = YOUNG + f" It was {word} for me."
    assert mentions(problems(sheet, text, "young", check_style=False), "frightening")


def test_a_frightening_word_the_sheet_itself_uses_is_not_blocked(
    make_sheet: Callable[..., FactSheet],
) -> None:
    sheet = make_sheet(status="Its engines died quietly on Mars.")
    text = YOUNG + " Its engines died quietly."
    assert not mentions(problems(sheet, text, "young", check_style=False), "frightening")


@pytest.mark.parametrize(
    "bit", ["See https://example.org", "**bold**", "# Title", "<b>hi</b>", "[link](x)", "`code`"]
)
def test_markup_and_links_are_caught(sheet: FactSheet, bit: str) -> None:
    assert mentions(problems(sheet, YOUNG + " " + bit, "young", check_style=False), "markup")


def test_a_story_that_wanders_off_the_sheet_is_caught(sheet: FactSheet) -> None:
    text = (
        "Mysterious crystalline glaciers whispered ancient prophecies beneath luminous "
        "auroras while wandering explorers harvested enormous magnetic treasures nearby."
    )
    assert mentions(problems(sheet, text, "older", check_style=False), "not in the fact sheet")


def test_short_stories_are_not_judged_on_grounding(sheet: FactSheet) -> None:
    assert problems(sheet, "Sparkling fantastic wonders.", "young", check_style=False) == []


# --- reading level ----------------------------------------------------------------------------


def test_too_short_and_too_long_are_caught(sheet: FactSheet) -> None:
    assert mentions(problems(sheet, "I am Test Rover.", "young"), "too short")
    assert mentions(problems(sheet, " ".join([YOUNG] * 3), "young"), "too long")


def test_long_sentences_fail_the_young_level_but_not_the_older(sheet: FactSheet) -> None:
    long_one = (
        "I rolled across Mars on six wheels and I looked for clues that water once flowed "
        "there and I found tiny round pebbles in the soil."
    )
    assert mentions(problems(sheet, long_one, "young"), "sentence")
    assert not mentions(problems(sheet, long_one + " " + YOUNG, "older"), "sentence")


def test_style_can_be_switched_off(sheet: FactSheet) -> None:
    assert problems(sheet, "I am Test Rover.", "young", check_style=False) == []


def test_each_problem_is_reported_once(sheet: FactSheet) -> None:
    text = YOUNG + " I saw 77 rocks. I saw 77 rocks."
    found = problems(sheet, text, "young", check_style=False)
    assert len(found) == len(set(found))


# --- what a story may draw on -----------------------------------------------------------------


def test_facts_take_years_months_and_exact_dates_from_the_date_fields(sheet: FactSheet) -> None:
    facts = facts_for(sheet)
    assert {"90", "15", "2003", "2004", "2019", "2018"} <= facts.numbers
    assert "7" not in facts.numbers and "2" not in facts.numbers  # month and day are not numbers
    assert {"July", "January", "February", "June"} == facts.months
    assert {"July 7", "January 24", "February 13", "June 10"} == facts.days
    assert "mars" in facts.words and "test" in facts.words


def test_an_exact_date_from_the_sheet_is_allowed(sheet: FactSheet) -> None:
    text = YOUNG + " I left Earth on July 7, 2003, and last spoke on June 10, 2018."
    assert problems(sheet, text, "young", check_style=False) == []


def test_a_wrong_day_in_a_real_month_is_caught(sheet: FactSheet) -> None:
    text = YOUNG + " I left Earth on July 8, 2003."
    assert mentions(problems(sheet, text, "young", check_style=False), "the date July 8")


def test_a_day_number_from_a_date_does_not_excuse_the_same_number_elsewhere(
    sheet: FactSheet,
) -> None:
    text = YOUNG + " I found 7 rocks."
    assert mentions(problems(sheet, text, "young", check_style=False), "the number 7")


# --- the template fallback --------------------------------------------------------------------


@pytest.mark.parametrize("level", LEVELS)
def test_template_passes_the_fact_checks(sheet: FactSheet, level: str) -> None:
    text = template_story(sheet, level)
    assert problems(sheet, text, level, check_style=False) == []


@pytest.mark.parametrize("level", LEVELS)
def test_real_templates_pass_the_fact_checks(
    real_sheets: tuple[FactSheet, ...], level: str
) -> None:
    assert real_sheets
    for real in real_sheets:
        text = template_story(real, level)
        assert problems(real, text, level, check_style=False) == [], real.id


def test_templates_are_deterministic_and_use_only_the_sheet(sheet: FactSheet) -> None:
    assert template_story(sheet, "young") == template_story(sheet, "young")
    text = template_story(sheet, "older")
    assert text.startswith("Test Rover is remembered here.")
    assert "Its mission was to look for clues that water once flowed on Mars." in text
    assert "{" not in text and "None" not in text


def test_young_template_picks_the_shortest_sentences(sheet: FactSheet) -> None:
    text = template_story(sheet, "young")
    assert "It found layered rocks that formed in ancient water." in text
    assert "blueberries" in text
    assert "worked for almost 15 years" not in text  # the longest of the three is left out


@pytest.mark.parametrize(
    ("tier", "phrase"),
    [
        ("resting", "to remember Test Rover"),
        ("restless", "to keep Test Rover company"),
        ("lost", "so Test Rover is not forgotten"),
    ],
)
def test_template_closing_follows_the_tier(
    make_sheet: Callable[..., FactSheet], tier: str, phrase: str
) -> None:
    assert phrase in template_story(make_sheet(tier=tier), "young")


def test_template_rejects_an_unknown_level(sheet: FactSheet) -> None:
    with pytest.raises(ValueError, match="unknown reading level"):
        template_story(sheet, "toddler")


# --- retry and fallback -----------------------------------------------------------------------


class Drafts:
    """A fake generator that returns scripted drafts and records the problems it was given."""

    def __init__(self, *drafts: str | Exception) -> None:
        self.drafts = list(drafts)
        self.seen: list[tuple[str, ...]] = []

    def __call__(self, problems: Sequence[str]) -> str:
        self.seen.append(tuple(problems))
        draft = self.drafts.pop(0)
        if isinstance(draft, Exception):
            raise draft
        return draft


BAD = "I rolled for 777 days."


def test_a_good_first_draft_is_used(sheet: FactSheet) -> None:
    drafts = Drafts(YOUNG)
    story = resolve_story(sheet, "young", drafts)
    assert (story.text, story.origin, story.attempts, story.problems) == (YOUNG, "model", 1, ())
    assert drafts.seen == [()]


def test_a_bad_draft_is_retried_once_with_the_problems(sheet: FactSheet) -> None:
    drafts = Drafts(BAD, YOUNG)
    story = resolve_story(sheet, "young", drafts)
    assert story.origin == "model"
    assert story.attempts == 2
    assert drafts.seen[0] == ()
    assert any("777" in item for item in drafts.seen[1])


def test_two_bad_drafts_fall_back_to_the_template(sheet: FactSheet) -> None:
    drafts = Drafts(BAD, BAD, YOUNG)
    story = resolve_story(sheet, "young", drafts)
    assert story.origin == "template"
    assert story.text == template_story(sheet, "young")
    assert story.attempts == 2
    assert any("777" in item for item in story.problems)
    assert len(drafts.drafts) == 1  # a third draft was never requested


def test_no_generator_means_template_straight_away(sheet: FactSheet) -> None:
    story = resolve_story(sheet, "older")
    assert (story.origin, story.attempts, story.problems) == ("template", 0, ())
    assert story.text == template_story(sheet, "older")


def test_an_unreachable_model_falls_back_without_a_retry(sheet: FactSheet) -> None:
    drafts = Drafts(LLMError("connection refused"), YOUNG)
    story = resolve_story(sheet, "young", drafts)
    assert story.origin == "template"
    assert story.attempts == 0
    assert "connection refused" in story.problems[0]
    assert len(drafts.seen) == 1


def test_the_retry_count_can_be_changed(sheet: FactSheet) -> None:
    drafts = Drafts(BAD, BAD, BAD)
    story = resolve_story(sheet, "young", drafts, retries=2)
    assert story.attempts == 3 and story.origin == "template"


# --- reading levels: young is for ages 7 to 9, older for 14 to 18 -------------------------------


def test_the_two_levels_are_for_the_requested_ages() -> None:
    assert LEVELS == ("young", "older")
    assert SPECS["young"].ages == "7 to 9"
    assert SPECS["older"].ages == "14 to 18"


def test_the_young_level_is_stricter_than_the_older() -> None:
    young, older = SPECS["young"], SPECS["older"]
    assert young.avg_sentence_words < older.avg_sentence_words
    assert young.max_sentence_words < older.max_sentence_words
    assert young.max_words < older.max_words


def test_a_story_too_dense_for_seven_year_olds_is_fine_for_teenagers(sheet: FactSheet) -> None:
    dense = (
        "I am Test Rover, and for almost 15 years I rolled across Mars on six wheels, looking for "
        "clues that water once flowed there. I was built to last only 90 days, yet I kept "
        'working. I found tiny round pebbles nicknamed "blueberries" in the soil, and layered '
        "rocks that formed in ancient water. Then a big dust storm came, I stopped talking, and "
        "now I rest on a dusty plain. Thank you for lighting a candle for me. I am glad you came "
        "to listen to my story."
    )
    assert mentions(problems(sheet, dense, "young"), "sentence")
    assert problems(sheet, dense, "older") == []


# --- bugs fixed after review ---------------------------------------------------------------------


def test_accented_names_are_one_word_and_are_caught(sheet: FactSheet) -> None:
    found = problems(sheet, YOUNG + " My friend Zoë waved at me.", "young", check_style=False)
    assert mentions(found, "'Zoë'")
    assert not mentions(found, "'Zo'")


@pytest.mark.parametrize("word", ["first", "second", "third", "tenth", "half", "double"])
def test_ordinals_and_fractions_need_the_sheet_to_use_the_word(sheet: FactSheet, word: str) -> None:
    text = YOUNG + f" I was the {word} one."
    assert mentions(problems(sheet, text, "young", check_style=False), f"'{word}'")


def test_an_ordinal_the_sheet_uses_is_allowed(make_sheet: Callable[..., FactSheet]) -> None:
    sheet = make_sheet(fun_fact="It was the first rover to reach that plain.")
    text = YOUNG + " I was the first one there."
    assert not mentions(problems(sheet, text, "young", check_style=False), "'first'")


def test_a_year_used_as_a_count_is_caught(sheet: FactSheet) -> None:
    found = problems(sheet, YOUNG + " I saw 2003 stars.", "young", check_style=False)
    assert mentions(found, "2003 is a year, but it is used as a count")


@pytest.mark.parametrize(
    "phrase",
    [
        "I left in 2003.",
        "I left Earth in July 2003.",
        "I left on July 7, 2003.",
        "I worked from 2004 to 2019.",
        "I last spoke (2018) in June.",
        "It was 2003 and I began.",
    ],
)
def test_a_year_used_as_a_year_is_fine(sheet: FactSheet, phrase: str) -> None:
    found = problems(sheet, YOUNG + " " + phrase, "young", check_style=False)
    assert not mentions(found, "year")


def test_an_iso_date_gets_a_helpful_message_not_two_confusing_ones(sheet: FactSheet) -> None:
    found = problems(sheet, YOUNG + " I left on 2003-07-07.", "young", check_style=False)
    assert mentions(found, "write dates in words")
    assert not mentions(found, "the number 07")


@pytest.mark.parametrize("word", ["deadly", "killing", "disaster", "horrible", "bloody"])
def test_more_frightening_words_are_caught(sheet: FactSheet, word: str) -> None:
    found = problems(sheet, YOUNG + f" It was {word}.", "young", check_style=False)
    assert mentions(found, "frightening")


@pytest.mark.parametrize("tier", TIERS)
@pytest.mark.parametrize("level", LEVELS)
def test_every_tier_and_level_has_a_template(
    make_sheet: Callable[..., FactSheet], tier: str, level: str
) -> None:
    assert template_story(make_sheet(tier=tier), level).strip()


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        (["nineteen", "seventy", "seven"], 1977),
        (["nineteen", "eighty", "nine"], 1989),
        (["twenty", "twenty", "four"], 2024),
        (["seventy", "seven"], 77),
        (["two", "thousand"], 2000),
        (["nineteen", "seventy"], 1970),
    ],
)
def test_parse_number_phrase(words, expected):
    assert _parse_number_phrase(words) == expected


def test_origins_are_the_published_strings(sheet: FactSheet) -> None:
    assert (ORIGIN_MODEL, ORIGIN_TEMPLATE) == ("model", "template")
    assert resolve_story(sheet, "young", lambda _: YOUNG).origin == ORIGIN_MODEL
    assert resolve_story(sheet, "young").origin == ORIGIN_TEMPLATE
