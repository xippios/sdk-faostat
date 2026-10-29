# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Refresh the upstream documentation snapshot in ``docs/upstream/`` (``/refresh-upstream``).

FAOSTAT documents its API in an OpenAPI document, ``SPEC_URL``, which the ReDoc page
``DOCS_URL`` beside it renders from a copy of its own. The script writes:

- ``openapi/faostat_openapi.yaml``: the OpenAPI document, byte for byte;
- ``pages/db-terms-of-use.md``: the FAO Statistical Database Terms of Use, which license
  FAOSTAT's data, converted to Markdown with the standard library's ``html.parser``;
- ``bulk/datasets_E.json``: the bulk downloads' catalogue, open, byte for byte;
- ``samples/<name>.json``: four answers of the API, byte for byte, structural samples
  fetched with the FAO account's bearer token (test fixtures are recorded separately,
  never here);
- ``FETCHED.md``: regenerated whole, one row per file and per page recorded without a
  file, the ReDoc page and the portal's application shell.

Everything is fetched before anything is written, one request at a time after a pause,
and every page is checked: a page the script does not recognise, or one that states a
copyright, a licence or terms of use that ``ATTRIBUTION`` does not record, stops the run.
A keyless request is retried at most once after a network error or a 5xx. The samples
come last: the script logs in once (``auth_login``) with ``FAOSTAT_USERNAME`` and
``FAOSTAT_PASSWORD`` from the environment, after every keyless page, and sends the access
token on the four sample requests only, which are never retried and never follow a
redirect. No other request sends a credential. Neither the credentials nor the token is
printed, logged, written or returned; a failed login prints its status only. Files under
the subdirectories the run writes to that it does not produce are removed; nothing else
under ``docs/upstream/`` is touched. Run from the repository root, the two variables set
(the family runs it through ``direnv exec``, which sets them for the script's process)::

    uv run scripts/refresh_upstream.py              # fetch, then write the snapshot
    uv run scripts/refresh_upstream.py --check      # fetch and compare; write nothing
    uv run scripts/refresh_upstream.py --keyless    # the keyless pages only; no login

``--check`` exits 1 when the snapshot differs from what upstream serves now, ``Fetched``
aside, a sample's ``metadata.processing_time`` aside, which changes on every request, and
a converted page's HTML aside while its Markdown is unchanged (a CMS re-render changes the
HTML's sha256 and validators, not the text): its row keeps the recorded ones. ``--keyless``
fetches and checks the keyless pages and compares their files and their rows with the
snapshot, writing nothing and logging in nowhere: a free trial before a run that spends
keyed calls (one login and four requests).
"""

import argparse
import hashlib
import html
import http.client
import json
import os
import re
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import IO, Any
from urllib.parse import urljoin

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
"""Seconds before the one retry of a keyless request after a network error or a 5xx."""

SPEC_URL = "https://www.fao.org/faostat/en/docs/faostat_openapi.yaml"
"""The OpenAPI document, served beside the ReDoc page; no page links it (``CAPTURE``)."""
SPEC_FILE = "openapi/faostat_openapi.yaml"
API_BASE = "https://faostatservices.fao.org/api/v1"
"""The document's one server, and the host the bearer token is sent to, and only it."""
LOGIN_URL = f"{API_BASE}/auth/login"
"""``auth_login`` of the document: form fields ``username`` and ``password``."""
LOGIN_ENVS = ("FAOSTAT_USERNAME", "FAOSTAT_PASSWORD")
"""The variables the login reads by name, the account's user name (its e-mail) first."""
USERNAME_ENV, SECRET_ENV = LOGIN_ENVS
PORTAL_URL = "https://www.fao.org/faostat/en/"
PORTAL_LINK = "https://www.fao.org/faostat/en/#developer-portal"
"""The developer portal's address; a fragment is never sent, so ``PORTAL_URL`` is fetched."""
TERMS_URL = "https://www.fao.org/contact-us/terms/db-terms-of-use/en/"
TERMS_FILE = "pages/db-terms-of-use.md"
REUSE_URL = "https://www.fao.org/contact-us/terms/en/"
"""FAO's Terms and Conditions regarding the Reuse of Web content, which the footer's
copyright line links to and the database terms incorporate; cited, not fetched."""
BULK_BASE = "https://bulks-faostat.fao.org/production"
CATALOGUE_URL = f"{BULK_BASE}/datasets_E.json"
CATALOGUE_FILE = "bulk/datasets_E.json"
CATALOGUE_KEYS = (
    "DatasetCode",
    "DatasetName",
    "Topic",
    "DatasetDescription",
    "Contact",
    "Email",
    "DateUpdate",
    "CompressionFormat",
    "FileType",
    "FileSize",
    "FileRows",
    "FileLocation",
)
"""The fields of every dataset in the catalogue, in upstream's order."""

REDOC_LABELS = frozenset(
    {
        "API docs by Redocly",
        "Array of",
        "Authorizations:",
        "Collapse all",
        "Content type",
        "Copy",
        "Default:",
        "Download OpenAPI specification",
        "Enum",
        "Example:",
        "Expand all",
        "Request Body schema:",
        "Response samples",
        "Responses",
        "strings",
    }
)
"""ReDoc's own labels, the only text of the ReDoc page that is not the document's."""
DEV_SERVER = {
    "url": "https://api-faostat.dev.fao.org/api/v1",
    "description": (
        "Development server, available for testing purposes only on FAO network. Data might "
        "not be up to date."
    ),
}
"""The server the ReDoc page's copy lists before the document's one, as printed."""
PROD_SERVER = {
    "url": API_BASE,
    "description": "Production server, available on the internet. Data is up to date.",
}
"""The document's one server, as printed."""


@dataclass(frozen=True)
class Sample:
    """One answer of the API the snapshot keeps as a structural sample.

    Attributes:
        file: Its path under ``docs/upstream/``.
        query: The path and query under ``API_BASE``.
        operation: The ``operationId`` the request is an instance of.
        template: That operation's path in the OpenAPI document.
    """

    file: str
    query: str
    operation: str
    template: str


SAMPLES = (
    Sample(
        "samples/data_QCL_231_2510_15_2015-2021.json",
        "/en/data/QCL?area=231&element=2510&item=15&year=2015,2016,2017,2018,2019,2020,2021"
        "&show_codes=true&show_unit=true&show_flags=true&show_notes=true&null_values=false"
        "&output_type=objects",
        "get_data",
        "/{lang}/data/{domain_code}",
    ),
    Sample(
        "samples/dimensions_QCL.json",
        "/en/dimensions/QCL?full=true",
        "get_dimensions",
        "/{lang}/dimensions/{domain_code}/",
    ),
    Sample(
        "samples/codes_element_QCL.json",
        "/en/codes/element/QCL",
        "getCodeList",
        "/{lang}/codes/{dimension_id}/{domain_code}",
    ),
    Sample(
        "samples/groupsanddomains.json",
        "/en/groupsanddomains",
        "get_groupsanddomains",
        "/{lang}/groupsanddomains",
    ),
)
"""The samples, fetched in this order after the login, with the account's bearer token."""

COPYRIGHT = "\N{COPYRIGHT SIGN} FAO 2026"
"""The copyright line of fao.org's footer, on the terms page, as printed."""
TERMS_NAME = "Statistical Database Terms of Use"
"""The terms' name, as the breadcrumb prints it; the heading prints it after ``FAO``."""
LICENCE = (
    "Unless specified otherwise in their metadata or webpage, all datasets disseminated "
    "through FAO corporate statistical databases (see examples in Annex 1) are licensed "
    "under the Creative Commons Attribution-4.0 International licence (CC BY 4.0) available "
    "here as complemented by the Terms of Use outlined below."
)
"""The terms' licence sentence, as printed; Annex 1 lists FAOSTAT."""
CITATION = (
    "FAO. [YYYY (year of last update)]. [Name of database: Name of dataset OR Name of "
    "database]. [Accessed on [DD Month YYYY]]. [URL] Licence: CC-BY-4.0."
)
"""The citation format the terms ask for, as printed inside its quotation marks."""
TERMS_CLAUSES = (
    "They are subject to the Statistical Database terms of use of this agreement "
    "(\N{LEFT DOUBLE QUOTATION MARK}Database terms\N{RIGHT DOUBLE QUOTATION MARK}) and the "
    "Terms and Conditions regarding the Reuse of Web content, which are incorporated herein "
    "by reference.",
    "LICENCES",
    "In other words, when you access, download, or otherwise extract any data or datasets "
    "from these databases, you agree to comply with the terms and conditions of the CC BY 4.0 "
    "licence and all terms specified in the additional terms of use outlined below.",
    "ADDITIONAL TERMS OF USE",
    "The CC BY 4.0 licence specifies that you must give appropriate attribution and credit to "
    "FAO for any work produced using an FAO dataset or when FAO data is re-disseminated.",
    "Any dispute, controversy or claim arising out of or in relation to this licence that "
    "cannot be settled amicably shall be submitted to arbitration in accordance with the "
    "Arbitration Rules of the United Nations Commission on International Trade Law "
    "(UNCITRAL).",
)
"""The terms page's other sentences and headings that name a licence or terms of use."""
ATTRIBUTION: tuple[str, ...] = (COPYRIGHT, TERMS_NAME, LICENCE, CITATION, *TERMS_CLAUSES)
"""Every copyright line, licence or terms of use the pages state, as printed.

``FETCHED.md`` quotes them under Attribution; every run stops when a page states one that
is not here, or when one of them is no longer printed on any page.
"""
INCIDENTAL = (
    "dissemination products available in the public domain or directly provided by member "
    "countries to FAO",
)
"""Text that carries one of the words without stating anything about the snapshot: the
catalogue's description of the census dataset WCAD, which draws on census reports
"available in the public domain"."""

_STATEMENT = re.compile(
    r"\N{COPYRIGHT SIGN}|copyright|licen[cs]e|terms of (?:use|service)|public domain",
    re.IGNORECASE,
)
_FETCHED = re.compile(r"\| (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) \|")
_PROCESSING_TIME = re.compile(rb'"processing_time": ?\d+')
_OPERATION_ID = re.compile(r"^[ \t]+operationId:[ \t]*(\S+)[ \t]*$", re.MULTILINE)
_REDOC_JS = re.compile(
    r'<script src="https://cdn\.redocly\.com/redoc/(v\d+\.\d+\.\d+)/bundles/'
    r'redoc\.standalone\.js"></script>'
)
_REDOC_STATE = "const __redoc_state = "
_REDOC_HYDRATE = "Redoc.hydrate(__redoc_state, container);"
_JSON_TOKEN = re.compile(r'"[^"]*"|\{ \}|\[ \]|true|false|null|-?\d+(?:\.\d+)?|[<>]')
"""A text fragment of a response sample ReDoc draws from the document's schemas."""
_VOID = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}
)
_NO_TEXT = frozenset({"script", "style", "svg", "template", "noscript", "iframe"})
_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_BLOCK = _HEADINGS | {"article", "aside", "blockquote", "br", "div", "footer", "form", "header"}
_BLOCK |= {"li", "main", "nav", "ol", "p", "section", "table", "td", "th", "tr", "ul"}
"""Elements whose text the visible text separates from their neighbours'."""


