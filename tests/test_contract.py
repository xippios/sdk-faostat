"""The package contract and what the adapters of xippios-core 0.4.0 answer a caller.

Offline, in process: the MCP server through an in-process ``mcp.Client``, the router
through FastAPI's ``TestClient`` and the entry point in a child process. ``mcp.build()``
is the tool set a host serves (conventions §8; sdk-core ADR-0026, amendment 2026-11-18,
points c and d), and ``_client.ENV_VARS`` the variables the package reads, for that host.
The refusals below send nothing; the answers that need a login replay
``tests/fixtures/auth_login/login.json``, as ``tests/test_tasks.py`` does.
"""

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.client import Client
from mcp.types import TextContent
from xippios.core import EnvVar
from xippios.core._loop import run
from xippios.core.mcp import ToolSet, build_server
from xippios.core.testing import ReplayFixture, load_fixture

from xippios.faostat import list_domains, mcp, tasks
from xippios.faostat._client import BASE_URL, ENV_VARS, PASSWORD_ENV, USERNAME_ENV, auth
from xippios.faostat.http import router

FIXTURES = Path(__file__).parent / "fixtures"
ENTRY_POINT = "xippios-faostat-mcp"


@pytest.fixture(autouse=True)
def fresh_login() -> Iterator[None]:
    """The process's one login starts and ends each test without a token."""
    auth.reset()
    yield
    auth.reset()


async def call(name: str, arguments: dict[str, Any]) -> tuple[bool, str]:
    """A tool's answer through an in-process client: whether it is flagged, and its text."""
    async with Client(mcp.server) as client:
        result = await client.call_tool(name, arguments)
    content = result.content[0]
    assert isinstance(content, TextContent), content
    return result.is_error, content.text


def test_env_vars_name_the_account_both_secret_and_required() -> None:
    assert (
        EnvVar(USERNAME_ENV, secret=True, required=True),
        EnvVar(PASSWORD_ENV, secret=True, required=True),
    ) == ENV_VARS
    assert mcp.ENV_VARS is ENV_VARS, "the template's mcp.py names the client's list"


def test_build_is_the_tool_set_the_entry_point_serves() -> None:
    tools = mcp.build()
    assert isinstance(tools, ToolSet)
    assert tools.source == "faostat"
    assert tools.read_only
    assert tools.caps == tasks.MCP_CAPS
    assert tools.instructions == mcp.INSTRUCTIONS
    served = {tool.name for tool in run(mcp.server.list_tools())}
    hosted = {tool.name for tool in run(build_server(tools).list_tools())}
    assert hosted == served
    assert served == {f"faostat_{name}" for name in tasks.__all__ if name not in tasks.BULK_TASKS}
    assert tools.add_options is None, "no option of the package's own"
    assert tools.apply_options is None


@pytest.mark.anyio
async def test_a_tool_refuses_an_argument_it_does_not_declare(
    respx_mock: respx.MockRouter,
) -> None:
    flagged, text = await call("faostat_list_domains", {"serch": "QCL"})
    assert flagged
    assert text == (
        "error: InvalidRequestError: serch: Not an argument of this tool; it takes search"
    )
    assert not respx_mock.calls, "refused before the task runs"


@pytest.mark.anyio
async def test_a_tool_flags_its_error_answer(respx_mock: respx.MockRouter) -> None:
    flagged, text = await call("faostat_get_data", {"domain": "QCL"})
    assert flagged
    assert text.startswith("error: InvalidRequestError: FAOSTAT refuses a data query without")
    assert not respx_mock.calls


@pytest.mark.anyio
async def test_an_unknown_code_ends_on_the_packaged_list(respx_mock: respx.MockRouter) -> None:
    flagged, text = await call(
        "faostat_get_data", {"domain": "QCL", "area": "231", "element": "5510"}
    )
    assert flagged
    assert text.endswith("If upstream added it since, the packaged list is out of date.")
    assert "/refresh-reference-data" not in text, "a command an agent cannot run"


