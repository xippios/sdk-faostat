"""Task functions, the public API: the adapters serve ``__all__`` (conventions §2).

``/add-endpoint`` adds them.

``get_data`` sends one ``get_data`` request (``api.get_data``) for a domain and the codes
given and returns the answer's rows; every request of the package to the API carries the
FAO account's bearer token, ``_client.LoginAuth``'s. It sends ``lang=en`` and the output
options the portal sends, fixed (``OUTPUT_OPTIONS``: ``show_codes``, ``show_unit``,
``show_flags`` and ``show_notes`` true, ``null_values`` false, ``output_type`` objects;
not in the OpenAPI document, as ``docs/upstream/OBSERVED.md`` notes),
and ``page_size`` and ``page_number`` only when given: the default is one
request for every row the query matches. Release metadata: the data answer carries no
date, so ``meta.vintage`` is the domain's ``date_update`` as ``get_groupsanddomains``
prints it (``"2025-12-31"``), read after the data answer through the cache (one request
per process per five minutes), ``None`` for a domain the list lacks; ``meta.published_at``
stays ``None``, since a date is no release time (conventions §4). ``meta.retrieved_at`` is
the older of the two reads' times, the kept release date's where the cache served it.
``meta.total`` is ``None``: the answer counts no rows (sdk-core ADR-0034).

``get_series`` is one ``get_data`` request for an area, item and element over a year
range: ``since`` and ``until`` become ``get_data``'s ``year`` filter, the years
``since..until`` as upstream's comma list, or no ``year`` filter when both are ``None``,
which answers every year the domain holds; one without the other is refused before any
request (https://github.com/xippios/sdk-faostat/pull/5; sdk-core ADR-0028: upstream's
own filter, nothing cut on the client). It composes the task, not the wrapper, as
sdk-eurostat's slices compose theirs (conventions §2), so the filter refusal,
the code checks, ``classify`` and the meta rules are ``get_data``'s; its ``meta`` is
``get_data``'s, ``meta.request`` the year list sent plus ``since`` and ``until`` as
given. One request, so no ceiling in conventions §4's sense; the rows keep upstream's
order, area, item, year ascending in every recorded answer.

Every task takes the domain by FAOSTAT's name for it, ``domain_code``, positional, and
``download_dataset`` the catalogue's ``dataset_code``; every other argument is keyword-only
(conventions §2). Every refusal before a request says that nothing was sent (conventions §5).

``list_domains`` answers from ``get_groupsanddomains``, every domain and subgroup with its
group and release dates, filtered by ``search`` in Python (``xippios.core.matches``).

``list_areas``, ``list_elements`` and ``list_items`` answer from the package's copies of
``getCodeList``'s ``codes/<dimension>/<domain>`` for QCL, TCL, FBS, PP and RL
(``params``; https://github.com/xippios/sdk-faostat/pull/4), without a request, filtered by
``search`` over code and label; ``meta`` is the packaged file's (``PackagedList.meta``:
``endpoint`` ``getCodeList``, ``retrieved_at`` the file's ``fetched``, ``vintage`` and
``total`` ``None``; sdk-core ADR-0041). With them ``get_data`` checks the area, element
and item codes of those five domains before it sends, since FAOSTAT answers an unknown
code with no rows: a code the domain's table lacks is refused with core's
``UnknownCode`` by one ``check`` of the codes given on the table's declaration,
``params.table``, naming the table, its fetch date and the closest codes (conventions §5;
sdk-core ADR-0045). The element tables hold the filter codes, and nothing is translated
into the codes the rows print, which ``docs/upstream/OBSERVED.md`` notes as the two element
code systems (sdk-core ADR-0028; https://github.com/xippios/sdk-faostat/pull/3).

``list_bulk_datasets`` answers from the bulk downloads' catalogue, ``datasets_E.json`` on
``bulks-faostat.fao.org`` (``api.datasets_e``), fetched without the account and cached for
five minutes, filtered by ``search`` over ``dataset_code`` and ``dataset_name``
(https://github.com/xippios/sdk-faostat/pull/6); ``meta.endpoint`` is the catalogue's path
``production/datasets_E.json``, ``meta.vintage`` ``None``, since the catalogue carries no
version, and ``meta.total`` ``None``.

``download_dataset`` is the bulk task, named in ``BULK_TASKS`` and so Python-only: the
adapters skip it, and no tool or route returns a file path (sdk-core ADR-0040, decision
4). It checks ``dest`` by core's ``check_dest``, looks the dataset up in the catalogue
and streams the ZIP its ``FileLocation`` names to the file the caller gives, through
core's ``download`` with ``auth=None``, so the account's token never goes to the bulk host
(conventions §6);
``parse.parse_bulk_csv`` reads the file. Its release metadata is the catalogue's:
``meta.vintage`` the dataset's ``DateUpdate`` as printed (``"2026-10-02T00:00:00"``) and
``meta.published_at`` that time, which the model reads without a zone, as the catalogue
prints it, ``published_at_naive`` set (conventions §4, sdk-core ADR-0041, decision 2). That is a
time, unlike the API's date-only ``date_update``, which ``get_data`` keeps in
``meta.vintage`` alone (conventions §4). ``meta.endpoint`` is the file kind as upstream
names the member it holds, ``All_Data_(Normalized).csv`` (sdk-core ADR-0020, decision
5), ``meta.request`` the dataset's code and the file's URL.
"""