@dataclass(frozen=True)
class Page:
    """One page the snapshot records, and the file it is kept as, if any.

    Attributes:
        url: Where the page is fetched from.
        file: Its path under ``docs/upstream/``, or ``None`` for a page recorded without
            a file.
        status: The HTTP status it answered with.
        note: The row's note in ``FETCHED.md``: how the file was made, or why there is none.
        stable: ``False`` for a body that changes on every request: its row records no
            size, sha256 or validators.
        excerpt: The file is this source's part of a shared document (conventions §3).
        keyed: Fetched with the account's bearer token; its ``metadata.processing_time``
            changes on every request, which ``--check`` disregards.
    """

    url: str
    file: str | None = None
    status: int = 200
    note: str = ""
    stable: bool = True
    excerpt: bool = False
    keyed: bool = False


@dataclass(frozen=True)
class Response:
    """One request as served: status, body and validators, and the redirects on the way."""

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
    """A network error or a 5xx: worth one more attempt, for a keyless request."""


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


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Follow no redirect, so a request with the token reaches ``API_BASE``'s host only."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        """Refuse the hop; urllib then raises the 3xx as an ``HTTPError``."""
        return None


def _log(message: str) -> None:
    print(message, flush=True)  # noqa: T201


def _get(url: str, expect: int, token: str | None) -> Response:
    headers = {"User-Agent": USER_AGENT}
    if token is not None:
        if not url.startswith(f"{API_BASE}/"):
            raise SystemExit(f"GET {url}: the token goes to {API_BASE}/ only. Nothing was written.")
        headers["Accept"] = "application/json"
        headers["Authorization"] = f"Bearer {token}"
    redirects = _RecordRedirects()
    opener = urllib.request.build_opener(redirects if token is None else _NoRedirects())
    request = urllib.request.Request(url, headers=headers)
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            body: bytes = response.read()
            status: int = response.status
            received = response.headers
    except urllib.error.HTTPError as error:
        if error.code >= 500:
            raise _RetryableError(f"HTTP {error.code} {error.reason}") from None
        if error.code != expect:
            raise SystemExit(f"GET {url}: HTTP {error.code} {error.reason}") from None
        body, status, received = error.read(), error.code, error.headers
    except (http.client.HTTPException, OSError) as error:  # URLError is an OSError
        raise _RetryableError(str(error)) from None
    if status != expect:
        raise SystemExit(f"GET {url}: expected HTTP {expect}, got {status}")
    encoding = received.get("Content-Encoding", "identity").strip().lower()
    if encoding != "identity":
        raise SystemExit(f"GET {url}: unexpected Content-Encoding {encoding!r}")
    return Response(
        url,
        status,
        body,
        received.get("ETag"),
        received.get("Last-Modified"),
        tuple(redirects.hops),
    )


