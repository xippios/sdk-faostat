"""``scripts/refresh_reference.py`` on the recorded answers, and the packaged files it wrote.

The script fetches fifteen tables through ``api.get_code_list`` (``getCodeList``): the
codes of ``area``, ``element`` and ``item`` in QCL, TCL, FBS, PP and RL. QCL's three
answers are recorded (``tests/fixtures/get_code_list/area_QCL``, ``element_QCL`` and
``item_QCL``, 2026-10-29), with ``countries_QCL``, the subdimension's answer the
packaged ``area`` table is chosen over; the other twelve domains' answers are packaged,
not recorded, to keep the recordings within the pull request's budget of keyed calls.
The tests replay QCL's answers through the script's fetcher, check that a packaged
record is upstream's record as sent, run the refresh into a directory of the test's own
on QCL's three tables, and check the committed files and the provenance table against
each other. They read the committed files' counts and fetch times, never pinning them.
"""

import importlib.util
import json
import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from xippios.core import PackagedList, sync
from xippios.core.testing import ReplayFixture, assert_time_between, load_fixture

from xippios.faostat import params
from xippios.faostat._client import auth
from xippios.faostat.models import CodeItem

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "refresh_reference.py"
FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE = ROOT / "src" / "xippios" / "faostat" / "reference"
ENUMS = ROOT / "src" / "xippios" / "faostat" / "enums.py"
CODES = "get_code_list"
QCL_TABLES = ("area_QCL", "element_QCL", "item_QCL")


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("refresh_reference", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = load_script()


def recorded_rows(case: str) -> list[dict[str, Any]]:
    """The recorded answer's ``data``, upstream's records as sent."""
    body = load_fixture(FIXTURES / CODES / f"{case}.json").response.body
    rows: list[dict[str, Any]] = json.loads(body)["data"]
    return rows


@pytest.fixture(autouse=True)
def logged_in(replay_fixture: ReplayFixture) -> Iterator[None]:
    """Every request logs in through the recorded login, the process's token forgotten."""
    auth.reset()
    replay_fixture("auth_login", "login")
    yield
    auth.reset()


def test_tables_are_the_packaged_lists() -> None:
    assert sorted(script.TABLES) == sorted(params.PACKAGED_LISTS)
    assert len(params.PACKAGED_LISTS) == len(params.DIMENSIONS) * len(params.DOMAINS)
    assert not script.LISTS
    assert not script.ID_LISTS
    for domain in params.DOMAINS:
        for dimension in params.DIMENSIONS:
            table = script.TABLES[f"{dimension}_{domain}"]
            assert table.endpoint == "getCodeList"
            assert table.param == dimension
            assert table.path == f"/en/codes/{dimension}/{domain}"


@pytest.mark.parametrize("name", QCL_TABLES)
def test_a_packaged_record_is_upstreams_record(
    replay_fixture: ReplayFixture, name: str, tmp_path: Path
) -> None:
    route = replay_fixture(CODES, name)
    table = script.TABLES[name]
    records = sync(table.fetch)()
    assert route.call_count == 1
    assert all(isinstance(record, CodeItem) for record in records)
    listed = script.packaged(
        name, table.endpoint, [record.dump_upstream() for record in records], param=table.param
    )
    assert listed.records == recorded_rows(name), "upstream's records, as sent, in order"
    listed.write(tmp_path / f"{name}.json")
    written = json.loads((tmp_path / f"{name}.json").read_text(encoding="utf-8"))
    assert list(written) == ["param", "endpoint", "fetched", "records"]
    assert written["param"] == table.param
    assert written["endpoint"] == "getCodeList"
    assert written["records"] == recorded_rows(name)
    assert PackagedList.model_validate(written).parse(CodeItem, source="faostat") == records


def test_item_records_keep_parent_and_area_records_have_none(
    replay_fixture: ReplayFixture,
) -> None:
    replay_fixture(CODES, "area_QCL")
    replay_fixture(CODES, "item_QCL")
    areas = sync(script.TABLES["area_QCL"].fetch)()
    items = sync(script.TABLES["item_QCL"].fetch)()
    assert all(area.parent is None for area in areas)
    assert all("parent" not in area.dump_upstream() for area in areas)
    assert all(item.parent for item in items)
    assert {item.columns == {} for item in [*areas, *items]} == {True}


def test_a_field_no_name_covers_is_kept_and_packaged_back() -> None:
    """A record as an in-memory mapping (no fixture): QCL's first item and one field more."""
    printed = recorded_rows("item_QCL")[0]
    record = {**printed, "extra": "x"}
    item = CodeItem.model_validate(record)
    assert item.columns == {"extra": "x"}
    assert item.dump_upstream() == record
    assert CodeItem.model_validate(item.model_dump()) == item, "a dump by name round-trips"


def test_the_countries_subdimension_answers_a_part_of_the_area_dimension() -> None:
    """Why ``area_QCL`` holds ``codes/area/QCL``: ``codes/countries/QCL`` lacks the aggregates."""
    areas = {row["code"]: row["label"] for row in recorded_rows("area_QCL")}
    countries = {row["code"]: row["label"] for row in recorded_rows("countries_QCL")}
    assert countries.items() <= areas.items(), "every country, with the same label"
    aggregates = set(areas) - set(countries)
    assert aggregates, "the regions and special groups the countries lack"
    assert {row["aggregate_type"] for row in recorded_rows("countries_QCL")} == {"0"}
    assert all(
        row["aggregate_type"] in {"+", ">"}
        for row in recorded_rows("area_QCL")
        if row["code"] in aggregates
    )


def test_refresh_writes_the_tables_the_provenance_and_the_enums(
    replay_fixture: ReplayFixture, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The refresh on QCL's three tables, into a reference directory of the test's own."""
    for name in QCL_TABLES:
        replay_fixture(CODES, name)
    reference = tmp_path / "reference"
    reference.mkdir()
    shutil.copy(REFERENCE / "README.md", reference / "README.md")
    monkeypatch.setattr(script, "TABLES", {name: script.TABLES[name] for name in QCL_TABLES})
    monkeypatch.setattr(script, "PACKAGED_LISTS", QCL_TABLES)
    monkeypatch.setattr(script, "REFERENCE", reference)
    monkeypatch.setattr(script, "README", reference / "README.md")
    monkeypatch.setattr(script, "ENUMS", tmp_path / "enums.py")
    before = datetime.now(UTC)
    script.refresh()
    after = datetime.now(UTC)
    for name in QCL_TABLES:
        listed = PackagedList.model_validate_json(
            (reference / f"{name}.json").read_text(encoding="utf-8")
        )
        assert listed.param == name.split("_")[0]
        assert listed.endpoint == "getCodeList"
        assert_time_between(listed.fetched, before, after)  # written to the second
        assert listed.records == recorded_rows(name)
    readme = (reference / "README.md").read_text(encoding="utf-8")
    rows = [line for line in readme.splitlines() if line.startswith("| `")]
    assert [row.split("`")[1] for row in rows] == [f"{name}.json" for name in QCL_TABLES]
    assert all("`getCodeList`, `GET /en/codes/" in row for row in rows)
    assert "(none yet)" not in readme
    assert (
        readme.split(script.PROVENANCE_HEADER)[0]
        == (REFERENCE / "README.md").read_text(encoding="utf-8").split(script.PROVENANCE_HEADER)[0]
    ), "the text above the table is kept"
    assert (tmp_path / "enums.py").read_text(encoding="utf-8") == ENUMS.read_text(
        encoding="utf-8"
    ), "no enum: the committed, empty module"


def test_with_provenance_replaces_the_rows_alone() -> None:
    readme = f"# Title\n\nText.\n\n{script.PROVENANCE_HEADER}\n| --- | --- | --- |\n| old | | |\n"
    readme += "\nAfter.\n"
    written = script.with_provenance(readme, ["| `a.json` | x | y |", "| `b.json` | x | y |"])
    assert written == (
        f"# Title\n\nText.\n\n{script.PROVENANCE_HEADER}\n| --- | --- | --- |\n"
        "| `a.json` | x | y |\n| `b.json` | x | y |\n\nAfter.\n"
    )


def test_with_provenance_refuses_a_readme_without_the_table() -> None:
    with pytest.raises(SystemExit, match="no table headed"):
        script.with_provenance("# Title\n", [])


@pytest.mark.parametrize("name", params.PACKAGED_LISTS)
def test_the_committed_table_is_a_packaged_code_list(name: str) -> None:
    dimension, domain = name.split("_")
    assert dimension in params.DIMENSIONS
    assert domain in params.DOMAINS
    listed = params.packaged(name)
    assert listed.param == dimension
    assert listed.endpoint == "getCodeList"
    assert listed.fetched.tzinfo is not None
    assert listed.records, f"{name}: upstream listed no code"
    codes = params.codes(name)
    assert [code.dump_upstream() for code in codes] == listed.records, "upstream's records"
    assert all(code.code and code.label for code in codes)
    assert params.labels(name) == {code.code: code.label for code in codes}


def test_the_committed_provenance_rows_are_the_files() -> None:
    readme = (REFERENCE / "README.md").read_text(encoding="utf-8")
    assert script.with_provenance(readme, script.provenance_rows()) == readme


def test_render_only_writes_the_committed_enums(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(script, "ENUMS", tmp_path / "enums.py")
    script.render()
    assert (tmp_path / "enums.py").read_text(encoding="utf-8") == ENUMS.read_text(encoding="utf-8")
