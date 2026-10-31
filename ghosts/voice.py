"""Prompts and story generation for the ghost voices (build stage 3).

This module only asks the model for a draft. It does not decide whether the draft is true:
``verify.resolve_story`` checks every draft against the fact sheet before it is published.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from ghosts.llm import TextGenerator
from ghosts.schema import FactSheet
from ghosts.verify import MONTHS, SPECS

BASE_SEED = 7  # fixed so a rebuild with the same model asks the same question the same way

SYSTEM = (
    "You write short, gentle memorial stories for young readers about spacecraft, told in "
    "the voice of each machine's friendly ghost. You only ever use the facts you are given."
)

_TIER_NOTES = {
    "resting": "It has finished its mission and is resting now. Be peaceful and grateful.",
    "restless": "It is still out there, still travelling or working. Be hopeful and curious.",
    "lost": "Contact with it was lost. Be tender and kind. Never frightening, never blaming.",
}

_LEVEL_GUIDES = {
    "young": (
        "Use very short sentences of about 8 words, simple everyday words, and one idea per "
        "sentence. Explain any science word in a few simple words. Be warm and playful."
    ),
    "older": (
        "Use clear, reflective language and precise words. A science term is fine if you "
        "briefly explain it. Be thoughtful and moving, never babyish."
    ),
}

_RULES = (
    "Use ONLY the facts listed below. Do not add any number, date, name, place, cause or quote "
    "that is not listed. If you are unsure of something, leave it out.",
    "Do not use quotation marks. Do not write words that a real person said.",
    "Speak as the machine's gentle ghost, in the first person (I). Be warm and calm. Never "
    "frighten the reader, and do not describe anything graphic.",
    "Do not say that any agency approves of or supports this story.",
    "Write one plain-text paragraph: no title, no list, no markdown, no emoji.",
)


def _date_rule(sheet: FactSheet) -> str:
    """Tell the model to write dates in words, with an example from this sheet's own launch."""
    rule = "Write dates in words, never as numbers joined by hyphens."
    parts = sheet.launched.split("-")
    if len(parts) == 3:
        year, month, day = (int(p) for p in parts)
        rule += f" For example, {sheet.launched} is written {MONTHS[month - 1]} {day}, {year}."
    return rule


def _word_range(level: str) -> str:
    spec = SPECS[level]
    return f"Write between {spec.min_words + 10} and {spec.max_words - 10} words."


def _fact_lines(sheet: FactSheet) -> list[str]:
    lines = [f"Name: {sheet.name}", f"Where: {sheet.body}", f"Launched: {sheet.launched}"]
    for label, value in (("Arrived", sheet.arrived), ("Ended", sheet.ended)):
        if value:
            lines.append(f"{label}: {value}")
    if sheet.last_contact:
        lines.append(f"Last contact: {sheet.last_contact}")
    lines += [f"Status: {sheet.status}", f"Purpose: {sheet.purpose}", "What it found or did:"]
    lines += [f"- {item}" for item in sheet.discoveries]
    lines.append("How it worked:")
    lines += [f"- {item}" for item in sheet.how_it_worked]
    lines.append(f"A fun fact: {sheet.fun_fact}")
    return lines


def build_prompt(sheet: FactSheet, level: str, problems: Sequence[str] = ()) -> str:
    """The full prompt for one story; ``problems`` lists what was wrong with the last draft."""
    if level not in SPECS:
        raise ValueError(f"unknown reading level {level!r}; use one of {', '.join(SPECS)}")
    sections = [
        f"Write a story about {sheet.name} for the altar.",
        f"Reading level: ages {SPECS[level].ages}. {_LEVEL_GUIDES[level]}",
        _word_range(level),
        _TIER_NOTES[sheet.tier],
        "Rules:",
        *[f"{i}. {rule}" for i, rule in enumerate((*_RULES, _date_rule(sheet)), start=1)],
        "Facts:",
        *_fact_lines(sheet),
    ]
    if problems:
        sections += ["", "Your last draft was rejected for these reasons:"]
        sections += [f"- {problem}" for problem in problems]
        sections.append("Fix every reason and write the story again.")
    sections += ["", "Output only the story."]
    return "\n".join(sections)


_FENCE_RE = re.compile(r"^```[a-z]*\s*|\s*```$", re.IGNORECASE)
_LABEL_RE = re.compile(r"^\s*(?:ghost\s+)?story\s*:\s*", re.IGNORECASE)


def _unwrap_quotes(text: str) -> str:
    for opening, closing in (('"', '"'), ("“", "”")):
        inner = text[1:-1]
        wrapped = len(text) > 1 and text[0] == opening and text[-1] == closing
        if wrapped and opening not in inner and closing not in inner:
            return inner.strip()
    return text


def clean_story(raw: str) -> str:
    """Remove the wrapping a model often adds: code fences, a 'Story:' label, outer quotes."""
    text = _FENCE_RE.sub("", raw.strip())
    text = _LABEL_RE.sub("", text)
    return _unwrap_quotes(" ".join(text.split()))


def generate_story(
    client: TextGenerator,
    sheet: FactSheet,
    level: str,
    problems: Sequence[str] = (),
    *,
    seed: int = BASE_SEED,
) -> str:
    """Ask the model for one draft. The retry (``problems`` given) uses the next seed."""
    prompt = build_prompt(sheet, level, problems)
    return clean_story(client.generate(prompt, system=SYSTEM, seed=seed + (1 if problems else 0)))
