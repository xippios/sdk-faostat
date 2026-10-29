"""Public API: ``__version__`` and the task functions re-exported here (conventions §2).

Upstream: FAOSTAT.
"""

from xippios.faostat._version import __version__
from xippios.faostat.tasks import (
    get_data,
    get_series,
    list_areas,
    list_domains,
    list_elements,
    list_items,
)

__all__ = [
    "__version__",
    "get_data",
    "get_series",
    "list_areas",
    "list_domains",
    "list_elements",
    "list_items",
]
