"""The login (``LoginAuth``, on core's ``RenewingBearerAuth``) and ``classify``, recorded.

Recorded on 2026-10-29 through the package's client (``tests/fixtures/``):
``auth_login/login``, the account's login, HTTP 200, its three tokens and the form fields
scrubbed to ``REDACTED`` before the write; ``auth_login/user_not_found``, a login with
``nobody@example.invalid`` and a made-up password, HTTP 400 ``UserNotFoundException``;
``get_data/unauthorized_401``, a data query without a bearer, HTTP 401 ``Missing
Authorization Header``; ``get_data/forbidden_403``, the same with ``Bearer invalid``,
HTTP 403 ``Authentication Failed``; ``get_data/no_filter_500`` and
``get_data/XXX_unknown_domain_500``, the two refusals ``classify`` maps.

In every test the account's variables hold core's placeholder, which core's plugin sets for
each secret variable of ``_client.ENV_VARS``, the replayed login answers it with the scrubbed token
``REDACTED``, and the process's one ``LoginAuth`` forgets its token before and after the
test. No assertion names a credential: the values compared are the placeholder and the
scrubbed token, read through helpers that keep no request in a test's frame.
"""

import asyncio
import dataclasses
import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from pydantic import SecretStr
from xippios.core import (
    AsyncClient,
    AuthError,
    ConfigError,
    InvalidRequestError,
    NotFoundError,
    RateLimitError,
    RenewingBearerAuth,
    UpstreamError,
    ValidationError,
    error_from_response,
)
from xippios.core.testing import (
    Fixture,
    ReplayFixture,
    load_fixture,
    response_from_fixture,
)

from xippios.faostat import api, tasks
from xippios.faostat._client import (
    BASE_URL,
    CREDENTIAL_REFUSALS,
    PASSWORD_ENV,
    SOURCE,
    USERNAME_ENV,
    LoginAuth,
    auth,
    classify,
    config,
)

FIXTURES = Path(__file__).parent / "fixtures"
QCL = "QCL_231_2510_15_2015_2021"
QCL_ARGUMENTS: dict[str, Any] = {
    "area": "231",
    "element": "2510",
    "item": "15",
    "year": list(range(2015, 2022)),
}
LOGIN_URL = f"{BASE_URL}/auth/login"


def recorded(endpoint: str, case: str) -> Fixture:
    return load_fixture(FIXTURES / endpoint / f"{case}.json")


def answer(fixture: Fixture) -> httpx.Response:
    """The recorded answer, to serve from a route of the test's own."""
    return httpx.Response(
        fixture.response.status, headers=fixture.response.headers, content=fixture.response.content
    )


def data_route(router: respx.MockRouter, domain: str = "QCL") -> respx.Route:
    """A route for ``GET /en/data/<domain>``, any query, as ``mount_fixture`` matches."""
    url = httpx.URL(f"{BASE_URL}/en/data/{domain}")
    return router.route(method="GET", host=url.host, path=url.path)


def bearers(route: respx.Route) -> list[str | None]:
    """The ``Authorization`` header of each request ``route`` received, oldest first."""
    return [call.request.headers.get("authorization") for call in route.calls]


def login_forms(route: respx.Route) -> list[dict[str, list[str]]]:
    """The form fields of each login ``route`` received, oldest first."""
    return [parse_qs(call.request.content.decode()) for call in route.calls]


def login_headers(route: respx.Route) -> list[tuple[str | None, str | None]]:
    """The ``Content-Type`` and ``User-Agent`` of each login ``route`` received."""
    return [
        (call.request.headers.get("content-type"), call.request.headers.get("user-agent"))
        for call in route.calls
    ]


@pytest.fixture(autouse=True)
def fresh_login() -> Iterator[None]:
    """The process's one login starts and ends each test without a token."""
    auth.reset()
    yield
    auth.reset()


