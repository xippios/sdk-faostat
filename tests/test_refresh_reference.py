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
committed files' counts and fetch times, never pinning them. Core's count of a run holds
every request the client sends, a login among them, and the script names the logins in a
line after that count, where the frame fetched: the tests that run the script's ``main`` run
core's frame on a copy of the packaged files, so that the repository's stay as committed.
"""

import importlib.util
import json
import re
import shutil
from collections.abc import Iterator
from dataclasses import replace
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


def test_the_folder_readme_dates_nothing_beside_its_provenance_rows() -> None:
    """The folder's README says what the packaged files hold, and its provenance rows, which
    core's frame writes, date each fetch: what FAOSTAT was seen to answer is a note of
    ``docs/upstream/OBSERVED.md`` with its probe, which the README points to (conventions
    §3). A fenced example's values and a code span date nothing."""
    readme = (REFERENCE / "README.md").read_text(encoding="utf-8")
    prose = re.sub(r"^```.*?^```", "", readme, flags=re.MULTILINE | re.DOTALL)
    running = " ".join(
        re.sub(r"`[^`\n]*`", "", line) for line in prose.splitlines() if not line.startswith("|")
    )
    assert re.findall(r".{0,40}\d{4}-\d{2}-\d{2}.{0,20}", running) == []
    assert "docs/upstream/OBSERVED.md" in readme


@pytest.fixture
def copied_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The packaged tables and the folder's README in a package of the test's own.

    Core's frame writes into the package's directory as imported, which must lie in the
    directory the script runs in, so the declaration is pointed at a copy under
    ``tmp_path`` and the run runs there: the repository's files stay as committed.

    Returns:
        The copy's ``reference/`` folder.
    """
    package = tmp_path / "copied_faostat"
    shutil.copytree(REFERENCE, package / "reference")
    (package / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(script, "LISTS", replace(script.LISTS, package=package.name))
    return package / "reference"


def lines_naming_logins(out: str) -> list[str]:
    return [line for line in out.splitlines() if "logins" in line]


def test_the_logins_are_counted_and_named_after_the_frames_fetch_alone(
    replay_fixture: ReplayFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    """The script counts each login the client's auth flow builds, and prints no line of
    them where core's frame began no fetch: a fetch outside the frame has no count of its
    to follow."""
    replay_fixture(CODES, "element_QCL")
    with script.counted_logins(auth) as counted:
        sync(LISTED["element_QCL"].fetch)()
    assert counted.logins == 1
    assert not hasattr(counted, "resent"), "a resend is core's to count"
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("option", ["--render-only", "--render"])
def test_a_render_prints_no_count_of_logins(
    copied_package: Path, option: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--render`` is ``--render-only`` as the frame's parser reads an abbreviation: the frame
    writes the provenance rows from the packaged files, sends nothing and counts nothing."""
    assert script.main([option]) == 0
    out = capsys.readouterr().out
    assert "requests sent" not in out, "the frame printed no count"
    assert lines_naming_logins(out) == []
    assert (copied_package / "README.md").read_bytes() == (REFERENCE / "README.md").read_bytes()


@pytest.mark.parametrize(
    "argv", [["--help"], ["--only", "element_QV"]], ids=["help", "refused-only"]
)
def test_a_run_stopped_before_its_first_request_prints_no_count_of_logins(
    copied_package: Path, argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """``--help`` and a list that ``--only`` does not know end the run in the frame's parser
    or its check, before a request."""
    with pytest.raises(SystemExit):
        script.main(argv)
    out = capsys.readouterr().out
    assert "requests sent" not in out, "the frame printed no count"
    assert lines_naming_logins(out) == []


def test_a_fetching_run_prints_its_logins_once_after_the_frames_count(
    copied_package: Path, replay_fixture: ReplayFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--only element_QCL`` on the recorded login and answer, through the package's client:
    the frame counts the login and the request, and the script names the login among them,
    once, after the count."""
    route = replay_fixture(CODES, "element_QCL")
    assert script.main(["--only", "element_QCL"]) == 0
    assert route.call_count == 1
    out = capsys.readouterr().out.splitlines()
    counts = [index for index, line in enumerate(out) if line.startswith("requests sent: 2")]
    assert len(counts) == 1, "the frame's count, the login among its two requests"
    assert lines_naming_logins("\n".join(out)) == ["of them, logins: 1"]
    assert out.index("of them, logins: 1") > counts[0]
    written = json.loads((copied_package / "element_QCL.json").read_text(encoding="utf-8"))
    assert written["records"] == recorded_rows("element_QCL"), "the copy holds the answer"
