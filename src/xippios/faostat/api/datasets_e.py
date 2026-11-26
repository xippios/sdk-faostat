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
it and no token goes to ``bulks-faostat.fao.org`` (conventions §6). The answer, recorded
in ``tests/fixtures/datasets_e/all.json``, is cached in the client's ``MemoryCache`` for
five minutes, under its 8 MiB bound, shared with the keyed requests' cache.
"""

from typing import Final, NamedTuple

from xippios.core import Answer, parse

from xippios.faostat._client import SOURCE, client
from xippios.faostat.models import DatasetsCatalogue

__all__ = ["BULK_URL", "ENDPOINT", "URL", "Catalogue", "datasets_e"]

BULK_URL: Final = "https://bulks-faostat.fao.org/production"
"""Where the bulk files live: the catalogue and every dataset's ZIP (``FileLocation``)."""

ENDPOINT: Final = "production/datasets_E.json"
"""The catalogue's path as upstream writes it, ``meta.endpoint`` of ``list_bulk_datasets``."""

URL: Final = f"{BULK_URL}/datasets_E.json"
"""The catalogue's URL, absolute: it is not under the client's base URL."""


class Catalogue(NamedTuple):
    """The catalogue as read: its datasets, and each ``DateUpdate`` as FAOSTAT sent it.

    ``models.BulkDataset`` reads ``DateUpdate`` into a ``datetime`` and keeps no text beside
    it, while ``meta.vintage`` of ``download_dataset`` is the release as upstream states it
    (conventions §4; https://github.com/xippios/sdk-usda-esr/issues/60, part 3), so the
    wrapper hands the task the text apart from the models, read from the decoded answer.

    Attributes:
        catalogue: The catalogue parsed, one ``BulkDataset`` per dataset.
        printed: Each dataset's ``DateUpdate`` exactly as sent, by its ``DatasetCode``, e.g.
            ``{"RL": "2026-10-02T00:00:00", ...}``; the first dataset's where upstream sends
            a code twice.
    """

    catalogue: DatasetsCatalogue
    printed: dict[str, str]


async def datasets_e() -> Answer[Catalogue]:
    """Fetch ``production/datasets_E.json``, the bulk catalogue, without the account.

    Reads the decoded answer with ``get_answer`` and parses it itself, so that each
    ``DateUpdate`` reaches the task as FAOSTAT sent it, and returns
    ``Answer(value, answer.retrieved_at)``.

    Returns:
        Core's ``Answer``: the ``Catalogue`` as ``payload``, and ``retrieved_at``,
        timezone-aware UTC, on a cache hit the time the entry was stored, else the time
        the answer arrived. An answer that is not JSON is not cached.

    Raises:
        ValidationError: The answer is not the documented catalogue.
    """
    answer = await client.get_answer(URL, auth=None)
    catalogue = parse(DatasetsCatalogue, answer.payload, source=SOURCE, endpoint=ENDPOINT)
    printed: dict[str, str] = {}
    for row in answer.payload["Datasets"]["Dataset"]:
        printed.setdefault(row["DatasetCode"], row["DateUpdate"])
    return Answer(Catalogue(catalogue, printed), answer.retrieved_at)
