"""Refresh the upstream documentation snapshot in ``docs/upstream/`` (``/refresh-upstream``).

FAOSTAT documents its API in an OpenAPI document, ``SPEC_URL``, which the ReDoc page
``DOCS_URL`` beside it renders from a copy of its own. The script declares its snapshot,
``SNAPSHOT``, to core's frame, ``xippios.core.refresh``, which fetches every page, checks the
attribution, writes the files and ``FETCHED.md`` and compares with ``--check`` (sdk-core
ADR-0062; conventions §3). The snapshot keeps:

- ``openapi/faostat_openapi.yaml``: the OpenAPI document, byte for byte;
- ``pages/db-terms-of-use.md``: the FAO Statistical Database Terms of Use, which license
  FAOSTAT's data, converted to Markdown with the standard library's ``html.parser``;
- ``bulk/datasets_E.json``: the bulk downloads' catalogue, open, byte for byte;
- ``samples/<name>.json``: four answers of the API, byte for byte, structural samples
  (test fixtures are recorded separately, never here), the snapshot's keyed pages;

and records the ReDoc page and the portal's application shell as rows without a file.

Every request goes through the package's own client, ``xippios.faostat._client.client``.
Its ``LoginAuth`` holds the FAO account's credentials, read from ``FAOSTAT_USERNAME`` and
``FAOSTAT_PASSWORD``, and sends them, and the access token the login issues, to the origin of
its base URL alone: the frame sends the four keyed samples with the client's auth, every
other page without it. The login runs once, before the first sample, inside the client's
auth flow; a sample refused with HTTP 401 or 403 logs in once more and is sent again, once.
The frame counts each of them among the requests it prints, a failed run's too.
Neither the credentials nor the token is printed, logged or written.

The script's own code is its hooks. ``reduce`` converts the terms page to Markdown. ``note``
checks every page the script recognises, the OpenAPI document's YAML ``info`` among them,
which the frame does not read, and writes each row's note; a page that changed in a way the
script does not know stops the run before anything is written. ``sections`` checks the ReDoc
page's copy of the OpenAPI document against the document, with every row read, and
writes no section of its own. ``canonical`` reads a sample
without its ``metadata.processing_time``, which changes on every request, so ``--check``
disregards it. The frame stops, too, on a copyright, a licence or terms of use that
``ATTRIBUTION`` does not record, on every page it reads but the samples. Run from the
repository root, the two variables set (``direnv exec .`` from the clone or a worktree sets
them for the script's process)::

    uv run scripts/refresh_upstream.py              # fetch, then write the snapshot
    uv run scripts/refresh_upstream.py --check      # fetch and compare; write nothing
    uv run scripts/refresh_upstream.py --keyless    # the keyless pages only; no login

``--check`` exits 1 when a file differs from what upstream serves now, a sample compared
without its ``processing_time``, or when ``FETCHED.md`` would change in more than its rows'
measures. ``--keyless`` fetches and compares the five keyless pages, writing nothing and
logging in nowhere: a free trial before a run that spends keyed calls.
"""

import html
import json
import re
import textwrap
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

from xippios.core.refresh import (
    NotFetched,
    Page,
    Response,
    Row,
    Section,
    Snapshot,
    Statement,
    changed,
    decode,
    parse_json,
    run,
)

from xippios.faostat._client import BASE_URL, PASSWORD_ENV, USERNAME_ENV, client

