"""``GET /{lang}/codes/{dimension_id}/{domain_code}``: ``getCodeList``, a dimension's codes.

Reference: ``docs/upstream/openapi/faostat_openapi.yaml``, path
``/{lang}/codes/{dimension_id}/{domain_code}``, operation ``getCodeList`` ("Returns
FAOSTAT code list": "Get the code list (e.g. countries, regions, or special groups),
used to describe a selected dimension (dimension_id) of a given domain (domain_code)"):
the path parameters ``lang``, ``dimension_id`` (the document's example ``countries``)
and ``domain_code`` (``QCL``), and the query parameter ``show_lists``, a boolean, "When
true (default), it includes details about which lists (e.g., M49, FAO, ISO3) the codes
belong to". The answer is the document's ``CodeResponse`` (``models.CodeResponse``;
``docs/upstream/samples/codes_element_QCL.json``).

``dimension_id`` takes the ids ``get_dimensions`` answers for a domain: the dimensions
``area``, ``element``, ``item`` and ``year`` of QCL, which the data endpoint's filters
are named after, and their subdimensions, ``countries``, ``regions`` and
``specialgroups`` under ``area`` (``docs/upstream/samples/dimensions_QCL.json``).
Recorded on 2026-10-29 for QCL (``tests/fixtures/get_code_list/``): ``codes/area/QCL``,
``codes/element/QCL``, ``codes/item/QCL`` and ``codes/countries/QCL``.

The document's other operation on codes, ``get_codes`` (``/{lang}/codes/{id}/{domain_code}/``),
is not wrapped: no task sends it.
"""

from datetime import datetime
from typing import NamedTuple
from urllib.parse import quote

from xippios.core import parse

from xippios.faostat._client import SOURCE, client
from xippios.faostat.models import CodeResponse

__all__ = ["ENDPOINT", "CodeListAnswer", "code_list_path", "get_code_list"]

ENDPOINT = "getCodeList"
"""The operation's ``operationId``."""


def code_list_path(lang: str, dimension_id: str, domain_code: str) -> str:
    """``getCodeList``'s path under ``BASE_URL``, e.g. ``"/en/codes/element/QCL"``."""
    return (
        f"/{quote(lang, safe='')}/codes/{quote(dimension_id, safe='')}"
        f"/{quote(domain_code, safe='')}"
    )


class CodeListAnswer(NamedTuple):
    """What ``get_code_list`` returns: the answer and when it was retrieved.

    Attributes:
        response: The answer, parsed.
        retrieved_at: Timezone-aware UTC: on a cache hit the time the entry was stored,
            else the time the answer arrived (``AsyncClient.get_answer``).
    """

    response: CodeResponse
    retrieved_at: datetime


async def get_code_list(
    lang: str, dimension_id: str, domain_code: str, *, show_lists: bool | None = None
) -> CodeListAnswer:
    """Call ``getCodeList``: the codes of one dimension of a domain, in upstream's order.

    A parameter left ``None`` is not sent, so upstream's default applies.

    Args:
        lang: ``lang``, e.g. ``"en"`` (the document's ``lang`` schema: ``en``, ``fr``,
            ``es``).
        dimension_id: ``dimension_id``, a dimension or subdimension id of the domain as
            ``get_dimensions`` lists it, e.g. ``"area"``, ``"element"``, ``"item"`` or
            ``"countries"``.
        domain_code: ``domain_code``, e.g. ``"QCL"``.
        show_lists: ``show_lists``, sent as ``"true"`` or ``"false"``; the document's
            default is true.

    Returns:
        The answer and when it was retrieved.
    """
    params = {} if show_lists is None else {"show_lists": str(show_lists).lower()}
    path = code_list_path(lang, dimension_id, domain_code)
    answer = await client.get_answer(path, params=params or None)
    response = parse(CodeResponse, answer.payload, source=SOURCE, endpoint=ENDPOINT)
    return CodeListAnswer(response=response, retrieved_at=answer.retrieved_at)
