"""Build ``site/generated/machines.json`` from verified fact sheets (build stage 3).

    python -m ghosts.build --model <ollama-model>   # local Gemma voices, verified, with fallback
    python -m ghosts.build --no-llm                 # deterministic templates only

Only sheets a human has marked verified are built. This module reads fact sheets and never
writes them, so it cannot mark anything verified.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from functools import partial
from pathlib import Path
from typing import Any

from ghosts.llm import (
    DEFAULT_HOST,
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    DEFAULT_TIMEOUT,
    LLMError,
    OllamaClient,
    TextGenerator,
)
from ghosts.schema import TIERS, FactSheet, load_buildable
from ghosts.verify import LEVELS, ORIGIN_MODEL, ORIGIN_TEMPLATE, Story, resolve_story
from ghosts.voice import BASE_SEED, generate_story

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
# Resolved from this file, not the current directory, so the build works from anywhere.
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = ROOT / "data" / "machines"
DEFAULT_OUT = ROOT / "site" / "generated" / "machines.json"
DEFAULT_RETRIES = 1

Teller = Callable[[FactSheet, str], Story]


class BuildError(RuntimeError):
    """The site data cannot be built; nothing is written."""


@dataclass(frozen=True)
class BuildReport:
    path: Path
    machines: int
    model_stories: int
    template_stories: int
    excluded: tuple[str, ...]


def template_teller(sheet: FactSheet, level: str) -> Story:
    """Tell every story from the deterministic template (the ``--no-llm`` path)."""
    return resolve_story(sheet, level)


def llm_teller(
    client: TextGenerator, *, seed: int = BASE_SEED, retries: int = DEFAULT_RETRIES
) -> Teller:
    """Tell stories with the model: verified, retried ``retries`` times, then templated."""

    def tell(sheet: FactSheet, level: str) -> Story:
        draft = partial(generate_story, client, sheet, level, seed=seed)
        return resolve_story(sheet, level, draft, retries=retries)

    return tell


def _plain(value: Any) -> Any:
    """Turn tuples into lists so the structure is exactly what JSON will hold."""
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    return value


def machine_entry(sheet: FactSheet, stories: dict[str, Story]) -> dict[str, Any]:
    """One machine for the site: the sheet's facts, its sources, and its stories.

    ``verified_by`` is left out on purpose: the site needs to know the facts were checked by a
    person, not who that person was.
    """
    entry = _plain(asdict(sheet))
    del entry["verified_by"]
    entry["stories"] = {
        level: {"text": story.text, "origin": story.origin} for level, story in stories.items()
    }
    return entry


def _order_key(sheet: FactSheet) -> tuple[int, str]:
    return (TIERS.index(sheet.tier), sheet.id)


def build_document(
    sheets: tuple[FactSheet, ...], tell: Teller, *, model: str | None
) -> tuple[dict[str, Any], list[Story]]:
    """Tell every story and assemble the document. Returns it with every story told."""
    machines: list[dict[str, Any]] = []
    told: list[Story] = []
    for sheet in sorted(sheets, key=_order_key):
        if not sheet.verified:
            raise BuildError(f"{sheet.id} is not verified; refusing to publish it")
        stories = {level: tell(sheet, level) for level in LEVELS}
        told += stories.values()
        machines.append(machine_entry(sheet, stories))
    document = {
        "schema_version": SCHEMA_VERSION,
        "generator": {"model": model},
        "machines": machines,
    }
    return document, told


def write_document(document: dict[str, Any], path: Path) -> None:
    """Write the JSON atomically, so a failed build never leaves half a file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(path.name + ".tmp")
    scratch.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(scratch, path)


def build_site(data_dir: Path, out_path: Path, tell: Teller, *, model: str | None) -> BuildReport:
    """Load the verified sheets, tell their stories, and write the site data."""
    result = load_buildable(data_dir)
    malformed = [e.filename for e in result.excluded if e.malformed]
    if malformed:
        raise BuildError(f"malformed fact sheets (fix them first): {', '.join(malformed)}")
    if not result.sheets:
        raise BuildError(f"no verified fact sheets found in {data_dir}")
    document, told = build_document(result.sheets, tell, model=model)
    write_document(document, out_path)
    return BuildReport(
        path=out_path,
        machines=len(result.sheets),
        model_stories=sum(1 for s in told if s.origin == ORIGIN_MODEL),
        template_stories=sum(1 for s in told if s.origin == ORIGIN_TEMPLATE),
        excluded=tuple(e.filename for e in result.excluded),
    )


def _non_negative_int(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return value


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return value


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build site/generated/machines.json.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--model", help="local Ollama model that writes the ghost voices")
    mode.add_argument("--no-llm", action="store_true", help="use deterministic templates only")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="fact sheet directory")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output JSON path")
    parser.add_argument("--host", default=DEFAULT_HOST, help="local Ollama address")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="seconds per call")
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--max-tokens", type=_positive_int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--seed", type=int, default=BASE_SEED, help="base seed for the model")
    parser.add_argument(
        "--retries", type=_non_negative_int, default=DEFAULT_RETRIES, help="extra tries per story"
    )
    return parser.parse_args(argv)


def _make_teller(args: argparse.Namespace) -> tuple[Teller, str | None]:
    if args.no_llm:
        return template_teller, None
    try:
        client = OllamaClient(
            args.model,
            host=args.host,
            timeout=args.timeout,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
    except ValueError as exc:  # a bad host or model name: a usage error, not a bug
        raise BuildError(str(exc)) from exc
    client.check_ready()
    return llm_teller(client, seed=args.seed, retries=args.retries), args.model


def main(argv: list[str] | None = None) -> int:
    """Build the site data; exit 1 if it cannot be built (nothing is written then)."""
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    try:
        tell, model = _make_teller(args)
        report = build_site(args.data, args.out, tell, model=model)
    except (BuildError, LLMError) as exc:
        log.error("build failed: %s", exc)
        return 1
    log.info(
        "wrote %s: %d machines, %d model stories, %d template stories",
        report.path,
        report.machines,
        report.model_stories,
        report.template_stories,
    )
    for name in report.excluded:
        log.info("  left out %s (not verified)", name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
