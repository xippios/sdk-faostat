"""Public API: ``__version__`` and the task functions re-exported here (conventions §2).

Upstream: FAOSTAT.
"""

from xippios.faostat._version import __version__
from xippios.faostat.tasks import get_data, list_domains

__all__ = ["__version__", "get_data", "list_domains"]
