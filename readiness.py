"""Core readiness rules shared by `preflight` and `knowledge-lookup`.

`preflight` reports readiness and browser diagnostics; `knowledge-lookup`
reports readiness beside an accepted-knowledge answer, so one lookup call
tells the executor whether the installation still needs a first run. Both
read the status from `core_readiness` here, so there is one rule set and
one status string.

Browser probing stays in `scripts/preflight`. No browser state changes the
status, and the lookup path must not pay for a subprocess probe.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

from knowledge_write_freeze import freeze_marker
from operational_memory.core import SCHEMA_VERSION
from platform_adapter import (
    filesystem_class,
    knowledge_root_marker_present,
    platform_identity,
    resolve_knowledge_root,
    safe_marker_stat,
)
from read_authority import ReadAuthorityStateError, read_cutover_active
from write_authority import WriteAuthorityStateError, current_write_authority


def marker_state(path: Path) -> str:
    try:
        value = os.lstat(path)
    except FileNotFoundError:
        return "INACTIVE"
    except OSError:
        return "INVALID"
    return "ACTIVE" if safe_marker_stat(value) else "INVALID"


def memory_report(root: Path) -> tuple[dict[str, object], list[str]]:
    errors: list[str] = []
    db = root / ".caravelaweb" / "operational_memory.db"
    report: dict[str, object] = {
        "path": str(db),
        "present": db.is_file(),
        "openable": False,
        "schema_version": None,
        "expected_schema_version": SCHEMA_VERSION,
    }
    if report["present"]:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
            table_version = connection.execute(
                "SELECT schema_version FROM schema_metadata WHERE singleton=1"
            ).fetchone()
            pragma_version = connection.execute("PRAGMA user_version").fetchone()[0]
            report["schema_version"] = pragma_version
            report["openable"] = bool(
                table_version
                and table_version[0] == SCHEMA_VERSION
                and pragma_version == SCHEMA_VERSION
            )
        except (OSError, sqlite3.DatabaseError):
            pass
        finally:
            if connection is not None:
                connection.close()
    if not report["present"]:
        errors.append(f"Operational Memory database is absent: {db}")
    elif not report["openable"]:
        errors.append(
            f"Operational Memory database is unreadable or has the wrong schema; expected {SCHEMA_VERSION}: {db}"
        )

    report["freeze"] = marker_state(freeze_marker(root))
    try:
        report["read_authority"] = (
            "OPERATIONAL_MEMORY" if read_cutover_active(root) else "LEGACY"
        )
    except ReadAuthorityStateError:
        report["read_authority"] = "INVALID"
    try:
        report["write_authority"] = current_write_authority(root)
    except WriteAuthorityStateError:
        report["write_authority"] = "INVALID"

    if report["freeze"] != "INACTIVE":
        errors.append(f"knowledge write freeze is {str(report['freeze']).lower()}")
    if report["read_authority"] != "OPERATIONAL_MEMORY":
        errors.append(f"read-authority state is {report['read_authority']}")
    if report["write_authority"] != "OPERATIONAL_MEMORY":
        errors.append(f"write-authority state is {report['write_authority']}")
    report["ready"] = not errors
    return report, errors


def root_warning(
    root: Path, kind: str, *, platform_name: str | None = None
) -> str | None:
    if kind == "native-local":
        return None
    platform_name = platform_name or sys.platform
    value = str(root).replace("\\", "/").casefold()
    if platform_name == "win32" and (
        value.startswith("//wsl.localhost/") or value.startswith("//wsl$/")
    ):
        return (
            f"knowledge root {root} is boundary-crossing and deprecated: native "
            "Windows observed SQLite lock failures on WSL-hosted roots; move it "
            "to a native Windows path. This warning does not refuse the root."
        )
    if platform_name == "linux" and value.startswith("/mnt/"):
        return (
            f"knowledge root {root} is boundary-crossing: concurrent Windows and "
            "WSL2 writers produced an explicit SQLite disk I/O failure; do not "
            "access the same database from both runtimes concurrently and prefer "
            "a native Linux path. This warning does not refuse the root."
        )
    return (
        f"knowledge root {root} is {kind}; safety under this workload is "
        "unproven; prefer a path native to the running platform"
    )


def core_readiness(override: str | None) -> tuple[Path | None, dict[str, object]]:
    """Return the resolved Knowledge Root and the readiness core of the report."""
    identity = platform_identity()
    errors: list[str] = []
    warnings: list[str] = []
    if not identity["python_meets_floor"]:
        errors.append(f"Python {identity['python']} is below the required 3.11 floor")
    root = resolve_knowledge_root(override)
    root_report: dict[str, object] = {
        "path": str(root) if root else None,
        "marker_present": knowledge_root_marker_present(root) if root else False,
        "targets_present": bool(root),
        "filesystem_class": filesystem_class(root) if root else "unknown",
    }
    if root is None:
        errors.append(
            f"knowledge root is unresolved; expected {'.caravelaweb-knowledge-root'} and targets/"
        )
        memory: dict[str, object] = {"ready": False}
    else:
        if not root_report["marker_present"]:
            errors.append(f"knowledge-root marker is absent: {root}")
        if warning := root_warning(root, str(root_report["filesystem_class"])):
            warnings.append(warning)
        memory, memory_errors = memory_report(root)
        errors.extend(memory_errors)
    core = {
        "status": "READY" if not errors else "NOT_READY",
        "platform": identity,
        "knowledge_root": root_report,
        "operational_memory": memory,
        "warnings": warnings,
        "errors": errors,
    }
    return root, core


def readiness_status(override: str | None) -> str:
    """The status string `preflight` prints, without its browser diagnostics."""
    return str(core_readiness(override)[1]["status"])


__all__ = [
    "core_readiness",
    "marker_state",
    "memory_report",
    "readiness_status",
    "root_warning",
]
