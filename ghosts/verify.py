"""Check generated stories against their fact sheet, and fall back to templates (stage 3).

The checks are deliberately mechanical. They cannot prove a story is true, but they catch the
mistakes a language model makes most often: new numbers, dates, names and quotes, frightening
words, markup, and wandering far from the sheet. A story that fails is retried once, and if it
fails again the deterministic template, built only from the sheet's own sentences, is used.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ghosts.llm import LLMError
from ghosts.schema import FactSheet

log = logging.getLogger(__name__)


ORIGIN_MODEL = "model"  # the model's draft passed verification
ORIGIN_TEMPLATE = "template"  # the deterministic fallback was used


@dataclass(frozen=True)
class LevelSpec:
    """Who a story is for, and how long and how simple it should be."""

    ages: str
    min_words: int
    max_words: int
    avg_sentence_words: float
    max_sentence_words: int


SPECS = {
    "young": LevelSpec(
        ages="7 to 9", min_words=30, max_words=80, avg_sentence_words=9.0, max_sentence_words=15
    ),
    "older": LevelSpec(
        ages="14 to 18", min_words=80, max_words=200, avg_sentence_words=22.0, max_sentence_words=40
    ),
}
LEVELS = tuple(SPECS)

MIN_GROUNDED = 0.5  # share of content words that must come from the fact sheet
_MIN_CONTENT_WORDS = 10  # shorter stories are not judged on grounding

_WORD_RE = re.compile(r"[^\W\d_]+")  # letters of any language, so "Zoë" is one word
_NUMBER_RE = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?\b")
_YEAR_RE = re.compile(r"[12]\d{3}")
_MARKUP_RE = re.compile(r"[<>*#`\[\]{}]|https?:|www\.")
_QUOTE_RES = (re.compile(r'"([^"]*)"'), re.compile(r"“([^”]*)”"))
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_ALL_MONTHS = "|".join(MONTHS)
_OTHER_MONTHS = "|".join(m for m in MONTHS if m != "May")
_MONTH_DAY_RE = re.compile(rf"\b({_ALL_MONTHS})\s+(\d{{1,2}})\b")
# A year must follow a word or mark that introduces one: "in 1979", "July, 2003", "(1999)".
_YEAR_CONTEXT_RE = re.compile(
    rf"(?:\b(?:in|of|since|until|by|from|to|during|before|after|around|and|or|was|late|early|mid)"
    rf"|\b(?:{_ALL_MONTHS})|[,(])\s*$",
    re.IGNORECASE,
)
# "May" is also a verb, so it only counts as a month when a number follows it.
_MONTH_RE = re.compile(rf"\b(?:{_OTHER_MONTHS})\b|\bMay(?=\s+\d)")

# Capitalised words a story may use even if the sheet does not: the speaker, the sky, and
# ordinary words that open a sentence ("The Sun was warm").
_NAME_ALLOWED = frozenset(
    "i the a an my our we you it this that then now and but so when once earth sun moon".split()
)

# Spelled-out numbers, which would otherwise slip past the digit check. "one" is left out
# because ordinary phrases such as "no one" and "one day" use it. None means "a vague amount".
_NUMBER_WORDS: dict[str, int | None] = {
    word: value
    for value, word in enumerate(
        "two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
        "sixteen seventeen eighteen nineteen twenty".split(),
        start=2,
    )
}
_NUMBER_WORDS.update(
    {
        **dict.fromkeys(
            "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth "
            "twentieth hundredth thousandth half quarter double triple".split()
        ),
        "thirty": 30,
        "forty": 40,
        "fifty": 50,
        "sixty": 60,
        "seventy": 70,
        "eighty": 80,
        "ninety": 90,
        "hundred": 100,
        "thousand": 1000,
        "million": 1_000_000,
        "billion": 1_000_000_000,
        "twice": 2,
        "dozen": 12,
        "hundreds": None,
        "thousands": None,
        "millions": None,
        "billions": None,
        "dozens": None,
    }
)

# Words that would frighten a child. Allowed only if the verified sheet itself uses the word.
_SCARY = frozenset(
    "dead deadly death die dies died dying kill kills killed killing killer crash crashes "
    "crashed crashing scary terrifying terrified horror horrible horrific horrifying scream "
    "screams screamed screaming blood bloody doom doomed tragic tragedy disaster murder".split()
)

# Function words and ofrenda-theme words that need no support from the fact sheet.
_FILLER = frozenset(
    "that this with from they them were have been will would could should there their where "
    "which when what then than into over just also only still some many much very even back "
    "away other about after before while because though through every each both more most such "
    "like felt feel always never come came here your you our ours ghost ghosts story candle "
    "candles light glow glowing gentle gently soft softly quiet quietly warm warmly home thank "
    "thanks friend friends little small wonder dream dreams remember remembered remembering "
    "remembers memory memories altar night stars star".split()
)
_SUFFIXES = ("ing", "ed", "es", "ly", "s")


def _stem(word: str) -> str:
    """A crude stem, enough to match 'travelling' with 'travelled' and 'rocks' with 'rock'."""
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            break
    word = word.rstrip("e")
    if len(word) > 3 and word[-1] == word[-2] and word[-1] not in "aeiou":
        word = word[:-1]
    return word


_FILLER_STEMS = frozenset(_stem(w) for w in _FILLER)


@dataclass(frozen=True)
class Verification:
    """The outcome of checking one story; ``problems`` is empty when it passed."""

    problems: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclass(frozen=True)
class Story:
    """The story that will be published, and how it was obtained."""

    text: str
    origin: str  # ORIGIN_MODEL or ORIGIN_TEMPLATE
    attempts: int  # how many model drafts were checked
    problems: tuple[str, ...]  # why the last rejected draft failed; empty if none was rejected


@dataclass(frozen=True)
class Facts:
    """Everything a story is allowed to draw on, taken from one fact sheet."""

    text: str
    words: frozenset[str]
    stems: frozenset[str]
    numbers: frozenset[str]
    months: frozenset[str]
    days: frozenset[str]  # exact dates the story may write, as "July 7"


def _norm_number(token: str) -> str:
    token = token.replace(",", "")
    return token if "." in token else str(int(token))


def _month_names(text: str) -> set[str]:
    return {m.group(0) for m in _MONTH_RE.finditer(text)}


def _month_days(text: str) -> set[str]:
    return {f"{month} {int(day)}" for month, day in _MONTH_DAY_RE.findall(text)}


def _date_facts(dates: Sequence[str]) -> tuple[set[str], set[str], set[str]]:
    """The years, month names and exact "Month day" dates written in the date fields."""
    years: set[str] = set()
    months: set[str] = set()
    days: set[str] = set()
    for date_text in dates:
        pieces = date_text.split("-")
        years.add(str(int(pieces[0])))
        if len(pieces) > 1:
            months.add(MONTHS[int(pieces[1]) - 1])
        if len(pieces) > 2:
            days.add(f"{MONTHS[int(pieces[1]) - 1]} {int(pieces[2])}")
    return years, months, days


def facts_for(sheet: FactSheet) -> Facts:
    """Collect the words, numbers, months, dates and wording a story may use.

    From the date fields only the year, the month name and the exact "Month day" are taken, so
    a date such as 2003-07-07 does not make a bare "7" acceptable anywhere in a story.
    """
    dates = [d for d in (sheet.launched, sheet.arrived, sheet.ended, sheet.last_contact) if d]
    parts = [sheet.name, sheet.agency, sheet.status, sheet.purpose, sheet.fun_fact]
    parts += [*sheet.discoveries, *sheet.how_it_worked]
    text = " ".join(parts)
    words = {w.lower() for w in _WORD_RE.findall(f"{text} {sheet.body}")}
    years, date_months, date_days = _date_facts(dates)
    numbers = {_norm_number(n) for n in _NUMBER_RE.findall(text)} | years
    return Facts(
        text=" ".join(text.lower().split()),
        words=frozenset(words),
        stems=frozenset(_stem(w) for w in words),
        numbers=frozenset(numbers),
        months=frozenset(_month_names(text) | date_months),
        days=frozenset(_month_days(text) | date_days),
    )


def _markup_problems(text: str) -> list[str]:
    if _MARKUP_RE.search(text):
        return ["contains markup, a link, or symbols that must not appear"]
    return []


def _parse_number_phrase(words: list[str]) -> int | None:
    """Convert a sequence of number words into an integer."""

    values = [_NUMBER_WORDS.get(word) for word in words]

    if not words or any(value is None for value in values):
        return None

    # Spoken years: nineteen seventy-seven -> 1977
    if (
        len(words) in (2, 3)
        and words[0] in {"nineteen", "twenty"}
        and words[1]
        in {
            "twenty",
            "thirty",
            "forty",
            "fifty",
            "sixty",
            "seventy",
            "eighty",
            "ninety",
        }
    ):
        first = int(_NUMBER_WORDS[words[0]])
        second = int(_NUMBER_WORDS[words[1]])

        if len(words) == 3:
            if words[2] not in {
                "two",
                "three",
                "four",
                "five",
                "six",
                "seven",
                "eight",
                "nine",
            }:
                return None
            second += int(_NUMBER_WORDS[words[2]])

        return first * 100 + second
    # Ordinary numbers: seventy-seven -> 77
    total = 0
    current = 0

    for value in values:
        value = int(value)

        if value >= 100:
            current = max(current, 1) * value
            if value >= 1000:
                total += current
                current = 0
        else:
            current += value

    return total + current


def _number_word_problems(text: str, facts: Facts) -> list[str]:
    problems: list[str] = []
    tokens = _WORD_RE.findall(text.lower())
    i = 0

    while i < len(tokens):
        word = tokens[i]

        if word not in _NUMBER_WORDS:
            i += 1
            continue

        # Allow number/ordinal words explicitly present in the fact sheet.
        # This covers phrases such as "six wheels" and "first rover".
        if word in facts.words:
            i += 1
            continue

        start = i
        while i < len(tokens) and tokens[i] in _NUMBER_WORDS:
            # Stop before a word explicitly supported by the sheet.
            if tokens[i] in facts.words:
                break
            i += 1

        phrase = tokens[start:i]

        if not phrase:
            i += 1
            continue

        value = _parse_number_phrase(phrase)

        if value is None or str(value) not in facts.numbers:
            problems.append(
                f"the number phrase '{' '.join(phrase)}' is not supported by the fact sheet"
            )

    return problems


def _number_problems(text: str, facts: Facts) -> list[str]:
    problems: list[str] = []
    if _ISO_DATE_RE.search(text):
        problems.append("write dates in words (for example July 7, 2003), not as 2003-07-07")
        text = _ISO_DATE_RE.sub(" ", text)
    problems += [
        f"the date {day} is not in the fact sheet" for day in sorted(_month_days(text) - facts.days)
    ]
    plain = _MONTH_DAY_RE.sub(r"\1", text)  # "July 7" was judged above; judge the rest
    for match in _NUMBER_RE.finditer(plain):
        token = match.group()
        if _norm_number(token) not in facts.numbers:
            problems.append(f"the number {token} is not in the fact sheet")
        elif _YEAR_RE.fullmatch(token) and not _YEAR_CONTEXT_RE.search(plain[: match.start()]):
            problems.append(f"{token} is a year, but it is used as a count")
    return problems + _number_word_problems(text, facts)


def _month_problems(text: str, facts: Facts) -> list[str]:
    return [
        f"the month {month} is not in the fact sheet"
        for month in sorted(_month_names(text) - facts.months)
    ]


def _split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_RE.split(text.strip()) if s.strip()]


def _name_problems(text: str, facts: Facts) -> list[str]:
    """Flag capitalised words (likely names) that the sheet never mentions.

    A sentence's first word is skipped unless the next word is capitalised too, because
    ordinary words are capitalised there. That is a known gap: an invented one-word name that
    opens a sentence (``Spirit rolled on``) is not caught.
    """
    months = {m.lower() for m in MONTHS}
    problems: list[str] = []
    for sentence in _split_sentences(text):
        tokens = _WORD_RE.findall(sentence)
        for i, token in enumerate(tokens):
            if not token[0].isupper():
                continue
            if i == 0 and not (len(tokens) > 1 and tokens[1][0].isupper()):
                continue
            lowered = token.lower()
            if lowered in facts.words or lowered in _NAME_ALLOWED or lowered in months:
                continue
            problems.append(f"the name '{token}' is not in the fact sheet")
    return problems


def _quote_problems(text: str, facts: Facts) -> list[str]:
    """Quoted words must be exact phrases from the sheet; nothing may be put in anyone's mouth."""
    problems: list[str] = []
    if text.count('"') % 2:
        problems.append("has an unmatched quotation mark")
    for pattern in _QUOTE_RES:
        for inner in pattern.findall(text):
            phrase = " ".join(inner.lower().split()).strip(" .,!?;:")
            if phrase not in facts.text:
                problems.append(f'the quotation "{inner}" is not wording from the fact sheet')
    return problems


