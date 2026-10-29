# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Refresh the upstream documentation snapshot in ``docs/upstream/`` (``/refresh-upstream``).

The template's skeleton of a capture script. A source fills ``PAGES``, ``SPEC_URL`` where
its documentation names a machine-readable API document, ``ATTRIBUTION``, ``CAPTURE`` and,
where a page is not kept as fetched, ``reduce``, and rewrites this paragraph to say what it
captures; the rest is the family's capture frame. Until ``PAGES`` or ``SPEC_URL`` is
filled, the script refuses to run.

Everything is fetched before anything is written, one request at a time after a pause,
each URL retried at most once after a network error or a 5xx. Each page with a file is
written under ``docs/upstream/``, and ``FETCHED.md`` is regenerated whole: the UTC time of
the run with an explicit ``Z``, the attribution, and one row per page with its HTTP
status, the size and sha256 of the body as fetched, and its ETag and Last-Modified where
sent. A page recorded without a file (a 403 or a 404, a page without documentation text)
has a row of its own, and a file cut from a shared document keeps the whole document's
size and sha256 in its row (conventions §3). Files the run does not produce are removed
from the subdirectories it writes to; nothing else under ``docs/upstream/`` is touched.
Every run stops, before writing, when a page states a copyright, a licence or terms of use
that ``ATTRIBUTION`` does not record. No key is needed or read. Run from the repository
root::

    uv run scripts/refresh_upstream.py            # fetch, then write the snapshot
    uv run scripts/refresh_upstream.py --check    # fetch and compare; write nothing

``--check`` exits 1 when the snapshot differs from what upstream serves now, ``Fetched``
aside. Where the documentation is HTML, ``reduce`` converts it to Markdown with
``markdownify``, the one converter a capture script may declare: in the ``# /// script``
block above, ``dependencies = ["markdownify==X.Y.Z"]``, and at the same pin in the dev
group of ``pyproject.toml``, so that ``mypy --strict`` reads its types.
"""

import argparse
import hashlib
import html
import http.client
import json
import re
import textwrap
import time
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import IO, Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "docs/upstream"
COMMAND = "uv run scripts/refresh_upstream.py"
SOURCE_NAME = "FAOSTAT"
DOCS_URL = "https://www.fao.org/faostat/en/docs/redoc-static.html"
"""Where the documentation lives: ``upstream_docs_url`` in ``.copier-answers.yml``."""
USER_AGENT = "xippios-faostat refresh_upstream (+https://github.com/xippios)"
TIMEOUT = 60.0
PAUSE = 2.0
"""Seconds before every request; requests never run in parallel."""
RETRY_PAUSE = 10.0
"""Seconds before the one retry after a network error or a 5xx."""


@dataclass(frozen=True)
class Page:
    """One page the snapshot records, and the file it is kept as, if any.

    Attributes:
        url: Where the page is fetched from.
        file: Its path under ``docs/upstream/`` (``pages/guide.md``,
            ``openapi/openapi.json``), or ``None`` for a page recorded without a file.
        status: The HTTP status it must answer with: 200, or the 403 or 404 of a page
            recorded by its status.
        note: The row's note in ``FETCHED.md``: how the file was made, or why there is none.
        stable: ``False`` for a body that changes on every request (a per-request
            reference in a refusal page): its row records no size, sha256 or validators.
        excerpt: The file is this source's part of a shared document (conventions §3);
            the row keeps the whole document's size and sha256, and its note says so.
    """

    url: str
    file: str | None = None
    status: int = 200
    note: str = ""
    stable: bool = True
    excerpt: bool = False


PAGES: tuple[Page, ...] = (
    # Page(DOCS_URL, "pages/index.md", note="converted to Markdown"),
    # Page("https://api.example.org/legal", status=403, note="403 at the CDN edge"),
)
"""Every page the snapshot records, in the order of ``FETCHED.md``'s rows."""

SPEC_URL: str | None = None
"""The machine-readable API document (OpenAPI, Swagger) the documentation names, if any.

The convention of ``/refresh-upstream``: a document named inside a page rather than linked
from it (a Swagger UI's configuration) is recorded here once found, and kept verbatim as
``SPEC_FILE`` after ``PAGES``. Where the page's setting must be read on every run, the
source reads it there instead and ``CAPTURE`` says from where.
"""
SPEC_FILE = "openapi/openapi.json"
"""The document's path under ``docs/upstream/``, with the extension it is served with."""

ATTRIBUTION: tuple[str, ...] = ()
"""Every copyright line, licence or terms of use the documentation states, as printed.

Empty: it states none. ``FETCHED.md`` quotes them under Attribution, and every run stops
when a page states one that is not here.
"""