import json
import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Final

from xippios.core import (
    Downloaded,
    InvalidRequestError,
    NotFoundError,
    Result,
    ResultCap,
    ResultMeta,
    check_dest,
    closest,
    matches,
    sync,
    tool_name,
)

from xippios.faostat import api, params
from xippios.faostat._client import FILTER_REFUSAL, SOURCE, client
from xippios.faostat.models import BulkDataset, CodeItem, DataRecord, Domain

NOTHING_SENT: Final = "Nothing was sent."
"""The sentence of every refusal before a request, after its first (conventions §5)."""

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
"""Tasks the adapters skip (sdk-core ADR-0040, decision 4): ``download_dataset``, which
writes a file and is Python-only. Core's ``tool_functions`` reads it from this module and
leaves its names out, so ``mcp.py``'s ``ToolSet.from_tasks(SOURCE, tasks, ...)`` serves no
tool of it and ``http.py``'s ``router_from_tasks(SOURCE, tool_functions(tasks))`` no route."""

MCP_INSTRUCTIONS: Final = (
    "FAOSTAT via xippios. "
    "Tools are read-only. "
    "Where list tools (faostat_list_*) exist, call them first to find valid values, "
    "then query."
)
"""The server's instructions, which core's ``ToolSet.from_tasks`` reads (conventions §8)."""

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
        paged=True,
        note=(
            "pass search, a part of a domain's code or name or of its group's name "
            "(QCL, crops, production), to see the rest"
        ),
    ),
    "list_areas": ResultCap(
        max_rows=1000,
        paged=True,
        note=(
            "pass search, a part of the code or of the label (231, united, africa), to see the rest"
        ),
    ),
    "list_elements": ResultCap(
        max_rows=1000,
        paged=True,
        note="pass search, a part of the code or of the label (2510, production), to see the rest",
    ),
    "list_items": ResultCap(
        max_rows=1000,
        paged=True,
        note="pass search, a part of the code or of the label (15, wheat, maize), to see the rest",
    ),
    "list_bulk_datasets": ResultCap(
        max_rows=100,
        paged=True,
        max_bytes=160 * 1024,
        note=(
            "pass search, a part of a dataset's code or name (QCL, trade, prices), to see the rest"
        ),
    ),
}
"""MCP result caps of their own, by task function name (conventions §8, sdk-core ADR-0038).

``get_data`` keeps the family's 200 rows and 64 KB and adds a note naming its paging and
its filters; a row of the recorded answers is served as 380 (QCL) to 407 (PP) bytes of
compact JSON, ``value_number`` among them, so the bytes cut a page at about 160 rows.
``get_series`` keeps the same cap, its note naming ``since`` and ``until`` and one code
per dimension, since it does not page.
``list_domains`` keeps the family's cap too: the 78 rows of its recording fit; the note
names ``search``.

The three code lists take up to 1,000 rows within the family's 64 KB (sdk-core ADR-0038,
decision 4), as sdk-eurostat's ``list_codes`` does, so a table an agent needs whole
comes whole up to the byte bound: a code is about 85 to 110 bytes as compact JSON, and
of the fifteen packaged tables fourteen fit, the largest QCL's 338 items
at 32,872 bytes; TCL's 674 items, 66,970 bytes, are cut by the bytes at 657 rows, with
the note naming ``search``.

``list_bulk_datasets`` takes a cap of its own, 100 rows and 160 KiB (163,840 bytes), so
the whole catalogue, which an agent needs to choose a dataset, comes uncut (sdk-core
ADR-0038): its recording measures 69 datasets and 107,481 bytes as compact JSON, a
dataset 399 to 4,104 bytes, its description the most of it, where the family's 64 KB
would cut it at 39 rows. The note names ``search`` for a catalogue grown past the bound.

Five caps are paged, ``ResultCap(paged=True)``, so their tools take ``offset`` and a cut
answer's note names the offset to continue with: the next page runs the task again and
sends nothing new, since the three code lists read packaged tables, and ``list_domains``
and ``list_bulk_datasets`` read answers that the client's cache keeps for five minutes,
each far under its bound of 8 MiB (sdk-core ADR-0047, as amended). ``get_data`` takes
none: it pages by FAOSTAT's own ``page_size`` and ``page_number``, which its note names
(https://github.com/xippios/sdk-faostat/issues/32). ``get_series`` takes none either:
it takes any number of codes and years, so one answer has no bound of its own and can pass
the cache's 8 MiB, past which a continuation would send its request again (conventions
§8; https://github.com/xippios/sdk-faostat/issues/80).
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
"""The output options ``get_data`` sends, those the portal sends, which
``docs/upstream/OBSERVED.md`` notes beside the same 15 columns of an answer without them;
not in the OpenAPI document."""

Codes = str | int | Sequence[str | int]
"""One code or several: ``"231"``, ``2020`` or ``["15", "27"]``."""


def _joined(codes: Codes | None, name: str) -> str | None:
    """``codes`` as upstream's comma list, ``None`` when not given.

    Several codes are a list, ``["231", "79"]``, for every domain and filter alike: a code
    given as a text with a comma is refused, since a comma-separated text is no argument form
    (conventions §2).

    Raises:
        InvalidRequestError: ``codes`` is empty, a text or a list without a code, or a code
            holds a comma.
    """
    if codes is None:
        return None
    given = [codes] if isinstance(codes, str | int) else list(codes)
    if any("," in str(code) for code in given):
        listed = [part.strip() for code in given for part in str(code).split(",") if part.strip()]
        given = [] if not listed else given  # commas alone: no code, refused below
        if listed:
            raise InvalidRequestError(
                f"{name} takes several codes as a list, {json.dumps(listed)}, not a text with "
                f"commas, {codes!r}. {NOTHING_SENT}",
                source=SOURCE,
            )
    text = ",".join(str(code) for code in given)
    if not text:
        raise InvalidRequestError(
            f"{name} lists no code: give one code or several, or leave {name} out. {NOTHING_SENT}",
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


def _check(dimension: str, codes: Codes | None, domain_code: str) -> None:
    """Refuse the first code of ``codes`` that the packaged table of ``dimension`` lacks.

    One call of core's ``check`` on the table's declaration, the codes as the text they are
    sent as, in their order. A domain without a packaged table, or a filter not given, is
    not checked; an empty filter is ``_joined``'s to refuse.

    Raises:
        UnknownCode: Naming the table (``"element_QCL"``), its fetch date, that nothing
            was sent, the closest codes by code and then by label, and the task that lists
            the codes.
    """
    if codes is None or domain_code not in params.DOMAINS:
        return
    given = [str(code) for code in ([codes] if isinstance(codes, str | int) else codes)]
    task = LIST_TASKS[dimension]
    reason = f'{UNKNOWN_CODE_REASON} {task}("{domain_code}") lists the codes'
    if dimension == "element":
        reason += " a filter takes"
    reason += f" (over MCP, the tool {tool_name(SOURCE, task)})"
    if dimension == "element":
        reason += ", which are not the element_code the rows print"
    params.table(params.table_name(dimension, domain_code)).check(
        dimension, given, reason=f"{reason}."
    )


async def _date_update(domain_code: str) -> tuple[str | None, datetime]:
    """The domain's ``date_update`` as ``get_groupsanddomains`` prints it, and the read's time.

    The text as FAOSTAT sent it, which the wrapper hands beside the parsed answer, since
    the model reads the date into a ``date``; ``None`` for a domain the list lacks. The
    time is the answer's ``retrieved_at``, a kept answer's where the cache served it, so
    that the task can give the older of its two reads (conventions §4).
    """
    answer = await api.get_groupsanddomains.get_groupsanddomains(LANG)
    return answer.payload.printed.get(domain_code), answer.retrieved_at


async def get_data_async(
    domain_code: str,
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

    One request to FAOSTAT's data endpoint; the rows come in upstream's order (area, item,
    year ascending), each with its codes and names, unit, flag, and value as printed with
    its number beside it. Give at least one of area, item, element and year, as FAOSTAT
    asks, or the task refuses before any request. Without page_size every matching row
    comes in one answer: keep the filters narrow, or page.
    For QCL, TCL, FBS, PP and RL, whose code lists the package carries, every area,
    element and item code is checked first, and one the domain lacks raises UnknownCode
    naming the closest codes; another domain's unknown code gives an empty list.
    meta.vintage is the domain's last update as list_domains prints it. A call sends the
    data and the domain's release date, each tried up to four times, a login where the
    process holds no token, and a login and the request again where FAOSTAT refuses with
    401 or 403.

    Args:
        domain_code: The domain's code, as ``list_domains`` lists it, e.g. ``"QCL"`` (Crops
            and livestock products), ``"TCL"`` (trade in crops and livestock products),
            ``"FBS"`` (Food Balances, 2010-), ``"PP"`` (Producer Prices) or ``"RL"``
            (Land Use); one FAOSTAT does not have raises ``NotFoundError``.
        area: One area code or several, FAO's codes unless ``area_cs`` says otherwise,
            as ``list_areas`` lists them, e.g. ``"231"`` (United States of America) or
            ``["231", "79"]``; checked when ``area_cs`` is ``None`` or ``"FAO"``.
        item: One item code or several, as ``list_items`` lists them, e.g. ``"15"``
            (Wheat) or ``["15", "27"]``; checked when ``item_cs`` is ``None`` or ``"FAO"``.
        element: One element code or several, the filter codes ``list_elements`` lists,
            e.g. ``"2510"`` (Production Quantity in QCL), which answers rows whose
            ``element_code`` is ``"5510"`` (Production); ``5510`` as a filter matches
            nothing and is refused.
        year: One year or several, e.g. ``2020`` or ``[2015, 2016, 2017]``; never checked.
        area_cs: The coding system of ``area``, one the domain's dimensions list
            (``"M49"``, ``"FAO"``, ``"ISO2"``, ``"ISO3"`` in QCL); ``None`` sends FAO's
            codes, which the rows print under ``area_code``. Given, the rows print the
            codes under a header naming the system (``Area Code (FAO)``), kept in
            ``columns``, and ``area_code`` is ``None``. ``area="840"`` with
            ``area_cs="M49"`` answered no rows when observed; the bulk files print M49
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
            f"area, item, element or year. {NOTHING_SENT}",
            source=SOURCE,
        )
    if area_cs is None or area_cs == FAO_CODES:
        _check("area", area, domain_code)
    if item_cs is None or item_cs == FAO_CODES:
        _check("item", item, domain_code)
    _check("element", element, domain_code)
    sent: dict[str, Any] = {
        **filters,
        "area_cs": area_cs,
        "item_cs": item_cs,
        "page_size": page_size,
        "page_number": page_number,
        **OUTPUT_OPTIONS,
    }
    answer = await api.get_data.get_data(LANG, domain_code, **sent)
    vintage, dated_at = await _date_update(domain_code)
    meta = ResultMeta(
        source=SOURCE,
        endpoint=api.get_data.ENDPOINT,
        retrieved_at=min(answer.retrieved_at, dated_at),
        published_at=None,
        vintage=vintage,
        request={"lang": LANG, "domain_code": domain_code, **sent},
        total=None,
    )
    return Result(data=answer.payload.data, meta=meta)


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
            f"{alone} came alone. {NOTHING_SENT}",
            source=SOURCE,
        )
    if since > until:
        raise InvalidRequestError(
            f"since {since} is after until {until}: since is the first year of the series "
            f"and until the last. {NOTHING_SENT}",
            source=SOURCE,
        )
    return list(range(since, until + 1))


async def get_series_async(
    domain_code: str,
    *,
    area: Codes,
    item: Codes,
    element: Codes,
    since: int | None = None,
    until: int | None = None,
) -> Result[list[DataRecord]]:
    """Get a FAOSTAT domain's yearly series for an area, an item and an element over a year range.

    One get_data request with the years since to until as its year filter; without either
    there is no year filter, and every year the domain holds comes. Give both or neither:
    one alone, or since after until, is refused before any request. Rows come in
    upstream's order, area, item, year ascending, so one code of each gives one series,
    oldest year first, and lists give several. A year the domain does not hold, not yet
    released or without a value, has no row: nothing is filled in. The codes are checked
    as get_data checks them, and meta is get_data's, with since and until added to
    meta.request. A call sends the data and the domain's release date, each tried up to
    four times, a login where the process holds no token, and a login and the request
    again where FAOSTAT refuses with 401 or 403.

    Args:
        domain_code: The domain's code, as ``list_domains`` lists it, e.g. ``"QCL"`` (Crops
            and livestock products), ``"TCL"`` (trade in crops and livestock products),
            ``"FBS"`` (Food Balances, 2010-), ``"PP"`` (Producer Prices) or ``"RL"``
            (Land Use); one FAOSTAT does not have raises ``NotFoundError``.
        area: The area's code, FAO's, as ``list_areas`` lists it, e.g. ``"231"`` (United
            States of America), or several, ``["231", "79"]``.
        item: The item's code, as ``list_items`` lists it, e.g. ``"15"`` (Wheat), or
            several, ``["15", "56"]``.
        element: The element's filter code, as ``list_elements`` lists it, e.g.
            ``"2510"`` (Production Quantity in QCL), which answers rows whose
            ``element_code`` is ``"5510"`` (Production); ``5510`` is refused naming
            ``2510``. Or several, ``["2510", "2312"]``.
        since: The first year, included, e.g. ``2015``; with ``until``. ``None`` with
            ``until`` ``None`` asks for every year the domain holds.
        until: The last year, included, e.g. ``2021``; with ``since``. ``list_domains``
            prints each domain's latest year as ``year_current`` (``"2024"`` for QCL in
            its recording).
    """
    years = _series_years(since, until)
    answer = await get_data_async(domain_code, area=area, item=item, element=element, year=years)
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
        for row in answer.payload.response.data
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


def _code_list(dimension: str, domain_code: str, search: str | None) -> Result[list[CodeItem]]:
    """The packaged codes of ``dimension`` in ``domain_code`` that ``search`` keeps, with meta.

    Raises:
        InvalidRequestError: The package carries no table for ``domain_code``.
    """
    if domain_code not in params.DOMAINS:
        near = closest(domain_code, {code: code for code in params.DOMAINS}, n=1)
        hint = f" Did you mean {near[0][0]}?" if near else ""
        raise InvalidRequestError(
            f"{LIST_TASKS[dimension]} answers for the domains whose code tables the package "
            f"carries, {', '.join(params.DOMAINS)}, not {domain_code!r}. {NOTHING_SENT}{hint} "
            "get_data sends the codes of another domain unchecked (over MCP, the tool "
            f"{tool_name(SOURCE, 'get_data')}).",
            source=SOURCE,
        )
    name = params.table_name(dimension, domain_code)
    found = [code for code in params.codes(name) if matches(search, code.code, code.label)]
    request = {
        "lang": LANG,
        "dimension_id": dimension,
        "domain_code": domain_code,
        "search": search,
    }
    return Result(data=found, meta=params.packaged(name).meta(SOURCE, request=request))


async def list_areas_async(
    domain_code: str, *, search: str | None = None
) -> Result[list[CodeItem]]:
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
        domain_code: The domain's code, ``"QCL"`` (Crops and livestock products), ``"TCL"``
            (trade in crops and livestock products), ``"FBS"`` (Food Balances, 2010-),
            ``"PP"`` (Producer Prices) or ``"RL"`` (Land Use).
        search: Text to look for in the code or the label, ignoring case, e.g.
            ``"united"``, ``"231"`` or ``"africa"``; ``None`` lists every code.
    """
    return _code_list("area", domain_code, search)


