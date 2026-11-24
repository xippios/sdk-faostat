"""The packaged reference lists, read from ``reference/`` without a call (conventions §3).

``/refresh-reference-data`` writes them; ``PackagedList.load(PACKAGE, name)`` reads one.

Fifteen tables ship inside the package, one per dimension and domain: the codes of the
dimensions ``area``, ``element`` and ``item`` (``DIMENSIONS``) of the domains QCL, TCL,
FBS, PP and RL (``DOMAINS``), each ``getCodeList``'s answer for
``codes/<dimension>/<domain>`` as ``scripts/refresh_reference.py`` fetched it, never
written by hand (https://github.com/xippios/sdk-faostat/pull/4). A file is named
``<dimension>_<domain>.json``, the domain's code as upstream writes it
(``element_QCL.json``); its ``param`` is the dimension, the name of the data endpoint's
filter that takes its codes (``"element"``), its ``endpoint`` ``getCodeList``, and its
records ``models.CodeItem``'s fields under upstream's names, in upstream's order
(sdk-core ADR-0041). ``list_areas``, ``list_elements`` and ``list_items`` answer from
them, and ``get_data`` checks the codes of a packaged domain against them before it
sends, by core's ``check`` on each table's declaration, ``table(name)``.

The element tables hold the codes a query filters by, which the data rows do not print:
``docs/upstream/OBSERVED.md`` notes the two element code systems, and nothing is
translated between them (sdk-core ADR-0028).
No enum is generated from the tables, so the package has no ``enums.py``. ``reference/README.md``
carries the provenance of every file.
"""

import functools

from xippios.core import PackagedCodes, PackagedList

from xippios.faostat._client import SOURCE
from xippios.faostat.models import CodeItem

__all__ = [
    "DIMENSIONS",
    "DOMAINS",
    "PACKAGE",
    "PACKAGED_LISTS",
    "codes",
    "packaged",
    "table",
    "table_name",
]

PACKAGE = "xippios.faostat"

DIMENSIONS: tuple[str, ...] = ("area", "element", "item")
"""The dimensions packaged per domain, as ``get_dimensions`` names them and as the data
endpoint's filters are named: ``getCodeList``'s ``dimension_id``."""

DOMAINS: tuple[str, ...] = ("QCL", "TCL", "FBS", "PP", "RL")
"""The domains whose tables are packaged: Crops and livestock products, their trade, Food
Balances (2010-), Producer Prices and Land Use (https://github.com/xippios/sdk-faostat/pull/4)."""


def table_name(dimension: str, domain: str) -> str:
    """The packaged table of ``dimension`` in ``domain``, e.g. ``"element_QCL"``."""
    return f"{dimension}_{domain}"


PACKAGED_LISTS: tuple[str, ...] = tuple(
    table_name(dimension, domain) for domain in DOMAINS for dimension in DIMENSIONS
)
"""The lists that ship inside the package, ``reference/<name>.json``; the refresh script
declares exactly these in its one ``LISTS``: ``area_QCL``, ``element_QCL``, ``item_QCL``,
``area_TCL`` and so on, domain by domain."""


@functools.cache
def packaged(name: str) -> PackagedList:
    """The packaged table ``reference/<name>.json``, read once per process.

    Raises:
        FileNotFoundError: The package ships no such table.
        ValidationError: The file is not a packaged list.
    """
    return PackagedList.load(PACKAGE, name)


@functools.cache
def _codes(name: str) -> tuple[CodeItem, ...]:
    return tuple(packaged(name).parse(CodeItem, source=SOURCE))


def codes(name: str) -> list[CodeItem]:
    """The codes of the packaged table ``name`` (``"area_QCL"``), in upstream's order.

    A new list each call.

    Raises:
        FileNotFoundError: The package ships no such table.
    """
    return list(_codes(name))


@functools.cache
def table(name: str) -> PackagedCodes:
    """The packaged table ``name`` (``"element_QCL"``) declared once, for core's ``check``.

    Its codes under ``code`` and their names under ``label``, compared as given, the table
    named by its file in a refusal (conventions §5; sdk-core ADR-0045).

    Raises:
        FileNotFoundError: The package ships no such table.
    """
    return packaged(name).codes("code", "label", list_name=name, source=SOURCE)
