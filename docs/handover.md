# Handover — xippios-faostat 0.1.0

Date: 2026-10-29 · Written in the release PR (`chore/release-0.1.0`) for the next
session on sdk-faostat · Decisions cite the coordination log of session `sdk-faostat` by
its time, CET: `coordination/log/sdk-faostat.md` in the coordination root
(`~/github/sdk`), whose `scripts/coord.py` is the root's script, not this repository's;
its `log show sdk-faostat` prints the last 20 entries by default, so read the 2026-10-29
lines from the file. "PR N" below is the package number of the 0.1.0 briefing
(`.claude/briefings/sdk-faostat/0.1.0.md` in the root); the GitHub number follows.

## State

- 0.1.0 is the first release. The release PR's merge runs `publish.yml`, which tags
  `v0.1.0` on the merge commit and waits at the `pypi` environment until Johannes
  approves the run; the PyPI pending publisher (owner xippios, repository sdk-faostat,
  workflow `publish.yml`, environment `pypi`) has been in place since 2026-10-29, set by
  Johannes at the scaffold (log 05:47). Confirm the release at
  `https://pypi.org/pypi/xippios-faostat/json` afterwards.
- Floor: `xippios-core~=0.3.0` from PyPI with its `mcp`, `http` and `testing` extras, no
  git pin (no `[tool.uv.sources]`); sdk-template v0.3.0 (`.copier-answers.yml`,
  `_commit: v0.3.0`, `has_files: true`, `api_key_env` empty, since the template renders
  no login: the login in `_client.py` and `live.yml`'s two secrets are hand-written);
  conventions 1.22.
- Merged before the release, each by Johannes on 2026-10-29: #1 the scaffold (PR 1,
  05:16:50Z, 4ef3734), #2 the upstream snapshot of 2026-10-29 (PR 2, 07:30:27Z,
  e1f91d5), #3 the login client, `get_data` and `list_domains` (PR 4, 07:58:46Z,
  d336387), #4 the packaged tables and the three list tasks (PR 6, 08:03:30Z, 2779cc0),
  #5 `get_series` (PR 7, 08:14:48Z, b91d758) and #6 the bulk catalogue,
  `download_dataset` and `parse_bulk_csv` (PR 8, 08:16:31Z, 2d4392b); this release PR
  (PR 11) last. Each branch was stacked on the one before it and opened against `main`
  once the one below had merged. PRs 3, 5 and 9 did not run: the package started on core
  0.3.0 and template v0.3.0 outright (G1, 2026-10-28), so no re-pin and no adoption. PR
  10, the reference refresh, did not run either (G5 third round, question 17, below).
- `.secrets.baseline` holds 23 audited entries: FETCHED.md's two quoted S3 ETags (row
  144), twenty response-header ids in the fixtures, nineteen `x-amz-cf-id` and one
  `x-amz-version-id` (row 271), and the `body_base64` line of MDDW's recorded ZIP (row
  124). A new recording brings entries of its own, and a PR that changes the baseline is
  class `human`.

## What 0.1.0 covers

Two hosts. The data API, `https://faostatservices.fao.org/api/v1`, needs a FAO account:
`_client.LoginAuth`, an `httpx.Auth`, reads `FAOSTAT_USERNAME` and `FAOSTAT_PASSWORD` by
name, logs in once per process at `POST /auth/login` (`auth_login`), keeps the access
token alone, a `SecretStr`, for its `ExpiresIn` (3,600 s) less 60 s, and logs in once
more on a 401 or 403 (row 252). The bulk downloads on `bulks-faostat.fao.org`, the
catalogue and the ZIPs, are open and fetched with `auth=None`, so no token goes there.
Eight tasks:

