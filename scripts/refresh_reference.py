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
is committed (ADR-0008). Where a member name derives to nothing, or two collide, name it
by hand in ``render``'s call: ``render_enums(member_names=...)``, per list and value (an
id for an ``IntEnum``).

Only lists that are the same for every caller are packaged; a multi-tenant source
packages no tenant data (ADR-0014). Run from the repository root, with whatever the list
endpoints need in the environment (a key only where they take one)::

    uv run python scripts/refresh_reference.py

``--render-only`` regenerates ``enums.py`` from the packaged ``reference/*.json`` alone,
without a request and without a key: after a core release changes the renderer
(conventions §15, item 6), it changes ``enums.py`` and nothing else.
"""

import argparse
import subprocess
import sys
from collections.abc import Callable, Coroutine, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xippios.core import PackagedList, UpstreamModel, sync
from xippios.core.reference import id_name_pairs, render_enums

from xippios.faostat.params import PACKAGED_LISTS

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "src/xippios/faostat"
REFERENCE = PACKAGE_DIR / "reference"
ENUMS = PACKAGE_DIR / "enums.py"
GENERATOR = "scripts/refresh_reference.py"

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

TABLES: dict[str, tuple[str, Records]] = {
    # the list to (the upstream operation, an async fetcher of its records through api/), e.g.
    # "commodities": ("GetCommodities", api.GetCommodities),
}
"""Record lists packaged as tables, with no enum, e.g. the codes ``params`` checks."""


def packaged(name: str, endpoint: str, records: Sequence[dict[str, Any]]) -> PackagedList:
    """The list ``name`` as just fetched from ``endpoint``, for ``reference/<name>.json``."""
    return PackagedList(
        param=name, endpoint=endpoint, fetched=datetime.now(UTC), records=list(records)
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
    class_names: dict[str, str] = {}
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
        class_names[id_field] = id_field[:1].upper() + id_field[1:]
    module = render_enums(lists, fetched=fetched, class_names=class_names, generator=GENERATOR)
    ENUMS.write_text(module, encoding="utf-8")
    sys.stdout.flush()
    for command in (["format"], ["check", "--fix"]):
        run = subprocess.run([sys.executable, "-m", "ruff", *command, str(ENUMS)], cwd=ROOT)
        if run.returncode:
            raise SystemExit(f"ruff {' '.join(command)} left {ENUMS.name} failing")
    print(f"{ENUMS.name}: {len(lists)} enums")  # noqa: T201


def refresh() -> None:
    """Fetch every list, then write its file, then regenerate ``enums.py`` from the files."""
    if sorted([*LISTS, *ID_LISTS, *TABLES]) != sorted(PACKAGED_LISTS):
        raise SystemExit("LISTS, ID_LISTS and TABLES name other lists than params.PACKAGED_LISTS")
    lists = [
        *(
            packaged(name, endpoint, [{name: value} for value in sync(fetch)()])
            for name, (endpoint, fetch) in LISTS.items()
        ),
        *(
            packaged(name, endpoint, [record.dump_upstream() for record in sync(fetch)()])
            for name, (endpoint, fetch, _, _) in ID_LISTS.items()
        ),
        *(
            packaged(name, endpoint, [record.dump_upstream() for record in sync(fetch)()])
            for name, (endpoint, fetch) in TABLES.items()
        ),
    ]
    REFERENCE.mkdir(exist_ok=True)
    for fetched in lists:
        path = REFERENCE / f"{fetched.param}.json"
        fetched.write(path)
        print(f"{path.name}: {len(fetched.records)} records from {fetched.endpoint}")  # noqa: T201
    render()


def main() -> None:
    """Refresh from upstream, or with ``--render-only`` regenerate ``enums.py`` alone."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="regenerate enums.py from the packaged reference/*.json, without a request or a key",
    )
    args = parser.parse_args()
    if args.render_only:
        render()
    else:
        refresh()


if __name__ == "__main__":
    main()
