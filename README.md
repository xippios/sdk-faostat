# xippios-faostat

Typed Python client, MCP server and FastAPI routes for
[FAOSTAT](https://www.fao.org/faostat/), part of the
[xippios SDK family](https://github.com/xippios). Names and semantics follow the
upstream documentation; every response carries its metadata (source, endpoint,
retrieved_at, request), and `get_data`, `get_series` and `download_dataset` carry the
release FAOSTAT states for it in `vintage`.

## Install

```bash
uv add xippios-faostat            # client only
uv add "xippios-faostat[mcp]"     # + MCP server
uv add "xippios-faostat[http]"    # + FastAPI router
```

A FAO account is needed: `FAOSTAT_USERNAME` (the account's e-mail) and
`FAOSTAT_PASSWORD` in the environment. The client logs in with them on its first request
(`POST /auth/login`, FAOSTAT's `auth_login`), once per process, sends the access token
with every request to the API, and logs in again when the token lapses (after an hour) or a request
is refused with HTTP 401 or 403. Neither the credentials nor a token is logged, and the
tasks return neither. The bulk downloads need none.

## 30-second example

```python
from xippios.faostat import get_data, get_series, list_domains, list_elements

wheat = get_data("QCL", area="231", element="2510", item="15", year=range(2015, 2022))
row = wheat.data[0]  # wheat production in the United States of America, 2015
row.area, row.item, row.year  # ("United States of America", "Wheat", "2015")
row.element_code, row.element  # ("5510", "Production"): the answer's code, not the 2510 sent
row.value, row.value_number  # ("55839540", Decimal("55839540")): as printed, and its number
row.unit, row.flag_description  # ("t", "Official value")
wheat.meta.vintage  # "2025-12-31": QCL's last update, as list_domains prints it
wheat.meta.request  # {"lang": "en", "domain_code": "QCL", "area": "231", ...}

series = get_series("QCL", area="231", item="15", element="2510", since=2015, until=2021)
series.meta.request["year"], series.meta.request["since"]  # ("2015,2016,...,2021", 2015)

list_domains(search="prices").data  # PP, CP, PD, PE (group Prices) and PA, an archive
list_elements("QCL", search="production").data[0]  # code "2510", "Production Quantity"
get_data("QCL", area="231", element="5510")  # UnknownCode: Nothing was sent. Did you mean 2510?
```

`get_data(domain_code, *, area, item, element, year, area_cs, item_cs, page_size,
page_number)` sends one request to FAOSTAT's data endpoint (`get_data`, `GET
/{lang}/data/{domain_code}`), in English, with the output options the portal sends (codes,
units, flags and notes shown); each filter is a code or a list of codes. At least one of
`area`, `item`, `element` and `year` is needed: FAOSTAT refuses a query without a filter,
and so does `get_data`, before sending, saying that nothing was sent. Without `page_size` every matching row comes in
one answer; with `page_size` and `page_number`, one page. A query filters by the element
codes of the domain's element list (2510, Production Quantity), and the rows print other
codes (5510, Production). FAOSTAT answers a code it does not know with no rows, so for
the five domains whose code tables ship with the package, QCL, TCL, FBS, PP and RL,
`get_data` checks every area, element and item code before sending and refuses one the
domain's table lacks with `UnknownCode`, naming the table, its fetch date and the
closest codes; another domain's codes are sent unchecked, and a code that matches nothing
there gives an empty list. An unknown domain raises `NotFoundError`. `meta.vintage` is
the domain's `date_update` from `list_domains` (`groupsanddomains`); `meta.published_at`
stays `None`, since a date is no release time.

`get_series(domain_code, *, area, item, element, since, until)` is one `get_data` request
for a yearly series: `since` and `until` become the year filter, the years from one to
the other as upstream's comma list, or no year filter when both are left out, which
answers every year the domain holds; one without the other is refused before sending.
The rows come in upstream's order, area, item, year ascending in the recorded answers,
and a year the domain does not hold has no row. The codes are checked as `get_data` checks them, and `meta` is
`get_data`'s, with `since` and `until` added to `meta.request`.

`list_areas(domain_code, *, search)`, `list_elements(domain_code, *, search)` and
`list_items(domain_code, *, search)` list the codes those filters take, for the same five
domains, from the package's copies of FAOSTAT's code lists (`getCodeList`,
`codes/<dimension>/<domain>`, `src/xippios/faostat/reference/`), without a request;
`search` keeps the codes whose code or label contains the text. The element lists hold
the filter codes, not the codes the rows print. `meta.retrieved_at` is when the package
fetched the list.

### Bulk downloads

```python
from pathlib import Path

from xippios.faostat import download_dataset, list_bulk_datasets
from xippios.faostat.parse import parse_bulk_csv

list_bulk_datasets(search="land use").data[0]  # dataset_code "RL", file_size "2902KB", ...
land = download_dataset("RL", dest=Path("RL.zip"))  # 3 MB; TCL's ZIP is 267 MB
land.data.path  # PosixPath("RL.zip"): the ZIP as FAOSTAT serves it
land.meta.vintage  # "2026-10-02T00:00:00": the catalogue's DateUpdate as printed
land.meta.published_at  # 2026-10-02 00:00 without a zone, meta.published_at_naive set
rows = parse_bulk_csv(land.data.path)  # one BulkRecord per row of its table, read lazily
first = next(rows)
first.area, first.area_code_m49, first.item, first.year  # ("Afghanistan", "'004", ...)
first.value, first.value_number  # ("65286.000000", Decimal("65286.000000"))
```

`list_bulk_datasets(*, search)` lists the datasets FAOSTAT publishes as files, 69 on
2026-10-29, from the bulk downloads' catalogue (`production/datasets_E.json` on
`bulks-faostat.fao.org`), fetched without the account: each with its code, the domain
code `get_data` takes, its name, last update, the ZIP's size and URL and the rows of its
table; `search` keeps the datasets whose code or name contains the text.

`download_dataset(dataset_code, *, dest)` looks the dataset up in the catalogue and streams its
ZIP to `dest`, without the account, never holding it in memory or caching it; it returns
core's `Downloaded` (path, size, content type, `ETag`, `Last-Modified`, retrieval time).
It is a bulk task: Python only, so the MCP server and the router skip it and no agent is
handed a file path. The files run from 12 KB (MDDW) to 410 MB (TM); TCL's is 267 MB.
`meta.vintage` is the catalogue's `DateUpdate` as printed and `meta.published_at` the
same time, which the catalogue prints without a zone. `parse_bulk_csv(path)` reads the
ZIP's normalized table, the member `<Name>_E_All_Data_(Normalized).csv`, row by row,
straight from the archive: each `BulkRecord` has the columns of the production files
(`area_code`, `area_code_m49` as printed with its apostrophe, `area`, `item_code`,
`item_code_cpc`, `item`, `element_code`, `element`, `year_code`, `year`, `unit`,
`value` as printed with `value_number` beside it, `flag`, `note`), `None` where a dataset does not print one, and
every other column of a dataset under its header in `columns`, as MDDW's surveys and
food groups.

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

Tools are read-only and named `faostat_<verb>_<noun>`. Results are capped, at 200 rows or
64 KB unless a tool has a cap of its own, with a note on how to see the rest, after the
client fetched the whole answer. The tools whose next page sends nothing new, the code
lists, `faostat_list_domains` and `faostat_list_bulk_datasets`, take `offset`, which the
note names; `faostat_get_data` pages by FAOSTAT's `page_size` and `page_number`, and
`faostat_get_series` is narrowed by its years and codes. `--http` serves streamable HTTP instead of stdio.

## Status

<!-- Core's family check (tests/test_family.py) reads this table: keep the "## Status"
heading and the "Task function" column. Each row's Task function cell starts with the
task's name in backticks, alone or as its call (`get_data(code, year)`); several tasks in
one row are backticked names separated by commas; prose may follow. The tables list
exactly tasks.__all__, and tasks_write.__all__ where the package has write tasks. -->

| Upstream operation | Task function | MCP tool | Status |
| --- | --- | --- | --- |
| `get_data` (`GET /{lang}/data/{domain_code}`), the release date from `get_groupsanddomains` | `get_data(domain_code, area, item, element, year, area_cs, item_cs, page_size, page_number)`, a domain's rows | `faostat_get_data` | alpha |
| `get_data` with a `year` list, the release date from `get_groupsanddomains` | `get_series(domain_code, area, item, element, since, until)`, one domain's series over a year range | `faostat_get_series` | alpha |
| `get_groupsanddomains` (`GET /{lang}/groupsanddomains`) | `list_domains(search)`, the domains and subgroups with their groups and release dates | `faostat_list_domains` | alpha |
| `getCodeList` (`GET /{lang}/codes/{dimension_id}/{domain_code}`), `area`, packaged for QCL, TCL, FBS, PP and RL | `list_areas(domain_code, search)`, a domain's area codes | `faostat_list_areas` | alpha |
| `getCodeList`, `element`, packaged for the same five domains | `list_elements(domain_code, search)`, a domain's element codes, the filter codes | `faostat_list_elements` | alpha |
| `getCodeList`, `item`, packaged for the same five domains | `list_items(domain_code, search)`, a domain's item codes | `faostat_list_items` | alpha |
| `production/datasets_E.json` on `bulks-faostat.fao.org`, the bulk downloads' catalogue | `list_bulk_datasets(search)`, the datasets FAOSTAT publishes as files, with sizes and last updates | `faostat_list_bulk_datasets` | alpha |
| The catalogue's `FileLocation`, a dataset's ZIP on `bulks-faostat.fao.org` | `download_dataset(dataset_code, dest)`, a dataset's ZIP on disk, its normalized CSV read by `parse_bulk_csv` | none: a bulk task, Python only, which the adapters skip | alpha |

Every request to the API logs in first where the process has no current token
(`auth_login`, `POST /auth/login`); the login is the client's, no task's. The bulk
downloads' catalogue and files are fetched without it.

## Scope

FAOSTAT's OpenAPI document holds 24 operations, and the package's scope is its data, its
lists and its releases, sixteen of them: the login, `auth_login`; `get_data`, with
`post_datasize` as its count; the code lists `getCodeList`, `get_codes` and
`get_dimensions`; the domains and their groups, `get_groupsanddomains`, `get_domains` and
`get_groups`; `get_bulkdownloads`, beside the bulk catalogue and its ZIPs; the history of
updates, `get_updates`; the four definitions, `get_definitions_domain`,
`get_definitions_domain_by_type`, `get_definitions_types` and `get_definitions_by_type`;
and `get_metadata`. Four of them are wrapped today, the login, the data, the groups and
domains, and the code list, the last for the packaged tables alone, as the status table
above names them. Eight are left out: `post_rankings`, `post_reportdata` and
`post_reportheaders`, since they are FAOSTAT's computed rankings and report tables of the
data, and
`get_search`, `get_suggestions`, `get_documents`, `get_metadata_print` and `get_ping`,
since they serve FAOSTAT's portal: its search, its suggestions, its list of documents, its
printable metadata and its ping. A caller cannot set yet these documented parameters of
the wrapped operations: `lang` on every operation, which the package sends as `en`
(https://github.com/xippios/sdk-faostat/issues/64); `datasource` and `List1Codes` to
`List9Codes` on `get_data` (https://github.com/xippios/sdk-faostat/issues/22) and the
value `csv` of its `output_type` (https://github.com/xippios/sdk-faostat/issues/41);
`datasource` and `section` on `get_groupsanddomains`; and `show_lists` on `getCodeList`,
which the packaged tables leave at upstream's default.

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

## Workflows

`ci.yml` runs ruff, its format check, mypy, pytest and pre-commit on Python 3.12, 3.13 and
3.14, requires a changelog entry of every pull request but Dependabot's and refuses a
fixture file over 256 KiB that a pull request adds or changes. It runs on every pull request and,
called by `publish.yml`, once for a release, and its job `ci` is the check the
organization's ruleset requires. It is handed no secret, and no variable switches it off.

`publish.yml` is the release train (conventions §12): on a push to `main` whose
`pyproject.toml` names a version that has no tag yet and has its section in `CHANGELOG.md`,
it runs `ci.yml`, refuses a core pinned to git, tags the merge commit, builds the package
and, once a reviewer of the environment `pypi` approves the run, publishes it to PyPI by
trusted publishing. Every push to `main` and a dispatch start it, and a push that brings no
release ends quietly. It is handed no secret: the step that tells a release is handed the
job's token as `GH_TOKEN`, the tag goes with the job's token and PyPI trusts the workflow
itself. Its job `tag` holds the one checkout of the repository that keeps its credentials,
since it pushes the tag with the job's token; every other checkout sets
`persist-credentials: false` (conventions §13). No variable switches it off.

`live.yml` runs every `live` test against the upstream with `--tb=short --assert=plain`, so
its public log holds neither a failing test's arguments nor the values an assertion compared.
It runs every night at 02:10 UTC and on demand, never on a pull request.
Its pytest step alone is handed `XIPPIOS_LIVE_TESTS` and, each from the secret of the same
name, `FAOSTAT_USERNAME`, `FAOSTAT_PASSWORD`, so the checkout, setup-uv and `uv sync` see none.
A variable `WORKFLOW_LIVE` of `off`, the repository's over the organization's, switches it off.

`conventions.yml` calls the organization's review of a pull request against the documents
listed under Documents below, the check `conventions / conventions`, when a pull request
opens, is pushed to, reopens or is edited, and on a push to `main` or a dispatch the review
of the range of commits, `range / range`. It hands the review the organization's
secret of the model's key, by name. A variable `WORKFLOW_CONVENTIONS` of `off`, the
repository's over the organization's, switches both off.

`adr-index.yml` calls the organization's check of the ADR index, `adr-index / adr-index`,
which runs `scripts/adr_index.py --check`, when a pull request opens, is pushed to or
reopens. It hands over nothing, and the called workflow reads its switch itself: a variable
`WORKFLOW_ADR_INDEX` of `off`, the repository's over the organization's, skips the check.

## Documents

- sdk-core: [docs/conventions.md](https://github.com/xippios/sdk-core/blob/main/docs/conventions.md) — the conventions every xippios source package follows: its layout, names, results, tests and releases.
- sdk-core: [docs/adr.md](https://github.com/xippios/sdk-core/blob/main/docs/adr.md) — the index of the family's architecture decisions, which the conventions cite.
- sdk-core: [docs/definition-of-done.md](https://github.com/xippios/sdk-core/blob/main/docs/definition-of-done.md) — what a change satisfies before its pull request is opened.
- sdk-core: [docs/review-checklist.md](https://github.com/xippios/sdk-core/blob/main/docs/review-checklist.md) — what the review of a pull request checks, in order.
- sdk-faostat: [docs/adr.md](https://github.com/xippios/sdk-faostat/blob/main/docs/adr.md) — the index of this package's own decisions, generated from the records in `docs/adr/`.
- sdk-faostat: [docs/upstream/FETCHED.md](https://github.com/xippios/sdk-faostat/blob/main/docs/upstream/FETCHED.md) — the snapshot of the upstream documentation, the reference for names, parameters and semantics.

## Licence

Apache-2.0. See [LICENSE](https://github.com/xippios/sdk-faostat/blob/main/LICENSE).