CAPTURE = ""
"""``FETCHED.md``'s "How this is captured": what is converted, cut or left out, and why."""

_STATEMENT = re.compile(
    r"\N{COPYRIGHT SIGN}|copyright|licen[cs]e|terms of (?:use|service)|public domain",
    re.IGNORECASE,
)
_FETCHED = re.compile(r"\| (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) \|")


@dataclass(frozen=True)
class Response:
    """One GET as served: status, body and validators, and the redirects on the way."""

    url: str
    status: int
    body: bytes
    etag: str | None
    last_modified: str | None
    redirects: tuple[tuple[int, str], ...]


@dataclass(frozen=True)
class Row:
    """One row of ``FETCHED.md``: the page, its response and its file's content, if any."""

    page: Page
    response: Response
    content: bytes | None


class _RetryableError(Exception):
    """A network error or a 5xx: worth one more attempt."""


class _RecordRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects as urllib does, remembering each status and target."""

    def __init__(self) -> None:
        super().__init__()
        self.hops: list[tuple[int, str]] = []

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        """Record the hop, then let urllib build the follow-up request."""
        self.hops.append((code, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _log(message: str) -> None:
    print(message, flush=True)  # noqa: T201


def _get(url: str, expect: int) -> Response:
    redirects = _RecordRedirects()
    opener = urllib.request.build_opener(redirects)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            body: bytes = response.read()
            status: int = response.status
            headers = response.headers
    except urllib.error.HTTPError as error:
        if error.code >= 500:
            raise _RetryableError(f"HTTP {error.code} {error.reason}") from None
        if error.code != expect:
            raise SystemExit(f"GET {url}: HTTP {error.code} {error.reason}") from None
        body, status, headers = error.read(), error.code, error.headers
    except (http.client.HTTPException, OSError) as error:  # URLError is an OSError
        raise _RetryableError(str(error)) from None
    if status != expect:
        raise SystemExit(f"GET {url}: expected HTTP {expect}, got {status}")
    encoding = headers.get("Content-Encoding", "identity").strip().lower()
    if encoding != "identity":
        raise SystemExit(f"GET {url}: unexpected Content-Encoding {encoding!r}")
    return Response(
        url,
        status,
        body,
        headers.get("ETag"),
        headers.get("Last-Modified"),
        tuple(redirects.hops),
    )


def fetch(url: str, expect: int = 200) -> Response:
    """GET ``url`` after a polite pause; retry once on a network error or a 5xx."""
    time.sleep(PAUSE)
    try:
        response = _get(url, expect)
    except _RetryableError as error:
        _log(f"  {url}: {error}; retrying once in {RETRY_PAUSE:g} s")
        time.sleep(RETRY_PAUSE)
        try:
            response = _get(url, expect)
        except _RetryableError as error:
            raise SystemExit(f"GET {url}: {error} (after one retry)") from None
    digest = hashlib.sha256(response.body).hexdigest()
    hops = "".join(f", {code} to {target}" for code, target in response.redirects)
    _log(
        f"  {url}: HTTP {response.status}{hops}, {len(response.body)} bytes, sha256 {digest}, "
        f"Last-Modified {response.last_modified or '-'}, ETag {response.etag or '-'}"
    )
    return response


def changed(url: str, what: str) -> SystemExit:
    """The error that stops the run on a page the script does not recognise."""
    return SystemExit(
        f"{url} changed: {what}.\nLook at the page by hand and update "
        "scripts/refresh_upstream.py. Nothing was written."
    )


def decode(response: Response) -> str:
    """The body as UTF-8 text; a body that is not UTF-8 stops the run."""
    try:
        return response.body.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise changed(response.url, f"the body is not UTF-8 ({error})") from None


def check_attribution(page: Page, response: Response) -> None:
    """Stop when the page states a copyright, licence or terms that ``ATTRIBUTION`` lacks.

    The check reads the whole body with its entities decoded, so a footer that the Markdown
    drops counts too; a source whose markup carries one of the words without stating
    anything (a ``license`` class) checks the text its ``reduce`` keeps instead.
    """
    body = html.unescape(response.body.decode("utf-8", "replace"))
    for statement in ATTRIBUTION:
        body = body.replace(statement, "")
    match = _STATEMENT.search(body)
    if match:
        around = " ".join(body[max(match.start() - 60, 0) : match.end() + 60].split())
        raise SystemExit(
            f"GET {page.url}: the page states {match.group(0)!r} ({around!r}), a copyright, "
            "licence or terms of use that ATTRIBUTION does not record.\nRead it by hand, "
            "record it in ATTRIBUTION and update scripts/refresh_upstream.py. Nothing was "
            "written."
        )


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    counts = Counter(key for key, _ in pairs)
    duplicates = sorted(key for key, count in counts.items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate keys {duplicates}")
    return dict(pairs)


def dump_json(value: Any, indent: int = 2) -> bytes:
    """``value`` as JSON in the order it holds, ``ensure_ascii=False``, with a final newline."""
    return (json.dumps(value, indent=indent, ensure_ascii=False) + "\n").encode("utf-8")


def load_json(response: Response, indent: int = 2) -> Any:
    """The JSON document of ``response``, once re-serialising it reproduces the fetched text.

    A source that keeps a JSON document cut to its part writes the part with ``dump_json``;
    this check makes sure that the whole document, written the same way, is the fetched
    text up to line endings, so the part is an excerpt of upstream's text. A duplicate key,
    which ``json.loads`` would drop silently, stops the run too.
    """
    try:
        document = json.loads(response.body, object_pairs_hook=_no_duplicates)
    except ValueError as error:
        raise SystemExit(f"GET {response.url}: not usable JSON ({error})") from None
    fetched = response.body.replace(b"\r\n", b"\n").rstrip(b"\n")
    if dump_json(document, indent).rstrip(b"\n") != fetched:
        raise SystemExit(
            f"GET {response.url}: re-serialised with json.dumps(indent={indent}, "
            "ensure_ascii=False), the document no longer reproduces the fetched text up to "
            "line endings, so a part cut from it would not be an excerpt of upstream's text."
            "\nLook at the document by hand and update scripts/refresh_upstream.py. Nothing "
            "was written."
        )
    return document


def reduce(page: Page, response: Response) -> bytes:
    """The content ``page``'s file is written with: the body as fetched, by default.

    A source fills this where a page is not kept as fetched, and stops the run with
    ``changed`` on a page it does not recognise, before anything is written:

    - an HTML page becomes Markdown, its headings, tables and parameter lists kept, its
      navigation dropped and a table with merged cells kept as HTML (conventions §3)::

          from markdownify import markdownify  # the one converter (module docstring)

          return markdownify(decode(response), heading_style="ATX").encode("utf-8")

    - a shared document is cut to this source's part, ``load_json`` then ``dump_json``,
      and its page marked ``excerpt=True``.
    """
    return response.body


def capture(page: Page) -> Row:
    """Fetch ``page``, check its attribution and make its file's content; write nothing."""
    response = fetch(page.url, page.status)
    check_attribution(page, response)
    return Row(page, response, reduce(page, response) if page.file else None)


