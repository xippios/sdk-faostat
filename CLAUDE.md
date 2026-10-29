# sdk-faostat — instructions for Claude Code

`xippios-faostat` wraps FAOSTAT as a typed Python client, an MCP server
and FastAPI routes, built on `xippios-core`. This file holds the facts of this package;
the family rules every source shares are in `.claude/family.md`, which the next line imports.

@.claude/family.md

## What this package wraps

| | |
| --- | --- |
| Upstream | FAOSTAT, https://www.fao.org/faostat/ |
| API base URL | `https://faostatservices.fao.org/api/v1` |
| Documentation | https://www.fao.org/faostat/en/docs/redoc-static.html, snapshotted in `docs/upstream/`; an OpenAPI or Swagger document a page names is kept beside it, its URL in `SPEC_URL` of `scripts/refresh_upstream.py` (`/refresh-upstream`) |
| Credentials | a FAO account: `FAOSTAT_USERNAME` (the account's e-mail) and `FAOSTAT_PASSWORD` from the environment; the package logs in at `POST /auth/login` (operation `auth_login`) and sends the access token as a bearer, from PR 4 on (queue row 252); the nightly `live.yml` passes both as org secrets from PR 4 on |
| Rate limit | 30 requests per minute, burst 1; a self-imposed pace: upstream documents no per-second or per-minute limit (ADR-0010); enforced client-side in `_client.py` <!-- name here an hourly or daily quota upstream documents, if any, and the QuotaPolicy that keeps it (ADR-0015) --> |
| Write tools | no, this package is read-only |
| Files | parsed in `parse/`, one module per file kind; the parser tests read the samples under `tests/fixtures/files/`, their provenance in its `README.md` (ADR-0020) <!-- each file kind upstream publishes, its format and the library that reads it --> |

The snapshot listed in `docs/upstream/FETCHED.md` is the reference for names, parameters and semantics.

## Layout

```
src/xippios/faostat/
  __init__.py      public surface: __version__ and re-exported task functions
  py.typed         PEP 561 marker; consumers' mypy --strict needs it
  _version.py      __version__ from distribution metadata
  _client.py       the one configured AsyncClient (base URL, rate limit) and classify,
                   upstream's documented error shapes
  errors.py        the package's own error classes, where conventions §5 calls for one
  models.py        pydantic models mirroring upstream payloads (UpstreamModel)
  api/             endpoint wrappers, one module per upstream operation
  parse/           file parsers, one module per file kind: parse_<file_kind>(path) -> list[Model]
  tasks.py         task functions; __all__ is what the adapters register, but BULK_TASKS,
                   the Python-only ones; MCP_CAPS any per-tool result caps
  mcp.py           xippios-faostat-mcp entry point
  http.py          FastAPI router
  params.py        the packaged reference lists, read from reference/
  enums.py         StrEnums (IntEnums for integer ids) generated from the packaged lists;
                   never edited by hand
  reference/       packaged code lists (CSV/JSON) plus README with provenance
scripts/
  refresh_reference.py   fetches the packaged lists through api/ and regenerates enums.py
  refresh_upstream.py    captures docs/upstream/ and writes FETCHED.md (/refresh-upstream); the
                         template's skeleton until the source fills it
tests/
  conftest.py      enables xippios.core.testing.plugin, which keeps the run offline
  fixtures/        recorded responses, <wrapper>/<case>.json, never hand-written
  fixtures/files/  a sample of each file kind, <file_kind>/<case>.<ext>; README.md, their provenance
  test_family.py   core's family check, one line: namespace levels, py.typed, __version__,
                   the adapters serving exactly the tasks, task shapes and docstrings, the
                   README status table, the template tag, the core bound
  test_api.py      optional: the endpoint wrappers' own tests
  test_tasks.py    per-task replay tests
  test_live.py     @pytest.mark.live smoke tests, one per task
docs/upstream/     documentation snapshot and FETCHED.md
.github/workflows/ ci.yml (the required ci check, with the CHANGELOG and fixture-size steps),
                   publish.yml (the release train: tag, build, PyPI), live.yml (nightly live
                   tests), gates.yml (the merge gates as jobs, off until GATES_CALLER is 1)
.claude/family.md  the family rules, the template's, imported above
.claude/commands/  add-endpoint, record-fixture, refresh-upstream, refresh-reference-data, release-prep,
                   adopt-release
```

The import path is `xippios.faostat` (ADR-0006); `src/xippios/` is a namespace
package.

## Commands

```bash
uv run pytest -m live --tb=short   # needs XIPPIOS_LIVE_TESTS=1

uv run xippios-faostat-mcp   # stdio; add --http for streamable HTTP
```

`.github/workflows/live.yml` runs the live tests nightly at 02:10 UTC, a time derived from
the slug.
From PR 4 on, the org secrets `FAOSTAT_USERNAME` and `FAOSTAT_PASSWORD` reach only its
`uv run pytest -m live` step.

## FAOSTAT specifics

### The account's credentials

Never read, print, log or compare `FAOSTAT_USERNAME`, `FAOSTAT_PASSWORD`, a token or
`.envrc`. They reach a process only through `direnv exec /home/johan/github/sdk <command>`
or the org secrets. No process listing or environment dump (`env`, `printenv`, `set`,
`export`, `ps`, `/proc/*/environ`): the shell's command line carries exported values.

### Two element code systems

A data query filters by the element codes of `codes/element/{domain}` (`2510`, Production
Quantity, in QCL); the answer prints a different code under `Element Code` (`5510`,
Production), and a filter with the answer's code matches nothing. See
`docs/upstream/samples/codes_element_QCL.json` and
`docs/upstream/samples/data_QCL_231_2510_15_2015-2021.json`.

### What the OpenAPI document does not state

Paging (`page_size` with `page_number`, `limit` with `offset`), `no_records`, the `show_*`
and `null_values` options, the coding-system parameters `area_cs` and `item_cs`, the
refusals (HTTP 500) and the absence of rate-limit headers were observed on 2026-10-29
and are listed in `docs/upstream/FETCHED.md`, under "How this is captured".
