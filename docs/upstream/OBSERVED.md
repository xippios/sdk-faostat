# What FAOSTAT does but never documents

Notes, written by hand, on what FAOSTAT's API and its bulk downloads do that no page of
this snapshot states (sdk-core's conventions §3). The OpenAPI document,
`openapi/faostat_openapi.yaml`, is the reference for names and parameters; it lists none
of the data endpoint's parameters below for `get_data`, and names `no_records` and
`null_values` only under `post_datasize` and `limit` only under `post_rankings`. Where the
live API answers differently, the wire wins, and `models.py` and `tests/fixtures/` follow
it. `scripts/refresh_upstream.py` neither writes nor checks this file, and `FETCHED.md`
lists it in a row of its own.

Each note ends with its probe: the date, the operation and the sample. A sample recorded
as a fixture is named by its path under `tests/fixtures/`, a sample file of the bulk
downloads by its path under `tests/fixtures/files/`, whose `README.md` gives its
provenance. The first probes of 2026-10-29, sent before the recordings, kept no answer:
their notes name the request.

## The data endpoint

### Paging

`page_size` with `page_number`, and `limit` with `offset`, page the data answer:
`page_size=2&page_number=2` answered rows 3 and 4 of a seven-row query (2017 and 2018 of
2015 to 2021), and `limit=2&offset=0` rows 1 and 2. Without them the whole answer comes in
one body: a query of 30,942 rows answered 9.3 MB at once. No maximum page size was found:
`page_size=60000` answered 60,000 rows, 19 MB in 32 s.

Probe: 2026-10-29, `get_data`; samples
`tests/fixtures/get_data/QCL_page_2.json` (QCL, area 231, item 15, element 2510, 2015 to
2021, `page_size=2&page_number=2`) and `tests/fixtures/get_data/PP_231_2020_page_size_2.json`;
the requests with `limit=2&offset=0`, without paging and with `page_size=60000` kept no
answer.

### `no_records`

`no_records=true` answers `[{"NoRecords": N}]` only, `N` the number of rows, printed as a
float (`1643610.0`) for a large count.

Probe: 2026-10-29, `get_data` with `no_records=true`; the request kept no answer.

### The output options

The data endpoint takes the options `show_codes`, `show_unit`, `show_flags`, `show_notes`
and `null_values`, which the portal sends; an answer without them carried the same 15
columns.

Probe: 2026-10-29, `get_data`; sample
`tests/fixtures/get_data/QCL_231_2510_15_2015_2021.json`, whose request sends the five
options, as every recording of `get_data` does; the request without them kept no answer.

### The coding systems `area_cs` and `item_cs`

`area_cs` and `item_cs` name the coding system of the codes sent: with `area_cs=FAO` and
`item_cs=FAO` the columns are `Area Code (FAO)` and `Item Code (FAO)`, and with
`area_cs=M49` `metadata.dsd` names `Area Code (M49)`; without them the codes are FAO's,
under `Area Code` and `Item Code`.

Probe: 2026-10-29, `get_data`; samples
`tests/fixtures/get_data/QCL_231_FAO_15_FAO_2510_2020.json` (one row),
`tests/fixtures/get_data/QCL_840_M49_15_2510_2020.json` (no rows) and
`tests/fixtures/get_data/QCL_231_2510_15_2015_2021.json`.

### The form of an M49 code in a filter

Whether the data endpoint's M49 filter takes an M49 code as the bulk files print it, with
a leading apostrophe, is not established: `area=840&area_cs=M49`, the United States of
America's M49 code without the apostrophe, answered no rows, where `area=231` answers the
country's rows in FAO's codes, and RL's bulk table prints Afghanistan's M49 code as
`'004`.

Probe: 2026-10-29, `get_data` with `area=840&area_cs=M49`; samples
`tests/fixtures/get_data/QCL_840_M49_15_2510_2020.json` and
`tests/fixtures/get_data/QCL_231_FAO_15_FAO_2510_2020.json`, and RL's table in
`tests/fixtures/files/bulk-csv/RL_first_rows.zip`.

### Two element code systems

The element codes a query filters by are not the answer's `Element Code`: `element=2510`
(Production Quantity, as `codes/element/QCL` lists it) answers rows with `Element Code`
`5510`, and `element=5510` answers no rows, as any unknown code does.

Probe: 2026-10-29, `getCodeList` and `get_data`; samples
`tests/fixtures/get_code_list/element_QCL.json`,
`tests/fixtures/get_data/QCL_231_2510_15_2015_2021.json` and
`tests/fixtures/get_data/QCL_element_5510_empty.json`.

### Refusals with HTTP 500

A data query with no filter is refused with HTTP 500 and the plain text body `Please add
at least one filter.`; a domain code FAOSTAT does not have with HTTP 500 and `Index: 0,
Size: 0`.

Probe: 2026-10-29, `get_data`; samples `tests/fixtures/get_data/no_filter_500.json` and
`tests/fixtures/get_data/XXX_unknown_domain_500.json`.

### No rate-limit headers

No answer carried an `X-RateLimit-*`, `RateLimit-*` or `Retry-After` header, neither the
API's nor the bulk host's.

Probe: 2026-10-29, `get_data`, `get_groupsanddomains`, `getCodeList`, `auth_login` and
`GET production/datasets_E.json`; the response headers of every recording under
`tests/fixtures/`, among them `tests/fixtures/get_data/QCL_231_2510_15_2015_2021.json` and
`tests/fixtures/datasets_e/all.json`.

## The answers' shapes

### Field names beside the document's schemas

The answers' field names differ from the document's schemas: `groupsanddomains` answers
`group_code`, `domain_code` and their like, the fields of the document's
`DomainMetadata`, not `GroupCode` and `DomainaCode`; the data answer `Area Code` and
`Item Code`, not `Area Code (M49)` and `Item Code (CPC)`.

Probe: 2026-10-29, `get_groupsanddomains` and `get_data`; samples
`tests/fixtures/get_groupsanddomains/all.json` and
`tests/fixtures/get_data/QCL_231_2510_15_2015_2021.json`.

## Access

### The portal's guest token

The developer portal reads the API with a guest token from `GET /api/v1/auth/guest`, a
path the OpenAPI document does not name, which refuses a plain client with HTTP 403; the
document's way in is the account's login, `auth_login`.

Probe: 2026-10-29, `GET https://faostatservices.fao.org/api/v1/auth/guest` without a
token, as a plain client; the request kept no answer.

## The bulk downloads

### The tables' columns are the dataset's own

A ZIP's normalized table prints the dataset's own columns: RL's header is `Area Code`,
`Area Code (M49)`, `Area`, `Item Code`, `Item`, `Element Code`, `Element`, `Year Code`,
`Year`, `Unit`, `Value`, `Flag` and `Note`, and MDDW's prints no area, item or year.
`Item Code (CPC)`, which the OpenAPI document's `DataResponse` names, is expected in QCL's
and TCL's tables, whose ZIPs (33 MB and 267 MB) were not fetched.

Probe: 2026-10-29, `GET production/datasets_E.json` and the ZIPs its `FileLocation` names
for RL and MDDW; samples `tests/fixtures/files/bulk-csv/RL_first_rows.zip` and
`tests/fixtures/files/bulk-csv/MDDW.zip`.

### `FileRows` miscounts a table

The catalogue's `FileRows` counts RL's table, 421,850 rows, but not MDDW's: it prints
2,035 where the table holds 1,223 rows.

Probe: 2026-10-29, `GET production/datasets_E.json` and MDDW's ZIP; samples
`tests/fixtures/datasets_e/all.json` and `tests/fixtures/files/bulk-csv/MDDW.zip`.
