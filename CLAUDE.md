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
| Documentation | FAO's OpenAPI document, https://www.fao.org/faostat/en/docs/faostat_openapi.yaml (`SPEC_URL` of `scripts/refresh_upstream.py`; no page links it), kept verbatim as `docs/upstream/openapi/faostat_openapi.yaml`, and the ReDoc page that renders it, https://www.fao.org/faostat/en/docs/redoc-static.html (`/refresh-upstream`) |
| Credentials | a FAO account: `FAOSTAT_USERNAME` (the account's e-mail) and `FAOSTAT_PASSWORD` from the environment; the package logs in at `POST /auth/login` (operation `auth_login`) and sends the access token as a bearer, from the first tasks PR on (queue row 252); the nightly `live.yml` passes both as org secrets from the first tasks PR on |
| Rate limit | 30 requests per minute, burst 1; a self-imposed pace: upstream documents no per-second or per-minute limit (ADR-0010); enforced client-side in `_client.py`; FAOSTAT documents no hourly or daily quota, so no `QuotaPolicy` is installed |
| Write tools | no, this package is read-only |
| Files | the bulk downloads on `bulks-faostat.fao.org`, without the account: the catalogue `production/datasets_E.json` (`api.datasets_e`) and one ZIP per dataset, holding its normalized table `<Name>_E_All_Data_(Normalized).csv` beside small code lists, the file kind `bulk-csv`, read by `parse/bulk_csv.py` with the standard library's `zipfile` and `csv`; the parser tests read the samples under `tests/fixtures/files/`, their provenance in its `README.md` (ADR-0020) |

The snapshot listed in `docs/upstream/FETCHED.md` is the reference for names, parameters and semantics.

## Layout

```
src/xippios/faostat/
  __init__.py      public surface: __version__ and re-exported task functions
  py.typed         PEP 561 marker; consumers' mypy --strict needs it
  _version.py      __version__ from distribution metadata
  _client.py       the one configured AsyncClient (base URL, rate limit, cache), LoginAuth,
                   the account's login, and classify, upstream's documented error shapes
  errors.py        the package's own error classes, where conventions §5 calls for one
  models.py        pydantic models mirroring upstream payloads (UpstreamModel)
  api/             endpoint wrappers, one module per upstream operation; datasets_e.py,
                   the bulk catalogue on bulks-faostat.fao.org, named from its path
  parse/           file parsers, one module per file kind: parse_<file_kind>(path) -> list[Model];
                   bulk_csv.py, parse_bulk_csv, a bulk ZIP's normalized table, a generator
  tasks.py         task functions; __all__ is what the adapters register, but BULK_TASKS,
                   the Python-only ones (download_dataset); MCP_CAPS any per-tool result
                   caps; get_series composes get_data, one request with a year list (queue
                   row 90); list_bulk_datasets and download_dataset read the bulk catalogue
  mcp.py           xippios-faostat-mcp entry point
  http.py          FastAPI router
  params.py        the packaged reference lists, read from reference/: the fifteen code
                   tables, DIMENSIONS by DOMAINS
  enums.py         StrEnums (IntEnums for integer ids) generated from the packaged lists;
                   never edited by hand; empty, since no table makes an enum
  reference/       fifteen packaged code tables, <dimension>_<domain>.json (area, element
                   and item of QCL, TCL, FBS, PP and RL), plus README with provenance
scripts/
  refresh_reference.py   fetches the fifteen code tables through api.get_code_list, writes
                         reference/ and its README's provenance rows, regenerates enums.py
  refresh_upstream.py    captures docs/upstream/ and writes FETCHED.md (/refresh-upstream): the
                         OpenAPI document, the terms of use, the bulk catalogue, and four
                         samples fetched with the account's token after one login
tests/
  conftest.py      enables xippios.core.testing.plugin, which keeps the run offline
  fixtures/        recorded responses, <wrapper>/<case>.json, never hand-written
  fixtures/files/  a sample of each file kind, <file_kind>/<case>.<ext>; README.md, their
                   provenance: bulk-csv/, MDDW's whole ZIP and RL's table cut to 20 rows
  test_family.py   core's family check, one line: namespace levels, py.typed, __version__,
                   the adapters serving exactly the tasks, task shapes and docstrings, the
                   README status table, the template tag, the core bound
  test_api.py      the endpoint wrappers' own tests: get_code_list and datasets_e on their
                   recordings
  test_parse.py    parse_bulk_csv on the samples under tests/fixtures/files/bulk-csv/
  test_refresh_reference.py  the refresh script on the recorded code lists, and the
                   committed tables and provenance rows against each other
  test_tasks.py    per-task replay tests
  test_live.py     @pytest.mark.live smoke tests, one per task and one per domain for
                   get_data; a run sends nine keyed requests and three without the
                   account, as its docstring counts
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
# needs XIPPIOS_LIVE_TESTS=1 and the account's two variables, from direnv exec run with
# the family workspace's root, whose .envrc holds them:
XIPPIOS_LIVE_TESTS=1 direnv exec <workspace root> uv run pytest -m live --tb=short

# refreshes the fifteen code tables under reference/: one login and fifteen requests
direnv exec <workspace root> uv run python scripts/refresh_reference.py

uv run xippios-faostat-mcp   # stdio; add --http for streamable HTTP
```

A live run sends nine keyed requests (one login, six data requests, five for `get_data`
and one for `get_series`, one `groupsanddomains`, one `getCodeList`) and three without the
account (the reachability check, the bulk catalogue and MDDW's ZIP, 12 KB);
`tests/test_live.py` counts them.

`.github/workflows/live.yml` runs the live tests nightly at 02:10 UTC, a time derived from
the slug.
From the first tasks PR on, the org secrets `FAOSTAT_USERNAME` and `FAOSTAT_PASSWORD`
reach only its `uv run pytest -m live` step.

## FAOSTAT specifics

### The account's credentials

`FAOSTAT_USERNAME`, `FAOSTAT_PASSWORD` and a token are never read by value, printed,
logged or compared, and `.envrc` is never read; code reads the two variables by name. They
reach a process only through `direnv exec` from the family workspace's root, whose
`.envrc` holds them, or through the org secrets. No process listing or environment dump
(`env`, `printenv`, `set`, `export`, `ps`, `/proc/*/environ`): the shell's command line
carries exported values. The portal's anonymous path, a guest token from
`GET /api/v1/auth/guest` (403 to a plain client, and not in the OpenAPI document), is not
used.

### The login and its recordings

`_client.LoginAuth` logs in once per process (`auth_login`, `POST /auth/login`, form
fields `username` and `password`), keeps the access token alone, a `SecretStr`, for its
`ExpiresIn` less 60 s, and logs in once more on a 401 or 403 (queue row 252). The login
runs inside `httpx`'s auth flow, below core's limiter, so the 30-per-minute pace does not
pace it, and two requests that start together before the first login answers may each
log in. A login refused with HTTP 400 and Cognito's `UserNotFoundException` or
`NotAuthorizedException` is `AuthError`, naming the status and the `__type` (`classify`
for `api.auth_login`, `LoginAuth` for its own login, which also maps a 401 or 403 so);
any other answer of `LoginAuth`'s login but HTTP 200 is core's `error_from_response`
(`RateLimitError` for a 429, `UpstreamError` for a 5xx). The flow reads the login's
answer and hands every other answer back unread. Offline tests send core's placeholder
as both variables (`xippios_placeholder_key_envs` in `pyproject.toml`); the replayed
`tests/fixtures/auth_login/login.json` answers it.

A recording that spends the account's calls:

- runs through `direnv exec <workspace root> uv run python <script>` from the
  repository, with `RetryPolicy(max_attempts=1)`; the script reads the two variables by name
  inside Python and prints fixture paths and statuses only;
- scrubs with one `Scrub(secrets=[...])` naming the user name and the password, each as
  given and percent-encoded (`urllib.parse.quote(value, safe="")` and `quote_plus`, the
  form body's encoding), a made-up login's password likewise
  (`auth_login/user_not_found.json`), and the login answer's three token values
  (`AccessToken`, `IdToken`, `RefreshToken`), which core's credential rule does not catch
  by name; the
  login is recorded with `write_fixture` after its answer is read, since the tokens are
  known only then, and the data through `record` on the client, whose `LoginAuth` logs in
  again (a keyed call to count); request headers, `Authorization` among them, are never
  recorded;
- passes the key-free check before the commit, counts only: `grep -rc REDACTED
  tests/fixtures/` (two lines in `login.json`, one in `user_not_found.json`, 0
  elsewhere), `grep -rEc 'eyJ[A-Za-z0-9_-]{20,}'
  tests/fixtures/` (0 everywhere), `grep -rEoh '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+'
  tests/fixtures/ | sort | uniq -c` (upstream's `@fao.org` addresses only), `grep -rc
  Bearer tests/fixtures/` (the login's `TokenType` only) and `grep -rc password
  tests/fixtures/` (the form field's name in the two login fixtures, its value
  `REDACTED`). A match outside these: delete the file and stop.

### Two element code systems

A data query filters by the element codes of `codes/element/{domain}` (`2510`, Production
Quantity, in QCL); the answer prints a different code under `Element Code` (`5510`,
Production), and a filter with the answer's code matches nothing. See
`docs/upstream/samples/codes_element_QCL.json` and
`docs/upstream/samples/data_QCL_231_2510_15_2015-2021.json`. The packaged element tables
hold the filter codes, so `get_data` refuses `element=5510` on QCL naming `2510`; nothing
is translated between the two systems (ADR-0003; G5 2026-10-29, question 10).

### The packaged code tables

`reference/` holds fifteen tables, `getCodeList`'s answers for `codes/<dimension>/<domain>`
of the dimensions `area`, `element` and `item` of QCL, TCL, FBS, PP and RL (Johannes, G5
2026-10-29, questions 3 and 5), each `<dimension>_<domain>.json` with the dimension as
`param` and `getCodeList` as `endpoint`, upstream's records as sent (`CodeItem.dump_upstream`
leaves out a named field the record lacked). `scripts/refresh_reference.py` fetches them
with the account, through `direnv exec <workspace root>` like a recording, and rewrites
the provenance rows of `reference/README.md`; no enum is generated. They come from the
dimension ids, which the data endpoint filters by, not from the subdimension ids the
OpenAPI document's examples name: `codes/countries/QCL` answers QCL's 210 countries,
`codes/area/QCL` those and the 68 regions and special groups beside them
(`tests/fixtures/get_code_list/`, `reference/README.md`). `list_areas`, `list_elements`
and `list_items` answer from them; `get_data` refuses an area, element or item code a
packaged domain's table lacks with `UnknownCode` before sending, area codes only when
`area_cs` is `None` or `FAO`, item codes likewise with `item_cs`, and sends any other
domain's codes unchecked. Only QCL's three answers and `codes/countries/QCL` are recorded
as fixtures; the other twelve tables are packaged, not recorded.

### Columns by domain

QCL's rows carry 15 columns, `Note` last; PP's carry `Months Code` and `Months` and no
`Note` (`tests/fixtures/get_data/PP_231_2020_page_size_2.json`). `area_cs` and `item_cs`
rename the code columns: the answer to `area_cs=FAO` and `item_cs=FAO` prints `Area Code
(FAO)` and `Item Code (FAO)` (`tests/fixtures/get_data/QCL_231_FAO_15_FAO_2510_2020.json`,
one row), and the one to `area_cs=M49` names `Area Code (M49)` in its `metadata.dsd`
(`tests/fixtures/get_data/QCL_840_M49_15_2510_2020.json`, no rows for `area=840`). The
bulk files print M49 codes with a leading apostrophe (`'004`, in the RL ZIP on
2026-10-29); whether the API's M49 filter wants that form is not established.
`models.DataRecord` names both shapes' columns, `area_code` and `item_code` `None` where
a coding system renamed them, and keeps every column a domain prints beyond the named
ones in `columns`, under upstream's headers (ADR-0003: nothing dropped), so a named
column is never there too; the live tests check that every column of each domain they
read is named or kept there.

### The bulk downloads

The catalogue `https://bulks-faostat.fao.org/production/datasets_E.json` and the ZIPs it
names (`FileLocation`) are open: `api.datasets_e` and `download_dataset` send them with
`auth=None`, so `LoginAuth` never logs in for them and no token goes to that host
(conventions §6), and their recordings, `tests/fixtures/datasets_e/` and
`tests/fixtures/download_dataset/`, were made with a client without the account. They go
through the package's one client all the same, paced by its 30 per minute, the catalogue
cached with the API's answers. On 2026-10-29 the catalogue listed 69 datasets, each code
a domain `list_domains` lists (`tests/fixtures/get_groupsanddomains/all.json`), every
one a `zip` of `csv`, `DateUpdate` a time without a zone (`2026-10-02T00:00:00`),
`FileSize` text in kilobytes (`2902KB`); the ZIPs run from 12 KB (MDDW) to 410,792 KB
(TM), TCL's 267,104 KB. A ZIP holds one `<Name>_E_All_Data_(Normalized).csv`, which
`parse_bulk_csv` chooses by that ending, and small code lists (`_AreaCodes.csv`,
`_Elements.csv`, `_Flags.csv`, `_ItemCodes.csv`; MDDW's `_Indicators.csv` and
`_Surveys.csv`); CRLF, no byte order mark, UTF-8. The normalized table is the dataset's
own: RL's header is `Area Code, Area Code (M49), Area, Item Code, Item, Element Code,
Element, Year Code, Year, Unit, Value, Flag, Note`, the M49 code printed with a leading
apostrophe (`'004`), `Value` with six decimals; MDDW's prints no area, item or year
(`models.BulkRecord` keeps such columns in `columns`). The catalogue's `FileRows` counts
RL's table (421,850) but not MDDW's (2,035, where the table holds 1,223 rows). `Item
Code (CPC)`, which the OpenAPI document's `DataResponse` names, is expected in QCL's and
TCL's tables, whose ZIPs (33 MB, 267 MB) were not fetched.

### What the OpenAPI document does not state

Paging (`page_size` with `page_number`, `limit` with `offset`), `no_records`, the `show_*`
and `null_values` options, the coding-system parameters `area_cs` and `item_cs`, the
refusals (HTTP 500) and the absence of rate-limit headers were observed on 2026-10-29
and are listed in `docs/upstream/FETCHED.md`, under "How this is captured".
