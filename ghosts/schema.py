"""Fact sheet schema and validation (build stage 2).

Fact sheets are the only source of truth. This module checks that a sheet is well formed and
decides whether it may enter the build. It never sets ``verified``: a human does that after
checking every claim against the listed sources.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger(__name__)

TIERS = ("resting", "restless", "lost")
BODIES = ("moon", "mars", "deep space")

# Every key must be present. Nullable ones may hold null (still travelling, never arrived, ...).
FIELDS = (
    "id",
    "name",
    "agency",
    "tier",
    "body",
    "launched",
    "arrived",
    "ended",
    "status",
    "purpose",
    "discoveries",
    "how_it_worked",
    "last_contact",
    "fun_fact",
    "sources",
    "verified",
    "verified_by",
)
TEXT_FIELDS = ("id", "name", "agency", "tier", "body", "status", "purpose", "fun_fact")
NULLABLE_DATE_FIELDS = ("arrived", "ended", "last_contact")
LIST_FIELDS = ("discoveries", "how_it_worked")

_ID_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_PARTIAL_DATE_RE = re.compile(r"\d{4}(?:-\d{2}(?:-\d{2})?)?")
_NOT_VERIFIED = "not verified by a human yet (verified is false)"


class SchemaError(ValueError):
    """Raised when a fact sheet fails validation; ``issues`` lists every problem found."""

    def __init__(self, issues: list[str]) -> None:
        super().__init__("; ".join(issues))
        self.issues = tuple(issues)


@dataclass(frozen=True)
class Source:
    title: str
    url: str
    accessed: str


@dataclass(frozen=True)
class FactSheet:
    id: str
    name: str
    agency: str
    tier: str
    body: str
    launched: str
    arrived: str | None
    ended: str | None
    status: str
    purpose: str
    discoveries: tuple[str, ...]
    how_it_worked: tuple[str, ...]
    last_contact: str | None
    fun_fact: str
    sources: tuple[Source, ...]
    verified: bool
    verified_by: str | None


@dataclass(frozen=True)
class Excluded:
    """A file left out of the build, with the human-readable reasons."""

    filename: str
    reasons: tuple[str, ...]
    malformed: bool


@dataclass(frozen=True)
class LoadResult:
    sheets: tuple[FactSheet, ...]
    excluded: tuple[Excluded, ...]


def is_valid_partial_date(value: str) -> bool:
    """True for a real calendar date written as YYYY, YYYY-MM, or YYYY-MM-DD."""
    if not _PARTIAL_DATE_RE.fullmatch(value):
        return False
    parts = [int(p) for p in value.split("-")]
    try:
        date(parts[0], parts[1] if len(parts) > 1 else 1, parts[2] if len(parts) > 2 else 1)
    except ValueError:
        return False
    return True


def _is_nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_http_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _check_text(raw: dict[str, Any], key: str, issues: list[str]) -> None:
    if key in raw and not _is_nonempty_str(raw[key]):
        issues.append(f"{key}: must be a non-empty string")


def _check_date(raw: dict[str, Any], key: str, issues: list[str], *, nullable: bool) -> None:
    if key not in raw:
        return
    value = raw[key]
    if value is None and nullable:
        return
    if not isinstance(value, str) or not is_valid_partial_date(value):
        suffix = " or null" if nullable else ""
        issues.append(f"{key}: must be a real date as YYYY, YYYY-MM, or YYYY-MM-DD{suffix}")


def _check_text_list(raw: dict[str, Any], key: str, issues: list[str]) -> None:
    if key not in raw:
        return
    value = raw[key]
    if not isinstance(value, list) or not value:
        issues.append(f"{key}: must be a non-empty list of strings")
    elif not all(_is_nonempty_str(item) for item in value):
        issues.append(f"{key}: every entry must be a non-empty string")


def _check_sources(raw: dict[str, Any], issues: list[str]) -> None:
    if "sources" not in raw:
        return
    sources = raw["sources"]
    if not isinstance(sources, list) or not sources:
        issues.append("sources: at least one source is required")
        return
    for i, src in enumerate(sources):
        where = f"sources[{i}]"
        if not isinstance(src, dict):
            issues.append(f"{where}: must be an object with title, url, accessed")
            continue
        issues += [
            f"{where}: unknown field: {k}" for k in sorted(set(src) - {"title", "url", "accessed"})
        ]
        if not _is_nonempty_str(src.get("title")):
            issues.append(f"{where}.title: must be a non-empty string")
        if not _is_http_url(src.get("url")):
            issues.append(f"{where}.url: must be an http(s) URL")
        accessed = src.get("accessed")
        try:
            if not isinstance(accessed, str):
                raise ValueError
            date.fromisoformat(accessed)
        except ValueError:
            issues.append(f"{where}.accessed: must be a full date as YYYY-MM-DD")


def validate(raw: Any, *, expected_id: str | None = None) -> list[str]:
    """Return every problem found in a parsed fact sheet; an empty list means it is well formed.

    ``expected_id`` is the filename stem, so a renamed or copy-pasted sheet is caught early.
    """
    if not isinstance(raw, dict):
        return ["fact sheet must be a JSON object"]

    issues: list[str] = []
    issues += [f"unknown field: {key}" for key in sorted(set(raw) - set(FIELDS))]
    issues += [f"missing field: {key}" for key in FIELDS if key not in raw]

    for key in TEXT_FIELDS:
        _check_text(raw, key, issues)
    for key in LIST_FIELDS:
        _check_text_list(raw, key, issues)
    _check_date(raw, "launched", issues, nullable=False)
    for key in NULLABLE_DATE_FIELDS:
        _check_date(raw, key, issues, nullable=True)
    _check_sources(raw, issues)

    sheet_id = raw.get("id")
    if _is_nonempty_str(sheet_id):
        if not _ID_RE.fullmatch(sheet_id):
            issues.append("id: use lowercase letters, digits, and single hyphens only")
        if expected_id is not None and sheet_id != expected_id:
            issues.append(f"id: '{sheet_id}' does not match filename '{expected_id}'")

    tier = raw.get("tier")
    if _is_nonempty_str(tier) and tier not in TIERS:
        issues.append(f"tier: must be one of {', '.join(TIERS)}")
    body = raw.get("body")
    if _is_nonempty_str(body) and body not in BODIES:
        issues.append(f"body: must be one of {', '.join(BODIES)}")
    if tier == "resting" and "ended" in raw and raw["ended"] is None:
        issues.append("ended: a resting machine has finished its mission, so a date is required")

    if "verified" in raw:
        verified = raw["verified"]
        verified_by = raw.get("verified_by")
        if not isinstance(verified, bool):
            issues.append("verified: must be true or false")
        elif verified and not _is_nonempty_str(verified_by):
            issues.append("verified_by: required when verified is true (who checked the sources)")
        if verified_by is not None and not isinstance(verified_by, str):
            issues.append("verified_by: must be a string or null")

    return issues


def from_dict(raw: Any, *, expected_id: str | None = None) -> FactSheet:
    """Validate and convert a parsed fact sheet; raises SchemaError listing every problem."""
    issues = validate(raw, expected_id=expected_id)
    if issues:
        raise SchemaError(issues)
    return FactSheet(
        id=raw["id"],
        name=raw["name"],
        agency=raw["agency"],
        tier=raw["tier"],
        body=raw["body"],
        launched=raw["launched"],
        arrived=raw["arrived"],
        ended=raw["ended"],
        status=raw["status"],
        purpose=raw["purpose"],
        discoveries=tuple(raw["discoveries"]),
        how_it_worked=tuple(raw["how_it_worked"]),
        last_contact=raw["last_contact"],
        fun_fact=raw["fun_fact"],
        sources=tuple(Source(s["title"], s["url"], s["accessed"]) for s in raw["sources"]),
        verified=raw["verified"],
        verified_by=raw["verified_by"],
    )


def load_sheet(path: Path) -> FactSheet:
    """Read one fact sheet file; raises SchemaError for bad JSON or a malformed sheet."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SchemaError([f"not valid JSON: {exc}"]) from exc
    return from_dict(raw, expected_id=path.stem)