def test_one_login_serves_every_request(
    replay_fixture: ReplayFixture, placeholder_api_key: str | None
) -> None:
    # NOT RECORDED: the recorded answers serve other queries, and the test asserts the logins and
    # bearers sent (conventions §10, kind 3).
    login = replay_fixture("auth_login", "login")
    data = replay_fixture("get_data", QCL)
    domains = replay_fixture("get_groupsanddomains", "all")
    tasks.get_data("QCL", **QCL_ARGUMENTS)
    tasks.get_data("QCL", area="231", element="2510", item="15", year=2020)
    assert login.call_count == 1, "one login for the process"
    assert data.call_count == 2
    assert domains.call_count == 1, "the second look-up is a cache hit"
    assert bearers(data) == ["Bearer REDACTED", "Bearer REDACTED"]
    assert bearers(domains) == ["Bearer REDACTED"]
    assert login_forms(login) == [
        {"username": [placeholder_api_key], "password": [placeholder_api_key]}
    ]
    assert login_headers(login) == [("application/x-www-form-urlencoded", config.user_agent)]
    assert bearers(login) == [None], "the login sends no bearer"


def test_the_token_is_kept_masked_and_alone(replay_fixture: ReplayFixture) -> None:
    replay_fixture("auth_login", "login")
    replay_fixture("get_data", QCL)
    replay_fixture("get_groupsanddomains", "all")
    tasks.get_data("QCL", **QCL_ARGUMENTS)
    kept = [value for value in vars(auth).values() if isinstance(value, SecretStr)]
    assert len(kept) == 1, "the access token alone: no id token, no refresh token"
    assert "REDACTED" not in repr(vars(auth)), "no token kept as plain text"


@pytest.mark.parametrize("case", ["unauthorized_401", "forbidden_403"])
def test_a_refused_request_logs_in_once_more_and_is_sent_again(
    replay_fixture: ReplayFixture, respx_mock: respx.MockRouter, case: str
) -> None:
    """NOT RECORDED: the recorded 401 or 403 of the data endpoint, served in memory to a
    request with a bearer, as FAOSTAT refuses one alike (conventions §10, kind 3)."""
    login = replay_fixture("auth_login", "login")
    domains = replay_fixture("get_groupsanddomains", "all")
    data = data_route(respx_mock).mock(
        side_effect=[answer(recorded("get_data", case)), answer(recorded("get_data", QCL))]
    )
    result = tasks.get_data("QCL", **QCL_ARGUMENTS)
    assert len(result.data) == 7
    assert login.call_count == 2, "the first login and one more after the refusal"
    assert data.call_count == 2
    assert bearers(data) == ["Bearer REDACTED", "Bearer REDACTED"]
    assert domains.call_count == 1


@pytest.mark.parametrize(("case", "status"), [("unauthorized_401", 401), ("forbidden_403", 403)])
def test_a_second_refusal_is_core_auth_error(
    replay_fixture: ReplayFixture, respx_mock: respx.MockRouter, case: str, status: int
) -> None:
    """NOT RECORDED: the recorded 401 or 403 of the data endpoint, served in memory twice to
    a request with a bearer, as FAOSTAT refuses one alike (conventions §10, kind 3)."""
    login = replay_fixture("auth_login", "login")
    domains = replay_fixture("get_groupsanddomains", "all")
    refused = answer(recorded("get_data", case))
    data = data_route(respx_mock).mock(side_effect=[refused, refused])
    with pytest.raises(AuthError) as raised:
        tasks.get_data("QCL", **QCL_ARGUMENTS)
    assert raised.value.status == status
    assert str(raised.value).startswith(f"{status} from GET /api/v1/en/data/QCL: ")
    assert login.call_count == 2, "at most one refresh per call"
    assert data.call_count == 2
    assert domains.call_count == 0


@pytest.mark.anyio
async def test_the_token_lapses_expires_in_less_the_margin_after_the_login(
    replay_fixture: ReplayFixture,
) -> None:
    login = replay_fixture("auth_login", "login")
    replay_fixture("get_groupsanddomains", "all")
    expires_in = json.loads(recorded("auth_login", "login").response.body)["AuthenticationResult"][
        "ExpiresIn"
    ]
    now = [1_000.0]
    timed = LoginAuth(source=SOURCE, clock=lambda: now[0])
    http = AsyncClient(dataclasses.replace(config, cache=None), auth=timed)
    try:
        await http.get_answer("/en/groupsanddomains")
        now[0] += expires_in - timed.margin - 1
        await http.get_answer("/en/groupsanddomains")
        assert login.call_count == 1, "still current a second before it lapses"
        now[0] += 1
        await http.get_answer("/en/groupsanddomains")
        assert login.call_count == 2, "lapsed: a new login"
    finally:
        await http.aclose()


