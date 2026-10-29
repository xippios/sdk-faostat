"""``parse_bulk_csv`` on the ``bulk-csv`` samples, two ZIPs recorded on 2026-10-29.

The samples under ``tests/fixtures/files/bulk-csv/``: ``MDDW.zip``, MDDW's whole ZIP, the
response body of the recorded ``download_dataset/MDDW.json`` byte for byte, which the
first test checks, its normalized table with MDDW's own columns (surveys, food groups,
indicators, geographic levels) beside four code lists; and ``RL_first_rows.zip``, a new
ZIP holding RL's normalized table cut to its header and first rows, the production-shaped
header (area with its M49 code, item, element, year, unit, value, flag, note).
``tests/fixtures/files/README.md`` gives their provenance (ADR-0020 decision 6). The tests
assert the parser's shape against the samples' own text, read here with the standard
library's ``zipfile`` and ``csv``, never values or sizes typed into a test (conventions
§10). ``NOT RECORDED`` marks a sample changed in memory to show a refusal.
"""

import csv
import hashlib
import inspect
import io
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest
from xippios.core import ValidationError
from xippios.core.testing import load_fixture

from xippios.faostat.models import BulkRecord, DatasetsCatalogue
from xippios.faostat.parse import parse_bulk_csv
from xippios.faostat.parse.bulk_csv import MEMBER_SUFFIX

TESTS = Path(__file__).parent
FIXTURES = TESTS / "fixtures"
FILES = FIXTURES / "files"
SAMPLES = FILES / "bulk-csv"
MDDW = SAMPLES / "MDDW.zip"
RL = SAMPLES / "RL_first_rows.zip"
RECORDED = FIXTURES / "download_dataset" / "MDDW.json"
CATALOGUE = FIXTURES / "datasets_e" / "all.json"
ZIP_MAGIC = b"PK\x03\x04"
NAMED = {
    field.validation_alias: name
    for name, field in BulkRecord.model_fields.items()
    if isinstance(field.validation_alias, str)
}
"""The headers ``BulkRecord`` names, each to its field."""


def members_of(sample: Path) -> dict[str, bytes]:
    """Every member of a ZIP, by name, in the archive's order."""
    with zipfile.ZipFile(sample) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def table_name(sample: Path) -> str:
    """The name of the sample's normalized table."""
    [name] = [name for name in members_of(sample) if name.endswith(MEMBER_SUFFIX)]
    return name


def table_of(sample: Path) -> tuple[list[str], list[list[str]]]:
    """The header and the rows of the sample's normalized table, as the stdlib reads them."""
    text = members_of(sample)[table_name(sample)].decode("utf-8")
    header, *rows = csv.reader(io.StringIO(text, newline=""))
    return header, rows


def zipped(path: Path, members: dict[str, bytes]) -> Path:
    """A ZIP at ``path`` holding ``members``, deflated: a sample changed in memory."""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


def rl_lines() -> list[bytes]:
    """The lines of RL's sample table, as printed, CRLF-separated, the last one empty."""
    return members_of(RL)[table_name(RL)].split(b"\r\n")


def rl_with(path: Path, lines: list[bytes]) -> Path:
    """A ZIP at ``path`` holding RL's table with ``lines`` in place of its own."""
    return zipped(path, {table_name(RL): b"\r\n".join(lines)})


def provenance(readme: str, sample: Path) -> str:
    row = f"| `{sample.relative_to(FILES)}` |"
    assert row in readme, f"{sample.name} has its provenance row"
    return next(line for line in readme.splitlines() if line.startswith(row))


def test_samples_are_the_recorded_body_and_a_real_cut() -> None:
    readme = (FILES / "README.md").read_text(encoding="utf-8")
    fixture = load_fixture(RECORDED)
    body = fixture.response.content
    assert fixture.response.body_base64 is True, "a ZIP, recorded whole and flagged binary"
    assert MDDW.read_bytes() == body, "the sample is the recorded body, byte for byte"
    line = provenance(readme, MDDW)
    assert f"| {fixture.request.url} |" in line
    assert f"| {len(body)} | `{hashlib.sha256(body).hexdigest()}` |" in line
    catalogue = DatasetsCatalogue.model_validate_json(load_fixture(CATALOGUE).response.body)
    listed = {dataset.dataset_code: dataset for dataset in catalogue.datasets.dataset}
    assert fixture.request.url == listed["MDDW"].file_location
    assert f"| `{listed['MDDW'].date_update}` (DateUpdate) |" in line
    line = provenance(readme, RL)
    assert f"| {listed['RL'].file_location} |" in line, "the full file's URL"
    assert f"| `{listed['RL'].date_update}` (DateUpdate) |" in line
    assert f"first {len(table_of(RL)[1])} rows" in line, "the rows kept"
    assert list(members_of(RL)) == [table_name(RL)], "one member of the archive"
    for sample in (MDDW, RL):
        assert sample.read_bytes()[:4] == ZIP_MAGIC


