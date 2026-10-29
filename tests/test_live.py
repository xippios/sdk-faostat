"""Live smoke tests, one per task, skipped unless XIPPIOS_LIVE_TESTS=1 (conventions §10).

``/add-endpoint`` adds them, next to the reachability check.

They need the FAO account: ``FAOSTAT_USERNAME`` and ``FAOSTAT_PASSWORD`` in the
environment (``live.yml`` passes the org secrets to its ``pytest -m live`` step only).
``get_data`` has one per domain of the design round's question 5 (G5, 2026-10-29): QCL,
TCL, FBS, PP and RL, each on the smallest slice with codes every one of them has, the
United States of America (area 231) in 2020, cut to its first five rows with
``page_size=5`` and ``page_number=1``. ``get_series`` has one, on the replay tests'
slice: wheat production in the United States of America, 2015 to 2021, QCL's
``area`` 231, ``item`` 15 and ``element`` 2510. ``list_domains`` has one. The three code-list
tasks answer from the packaged tables: ``list_elements``'s test fetches
``codes/element/QCL`` through ``api.get_code_list``, as the refresh script does, and
checks that upstream's answer still has the packaged table's shape, its fields, every
code and label non-empty, and every packaged code present; ``list_areas``'s and
``list_items``'s read the packaged tables of the five domains, without a request. A run
sends nine keyed requests: one login, five data requests, one ``groupsanddomains``
request, the first domain's release-date look-up, one data request for ``get_series``,
and one ``getCodeList`` request; the other look-ups, ``get_series``'s among them, and
``list_domains`` answer from the client's cache, which lives for the run, and each
``get_data`` test's check that every column the answer prints is named or kept in
``columns`` reads its data request from the cache as well. The reachability check sends
one more request, without the account. The bulk tasks have one each, without the
account: ``list_bulk_datasets``'s fetches the catalogue, and ``download_dataset``'s
downloads MDDW's ZIP, the smallest dataset's (12 KB), to a temporary file and reads it
with ``parse_bulk_csv``, the live parser test of the file kind ``bulk-csv`` (ADR-0020
decision 6), its look-up in the catalogue a cache hit: two requests, and a guard fails
either test if a request goes through the account's login. The tests assert shape and
release metadata, never values, which FAOSTAT revises.
"""

import csv
import io
import re
import zipfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from xippios.core.testing import assert_time_between

from xippios.faostat import api, params, tasks
from xippios.faostat._client import BASE_URL, auth, config
from xippios.faostat.models import BulkDataset, BulkRecord, CodeItem, DataRecord, Domain
from xippios.faostat.parse import parse_bulk_csv
from xippios.faostat.parse.bulk_csv import MEMBER_SUFFIX

pytestmark = [pytest.mark.live, pytest.mark.anyio]

DOMAINS = ("QCL", "TCL", "FBS", "PP", "RL")
"""The domains of G5's question 5: production, trade, food balances, prices, land use."""
SLICE: dict[str, Any] = {"area": "231", "year": 2020, "page_size": 5, "page_number": 1}
"""The smallest slice with codes every domain has: one area, one year, five rows."""
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
"""``date_update`` as ``groupsanddomains`` prints it, e.g. ``2025-12-31``."""
HEADERS = {
    field.validation_alias for field in DataRecord.model_fields.values() if field.validation_alias
}
"""The columns ``DataRecord`` reads, under the headers upstream prints."""


async def test_upstream_answers() -> None:
    """The base URL answers without a server error.

    A plain request, not the package's client, without the account; any answer below
    500 (a 404 at the root, say) shows the host is up.
    """
    async with httpx.AsyncClient(
        headers={"User-Agent": config.user_agent},
        timeout=config.timeouts.to_httpx(),
        follow_redirects=True,
    ) as http:
        response = await http.get(BASE_URL)
    assert response.status_code < 500


