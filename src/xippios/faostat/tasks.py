"""Task functions, the public API: the adapters serve ``__all__`` (conventions §2).

``/add-endpoint`` adds them.

``get_data`` sends one ``get_data`` request (``api.get_data``) for a domain and the codes
given and returns the answer's rows; every request of the package carries the FAO
account's bearer token, ``_client.LoginAuth``'s. It sends ``lang=en`` and the output
options the portal sends, fixed (``OUTPUT_OPTIONS``: ``show_codes``, ``show_unit``,
``show_flags`` and ``show_notes`` true, ``null_values`` false, ``output_type`` objects;
not in the OpenAPI document, observed on 2026-10-29, FETCHED.md's "How this is
captured"), and ``page_size`` and ``page_number`` only when given: the default is one
request for every row the query matches. Release metadata: the data answer carries no
date, so ``meta.vintage`` is the domain's ``date_update`` as ``get_groupsanddomains``
prints it (``"2025-12-31"``), read after the data answer through the cache (one request
per process per five minutes), ``None`` for a domain the list lacks; ``meta.published_at``
stays ``None``, since a date is no release time (conventions §4; queue row 263).
``meta.total`` is ``None``: the answer counts no rows (ADR-0012).

``list_domains`` answers from ``get_groupsanddomains``, every domain and subgroup with its
group and release dates, filtered by ``search`` in Python (``xippios.core.matches``).
"""

from collections.abc import Mapping, Sequence
from typing import Any, Final

from xippios.core import InvalidRequestError, Result, ResultCap, ResultMeta, matches, sync

from xippios.faostat import api
from xippios.faostat._client import FILTER_REFUSAL, SOURCE
from xippios.faostat.models import DataRecord, Domain

__all__ = ["get_data", "list_domains"]

# A task named here is Python-only: no tool, no route; the adapters skip it (ADR-0019 decision 4).
BULK_TASKS: frozenset[str] = frozenset()

MCP_CAPS: Mapping[str, ResultCap] = {
    "get_data": ResultCap(
        max_rows=200,
        note=(
            "rows run area, item, year ascending; pass page_size and page_number, or "
            "narrower filters, to see the rest"
        ),
    ),
    "list_domains": ResultCap(
        note=(
            "pass search, a part of a domain's code or name or of its group's name "
            "(QCL, crops, production), to see the rest"
        ),
    ),
}
"""MCP result caps of their own, by task function name (conventions §8, ADR-0016).

``get_data`` keeps the family's 200 rows and 64 KB and adds a note naming its paging and
its filters; a row of the recorded answers is 356 (QCL) to 383 (PP) bytes as compact
JSON, so the bytes cut a page at about 170 rows. ``list_domains`` keeps the family's cap
too: its 78 rows of 2026-10-29 fit; the note names ``search``.
"""

LANG: Final = "en"
"""The language every task asks for, ``lang`` of the OpenAPI document's ``en``, ``fr``, ``es``."""

OUTPUT_OPTIONS: Mapping[str, bool | str] = {
    "show_codes": True,
    "show_unit": True,
    "show_flags": True,
    "show_notes": True,
    "null_values": False,
    "output_type": "objects",
}
"""The output options ``get_data`` sends, those the portal sends (FETCHED.md, observed
2026-10-29; not in the OpenAPI document): an answer without them carried the same 15
columns."""

Codes = str | int | Sequence[str | int]
"""One code or several: ``"231"``, ``2020`` or ``["15", "27"]``."""


def _joined(codes: Codes | None, name: str) -> str | None:
    """``codes`` as upstream's comma list, ``None`` when not given.

    Raises:
        InvalidRequestError: ``codes`` is empty, a text or a list without a code.
    """
    if codes is None:
        return None
    text = str(codes) if isinstance(codes, str | int) else ",".join(str(code) for code in codes)
    if not text:
        raise InvalidRequestError(
            f"{name} lists no code: give one code or several, or leave {name} out",
            source=SOURCE,
        )
    return text


async def _date_update(domain: str) -> str | None:
    """The domain's ``date_update`` as ``get_groupsanddomains`` prints it, else ``None``."""
    answer = await api.get_groupsanddomains.get_groupsanddomains(LANG)
    for row in answer.response.data:
        if row.domain_code == domain:
            return row.date_update
    return None


