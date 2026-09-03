"""Small, explicit Operational-Memory-native write boundary.

This module is deliberately separate from ``integration_bridge``. The latter
owns lookup compatibility; this boundary never reads or writes Markdown.

It is also deliberately separate from ``operational_memory``: this module
owns write *policy* (review-token staleness, explicit write authority,
bilateral-evidence rules for replacement, structural Candidate validation),
while ``operational_memory`` owns the canonical schema, SQL, and projection
semantics. This module never touches SQL, table names, or private
``SQLiteOperationalMemory`` state directly -- it composes the package's
public read/write API exclusively.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from operational_memory import (
    EPISTEMIC_CLASSES,
    SQLiteOperationalMemory,
    canonical_json,
    validate_timestamp,
)
from write_authority import assert_om_write_authority

WRITE_DESTINATION = "OPERATIONAL_MEMORY"
TOKEN_VERSION = "om-review-v1"


@contextmanager
def _write_scope(memory: SQLiteOperationalMemory, writer: Any | None):
    """Use the caller's transaction when composing multiple OM writes."""
    if writer is not None:
        yield writer
    else:
        with memory.write_transaction() as owned_writer:
            yield owned_writer


class OMNativeWriteError(RuntimeError):
    """Base error for the OM-native write boundary."""


class OMStaleBaseError(OMNativeWriteError):
    """The accepted projection differs from the projection that was reviewed."""


class OMAmbiguousCandidateError(OMNativeWriteError):
    """Candidate identity, scope, or provenance is incomplete or ambiguous."""


class OMProposalError(OMNativeWriteError):
    """The selected Proposal cannot be promoted."""


@dataclass(frozen=True)
class CandidateCapture:
    proposal_id: str
    claim_ids: tuple[str, ...]
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class Promotion:
    decision_id: str
    claim_ids: tuple[str, ...]
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class Replacement:
    decision_ids: tuple[str, str]
    replaced_claim_ids: tuple[str, ...]
    accepted_claim_ids: tuple[str, ...]
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class CandidateEnrichment:
    proposal_id: str
    claim_id: str
    records_created: int


def _record_exists(memory: SQLiteOperationalMemory, record_id: str) -> bool:
    try:
        memory.get_record(record_id)
    except KeyError:
        return False
    return True


def assert_om_native_write_authority(memory: SQLiteOperationalMemory) -> None:
    """Fail closed unless this installation's real marker grants OM write authority.

    The only input is ``memory.knowledge_root`` and the write-authority marker
    it resolves to -- no caller-supplied flag can assert or bypass this.
    """
    if memory.knowledge_root is None:
        raise OMNativeWriteError("OM-native operation requires an installation knowledge root")
    assert_om_write_authority(memory.knowledge_root)


def _require_boundary(memory: SQLiteOperationalMemory) -> None:
    assert_om_native_write_authority(memory)


def _identity(
    memory: SQLiteOperationalMemory, target: str, capability: str
) -> tuple[str, str]:
    if not isinstance(target, str) or not target.strip():
        raise OMAmbiguousCandidateError("target identity is required")
    if not isinstance(capability, str) or not capability.strip():
        raise OMAmbiguousCandidateError("capability identity is required")
    try:
        return (
            memory.resolve_target(target),
            memory.resolve_capability(target, capability),
        )
    except KeyError as exc:
        raise OMAmbiguousCandidateError(str(exc)) from exc


def _token_payload(
    memory: SQLiteOperationalMemory, target: str, capability: str
) -> dict[str, Any]:
    target_id, capability_id = _identity(memory, target, capability)
    now = memory.now()
    projection = memory.projection(
        target, capability, knowledge_time=now, domain_time=now
    )
    claims = []
    for claim_id in sorted(projection.accepted_claim_ids):
        try:
            claims.append(memory.get_record(claim_id))
        except KeyError:
            raise OMNativeWriteError(f"accepted Claim disappeared: {claim_id}") from None
    decisions = []
    for decision_id in sorted(projection.provenance_decision_ids):
        try:
            decisions.append(memory.get_record(decision_id))
        except KeyError:
            raise OMNativeWriteError(f"supporting Decision disappeared: {decision_id}") from None
    return {
        "version": TOKEN_VERSION,
        "target_id": target_id,
        "capability_id": capability_id,
        "accepted_claims": claims,
        "supporting_decisions": decisions,
        "accepted_intervals": {
            key: dict(projection.intervals[key])
            for key in sorted(projection.intervals)
        },
    }


