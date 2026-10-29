# xippios-faostat

Typed Python client, MCP server and FastAPI routes for
[FAOSTAT](https://www.fao.org/faostat/), part of the
[xippios SDK family](https://github.com/xippios). Names and semantics follow the
upstream documentation; every response carries release metadata (source, endpoint,
retrieved_at, published_at, vintage).

## Install

```bash
uv add xippios-faostat            # client only
uv add "xippios-faostat[mcp]"     # + MCP server
uv add "xippios-faostat[http]"    # + FastAPI router
```

A FAO account is needed: `FAOSTAT_USERNAME` (the account's e-mail) and
`FAOSTAT_PASSWORD` in the environment. The client logs in with them on its first request
(`POST /auth/login`, FAOSTAT's `auth_login`), once per process, sends the access token
with every request, and logs in again when the token lapses (after an hour) or a request
is refused with HTTP 401 or 403. Neither the credentials nor a token is logged, and the
tasks return neither. The bulk downloads need none.

## 30-second example

```python
from xippios.faostat import get_data, list_domains

wheat = get_data("QCL", area="231", element="2510", item="15", year=range(2015, 2022))
row = wheat.data[0]  # wheat production in the United States of America, 2015
row.area, row.item, row.year  # ("United States of America", "Wheat", "2015")
row.element_code, row.element  # ("5510", "Production"): the answer's code, not the 2510 sent
row.value, row.unit, row.flag_description  # (Decimal("55839540"), "t", "Official value")
wheat.meta.vintage  # "2025-12-31": QCL's last update, as list_domains prints it
wheat.meta.request  # {"lang": "en", "domain_code": "QCL", "area": "231", ...}

list_domains(search="prices").data  # PP, CP, PD, PE (group Prices) and PA, an archive
```

`get_data(domain, *, area, item, element, year, area_cs, item_cs, page_size,
page_number)` sends one request to FAOSTAT's data endpoint (`get_data`, `GET
/{lang}/data/{domain_code}`), in English, with the output options the portal sends (codes,
units, flags and notes shown); each filter is a code or a list of codes. At least one of
`area`, `item`, `element` and `year` is needed: FAOSTAT refuses a query without a filter,
and so does `get_data`, before sending. Without `page_size` every matching row comes in
one answer; with `page_size` and `page_number`, one page. A query filters by the element
codes of the domain's element list (2510, Production Quantity), and the rows print other
codes (5510, Production). A code that matches nothing gives an empty list; an unknown
domain raises `NotFoundError`. `meta.vintage` is the domain's `date_update` from
`list_domains` (`groupsanddomains`); `meta.published_at` stays `None`, since a date is
no release time.

## MCP

```json
{
  "mcpServers": {
    "faostat": {
      "command": "uvx",
      "args": ["--from", "xippios-faostat[mcp]", "xippios-faostat-mcp"]
    }
  }
}
```

Tools are read-only and named `faostat_<verb>_<noun>`. Results are capped, at
200 rows or 64 KB unless a tool has a cap of its own, with a note on how to see the rest.
`--http` serves streamable HTTP instead of stdio.

## Status

<!-- Core's family check (tests/test_family.py) reads this table: keep the "## Status"
heading and the "Task function" column. Each row's Task function cell starts with the
task's name in backticks, alone or as its call (`get_data(code, year)`); several tasks in
one row are backticked names separated by commas; prose may follow. The tables list
exactly tasks.__all__. -->

| Upstream operation | Task function | MCP tool | Status |
| --- | --- | --- | --- |
| `get_data` (`GET /{lang}/data/{domain_code}`), the release date from `get_groupsanddomains` | `get_data(domain, area, item, element, year, area_cs, item_cs, page_size, page_number)`, a domain's rows | `faostat_get_data` | alpha |
| `get_groupsanddomains` (`GET /{lang}/groupsanddomains`) | `list_domains(search)`, the domains and subgroups with their groups and release dates | `faostat_list_domains` | alpha |

Every request logs in first where the process has no current token (`auth_login`,
`POST /auth/login`); the login is the client's, no task's.

## Upstream terms and attribution

Data comes from FAOSTAT (https://www.fao.org/faostat/) under the
[FAO Statistical Database Terms of Use](https://www.fao.org/contact-us/terms/db-terms-of-use/en/):
unless their metadata or webpage say otherwise, the datasets FAO's corporate statistical
databases disseminate, FAOSTAT among them (the terms' Annex 1), are licensed under the
Creative Commons Attribution-4.0 International licence (CC BY 4.0), as complemented by
those terms. The terms ask for this citation:

> FAO. [YYYY (year of last update)]. [Name of database: Name of dataset OR Name of
> database]. [Accessed on [DD Month YYYY]]. [URL] Licence: CC-BY-4.0.

This package adds no rights to the data. Documentation snapshot and its attribution:
`docs/upstream/FETCHED.md`.

## Licence

Apache-2.0. See [LICENSE](LICENSE).
