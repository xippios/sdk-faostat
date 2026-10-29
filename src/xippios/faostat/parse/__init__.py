"""File parsers, layer 1 beside ``api/``: one module per file kind (conventions §2, ADR-0020).

Each module has one function, ``parse_<file_kind>(path) -> list[Model]``; a parser's
library is this package's dependency, declared in ``pyproject.toml``, never core's.
"""
