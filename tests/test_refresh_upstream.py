"""``scripts/refresh_upstream.py``'s ``FETCHED.md`` and its writing, offline.

Nothing here sends a request: ``render_fetched``, ``write_snapshot`` and ``compare`` take
what a capture run fetched, here one row made up for the test alone, written under
``tmp_path``, never to ``docs/upstream/``. ``OBSERVED.md`` is the one file under
``docs/upstream/`` written by hand (conventions §3, sdk-core ADR-0028), which the table
lists in a row of its own where it exists.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "refresh_upstream.py"
FETCHED = "2026-11-20T09:00:00Z"
HAND = "written by hand: what upstream does but never documents; not fetched or checked"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("refresh_upstream", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = load_script()


def a_row() -> object:
    """A row of a page kept byte for byte, as a capture run makes one."""
    response = script.Response(
        url="https://www.fao.org/faostat/en/docs/faostat_openapi.yaml",
        status=200,
        body=b"openapi: 3.0.0\n",
        etag=None,
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
