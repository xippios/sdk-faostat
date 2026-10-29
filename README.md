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

A FAO account is needed: `FAOSTAT_USERNAME` and `FAOSTAT_PASSWORD` in the environment;
the client logs in for you (from 0.1.0's first tasks on). The bulk downloads need none.

## 30-second example

```python
from xippios.faostat import tasks

# result = tasks.<task>(...)
# result.data, result.meta.retrieved_at, result.meta.request
```

Task functions are listed in the status table below as they are added.

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
| (none yet) | | | |

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
