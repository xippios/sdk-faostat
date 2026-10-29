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

``list_areas``, ``list_elements`` and ``list_items`` answer from the package's copies of
``getCodeList``'s ``codes/<dimension>/<domain>`` for QCL, TCL, FBS, PP and RL
(``params``; Johannes, G5 2026-10-29, questions 3 and 5), without a request, filtered by
``search`` over code and label; ``meta`` is the packaged file's (``PackagedList.meta``:
``endpoint`` ``getCodeList``, ``retrieved_at`` the file's ``fetched``, ``vintage`` and
``total`` ``None``; ADR-0022). With them ``get_data`` checks the area, element and item
codes of those five domains before it sends, since FAOSTAT answers an unknown code with
no rows: a code the domain's table lacks is refused with core's ``UnknownCode``, naming
the table, its fetch date and the closest codes (conventions §5; ADR-0022, amendment
2026-10-27, decision 3). The element tables hold the filter codes, not the codes the
rows print, and nothing is translated between the two (ADR-0003; G5, question 10).
"""

from collections.abc import Mapping, Sequence
from typing import Any, Final

from xippios.core import (
    InvalidRequestError,
    Result,
    ResultCap,
    ResultMeta,
    UnknownCode,
    closest,
    matches,
    sync,
)

from xippios.faostat import api, params
from xippios.faostat._client import FILTER_REFUSAL, SOURCE
from xippios.faostat.models import CodeItem, DataRecord, Domain

__all__ = ["get_data", "list_areas", "list_domains", "list_elements", "list_items"]

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
    "list_areas": ResultCap(
        max_rows=1000,
        note=(
            "pass search, a part of the code or of the label (231, united, africa), to see the rest"
        ),
    ),
    "list_elements": ResultCap(
        max_rows=1000,
        note="pass search, a part of the code or of the label (2510, production), to see the rest",
    ),
    "list_items": ResultCap(
        max_rows=1000,
        note="pass search, a part of the code or of the label (15, wheat, maize), to see the rest",
    ),
}
"""MCP result caps of their own, by task function name (conventions §8, ADR-0016).

``get_data`` keeps the family's 200 rows and 64 KB and adds a note naming its paging and
its filters; a row of the recorded answers is 356 (QCL) to 383 (PP) bytes as compact
JSON, so the bytes cut a page at about 170 rows. ``list_domains`` keeps the family's cap
too: its 78 rows of 2026-10-29 fit; the note names ``search``.

The three code lists take up to 1,000 rows within the family's 64 KB (ADR-0016 decision
4), as sdk-eurostat's ``list_codes`` does, so a table an agent needs whole comes whole up
to the byte bound: a code is about 85 to 110 bytes as compact JSON, and of the fifteen
tables packaged on 2026-10-29 fourteen fit, the largest QCL's 338 items at 32,872 bytes;
TCL's 674 items, 66,970 bytes, are cut by the bytes at 657 rows, with the note naming
``search``.
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


FAO_CODES: Final = "FAO"
"""The coding system of the packaged area and item codes: ``get_data`` checks ``area``
when ``area_cs`` is ``None`` or ``"FAO"``, and ``item`` when ``item_cs`` is."""

LIST_TASKS: Mapping[str, str] = {
    "area": "list_areas",
    "element": "list_elements",
    "item": "list_items",
}
"""The task that lists each packaged dimension's codes, for a refusal to name."""

UNKNOWN_CODE_REASON = (
    "FAOSTAT answers a code it does not know with no rows, as it answers a query without "
    "data, so the package refuses it before sending;"
)
"""Why ``get_data`` refuses a code the domain's packaged table lacks (conventions §5)."""


