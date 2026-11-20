"""Refresh the packaged reference data from upstream (``/refresh-reference-data``).

Every list in ``LISTS``, ``ID_LISTS`` or ``TABLES`` is fetched through the layer-1
wrappers in ``api/``, never through a task that might answer from the package; once all
are fetched, each is written to ``reference/<name>.json`` by ``PackagedList.write``: the
list's name, the upstream operation it came from, the UTC time of the fetch to the second
and upstream's records under upstream's field names (``dump_upstream``), a value list as
records of one field named by the list (conventions §3). ``TABLES`` are packaged without
an enum. Then ``enums.py`` is regenerated from the packaged files by one
``xippios.core.reference.render_enums`` call, a ``StrEnum`` per value list in ``LISTS``
and an ``IntEnum`` per list of integer ids and names in ``ID_LISTS`` (``id_name_pairs``),
so that a member compares equal to the id in upstream's data, each class naming the day
its list was fetched; and formatted with ``ruff format`` and ``ruff check --fix``, as it
is committed (sdk-core ADR-0031). Where a member name derives to nothing, or two collide,
name it by hand in ``render``'s call: ``render_enums(member_names=...)``, per list and
value (an id for an ``IntEnum``); a class takes core's default name, from its list or its
id field, unless ``render_enums(class_names=...)`` names it.

Only lists that are the same for every caller are packaged; a multi-tenant source
packages no tenant data (sdk-core ADR-0036). Run from the repository root, with whatever
the list endpoints need in the environment: FAOSTAT's take the account, as the last
paragraph says.

The package's client sends each request once, ``RetryPolicy(max_attempts=1)``, so a 5xx
or a 429 spends no second keyed call: a run that fails writes nothing and is run again.
After the fetches it prints the requests it sent, the logins among them, and the quota
left that upstream reported, a failed run's too, a refused login and a failed renewal
included; FAOSTAT reports none (``QUOTA_HEADER``). A request that fails in transport is
not counted: its error ends the run.
``--only <list> [<list> ...]`` fetches the named tables alone, writes their files and
keeps every other table's file as it is, as a change that packages a new table does; the
provenance rows and ``enums.py`` are then written from all of them, so every table it
keeps must be packaged already. That, the names ``--only`` takes and the provenance table
of ``reference/README.md`` are checked before the first request.

``--render-only`` regenerates ``enums.py`` from the packaged ``reference/*.json`` alone,
without a request and without a key: after a core release changes the renderer
(conventions §15, item 6), it changes ``enums.py`` and nothing else.

FAOSTAT's packaged lists are fifteen tables and no enum (Johannes, G5 2026-10-29,
questions 3 and 5): the codes of the dimensions ``area``, ``element`` and ``item`` of the
domains QCL, TCL, FBS, PP and RL (``params.DIMENSIONS``, ``params.DOMAINS``), each
fetched through ``api.get_code_list`` (``getCodeList``, ``GET
/en/codes/<dimension>/<domain>``, ``show_lists`` left to upstream's default) and written
to ``reference/<dimension>_<domain>.json`` with the dimension as ``param``, the filter of
the data endpoint that takes the codes, so ``LISTS`` and ``ID_LISTS`` stay empty and
``enums.py`` an empty module. The dimension ids are those ``get_dimensions`` answers and
the data endpoint filters by; the subdimension ids the OpenAPI document's examples name
(``countries``) answer a part of a dimension's codes (``reference/README.md``). After
the files, the script rewrites the provenance table of ``reference/README.md`` from them,
one row per file: the operation, the path, the fetch time. The API answers an account's
requests only, so the script runs with the account's two variables in the environment,
through ``direnv exec`` from the family workspace's root (``CLAUDE.md``)::

    direnv exec <workspace root> uv run python scripts/refresh_reference.py

One login and fifteen requests, paced by the package's client at 30 a minute; the login
is not paced, since it runs inside the client's auth flow. A request refused with HTTP 401
or 403 logs in once more and is sent again once, so a run sends at most 46 requests, 16
of them logins, all to the API's host under the account.
"""

import argparse
import subprocess
import sys
from collections.abc import Callable, Coroutine, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

import httpx
from xippios.core import AsyncClient, PackagedList, RetryPolicy, UpstreamModel, sync
from xippios.core.reference import id_name_pairs, render_enums

