"""The package's one configured ``AsyncClient``, its login and its error mapping (conventions §6).

FAOSTAT's API answers an account's requests only: the OpenAPI document requires
``bearerAuth``, an HTTP bearer, on every operation, and ``auth_login`` (``POST
/auth/login``, form fields ``username`` and ``password``) issues the token
(``docs/upstream/openapi/faostat_openapi.yaml``). ``LoginAuth`` is the client's
``auth``: on the first request of the process it reads ``FAOSTAT_USERNAME`` (the
account's e-mail) and ``FAOSTAT_PASSWORD`` from the environment, logs in, keeps the
answer's ``AuthenticationResult.AccessToken`` and sends it as ``Authorization: Bearer
<token>`` on that request and every later one. A request sent with ``auth=None`` passes
it by: the bulk downloads' catalogue and files on ``bulks-faostat.fao.org``
(``api.datasets_e``, ``tasks.download_dataset``) go without a login and without the
token. The token lives ``ExpiresIn`` seconds (3600 in the recorded login); it is used
for that time less a margin of ``EXPIRY_MARGIN`` (60 s), and the first request after it
logs in again. A request answered with HTTP 401 or 403 logs in once more and is sent
again, once: a second 401 or 403 goes back to core, whose status mapping raises
``AuthError``. So a request logs in at most twice (queue row 252). The login runs inside
the request's ``httpx`` auth flow, below core's limiter, hooks, cache and ``classify``:
a login is not paced and not cached. A login refused with HTTP 401 or 403, or with HTTP
400 and Cognito's ``UserNotFoundException`` (recorded for an unknown user) or
``NotAuthorizedException``, raises ``AuthError`` naming the status and upstream's
``__type``; any other answer but HTTP 200 raises what core's ``error_from_response``
makes of it (``RateLimitError`` for a 429, ``UpstreamError`` for a 5xx). The flow reads
the login's answer and no other: the answer of the request it signs, a streamed
download's among them, goes back to the client unread.

Nothing of the account is logged, printed or kept but the access token: neither the
user name nor the password, read where the login request is built and kept in no
attribute and in no local that outlives the call, nor the answer's id token, which
carries the account's e-mail, nor its refresh token. The access token is kept as a
``SecretStr``, whose ``repr`` is masked. An error names a variable, a status and
upstream's ``__type``, never a value.

The developer portal (https://www.fao.org/faostat/en/#developer-portal) draws in the
browser with a guest token of its own; this package does not use it, it logs in with
the account (Johannes, G5 2026-10-29, question 8).

``classify`` maps the login's refusal of the credentials, HTTP 400 with Cognito's
``UserNotFoundException`` or ``NotAuthorizedException`` (recorded under
``tests/fixtures/auth_login/``), to ``AuthError``, and the data endpoint's two recorded
refusals, both HTTP 500 with a plain text body (``Content-Type: text/plain``;
FETCHED.md, "How this is captured"; ``tests/fixtures/get_data/``): ``Please add at least
one filter.`` to ``InvalidRequestError`` and ``Index: 0, Size: 0``, an unknown domain, to
``NotFoundError`` naming the domain. Everything else falls through to core's status
mapping: the 401 ``Missing Authorization Header`` and the 403 ``Authentication Failed``
(recorded under ``tests/fixtures/get_data/``) are ``AuthError`` there.

Answers of HTTP 200 are cached in core's ``MemoryCache`` with its default lifetime of
five minutes, up to core's ``cache_max_bytes`` of 8 MiB a body (ADR-0019 decision 3):
``tasks.get_data``'s look-up of a domain's release date in ``get_groupsanddomains``
costs one request per process per five minutes, as does the bulk catalogue
(``datasets_E.json``, 107 KB), and a larger data answer is returned and fetched again the
next time. A bulk file goes through ``download`` and is never cached.
"""

import os
import re
import threading
import time
from collections.abc import AsyncGenerator, Callable, Generator
from urllib.parse import unquote

import httpx
import pydantic
from pydantic import SecretStr
from xippios.core import (
    AsyncClient,
    AuthError,
    ClientConfig,
    ConfigError,
    InvalidRequestError,
    NotFoundError,
    RateLimit,
    UpstreamError,
    ValidationError,
    XippiosError,
    error_from_response,
)
from xippios.core.client import MemoryCache

from xippios.faostat._version import __version__
from xippios.faostat.models import Auth

