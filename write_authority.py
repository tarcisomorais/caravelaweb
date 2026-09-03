"""Installation-owned write-authority state and transition lock."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from platform_adapter import safe_marker_stat

try:
    import fcntl
except ModuleNotFoundError:  # Native Windows.
    fcntl = None

WRITE_AUTHORITY_MARKER = ".caravelaweb/write-authority.json"
WRITE_AUTHORITY_LOCK = ".caravelaweb/write-authority.lock"

# Two legitimate write-authority origins share the same current operational
# state (OPERATIONAL_MEMORY) but must never be conflated: an imported
# installation truthfully had LEGACY authority before transition, while a
# fresh installation never did. Minting a MIGRATED_WRITE_AUTHORITY_KIND marker
# for a fresh install would fabricate provenance that never happened.
MIGRATED_WRITE_AUTHORITY_KIND = "phase4d-write-authority"
FRESH_INSTALL_WRITE_AUTHORITY_KIND = "fresh-install-write-authority"


class WriteAuthorityStateError(RuntimeError):
    """Write-authority state is malformed or incompatible with the operation."""


class AuthorityLockUnavailableError(RuntimeError):
    """The platform does not provide the maintenance-only authority lock."""


def write_authority_marker(root: str | Path) -> Path:
    return Path(root) / WRITE_AUTHORITY_MARKER


def write_authority_lock(root: str | Path) -> Path:
    return Path(root) / WRITE_AUTHORITY_LOCK


@contextmanager
def authority_lock(root: str | Path, *, exclusive: bool) -> Iterator[None]:
    if fcntl is None:
        raise AuthorityLockUnavailableError(
            "authority lock unavailable: fcntl is not available on this platform"
        )
    path = write_authority_lock(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield
    finally:
        os.close(descriptor)


def _read_marker(root: str | Path) -> dict[str, Any] | None:
    marker = write_authority_marker(root)
    try:
        stat = os.lstat(marker)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise WriteAuthorityStateError(
            f"write-authority state cannot be inspected: {marker}"
        ) from exc
    if not safe_marker_stat(stat):
        raise WriteAuthorityStateError(f"unsafe write-authority marker: {marker}")
    # Belt-and-braces: the lstat above refuses a symlink before the open;
    # this descriptor-first read refuses a swap that lands between the
    # lstat and the open (a TOCTOU race the path-based lstat cannot see).
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(marker, flags)
    except OSError as exc:
        raise WriteAuthorityStateError(f"unsafe write-authority marker: {marker}") from exc
    try:
        if not safe_marker_stat(os.fstat(fd)):
            raise WriteAuthorityStateError(f"unsafe write-authority marker: {marker}")
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = -1
            text = stream.read()
    finally:
        if fd != -1:
            os.close(fd)
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise WriteAuthorityStateError(f"invalid write-authority marker: {marker}") from exc
    kind = payload.get("kind")
    common_valid = (
        payload.get("status") == "ACTIVE"
        and payload.get("write_authority") == "OPERATIONAL_MEMORY"
    )
    if kind == MIGRATED_WRITE_AUTHORITY_KIND:
        # The imported-installation first-write ceremony is compatibility
        # provenance: it records whether that one-shot transition's first
        # OM-authoritative write was performed, not a running write count.
        # A fresh installation never went through that ceremony and must not
        # carry (or fake) these fields at all -- see FRESH_INSTALL_WRITE_AUTHORITY_KIND.
        writes = payload.get("om_authoritative_writes")
        first_write = payload.get("first_om_write")
        first_write_state_valid = (
            (writes == 0 and first_write == "NOT_PERFORMED")
            or (
                writes == 1
                and first_write == "PERFORMED"
                and isinstance(payload.get("first_om_write_receipt"), str)
                and isinstance(payload.get("first_om_write_receipt_sha256"), str)
            )
        )
        valid = (
            common_valid
            and payload.get("previous_write_authority") == "LEGACY"
            and first_write_state_valid
        )
    elif kind == FRESH_INSTALL_WRITE_AUTHORITY_KIND:
        valid = common_valid and payload.get("previous_write_authority") == "NONE"
    else:
        valid = False
    if not valid:
        raise WriteAuthorityStateError("inconsistent write-authority marker")
    return payload


def current_write_authority(root: str | Path) -> str:
    return "OPERATIONAL_MEMORY" if _read_marker(root) is not None else "LEGACY"


def assert_legacy_write_authority(root: str | Path) -> None:
    if current_write_authority(root) != "LEGACY":
        raise WriteAuthorityStateError(
            "legacy compatibility write refused: write authority is OPERATIONAL_MEMORY; "
            "automatic rollback to LEGACY is forbidden after the first OM-authoritative write"
        )


def automatic_legacy_rollback_allowed(root: str | Path) -> bool:
    """Return False once automatic rollback to LEGACY is no longer meaningful or safe.

    Only a historical migrated installation ever had LEGACY authority to roll
    back to; this is False before the first OM-authoritative write of that
    migration and permanently False after it. A fresh installation never had
    LEGACY authority in the first place, so there is nothing to roll back to
    and this is always False for it, regardless of how many OM writes have
    since happened.
    """
    payload = _read_marker(root)
    if payload is None:
        return True
    if payload.get("kind") != MIGRATED_WRITE_AUTHORITY_KIND:
        return False
    return payload["om_authoritative_writes"] == 0


def assert_automatic_legacy_rollback_allowed(root: str | Path) -> None:
    if not automatic_legacy_rollback_allowed(root):
        raise WriteAuthorityStateError(
            "automatic rollback to LEGACY is forbidden after the first "
            "OM-authoritative write; explicit reconciliation/repair is required"
        )


def assert_om_write_authority(root: str | Path) -> dict[str, Any]:
    payload = _read_marker(root)
    if payload is None:
        raise WriteAuthorityStateError(
            "OM-native write refused: write authority is LEGACY"
        )
    return payload


__all__ = [
    "FRESH_INSTALL_WRITE_AUTHORITY_KIND",
    "MIGRATED_WRITE_AUTHORITY_KIND",
    "WRITE_AUTHORITY_LOCK",
    "WRITE_AUTHORITY_MARKER",
    "AuthorityLockUnavailableError",
    "WriteAuthorityStateError",
    "assert_legacy_write_authority",
    "assert_automatic_legacy_rollback_allowed",
    "automatic_legacy_rollback_allowed",
    "assert_om_write_authority",
    "authority_lock",
    "current_write_authority",
    "write_authority_lock",
    "write_authority_marker",
]