@pytest.mark.parametrize("sample", [MDDW, RL], ids=["MDDW", "RL"])
def test_parse_bulk_csv_reads_every_row_as_printed(sample: Path) -> None:
    header, table = table_of(sample)
    others = [column for column in header if column not in NAMED]
    absent = [name for column, name in NAMED.items() if column not in header]
    rows = list(parse_bulk_csv(sample))
    assert len(rows) == len(table), "one row per data line, none dropped"
    for row, cells in zip(rows, table, strict=True):
        record = dict(zip(header, cells, strict=True))
        assert isinstance(row, BulkRecord)
        for column, text in record.items():
            if column == "Value":
                assert isinstance(row.value, Decimal)
                assert str(row.value) == text, "the number as printed, its decimals kept"
            elif column in NAMED:
                assert getattr(row, NAMED[column]) == text, column
        assert list(row.columns) == others, "the other columns, in the header's order"
        assert list(row.columns.values()) == [record[column] for column in others]
        assert all(getattr(row, name) is None for name in absent), "a column not printed"


def test_parse_bulk_csv_keeps_mddws_own_columns() -> None:
    """MDDW prints no area, item or year: those fields are ``None`` and its survey, food
    group, indicator and geographic level columns are kept under their headers."""
    header, _ = table_of(MDDW)
    rows = list(parse_bulk_csv(MDDW))
    assert {"Element Code", "Unit", "Value", "Flag"} <= set(header)
    assert {"Area Code", "Item Code", "Year", "Note"}.isdisjoint(header)
    assert all(row.area_code is None and row.year is None and row.note is None for row in rows)
    assert all(row.columns for row in rows)
    assert {column.removesuffix(" Code") for column in rows[0].columns} == {
        "Survey",
        "Food Group",
        "Indicator",
        "Geographic Level",
    }


def test_parse_bulk_csv_names_every_column_of_rl() -> None:
    """RL's header is the production shape: every column named, none in ``columns``; the
    M49 code as printed, with its leading apostrophe; ``Note`` printed empty."""
    header, table = table_of(RL)
    assert set(header) <= set(NAMED)
    assert "Item Code (CPC)" not in header
    rows = list(parse_bulk_csv(RL))
    assert all(row.columns == {} for row in rows)
    assert all(row.item_code_cpc is None for row in rows), "RL prints no CPC code"
    assert all((row.area_code_m49 or "").startswith("'") for row in rows), "'004, as printed"
    assert [row.note for row in rows] == [cells[header.index("Note")] for cells in table]


def test_parse_bulk_csv_is_a_generator(tmp_path: Path) -> None:
    rows = parse_bulk_csv(MDDW)
    assert inspect.isgenerator(rows)
    first = next(rows)
    rows.close()
    assert first == next(parse_bulk_csv(str(MDDW))), "a path as text works too"
    lines = rl_lines()
    header_only = rl_with(tmp_path / "header.zip", [lines[0], b""])
    assert list(parse_bulk_csv(header_only)) == [], "a header and no row yields nothing"
    empty = rl_with(tmp_path / "empty.zip", [b""])
    assert list(parse_bulk_csv(empty)) == [], "an empty table yields nothing"


def test_parse_bulk_csv_reads_an_empty_value_as_none(tmp_path: Path) -> None:
    """NOT RECORDED: RL's first row with its ``Value`` cell emptied in memory, as RL prints
    the values it flags ``L``, missing (85 rows on 2026-10-29)."""
    lines = rl_lines()
    header = lines[0].decode().split(",")
    cells = lines[1].split(b",")
    cells[header.index("Value")] = b""
    lines[1] = b",".join(cells)
    first = next(parse_bulk_csv(rl_with(tmp_path / "missing.zip", lines)))
    assert first.value is None
    assert first.flag == cells[header.index("Flag")].decode().strip('"')


def test_parse_bulk_csv_refuses_an_archive_without_a_normalized_table(tmp_path: Path) -> None:
    """NOT RECORDED: MDDW's four code lists alone, in a new ZIP."""
    lists = {name: data for name, data in members_of(MDDW).items() if name != table_name(MDDW)}
    path = zipped(tmp_path / "lists.zip", lists)
    with pytest.raises(ValidationError) as refused:
        next(parse_bulk_csv(path))
    assert str(refused.value) == (
        f"faostat: lists.zip holds no member named *{MEMBER_SUFFIX}, the normalized table; "
        f"its members: {', '.join(lists)}"
    )


