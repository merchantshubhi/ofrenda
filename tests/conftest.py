from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ghosts.schema import FactSheet, from_dict, load_sheet

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "machines"

# A small, valid, verified sheet that does not depend on the real data files. Every number,
# month, name and quotable phrase the tests rely on is written out here.
SHEET: dict[str, Any] = {
    "id": "test-rover",
    "name": "Test Rover",
    "agency": "Example Space Agency",
    "tier": "resting",
    "body": "mars",
    "launched": "2003-07-07",
    "arrived": "2004-01-24",
    "ended": "2019-02-13",
    "status": "Resting on a dusty plain on Mars. It stopped talking during a big dust storm.",
    "purpose": "To look for clues that water once flowed on Mars.",
    "discoveries": [
        'It found tiny round pebbles nicknamed "blueberries" in the soil.',
        "It found layered rocks that formed in ancient water.",
    ],
    "how_it_worked": ["It rolled across the surface on six wheels.", "It used solar panels."],
    "last_contact": "2018-06-10",
    "fun_fact": "It was built to last 90 days, but it worked for almost 15 years.",
    "sources": [{"title": "A page", "url": "https://example.org/a", "accessed": "2026-10-29"}],
    "verified": True,
    "verified_by": "tester",
}


@pytest.fixture
def make_sheet() -> Callable[..., FactSheet]:
    """Build a valid FactSheet from SHEET, with any fields overridden."""

    def make(**overrides: Any) -> FactSheet:
        raw = {**SHEET, **overrides}
        return from_dict(raw, expected_id=raw["id"])

    return make


@pytest.fixture
def sheet(make_sheet: Callable[..., FactSheet]) -> FactSheet:
    return make_sheet()


@pytest.fixture
def real_sheets() -> tuple[FactSheet, ...]:
    """The machines actually shipped in data/machines (whatever is there when tests run)."""
    return tuple(load_sheet(path) for path in sorted(DATA.glob("*.json")))