def fetch(url: str, expect: int = 200, *, token: str | None = None) -> Response:
    """GET ``url`` after a polite pause; a keyless request is retried once on a 5xx.

    A request with ``token`` sends it as a bearer token, follows no redirect and is never
    retried, so a 5xx or a network error costs one keyed call and stops the run.
    """
    time.sleep(PAUSE)
    try:
        response = _get(url, expect, token)
    except _RetryableError as error:
        if token is not None:
            raise SystemExit(
                f"GET {url}: {error}; a keyed request is not retried. Nothing was written."
            ) from None
        _log(f"  {url}: {error}; retrying once in {RETRY_PAUSE:g} s")
        time.sleep(RETRY_PAUSE)
        try:
            response = _get(url, expect, token)
        except _RetryableError as error:
            raise SystemExit(f"GET {url}: {error} (after one retry)") from None
    digest = hashlib.sha256(response.body).hexdigest()
    hops = "".join(f", {code} to {target}" for code, target in response.redirects)
    _log(
        f"  {url}: HTTP {response.status}{hops}, {len(response.body)} bytes, sha256 {digest}, "
        f"Last-Modified {response.last_modified or '-'}, ETag {response.etag or '-'}"
    )
    return response


def _require_credentials() -> None:
    """Stop, before anything is fetched, when a credential variable is unset (by name)."""
    for name in (USERNAME_ENV, SECRET_ENV):
        if not os.environ.get(name):
            raise SystemExit(
                f"{name} is not set. The samples need the FAO account's login; set "
                f"{USERNAME_ENV} and {SECRET_ENV}, or run with --keyless. Nothing was "
                "fetched or written."
            )


