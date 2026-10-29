"""Task functions, the public API: the adapters serve ``__all__`` (conventions §2).

``/add-endpoint`` adds them.
"""

__all__: list[str] = []

# A task named here is Python-only: no tool, no route; the adapters skip it (ADR-0019 decision 4).
BULK_TASKS: frozenset[str] = frozenset()

# MCP_CAPS, only where a tool needs a result cap of its own, keyed by the task function's
# name (conventions §8, ADR-0016):
#
# from xippios.core import ResultCap
#
# MCP_CAPS = {"list_<thing>": ResultCap(max_rows=400)}
