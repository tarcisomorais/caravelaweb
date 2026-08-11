"""Fail-closed guard for the reusable-knowledge write freeze."""

from __future__ import annotations

import os
from pathlib import Path

from platform_adapter import safe_marker_stat


class KnowledgeWriteFrozenError(RuntimeError):
    """Reusable knowledge cannot be changed while the freeze is active."""


# Public names used by the rehearsal layer.  Keep the stricter legacy names as
# the implementation so symlinks and malformed marker objects remain blocked.
KnowledgeWriteFrozen = KnowledgeWriteFrozenError


def freeze_marker(root: str | Path) -> Path:
    return Path(root) / ".caravelaweb" / "knowledge-write-freeze"


def assert_knowledge_writes_allowed(root: str | Path) -> None:
    """Allow only a genuinely absent marker; every present state blocks."""
    marker = freeze_marker(root)
    try:
        marker_stat = os.lstat(marker)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise KnowledgeWriteFrozenError(
            f"knowledge write freeze state cannot be inspected: {marker}"
        ) from exc

    # A symlink, directory, device, or any unexpected object is deliberately
    # treated as frozen. Only absence means writes are allowed.
    kind = "regular marker" if safe_marker_stat(marker_stat) else "unexpected marker"
    raise KnowledgeWriteFrozenError(f"knowledge write freeze active ({kind}): {marker}")


def freeze_path(root: str | Path) -> Path:
    return freeze_marker(root)


def is_frozen(root: str | Path) -> bool:
    try:
        assert_knowledge_writes_allowed(root)
    except KnowledgeWriteFrozenError:
        return True
    return False


def enable_freeze(root: str | Path, *, reason: str) -> Path:
    marker = freeze_marker(root)
    marker.parent.mkdir(parents=True, exist_ok=True)
    if marker.exists() or marker.is_symlink():
        assert_knowledge_writes_allowed(root)
    marker.write_text(reason.strip() + "\n", encoding="utf-8")
    return marker


def disable_freeze(root: str | Path) -> None:
    marker = freeze_marker(root)
    if marker.is_symlink() or (marker.exists() and not marker.is_file()):
        raise KnowledgeWriteFrozenError(f"unsafe freeze marker: {marker}")
    marker.unlink(missing_ok=True)


def inferred_knowledge_root(db_path: str | Path) -> Path | None:
    path = Path(db_path)
    if path.parent.name != ".caravelaweb":
        return None
    return path.parent.parent