def login() -> str:
    """Log in once (``auth_login``) and return the access token; print nothing of either.

    The credentials are read here, from the environment, and go into the form body only;
    a failed login prints its status and nothing of the answer.
    """
    form = urllib.parse.urlencode(
        {"username": os.environ.get(USERNAME_ENV, ""), "password": os.environ.get(SECRET_ENV, "")}
    ).encode("ascii")
    request = urllib.request.Request(
        LOGIN_URL,
        data=form,
        method="POST",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    time.sleep(PAUSE)
    try:
        with urllib.request.build_opener(_NoRedirects()).open(request, timeout=TIMEOUT) as answer:
            status: int = answer.status
            body: bytes = answer.read()
    except urllib.error.HTTPError as error:
        raise SystemExit(
            f"POST {LOGIN_URL}: HTTP {error.code}; the answer is not shown. Nothing was written."
        ) from None
    except (http.client.HTTPException, OSError):
        raise SystemExit(
            f"POST {LOGIN_URL}: no answer (a network error); not retried. Nothing was written."
        ) from None
    if status != 200:
        raise SystemExit(f"POST {LOGIN_URL}: HTTP {status}; the answer is not shown.")
    try:
        result = json.loads(body).get("AuthenticationResult")
        token = result.get("AccessToken")
        kind = result.get("TokenType")
    except (ValueError, AttributeError):
        raise SystemExit(
            f"POST {LOGIN_URL}: HTTP 200, but not the documented `Auth` answer; the answer is "
            "not shown. Nothing was written."
        ) from None
    if not isinstance(token, str) or not token or kind != "Bearer":
        raise SystemExit(
            f"POST {LOGIN_URL}: HTTP 200, but no Bearer AccessToken in AuthenticationResult; "
            "the answer is not shown. Nothing was written."
        )
    _log(f"  {LOGIN_URL}: HTTP 200, logged in (the answer and its tokens are not shown)")
    return token


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


def check_attribution(url: str, text: str) -> set[str]:
    """Stop when ``text`` states a copyright, licence or terms that ``ATTRIBUTION`` lacks.

    The recorded statements and the ``INCIDENTAL`` text are removed first; the statements
    found are returned, so that the run can stop when one is no longer printed anywhere.
    A JSON or YAML body is checked whole, an HTML page as its caller says: the whole body
    with its entities decoded, or the visible text of a page whose sentences run across
    inline elements (the terms page).
    """
    found = {statement for statement in ATTRIBUTION if statement in text}
    for statement in (*ATTRIBUTION, *INCIDENTAL):
        text = text.replace(statement, "")
    match = _STATEMENT.search(text)
    if match:
        around = " ".join(text[max(match.start() - 60, 0) : match.end() + 60].split())
        raise SystemExit(
            f"GET {url}: the page states {match.group(0)!r} ({around!r}), a copyright, "
            "licence or terms of use that ATTRIBUTION does not record.\nRead it by hand, "
            "record it in ATTRIBUTION and update scripts/refresh_upstream.py. Nothing was "
            "written."
        )
    return found


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    counts = Counter(key for key, _ in pairs)
    duplicates = sorted(key for key, count in counts.items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate keys {duplicates}")
    return dict(pairs)


def load_json(response: Response) -> Any:
    """The JSON document of ``response``; a duplicate key or a parse error stops the run."""
    try:
        return json.loads(decode(response), object_pairs_hook=_no_duplicates)
    except ValueError as error:
        raise changed(response.url, f"not usable JSON ({error})") from None


def _endings(body: bytes) -> str:
    crlf, lf = body.count(b"\r\n"), body.count(b"\n")
    return "CRLF" if crlf and crlf == lf else "LF" if not crlf else "mixed"


def _squash(text: str) -> str:
    return " ".join(text.split())


def _names(names: Sequence[str]) -> str:
    return ", ".join(f"`{name}`" for name in names)


# --- HTML to a tree -------------------------------------------------------------------


@dataclass
class Element:
    """One HTML element as ``html.parser`` reads it: tag, attributes and children."""

    tag: str
    attrs: dict[str, str]
    children: list["Element | str"] = field(default_factory=list)

    def has_class(self, name: str) -> bool:
        """Whether ``name`` is one of the element's classes."""
        return name in self.attrs.get("class", "").split()

    def elements(self) -> Iterator["Element"]:
        """Every element below this one, depth first, in document order."""
        for child in self.children:
            if isinstance(child, Element):
                yield child
                yield from child.elements()

    def find_all(self, tag: str) -> list["Element"]:
        """The elements below this one named ``tag``."""
        return [item for item in self.elements() if item.tag == tag]

    def child_elements(self) -> list["Element"]:
        """The direct children that are elements."""
        return [child for child in self.children if isinstance(child, Element)]

    def contains(self, other: "Element") -> bool:
        """Whether ``other`` is below this element."""
        return any(item is other for item in self.elements())


class _TreeBuilder(HTMLParser):
    """Build an ``Element`` tree; an end tag closes the nearest open element it names."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("#document", {})
        self._open = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Open an element, or add a void one."""
        element = Element(tag, {name: value or "" for name, value in attrs})
        self._open[-1].children.append(element)
        if tag not in _VOID:
            self._open.append(element)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Add a self-closed element."""
        self._open[-1].children.append(Element(tag, {name: value or "" for name, value in attrs}))

    def handle_endtag(self, tag: str) -> None:
        """Close the nearest open element named ``tag``; ignore a stray end tag."""
        for index in range(len(self._open) - 1, 0, -1):
            if self._open[index].tag == tag:
                del self._open[index:]
                return

    def handle_data(self, data: str) -> None:
        """Keep text where it stands."""
        self._open[-1].children.append(data)


def parse_html(text: str) -> Element:
    """The document's element tree."""
    builder = _TreeBuilder()
    builder.feed(text)
    builder.close()
    return builder.root


def visible_text(node: Element) -> str:
    """The text below ``node`` as a browser shows it, block by block, whitespace collapsed."""
    parts: list[str] = []

    def walk(element: Element) -> None:
        for child in element.children:
            if isinstance(child, str):
                parts.append(child)
            elif child.tag not in _NO_TEXT:
                block = child.tag in _BLOCK
                parts.append("\n" if block else "")
                walk(child)
                parts.append("\n" if block else "")

    walk(node)
    return _squash("".join(parts))


def fragments(node: Element) -> Iterator[str]:
    """Each text node below ``node`` outside scripts and styles, whitespace collapsed."""
    for child in node.children:
        if isinstance(child, str):
            if child.strip():
                yield _squash(child)
        elif child.tag not in _NO_TEXT:
            yield from fragments(child)


def _one_body(url: str, root: Element) -> Element:
    bodies = root.find_all("body")
    if len(bodies) != 1:
        raise changed(url, f"expected one <body>, found {len(bodies)}")
    return bodies[0]


# --- the terms page to Markdown -------------------------------------------------------


def _escape(text: str) -> str:
    return re.sub(r"([\\`*_])", r"\\\1", text)


def _wrap(inner: str, before: str, after: str) -> str:
    """``inner`` between the markers, its outer whitespace kept outside them."""
    core = inner.strip()
    if not core:
        return inner
    lead = inner[: len(inner) - len(inner.lstrip())]
    trail = inner[len(inner.rstrip()) :]
    return f"{lead}{before}{_squash(core)}{after}{trail}"


def _href(url: str, value: str) -> str:
    absolute = urljoin(url, value.strip())
    return absolute.replace(" ", "%20").replace("(", "%28").replace(")", "%29")


def _cell(value: str) -> str:
    return value.replace("|", r"\|")


class _Markdown:
    """Convert the terms page's content blocks: headings, paragraphs, lists, tables, links.

    A table with merged cells (``rowspan``, ``colspan``) or a nested table stays HTML
    (conventions §3), counted in ``html_tables``; an element the converter does not know
    stops the run.
    """

    def __init__(self, url: str, title: Element) -> None:
        self.url = url
        self.title = title
        self.html_tables = 0

    def inline(self, node: Element) -> str:
        """Markdown for the content of ``node``, whitespace not yet collapsed."""
        parts: list[str] = []
        for child in node.children:
            if isinstance(child, str):
                parts.append(_escape(child))
            elif child.tag in _NO_TEXT:
                continue
            elif child.tag in {"strong", "b"}:
                parts.append(_wrap(self.inline(child), "**", "**"))
            elif child.tag in {"em", "i"}:
                parts.append(_wrap(self.inline(child), "*", "*"))
            elif child.tag == "a" and child.attrs.get("href", "").strip():
                href = _href(self.url, child.attrs["href"])
                parts.append(_wrap(self.inline(child), "[", f"]({href})"))
            elif child.tag in {"a", "span"}:
                parts.append(self.inline(child))
            elif child.tag == "br":
                parts.append("\n")
            else:
                raise changed(self.url, f"an inline <{child.tag}> the script does not convert")
        return "".join(parts)

    def blocks(self, node: Element) -> list[str]:
        """Markdown lines for the block elements below ``node``, each followed by a blank."""
        lines: list[str] = []
        for child in node.children:
            if isinstance(child, str):
                if child.strip():
                    raise changed(self.url, f"loose text {_squash(child)[:60]!r} between blocks")
                continue
            text = _squash(self.inline(child)) if child.tag in {"p", *_HEADINGS} else ""
            if child is self.title:
                lines += [f"# {text}", ""]
            elif child.tag in _HEADINGS:
                lines += [f"{'#' * int(child.tag[1])} {text}", ""]
            elif child.tag == "p":
                lines += [text, ""] if text else []
            elif child.tag in {"ul", "ol"}:
                lines += [*self.listing(child), ""]
            elif child.tag == "table":
                lines += [*self.table(child), ""]
            elif child.tag == "div":
                lines += self.blocks(child)
            else:
                raise changed(self.url, f"a <{child.tag}> block the script does not convert")
        return lines

    def listing(self, node: Element) -> list[str]:
        """One line per list item: ``- `` or ``1. ``; a nested list stops the run."""
        items: list[str] = []
        for child in node.children:
            if isinstance(child, str):
                if child.strip():
                    raise changed(self.url, "loose text in a list")
                continue
            if child.tag != "li" or any(e.tag in {"ul", "ol"} for e in child.elements()):
                raise changed(self.url, f"a list holds a <{child.tag}> or a nested list")
            marker = "-" if node.tag == "ul" else f"{len(items) + 1}."
            items.append(f"{marker} {_squash(self.inline(child))}")
        return items

    def table(self, node: Element) -> list[str]:
        """A pipe table, or the table's HTML where cells are merged or a table is nested."""
        cells = [item for item in node.elements() if item.tag in {"th", "td"}]
        if node.find_all("table") or any(
            "rowspan" in cell.attrs or "colspan" in cell.attrs for cell in cells
        ):
            self.html_tables += 1
            return [self.html(node)]
        rows = [
            [_cell(_squash(self.inline(cell))) for cell in row.child_elements()]
            for row in node.find_all("tr")
        ]
        if not rows or any(len(row) != len(rows[0]) for row in rows):
            raise changed(self.url, "a table whose rows differ in length, or without rows")
        lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * len(rows[0])]
        return lines + ["| " + " | ".join(row) + " |" for row in rows[1:]]

    def html(self, node: Element) -> str:
        """A table as simplified HTML: its structure, ``rowspan`` and ``colspan`` kept."""
        if node.tag in {"th", "td"}:
            spans = "".join(
                f' {name}="{html.escape(node.attrs[name])}"'
                for name in ("rowspan", "colspan")
                if name in node.attrs
            )
            parts: list[str] = []
            run: list[Element | str] = []
            for child in [*node.children, Element("table", {})]:
                if isinstance(child, Element) and child.tag == "table":
                    text = _squash(self.inline(Element("span", {}, run)))
                    parts.append(html.escape(text, quote=False))
                    parts.append(self.html(child) if child.children else "")
                    run = []
                else:
                    run.append(child)
            inner = " ".join(part for part in parts if part)
            return f"<{node.tag}{spans}>{inner}</{node.tag}>"
        if node.tag not in {"table", "thead", "tbody", "tfoot", "tr", "caption"}:
            raise changed(self.url, f"a <{node.tag}> inside a table")
        inner = "".join(self.html(child) for child in node.child_elements())
        return f"<{node.tag}>{inner}</{node.tag}>"


def terms_markdown(response: Response) -> tuple[str, str, int]:
    """The terms page as Markdown, its visible text and the tables kept as HTML.

    The content is the page's Sitefinity container (``data-sf-element="Container"``) that
    holds the one ``h2.page-title``, read block by block (``div.sfContentBlock``); the
    site's header, navigation, breadcrumb, share buttons, footer and scripts are dropped.
    """
    root = parse_html(decode(response))
    body = _one_body(response.url, root)
    titles = [item for item in body.find_all("h2") if item.has_class("page-title")]
    if len(titles) != 1:
        raise changed(response.url, f"expected one <h2 class=page-title>, found {len(titles)}")
    containers = [
        item
        for item in body.elements()
        if item.attrs.get("data-sf-element") == "Container" and item.contains(titles[0])
    ]
    innermost = [item for item in containers if not any(item.contains(c) for c in containers)]
    if len(innermost) != 1:
        raise changed(response.url, "the page title is not inside one Sitefinity container")
    container = innermost[0]
    blocks = [item for item in container.elements() if item.has_class("sfContentBlock")]
    if not blocks or any(a.contains(b) for a in blocks for b in blocks if a is not b):
        raise changed(response.url, "no content blocks, or a content block inside another")
    if not blocks[0].contains(titles[0]) or visible_text(container) != _squash(
        " ".join(visible_text(block) for block in blocks)
    ):
        raise changed(response.url, "the container holds text outside its content blocks")
    converter = _Markdown(response.url, titles[0])
    lines: list[str] = []
    for block in blocks:
        lines += converter.blocks(block)
    lines[2:2] = _paragraph(
        f"Converted from {response.url} by `scripts/refresh_upstream.py`; see `../FETCHED.md`."
    )
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n", visible_text(body), converter.html_tables


# --- the pages ------------------------------------------------------------------------


def _operation_ids(text: str) -> list[str]:
    return _OPERATION_ID.findall(text)


def spec_row() -> tuple[Row, str, set[str]]:
    """Fetch the OpenAPI document; it is kept byte for byte, so only read, never parsed."""
    response = fetch(SPEC_URL)
    text = decode(response)
    found = check_attribution(SPEC_URL, html.unescape(text))
    version = re.search(r"^openapi:[ \t]*['\"]?(3\.[0-9.]+)", text, re.MULTILINE)
    info = re.search(r"^info:[^\n]*\n((?:[ \t][^\n]*\n)*)", text, re.MULTILINE)
    if not version or not info:
        raise changed(SPEC_URL, "not an OpenAPI 3 document with an info object")
    stated = re.findall(r"^  (license|termsOfService|contact):", info.group(1), re.MULTILINE)
    if stated:
        raise changed(SPEC_URL, f"info now names {stated}; quote it under Attribution")
    operations = _operation_ids(text)
    if not operations or len(set(operations)) != len(operations):
        raise changed(SPEC_URL, "no operationId, or one used twice")
    servers = re.search(r"^servers:[ \t]*\n((?:[- \t][^\n]*(?:\n|$))*)", text, re.MULTILINE)
    urls = re.findall(r"^- url:[ \t]*(\S+)", servers.group(1), re.MULTILINE) if servers else []
    if urls != [API_BASE] or _squash(PROD_SERVER["description"]) not in _squash(text):
        raise changed(SPEC_URL, f"`servers` lists {urls}, not {API_BASE} as recorded")
    bearer = re.search(r"bearerAuth:[ \t]*\n[ \t]+type: http[ \t]*\n[ \t]+scheme: bearer", text)
    if not bearer or not re.search(r"^security:[ \t]*\n[ \t]*- bearerAuth: \[\]", text, re.M):
        raise changed(SPEC_URL, "the document no longer requires bearerAuth, an HTTP bearer")
    if f"operationId: {'auth_login'}" not in text or "  /auth/login:" not in text:
        raise changed(SPEC_URL, "no auth_login at /auth/login")
    note = (
        f"SPEC_URL, verbatim, byte for byte ({_endings(response.body)} line endings, as "
        f"served); OpenAPI {version.group(1)}, {len(operations)} operations by `operationId`; "
        f"`servers` {API_BASE}; `security` `bearerAuth`, an HTTP bearer (JWT), whose token "
        "`auth_login` (`POST /auth/login`) issues; `info` names no licence, terms of service "
        "or contact; no page links the document, the ReDoc page renders a copy of its own"
    )
    page = Page(SPEC_URL, SPEC_FILE, note=note)
    return Row(page, response, response.body), text, found


def _strings(value: Any) -> Iterator[str]:
    """Every key and string value inside ``value``."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, str):
        yield value


def redoc_row(spec_text: str) -> tuple[Row, set[str]]:
    """Record the ReDoc page: ReDoc's rendering of a copy of the OpenAPI document."""
    response = fetch(DOCS_URL)
    text = decode(response)
    found = check_attribution(DOCS_URL, html.unescape(text))
    versions = _REDOC_JS.findall(text)
    if len(versions) != 1 or text.count(_REDOC_STATE) != 1:
        raise changed(DOCS_URL, "not one redoc.standalone.js and one __redoc_state")
    start = text.index(_REDOC_STATE) + len(_REDOC_STATE)
    try:
        state, end = json.JSONDecoder(object_pairs_hook=_no_duplicates).raw_decode(text, start)
    except ValueError as error:
        raise changed(DOCS_URL, f"__redoc_state is not JSON ({error})") from None
    if not text[end:].lstrip().startswith(";") or _REDOC_HYDRATE not in text[end:]:
        raise changed(DOCS_URL, "the page no longer hydrates ReDoc from __redoc_state")
    spec = state.get("spec", {}).get("data") if isinstance(state, dict) else None
    if not isinstance(spec, dict) or spec.get("servers") != [DEV_SERVER, PROD_SERVER]:
        servers = spec.get("servers") if isinstance(spec, dict) else None
        raise changed(DOCS_URL, f"the embedded copy's servers are {servers}, not as recorded")
    flat = _squash(spec_text)
    rest = {key: value for key, value in spec.items() if key != "servers"}
    foreign = sorted({item for item in _strings(rest) if _squash(item) not in flat})
    if foreign:
        raise changed(DOCS_URL, f"the embedded copy holds text the document lacks: {foreign[:5]}")
    paths = spec.get("paths")
    copied = [
        operation["operationId"]
        for methods in (paths.values() if isinstance(paths, dict) else [])
        for operation in (methods.values() if isinstance(methods, dict) else [])
        if isinstance(operation, dict) and "operationId" in operation
    ]
    if sorted(copied) != sorted(_operation_ids(spec_text)):
        raise changed(DOCS_URL, "the embedded copy's operations are not the document's")
    known = "\n".join(_squash(item) for item in _strings(spec))
    unknown = sorted(
        {
            item
            for item in fragments(parse_html(text))
            if item not in known and item not in REDOC_LABELS and not _JSON_TOKEN.fullmatch(item)
        }
    )
    if unknown:
        raise changed(DOCS_URL, f"text that is neither the copy's nor ReDoc's: {unknown[:5]}")
    note = (
        f"no documentation text of its own, so no file: ReDoc {versions[0]} "
        "(`redoc.standalone.js` from cdn.redocly.com) hydrating a copy of the OpenAPI "
        "document embedded in the page's `__redoc_state`, every key and string of which the "
        "document holds but those of `servers`, which list before the document's server a "
        f"development server, {DEV_SERVER['url']}, \N{LEFT DOUBLE QUOTATION MARK}"
        f"{DEV_SERVER['description']}\N{RIGHT DOUBLE QUOTATION MARK}; {len(copied)} "
        "operations, the document's; the page's text is the copy's and ReDoc's labels"
    )
    return Row(Page(DOCS_URL, note=note), response, None), found


def portal_row() -> tuple[Row, set[str]]:
    """Record the portal's application shell, an empty ``<body>`` that RequireJS fills."""
    response = fetch(PORTAL_URL)
    text = decode(response)
    found = check_attribution(PORTAL_URL, html.unescape(text))
    root = parse_html(text)
    body = _one_body(PORTAL_URL, root)
    if visible_text(body) or body.child_elements():
        raise changed(PORTAL_URL, "the <body> is no longer empty")
    loaders = [item for item in root.find_all("script") if "data-main" in item.attrs]
    if len(loaders) != 1 or not loaders[0].attrs.get("src", "").endswith("require.min.js"):
        raise changed(PORTAL_URL, "no one RequireJS loader with data-main")
    note = (
        f"the developer portal's address, {PORTAL_LINK}, is this request, since a fragment is "
        "never sent: the portal's application shell, an empty `<body>` that a RequireJS "
        f"application (`data-main` `{loaders[0].attrs['data-main']}`) draws in the browser, "
        "so no documentation text and no file"
    )
    return Row(Page(PORTAL_URL, note=note), response, None), found


def terms_row() -> tuple[Row, set[str]]:
    """Fetch the FAO Statistical Database Terms of Use and convert them to Markdown."""
    response = fetch(TERMS_URL)
    content, text, html_tables = terms_markdown(response)
    found = check_attribution(TERMS_URL, text)
    tables = (
        f"{html_tables} table with merged cells kept as HTML"
        if html_tables == 1
        else f"{html_tables} tables with merged cells kept as HTML"
        if html_tables
        else "no table on the page"
    )
    note = (
        "converted to Markdown with `html.parser`, the page's content kept and the site's "
        f"header, navigation, breadcrumb, share buttons and footer dropped; {tables}; Bytes "
        "and sha256 are the HTML page's"
    )
    return Row(Page(TERMS_URL, TERMS_FILE, note=note), response, content.encode("utf-8")), found


def catalogue_row() -> tuple[Row, set[str]]:
    """Fetch the bulk downloads' catalogue; it is kept byte for byte."""
    response = fetch(CATALOGUE_URL)
    found = check_attribution(CATALOGUE_URL, html.unescape(decode(response)))
    document = load_json(response)
    datasets = document.get("Datasets", {}).get("Dataset") if isinstance(document, dict) else None
    if not isinstance(datasets, list) or not datasets:
        raise changed(CATALOGUE_URL, "no list under Datasets.Dataset")
    if any(not isinstance(item, dict) or tuple(item) != CATALOGUE_KEYS for item in datasets):
        raise changed(CATALOGUE_URL, "a dataset whose fields are not the recorded ones")
    if any(not str(item["FileLocation"]).startswith(f"{BULK_BASE}/") for item in datasets):
        raise changed(CATALOGUE_URL, f"a FileLocation outside {BULK_BASE}/")
    kinds = Counter((str(item["CompressionFormat"]), str(item["FileType"])) for item in datasets)
    files = (
        "every file a `{}` of `{}`".format(*next(iter(kinds)))
        if len(kinds) == 1
        else "the files " + ", ".join(f"{n} a `{c}` of `{t}`" for (c, t), n in kinds.most_common())
    )
    note = (
        f"verbatim, byte for byte ({_endings(response.body)} line endings, as served); the "
        f"bulk downloads' catalogue, open, no key: {len(datasets)} datasets under "
        f"`Datasets.Dataset`, each with {_names(CATALOGUE_KEYS)}; `FileLocation` under "
        f"{BULK_BASE}/, {files} (`CompressionFormat`, `FileType`)"
    )
    page = Page(CATALOGUE_URL, CATALOGUE_FILE, note=note)
    return Row(page, response, response.body), found


def sample_note(sample: Sample, response: Response) -> str:
    """Check one sample's answer and write its row's note; a strange answer stops the run."""
    check_attribution(response.url, html.unescape(decode(response)))
    document = load_json(response)
    metadata = document.get("metadata") if isinstance(document, dict) else None
    data = document.get("data") if isinstance(document, dict) else None
    if (
        not isinstance(metadata, dict)
        or not isinstance(metadata.get("processing_time"), int)
        or not isinstance(data, list)
        or not data
        or not all(isinstance(item, dict) for item in data)
    ):
        raise changed(response.url, "not `metadata` with `processing_time` and rows under `data`")
    keys = list(dict.fromkeys(key for item in data for key in item))
    sets = {frozenset(item) for item in data}
    if len({tuple(item) for item in data}) == 1:
        fields = f"each with {_names(keys)}"
    elif len(sets) == 1:
        fields = f"each with {_names(keys)}, in varying order"
    else:
        fields = f"with the fields {_names(keys)}, in {len(sets)} different sets across the rows"
    if sample.operation == "get_data":
        printed = sorted({str(item.get("Element Code")) for item in data})
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(response.url).query)
        detail = (
            f"; the filter `element={query['element'][0]}` answers `Element Code` "
            + ", ".join(f"`{code}`" for code in printed)
        )
    elif sample.operation == "get_dimensions":
        detail = "; the dimensions " + _names([str(item.get("id")) for item in data])
    elif sample.operation == "getCodeList":
        detail = "; the codes " + ", ".join(
            f"`{item.get('code')}` {item.get('label')}" for item in data
        )
    else:
        detail = ""
    return (
        f"verbatim; `{sample.operation}` (`GET {sample.template}`), fetched with the account's "
        f"bearer token; `metadata` with {_names(list(metadata))}, of which `processing_time` "
        f"changes on every request; {len(data)} rows under `data`, {fields}{detail}; "
        "a structural sample of the API's answer, not a test fixture"
    )


