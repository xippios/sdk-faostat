# Layout

The files that every source of the family holds are laid out once, in the tree of
sdk-template's README,
[What gets generated](https://github.com/xippios/sdk-template/blob/main/README.md#what-gets-generated).
This file holds what `xippios-faostat` adds to that tree, a module, a task file, a
script or a test of its own, each with what it holds, and the change that adds one updates it.

The import path is `xippios.faostat` (sdk-core ADR-0006); `src/xippios/` is a
namespace package.
Where the API's operation ids repeat across its services, `api/` keeps one module per service
instead, named after the service, and this file says so (conventions §2).

```
src/xippios/faostat/
  _client.py       also LoginAuth, the account's login on core's RenewingBearerAuth with
                   USERNAME_ENV and PASSWORD_ENV, and the refusals classify maps,
                   CREDENTIAL_REFUSALS, FILTER_REFUSAL and UNKNOWN_DOMAIN
  api/             one module per operation of the OpenAPI document, named after its
                   operationId in snake case: auth_login, get_code_list (getCodeList),
                   get_data and get_groupsanddomains; and datasets_e, the bulk downloads'
                   catalogue on bulks-faostat.fao.org, named from its path
  parse/bulk_csv.py  parse_bulk_csv, a bulk ZIP's normalized table read row by row, a
                   generator
  tasks.py         also get_series, which composes get_data, one request with a year list,
                   and list_bulk_datasets and download_dataset over the bulk catalogue
  params.py        also DIMENSIONS and DOMAINS, the axes of the fifteen tables, and table,
                   each table's declaration, which core's check reads
  enums.py         empty, since no table makes an enum
  reference/       fifteen code tables, <dimension>_<domain>.json: the dimensions area,
                   element and item of QCL, TCL, FBS, PP and RL
tests/
  fixtures/        recorded exchanges, one directory per wrapper or task: auth_login,
                   datasets_e, download_dataset, get_code_list, get_data and
                   get_groupsanddomains
  fixtures/files/bulk-csv/  MDDW's whole ZIP and RL's table cut to 20 rows
  test_api.py      the endpoint wrappers on their recordings: get_code_list and datasets_e
  test_client.py   the login and classify on the recorded exchanges
  test_parse.py    parse_bulk_csv on the samples under tests/fixtures/files/bulk-csv/
  test_refresh_reference.py  the reference script's declaration on the recorded code
                   lists, the logins it names among core's count, and the committed tables
                   and provenance rows against each other
  test_refresh_upstream.py   the snapshot script's declaration and hooks, offline: its
                   pages, the keyed samples, the attribution, the terms page's converter,
                   the pages' notes and the ReDoc page's check against the document in
                   sections; and that no docstring of src/, README.md or
                   CLAUDE.md dates an observation, which OBSERVED.md alone holds
docs/
  upstream/        also OBSERVED.md, the notes by hand on what FAOSTAT does but never
                   documents; openapi/, the OpenAPI document; pages/, the terms of use in
                   Markdown; bulk/, the bulk catalogue; samples/, four answers of the API
```
