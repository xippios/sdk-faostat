"""The package's one configured ``AsyncClient``, its login and its error mapping (conventions §6).

FAOSTAT's API answers an account's requests only: the OpenAPI document requires
``bearerAuth``, an HTTP bearer, on every operation, and ``auth_login`` (``POST
/auth/login``, form fields ``username`` and ``password``) issues the token
(``docs/upstream/openapi/faostat_openapi.yaml``). ``LoginAuth`` is the client's
``auth``, a ``RenewingBearerAuth`` of core's (sdk-core ADR-0025, amendment 2026-11-18,
point c) that writes what is FAOSTAT's: the login's request, the reading of its answer
and its refusals. On the first request of the process core's flow has it read
``FAOSTAT_USERNAME`` (the account's e-mail) and ``FAOSTAT_PASSWORD`` from the
environment, logs in, keeps the answer's ``AuthenticationResult.AccessToken`` and sends
it as ``Authorization: Bearer <token>`` on that request and every later one; requests
that start together while the login runs wait for it and send the token it brought. A
request sent with ``auth=None`` passes it by, and the client sends its auth to the base
URL's origin only: the bulk downloads' catalogue and files on ``bulks-faostat.fao.org``
(``api.datasets_e``, ``tasks.download_dataset``) go without a login and without the
token. The token lives ``ExpiresIn`` seconds (3600 in the recorded login); it is used for
that time less core's margin of 60 s, and the first request after it logs in again. A
request answered with HTTP 401 or 403 (``REFUSED``) logs in once more and is sent again,
once: a second 401 or 403 goes back to core, whose status mapping raises ``AuthError``.
So a request logs in at most twice (sdk-core ADR-0025). The login runs inside the request's
``httpx`` auth flow, below core's limiter, hooks, cache and ``classify``: a login is not
paced, observed or cached. A login refused with HTTP 401 or 403, or with HTTP 400 and
Cognito's ``UserNotFoundException`` (recorded for an unknown user) or
``NotAuthorizedException``, raises ``AuthError`` naming the status and upstream's
``__type``; any other answer but HTTP 200 raises what core's ``token_refused`` makes of
it (``RateLimitError`` for a 429, ``UpstreamError`` for a 5xx), quoting nothing of it.
The flow reads the login's answer and no other: the answer of the request it signs, a
streamed download's among them, goes back to the client unread.

Nothing of the account is logged, printed or kept but the access token: neither the
user name nor the password, read where the login request is built and kept in no
attribute and in no local that outlives the call, nor the answer's id token, which
carries the account's e-mail, nor its refresh token. The access token is kept as a
``SecretStr``, whose ``repr`` is masked. An error names a variable, a status and
upstream's ``__type``, never a value. ``ENV_VARS`` names the two variables for a host.

The developer portal (https://www.fao.org/faostat/en/#developer-portal) draws in the
browser with a guest token of its own; this package does not use it, it logs in with
the account, as https://github.com/xippios/sdk-faostat/pull/3 decided.

``classify`` maps the login's refusal of the credentials, HTTP 400 with Cognito's
``UserNotFoundException`` or ``NotAuthorizedException`` (recorded under
``tests/fixtures/auth_login/``), to ``AuthError``, and the data endpoint's two recorded
refusals, both HTTP 500 with a plain text body (``Content-Type: text/plain``;
``docs/upstream/OBSERVED.md``; ``tests/fixtures/get_data/``): ``Please add at least
one filter.`` to ``InvalidRequestError`` and ``Index: 0, Size: 0``, an unknown domain, to
``NotFoundError`` naming the domain. Everything else falls through to core's status
mapping: the 401 ``Missing Authorization Header`` and the 403 ``Authentication Failed``
(recorded under ``tests/fixtures/get_data/``) are ``AuthError`` there.

Answers of HTTP 200 are cached in core's ``MemoryCache`` with its default lifetime of
five minutes for every path, ``{"/": 300.0}``, up to core's ``cache_max_bytes`` of 8 MiB a
body (sdk-core ADR-0040, decision 3), once ``get_answer`` has decoded them, and an entry
whose five minutes have passed is dropped at the cache's next read or write:
``tasks.get_data``'s look-up of a domain's release date in ``get_groupsanddomains`` costs
one request per process per five minutes, as does the bulk catalogue (``datasets_E.json``,
107 KB), a larger data answer is returned and fetched again the next time, and an answer
that is not JSON is asked again. A bulk file goes through ``download`` and is never cached.
"""

