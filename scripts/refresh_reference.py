"""Refresh the packaged reference data from upstream (``/refresh-reference-data``).

The script declares FAOSTAT's packaged lists in one ``Lists`` and hands it to core's
``run`` (sdk-core ADR-0062), which fetches every list through the declared fetch, then
writes each to ``reference/<name>.json``, the provenance rows of ``reference/README.md``
and ``enums.py``; ``--only <list> [<list> ...]`` fetches the named lists alone and keeps
the others' files, and ``--render-only`` writes the rows and ``enums.py`` from the
packaged files without a request. The frame sends each request once through the
package's client and prints the requests it counted.

FAOSTAT's packaged lists are fifteen tables and no enum, as
https://github.com/xippios/sdk-faostat/pull/4 packaged them: the codes of the dimensions
``area``, ``element`` and ``item`` of QCL, TCL, FBS, PP and RL (``params.DIMENSIONS``,
``params.DOMAINS``), each fetched through ``api.get_code_list`` (``getCodeList``, ``GET
/en/codes/<dimension>/<domain>``, ``show_lists`` left to upstream's default) and written to
``reference/<dimension>_<domain>.json`` with the dimension as ``param``, the filter of the
data endpoint that takes the codes, its provenance row naming the operation and the path.
The dimension ids are those ``get_dimensions`` answers and the data endpoint filters by;
the subdimension ids the OpenAPI document's examples name (``countries``) answer a part of
a dimension's codes (``reference/README.md``). FAOSTAT reports no quota: no answer carried
an ``X-RateLimit-*``, ``RateLimit-*`` or ``Retry-After`` header
(``docs/upstream/OBSERVED.md``).

The API answers an account's requests only, so the script runs with the account's two
variables in the environment, ``FAOSTAT_USERNAME`` and ``FAOSTAT_PASSWORD``::

    uv run python scripts/refresh_reference.py

One login and fifteen requests, paced by the package's client at 30 a minute; the login
is not paced, since it runs inside the client's auth flow. A request refused with HTTP 401
or 403 logs in once more and is sent again once, so a run sends at most 46 requests, 16
of them logins, all to the API's host under the account. Core's count of the run holds
every request the client hands its transport, the logins and the resends after a refused
token among them, and the script names the logins among it (``counted_logins``, sdk-core
ADR-0062).
"""

import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

import httpx
from xippios.core.refresh import Listed, Lists, run

from xippios.faostat import api
from xippios.faostat._client import LoginAuth, auth, client
from xippios.faostat.models import CodeItem
from xippios.faostat.params import DIMENSIONS, DOMAINS, PACKAGE, PACKAGED_LISTS, table_name

LANG = "en"
"""The language the tables are fetched in, the tasks' ``lang``."""


def code_table(dimension: str, domain: str) -> Listed:
    """The packaged table of ``dimension`` in ``domain``: ``getCodeList``'s answer."""

    async def fetch() -> list[CodeItem]:
        answer = await api.get_code_list.get_code_list(LANG, dimension, domain)
        return answer.payload.data

    path = api.get_code_list.code_list_path(LANG, dimension, domain)
    return Listed(
        name=table_name(dimension, domain),
        fetch=fetch,
        endpoint=api.get_code_list.ENDPOINT,
        param=dimension,
        origin=f"`{api.get_code_list.ENDPOINT}`, `GET {path}`",
    )


LISTS = Lists(
    package=PACKAGE,
    lists=tuple(code_table(dimension, domain) for domain in DOMAINS for dimension in DIMENSIONS),
    packaged=PACKAGED_LISTS,
    client=client,
    quota_header=None,
)
"""The fifteen tables, domain by domain, the codes ``get_data`` checks and the list tasks
answer with; no enum."""


class Logins:
    """The logins among the requests that core's count of the run holds.

    Attributes:
        logins: The logins the client's auth flow built, a refused one too.
    """

    def __init__(self) -> None:
        self.logins = 0

    def built(self, request: httpx.Request) -> None:
        """Count a login built ahead of ``request``."""
        self.logins += 1

    def report(self) -> str:
        """The logins, one line after core's count."""
        return f"of them, logins: {self.logins}"


@contextmanager
def counted_logins(login: LoginAuth) -> Iterator[Logins]:
    """``login`` for the block with each login it builds counted, then the count printed.

    The flow builds each login through the instance, so a wrapper of ``token_request`` sees
    every one, a refused one too; the method is restored after the block, a failed run's
    too.
    """
    counted = Logins()
    build = login.token_request

    def token_request(request: httpx.Request) -> httpx.Request:
        built = build(request)
        counted.built(request)
        return built

    login.token_request = token_request  # type: ignore[method-assign]
    try:
        yield counted
    finally:
        del login.token_request
        print(counted.report())  # noqa: T201


def main(argv: Sequence[str] | None = None) -> int:
    """Run core's frame on ``LISTS`` and name the logins among the requests it counts.

    ``--render-only`` sends nothing and the frame prints no count for it, so the line of
    logins belongs to a run that fetches alone.
    """
    given = list(sys.argv[1:] if argv is None else argv)
    if "--render-only" in given:
        return run(LISTS, given)
    with counted_logins(auth):
        return run(LISTS, given)


if __name__ == "__main__":
    raise SystemExit(main())
