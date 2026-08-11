"""Production Operational Memory core for CaravelaWeb v0.4."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .core import (
    EPISTEMIC_CLASSES,
    CorrectionScopeAmbiguityError,
    DatabaseOpenError,
    MemoryError,
    RecordValidationError,
    SchemaVersionError,
    SQLiteOperationalMemory as _SQLiteOperationalMemory,
    canonical_json,
    validate_timestamp,
)


class SQLiteOperationalMemory(_SQLiteOperationalMemory):
    """Internal package boundary with explicit open/corruption error classification.

    Not an external CaravelaWeb product API; see `core.SQLiteOperationalMemory`.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        clock: Callable[[], str] | None = None,
        create: bool = True,
        knowledge_root: str | Path | None = None,
    ) -> None:
        try:
            super().__init__(db_path, clock=clock, create=create, knowledge_root=knowledge_root)
        except SchemaVersionError as exc:
            if str(exc) == "database is not an Operational Memory schema":
                raise DatabaseOpenError(f"not a valid SQLite Operational Memory database: {db_path}") from exc
            raise


__all__ = [
    "EPISTEMIC_CLASSES",
    "CorrectionScopeAmbiguityError",
    "DatabaseOpenError",
    "MemoryError",
    "RecordValidationError",
    "SchemaVersionError",
    "SQLiteOperationalMemory",
    "canonical_json",
    "validate_timestamp",
]
