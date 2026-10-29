"""The endpoint wrappers' own tests: ``get_code_list`` and ``datasets_e`` on their recordings.

``tests/fixtures/get_code_list/`` holds ``getCodeList``'s answers for QCL, recorded on
2026-10-29 through the package's client with the account's token:
``codes/area/QCL``, ``codes/element/QCL``, ``codes/item/QCL`` and
``codes/countries/QCL``, none with ``show_lists``, so upstream's default applies.
``tests/fixtures/datasets_e/all.json`` is the bulk catalogue ``datasets_E.json``, recorded
later that day without the account, whole (107,107 bytes, a JSON object the recorder does
not cut); its body was the snapshot's ``docs/upstream/bulk/datasets_E.json`` byte for byte
then.
"""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import respx
from xippios.core.testing import (
    ReplayFixture,
    assert_time_between,
    load_fixture,
    sent_query,
    sent_urls,
)

from xippios.faostat import api
from xippios.faostat._client import auth
from xippios.faostat.models import BulkDataset, CodeItem, CodeResponse, DatasetsCatalogue

FIXTURES = Path(__file__).parent / "fixtures"
CODES = "get_code_list"
CATALOGUE = "datasets_e"

pytestmark = pytest.mark.anyio


def recorded(case: str) -> CodeResponse:
    body = load_fixture(FIXTURES / CODES / f"{case}.json").response.body
    return CodeResponse.model_validate_json(body)


@pytest.fixture(autouse=True)
def logged_in(replay_fixture: ReplayFixture) -> Iterator[None]:
    """Every request logs in through the recorded login, the process's token forgotten."""
    auth.reset()
    replay_fixture("auth_login", "login")
    yield
    auth.reset()


@pytest.mark.parametrize(
    ("dimension", "case"),
    [
        ("area", "area_QCL"),
        ("element", "element_QCL"),
        ("item", "item_QCL"),
        ("countries", "countries_QCL"),
    ],
)
async def test_get_code_list(replay_fixture: ReplayFixture, dimension: str, case: str) -> None:
    route = replay_fixture(CODES, case)
    before = datetime.now(UTC)
    answer = await api.get_code_list.get_code_list("en", dimension, "QCL")
    after = datetime.now(UTC)
    assert route.call_count == 1
    assert sent_query(route) == {}, "show_lists left to upstream's default"
    assert answer.response == recorded(case)
    assert answer.response.data
    assert all(isinstance(code, CodeItem) for code in answer.response.data)
    assert answer.response.metadata.output_type == "OBJECTS"
    assert_time_between(answer.retrieved_at, before, after)


async def test_get_code_list_sends_show_lists_when_given(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture(CODES, "element_QCL")
    await api.get_code_list.get_code_list("en", "element", "QCL", show_lists=False)
    assert sent_query(route) == {"show_lists": "false"}


async def test_get_code_list_keeps_upstreams_records(replay_fixture: ReplayFixture) -> None:
    """Each code dumps back to the record upstream sent: ``parent`` where it was sent."""
    replay_fixture(CODES, "item_QCL")
    answer = await api.get_code_list.get_code_list("en", "item", "QCL")
    body = load_fixture(FIXTURES / CODES / "item_QCL.json").response.body
    assert [code.dump_upstream() for code in answer.response.data] == json.loads(body)["data"]


def test_code_list_path_quotes_each_segment() -> None:
    assert api.get_code_list.code_list_path("en", "element", "QCL") == "/en/codes/element/QCL"
    assert api.get_code_list.code_list_path("en", "a/b", "Q L") == "/en/codes/a%2Fb/Q%20L"


async def test_datasets_e(replay_fixture: ReplayFixture, respx_mock: respx.MockRouter) -> None:
    """The catalogue on ``bulks-faostat.fao.org``, fetched without the account."""
    route = replay_fixture(CATALOGUE, "all")
    body = load_fixture(FIXTURES / CATALOGUE / "all.json").response.body
    before = datetime.now(UTC)
    answer = await api.datasets_e.datasets_e()
    after = datetime.now(UTC)
    assert sent_urls(route) == [api.datasets_e.URL]
    assert [call.request.headers.get("authorization") for call in route.calls] == [None]
    assert {call.request.url.host for call in respx_mock.calls} == {"bulks-faostat.fao.org"}, (
        "no login"
    )
    assert answer.response == DatasetsCatalogue.model_validate_json(body)
    assert_time_between(answer.retrieved_at, before, after)
    datasets = answer.response.datasets.dataset
    printed = json.loads(body)["Datasets"]["Dataset"]
    assert [dataset.dataset_code for dataset in datasets] == [row["DatasetCode"] for row in printed]
    assert all(isinstance(dataset, BulkDataset) for dataset in datasets)
    assert len({dataset.dataset_code for dataset in datasets}) == len(datasets), "one per code"
    named = {field.validation_alias for field in BulkDataset.model_fields.values()}
    assert {key for row in printed for key in row} == named, "every field the catalogue prints"
    assert all(
        dataset.file_location.startswith(f"{api.datasets_e.BULK_URL}/") for dataset in datasets
    )
    assert all(dataset.file_location.endswith(".zip") for dataset in datasets)
    assert all(isinstance(dataset.file_rows, int) for dataset in datasets)
    assert {(row.compression_format, row.file_type) for row in datasets} == {("zip", "csv")}
