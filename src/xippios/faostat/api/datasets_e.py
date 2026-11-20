"""``GET https://bulks-faostat.fao.org/production/datasets_E.json``: the bulk downloads' catalogue.

Reference: ``docs/upstream/bulk/datasets_E.json``, kept verbatim, and its row in
``docs/upstream/FETCHED.md``: the catalogue of FAOSTAT's bulk downloads, open, no account,
``Datasets.Dataset`` listing each dataset with its code, name, last update and the URL
of its ZIP (``models.DatasetsCatalogue``). It is a file on another host, not an
operation of the OpenAPI document, so it has no ``operationId`` and is named from its
path (conventions §2): ``production/``, the directory every bulk file shares, dropped,
and ``datasets_E.json`` without ``.json``, snake-cased. ``ENDPOINT`` keeps the path
as upstream writes it, for ``meta.endpoint``.

The request is sent with ``auth=None``: the client's ``LoginAuth`` does not log in for
it and no token goes to ``bulks-faostat.fao.org`` (conventions §6). The answer, 107 KB
on 2026-10-29, is cached in the client's ``MemoryCache`` for five minutes, under its
8 MiB bound, shared with the keyed requests' cache.
"""

from typing import Final

from xippios.core import Answer

from xippios.faostat._client import client
from xippios.faostat.models import DatasetsCatalogue

__all__ = ["BULK_URL", "ENDPOINT", "URL", "datasets_e"]

BULK_URL: Final = "https://bulks-faostat.fao.org/production"
"""Where the bulk files live: the catalogue and every dataset's ZIP (``FileLocation``)."""

ENDPOINT: Final = "production/datasets_E.json"
"""The catalogue's path as upstream writes it, ``meta.endpoint`` of ``list_bulk_datasets``."""

URL: Final = f"{BULK_URL}/datasets_E.json"
"""The catalogue's URL, absolute: it is not under the client's base URL."""


async def datasets_e() -> Answer[DatasetsCatalogue]:
    """Fetch ``production/datasets_E.json``, the bulk catalogue, without the account.

    Returns:
        Core's ``Answer``: the catalogue, parsed, as ``payload``, and ``retrieved_at``,
        timezone-aware UTC, on a cache hit the time the entry was stored, else the time
        the answer arrived. An answer that does not parse is not cached.
    """
    return await client.get_answer(URL, auth=None, parse=DatasetsCatalogue, endpoint=ENDPOINT)