def _tone_problems(text: str, facts: Facts) -> list[str]:
    found = {w for w in _WORD_RE.findall(text.lower()) if w in _SCARY and w not in facts.words}
    return [f"the word '{word}' is too frightening for this audience" for word in sorted(found)]


def _grounding_problems(text: str, facts: Facts) -> list[str]:
    content = [w for w in (x.lower() for x in _WORD_RE.findall(text)) if len(w) >= 4]
    content = [w for w in content if _stem(w) not in _FILLER_STEMS]
    if len(content) < _MIN_CONTENT_WORDS:
        return []
    ungrounded = [w for w in content if _stem(w) not in facts.stems]
    if 1 - len(ungrounded) / len(content) >= MIN_GROUNDED:
        return []
    examples = ", ".join(sorted(set(ungrounded))[:8])
    return [f"too many words that are not in the fact sheet (for example: {examples})"]


def _style_problems(text: str, spec: LevelSpec) -> list[str]:
    problems: list[str] = []
    count = len(text.split())
    if count < spec.min_words:
        problems.append(f"too short: {count} words (at least {spec.min_words})")
    if count > spec.max_words:
        problems.append(f"too long: {count} words (at most {spec.max_words})")
    lengths = [len(s.split()) for s in _split_sentences(text)] or [0]
    average = sum(lengths) / len(lengths)
    if average > spec.avg_sentence_words:
        limit = spec.avg_sentence_words
        problems.append(f"sentences average {average:.0f} words (limit {limit:.0f})")
    if max(lengths) > spec.max_sentence_words:
        problems.append(f"a sentence has {max(lengths)} words (limit {spec.max_sentence_words})")
    return problems