async def get_data_async(
    domain: str,
    *,
    area: Codes | None = None,
    item: Codes | None = None,
    element: Codes | None = None,
    year: Codes | None = None,
    area_cs: str | None = None,
    item_cs: str | None = None,
    page_size: int | None = None,
    page_number: int | None = None,
) -> Result[list[DataRecord]]:
    """Get one FAOSTAT domain's rows for the areas, items, elements and years given.

    One request to FAOSTAT's data endpoint, rows in upstream's order (area, item, year
    ascending in the recorded answers), every row with its codes and names, unit, value,
    flag and note. Give at least one of ``area``, ``item``, ``element`` and ``year``:
    FAOSTAT refuses a query without a filter ("Please add at least one filter."), and
    so does this task, before any request, with ``InvalidRequestError``. Without
    ``page_size`` every matching row comes in one answer, which for a whole domain runs
    to millions of rows: keep the filters narrow, or page. The element codes a query
    filters by are not those the rows print: ``element="2510"`` (Production Quantity)
    answers rows with ``element_code`` ``"5510"`` (Production), and ``5510`` as a filter
    matches nothing; ``codes/element/{domain}`` lists the filter codes, which
    ``list_elements`` will serve. A code that matches nothing gives an empty list, not
    an error; an unknown domain raises ``NotFoundError``. ``meta.vintage`` is the
    domain's last update as ``list_domains`` prints it (``"2025-12-31"``); the release
    date is there, ``meta.published_at`` stays ``None``. ``value`` is a number where
    upstream's text is one.

    Args:
        domain: The domain's code, as ``list_domains`` lists it, e.g. ``"QCL"`` (Crops
            and livestock products), ``"TCL"`` (trade in crops and livestock products),
            ``"FBS"`` (Food Balances, 2010-), ``"PP"`` (Producer Prices) or ``"RL"``
            (Land Use).
        area: One area code or several, FAO's codes unless ``area_cs`` says otherwise,
            e.g. ``"231"`` (United States of America) or ``["231", "79"]``.
        item: One item code or several, e.g. ``"15"`` (Wheat) or ``["15", "27"]``.
        element: One element code or several, the filter codes of the domain's element
            list, e.g. ``"2510"`` (Production Quantity in QCL), not the ``5510`` the
            rows print.
        year: One year or several, e.g. ``2020`` or ``[2015, 2016, 2017]``.
        area_cs: The coding system of ``area``, one the domain's dimensions list
            (``"M49"``, ``"FAO"``, ``"ISO2"``, ``"ISO3"`` in QCL); ``None`` sends FAO's
            codes, which the rows print under ``area_code``. Given, the rows print the
            codes under a header naming the system (``Area Code (M49)``), kept in
            ``columns``, and ``area_code`` is ``None``; ``area="840"`` with
            ``area_cs="M49"`` answered no rows on 2026-10-29.
        item_cs: The coding system of ``item``, ``"CPC"`` or ``"FAO"`` in QCL; ``None``
            sends FAO's codes, which the rows print under ``item_code``. Given, the rows
            print the codes under a header naming the system (``Item Code (FAO)``), kept
            in ``columns``, and ``item_code`` is ``None``.
        page_size: Rows per page, e.g. ``100``; with ``page_number``, one page of the
            answer. ``None`` returns every row.
        page_number: The page to return, from 1, e.g. ``2`` (rows 101 to 200 with
            ``page_size=100``).
    """
    filters = {
        "area": _joined(area, "area"),
        "item": _joined(item, "item"),
        "element": _joined(element, "element"),
        "year": _joined(year, "year"),
    }
    if all(value is None for value in filters.values()):
        raise InvalidRequestError(
            f'FAOSTAT refuses a data query without a filter ("{FILTER_REFUSAL}"): pass '
            "area, item, element or year",
            source=SOURCE,
        )
    sent: dict[str, Any] = {
        **filters,
        "area_cs": area_cs,
        "item_cs": item_cs,
        "page_size": page_size,
        "page_number": page_number,
        **OUTPUT_OPTIONS,
    }
    answer = await api.get_data.get_data(LANG, domain, **sent)
    vintage = await _date_update(domain)
    meta = ResultMeta(
        source=SOURCE,
        endpoint=api.get_data.ENDPOINT,
        retrieved_at=answer.retrieved_at,
        published_at=None,
        vintage=vintage,
        request={"lang": LANG, "domain_code": domain, **sent},
        total=None,
    )
    return Result(data=answer.response.data, meta=meta)


get_data = sync(get_data_async)


async def list_domains_async(*, search: str | None = None) -> Result[list[Domain]]:
    """List FAOSTAT's domains, the datasets ``get_data`` reads, with their groups and release dates.

    One request to ``groupsanddomains``, cached for five minutes. Each row is a domain
    (``domain_level`` 2 or 3) or a subgroup of domains (``domain_level`` 1,
    ``subgroup_flag`` ``"1"``, no dates), with its group, its last update
    (``date_update``), its current and next release and its contact, all as printed.

    Args:
        search: Text to look for, ignoring case, in a row's ``domain_code``,
            ``domain_name`` or ``group_name``, e.g. ``"QCL"``, ``"crops"`` or
            ``"prices"``; ``None`` lists every row.
    """
    answer = await api.get_groupsanddomains.get_groupsanddomains(LANG)
    rows = [
        row
        for row in answer.response.data
        if matches(search, row.domain_code, row.domain_name, row.group_name)
    ]
    meta = ResultMeta(
        source=SOURCE,
        endpoint=api.get_groupsanddomains.ENDPOINT,
        retrieved_at=answer.retrieved_at,
        published_at=None,
        vintage=None,
        request={"lang": LANG, "search": search},
        total=None,
    )
    return Result(data=rows, meta=meta)


list_domains = sync(list_domains_async)