def test_a_route_answers_an_argument_its_schema_refuses_as_problem_details(
    respx_mock: respx.MockRouter,
) -> None:
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as http:
        answered = http.post("/faostat/get_data", json={"domain": "QCL", "page_size": "many"})
    assert answered.status_code == 422
    assert answered.headers["content-type"].startswith("application/problem+json")
    problem = answered.json()
    assert problem["title"] == "InvalidRequestError"
    assert problem["detail"].startswith("page_size: ")
    assert "many" not in answered.text, "the value given is not echoed"
    assert not respx_mock.calls


def entry_point(*argv: str) -> subprocess.CompletedProcess[str]:
    """The entry point's run with ``argv``, colours off and a width of its own."""
    environment = {**os.environ, "PYTHON_COLORS": "0", "NO_COLOR": "1", "COLUMNS": "100"}
    environment.pop("FORCE_COLOR", None)
    script = Path(sys.executable).with_name(ENTRY_POINT)
    return subprocess.run(
        [str(script), *argv], capture_output=True, text=True, env=environment, timeout=60
    )


def test_the_entry_point_names_itself_in_its_usage_and_errors() -> None:
    refused = entry_point("--bogus")
    assert refused.returncode == 2
    assert refused.stderr.startswith(f"usage: {ENTRY_POINT} ")
    assert f"{ENTRY_POINT}: error: unrecognized arguments: --bogus" in refused.stderr


def test_the_entry_point_help_says_allow_remote_changes_nothing_here() -> None:
    helped = entry_point("--help")
    assert helped.returncode == 0
    text = " ".join(helped.stdout.split())
    assert "--allow-remote changes nothing: this read server is not held to loopback" in text


def test_a_cache_miss_and_its_hit_report_one_retrieved_at(replay_fixture: ReplayFixture) -> None:
    replay_fixture("auth_login", "login")
    route = replay_fixture("get_groupsanddomains", "all")
    first = list_domains()
    second = list_domains()
    assert route.call_count == 1, "the second answer comes from the cache"
    assert second.meta.retrieved_at == first.meta.retrieved_at


def test_an_answer_that_is_not_json_is_not_cached(
    replay_fixture: ReplayFixture, respx_mock: respx.MockRouter
) -> None:
    """A test double: a 200 that is no JSON, then the recorded list, at one route."""
    replay_fixture("auth_login", "login")
    recorded = load_fixture(FIXTURES / "get_groupsanddomains" / "all.json").response
    route = respx_mock.get(f"{BASE_URL}/en/groupsanddomains").mock(
        side_effect=[
            httpx.Response(200, text="<html>maintenance</html>"),
            httpx.Response(200, headers=recorded.headers, content=recorded.content),
        ]
    )
    with pytest.raises(Exception, match="not JSON") as raised:
        list_domains()
    assert type(raised.value).__name__ == "ValidationError"
    rows = list_domains().data
    assert route.call_count == 2, "asked again, not answered from the cache"
    assert len(rows) == len(json.loads(recorded.content)["data"])


def test_an_answer_that_is_not_the_documented_one_is_not_cached(
    replay_fixture: ReplayFixture, respx_mock: respx.MockRouter
) -> None:
    """A test double: JSON without the documented ``data``, then the recorded list."""
    replay_fixture("auth_login", "login")
    recorded = load_fixture(FIXTURES / "get_groupsanddomains" / "all.json").response
    route = respx_mock.get(f"{BASE_URL}/en/groupsanddomains").mock(
        side_effect=[
            httpx.Response(200, json={"unexpected": True}),
            httpx.Response(200, headers=recorded.headers, content=recorded.content),
        ]
    )
    with pytest.raises(Exception, match="get_groupsanddomains") as raised:
        list_domains()
    assert type(raised.value).__name__ == "ValidationError"
    rows = list_domains().data
    assert route.call_count == 2, "asked again, not answered from the cache"
    assert len(rows) == len(json.loads(recorded.content)["data"])
