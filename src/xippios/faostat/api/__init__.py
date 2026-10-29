"""Endpoint wrappers, layer 1: one async function per upstream operation (conventions §2).

``/add-endpoint`` adds them. One module per ``operationId`` of the OpenAPI document,
snake-cased: ``auth_login``, ``get_code_list`` (``getCodeList``), ``get_data``,
``get_groupsanddomains``; and ``datasets_e``, the bulk downloads' catalogue
``production/datasets_E.json`` on ``bulks-faostat.fao.org``, which the document does not
describe, named from its path (conventions §2).
"""

from xippios.faostat.api import (
    auth_login,
    datasets_e,
    get_code_list,
    get_data,
    get_groupsanddomains,
)

__all__ = ["auth_login", "datasets_e", "get_code_list", "get_data", "get_groupsanddomains"]
