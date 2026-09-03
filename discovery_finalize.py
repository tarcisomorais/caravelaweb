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
    assert_om_native_write_authority, capture_candidate, enrich_candidate,
    promote_candidate, replace_candidate, review_token,
)
from operational_memory.core import (
    EPISTEMIC_CLASSES, SQLiteOperationalMemory, TargetIdentityError,
    is_canonical_target_id, normalize_capability_id, normalize_host_reference,
    RecordValidationError, validate_public_hostname, validate_timestamp,
)
from transport_policy import (
    AVAILABLE, CHROME, DIRECT_READ, INSUFFICIENT, LIGHTPANDA,
    PLATFORM_UNSUPPORTED, SATISFIED, UNAVAILABLE, TransportPolicyError,
    next_transport,
)


class DiscoveryFinalizationError(ValueError):
    """Discovery output is incomplete, non-reusable, or unsafe to retain."""

    def __init__(self, message: str, *, code: str = "PAYLOAD_INVALID") -> None:
        super().__init__(message)
        self.code = code


class _DryRunRollback(Exception):
    """Internal sentinel: unwinds ``write_transaction()`` without persisting it."""


# Correctable `NOT_SAVED` reason codes: the payload can be fixed and resubmitted
# under the same `run_id`, so the matching run stays open. Every other result
# closes the matching run. Kept beside `DiscoveryFinalization` so the CLI never
# duplicates this list.
RETRYABLE_REASON_CODES = frozenset({"TRANSPORT_POLICY_UNPROVEN", "FAILURE_UNCLASSIFIED"})


# `DiscoveryFinalizationError.code` vocabulary. Every `raise
# DiscoveryFinalizationError(...)` site in this module must pass one of these
# explicitly; `tests.test_discovery_finalize` walks the module's AST to
# enforce it. A site that fits none of these keeps the class default
# `PAYLOAD_INVALID`, but the AST test's allowlist for that default is empty,
# so every current site must be classified.
PAYLOAD_SHAPE = "PAYLOAD_SHAPE"
PAYLOAD_VALUE = "PAYLOAD_VALUE"
TASK_DATA_REJECTED = "TASK_DATA_REJECTED"
HOST_SCOPE = "HOST_SCOPE"
EVIDENCE_LINKAGE = "EVIDENCE_LINKAGE"
PROVENANCE = "PROVENANCE"
TRANSPORT_TRACE = "TRANSPORT_TRACE"
TARGET_REFERENCE = "TARGET_REFERENCE"


OPERATIONAL_FAMILIES = {
    "transport", "search_surface", "extraction", "pagination", "paywall",
    "authentication", "blocking", "validation", "limitation", "unknown",
}
# These two families assert a constraint or an absence -- the claims that are
# hardest to reread later and easiest to overstate. Claiming OBSERVED for one
# requires naming the transport and context that observed it; an unvalidated
# constraint stays INFERRED or UNKNOWN rather than silently ranking as fact.
_VALIDATION_REQUIRED_FAMILIES = frozenset({"blocking", "limitation"})
# `references/transport-and-modes.md` classifies these as runtime, tool, or
# environment state rather than target behavior, so none of them may turn a
# failed ladder into durable target knowledge. A ladder that reached no working
# transport must name a class outside this set before it is saved -- otherwise
# one bad network minute is stored as a property of the target.
_NON_DURABLE_FAILURE_CLASSES = frozenset({
    "TRANSIENT_NETWORK", "UPSTREAM_TOOL_ERROR", "LOCAL_ENVIRONMENT",
    "PLATFORM_UNSUPPORTED", "UNKNOWN",
})
_OPERATIONAL_PROOF_VERSION = 1
_TASK_DATA_TEXT = re.compile(r"<(?:html|body|article|script)\b|\b(?:R\$|US\$)\s?\d|\b(?:articles?|stores?|shops?)\s+(?:found|returned)\b", re.I)
_SCHEMA_FIELD_PATH = re.compile(
    r"^(?:\$|[A-Za-z_][A-Za-z0-9_]*)(?:\.[A-Za-z_][A-Za-z0-9_]*|\[\d*\])+$"
)
_FIELD_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SYMBOL = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]*$")
_EVIDENCE_KIND = re.compile(r"^[a-z][a-z0-9-]*$")
_TRANSPORTS = {DIRECT_READ, LIGHTPANDA, CHROME}
_BROWSER_TRANSPORTS = {LIGHTPANDA, CHROME}
_TRANSPORT_FAILURES = {"FAILED", "INSUFFICIENT"}


def _resolve_target_argument(memory: SQLiteOperationalMemory, target: str) -> str:
    """Resolve the top-level ``target`` argument to a stable canonical ID.

    A literal kebab-case reference (``gtolab``, ``example-jobs``) is used
    as-is -- it is never reinterpreted as a hostname. A URL/hostname
    reference (contains a dot) is resolved only against an *existing*
    target<->host association recorded via ``observation.host``: it is
    never used to manufacture a new target ID by slugging the hostname.
    First-time Discovery for a brand-new target must supply the stable
    canonical ID directly, e.g. ``target: "gtolab"`` with an accompanying
    ``host: "gtolab.com"`` observation to register the association.
    """
    if is_canonical_target_id(target.strip().lower()):
        return target.strip().lower()
    try:
        # Unstripped: normalize_host_reference itself fails closed on
        # leading/trailing/embedded whitespace rather than silently
        # trimming a malformed reference.
        host_reference = normalize_host_reference(target)
    except TargetIdentityError as exc:
        raise DiscoveryFinalizationError(
            f"target reference is ambiguous: {exc}", code=TARGET_REFERENCE
        ) from exc
    matches = memory.target_ids_for_host(host_reference)
    if not matches:
        raise DiscoveryFinalizationError(
            "no existing target is associated with this hostname; first-time "
            "Discovery must supply the stable canonical target ID directly",
            code=TARGET_REFERENCE,
        )
    if len(matches) > 1:
        raise DiscoveryFinalizationError(
            "this hostname is associated with more than one target; the "
            "stable canonical target ID must be supplied directly",
            code=TARGET_REFERENCE,
        )
    return matches[0].removeprefix("tgt:")