SOURCE = "faostat"
BASE_URL = "https://faostatservices.fao.org/api/v1"
# No API key exists: FAOSTAT authenticates an account by its login (LoginAuth below), so
# the template's key variable stays None and the account's two variables are named below.
API_KEY_ENV: str | None = None
USERNAME_ENV = "FAOSTAT_USERNAME"
"""The variable holding the FAO account's user name, its e-mail: ``auth_login``'s ``username``."""
# The variable's name, not a value: detect-secrets reads the assignment as one.
PASSWORD_ENV = "FAOSTAT_PASSWORD"  # pragma: allowlist secret
"""The variable holding the FAO account's password: ``auth_login``'s ``password``."""
LOGIN_PATH = "/auth/login"
"""``auth_login``'s path, under ``BASE_URL``; ``api.auth_login`` and ``LoginAuth`` send it."""
EXPIRY_MARGIN = 60.0
"""Seconds before the token's ``ExpiresIn`` runs out that ``LoginAuth`` logs in again."""
REFUSED = frozenset({401, 403})
"""The statuses that make ``LoginAuth`` log in once more and send the request again."""
# A self-imposed pace: upstream documents no per-second or per-minute limit (ADR-0010 decision 1).
RATE_LIMIT = RateLimit(per_minute=30, burst=1)

FILTER_REFUSAL = "Please add at least one filter."
"""The body of the data endpoint's HTTP 500 to a query without a filter, as recorded."""
UNKNOWN_DOMAIN = "Index: 0, Size: 0"
"""The body of the data endpoint's HTTP 500 to an unknown domain, as recorded."""
_DATA_PATH = re.compile(
    re.escape(httpx.URL(BASE_URL).path) + r"/(?P<lang>[^/]+)/data/(?P<domain_code>[^/]+)/?"
)
"""``get_data``'s path, ``/{lang}/data/{domain_code}`` under ``BASE_URL``."""
_LOGIN_URL_PATH = httpx.URL(BASE_URL).path + LOGIN_PATH
"""``auth_login``'s path as sent, ``/api/v1/auth/login``."""
CREDENTIAL_REFUSALS = frozenset({"UserNotFoundException", "NotAuthorizedException"})
"""The Cognito ``__type`` of a login's HTTP 400 that refuses the credentials:
``UserNotFoundException``, recorded for an unknown user
(``tests/fixtures/auth_login/user_not_found.json``), and ``NotAuthorizedException``,
Cognito's answer to a wrong password."""


def _credential(name: str, source: str | None) -> str:
    """The value of the variable ``name``; an empty one counts as unset.

    Raises:
        ConfigError: The variable is unset or empty; the message names it, never a value.
    """
    value = os.environ.get(name)
    if value:
        return value
    raise ConfigError(
        f"{name} is not set; FAOSTAT needs a FAO account: export {USERNAME_ENV} (the "
        f"account's e-mail) and {PASSWORD_ENV}",
        source=source,
    )


def _upstream_type(response: httpx.Response) -> str | None:
    """The ``__type`` of a JSON error body (``UserNotFoundException``), else ``None``."""
    try:
        payload = response.json()
    except ValueError:
        return None
    kind = payload.get("__type") if isinstance(payload, dict) else None
    return kind if isinstance(kind, str) and kind.isidentifier() else None


def _credentials_refused(response: httpx.Response) -> bool:
    """Whether a login's answer refuses the credentials: HTTP 401 or 403, or a Cognito 400."""
    status = response.status_code
    if status in REFUSED:
        return True
    return status == 400 and _upstream_type(response) in CREDENTIAL_REFUSALS


def _login_refused(
    response: httpx.Response, *, source: str | None = SOURCE, hint: str = ""
) -> AuthError:
    """``AuthError`` for a refused login, naming the status and upstream's ``__type``.

    Never a credential: the message names the method, the path, the status and the
    ``__type``, and the body is not quoted.
    """
    request = response.request
    status = response.status_code
    kind = _upstream_type(response)
    return AuthError(
        f"FAOSTAT refused the login: {request.method} {request.url.path} answered HTTP "
        f"{status}{f' ({kind})' if kind else ''}{hint}",
        status=status,
        source=source,
    )