from xippios.faostat import api
from xippios.faostat._client import LoginAuth, auth, client
from xippios.faostat.models import CodeItem
from xippios.faostat.params import DIMENSIONS, DOMAINS, PACKAGED_LISTS, table_name

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "src/xippios/faostat"
REFERENCE = PACKAGE_DIR / "reference"
ENUMS = PACKAGE_DIR / "enums.py"
README = REFERENCE / "README.md"
GENERATOR = "scripts/refresh_reference.py"
LANG = "en"
"""The language the tables are fetched in, the tasks' ``lang``."""
PROVENANCE_HEADER = "| File | Origin | Fetched |"
"""The header of ``reference/README.md``'s provenance table, whose rows the refresh writes."""
QUOTA_HEADER: str | None = None
"""The response header in which upstream reports the requests left in its quota: none,
since FAOSTAT documents no quota and no answer carried an ``X-RateLimit-*``,
``RateLimit-*`` or ``Retry-After`` header (``docs/upstream/FETCHED.md``)."""

Values = Callable[[], Coroutine[Any, Any, Sequence[str]]]
"""An async fetcher of a list's values through ``api/``."""

Records = Callable[[], Coroutine[Any, Any, Sequence[UpstreamModel]]]
"""An async fetcher of a list's records through ``api/``, e.g. the wrapper itself."""

LISTS: dict[str, tuple[str, Values]] = {
    # the list, as upstream names the parameter, to (the upstream operation, an async
    # fetcher of its values through api/), e.g.
    # "state_alpha": ("get_param_values", lambda: api.get_param_values("state_alpha")),
}
"""Value lists, packaged as records of one field named by the list, one ``StrEnum`` each."""

ID_LISTS: dict[str, tuple[str, Records, str, str]] = {
    # the list to (the upstream operation, an async fetcher of its records through api/,
    # the id field, the name field), the fields as upstream names them, e.g.
    # "unitsOfMeasure": ("GetUnitsOfMeasure", api.GetUnitsOfMeasure, "unitId", "unitDescription"),
}
"""Lists of integer ids and names, packaged as upstream's records, one ``IntEnum`` each.

Each enum is keyed by its id field and named after it, ``unitId`` making ``UnitId``,
whose docstring reads "Values of ``unitId``" (conventions §3).
"""


class Table(NamedTuple):
    """A packaged table: where it comes from and how it is fetched.

    Attributes:
        endpoint: The upstream operation, the file's ``endpoint``, e.g. ``"getCodeList"``.
        param: The upstream parameter its codes feed, the file's ``param``, e.g.
            ``"element"``.
        path: The URL path it is fetched from, under ``BASE_URL``, e.g.
            ``"/en/codes/element/QCL"``, for the provenance row.
        fetch: An async fetcher of its records through ``api/``.
    """

    endpoint: str
    param: str
    path: str
    fetch: Records


async def fetch_codes(dimension: str, domain: str) -> list[CodeItem]:
    """The codes of ``dimension`` in ``domain`` through ``api.get_code_list``: one request."""
    answer = await api.get_code_list.get_code_list(LANG, dimension, domain)
    return answer.payload.data


def code_table(dimension: str, domain: str) -> Table:
    """The packaged table of ``dimension`` in ``domain``: ``getCodeList``'s answer."""

    async def fetch() -> list[CodeItem]:
        return await fetch_codes(dimension, domain)

    return Table(
        endpoint=api.get_code_list.ENDPOINT,
        param=dimension,
        path=api.get_code_list.code_list_path(LANG, dimension, domain),
        fetch=fetch,
    )


TABLES: dict[str, Table] = {
    table_name(dimension, domain): code_table(dimension, domain)
    for domain in DOMAINS
    for dimension in DIMENSIONS
}
"""Record lists packaged as tables, with no enum: the codes ``get_data`` checks and the
list tasks answer with, ``reference/<dimension>_<domain>.json``, fifteen of them."""


