"""The capture script's declaration and its hooks on core's frame, offline: nothing is fetched.

``scripts/refresh_upstream.py`` declares its snapshot, ``SNAPSHOT``, to ``xippios.core.refresh``,
whose fetch, attribution check, ``FETCHED.md``, write and ``--check`` core's tests hold
(sdk-core ADR-0062), as core's family check holds the notes of ``OBSERVED.md`` (sdk-core
ADR-0044). What stays here is the script's own: its pages, the keyed samples among them, its
attribution and vocabulary, and its hooks, the converter of the terms page, the checks and the
notes of the pages' rows, the check of the OpenAPI document's ``info`` and the form in which
``--check`` compares a sample. A hook is handed an answer built from a file under
``docs/upstream/`` or from a literal of the page's shape, never one fetched.
"""

import ast
import importlib.util
import io
import json
import re
import tokenize
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from xippios.core.refresh import Page, Response, Row

from xippios.faostat._client import BASE_URL, PASSWORD_ENV, USERNAME_ENV, client

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "refresh_upstream.py"
UPSTREAM = ROOT / "docs" / "upstream"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("refresh_upstream", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = load_script()


def declared(url: str) -> Page:
    """The page that ``SNAPSHOT`` declares at ``url``."""
    pages: tuple[Page, ...] = script.SNAPSHOT.pages
    (found,) = [page for page in pages if page.url == url]
    return found


def answer(url: str, body: bytes) -> Response:
    """The answer at ``url`` with HTTP 200, as the frame hands it to a hook.

    The body is an input of the test, not an answer from FAOSTAT: a file under
    ``docs/upstream/`` as the snapshot keeps it, or a literal of the page's shape.
    """
    return Response(
        url=url,
        status=200,
        body=body,
        content_type=None,
        etag=None,
        last_modified=None,
        redirects=(),
    )


def kept(page: Page) -> Response:
    """The answer to ``page`` as the snapshot keeps its file under ``docs/upstream/``."""
    assert page.file is not None
    return answer(page.url, (UPSTREAM / page.file).read_bytes())


def noted(page: Page, response: Response) -> str:
    """The row's note that the script's ``note`` writes, its checks passed."""
    text: str = script.note(Row(page, response, response.body if page.file else None))
    return text


# --- the declaration -------------------------------------------------------------------


def test_the_snapshot_declares_its_pages_in_the_order_of_fetched_md() -> None:
    """The OpenAPI document, the ReDoc page, the portal's shell, the terms, the bulk
    catalogue, then the four samples; the ReDoc page and the shell are rows without a file."""
    snapshot = script.SNAPSHOT
    assert [(page.url, page.file) for page in snapshot.pages] == [
        (script.SPEC_URL, script.SPEC_FILE),
        (script.DOCS_URL, None),
        (script.PORTAL_URL, None),
        (script.TERMS_URL, script.TERMS_FILE),
        (script.CATALOGUE_URL, script.CATALOGUE_FILE),
        *((f"{BASE_URL}{sample.query}", sample.file) for sample in script.SAMPLES),
    ]
    assert (snapshot.name, snapshot.slug, snapshot.out) == ("FAOSTAT", "faostat", UPSTREAM)
    hooks = (snapshot.reduce, snapshot.note, snapshot.canonical)
    assert hooks == (script.reduce, script.note, script.canonical)


def test_the_four_samples_alone_are_keyed_and_sent_by_the_packages_client() -> None:
    """The package's client logs in with ``LoginAuth`` and sends the token to its base URL's
    origin alone, the samples' (conventions §3); the frame needs both variables set before
    it fetches anything, and ``--keyless`` leaves the samples out."""
    snapshot = script.SNAPSHOT
    keyed = [page for page in snapshot.pages if page.keyed]
    assert keyed == [page for page in snapshot.pages if page.sample]
    assert [page.file for page in keyed] == [sample.file for sample in script.SAMPLES]
    assert all(page.url.startswith(f"{BASE_URL}/") for page in keyed)
    assert snapshot.client is client
    assert snapshot.variables == (USERNAME_ENV, PASSWORD_ENV)


def test_the_attribution_stands_on_the_terms_page_which_is_the_terms() -> None:
    """Every statement is printed on the terms page, the one page marked ``terms``: each run
    checks that the page prints them all, and searches nothing else on it."""
    snapshot = script.SNAPSHOT
    assert [page.url for page in snapshot.pages if page.terms] == [script.TERMS_URL]
    assert [statement.text for statement in snapshot.attribution] == [
        script.COPYRIGHT,
        script.TERMS_NAME,
        script.LICENCE,
        script.CITATION,
        *script.TERMS_CLAUSES,
    ]
    for statement in snapshot.attribution:
        assert (statement.source, statement.link) == (script.TERMS_URL, None)
        assert statement.where


def test_the_vocabulary_reads_past_the_catalogues_public_domain() -> None:
    """The catalogue's description of the census dataset WCAD says census reports are
    "available in the public domain", which states nothing about the catalogue: the
    declaration's vocabulary holds the phrase as the kept catalogue prints it. The frame's
    check of it runs at a refresh, with its request alone (sdk-core ADR-0062, decision 9)."""
    kept_file = declared(script.CATALOGUE_URL).file
    assert kept_file is not None
    catalogue = (UPSTREAM / kept_file).read_text(encoding="utf-8")
    assert script.SNAPSHOT.vocabulary == script.VOCABULARY
    for phrase in script.VOCABULARY:
        assert phrase in catalogue
        assert "public domain" in phrase


def test_the_script_keeps_no_observed_notes() -> None:
    """The notes moved to ``OBSERVED.md``: neither the script nor its declaration holds them."""
    assert not hasattr(script, "OBSERVED")
    snapshot = script.SNAPSHOT
    declared_text = [
        *snapshot.capture,
        *(row.reason for row in snapshot.not_fetched),
        *(statement.text for statement in snapshot.attribution),
    ]
    text = " ".join(" ".join(declared_text).split())
    source = SCRIPT.read_text(encoding="utf-8")
    for note in ("observed in probes", "no_records"):
        assert note not in text
        assert note not in source


def page_of(url: str) -> str:
    """The page a link names: its fragment, which is never sent, and a trailing slash dropped."""
    return url.split("#", 1)[0].rstrip("/")


FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
"""A fenced block of Markdown, an example whose values are data, not notes."""
CODE_SPAN = re.compile(r"``[^`]*``|`[^`\n]*`")
"""A code span, a value as upstream prints it, ``"2025-12-31"`` say, which dates nothing."""
AMENDMENT = re.compile(r"amendment \d{4}-\d{2}-\d{2}")
"""An ADR's amendment cited by its date, which dates a record, not an observation."""
RECORDED = re.compile(r"recorded[^.;]{0,60}?\d{4}-\d{2}-\d{2}", re.IGNORECASE)
"""A recording's date, a fixture's provenance, which dates the file and not what it holds."""
DATE = re.compile(r".{0,40}\d{4}-\d{2}-\d{2}.{0,20}")
"""A date in running text, with the words around it for the failure's message."""
SIZE = re.compile(r".{0,40}\b\d[\d,.]* ?[KMG]B\b.{0,20}")
"""A size in kilobytes or more in running text, a file's or an answer's, which upstream
moves with each release, with the words around it for the failure's message."""
FAMILY_CAP = re.compile(r"\b64 KB\b")
"""The family's cap of an answer over MCP, a bound of core's and no size of upstream's."""
PACKAGE_TEXT = sorted(
    [
        *(ROOT / "src").rglob("*.py"),
        *(ROOT / "tests").glob("*.py"),
        *(ROOT / "scripts").glob("*.py"),
        ROOT / "README.md",
        ROOT / "CLAUDE.md",
    ],
    key=lambda path: path.relative_to(ROOT).as_posix(),
)
"""The package's own text: the docstrings and comments of its code, its tests and its scripts,
the README and CLAUDE.md."""


def prose(path: Path) -> str:
    """The text of ``path`` that a reader reads: a Python file's docstrings and comments.

    A string that stands as a statement of its own is a docstring, a module's, a class's, a
    function's or an attribute's; every other string is a value of the code, a date in it
    among them, which dates nothing.
    """
    text = path.read_text(encoding="utf-8")
    if path.suffix != ".py":
        return FENCE.sub("", text)
    strings = [
        node.value.value
        for node in ast.walk(ast.parse(text))
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    ]
    comments = [
        token.string
        for token in tokenize.generate_tokens(io.StringIO(text).readline)
        if token.type == tokenize.COMMENT
    ]
    return "\n".join([*strings, *comments])


@pytest.mark.parametrize(
    "path", PACKAGE_TEXT, ids=[path.relative_to(ROOT).as_posix() for path in PACKAGE_TEXT]
)
def test_no_dated_note_of_what_faostat_answered_stands_outside_observed_md(path: Path) -> None:
    """What FAOSTAT was seen to do stands in ``OBSERVED.md`` alone, each note with its probe.

    That no dated note of what upstream answered stands outside the file is the source's own
    test (conventions §3), so the package's text points to the notes and dates none, the
    tests' comments and docstrings included. A date in a code span or a fenced example is a
    value as printed, an amendment's date cites a record, and a recording's date is its
    fixture's provenance. A size of what upstream serves, which moves with each release, is
    such a note too, while the family's bound of an answer is none.
    ``src/xippios/faostat/reference/README.md``, the packaged tables' provenance, is read
    once https://github.com/xippios/sdk-faostat/pull/76 takes the dates out of its prose.
    """
    text = RECORDED.sub("", CODE_SPAN.sub("", prose(path)))
    running = AMENDMENT.sub("", " ".join(text.split()))
    assert DATE.findall(running) == []
    assert SIZE.findall(FAMILY_CAP.sub("", running)) == []


def test_the_record_lists_every_page_the_declaration_leaves_out() -> None:
    """``FETCHED.md``, as the last capture wrote it, holds a row of Not fetched for each page
    that the declaration leaves out, so that the record and the declaration agree until the
    next capture writes the record again (conventions §3)."""
    record = (UPSTREAM / "FETCHED.md").read_text(encoding="utf-8")
    table = record[record.index("## Not fetched") :]
    listed = {
        line.removeprefix("| ").split(" | ")[0]
        for line in table.splitlines()
        if line.startswith("| http")
    }
    declared = {row.url for row in script.SNAPSHOT.not_fetched}
    assert sorted(declared - listed) == []


def test_every_page_the_documentation_links_is_fetched_or_not_fetched() -> None:
    """The pages the documentation links, the terms' and the ReDoc copy's server among them,
    and the folder of the ZIPs the catalogue names: each is a page of the snapshot or a row
    of Not fetched, never both (conventions §3)."""
    snapshot = script.SNAPSHOT
    left_out = {page_of(row.url) for row in snapshot.not_fetched}
    fetched = {page_of(page.url) for page in snapshot.pages}
    assert not left_out & fetched
    terms = (UPSTREAM / script.TERMS_FILE).read_text(encoding="utf-8")
    linked = {page_of(url) for url in re.findall(r"\]\((https?://[^)\s]+)\)", terms)}
    linked |= {page_of(script.DEV_SERVER["url"]), page_of(f"{script.BULK_BASE}/")}
    assert len(linked) >= 19
    assert sorted(linked - fetched - left_out) == []


# --- the OpenAPI document and its info -------------------------------------------------


def test_the_documents_note_names_its_version_operations_and_server() -> None:
    page = declared(script.SPEC_URL)
    response = kept(page)
    operations = re.findall(r"^[ \t]+operationId:[ \t]*(\S+)", response.body.decode(), re.M)
    note = noted(page, response)
    assert f"OpenAPI 3.0.0, {len(operations)} operations by `operationId`" in note
    assert f"`servers` {BASE_URL}" in note
    assert "`info` names no licence, terms of service or contact" in note


def test_the_info_fields_are_the_three_the_conventions_name() -> None:
    """Conventions §3 and sdk-core ADR-0062, decision 10, name the fields of ``info``."""
    assert script.INFO_FIELDS == ("license", "termsOfService", "contact")


@pytest.mark.parametrize("term", ["license", "termsOfService", "contact"])
def test_an_info_that_names_a_licence_terms_or_a_contact_stops_the_run(term: str) -> None:
    """The frame reads the ``info`` of an API document in JSON alone (conventions §3), and
    FAOSTAT's is YAML: the script reads its ``info`` and stops on each of the three it names,
    before anything is written. The changed document is an input of the test, not an answer
    from FAOSTAT."""
    page = declared(script.SPEC_URL)
    text = (UPSTREAM / script.SPEC_FILE).read_text(encoding="utf-8")
    named = text.replace("\ninfo:\n", f"\ninfo:\n  {term}:\n    name: Example\n", 1)
    assert named != text
    with pytest.raises(SystemExit, match=rf"info` now names \['{term}'\]"):
        noted(page, answer(page.url, named.encode()))


def test_a_sample_whose_operation_the_document_lacks_stops_the_run_before_any_login() -> None:
    """The document comes first and the samples last, so a sample's operation that the
    document no longer holds stops the run before a keyed call is spent. The changed
    document is an input of the test, not an answer from FAOSTAT."""
    page = declared(script.SPEC_URL)
    text = (UPSTREAM / script.SPEC_FILE).read_text(encoding="utf-8")
    renamed = text.replace("operationId: get_dimensions\n", "operationId: get_dimension\n")
    assert renamed != text
    with pytest.raises(SystemExit, match="no `get_dimensions` at"):
        noted(page, answer(page.url, renamed.encode()))


# --- the catalogue and the samples -----------------------------------------------------


def test_the_catalogues_note_counts_its_datasets() -> None:
    page = declared(script.CATALOGUE_URL)
    response = kept(page)
    datasets = json.loads(response.body)["Datasets"]["Dataset"]
    note = noted(page, response)
    assert f"{len(datasets)} datasets under `Datasets.Dataset`" in note
    assert f"`FileLocation` under {script.BULK_BASE}/" in note


@pytest.mark.parametrize("sample", script.SAMPLES, ids=lambda sample: sample.operation)
def test_each_samples_note_names_its_operation_and_its_rows(sample: Any) -> None:
    page = declared(f"{BASE_URL}{sample.query}")
    response = kept(page)
    rows = json.loads(response.body)["data"]
    note = noted(page, response)
    assert note.startswith(f"`{sample.operation}` (`GET {sample.template}`)")
    assert f"{len(rows)} rows under `data`" in note


def test_the_data_samples_note_names_the_element_code_its_rows_print() -> None:
    """A data query filters by ``codes/element``'s code, and its rows print another."""
    (sample,) = [item for item in script.SAMPLES if item.operation == "get_data"]
    page = declared(f"{BASE_URL}{sample.query}")
    assert "the filter `element=2510` answers `Element Code` `5510`" in noted(page, kept(page))


def test_check_compares_a_sample_without_its_processing_time() -> None:
    """``metadata.processing_time`` changes on every request, so ``--check`` compares a
    sample without it; any other byte counts, and a file that is no sample is compared as
    written. The changed bytes are an input of the test, not an answer from FAOSTAT."""
    page = declared(f"{BASE_URL}{script.SAMPLES[1].query}")
    assert page.file is not None
    content = (UPSTREAM / page.file).read_bytes()
    timed = re.sub(rb'"processing_time": ?\d+', b'"processing_time": 98765', content, count=1)
    assert timed != content
    assert script.canonical(page, timed) == script.canonical(page, content)
    other = content.replace(b'"PRODUCTION"', b'"DEVELOPMENT"')
    assert other != content
    assert script.canonical(page, other) != script.canonical(page, content)
    assert script.canonical(declared(script.SPEC_URL), timed) == timed


# --- the terms page and the portal's shell ---------------------------------------------

TERMS_PAGE = (
    "<html><body><header><nav>FAO</nav></header>"
    '<div data-sf-element="Container">'
    '<div class="sfContentBlock"><h2 class="page-title">FAO Statistical Database Terms of Use'
    '</h2><p>Under <strong>CC BY 4.0</strong> and the <a href="/contact-us/terms/en/">Terms'
    "</a>.</p></div>"
    '<div class="sfContentBlock"><h3>Annex 1</h3><ul><li>FAOSTAT</li><li>AQUASTAT</li></ul>'
    '<table><tr><td rowspan="2">a</td><td>b</td></tr><tr><td>c</td></tr></table></div>'
    "</div><footer>\N{COPYRIGHT SIGN} FAO 2026</footer></body></html>"
)
"""A page of the terms page's shape; the page is an input of the test, not an answer from
FAOSTAT."""

TERMS_MARKDOWN = """\
# FAO Statistical Database Terms of Use

Converted from https://www.fao.org/contact-us/terms/db-terms-of-use/en/ by
`scripts/refresh_upstream.py`; see `../FETCHED.md`.

Under **CC BY 4.0** and the [Terms](https://www.fao.org/contact-us/terms/en/).

### Annex 1

- FAOSTAT
- AQUASTAT

<table><tr><td rowspan="2">a</td><td>b</td></tr><tr><td>c</td></tr></table>
"""


def test_the_converter_writes_the_terms_pages_content_as_markdown() -> None:
    """The content blocks of the page's container, its links made absolute, the site's
    header and footer dropped; a table with merged cells stays HTML, and the note counts it.
    The page is an input of the test, not an answer from FAOSTAT."""
    page = declared(script.TERMS_URL)
    response = answer(page.url, TERMS_PAGE.encode())
    content = script.reduce(page, response)
    assert content.decode() == TERMS_MARKDOWN
    note = script.note(Row(page, response, content))
    assert "1 table with merged cells kept as HTML" in note


def test_the_converter_stops_on_an_element_it_does_not_convert() -> None:
    """The page is an input of the test, not an answer from FAOSTAT."""
    page = declared(script.TERMS_URL)
    form = TERMS_PAGE.replace("<ul>", "<form><ul>").replace("</ul>", "</ul></form>")
    with pytest.raises(SystemExit, match="a <form> block the script does not convert"):
        script.reduce(page, answer(page.url, form.encode()))


SHELL = (
    "<html><head><title>FAOSTAT</title>"
    '<script data-main="js/main" src="js/require.min.js"></script></head><body></body></html>'
)
"""A page of the portal's shape; the page is an input of the test, not an answer from
FAOSTAT."""


def test_the_portal_is_an_empty_shell_that_requirejs_draws() -> None:
    """The page is an input of the test, not an answer from FAOSTAT."""
    page = declared(script.PORTAL_URL)
    assert "(`data-main` `js/main`)" in noted(page, answer(page.url, SHELL.encode()))
    drawn = SHELL.replace("<body></body>", "<body><p>Data</p></body>")
    with pytest.raises(SystemExit, match="the <body> is no longer empty"):
        noted(page, answer(page.url, drawn.encode()))


def test_the_redoc_page_is_checked_against_the_document_in_sections() -> None:
    """The check of one page against another runs in ``sections``, which sees every row."""
    assert script.SNAPSHOT.sections is script.sections
    assert not hasattr(script, "_READ"), "no page kept between two hooks"
    assert not hasattr(script, "load_json"), "core's parse_json reads a JSON answer"


def redoc_page(paths: dict[str, Any]) -> bytes:
    """A ReDoc page of the recorded shape embedding a copy of the document with ``paths``.

    The page is an input of the test, not an answer from FAOSTAT: the snapshot keeps no file
    of the ReDoc page, so its shape is written from the script's own constants.
    """
    spec = {"servers": [script.DEV_SERVER, script.PROD_SERVER], "paths": paths}
    state = json.dumps({"spec": {"data": spec}})
    return (
        '<script src="https://cdn.redocly.com/redoc/v2.1.5/bundles/redoc.standalone.js">'
        f"</script><script>const __redoc_state = {state};\n"
        "Redoc.hydrate(__redoc_state, container);</script>"
    ).encode()


def read_rows(redoc: bytes) -> list[Row]:
    """The document's row as kept and the ReDoc page's row with ``redoc``, for ``sections``."""
    document = declared(script.SPEC_URL)
    docs = declared(script.DOCS_URL)
    return [
        Row(document, kept(document), kept(document).body),
        Row(docs, answer(script.DOCS_URL, redoc), None),
    ]


@pytest.mark.parametrize("missing", ["SPEC_URL", "DOCS_URL"])
def test_sections_stops_where_a_row_it_compares_is_missing(missing: str) -> None:
    """A check that cannot run does not read as one that passed."""
    rows = [row for row in read_rows(redoc_page({})) if row.page.url != getattr(script, missing)]
    with pytest.raises(SystemExit, match="Nothing was written"):
        script.sections(rows)


def test_sections_stops_where_the_redoc_copy_names_an_operation_the_document_lacks() -> None:
    copy = {"/x": {"get": {"operationId": "not_in_the_document"}}}
    with pytest.raises(SystemExit, match=r"operations are not the document's|the document lacks"):
        script.sections(read_rows(redoc_page(copy)))
