"""``GET /{lang}/groupsanddomains``: ``get_groupsanddomains``, the domains and their groups.

Reference: ``docs/upstream/openapi/faostat_openapi.yaml``, path ``/{lang}/groupsanddomains``,
operation ``get_groupsanddomains`` ("FAOSTAT groups and domains tree."), the path
parameter ``lang``. The document's answer schema names ``GroupCode``, ``GroupName``,
``DomainaCode`` and ``DomainName``; the recorded answers carry the fields of its
``DomainMetadata`` schema instead, ``group_code``, ``domain_code`` and their like
(FETCHED.md; ``docs/upstream/samples/groupsanddomains.json``), which ``models.Domain``
mirrors. The document's optional ``datasource`` and ``section`` are not wrapped: no task
sends them.
"""

from datetime import datetime
from typing import NamedTuple
from urllib.parse import quote

from xippios.core import parse

from xippios.faostat._client import SOURCE, client
from xippios.faostat.models import GroupsAndDomainsResponse

__all__ = ["ENDPOINT", "GroupsAndDomainsAnswer", "get_groupsanddomains"]

ENDPOINT = "get_groupsanddomains"
"""The operation's ``operationId``."""


class GroupsAndDomainsAnswer(NamedTuple):
    """What ``get_groupsanddomains`` returns: the answer and when it was retrieved.

    Attributes:
        response: The answer, parsed.
        retrieved_at: Timezone-aware UTC: on a cache hit the time the entry was stored,
            else the time the answer arrived (``AsyncClient.get_answer``).
    """

    response: GroupsAndDomainsResponse
    retrieved_at: datetime


async def get_groupsanddomains(lang: str) -> GroupsAndDomainsAnswer:
    """Call ``get_groupsanddomains``: every domain and subgroup with its group and release dates.

    Args:
        lang: ``lang``, e.g. ``"en"`` (the document's ``lang`` schema: ``en``, ``fr``,
            ``es``).

    Returns:
        The answer and when it was retrieved.
    """
    answer = await client.get_answer(f"/{quote(lang, safe='')}/groupsanddomains")
    response = parse(GroupsAndDomainsResponse, answer.payload, source=SOURCE, endpoint=ENDPOINT)
    return GroupsAndDomainsAnswer(response=response, retrieved_at=answer.retrieved_at)