def _check_codes(dimension: str, codes: str | None, domain: str) -> None:
    """Refuse a code of ``codes`` that the packaged table of ``dimension`` in ``domain`` lacks.

    ``codes`` is the filter as sent, a comma list (``"231,79"``); each code is checked as
    given. A domain without a packaged table, or a filter not given, is not checked.

    Raises:
        UnknownCode: Naming the table (``"element_QCL"``), its fetch date, the closest
            codes by code and then by label, and the task that lists the codes.
    """
    if codes is None or domain not in params.DOMAINS:
        return
    name = params.table_name(dimension, domain)
    labels = params.labels(name)
    for code in codes.split(","):
        if code in labels:
            continue
        reason = f'{UNKNOWN_CODE_REASON} {LIST_TASKS[dimension]}("{domain}") lists the codes'
        if dimension == "element":
            reason += " a filter takes, which are not the element_code the rows print"
        raise UnknownCode(
            dimension,
            code,
            list_name=name,
            fetched=params.packaged(name).fetched,
            closest=closest(code, labels),
            reason=f"{reason}.",
            source=SOURCE,
        )


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
    matches nothing; ``list_elements`` lists the filter codes. FAOSTAT answers a code it
    does not know with no rows, so for QCL, TCL, FBS, PP and RL, whose code tables the
    package carries (``list_areas``, ``list_elements``, ``list_items``), every area,
    element and item code is checked before the request: one the domain's table lacks
    raises ``UnknownCode`` naming the table, its fetch date and the closest codes, so
    ``element="5510"`` on QCL is refused naming ``2510`` (Production Quantity). Area
    codes are checked when ``area_cs`` is ``None`` or ``"FAO"``, item codes when
    ``item_cs`` is, since the tables list FAO's codes; years are never checked. Any
    other domain's codes are sent unchecked, and a code that matches nothing there gives
    an empty list, not an error; an unknown domain raises ``NotFoundError``.
    ``meta.vintage`` is the domain's last update as ``list_domains`` prints it
    (``"2025-12-31"``); the release date is there, ``meta.published_at`` stays ``None``.
    ``value`` is a number where upstream's text is one.

    Args:
        domain: The domain's code, as ``list_domains`` lists it, e.g. ``"QCL"`` (Crops
            and livestock products), ``"TCL"`` (trade in crops and livestock products),
            ``"FBS"`` (Food Balances, 2010-), ``"PP"`` (Producer Prices) or ``"RL"``
            (Land Use).
        area: One area code or several, FAO's codes unless ``area_cs`` says otherwise,
            as ``list_areas`` lists them, e.g. ``"231"`` (United States of America) or
            ``["231", "79"]``.
        item: One item code or several, as ``list_items`` lists them, e.g. ``"15"``
            (Wheat) or ``["15", "27"]``.
        element: One element code or several, the filter codes ``list_elements`` lists,
            e.g. ``"2510"`` (Production Quantity in QCL), not the ``5510`` the rows
            print, which is refused.
        year: One year or several, e.g. ``2020`` or ``[2015, 2016, 2017]``.
        area_cs: The coding system of ``area``, e.g. ``"FAO"`` or ``"M49"``; ``None``
            sends FAO's codes, as the rows print them under ``area_code``.
        item_cs: The coding system of ``item``, e.g. ``"FAO"`` or ``"CPC"``; ``None``
            sends FAO's codes.
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
    if area_cs is None or area_cs == FAO_CODES:
        _check_codes("area", filters["area"], domain)
    if item_cs is None or item_cs == FAO_CODES:
        _check_codes("item", filters["item"], domain)
    _check_codes("element", filters["element"], domain)
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


def _code_list(dimension: str, domain: str, search: str | None) -> Result[list[CodeItem]]:
    """The packaged codes of ``dimension`` in ``domain`` that ``search`` keeps, with meta.

    Raises:
        InvalidRequestError: The package carries no table for ``domain``.
    """
    if domain not in params.DOMAINS:
        near = closest(domain, {code: code for code in params.DOMAINS}, n=1)
        hint = f" Did you mean {near[0][0]}?" if near else ""
        raise InvalidRequestError(
            f"{LIST_TASKS[dimension]} answers for the domains whose code tables the package "
            f"carries, {', '.join(params.DOMAINS)}, not {domain!r}.{hint} get_data sends "
            f"another domain's codes unchecked, and its rows print each {dimension}'s code.",
            source=SOURCE,
        )
    name = params.table_name(dimension, domain)
    found = [code for code in params.codes(name) if matches(search, code.code, code.label)]
    request = {"lang": LANG, "dimension_id": dimension, "domain_code": domain, "search": search}
    return Result(data=found, meta=params.packaged(name).meta(SOURCE, request=request))