class Meter:
    """What a run spent: the requests it sent, the logins among them, and the quota left.

    The client's ``observe`` hook, which core calls with every response from the wire. It
    calls the hook the client had first, a quota policy's say (sdk-core ADR-0037), and keeps
    the last count that upstream sent in ``QUOTA_HEADER``. A request is counted by its
    response: with no retry each has one, but for one that fails in transport, whose error
    ends the run. The login runs inside the client's auth flow, below the hook, so
    ``metered`` counts it where the flow builds it, through ``exchanged``, whether it is
    then answered or refused: a login the flow builds for a signed request renews a token
    that request was refused with, and the refused request is counted with it. The
    script's requests go one at a time, so no other request's login renews that token.
    """

    def __init__(self, observe: Callable[[httpx.Response], None] | None) -> None:
        self.sent = 0
        self.logins = 0
        self.left: int | None = None
        self._observe = observe

    def __call__(self, response: httpx.Response) -> None:
        """Count ``response`` and keep the quota it reports, after the hook it replaces."""
        if self._observe is not None:
            self._observe(response)
        self.sent += 1
        value = response.headers.get(QUOTA_HEADER) if QUOTA_HEADER else None
        if value is not None and value.isascii() and value.isdigit():
            self.left = int(value)

    def exchanged(self, request: httpx.Request) -> None:
        """Count a login built ahead of ``request``, and ``request`` where it was refused.

        ``request`` carries a bearer only where the flow renews the token it was refused
        with; the first login of a run, or one after the token lapsed, precedes an
        unsigned request.
        """
        self.sent += 1
        self.logins += 1
        if "authorization" in request.headers:
            self.sent += 1

    def report(self) -> str:
        """The requests sent, the logins among them and the quota left, one line."""
        left = "not reported" if self.left is None else f"{self.left} ({QUOTA_HEADER})"
        return f"requests sent: {self.sent}, logins among them: {self.logins}; quota left: {left}"


@contextmanager
def metered(target: AsyncClient, login: LoginAuth) -> Iterator[Meter]:
    """``target`` for the block: one attempt per request, each counted, then the report.

    ``RetryPolicy(max_attempts=1)`` keeps a 5xx or a 429 from spending a second keyed
    call. ``login``, ``target``'s auth, has its ``token_request`` wrapped for the block, so
    each login it builds is counted, a refused one too. ``target``'s configuration and
    ``login``'s method are restored after the block, and the report is printed, a failed
    run's too.
    """
    configured = target.config
    meter = Meter(configured.observe)
    build = login.token_request

    def counted(request: httpx.Request) -> httpx.Request:
        built = build(request)
        meter.exchanged(request)
        return built

    target.config = replace(configured, retry=RetryPolicy(max_attempts=1), observe=meter)
    # The flow builds each login through the instance, so the wrapper sees every one.
    login.token_request = counted  # type: ignore[method-assign]
    try:
        yield meter
    finally:
        del login.token_request
        target.config = configured
        print(meter.report())  # noqa: T201


def packaged(
    name: str, endpoint: str, records: Sequence[dict[str, Any]], *, param: str | None = None
) -> PackagedList:
    """The list ``name`` as just fetched from ``endpoint``, for ``reference/<name>.json``.

    ``param`` is the upstream parameter the list feeds, ``name`` itself when ``None``.
    """
    return PackagedList(
        param=param or name, endpoint=endpoint, fetched=datetime.now(UTC), records=list(records)
    )


def read(name: str) -> PackagedList:
    """The packaged ``reference/<name>.json``, as ``refresh`` wrote it."""
    path = REFERENCE / f"{name}.json"
    if not path.is_file():
        raise SystemExit(f"{path.name} is not packaged yet: run the script without --render-only")
    return PackagedList.model_validate_json(path.read_text(encoding="utf-8"))


def render() -> None:
    """Regenerate ``enums.py`` from the packaged files and format it as it is committed."""
    lists: dict[str, Sequence[str] | Sequence[tuple[int, str]]] = {}
    fetched: dict[str, str] = {}
    keys = [*LISTS, *(id_field for _, _, id_field, _ in ID_LISTS.values())]
    if len(set(keys)) < len(keys):
        raise SystemExit("an id field of ID_LISTS names a list of LISTS: one enum each")
    for name in LISTS:
        values = read(name)
        lists[name] = [record[name] for record in values.records]
        fetched[name] = f"{values.fetched:%Y-%m-%d}"
    for name, (_, _, id_field, name_field) in ID_LISTS.items():
        ids = read(name)
        lists[id_field] = id_name_pairs(ids.records, id_field=id_field, name_field=name_field)
        fetched[id_field] = f"{ids.fetched:%Y-%m-%d}"
    module = render_enums(lists, fetched=fetched, generator=GENERATOR)
    ENUMS.write_text(module, encoding="utf-8")
    sys.stdout.flush()
    for command in (["format"], ["check", "--fix"]):
        run = subprocess.run([sys.executable, "-m", "ruff", *command, str(ENUMS)], cwd=ROOT)
        if run.returncode:
            raise SystemExit(f"ruff {' '.join(command)} left {ENUMS.name} failing")
    print(f"{ENUMS.name}: {len(lists)} enums")  # noqa: T201


