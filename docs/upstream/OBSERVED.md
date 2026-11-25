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
provenance, and a file of this snapshot by its path under `docs/upstream/`, as the capture
of 2026-11-25 wrote it, an earlier capture by the commit that holds it. The first probes of 2026-10-29, sent before the recordings, kept no
answer: their notes name the request.

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

### The code lists carry `parent` beyond the document's schema

The document's `CodeItem` names `code`, `label` and `aggregate_type`. QCL's and TCL's item
lists, RL's on 51 of its 57 records, and TCL's and RL's element lists carry `parent` as
well, the code above a record in the list's tree; every area list, the element lists of
QCL, FBS and PP and the item lists of FBS and PP carry none. On 2026-11-25 FBS's element
list, grown from 21 records to 28, carried `parent` on every one, and the other fourteen
lists carried it as before.

Probe: 2026-10-29 and 2026-11-25, `getCodeList` for the dimensions `area`, `element` and
`item` of QCL, TCL, FBS, PP and RL; samples `tests/fixtures/get_code_list/item_QCL.json`
and `tests/fixtures/get_code_list/area_QCL.json`, the packaged tables
`src/xippios/faostat/reference/item_RL.json` and
`src/xippios/faostat/reference/element_TCL.json`, and the fifteen tables of the reference
refresh of 2026-11-25 in https://github.com/xippios/sdk-faostat/pull/76.

### The area list holds the countries and the aggregates

`codes/area/QCL` lists 278 codes: the 210 countries that `codes/countries/QCL` lists,
with the same labels, and 68 aggregates beside them, the totals and lists of regions and
special groups, such as `5000` World + (Total) and `5000>` World > (List). The OpenAPI
document's examples of `dimension_id` name the subdimension ids alone. On 2026-11-25 the
area list still held 278 codes.

Probe: 2026-10-29 and 2026-11-25, `getCodeList` for `codes/area/QCL` and
`codes/countries/QCL`; samples `tests/fixtures/get_code_list/area_QCL.json` and
`tests/fixtures/get_code_list/countries_QCL.json`, and the table of the reference
refresh of 2026-11-25 in https://github.com/xippios/sdk-faostat/pull/76.

### The columns differ by domain

A data answer's rows carry their domain's columns: QCL's carry 15, from `Domain Code` to
`Note`, and PP's carry `Months Code` and `Months` after `Year` and no `Note`.

Probe: 2026-10-29, `get_data`; samples
`tests/fixtures/get_data/QCL_231_2510_15_2015_2021.json` and
`tests/fixtures/get_data/PP_231_2020_page_size_2.json`.

## Access

### The portal's guest token

The developer portal reads the API with a guest token from `GET /api/v1/auth/guest`, a
path the OpenAPI document does not name, which refuses a plain client with HTTP 403; the
document's way in is the account's login, `auth_login`.

Probe: 2026-10-29, `GET https://faostatservices.fao.org/api/v1/auth/guest` without a
token, as a plain client; the request kept no answer.

## The bulk downloads

### The catalogue and its files are open

The bulk host, which the OpenAPI document does not name, serves its catalogue,
`production/datasets_E.json`, and the ZIPs that its `FileLocation` names to a client
without the account. The catalogue listed 69 datasets, each code a domain that
`get_groupsanddomains` lists, every one a `zip` of `csv`, its `DateUpdate` a time without
a zone (`2026-10-02T00:00:00` for RL) and its `FileSize` text in kilobytes (`2902KB`).
Its `Topic` was `null` for 12 datasets and its `DatasetDescription` for 3. The ZIPs ran
from `12KB`, MDDW's, to `410792KB`, TM's, with TCL's `267104KB`, QCL's `33127KB` and
RL's `2902KB`; on 2026-11-25 MDDW's, still the smallest, printed `19KB` after its
release of 2026-11-23, and TM's was still the largest.

Probe: 2026-10-29 and 2026-11-25, `GET production/datasets_E.json` without the account,
and `get_groupsanddomains` on 2026-10-29; samples `tests/fixtures/datasets_e/all.json`,
`tests/fixtures/get_groupsanddomains/all.json` and `docs/upstream/bulk/datasets_E.json`
as the capture of 2026-11-25 wrote it.

### A ZIP holds one normalized table and its code lists

A dataset's ZIP holds one table whose name ends in `_E_All_Data_(Normalized).csv` and
small code lists beside it, RL's `_AreaCodes.csv`, `_Elements.csv`, `_Flags.csv` and
`_ItemCodes.csv`, and MDDW's `_Elements.csv`, `_Flags.csv`, `_Indicators.csv` and
`_Surveys.csv`. The table is UTF-8 without a byte order mark, and its lines end in CRLF.

Probe: 2026-10-29, the ZIPs that the catalogue's `FileLocation` names for RL and MDDW;
samples `tests/fixtures/files/bulk-csv/MDDW.zip`, whole, and
`tests/fixtures/files/bulk-csv/RL_first_rows.zip`, RL's table cut to its first rows, each
with its URL, bytes and sha256 in `tests/fixtures/files/README.md`.

### The tables' columns are the dataset's own

A ZIP's normalized table prints the dataset's own columns: RL's header is `Area Code`,
`Area Code (M49)`, `Area`, `Item Code`, `Item`, `Element Code`, `Element`, `Year Code`,
`Year`, `Unit`, `Value`, `Flag` and `Note`, its M49 code printed with a leading apostrophe
(`'004`) and its `Value` with six decimals, and MDDW's prints no area, item or year.
RL's `Value` was empty for its 85 values flagged `L`, "Missing value", and its `Note`
empty on every row. `Item Code (CPC)`, which the OpenAPI document's `DataResponse` names,
is expected in QCL's and TCL's tables, whose ZIPs (33 MB and 267 MB) were not fetched.

Probe: 2026-10-29, `GET production/datasets_E.json` and the ZIPs its `FileLocation` names
for RL and MDDW, RL's whole table read at the recording; samples
`tests/fixtures/files/bulk-csv/RL_first_rows.zip`, that table cut to its first 20 rows,
and `tests/fixtures/files/bulk-csv/MDDW.zip`.

### `FileRows` and `FileSize` move without a new release

The catalogue's `FileRows` is its own count of a table's rows, which changes while the
dataset's `DateUpdate` and `FileSize` stay as they were, and its `FileSize` moves while
the other two stay. On 2026-10-29 it counted RL's
table, 421,850 rows, but not MDDW's: it printed 2,035 where the table held 1,223 rows. On
2026-11-20 it printed 1,223 for MDDW, and the `FileRows` of eight datasets, CB, EA, FBS,
FO, HCES, MDDW, SCL and SUA, had changed with their `DateUpdate` and `FileSize` unchanged
(FBS from 5,878,736 to 4,820,497). On 2026-11-25 FBSH's `FileSize` had moved from
`70769KB` to `70486KB` with its `DateUpdate` and `FileRows` unchanged. Only RL's and
MDDW's tables were read.

Probe: 2026-10-29, 2026-11-20 and 2026-11-25, `GET production/datasets_E.json`, and
MDDW's ZIP on 2026-10-29; samples `tests/fixtures/datasets_e/all.json`,
`docs/upstream/bulk/datasets_E.json` as the capture of 2026-11-25 wrote it, the capture
of 2026-11-20 in
[3df2999](https://github.com/xippios/sdk-faostat/commit/3df299939b1b7a91facd3474725fd4ac879caec6),
and `tests/fixtures/files/bulk-csv/MDDW.zip`.