@pytest.mark.parametrize("domain", DOMAINS)
async def test_get_data(domain: str) -> None:
    before = datetime.now(UTC)
    result = await tasks.get_data_async(domain, **SLICE)
    after = datetime.now(UTC)
    rows = result.data
    assert 0 < len(rows) <= 5, "one page of at most five rows"
    assert all(isinstance(row, DataRecord) for row in rows)
    assert {row.domain_code for row in rows} == {domain}
    assert {row.area_code for row in rows} == {"231"}
    assert {row.year for row in rows} == {"2020"}
    assert all(isinstance(row.value, Decimal | str | None) for row in rows)
    meta = result.meta
    assert meta.endpoint == "get_data"
    assert meta.vintage is not None
    assert DATE.fullmatch(meta.vintage)
    assert meta.published_at is None
    assert meta.total is None
    assert_time_between(meta.retrieved_at, before, after)
    # The same request through the wrapper: a cache hit, no request; its columns.
    answer = await api.get_data.get_data(
        "en",
        domain,
        area="231",
        year="2020",
        page_size=5,
        page_number=1,
        show_codes=True,
        show_unit=True,
        show_flags=True,
        show_notes=True,
        null_values=False,
        output_type="objects",
    )
    printed = {column.key for column in answer.response.metadata.dsd}
    assert all(printed - HEADERS <= set(row.columns) for row in answer.response.data), (
        f"{domain}: a column neither named nor kept in columns"
    )


async def test_get_series() -> None:
    """One data request, the years 2015 to 2021 as the year filter; years oldest first."""
    before = datetime.now(UTC)
    result = await tasks.get_series_async("QCL", "231", "15", "2510", since=2015, until=2021)
    after = datetime.now(UTC)
    rows = result.data
    years = [row.year for row in rows]
    assert 0 < len(rows) <= 7, "at most one row a year"
    assert all(isinstance(row, DataRecord) for row in rows)
    assert {(row.domain_code, row.area_code, row.item_code) for row in rows} == {
        ("QCL", "231", "15")
    }
    assert set(years) <= {str(year) for year in range(2015, 2022)}
    assert years == sorted(years), "upstream's order, year ascending"
    assert all(isinstance(row.value, Decimal | str | None) for row in rows)
    meta = result.meta
    assert meta.endpoint == "get_data"
    assert meta.request["year"] == ",".join(str(year) for year in range(2015, 2022))
    assert (meta.request["since"], meta.request["until"]) == (2015, 2021)
    assert meta.vintage is not None
    assert DATE.fullmatch(meta.vintage)
    assert meta.published_at is None
    assert meta.total is None
    assert_time_between(meta.retrieved_at, before, after)


async def test_list_domains() -> None:
    result = await tasks.list_domains_async()
    assert result.data
    assert all(isinstance(row, Domain) for row in result.data)
    listed = {row.domain_code: row for row in result.data}
    assert set(DOMAINS) <= set(listed), "every domain the data tests read is listed"
    assert all(DATE.fullmatch(listed[domain].date_update or "") for domain in DOMAINS)
    assert result.meta.endpoint == "get_groupsanddomains"
    assert result.meta.vintage is None
    assert result.meta.total is None


async def test_list_elements() -> None:
    """``codes/element/QCL`` as upstream serves it still has the packaged table's shape.

    One ``getCodeList`` request through the wrapper the refresh script fetches with.
    """
    answer = await api.get_code_list.get_code_list("en", "element", "QCL")
    live = answer.response.data
    table = params.packaged("element_QCL")
    assert live
    assert all(isinstance(code, CodeItem) and code.code and code.label for code in live)
    assert {tuple(code.dump_upstream()) for code in live} == {
        tuple(record) for record in table.records
    }, "the packaged table's fields"
    missing = {record["code"] for record in table.records} - {code.code for code in live}
    assert len(missing) == 0, "packaged codes upstream no longer lists: refresh the tables"
    result = await tasks.list_elements_async("QCL")
    assert result.data == table.parse(CodeItem, source="faostat")
    assert result.meta.endpoint == "getCodeList"
    assert result.meta.retrieved_at == table.fetched


