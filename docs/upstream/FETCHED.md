# Upstream documentation snapshot — FAOSTAT

Source of truth for every endpoint wrapper (ADR-0003). Files in this directory are
fetched from https://www.fao.org/faostat/en/docs/redoc-static.html by `/refresh-upstream`, never edited by hand, and
refreshed deliberately by PR so that changes show up as diffs. Once
`scripts/refresh_upstream.py` is filled, it writes them and regenerates this file whole.

## Attribution

(The copyright line as the documentation states it, e.g. `© 2026 Example Ltd.`, or
"none stated"; where `scripts/refresh_upstream.py` captures the documentation, it checks
this on every run and stops when the documentation starts to state one.) The
documentation's text is reproduced here as this package's reference (ADR-0003); the
publisher's objection is met by replacing it with a summary that keeps the names and
semantics the wrappers rely on.

## Files and pages

`Fetched` is the UTC time of the run in ISO 8601 with an explicit `Z`
(`2026-10-24T09:15:00Z`). Bytes and sha256 are those of the body as fetched, ETag as
sent and Last-Modified in UTC, `-` where none is sent. A table with merged cells
(`rowspan`, `colspan`) or a table nested in it, which a Markdown pipe table cannot hold,
is kept as its HTML in the Markdown file, and its row's note says so. The capture script
writes three kinds of row, here with example values:

- a file, kept verbatim or converted: its path and the page it was made from;
- a page recorded without a file, a 403 or a 404 or a page without documentation text:
  `(no file)` and its status, and no size, sha256 or validators where its body changes
  on every request;
- an excerpt, this source's part of a shared document (conventions §3): its path, with
  the whole document's size and sha256.

```text
| openapi/openapi.json | https://api.example.org/openapi.json | 2026-10-24T09:15:00Z | 200 | 48213 | 3f2a…c9e1 | "a1b2" | 2026-10-20T08:00:00Z | SPEC_URL, verbatim |
| (no file) | https://api.example.org/legal | 2026-10-24T09:15:00Z | 403 | - | - | - | - | the body changes on every request, so no size, sha256 or validators; 403 at the CDN edge |
| openapi/part.json | https://api.example.org/shared.json | 2026-10-24T09:15:00Z | 200 | 912044 | 7d0c…5a2f | - | - | excerpt of a shared document; Bytes and sha256 are the whole document's |
```

| File | URL | Fetched | HTTP | Bytes | sha256 | ETag | Last-Modified | Note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| (nothing fetched yet) | https://www.fao.org/faostat/en/docs/redoc-static.html | | | | | | | |
