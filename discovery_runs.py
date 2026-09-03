"""Run-scoped markers for bounded Discovery work."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from operational_memory.core import (
    RecordValidationError,
    is_canonical_target_id,
    normalize_capability_id,
    validate_timestamp,
)
from platform_adapter import safe_marker_stat


class DiscoveryRunError(ValueError):
    """A Discovery run marker is missing, invalid, or unavailable."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _identity(target: Any, capability: Any) -> tuple[str, str]:
    if not isinstance(target, str) or not is_canonical_target_id(target):
        raise DiscoveryRunError("Discovery target must be a stable lower-kebab target ID")
    try:
        capability = normalize_capability_id(capability)
    except RecordValidationError as exc:
        raise DiscoveryRunError(str(exc)) from exc
    return target, capability


def _directory(root: Path) -> Path:
    return root / ".caravelaweb" / "open-discovery"


def _marker(root: Path, run_id: str) -> Path:
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()
    return _directory(root) / f"{digest}.json"


def begin_discovery(
    root: Path, target: str, capability: str, *,
    run_id: str | None = None, opened_at: str | None = None,
) -> dict[str, str]:
    target, capability = _identity(target, capability)
    run_id = run_id or f"run:{target}:{uuid.uuid4()}"
    opened_at = opened_at or _now()
    if not isinstance(run_id, str) or not run_id.strip():
        raise DiscoveryRunError("Discovery run_id must be a non-empty string")
    try:
        validate_timestamp(opened_at, field="opened_at")
    except RecordValidationError as exc:
        raise DiscoveryRunError(str(exc)) from exc
    record = {
        "target": target, "capability": capability,
        "run_id": run_id, "opened_at": opened_at,
    }
    directory = _directory(root)
    marker = _marker(root, run_id)
    temporary = directory / f".{uuid.uuid4()}.tmp"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, marker)
    except OSError as exc:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise DiscoveryRunError("Discovery could not be registered in the Knowledge Root") from exc
    return record


def _open_marker(path: Path) -> str:
    """Read a run marker only if it is a regular, singly linked file."""
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        if not safe_marker_stat(os.fstat(fd)):
            raise DiscoveryRunError("Discovery run marker is not a regular file")
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = -1
            return stream.read()
    finally:
        if fd != -1:
            os.close(fd)


def _read_marker(path: Path) -> dict[str, str]:
    try:
        value = json.loads(_open_marker(path))
        if not isinstance(value, dict) or set(value) != {
            "target", "capability", "run_id", "opened_at",
        }:
            raise ValueError
        target, capability = _identity(value["target"], value["capability"])
        run_id, opened_at = value["run_id"], value["opened_at"]
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError
        validate_timestamp(opened_at, field="opened_at")
    except (OSError, ValueError, json.JSONDecodeError, RecordValidationError) as exc:
        raise DiscoveryRunError("Discovery run marker is invalid") from exc
    return {
        "target": target, "capability": capability,
        "run_id": run_id, "opened_at": opened_at,
    }


def require_open_discovery(
    root: Path, target: str, capability: str, run_id: Any,
) -> dict[str, str]:
    target, capability = _identity(target, capability)
    if not isinstance(run_id, str) or not run_id.strip():
        raise DiscoveryRunError("provenance.run_id must identify an open Discovery run")
    marker = _marker(root, run_id)
    try:
        stat = os.lstat(marker)
    except FileNotFoundError:
        raise DiscoveryRunError("no open Discovery marker matches provenance.run_id") from None
    if not safe_marker_stat(stat):
        raise DiscoveryRunError("Discovery run marker is invalid")
    record = _read_marker(marker)
    if (record["target"], record["capability"]) != (target, capability):
        raise DiscoveryRunError("the open Discovery marker belongs to another target or capability")
    return record


def close_discovery(root: Path, target: str, capability: str, run_id: str) -> None:
    require_open_discovery(root, target, capability, run_id)
    try:
        _marker(root, run_id).unlink()
    except OSError as exc:
        raise DiscoveryRunError("Discovery finalized, but its open marker could not be closed") from exc


def list_open_discoveries(
    root: Path, *, target: str | None = None, capability: str | None = None,
) -> list[dict[str, str]]:
    if capability is not None:
        try:
            capability = normalize_capability_id(capability)
        except RecordValidationError:
            return []
    records: list[dict[str, str]] = []
    try:
        paths = sorted(_directory(root).glob("*.json"))
    except OSError:
        return []
    for path in paths:
        try:
            record = _read_marker(path)
        except DiscoveryRunError:
            records.append({"status": "INVALID", "marker": path.name})
            continue
        if target is not None and record["target"] != target:
            continue
        if capability is not None and record["capability"] != capability:
            continue
        records.append(record)
    return records


__all__ = [
    "DiscoveryRunError", "begin_discovery", "close_discovery",
    "list_open_discoveries", "require_open_discovery",
]
