from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _as_list(case: dict[str, Any], plural: str, singular: str, reverse: bool) -> list[dict[str, Any]]:
    values = list(case.get(plural, []))
    if not values and singular in case:
        values = [case[singular]]
    return list(reversed(values)) if reverse else values


def _capability_id(record_id: str, capability_ids: list[str], default_capability: str | None, prefix: str) -> str:
    matches = [
        capability_id
        for capability_id in capability_ids
        if record_id.startswith(capability_id.replace("cap:", prefix) + ":")
    ]
    if len(matches) == 1:
        return matches[0]
    if default_capability is not None:
        return default_capability
    raise ValueError(f"cannot derive capability for {record_id}")


def load_memory_lab(memory: Any, fixture_path: str | Path, *, reverse: bool = False) -> dict[str, Any]:
    """Test-only adapter from frozen memory-lab-v1 JSON to production write primitives."""
    fixture = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    cases = list(fixture["cases"])
    if reverse:
        cases.reverse()

    with memory.write_transaction() as writer:
        for case in cases:
            target = dict(case["target"])
            target_id = target["id"]
            writer.target(target)

            hosts = _as_list(case, "hosts", "host", reverse)
            for host in hosts:
                writer.host({**host, "target_id": target_id})

            capabilities = _as_list(case, "capabilities", "capability", reverse)
            capability_ids = [capability["id"] for capability in capabilities]
            default_capability = capability_ids[0] if len(capability_ids) == 1 else None
            for capability in capabilities:
                writer.capability(
                    {
                        **capability,
                        "target_id": target_id,
                        "key": capability.get("name") or capability["id"].split(":", 2)[-1],
                    }
                )

            evidence = list(case.get("evidence", []))
            if reverse:
                evidence.reverse()
            for item in evidence:
                writer.evidence(item)

            validations = list(case.get("validations", []))
            if reverse:
                validations.reverse()
            for validation in validations:
                capability_id = validation.get("capability_id") or default_capability
                if capability_id is None:
                    raise ValueError(f"{validation['id']}: missing capability_id")
                writer.validation({**validation, "capability_id": capability_id})

            observations = list(case.get("observations", []))
            if reverse:
                observations.reverse()
            for observation in observations:
                writer.observation(observation)

            claims = list(case.get("claims", []))
            if reverse:
                claims.reverse()
            for claim in claims:
                capability_id = _capability_id(
                    claim["id"], capability_ids, default_capability, "clm:"
                )
                writer.claim(
                    {
                        **claim,
                        "target_id": target_id,
                        "capability_id": capability_id,
                    }
                )

            proposals = list(case.get("proposals", []))
            if reverse:
                proposals.reverse()
            for proposal in proposals:
                capability_id = _capability_id(
                    proposal["id"], capability_ids, default_capability, "prop:"
                )
                writer.proposal(
                    {
                        **proposal,
                        "target_id": target_id,
                        "capability_id": capability_id,
                    }
                )

            decisions = list(case.get("decisions", []))
            if reverse:
                decisions.reverse()
            for decision in decisions:
                decision_claim_ids = list(decision.get("claim_ids", []))
                decision_caps = {
                    _capability_id(claim_id, capability_ids, default_capability, "clm:")
                    for claim_id in decision_claim_ids
                }
                capability_id = next(iter(decision_caps)) if len(decision_caps) == 1 else default_capability
                if capability_id is None:
                    raise ValueError(f"{decision['id']}: ambiguous capability")
                writer.decision(
                    {
                        **decision,
                        "target_id": target_id,
                        "capability_id": capability_id,
                    }
                )

            for observation in observations:
                for claim_id in observation.get("contradicts_claim_ids", []):
                    writer.contradiction(observation["id"], claim_id)

    return fixture


def compare_minimum(expected: Any, actual: Any, path: str = "$") -> list[str]:
    diffs: list[str] = []
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}: expected object, got {type(actual).__name__}"]
        for key, value in expected.items():
            if key not in actual:
                diffs.append(f"{path}.{key}: missing")
            else:
                diffs.extend(compare_minimum(value, actual[key], f"{path}.{key}"))
    elif isinstance(expected, list):
        if expected != actual:
            diffs.append(f"{path}: expected {expected!r}, got {actual!r}")
    elif expected != actual:
        diffs.append(f"{path}: expected {expected!r}, got {actual!r}")
    return diffs