@dataclass(frozen=True)
class DiscoveryFinalization:
    status: str
    target: str
    capability: str
    proposal_id: str | None = None
    claims_created: int = 0
    reason: str | None = None
    reason_code: str | None = None
    lifecycle: str | None = None
    lifecycle_gap: str | None = None

    @property
    def closes_run(self) -> bool:
        """Whether this result closes the matching Discovery run.

        `SAVED`, `ALREADY_EXISTS`, and every terminal `NOT_SAVED` reason close
        the run. `TRANSPORT_POLICY_UNPROVEN` and `FAILURE_UNCLASSIFIED` are
        correctable, so they leave the run open for a corrected resubmission
        under the same `run_id`.
        """
        if self.status != "NOT_SAVED":
            return True
        return self.reason_code not in RETRYABLE_REASON_CODES

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status, "target": self.target, "capability": self.capability,
        }
        if self.status == "NOT_SAVED" and self.reason:
            result["reason"] = self.reason
        if self.status == "NOT_SAVED" and self.reason_code:
            result["reason_code"] = self.reason_code
        if self.status in ("SAVED", "ALREADY_EXISTS"):
            result["lifecycle"] = self.lifecycle
            if self.lifecycle is None:
                result["lifecycle_gap"] = self.lifecycle_gap
        result["run_state"] = "CLOSED" if self.closes_run else "OPEN"
        return result


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()[:20]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _reject_unsafe_content(value: Any, *, field: str = "observation") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise DiscoveryFinalizationError(
                    f"{field} keys must be strings", code=PAYLOAD_SHAPE
                )
            _reject_unsafe_content(child, field=field)
    elif isinstance(value, list):
        for child in value:
            _reject_unsafe_content(child, field=field)
    elif isinstance(value, str):
        if value.strip().upper().replace(" ", "_") == PLATFORM_UNSUPPORTED:
            raise DiscoveryFinalizationError(
                f"{field} contains platform runtime state, which is runtime "
                "or environment state, not target knowledge",
                code=TASK_DATA_REJECTED,
            )
        if len(value) > 500:
            raise DiscoveryFinalizationError(
                f"{field} contains task-specific or raw content: over 500 "
                f"characters ({len(value)})",
                code=TASK_DATA_REJECTED,
            )
        match = _TASK_DATA_TEXT.search(value)
        if match:
            raise DiscoveryFinalizationError(
                f"{field} contains task-specific or raw content: matches "
                f"raw-content pattern {match.group(0)!r}",
                code=TASK_DATA_REJECTED,
            )


def _exact_keys(
    value: Mapping[str, Any], *, field: str,
    required: set[str] | frozenset[str] = frozenset(),
    optional: set[str] | frozenset[str] = frozenset(),
) -> None:
    missing = required - set(value)
    unknown = set(value) - required - optional
    if missing:
        raise DiscoveryFinalizationError(
            f"{field} is missing required fields: {', '.join(sorted(missing))}. "
            f"Required: {', '.join(sorted(required)) or 'none'}; "
            f"optional: {', '.join(sorted(optional)) or 'none'}",
            code=PAYLOAD_SHAPE,
        )
    if unknown:
        raise DiscoveryFinalizationError(
            f"{field} contains unsupported fields: {', '.join(sorted(unknown))}. "
            f"Accepted fields: {', '.join(sorted(required | optional)) or 'none'}",
            code=PAYLOAD_SHAPE,
        )


def _text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DiscoveryFinalizationError(
            f"{field} must be a non-empty string", code=PAYLOAD_SHAPE
        )
    _reject_unsafe_content(value, field=field)
    return value


def _symbol(value: Any, *, field: str) -> str:
    value = _text(value, field=field)
    if not _SYMBOL.fullmatch(value):
        raise DiscoveryFinalizationError(
            f"{field} {value!r} must be a symbolic value: it starts with a "
            "letter and may contain letters, digits, '_', '.', ':', or '-' "
            "(for example SITE_BLOCKING)",
            code=PAYLOAD_VALUE,
        )
    return value


def _transport(value: Any, *, field: str) -> str:
    value = _symbol(value, field=field)
    if value not in _TRANSPORTS:
        raise DiscoveryFinalizationError(
            f"{field} {value!r} is not a supported transport. Accepted "
            f"transports: {', '.join((DIRECT_READ, LIGHTPANDA, CHROME))}",
            code=PAYLOAD_VALUE,
        )
    return value


def _schema_map(value: Any, *, field: str, paths: bool) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise DiscoveryFinalizationError(
            f"{field} must be a non-empty object", code=PAYLOAD_SHAPE
        )
    result: dict[str, str] = {}
    for key, locator in value.items():
        if not isinstance(key, str) or not _FIELD_NAME.fullmatch(key):
            raise DiscoveryFinalizationError(
                f"{field} contains an invalid output field: {key!r}",
                code=PAYLOAD_VALUE,
            )
        locator = _text(locator, field=f"{field}.{key}")
        if paths and not _SCHEMA_FIELD_PATH.fullmatch(locator):
            raise DiscoveryFinalizationError(
                f"{field}.{key} must be a reusable schema field path, not raw "
                "task content. Accepted forms: $.headline (explicit root), "
                "post.headline (dotted), items[].name (collection). A bare "
                "word such as 'headline' is invalid -- use $.headline",
                code=PAYLOAD_VALUE,
            )
        result[key] = locator
    return result