list_areas = sync(list_areas_async)


async def list_elements_async(
    domain_code: str, *, search: str | None = None
) -> Result[list[CodeItem]]:
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
        domain_code: The domain's code, ``"QCL"`` (Crops and livestock products), ``"TCL"``
            (trade in crops and livestock products), ``"FBS"`` (Food Balances, 2010-),
            ``"PP"`` (Producer Prices) or ``"RL"`` (Land Use).
        search: Text to look for in the code or the label, ignoring case, e.g.
            ``"production"``, ``"2510"`` or ``"export"``; ``None`` lists every code.
    """
    return _code_list("element", domain_code, search)


list_elements = sync(list_elements_async)


async def list_items_async(
    domain_code: str, *, search: str | None = None
) -> Result[list[CodeItem]]:
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
        domain_code: The domain's code, ``"QCL"`` (Crops and livestock products), ``"TCL"``
            (trade in crops and livestock products), ``"FBS"`` (Food Balances, 2010-),
            ``"PP"`` (Producer Prices) or ``"RL"`` (Land Use).
        search: Text to look for in the code or the label, ignoring case, e.g.
            ``"wheat"``, ``"15"`` or ``"cereals"``; ``None`` lists every code.
    """
    return _code_list("item", domain_code, search)


list_items = sync(list_items_async)


