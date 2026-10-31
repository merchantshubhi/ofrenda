from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ghosts import build
from ghosts.build import (
    BuildError,
    build_document,
    build_site,
    llm_teller,
    machine_entry,
    template_teller,
)
from ghosts.llm import DEFAULT_MAX_TOKENS, DEFAULT_TEMPERATURE, LLMError
from ghosts.schema import FactSheet, load_buildable
from ghosts.verify import LEVELS, Story

DATA = Path(__file__).resolve().parent.parent / "data" / "machines"


def copy_real_sheets(destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    for path in DATA.glob("*.json"):
        shutil.copy(path, destination / path.name)
    return destination


def write_sheet(directory: Path, raw: dict[str, Any]) -> None:
    (directory / f"{raw['id']}.json").write_text(json.dumps(raw), encoding="utf-8")


def raw_sheet(name: str = "opportunity") -> dict[str, Any]:
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# --- one machine ------------------------------------------------------------------------------


def test_machine_entry_carries_facts_sources_and_stories(sheet: FactSheet) -> None:
    stories = {level: template_teller(sheet, level) for level in LEVELS}
    entry = machine_entry(sheet, stories)
    assert entry["id"] == "test-rover" and entry["tier"] == "resting"
    assert entry["discoveries"] == list(sheet.discoveries)
    assert entry["sources"] == [
        {"title": "A page", "url": "https://example.org/a", "accessed": "2026-10-29"}
    ]
    assert set(entry["stories"]) == set(LEVELS)
    assert entry["stories"]["young"] == {
        "text": stories["young"].text,
        "origin": "template",
    }
    json.dumps(entry)  # must be plain JSON data


def test_machine_entry_keeps_the_verifiers_name_out_of_the_site(sheet: FactSheet) -> None:
    entry = machine_entry(sheet, {level: template_teller(sheet, level) for level in LEVELS})
    assert "verified_by" not in entry
    assert entry["verified"] is True
    assert "tester" not in json.dumps(entry)


# --- the document -----------------------------------------------------------------------------


def test_document_orders_machines_by_tier_then_id(make_sheet: Callable[..., FactSheet]) -> None:
    sheets = (
        make_sheet(id="zzz-lost", tier="lost"),
        make_sheet(id="bbb-resting", tier="resting"),
        make_sheet(id="mmm-restless", tier="restless"),
        make_sheet(id="aaa-resting", tier="resting"),
    )
    document, _ = build_document(sheets, template_teller, model=None)
    assert [m["id"] for m in document["machines"]] == [
        "aaa-resting",
        "bbb-resting",
        "mmm-restless",
        "zzz-lost",
    ]


def test_document_records_the_model_and_version(sheet: FactSheet) -> None:
    document, told = build_document((sheet,), template_teller, model="gemma-test")
    assert document["generator"] == {"model": "gemma-test"}
    assert document["schema_version"] == build.SCHEMA_VERSION
    assert len(told) == len(LEVELS)


def test_document_refuses_an_unverified_sheet(make_sheet: Callable[..., FactSheet]) -> None:
    draft = make_sheet(id="draft-one", verified=False, verified_by=None)
    with pytest.raises(BuildError, match="draft-one is not verified"):
        build_document((draft,), template_teller, model=None)


def test_document_asks_the_teller_once_per_machine_and_level(sheet: FactSheet) -> None:
    asked: list[tuple[str, str]] = []

    def tell(item: FactSheet, level: str) -> Story:
        asked.append((item.id, level))
        return Story(f"{level} story", "model", 1, ())

    build_document((sheet,), tell, model="m")
    assert asked == [("test-rover", "young"), ("test-rover", "older")]


# --- building the file ------------------------------------------------------------------------


def test_no_llm_build_writes_valid_json_from_the_real_sheets(tmp_path: Path) -> None:
    out = tmp_path / "site" / "generated" / "machines.json"
    report = build_site(copy_real_sheets(tmp_path / "data"), out, template_teller, model=None)
    document = read(out)
    expected = {s.id for s in load_buildable(DATA).sheets}
    assert {m["id"] for m in document["machines"]} == expected
    assert report.machines == len(expected)
    assert report.model_stories == 0
    assert report.template_stories == len(expected) * len(LEVELS)
    for machine in document["machines"]:
        assert machine["sources"], machine["id"]
        for level in LEVELS:
            assert machine["stories"][level]["text"].strip()
            assert machine["stories"][level]["origin"] == "template"


def test_the_build_is_byte_for_byte_repeatable(tmp_path: Path) -> None:
    data = copy_real_sheets(tmp_path / "data")
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    build_site(data, first, template_teller, model=None)
    build_site(data, second, template_teller, model=None)
    assert first.read_bytes() == second.read_bytes()


def test_an_unverified_sheet_never_reaches_the_site(tmp_path: Path) -> None:
    data = copy_real_sheets(tmp_path / "data")
    draft = raw_sheet()
    draft.update(id="secret-draft", name="Secret Draft", verified=False, verified_by=None)
    write_sheet(data, draft)
    out = tmp_path / "machines.json"
    report = build_site(data, out, template_teller, model=None)
    assert "secret-draft" not in out.read_text(encoding="utf-8")
    assert "Secret Draft" not in out.read_text(encoding="utf-8")
    assert report.excluded == ("secret-draft.json",)


def test_building_never_changes_the_fact_sheets(tmp_path: Path) -> None:
    data = copy_real_sheets(tmp_path / "data")
    draft = raw_sheet()
    draft.update(id="draft-one", verified=False, verified_by=None)
    write_sheet(data, draft)
    before = {p.name: p.read_bytes() for p in data.glob("*.json")}
    build_site(data, tmp_path / "machines.json", template_teller, model=None)
    assert {p.name: p.read_bytes() for p in data.glob("*.json")} == before
    assert json.loads((data / "draft-one.json").read_text())["verified"] is False


def test_a_malformed_sheet_stops_the_build_and_keeps_the_old_file(tmp_path: Path) -> None:
    data = copy_real_sheets(tmp_path / "data")
    broken = raw_sheet()
    broken.update(id="broken", tier="haunted")
    write_sheet(data, broken)
    out = tmp_path / "machines.json"
    out.write_text("previous build", encoding="utf-8")
    with pytest.raises(BuildError, match="broken.json"):
        build_site(data, out, template_teller, model=None)
    assert out.read_text(encoding="utf-8") == "previous build"


def test_nothing_verified_means_nothing_built(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    draft = raw_sheet()
    draft.update(verified=False, verified_by=None)
    write_sheet(data, draft)
    with pytest.raises(BuildError, match="no verified fact sheets"):
        build_site(data, tmp_path / "machines.json", template_teller, model=None)
    assert not (tmp_path / "machines.json").exists()


def test_no_temporary_file_is_left_behind(tmp_path: Path) -> None:
    out = tmp_path / "out" / "machines.json"
    build_site(copy_real_sheets(tmp_path / "data"), out, template_teller, model=None)
    assert [p.name for p in out.parent.iterdir()] == ["machines.json"]


def test_unicode_is_written_as_is(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    raw = raw_sheet()
    raw["name"] = "Opportunity ★"
    write_sheet(data, raw)
    out = tmp_path / "machines.json"
    build_site(data, out, template_teller, model=None)
    assert "★" in out.read_text(encoding="utf-8")


# --- the model path, with a fake model --------------------------------------------------------


class ScriptedClient:
    def __init__(self, reply: str | Exception) -> None:
        self.reply = reply
        self.prompts: list[str] = []
        self.seeds: list[int | None] = []

    def generate(self, prompt: str, *, system: str = "", seed: int | None = None) -> str:
        self.prompts.append(prompt)
        self.seeds.append(seed)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply

    def check_ready(self) -> None:
        return None


def test_a_bad_model_story_is_replaced_by_the_template(sheet: FactSheet) -> None:
    client = ScriptedClient("I rolled for 777 days.")
    story = llm_teller(client)(sheet, "young")
    assert story.origin == "template"
    assert len(client.prompts) == 2  # first try, then one retry
    assert "777" in client.prompts[1]  # the retry says what was wrong


def test_a_dead_model_still_gives_every_story_a_template(sheet: FactSheet) -> None:
    client = ScriptedClient(LLMError("connection refused"))
    document, told = build_document((sheet,), llm_teller(client), model="gemma-test")
    assert {s.origin for s in told} == {"template"}
    assert len(document["machines"][0]["stories"]) == len(LEVELS)


# --- the command line -------------------------------------------------------------------------


def test_main_no_llm_builds_the_site_file(tmp_path: Path) -> None:
    out = tmp_path / "machines.json"
    data = copy_real_sheets(tmp_path / "data")
    assert build.main(["--no-llm", "--data", str(data), "--out", str(out)]) == 0
    assert read(out)["generator"] == {"model": None}


def test_main_needs_a_model_or_no_llm(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        build.main(["--data", str(tmp_path)])


def test_main_refuses_both_a_model_and_no_llm() -> None:
    with pytest.raises(SystemExit):
        build.main(["--no-llm", "--model", "gemma"])


def test_main_returns_1_for_a_bad_data_directory(tmp_path: Path) -> None:
    out = tmp_path / "machines.json"
    assert build.main(["--no-llm", "--data", str(tmp_path / "nope"), "--out", str(out)]) == 1
    assert not out.exists()


def test_main_refuses_a_hosted_endpoint(tmp_path: Path) -> None:
    out = tmp_path / "machines.json"
    argv = ["--model", "gemma", "--host", "https://api.example.com", "--out", str(out)]
    assert build.main(argv) == 1
    assert not out.exists()


def test_main_fails_cleanly_when_ollama_is_not_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class NotReady:
        def __init__(self, model: str, **kwargs: Any) -> None:
            pass

        def check_ready(self) -> None:
            raise LLMError("model 'gemma' is not installed; run: ollama pull gemma")

    monkeypatch.setattr(build, "OllamaClient", NotReady)
    out = tmp_path / "machines.json"
    data = copy_real_sheets(tmp_path / "data")
    assert build.main(["--model", "gemma", "--data", str(data), "--out", str(out)]) == 1
    assert not out.exists()


def test_main_with_a_model_falls_back_per_story(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[dict[str, Any]] = []

    class FakeOllama(ScriptedClient):
        def __init__(self, model: str, **kwargs: Any) -> None:
            super().__init__("Spirit found 12,345 purple crystals.")
            created.append({"model": model, **kwargs})

        def check_ready(self) -> None:
            return None

    monkeypatch.setattr(build, "OllamaClient", FakeOllama)
    out = tmp_path / "machines.json"
    data = copy_real_sheets(tmp_path / "data")
    argv = ["--model", "gemma-test", "--data", str(data), "--out", str(out), "--timeout", "5"]
    assert build.main(argv) == 0
    assert created == [
        {
            "model": "gemma-test",
            "host": build.DEFAULT_HOST,
            "timeout": 5.0,
            "temperature": DEFAULT_TEMPERATURE,
            "max_tokens": DEFAULT_MAX_TOKENS,
        }
    ]
    document = read(out)
    assert document["generator"] == {"model": "gemma-test"}
    origins = {
        story["origin"] for machine in document["machines"] for story in machine["stories"].values()
    }
    assert origins == {"template"}  # every invented draft was rejected


def test_story_text_is_plain_text_with_no_links_or_markup(tmp_path: Path) -> None:
    """Stories are rendered with textContent, but they should hold no links or markup anyway."""
    out = tmp_path / "machines.json"
    build_site(copy_real_sheets(tmp_path / "data"), out, template_teller, model=None)
    for machine in read(out)["machines"]:
        for story in machine["stories"].values():
            assert "http" not in story["text"] and "<" not in story["text"]


# --- bugs fixed after review ---------------------------------------------------------------------


def test_default_paths_come_from_the_repo_root_not_the_current_directory() -> None:
    assert build.DEFAULT_DATA.is_absolute() and build.DEFAULT_OUT.is_absolute()
    assert build.DEFAULT_DATA == build.ROOT / "data" / "machines"
    assert build.DEFAULT_OUT == build.ROOT / "site" / "generated" / "machines.json"
    assert build.DEFAULT_DATA.is_dir()


def test_the_build_works_from_any_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = tmp_path / "somewhere" / "else"
    elsewhere.mkdir(parents=True)
    monkeypatch.chdir(elsewhere)
    out = tmp_path / "machines.json"
    assert build.main(["--no-llm", "--out", str(out)]) == 0  # the default --data still resolves
    assert read(out)["machines"]


def test_a_real_bug_is_not_hidden_behind_a_polite_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: Any, **kwargs: Any) -> None:
        raise ValueError("a genuine bug")

    monkeypatch.setattr(build, "build_site", broken)
    with pytest.raises(ValueError, match="a genuine bug"):
        build.main(["--no-llm", "--out", str(tmp_path / "machines.json")])


def test_a_blank_model_name_is_a_usage_error(tmp_path: Path) -> None:
    assert build.main(["--model", " ", "--out", str(tmp_path / "machines.json")]) == 1


class FakeOllamaFactory:
    """Replaces OllamaClient and keeps the clients it made, so tests can inspect them."""

    def __init__(self, reply: str | Exception = "I rolled for 777 days.") -> None:
        self.reply = reply
        self.clients: list[ScriptedClient] = []
        self.kwargs: list[dict[str, Any]] = []

    def __call__(self, model: str, **kwargs: Any) -> ScriptedClient:
        client = ScriptedClient(self.reply)
        self.clients.append(client)
        self.kwargs.append(kwargs)
        return client


def run_with_fake_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *flags: str
) -> FakeOllamaFactory:
    factory = FakeOllamaFactory()
    monkeypatch.setattr(build, "OllamaClient", factory)
    data = copy_real_sheets(tmp_path / "data")
    argv = ["--model", "m", "--data", str(data), "--out", str(tmp_path / "out.json"), *flags]
    assert build.main(argv) == 0
    return factory


def test_the_tuning_flags_reach_the_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    factory = run_with_fake_model(
        tmp_path, monkeypatch, "--temperature", "0.2", "--max-tokens", "123", "--seed", "50"
    )
    assert factory.kwargs[0]["temperature"] == 0.2
    assert factory.kwargs[0]["max_tokens"] == 123
    assert set(factory.clients[0].seeds) == {50, 51}  # first try, then the retry's next seed


def test_retries_zero_asks_the_model_once_per_story(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = run_with_fake_model(tmp_path, monkeypatch, "--retries", "0")
    machines = len(read(tmp_path / "out.json")["machines"])
    assert len(factory.clients[0].prompts) == machines * len(LEVELS)


def test_the_default_is_one_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    factory = run_with_fake_model(tmp_path, monkeypatch)
    machines = len(read(tmp_path / "out.json")["machines"])
    assert len(factory.clients[0].prompts) == machines * len(LEVELS) * 2


@pytest.mark.parametrize("flag", [["--retries", "-1"], ["--max-tokens", "0"]])
def test_nonsense_tuning_values_are_refused(flag: list[str]) -> None:
    with pytest.raises(SystemExit):
        build.main(["--model", "m", *flag])