ROOT = Path(__file__).resolve().parents[1]
DOCS_URL = "https://www.fao.org/faostat/en/docs/redoc-static.html"
"""Where the documentation lives: ``upstream_docs_url`` in ``.copier-answers.yml``."""
SPEC_URL = "https://www.fao.org/faostat/en/docs/faostat_openapi.yaml"
"""The OpenAPI document, served beside the ReDoc page; no page links it (``CAPTURE``)."""
SPEC_FILE = "openapi/faostat_openapi.yaml"
API_BASE = BASE_URL
"""The document's one server and the client's base URL, whose origin alone receives the
credentials and the token: the samples' requests."""
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
"""The samples, fetched in this order after every keyless page, with the account's token."""
_SAMPLE_FILES = {sample.file: sample for sample in SAMPLES}

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
_CLAUSE = "a sentence or heading of the terms that names a licence or terms of use"
ATTRIBUTION = (
    Statement(
        COPYRIGHT,
        TERMS_URL,
        where="the copyright line of fao.org's footer, linked to FAO's Terms and Conditions "
        f"regarding the Reuse of Web content, {REUSE_URL}, which the terms incorporate by "
        "reference (cited, not fetched)",
    ),
    Statement(
        TERMS_NAME,
        TERMS_URL,
        where="the name of the terms that govern FAOSTAT's data, as the breadcrumb prints it, "
        f"the heading after `FAO`; kept whole as `{TERMS_FILE}`",
    ),
    Statement(
        LICENCE,
        TERMS_URL,
        where="the terms' licence; Annex 1 of the terms lists FAOSTAT among those databases",
    ),
    Statement(CITATION, TERMS_URL, where="the citation the terms ask for, inside its quotes"),
    *(Statement(clause, TERMS_URL, where=_CLAUSE) for clause in TERMS_CLAUSES),
)
"""Every copyright line, licence or terms of use the pages state, as printed: all on the
terms page, the terms themselves, which must print each of them on every run."""
VOCABULARY = (
    "dissemination products available in the public domain or directly provided by member "
    "countries to FAO",
)
"""Text that carries one of the words without stating anything about the snapshot: the
catalogue's description of the census dataset WCAD, which draws on census reports
"available in the public domain"."""

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


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    counts = Counter(key for key, _ in pairs)
    duplicates = sorted(key for key, count in counts.items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate keys {duplicates}")
    return dict(pairs)


def _endings(body: bytes) -> str:
    crlf, lf = body.count(b"\r\n"), body.count(b"\n")
    return "CRLF" if crlf and crlf == lf else "LF" if not crlf else "mixed"


def _squash(text: str) -> str:
    return " ".join(text.split())


def _names(names: Sequence[str]) -> str:
    return ", ".join(f"`{name}`" for name in names)


def _paragraph(*sentences: str) -> list[str]:
    text = " ".join(sentences)
    wrapped = textwrap.fill(text, width=88, break_long_words=False, break_on_hyphens=False)
    return [*wrapped.splitlines(), ""]


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


def terms_markdown(response: Response) -> str:
    """The terms page as Markdown, a table with merged cells kept as HTML on a line of its own.

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
    return "\n".join(lines) + "\n"


# --- the pages' checks and notes -------------------------------------------------------


INFO_FIELDS = ("license", "termsOfService", "contact")
"""The fields of an API document's ``info`` that state a licence, terms or whom to ask, as
conventions §3 and sdk-core ADR-0062, decision 10, name them: the frame reads them from a
document in JSON alone, and FAOSTAT's is YAML."""


def check_info(url: str, info: str) -> None:
    """Stop when the OpenAPI document's ``info`` names a licence, terms of service or contact.

    The frame reads the ``info`` of an API document in JSON alone, and FAOSTAT's is YAML,
    so the script reads the block itself: each of ``INFO_FIELDS`` it names is read by hand and
    recorded in the attribution (conventions §3).
    """
    stated = re.findall(rf"^  ({'|'.join(INFO_FIELDS)}):", info, re.MULTILINE)
    if stated:
        raise changed(
            url, f"its `info` now names {stated}: read it by hand and record it in ATTRIBUTION"
        )


def document_note(response: Response) -> str:
    """Check the OpenAPI document, kept byte for byte, and write its row's note.

    The document is read as text, never parsed: its version and its ``info``, its operations,
    each named once, its one server, its HTTP bearer and the login that issues the token, and
    each sample's operation, looked up here so that a missing one stops the run before the
    login spends a keyed call, the samples being fetched last.
    """
    url = response.url
    text = decode(response)
    version = re.search(r"^openapi:[ \t]*['\"]?(3\.[0-9.]+)", text, re.MULTILINE)
    info = re.search(r"^info:[^\n]*\n((?:[ \t][^\n]*\n)*)", text, re.MULTILINE)
    if not version or not info:
        raise changed(url, "not an OpenAPI 3 document with an info object")
    check_info(url, info.group(1))
    operations = _OPERATION_ID.findall(text)
    if not operations or len(set(operations)) != len(operations):
        raise changed(url, "no operationId, or one used twice")
    servers = re.search(r"^servers:[ \t]*\n((?:[- \t][^\n]*(?:\n|$))*)", text, re.MULTILINE)
    urls = re.findall(r"^- url:[ \t]*(\S+)", servers.group(1), re.MULTILINE) if servers else []
    if urls != [API_BASE] or _squash(PROD_SERVER["description"]) not in _squash(text):
        raise changed(url, f"`servers` lists {urls}, not {API_BASE} as recorded")
    bearer = re.search(r"bearerAuth:[ \t]*\n[ \t]+type: http[ \t]*\n[ \t]+scheme: bearer", text)
    if not bearer or not re.search(r"^security:[ \t]*\n[ \t]*- bearerAuth: \[\]", text, re.M):
        raise changed(url, "the document no longer requires bearerAuth, an HTTP bearer")
    if "operationId: auth_login" not in text or "  /auth/login:" not in text:
        raise changed(url, "no auth_login at /auth/login")
    for sample in SAMPLES:
        if f"  {sample.template}:" not in text or f"operationId: {sample.operation}" not in text:
            raise changed(url, f"no `{sample.operation}` at {sample.template}")
    return (
        f"SPEC_URL, verbatim, byte for byte ({_endings(response.body)} line endings, as "
        f"served); OpenAPI {version.group(1)}, {len(operations)} operations by `operationId`; "
        f"`servers` {API_BASE}; `security` `bearerAuth`, an HTTP bearer (JWT), whose token "
        "`auth_login` (`POST /auth/login`) issues; `info` names no licence, terms of service "
        "or contact; no page links the document, the ReDoc page renders a copy of its own"
    )


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


def _redoc_copy(response: Response) -> tuple[str, str, dict[str, Any]]:
    """The ReDoc page's text, its ReDoc version and the copy of the document it embeds.

    Raises ``changed`` where the page is not one ReDoc hydrating one ``__redoc_state``, or the
    copy's servers are not as recorded.
    """
    url = response.url
    text = decode(response)
    versions = _REDOC_JS.findall(text)
    if len(versions) != 1 or text.count(_REDOC_STATE) != 1:
        raise changed(url, "not one redoc.standalone.js and one __redoc_state")
    start = text.index(_REDOC_STATE) + len(_REDOC_STATE)
    try:
        # A JSON value embedded in a page: core's parse_json reads a whole answer alone.
        state, end = json.JSONDecoder(object_pairs_hook=_no_duplicates).raw_decode(text, start)
    except ValueError as error:
        raise changed(url, f"__redoc_state is not JSON ({error})") from None
    if not text[end:].lstrip().startswith(";") or _REDOC_HYDRATE not in text[end:]:
        raise changed(url, "the page no longer hydrates ReDoc from __redoc_state")
    spec = state.get("spec", {}).get("data") if isinstance(state, dict) else None
    if not isinstance(spec, dict) or spec.get("servers") != [DEV_SERVER, PROD_SERVER]:
        servers = spec.get("servers") if isinstance(spec, dict) else None
        raise changed(url, f"the embedded copy's servers are {servers}, not as recorded")
    return text, versions[0], spec


def _operations(spec: dict[str, Any]) -> list[str]:
    """The ``operationId`` of each operation of the embedded copy, in its order."""
    paths = spec.get("paths")
    return [
        operation["operationId"]
        for methods in (paths.values() if isinstance(paths, dict) else [])
        for operation in (methods.values() if isinstance(methods, dict) else [])
        if isinstance(operation, dict) and "operationId" in operation
    ]


def redoc_note(response: Response) -> str:
    """Check the ReDoc page alone and write its note.

    The page is ReDoc's rendering of a copy of the document, embedded in its
    ``__redoc_state``: its text is the copy's and ReDoc's labels. ``sections`` checks the copy
    against the document, a check of one page against another.
    """
    text, version, spec = _redoc_copy(response)
    known = "\n".join(_squash(item) for item in _strings(spec))
    unknown = sorted(
        {
            item
            for item in fragments(parse_html(text))
            if item not in known and item not in REDOC_LABELS and not _JSON_TOKEN.fullmatch(item)
        }
    )
    if unknown:
        raise changed(response.url, f"text that is neither the copy's nor ReDoc's: {unknown[:5]}")
    return (
        f"no documentation text of its own, so no file: ReDoc {version} "
        "(`redoc.standalone.js` from cdn.redocly.com) hydrating a copy of the OpenAPI "
        "document embedded in the page's `__redoc_state`, every key and string of which the "
        "document holds but those of `servers`, which list before the document's server a "
        f"development server, {DEV_SERVER['url']}, \N{LEFT DOUBLE QUOTATION MARK}"
        f"{DEV_SERVER['description']}\N{RIGHT DOUBLE QUOTATION MARK}; "
        f"{len(_operations(spec))} operations, the document's; the page's text is the copy's "
        "and ReDoc's labels"
    )


def redoc_against(response: Response, document: str) -> None:
    """Check the ReDoc page's copy against ``document``, the OpenAPI document's text.

    The copy holds no text the document lacks but its servers, and names the document's
    operations; a difference stops the run with ``changed``.
    """
    _, _, spec = _redoc_copy(response)
    flat = _squash(document)
    rest = {key: value for key, value in spec.items() if key != "servers"}
    foreign = sorted({item for item in _strings(rest) if _squash(item) not in flat})
    if foreign:
        raise changed(
            response.url, f"the embedded copy holds text the document lacks: {foreign[:5]}"
        )
    if sorted(_operations(spec)) != sorted(_OPERATION_ID.findall(document)):
        raise changed(response.url, "the embedded copy's operations are not the document's")


def portal_note(response: Response) -> str:
    """Check the portal's application shell, an empty ``<body>`` that RequireJS fills."""
    root = parse_html(decode(response))
    body = _one_body(response.url, root)
    if visible_text(body) or body.child_elements():
        raise changed(response.url, "the <body> is no longer empty")
    loaders = [item for item in root.find_all("script") if "data-main" in item.attrs]
    if len(loaders) != 1 or not loaders[0].attrs.get("src", "").endswith("require.min.js"):
        raise changed(response.url, "no one RequireJS loader with data-main")
    return (
        f"the developer portal's address, {PORTAL_LINK}, is this request, since a fragment is "
        "never sent: the portal's application shell, an empty `<body>` that a RequireJS "
        f"application (`data-main` `{loaders[0].attrs['data-main']}`) draws in the browser, "
        "so no documentation text and no file"
    )


def terms_note(content: bytes) -> str:
    """The terms page's note, from its Markdown: the tables with merged cells kept as HTML."""
    lines = content.decode("utf-8").splitlines()
    html_tables = sum(1 for line in lines if line.startswith("<table"))
    tables = (
        f"{html_tables} table with merged cells kept as HTML"
        if html_tables == 1
        else f"{html_tables} tables with merged cells kept as HTML"
        if html_tables
        else "no table on the page"
    )
    return (
        "converted to Markdown with `html.parser`, the page's content kept and the site's "
        f"header, navigation, breadcrumb, share buttons and footer dropped; {tables}"
    )


def catalogue_note(response: Response) -> str:
    """Check the bulk downloads' catalogue, kept byte for byte, and write its row's note."""
    url = response.url
    document = parse_json(response)
    datasets = document.get("Datasets", {}).get("Dataset") if isinstance(document, dict) else None
    if not isinstance(datasets, list) or not datasets:
        raise changed(url, "no list under Datasets.Dataset")
    if any(not isinstance(item, dict) or tuple(item) != CATALOGUE_KEYS for item in datasets):
        raise changed(url, "a dataset whose fields are not the recorded ones")
    if any(not str(item["FileLocation"]).startswith(f"{BULK_BASE}/") for item in datasets):
        raise changed(url, f"a FileLocation outside {BULK_BASE}/")
    kinds = Counter((str(item["CompressionFormat"]), str(item["FileType"])) for item in datasets)
    files = (
        "every file a `{}` of `{}`".format(*next(iter(kinds)))
        if len(kinds) == 1
        else "the files " + ", ".join(f"{n} a `{c}` of `{t}`" for (c, t), n in kinds.most_common())
    )
    return (
        f"verbatim, byte for byte ({_endings(response.body)} line endings, as served); the "
        f"bulk downloads' catalogue, open, no key: {len(datasets)} datasets under "
        f"`Datasets.Dataset`, each with {_names(CATALOGUE_KEYS)}; `FileLocation` under "
        f"{BULK_BASE}/, {files} (`CompressionFormat`, `FileType`)"
    )


def sample_note(sample: Sample, response: Response) -> str:
    """Check one sample's answer and write its row's note; a strange answer stops the run."""
    document = parse_json(response)
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
        query = parse_qs(urlsplit(response.url).query)
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
        f"`{sample.operation}` (`GET {sample.template}`), fetched with the account's bearer "
        f"token; `metadata` with {_names(list(metadata))}, of which `processing_time` changes "
        f"on every request; {len(data)} rows under `data`, {fields}{detail}"
    )


