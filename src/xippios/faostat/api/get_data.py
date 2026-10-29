"""``GET /{lang}/data/{domain_code}``: ``get_data``, a domain's data.

Reference: ``docs/upstream/openapi/faostat_openapi.yaml``, path ``/{lang}/data/{domain_code}``,
operation ``get_data`` ("FAOSTAT data."): the path parameters ``lang`` and
``domain_code``, and among its query parameters ``area``, ``item``, ``element`` and
``year``, each "Alias for <dimension> dimension codes", and ``output_type`` (``objects``
or ``csv``). The answer is the document's ``DataResponse`` as the recorded answers spell
it (``models.DataResponse``; ``docs/upstream/samples/data_QCL_231_2510_15_2015-2021.json``).

The document does not list the other parameters this wrapper sends, observed on
2026-10-29 (FETCHED.md, "How this is captured"): ``page_size`` with ``page_number``,
which page the answer; ``area_cs`` and ``item_cs``, the coding system of the codes sent;
``show_codes``, ``show_unit``, ``show_flags``, ``show_notes`` and ``null_values``, the
options the portal sends. Each filter is a comma list of codes, as upstream takes it
(``year=2015,2016``). The document's ``datasource`` and ``List1Codes`` to ``List9Codes``
are not wrapped: no task sends them.

Refusals are mapped once in ``_client.classify``: a query without a filter
(``InvalidRequestError``) and an unknown domain (``NotFoundError``), both HTTP 500
upstream; this wrapper inspects no status.
"""

from datetime import datetime
from typing import Literal, NamedTuple
from urllib.parse import quote

from xippios.core import parse

from xippios.faostat._client import SOURCE, client
from xippios.faostat.models import DataResponse

__all__ = ["ENDPOINT", "DataAnswer", "get_data"]

ENDPOINT = "get_data"
"""The operation's ``operationId``."""


class DataAnswer(NamedTuple):
    """What ``get_data`` returns: the answer and when it was retrieved.

    Attributes:
        response: The answer, parsed.
        retrieved_at: Timezone-aware UTC: on a cache hit the time the entry was stored,
            else the time the answer arrived (``AsyncClient.get_answer``); the task's
            ``meta.retrieved_at``.
    """

    response: DataResponse
    retrieved_at: datetime


def _flag(value: bool | None) -> str | None:
    """A boolean option as upstream takes it, ``"true"`` or ``"false"``; ``None`` unsent."""
    return None if value is None else str(value).lower()


async def get_data(
    lang: str,
    domain_code: str,
    *,
    area: str | None = None,
    item: str | None = None,
    element: str | None = None,
    year: str | None = None,
    area_cs: str | None = None,
    item_cs: str | None = None,
    page_size: int | None = None,
    page_number: int | None = None,
    show_codes: bool | None = None,
    show_unit: bool | None = None,
    show_flags: bool | None = None,
    show_notes: bool | None = None,
    null_values: bool | None = None,
    output_type: Literal["objects"] | None = None,
) -> DataAnswer:
    """Call ``get_data``: one domain's rows for the codes given.

    A parameter left ``None`` is not sent.

    Args:
        lang: ``lang``, e.g. ``"en"`` (the document's ``lang`` schema: ``en``, ``fr``,
            ``es``).
        domain_code: ``domain_code``, e.g. ``"QCL"``.
        area: ``area``, area codes as a comma list, e.g. ``"231"``.
        item: ``item``, item codes as a comma list, e.g. ``"15"``.
        element: ``element``, element codes of ``codes/element/{domain_code}`` as a
            comma list, e.g. ``"2510"``.
        year: ``year``, years as a comma list, e.g. ``"2015,2016"``.
        area_cs: ``area_cs``, the coding system of ``area``, e.g. ``"M49"`` or ``"FAO"``;
            not in the document. The answer then prints the codes under ``Area Code
            (<system>)`` (``Area Code (M49)`` recorded, ``Area Code (FAO)`` in FETCHED.md).
        item_cs: ``item_cs``, the coding system of ``item``, e.g. ``"FAO"``; not in the
            document. The answer then prints the codes under ``Item Code (<system>)``
            (``Item Code (FAO)`` in FETCHED.md).
        page_size: ``page_size``, rows per page, e.g. ``2``; not in the document.
        page_number: ``page_number``, the page, from 1, e.g. ``2``; not in the document.
        show_codes: ``show_codes``; not in the document.
        show_unit: ``show_unit``; not in the document.
        show_flags: ``show_flags``; not in the document.
        show_notes: ``show_notes``; not in the document.
        null_values: ``null_values``; listed in the document under ``post_datasize`` only.
        output_type: ``output_type``, ``"objects"``, the JSON this wrapper parses; the
            document's other value, ``csv``, is no JSON and is not offered.

    Returns:
        The answer and when it was retrieved.

    Raises:
        InvalidRequestError: No filter was sent (upstream's HTTP 500).
        NotFoundError: No such domain (upstream's HTTP 500).
    """
    sent = {
        "area": area,
        "area_cs": area_cs,
        "element": element,
        "item": item,
        "item_cs": item_cs,
        "year": year,
        "page_size": page_size,
        "page_number": page_number,
        "show_codes": _flag(show_codes),
        "show_unit": _flag(show_unit),
        "show_flags": _flag(show_flags),
        "show_notes": _flag(show_notes),
        "null_values": _flag(null_values),
        "output_type": output_type,
    }
    params = {name: value for name, value in sent.items() if value is not None}
    path = f"/{quote(lang, safe='')}/data/{quote(domain_code, safe='')}"
    answer = await client.get_answer(path, params=params)
    response = parse(DataResponse, answer.payload, source=SOURCE, endpoint=ENDPOINT)
    return DataAnswer(response=response, retrieved_at=answer.retrieved_at)