import re
import time
from collections.abc import Callable
from urllib.parse import unquote

import httpx
import pydantic
from xippios.core import (
    AsyncClient,
    AuthError,
    BearerToken,
    ClientConfig,
    EnvVar,
    InvalidRequestError,
    MemoryCache,
    NotFoundError,
    RateLimit,
    RenewingBearerAuth,
    ValidationError,
    XippiosError,
    request_description,
    tool_name,
)

from xippios.faostat._version import __version__
from xippios.faostat.models import Auth

SOURCE = "faostat"
BASE_URL = "https://faostatservices.fao.org/api/v1"
USERNAME_ENV = "FAOSTAT_USERNAME"
"""The variable holding the FAO account's user name, its e-mail: ``auth_login``'s ``username``."""
# The variable's name, not a value: detect-secrets reads the assignment as one.
PASSWORD_ENV = "FAOSTAT_PASSWORD"  # pragma: allowlist secret
"""The variable holding the FAO account's password: ``auth_login``'s ``password``."""
ENV_VARS: tuple[EnvVar, ...] = (
    EnvVar(USERNAME_ENV, secret=True, required=True),
    EnvVar(PASSWORD_ENV, secret=True, required=True),
)
"""The variables the package reads, for a host (conventions §7; sdk-core ADR-0026, amendment
2026-11-18, point c): the account's two, both secret, since the user name is the account's
e-mail and never printed, and both required, since every request to the API logs in. An
``EnvVar`` names a variable and reads none."""
LOGIN_PATH = "/auth/login"
"""``auth_login``'s path, under ``BASE_URL``; ``api.auth_login`` and ``LoginAuth`` send it."""
REFUSED = frozenset({401, 403})
"""The statuses that make ``LoginAuth`` log in once more and send the request again: FAOSTAT
refuses a bearer with either (``tests/fixtures/get_data/``)."""
# A self-imposed pace: upstream documents no per-second or per-minute limit (sdk-core ADR-0033
# decision 1).
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

    Never a credential: the message names the request as ``request_description`` does,
    the status and the ``__type``, and the body is not quoted.
    """
    status = response.status_code
    kind = _upstream_type(response)
    return AuthError(
        f"FAOSTAT refused the login: {request_description(response)} answered HTTP "
        f"{status}{f' ({kind})' if kind else ''}{hint}",
        status=status,
        source=source,
    )


class LoginAuth(RenewingBearerAuth):
    """Log in with the FAO account, send its access token, log in again when it lapses.

    Core's ``RenewingBearerAuth`` (sdk-core ADR-0025, amendment 2026-11-18, point c) with
    what is FAOSTAT's: ``token_request`` builds ``auth_login``'s request on ``base_url``
    (``POST /auth/login``, form-encoded ``username`` and ``password`` from
    ``FAOSTAT_USERNAME`` and ``FAOSTAT_PASSWORD``, read through ``credential`` there and
    kept in no attribute), ``read_token`` keeps the answer's access token and its
    ``ExpiresIn``, and ``token_refused`` names the two variables when the login refuses
    them. Core keeps the token, a ``SecretStr``, until 60 s before it lapses, logs in once
    for requests that start together, and logs in once more on a 401 or a 403
    (``renew_on``), sending the request again once; that answer is returned as it is,
    unread. It runs on core's async client only.

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
            core's ``token_refused``, e.g. ``RateLimitError`` for a 429, ``UpstreamError``
            for a 5xx.
        ValidationError: From a request, when the login's HTTP 200 is not the documented
            ``Auth`` answer; nothing of the answer is quoted.
    """

    renew_on = REFUSED

    def __init__(
        self,
        *,
        source: str | None = None,
        base_url: str = BASE_URL,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(source=source, clock=clock)
        self.login_url = httpx.URL(base_url.rstrip("/") + LOGIN_PATH)

    def credential_help(self, name: str) -> str:
        """What the ``ConfigError`` of an unset variable tells the user: the account's two."""
        return (
            f"FAOSTAT needs a FAO account: export {USERNAME_ENV} (the account's e-mail) and "
            f"{PASSWORD_ENV}"
        )

    def token_request(self, request: httpx.Request) -> httpx.Request:
        """``auth_login``'s request, sent ahead of ``request``, with its ``User-Agent``."""
        return httpx.Request(
            "POST",
            self.login_url,
            data={
                "username": self.credential(USERNAME_ENV),
                "password": self.credential(PASSWORD_ENV),
            },
            headers={"Accept": "application/json"},
        )

    def read_token(self, response: httpx.Response) -> BearerToken:
        """The access token and its ``ExpiresIn`` from the login's HTTP 200.

        Raises:
            ValidationError: The answer is not the documented ``Auth`` answer; nothing of
                it is quoted.
        """
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
        return BearerToken(token=result.access_token, expires_in=result.expires_in)

    def token_refused(self, response: httpx.Response) -> XippiosError:
        """``AuthError`` naming the two variables for a refusal of the credentials, else core's.

        A refusal is HTTP 401 or 403, or HTTP 400 with Cognito's ``UserNotFoundException``
        or ``NotAuthorizedException``; any other status is core's ``token_refused``.
        """
        if _credentials_refused(response):
            return _login_refused(
                response, source=self.source, hint=f"; check {USERNAME_ENV} and {PASSWORD_ENV}"
            )
        return super().token_refused(response)


