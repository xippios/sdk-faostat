"""Public API: ``__version__`` and the task functions re-exported here (conventions §2).

Upstream: FAOSTAT.
"""

from xippios.faostat._version import __version__
from xippios.faostat.tasks import (
    download_dataset,
    get_data,
    get_series,
    list_areas,
    list_bulk_datasets,
    list_domains,
    list_elements,
    list_items,
)

__all__ = [
    "__version__",
    "download_dataset",
    "get_data",
    "get_series",
    "list_areas",
    "list_bulk_datasets",
    "list_domains",
    "list_elements",
    "list_items",
]
