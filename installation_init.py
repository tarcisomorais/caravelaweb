"""Fresh initialization for the honest NONE -> OPERATIONAL_MEMORY lifecycle.

It never fabricates prior authority, transition receipts, or an imported
knowledge corpus; it creates only the state a new installation requires.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from operational_memory import SQLiteOperationalMemory
from platform_adapter import (
    KNOWLEDGE_ROOT_MARKER,
    TARGETS_DIRECTORY,
    default_knowledge_root,
    validate_knowledge_root,
    write_configured_knowledge_root,
)
from read_authority import read_cutover_marker
from write_authority import FRESH_INSTALL_WRITE_AUTHORITY_KIND, write_authority_marker

STATE_DIRECTORY = ".caravelaweb"
_TOLERATED_STATE_RESIDUE = {"write-authority.lock"}
# targets/ is the required Knowledge Root corpus directory; candidates/ is a
# compatibility corpus input. Content in either means the location is not a
# fresh installation.
_LEGACY_INPUT_DIRECTORIES = (TARGETS_DIRECTORY, "candidates")


class InitializationRefusedError(RuntimeError):
    """The target location cannot be truthfully classified as uninitialized."""


@dataclass(frozen=True)
class InitializationResult:
    """A valid, fully created Knowledge Root, and whether it was remembered.

    ``remembered`` is False only when the installation itself succeeded but
    the separate, best-effort convenience write of the remembered-root
    pointer failed (e.g. an unwritable home directory). The installation is
    never rolled back for that: ``root`` is always genuinely valid here.
    """

    root: Path
    remembered: bool
    remember_error: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_new_marker(path: Path, text: str) -> None:
    """Create a brand-new regular file; refuse to follow a symlink or overwrite."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)


def assert_initializable(root: Path) -> None:
    """Fail closed unless ``root`` can be truthfully classified as uninitialized."""
    if root.exists() and not root.is_dir():
        raise InitializationRefusedError(f"initialization target is not a directory: {root}")
    marker = root / KNOWLEDGE_ROOT_MARKER
    if marker.exists() or marker.is_symlink():
        raise InitializationRefusedError(f"already an initialized knowledge root: {root}")
    for name in _LEGACY_INPUT_DIRECTORIES:
        candidate = root / name
        if not candidate.exists():
            continue
        if candidate.is_symlink() or not candidate.is_dir():
            raise InitializationRefusedError(f"{candidate} exists and is not a plain directory")
        if any(candidate.iterdir()):
            raise InitializationRefusedError(
                f"refusing to initialize: {candidate} already contains a knowledge corpus; "
                "fresh initialization must not repurpose existing or legacy knowledge"
            )
    state = root / STATE_DIRECTORY
    if state.exists():
        if state.is_symlink() or not state.is_dir():
            raise InitializationRefusedError(f"{state} exists and is not a plain directory")
        residue = sorted(
            entry.name for entry in state.iterdir() if entry.name not in _TOLERATED_STATE_RESIDUE
        )
        if residue:
            raise InitializationRefusedError(
                f"refusing to initialize: {state} already contains installation state "
                f"({', '.join(residue)})"
            )


def initialize_knowledge_root(knowledge_root: str | Path | None = None) -> InitializationResult:
    """Create a new Knowledge Root with fresh-install (NONE -> OPERATIONAL_MEMORY) provenance.

    With no explicit location, uses the recommended per-user default so a
    normal user does not need to make a technical decision. Either way, the
    resulting root is remembered as the default for future sessions -- unless
    that best-effort convenience write fails, in which case the (still fully
    valid) installation is reported with ``remembered=False`` rather than
    raised as a failure.
    """
    # Resolve uniformly for both branches: on Windows, an unresolved default
    # (built from %LOCALAPPDATA%) can be a short 8.3-alias path (observed on
    # GitHub-hosted windows-latest runners, e.g. "RUNNER~1"), which would
    # otherwise mismatch the canonical form the post-init self-check below
    # compares against and spuriously refuse a legitimate fresh install.
    root = (
        Path(knowledge_root).expanduser().resolve()
        if knowledge_root is not None
        else default_knowledge_root().resolve()
    )
    assert_initializable(root)
    created: list[Path] = []
    try:
        root.mkdir(parents=True, exist_ok=True)
        targets = root / TARGETS_DIRECTORY
        if not targets.exists():
            targets.mkdir()
        state = root / STATE_DIRECTORY
        state.mkdir(exist_ok=True)

        db_path = state / "operational_memory.db"
        with SQLiteOperationalMemory(db_path, create=True, knowledge_root=root):
            pass
        created.append(db_path)

        recorded_at = _now()

        read_marker = read_cutover_marker(root)
        _write_new_marker(read_marker, "active\n")
        created.append(read_marker)

        write_marker = write_authority_marker(root)
        # Deliberately no om_authoritative_writes/first_om_write/receipt
        # fields: those belong only to imported installations. A fresh
        # installation never runs that transition ceremony, and routine
        # Discovery writes never update this marker for either origin, so a
        # write count here would go stale and misrepresent real usage.
        payload = {
            "kind": FRESH_INSTALL_WRITE_AUTHORITY_KIND,
            "status": "ACTIVE",
            "write_authority": "OPERATIONAL_MEMORY",
            "previous_write_authority": "NONE",
            "initialized_at": recorded_at,
        }
        _write_new_marker(write_marker, json.dumps(payload, indent=2, sort_keys=True) + "\n")
        created.append(write_marker)

        root_marker = root / KNOWLEDGE_ROOT_MARKER
        _write_new_marker(
            root_marker,
            "CaravelaWeb Knowledge Root.\n"
            f"kind: fresh-install\ninitialized_at: {recorded_at}\n",
        )
        created.append(root_marker)
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise

    if validate_knowledge_root(root) != root:
        raise InitializationRefusedError(f"initialized root failed post-initialization validation: {root}")
    # The root itself is now valid and fully initialized; remembering it as
    # the default is a convenience on top, not part of the safety-gated
    # creation above. A failure here must not unwind the real, already-valid
    # installation -- report it instead of hiding or escalating it.
    try:
        write_configured_knowledge_root(root)
    except OSError as error:
        return InitializationResult(root=root, remembered=False, remember_error=str(error))
    return InitializationResult(root=root, remembered=True)


__all__ = [
    "InitializationRefusedError",
    "InitializationResult",
    "assert_initializable",
    "initialize_knowledge_root",
]
