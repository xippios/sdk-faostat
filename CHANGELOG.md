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