async def list_areas_async(domain: str, *, search: str | None = None) -> Result[list[CodeItem]]:
    """List a FAOSTAT domain's area codes, the codes ``get_data``'s ``area`` filter takes.

    Answered from the package's copy of FAOSTAT's code list ``codes/area/<domain>``
    (``getCodeList``), without a request, for QCL, TCL, FBS, PP and RL; another domain
    raises ``InvalidRequestError``. FAO's area codes, each with its label: the countries,
    e.g. ``"231"`` United States of America and ``"79"`` Germany, and the regions and
    special groups, each as a total and as a list, e.g. ``"5000"`` World + (Total) and
    ``"5000>"`` World > (List). ``get_data`` refuses a code the domain's list lacks.
    ``meta.retrieved_at`` is when the package fetched the list; ``meta.vintage`` is
    empty, as upstream gives the list no release identifier. A code FAOSTAT added since
    is missing until the package is refreshed.

    Args:
        domain: The domain's code, ``"QCL"`` (Crops and livestock products), ``"TCL"``
            (trade in crops and livestock products), ``"FBS"`` (Food Balances, 2010-),
            ``"PP"`` (Producer Prices) or ``"RL"`` (Land Use).
        search: Text to look for in the code or the label, ignoring case, e.g.
            ``"united"``, ``"231"`` or ``"africa"``; ``None`` lists every code.
    """
    return _code_list("area", domain, search)


list_areas = sync(list_areas_async)


async def list_elements_async(domain: str, *, search: str | None = None) -> Result[list[CodeItem]]:
    """List a FAOSTAT domain's element codes, the codes ``get_data``'s ``element`` filter takes.

    Answered from the package's copy of FAOSTAT's code list ``codes/element/<domain>``
    (``getCodeList``), without a request, for QCL, TCL, FBS, PP and RL; another domain
    raises ``InvalidRequestError``. These are the codes a query filters by, not the
    element codes the data rows print: QCL's ``"2510"`` Production Quantity answers rows
    whose ``element_code`` is ``"5510"`` (Production), a filter with ``5510`` is
    refused, and nothing is translated between the two. E.g. QCL ``"2510"`` Production
    Quantity and ``"2312"`` Area harvested, TCL ``"2610"`` Import quantity and ``"2910"``
    Export quantity, FBS ``"2141"`` Food and ``"664"`` Food supply (kcal/capita/day), PP
    ``"5532"`` Producer Price (USD/tonne), RL ``"5110"`` Area. ``meta.retrieved_at`` is
    when the package fetched the list; ``meta.vintage`` is empty, as upstream gives the
    list no release identifier.

    Args:
        domain: The domain's code, ``"QCL"`` (Crops and livestock products), ``"TCL"``
            (trade in crops and livestock products), ``"FBS"`` (Food Balances, 2010-),
            ``"PP"`` (Producer Prices) or ``"RL"`` (Land Use).
        search: Text to look for in the code or the label, ignoring case, e.g.
            ``"production"``, ``"2510"`` or ``"export"``; ``None`` lists every code.
    """
    return _code_list("element", domain, search)


list_elements = sync(list_elements_async)


async def list_items_async(domain: str, *, search: str | None = None) -> Result[list[CodeItem]]:
    """List a FAOSTAT domain's item codes, the codes ``get_data``'s ``item`` filter takes.

    Answered from the package's copy of FAOSTAT's code list ``codes/item/<domain>``
    (``getCodeList``), without a request, for QCL, TCL, FBS, PP and RL; another domain
    raises ``InvalidRequestError``. FAO's item codes with their labels, e.g. QCL ``"15"``
    Wheat and ``"56"`` Maize (corn), FBS ``"2511"`` Wheat and products, RL ``"6601"``
    Land area, and the item groups, as totals and as lists, e.g. QCL ``"1717"`` Cereals,
    primary + (Total) and ``"1717>"`` Cereals, primary > (List). Where upstream prints
    it, ``parent`` names the group above an item (``"QC>"`` Crops, primary > (List)); a
    list may name a group twice, as upstream sends it. ``get_data`` refuses a code the
    domain's list lacks. ``meta.retrieved_at`` is when the package fetched the list;
    ``meta.vintage`` is empty, as upstream gives the list no release identifier.

    Args:
        domain: The domain's code, ``"QCL"`` (Crops and livestock products), ``"TCL"``
            (trade in crops and livestock products), ``"FBS"`` (Food Balances, 2010-),
            ``"PP"`` (Producer Prices) or ``"RL"`` (Land Use).
        search: Text to look for in the code or the label, ignoring case, e.g.
            ``"wheat"``, ``"15"`` or ``"cereals"``; ``None`` lists every code.
    """
    return _code_list("item", domain, search)


list_items = sync(list_items_async)
