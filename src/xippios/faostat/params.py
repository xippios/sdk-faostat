"""The packaged reference lists, read from ``reference/`` without a call (conventions §3).

``/refresh-reference-data`` writes them; ``PackagedList.load(PACKAGE, name)`` reads one.

Fifteen tables ship inside the package, one per dimension and domain: the codes of the
dimensions ``area``, ``element`` and ``item`` (``DIMENSIONS``) of the domains QCL, TCL,
FBS, PP and RL (``DOMAINS``), each ``getCodeList``'s answer for
``codes/<dimension>/<domain>`` as ``scripts/refresh_reference.py`` fetched it, never
written by hand (Johannes, G5 2026-10-29, questions 3 and 5). A file is named
``<dimension>_<domain>.json``, the domain's code as upstream writes it
(``element_QCL.json``); its ``param`` is the dimension, the name of the data endpoint's
filter that takes its codes (``"element"``), its ``endpoint`` ``getCodeList``, and its
records ``models.CodeItem``'s fields under upstream's names, in upstream's order
(ADR-0022). ``list_areas``, ``list_elements`` and ``list_items`` answer from them, and
``get_data`` checks the codes of a packaged domain against them before it sends.

The element tables hold the codes a query filters by (``2510`` Production Quantity in
QCL), which are not the ``Element Code`` the data rows print (``5510`` Production);
nothing is translated between the two (ADR-0003; G5 2026-10-29, question 10). No enum is
generated from the tables; ``enums.py`` holds none. ``reference/README.md`` carries the
provenance of every file.
"""

import functools
from collections.abc import Mapping
from types import MappingProxyType

from xippios.core import PackagedList

from xippios.faostat._client import SOURCE
from xippios.faostat.models import CodeItem

__all__ = [
    "DIMENSIONS",
    "DOMAINS",
    "PACKAGE",
    "PACKAGED_LISTS",
    "codes",
    "labels",
    "packaged",
    "table_name",
]

PACKAGE = "xippios.faostat"

DIMENSIONS: tuple[str, ...] = ("area", "element", "item")
"""The dimensions packaged per domain, as ``get_dimensions`` names them and as the data
endpoint's filters are named: ``getCodeList``'s ``dimension_id``."""

DOMAINS: tuple[str, ...] = ("QCL", "TCL", "FBS", "PP", "RL")
"""The domains whose tables are packaged (G5 2026-10-29, question 5): Crops and livestock
products, their trade, Food Balances (2010-), Producer Prices and Land Use."""


def table_name(dimension: str, domain: str) -> str:
    """The packaged table of ``dimension`` in ``domain``, e.g. ``"element_QCL"``."""
    return f"{dimension}_{domain}"


PACKAGED_LISTS: tuple[str, ...] = tuple(
    table_name(dimension, domain) for domain in DOMAINS for dimension in DIMENSIONS
)
"""The lists that ship inside the package, ``reference/<name>.json``; the refresh script
writes exactly these, its ``TABLES``: ``area_QCL``, ``element_QCL``, ``item_QCL``,
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
def labels(name: str) -> Mapping[str, str]:
    """The packaged table ``name``'s codes to their labels, read once per process.

    Raises:
        FileNotFoundError: The package ships no such table.
    """
    return MappingProxyType({code.code: code.label for code in _codes(name)})
