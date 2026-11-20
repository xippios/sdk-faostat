"""``scripts/refresh_upstream.py``'s ``FETCHED.md`` and the notes of ``OBSERVED.md``, offline.

Nothing here sends a request: ``render_fetched``, ``write_snapshot`` and ``compare`` take
what a capture run fetched, here one row made up for the test alone, written under
``tmp_path``, never to ``docs/upstream/``. ``OBSERVED.md`` is the one file under
``docs/upstream/`` written by hand (conventions §3, sdk-core ADR-0028), which the table
lists in a row of its own where it exists. The committed ``FETCHED.md`` and
``OBSERVED.md`` are read as they stand: the script's text is the committed text, which a
``--check`` would compare after a request to every page, and each note of ``OBSERVED.md``
is a ``###`` section whose last paragraph, ``Probe:``, names its date, its operation and
its sample, every file it cites present.
"""

import importlib.util
import re
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "refresh_upstream.py"
UPSTREAM = ROOT / "docs" / "upstream"
OBSERVED = UPSTREAM / "OBSERVED.md"
FETCHED = "2026-11-20T09:00:00Z"
HAND = "written by hand: what upstream does but never documents; not fetched or checked"
DATE = re.compile(r"\b20\d\d-\d\d-\d\d\b")
CITED = re.compile(r"`((?:tests|docs|src)/[^`\s]+\.[a-z]+)`")
REQUEST = re.compile(r"`GET [^`]+`")
FILES = "## Files and pages"
LEFT_OUT = "## Not fetched"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("refresh_upstream", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = load_script()


def a_row(etag: str | None = None) -> object:
    """A row of a page kept byte for byte, as a capture run makes one."""
    response = script.Response(
        url="https://www.fao.org/faostat/en/docs/faostat_openapi.yaml",
        status=200,
        body=b"openapi: 3.0.0\n",
        etag=etag,
        last_modified=None,
        redirects=(),
    )
    page = script.Page(response.url, "openapi/faostat_openapi.yaml", note="a note")
    return script.Row(page, response, response.body)


def render(*, observed: bool) -> str:
    text: str = script.render_fetched([a_row()], FETCHED, observed=observed)
    return text


def test_fetched_md_lists_observed_md_in_a_row_of_its_own() -> None:
    """Once ``OBSERVED.md`` exists, the table lists it as written by hand."""
    text = render(observed=True)
    row = f"| {script.OBSERVED_FILE} | - | - | - | - | - | - | - | {HAND} |"
    assert row in text.splitlines()
    assert f"edited by hand but `{script.OBSERVED_FILE}`" in " ".join(text.split())


def test_fetched_md_names_no_observed_md_while_there_is_none() -> None:
    text = render(observed=False)
    assert script.OBSERVED_FILE not in text
    assert "nothing here is edited by hand." in " ".join(text.split())


def test_fetched_md_cites_the_standing_record_of_sdk_core() -> None:
    """The sentences the script writes cite sdk-core's record as it stands at core 0.4.0,
    sdk-core ADR-0028, which restates sdk-core ADR-0003, by the repository's name."""
    text = " ".join(render(observed=False).split())
    assert text.count("(sdk-core ADR-0028)") == 2
    assert "ADR-0003" not in text


def test_a_snapshot_leaves_observed_md_as_written_and_check_reads_it(tmp_path: Path) -> None:
    """The run writes its files and ``FETCHED.md`` and never touches the notes, and
    ``--check`` renders the table with their row where the file exists."""
    notes = tmp_path / script.OBSERVED_FILE
    notes.write_text("# What FAOSTAT does but never documents\n", encoding="utf-8")
    (tmp_path / "FETCHED.md").write_text("old\n", encoding="utf-8")
    script.write_snapshot(tmp_path, [a_row()], render(observed=True))
    assert notes.read_text(encoding="utf-8") == "# What FAOSTAT does but never documents\n"
    assert (tmp_path / "openapi/faostat_openapi.yaml").read_bytes() == b"openapi: 3.0.0\n"
    assert script.compare(tmp_path, [a_row()]) == []
    notes.unlink()
    assert script.compare(tmp_path, [a_row()]) == ["FETCHED.md"], "the row of a file now gone"


def test_the_script_keeps_no_observed_notes() -> None:
    """The notes moved to ``OBSERVED.md``: the script neither holds nor prints them."""
    assert not hasattr(script, "OBSERVED")
    text = " ".join(render(observed=True).split())
    assert "observed in probes" not in text
    assert "no_records" not in text


def test_a_page_left_out_has_a_row_in_not_fetched() -> None:
    """Each page the snapshot cites and never requests, with its reason (conventions §3)."""
    lines = render(observed=True).splitlines()
    start = lines.index(LEFT_OUT)
    assert lines[start + 2 : start + 4] == [
        "| URL | HTTP | Redirects to | Reason |",
        "| --- | --- | --- | --- |",
    ]
    rows = [f"| {page.url} | (not requested) | - | {page.reason} |" for page in script.NOT_FETCHED]
    assert lines[start + 4 : start + 4 + len(rows)] == rows
    assert lines.index(f"| {script.OBSERVED_FILE} | - | - | - | - | - | - | - | {HAND} |") < start
    assert lines[-1].startswith("Regenerate")


def page(url: str) -> str:
    """The page a link names: its fragment, which is never sent, and a trailing slash dropped."""
    return url.split("#", 1)[0].rstrip("/")


def test_every_page_the_documentation_links_is_fetched_or_not_fetched() -> None:
    """The pages the documentation links, the terms' and the ReDoc copy's server among them,
    and the folder of the ZIPs the catalogue names: each is fetched or a row of Not fetched,
    never both (conventions §3)."""
    left_out = {page(row.url) for row in script.NOT_FETCHED}
    fetched = {page(url) for url in (script.SPEC_URL, script.DOCS_URL, script.PORTAL_URL)}
    fetched |= {page(script.TERMS_URL), page(script.CATALOGUE_URL)}
    assert not left_out & fetched
    terms = (UPSTREAM / script.TERMS_FILE).read_text(encoding="utf-8")
    linked = {page(url) for url in re.findall(r"\]\((https?://[^)\s]+)\)", terms)}
    linked |= {page(script.DEV_SERVER["url"]), page(f"{script.BULK_BASE}/")}
    assert len(linked) >= 19
    assert sorted(linked - fetched - left_out) == []


def test_the_committed_fetched_md_is_the_scripts_text() -> None:
    """What ``--check`` compares beside the rows: the prose above the table and the table
    ``Not fetched`` below it are the script's, and the table lists ``OBSERVED.md``."""
    committed = (UPSTREAM / "FETCHED.md").read_text(encoding="utf-8")
    rendered = script.render_fetched([], FETCHED, observed=True)
    assert committed.split(FILES)[0] == rendered.split(FILES)[0]
    assert committed[committed.index(LEFT_OUT) :] == rendered[rendered.index(LEFT_OUT) :]
    row = f"| {script.OBSERVED_FILE} | - | - | - | - | - | - | - | {HAND} |"
    assert row in committed.splitlines()


def notes() -> dict[str, list[str]]:
    """Each ``###`` note of ``OBSERVED.md``: its heading and its paragraphs, each joined."""
    parts = re.split(r"^(##|###) (.+)$", OBSERVED.read_text(encoding="utf-8"), flags=re.M)
    return {
        heading: [" ".join(block.split()) for block in body.split("\n\n") if block.strip()]
        for level, heading, body in zip(parts[1::3], parts[2::3], parts[3::3], strict=True)
        if level == "###"
    }


def test_every_note_ends_with_its_probe_its_date_and_its_operation() -> None:
    spec = (UPSTREAM / "openapi" / "faostat_openapi.yaml").read_text(encoding="utf-8")
    operations = set(re.findall(r"operationId:\s*(\S+)", spec))
    found = notes()
    assert len(found) >= 12
    for heading, paragraphs in found.items():
        probe = paragraphs[-1]
        assert probe.startswith("Probe: "), heading
        assert DATE.search(probe), heading
        named = set(re.findall(r"`(\w+)`", probe)) & operations
        assert named or REQUEST.search(probe), heading


def test_every_file_a_note_cites_exists() -> None:
    cited = set(CITED.findall(OBSERVED.read_text(encoding="utf-8")))
    assert cited
    assert sorted(path for path in cited if not (ROOT / path).is_file()) == []


def etag_cell(etag: str | None) -> str:
    """The ETag cell the renderer writes for a row whose response sent ``etag``."""
    for line in script.render_fetched([a_row(etag)], FETCHED).splitlines():
        cells = script._cells(line)
        if cells:
            return str(cells[6])
    raise AssertionError("render_fetched wrote no row")


def test_a_rows_etag_stands_in_a_code_span() -> None:
    """An ETag is no commit: its cell holds it as sent, quotes included, in a code span,
    and a row without one keeps ``-``."""
    assert etag_cell('"abc123"') == '`"abc123"`'
    assert etag_cell(None) == "-"


def test_the_committed_etags_are_the_renderers_cells() -> None:
    """Each ETag cell of the committed table is what the renderer writes for its ETag."""
    text = (UPSTREAM / "FETCHED.md").read_text(encoding="utf-8")
    cells = [row[6] for row in map(script._cells, text.splitlines()) if row]
    assert any(cell != "-" for cell in cells)
    for cell in cells:
        assert cell == etag_cell(None if cell == "-" else cell.strip("`"))