def _spec(level: str) -> LevelSpec:
    if level not in SPECS:
        raise ValueError(f"unknown reading level {level!r}; use one of {', '.join(LEVELS)}")
    return SPECS[level]


def check_story(
    sheet: FactSheet, text: str, level: str, *, check_style: bool = True
) -> Verification:
    """Check one story against its sheet. ``check_style`` adds the length and reading limits."""
    spec = _spec(level)
    if not text.strip():
        return Verification(("the story is empty",))
    facts = facts_for(sheet)
    problems = [
        *_markup_problems(text),
        *_number_problems(text, facts),
        *_month_problems(text, facts),
        *_name_problems(text, facts),
        *_quote_problems(text, facts),
        *_tone_problems(text, facts),
        *_grounding_problems(text, facts),
    ]
    if check_style:
        problems += _style_problems(text, spec)
    return Verification(tuple(dict.fromkeys(problems)))


# --- the deterministic fallback ------------------------------------------------------------


def _ensure_stop(sentence: str) -> str:
    sentence = sentence.strip()
    return sentence if sentence[-1] in ".!?" else sentence + "."


def _first_sentence(text: str) -> str:
    return _ensure_stop(_SENTENCE_RE.split(text.strip(), maxsplit=1)[0])


def _mission_sentence(purpose: str) -> str:
    first = _first_sentence(purpose)
    return "Its mission was to " + first[3:] if first.startswith("To ") else first


