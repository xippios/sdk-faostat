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

from urllib.parse import quote

from xippios.core import Answer

from xippios.faostat._client import client
from xippios.faostat.models import GroupsAndDomainsResponse

__all__ = ["ENDPOINT", "get_groupsanddomains"]

ENDPOINT = "get_groupsanddomains"
"""The operation's ``operationId``."""


async def get_groupsanddomains(lang: str) -> Answer[GroupsAndDomainsResponse]:
    """Call ``get_groupsanddomains``: every domain and subgroup with its group and release dates.

    Args:
        lang: ``lang``, e.g. ``"en"`` (the document's ``lang`` schema: ``en``, ``fr``,
            ``es``).

    Returns:
        Core's ``Answer``: the answer, parsed, as ``payload``, and ``retrieved_at``,
        timezone-aware UTC, on a cache hit the time the entry was stored, else the time
        the answer arrived. An answer that does not parse is not cached.
    """
    return await client.get_answer(
        f"/{quote(lang, safe='')}/groupsanddomains",
        parse=GroupsAndDomainsResponse,
        endpoint=ENDPOINT,
    )