# --- the hooks -------------------------------------------------------------------------


def reduce(page: Page, response: Response) -> bytes:
    """The content of a page's file: the terms page as Markdown, every other file as fetched."""
    if page.file == TERMS_FILE:
        return terms_markdown(response).encode("utf-8")
    return response.body


def note(row: Row) -> str:
    """Check the page a row was read from and write the row's note.

    A page that changed in a way the script does not know stops the run with ``changed``,
    before anything is written.
    """
    url, response = row.page.url, row.response
    if url == SPEC_URL:
        return document_note(response)
    if url == DOCS_URL:
        return redoc_note(response)
    if url == PORTAL_URL:
        return portal_note(response)
    if url == TERMS_URL:
        return terms_note(row.content or b"")
    if url == CATALOGUE_URL:
        return catalogue_note(response)
    if row.page.file in _SAMPLE_FILES:
        return sample_note(_SAMPLE_FILES[row.page.file], response)
    return row.note


def sections(rows: Sequence[Row]) -> Sequence[Section]:
    """Check the ReDoc page's copy against the OpenAPI document, with every row read.

    The one check of one page against another (sdk-core ADR-0062): it writes no section of
    its own, ``()``, and stops the run with ``changed`` before anything is written. A run
    without either row stops too, since a check that cannot run must not read as one that
    passed.
    """
    read = {row.page.url: row.response for row in rows}
    missing = [url for url in (SPEC_URL, DOCS_URL) if url not in read]
    if missing:
        raise SystemExit(
            f"{DOCS_URL} is read against the OpenAPI document, {SPEC_URL}, and this run read "
            f"no row of {', '.join(missing)}: declare both. Nothing was written."
        )
    redoc_against(read[DOCS_URL], decode(read[SPEC_URL]))
    return ()


