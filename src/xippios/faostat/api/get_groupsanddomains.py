"""``GET /{lang}/groupsanddomains``: ``get_groupsanddomains``, the domains and their groups.

Reference: ``docs/upstream/openapi/faostat_openapi.yaml``, path ``/{lang}/groupsanddomains``,
operation ``get_groupsanddomains`` ("FAOSTAT groups and domains tree."), the path
parameter ``lang``. The document's answer schema names ``GroupCode``, ``GroupName``,
``DomainaCode`` and ``DomainName``; the recorded answers carry the fields of its
``DomainMetadata`` schema instead, ``group_code``, ``domain_code`` and their like
(``docs/upstream/OBSERVED.md``, ``docs/upstream/samples/groupsanddomains.json``), which
``models.Domain`` mirrors. The document's optional ``datasource`` and ``section`` are not
wrapped: no task sends them.
"""

from typing import NamedTuple
from urllib.parse import quote

from xippios.core import Answer, parse

from xippios.faostat._client import SOURCE, client
from xippios.faostat.models import GroupsAndDomainsResponse

__all__ = ["ENDPOINT", "GroupsAndDomains", "get_groupsanddomains"]


class GroupsAndDomains(NamedTuple):
    """The answer as read: the domains, and each domain's ``date_update`` as FAOSTAT sent it.

    ``models.Domain`` reads ``date_update`` into a ``date`` and keeps no text beside it, while
    ``meta.vintage`` of ``get_data`` is the release as upstream states it (conventions §4;
    https://github.com/xippios/sdk-usda-esr/issues/60, part 3), so the wrapper hands the
    task the text apart from the models, read from the decoded answer.

    Attributes:
        response: The answer parsed, its metadata and one ``Domain`` per row.
        printed: Each row's ``date_update`` exactly as sent, by its ``domain_code``, e.g.
            ``{"QCL": "2025-12-31", ...}``, ``None`` for a row without one; the first row's
            where upstream sends a code twice.
    """

    response: GroupsAndDomainsResponse
    printed: dict[str, str | None]


ENDPOINT = "get_groupsanddomains"
"""The operation's ``operationId``."""


async def get_groupsanddomains(lang: str) -> Answer[GroupsAndDomains]:
    """Call ``get_groupsanddomains``: every domain and subgroup with its group and release dates.

    Args:
        lang: ``lang``, e.g. ``"en"`` (the document's ``lang`` schema: ``en``, ``fr``,
            ``es``).

    Reads the decoded answer with ``get_answer`` and parses it itself, so that each
    ``date_update`` reaches the task as FAOSTAT sent it, and returns
    ``Answer(value, answer.retrieved_at)``, the form of core's ``Answer`` for a value a
    wrapper derives from the payload.

    Returns:
        Core's ``Answer``: the ``GroupsAndDomains`` as ``payload``, and ``retrieved_at``,
        timezone-aware UTC, on a cache hit the time the entry was stored, else the time
        the answer arrived. An answer that is not JSON is not cached.

    Raises:
        ValidationError: The answer is not the documented one.
    """
    answer = await client.get_answer(f"/{quote(lang, safe='')}/groupsanddomains")
    response = parse(GroupsAndDomainsResponse, answer.payload, source=SOURCE, endpoint=ENDPOINT)
    printed: dict[str, str | None] = {}
    for row in answer.payload["data"]:
        printed.setdefault(row["domain_code"], row.get("date_update"))
    return Answer(GroupsAndDomains(response, printed), answer.retrieved_at)
