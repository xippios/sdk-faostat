# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (pre-1.0: breaking changes bump the minor).

## [0.2.0] - 2026-11-20

### Added

- `xippios.faostat.mcp` exports `build()`, the tool set of xippios-core's package contract
  with the tools' caps, `server`, built from it, and `ENV_VARS`, the variables the package
  reads, `FAOSTAT_USERNAME` and `FAOSTAT_PASSWORD`, both secret and required, so a host
  serves the package as `xippios-faostat-mcp` does.
  (https://github.com/xippios/sdk-core/issues/245)

### Changed

- The package's docstrings and `CLAUDE.md` cite each design decision by a public record,
  the pull request that took it or a convention of sdk-core, where they named a person, a
  date or an internal reference that no reader could open, and a command that needs the
  account runs as `direnv exec .` from the clone or a worktree. `docs/handover.md`, the
  hand-over of the 0.1.0 release, is removed: its known limits stand in
  `docs/upstream/OBSERVED.md`, `CLAUDE.md`, the README and `get_data`'s docstring.
  (https://github.com/xippios/sdk-faostat/issues/16)
- What FAOSTAT's API does that its OpenAPI document does not state moves from the capture
  section of `docs/upstream/FETCHED.md` into `docs/upstream/OBSERVED.md`, each note with
  the probe that showed it, joined by what the bulk tables, the M49 filter and the portal's
  guest token showed. `FETCHED.md` lists the file in a row of its own, and the pages it
  cites without requesting them in a table `Not fetched`. The documentation snapshot under
  `docs/upstream/` is refreshed on 2026-11-20, its OpenAPI document unchanged.
  (https://github.com/xippios/sdk-faostat/issues/17)
- Requests that start together while the process holds no token log in once and wait for
  that login, where each could log in, a keyed call each. A request refused with HTTP 401
  or 403 still logs in once more and is sent again once. A login answered with another
  status than 200 or a refusal of the account raises xippios-core's error quoting nothing
  of the answer, a 5xx an `UpstreamError` with an empty `body`, where it held the answer's
  text. (https://github.com/xippios/sdk-core/issues/156)
- `xippios-faostat-mcp` names itself in its usage line and its errors, an unknown option
  ending `xippios-faostat-mcp: error: unrecognized arguments: --bogus`, where they named the
  server, `xippios-faostat`. Its help says that `--allow-remote` changes nothing on this
  read server, which is not held to loopback, where it described the option of a write
  server. (https://github.com/xippios/sdk-core/issues/167)
- A tool's error answer sets `isError` on its result beside the text
  `error: <ErrorClass>: <message>`, `faostat_get_data` without a filter or with a code that
  a packaged table lacks among them, so a client tells a refusal from data without reading
  the text, where the result was not flagged. (https://github.com/xippios/sdk-core/issues/168)
- `parse_bulk_csv`'s refusal of a table names the table alone,
  `faostat: Inputs_LandUse_E_All_Data_(Normalized).csv is not UTF-8 text: invalid start
  byte`, where it named the table in its ZIP, `... (Normalized).csv in RL.zip ...`. A
  refusal of the archive itself still names the ZIP, and the table is read through
  xippios-core's `decode_csv`. (https://github.com/xippios/sdk-core/issues/89)
- A refusal that names another task names its MCP tool too, where it named the task alone:
  an unknown domain's `NotFoundError` ends `list_domains names the domains (over MCP, the
  tool faostat_list_domains)`, an unknown code's names `faostat_list_areas`,
  `faostat_list_elements` or `faostat_list_items` beside its task, and a list task's
  refusal of a domain without a packaged table names `faostat_get_data`.
  (https://github.com/xippios/sdk-core/issues/111)
- A route answers an argument that its schema refuses, `page_size` `"many"` posted to
  `/faostat/get_data` say, as problem details before the task runs: HTTP 422,
  `application/problem+json`, the title `InvalidRequestError` and the detail
  `page_size: <message>`, without the value given, where FastAPI's own 422 listed its error
  details with the input. (https://github.com/xippios/sdk-core/issues/66)
- A refusal of a code that a packaged table lacks, `element="5510"` on QCL say, ends with
  `If upstream added it since, the packaged list is out of date.`, where it ended `the
  packaged list needs a refresh (/refresh-reference-data).`, a command an agent cannot run.
  (https://github.com/xippios/sdk-core/issues/111)
- Adopts sdk-template v0.3.4, from v0.3.2, with conventions 1.27 and no new core minor: the
  floor stays `xippios-core~=0.3.0`. The README lists the package's documents under
  `## Documents`, and `CLAUDE.md` holds the rules that `.claude/family.md` carried, which
  leaves with `/adopt-release`, citing sdk-core's decision records as `sdk-core ADR-NNNN`.
  Changelog entries are fragments under `changelog/`, the package's own decisions go into
  `docs/adr/` with the index that `scripts/adr_index.py` writes, and a pull request runs the
  organization's checks from `organization.yml`, where `gates.yml` was.
  (https://github.com/xippios/sdk-template/releases/tag/v0.3.4,
  https://github.com/xippios/sdk-faostat/issues/14)
- Adopts sdk-template v0.3.2, from v0.3.0.
- `.copier-answers.yml` records the answer
  `live_secrets: '[FAOSTAT_USERNAME, FAOSTAT_PASSWORD]'` ahead of the adoption of
  sdk-template v0.3.2, which asks it: the rendered `live.yml` then passes the account's
  two secrets, `FAOSTAT_USERNAME` and `FAOSTAT_PASSWORD`, to the live step, which until
  now takes them by a hand edit that the template's render drops.

### Fixed

- An answer of HTTP 200 that is not JSON, a maintenance page say, or JSON that is not the
  documented answer is asked again on the next call, where it was cached for five minutes
  and every call in that time failed with `ValidationError` without a request.
  (https://github.com/xippios/sdk-core/issues/122)
- A call that fetches `groupsanddomains`, a data answer or the bulk catalogue and a later
  call that the cache answers within five minutes report one `meta.retrieved_at`, the time
  the answer arrived, where the two reported two readings of the clock, `list_domains`
  called twice say. (https://github.com/xippios/sdk-core/issues/79)

### Breaking

- The wrappers `api.get_data.get_data`, `api.get_code_list.get_code_list`,
  `api.get_groupsanddomains.get_groupsanddomains` and `api.datasets_e.datasets_e` return
  xippios-core's `Answer`, the parsed answer as `payload` beside `retrieved_at`, where each
  returned a pair of its own with the answer as `response`. `DataAnswer`, `CodeListAnswer`,
  `GroupsAndDomainsAnswer` and `DatasetsCatalogueAnswer` are gone, and the tasks answer as
  before. (https://github.com/xippios/sdk-core/issues/123)
- A tool refuses an argument that it does not declare before it runs, whatever its value,
  where the argument was dropped and the tool ran without it: `faostat_list_domains` called
  with `serch` answers `error: InvalidRequestError: serch: Not an argument of this tool`,
  then names `search`, the one argument it takes, where it listed every domain.
  (https://github.com/xippios/sdk-core/issues/84)
- Adopts sdk-template v0.4.0, from v0.3.4, with `core_version=0.4.0`. The package depends
  on `xippios-core~=0.4.0`, its extras likewise, and follows conventions 1.28.
  (https://github.com/xippios/sdk-template/releases/tag/v0.4.0,
  https://github.com/xippios/sdk-faostat/issues/48)

## [0.1.0] - 2026-10-29

First release, on xippios-core 0.3.0 from PyPI (`~=0.3.0`), sdk-template v0.3.0 and the
family's conventions 1.22. It wraps FAOSTAT, the statistical database of the Food and
Agriculture Organization of the United Nations (FAO): its data API, which needs a FAO
account, and its bulk downloads, which need none. The client logs in with the account
(`FAOSTAT_USERNAME`, `FAOSTAT_PASSWORD`) once per process, sends the access token as a
bearer, and logs in again when the token lapses or a request is refused with HTTP 401 or
403. `get_data` reads a domain's rows, `list_domains` lists the domains with their
release dates, and `get_series` reads a yearly series in one request. Fifteen code
tables ship with this version, the area, element and item codes of five domains (QCL,
TCL, FBS, PP and RL) as fetched on 2026-10-29: `list_areas`, `list_elements` and
`list_items` read them without a request, and `get_data` refuses before sending a code
the domain's table lacks, unless the query names another coding system. FAOSTAT has two
element code systems: a query filters by the codes of the domain's element list (2510,
Production Quantity, in QCL) and the rows print others (5510, Production); the tables
hold the codes a query takes, and nothing is translated between the two.
`list_bulk_datasets` reads the bulk downloads' catalogue; the bulk task
`download_dataset`, in Python only, with no MCP tool and no route, streams a dataset's
ZIP to disk, and `parse.parse_bulk_csv` reads its table row by row. The other seven
tasks are MCP tools and HTTP routes. The client keeps a self-imposed pace of 30 requests
per minute, since FAOSTAT documents no rate limit, and caches its answers of HTTP 200
for five minutes. The documentation snapshot of 2026-10-29 under `docs/upstream/`, FAO's
OpenAPI document among it, is the reference for names and semantics.

### Added

- Scaffold from [sdk-template](https://github.com/xippios/sdk-template): configured
  client for FAOSTAT, MCP server and FastAPI router wired to the task layer, test
  harness with core's family check, CI, the nightly live tests and the release train, in
  which a release PR's merge tags and publishes.
- The documentation snapshot in `docs/upstream/`, captured on 2026-10-29 by
  `scripts/refresh_upstream.py`: FAO's OpenAPI document, the FAO Statistical Database
  Terms of Use, the bulk downloads' catalogue and four structural samples of the API's
  answers; the README names the FAO account the API needs and the data's licence,
  CC BY 4.0.
- The FAO account's login: the client logs in once per process with `FAOSTAT_USERNAME`
  and `FAOSTAT_PASSWORD` (`auth_login`, `POST /auth/login`), sends the access token as a
  bearer, and logs in again when the token lapses or a request is refused with HTTP 401
  or 403, once per request; a missing variable is `ConfigError`, a login that refuses the
  credentials `AuthError`, any other failed login core's mapping (`RateLimitError`,
  `UpstreamError`). Only the login's answer is read by the login; every other answer goes
  back to the client unread. Neither the credentials nor a token is logged; the access
  token alone is kept, masked.
- `get_data(domain, *, area, item, element, year, area_cs, item_cs, page_size,
  page_number)`, a domain's rows from FAOSTAT's data endpoint, each filter a code or a
  list of codes, every row's value a number where upstream's text is one, every column a
  domain prints beyond the named ones kept in `columns` under upstream's header (a code
  column that `area_cs` or `item_cs` renames among them, `area_code` or `item_code` then
  `None`); a query without a filter is refused before sending, an unknown domain is
  `NotFoundError`; `meta.vintage` is the domain's last update as `groupsanddomains` prints it,
  `meta.published_at` stays empty. Tool `faostat_get_data`.
- `list_domains(*, search)`, FAOSTAT's domains and subgroups with their groups and release
  dates (`groupsanddomains`). Tool `faostat_list_domains`.
- The wrappers `api.auth_login`, `api.get_data` and `api.get_groupsanddomains`, their
  recorded fixtures, and the nightly live run with the account's two org secrets.
- Fifteen packaged code tables under `reference/`, the area, element and item codes of
  QCL, TCL, FBS, PP and RL as FAOSTAT's `getCodeList` lists them, fetched on 2026-10-29 by
  `scripts/refresh_reference.py` through the new wrapper `api.get_code_list`.
- `list_areas(domain, *, search)`, `list_elements(domain, *, search)` and
  `list_items(domain, *, search)`, a domain's codes from the packaged tables, without a
  request, `search` over code and label; the element lists hold the codes a data query
  filters by, not those the rows print. Tools `faostat_list_areas`,
  `faostat_list_elements` and `faostat_list_items`, up to 1,000 rows each.
- `get_data` refuses an area, element or item code the packaged table of QCL, TCL, FBS,
  PP or RL lacks with `UnknownCode` before sending, naming the table, its fetch date and
  the closest codes (`element=5510` on QCL names 2510, Production Quantity), since
  FAOSTAT answers an unknown code with no rows; another domain's codes are sent unchecked.
- `get_series(domain, area, item, element, *, since, until)`, one `get_data` request for
  a yearly series: the years `since` to `until` as upstream's `year` list, or no year
  filter when both are left out, every year the domain holds; one without the other, or
  `since` after `until`, is refused before sending. Rows in upstream's order, `get_data`'s
  code checks and `meta`, `since` and `until` added to `meta.request`. Tool
  `faostat_get_series`, 200 rows with a note naming `since` and `until`.
- `list_bulk_datasets(*, search)`, the datasets FAOSTAT publishes as files, from the bulk
  downloads' catalogue `datasets_E.json` on `bulks-faostat.fao.org`, fetched without the
  account through the new wrapper `api.datasets_e`: each dataset's code, name, last update,
  ZIP size, rows and URL; `search` over code and name. Tool `faostat_list_bulk_datasets`,
  up to 100 rows and 160 KiB, the whole catalogue uncut, its note naming `search`.
- `download_dataset(domain, dest)`, a bulk task, Python only: the dataset's ZIP, as the
  catalogue names it, streamed to `dest` without the account, never held in memory;
  `meta.vintage` the catalogue's last update as printed and `meta.published_at` the same
  time, which the catalogue prints without a zone.
- `parse_bulk_csv(path)` in `xippios.faostat.parse`, the ZIP's normalized table
  (`<Name>_E_All_Data_(Normalized).csv`) read row by row straight from the archive, each
  row a `BulkRecord`: the columns of the production files named, every other column a
  dataset prints kept under its header in `columns`, `value` a number where its text is
  one.