def canonical(page: Page, content: bytes) -> bytes:
    """A sample without its ``metadata.processing_time``, which changes on every request."""
    if page.sample:
        return _PROCESSING_TIME.sub(b'"processing_time": 0', content, count=1)
    return content


# --- the declaration -------------------------------------------------------------------

CAPTURE = "\n\n".join(
    (
        "FAO documents the FAOSTAT API in an OpenAPI document, kept verbatim as "
        f"`{SPEC_FILE}` from {SPEC_URL} (`SPEC_URL`), and renders it on the ReDoc page "
        f"{DOCS_URL}. No page links the document: it is served beside the ReDoc page, which "
        "embeds a copy of its own and draws it in the browser. The script checks on every run "
        "that the copy holds no text the document lacks but a development server, and that "
        "the page's text is the copy's and ReDoc's labels; the page is a row without a file. "
        "The document is YAML, so the script reads its `info` itself: it names no licence, "
        "terms of service or contact.",
        f"The developer portal, {PORTAL_LINK}, is a fragment of {PORTAL_URL}, the portal's "
        "application shell, an empty page that a RequireJS application fills in the browser; "
        "it carries no documentation text and is a row without a file.",
        "The FAO Statistical Database Terms of Use are converted to Markdown with the "
        "standard library's `html.parser`: the page's content, its headings, paragraphs, "
        "lists, tables and links (made absolute) kept, a table with merged cells or a nested "
        "table kept as HTML, the site's header, navigation, breadcrumb, share buttons, footer "
        "and scripts dropped. The run stops on an element the converter does not know. The "
        "page is the terms themselves: every run checks that it prints each statement under "
        "Attribution, and the file's diff shows any other change.",
        "The bulk downloads' catalogue is open and kept verbatim; its description of the "
        "census dataset WCAD says census reports are \N{LEFT DOUBLE QUOTATION MARK}available "
        "in the public domain\N{RIGHT DOUBLE QUOTATION MARK}, which states nothing about the "
        "catalogue, so the check reads past the phrase. The four samples under `samples/` are "
        "answers of the API, kept verbatim, sent through the package's own client: its login, "
        "`auth_login` (`POST /auth/login`, the form fields `username` and `password`), runs "
        "once, inside the client's auth flow, before the first sample. A sample refused with "
        "HTTP 401 or 403 logs in once more and is sent again, once, inside that flow: no retry "
        "of the capture's own, which sends each sample once, and counted among its "
        "requests, as the login is. Their "
        "`metadata.processing_time` changes on every request, which `--check` disregards. "
        "They are structural samples; test fixtures are recorded separately.",
    )
)
"""``FETCHED.md``'s "How this is captured": what is converted, cut or left out, and why."""

