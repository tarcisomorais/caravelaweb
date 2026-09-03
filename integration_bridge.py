"""Internal read boundary behind the public ``knowledge-lookup`` CLI."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from read_authority import ReadAuthorityStateError, read_cutover_active

from operational_memory import MemoryError as OperationalMemoryError, SQLiteOperationalMemory
from operational_memory.core import normalize_capability_id


class BridgeError(Exception):
    """The lookup boundary could not produce a trustworthy result."""


@dataclass(frozen=True)
class LookupResult:
    source: str
    target: str
    capability: str | None
    profile_path: str | None = None
    operational_context: Mapping[str, Any] | None = None
    markdown_projection: str | None = None


DEFAULT_OPERATIONAL_MEMORY_RELATIVE_PATH = Path(".caravelaweb") / "operational_memory.db"


def default_operational_memory_path(knowledge_root: str | Path) -> Path:
    """Return the installation-owned Operational Memory database path."""
    return Path(knowledge_root) / DEFAULT_OPERATIONAL_MEMORY_RELATIVE_PATH


class KnowledgeLookupBoundary:
    """Production read boundary with explicit diagnostic compatibility."""

    def __init__(self, legacy_root: str | Path, memory_db: str | Path | None = None):
        self.legacy_root = Path(legacy_root)
        self.memory_db = (
            Path(memory_db) if memory_db is not None else default_operational_memory_path(self.legacy_root)
        )

    def lookup(
        self,
        target: str,
        *,
        capability: str | None = None,
        use_operational_memory: bool = False,
        use_legacy: bool = False,
        caller_context: Mapping[str, Any] | None = None,
    ) -> LookupResult:
        target = target.removesuffix(".md")
        capability = normalize_capability_id(capability) if capability is not None else None
        if use_operational_memory and use_legacy:
            raise BridgeError("legacy and Operational Memory lookup modes are mutually exclusive")
        try:
            cutover_active = read_cutover_active(self.legacy_root)
        except ReadAuthorityStateError as error:
            raise BridgeError(str(error)) from error
        use_operational = use_operational_memory or (cutover_active and not use_legacy)
        if use_legacy or not use_operational:
            profile = self.legacy_root / "targets" / f"{target}.md"
            return LookupResult(
                source="legacy",
                target=target,
                capability=capability,
                profile_path=str(profile) if profile.is_file() else None,
            )
        try:
            with SQLiteOperationalMemory(self.memory_db, create=False) as memory:
                try:
                    target_id = memory.resolve_target(target)
                except KeyError:
                    return LookupResult(source="operational-memory", target=target, capability=capability)
                if capability:
                    # A valid OM database with no such capability is an honest
                    # absence. Keep this catch around identity resolution only;
                    # query/schema/database failures remain bridge_error.
                    try:
                        memory.resolve_capability(target, capability)
                    except KeyError:
                        return LookupResult(source="operational-memory", target=target, capability=capability)
                    context = memory.render_operational_context(target, capability, caller_context)
                    if not any(context["current"].values()):
                        return LookupResult(source="operational-memory", target=target, capability=capability)
                else:
                    keys = memory.list_capability_keys(target)
                    contexts = {}
                    for key in keys:
                        rendered = memory.render_operational_context(target, key, caller_context)
                        if any(rendered["current"].values()):
                            contexts[key] = rendered
                    context = {
                        "target_id": target_id,
                        "capabilities": contexts,
                        "caller_context": dict(caller_context or {}),
                        "history_included": False,
                    }
                markdown = memory.render_markdown(target)
        except (sqlite3.DatabaseError, json.JSONDecodeError, OperationalMemoryError) as error:
            raise BridgeError(f"Operational Memory query failed: {error}") from error
        return LookupResult(
            source="operational-memory",
            target=target,
            capability=capability,
            operational_context=context,
            markdown_projection=markdown,
        )

    def list_index(self) -> list[dict[str, Any]]:
        """Exact index of every target with its hosts and capability keys."""
        try:
            cutover_active = read_cutover_active(self.legacy_root)
        except ReadAuthorityStateError as error:
            raise BridgeError(str(error)) from error
        if not cutover_active:
            raise BridgeError("the legacy path has no index; Operational Memory is not active")
        try:
            with SQLiteOperationalMemory(self.memory_db, create=False) as memory:
                return memory.list_targets()
        except (sqlite3.DatabaseError, json.JSONDecodeError, OperationalMemoryError) as error:
            raise BridgeError(f"Operational Memory query failed: {error}") from error

__all__ = [
    "BridgeError",
    "KnowledgeLookupBoundary",
    "LookupResult",
    "default_operational_memory_path",
]