- `get_data(domain, *, area, item, element, year, area_cs, item_cs, page_size,
  page_number)`: one data request (`GET /{lang}/data/{domain_code}`, in English, the
  portal's output options fixed), each filter a code or a list of codes; unpaged by
  default, every matching row in one answer, `page_size` and `page_number` passed
  through; a query without a filter refused before sending, an unknown domain
  `NotFoundError`. A `DataRecord` names the columns QCL and PP print (PP's `Months Code`
  and `Months`), the value a `Decimal` where its text is a number, and keeps every other
  column under its header in `columns`, a code column that `area_cs` or `item_cs`
  renames among them (`area_code` or `item_code` then `None`). `meta.vintage` is the
  domain's `date_update` from `groupsanddomains`, read through the cache;
  `meta.published_at` and `meta.total` are `None` (row 263; ADR-0012).
- `get_series(domain, area, item, element, *, since, until)`: one `get_data` request
  with the years `since` to `until` as upstream's year list, or no year filter when both
  are `None`; one alone, or `since` after `until`, refused before sending. It composes
  the task, as sdk-eurostat's slices do (row 90).
- `list_domains(*, search)`: `groupsanddomains`, 78 domains and subgroups on 2026-10-29,
  with their groups and release dates.
- `list_areas`, `list_elements` and `list_items` (`domain, *, search`): the fifteen
  packaged tables below, without a request; a domain without a table is
  `InvalidRequestError`. `get_data` checks a packaged domain's area, element and item
  codes against them before sending and refuses a code the table lacks with
  `UnknownCode`, naming the table, its fetch date and the closest codes (`element=5510`
  on QCL names 2510): area codes only when `area_cs` is `None` or `FAO`, item codes
  likewise with `item_cs` (row 278). Another domain's codes go unchecked.
- `list_bulk_datasets(*, search)`: the catalogue `production/datasets_E.json`
  (`api.datasets_e`), 69 datasets on 2026-10-29, each with its code, name, last update,
  ZIP size, rows and URL.
- `download_dataset(domain, dest)`: the dataset's ZIP as the catalogue names it,
  streamed to `dest` through core's `download`, never cached; named in `BULK_TASKS`, so
  Python only. `meta.vintage` is the catalogue's `DateUpdate` as printed and
  `meta.published_at` the same time without a zone, `published_at_naive` set.
  `parse.parse_bulk_csv(path)` yields one `BulkRecord` per row of the ZIP's member
  `<Name>_E_All_Data_(Normalized).csv`, lazily, with the standard library's `zipfile`
  and `csv` (row 125).

The seven others are MCP tools and HTTP routes. `MCP_CAPS`: `get_data` and `get_series`
200 rows within the family's 64 KB, each with a note; `list_domains` the family's cap
with a note naming `search`; the three code lists 1,000 rows within 64 KB (TCL's 674
items are cut by the bytes at 657 rows); `list_bulk_datasets` 100 rows and 160 KiB, so
the whole catalogue (107,481 bytes as compact JSON on 2026-10-29) comes uncut.

The fifteen tables, `reference/<dimension>_<domain>.json`, are `getCodeList`'s answers
for `codes/<dimension>/<domain>`, fetched with the account by one
`scripts/refresh_reference.py` run on 2026-10-29 between 07:06:41Z and 07:07:05Z (16
keyed calls, in #4); each file's `fetched` is its `meta.retrieved_at`. Codes per table:

| Domain | area | element | item |
| --- | --- | --- | --- |
| QCL | 278 | 5 | 338 |
| TCL | 317 | 4 | 674 |
| FBS | 247 | 21 | 147 |
| PP | 233 | 4 | 259 |
| RL | 321 | 9 | 57 |

The element tables hold the codes a query filters by (2510, Production Quantity), not
the `Element Code` the rows print (5510, Production); nothing is translated between the
two (ADR-0003). The tables come from the dimension ids, which the data endpoint filters
by (`codes/area/QCL`, 278 codes), not from the subdimension ids the OpenAPI document's
examples name (`codes/countries/QCL`, QCL's 210 countries without its 68 aggregates).

## Known limits

- The M49 filter form is not established: the bulk files print M49 codes with a leading
  apostrophe (`'004`), and `area_cs=M49` with `area=840` answered no rows
  (`tests/fixtures/get_data/QCL_840_M49_15_2510_2020.json`), so whether the API's M49
  filter wants that form is open.
- The portal's guest token (`GET /api/v1/auth/guest`, 403 to a plain client, not in the
  OpenAPI document) is not used; the API needs the account.
- The coding-system exemption (row 278): the tables hold FAO codes, so `get_data` checks
  no area code under `area_cs` `M49`, `ISO2` or `ISO3` and no item code under `item_cs`
  `CPC`; such codes are sent unchecked, and one FAOSTAT does not know answers no rows.
- The bulk CSV's columns are the dataset's own: RL's table prints `Area Code (M49)` and
  `Note`, MDDW's no area, item or year; `BulkRecord` names the production files' columns
  and keeps the rest in `columns`. `Item Code (CPC)`, which the OpenAPI document's
  `DataResponse` names, is expected in QCL's and TCL's tables, whose ZIPs (33 MB,
  267 MB) were never fetched. The catalogue's `FileRows` counts RL's table (421,850) but
  not MDDW's (2,035, where the table holds 1,223 rows).
- The login runs inside `httpx`'s auth flow, below core's limiter, so the pace does not
  pace it, and two requests that start together before the first login answers may each
  log in (row 252's review points).
- `get_data` is unpaged by default: step 0 saw 30,942 rows in 9.3 MB in one answer and
  60,000 rows (19 MB, 32 s) for `page_size=60000`, no maximum found; the MCP cap bounds
  what an agent receives, not what the client fetches.

## Pace, cache, live budget

- Pace: 30 requests per minute, burst 1, self-imposed (G5 question 6; ADR-0010):
  FAOSTAT documents no limit, and no answer carried a rate-limit header or
  `Retry-After` (step 0); no `QuotaPolicy`. The bulk host goes through the same client
  and its pace.
- Cache: answers of HTTP 200 in core's `MemoryCache` at its defaults, five minutes, up
  to 8 MiB a body; the login is never cached, and a download streamed to disk never
  touches the cache.
- The nightly `live.yml` (02:10 UTC, and on dispatch) passes the org secrets
  `FAOSTAT_USERNAME` and `FAOSTAT_PASSWORD` to its `uv run pytest -m live` step only. A
  run is 21 tests and sends nine keyed requests (one login; five `get_data` requests,
  one per domain, area 231 in 2020, five rows each; one `groupsanddomains`; one
  `getCodeList`, `codes/element/QCL`, compared with the packaged table; one
  `get_series` data request) and three without the account (the reachability check, the
  bulk catalogue, and MDDW's 12 KB ZIP, read by `parse_bulk_csv` as the live parser
  test); `tests/test_live.py` counts them.
- The release's live evidence: `live.yml` dispatched on `main` (2d4392b) at 2026-10-29
  08:17:35Z, completed with success at 08:18:08Z (the job at 08:18:07Z), 21 passed, 192
  deselected in 19.73 s,
  https://github.com/xippios/sdk-faostat/actions/runs/40841092969: 9 keyed calls and 3
  without the account. It also proved that the two org secrets reach the pytest step (G5
  third round, question 18). This release PR ran no live test.
- The package's keyed-call ledger on the FAO account closes at 118, each count as the
  log and the PRs' bodies give it:

| Step | GitHub | Keyed | Without the account |
| --- | --- | --- | --- |
| Step 0, the login and paging check | | 41 (5 logins, 36 GETs) | status probes, not counted |
| PR 1, the scaffold | #1 | none | none |
| PR 2, the snapshot | #2 | 10 | 48 |
| PR 4, the login client, `get_data`, `list_domains` | #3 | 20 | 5 |
| PR 6, the packaged tables | #4 | 29 | 1 |
| PR 7, `get_series` | #5 | 9 | 1 |
| PR 8, the bulk tasks | #6 | none | 5 |
| The release's dispatch of `live.yml` | | 9 | 3 |
| PR 11, this release PR | | none | none |
| Total | | 118 | 63 |

Step 0 spent 41 against the briefing's about six, since the first twenty queries
answered no rows until the two element code systems were found; Johannes accepted it at
G5 question 7, and row 254 asks for a rule.

## Decisions, by date

2026-10-28

- G1, Johannes (the briefing's "Named at G1"): core 0.3.0 from PyPI outright and
  template v0.3.0, so PRs 3, 5 and 9 fall away; the secret names `FAOSTAT_USERNAME` and
  `FAOSTAT_PASSWORD`; the login and paging check at step 0 with his account (D65, D97).

2026-10-29

- 05:12, step 0: 41 keyed calls; the login's Cognito answer (`ExpiresIn` 3600,
  `TokenType` Bearer); the element codes a query filters by differ from those the
  answer prints; the data endpoint's paging, options and refusals; the bulk catalogue's
  69 datasets.
- 05:22, G5 first round, Johannes: Q1 one login per process, again on a 401 or 403 or at
  expiry, at most one refresh per call (row 252); Q2 `get_data` unpaged by default,
  `page_size` and `page_number` passed through, `meta.total` `None`; Q3 packaged tables
  per domain from `codes/{dimension}/{domain}`, the three list tasks with `search` and
  `MCP_CAPS`, the element tables holding the filter codes; Q4 `list_bulk_datasets`,
  `download_dataset` in `BULK_TASKS`, `parse_bulk_csv`, `has_files=true`; Q5 QCL, TCL,
  FBS, PP and RL; Q6 30 a minute, burst 1, self-imposed; Q7 step 0's 41 accepted, the
  recordings and one live run per code PR, at most four keyed PRs a day, the overrun a
  gap row (254); Q8 the account login stands, the guest-token path noted and not used;
  Q9 a value a `Decimal` where its text is a number, else the text, `None` for null; Q10
  filter codes in, the answer's `Element Code` out as printed, nothing translated; Q11
  `classify` maps the recorded 500s (no filter `InvalidRequestError`, an unknown domain
  `NotFoundError`), an all-`None` filter set refused before sending, an empty answer
  returned as such; Q12 the snapshot's API reference is FAO's OpenAPI document and its
  ReDoc page, with the terms page, the catalogue and recorded samples.
- 05:47, G4: Johannes ran `new-source.sh` from his terminal (the repository, the `pypi`
  environment) and set `GATES_CALLER=1`, the PyPI pending publisher and the two org
  secrets.
- 06:03, the session, on PR 1's review: the scaffold's key sentences corrected in PR 2;
  rows 258 and 259 filed, row 255 corrected.
- 06:19, the session: FETCHED.md's two S3 ETags as audited baseline entries, class
  `human` (row 144, as sdk-comtrade did).
- 07:51, G5 second round, Johannes: Q13 the bulk model `BulkRecord`, mirroring the
  normalized CSV, `DataRecord` staying the API's; Q14 the CSV read lazily from the ZIP
  member with the standard library (row 125); Q15 `get_series` sends the year list
  `since..until`, no year filter when both are `None`, one alone refused; Q16 the budget
  as planned, PR 6 bringing the refusal of a code a packaged table lacks
  (`UnknownCode`).
- 08:06, the session, on PR 4's review: `area_code` and `item_code` optional, a renamed
  code column kept in `columns`, proven by recorded answers to `area_cs=M49` and to
  `area_cs=FAO` with `item_cs=FAO`; a failed login mapped by the taxonomy; `LoginAuth`
  reads only the login's answer.
- 08:20, PR 6: the code check for the FAO coding system only (row 278).
- 08:31, PR 7: a year past the domain's last has no row (ADR-0022 decision 6 governs
  one call per period, not a one-request series); `since` after `until` refused
  (ADR-0007).
- 09:01, PR 8: the wrapper `datasets_e`, named by conventions 1.22 §2's path rule;
  `list_bulk_datasets` a cap of its own (ADR-0016); rows 124 and 271 extended.
- 09:03, G5 third round, Johannes: Q17 no reference refresh before the release: the
  tables fetched on 2026-10-29 at 07:06Z, the release's own day, ship, which meets D15;
  Q18 the release's live evidence is one dispatch of `live.yml` on `main` after PR 8
  merged, which also proves the two org secrets reach the pytest step.
- 09:18, the dispatch's result, above.

## Next

- The reference refresh before the next release (`/refresh-reference-data`, one login
  and fifteen `getCodeList` requests, 16 keyed calls), a PR of its own only when a table
  changed (the briefing's PR 10).
- 0.2.0 might hold: `get_top_producers`, out of 0.1.0 by the briefing; counts through
  `no_records=true`, which answers `[{"NoRecords": N}]` only (FETCHED.md), for a query's
  size before its rows are fetched; more domains' tables, by `params.DOMAINS` and a
  refresh; the M49 filter form, settled by a probe before any code depends on it.
- Row 252's helper in core once a second login-keyed source files; the package then
  drops its own `LoginAuth` in the adoption PR.
- A core minor or template release arrives through `/adopt-release`, in one adoption PR
  before the next release; `live.yml` is hand-written (row 255), so an update that
  touches it is class `human`.
- The gates' `family-review` job was skipped on PR 1 for want of the org secret's access
  (log 06:03; row 258); check whether it reaches this repository before reading anything
  into its result.

## Queue rows this package filed or extended

Titles as `python3 scripts/coord.py queue show N` gives them; all open as of
2026-10-29. A row's "PR N" is the briefing's package number, as above.

Filed:

| Row | Repository | Title |
| --- | --- | --- |
| 252 | sdk-core | login-and-refresh httpx.Auth for a bearer token from a username-and-password login (sdk-faostat) |
| 254 | sdk-core | gap: a session's step-0 probe budget when its first design assumption fails (sdk-faostat spent 41 keyed calls against about six) |
| 255 | sdk-template | gap: the rendered secrecy rule and the key wording name an _API_KEY variable only; a login-keyed source (FAOSTAT_USERNAME, FAOSTAT_PASSWORD) is not covered |
| 258 | sdk-template | new-source.sh's human steps name neither GATES_CALLER=1 nor the new repository's access to the family-review org secret; the scaffold's CLAUDE.md Layout line predates conventions 1.22 |
| 259 | sdk-gates | gap: merge-class rule 5 fires on a scaffold PR (release None -> 0.1.0), a noisy reason beside rule 1 |
| 263 | sdk-core | gap: a release identifier that is a date only (FAOSTAT's date_update) goes to vintage; published_at stays None |
| 271 | sdk-core | gap: CloudFront's x-amz-cf-id response header in every recorded fixture trips detect-secrets; sdk-faostat baselines 11 entries (PR 4) |
| 277 | sdk-core | gap: the recorder's Scrub is given before the request, so a secret known only from the answer (a login's tokens) cannot be named; sdk-faostat writes the login fixture through client.request and write_fixture |
| 278 | sdk-core | gap: a code check against a packaged list when the query names another coding system (FAOSTAT's area_cs/item_cs: the tables hold FAO codes) |

Rows 252, 255 and 271 were extended by later PRs of the package: 252 with the helper's
shape as PR 4 carries it and that PR's review points, 255 with `live.yml`, which the
template cannot render for a login, 271 with S3's `x-amz-version-id` and the count of
twenty header entries.

Extended:

| Row | Repository | Title | Extended with |
| --- | --- | --- | --- |
| 72 | sdk-core | gap: where a probe-backed list of how the live API deviates from its snapshot lives (conventions §3, ADR-0003; from the sdk-usda-esmis snapshot review) | PR 2: the observed list hand-written in `scripts/refresh_upstream.py` and printed into FETCHED.md's capture section, an interim |
| 90 | sdk-core | gap: a task that composes another task of the same package (eurostat slices call get_data async); conventions §2 says tasks compose endpoint wrappers (from sdk-eurostat PR 7) | PR 7: the second consumer, `get_series` over `get_data_async` |
| 124 | sdk-template | the secret scan flags a recorder body_base64 line as a high-entropy string: every binary fixture of ADR-0019 trips detect-secrets (from sdk-eurostat PR 8) | PR 8: MDDW's recorded ZIP, one more audited entry |
| 125 | sdk-core | decode_csv over an open text stream, or opening a gzip path itself (from sdk-eurostat PR 8) | PR 8: the second carrier, `parse/bulk_csv.py` reading a ZIP member as a stream |
| 144 | sdk-template | the rendered .secrets.baseline has empty results, so a source whose docs/upstream snapshot carries high-entropy strings is class human on every template update (from sdk-comtrade PR 1) | PR 2: FETCHED.md's quoted S3 ETags |
| 167 | sdk-template | refresh_upstream.py skeleton limits met by the sdk-usda-wasde snapshot (six points, from PR 2) | PR 2: (f) `html.parser` as declaring no converter; (e) confirmed, the terms page's HTML re-rendered with its Markdown unchanged |