ANNEX_1 = (
    (
        "https://app.amis-outlook.org/#/market-database/supply-and-demand-overview",
        "Agricultural Market Information Systems (AMIS)",
    ),
    ("https://www.fao.org/aid-monitor/en/", "AIDmonitor"),
    ("https://data-in-emergencies.fao.org/", "Data in Emergencies Hub (DIEM)"),
    (
        "https://www.fao.org/dad-is/data/en/",
        "Domestic Animal Diversity Information System (DAD-IS)",
    ),
    ("https://dataexplorer.fao.org/", "FAODATA Explorer"),
    (
        "https://www.fao.org/infoods/infoods/tables-and-databases/faoinfoods-databases/en/",
        "FAO/INFOODS Food Composition Databases",
    ),
    ("https://www.fao.org/fishery/en/fishstat", "Fisheries and Aquaculture (FishStat)"),
    (
        "https://www.fao.org/giews/food-prices/tool/public/",
        "Food Price Monitoring and Analysis (FPMA) Tool",
    ),
    ("https://empres-i.apps.fao.org/", "Global Animal Disease Information System (EMPRES-i +)"),
    ("https://fra-data.fao.org/assessments/fra/2020/", "Global Forest Resources Assessments (FRA)"),
    (
        "https://www.fao.org/gift-individual-food-consumption/en",
        "Global Individual Food Consumption (FAO/WHO GIFT)",
    ),
    (
        "https://www.fao.org/nr/water/aquastat/data/query/index.html?lang=en",
        "Global Information System on Water and Agriculture (AQUASTAT)",
    ),
    ("https://www.fao.org/hih-geospatial-platform/en", "Hand-in-Hand (HiH) Geospatial Platform"),
    ("https://data.apps.fao.org/wapor/?lang=en", "WaPOR"),
    (
        "https://www.fao.org/wiews/data/domains/monitoring-framework/en/",
        "World Information and Early Warning System on Plant Genetic Resources for Food and "
        "Agriculture (WIEWS)",
    ),
    ("https://www.fao.org/worldfoodsituation/foodpricesindex", "FAO Food Price Index"),
    ("https://www.fao.org/worldfoodsituation/csdb", "FAO Cereal Supply and Demand"),
)
"""The databases that Annex 1 of the terms links beside FAOSTAT, whose portal has its row,
each URL as linked and its name as the annex prints it."""