def load_buildable(directory: Path) -> LoadResult:
    """Load every sheet that may enter the build.

    A sheet is excluded if it is malformed or if a human has not marked it verified. Excluded
    sheets are reported, never silently dropped, so a typo cannot quietly remove a machine.
    """
    sheets: list[FactSheet] = []
    excluded: list[Excluded] = []
    for path in sorted(directory.glob("*.json")):
        try:
            sheet = load_sheet(path)
        except SchemaError as exc:
            excluded.append(Excluded(path.name, exc.issues, malformed=True))
            log.warning("excluded %s: %s", path.name, exc)
            continue
        if not sheet.verified:
            excluded.append(Excluded(path.name, (_NOT_VERIFIED,), malformed=False))
            log.info("excluded %s: not verified", path.name)
            continue
        sheets.append(sheet)
    return LoadResult(tuple(sheets), tuple(excluded))


def main(argv: list[str] | None = None) -> int:
    """Check a directory of fact sheets; exit 1 if any sheet is malformed."""
    parser = argparse.ArgumentParser(description="Validate fact sheets.")
    parser.add_argument("directory", nargs="?", default="data/machines", type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)

    result = load_buildable(args.directory)
    log.info("%d buildable, %d excluded", len(result.sheets), len(result.excluded))
    for item in result.excluded:
        for reason in item.reasons:
            log.info("  %s: %s", item.filename, reason)
    return 1 if any(e.malformed for e in result.excluded) else 0


if __name__ == "__main__":
    raise SystemExit(main())
