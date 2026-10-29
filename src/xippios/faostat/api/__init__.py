"""Endpoint wrappers, layer 1: one async function per upstream operation (conventions §2).

``/add-endpoint`` adds them. One module per ``operationId`` of the OpenAPI document:
``auth_login``, ``get_data``, ``get_groupsanddomains``.
"""

from xippios.faostat.api import auth_login, get_data, get_groupsanddomains

__all__ = ["auth_login", "get_data", "get_groupsanddomains"]