def _output_schema(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise DiscoveryFinalizationError(
            f"{field} must be a non-empty object", code=PAYLOAD_SHAPE
        )
    _exact_keys(
        value, field=field,
        optional={"structure", "field_paths", "selectors"},
    )
    result: dict[str, Any] = {}
    if "structure" in value:
        result["structure"] = _symbol(value["structure"], field=f"{field}.structure")
    if "field_paths" in value:
        result["field_paths"] = _schema_map(
            value["field_paths"], field=f"{field}.field_paths", paths=True
        )
    if "selectors" in value:
        result["selectors"] = _schema_map(
            value["selectors"], field=f"{field}.selectors", paths=False
        )
    if not ({"field_paths", "selectors"} & set(result)):
        raise DiscoveryFinalizationError(
            f"{field} requires field_paths or selectors", code=PAYLOAD_SHAPE
        )
    return result


def _operational_proof(value: Any) -> dict[str, Any]:
    field = "observation.value.operational_proof"
    if not isinstance(value, Mapping) or not value:
        raise DiscoveryFinalizationError(
            f"{field} must be a non-empty object", code=PAYLOAD_SHAPE
        )
    _exact_keys(
        value, field=field,
        optional={
            "entrypoint", "required_output", "required_action",
            "completion_condition", "critical_constraints",
        },
    )
    result: dict[str, Any] = {}
    if "entrypoint" in value:
        result["entrypoint"] = _text(value["entrypoint"], field=f"{field}.entrypoint")
    if "required_output" in value:
        result["required_output"] = _output_schema(
            value["required_output"], field=f"{field}.required_output"
        )
    if "required_action" in value:
        result["required_action"] = _text(
            value["required_action"], field=f"{field}.required_action"
        )
    if "completion_condition" in value:
        result["completion_condition"] = _text(
            value["completion_condition"], field=f"{field}.completion_condition"
        )
    if "critical_constraints" in value:
        constraints = value["critical_constraints"]
        if not isinstance(constraints, list):
            raise DiscoveryFinalizationError(
                f"{field}.critical_constraints must be an array",
                code=PAYLOAD_SHAPE,
            )
        normalized_constraints: list[str] = []
        for index, constraint in enumerate(constraints):
            constraint_field = f"{field}.critical_constraints[{index}]"
            normalized_constraints.append(_text(constraint, field=constraint_field))
        result["critical_constraints"] = normalized_constraints
    return result


_FAMILY_FIELDS = {
    "transport": {"transport", "outcome", "requirement"},
    "search_surface": {"surface", "path", "entrypoint", "method", "loading"},
    "extraction": {
        "structure", "field_paths", "selectors", "transport", "outcome",
        "evidence_quality",
    },
    "pagination": {"mode", "parameter", "path", "next_path", "stop_condition"},
    "paywall": {"signal", "state", "condition"},
    "authentication": {"access_model", "entrypoint", "condition"},
    "blocking": {"failure_class", "signal", "state", "condition"},
    "limitation": {"kind", "mode", "state", "condition", "constraint"},
    "unknown": {"state", "subject", "condition"},
}
_TEXT_FIELDS = {
    "path", "entrypoint", "stop_condition", "condition", "constraint", "subject",
}


def _normalize_family_value(family: str, value: Mapping[str, Any]) -> dict[str, Any]:
    field = "observation.value"
    if family == "validation":
        _exact_keys(value, field=field, optional={"rule", "operational_proof"})
        if len(value) != 1:
            raise DiscoveryFinalizationError(
                "validation value requires exactly one reusable validation "
                "form: rule or operational_proof",
                code=PAYLOAD_SHAPE,
            )
        if "rule" in value:
            return {"rule": _symbol(value["rule"], field=f"{field}.rule")}
        return {"operational_proof": _operational_proof(value["operational_proof"])}

    allowed = _FAMILY_FIELDS[family]
    _exact_keys(value, field=field, optional=allowed)
    result: dict[str, Any] = {}
    for key, child in value.items():
        child_field = f"{field}.{key}"
        if key == "transport":
            result[key] = _transport(child, field=child_field)
        elif key == "field_paths":
            result[key] = _schema_map(child, field=child_field, paths=True)
        elif key == "selectors":
            result[key] = _schema_map(child, field=child_field, paths=False)
        elif key in _TEXT_FIELDS:
            result[key] = _text(child, field=child_field)
        else:
            result[key] = _symbol(child, field=child_field)
    return result


def _is_canonical_family_value(family: str, value: Mapping[str, Any]) -> bool:
    try:
        return _normalize_family_value(family, value) == value
    except DiscoveryFinalizationError:
        return False


def _normalize_hostname(value: Any) -> str | None:
    """Validate and canonicalize ``observation.host``.

    Shares :func:`validate_public_hostname` with target-reference
    resolution for its structural guarantees (no whitespace, no IP
    literal, no malformed dots, canonical IDNA form), but does not strip a
    leading ``www.``: an observation's host is a literal recorded host
    scope, so ``www.example.com`` and ``example.com`` must stay distinct.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise DiscoveryFinalizationError(
            "observation.host must be a hostname", code=HOST_SCOPE
        )
    try:
        return validate_public_hostname(value)
    except TargetIdentityError as exc:
        raise DiscoveryFinalizationError(
            f"observation.host must be a normalized public hostname: {exc}",
            code=HOST_SCOPE,
        ) from exc


def _normalize_validation(value: Any, *, field: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise DiscoveryFinalizationError(
            f"{field} must be an object", code=PAYLOAD_SHAPE
        )
    allowed = {
        "transport", "engine", "javascript", "context", "outcome",
        "failure_class", "evidence",
    }
    unsupported = set(value) - allowed
    if unsupported:
        raise DiscoveryFinalizationError(
            f"{field} contains unsupported keys: {', '.join(sorted(unsupported))}. "
            f"Accepted top-level validation keys: {', '.join(sorted(allowed))}",
            code=PAYLOAD_SHAPE,
        )
    context = value.get("context", {})
    if not isinstance(context, Mapping):
        raise DiscoveryFinalizationError(
            f"{field}.context must be an object", code=PAYLOAD_SHAPE
        )
    _exact_keys(
        context, field=f"{field}.context",
        optional={"authentication", "environment"},
    )
    clean: dict[str, Any] = {}
    if "transport" in value:
        clean["transport"] = _transport(value["transport"], field=f"{field}.transport")
    if "engine" in value:
        clean["engine"] = (
            None if value["engine"] is None
            else _text(value["engine"], field=f"{field}.engine")
        )
    if "javascript" in value:
        if not isinstance(value["javascript"], bool):
            raise DiscoveryFinalizationError(
                f"{field}.javascript must be a boolean", code=PAYLOAD_SHAPE
            )
        clean["javascript"] = value["javascript"]
    for key in ("outcome", "failure_class"):
        if key in value:
            clean[key] = _symbol(value[key], field=f"{field}.{key}")
    references = value.get("evidence", [])
    if (
        not isinstance(references, Sequence)
        or isinstance(references, (str, bytes))
        or any(not isinstance(item, str) or not item for item in references)
    ):
        raise DiscoveryFinalizationError(
            f"{field}.evidence must be an array of locators",
            code=EVIDENCE_LINKAGE,
        )
    clean["evidence"] = sorted(set(references))
    clean["context"] = {
        key: _symbol(child, field=f"{field}.context.{key}")
        for key, child in context.items()
    }
    _reject_unsafe_content(clean, field=field)
    return clean


def _normalize_observations(observations: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(observations, Sequence) or isinstance(observations, (str, bytes)):
        raise DiscoveryFinalizationError(
            "observations must be an array", code=PAYLOAD_SHAPE
        )
    normalized: dict[str, dict[str, Any]] = {}
    for item in observations:
        if not isinstance(item, Mapping):
            raise DiscoveryFinalizationError(
                "every observation must be an object", code=PAYLOAD_SHAPE
            )
        family = item.get("family")
        epistemic = item.get("epistemic", "OBSERVED")
        value = item.get("value")
        host = _normalize_hostname(item.get("host"))
        if family not in OPERATIONAL_FAMILIES:
            raise DiscoveryFinalizationError(
                f"observation.family {family!r} is not a reusable operational "
                f"family. Accepted families: {', '.join(sorted(OPERATIONAL_FAMILIES))}",
                code=PAYLOAD_VALUE,
            )
        _exact_keys(
            item, field="observation",
            required={"family", "value"},
            optional={"epistemic", "host", "validation", "contradiction"},
        )
        if epistemic not in EPISTEMIC_CLASSES:
            raise DiscoveryFinalizationError(
                f"observation.epistemic {epistemic!r} is invalid. Accepted "
                f"epistemic classes: {', '.join(('OBSERVED', 'INFERRED', 'UNKNOWN'))}",
                code=PAYLOAD_VALUE,
            )
        if not isinstance(value, Mapping) or not value:
            raise DiscoveryFinalizationError(
                "observation.value must be a non-empty object", code=PAYLOAD_SHAPE
            )
        clean_value = _normalize_family_value(str(family), value)
        validation = _normalize_validation(item.get("validation"), field="observation.validation")
        if family in _VALIDATION_REQUIRED_FAMILIES and epistemic == "OBSERVED":
            # Every validation field is individually optional, so presence alone
            # proves nothing: `{}` normalizes to an empty context and no
            # transport. Require every field the rule actually asks for.
            context = (validation or {}).get("context") or {}
            if (
                validation is None
                or not _meaningful(validation.get("transport"))
                or "engine" not in validation
                or not isinstance(validation.get("javascript"), bool)
                or set(context) != {"authentication", "environment"}
                or any(not _meaningful(child) for child in context.values())
            ):
                raise DiscoveryFinalizationError(
                    f"an OBSERVED {family} observation requires a validation "
                    "naming the transport, engine, javascript, and "
                    "authentication/environment context that observed it",
                    code=PAYLOAD_VALUE,
                )
        contradiction = item.get("contradiction")
        clean_contradiction = None
        if contradiction is not None:
            if not isinstance(contradiction, Mapping) or set(contradiction) != {"prior_value", "validation"}:
                raise DiscoveryFinalizationError(
                    "observation.contradiction requires prior_value and validation",
                    code=PAYLOAD_SHAPE,
                )
            if not isinstance(contradiction["prior_value"], Mapping) or not contradiction["prior_value"]:
                raise DiscoveryFinalizationError(
                    "contradiction.prior_value must be a non-empty object",
                    code=PAYLOAD_SHAPE,
                )
            clean_contradiction = {
                "prior_value": _normalize_family_value(
                    str(family), contradiction["prior_value"]
                ),
                "validation": _normalize_validation(
                    contradiction["validation"], field="observation.contradiction.validation"
                ),
            }
        semantic = {"family": family, "epistemic": epistemic, "value": clean_value, "host": host}
        normalized[_canonical(semantic)] = {
            "family": family, "epistemic": epistemic, "value": clean_value,
            "host": host, "validation": validation, "contradiction": clean_contradiction,
        }
    return [normalized[key] for key in sorted(normalized)]


def _meaningful(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return isinstance(value, (Mapping, list)) and bool(value)


def _operational_proof_dependencies(
    memory: SQLiteOperationalMemory,
    target: str,
    capability: str,
    claims: Sequence[Mapping[str, Any]],
    evidence: Sequence[Mapping[str, Any]],
    validated_transport: tuple[str | None, str] | None,
) -> tuple[tuple[str, ...] | None, str | None]:
    """Return the Claims that prove one reproducible path, or fail closed.

    On success: ``(claim_ids, None)``. On failure: ``(None, <gap code>)``
    naming the first condition the last-considered proof failed, or
    ``NO_OPERATIONAL_PROOF`` when no candidate proof existed at all.
    """
    try:
        current = memory.get_current(target, capability)
    except KeyError:
        current = {"accepted_claims": [], "contradiction_warnings": []}
    merged = [*current["accepted_claims"], *claims]
    contradicted = {
        warning["contradicted_claim_id"]
        for warning in current["contradiction_warnings"]
    }

    proofs: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for claim in merged:
        if claim["family"] != "validation" or claim["epistemic"] != "OBSERVED":
            continue
        value = claim["value"]
        if not isinstance(value, Mapping) or set(value) != {"operational_proof"}:
            continue
        validation = claim.get("discovery_validation")
        if validation is None:
            try:
                validation = memory.get_record(str(claim["id"])).get("discovery_validation")
            except KeyError:
                continue
        if isinstance(validation, Mapping):
            proofs.append((claim, validation))

    eligible: list[tuple[str, ...]] = []
    gap: str | None = "NO_OPERATIONAL_PROOF" if not proofs else None
    evidence_locators = {item["locator"] for item in evidence}
    for proof_claim, validation in proofs:
        proof = proof_claim["value"]["operational_proof"]
        if not isinstance(proof, Mapping):
            gap = "PROOF_SHAPE_INVALID"
            continue
        try:
            if _operational_proof(proof) != proof:
                gap = "PROOF_SHAPE_INVALID"
                continue
        except DiscoveryFinalizationError:
            gap = "PROOF_SHAPE_INVALID"
            continue
        required = {"entrypoint", "completion_condition", "critical_constraints"}
        if not required <= proof.keys() or set(proof) - required - {"required_output", "required_action"}:
            gap = "PROOF_SHAPE_INVALID"
            continue
        if ("required_output" in proof) == ("required_action" in proof):
            gap = "PROOF_SHAPE_INVALID"
            continue
        if (
            not _meaningful(proof["entrypoint"])
            or not _meaningful(proof["completion_condition"])
            or not _meaningful(proof.get("required_output", proof.get("required_action")))
            or not isinstance(proof["critical_constraints"], list)
        ):
            gap = "PROOF_SHAPE_INVALID"
            continue
        references = validation.get("evidence")
        if (
            validation.get("outcome") != "SUCCESS"
            or not isinstance(references, list)
            or not references
        ):
            gap = "PROOF_VALIDATION_NOT_SUCCESS"
            continue
        proof_id = str(proof_claim["id"])
        if proof_id in contradicted:
            gap = "PROOF_CONTRADICTED"
            continue
        if proof_claim in claims:
            if not set(references) <= evidence_locators:
                gap = "PROOF_EVIDENCE_UNREFERENCED"
                continue
        else:
            recorded = {
                item.get("locator") for item in memory.get_evidence(proof_id)["evidence"]
            }
            if not set(references) <= recorded:
                gap = "PROOF_EVIDENCE_UNREFERENCED"
                continue

        transport = validation.get("transport")
        context = validation.get("context")
        access_model = context.get("authentication") if isinstance(context, Mapping) else None
        if not _meaningful(transport) or not _meaningful(access_model):
            gap = "PROOF_CONTEXT_INCOMPLETE"
            continue
        if transport in {"LIGHTPANDA", "CHROME"} and (
            not _meaningful(validation.get("engine"))
            or not isinstance(validation.get("javascript"), bool)
        ):
            gap = "PROOF_BROWSER_CONTEXT_INCOMPLETE"
            continue

        proof_host = proof_claim.get("host_id")
        in_scope = lambda claim: claim.get("host_id") in {None, proof_host}
        all_transport_facts = [
            claim for claim in merged
            if claim["family"] == "transport"
            and in_scope(claim)
            and claim["id"] not in contradicted
        ]
        access_facts = [
            claim for claim in merged
            if claim["family"] == "authentication"
            and in_scope(claim)
            and claim["id"] not in contradicted
        ]
        if any(
            claim["epistemic"] != "OBSERVED"
            or not isinstance(claim["value"], Mapping)
            or not _is_canonical_family_value("transport", claim["value"])
            or not _meaningful(claim["value"].get("transport"))
            for claim in all_transport_facts
        ) or any(
            claim["epistemic"] != "OBSERVED"
            or not isinstance(claim["value"], Mapping)
            or not _is_canonical_family_value("authentication", claim["value"])
            or not _meaningful(claim["value"].get("access_model"))
            for claim in access_facts
        ):
            gap = "SUPPORTING_CLAIM_NOT_OBSERVED"
            continue
        transport_facts = [
            claim for claim in all_transport_facts
            if claim["value"].get("outcome") == "FUNCTIONAL"
        ]
        if transport in _BROWSER_TRANSPORTS and validated_transport != (
            proof_host, transport
        ):
            gap = "TRANSPORT_LADDER_UNPROVEN"
            continue
        transports = {
            claim["value"].get("transport") for claim in transport_facts
            if _meaningful(claim["value"].get("transport"))
        }
        access_models = {
            claim["value"].get("access_model") for claim in access_facts
            if _meaningful(claim["value"].get("access_model"))
        }
        if transports == {transport} and access_models == {access_model}:
            transport_claim = next(
                claim for claim in transport_facts
                if claim["value"].get("transport") == transport
            )
            access_claim = next(
                claim for claim in access_facts
                if claim["value"].get("access_model") == access_model
            )
            eligible.append(tuple(sorted({
                proof_id, str(transport_claim["id"]), str(access_claim["id"]),
            })))
        else:
            gap = (
                "NO_FUNCTIONAL_TRANSPORT_CLAIM" if not transports
                else "NO_AUTHENTICATION_CLAIM" if not access_models
                else "SUPPORTING_FACTS_AMBIGUOUS"
            )
    if len(eligible) == 1:
        return eligible[0], None
    if len(eligible) > 1:
        return None, "MULTIPLE_ELIGIBLE_PROOFS"
    return None, gap or "NO_OPERATIONAL_PROOF"


def _validate_provenance(provenance: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(provenance, Mapping) or not provenance:
        raise DiscoveryFinalizationError(
            "run provenance is required", code=PROVENANCE
        )
    _exact_keys(
        provenance, field="provenance",
        required={"run_id", "observed_at"},
    )
    run_id, observed_at = provenance["run_id"], provenance["observed_at"]
    run_id = _text(run_id, field="provenance.run_id")
    validate_timestamp(observed_at, field="provenance.observed_at")
    return {"run_id": run_id, "observed_at": observed_at}


def _validate_evidence(evidence: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(evidence, Sequence) or isinstance(evidence, (str, bytes)) or not evidence:
        raise DiscoveryFinalizationError(
            "evidence is required", code=EVIDENCE_LINKAGE
        )
    result: dict[str, dict[str, Any]] = {}
    for item in evidence:
        if not isinstance(item, Mapping):
            raise DiscoveryFinalizationError(
                "every evidence item must be an object", code=EVIDENCE_LINKAGE
            )
        _exact_keys(
            item, field="evidence",
            required={"kind", "locator"}, optional={"scope"},
        )
        kind, locator = item.get("kind"), item.get("locator")
        if not isinstance(kind, str) or not _EVIDENCE_KIND.fullmatch(kind):
            raise DiscoveryFinalizationError(
                f"evidence.kind {kind!r} must be a lowercase symbolic value: "
                "it starts with a lowercase letter and may contain lowercase "
                "letters, digits, or '-' (for example direct-read-validation)",
                code=EVIDENCE_LINKAGE,
            )
        locator = _text(locator, field="evidence.locator")
        clean = {"kind": kind, "locator": locator}
        if "scope" in item:
            clean["scope"] = _symbol(item["scope"], field="evidence.scope")
        result[_canonical(clean)] = clean
    return [result[key] for key in sorted(result)]


def _normalize_transport_trace(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise DiscoveryFinalizationError(
            "transport_trace must be an object", code=TRANSPORT_TRACE
        )
    _exact_keys(
        value, field="transport_trace",
        required={"availability", "attempts"},
    )
    availability = value["availability"]
    if not isinstance(availability, Mapping):
        raise DiscoveryFinalizationError(
            "transport_trace.availability must be an object",
            code=TRANSPORT_TRACE,
        )
    _exact_keys(
        availability, field="transport_trace.availability",
        required={LIGHTPANDA, CHROME},
    )
    clean_availability = dict(availability)
    if any(
        not isinstance(status, str) or not _SYMBOL.fullmatch(status)
        for status in clean_availability.values()
    ):
        raise DiscoveryFinalizationError(
            "transport_trace availability contains an invalid status: "
            f"{clean_availability!r}",
            code=TRANSPORT_TRACE,
        )
    if any(
        status not in {AVAILABLE, UNAVAILABLE, PLATFORM_UNSUPPORTED}
        for status in clean_availability.values()
    ):
        raise DiscoveryFinalizationError(
            f"transport_trace availability contains an unsupported status: "
            f"{clean_availability!r}. Accepted statuses: "
            f"{', '.join((AVAILABLE, UNAVAILABLE, PLATFORM_UNSUPPORTED))}",
            code=TRANSPORT_TRACE,
        )

    attempts = value["attempts"]
    if (
        not isinstance(attempts, Sequence)
        or isinstance(attempts, (str, bytes))
        or not attempts
    ):
        raise DiscoveryFinalizationError(
            "transport_trace.attempts must be a non-empty array",
            code=TRANSPORT_TRACE,
        )
    clean_attempts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for attempt in attempts:
        if not isinstance(attempt, Mapping):
            raise DiscoveryFinalizationError(
                "every transport_trace attempt must be an object",
                code=TRANSPORT_TRACE,
            )
        _exact_keys(
            attempt, field="transport_trace.attempt",
            required={"transport", "outcome", "evidence"}, optional={"host"},
        )
        transport = _transport(
            attempt["transport"], field="transport_trace.attempt.transport"
        )
        if transport in seen:
            raise DiscoveryFinalizationError(
                f"transport_trace may attempt each transport only once: "
                f"{transport!r} was already attempted",
                code=TRANSPORT_TRACE,
            )
        seen.add(transport)
        outcome = _symbol(
            attempt["outcome"], field="transport_trace.attempt.outcome"
        )
        if outcome not in _TRANSPORT_FAILURES | {"FUNCTIONAL"}:
            raise DiscoveryFinalizationError(
                f"transport_trace attempt outcome {outcome!r} must be one of "
                f"{', '.join(('FAILED', 'INSUFFICIENT', 'FUNCTIONAL'))}",
                code=TRANSPORT_TRACE,
            )
        references = attempt["evidence"]
        if (
            not isinstance(references, Sequence)
            or isinstance(references, (str, bytes))
            or not references
            or any(not isinstance(item, str) or not item for item in references)
        ):
            raise DiscoveryFinalizationError(
                "transport_trace attempt evidence must be a non-empty locator array",
                code=TRANSPORT_TRACE,
            )
        clean_attempts.append({
            "transport": transport,
            "outcome": outcome,
            "host": _normalize_hostname(attempt.get("host")),
            "evidence": sorted(set(references)),
        })
    return {"availability": clean_availability, "attempts": clean_attempts}


def _failed_without_a_working_transport(observations: Sequence[Mapping[str, Any]]) -> bool:
    """True when this run recorded failures and reached nothing that worked."""
    failed = False
    for item in observations:
        validation = item.get("validation")
        if validation and validation.get("outcome") in {"FUNCTIONAL", "SUCCESS"}:
            return False
        if item["family"] != "transport":
            continue
        outcome = item["value"].get("outcome")
        if outcome == "FUNCTIONAL":
            return False
        failed = failed or outcome in _TRANSPORT_FAILURES
    return failed


def _durable_failure_classified(observations: Sequence[Mapping[str, Any]]) -> bool:
    """True when some observation says why the ladder failed, durably."""
    classes: set[Any] = set()
    for item in observations:
        if item["family"] == "blocking":
            classes.add(item["value"].get("failure_class"))
        for source in (item.get("validation"), (item.get("contradiction") or {}).get("validation")):
            if source:
                classes.add(source.get("failure_class"))
    return any(
        isinstance(item, str) and item not in _NON_DURABLE_FAILURE_CLASSES
        for item in classes
    )


def _browser_trace_required(observations: Sequence[Mapping[str, Any]]) -> bool:
    return any(
        transport in _BROWSER_TRANSPORTS
        for item in observations
        for transport in (
            item["value"].get("transport"),
            (item.get("validation") or {}).get("transport"),
        )
    )


def _validated_transport_trace(
    trace: Mapping[str, Any], observations: Sequence[Mapping[str, Any]],
    evidence: Sequence[Mapping[str, Any]], host_ids: Mapping[str, str],
) -> tuple[bool, tuple[str | None, str] | None]:
    """Return (ladder proven, operational transport).

    A ladder is proven when it either reaches a `FUNCTIONAL` transport or is
    exhausted with every available transport attempted. The second case is a
    fully blocked capability: it is a complete, reusable observation that
    identifies no operational transport, so it returns `(True, None)`.
    """
    availability = trace["availability"]
    policy_attempts: dict[str, str] = {}
    selected: tuple[str | None, str] | None = None
    evidence_locators = {item["locator"] for item in evidence}
    material_context: dict[str, Any] | None = None

    observed: list[dict[str, Any]] = []
    for item in observations:
        validation = item.get("validation")
        if validation:
            observed.append({
                "host": item.get("host"), "value": item["value"],
                "validation": validation, "functional": True,
                "epistemic": item["epistemic"],
                "transport_claim": item["family"] == "transport",
            })
        contradiction = item.get("contradiction")
        if contradiction:
            observed.append({
                "host": item.get("host"),
                "value": contradiction["prior_value"],
                "validation": contradiction["validation"],
                "functional": False, "epistemic": item["epistemic"],
                "transport_claim": item["family"] == "transport",
            })

    for attempt in trace["attempts"]:
        transport, outcome = attempt["transport"], attempt["outcome"]
        try:
            expected = next_transport(policy_attempts, availability)
        except TransportPolicyError:
            return False, None
        if expected != transport:
            return False, None
        policy_outcome = SATISFIED if outcome == "FUNCTIONAL" else INSUFFICIENT
        policy_attempts[transport] = policy_outcome

        references = set(attempt["evidence"])
        if not references <= evidence_locators:
            return False, None
        matches: list[dict[str, Any]] = []
        for candidate in observed:
            validation = candidate["validation"]
            value = candidate["value"]
            validation_outcome = validation.get("outcome")
            if (
                candidate["epistemic"] != "OBSERVED"
                or candidate["host"] != attempt["host"]
                or validation.get("transport") != transport
                or not references <= set(validation.get("evidence", ()))
                or "engine" not in validation
                or not isinstance(validation.get("javascript"), bool)
            ):
                continue
            if candidate["transport_claim"] and value.get("transport") != transport:
                continue
            if outcome == "FUNCTIONAL":
                if (
                    not candidate["functional"]
                    or validation_outcome != "FUNCTIONAL"
                    or (
                        candidate["transport_claim"]
                        and value.get("outcome") != "FUNCTIONAL"
                    )
                ):
                    continue
            elif validation_outcome not in _TRANSPORT_FAILURES or (
                candidate["functional"] and candidate["transport_claim"]
                and value.get("outcome") not in _TRANSPORT_FAILURES
            ):
                continue
            context = validation.get("context")
            if (
                not isinstance(context, Mapping)
                or set(context) != {"authentication", "environment"}
                or any(not _meaningful(child) for child in context.values())
            ):
                continue
            matches.append(candidate)
        contexts = {_canonical(item["validation"]["context"]) for item in matches}
        if len(contexts) != 1:
            return False, None
        context = dict(matches[0]["validation"]["context"])
        if material_context is None:
            material_context = context
        elif material_context != context:
            return False, None
        if outcome == "FUNCTIONAL":
            selected = (
                host_ids.get(str(attempt["host"])) if attempt["host"] else None,
                transport,
            )

    if selected is None:
        # No transport worked. The ladder still proves the capability's real
        # state -- but only when it was actually exhausted. Two things must
        # hold: the policy has no next step, and no transport this machine
        # actually has was left untried. The second is not implied by the
        # first. `next_transport` halts at an UNAVAILABLE Lightpanda tier even
        # when Chrome is present, and a run that never reached Chrome cannot
        # claim the capability is blocked.
        try:
            remaining = next_transport(policy_attempts, availability)
        except TransportPolicyError:
            return False, None
        untried = {
            transport for transport, status in availability.items()
            if status == AVAILABLE and transport not in policy_attempts
        }
        if remaining is not None or untried:
            return False, None
    return True, selected


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
        raise DiscoveryFinalizationError(
            "validation references unknown evidence", code=EVIDENCE_LINKAGE
        )
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
    semantic_keys: set[str],
) -> tuple[str, dict[str, str]] | None:
    matches: list[tuple[str, dict[str, str]]] = []
    for proposal in memory.get_pending_candidates(target, capability):
        claim_ids: dict[str, str] = {}
        for row in memory._conn.execute(
            """SELECT id,family,epistemic,value_json,host_id FROM claims
               WHERE proposal_id=? ORDER BY id""",
            (proposal["proposal_id"],),
        ):
            key = _semantic_key(
                row["family"], row["epistemic"],
                json.loads(row["value_json"]), row["host_id"],
            )
            claim_ids[key] = row["id"]
        if set(claim_ids) == semantic_keys and len(claim_ids) == len(
            proposal["claim_ids"]
        ):
            matches.append((proposal["proposal_id"], claim_ids))
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
            raise DiscoveryFinalizationError(
                "hostname scope is ambiguous for this target", code=HOST_SCOPE
            )
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
            evidence_hostnames = sorted({
                urlparse(str(source["locator"])).hostname.lower().rstrip(".")
                for source in evidence
                if urlparse(str(source.get("locator", ""))).hostname
            })
            raise DiscoveryFinalizationError(
                f"a new observation host requires TARGET_SURFACE evidence from "
                f"that hostname. Claimed Observation Host: {hostname!r}. "
                f"Public hostnames found in evidence locators: {evidence_hostnames!r}. "
                "An evidence item's scope must be exactly 'TARGET_SURFACE', and "
                "its locator hostname must exactly match the literal Observation "
                "Host (a leading 'www.' is not normalized here, unlike target "
                "reference resolution)",
                code=HOST_SCOPE,
            )
        # Target-reference resolution reads these associations, and it fails
        # closed on more than one match. Creating the second one silently would
        # make the hostname permanently unresolvable, so refuse it here where
        # the caller can still correct the target.
        if any(other != target_id for other in memory.target_ids_for_host(hostname)):
            raise DiscoveryFinalizationError(
                "this hostname is already associated with a different target",
                code=HOST_SCOPE,
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
        return tuple(candidates), False, "INSUFFICIENT_BILATERAL_EVIDENCE"
    support = list(memory._conn.execute(
        """SELECT v.host_id,v.transport,v.context_json
           FROM claim_observations co
           JOIN observations o ON o.id=co.observation_id
           JOIN validations v ON v.id=o.validation_id
           WHERE co.claim_id=? AND co.relation='supports'""",
        (candidates[0],),
    ))
    if len(support) != 1:
        return tuple(candidates), False, "INSUFFICIENT_MATERIAL_BASELINE"
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
        return tuple(candidates), False, "INSUFFICIENT_MATERIAL_BASELINE"
    if old_material is None or new_material is None or baseline != old_material:
        return tuple(candidates), False, "INCOMPARABLE_MATERIAL_CONTEXT"
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
        return tuple(candidates), False, "INCOMPARABLE_MATERIAL_CONTEXT"
    return tuple(candidates), True, None


def _has_conflict(
    memory: SQLiteOperationalMemory,
    target: str,
    capability: str,
    delta: Sequence[Mapping[str, Any]],
    host_ids: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Keep conflicting observations out of automatic acceptance.

    This is deliberately a small structural gate, not a risk classifier: an
    automatic Decision is allowed only when a family has no other value in the
    current accepted or pending view. Returns the conflicting Claims (empty
    list means no conflict) so a refusal can name what blocked it.
    """
    # Operational proofs are append-only evidence summaries: an incomplete
    # earlier summary may be completed by a later Discovery, while two complete
    # summaries remain ambiguous at the dedicated proof gate above.
    conflict_delta = [
        item for item in delta
        if not (
            item["family"] == "validation"
            and isinstance(item["value"], Mapping)
            and "operational_proof" in item["value"]
        )
    ]
    families = {str(item["family"]) for item in conflict_delta}
    if not families:
        return []
    delta_values: dict[tuple[str, str | None, str | None], set[str]] = {}
    for item in conflict_delta:
        host_id = host_ids.get(str(item.get("host"))) if item.get("host") else None
        transport = (
            item["value"].get("transport")
            if item["family"] == "transport" else None
        )
        delta_values.setdefault((item["family"], host_id, transport), set()).add(
            json.dumps(item["value"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
    intra_delta_conflicts = [
        {
            "source": "payload",
            "family": key[0],
            "host_id": key[1],
            "values": sorted(values),
        }
        for key, values in delta_values.items()
        if len(values) > 1
    ]
    if intra_delta_conflicts:
        return intra_delta_conflicts
    try:
        capability_id = memory.resolve_capability(target, capability)
    except KeyError:
        return []
    current_claim_ids = set(memory.get_current(target, capability)["accepted_claim_ids"])
    pending_claim_ids = {
        claim_id
        for proposal in memory.get_pending_candidates(target, capability)
        for claim_id in proposal["claim_ids"]
    }
    claim_ids = sorted(current_claim_ids | pending_claim_ids)
    if not claim_ids:
        return []
    rows = memory._conn.execute(
        """SELECT id,family,value_json,host_id FROM claims
           WHERE id IN ({}) AND family IN ({})""".format(
            ",".join("?" for _ in claim_ids), ",".join("?" for _ in families)
        ),
        (*claim_ids, *sorted(families)),
    )
    current_values: dict[tuple[str, str | None, str | None], set[tuple[str, str]]] = {}
    for row in rows:
        value = json.loads(row["value_json"])
        key = (
            row["family"], row["host_id"],
            value.get("transport") if row["family"] == "transport" else None,
        )
        current_values.setdefault(key, set()).add(
            (
                row["id"],
                json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            )
        )
    conflicts: list[dict[str, Any]] = []
    for item in conflict_delta:
        key = (
            item["family"],
            host_ids.get(str(item.get("host"))) if item.get("host") else None,
            item["value"].get("transport") if item["family"] == "transport" else None,
        )
        item_value_json = json.dumps(
            item["value"], ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        for claim_id, value_json in current_values.get(key, set()):
            if value_json == item_value_json:
                continue
            conflicts.append({
                "source": "accepted" if claim_id in current_claim_ids else "pending",
                "claim_id": claim_id,
                "family": key[0],
                "host_id": key[1],
                "value": json.loads(value_json),
            })
    return conflicts


def finalize_discovery(
    memory: SQLiteOperationalMemory,
    *, target: str, capability: str, observations: Sequence[Mapping[str, Any]],
    evidence: Sequence[Mapping[str, Any]], provenance: Mapping[str, Any],
    transport_trace: Mapping[str, Any] | None = None,
    recorded_at: str | None = None,
    dry_run: bool = False,
) -> DiscoveryFinalization:
    """Finalize Discovery into local OM, accepting only direct observations.

    ``dry_run`` executes the identical write path and rolls it back before
    commit, via `_DryRunRollback` -- it never introduces a second validator or
    a separate prediction path. Early no-write results (schema rejection,
    ``NO_REUSABLE_KNOWLEDGE``, ``ALREADY_EXISTS``, ...) return normally
    without reaching ``write_transaction()`` at all.
    """
    if not isinstance(target, str) or not target.strip():
        raise DiscoveryFinalizationError(
            "target and capability are required", code=PAYLOAD_SHAPE
        )
    target = _resolve_target_argument(memory, target)
    try:
        capability = normalize_capability_id(capability)
    except RecordValidationError as exc:
        raise DiscoveryFinalizationError(str(exc), code=PAYLOAD_VALUE) from exc
    # Validate authority before examining or normalizing Discovery output. This
    # deliberately fails closed when the installation is not OM-writable, and
    # is derived solely from memory.knowledge_root's real write-authority
    # marker -- no caller-supplied argument can assert or bypass it.
    assert_om_native_write_authority(memory)
    recorded_at = recorded_at or _now()
    validate_timestamp(recorded_at, field="finalize_discovery.recorded_at")
    normalized = _normalize_observations(observations)
    clean_provenance = _validate_provenance(provenance)
    if not normalized:
        return DiscoveryFinalization(
            "NOT_SAVED", target, capability,
            reason="Discovery found no reusable operating knowledge.",
            reason_code="NO_REUSABLE_KNOWLEDGE",
        )
    clean_evidence = _validate_evidence(evidence)
    host_ids, hosts_to_create = _host_plan(memory, target, normalized, clean_evidence)
    clean_trace = _normalize_transport_trace(transport_trace)
    ladder_proven, validated_transport = (
        _validated_transport_trace(
            clean_trace, normalized, clean_evidence, host_ids
        )
        if clean_trace else (False, None)
    )
    if (clean_trace is not None or _browser_trace_required(normalized)) and not ladder_proven:
        return DiscoveryFinalization(
            "NOT_SAVED", target, capability,
            reason=(
                "The transport ladder and available simpler transports were not "
                "proven by this Discovery run. Supply a run-scoped "
                "transport_trace covering every transport this run attempted, "
                "including a ladder where all of them were blocked. Never drop "
                "an observation, validation, or evidence item to pass this gate."
            ),
            reason_code="TRANSPORT_POLICY_UNPROVEN",
        )
    if _failed_without_a_working_transport(normalized) and not _durable_failure_classified(normalized):
        return DiscoveryFinalization(
            "NOT_SAVED", target, capability,
            reason=(
                "This run reached no working transport and did not classify why. "
                "Classify the failure first: a transient network fault, a tool "
                "error, or a local environment problem is runtime state and "
                "never becomes target knowledge. Record the durable class "
                "(for example SITE_BLOCKING, AUTH_REQUIRED, or "
                "AUTHORITY_BOUNDARY) that this run actually observed."
            ),
            reason_code="FAILURE_UNCLASSIFIED",
        )
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
        return DiscoveryFinalization(
            "ALREADY_EXISTS", target, capability,
            lifecycle=(
                "OPERATIONAL"
                if memory.has_verified_operational_lifecycle(target, capability)
                else None
            ),
        )
    delta_keys = {semantic(item) for item in delta}
    pending_match = (
        _matching_pending_candidate(
            memory, target, capability, delta_keys
        )
        if delta_keys <= pending else None
    )
    if delta_keys <= pending and pending_match is None:
        return DiscoveryFinalization(
            "NOT_SAVED", target, capability,
            reason="This knowledge is already pending confirmation before it can be used.",
            reason_code="ALREADY_PENDING",
        )
    if pending_match is None:
        delta = [item for item in delta if semantic(item) not in pending]
    if not delta:
        return DiscoveryFinalization(
            "NOT_SAVED", target, capability,
            reason="This knowledge is already pending confirmation before it can be used.",
            reason_code="ALREADY_PENDING",
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
        item_semantic = semantic(item)
        claim_id = (
            pending_match[1][item_semantic] if pending_match
            else f"clm:{target}:{capability}:discovery-{_digest(item_semantic)}"
        )
        claim = {
            "id": claim_id, "family": item["family"], "epistemic": item["epistemic"],
            "value": item["value"],
        }
        if item.get("host"):
            claim["host_id"] = host_ids[str(item["host"])]
        claims.append(claim)
        validation = item.get("validation") or {}
        if validation:
            claim["discovery_validation"] = validation
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
    # A contradiction is a durable replacement, not ordinary new knowledge: it
    # may only reach the accepted view through the replacement path. Transport
    # Claims for different transports are parallel facts rather than conflicts,
    # so `_has_conflict` alone would let an unproven replacement fall through to
    # automatic promotion. A proven replacement still earns an operational
    # proof, because `replace_candidate` -- not `promote_candidate` -- performs
    # its Decision.
    automatic = (
        all(item["epistemic"] == "OBSERVED" for item in delta)
        and not has_conflict
        and (
            replacement_ready
            or not any(item.get("contradiction") for item in delta)
        )
    )
    proof_claim_ids, lifecycle_gap = (
        _operational_proof_dependencies(
            memory, target, capability, claims, clean_evidence,
            validated_transport,
        )
        if automatic else (None, "CANDIDATE_NOT_AUTOMATIC")
    )
    lifecycle_state: str | None = None
    if proof_claim_ids and memory.has_verified_operational_lifecycle(target, capability):
        lifecycle_gap = None
        lifecycle_state = "OPERATIONAL"
    elif proof_claim_ids:
        lifecycle_id = (
            f"clm:{target}:{capability}:lifecycle-operational-"
            f"{_digest(proof_claim_ids)}"
        )
        claims.append({
            "id": lifecycle_id,
            "family": "lifecycle",
            "epistemic": "OBSERVED",
            "value": "OPERATIONAL",
            "operational_proof": {
                "version": _OPERATIONAL_PROOF_VERSION,
                "claim_ids": list(proof_claim_ids),
            },
        })
        lifecycle_state = "OPERATIONAL"
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
    try:
        with memory.write_transaction() as writer:
            if pending_match:
                pending_claim_ids = set(pending_match[1].values())
                for claim in claims:
                    claim_id = claim["id"]
                    if claim_id not in pending_claim_ids:
                        continue
                    enrichment = enrich_candidate(
                        memory, target=target, capability=capability,
                        proposal_id=proposal_id, claim_id=claim_id,
                        supporting_evidence=supports.get(claim_id, ()),
                        validation_context=validations.get(claim_id),
                        contradicted_claim_id=(
                            replacement_ids[0]
                            if replacement_ids and claim_id in contradicting else None
                        ),
                        contradicting_evidence=contradiction_supports.get(claim_id, ()),
                        contradiction_context=contradiction_contexts.get(claim_id),
                        _writer=writer,
                    )
                    enrichment_created += enrichment.records_created
                for claim in claims:
                    if claim["id"] in pending_claim_ids:
                        continue
                    writer.claim({
                        **claim,
                        "target_id": f"tgt:{target}",
                        "capability_id": f"cap:{target}:{capability}",
                        "proposal_id": proposal_id,
                        "recorded_at": recorded_at,
                        "provenance": clean_provenance,
                    })
                    writer.proposal_claim(proposal_id, claim["id"])
            else:
                capture_candidate(
                    memory, target=target, capability=capability,
                    proposal_id=proposal_id, claims=claims,
                    provenance=clean_provenance, recorded_at=recorded_at,
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
                    _writer=writer,
                )
            elif automatic:
                promote_candidate(
                    memory,
                    target=target,
                    capability=capability,
                    proposal_id=proposal_id,
                    reviewed_token=review_token(memory, target=target, capability=capability),
                    decision_id=f"dec:{target}:{capability}:discovery-{_digest(delta)}",
                    recorded_at=recorded_at,
                    effective_at=recorded_at,
                    _writer=writer,
                )
            if dry_run:
                raise _DryRunRollback
    except _DryRunRollback:
        pass
    if (
        pending_match and not automatic and not replacement_ready
        and enrichment_created == 0
    ):
        return DiscoveryFinalization(
            "NOT_SAVED", target, capability, proposal_id, 0,
            reason="This knowledge is already pending confirmation before it can be used.",
            reason_code="ALREADY_PENDING",
        )
    if not automatic and not replacement_ready:
        if any(item["epistemic"] != "OBSERVED" for item in delta):
            reason_code = "INFERENCE_ONLY"
        elif replacement_refusal:
            reason_code = replacement_refusal
        elif any(item.get("contradiction") for item in delta):
            reason_code = "REPLACEMENT_UNPROVEN"
        elif has_conflict:
            reason_code = "CONFLICT_OR_AMBIGUITY"
        else:
            reason_code = "CONFIRMATION_PENDING"
        if reason_code == "CONFLICT_OR_AMBIGUITY":
            reason = (
                "Conflicting values for the same family and host block automatic acceptance. "
                "Conflicts: " + json.dumps(has_conflict[:10], ensure_ascii=False, sort_keys=True)
                + " A pending Claim is not accepted knowledge; a later run may enrich it, "
                "or it can be discarded (see knowledge-resolve)."
            )
        else:
            reason = "Conflicting or unconfirmed information blocked validation of a reusable path."
        return DiscoveryFinalization(
            "NOT_SAVED", target, capability, proposal_id, len(claims),
            reason=reason,
            reason_code=reason_code,
        )
    return DiscoveryFinalization(
        "SAVED", target, capability, proposal_id, len(claims),
        lifecycle=lifecycle_state,
        lifecycle_gap=None if lifecycle_state else lifecycle_gap,
    )


__all__ = ["DiscoveryFinalization", "DiscoveryFinalizationError", "finalize_discovery"]