def test_the_login_is_core_renewing_bearer_renewed_on_401_and_403() -> None:
    """Core's ``RenewingBearerAuth`` keeps the token; FAOSTAT refuses one with 401 or 403."""
    assert isinstance(auth, RenewingBearerAuth)
    assert LoginAuth.renew_on == frozenset({401, 403})
    assert auth.margin == 60.0, "renewed a minute before ExpiresIn runs out"


@pytest.mark.anyio
async def test_two_requests_that_start_together_log_in_once(
    replay_fixture: ReplayFixture, respx_mock: respx.MockRouter
) -> None:
    """The login answers after a pause, so the second request starts while it is pending.

    NOT RECORDED: the recorded login, served in memory after the pause (conventions §10,
    kind 3).
    """
    recorded_login = answer(recorded("auth_login", "login"))

    async def slow_login(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.01)
        return httpx.Response(
            recorded_login.status_code,
            headers=recorded_login.headers,
            content=recorded_login.content,
        )

    login = respx_mock.post(LOGIN_URL).mock(side_effect=slow_login)
    data = replay_fixture("get_data", QCL)
    replay_fixture("get_groupsanddomains", "all")
    await asyncio.gather(
        tasks.get_data_async("QCL", **QCL_ARGUMENTS), tasks.get_data_async("QCL", **QCL_ARGUMENTS)
    )
    assert login.call_count == 1, "one login for both"
    assert data.call_count == 2
    assert bearers(data) == ["Bearer REDACTED", "Bearer REDACTED"]


@pytest.mark.parametrize("name", [USERNAME_ENV, PASSWORD_ENV])
@pytest.mark.parametrize("unset", ["deleted", "empty"])
def test_an_unset_variable_is_config_error_and_nothing_is_sent(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch, name: str, unset: str
) -> None:
    if unset == "deleted":
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, "")
    with pytest.raises(ConfigError) as raised:
        tasks.get_data("QCL", **QCL_ARGUMENTS)
    assert str(raised.value).startswith(f"{name} is not set")
    assert raised.value.source == SOURCE
    assert not respx_mock.calls, "neither the login nor the data request was sent"


def test_a_refused_login_is_auth_error_naming_upstream_type(
    replay_fixture: ReplayFixture,
    respx_mock: respx.MockRouter,
    placeholder_api_key: str | None,
) -> None:
    # NOT RECORDED: the recorded refusal of an unknown user answers the placeholder's login, as
    # FAOSTAT refuses any unknown user alike (conventions §10, kind 3).
    login = replay_fixture("auth_login", "user_not_found")
    data = data_route(respx_mock)
    with pytest.raises(AuthError) as raised:
        tasks.get_data("QCL", **QCL_ARGUMENTS)
    assert raised.value.status == 400
    assert str(raised.value) == (
        "FAOSTAT refused the login: POST /api/v1/auth/login answered HTTP 400 "
        f"(UserNotFoundException); check {USERNAME_ENV} and {PASSWORD_ENV}"
    )
    assert placeholder_api_key is not None
    assert placeholder_api_key not in str(raised.value)
    assert login.call_count == 1
    assert data.call_count == 0


@pytest.mark.parametrize("status", [401, 403])
def test_a_login_refused_with_401_or_403_is_auth_error(
    respx_mock: respx.MockRouter, status: int
) -> None:
    """NOT RECORDED: the recorded refusals' statuses served at the login, their bodies
    removed, a form the login was not seen to send (conventions §10, kind 4)."""
    respx_mock.post(LOGIN_URL).mock(return_value=httpx.Response(status))
    with pytest.raises(AuthError) as raised:
        tasks.get_data("QCL", **QCL_ARGUMENTS)
    assert raised.value.status == status
    assert str(raised.value).endswith(f"; check {USERNAME_ENV} and {PASSWORD_ENV}")


