from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from ghosts import schema
from ghosts.schema import SchemaError, from_dict, load_buildable, load_sheet, validate

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = Path(__file__).parent / "samples" / "sample-lander.json"


def sample() -> dict[str, Any]:
    return copy.deepcopy(json.loads(SAMPLE.read_text(encoding="utf-8")))


def write(directory: Path, raw: dict[str, Any], name: str | None = None) -> Path:
    path = directory / f"{name or raw['id']}.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def has_issue(issues: list[str], fragment: str) -> bool:
    return any(fragment in issue for issue in issues)


# --- the sample sheet -------------------------------------------------------------------------


def test_sample_is_valid() -> None:
    assert validate(sample(), expected_id="sample-lander") == []


def test_sample_loads_into_frozen_dataclass() -> None:
    sheet = load_sheet(SAMPLE)
    assert sheet.id == "sample-lander"
    assert sheet.tier == "resting"
    assert isinstance(sheet.discoveries, tuple)
    assert sheet.sources[0].url.startswith("https://")
    with pytest.raises(dataclasses.FrozenInstanceError):
        sheet.name = "changed"  # type: ignore[misc]


def test_field_list_matches_dataclass() -> None:
    names = tuple(f.name for f in dataclasses.fields(schema.FactSheet))
    assert names == schema.FIELDS


# --- required fields and shape ----------------------------------------------------------------


@pytest.mark.parametrize("key", schema.FIELDS)
def test_every_field_is_required(key: str) -> None:
    raw = sample()
    del raw[key]
    assert has_issue(validate(raw), f"missing field: {key}")


def test_not_an_object() -> None:
    assert validate([]) == ["fact sheet must be a JSON object"]


def test_unknown_field_is_flagged() -> None:
    raw = sample()
    raw["fun_facts"] = "typo"
    assert has_issue(validate(raw), "unknown field: fun_facts")


@pytest.mark.parametrize("key", schema.TEXT_FIELDS)
def test_text_fields_reject_blank(key: str) -> None:
    raw = sample()
    raw[key] = "   "
    assert has_issue(validate(raw), f"{key}: must be a non-empty string")


@pytest.mark.parametrize("key", schema.LIST_FIELDS)
@pytest.mark.parametrize("bad", [[], "not a list", [""], [1]])
def test_list_fields_reject_bad_values(key: str, bad: object) -> None:
    raw = sample()
    raw[key] = bad
    assert has_issue(validate(raw), key)


# --- enums and ids ----------------------------------------------------------------------------


def test_bad_tier() -> None:
    raw = sample()
    raw["tier"] = "haunted"
    assert has_issue(validate(raw), "tier: must be one of")


def test_bad_body() -> None:
    raw = sample()
    raw["body"] = "venus"
    assert has_issue(validate(raw), "body: must be one of")


@pytest.mark.parametrize("tier", schema.TIERS)
def test_all_tiers_accepted(tier: str) -> None:
    raw = sample()
    raw["tier"] = tier
    assert validate(raw) == []


@pytest.mark.parametrize("body", schema.BODIES)
def test_all_bodies_accepted(body: str) -> None:
    raw = sample()
    raw["body"] = body
    assert validate(raw) == []


@pytest.mark.parametrize("bad", ["Sample Lander", "sample_lander", "-sample", "a--b", "Sample"])
def test_bad_id_slug(bad: str) -> None:
    raw = sample()
    raw["id"] = bad
    assert has_issue(validate(raw), "id: use lowercase")


def test_id_must_match_filename() -> None:
    assert has_issue(validate(sample(), expected_id="other-name"), "does not match filename")


# --- dates ------------------------------------------------------------------------------------


@pytest.mark.parametrize("good", ["1999", "1999-02", "1999-02-28", "2024-02-29"])
def test_partial_dates_accepted(good: str) -> None:
    assert schema.is_valid_partial_date(good)


@pytest.mark.parametrize(
    "bad", ["", "99", "1999-13", "1999-00", "1999-02-30", "2023-02-29", "Jan 1999", "1999-1-1"]
)
def test_partial_dates_rejected(bad: str) -> None:
    assert not schema.is_valid_partial_date(bad)


def test_launched_cannot_be_null() -> None:
    raw = sample()
    raw["launched"] = None
    assert has_issue(validate(raw), "launched: must be a real date")


@pytest.mark.parametrize("key", schema.NULLABLE_DATE_FIELDS)
def test_nullable_dates_accept_null(key: str) -> None:
    raw = sample()
    raw["tier"] = "restless"  # a resting machine must have an end date
    raw[key] = None
    assert validate(raw) == []


@pytest.mark.parametrize("key", ["launched", *schema.NULLABLE_DATE_FIELDS])
def test_invalid_dates_rejected(key: str) -> None:
    raw = sample()
    raw[key] = "1999-02-30"
    assert has_issue(validate(raw), f"{key}: must be a real date")


