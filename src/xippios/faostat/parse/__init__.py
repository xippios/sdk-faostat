"""File parsers, layer 1 beside ``api/``: one module per file kind (conventions §2).

Each module has one function, ``parse_<file_kind>(path) -> list[Model]``, or an iterator
of models for a bulk file kind (sdk-core ADR-0020); a parser's library is this package's
dependency, declared in ``pyproject.toml``, never core's. ``bulk_csv`` reads the file kind
``bulk-csv``, a bulk dataset's ZIP, its normalized table row by row (``parse_bulk_csv``, a
generator) through core's ``decode_csv``.
"""

from xippios.faostat.parse.bulk_csv import parse_bulk_csv

__all__ = ["parse_bulk_csv"]
