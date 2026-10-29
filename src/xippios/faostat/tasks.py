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

``get_series`` is one ``get_data`` request for an area, item and element over a year
range: ``since`` and ``until`` become ``get_data``'s ``year`` filter, the years
``since..until`` as upstream's comma list, or no ``year`` filter when both are ``None``,
which answers every year the domain holds; one without the other is refused before any
request (Johannes, G5 2026-10-29, second round, question 15; ADR-0003: upstream's own
filter, nothing cut on the client). It composes the task, not the wrapper, as
sdk-eurostat's slices compose theirs (queue row 90), so the filter refusal, the code
checks, ``classify`` and the meta rules are ``get_data``'s; its ``meta`` is
``get_data``'s, ``meta.request`` the year list sent plus ``since`` and ``until`` as
given. One request, so no ceiling in conventions §4's sense; the rows keep upstream's
order, area, item, year ascending in every recorded answer.

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

``list_bulk_datasets`` answers from the bulk downloads' catalogue, ``datasets_E.json`` on
``bulks-faostat.fao.org`` (``api.datasets_e``), fetched without the account and cached for
five minutes, filtered by ``search`` over ``dataset_code`` and ``dataset_name``
(Johannes, G5 2026-10-29, question 4); ``meta.endpoint`` is the catalogue's path
``production/datasets_E.json``, ``meta.vintage`` ``None``, since the catalogue carries no
version, and ``meta.total`` ``None``.

``download_dataset`` is the bulk task, named in ``BULK_TASKS`` and so Python-only: the
adapters skip it, and no tool or route returns a file path (ADR-0019 decision 4). It
looks the domain up in the catalogue and streams the ZIP its ``FileLocation`` names to the
file the caller gives, through core's ``download`` with ``auth=None``, so the account's
token never goes to the bulk host (conventions §6); ``parse.parse_bulk_csv`` reads the
file. Its release metadata is the catalogue's: ``meta.vintage`` the dataset's
``DateUpdate`` as printed (``"2026-10-02T00:00:00"``) and ``meta.published_at`` the same
time, which the catalogue prints without a zone, ``published_at_naive`` set (conventions
§4, ADR-0022 rule 2). That is a time, unlike the API's date-only ``date_update``, which
``get_data`` keeps in ``meta.vintage`` alone (queue row 263). ``meta.endpoint`` is the
file kind as upstream names the member it holds, ``All_Data_(Normalized).csv`` (ADR-0020
decision 5), ``meta.request`` the domain and the file's URL.
"""

import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from xippios.core import (
    Downloaded,
    InvalidRequestError,
    NotFoundError,
    Result,
    ResultCap,
    ResultMeta,
    UnknownCode,
    ValidationError,
    closest,
    matches,
    sync,
)

from xippios.faostat import api, params
from xippios.faostat._client import FILTER_REFUSAL, SOURCE, client
from xippios.faostat.models import BulkDataset, CodeItem, DataRecord, Domain

__all__ = [
    "download_dataset",
    "get_data",
    "get_series",
    "list_areas",
    "list_bulk_datasets",
    "list_domains",
    "list_elements",
    "list_items",
]

BULK_TASKS: frozenset[str] = frozenset({"download_dataset"})
"""Tasks the adapters skip (ADR-0019 decision 4): ``download_dataset``, which writes a file
and is Python-only. Core's ``build_server`` and ``router_from_tasks`` read it from this
module and leave its names out, so ``mcp.py`` and ``http.py`` pass ``__all__`` whole."""

MCP_CAPS: Mapping[str, ResultCap] = {
    "get_data": ResultCap(
        max_rows=200,
        note=(
            "rows run area, item, year ascending; pass page_size and page_number, or "
            "narrower filters, to see the rest"
        ),
    ),
    "get_series": ResultCap(
        max_rows=200,
        note=(
            "rows run area, item, year ascending; narrow since and until, or one code per "
            "dimension, to see the rest"
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
    "list_bulk_datasets": ResultCap(
        note=(
            "pass search, a part of a dataset's code or name (QCL, trade, prices), to see the rest"
        ),
    ),
}
"""MCP result caps of their own, by task function name (conventions §8, ADR-0016).