NORMALIZED_TABLE: Final = "All_Data_(Normalized).csv"
"""The file kind ``download_dataset`` names in ``meta.endpoint``: the normalized table, as
upstream names its member, ``<Name>_E_All_Data_(Normalized).csv``."""


async def list_bulk_datasets_async(*, search: str | None = None) -> Result[list[BulkDataset]]:
    """List FAOSTAT's bulk downloads, one ZIP per dataset, with its size, rows and last update.

    One request, without the account, to the bulk downloads' catalogue
    (``https://bulks-faostat.fao.org/production/datasets_E.json``), cached for five
    minutes: every dataset FAOSTAT publishes as a file, each with its
    code (``dataset_code``, the domain code ``get_data`` takes), name, topic and
    description, contact, last update as printed (``date_update``,
    ``"2026-10-02T00:00:00"``), the ZIP's size as printed (``file_size``, ``"2902KB"``),
    the normalized table's rows (``file_rows``) and the ZIP's URL (``file_location``).
    The files run from MDDW's, the smallest, to TM's, the detailed trade matrix, the
    largest, and are downloaded in Python only, with ``download_dataset``; no tool returns
    a file. ``meta.vintage`` is empty,
    as the catalogue carries no version.

    Args:
        search: Text to look for, ignoring case, in a dataset's ``dataset_code`` or
            ``dataset_name``, e.g. ``"QCL"``, ``"trade"`` or ``"prices"``; ``None`` lists
            every dataset.
    """
    answer = await api.datasets_e.datasets_e()
    rows = [
        dataset
        for dataset in answer.payload.catalogue.datasets.dataset
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


async def download_dataset_async(
    dataset_code: str, *, dest: str | os.PathLike[str]
) -> Result[Downloaded]:
    """Download a FAOSTAT dataset's bulk file, a ZIP holding its normalized table as CSV.

    Python only, no MCP tool or HTTP route (a bulk task). Two requests, neither with the
    account, each tried up to four times: the bulk catalogue, as ``list_bulk_datasets``
    reads it (cached for five minutes), for the dataset's ``FileLocation``, and the ZIP
    there, streamed to ``dest`` by core's ``download``, never held in memory or cached;
    nothing in it is read. ``parse_bulk_csv(result.data.path)`` from
    ``xippios.faostat.parse`` reads its normalized table, the member
    ``<Name>_E_All_Data_(Normalized).csv``, row by row. The files can be large, TM's (the
    detailed trade matrix) the largest and TCL's (trade in crops and livestock products)
    next, MDDW's the smallest, and the table inside is larger still;
    ``list_bulk_datasets`` prints each ``file_size`` and ``file_rows``.
    ``result.data`` is core's ``Downloaded``: the path, its size, the content type,
    ``ETag`` and ``Last-Modified``. ``meta.vintage`` is the catalogue's ``DateUpdate`` for
    the dataset as printed (``"2026-10-02T00:00:00"``) and ``meta.published_at`` that
    time, which the catalogue prints without a zone (``meta.published_at_naive``): a time,
    unlike ``get_data``'s ``meta.vintage``, the API's ``date_update``, a date, which stays
    out of ``published_at``. ``meta.retrieved_at`` is the older of the two reads' times,
    the kept catalogue's where the cache served it, and ``result.data.retrieved_at`` the
    file's. ``meta.endpoint`` is ``"All_Data_(Normalized).csv"``, the
    file kind as upstream names its member; ``meta.request`` the dataset's code and the
    file's URL. A code the catalogue does not list raises ``NotFoundError`` naming the
    closest, once the catalogue is read and before the file is requested; ``dest`` must
    name a file in a directory that exists, and a directory, or a missing one, is refused
    with ``InvalidRequestError`` before any request.

    Args:
        dataset_code: The dataset's code, as ``list_bulk_datasets`` lists it, upstream's
            ``DatasetCode``, the domain code ``get_data`` takes, e.g. ``"RL"`` (Land Use),
            ``"QCL"`` (Crops and livestock products), ``"MDDW"`` (Minimum Dietary
            Diversity for Women) or ``"TCL"`` (trade in crops and livestock products).
        dest: The file to write, e.g. ``"RL.zip"`` or ``Path("data") / "QCL.zip"``, in a
            directory that exists; a file there is replaced once the download is
            complete.
    """
    target = check_dest(dest, source=SOURCE)
    answer = await api.datasets_e.datasets_e()
    datasets = answer.payload.catalogue.datasets.dataset
    listed = {dataset.dataset_code: dataset for dataset in datasets}
    dataset = listed.get(dataset_code)
    if dataset is None:
        near = closest(dataset_code, {code: entry.dataset_name for code, entry in listed.items()})
        hint = f" Did you mean {', '.join(code for code, _ in near)}?" if near else ""
        raise NotFoundError(
            f"FAOSTAT's bulk catalogue lists no dataset {dataset_code!r}. The catalogue was "
            f"requested and no file was.{hint} list_bulk_datasets lists them.",
            source=SOURCE,
        )
    released = dataset.date_update
    downloaded = await client.download(dataset.file_location, target, auth=None)
    meta = ResultMeta(
        source=SOURCE,
        endpoint=NORMALIZED_TABLE,
        retrieved_at=min(answer.retrieved_at, downloaded.retrieved_at),
        published_at=released,
        published_at_naive=released.tzinfo is None,
        vintage=answer.payload.printed[dataset_code],
        request={"dataset_code": dataset_code, "url": dataset.file_location},
        total=None,
    )
    return Result(data=downloaded, meta=meta)


download_dataset = sync(download_dataset_async)