@pytest.mark.parametrize("domain", DOMAINS)
async def test_list_areas(domain: str) -> None:
    """Answered from the packaged table, without a request; 231 is the data tests' area."""
    result = await tasks.list_areas_async(domain)
    assert result.data
    assert "231" in {code.code for code in result.data}, "the area the data tests read"
    assert result.meta.endpoint == "getCodeList"
    assert result.meta.retrieved_at == params.packaged(f"area_{domain}").fetched
    assert result.meta.vintage is None


@pytest.mark.parametrize("domain", DOMAINS)
async def test_list_items(domain: str) -> None:
    """Answered from the packaged table, without a request."""
    result = await tasks.list_items_async(domain)
    assert result.data
    assert all(code.code and code.label for code in result.data)
    assert result.meta.endpoint == "getCodeList"
    assert result.meta.retrieved_at == params.packaged(f"item_{domain}").fetched


DATE_UPDATE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
"""The catalogue's ``DateUpdate`` as printed, e.g. ``2026-10-02T00:00:00``, no zone."""
BULK_HEADERS = {
    field.validation_alias for field in BulkRecord.model_fields.values() if field.validation_alias
}
"""The columns ``BulkRecord`` names, under the headers the files print."""


@pytest.fixture
def without_the_account(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail a request that goes through the client's ``LoginAuth``: the bulk side sends none."""

    def refused(request: httpx.Request) -> Any:
        raise AssertionError(f"{request.method} {request.url.path} went through LoginAuth")

    monkeypatch.setattr(auth, "async_auth_flow", refused)


@pytest.mark.usefixtures("without_the_account")
async def test_list_bulk_datasets() -> None:
    """The catalogue: one request, without the account."""
    before = datetime.now(UTC)
    result = await tasks.list_bulk_datasets_async()
    after = datetime.now(UTC)
    rows = result.data
    assert rows
    assert all(isinstance(row, BulkDataset) for row in rows)
    codes = [row.dataset_code for row in rows]
    assert len(set(codes)) == len(codes), "one row per dataset"
    assert {"MDDW", *DOMAINS} <= set(codes), "the download test's and the data tests' domains"
    assert all(row.file_location.startswith(f"{api.datasets_e.BULK_URL}/") for row in rows)
    assert all(row.file_location.endswith(".zip") for row in rows)
    assert all(DATE_UPDATE.fullmatch(row.date_update) for row in rows)
    assert result.meta.endpoint == "production/datasets_E.json"
    assert result.meta.vintage is None
    assert result.meta.total is None
    assert_time_between(result.meta.retrieved_at, before, after)


@pytest.mark.usefixtures("without_the_account")
async def test_download_dataset_mddw(tmp_path: Path) -> None:
    """MDDW's ZIP, read with ``parse_bulk_csv``: every column of its table named or kept."""
    dest = tmp_path / "MDDW.zip"
    result = await tasks.download_dataset_async("MDDW", dest)
    assert result.data.path == dest
    assert result.data.bytes == dest.stat().st_size
    assert dest.read_bytes()[:4] == b"PK\x03\x04", "a ZIP"
    with zipfile.ZipFile(dest) as archive:
        tables = [name for name in archive.namelist() if name.endswith(MEMBER_SUFFIX)]
        assert len(tables) == 1, "one normalized table"
        with archive.open(tables[0]) as raw:
            header = next(csv.reader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")))
    rows = list(parse_bulk_csv(dest))
    assert rows, "the table has rows"
    assert all(isinstance(row, BulkRecord) for row in rows)
    others = [column for column in header if column not in BULK_HEADERS]
    assert all(list(row.columns) == others for row in rows), "every other column in columns"
    assert all(isinstance(row.value, Decimal | str | None) for row in rows)
    meta = result.meta
    assert meta.endpoint == "All_Data_(Normalized).csv"
    assert meta.vintage is not None
    assert DATE_UPDATE.fullmatch(meta.vintage)
    assert meta.published_at is not None
    assert meta.published_at.tzinfo is None
    assert meta.published_at_naive is True
    assert meta.request["domain"] == "MDDW"
    assert meta.request["url"].endswith("_All_Data_(Normalized).zip")
