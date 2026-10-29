"""The endpoint wrappers' own tests: ``api.get_code_list`` on its recorded answers.

``tests/fixtures/get_code_list/`` holds ``getCodeList``'s answers for QCL, recorded on
2026-10-29 through the package's client with the account's token:
``codes/area/QCL``, ``codes/element/QCL``, ``codes/item/QCL`` and
``codes/countries/QCL``, none with ``show_lists``, so upstream's default applies.
"""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from xippios.core.testing import ReplayFixture, assert_time_between, load_fixture, sent_query

from xippios.faostat import api
from xippios.faostat._client import auth
from xippios.faostat.models import CodeItem, CodeResponse

FIXTURES = Path(__file__).parent / "fixtures"
CODES = "get_code_list"

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