class LoginAuth(httpx.Auth):
    """Log in with the FAO account once, send its access token, log in again when it lapses.

    The ``httpx.Auth`` of the package's client (queue row 252: this source's helper; core
    has none for a login). On the first request it builds ``auth_login``'s request on
    ``base_url`` (``POST /auth/login``, form-encoded ``username`` and ``password`` from
    ``FAOSTAT_USERNAME`` and ``FAOSTAT_PASSWORD``, read there and kept in no attribute and
    in no local that outlives the call) and sends it ahead of the request; from the answer,
    which it reads in full (and no other answer), it keeps the access token, a ``SecretStr``,
    and when it lapses, ``ExpiresIn`` less ``EXPIRY_MARGIN`` seconds from the answer, under
    a lock, and nothing else. Every request goes out with ``Authorization: Bearer
    <token>``. A request answered with HTTP 401 or 403 logs in once more and goes out
    again, once; the answer to that one is returned as it is, unread. Two requests that
    start together before the first login has answered may each log in. It runs on core's
    async client only (``async_auth_flow``).

    Args:
        source: Source slug for the errors, e.g. ``"faostat"``.
        base_url: The client's base URL, which ``LOGIN_PATH`` is joined onto.
        clock: Monotonic seconds, replaceable in tests.

    Raises:
        ConfigError: From a request, when ``FAOSTAT_USERNAME`` or ``FAOSTAT_PASSWORD`` is
            unset or empty; nothing is sent.
        AuthError: From a request, when the login refuses the credentials (HTTP 401 or
            403, or HTTP 400 with Cognito's ``UserNotFoundException`` or
            ``NotAuthorizedException``); the message names the status and the ``__type``.
        XippiosError: From a request, for any other answer of the login but HTTP 200:
            core's mapping, e.g. ``RateLimitError`` for a 429, ``UpstreamError`` for a 5xx.
        ValidationError: From a request, when the login's HTTP 200 is not the documented
            ``Auth`` answer; nothing of the answer is quoted.
    """

    # The flow reads the login's answer itself; a response of the request it signs, a
    # streamed download's among them, is never buffered by it (ADR-0019 decision 1).
    requires_response_body = False

    def __init__(
        self,
        *,
        source: str | None = None,
        base_url: str = BASE_URL,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.source = source
        self.login_url = httpx.URL(base_url.rstrip("/") + LOGIN_PATH)
        self._clock = clock
        self._token: SecretStr | None = None
        self._lapses_at = 0.0
        self._lock = threading.Lock()

    def reset(self) -> None:
        """Forget the token, so that the next request logs in again."""
        with self._lock:
            self._token = None
            self._lapses_at = 0.0

    def _current(self) -> SecretStr | None:
        """The token while it has not lapsed, else ``None``."""
        with self._lock:
            if self._token is not None and self._clock() < self._lapses_at:
                return self._token
            return None

    def _login(self, request: httpx.Request) -> httpx.Request:
        """``auth_login``'s request, ahead of ``request``, whose ``User-Agent`` it sends."""
        headers = {"Accept": "application/json"}
        if "user-agent" in request.headers:
            headers["User-Agent"] = request.headers["user-agent"]
        return httpx.Request(
            "POST",
            self.login_url,
            data={
                "username": _credential(USERNAME_ENV, self.source),
                "password": _credential(PASSWORD_ENV, self.source),
            },
            headers=headers,
        )

    def _keep(self, response: httpx.Response) -> None:
        """Keep the access token and when it lapses from the login's answer, read in full.

        Raises:
            AuthError: The credentials were refused: HTTP 401 or 403, or HTTP 400 with
                Cognito's ``UserNotFoundException`` or ``NotAuthorizedException``; the
                message names the two variables to check.
            XippiosError: Another 4xx or 5xx, by core's mapping (``error_from_response``):
                ``RateLimitError`` for a 429, ``UpstreamError`` for a 5xx.
            UpstreamError: Another status below 400 than HTTP 200.
            ValidationError: The HTTP 200 is not the documented ``Auth`` answer.
        """
        status = response.status_code
        if status != 200:
            if _credentials_refused(response):
                raise _login_refused(
                    response, source=self.source, hint=f"; check {USERNAME_ENV} and {PASSWORD_ENV}"
                )
            error = error_from_response(response, source=self.source)
            if error is None:
                error = UpstreamError(
                    f"POST {self.login_url.path} answered HTTP {status}, not the documented "
                    "200; the answer is not shown",
                    status=status,
                    body="",
                    source=self.source,
                )
            raise error
        try:
            result = Auth.model_validate_json(response.content).authentication_result
        except pydantic.ValidationError:
            # Raised without pydantic's text, which would quote the tokens it read.
            raise ValidationError(
                f"POST {LOGIN_PATH} answered HTTP 200, but not the documented Auth answer "
                "(AuthenticationResult with AccessToken and ExpiresIn); the answer is not shown",
                raw="",
                source=self.source,
            ) from None
        lapses_at = self._clock() + max(0.0, result.expires_in - EXPIRY_MARGIN)
        with self._lock:
            self._token = result.access_token
            self._lapses_at = lapses_at

    def _sign(self, request: httpx.Request) -> None:
        """Attach the kept token to ``request`` as a bearer."""
        with self._lock:
            token = self._token
        if token is None:  # pragma: no cover - _keep sets it or raises
            raise AuthError("no FAOSTAT token to send", status=401, source=self.source)
        request.headers["Authorization"] = f"Bearer {token.get_secret_value()}"

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """The httpx hook: log in without a current token, sign, log in once more on 401/403.

        Only a login's answer is read here; the signed request's answer is handed back
        to the client unread, its status alone looked at.
        """
        if self._current() is None:
            login = yield self._login(request)
            await login.aread()
            self._keep(login)
        self._sign(request)
        response = yield request
        if response.status_code in REFUSED:
            login = yield self._login(request)
            await login.aread()
            self._keep(login)
            self._sign(request)
            yield request

    def sync_auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response]:
        """Not served: core's client is async, and runs ``async_auth_flow``.

        Raises:
            NotImplementedError: Always; send through ``_client.client``.
        """
        raise NotImplementedError(
            "LoginAuth runs on core's async client only (async_auth_flow); send through "
            "xippios.faostat._client.client"
        )