def test_parse_bulk_csv_refuses_two_normalized_tables(tmp_path: Path) -> None:
    """NOT RECORDED: RL's table and MDDW's in one new ZIP."""
    path = zipped(
        tmp_path / "two.zip",
        {table_name(RL): members_of(RL)[table_name(RL)], table_name(MDDW): b""},
    )
    with pytest.raises(ValidationError, match=r"^faostat: two\.zip holds 2 members named "):
        next(parse_bulk_csv(path))


@pytest.mark.parametrize("cut", ["half", "table"])
def test_parse_bulk_csv_refuses_a_file_that_is_no_whole_zip(tmp_path: Path, cut: str) -> None:
    """NOT RECORDED: MDDW's ZIP cut to its first half, and RL's table on its own, no ZIP."""
    path = tmp_path / "cut.zip"
    data = MDDW.read_bytes()
    path.write_bytes(data[: len(data) // 2] if cut == "half" else members_of(RL)[table_name(RL)])
    with pytest.raises(ValidationError, match=r"^faostat: cut\.zip is not a whole ZIP file: "):
        next(parse_bulk_csv(path))


def test_parse_bulk_csv_refuses_a_damaged_member(tmp_path: Path) -> None:
    """NOT RECORDED: MDDW's ZIP with the first byte of its table's deflated data set, in
    memory, to a block type deflate does not have (RFC 1951: ``BTYPE`` 11); the archive's
    directory still reads, the table's first read does not."""
    data = bytearray(MDDW.read_bytes())
    with zipfile.ZipFile(MDDW) as archive:
        member = archive.getinfo(table_name(MDDW))
    assert member.compress_type == zipfile.ZIP_DEFLATED
    local = member.header_offset
    names = int.from_bytes(data[local + 26 : local + 28], "little")
    extra = int.from_bytes(data[local + 28 : local + 30], "little")
    data[local + 30 + names + extra] = 0b111
    path = tmp_path / "damaged.zip"
    path.write_bytes(bytes(data))
    with pytest.raises(ValidationError, match=r"^faostat: damaged\.zip is not a whole ZIP file: "):
        list(parse_bulk_csv(path))


def test_parse_bulk_csv_refuses_a_row_that_does_not_match_its_header(tmp_path: Path) -> None:
    """NOT RECORDED: RL's table with its second row's last two cells cut in memory."""
    lines = rl_lines()
    lines[2] = lines[2].rsplit(b",", 2)[0]
    rows = parse_bulk_csv(rl_with(tmp_path / "short.zip", lines))
    next(rows)
    with pytest.raises(ValidationError) as refused:
        next(rows)
    assert str(refused.value) == (
        f"faostat: {table_name(RL)} in short.zip has a row, line 3, whose values do not "
        "match its header"
    )


def test_parse_bulk_csv_refuses_a_header_naming_a_column_twice(tmp_path: Path) -> None:
    """NOT RECORDED: RL's header with ``Note`` renamed ``Flag`` in memory; a second
    ``Flag`` would drop the first."""
    lines = rl_lines()
    lines[0] = lines[0].replace(b",Note", b",Flag")
    with pytest.raises(ValidationError) as refused:
        next(parse_bulk_csv(rl_with(tmp_path / "twice.zip", lines)))
    assert str(refused.value) == (
        f"faostat: {table_name(RL)} in twice.zip names a column twice in its header: Flag"
    )


def test_parse_bulk_csv_refuses_text_that_is_not_utf8(tmp_path: Path) -> None:
    """NOT RECORDED: RL's rows repeated past 64 KiB, the last row with a byte that is no
    UTF-8, in memory: the header and first rows read, the decoder refuses it later."""
    lines = rl_lines()
    rows = [line for line in lines[1:] if line]
    body = rows * (64 * 1024 // len(b"\r\n".join(rows)) + 1)
    body[-1] = body[-1].replace(b'"Afghanistan"', b'"Afghan\xffistan"')
    read = parse_bulk_csv(rl_with(tmp_path / "latin.zip", [lines[0], *body, b""]))
    assert next(read).area is not None, "the header and first rows read"
    with pytest.raises(ValidationError) as refused:
        list(read)
    assert str(refused.value) == (
        f"faostat: {table_name(RL)} in latin.zip is not UTF-8 text: invalid start byte"
    )


def test_parse_bulk_csv_refuses_csv_the_csv_module_cannot_read(tmp_path: Path) -> None:
    """NOT RECORDED: RL's table with one ``Note`` cell made longer than the csv module's
    field limit (131,072 characters) in memory."""
    lines = rl_lines()
    lines[1] = lines[1] + b'"' + b"n" * (csv.field_size_limit() + 1) + b'"'
    with pytest.raises(ValidationError) as refused:
        list(parse_bulk_csv(rl_with(tmp_path / "wide.zip", lines)))
    assert str(refused.value) == (
        f"faostat: {table_name(RL)} in wide.zip is not CSV the csv module reads: field larger "
        f"than field limit ({csv.field_size_limit()})"
    )