def sample_row(sample: Sample, token: str) -> Row:
    """Fetch one sample with the token; it is kept byte for byte."""
    response = fetch(f"{API_BASE}{sample.query}", token=token)
    page = Page(response.url, sample.file, note=sample_note(sample, response), keyed=True)
    return Row(page, response, response.body)


def sample_rows(spec_text: str) -> list[Row]:
    """Log in once, then fetch the samples; the token lives in this call only.

    Every sample's operation is looked up in the document first, so that a missing one
    stops the run before the login spends a keyed call.
    """
    for sample in SAMPLES:
        if f"  {sample.template}:" not in spec_text or (
            f"operationId: {sample.operation}" not in spec_text
        ):
            raise changed(SPEC_URL, f"no `{sample.operation}` at {sample.template}")
    token = login()
    return [sample_row(sample, token) for sample in SAMPLES]


def keyless_rows() -> tuple[list[Row], str, set[str]]:
    """Fetch and check every keyless page; return the rows, the document and the statements."""
    spec, text, found = spec_row()
    rows = [spec]
    for row, statements in (redoc_row(text), portal_row(), terms_row(), catalogue_row()):
        rows.append(row)
        found |= statements
    missing = [statement for statement in ATTRIBUTION if statement not in found]
    if missing:
        raise SystemExit(
            f"ATTRIBUTION records {missing}, which no page prints any more.\nRead the pages by "
            "hand and update scripts/refresh_upstream.py. Nothing was written."
        )
    return rows, text, found


