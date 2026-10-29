"""Replay tests on recorded fixtures, at least one per task (conventions §10).

``/add-endpoint`` and ``/record-fixture`` add them.

The fixtures were recorded on 2026-10-29 through the package's client, with the FAO
account's token (``tests/test_client.py`` covers the login). ``get_data``'s are under
``tests/fixtures/get_data/``: ``QCL_231_2510_15_2015_2021``, wheat production in the
United States of America over seven years (7 rows); ``QCL_page_2``, the same query with
``page_size=2&page_number=2`` (rows 3 and 4); ``QCL_element_5510_empty``, the same query
with the answer's element code as the filter (no rows); ``PP_231_2020_page_size_2``, the
first two producer prices of 2020, whose rows carry ``Months Code`` and ``Months`` and no
``Note``; ``XXX_unknown_domain_500``, an unknown domain; ``no_filter_500``, a query
without a filter, sent through the wrapper since the task refuses it before sending.
``list_domains`` and ``get_data``'s release date read
``tests/fixtures/get_groupsanddomains/all.json`` (78 rows); the tests take the expected
values from it. Each test sends exactly the recorded query (``sent_query`` against
``recorded_query``).
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
from xippios.core import InvalidRequestError, NotFoundError, matches
from xippios.core.mcp import build_server
from xippios.core.testing import (
    Fixture,
    ReplayFixture,
    assert_time_between,
    load_fixture,
    mcp_call,
    recorded_query,
    sent_query,
)

from xippios.faostat import api, get_data, list_domains, tasks
from xippios.faostat._client import FILTER_REFUSAL, SOURCE, auth
from xippios.faostat.http import router
from xippios.faostat.mcp import server
from xippios.faostat.models import DataRecord, DataResponse, Domain, GroupsAndDomainsResponse

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


def test_get_data_an_unmatched_code_is_an_empty_list(replay_fixture: ReplayFixture) -> None:
    case = "QCL_element_5510_empty"
    route = replay_fixture(GET_DATA, case)
    replay_fixture(DOMAINS, "all")
    result = get_data("QCL", **{**QCL_ARGUMENTS, "element": 5510})
    assert sent_query(route) == recorded_query(recorded(GET_DATA, case))
    assert result.data == []
    assert result.meta.vintage == date_update("QCL")


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