def test_a_login_answered_503_is_core_upstream_error(respx_mock: respx.MockRouter) -> None:
    """Another answer of the login goes through core's mapping, without the variables' hint.

    NOT RECORDED: a 503 of no shape FAOSTAT sends, to show that the source leaves it to core
    (conventions §10, kind 5).
    """
    login = respx_mock.post(LOGIN_URL).mock(
        return_value=httpx.Response(503, text="Service Unavailable")
    )
    data = data_route(respx_mock)
    with pytest.raises(UpstreamError) as raised:
        tasks.get_data("QCL", **QCL_ARGUMENTS)
    assert raised.value.status == 503
    assert str(raised.value) == "503 from POST /api/v1/auth/login: Service Unavailable"
    assert USERNAME_ENV not in str(raised.value), "the hint is the credentials' refusal's"
    assert login.call_count == 1, "a login inside the auth flow is never retried"
    assert data.call_count == 0


def test_a_login_answered_429_is_core_rate_limit_error(respx_mock: respx.MockRouter) -> None:
    """NOT RECORDED: a 429 of no shape FAOSTAT sends, to show that the source leaves it to
    core (conventions §10, kind 5)."""
    respx_mock.post(LOGIN_URL).mock(return_value=httpx.Response(429, headers={"Retry-After": "7"}))
    with pytest.raises(RateLimitError) as raised:
        tasks.get_data("QCL", **QCL_ARGUMENTS)
    assert raised.value.retry_after == 7