``get_data`` keeps the family's 200 rows and 64 KB and adds a note naming its paging and
its filters; a row of the recorded answers is 356 (QCL) to 383 (PP) bytes as compact
JSON, so the bytes cut a page at about 170 rows. ``get_series`` keeps the same cap, its
note naming ``since`` and ``until`` and one code per dimension, since it does not page.
``list_domains`` keeps the family's cap too: its 78 rows of 2026-10-29 fit; the note
names ``search``.

The three code lists take up to 1,000 rows within the family's 64 KB (ADR-0016 decision
4), as sdk-eurostat's ``list_codes`` does, so a table an agent needs whole comes whole up
to the byte bound: a code is about 85 to 110 bytes as compact JSON, and of the fifteen
tables packaged on 2026-10-29 fourteen fit, the largest QCL's 338 items at 32,872 bytes;
TCL's 674 items, 66,970 bytes, are cut by the bytes at 657 rows, with the note naming
``search``.

``list_bulk_datasets`` keeps the family's cap too, its note naming ``search``: a dataset
is 399 to 4,104 bytes as compact JSON, its description the most of it, so of the 69 of
2026-10-29, 107,481 bytes, the first 39 fit the 64 KB.
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
        area_cs: The coding system of ``area``, one the domain's dimensions list
            (``"M49"``, ``"FAO"``, ``"ISO2"``, ``"ISO3"`` in QCL); ``None`` sends FAO's
            codes, which the rows print under ``area_code``. Given, the rows print the
            codes under a header naming the system (``Area Code (FAO)``), kept in
            ``columns``, and ``area_code`` is ``None``. ``area="840"`` with
            ``area_cs="M49"`` answered no rows on 2026-10-29; the bulk files print M49
            codes with a leading apostrophe (``'004``), and whether the M49 filter wants
            that form is not established.
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


def _series_years(since: int | None, until: int | None) -> list[int] | None:
    """The years ``since`` to ``until``, both included, ``None`` when both are ``None``.

    Raises:
        InvalidRequestError: One of the pair is given without the other, or ``since``
            is after ``until``.
    """
    if since is None and until is None:
        return None
    if since is None or until is None:
        alone = "until" if since is None else "since"
        raise InvalidRequestError(
            "since and until go together: give both, the first and the last year of the "
            "series (since=2015, until=2021), or neither, for every year the domain holds; "
            f"{alone} came alone",
            source=SOURCE,
        )
    if since > until:
        raise InvalidRequestError(
            f"since {since} is after until {until}: since is the first year of the series "
            "and until the last",
            source=SOURCE,
        )
    return list(range(since, until + 1))


async def get_series_async(
    domain: str,
    area: Codes,
    item: Codes,
    element: Codes,
    *,
    since: int | None = None,
    until: int | None = None,
) -> Result[list[DataRecord]]:
    """Get a FAOSTAT domain's yearly series for an area, an item and an element over a year range.

    One request to FAOSTAT's data endpoint, as ``get_data`` sends it, with the years
    ``since`` to ``until`` as its year filter (``since=2015, until=2021`` asks for the
    seven years 2015 to 2021); without ``since`` and ``until`` there is no year filter,
    and the answer holds every year the domain has. Give both or neither: one without the
    other, or ``since`` after ``until``, is refused with ``InvalidRequestError`` before
    any request. Rows come in upstream's order, area, item, year ascending in the
    recorded answers, so one area, item and element give one series, oldest year first;
    lists of codes give several series in one list, in upstream's order. A year the
    domain does not hold, not yet released or without a value, has no row: nothing is
    filled in. ``list_domains`` prints each domain's latest year as ``year_current``
    (``"2024"`` for QCL on 2026-10-29). The element codes a query filters by are not
    those the rows print: ``element="2510"`` (Production Quantity) answers rows with
    ``element_code`` ``"5510"`` (Production), and ``list_elements`` lists the filter
    codes. For QCL, TCL, FBS, PP and RL every area, element and item code is checked
    against the package's code tables before the request, as ``get_data`` checks them:
    one the domain's table lacks raises ``UnknownCode`` naming the closest codes, so
    ``element="5510"`` on QCL is refused naming ``2510``. Another domain's codes are sent
    unchecked, and a code that matches nothing there gives an empty list; an unknown
    domain raises ``NotFoundError``. ``meta`` is ``get_data``'s: ``meta.vintage`` the
    domain's last update as ``list_domains`` prints it (``"2025-12-31"``),
    ``meta.published_at`` ``None``, ``meta.request`` the year list sent, plus ``since``
    and ``until`` as given. ``value`` is a number where upstream's text is one.

    Args:
        domain: The domain's code, as ``list_domains`` lists it, e.g. ``"QCL"`` (Crops
            and livestock products), ``"TCL"`` (trade in crops and livestock products),
            ``"FBS"`` (Food Balances, 2010-), ``"PP"`` (Producer Prices) or ``"RL"``
            (Land Use).
        area: The area's code, FAO's, as ``list_areas`` lists it, e.g. ``"231"`` (United
            States of America), or several, ``["231", "79"]``.
        item: The item's code, as ``list_items`` lists it, e.g. ``"15"`` (Wheat), or
            several, ``["15", "56"]``.
        element: The element's filter code, as ``list_elements`` lists it, e.g.
            ``"2510"`` (Production Quantity in QCL), not the ``5510`` the rows print,
            which is refused; or several, ``["2510", "2312"]``.
        since: The first year, included, e.g. ``2015``; with ``until``. ``None`` with
            ``until`` ``None`` asks for every year the domain holds.
        until: The last year, included, e.g. ``2021``; with ``since``.
    """
    years = _series_years(since, until)
    answer = await get_data_async(domain, area=area, item=item, element=element, year=years)
    meta = ResultMeta(
        **answer.meta.model_dump(exclude={"request"}),
        request={**answer.meta.request, "since": since, "until": until},
    )
    return Result(data=answer.data, meta=meta)


get_series = sync(get_series_async)


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


NORMALIZED_TABLE: Final = "All_Data_(Normalized).csv"
"""The file kind ``download_dataset`` names in ``meta.endpoint``: the normalized table, as
upstream names its member, ``<Name>_E_All_Data_(Normalized).csv``."""


def _target(dest: str | os.PathLike[str]) -> Path:
    """``dest`` as a path, refused when it is a directory or its directory is missing.

    Core's own text (``AsyncClient.download``), as the taxonomy's refusal, before any
    request.

    Raises:
        InvalidRequestError: ``dest`` is a directory, or its directory does not exist.
    """
    target = Path(dest)
    if target.is_dir():
        raise InvalidRequestError("dest is a directory; name the file to write", source=SOURCE)
    if not target.parent.is_dir():
        raise InvalidRequestError("dest's directory does not exist; create it first", source=SOURCE)
    return target


def _released(dataset: BulkDataset) -> datetime:
    """The dataset's ``DateUpdate`` as a time, without a zone where the catalogue prints none.

    Raises:
        ValidationError: The catalogue's ``DateUpdate`` is not an ISO 8601 time.
    """
    try:
        return datetime.fromisoformat(dataset.date_update)
    except ValueError:
        raise ValidationError(
            f"{SOURCE} {api.datasets_e.ENDPOINT}: the DateUpdate of {dataset.dataset_code} is "
            "not printed as an ISO 8601 time (2026-10-02T00:00:00)",
            raw=dataset.date_update,
            source=SOURCE,
        ) from None


async def list_bulk_datasets_async(*, search: str | None = None) -> Result[list[BulkDataset]]:
    """List FAOSTAT's bulk downloads, one ZIP per dataset, with its size, rows and last update.

    One request, without the account, to the bulk downloads' catalogue
    (``https://bulks-faostat.fao.org/production/datasets_E.json``), cached for five
    minutes: every dataset FAOSTAT publishes as a file, 69 on 2026-10-29, each with its
    code (``dataset_code``, the domain code ``get_data`` takes), name, topic and
    description, contact, last update as printed (``date_update``,
    ``"2026-10-02T00:00:00"``), the ZIP's size as printed (``file_size``, ``"2902KB"``),
    the normalized table's rows (``file_rows``) and the ZIP's URL (``file_location``).
    The files run from 12 KB (MDDW) to 410,792 KB (TM, the detailed trade matrix; TCL,
    trade in crops and livestock products, is 267,104 KB) and are downloaded in Python
    only, with ``download_dataset``; no tool returns a file. ``meta.vintage`` is empty,
    as the catalogue carries no version.

    Args:
        search: Text to look for, ignoring case, in a dataset's ``dataset_code`` or
            ``dataset_name``, e.g. ``"QCL"``, ``"trade"`` or ``"prices"``; ``None`` lists
            every dataset.
    """
    answer = await api.datasets_e.datasets_e()
    rows = [
        dataset
        for dataset in answer.response.datasets.dataset
        if matches(search, dataset.dataset_code, dataset.dataset_name)
    ]
    meta = ResultMeta(
        source=SOURCE,
        endpoint=api.datasets_e.ENDPOINT,
        retrieved_at=answer.retrieved_at,
        published_at=None,
        vintage=None,
        request={"search": search},
        total=None,
    )
    return Result(data=rows, meta=meta)


list_bulk_datasets = sync(list_bulk_datasets_async)


async def download_dataset_async(domain: str, dest: str | os.PathLike[str]) -> Result[Downloaded]:
    """Download a FAOSTAT dataset's bulk file, a ZIP holding its normalized table as CSV.

    Python only, no MCP tool or HTTP route (a bulk task). Two requests, neither with the
    account: the bulk catalogue, as ``list_bulk_datasets`` reads it (cached for five
    minutes), for the dataset's ``FileLocation``, and the ZIP there, streamed to ``dest``
    by core's ``download``, never held in memory or cached; nothing in it is read.
    ``parse_bulk_csv(result.data.path)`` from ``xippios.faostat.parse`` reads its
    normalized table, the member ``<Name>_E_All_Data_(Normalized).csv``, row by row. The
    files are large: TCL's (trade in crops and livestock products) is 267 MB, TM's (the
    detailed trade matrix) 410 MB, QCL's 33 MB, RL's 3 MB, MDDW's 12 KB, the smallest;
    the table inside is larger still (RL's 50 MB); ``list_bulk_datasets`` prints each
    ``file_size`` and ``file_rows``. ``result.data`` is core's ``Downloaded``: the path,
    its size, the content type, ``ETag`` and ``Last-Modified``. ``meta.vintage`` is the
    catalogue's ``date_update`` for the dataset as printed (``"2026-10-02T00:00:00"``)
    and ``meta.published_at`` the same time, which the catalogue prints without a zone
    (``meta.published_at_naive``): a time, unlike ``get_data``'s ``meta.vintage``, the
    API's ``date_update``, a date, which stays out of ``published_at``.
    ``meta.endpoint`` is ``"All_Data_(Normalized).csv"``, the file kind as upstream names
    its member; ``meta.request`` the domain and the file's URL. A code the catalogue does
    not list raises ``NotFoundError`` naming the closest; ``dest`` must name a file in a
    directory that exists, and a directory, or a missing one, is refused with
    ``InvalidRequestError``, both before the file is requested.

    Args:
        domain: The dataset's code, as ``list_bulk_datasets`` lists it (its
            ``dataset_code``, the domain code ``get_data`` takes), e.g. ``"RL"`` (Land
            Use), ``"QCL"`` (Crops and livestock products), ``"MDDW"`` (Minimum Dietary
            Diversity for Women) or ``"TCL"`` (trade in crops and livestock products).
        dest: The file to write, e.g. ``"RL.zip"`` or ``Path("data") / "QCL.zip"``, in a
            directory that exists; a file there is replaced once the download is
            complete.
    """
    target = _target(dest)
    answer = await api.datasets_e.datasets_e()
    listed = {dataset.dataset_code: dataset for dataset in answer.response.datasets.dataset}
    dataset = listed.get(domain)
    if dataset is None:
        near = closest(domain, {code: entry.dataset_name for code, entry in listed.items()})
        hint = f" Did you mean {', '.join(code for code, _ in near)}?" if near else ""
        raise NotFoundError(
            f"FAOSTAT's bulk catalogue lists no dataset {domain!r}.{hint} list_bulk_datasets "
            "lists them",
            source=SOURCE,
        )
    released = _released(dataset)
    downloaded = await client.download(dataset.file_location, target, auth=None)
    meta = ResultMeta(
        source=SOURCE,
        endpoint=NORMALIZED_TABLE,
        retrieved_at=downloaded.retrieved_at,
        published_at=released,
        published_at_naive=released.tzinfo is None,
        vintage=dataset.date_update,
        request={"domain": domain, "url": dataset.file_location},
        total=None,
    )
    return Result(data=downloaded, meta=meta)


download_dataset = sync(download_dataset_async)