NOT_FETCHED = (
    NotFetched(
        REUSE_URL,
        "FAO's Terms and Conditions regarding the Reuse of Web content, which the terms page "
        "links and incorporates by reference: terms of the website, no API documentation; "
        "cited under Attribution",
    ),
    NotFetched(
        "https://creativecommons.org/licenses/by/4.0/legalcode.en",
        "the CC BY 4.0 licence, which the terms page links: a third-party licence, cited, "
        "not snapshotted; the terms quote its name",
    ),
    NotFetched(
        DEV_SERVER["url"],
        "the development server that the ReDoc page's copy of the document lists before the "
        "document's one, \N{LEFT DOUBLE QUOTATION MARK}available for testing purposes only on "
        "FAO network\N{RIGHT DOUBLE QUOTATION MARK}: an API server, no documentation",
    ),
    NotFetched(
        f"{BULK_BASE}/",
        "the folder of the ZIPs that the catalogue's `FileLocation` names, one per dataset: "
        "data, no documentation; `download_dataset` fetches one on a caller's request",
    ),
    *(
        NotFetched(url, f"{name}, a database that Annex 1 of the terms lists: no API documentation")
        for url, name in ANNEX_1
    ),
)
"""Every page the documentation links that the snapshot deliberately does not request."""

SNAPSHOT = Snapshot(
    name="FAOSTAT",
    slug="faostat",
    pages=(
        Page(SPEC_URL, SPEC_FILE),
        Page(DOCS_URL),
        Page(PORTAL_URL),
        Page(TERMS_URL, TERMS_FILE, terms=True),
        Page(CATALOGUE_URL, CATALOGUE_FILE),
        *(
            Page(f"{API_BASE}{sample.query}", sample.file, sample=True, keyed=True)
            for sample in SAMPLES
        ),
    ),
    attribution=ATTRIBUTION,
    not_fetched=NOT_FETCHED,
    vocabulary=VOCABULARY,
    capture=CAPTURE,
    out=ROOT / "docs" / "upstream",
    reduce=reduce,
    canonical=canonical,
    note=note,
    sections=sections,
    client=client,
    variables=(USERNAME_ENV, PASSWORD_ENV),
)
"""The snapshot: the document first, so that its checks run before any keyed call, and the
samples last, sent with the account by the package's client."""

if __name__ == "__main__":
    raise SystemExit(run(SNAPSHOT))