class _Unread(httpx.AsyncByteStream):
    """A body that is read only when someone iterates it; ``read`` says whether one did."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.read = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.read = True
        yield self.body


@pytest.mark.anyio
async def test_the_flow_reads_the_login_answer_and_not_the_signed_requests() -> None:
    """``async_auth_flow`` driven by hand, with the recorded answers as unread streams.

    The recorded login and data bodies go straight to the flow: no route serves them and
    ``classify`` reads neither. Each body so handed is an input of the test, not an answer
    from FAOSTAT.
    """
    flow = LoginAuth(source=SOURCE).async_auth_flow(
        httpx.Request("GET", f"{BASE_URL}/en/data/QCL", headers={"User-Agent": "test"})
    )
    login_request = await anext(flow)
    assert login_request.url == LOGIN_URL
    login_body = _Unread(recorded("auth_login", "login").response.content)
    signed = await flow.asend(httpx.Response(200, stream=login_body, request=login_request))
    assert login_body.read, "the login's answer is read"
    assert signed.headers["authorization"] == "Bearer REDACTED"
    data_body = _Unread(recorded("get_data", QCL).response.content)
    data_response = httpx.Response(200, stream=data_body, request=signed)
    with pytest.raises(StopAsyncIteration):
        await flow.asend(data_response)
    assert not data_body.read, "the signed request's answer goes back unread"
    assert not data_response.is_stream_consumed


def test_the_sync_flow_is_not_served() -> None:
    with pytest.raises(NotImplementedError, match="async client only"):
        next(LoginAuth(source=SOURCE).sync_auth_flow(httpx.Request("GET", BASE_URL)))


def test_a_login_answer_not_auth_is_validation_error_quoting_nothing(
    respx_mock: respx.MockRouter,
) -> None:
    """A 200 that is not ``Auth``: the recorded login without its ``AuthenticationResult``.

    NOT RECORDED: the recorded login changed in memory, its tokens' field removed, a form the
    login was not seen to send, to show that the source refuses it without quoting it
    (conventions §10, kind 4).
    """
    login = recorded("auth_login", "login").response
    changed = {
        key: value for key, value in json.loads(login.body).items() if key != "AuthenticationResult"
    }
    respx_mock.post(LOGIN_URL).mock(
        return_value=httpx.Response(200, headers=login.headers, json=changed)
    )
    with pytest.raises(ValidationError) as raised:
        tasks.get_data("QCL", **QCL_ARGUMENTS)
    assert "not the documented Auth answer" in str(raised.value)
    assert raised.value.raw == ""


@pytest.mark.anyio
async def test_auth_login_returns_the_tokens_masked(replay_fixture: ReplayFixture) -> None:
    route = replay_fixture("auth_login", "login")
    result = await api.auth_login.auth_login("nobody@example.invalid", "made-up")
    tokens = result.authentication_result
    assert isinstance(tokens.access_token, SecretStr)
    assert isinstance(tokens.id_token, SecretStr)
    assert isinstance(tokens.refresh_token, SecretStr)
    assert tokens.token_type == "Bearer"
    assert tokens.expires_in == 3600
    assert result.challenge_parameters == {}
    assert "REDACTED" not in repr(result), "every token masked"
    assert bearers(route) == [None], "auth_login sends no bearer"
    assert login_forms(route) == [{"username": ["nobody@example.invalid"], "password": ["made-up"]}]


@pytest.mark.anyio
async def test_auth_login_refused_is_auth_error_through_classify(
    replay_fixture: ReplayFixture,
) -> None:
    replay_fixture("auth_login", "user_not_found")
    with pytest.raises(AuthError) as raised:
        await api.auth_login.auth_login("nobody@example.invalid", "made-up")
    assert raised.value.status == 400
    assert str(raised.value) == (
        "FAOSTAT refused the login: POST /api/v1/auth/login answered HTTP 400 "
        "(UserNotFoundException)"
    )
    assert "made-up" not in str(raised.value), "no credential in the message"


def test_classify_maps_the_login_refusal_of_the_credentials() -> None:
    error = classify(response_from_fixture(recorded("auth_login", "user_not_found")))
    assert isinstance(error, AuthError)
    assert error.status == 400
    assert "(UserNotFoundException)" in str(error)
    assert "nobody" not in str(error), "the body is not quoted"


def test_classify_leaves_another_status_at_the_login_path_to_core() -> None:
    """A 400 at another path, or another status at the login path, is not classify's.

    NOT RECORDED: the recorded refusal of an unknown user, its request replaced in memory by
    one at another path (conventions §10, kind 4).
    """
    refused = response_from_fixture(recorded("auth_login", "user_not_found"))
    elsewhere = httpx.Response(
        400,
        headers=refused.headers,
        content=refused.content,
        request=httpx.Request("POST", f"{BASE_URL}/en/datasize/"),
    )
    assert classify(elsewhere) is None
    login_200 = response_from_fixture(recorded("auth_login", "login"))
    assert classify(login_200) is None


def test_classify_maps_a_query_without_a_filter() -> None:
    error = classify(response_from_fixture(recorded("get_data", "no_filter_500")))
    assert isinstance(error, InvalidRequestError)
    assert str(error) == (
        'FAOSTAT refused GET /api/v1/en/data/QCL with HTTP 500, "Please add at least one '
        'filter.": a data query needs area, item, element or year'
    )


def test_classify_maps_an_unknown_domain() -> None:
    error = classify(response_from_fixture(recorded("get_data", "XXX_unknown_domain_500")))
    assert isinstance(error, NotFoundError)
    assert str(error) == (
        "FAOSTAT has no domain 'XXX': GET /api/v1/en/data/XXX answered HTTP 500, "
        '"Index: 0, Size: 0"; list_domains names the domains (over MCP, the tool '
        "faostat_list_domains)"
    )
    assert "faostatservices" not in str(error), "no host"
    assert "area=" not in str(error), "no query"


@pytest.mark.parametrize(("case", "status"), [("unauthorized_401", 401), ("forbidden_403", 403)])
def test_the_recorded_401_and_403_are_core_auth_error(case: str, status: int) -> None:
    response = response_from_fixture(recorded("get_data", case))
    assert classify(response) is None, "core's mapping, not classify's"
    error = error_from_response(response, source=SOURCE)
    assert isinstance(error, AuthError)
    assert error.status == status


@pytest.mark.parametrize(
    ("endpoint", "case"),
    [
        ("get_data", QCL),
        ("get_data", "QCL_element_5510_empty"),
        ("get_groupsanddomains", "all"),
        ("auth_login", "login"),
    ],
)
def test_classify_lets_every_other_answer_through(endpoint: str, case: str) -> None:
    assert classify(response_from_fixture(recorded(endpoint, case))) is None


def test_the_credential_refusals_hold_the_recorded_cognito_type() -> None:
    """``CREDENTIAL_REFUSALS``, written by hand, against the recorded refusal of an unknown user.

    ``NotAuthorizedException``, Cognito's answer to a wrong password, stands in no document
    under ``docs/upstream/`` and was not recorded, so the test holds the set's size alone for it.
    """
    refused = json.loads(recorded("auth_login", "user_not_found").response.body)["__type"]
    assert refused in CREDENTIAL_REFUSALS
    assert frozenset({refused, "NotAuthorizedException"}) == CREDENTIAL_REFUSALS
