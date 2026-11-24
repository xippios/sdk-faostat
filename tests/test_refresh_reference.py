"""``scripts/refresh_reference.py``'s declaration on the recorded answers, and the packaged files.

The script declares fifteen tables in one ``Lists`` and hands it to core's ``run``, which
fetches, writes the files, the provenance rows and ``enums.py`` (sdk-core ADR-0062): core
tests that frame, and these tests hold what the script declares. Each table is fetched
through ``api.get_code_list`` (``getCodeList``): the codes of ``area``, ``element`` and
``item`` in QCL, TCL, FBS, PP and RL. QCL's three answers are recorded
(``tests/fixtures/get_code_list/area_QCL``, ``element_QCL`` and ``item_QCL``, 2026-10-29),
with ``countries_QCL``, the subdimension's answer the packaged ``area`` table is chosen over;
the other twelve domains' answers are packaged, not recorded. The tests replay QCL's answers
through the declared fetches, check that a packaged record is upstream's record as sent, and
check the committed files and the provenance rows against the declaration. They read the
committed files' counts and fetch times, never pinning them. The logins that core's count of
a run leaves out, since they run inside the client's auth flow, are counted by the script.
"""

import importlib.util
import json
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from xippios.core import sync
from xippios.core.testing import ReplayFixture, load_fixture

from xippios.faostat import params
from xippios.faostat._client import auth, client
from xippios.faostat.models import CodeItem

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "refresh_reference.py"
FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE = ROOT / "src" / "xippios" / "faostat" / "reference"
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
LISTED = {listed.name: listed for listed in script.LISTS.lists}


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


def test_the_lists_are_the_packaged_tables_in_one_declaration() -> None:
    lists = script.LISTS
    assert lists.package == params.PACKAGE
    assert tuple(lists.packaged) == params.PACKAGED_LISTS
    assert [listed.name for listed in lists.lists] == list(params.PACKAGED_LISTS)
    assert lists.client is client, "the package's client, whose LoginAuth logs in"
    assert lists.quota_header is None, "FAOSTAT reports no quota"
    for domain in params.DOMAINS:
        for dimension in params.DIMENSIONS:
            listed = LISTED[f"{dimension}_{domain}"]
            assert listed.endpoint == "getCodeList"
            assert listed.param == dimension
            assert listed.enum is None, "a table, no enum"
            assert listed.origin == f"`getCodeList`, `GET /en/codes/{dimension}/{domain}`"


@pytest.mark.parametrize("name", QCL_TABLES)
def test_a_packaged_record_is_upstreams_record(replay_fixture: ReplayFixture, name: str) -> None:
    route = replay_fixture(CODES, name)
    records = sync(LISTED[name].fetch)()
    assert route.call_count == 1
    assert all(isinstance(record, CodeItem) for record in records)
    assert [record.dump_upstream() for record in records] == recorded_rows(name), "as sent"


def test_item_records_keep_parent_and_area_records_have_none(
    replay_fixture: ReplayFixture,
) -> None:
    replay_fixture(CODES, "area_QCL")
    replay_fixture(CODES, "item_QCL")
    areas = sync(LISTED["area_QCL"].fetch)()
    items = sync(LISTED["item_QCL"].fetch)()
    assert all(area.parent is None for area in areas)
    assert all("parent" not in area.dump_upstream() for area in areas)
    assert all(item.parent for item in items)
    assert {item.columns == {} for item in [*areas, *items]} == {True}


def test_a_field_no_name_covers_is_kept_and_packaged_back() -> None:
    """A record as an in-memory mapping: QCL's first item and one field more.

    The record is an input of the test, not an answer from FAOSTAT.
    """
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
    assert all(params.table(name).name_of(code.code) is not None for code in codes)


def test_the_committed_provenance_rows_are_the_declared_origins() -> None:
    """The rows core's frame writes from each list's origin and its file's fetch time."""
    readme = (REFERENCE / "README.md").read_text(encoding="utf-8")
    rows = [line for line in readme.splitlines() if line.startswith("| `")]
    assert rows == [
        f"| `{listed.name}.json` | {listed.origin} | "
        f"{params.packaged(listed.name).fetched:%Y-%m-%dT%H:%M:%SZ} |"
        for listed in script.LISTS.lists
    ]
    assert "| File | Origin | Fetched |" in readme, "the one header core's frame knows"


def test_the_logins_among_cores_count_are_named(
    replay_fixture: ReplayFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    """Core's count of the run holds the logins among its requests; the script names them."""
    replay_fixture(CODES, "element_QCL")
    with script.counted_logins(auth) as counted:
        sync(LISTED["element_QCL"].fetch)()
    assert counted.logins == 1
    assert not hasattr(counted, "resent"), "a resend is core's to count"
    assert capsys.readouterr().out.splitlines() == ["of them, logins: 1"]


def test_render_only_prints_no_count_of_logins(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--render-only`` sends nothing, so no count of the frame's stands for the line to name."""
    handed: list[list[str]] = []

    def frame(lists: object, argv: list[str]) -> int:
        handed.append(list(argv))
        return 0

    monkeypatch.setattr(script, "run", frame)
    assert script.main(["--render-only"]) == 0
    assert capsys.readouterr().out == ""
    assert script.main(["--only", "element_QCL"]) == 0
    assert capsys.readouterr().out.splitlines() == ["of them, logins: 0"]
    assert handed == [["--render-only"], ["--only", "element_QCL"]]
