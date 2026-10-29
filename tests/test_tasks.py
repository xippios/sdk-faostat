"""Replay tests on recorded fixtures, at least one per task (conventions §10).

``/add-endpoint`` and ``/record-fixture`` add them.

The fixtures were recorded on 2026-10-29 through the package's client, with the FAO
account's token (``tests/test_client.py`` covers the login). ``get_data``'s are under
``tests/fixtures/get_data/``: ``QCL_231_2510_15_2015_2021``, wheat production in the
United States of America over seven years (7 rows); ``QCL_page_2``, the same query with
``page_size=2&page_number=2`` (rows 3 and 4); ``QCL_element_5510_empty``, the same query
with the answer's element code as the filter (no rows), which ``get_data`` now refuses
before sending, the route mounted to show it is never called; ``PP_231_2020_page_size_2``, the
first two producer prices of 2020, whose rows carry ``Months Code`` and ``Months`` and no
``Note``; ``XXX_unknown_domain_500``, an unknown domain; ``no_filter_500``, a query
without a filter, sent through the wrapper since the task refuses it before sending.
``list_domains`` and ``get_data``'s release date read
``tests/fixtures/get_groupsanddomains/all.json`` (78 rows); the tests take the expected
values from it. ``QCL_840_M49_15_2510_2020``, recorded later on 2026-10-29, is the answer
to ``area_cs=M49``: no rows, and a ``metadata.dsd`` naming ``Area Code (M49)``;
``QCL_231_FAO_15_FAO_2510_2020``, the answer to ``area_cs=FAO`` and ``item_cs=FAO``, one
row whose code columns are ``Area Code (FAO)`` and ``Item Code (FAO)``. The
replay tests of ``get_data`` and ``list_domains`` send exactly the recorded query
(``sent_query`` against ``recorded_query``); the MCP test of ``get_data`` sends two
years where the fixture recorded seven, and checks the years sent.

``get_series`` replays ``QCL_231_2510_15_2015_2021`` too, its recorded query being the
year list ``since=2015, until=2021`` sends: the route matches the recorded ``area``,
``item``, ``element`` and ``year`` (``match_params``), so a request with other years finds
no route. Without ``since`` and ``until`` the same answer is served at its path, whatever
the query, and the test checks that no ``year`` filter was sent; the refusals send
nothing.

``list_areas``, ``list_elements`` and ``list_items`` answer from the fifteen packaged
tables under ``src/xippios/faostat/reference/``, without a request; their tests, and
``get_data``'s refusals of a code a table lacks, read the codes, labels, counts and fetch
times from the packaged files (``params``), never pinning them, so a refresh of the
tables breaks no test.

``list_bulk_datasets`` and ``download_dataset`` read the bulk catalogue recorded as
``tests/fixtures/datasets_e/all.json`` (69 datasets) and ``download_dataset`` replays
``tests/fixtures/download_dataset/MDDW.json``, the GET of MDDW's ZIP, the smallest
dataset's, recorded whole (12,146 bytes) and flagged binary; both were recorded on
2026-10-29 without the account. Their tests take the expected values from the
recordings, and check that no request carried an ``Authorization`` header and none went
to the API's host, so no login was sent either.
"""

import dataclasses
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from xippios.core import Downloaded, InvalidRequestError, NotFoundError, UnknownCode, matches
from xippios.core._loop import run
from xippios.core.mcp import build_server
from xippios.core.testing import (
    Fixture,
    ReplayFixture,
    assert_time_between,
    load_fixture,
    mcp_call,
    mcp_call_text,
    recorded_query,
    sent_query,
    sent_urls,
)

from xippios.faostat import (
    api,
    download_dataset,
    get_data,
    get_series,
    list_areas,
    list_bulk_datasets,
    list_domains,
    list_elements,
    list_items,
    params,
    tasks,
)
from xippios.faostat._client import FILTER_REFUSAL, SOURCE, auth
from xippios.faostat.http import router
from xippios.faostat.mcp import server
from xippios.faostat.models import (
    BulkDataset,
    CodeItem,
    DataRecord,
    DataResponse,
    DatasetsCatalogue,
    Domain,
    DsdColumn,
    GroupsAndDomainsResponse,
)
from xippios.faostat.parse import parse_bulk_csv

FIXTURES = Path(__file__).parent / "fixtures"
GET_DATA = "get_data"
DOMAINS = "get_groupsanddomains"
QCL = "QCL_231_2510_15_2015_2021"
QCL_ARGUMENTS: dict[str, Any] = {
    "area": "231",
    "element": "2510",
    "item": "15",
    "year": list(range(2015, 2022)),
}
SENT_OPTIONS = {
    "show_codes": True,
    "show_unit": True,
    "show_flags": True,
    "show_notes": True,
    "null_values": False,
    "output_type": "objects",
}


def recorded(endpoint: str, case: str) -> Fixture:
    return load_fixture(FIXTURES / endpoint / f"{case}.json")


def recorded_rows(case: str) -> list[DataRecord]:
    return DataResponse.model_validate_json(recorded(GET_DATA, case).response.body).data


def recorded_dsd(case: str) -> list[DsdColumn]:
    return DataResponse.model_validate_json(recorded(GET_DATA, case).response.body).metadata.dsd


def recorded_domains() -> list[Domain]:
    return GroupsAndDomainsResponse.model_validate_json(recorded(DOMAINS, "all").response.body).data


def date_update(domain: str) -> str | None:
    """The domain's ``date_update`` in the recorded list, as ``meta.vintage`` must hold it."""
    return next(row.date_update for row in recorded_domains() if row.domain_code == domain)


@pytest.fixture(autouse=True)
def logged_in(replay_fixture: ReplayFixture) -> Iterator[None]:
    """Every test logs in through the recorded login, the process's token forgotten around it."""
    auth.reset()
    replay_fixture("auth_login", "login")
    yield
    auth.reset()


