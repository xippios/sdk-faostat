"""``parse_bulk_csv``: a bulk dataset's ZIP, its normalized table read one row at a time.

The file kind ``bulk-csv``: the ZIP ``download_dataset`` writes, one per dataset of the
catalogue ``datasets_E.json``, whose ``FileLocation`` names it
(``<Name>_E_All_Data_(Normalized).zip``). It holds the dataset's normalized table, the
member ``<Name>_E_All_Data_(Normalized).csv``, beside small code lists
(``<Name>_E_AreaCodes.csv``, ``_Elements.csv``, ``_Flags.csv``, ``_ItemCodes.csv``; MDDW's
``_Indicators.csv`` and ``_Surveys.csv``), recorded on 2026-10-29
(``tests/fixtures/files/bulk-csv/``). The table is UTF-8 without a byte order mark,
comma-separated, every cell quoted but an empty one, lines ending in CRLF, a header row
and one row per value; its columns are the dataset's own. RL's, its first row cut short
here where it runs past the line::

    Area Code,Area Code (M49),Area,Item Code,Item,Element Code,Element,Year Code,Year,...
    "2","'004","Afghanistan","6600","Country area","5110","Area","1961","1961",...

its last four columns ``Unit``, ``Value``, ``Flag`` and ``Note`` (``"1000 ha"``,
``"65286.000000"``, ``"A"`` and an empty cell). MDDW's are ``Survey Code``, ``Survey``,
``Food Group Code``, ``Food Group``, ``Indicator Code``, ``Indicator``, ``Geographic
Level Code``, ``Geographic Level``, ``Element Code``, ``Element``, ``Unit``, ``Value``
and ``Flag``. Each row becomes a ``models.BulkRecord``, the
columns it names as fields and every other under its header in ``columns``, nothing
renamed or computed (ADR-0020 decision 2); ``Value`` is parsed as a ``Decimal`` where its
text is a number.

The member is chosen by its name, the one ending in ``_All_Data_(Normalized).csv``;
none, or more than one, is refused. It is read lazily from the archive through the
standard library, ``zipfile.ZipFile`` and ``io.TextIOWrapper(..., encoding="utf-8-sig",
newline="")`` under ``csv.DictReader``, headers as printed, as core's ``decode_csv`` reads
a path, its errors worded alike: ``decode_csv`` takes a path or a response, not an open
stream, and a decompressed copy on disk would write the whole table again, RL's 50 MB
from a ZIP of 3 MB and TCL's from one of 267 MB, before its first row could be read
(Johannes, G5 2026-10-29, second round, question 14; gap, row 125). Neither the archive
nor the table is ever held in memory whole.
"""

import csv
import io
import os
import zipfile
import zlib
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path

import pydantic
from xippios.core import ValidationError, parse

from xippios.faostat._client import SOURCE
from xippios.faostat.models import BulkRecord

__all__ = ["FILE_KIND", "MEMBER_SUFFIX", "parse_bulk_csv"]

FILE_KIND = "bulk-csv"
"""The file kind, named in a parse error and in the samples' directory."""

MEMBER_SUFFIX = "_All_Data_(Normalized).csv"
"""How the normalized table's member name ends, e.g.
``Inputs_LandUse_E_All_Data_(Normalized).csv``."""


def _refuse(name: str, reason: str) -> ValidationError:
    """A refusal worded as ``decode_csv`` words its own: ``"faostat: <file> <reason>"``."""
    return ValidationError(f"{SOURCE}: {name} {reason}", raw="", source=SOURCE)


@contextmanager
def _reading(archive: str, name: str) -> Iterator[None]:
    """Map what reading the archive and its table can raise to ``ValidationError``.

    ``archive`` names the ZIP, for a damaged archive; ``name`` the table being read, for
    text that is not UTF-8 or not CSV, as ``decode_csv`` names its file.
    """
    try:
        yield
    except UnicodeDecodeError as exc:
        raise _refuse(name, f"is not UTF-8 text: {exc.reason}") from None
    except csv.Error as exc:
        raise _refuse(name, f"is not CSV the csv module reads: {exc}") from None
    except (zipfile.BadZipFile, EOFError, zlib.error) as exc:
        raise _refuse(archive, f"is not a whole ZIP file: {exc}") from None


def _member(archive: zipfile.ZipFile, name: str) -> zipfile.ZipInfo:
    """The one member whose name ends in ``MEMBER_SUFFIX``.

    Raises:
        ValidationError: No member's name ends so, or more than one's does; the message
            names the members.
    """
    members = archive.infolist()
    tables = [member for member in members if member.filename.endswith(MEMBER_SUFFIX)]
    if len(tables) == 1:
        return tables[0]
    listed = ", ".join(member.filename for member in members) or "none"
    if not tables:
        reason = f"holds no member named *{MEMBER_SUFFIX}, the normalized table; its members: "
    else:
        reason = f"holds {len(tables)} members named *{MEMBER_SUFFIX}, not one: "
    raise _refuse(name, reason + listed)


def parse_bulk_csv(path: str | os.PathLike[str]) -> Generator[BulkRecord, None, None]:
    """Read a bulk dataset's ZIP row by row, each row of its normalized table one ``BulkRecord``.

    A generator: the archive is opened and its table read as the rows are taken, and
    both are closed when the generator ends or is closed; ``list(parse_bulk_csv(path))``
    reads it all, which for a large dataset (TCL's 17 million rows) is better left
    undone. The archive is checked first, before any row: a file that is not a ZIP, or
    one without exactly one member named ``*_All_Data_(Normalized).csv``, is refused at
    the first ``next``. A table with a header and no row, or an empty one, yields
    nothing.

    Args:
        path: The ZIP, e.g. ``result.data.path`` of ``download_dataset``, or
            ``"Inputs_LandUse_E_All_Data_(Normalized).zip"``.

    Raises:
        ValidationError: The file is not a whole ZIP file, holds no normalized table or
            more than one, its table's header names a column twice, a row has more or
            fewer values than the header, or the text is not UTF-8 or not CSV. Raised at
            the first ``next``, or at the row where it is found.
    """
    file = Path(path)
    with _reading(file.name, file.name), zipfile.ZipFile(file) as archive:
        member = _member(archive, file.name)
        table = f"{member.filename} in {file.name}"
        with (
            _reading(file.name, table),
            archive.open(member) as raw,
            io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text,
        ):
            records = csv.DictReader(text)
            header = records.fieldnames
            if header is None:
                return
            twice = sorted({column for column in header if header.count(column) > 1})
            if twice:
                raise _refuse(table, f"names a column twice in its header: {', '.join(twice)}")
            for line, record in enumerate(records, start=2):
                if None in record or None in record.values():
                    raise _refuse(
                        table, f"has a row, line {line}, whose values do not match its header"
                    )
                try:
                    yield BulkRecord.model_validate(record)
                except pydantic.ValidationError:
                    yield parse(
                        BulkRecord, record, source=SOURCE, endpoint=f"{FILE_KIND} line {line}"
                    )