def classify(response: httpx.Response) -> XippiosError | None:
    """Upstream's recorded refusals as taxonomy errors, else ``None`` (conventions §6).

    The ``ClientConfig.classify`` hook: it sees every response before core's status
    mapping. ``POST /auth/login`` refuses the credentials with HTTP 400 and a JSON body
    whose ``__type`` is Cognito's (``CREDENTIAL_REFUSALS``: ``UserNotFoundException``,
    recorded for an unknown user, and ``NotAuthorizedException``): that is ``AuthError``,
    upstream's refusal of the credentials (conventions §5), naming the status and the
    ``__type``, never a credential; ``api.auth_login`` raises it, and ``LoginAuth``, whose
    login runs below this hook, raises the same for it and for a login's 401 or 403, and
    core's ``token_refused`` for any other status. ``GET /{lang}/data/{domain_code}`` answers two
    refusals with HTTP 500 and a plain text body (``Content-Type: text/plain``), recorded
    on 2026-10-29:

    - ``Please add at least one filter.``, a query without ``area``, ``item``,
      ``element`` or ``year``, is ``InvalidRequestError``, upstream's refusal of the
      query as given (sdk-core ADR-0007); ``tasks.get_data`` refuses such a query before
      sending;
    - ``Index: 0, Size: 0``, a domain code FAOSTAT does not have, is ``NotFoundError``
      naming the domain and the task, and its tool, that lists the domains (conventions §8).

    Everything else falls through, and core's mapping applies: the 401 and 403 of a
    request without a valid token are ``AuthError``, another 500 ``UpstreamError``.
    Messages name the method and the path, ``request_description``'s, never the host or
    the query (conventions §5).
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
            f"FAOSTAT refused {request_description(response)} with HTTP 500, "
            f'"{FILTER_REFUSAL}": a data query needs area, item, element or year',
            source=SOURCE,
        )
    if body == UNKNOWN_DOMAIN:
        domain_code = unquote(match["domain_code"])
        return NotFoundError(
            f"FAOSTAT has no domain {domain_code!r}: {request_description(response)} answered "
            f'HTTP 500, "{UNKNOWN_DOMAIN}"; list_domains names the domains (over MCP, the '
            f"tool {tool_name(SOURCE, 'list_domains')})",
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
# config (conventions §6, sdk-core ADR-0037); core's README shows how. FAOSTAT documents none.

auth = LoginAuth(source=SOURCE)
"""The process's one login: every request of ``client`` sends its token but those sent with
``auth=None``, the bulk downloads'."""

client = AsyncClient(config, auth=auth)

__all__ = [
    "BASE_URL",
    "CREDENTIAL_REFUSALS",
    "ENV_VARS",
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
