"""``POST /auth/login``: ``auth_login``, the FAO account's login.

Reference: ``docs/upstream/openapi/faostat_openapi.yaml``, path ``/auth/login``, operation
``auth_login``: "Returns AccessToken, IdToken and RefreshToken from Cognito by providing
username and password", the request body ``application/x-www-form-urlencoded`` with the
required fields ``username`` ("usually an email") and ``password``, the answer the
``Auth`` schema; ``400`` Bad Request and ``401`` Unauthorized are documented without a
body. Recorded (``tests/fixtures/auth_login/``): an unknown user answers HTTP 400 with a
JSON body whose ``__type`` is ``UserNotFoundException``.

The package's client logs in by itself (``_client.LoginAuth``), on this path with these
fields; this wrapper is the operation as upstream documents it, for a caller that wants
the tokens, and the exchange the fixture recorder records. It sends no bearer
(``auth=None``) and is never cached (a POST). Refusals are core's mapping: HTTP 401 is
``AuthError``, HTTP 400 ``UpstreamError`` whose message quotes upstream's body.
"""

from xippios.core import parse
from xippios.core.client import decode_json

from xippios.faostat._client import LOGIN_PATH, SOURCE, client
from xippios.faostat.models import Auth

__all__ = ["ENDPOINT", "auth_login"]

ENDPOINT = "auth_login"
"""The operation's ``operationId``."""


async def auth_login(username: str, password: str) -> Auth:
    """Call ``auth_login``: log in with an account's user name and password; its tokens.

    Args:
        username: ``username``, the account's user name, its e-mail.
        password: ``password``, the account's password.

    Returns:
        The tokens, each a ``SecretStr``, and ``ExpiresIn``.

    Raises:
        AuthError: HTTP 401.
        UpstreamError: HTTP 400, e.g. ``UserNotFoundException`` for an unknown user.
        ValidationError: The answer is not the documented ``Auth``.
    """
    response = await client.request(
        "POST", LOGIN_PATH, data={"username": username, "password": password}, auth=None
    )
    payload = decode_json(response, source=SOURCE, path=LOGIN_PATH)
    return parse(Auth, payload, source=SOURCE, endpoint=ENDPOINT)
