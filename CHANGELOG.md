# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (pre-1.0: breaking changes bump the minor).

## [Unreleased]

### Added

- Scaffold from [sdk-template](https://github.com/xippios/sdk-template): configured
  client for FAOSTAT, empty task layer, MCP server and FastAPI router
  wired to it, test harness with core's family check, CI, the nightly live tests and
  the release train, in which a release PR's merge tags and publishes.
- The documentation snapshot in `docs/upstream/`, captured on 2026-10-29 by
  `scripts/refresh_upstream.py`: FAO's OpenAPI document, the FAO Statistical Database
  Terms of Use, the bulk downloads' catalogue and four structural samples of the API's
  answers; the README names the FAO account the API needs and the data's licence,
  CC BY 4.0.
- The FAO account's login: the client logs in once per process with `FAOSTAT_USERNAME`
  and `FAOSTAT_PASSWORD` (`auth_login`, `POST /auth/login`), sends the access token as a
  bearer, and logs in again when the token lapses or a request is refused with HTTP 401
  or 403, once per request; a missing variable is `ConfigError`, a refused login
  `AuthError`.
  Neither the credentials nor a token is logged; the access token alone is kept, masked.
- `get_data(domain, *, area, item, element, year, area_cs, item_cs, page_size,
  page_number)`, a domain's rows from FAOSTAT's data endpoint, each filter a code or a
  list of codes, every row's value a number where upstream's text is one, every column a
  domain prints beyond the named ones kept in `columns` under upstream's header; a query
  without a filter is refused before sending, an unknown domain is `NotFoundError`;
  `meta.vintage` is the domain's last update as `groupsanddomains` prints it,
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