def _iso_http_date(value: str | None) -> str:
    if value is None:
        return "-"
    return parsedate_to_datetime(value).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cell(value: str) -> str:
    return value.replace("|", r"\|")


def _paragraph(*sentences: str) -> list[str]:
    text = " ".join(sentences)
    wrapped = textwrap.fill(text, width=88, break_long_words=False, break_on_hyphens=False)
    return [*wrapped.splitlines(), ""]


def _note(row: Row) -> str:
    parts = [f"redirected ({code}) to {target}" for code, target in row.response.redirects]
    if row.page.excerpt:
        parts.append("excerpt of a shared document; Bytes and sha256 are the whole document's")
    if not row.page.stable:
        parts.append("the body changes on every request, so no size, sha256 or validators")
    if row.page.note:
        parts.append(row.page.note)
    return "; ".join(parts) or "-"


def render_fetched(rows: Sequence[Row], fetched: str) -> str:
    """The whole of ``FETCHED.md``, ``fetched`` being the UTC time the run started."""
    if ATTRIBUTION:
        stated = "The documentation states " + "; ".join(f"`{s}`" for s in ATTRIBUTION) + "."
    else:
        stated = "None stated: no page this script reads states a copyright line, a licence"
        stated += " or terms of use."
    lines = [
        f"# Upstream documentation snapshot \N{EM DASH} {SOURCE_NAME}",
        "",
        *_paragraph(
            "Source of truth for every endpoint wrapper (ADR-0003). The files in this",
            "directory are written by `scripts/refresh_upstream.py` (`/refresh-upstream`)",
            "from the pages in the table below and refreshed deliberately by PR, so that",
            "changes show up as diffs. This file is generated by the same script; nothing",
            "here is edited by hand.",
        ),
        "## Attribution",
        "",
        *_paragraph(
            stated,
            "The script stops when a page it reads states one it does not record. The",
            "documentation's text is reproduced here as this package's reference",
            "(ADR-0003); the publisher's objection is met by replacing it with a summary",
            "that keeps the names and semantics the wrappers rely on.",
        ),
        "## How this is captured",
        "",
        *(_paragraph(CAPTURE) if CAPTURE else []),
        *_paragraph(
            "Fetched is the UTC time the run started, in ISO 8601 with an explicit Z, the",
            "same for every row. Bytes and sha256 are those of the body as fetched: a",
            "converted page's row holds the HTML page's, an excerpt's the whole document's.",
            "Last-Modified is the HTTP header in UTC, ETag as sent. A page recorded without",
            "a file is `(no file)`, and a body that changes on every request records no",
            f"size, sha256 or validators. Requests go one at a time, {PAUSE:g} s apart,",
            f"each retried at most once, identified as `{USER_AGENT}`; no API key is sent",
            "or read.",
        ),
        "## Files and pages",
        "",
        "| File | URL | Fetched | HTTP | Bytes | sha256 | ETag | Last-Modified | Note |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        response, kept = row.response, row.page.stable
        cells = [
            row.page.file or "(no file)",
            response.url,
            fetched,
            str(response.status),
            str(len(response.body)) if kept else "-",
            hashlib.sha256(response.body).hexdigest() if kept else "-",
            (response.etag or "-") if kept else "-",
            _iso_http_date(response.last_modified) if kept else "-",
            _note(row),
        ]
        lines.append("| " + " | ".join(_cell(cell) for cell in cells) + " |")
    lines += ["", f"Regenerate: `{COMMAND}`"]
    return "\n".join(lines) + "\n"


def _files(rows: Sequence[Row]) -> dict[str, bytes]:
    return {row.page.file: row.content for row in rows if row.page.file and row.content is not None}


def _stale(out: Path, files: dict[str, bytes]) -> list[str]:
    """The files under the subdirectories the run writes to that it does not produce."""
    subdirs = sorted({name.split("/", 1)[0] for name in files if "/" in name})
    found = [path for subdir in subdirs for path in sorted((out / subdir).rglob("*"))]
    names = [path.relative_to(out).as_posix() for path in found if path.is_file()]
    return [name for name in names if name not in files]


def write_snapshot(out: Path, rows: Sequence[Row], fetched_md: str) -> None:
    """Write every file as ``reduce`` made it, then ``FETCHED.md``; remove the stale files."""
    if out.exists() and any(out.iterdir()) and not (out / "FETCHED.md").is_file():
        raise SystemExit(f"{out} is neither empty nor a snapshot (no FETCHED.md); not writing")
    files = _files(rows)
    for name in _stale(out, files):
        (out / name).unlink()
        _log(f"  removed {name}: no longer produced")
    for name, content in files.items():
        (out / name).parent.mkdir(parents=True, exist_ok=True)
        (out / name).write_bytes(content)
    (out / "FETCHED.md").write_bytes(fetched_md.encode("utf-8"))


def compare(out: Path, rows: Sequence[Row]) -> list[str]:
    """The snapshot's files that differ from this run's, ``FETCHED.md``'s ``Fetched`` aside."""
    files = _files(rows)
    differ = [
        name
        for name, content in files.items()
        if not (out / name).is_file() or (out / name).read_bytes() != content
    ]
    differ += [f"{name} (no longer produced)" for name in _stale(out, files)]
    current = out / "FETCHED.md"
    old = current.read_bytes().decode("utf-8") if current.is_file() else ""
    match = _FETCHED.search(old, max(old.find("| --- |"), 0))
    if not match or render_fetched(rows, match.group(1)) != old:
        differ.append("FETCHED.md")
    return differ


def main(argv: Sequence[str] | None = None) -> int:
    """Fetch every page, then write the snapshot, or with ``--check`` compare it."""
    parser = argparse.ArgumentParser(description="Refresh docs/upstream/ from upstream.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="snapshot directory")
    parser.add_argument(
        "--check", action="store_true", help="fetch and compare with the snapshot; write nothing"
    )
    args = parser.parse_args(argv)
    out: Path = args.out
    pages = list(PAGES)
    if SPEC_URL:
        pages.append(Page(SPEC_URL, SPEC_FILE, note="SPEC_URL, verbatim"))
    if not pages:
        raise SystemExit(
            "Nothing to fetch: fill PAGES, and SPEC_URL where the documentation names an "
            "API document, as /refresh-upstream says."
        )
    fetched = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    _log(f"Fetching {len(pages)} pages; nothing is written before the last")
    rows = [capture(page) for page in pages]
    if args.check:
        differ = compare(out, rows)
        for name in differ:
            _log(f"  differs: {name}")
        _log(
            f"{len(differ)} of the snapshot's files differ from upstream; run without --check"
            if differ
            else "The snapshot is current: upstream serves what it records."
        )
        return 1 if differ else 0
    write_snapshot(out, rows, render_fetched(rows, fetched))
    written = sum(1 for row in rows if row.content is not None)
    _log(f"Wrote {written} files and FETCHED.md under {out} (Fetched {fetched})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