def classify(response: httpx.Response) -> XippiosError | None:
    """Upstream's recorded refusals as taxonomy errors, else ``None`` (conventions §6).

    The ``ClientConfig.classify`` hook: it sees every response before core's status
    mapping. ``POST /auth/login`` refuses the credentials with HTTP 400 and a JSON body
    whose ``__type`` is Cognito's (``CREDENTIAL_REFUSALS``: ``UserNotFoundException``,
    recorded for an unknown user, and ``NotAuthorizedException``): that is ``AuthError``,
    upstream's refusal of the credentials (conventions §5), naming the status and the
    ``__type``, never a credential; ``api.auth_login`` raises it, and ``LoginAuth``, whose
    login runs below this hook, raises the same for it and for a login's 401 or 403, and
    core's mapping for any other status. ``GET /{lang}/data/{domain_code}`` answers two
    refusals with HTTP 500 and a plain text body (``Content-Type: text/plain``), recorded
    on 2026-10-29:

    - ``Please add at least one filter.``, a query without ``area``, ``item``,
      ``element`` or ``year``, is ``InvalidRequestError``, upstream's refusal of the
      query as given (ADR-0007); ``tasks.get_data`` refuses such a query before sending;
    - ``Index: 0, Size: 0``, a domain code FAOSTAT does not have, is ``NotFoundError``
      naming the domain.

    Everything else falls through, and core's mapping applies: the 401 and 403 of a
    request without a valid token are ``AuthError``, another 500 ``UpstreamError``.
    Messages name the method and the path, never the host or the query (conventions §5).
    """
    request = response.request
    if (
        response.status_code == 400
        and request.method == "POST"
        and request.url.path == _LOGIN_URL_PATH
        and _upstream_type(response) in CREDENTIAL_REFUSALS
    ):
        return _login_refused(response)
    if response.status_code != 500:
        return None
    match = _DATA_PATH.fullmatch(request.url.path)
    if match is None:
        return None
    body = response.text.strip()
    if body == FILTER_REFUSAL:
        return InvalidRequestError(
            f"FAOSTAT refused {request.method} {request.url.path} with HTTP 500, "
            f'"{FILTER_REFUSAL}": a data query needs area, item, element or year',
            source=SOURCE,
        )
    if body == UNKNOWN_DOMAIN:
        domain_code = unquote(match["domain_code"])
        return NotFoundError(
            f"FAOSTAT has no domain {domain_code!r}: {request.method} {request.url.path} "
            f'answered HTTP 500, "{UNKNOWN_DOMAIN}"; list_domains names the domains',
            source=SOURCE,
        )
    return None


config = ClientConfig(
    source=SOURCE,
    version=__version__,
    base_url=BASE_URL,
    rate_limit=RATE_LIMIT,
    classify=classify,
    cache=MemoryCache(),
)

# A source with a documented hourly or daily quota installs a QuotaPolicy of its own on
# config (conventions §6, ADR-0015); core's README shows how. FAOSTAT documents none.

auth = LoginAuth(source=SOURCE)
"""The process's one login: every request of ``client`` sends its token but those sent with
``auth=None``, the bulk downloads'."""

client = AsyncClient(config, auth=auth)

__all__ = [
    "API_KEY_ENV",
    "BASE_URL",
    "CREDENTIAL_REFUSALS",
    "EXPIRY_MARGIN",
    "FILTER_REFUSAL",
    "LOGIN_PATH",
    "PASSWORD_ENV",
    "RATE_LIMIT",
    "REFUSED",
    "SOURCE",
    "UNKNOWN_DOMAIN",
    "USERNAME_ENV",
    "LoginAuth",
    "auth",
    "classify",
    "client",
    "config",
]