# --- FETCHED.md -----------------------------------------------------------------------

CAPTURE = (
    (
        "FAO documents the FAOSTAT API in an OpenAPI document, kept verbatim as `openapi/"
        f"faostat_openapi.yaml` from {SPEC_URL} (`SPEC_URL`), and renders it on the ReDoc page "
        f"{DOCS_URL}. No page links the document: it is served beside the ReDoc page, which "
        "embeds a copy of its own and draws it in the browser. The script checks on every run "
        "that the copy holds no text the document lacks but a development server, and that "
        "the page's text is the copy's and ReDoc's labels; the page is a row without a file."
    ),
    (
        f"The developer portal, {PORTAL_LINK}, is a fragment of {PORTAL_URL}, the portal's "
        "application shell, an empty page that a RequireJS application fills in the browser; "
        "it carries no documentation text and is a row without a file."
    ),
    (
        "The FAO Statistical Database Terms of Use are converted to Markdown with the "
        "standard library's `html.parser`: the page's content, its headings, paragraphs, "
        "lists, tables and links (made absolute) kept, a table with merged cells or a nested "
        "table kept as HTML, the site's header, navigation, breadcrumb, share buttons, footer "
        "and scripts dropped. The run stops on an element the converter does not know."
    ),
    (
        "The bulk downloads' catalogue is open and kept verbatim; its description of the "
        "census dataset WCAD says census reports are \N{LEFT DOUBLE QUOTATION MARK}available "
        "in the public domain\N{RIGHT DOUBLE QUOTATION MARK}, which states nothing about the "
        "catalogue, and the script records the phrase as incidental (`INCIDENTAL`). The four "
        "samples under "
        "`samples/` are answers of the API, kept verbatim, fetched with the FAO account's "
        "bearer token: the script logs in once with `auth_login` (`POST /auth/login`, the "
        "form fields `username` and `password`, from `FAOSTAT_USERNAME` and "
        "`FAOSTAT_PASSWORD`), after every keyless page, and sends the access token on these "
        "four requests only; neither the credentials nor the token is recorded. Their "
        "`metadata.processing_time` changes on every request, which `--check` disregards. "
        "They are structural samples; test fixtures are recorded separately."
    ),
    (
        "What the API does that the OpenAPI document does not state, observed in probes on "
        "2026-10-29 and not documented (the document lists none of these parameters for "
        "`get_data`; `no_records` and `null_values` appear only under `post_datasize`, "
        "`limit` only under `post_rankings`):"
    ),
)
"""``FETCHED.md``'s "How this is captured": what is converted, cut or left out, and why."""

