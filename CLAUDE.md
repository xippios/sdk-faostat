# sdk-faostat — instructions for Claude Code

`xippios-faostat` wraps FAOSTAT as a typed Python client, an MCP server
and FastAPI routes, built on `xippios-core`. This file holds what an agent needs to work on
the package: what it wraps, its layout, its commands and what only it knows. The documents it
follows, sdk-core's conventions among them, are listed under
[`## Documents` in the README](README.md#documents); read them before you change a file. The
rules that no change breaks stand in `.claude/rules/never.md`, which Claude Code loads with
this file.

## What this package wraps

| | |
| --- | --- |
| Upstream | FAOSTAT, https://www.fao.org/faostat/ |
| API base URL | `https://faostatservices.fao.org/api/v1` |
| Bulk host | `https://bulks-faostat.fao.org/production`, the bulk downloads' catalogue and ZIPs, sent without the account through the API's one client: 30 requests per minute, burst 1, shared with the API, a self-imposed pace, since FAO documents no limit for either host |
| Documentation | FAO's OpenAPI document, https://www.fao.org/faostat/en/docs/faostat_openapi.yaml (`SPEC_URL` of `scripts/refresh_upstream.py`; no page links it), kept verbatim as `docs/upstream/openapi/faostat_openapi.yaml`, and the ReDoc page that renders it, https://www.fao.org/faostat/en/docs/redoc-static.html (`/refresh-upstream`) |
| Credentials | a FAO account: `FAOSTAT_USERNAME` (the account's e-mail) and `FAOSTAT_PASSWORD` from the environment, both in `ENV_VARS`; the package logs in at `POST /auth/login` (operation `auth_login`) through core's `RenewingBearerAuth` and sends the access token as a bearer (sdk-core ADR-0025, amendment 2026-11-18, point c); the nightly `live.yml` passes both, each from the secret of the same name |
| Rate limit | 30 requests per minute, burst 1; a self-imposed pace: upstream documents no per-second or per-minute limit (sdk-core ADR-0033); enforced client-side in `_client.py`; FAOSTAT documents no hourly or daily quota, so no `QuotaPolicy` is installed |
| Write tools | no, this package is read-only |
| Files | the bulk downloads on `bulks-faostat.fao.org`, without the account: the catalogue `production/datasets_E.json` (`api.datasets_e`) and one ZIP per dataset, holding its normalized table `<Name>_E_All_Data_(Normalized).csv` beside small code lists, the file kind `bulk-csv`, read by `parse/bulk_csv.py`, the ZIP opened with the standard library's `zipfile` and its table's rows read through core's `decode_csv`, the header alone through `csv`; the parser tests read the samples under `tests/fixtures/files/`, their provenance in its `README.md` (sdk-core ADR-0020) |

The snapshot listed in `docs/upstream/FETCHED.md` is the reference for names, parameters and
semantics; a wrapper is never written from memory of the API.

## Layout

What this package adds to the family's tree, and its import path, stand in `docs/layout.md`,
imported here:

@docs/layout.md

## Commands

```bash
uv sync --all-extras
uv run pytest                      # offline, replays the fixtures
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pre-commit run --all-files
python3 -I scripts/adr_index.py --check   # the index matches the records in docs/adr/
uv run pytest -m live --tb=short --assert=plain   # needs XIPPIOS_LIVE_TESTS=1, FAOSTAT_USERNAME, FAOSTAT_PASSWORD

# refreshes the fifteen code tables under reference/: one login and fifteen requests, each
# sent once, the count printed; --only element_QCL ... fetches the tables named alone
direnv exec . uv run python scripts/refresh_reference.py

uv run xippios-faostat-mcp   # stdio; add --http for streamable HTTP
```

`.github/workflows/live.yml` runs the live tests nightly at 02:10 UTC, a time derived from
the slug, and on demand; a pull request never runs them.
Only its `uv run pytest -m live --tb=short --assert=plain` step sees `FAOSTAT_USERNAME` and `FAOSTAT_PASSWORD`, each from the secret of the same name.
Every live run takes `--tb=short --assert=plain`, since the log of `live.yml` is public:
the first keeps a failing test's frame arguments out of it, a raw upstream payload among
them, and the second the values a failed `assert` compares. A live test asserts on shapes
and counts, never on a raw payload. The docstring of `tests/test_live.py` says what a live
run sends, and core's plugin prints the count at its end.

## Template updates

This repository is generated from sdk-template, at the tag `.copier-answers.yml` records. A
template release reaches it in a pull request of its own, with
`uvx --from 'copier>=9.19' copier update --defaults --vcs-ref=<tag>` (conventions §15). The
update never overwrites a file this package fills, those that `_skip_if_exists` lists in
sdk-template's [`copier.yml`](https://github.com/xippios/sdk-template/blob/main/copier.yml),
and sdk-template's
[CHANGELOG](https://github.com/xippios/sdk-template/blob/main/CHANGELOG.md) says, per
release, what to port into those by hand in the same pull request.

The update writes every other file it renders again, since they are the template's,
`.claude/rules/never.md` among them. This package keeps no text of its own in them, the
docstring of `mcp.py` included: its own words go into a file it fills. A line it has to
add to one, such as a dependency in `pyproject.toml`, the update carries into the new
render, silently where the release leaves the lines around it alone and as a conflict
where it changes them.

## FAOSTAT specifics

### The bulk host

The bulk host shares the API's one client and its pace: `api.datasets_e` reads the
catalogue and `download_dataset` its ZIPs through `_client.client` with `auth=None`, one
limiter over both hosts, as conventions §4 sends a file that a catalogue links on another
origin through the client without its credentials
(https://github.com/xippios/sdk-faostat/issues/50).

### The account's credentials

`FAOSTAT_USERNAME`, `FAOSTAT_PASSWORD` and a token are never read by value, printed,
logged or compared, and `.envrc` is never read; code reads the two variables by name. They
reach a process only through `direnv exec .` from the clone or a worktree, which loads
them from an `.envrc` that git ignores, or through the org secrets. No process listing or
environment dump (`env`, `printenv`, `set`, `export`, `ps`, `/proc/*/environ`): the shell's
command line carries exported values. The portal's anonymous path, a guest token from
`GET /api/v1/auth/guest` (403 to a plain client, and not in the OpenAPI document), is not
used.

### The login and its recordings

`_client.LoginAuth`, core's `RenewingBearerAuth` with FAOSTAT's `token_request`,
`read_token` and `token_refused`, logs in once per process (`auth_login`, `POST
/auth/login`, form fields `username` and `password`), keeps the access token alone, a
`SecretStr`, for its `ExpiresIn` less 60 s, and logs in once more on a 401 or 403
(`renew_on`; sdk-core ADR-0025). The login runs inside `httpx`'s auth flow, below core's
limiter and hooks, so the 30-per-minute pace does not pace it, and two requests that start
together before the first login answers wait for it and log in once. A login refused with
HTTP 400 and Cognito's `UserNotFoundException` or `NotAuthorizedException` is
`AuthError`, naming the status and the `__type` (`classify` for `api.auth_login`,
`LoginAuth.token_refused` for its own login, which also maps a 401 or 403 so); any other
answer of the login but HTTP 200 is core's `token_refused` (`RateLimitError` for a 429,
`UpstreamError` for a 5xx). The flow reads the login's answer and hands every other
answer back unread. Offline tests send core's placeholder as both variables, which core's
plugin reads from `ENV_VARS` in `_client.py`; the replayed
`tests/fixtures/auth_login/login.json` answers it.

A recording that spends the account's calls:

- runs through `direnv exec . uv run python <script>` from the clone or a
  worktree, with `RetryPolicy(max_attempts=1)`; the script reads the two variables by name
  inside Python and prints fixture paths and statuses only;
- scrubs with one `Scrub` that names each secret once, the user name and the password, a
  made-up login's password likewise (`auth_login/user_not_found.json`), and the login
  answer's three token values (`AccessToken`, `IdToken`, `RefreshToken`), which core's
  credential rule does not catch by name; core replaces each in its every encoded form. The
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

### The packaged code tables

`reference/` holds fifteen tables, `getCodeList`'s answers for `codes/<dimension>/<domain>`
of the dimensions `area`, `element` and `item` of QCL, TCL, FBS, PP and RL, the domains
https://github.com/xippios/sdk-faostat/pull/4 packaged, each `<dimension>_<domain>.json`
with the dimension as `param` and `getCodeList` as `endpoint`, upstream's records as sent
(`CodeItem.dump_upstream` leaves out a named field the record lacked), fetched with the
account by `scripts/refresh_reference.py` through `direnv exec .`, which also rewrites
the provenance rows of `reference/README.md`; no enum is generated. They come from the
dimension ids, which the data endpoint filters by, not from the subdimension ids the
OpenAPI document's examples name; `docs/upstream/OBSERVED.md` notes what
`codes/area/QCL` and `codes/countries/QCL` answer. `list_areas`, `list_elements`
and `list_items` answer from them; `get_data` refuses an area, element or item code a
packaged domain's table lacks with `UnknownCode` before sending, area codes only when
`area_cs` is `None` or `FAO`, item codes likewise with `item_cs`, and sends any other
domain's codes unchecked. Only QCL's three answers and `codes/countries/QCL` are recorded
as fixtures; the other twelve tables are packaged, not recorded.

### What FAOSTAT does beyond its document

Paging (`page_size` with `page_number`, `limit` with `offset`), `no_records`, the `show_*`
and `null_values` options, the coding-system parameters `area_cs` and `item_cs`, the two
element code systems, the columns that differ by domain, the refusals (HTTP 500), the
absence of rate-limit headers, and the bulk downloads' catalogue, files and tables are
noted, each with its probe, in `docs/upstream/OBSERVED.md`, the one file that dates them.
