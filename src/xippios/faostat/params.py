"""The packaged reference lists, read from ``reference/`` without a call (conventions §3).

``/refresh-reference-data`` writes them; ``PackagedList.load(PACKAGE, name)`` reads one.
"""

__all__ = ["PACKAGED_LISTS"]

PACKAGE = "xippios.faostat"

PACKAGED_LISTS: tuple[str, ...] = ()
"""The lists that ship inside the package, ``reference/<name>.json``; the refresh script
writes exactly these, its ``LISTS``, ``ID_LISTS`` and ``TABLES``."""