OBSERVED = (
    "`page_size` with `page_number`, and `limit` with `offset`, page the data answer "
    "(`page_size=2&page_number=2` answered rows 3 and 4, `limit=2&offset=0` rows 1 and 2); "
    "without them the whole answer comes in one body (30,942 rows, 9.3 MB); no maximum page "
    "size was found (`page_size=60000` answered 60,000 rows).",
    '`no_records=true` answers `[{"NoRecords": N}]` only, `N` the number of rows, printed as '
    "a float (`1643610.0`) for a large count.",
    "The data endpoint takes the options `show_codes`, `show_unit`, `show_flags`, "
    "`show_notes` and `null_values`, which the portal sends; an answer without them carried "
    "the same 15 columns.",
    "`area_cs` and `item_cs` name the coding system of the codes sent: with `area_cs=FAO` "
    "and `item_cs=FAO` the columns are `Area Code (FAO)` and `Item Code (FAO)`; without them "
    "the codes are FAO's, under `Area Code` and `Item Code`.",
    "The element codes a query filters by are not the answer's `Element Code`: `element=2510` "
    "(Production Quantity, as `codes/element/QCL` lists it) answers rows with `Element Code` "
    "`5510`, and `element=5510` answers no rows, as any unknown code does.",
    "A data query with no filter is refused with HTTP 500 and the body `Please add at least "
    "one filter.`; an unknown domain with HTTP 500 `Index: 0, Size: 0`.",
    "No answer carried an `X-RateLimit-*`, `RateLimit-*` or `Retry-After` header.",
    "The answers' field names differ from the document's schemas: `groupsanddomains` "
    "answers `group_code`, `domain_code` and their like, not `GroupCode` and `DomainaCode`; "
    "the data answer `Area Code` and `Item Code`, not `Area Code (M49)` and "
    "`Item Code (CPC)`; the samples show them.",
)
"""Upstream behaviour the document does not state, with the date it was observed."""


def _iso_http_date(value: str | None) -> str:
    if value is None:
        return "-"
    return parsedate_to_datetime(value).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _paragraph(*sentences: str) -> list[str]:
    text = " ".join(sentences)
    wrapped = textwrap.fill(text, width=88, break_long_words=False, break_on_hyphens=False)
    return [*wrapped.splitlines(), ""]


def _bullet(text: str) -> list[str]:
    wrapped = textwrap.fill(
        text,
        width=88,
        initial_indent="- ",
        subsequent_indent="  ",
        break_long_words=False,
        break_on_hyphens=False,
    )
    return wrapped.splitlines()