def test_resting_needs_end_date() -> None:
    raw = sample()
    raw["ended"] = None
    assert has_issue(validate(raw), "ended: a resting machine")


# --- sources ----------------------------------------------------------------------------------


def test_sources_required() -> None:
    raw = sample()
    raw["sources"] = []
    assert has_issue(validate(raw), "at least one source")


@pytest.mark.parametrize(
    "url", ["", "example.org", "javascript:alert(1)", "ftp://x.org/a", "https://"]
)
def test_source_url_must_be_http(url: str) -> None:
    raw = sample()
    raw["sources"][0]["url"] = url
    assert has_issue(validate(raw), "sources[0].url")


@pytest.mark.parametrize("accessed", ["2026", "2026-02", "yesterday", "2026-02-30", None])
def test_source_accessed_must_be_full_date(accessed: object) -> None:
    raw = sample()
    raw["sources"][0]["accessed"] = accessed
    assert has_issue(validate(raw), "sources[0].accessed")


def test_source_needs_title() -> None:
    raw = sample()
    raw["sources"][0]["title"] = ""
    assert has_issue(validate(raw), "sources[0].title")


def test_source_unknown_key_and_wrong_type() -> None:
    raw = sample()
    raw["sources"][0]["note"] = "x"
    raw["sources"].append("https://example.org")
    issues = validate(raw)
    assert has_issue(issues, "sources[0]: unknown field: note")
    assert has_issue(issues, "sources[1]: must be an object")


# --- verification flag ------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["true", 1, None])
def test_verified_must_be_a_real_bool(bad: object) -> None:
    raw = sample()
    raw["verified"] = bad
    assert has_issue(validate(raw), "verified: must be true or false")


@pytest.mark.parametrize("who", [None, "", "  "])
def test_verified_true_needs_a_name(who: object) -> None:
    raw = sample()
    raw["verified_by"] = who
    assert has_issue(validate(raw), "verified_by: required")


def test_unverified_draft_needs_no_name() -> None:
    raw = sample()
    raw["verified"] = False
    raw["verified_by"] = None
    assert validate(raw) == []


def test_all_problems_reported_together() -> None:
    raw = sample()
    raw["tier"] = "haunted"
    raw["launched"] = "soon"
    del raw["fun_fact"]
    with pytest.raises(SchemaError) as info:
        from_dict(raw)
    assert len(info.value.issues) == 3


# --- loading and the build gate ---------------------------------------------------------------


def test_load_includes_verified_sheet(tmp_path: Path) -> None:
    write(tmp_path, sample())
    result = load_buildable(tmp_path)
    assert [s.id for s in result.sheets] == ["sample-lander"]
    assert result.excluded == ()


def test_load_excludes_unverified_sheet(tmp_path: Path) -> None:
    raw = sample()
    raw.update(id="draft-one", verified=False, verified_by=None)
    write(tmp_path, raw)
    result = load_buildable(tmp_path)
    assert result.sheets == ()
    assert result.excluded[0].filename == "draft-one.json"
    assert not result.excluded[0].malformed


def test_load_reports_malformed_and_bad_json(tmp_path: Path) -> None:
    broken = sample()
    broken["tier"] = "haunted"
    write(tmp_path, broken)
    (tmp_path / "garbled.json").write_text("{not json", encoding="utf-8")
    write(tmp_path, sample(), name="wrong-name")
    result = load_buildable(tmp_path)
    assert result.sheets == ()
    assert {e.filename for e in result.excluded} == {
        "sample-lander.json",
        "garbled.json",
        "wrong-name.json",
    }
    assert all(e.malformed for e in result.excluded)


def test_load_is_sorted_and_ignores_other_files(tmp_path: Path) -> None:
    for name in ("zeta", "alpha"):
        raw = sample()
        raw["id"] = name
        write(tmp_path, raw)
    (tmp_path / ".gitkeep").write_text("")
    (tmp_path / "notes.txt").write_text("hi")
    assert [s.id for s in load_buildable(tmp_path).sheets] == ["alpha", "zeta"]


def test_main_exit_codes(tmp_path: Path) -> None:
    write(tmp_path, sample())
    assert schema.main([str(tmp_path)]) == 0
    draft = sample()
    draft.update(id="draft", verified=False, verified_by=None)
    write(tmp_path, draft)
    assert schema.main([str(tmp_path)]) == 0  # unverified is excluded, not an error
    (tmp_path / "bad.json").write_text("[]")
    assert schema.main([str(tmp_path)]) == 1


def test_real_fact_sheets_are_well_formed() -> None:
    """Guard for data/machines: unverified drafts are fine, malformed sheets are not."""
    for path in sorted((ROOT / "data" / "machines").glob("*.json")):
        load_sheet(path)  # raises SchemaError on any problem
