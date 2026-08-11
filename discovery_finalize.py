"""Close a bounded Discovery by capturing only reusable operational knowledge.

This is intentionally a small adapter over :func:`capture_candidate`: it
normalizes Discovery output, removes knowledge already represented in OM, and
lets the native write boundary own Claim/Proposal validation and transaction.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from om_native_writes import (
    WRITE_DESTINATION, capture_candidate, enrich_candidate, promote_candidate,
    replace_candidate, review_token,
)
from operational_memory.core import EPISTEMIC_CLASSES, SQLiteOperationalMemory, validate_timestamp
from transport_policy import PLATFORM_UNSUPPORTED


class DiscoveryFinalizationError(ValueError):
    """Discovery output is incomplete, non-reusable, or unsafe to retain."""


OPERATIONAL_FAMILIES = {
    "transport", "search_surface", "extraction", "pagination", "paywall",
    "authentication", "blocking", "validation", "limitation", "unknown",
}
_TASK_DATA_KEYS = {
    "article", "articles", "title", "titles", "store", "stores", "shop", "shops",
    "price", "prices", "result", "results", "html", "raw_html", "log", "logs",
    "task", "task_summary", "listing", "listings", "product", "products",
}
_TASK_DATA_TEXT = re.compile(r"<(?:html|body|article|script)\b|\b(?:R\$|US\$)\s?\d|\b(?:articles?|stores?|shops?)\s+(?:found|returned)\b", re.I)
# A schema field-path pointer (e.g. "post.title", "items[].title") names where a
# field lives, it does not carry the field's actual content. Requires at least
# one ".segment" or "[]" hop so a bare word (a real one-word title) still trips
# the key-name check below.
_SCHEMA_FIELD_PATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*|\[\d*\])+$")


def _is_schema_field_path(value: Any) -> bool:
    return isinstance(value, str) and bool(_SCHEMA_FIELD_PATH.match(value))


def _scope_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower().replace("_", "-")).strip("-")


@dataclass(frozen=True)
class DiscoveryFinalization:
    status: str
    target: str
    capability: str
    proposal_id: str | None = None
    claims_created: int = 0
    reason: str | None = None
    reason_code: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status, "target": self.target, "capability": self.capability,
        }
        if self.status == "NÃO_SALVA" and self.reason:
            result["motivo"] = self.reason
        if self.status == "NÃO_SALVA" and self.reason_code:
            result["motivo_codigo"] = self.reason_code
        return result


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()[:20]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _reject_task_data(value: Any, *, field: str = "observation", allow_schema_pointer: bool = False) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise DiscoveryFinalizationError(f"{field} keys must be strings")
            if key.lower() in _TASK_DATA_KEYS and not (allow_schema_pointer and _is_schema_field_path(child)):
                raise DiscoveryFinalizationError(f"{field} contains task-specific data ({key})")
            _reject_task_data(child, field=field, allow_schema_pointer=allow_schema_pointer)
    elif isinstance(value, list):
        for child in value:
            _reject_task_data(child, field=field, allow_schema_pointer=allow_schema_pointer)
    elif isinstance(value, str):
        if value.strip().upper().replace(" ", "_") == PLATFORM_UNSUPPORTED:
            raise DiscoveryFinalizationError(
                f"{field} contains platform runtime state"
            )
        if len(value) > 500 or _TASK_DATA_TEXT.search(value):
            raise DiscoveryFinalizationError(f"{field} contains task-specific or raw content")


def _normalize_hostname(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise DiscoveryFinalizationError("observation.host must be a hostname")
    raw = value.strip().lower().rstrip(".")
    try:
        hostname = urlparse(f"//{raw}").hostname
        ascii_name = hostname.encode("idna").decode("ascii") if hostname else None
    except (UnicodeError, ValueError):
        ascii_name = None
    if not ascii_name or ascii_name != raw or "." not in ascii_name:
        raise DiscoveryFinalizationError("observation.host must be a normalized public hostname")
    return ascii_name


def _normalize_validation(value: Any, *, field: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise DiscoveryFinalizationError(f"{field} must be an object")
    allowed = {
        "transport", "engine", "javascript", "context", "outcome",
        "failure_class", "evidence",
    }
    if set(value) - allowed:
        raise DiscoveryFinalizationError(f"{field} contains unsupported context")
    context = value.get("context", {})
    if not isinstance(context, Mapping):
        raise DiscoveryFinalizationError(f"{field}.context must be an object")
    clean = {key: value[key] for key in allowed if key in value}
    references = value.get("evidence", [])
    if (
        not isinstance(references, Sequence)
        or isinstance(references, (str, bytes))
        or any(not isinstance(item, str) or not item for item in references)
    ):
        raise DiscoveryFinalizationError(f"{field}.evidence must be an array of locators")
    clean["evidence"] = sorted(set(references))
    clean["context"] = dict(context)
    _reject_task_data(clean, field=field)
    return clean


def _normalize_observations(observations: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(observations, Sequence) or isinstance(observations, (str, bytes)):
        raise DiscoveryFinalizationError("observations must be an array")
    normalized: dict[str, dict[str, Any]] = {}
    for item in observations:
        if not isinstance(item, Mapping):
            raise DiscoveryFinalizationError("every observation must be an object")
        family = item.get("family")
        epistemic = item.get("epistemic", "OBSERVED")
        value = item.get("value")
        host = _normalize_hostname(item.get("host"))
        if family not in OPERATIONAL_FAMILIES:
            raise DiscoveryFinalizationError("observation family is not reusable operational knowledge")
        if epistemic not in EPISTEMIC_CLASSES:
            raise DiscoveryFinalizationError("observation epistemic class is invalid")
        if not isinstance(value, Mapping) or not value:
            raise DiscoveryFinalizationError("observation value must be a non-empty object")
        _reject_task_data(value, allow_schema_pointer=(family == "extraction"))
        validation = _normalize_validation(item.get("validation"), field="observation.validation")
        contradiction = item.get("contradiction")
        clean_contradiction = None
        if contradiction is not None:
            if not isinstance(contradiction, Mapping) or set(contradiction) != {"prior_value", "validation"}:
                raise DiscoveryFinalizationError(
                    "observation.contradiction requires prior_value and validation"
                )
            if not isinstance(contradiction["prior_value"], Mapping) or not contradiction["prior_value"]:
                raise DiscoveryFinalizationError("contradiction.prior_value must be a non-empty object")
            clean_contradiction = {
                "prior_value": dict(contradiction["prior_value"]),
                "validation": _normalize_validation(
                    contradiction["validation"], field="observation.contradiction.validation"
                ),
            }
            _reject_task_data(clean_contradiction["prior_value"], field="contradiction.prior_value")
        semantic = {"family": family, "epistemic": epistemic, "value": value, "host": host}
        normalized[_canonical(semantic)] = {
            "family": family, "epistemic": epistemic, "value": dict(value),
            "host": host, "validation": validation, "contradiction": clean_contradiction,
        }
    return [normalized[key] for key in sorted(normalized)]


def _validate_provenance(provenance: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(provenance, Mapping) or not provenance:
        raise DiscoveryFinalizationError("run provenance is required")
    run_id, observed_at = provenance.get("run_id"), provenance.get("observed_at")
    if not isinstance(run_id, str) or not run_id.strip():
        raise DiscoveryFinalizationError("provenance.run_id is required")
    validate_timestamp(observed_at, field="provenance.observed_at")
    _reject_task_data(dict(provenance), field="provenance")
    return dict(provenance)


def _validate_evidence(evidence: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(evidence, Sequence) or isinstance(evidence, (str, bytes)) or not evidence:
        raise DiscoveryFinalizationError("evidence is required")
    result: dict[str, dict[str, Any]] = {}
    for item in evidence:
        if not isinstance(item, Mapping):
            raise DiscoveryFinalizationError("every evidence item must be an object")
        kind, locator = item.get("kind"), item.get("locator")
        if not isinstance(kind, str) or not kind or not isinstance(locator, str) or not locator:
            raise DiscoveryFinalizationError("evidence requires kind and locator")
        _reject_task_data(dict(item), field="evidence")
        clean = {key: value for key, value in item.items() if key != "id"}
        result[_canonical(clean)] = clean
    return [result[key] for key in sorted(result)]


def _referenced_evidence(
    validation: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]],
    *,
    required: bool = False,
) -> list[dict[str, Any]]:
    references = set(validation.get("evidence", ()))
    if not references:
        return [] if required else [dict(item) for item in evidence]
    selected = [dict(item) for item in evidence if item["locator"] in references]
    if {item["locator"] for item in selected} != references:
        raise DiscoveryFinalizationError("validation references unknown evidence")
    return selected


def _semantic_key(family: str, epistemic: str, value: Any, host_id: str | None) -> str:
    return _canonical({
        "family": family, "epistemic": epistemic, "value": value, "host_id": host_id,
    })


def _semantic_keys(memory: SQLiteOperationalMemory, target: str, capability: str, *, pending: bool) -> set[str]:
    if pending:
        proposal_ids = [item["proposal_id"] for item in memory.get_pending_candidates(target, capability)]
        placeholders = ",".join("?" for _ in proposal_ids)
        if not placeholders:
            return set()
        rows = memory._conn.execute(
            f"SELECT family,epistemic,value_json,host_id FROM claims WHERE proposal_id IN ({placeholders})",
            proposal_ids,
        )
    else:
        current = memory.get_current(target, capability)
        claim_ids = current["accepted_claim_ids"]
        placeholders = ",".join("?" for _ in claim_ids)
        if not placeholders:
            return set()
        rows = memory._conn.execute(
            f"SELECT family,epistemic,value_json,host_id FROM claims WHERE id IN ({placeholders})", claim_ids
        )
    return {
        _semantic_key(row["family"], row["epistemic"], json.loads(row["value_json"]), row["host_id"])
        for row in rows
    }


def _matching_pending_candidate(
    memory: SQLiteOperationalMemory,
    target: str,
    capability: str,
    semantic_key: str,
) -> tuple[str, str] | None:
    matches: list[tuple[str, str]] = []
    for proposal in memory.get_pending_candidates(target, capability):
        if len(proposal["claim_ids"]) != 1:
            continue
        for row in memory._conn.execute(
            """SELECT id,family,epistemic,value_json,host_id FROM claims
               WHERE proposal_id=? ORDER BY id""",
            (proposal["proposal_id"],),
        ):
            key = _semantic_key(
                row["family"], row["epistemic"],
                json.loads(row["value_json"]), row["host_id"],
            )
            if key == semantic_key:
                matches.append((proposal["proposal_id"], row["id"]))
    return matches[0] if len(matches) == 1 else None


def _host_plan(
    memory: SQLiteOperationalMemory, target: str, observations: Sequence[Mapping[str, Any]],
    evidence: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    hostnames = sorted({str(item["host"]) for item in observations if item.get("host")})
    if not hostnames:
        return {}, []
    target_id = f"tgt:{target}"
    mapped: dict[str, str] = {}
    created: list[dict[str, Any]] = []
    for hostname in hostnames:
        rows = list(memory._conn.execute(
            "SELECT id FROM hosts WHERE target_id=? AND hostname=? ORDER BY id", (target_id, hostname)
        ))
        if len(rows) > 1:
            raise DiscoveryFinalizationError("hostname scope is ambiguous for this target")
        if rows:
            mapped[hostname] = rows[0]["id"]
            continue
        proven = any(
            source.get("scope") == "TARGET_SURFACE"
            and urlparse(str(source.get("locator", ""))).hostname
            and urlparse(str(source["locator"])).hostname.lower().rstrip(".") == hostname
            for source in evidence
        )
        if not proven:
            raise DiscoveryFinalizationError(
                "a new observation host requires TARGET_SURFACE evidence from that hostname"
            )
        host_id = f"host:{target}:{_digest(hostname)}"
        mapped[hostname] = host_id
        created.append({"id": host_id, "target_id": target_id, "hostname": hostname})
    return mapped, created


def _replacement_plan(
    memory: SQLiteOperationalMemory, target: str, capability: str,
    delta: Sequence[Mapping[str, Any]], host_ids: Mapping[str, str],
    pending_proposal_id: str | None = None,
) -> tuple[tuple[str, ...] | None, bool, str | None]:
    try:
        pending = memory.get_pending_candidates(target, capability)
    except KeyError:
        return None, False, None
    competing = [
        item for item in pending if item["proposal_id"] != pending_proposal_id
    ]
    if len(delta) != 1 or competing:
        return None, False, None
    item = delta[0]
    contradiction, validation = item.get("contradiction"), item.get("validation")
    if item["epistemic"] != "OBSERVED" or not contradiction or not validation:
        return None, False, None
    host_id = host_ids.get(item.get("host")) if item.get("host") else None
    capability_id = memory.resolve_capability(target, capability)
    current_claim_ids = memory.get_current(target, capability)["accepted_claim_ids"]
    rows = (
        list(memory._conn.execute(
            """SELECT c.id,c.value_json,c.epistemic FROM claims c
               WHERE c.capability_id=? AND c.family=? AND c.host_id IS ?
                 AND c.id IN ({})""".format(
                    ",".join("?" for _ in current_claim_ids)
                ),
            (capability_id, item["family"], host_id, *current_claim_ids),
        ))
        if current_claim_ids else []
    )
    candidates = [
        row["id"] for row in rows
        if row["epistemic"] == "OBSERVED"
        and json.loads(row["value_json"]) == contradiction["prior_value"]
    ]
    if len(candidates) != 1:
        return None, False, None
    old_validation = contradiction["validation"]
    if (
        validation.get("outcome") != "FUNCTIONAL"
        or old_validation.get("outcome") != "FAILED"
        or old_validation.get("failure_class") != "TARGET_CHANGED"
    ):
        return tuple(candidates), False, None
    new_evidence = set(validation.get("evidence", ()))
    old_evidence = set(old_validation.get("evidence", ()))
    if not new_evidence or not old_evidence or new_evidence & old_evidence:
        return tuple(candidates), False, "EVIDENCIA_BILATERAL_INSUFICIENTE"
    support = list(memory._conn.execute(
        """SELECT v.host_id,v.transport,v.context_json
           FROM claim_observations co
           JOIN observations o ON o.id=co.observation_id
           JOIN validations v ON v.id=o.validation_id
           WHERE co.claim_id=? AND co.relation='supports'""",
        (candidates[0],),
    ))
    if len(support) != 1:
        return tuple(candidates), False, "BASELINE_MATERIAL_INSUFICIENTE"
    prior_context = json.loads(support[0]["context_json"])
    baseline = {
        "host_id": support[0]["host_id"],
        "transport": support[0]["transport"],
        **{
            key: value for key, value in prior_context.items()
            if key not in {"outcome", "failure_class"}
        },
    }

    def material(validation_record: Mapping[str, Any]) -> dict[str, Any] | None:
        context = dict(validation_record.get("context", {}))
        for key in ("engine", "javascript"):
            if key in validation_record:
                context[key] = validation_record[key]
        result = {
            "host_id": host_id,
            "transport": validation_record.get("transport"),
            **context,
        }
        required = {"transport", "engine", "javascript", "authentication", "environment"}
        return result if required <= result.keys() and result["transport"] else None

    old_material = material(old_validation)
    new_material = material(validation)
    required_baseline = {"transport", "engine", "javascript", "authentication", "environment"}
    if not required_baseline <= baseline.keys() or not baseline["transport"]:
        return tuple(candidates), False, "BASELINE_MATERIAL_INSUFICIENTE"
    if old_material is None or new_material is None or baseline != old_material:
        return tuple(candidates), False, "CONTEXTO_MATERIAL_INCOMPARAVEL"
    changed = {
        key for key in set(old_material) | set(new_material)
        if old_material.get(key) != new_material.get(key)
    }
    allowed_changes: set[str] = set()
    if item["family"] == "transport":
        allowed_changes.add("transport")
    for key in changed:
        if (
            key in contradiction["prior_value"]
            and key in item["value"]
            and contradiction["prior_value"][key] == old_material.get(key)
            and item["value"][key] == new_material.get(key)
        ):
            allowed_changes.add(key)
    if changed - allowed_changes:
        return tuple(candidates), False, "CONTEXTO_MATERIAL_INCOMPARAVEL"
    return tuple(candidates), True, None


def _has_conflict(
    memory: SQLiteOperationalMemory,
    target: str,
    capability: str,
    delta: Sequence[Mapping[str, Any]],
    host_ids: Mapping[str, str],
) -> bool:
    """Keep conflicting observations out of automatic acceptance.

    This is deliberately a small structural gate, not a risk classifier: an
    automatic Decision is allowed only when a family has no other value in the
    current accepted or pending view.
    """
    families = {str(item["family"]) for item in delta}
    if not families:
        return False
    delta_values: dict[tuple[str, str | None], set[str]] = {}
    for item in delta:
        host_id = host_ids.get(str(item.get("host"))) if item.get("host") else None
        delta_values.setdefault((item["family"], host_id), set()).add(
            json.dumps(item["value"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
    if any(len(values) > 1 for values in delta_values.values()):
        return True
    try:
        capability_id = memory.resolve_capability(target, capability)
    except KeyError:
        return False
    current_claim_ids = set(memory.get_current(target, capability)["accepted_claim_ids"])
    pending_claim_ids = {
        claim_id
        for proposal in memory.get_pending_candidates(target, capability)
        for claim_id in proposal["claim_ids"]
    }
    claim_ids = sorted(current_claim_ids | pending_claim_ids)
    if not claim_ids:
        return False
    rows = memory._conn.execute(
        """SELECT family,value_json,host_id FROM claims
           WHERE id IN ({}) AND family IN ({})""".format(
            ",".join("?" for _ in claim_ids), ",".join("?" for _ in families)
        ),
        (*claim_ids, *sorted(families)),
    )
    current_values: dict[tuple[str, str | None], set[str]] = {}
    for row in rows:
        key = (row["family"], row["host_id"])
        current_values.setdefault(key, set()).add(
            json.dumps(json.loads(row["value_json"]), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
    return any(
        current_values.get((
            item["family"],
            host_ids.get(str(item.get("host"))) if item.get("host") else None,
        ), set()) - {
            json.dumps(
                item["value"], ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            )
        }
        for item in delta
    )


def finalize_discovery(
    memory: SQLiteOperationalMemory,
    *, target: str, capability: str, observations: Sequence[Mapping[str, Any]],
    evidence: Sequence[Mapping[str, Any]], provenance: Mapping[str, Any],
    recorded_at: str | None = None, knowledge_write_authority: bool = True,
    write_destination: str | None = WRITE_DESTINATION, authority_at_operation: str = WRITE_DESTINATION,
) -> DiscoveryFinalization:
    """Finalize Discovery into local OM, accepting only direct observations."""
    if not isinstance(target, str) or not target.strip() or not isinstance(capability, str) or not capability.strip():
        raise DiscoveryFinalizationError("target and capability are required")
    target, capability = _scope_key(target), _scope_key(capability)
    if not target or not capability:
        raise DiscoveryFinalizationError("target and capability are required")
    # Validate authority before examining or normalizing Discovery output.  This
    # deliberately fails closed when the installation is not OM-writable.
    from om_native_writes import assert_om_native_write_authority
    if knowledge_write_authority is not True or write_destination != WRITE_DESTINATION:
        # Let the native primitive preserve its established authority errors.
        capture_candidate(memory, target=target, capability=capability, proposal_id="prop:authority-check",
            claims=[{"id": "clm:authority-check", "family": "unknown", "epistemic": "UNKNOWN", "value": {"state": "UNKNOWN"}}],
            provenance={"check": "authority"}, recorded_at=recorded_at or _now(),
            knowledge_write_authority=knowledge_write_authority, write_destination=write_destination,
            authority_at_operation=authority_at_operation)
    assert_om_native_write_authority(memory, authority_at_operation=authority_at_operation)
    recorded_at = recorded_at or _now()
    validate_timestamp(recorded_at, field="finalize_discovery.recorded_at")
    normalized = _normalize_observations(observations)
    clean_provenance = _validate_provenance(provenance)
    if not normalized:
        return DiscoveryFinalization(
            "NÃO_SALVA", target, capability,
            reason="A Discovery não encontrou conhecimento operacional reutilizável.",
            reason_code="SEM_CONHECIMENTO_REUTILIZAVEL",
        )
    clean_evidence = _validate_evidence(evidence)
    host_ids, hosts_to_create = _host_plan(memory, target, normalized, clean_evidence)
    # A new scope has no accepted or pending Claims yet. It is created atomically
    # with the pending Candidate below, after authority and payload validation.
    try:
        memory.resolve_capability(target, capability)
    except KeyError:
        accepted, pending = set(), set()
    else:
        accepted = _semantic_keys(memory, target, capability, pending=False)
        pending = _semantic_keys(memory, target, capability, pending=True)
    def semantic(item: Mapping[str, Any]) -> str:
        host_id = host_ids.get(str(item.get("host"))) if item.get("host") else None
        return _semantic_key(item["family"], item["epistemic"], item["value"], host_id)

    delta = [item for item in normalized if semantic(item) not in accepted]
    if not delta:
        return DiscoveryFinalization("JÁ_EXISTENTE", target, capability)
    delta_keys = {semantic(item) for item in delta}
    pending_match = (
        _matching_pending_candidate(
            memory, target, capability, semantic(delta[0])
        )
        if len(delta) == 1 and semantic(delta[0]) in pending else None
    )
    if delta_keys <= pending and pending_match is None:
        return DiscoveryFinalization(
            "NÃO_SALVA", target, capability,
            reason="Esse aprendizado já está aguardando confirmação antes de ser usado.",
            reason_code="JA_PENDENTE",
        )
    if pending_match is None:
        delta = [item for item in delta if semantic(item) not in pending]
    if not delta:
        return DiscoveryFinalization(
            "NÃO_SALVA", target, capability,
            reason="Esse aprendizado já está aguardando confirmação antes de ser usado.",
            reason_code="JA_PENDENTE",
        )
    fingerprint = _digest({
        "target": target, "capability": capability,
        "claims": [semantic(item) for item in delta],
    })
    proposal_id = (
        pending_match[0] if pending_match
        else f"prop:{target}:{capability}:discovery-{fingerprint}"
    )
    claims: list[dict[str, Any]] = []
    supports: dict[str, list[dict[str, Any]]] = {}
    contradiction_supports: dict[str, list[dict[str, Any]]] = {}
    validations: dict[str, dict[str, Any]] = {}
    for item in delta:
        claim_id = (
            pending_match[1] if pending_match
            else f"clm:{target}:{capability}:discovery-{_digest(semantic(item))}"
        )
        claim = {
            "id": claim_id, "family": item["family"], "epistemic": item["epistemic"],
            "value": item["value"],
        }
        if item.get("host"):
            claim["host_id"] = host_ids[str(item["host"])]
        claims.append(claim)
        validation = item.get("validation") or {}
        validation_context = dict(validation.get("context", {}))
        for key in ("engine", "javascript", "outcome", "failure_class"):
            if key in validation:
                validation_context[key] = validation[key]
        validations[claim_id] = {
            "transport": validation.get("transport"),
            "context": validation_context,
            "observed_at": clean_provenance["observed_at"],
            "recorded_at": recorded_at,
        }
        new_sources = _referenced_evidence(
            validation, clean_evidence, required=bool(item.get("contradiction"))
        )
        support_records = [
            {"id": f"ev:{target}:{capability}:{_digest({'claim': claim_id, 'evidence': source})}",
             "recorded_at": recorded_at, **source}
            for source in new_sources
        ]
        if support_records:
            supports[claim_id] = support_records
    # Only directly observed, non-conflicting claims are eligible for the
    # normal automatic path. Other valid candidates remain historical/pending
    # and never enter the lookup projection.
    replacement_ids, replacement_ready, replacement_refusal = _replacement_plan(
        memory, target, capability, delta, host_ids,
        pending_proposal_id=proposal_id if pending_match else None,
    )
    has_conflict = _has_conflict(memory, target, capability, delta, host_ids)
    automatic = (
        all(item["epistemic"] == "OBSERVED" for item in delta)
        and not has_conflict
    )
    contradicting: dict[str, list[str]] = {}
    contradiction_contexts: dict[str, dict[str, Any]] = {}
    if replacement_ids:
        old_validation = delta[0]["contradiction"]["validation"]
        old_sources = _referenced_evidence(
            old_validation, clean_evidence, required=True
        )
        contradiction_supports[claims[0]["id"]] = [
            {
                "id": f"ev:{target}:{capability}:{_digest(dict(claim=claims[0]['id'], side='contradiction', evidence=source))}",
                "recorded_at": recorded_at,
                **source,
            }
            for source in old_sources
        ]
        if contradiction_supports[claims[0]["id"]]:
            old_context = dict(old_validation.get("context", {}))
            for key in ("engine", "javascript", "outcome", "failure_class"):
                if key in old_validation:
                    old_context[key] = old_validation[key]
            contradiction_contexts[claims[0]["id"]] = {
                "transport": old_validation.get("transport"),
                "context": old_context,
                "observed_at": clean_provenance["observed_at"],
                "recorded_at": recorded_at,
                "value": delta[0]["contradiction"]["prior_value"],
            }
            contradicting[claims[0]["id"]] = list(replacement_ids)
    base_token = (
        review_token(memory, target=target, capability=capability)
        if replacement_ready else None
    )
    enrichment_created = 0
    with memory.write_transaction() as writer:
        if pending_match:
            enrichment = enrich_candidate(
                memory, target=target, capability=capability,
                proposal_id=proposal_id, claim_id=claims[0]["id"],
                supporting_evidence=supports.get(claims[0]["id"], ()),
                validation_context=validations.get(claims[0]["id"]),
                contradicted_claim_id=(
                    replacement_ids[0]
                    if replacement_ids and contradicting else None
                ),
                contradicting_evidence=contradiction_supports.get(
                    claims[0]["id"], ()
                ),
                contradiction_context=contradiction_contexts.get(claims[0]["id"]),
                knowledge_write_authority=knowledge_write_authority,
                write_destination=write_destination,
                authority_at_operation=authority_at_operation,
                _writer=writer,
            )
            enrichment_created = enrichment.records_created
        else:
            capture_candidate(
                memory, target=target, capability=capability,
                proposal_id=proposal_id, claims=claims,
                provenance=clean_provenance, recorded_at=recorded_at,
                knowledge_write_authority=knowledge_write_authority,
                write_destination=write_destination,
                authority_at_operation=authority_at_operation,
                operation_context={
                    "source": "discovery-finalize",
                    "run_id": clean_provenance["run_id"],
                },
                supporting_evidence=supports,
                validation_contexts=validations,
                contradicting_claims=contradicting,
                contradiction_contexts=contradiction_contexts,
                contradicting_evidence=contradiction_supports,
                hosts=hosts_to_create,
                create_missing_scope=True,
                _writer=writer,
            )
        if replacement_ready:
            replace_candidate(
                memory,
                target=target, capability=capability, proposal_id=proposal_id,
                replaced_claim_ids=replacement_ids, reviewed_token=str(base_token),
                decision_id=f"dec:{target}:{capability}:replace-{_digest(delta)}",
                recorded_at=recorded_at, effective_at=recorded_at,
                knowledge_write_authority=knowledge_write_authority,
                write_destination=write_destination,
                authority_at_operation=authority_at_operation, _writer=writer,
            )
        elif automatic and not pending_match:
            promote_candidate(
                memory,
                target=target,
                capability=capability,
                proposal_id=proposal_id,
                reviewed_token=review_token(memory, target=target, capability=capability),
                decision_id=f"dec:{target}:{capability}:discovery-{_digest(delta)}",
                recorded_at=recorded_at,
                effective_at=recorded_at,
                knowledge_write_authority=knowledge_write_authority,
                write_destination=write_destination,
                authority_at_operation=authority_at_operation,
                _writer=writer,
            )
    if pending_match and not replacement_ready and enrichment_created == 0:
        return DiscoveryFinalization(
            "NÃO_SALVA", target, capability, proposal_id, 0,
            reason="Esse aprendizado já está aguardando confirmação antes de ser usado.",
            reason_code="JA_PENDENTE",
        )
    if not automatic and not replacement_ready:
        if any(item["epistemic"] != "OBSERVED" for item in delta):
            reason_code = "APENAS_INFERENCIA"
        elif replacement_refusal:
            reason_code = replacement_refusal
        elif any(item.get("contradiction") for item in delta):
            reason_code = "SUBSTITUICAO_NAO_COMPROVADA"
        elif has_conflict:
            reason_code = "CONFLITO_OU_AMBIGUIDADE"
        else:
            reason_code = "CONFIRMACAO_PENDENTE"
        return DiscoveryFinalization(
            "NÃO_SALVA", target, capability, proposal_id, len(claims),
            reason="Encontrei informações conflitantes ou não confirmadas e não consegui validar um caminho reutilizável.",
            reason_code=reason_code,
        )
    return DiscoveryFinalization(
        "SALVA", target, capability, proposal_id, len(claims)
    )


__all__ = ["DiscoveryFinalization", "DiscoveryFinalizationError", "finalize_discovery"]
