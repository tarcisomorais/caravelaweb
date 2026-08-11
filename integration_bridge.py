"""Internal read boundary behind `knowledge-lookup`, plus Phase 4A/4B legacy-to-OM mapping helpers.

Not an external product API. `KnowledgeLookupBoundary`/`LookupResult`/
`default_operational_memory_path` are permanent internal infrastructure for
the public `knowledge-lookup` CLI. `map_candidate_markdown` and
`promote_mapped_candidate` are migration-only, used by `phase4a_migration.py`
to reproduce the historical legacy-to-OM rebuild; they are not part of
current runtime operation.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from knowledge_write_freeze import assert_knowledge_writes_allowed
from read_authority import ReadAuthorityStateError, read_cutover_active
from write_authority import assert_legacy_write_authority

from operational_memory import MemoryError as OperationalMemoryError, SQLiteOperationalMemory


class BridgeError(Exception):
    """Base error for the Integration Bridge (see module docstring for scope)."""


class KnowledgeWriteAuthorityRequired(BridgeError):
    """A bridge write was attempted without explicit knowledge-write authority."""


class BridgeStaleBaseError(BridgeError):
    """The reviewed legacy profile no longer matches the promoted base."""


@dataclass(frozen=True)
class LookupResult:
    source: str
    target: str
    capability: str | None
    profile_path: str | None = None
    operational_context: Mapping[str, Any] | None = None
    markdown_projection: str | None = None


def _slug(value: str) -> str:
    value = value.strip().lower().replace("_", "-")
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "unknown"


def _clean_text(value: str) -> str:
    value = value.replace("`", "")
    return re.sub(r"\s+", " ", value).strip()


DEFAULT_OPERATIONAL_MEMORY_RELATIVE_PATH = Path(".caravelaweb") / "operational_memory.db"


def default_operational_memory_path(knowledge_root: str | Path) -> Path:
    """Future live Operational Memory location; Phase 3.5 does not create/populate it."""
    return Path(knowledge_root) / DEFAULT_OPERATIONAL_MEMORY_RELATIVE_PATH


class KnowledgeLookupBoundary:
    """Production read boundary with explicit pre-cutover legacy compatibility."""

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
        capability = _slug(capability) if capability else None
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


def _candidate_entries(section_text: str) -> list[str]:
    """Return complete numbered candidate statements, retaining indented detail."""
    entries: list[str] = []
    current: list[str] = []
    for raw in section_text.splitlines():
        match = re.match(r"^\s*\d+\.\s+(.+)$", raw)
        if match:
            if current:
                entries.append(_clean_text(" ".join(current)))
            current = [match.group(1).strip()]
            continue
        stripped = raw.strip()
        if current and stripped and stripped not in {"```", "---"}:
            current.append(stripped)
    if current:
        entries.append(_clean_text(" ".join(current)))
    if not entries:
        entries = [
            _clean_text(match.group(1))
            for raw in section_text.splitlines()
            if (match := re.match(r"^\s*-\s+(.+)$", raw))
        ]
    return entries


def _candidate_knowledge_root(path: Path) -> Path | None:
    resolved = path.resolve()
    for parent in resolved.parents:
        if parent.name == "candidates" and (parent.parent / "targets").is_dir():
            return parent.parent
    return None


def map_candidate_markdown(
    memory: SQLiteOperationalMemory,
    candidate_path: str | Path,
    *,
    recorded_at: str,
    knowledge_write_authority: bool,
    migration_provenance: Mapping[str, Any] | None = None,
    knowledge_root: str | Path | None = None,
) -> dict[str, Any]:
    """Temporary transition/migration support: map legacy candidate to pending Claims + Proposal."""
    if not knowledge_write_authority:
        raise KnowledgeWriteAuthorityRequired(
            "candidate capture requires explicit knowledge-write authority"
        )

    path = Path(candidate_path)
    freeze_root = knowledge_root or _candidate_knowledge_root(path) or memory.knowledge_root
    if freeze_root is not None:
        assert_legacy_write_authority(freeze_root)
        assert_knowledge_writes_allowed(freeze_root)
    text = path.read_text(encoding="utf-8")
    target_field_match = re.search(r"(?mi)^Target:\s*`?([^`\n]+)`?\s*$", text)
    target_match = re.search(r"(?m)^# Candidate Delta —\s*([^\n]+)$", text)
    capability_match = re.search(r"(?mi)^Capability:\s*\*\*([^*]+)\*\*", text)
    if capability_match is None:
        capability_match = re.search(r"(?mi)^Capability:\s*`?([^`\n]+)`?\s*$", text)
    if not target_match or not capability_match:
        raise BridgeError("candidate Markdown is missing target/capability identity")

    target = _slug(
        target_field_match.group(1) if target_field_match else target_match.group(1)
    )
    capability = _slug(capability_match.group(1))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    provenance = dict(migration_provenance or {})
    explicit_hosts = sorted(
        {
            hostname
            for raw_url in re.findall(r"https?://[^\s`<>)\]}]+", text)
            if (hostname := urlparse(raw_url.rstrip(".,;:'\"")).hostname)
        }
    )
    if len(explicit_hosts) > 1:
        raise BridgeError(
            "candidate structural host scope is ambiguous: "
            + ", ".join(explicit_hosts)
        )
    host_id = f"host:{target}:{_slug(explicit_hosts[0])}" if explicit_hosts else None
    if host_id is not None:
        compatible = memory._conn.execute(
            "SELECT 1 FROM hosts WHERE id=? AND target_id=?",
            (host_id, f"tgt:{target}"),
        ).fetchone()
        if compatible is None:
            raise BridgeError(
                f"candidate structural host scope is incompatible: {host_id}"
            )
    proposal_id = f"prop:{target}:{capability}:legacy-{digest[:12]}"
    claims: list[dict[str, Any]] = []

    for epistemic in ("OBSERVED", "INFERRED", "UNKNOWN"):
        section = re.search(
            rf"(?ms)^## {epistemic}\s*$([\s\S]*?)(?=^## |\Z)", text
        )
        if not section:
            continue
        for index, statement in enumerate(_candidate_entries(section.group(1)), start=1):
            family = "unknown" if epistemic == "UNKNOWN" else "constraint"
            if "route" in statement.lower() or "GET /" in statement:
                family = "entrypoint"
            claim_id = (
                f"clm:{target}:{capability}:{family}:candidate-"
                f"{epistemic.lower()}-{index}-{hashlib.sha256(statement.encode()).hexdigest()[:8]}"
            )
            claims.append(
                {
                    "id": claim_id,
                    "target_id": f"tgt:{target}",
                    "capability_id": f"cap:{target}:{capability}",
                    "host_id": host_id,
                    "family": family,
                    "epistemic": epistemic,
                    "value": {
                        "legacy_candidate_statement": statement,
                        "candidate_sha256": digest,
                        **provenance,
                    },
                    "proposal_id": proposal_id,
                    "recorded_at": recorded_at,
                }
            )

    if not claims:
        raise BridgeError(
            "candidate Markdown yielded no explicit OBSERVED/INFERRED/UNKNOWN claims"
        )

    with memory.write_transaction() as writer:
        for claim in claims:
            writer.claim(claim)
        writer.proposal(
            {
                "id": proposal_id,
                "target_id": f"tgt:{target}",
                "capability_id": f"cap:{target}:{capability}",
                "recorded_at": recorded_at,
                "claim_ids": [claim["id"] for claim in claims],
                "legacy_candidate_path": str(path),
                "legacy_candidate_sha256": digest,
                "structural_host_id": host_id,
                **provenance,
            }
        )

    return {
        "proposal_id": proposal_id,
        "claim_ids": sorted(claim["id"] for claim in claims),
        "host_id": host_id,
    }


def promote_mapped_candidate(
    memory: SQLiteOperationalMemory,
    *,
    target: str,
    capability: str,
    proposal_id: str,
    reviewed_base_sha256: str,
    current_base: bytes,
    recorded_at: str,
    knowledge_write_authority: bool,
    knowledge_root: str | Path | None = None,
) -> str:
    """Temporary transition/migration support: map explicit reviewed promotion to a Decision."""
    if not knowledge_write_authority:
        raise KnowledgeWriteAuthorityRequired(
            "promotion requires explicit knowledge-write authority"
        )
    freeze_root = knowledge_root or memory.knowledge_root
    if freeze_root is not None:
        assert_legacy_write_authority(freeze_root)
        assert_knowledge_writes_allowed(freeze_root)
    if hashlib.sha256(current_base).hexdigest() != reviewed_base_sha256.lower():
        raise BridgeStaleBaseError("reviewed legacy profile base is stale")

    pending = {
        item["proposal_id"]: item
        for item in memory.get_pending_candidates(
            target, capability, knowledge_time=recorded_at
        )
    }
    proposal = pending.get(proposal_id)
    if proposal is None:
        raise BridgeError("proposal is not pending at promotion time")

    compact = re.sub(r"[-:]", "", recorded_at)
    decision_id = (
        f"dec:{_slug(target)}:{_slug(capability)}:{compact}:bridge-promotion"
    )
    with memory.write_transaction() as writer:
        writer.decision(
            {
                "id": decision_id,
                "target_id": memory.resolve_target(target),
                "capability_id": memory.resolve_capability(target, capability),
                "action": "ACCEPT",
                "proposal_id": proposal_id,
                "claim_ids": proposal["claim_ids"],
                "effective_at": recorded_at,
                "recorded_at": recorded_at,
                "validity": {"valid_from": recorded_at, "valid_to": None},
                "rationale": (
                    "explicit Phase 3 bridge promotion after reviewed legacy candidate"
                ),
            }
        )
    return decision_id


__all__ = [
    "BridgeError",
    "BridgeStaleBaseError",
    "KnowledgeLookupBoundary",
    "KnowledgeWriteAuthorityRequired",
    "LookupResult",
    "default_operational_memory_path",
    "map_candidate_markdown",
    "promote_mapped_candidate",
]