def _shortest(items: Sequence[str], count: int) -> list[str]:
    """The ``count`` shortest items (earlier wins a tie), kept in their original order."""
    ranked = sorted(range(len(items)), key=lambda i: (len(items[i].split()), i))
    return [_ensure_stop(items[i]) for i in sorted(ranked[:count])]


def _closing(sheet: FactSheet) -> str:
    return {
        "resting": f"We light a candle to remember {sheet.name}.",
        "restless": f"We light a candle to keep {sheet.name} company.",
        "lost": f"We light a candle so {sheet.name} is not forgotten.",
    }[sheet.tier]


def template_story(sheet: FactSheet, level: str) -> str:
    """Build a story only from the sheet's own sentences; the same input gives the same text.

    It is a safe fallback, not a polished one: the sentences are the sheet's, so their reading
    level is the sheet's too. The young version picks the shortest sentences to stay readable.
    """
    _spec(level)
    parts = [f"{sheet.name} is remembered here."]
    if level == "young":
        parts.append(_first_sentence(sheet.status))
        parts += _shortest([*sheet.discoveries, sheet.fun_fact], 2)
    else:
        parts += [
            _ensure_stop(sheet.status),
            _mission_sentence(sheet.purpose),
            _ensure_stop(sheet.discoveries[0]),
            _ensure_stop(sheet.fun_fact),
        ]
    parts.append(_closing(sheet))
    return " ".join(parts)


def resolve_story(
    sheet: FactSheet,
    level: str,
    generate: Callable[[Sequence[str]], str] | None = None,
    *,
    retries: int = 1,
) -> Story:
    """Get a verified story: the model's if it passes, else one retry, else the template.

    ``generate`` receives the problems found in the previous draft (empty on the first call).
    With no generator the template is used straight away. If the model cannot be reached the
    template is used without a retry, since retrying would only wait for another timeout.
    """
    problems: tuple[str, ...] = ()
    attempts = 0
    if generate is not None:
        for _ in range(1 + retries):
            try:
                text = generate(problems)
            except LLMError as exc:
                log.warning("%s/%s: model unavailable (%s)", sheet.id, level, exc)
                problems = (f"model unavailable: {exc}",)
                break
            attempts += 1
            verdict = check_story(sheet, text.strip(), level)
            if verdict.ok:
                return Story(text.strip(), ORIGIN_MODEL, attempts, ())
            problems = verdict.problems
            log.info("%s/%s: draft %d rejected: %s", sheet.id, level, attempts, "; ".join(problems))
    return Story(template_story(sheet, level), ORIGIN_TEMPLATE, attempts, problems)
