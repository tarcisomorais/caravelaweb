"""Small installation-owned marker for Operational Memory read authority."""

from __future__ import annotations

import os
from pathlib import Path

from platform_adapter import safe_marker_stat


READ_CUTOVER_MARKER = ".caravelaweb/read-authority-operational-memory"


class ReadAuthorityStateError(RuntimeError):
    """The read-authority marker is malformed or cannot be inspected."""


def read_cutover_marker(root: str | Path) -> Path:
    return Path(root) / READ_CUTOVER_MARKER


def read_cutover_active(root: str | Path) -> bool:
    marker = read_cutover_marker(root)
    try:
        marker_stat = os.lstat(marker)
    except FileNotFoundError:
        return False
    except OSError as error:
        raise ReadAuthorityStateError(f"read-authority state cannot be inspected: {marker}") from error
    if not safe_marker_stat(marker_stat):
        raise ReadAuthorityStateError(f"unsafe read-authority marker: {marker}")
    return True


__all__ = ["READ_CUTOVER_MARKER", "ReadAuthorityStateError", "read_cutover_active", "read_cutover_marker"]