def _quote(text: str) -> list[str]:
    wrapped = textwrap.fill(
        text,
        width=88,
        initial_indent="> ",
        subsequent_indent="> ",
        break_long_words=False,
        break_on_hyphens=False,
    )
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
            f"FAOSTAT's data are governed by the FAO {TERMS_NAME}, {TERMS_URL}, kept whole as",
            f"`{TERMS_FILE}`. Their licence, as printed:",
        ),
        *_quote(LICENCE),
        *_paragraph(
            "Annex 1 of the terms lists FAOSTAT among those databases. The citation the terms",
            "ask for, as printed:",
        ),
        *_quote(CITATION),
        *_paragraph(
            f"The terms page's footer prints `{COPYRIGHT}`, linked to FAO's Terms and",
            f"Conditions regarding the Reuse of Web content, {REUSE_URL}, which the terms",
            "incorporate by reference (cited, not fetched). The OpenAPI document's `info`",
            "names no licence, terms of service or contact, and the ReDoc page, the portal's",
            "shell, the catalogue and the samples state none.",
        ),
        *_paragraph(
            "Every statement of a copyright, a licence or terms of use the pages print is",
            "recorded, as printed, in `ATTRIBUTION` of `scripts/refresh_upstream.py`: the",
            "three above, the terms' name, and the terms page's other sentences and headings",
            "that name a licence or terms of use:",
        ),
        *[line for clause in (TERMS_NAME, *TERMS_CLAUSES) for line in _bullet(f"`{clause}`")],
        "",
        *_paragraph(
            "The script stops when a page states one it does not record, or when one it",
            "records is no longer printed. The documentation's text is reproduced here as",
            "this package's reference (ADR-0003); the publisher's objection is met by",
            "replacing it with a summary that keeps the names and semantics the wrappers",
            "rely on.",
        ),
        "## How this is captured",
        "",
        *[line for paragraph in CAPTURE for line in _paragraph(paragraph)][:-1],
        "",
        *[line for item in OBSERVED for line in _bullet(item)],
        "",
        *_paragraph(
            "Fetched is the UTC time the run started, in ISO 8601 with an explicit Z, the",
            "same for every row. Bytes and sha256 are those of the body as fetched: a",
            "converted page's row holds the HTML page's. Last-Modified is the HTTP header in",
            "UTC, ETag as sent. A page recorded without a file is `(no file)`. Requests go",
            f"one at a time, {PAUSE:g} s apart, identified as `{USER_AGENT}`; a keyless one is",
            "retried at most once, a keyed one never. No API key exists. The four samples are",
            "fetched with the account's bearer token after one login; no other request sends",
            "a credential, and neither the credentials nor the token is written.",
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
    lines += ["", f"Regenerate, with `{USERNAME_ENV}` and `{SECRET_ENV}` set: `{COMMAND}`"]
    return "\n".join(lines) + "\n"


# --- writing and comparing ------------------------------------------------------------


def _files(rows: Sequence[Row]) -> dict[str, bytes]:
    return {row.page.file: row.content for row in rows if row.page.file and row.content is not None}


def _stale(out: Path, files: dict[str, bytes]) -> list[str]:
    """The files under the subdirectories the run writes to that it does not produce."""
    subdirs = sorted({name.split("/", 1)[0] for name in files if "/" in name})
    found = [path for subdir in subdirs for path in sorted((out / subdir).rglob("*"))]
    names = [path.relative_to(out).as_posix() for path in found if path.is_file()]
    return [name for name in names if name not in files]


def write_snapshot(out: Path, rows: Sequence[Row], fetched_md: str) -> None:
    """Write every file as fetched or converted, then ``FETCHED.md``; remove stale files."""
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


def _masked(content: bytes) -> bytes:
    return _PROCESSING_TIME.sub(b'"processing_time": 0', content, count=1)


def as_recorded(out: Path, rows: Sequence[Row]) -> list[Row]:
    """The rows, a sample that differs from its file only in ``processing_time`` as the file."""
    result: list[Row] = []
    for row in rows:
        path = out / row.page.file if row.page.file else None
        if row.page.keyed and path and path.is_file() and row.content is not None:
            old = path.read_bytes()
            if old != row.content and _masked(old) == _masked(row.content):
                row = Row(row.page, replace(row.response, body=old), old)
        result.append(row)
    return result


def _differing(out: Path, files: dict[str, bytes]) -> list[str]:
    return [
        name
        for name, content in files.items()
        if not (out / name).is_file() or (out / name).read_bytes() != content
    ]


def _cells(line: str) -> list[str] | None:
    """A ``FETCHED.md`` table row's nine cells, or ``None`` for any other line."""
    cells = line[2:-2].split(" | ") if line.startswith("| ") and line.endswith(" |") else []
    return cells if len(cells) == 9 and cells[0] != "---" and cells[2] != "Fetched" else None


def compare(out: Path, rows: Sequence[Row], *, keyless: bool = False) -> list[str]:
    """The snapshot's files and rows that differ from this run's, ``Fetched`` and timings aside.

    A converted page whose file is unchanged keeps its recorded Bytes, sha256, ETag and
    Last-Modified. With ``keyless``, only these rows' files and table rows are compared.
    """
    rows = as_recorded(out, rows)
    files = _files(rows)
    differ = _differing(out, files)
    if not keyless:
        differ += [f"{name} (no longer produced)" for name in _stale(out, files)]
    current = out / "FETCHED.md"
    old = current.read_bytes().decode("utf-8") if current.is_file() else ""
    match = _FETCHED.search(old, max(old.find("| --- |"), 0))
    recorded = {cells[1]: cells for cells in map(_cells, old.splitlines()) if cells}
    kept = {
        row.response.url
        for row in rows
        if row.content not in (None, row.response.body) and row.page.file not in differ
    }
    lines = []
    for line in render_fetched(rows, match.group(1) if match else "-").splitlines():
        cells = _cells(line)
        if cells and cells[1] in kept and cells[1] in recorded:
            cells[4:8] = recorded[cells[1]][4:8]
            line = "| " + " | ".join(cells) + " |"
        lines.append(line)
    if keyless:
        new = [cells for cells in map(_cells, lines) if cells]
        differ += [f"FETCHED.md row of {c[1]}" for c in new if recorded.get(c[1]) != c]
    elif not match or "\n".join(lines) + "\n" != old:
        differ.append("FETCHED.md")
    return differ


def main(argv: Sequence[str] | None = None) -> int:
    """Fetch every page, then write the snapshot, or with ``--check`` compare it."""
    parser = argparse.ArgumentParser(description="Refresh docs/upstream/ from FAOSTAT.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="snapshot directory")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check", action="store_true", help="fetch and compare with the snapshot; write nothing"
    )
    mode.add_argument(
        "--keyless",
        action="store_true",
        help="fetch the keyless pages only and compare their files; no login, write nothing",
    )
    args = parser.parse_args(argv)
    out: Path = args.out
    if not args.keyless:
        _require_credentials()
    fetched = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    _log("Keyless pages: the OpenAPI document, the ReDoc page, the shell, the terms, the bulk")
    rows, spec_text, _ = keyless_rows()
    if args.keyless:
        differ = compare(out, rows, keyless=True)
        for name in differ:
            _log(f"  differs: {name}")
        _log(
            f"{len(differ)} of the keyless files and rows differ; nothing was written"
            if differ
            else "The keyless files and rows are current; nothing was written, no login was made."
        )
        return 1 if differ else 0
    _log(f"Samples, with the account's bearer token: {len(SAMPLES)} pages after one login")
    rows += sample_rows(spec_text)
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