def test_get_data_qcl(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture(GET_DATA, QCL)
    domains = replay_fixture(DOMAINS, "all")
    before = datetime.now(UTC)
    result = get_data("QCL", **QCL_ARGUMENTS)
    after = datetime.now(UTC)
    assert sent_query(route) == recorded_query(recorded(GET_DATA, QCL))
    assert sent_query(domains) == {}
    assert result.data == recorded_rows(QCL)
    assert len(result.data) == 7
    assert all(isinstance(row, DataRecord) for row in result.data)
    assert all(isinstance(row.value, Decimal) for row in result.data)
    assert [row.year for row in result.data] == [str(year) for year in range(2015, 2022)]
    assert {row.element_code for row in result.data} == {"5510"}, "the answer's code, not 2510"
    assert {row.item_code for row in result.data} == {"15"}
    assert {row.area_code for row in result.data} == {"231"}
    assert {row.note for row in result.data} == {""}
    assert {(row.months_code, row.months) for row in result.data} == {(None, None)}
    meta = result.meta
    assert meta.source == SOURCE
    assert meta.endpoint == "get_data"
    assert_time_between(meta.retrieved_at, before, after)
    assert meta.published_at is None, "a date is no release time: it is in vintage"
    assert meta.published_at_naive is False
    assert meta.vintage == date_update("QCL")
    assert meta.total is None
    assert meta.request == {
        "lang": "en",
        "domain_code": "QCL",
        "area": "231",
        "item": "15",
        "element": "2510",
        "year": "2015,2016,2017,2018,2019,2020,2021",
        **SENT_OPTIONS,
    }


def test_get_data_page(replay_fixture: ReplayFixture) -> None:
    case = "QCL_page_2"
    route = replay_fixture(GET_DATA, case)
    replay_fixture(DOMAINS, "all")
    result = get_data("QCL", **QCL_ARGUMENTS, page_size=2, page_number=2)
    assert sent_query(route) == recorded_query(recorded(GET_DATA, case))
    assert sent_query(route)["page_size"] == "2"
    assert sent_query(route)["page_number"] == "2"
    assert result.data == recorded_rows(case)
    assert [row.year for row in result.data] == ["2017", "2018"], "rows 3 and 4 of the 7"
    assert result.meta.request["page_size"] == 2
    assert result.meta.request["page_number"] == 2
    assert result.meta.total is None


def test_get_data_refuses_the_rows_element_code_before_sending(
    replay_fixture: ReplayFixture, respx_mock: respx.MockRouter
) -> None:
    """Upstream answers the rows' element code with no rows: refused, naming the filter code."""
    case = "QCL_element_5510_empty"
    assert recorded_rows(case) == [], "upstream's recorded answer to element=5510"
    route = replay_fixture(GET_DATA, case)
    replay_fixture(DOMAINS, "all")
    with pytest.raises(UnknownCode) as raised:
        get_data("QCL", **{**QCL_ARGUMENTS, "element": 5510})
    assert route.call_count == 0
    assert not respx_mock.calls, "nothing sent, not even the login"
    refusal = raised.value
    table = params.packaged("element_QCL")
    labels = params.labels("element_QCL")
    assert isinstance(refusal, InvalidRequestError)
    assert (refusal.param, refusal.value, refusal.list_name) == ("element", "5510", "element_QCL")
    assert refusal.fetched == table.fetched
    assert ("2510", labels["2510"]) in refusal.closest, "the filter code of the rows' 5510"
    message = str(refusal)
    assert f"in the packaged element_QCL list (fetched {table.fetched:%Y-%m-%d})" in message
    assert f"2510 ({labels['2510']})" in message
    assert 'list_elements("QCL") lists the codes a filter takes' in message
    assert "not the element_code the rows print" in message


@pytest.mark.parametrize(
    ("arguments", "dimension", "code"),
    [
        ({"area": "99999", "year": 2020}, "area", "99999"),
        ({"area": ["231", "99999"], "year": 2020}, "area", "99999"),
        ({"area": "231", "item": "999999"}, "item", "999999"),
        ({"area": "231", "element": "1"}, "element", "1"),
    ],
)
def test_get_data_refuses_a_code_the_domain_table_lacks(
    respx_mock: respx.MockRouter, arguments: dict[str, Any], dimension: str, code: str
) -> None:
    name = f"{dimension}_QCL"
    assert code not in params.labels(name)
    with pytest.raises(UnknownCode) as raised:
        get_data("QCL", **arguments)
    assert not respx_mock.calls
    assert (raised.value.param, raised.value.value) == (dimension, code)
    assert raised.value.list_name == name
    assert raised.value.fetched == params.packaged(name).fetched
    assert f'{tasks.LIST_TASKS[dimension]}("QCL") lists the codes' in str(raised.value)


@pytest.mark.parametrize(
    ("arguments", "dimension", "label"),
    [({"area": "germany"}, "area", "germany"), ({"area": "231", "item": "wheat"}, "item", "wheat")],
)
def test_get_data_names_the_closest_codes_by_label(
    respx_mock: respx.MockRouter, arguments: dict[str, Any], dimension: str, label: str
) -> None:
    """A name given for a code: the refusal names the code whose label it is."""
    labels = params.labels(f"{dimension}_QCL")
    codes = [code for code, text in labels.items() if text.lower() == label]
    assert codes, f"the packaged {dimension}_QCL labels {label!r}"
    with pytest.raises(UnknownCode) as raised:
        get_data("QCL", **arguments)
    assert (codes[0], labels[codes[0]]) in raised.value.closest
    assert not respx_mock.calls


def test_get_data_sends_a_domain_without_a_table_unchecked(replay_fixture: ReplayFixture) -> None:
    """QV has no packaged table: an area code no table holds is sent, as before."""
    domain = "QV"
    assert domain not in params.DOMAINS
    assert all("99999" not in params.labels(f"area_{packaged}") for packaged in params.DOMAINS)
    fixture = recorded(GET_DATA, QCL)
    route = replay_fixture(
        GET_DATA, QCL, url=fixture.request.url.replace("/data/QCL?", f"/data/{domain}?")
    )
    replay_fixture(DOMAINS, "all")
    result = get_data(domain, area="99999", element="5510", item="999999")
    assert route.call_count == 1
    assert sent_query(route)["area"] == "99999"
    assert sent_query(route)["element"] == "5510"
    assert result.data == recorded_rows(QCL), "the recorded rows, served at QV's path"


@pytest.mark.parametrize(
    ("arguments", "sent"),
    [
        ({"area": "840", "area_cs": "M49", "item": "15"}, {"area": "840", "area_cs": "M49"}),
        ({"area": "231", "item": "01111", "item_cs": "CPC"}, {"item": "01111", "item_cs": "CPC"}),
    ],
)
def test_get_data_sends_another_coding_systems_codes_unchecked(
    replay_fixture: ReplayFixture, arguments: dict[str, Any], sent: dict[str, str]
) -> None:
    """The tables list FAO's codes: an area or item code of another system is not checked."""
    for name, value in sent.items():
        if not name.endswith("_cs"):
            assert value not in params.labels(f"{name}_QCL")
    route = replay_fixture(GET_DATA, QCL)
    replay_fixture(DOMAINS, "all")
    get_data("QCL", **arguments)
    assert route.call_count == 1
    assert {name: sent_query(route)[name] for name in sent} == sent


def test_get_data_checks_an_fao_coding_systems_codes(respx_mock: respx.MockRouter) -> None:
    with pytest.raises(UnknownCode):
        get_data("QCL", area="99999", area_cs="FAO")
    assert not respx_mock.calls


@pytest.mark.anyio
async def test_get_data_tool_answers_a_refusal_as_text(respx_mock: respx.MockRouter) -> None:
    text = await mcp_call_text(
        server, "faostat_get_data", {"domain": "QCL", "area": "231", "element": "5510"}
    )
    assert text.startswith("error: UnknownCode: '5510' is not an element"), text
    assert "element_QCL" in text
    assert not respx_mock.calls


def test_get_data_route_answers_a_refusal_with_422(respx_mock: respx.MockRouter) -> None:
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as http:
        answered = http.post("/faostat/get_data", json={"domain": "QCL", "element": "5510"})
    assert answered.status_code == 422
    assert "element_QCL" in answered.json()["detail"]
    assert not respx_mock.calls


def test_get_data_pp_keeps_its_months_columns(replay_fixture: ReplayFixture) -> None:
    case = "PP_231_2020_page_size_2"
    route = replay_fixture(GET_DATA, case)
    replay_fixture(DOMAINS, "all")
    result = get_data("PP", area=231, year=2020, page_size=2, page_number=1)
    assert sent_query(route) == recorded_query(recorded(GET_DATA, case))
    assert result.data == recorded_rows(case)
    assert len(result.data) == 2
    assert all(row.months_code is not None and row.months is not None for row in result.data)
    assert {row.note for row in result.data} == {None}, "PP prints no Note"
    assert all(isinstance(row.value, Decimal) for row in result.data)
    assert result.meta.vintage == date_update("PP")


@pytest.mark.parametrize("case", [QCL, "PP_231_2020_page_size_2"])
def test_the_recorded_rows_print_no_column_beyond_the_named_ones(case: str) -> None:
    assert {row.columns == {} for row in recorded_rows(case)} == {True}


def test_get_data_with_a_coding_system(replay_fixture: ReplayFixture) -> None:
    """``area_cs=M49``: the recorded answer names the code column ``Area Code (M49)``.

    United States of America's M49 code, 840, matched no rows on 2026-10-29; the answer's
    ``metadata.dsd`` still names its columns, which the next test applies to a row.
    """
    case = "QCL_840_M49_15_2510_2020"
    route = replay_fixture(GET_DATA, case)
    replay_fixture(DOMAINS, "all")
    result = get_data("QCL", area="840", area_cs="M49", item="15", element="2510", year=2020)
    assert sent_query(route) == recorded_query(recorded(GET_DATA, case))
    assert sent_query(route)["area_cs"] == "M49"
    assert result.data == recorded_rows(case) == []
    assert result.meta.request["area_cs"] == "M49"
    headers = [column.key for column in recorded_dsd(case)]
    assert "Area Code (M49)" in headers
    assert "Area Code" not in headers


def test_get_data_with_fao_coding_systems_keeps_the_coded_columns(
    replay_fixture: ReplayFixture,
) -> None:
    """``area_cs=FAO`` and ``item_cs=FAO``: the recorded rows print both code columns renamed."""
    case = "QCL_231_FAO_15_FAO_2510_2020"
    route = replay_fixture(GET_DATA, case)
    replay_fixture(DOMAINS, "all")
    result = get_data(
        "QCL", area="231", area_cs="FAO", item="15", item_cs="FAO", element="2510", year=2020
    )
    assert sent_query(route) == recorded_query(recorded(GET_DATA, case))
    printed = json.loads(recorded(GET_DATA, case).response.body)["data"]
    assert len(result.data) == len(printed) == 1
    row, recorded_row = result.data[0], printed[0]
    assert row.area_code is None
    assert row.item_code is None
    assert row.columns == {
        "Area Code (FAO)": recorded_row["Area Code (FAO)"],
        "Item Code (FAO)": recorded_row["Item Code (FAO)"],
    }
    assert row.area == recorded_row["Area"]
    assert row.value == Decimal(recorded_row["Value"])
    assert result.meta.request["area_cs"] == "FAO"
    assert result.meta.request["item_cs"] == "FAO"


def test_a_coded_column_is_kept_in_columns_and_its_field_is_none() -> None:
    """QCL's first recorded row with its area code under the header the M49 answer prints.

    An in-memory mapping, no fixture: the value is the row's own, the test is about where
    the column lands.
    """
    printed = json.loads(recorded(GET_DATA, QCL).response.body)["data"][0]
    coded = next(
        column.key
        for column in recorded_dsd("QCL_840_M49_15_2510_2020")
        if column.key.startswith("Area Code")
    )
    renamed = {coded if header == "Area Code" else header: v for header, v in printed.items()}
    row = DataRecord.model_validate(renamed)
    assert row.area_code is None
    assert row.columns == {coded: printed["Area Code"]}
    assert row.item_code == printed["Item Code"], "the other columns as before"


def test_a_column_no_field_names_is_kept_in_columns() -> None:
    """A row as an in-memory mapping (no fixture): QCL's first row and one column more."""
    printed = json.loads(recorded(GET_DATA, QCL).response.body)["data"][0]
    row = DataRecord.model_validate({**printed, "Extra Column": "x", "Other": None})
    assert row.columns == {"Extra Column": "x", "Other": None}
    assert row.area_code == printed["Area Code"]
    assert not set(row.columns) & set(printed), "no named column is in columns too"
    assert DataRecord.model_validate(row.model_dump()) == row, "a dump by name round-trips"
    assert row.model_dump(mode="json")["columns"] == {"Extra Column": "x", "Other": None}


@pytest.mark.parametrize(
    "arguments",
    [{}, {"area": None, "item": None, "element": None, "year": None}, {"page_size": 2}],
)
def test_get_data_without_a_filter_is_refused_before_sending(
    respx_mock: respx.MockRouter, arguments: dict[str, Any]
) -> None:
    with pytest.raises(InvalidRequestError) as raised:
        get_data("QCL", **arguments)
    assert f'"{FILTER_REFUSAL}"' in str(raised.value)
    assert "area, item, element or year" in str(raised.value)
    assert not respx_mock.calls, "nothing sent, not even the login"


@pytest.mark.parametrize("empty", [[], ""])
def test_get_data_an_empty_filter_is_refused_before_sending(
    respx_mock: respx.MockRouter, empty: Any
) -> None:
    with pytest.raises(InvalidRequestError) as raised:
        get_data("QCL", area="231", year=empty)
    assert str(raised.value) == "year lists no code: give one code or several, or leave year out"
    assert not respx_mock.calls


def test_get_data_an_unknown_domain_is_not_found(replay_fixture: ReplayFixture) -> None:
    case = "XXX_unknown_domain_500"
    route = replay_fixture(GET_DATA, case)
    domains = replay_fixture(DOMAINS, "all")
    with pytest.raises(NotFoundError) as raised:
        get_data("XXX", area="231")
    assert sent_query(route) == recorded_query(recorded(GET_DATA, case))
    assert "no domain 'XXX'" in str(raised.value)
    assert domains.call_count == 0, "no release date looked up for a refused query"


@pytest.mark.anyio
async def test_the_wrapper_maps_upstream_refusal_of_a_query_without_a_filter(
    replay_fixture: ReplayFixture,
) -> None:
    route = replay_fixture(GET_DATA, "no_filter_500")
    with pytest.raises(InvalidRequestError) as raised:
        await api.get_data.get_data("en", "QCL")
    assert sent_query(route) == {}
    assert route.call_count == 1, "classify ends core's retries of the 500"
    assert FILTER_REFUSAL in str(raised.value)


def test_get_data_vintage_is_none_for_a_domain_the_list_lacks(
    replay_fixture: ReplayFixture,
) -> None:
    """The QCL rows served at an unlisted domain's path: the release date look-up finds none."""
    domain = "QCX"
    assert domain not in {row.domain_code for row in recorded_domains()}
    fixture = recorded(GET_DATA, QCL)
    replay_fixture(GET_DATA, QCL, url=fixture.request.url.replace("/data/QCL?", f"/data/{domain}?"))
    replay_fixture(DOMAINS, "all")
    result = get_data(domain, **QCL_ARGUMENTS)
    assert result.meta.vintage is None


@pytest.mark.anyio
async def test_get_data_tool_end_to_end(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture(GET_DATA, QCL)
    replay_fixture(DOMAINS, "all")
    payload = await mcp_call(
        server,
        "faostat_get_data",
        {"domain": "QCL", "area": "231", "element": "2510", "item": "15", "year": [2015, 2021]},
    )
    assert sent_query(route)["year"] == "2015,2021"
    assert len(payload["data"]) == 7, "the recorded answer, served whatever the years"
    assert payload["data"][0]["value"] == 55839540, "a Decimal is a JSON number"
    assert payload["data"][0]["element_code"] == "5510"
    assert payload["data"][0]["columns"] == {}
    assert "note" not in payload, "7 rows, under the cap"
    assert payload["meta"]["endpoint"] == "get_data"
    assert payload["meta"]["vintage"] == date_update("QCL")
    assert payload["meta"]["published_at"] is None


@pytest.mark.anyio
async def test_get_data_tool_cap_note_names_paging(replay_fixture: ReplayFixture) -> None:
    """``MCP_CAPS``'s note, through a server built as ``mcp.py`` builds it, rows cut to 2."""
    replay_fixture(GET_DATA, QCL)
    replay_fixture(DOMAINS, "all")
    cap = tasks.MCP_CAPS["get_data"]
    assert cap.max_rows == 200
    narrow = build_server(
        SOURCE, [tasks.get_data], caps={"get_data": dataclasses.replace(cap, max_rows=2)}
    )
    payload = await mcp_call(narrow, "faostat_get_data", {"domain": "QCL", **QCL_ARGUMENTS})
    assert len(payload["data"]) == 2
    shown = f"showing 2 of 7 rows (cap: 2 rows or {cap.max_bytes} bytes)"
    assert payload["note"] == f"{shown}; {cap.note}"
    assert "page_size and page_number" in payload["note"]


def test_get_data_route_takes_a_json_body(replay_fixture: ReplayFixture) -> None:
    """The filters take lists, so the route is a POST (ADR-0007)."""
    route = replay_fixture(GET_DATA, QCL)
    replay_fixture(DOMAINS, "all")
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as http:
        answered = http.post("/faostat/get_data", json={"domain": "QCL", **QCL_ARGUMENTS})
    assert answered.status_code == 200
    assert sent_query(route) == recorded_query(recorded(GET_DATA, QCL))
    assert len(answered.json()["data"]) == 7


SERIES = ("QCL", "231", "15", "2510")
"""``get_series``'s domain, area, item and element: wheat production in the United States."""
SERIES_FILTERS = ["area", "item", "element", "year"]
"""The recorded query parameters a ``get_series`` replay must send as recorded."""


def test_get_series_qcl(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture(GET_DATA, QCL, match_params=SERIES_FILTERS)
    domains = replay_fixture(DOMAINS, "all")
    before = datetime.now(UTC)
    result = get_series(*SERIES, since=2015, until=2021)
    after = datetime.now(UTC)
    assert route.call_count == 1
    assert sent_query(route) == recorded_query(recorded(GET_DATA, QCL))
    assert domains.call_count == 1, "the release date, as get_data looks it up"
    assert result.data == recorded_rows(QCL)
    assert [row.year for row in result.data] == [str(year) for year in range(2015, 2022)]
    assert {(row.area_code, row.item_code, row.element_code) for row in result.data} == {
        ("231", "15", "5510")
    }, "the answer's element code, not the 2510 sent"
    assert all(isinstance(row.value, Decimal) for row in result.data)
    meta = result.meta
    assert meta.source == SOURCE
    assert meta.endpoint == "get_data"
    assert_time_between(meta.retrieved_at, before, after)
    assert meta.published_at is None
    assert meta.published_at_naive is False
    assert meta.vintage == date_update("QCL")
    assert meta.total is None
    assert meta.request == {
        "lang": "en",
        "domain_code": "QCL",
        "area": "231",
        "item": "15",
        "element": "2510",
        "year": "2015,2016,2017,2018,2019,2020,2021",
        **SENT_OPTIONS,
        "since": 2015,
        "until": 2021,
    }


def test_get_series_without_since_and_until_sends_no_year_filter(
    replay_fixture: ReplayFixture,
) -> None:
    """Every year the domain holds: no ``year`` filter; the recorded answer served at its path."""
    route = replay_fixture(GET_DATA, QCL)
    replay_fixture(DOMAINS, "all")
    result = get_series(*SERIES)
    recorded_filters = recorded_query(recorded(GET_DATA, QCL))
    assert "year" not in sent_query(route)
    assert sent_query(route) == {
        name: value for name, value in recorded_filters.items() if name != "year"
    }
    assert result.data == recorded_rows(QCL)
    assert "year" not in result.meta.request
    assert "since" not in result.meta.request
    assert "until" not in result.meta.request
    assert result.meta.vintage == date_update("QCL")


@pytest.mark.parametrize(
    ("since", "until", "alone"), [(2015, None, "since"), (None, 2021, "until")]
)
def test_get_series_refuses_one_of_since_and_until(
    respx_mock: respx.MockRouter, since: int | None, until: int | None, alone: str
) -> None:
    with pytest.raises(InvalidRequestError) as raised:
        get_series(*SERIES, since=since, until=until)
    message = str(raised.value)
    assert message.startswith("since and until go together: give both"), message
    assert message.endswith(f"{alone} came alone")
    assert not isinstance(raised.value, UnknownCode)
    assert not respx_mock.calls, "nothing sent, not even the login"


def test_get_series_refuses_since_after_until(respx_mock: respx.MockRouter) -> None:
    with pytest.raises(InvalidRequestError) as raised:
        get_series(*SERIES, since=2021, until=2015)
    assert str(raised.value) == (
        "since 2021 is after until 2015: since is the first year of the series and until the last"
    )
    assert not respx_mock.calls


def test_get_series_one_year(replay_fixture: ReplayFixture) -> None:
    """``since`` equal to ``until``: one year in the filter."""
    route = replay_fixture(GET_DATA, QCL)
    replay_fixture(DOMAINS, "all")
    result = get_series(*SERIES, since=2020, until=2020)
    assert sent_query(route)["year"] == "2020"
    assert result.meta.request["year"] == "2020"
    assert (result.meta.request["since"], result.meta.request["until"]) == (2020, 2020)


def test_get_series_checks_codes_as_get_data_does(respx_mock: respx.MockRouter) -> None:
    """The rows' element code is refused before sending, by ``get_data``'s own check."""
    with pytest.raises(UnknownCode) as raised:
        get_series("QCL", "231", "15", "5510", since=2015, until=2021)
    assert (raised.value.param, raised.value.value, raised.value.list_name) == (
        "element",
        "5510",
        "element_QCL",
    )
    assert ("2510", params.labels("element_QCL")["2510"]) in raised.value.closest
    assert not respx_mock.calls


@pytest.mark.anyio
async def test_get_series_tool_end_to_end(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture(GET_DATA, QCL, match_params=SERIES_FILTERS)
    replay_fixture(DOMAINS, "all")
    domain, area, item, element = SERIES
    arguments = {"domain": domain, "area": area, "item": item, "element": element}
    payload = await mcp_call(
        server, "faostat_get_series", {**arguments, "since": 2015, "until": 2021}
    )
    assert sent_query(route) == recorded_query(recorded(GET_DATA, QCL))
    assert [row["year"] for row in payload["data"]] == [str(year) for year in range(2015, 2022)]
    assert "note" not in payload, "7 rows, under the cap"
    assert payload["meta"]["endpoint"] == "get_data"
    assert payload["meta"]["vintage"] == date_update("QCL")
    assert (payload["meta"]["request"]["since"], payload["meta"]["request"]["until"]) == (
        2015,
        2021,
    )


@pytest.mark.anyio
async def test_get_series_tool_cap_note_names_since_and_until(
    replay_fixture: ReplayFixture,
) -> None:
    """``MCP_CAPS``'s note, through a server built as ``mcp.py`` builds it, rows cut to 2."""
    replay_fixture(GET_DATA, QCL, match_params=SERIES_FILTERS)
    replay_fixture(DOMAINS, "all")
    cap = tasks.MCP_CAPS["get_series"]
    assert cap.max_rows == 200
    narrow = build_server(
        SOURCE, [tasks.get_series], caps={"get_series": dataclasses.replace(cap, max_rows=2)}
    )
    domain, area, item, element = SERIES
    payload = await mcp_call(
        narrow,
        "faostat_get_series",
        {
            "domain": domain,
            "area": area,
            "item": item,
            "element": element,
            "since": 2015,
            "until": 2021,
        },
    )
    assert [row["year"] for row in payload["data"]] == ["2015", "2016"]
    shown = f"showing 2 of 7 rows (cap: 2 rows or {cap.max_bytes} bytes)"
    assert payload["note"] == f"{shown}; {cap.note}"
    assert "narrow since and until, or one code per dimension" in payload["note"]


def test_list_domains(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture(DOMAINS, "all")
    before = datetime.now(UTC)
    result = list_domains()
    after = datetime.now(UTC)
    assert sent_query(route) == {}
    assert result.data == recorded_domains()
    assert len(result.data) == len(json.loads(recorded(DOMAINS, "all").response.body)["data"])
    qcl = next(row for row in result.data if row.domain_code == "QCL")
    assert qcl.domain_name == "Crops and livestock products"
    assert qcl.focal_point is not None
    subgroups = [row for row in result.data if row.subgroup_flag == "1"]
    assert subgroups, "the recorded list holds subgroups"
    assert all(row.date_update is None and row.domain_level == 1 for row in subgroups)
    meta = result.meta
    assert meta.source == SOURCE
    assert meta.endpoint == "get_groupsanddomains"
    assert_time_between(meta.retrieved_at, before, after)
    assert meta.vintage is None
    assert meta.published_at is None
    assert meta.total is None
    assert meta.request == {"lang": "en"}


@pytest.mark.parametrize("search", ["QCL", "crops", "PRICES", "land use"])
def test_list_domains_search(replay_fixture: ReplayFixture, search: str) -> None:
    replay_fixture(DOMAINS, "all")
    result = list_domains(search=search)
    expected = [
        row
        for row in recorded_domains()
        if matches(search, row.domain_code, row.domain_name, row.group_name)
    ]
    assert result.data == expected
    assert result.data, f"the recorded list has a row for {search!r}"
    assert result.meta.request == {"lang": "en", "search": search}


def test_list_domains_search_matches_code_name_and_group(replay_fixture: ReplayFixture) -> None:
    replay_fixture(DOMAINS, "all")
    assert [row.domain_code for row in list_domains(search="qcl").data] == ["QCL"]
    crops = {row.domain_code for row in list_domains(search="crops and livestock").data}
    assert {"QCL", "TCL"} <= crops, "production and trade both name it"
    prices = list_domains(search="prices").data
    assert "PP" in {row.domain_code for row in prices}
    assert list_domains(search="no such domain anywhere").data == []


@pytest.mark.anyio
async def test_list_domains_tool_end_to_end(replay_fixture: ReplayFixture) -> None:
    replay_fixture(DOMAINS, "all")
    payload = await mcp_call(server, "faostat_list_domains", {"search": "QCL"})
    assert [row["domain_code"] for row in payload["data"]] == ["QCL"]
    assert payload["data"][0]["focal_point"] is not None
    assert payload["meta"]["endpoint"] == "get_groupsanddomains"
    assert payload["meta"]["request"] == {"lang": "en", "search": "QCL"}


LIST_TASKS = [(list_areas, "area"), (list_elements, "element"), (list_items, "item")]


def packaged_codes(dimension: str, domain: str) -> list[CodeItem]:
    """The packaged table's codes as the list task must return them."""
    return params.packaged(f"{dimension}_{domain}").parse(CodeItem, source=SOURCE)


@pytest.mark.parametrize("domain", params.DOMAINS)
@pytest.mark.parametrize(("task", "dimension"), LIST_TASKS, ids=[d for _, d in LIST_TASKS])
def test_list_task_answers_the_packaged_table(
    respx_mock: respx.MockRouter, task: Any, dimension: str, domain: str
) -> None:
    result = task(domain)
    table = params.packaged(f"{dimension}_{domain}")
    assert result.data == packaged_codes(dimension, domain)
    assert len(result.data) == len(table.records)
    assert all(isinstance(code, CodeItem) for code in result.data)
    meta = result.meta
    assert meta.source == SOURCE
    assert meta.endpoint == "getCodeList"
    assert meta.retrieved_at == table.fetched, "the packaged file's fetch time"
    assert meta.published_at is None
    assert meta.vintage is None, "a fetch date is no vintage"
    assert meta.total is None
    assert meta.request == {"lang": "en", "dimension_id": dimension, "domain_code": domain}
    assert not respx_mock.calls, "answered from the package"


@pytest.mark.parametrize(
    ("task", "dimension", "domain", "search"),
    [
        (list_areas, "area", "QCL", "united"),
        (list_areas, "area", "TCL", "231"),
        (list_areas, "area", "RL", "AFRICA"),
        (list_elements, "element", "QCL", "production"),
        (list_elements, "element", "TCL", "export"),
        (list_items, "item", "QCL", "wheat"),
        (list_items, "item", "FBS", "Wheat"),
        (list_items, "item", "PP", "15"),
    ],
)
def test_list_task_search(task: Any, dimension: str, domain: str, search: str) -> None:
    result = task(domain, search=search)
    expected = [
        code for code in packaged_codes(dimension, domain) if matches(search, code.code, code.label)
    ]
    assert result.data == expected
    assert result.data, f"the packaged {dimension}_{domain} has a code for {search!r}"
    assert len(result.data) < len(packaged_codes(dimension, domain))
    assert result.meta.request["search"] == search


@pytest.mark.parametrize(("task", "dimension"), LIST_TASKS, ids=[d for _, d in LIST_TASKS])
def test_list_task_search_without_a_hit(task: Any, dimension: str) -> None:
    result = task("QCL", search="no such code anywhere")
    assert result.data == []
    assert result.meta.endpoint == "getCodeList"


@pytest.mark.parametrize(("task", "dimension"), LIST_TASKS, ids=[d for _, d in LIST_TASKS])
def test_list_task_refuses_a_domain_without_a_table(
    respx_mock: respx.MockRouter, task: Any, dimension: str
) -> None:
    with pytest.raises(InvalidRequestError) as raised:
        task("QV")
    message = str(raised.value)
    assert not isinstance(raised.value, UnknownCode)
    assert "QCL, TCL, FBS, PP, RL, not 'QV'" in message
    assert "get_data sends another domain's codes unchecked" in message
    assert not respx_mock.calls
    with pytest.raises(InvalidRequestError, match=r"Did you mean QCL\?"):
        task("qcl")


@pytest.mark.anyio
async def test_list_elements_tool_end_to_end() -> None:
    payload = await mcp_call(server, "faostat_list_elements", {"domain": "QCL"})
    assert [row["code"] for row in payload["data"]] == [
        code.code for code in packaged_codes("element", "QCL")
    ]
    assert payload["data"][0]["columns"] == {}
    assert "note" not in payload, "a whole table, under the cap"
    assert payload["meta"]["endpoint"] == "getCodeList"
    assert payload["meta"]["request"] == {
        "lang": "en",
        "dimension_id": "element",
        "domain_code": "QCL",
    }


@pytest.mark.anyio
async def test_list_items_tool_search(respx_mock: respx.MockRouter) -> None:
    payload = await mcp_call(server, "faostat_list_items", {"domain": "QCL", "search": "wheat"})
    assert [row["code"] for row in payload["data"]] == [
        code.code
        for code in packaged_codes("item", "QCL")
        if matches("wheat", code.code, code.label)
    ]
    assert payload["meta"]["request"]["search"] == "wheat"
    assert not respx_mock.calls


@pytest.mark.parametrize("name", ["list_areas", "list_elements", "list_items"])
@pytest.mark.anyio
async def test_list_task_tool_cap_note_names_search(name: str) -> None:
    """``MCP_CAPS``'s note, through a server built as ``mcp.py`` builds it, rows cut to 2."""
    cap = tasks.MCP_CAPS[name]
    assert cap.max_rows == 1000
    assert cap.note is not None
    assert cap.note.startswith("pass search")
    narrow = build_server(
        SOURCE, [getattr(tasks, name)], caps={name: dataclasses.replace(cap, max_rows=2)}
    )
    payload = await mcp_call(narrow, f"faostat_{name}", {"domain": "QCL"})
    dimension = name.removeprefix("list_").removesuffix("s")
    total = len(params.packaged(f"{dimension}_QCL").records)
    assert len(payload["data"]) == 2
    assert (
        payload["note"]
        == f"showing 2 of {total} rows (cap: 2 rows or {cap.max_bytes} bytes); {cap.note}"
    )


def test_list_areas_route_is_a_get() -> None:
    """Every parameter is a scalar, so the route is a GET with a query (ADR-0007)."""
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as http:
        answered = http.get("/faostat/list_areas", params={"domain": "QCL", "search": "united"})
    assert answered.status_code == 200
    expected = [
        code.code
        for code in packaged_codes("area", "QCL")
        if matches("united", code.code, code.label)
    ]
    assert [row["code"] for row in answered.json()["data"]] == expected


CATALOGUE = "datasets_e"
DOWNLOAD = "download_dataset"
BULK_HOST = "bulks-faostat.fao.org"


def recorded_catalogue() -> list[BulkDataset]:
    body = recorded(CATALOGUE, "all").response.body
    return DatasetsCatalogue.model_validate_json(body).datasets.dataset


def recorded_dataset(code: str) -> BulkDataset:
    return next(dataset for dataset in recorded_catalogue() if dataset.dataset_code == code)


def sent_without_the_account(respx_mock: respx.MockRouter) -> bool:
    """Whether every request went to the bulk host without an ``Authorization`` header.

    Hosts and header presence only: no request is kept in the test's frame.
    """
    return all(
        call.request.url.host == BULK_HOST and "authorization" not in call.request.headers
        for call in respx_mock.calls
    )


def test_list_bulk_datasets(replay_fixture: ReplayFixture, respx_mock: respx.MockRouter) -> None:
    route = replay_fixture(CATALOGUE, "all")
    before = datetime.now(UTC)
    result = list_bulk_datasets()
    after = datetime.now(UTC)
    assert sent_urls(route) == [api.datasets_e.URL]
    assert sent_without_the_account(respx_mock)
    assert result.data == recorded_catalogue()
    assert all(isinstance(dataset, BulkDataset) for dataset in result.data)
    meta = result.meta
    assert meta.source == SOURCE
    assert meta.endpoint == "production/datasets_E.json"
    assert_time_between(meta.retrieved_at, before, after)
    assert meta.published_at is None
    assert meta.vintage is None, "the catalogue carries no version"
    assert meta.total is None
    assert meta.request == {}, "search left None is omitted"
    list_bulk_datasets(search="QCL")
    assert route.call_count == 1, "the second call is a cache hit"


@pytest.mark.parametrize("search", ["QCL", "qcl", "trade", "land use", "Diversity"])
def test_list_bulk_datasets_search(replay_fixture: ReplayFixture, search: str) -> None:
    replay_fixture(CATALOGUE, "all")
    result = list_bulk_datasets(search=search)
    expected = [
        dataset
        for dataset in recorded_catalogue()
        if matches(search, dataset.dataset_code, dataset.dataset_name)
    ]
    assert result.data == expected
    assert result.data, f"the recorded catalogue has a dataset for {search!r}"
    assert result.meta.request == {"search": search}


def test_list_bulk_datasets_search_matches_code_and_name_only(
    replay_fixture: ReplayFixture,
) -> None:
    replay_fixture(CATALOGUE, "all")
    assert [dataset.dataset_code for dataset in list_bulk_datasets(search="rl").data] == [
        dataset.dataset_code
        for dataset in recorded_catalogue()
        if "rl" in dataset.dataset_code.lower() or "rl" in dataset.dataset_name.lower()
    ]
    catalogue = recorded_catalogue()
    topic = recorded_dataset("MDDW").topic or ""
    only_in_topic = next(
        word
        for word in topic.split()
        if word.isalpha()
        and not any(matches(word, row.dataset_code, row.dataset_name) for row in catalogue)
    )
    assert list_bulk_datasets(search=only_in_topic).data == [], "the topic is not searched"
    assert list_bulk_datasets(search="no such dataset anywhere").data == []


@pytest.mark.anyio
async def test_list_bulk_datasets_tool_end_to_end(
    replay_fixture: ReplayFixture, respx_mock: respx.MockRouter
) -> None:
    replay_fixture(CATALOGUE, "all")
    payload = await mcp_call(server, "faostat_list_bulk_datasets", {"search": "land use"})
    expected = [
        dataset.dataset_code
        for dataset in recorded_catalogue()
        if matches("land use", dataset.dataset_code, dataset.dataset_name)
    ]
    assert [row["dataset_code"] for row in payload["data"]] == expected
    assert isinstance(payload["data"][0]["file_rows"], int)
    assert payload["meta"]["endpoint"] == "production/datasets_E.json"
    assert payload["meta"]["request"] == {"search": "land use"}
    assert "note" not in payload
    assert sent_without_the_account(respx_mock)


@pytest.mark.anyio
async def test_list_bulk_datasets_tool_serves_the_whole_catalogue_uncut(
    replay_fixture: ReplayFixture,
) -> None:
    """The cap of its own (ADR-0016) serves every dataset of the recorded catalogue, no note."""
    replay_fixture(CATALOGUE, "all")
    cap = tasks.MCP_CAPS["list_bulk_datasets"]
    assert cap.note is not None
    assert cap.note.startswith("pass search")
    payload = await mcp_call(server, "faostat_list_bulk_datasets", {})
    assert [row["dataset_code"] for row in payload["data"]] == [
        dataset.dataset_code for dataset in recorded_catalogue()
    ], "every dataset, in the catalogue's order"
    assert "note" not in payload, "uncut"


@pytest.mark.anyio
async def test_list_bulk_datasets_tool_cap_note_names_search(
    replay_fixture: ReplayFixture,
) -> None:
    """``MCP_CAPS``'s note, through a server built as ``mcp.py`` builds it, rows cut to 2."""
    replay_fixture(CATALOGUE, "all")
    cap = tasks.MCP_CAPS["list_bulk_datasets"]
    narrow = build_server(
        SOURCE,
        [tasks.list_bulk_datasets],
        caps={"list_bulk_datasets": dataclasses.replace(cap, max_rows=2)},
    )
    payload = await mcp_call(narrow, "faostat_list_bulk_datasets", {})
    total = len(recorded_catalogue())
    assert len(payload["data"]) == 2
    assert payload["note"] == (
        f"showing 2 of {total} rows (cap: 2 rows or {cap.max_bytes} bytes); {cap.note}"
    )


def test_list_bulk_datasets_route_is_a_get(replay_fixture: ReplayFixture) -> None:
    replay_fixture(CATALOGUE, "all")
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as http:
        answered = http.get("/faostat/list_bulk_datasets", params={"search": "QCL"})
    assert answered.status_code == 200
    assert [row["dataset_code"] for row in answered.json()["data"]] == ["QCL"]


def test_download_dataset_mddw(
    replay_fixture: ReplayFixture, respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    catalogue = replay_fixture(CATALOGUE, "all")
    fixture = recorded(DOWNLOAD, "MDDW")
    route = replay_fixture(DOWNLOAD, "MDDW")
    mddw = recorded_dataset("MDDW")
    dest = tmp_path / "MDDW.zip"
    before = datetime.now(UTC)
    result = download_dataset("MDDW", dest)
    after = datetime.now(UTC)
    assert sent_urls(catalogue) == [api.datasets_e.URL]
    assert sent_urls(route) == [mddw.file_location] == [fixture.request.url]
    assert sent_without_the_account(respx_mock), "the token never goes to the bulk host"
    downloaded = result.data
    assert isinstance(downloaded, Downloaded)
    assert downloaded.path == dest
    assert dest.read_bytes() == fixture.response.content, "the recorded ZIP, byte for byte"
    assert downloaded.bytes == len(fixture.response.content)
    headers = dict(fixture.response.headers)
    assert downloaded.content_type == headers["content-type"]
    assert downloaded.etag == headers["etag"]
    assert downloaded.last_modified == headers["last-modified"]
    assert_time_between(downloaded.retrieved_at, before, after)
    assert list(tmp_path.iterdir()) == [dest], "no partial file left behind"
    meta = result.meta
    assert meta.source == SOURCE
    assert meta.endpoint == "All_Data_(Normalized).csv"
    assert meta.vintage == mddw.date_update
    assert meta.published_at == datetime.fromisoformat(mddw.date_update)
    assert meta.published_at.tzinfo is None, "a time printed without a zone"
    assert meta.published_at_naive is True
    assert meta.request == {"domain": "MDDW", "url": mddw.file_location}
    assert meta.total is None
    assert_time_between(meta.retrieved_at, before, after)
    rows = list(parse_bulk_csv(dest))
    assert rows, "the downloaded ZIP reads"
    assert rows == list(parse_bulk_csv(Path(__file__).parent / "fixtures/files/bulk-csv/MDDW.zip"))


def test_download_dataset_refuses_a_domain_the_catalogue_lacks(
    replay_fixture: ReplayFixture, tmp_path: Path
) -> None:
    replay_fixture(CATALOGUE, "all")
    route = replay_fixture(DOWNLOAD, "MDDW")
    with pytest.raises(NotFoundError) as raised:
        download_dataset("mddw", tmp_path / "MDDW.zip")
    assert route.call_count == 0, "no file requested"
    assert str(raised.value) == (
        "FAOSTAT's bulk catalogue lists no dataset 'mddw'. Did you mean MDDW? "
        "list_bulk_datasets lists them"
    )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("where", ["directory", "missing"])
def test_download_dataset_refuses_a_dest_it_cannot_write(
    respx_mock: respx.MockRouter, tmp_path: Path, where: str
) -> None:
    dest = tmp_path if where == "directory" else tmp_path / "missing" / "MDDW.zip"
    with pytest.raises(InvalidRequestError, match=r"^dest"):
        download_dataset("MDDW", dest)
    assert not respx_mock.calls, "refused before any request"


def test_download_dataset_is_served_by_no_adapter() -> None:
    """A bulk task: no MCP tool, no route (ADR-0019 decision 4); the catalogue task is both."""
    assert {"download_dataset"} == tasks.BULK_TASKS
    assert "download_dataset" in tasks.__all__
    tools = {tool.name for tool in run(server.list_tools())}
    assert "faostat_download_dataset" not in tools
    assert "faostat_list_bulk_datasets" in tools
    paths = {getattr(route, "path", None) for route in router.routes}
    assert "/faostat/download_dataset" not in paths
    assert "/faostat/list_bulk_datasets" in paths