def review_token(
    memory: SQLiteOperationalMemory, *, target: str, capability: str
) -> str:
    """Hash the canonical accepted OM projection being reviewed."""
    encoded = canonical_json(_token_payload(memory, target, capability)).encode("utf-8")
    return f"{TOKEN_VERSION}:{hashlib.sha256(encoded).hexdigest()}"


def _operation_metadata(
    *,
    operation: str,
    target_id: str,
    capability_id: str,
    proposal_id: str,
    recorded_at: str,
    decision_id: str | None = None,
    effective_at: str | None = None,
    reviewed_token: str | None = None,
    first_om_authoritative_write: bool = False,
    operation_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    # `_require_boundary` already verified real OM write authority before any
    # caller reaches this point, so this is the verified boundary's own
    # record, never a caller-supplied claim.
    metadata = {
        "operation": operation,
        "authority_at_operation": WRITE_DESTINATION,
        "write_destination": WRITE_DESTINATION,
        "target_id": target_id,
        "capability_id": capability_id,
        "proposal_id": proposal_id,
        "decision_id": decision_id,
        "recorded_at": recorded_at,
        "effective_at": effective_at,
        "review_token": reviewed_token,
        "first_om_authoritative_write": first_om_authoritative_write,
    }
    if operation_context is not None:
        if not isinstance(operation_context, Mapping) or not operation_context:
            raise OMNativeWriteError("operation_context must be a non-empty object")
        metadata["operation_context"] = dict(operation_context)
    return metadata


def capture_candidate(
    memory: SQLiteOperationalMemory,
    *,
    target: str,
    capability: str,
    proposal_id: str,
    claims: Sequence[Mapping[str, Any]],
    provenance: Mapping[str, Any],
    recorded_at: str,
    first_om_authoritative_write: bool = False,
    operation_context: Mapping[str, Any] | None = None,
    supporting_evidence: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    validation_contexts: Mapping[str, Mapping[str, Any]] | None = None,
    contradicting_claims: Mapping[str, Sequence[str]] | None = None,
    contradiction_contexts: Mapping[str, Mapping[str, Any]] | None = None,
    contradicting_evidence: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    hosts: Sequence[Mapping[str, Any]] | None = None,
    create_missing_scope: bool = False,
    _writer: Any | None = None,
) -> CandidateCapture:
    """Persist one structured Candidate as pending Claims plus one Proposal.

    ``create_missing_scope`` is reserved for Discovery finalization: a new
    target/capability is materialized only in the same transaction as its first
    pending Proposal, never as accepted knowledge.
    """
    _require_boundary(memory)
    if create_missing_scope:
        if not isinstance(target, str) or not target.strip():
            raise OMAmbiguousCandidateError("target identity is required")
        if not isinstance(capability, str) or not capability.strip():
            raise OMAmbiguousCandidateError("capability identity is required")
        target_key = target.removeprefix("tgt:")
        capability_key = capability.removeprefix("cap:").rsplit(":", 1)[-1]
        target_id = f"tgt:{target_key}"
        capability_id = f"cap:{target_key}:{capability_key}"
    else:
        target_id, capability_id = _identity(memory, target, capability)
    validate_timestamp(recorded_at, field="candidate.recorded_at")
    if not isinstance(proposal_id, str) or not proposal_id.startswith("prop:"):
        raise OMAmbiguousCandidateError("a canonical prop: Proposal identity is required")
    if not isinstance(provenance, Mapping) or not provenance:
        raise OMAmbiguousCandidateError("explicit candidate provenance is required")
    if any(value in (None, "", [], {}) for value in provenance.values()):
        raise OMAmbiguousCandidateError("candidate provenance contains an ambiguous value")
    if not isinstance(claims, Sequence) or isinstance(claims, (str, bytes)) or not claims:
        raise OMAmbiguousCandidateError("candidate requires at least one Claim")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for supplied in claims:
        if not isinstance(supplied, Mapping):
            raise OMAmbiguousCandidateError("every candidate Claim must be an object")
        claim_id = supplied.get("id")
        if not isinstance(claim_id, str) or not claim_id.startswith("clm:"):
            raise OMAmbiguousCandidateError("every candidate Claim needs a canonical clm: id")
        if claim_id in seen:
            raise OMAmbiguousCandidateError(f"duplicate Claim identity: {claim_id}")
        seen.add(claim_id)
        for key, expected in (
            ("target_id", target_id),
            ("capability_id", capability_id),
            ("proposal_id", proposal_id),
        ):
            if key in supplied and supplied[key] != expected:
                raise OMAmbiguousCandidateError(f"Claim {claim_id} has mismatched {key}")
        if supplied.get("epistemic") not in EPISTEMIC_CLASSES:
            raise OMAmbiguousCandidateError(f"Claim {claim_id} has invalid epistemic class")
        if not isinstance(supplied.get("family"), str) or not supplied["family"]:
            raise OMAmbiguousCandidateError(f"Claim {claim_id} has ambiguous family")
        if "value" not in supplied:
            raise OMAmbiguousCandidateError(f"Claim {claim_id} has no explicit value")
        normalized.append(
            {
                **dict(supplied),
                "target_id": target_id,
                "capability_id": capability_id,
                "proposal_id": proposal_id,
                "recorded_at": recorded_at,
                "provenance": dict(provenance),
            }
        )

    metadata = _operation_metadata(
        operation="CANDIDATE_CAPTURE",
        target_id=target_id,
        capability_id=capability_id,
        proposal_id=proposal_id,
        recorded_at=recorded_at,
        first_om_authoritative_write=first_om_authoritative_write,
        operation_context=operation_context,
    )
    supporting_evidence = supporting_evidence or {}
    validation_contexts = validation_contexts or {}
    contradicting_claims = contradicting_claims or {}
    contradiction_contexts = contradiction_contexts or {}
    contradicting_evidence = contradicting_evidence or {}
    hosts = hosts or ()
    if not isinstance(supporting_evidence, Mapping):
        raise OMAmbiguousCandidateError("supporting_evidence must be an object")
    unknown_supports = set(supporting_evidence) - seen
    if unknown_supports:
        raise OMAmbiguousCandidateError("supporting evidence refers to an unknown Claim")
    if (
        set(validation_contexts) - seen
        or set(contradicting_claims) - seen
        or set(contradiction_contexts) - seen
        or set(contradicting_evidence) - seen
    ):
        raise OMAmbiguousCandidateError("observation metadata refers to an unknown Claim")

    with _write_scope(memory, _writer) as writer:
        if create_missing_scope:
            if not _record_exists(memory, target_id):
                writer.target({"id": target_id, "name": target_key})
            if not _record_exists(memory, capability_id):
                writer.capability({"id": capability_id, "target_id": target_id, "key": capability_key})
        for host in hosts:
            if not isinstance(host, Mapping) or host.get("target_id") != target_id:
                raise OMAmbiguousCandidateError("Candidate has incompatible host scope")
            try:
                existing = memory.get_record(str(host.get("id")))
            except KeyError:
                writer.host(host)
            else:
                if existing.get("target_id") != target_id or existing.get("hostname") != host.get("hostname"):
                    raise OMAmbiguousCandidateError("Candidate host identity is inconsistent")
        for claim in normalized:
            host_id = claim.get("host_id")
            if host_id is not None:
                try:
                    host_record = memory.get_record(host_id)
                except KeyError:
                    raise OMAmbiguousCandidateError(
                        f"Claim {claim['id']} has incompatible host scope"
                    ) from None
                if host_record.get("target_id") != target_id:
                    raise OMAmbiguousCandidateError(
                        f"Claim {claim['id']} has incompatible host scope"
                    )
        claim_observations: dict[str, list[str]] = {}
        for claim_id in sorted(supporting_evidence):
            evidence_records = supporting_evidence[claim_id]
            if not isinstance(evidence_records, Sequence) or isinstance(evidence_records, (str, bytes)) or not evidence_records:
                raise OMAmbiguousCandidateError(f"Claim {claim_id} needs non-empty supporting evidence")
            evidence_ids: list[str] = []
            for evidence in evidence_records:
                if not isinstance(evidence, Mapping):
                    raise OMAmbiguousCandidateError(f"Claim {claim_id} has invalid supporting evidence")
                writer.evidence(evidence)
                evidence_ids.append(str(evidence["id"]))
            observation_id = f"obs:{claim_id[4:]}"
            validation_id = f"val:{claim_id[4:]}"
            validation = validation_contexts.get(claim_id, {})
            if not isinstance(validation, Mapping):
                raise OMAmbiguousCandidateError("validation context must be an object")
            writer.validation(
                {
                    "id": validation_id,
                    "capability_id": capability_id,
                    "host_id": next(item.get("host_id") for item in normalized if item["id"] == claim_id),
                    "observed_at": validation.get("observed_at", recorded_at),
                    "recorded_at": recorded_at,
                    "time_precision": "exact",
                    "transport": validation.get("transport"),
                    "context": dict(validation.get("context", {})),
                }
            )
            value = next(item["value"] for item in normalized if item["id"] == claim_id)
            writer.observation(
                {
                    "id": observation_id,
                    "validation_id": validation_id,
                    "result": "SUPPORTS_CANDIDATE",
                    "value": value,
                    "evidence_ids": evidence_ids,
                }
            )
            contradicted_ids = sorted(set(contradicting_claims.get(claim_id, ())))
            contradiction = contradiction_contexts.get(claim_id)
            if contradicted_ids and (
                not isinstance(contradiction, Mapping) or not contradiction
            ):
                raise OMAmbiguousCandidateError("contradiction validation is required")
            if contradiction:
                contradiction_evidence = contradicting_evidence.get(claim_id, ())
                if (
                    not isinstance(contradiction_evidence, Sequence)
                    or isinstance(contradiction_evidence, (str, bytes))
                    or not contradiction_evidence
                ):
                    raise OMAmbiguousCandidateError(
                        "contradiction needs separate supporting evidence"
                    )
                contradiction_evidence_ids: list[str] = []
                for evidence in contradiction_evidence:
                    if not isinstance(evidence, Mapping):
                        raise OMAmbiguousCandidateError(
                            "Claim has invalid contradiction evidence"
                        )
                    writer.evidence(evidence)
                    contradiction_evidence_ids.append(str(evidence["id"]))
                contradiction_validation_id = f"{validation_id}:contradiction"
                contradiction_observation_id = f"{observation_id}:contradiction"
                writer.validation({
                    "id": contradiction_validation_id,
                    "capability_id": capability_id,
                    "host_id": next(
                        item.get("host_id") for item in normalized if item["id"] == claim_id
                    ),
                    "observed_at": contradiction.get("observed_at", recorded_at),
                    "recorded_at": recorded_at,
                    "time_precision": "exact",
                    "transport": contradiction.get("transport"),
                    "context": dict(contradiction.get("context", {})),
                })
                writer.observation({
                    "id": contradiction_observation_id,
                    "validation_id": contradiction_validation_id,
                    "result": "CONTRADICTS_ACCEPTED_PATH",
                    "value": contradiction.get("value"),
                    "evidence_ids": contradiction_evidence_ids,
                })
            for contradicted_claim_id in contradicted_ids:
                try:
                    contradicted_record = memory.get_record(contradicted_claim_id)
                except KeyError:
                    raise OMAmbiguousCandidateError("contradiction crosses Candidate scope") from None
                if (
                    contradicted_record.get("target_id") != target_id
                    or contradicted_record.get("capability_id") != capability_id
                ):
                    raise OMAmbiguousCandidateError("contradiction crosses Candidate scope")
                writer.contradiction(contradiction_observation_id, contradicted_claim_id)
            claim_observations[claim_id] = [observation_id]
        for claim in sorted(normalized, key=lambda item: item["id"]):
            claim = {**claim, "support_observation_ids": claim_observations.get(claim["id"], [])}
            writer.claim(claim)
        writer.proposal(
            {
                "id": proposal_id,
                "target_id": target_id,
                "capability_id": capability_id,
                "recorded_at": recorded_at,
                "claim_ids": sorted(seen),
                "provenance": dict(provenance),
                "write_metadata": metadata,
            }
        )
    return CandidateCapture(proposal_id, tuple(sorted(seen)), metadata)


def replace_candidate(
    memory: SQLiteOperationalMemory,
    *,
    target: str,
    capability: str,
    proposal_id: str,
    replaced_claim_ids: Sequence[str],
    reviewed_token: str,
    decision_id: str,
    recorded_at: str,
    effective_at: str,
    _writer: Any | None = None,
) -> Replacement:
    """Atomically supersede one unambiguous accepted family and accept its replacement."""
    _require_boundary(memory)
    target_id, capability_id = _identity(memory, target, capability)
    validate_timestamp(recorded_at, field="replacement.recorded_at")
    validate_timestamp(effective_at, field="replacement.effective_at")
    old_ids = tuple(sorted(set(replaced_claim_ids)))
    if len(old_ids) != 1:
        raise OMProposalError("replacement requires exactly one accepted Claim")
    if review_token(memory, target=target, capability=capability) != reviewed_token:
        raise OMStaleBaseError("reviewed Operational Memory projection is stale")
    metadata = _operation_metadata(
        operation="REPLACEMENT", target_id=target_id, capability_id=capability_id,
        proposal_id=proposal_id, decision_id=decision_id, recorded_at=recorded_at,
        effective_at=effective_at, reviewed_token=reviewed_token,
    )
    with _write_scope(memory, _writer) as writer:
        if review_token(memory, target=target, capability=capability) != reviewed_token:
            raise OMStaleBaseError("reviewed Operational Memory projection is stale")
        current_ids = set(memory.get_current(target, capability)["accepted_claim_ids"])
        if old_ids[0] not in current_ids:
            raise OMStaleBaseError("replacement base is no longer current")
        try:
            old_claim = memory.get_record(old_ids[0])
        except KeyError:
            raise OMProposalError("replaced Claim scope does not match") from None
        if old_claim.get("target_id") != target_id or old_claim.get("capability_id") != capability_id:
            raise OMProposalError("replaced Claim scope does not match")
        if old_claim.get("epistemic") != "OBSERVED":
            raise OMProposalError("replaced Claim is not directly observed")
        try:
            proposal = memory.get_record(proposal_id)
        except KeyError:
            raise OMProposalError("replacement Proposal scope does not match") from None
        if (proposal.get("target_id"), proposal.get("capability_id")) != (target_id, capability_id):
            raise OMProposalError("replacement Proposal scope does not match")
        new_claim_ids = memory.proposal_claim_ids(proposal_id)
        if len(new_claim_ids) != 1:
            raise OMProposalError("replacement Proposal requires exactly one Claim")
        new_ids = (new_claim_ids[0],)
        new_claim = memory.get_record(new_ids[0])
        if (
            new_claim.get("proposal_id") != proposal_id
            or new_claim.get("target_id") != target_id
            or new_claim.get("capability_id") != capability_id
        ):
            raise OMProposalError("replacement Claim does not belong to Proposal scope")
        if new_claim.get("epistemic") != "OBSERVED":
            raise OMProposalError("replacement Claim is not directly observed")
        if new_claim.get("family") != old_claim.get("family"):
            raise OMProposalError("replacement family does not match")
        if new_claim.get("host_id") != old_claim.get("host_id"):
            raise OMProposalError("replacement host scope does not match")
        contradiction_observation_prefix = f"obs:{new_claim['id'][4:]}:contradiction"
        contradiction_observations = [
            observation["observation_id"]
            for observation in memory.contradicting_observations(old_ids[0])
            if observation["observation_id"].startswith(contradiction_observation_prefix)
            and observation["capability_id"] == capability_id
            and observation["host_id"] == old_claim.get("host_id")
        ]
        if not contradiction_observations:
            raise OMProposalError("replacement has no recorded contradiction")
        new_evidence = set(memory.get_evidence(new_claim["id"])["evidence_ids"])
        old_failure_evidence = {
            evidence_id
            for observation_id in contradiction_observations
            for evidence_id in memory.get_evidence(observation_id)["evidence_ids"]
        }
        if (
            not new_evidence
            or not old_failure_evidence
            or new_evidence & old_failure_evidence
        ):
            raise OMProposalError("replacement evidence is not bilateral and separate")
        new_locators = {memory.get_record(evidence_id).get("locator") for evidence_id in new_evidence}
        old_failure_locators = {
            memory.get_record(evidence_id).get("locator") for evidence_id in old_failure_evidence
        }
        if (
            None in new_locators
            or None in old_failure_locators
            or new_locators & old_failure_locators
        ):
            raise OMProposalError("replacement evidence locators are not separate")
        if memory.get_pending_candidates(target, capability) != [{
            "proposal_id": proposal_id, "capability_id": capability_id, "claim_ids": list(new_ids)
        }]:
            raise OMProposalError("replacement has a concurrent pending Proposal")
        close_id = f"{decision_id}:close"
        writer.decision({
            "id": close_id, "target_id": target_id, "capability_id": capability_id,
            "action": "SUPERSEDE", "claim_ids": list(old_ids),
            "effective_at": effective_at, "recorded_at": recorded_at,
            "validity": {"valid_from": None, "valid_to": effective_at},
            "write_metadata": metadata,
        })
        writer.decision({
            "id": decision_id, "target_id": target_id, "capability_id": capability_id,
            "action": "ACCEPT_SUPERSEDE", "proposal_id": proposal_id,
            "claim_ids": list(new_ids), "effective_at": effective_at, "recorded_at": recorded_at,
            "validity": {"valid_from": effective_at, "valid_to": None},
            "write_metadata": metadata,
        })
    return Replacement((close_id, decision_id), old_ids, new_ids, metadata)


def enrich_candidate(
    memory: SQLiteOperationalMemory,
    *,
    target: str,
    capability: str,
    proposal_id: str,
    claim_id: str,
    supporting_evidence: Sequence[Mapping[str, Any]],
    validation_context: Mapping[str, Any] | None,
    contradicted_claim_id: str | None,
    contradicting_evidence: Sequence[Mapping[str, Any]],
    contradiction_context: Mapping[str, Any] | None,
    _writer: Any | None = None,
) -> CandidateEnrichment:
    """Add missing structured support to one Claim in a pending Candidate."""
    _require_boundary(memory)
    target_id, capability_id = _identity(memory, target, capability)
    try:
        proposal_record = memory.get_record(proposal_id)
        claim_record = memory.get_record(claim_id)
    except KeyError:
        raise OMProposalError("pending Candidate scope does not match enrichment") from None
    if (
        proposal_record.get("target_id") != target_id
        or proposal_record.get("capability_id") != capability_id
        or claim_record.get("proposal_id") != proposal_id
        or claim_record.get("target_id") != target_id
        or claim_record.get("capability_id") != capability_id
        or claim_id not in memory.proposal_claim_ids(proposal_id)
    ):
        raise OMProposalError("pending Candidate scope does not match enrichment")
    candidate = {"host_id": claim_record.get("host_id"), "value": claim_record.get("value")}
    pending_ids = {
        item["proposal_id"]
        for item in memory.get_pending_candidates(target, capability)
    }
    if proposal_id not in pending_ids:
        raise OMProposalError("Candidate enrichment requires a pending Claim")

    def evidence_ids(
        writer: Any, records: Sequence[Mapping[str, Any]]
    ) -> list[str]:
        result: list[str] = []
        for record in records:
            if not isinstance(record, Mapping):
                raise OMAmbiguousCandidateError("Candidate enrichment evidence is invalid")
            evidence_id = str(record.get("id", ""))
            if not evidence_id.startswith("ev:"):
                raise OMAmbiguousCandidateError("Candidate enrichment evidence needs an ev: id")
            try:
                stored = memory.get_record(evidence_id)
            except KeyError:
                writer.evidence(record)
            else:
                for key in ("kind", "locator", "scope"):
                    if stored.get(key) != record.get(key):
                        raise OMAmbiguousCandidateError(
                            "Candidate enrichment evidence identity is inconsistent"
                        )
            result.append(evidence_id)
        return sorted(set(result))

    def matching_observation(
        *, relation: str | None, validation: Mapping[str, Any],
        result: str, value: Any, contradicted: str | None = None,
    ) -> str | None:
        context = dict(validation.get("context", {}))
        candidates = (
            memory.observations_supporting_claim(claim_id)
            if relation == "supports"
            else memory.contradicting_observations(str(contradicted))
        )
        for observation in candidates:
            if (
                observation["capability_id"] == capability_id
                and observation["host_id"] == candidate["host_id"]
                and observation["transport"] == validation.get("transport")
                and observation["context"] == context
                and observation["result"] == result
                and observation["value"] == value
            ):
                return observation["observation_id"]
        return None

    before = memory.total_changes
    with _write_scope(memory, _writer) as writer:
        support_ids = evidence_ids(writer, supporting_evidence)
        if validation_context and support_ids:
            observation_id = matching_observation(
                relation="supports", validation=validation_context,
                result="SUPPORTS_CANDIDATE", value=candidate["value"],
            )
            if observation_id is None:
                signature = hashlib.sha256(canonical_json({
                    "claim": claim_id, "validation": validation_context,
                    "value": candidate["value"],
                }).encode("utf-8")).hexdigest()[:20]
                validation_id = f"val:{claim_id[4:]}:enrichment-{signature}"
                observation_id = f"obs:{claim_id[4:]}:enrichment-{signature}"
                writer.validation({
                    "id": validation_id, "capability_id": capability_id,
                    "host_id": candidate["host_id"],
                    "observed_at": validation_context["observed_at"],
                    "recorded_at": validation_context["recorded_at"],
                    "time_precision": "exact",
                    "transport": validation_context.get("transport"),
                    "context": dict(validation_context.get("context", {})),
                })
                writer.observation({
                    "id": observation_id, "validation_id": validation_id,
                    "result": "SUPPORTS_CANDIDATE",
                    "value": candidate["value"],
                    "evidence_ids": support_ids,
                })
                writer.claim_observation(claim_id, observation_id, "supports")
            else:
                linked = set(memory.get_evidence(observation_id)["evidence_ids"])
                for evidence_id in support_ids:
                    if evidence_id not in linked:
                        writer.observation_evidence(observation_id, evidence_id)

        contradiction_ids = evidence_ids(writer, contradicting_evidence)
        if contradicted_claim_id and contradiction_context and contradiction_ids:
            observation_id = matching_observation(
                relation=None, validation=contradiction_context,
                result="CONTRADICTS_ACCEPTED_PATH",
                value=contradiction_context.get("value"),
                contradicted=contradicted_claim_id,
            )
            if observation_id is None:
                signature = hashlib.sha256(canonical_json({
                    "claim": claim_id, "contradicted": contradicted_claim_id,
                    "validation": contradiction_context,
                }).encode("utf-8")).hexdigest()[:20]
                validation_id = f"val:{claim_id[4:]}:contradiction-{signature}"
                observation_id = f"obs:{claim_id[4:]}:contradiction-{signature}"
                writer.validation({
                    "id": validation_id, "capability_id": capability_id,
                    "host_id": candidate["host_id"],
                    "observed_at": contradiction_context["observed_at"],
                    "recorded_at": contradiction_context["recorded_at"],
                    "time_precision": "exact",
                    "transport": contradiction_context.get("transport"),
                    "context": dict(contradiction_context.get("context", {})),
                })
                writer.observation({
                    "id": observation_id, "validation_id": validation_id,
                    "result": "CONTRADICTS_ACCEPTED_PATH",
                    "value": contradiction_context.get("value"),
                    "evidence_ids": contradiction_ids,
                })
                writer.contradiction(observation_id, contradicted_claim_id)
            else:
                linked = set(memory.get_evidence(observation_id)["evidence_ids"])
                for evidence_id in contradiction_ids:
                    if evidence_id not in linked:
                        writer.observation_evidence(observation_id, evidence_id)
    return CandidateEnrichment(
        proposal_id, claim_id, memory.total_changes - before
    )


def promote_candidate(
    memory: SQLiteOperationalMemory,
    *,
    target: str,
    capability: str,
    proposal_id: str,
    reviewed_token: str,
    decision_id: str,
    recorded_at: str,
    effective_at: str,
    _writer: Any | None = None,
) -> Promotion:
    """Accept exactly one pending Proposal through an explicit Decision."""
    _require_boundary(memory)
    target_id, capability_id = _identity(memory, target, capability)
    validate_timestamp(recorded_at, field="promotion.recorded_at")
    validate_timestamp(effective_at, field="promotion.effective_at")
    if not isinstance(proposal_id, str) or not proposal_id.startswith("prop:"):
        raise OMProposalError("a canonical prop: Proposal identity is required")
    if not isinstance(decision_id, str) or not decision_id.startswith("dec:"):
        raise OMProposalError("a canonical dec: Decision identity is required")

    # Required pre-transaction stale-base check.  A second check under the
    # SQLite write lock below closes the check/write race.
    if review_token(memory, target=target, capability=capability) != reviewed_token:
        raise OMStaleBaseError("reviewed Operational Memory projection is stale")

    metadata = _operation_metadata(
        operation="PROMOTION",
        target_id=target_id,
        capability_id=capability_id,
        proposal_id=proposal_id,
        decision_id=decision_id,
        recorded_at=recorded_at,
        effective_at=effective_at,
        reviewed_token=reviewed_token,
    )
    claim_ids: tuple[str, ...] = ()
    with _write_scope(memory, _writer) as writer:
        if review_token(memory, target=target, capability=capability) != reviewed_token:
            raise OMStaleBaseError("reviewed Operational Memory projection is stale")
        try:
            proposal = memory.get_record(proposal_id)
        except KeyError:
            raise OMProposalError("Proposal does not exist") from None
        if proposal.get("target_id") != target_id or proposal.get("capability_id") != capability_id:
            raise OMProposalError("Proposal target/capability scope does not match promotion")
        claim_ids = memory.proposal_claim_ids(proposal_id)
        if not claim_ids:
            raise OMProposalError("Proposal has no Claims")
        for member_claim_id in claim_ids:
            member_claim = memory.get_record(member_claim_id)
            if (
                member_claim.get("proposal_id") != proposal_id
                or member_claim.get("target_id") != target_id
                or member_claim.get("capability_id") != capability_id
            ):
                raise OMProposalError("Proposal contains a Claim with mismatched ownership")
        # Resolution uses the same canonical rule as every other read of
        # "is this Proposal still pending" (get_pending_candidates), so this
        # can never diverge from Operational Memory's own Decision Action
        # semantics the way a locally-reimplemented action list could.
        pending_ids = {
            item["proposal_id"]
            for item in memory.get_pending_candidates(target, capability)
        }
        if proposal_id not in pending_ids:
            raise OMProposalError("Proposal is already resolved")
        writer.decision(
            {
                "id": decision_id,
                "target_id": target_id,
                "capability_id": capability_id,
                "action": "ACCEPT",
                "proposal_id": proposal_id,
                "claim_ids": list(claim_ids),
                "effective_at": effective_at,
                "recorded_at": recorded_at,
                "validity": {"valid_from": effective_at, "valid_to": None},
                "write_metadata": metadata,
            }
        )
    return Promotion(decision_id, claim_ids, metadata)


@dataclass(frozen=True)
class Rejection:
    decision_id: str
    claim_ids: tuple[str, ...]
    metadata: dict[str, Any]


def reject_candidate(
    memory: SQLiteOperationalMemory,
    *,
    target: str,
    capability: str,
    proposal_id: str,
    reason: str,
    reviewed_token: str,
    decision_id: str,
    recorded_at: str,
    effective_at: str,
    _writer: Any | None = None,
) -> Rejection:
    """Resolve exactly one pending Proposal with a REJECT Decision.

    A rejection asserts nothing positive: the Claims stay in history, are
    never accepted, and stop counting as pending. Only a pending Proposal
    of this target/capability may be rejected.
    """
    _require_boundary(memory)
    target_id, capability_id = _identity(memory, target, capability)
    validate_timestamp(recorded_at, field="rejection.recorded_at")
    validate_timestamp(effective_at, field="rejection.effective_at")
    if not isinstance(proposal_id, str) or not proposal_id.startswith("prop:"):
        raise OMProposalError("a canonical prop: Proposal identity is required")
    if not isinstance(decision_id, str) or not decision_id.startswith("dec:"):
        raise OMProposalError("a canonical dec: Decision identity is required")
    if not isinstance(reason, str) or not reason.strip():
        raise OMProposalError("a non-empty rejection reason is required")
    if len(reason) > 500:
        raise OMProposalError("rejection reason must be at most 500 characters")

    # Required pre-transaction stale-base check.  A second check under the
    # SQLite write lock below closes the check/write race.
    if review_token(memory, target=target, capability=capability) != reviewed_token:
        raise OMStaleBaseError("reviewed Operational Memory projection is stale")

    metadata = _operation_metadata(
        operation="REJECTION",
        target_id=target_id,
        capability_id=capability_id,
        proposal_id=proposal_id,
        decision_id=decision_id,
        recorded_at=recorded_at,
        effective_at=effective_at,
        reviewed_token=reviewed_token,
    )
    claim_ids: tuple[str, ...] = ()
    with _write_scope(memory, _writer) as writer:
        if review_token(memory, target=target, capability=capability) != reviewed_token:
            raise OMStaleBaseError("reviewed Operational Memory projection is stale")
        try:
            proposal = memory.get_record(proposal_id)
        except KeyError:
            raise OMProposalError("Proposal does not exist") from None
        if proposal.get("target_id") != target_id or proposal.get("capability_id") != capability_id:
            raise OMProposalError("Proposal target/capability scope does not match rejection")
        claim_ids = memory.proposal_claim_ids(proposal_id)
        if not claim_ids:
            raise OMProposalError("Proposal has no Claims")
        for member_claim_id in claim_ids:
            member_claim = memory.get_record(member_claim_id)
            if (
                member_claim.get("proposal_id") != proposal_id
                or member_claim.get("target_id") != target_id
                or member_claim.get("capability_id") != capability_id
            ):
                raise OMProposalError("Proposal contains a Claim with mismatched ownership")
        # Resolution uses the same canonical rule as every other read of
        # "is this Proposal still pending" (get_pending_candidates), so this
        # can never diverge from Operational Memory's own Decision Action
        # semantics the way a locally-reimplemented action list could.
        pending_ids = {
            item["proposal_id"]
            for item in memory.get_pending_candidates(target, capability)
        }
        if proposal_id not in pending_ids:
            raise OMProposalError("Proposal is already resolved")
        writer.decision(
            {
                "id": decision_id,
                "target_id": target_id,
                "capability_id": capability_id,
                "action": "REJECT",
                "proposal_id": proposal_id,
                "claim_ids": list(claim_ids),
                "reason": reason,
                "effective_at": effective_at,
                "recorded_at": recorded_at,
                "validity": {"valid_from": None, "valid_to": None},
                "write_metadata": metadata,
            }
        )
    return Rejection(decision_id, claim_ids, metadata)


__all__ = [
    "CandidateCapture",
    "CandidateEnrichment",
    "OMAmbiguousCandidateError",
    "OMNativeWriteError",
    "OMProposalError",
    "OMStaleBaseError",
    "Promotion",
    "Rejection",
    "Replacement",
    "TOKEN_VERSION",
    "WRITE_DESTINATION",
    "capture_candidate",
    "enrich_candidate",
    "promote_candidate",
    "reject_candidate",
    "replace_candidate",
    "review_token",
    "assert_om_native_write_authority",
]