def provenance_rows() -> list[str]:
    """The provenance table's rows, one per table, from the packaged files as written."""
    rows = []
    for name, table in TABLES.items():
        listed = read(name)
        rows.append(
            f"| `{name}.json` | `{listed.endpoint}`, `GET {table.path}` | "
            f"{listed.fetched:%Y-%m-%dT%H:%M:%SZ} |"
        )
    return rows


def check_provenance(readme: str) -> None:
    """Stop unless ``readme`` holds the provenance table under ``PROVENANCE_HEADER``.

    Raises:
        SystemExit: ``readme`` holds no provenance table.
    """
    if PROVENANCE_HEADER not in readme.splitlines():
        raise SystemExit(f"{README.name} has no table headed {PROVENANCE_HEADER!r}")


def with_provenance(readme: str, rows: Sequence[str]) -> str:
    """``readme`` with the rows of its provenance table replaced by ``rows``.

    The table is the one under ``PROVENANCE_HEADER``: its separator line is kept, and
    every line after it that starts with ``|`` is replaced; the text around is kept.

    Raises:
        SystemExit: ``readme`` holds no provenance table.
    """
    check_provenance(readme)
    lines = readme.splitlines()
    start = lines.index(PROVENANCE_HEADER) + 2
    end = start
    while end < len(lines) and lines[end].startswith("|"):
        end += 1
    return "\n".join([*lines[:start], *rows, *lines[end:]]) + "\n"


def refresh(only: Sequence[str] = ()) -> None:
    """Fetch every table, then write its file, the provenance rows and ``enums.py``.

    ``only``, the tables ``--only`` names, fetches those alone and keeps every other
    table's file, which must be packaged already, since the provenance rows and the render
    read every file. Both, and the README's provenance table, are checked before the first
    request, and every table is fetched before the first file is written, each request
    sent once and counted.
    """
    names = [*LISTS, *ID_LISTS, *TABLES]
    if sorted(names) != sorted(PACKAGED_LISTS):
        raise SystemExit("LISTS, ID_LISTS and TABLES name other lists than params.PACKAGED_LISTS")
    if unknown := [name for name in only if name not in names]:
        raise SystemExit(f"--only: no list {', '.join(unknown)} in {', '.join(names)}")
    chosen = set(only or names)
    kept = [name for name in names if name not in chosen]
    if missing := [name for name in kept if not (REFERENCE / f"{name}.json").is_file()]:
        raise SystemExit(f"{', '.join(missing)} is not packaged yet: run without --only")
    check_provenance(README.read_text(encoding="utf-8"))
    with metered(client, auth):
        lists = [
            *(
                (name, packaged(name, endpoint, [{name: value} for value in sync(fetch)()]))
                for name, (endpoint, fetch) in LISTS.items()
                if name in chosen
            ),
            *(
                (
                    name,
                    packaged(name, endpoint, [record.dump_upstream() for record in sync(fetch)()]),
                )
                for name, (endpoint, fetch, _, _) in ID_LISTS.items()
                if name in chosen
            ),
            *(
                (
                    name,
                    packaged(
                        name,
                        table.endpoint,
                        [record.dump_upstream() for record in sync(table.fetch)()],
                        param=table.param,
                    ),
                )
                for name, table in TABLES.items()
                if name in chosen
            ),
        ]
    REFERENCE.mkdir(exist_ok=True)
    for name, fetched in lists:
        path = REFERENCE / f"{name}.json"
        fetched.write(path)
        print(f"{path.name}: {len(fetched.records)} records from {fetched.endpoint}")  # noqa: T201
    README.write_text(
        with_provenance(README.read_text(encoding="utf-8"), provenance_rows()), encoding="utf-8"
    )
    print(f"{README.name}: {len(TABLES)} provenance rows")  # noqa: T201
    render()


def main(argv: Sequence[str] | None = None) -> None:
    """Refresh from upstream, some tables with ``--only``, or ``enums.py`` alone."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument(
        "--render-only",
        action="store_true",
        help="regenerate enums.py from the packaged reference/*.json, without a request or a key",
    )
    choice.add_argument(
        "--only",
        nargs="+",
        default=[],
        metavar="LIST",
        help="fetch these tables alone, e.g. element_QCL, and keep every other table's file",
    )
    args = parser.parse_args(argv)
    if args.render_only:
        render()
    else:
        refresh(args.only)


if __name__ == "__main__":
    main()
