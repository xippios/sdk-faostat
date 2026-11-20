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
A run sends each request once and prints what it sent, the login among it, a failed
run's too; ``--only`` fetches the tables it names and keeps the others' files, and both
are checked before the first request. The 503 below is a test double, no recording.
"""

import importlib.util
import inspect
import json
import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
import respx
from xippios.core import AuthError, PackagedList, UpstreamError, sync
from xippios.core.testing import ReplayFixture, assert_time_between, load_fixture

from xippios.faostat import params
from xippios.faostat._client import BASE_URL, LOGIN_PATH, auth
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


def qcl_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *kept: str) -> Path:
    """The script on QCL's three tables, into a reference directory of the test's own.

    ``kept`` are the tables whose committed files the directory starts with.
    """
    reference = tmp_path / "reference"
    reference.mkdir()
    shutil.copy(REFERENCE / "README.md", reference / "README.md")
    for name in kept:
        shutil.copy(REFERENCE / f"{name}.json", reference / f"{name}.json")
    monkeypatch.setattr(script, "TABLES", {name: script.TABLES[name] for name in QCL_TABLES})
    monkeypatch.setattr(script, "PACKAGED_LISTS", QCL_TABLES)
    monkeypatch.setattr(script, "REFERENCE", reference)
    monkeypatch.setattr(script, "README", reference / "README.md")
    monkeypatch.setattr(script, "ENUMS", tmp_path / "enums.py")
    return reference


def test_a_refresh_prints_the_requests_it_sent_the_login_among_them(
    replay_fixture: ReplayFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in QCL_TABLES:
        replay_fixture(CODES, name)
    qcl_run(monkeypatch, tmp_path)
    script.refresh()
    printed = capsys.readouterr().out.splitlines()
    assert "requests sent: 4, logins among them: 1; quota left: not reported" in printed


def test_a_failed_fetch_is_sent_once_writes_nothing_and_is_counted(
    replay_fixture: ReplayFixture,
    respx_mock: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    replay_fixture(CODES, "area_QCL")
    replay_fixture(CODES, "element_QCL")
    failing = respx_mock.get(f"{BASE_URL}/en/codes/item/QCL").mock(
        return_value=httpx.Response(503, text="Service Unavailable")
    )
    reference = qcl_run(monkeypatch, tmp_path)
    with pytest.raises(UpstreamError):
        script.refresh()
    assert failing.call_count == 1, "one attempt: a 5xx spends no second keyed call"
    assert sorted(path.name for path in reference.iterdir()) == ["README.md"], "nothing written"
    assert (reference / "README.md").read_bytes() == (REFERENCE / "README.md").read_bytes()
    printed = capsys.readouterr().out.splitlines()
    assert "requests sent: 4, logins among them: 1; quota left: not reported" in printed
    assert script.client.config.retry.max_attempts > 1, "the client's own policy restored"


def test_only_fetches_the_named_table_and_keeps_the_others(
    replay_fixture: ReplayFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    kept = ("area_QCL", "item_QCL")
    route = replay_fixture(CODES, "element_QCL")
    reference = qcl_run(monkeypatch, tmp_path, *kept)
    script.main(["--only", "element_QCL"])
    assert route.call_count == 1
    for name in kept:
        assert (reference / f"{name}.json").read_bytes() == (
            REFERENCE / f"{name}.json"
        ).read_bytes()
    fetched = PackagedList.model_validate_json(
        (reference / "element_QCL.json").read_text(encoding="utf-8")
    )
    assert fetched.records == recorded_rows("element_QCL")
    readme = (reference / "README.md").read_text(encoding="utf-8")
    rows = [line.split("`")[1] for line in readme.splitlines() if line.startswith("| `")]
    assert rows == [f"{name}.json" for name in QCL_TABLES], "a row for every packaged table"
    assert "requests sent: 2, logins among them: 1; quota left: not reported" in (
        capsys.readouterr().out.splitlines()
    )


def test_only_refuses_a_table_the_script_does_not_package_before_a_request(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    qcl_run(monkeypatch, tmp_path, "area_QCL", "item_QCL")
    with pytest.raises(SystemExit, match=r"^--only: no list element_XXX in area_QCL, "):
        script.main(["--only", "element_XXX"])
    assert not respx_mock.calls, "neither the login nor a table was asked"


def test_only_refuses_while_a_kept_table_is_not_packaged_before_a_request(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The provenance rows read every table's file, so a kept one must be there first."""
    reference = qcl_run(monkeypatch, tmp_path, "item_QCL")
    with pytest.raises(SystemExit, match=r"^area_QCL is not packaged yet: run without --only"):
        script.main(["--only", "element_QCL"])
    assert not respx_mock.calls, "neither the login nor a table was asked"
    assert sorted(path.name for path in reference.iterdir()) == ["README.md", "item_QCL.json"]


def test_render_names_no_class_of_its_own() -> None:
    """Core's default names a class after its list or id field (sdk-core ADR-0031)."""
    assert "class_names" not in inspect.getsource(script.render)


def test_a_refused_login_is_counted(
    respx_mock: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A test double: the login refused with HTTP 401, which ends the run."""
    respx_mock.routes.clear()  # the recorded login of the autouse fixture gives way
    respx_mock.post(f"{BASE_URL}{LOGIN_PATH}").mock(return_value=httpx.Response(401))
    reference = qcl_run(monkeypatch, tmp_path)
    with pytest.raises(AuthError):
        script.refresh()
    assert len(respx_mock.calls) == 1
    assert sorted(path.name for path in reference.iterdir()) == ["README.md"], "nothing written"
    printed = capsys.readouterr().out.splitlines()
    assert "requests sent: 1, logins among them: 1; quota left: not reported" in printed


def test_a_renewal_whose_login_fails_is_counted_with_the_refused_request(
    replay_fixture: ReplayFixture,
    respx_mock: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test doubles: the second table refused with HTTP 403, the renewal's login with 503."""
    recorded_login = load_fixture(FIXTURES / "auth_login" / "login.json").response
    respx_mock.routes.clear()  # the recorded login of the autouse fixture gives way
    respx_mock.post(f"{BASE_URL}{LOGIN_PATH}").mock(
        side_effect=[
            httpx.Response(200, headers=recorded_login.headers, content=recorded_login.content),
            httpx.Response(503, text="Service Unavailable"),
        ]
    )
    replay_fixture(CODES, "area_QCL")
    respx_mock.get(f"{BASE_URL}/en/codes/element/QCL").mock(return_value=httpx.Response(403))
    qcl_run(monkeypatch, tmp_path)
    with pytest.raises(UpstreamError):
        script.refresh()
    assert len(respx_mock.calls) == 4, "a login, a table, the refused table, the renewal"
    printed = capsys.readouterr().out.splitlines()
    assert "requests sent: 4, logins among them: 2; quota left: not reported" in printed


def test_a_readme_without_its_provenance_table_stops_the_run_before_a_request(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    reference = qcl_run(monkeypatch, tmp_path)
    (reference / "README.md").write_text("# Reference data\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="no table headed"):
        script.refresh()
    assert not respx_mock.calls, "neither the login nor a table was asked"
    assert sorted(path.name for path in reference.iterdir()) == ["README.md"], "nothing written"
