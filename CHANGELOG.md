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
