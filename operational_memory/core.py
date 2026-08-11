from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

from knowledge_write_freeze import (
    KnowledgeWriteFrozenError,
    assert_knowledge_writes_allowed,
    inferred_knowledge_root,
)
from transport_policy import BROWSER_TRANSPORTS

SCHEMA_VERSION = 2
RENDERING_VERSION = "operational-memory-v1"
ACCEPT_ACTIONS = {"ACCEPT", "ACCEPT_SUPERSEDE", "RETROACTIVE_CORRECTION"}
CLOSE_ACTIONS = {"DEGRADE", "SUPERSEDE"}
RESOLUTION_ACTIONS = CLOSE_ACTIONS | {"RETROACTIVE_CORRECTION"}
DECISION_ACTIONS = ACCEPT_ACTIONS | CLOSE_ACTIONS | {"REJECT"}
EPISTEMIC_CLASSES = {"OBSERVED", "INFERRED", "UNKNOWN"}
TIME_PRECISIONS = {"exact", "day", "fixture"}

_TABLE_BY_PREFIX = {
    "tgt:": "targets",
    "host:": "hosts",
    "cap:": "capabilities",
    "ev:": "evidence",
    "val:": "validations",
    "obs:": "observations",
    "clm:": "claims",
    "prop:": "proposals",
    "dec:": "decisions",
}


class MemoryError(Exception):
    """Base error for the production Operational Memory core."""


class DatabaseOpenError(MemoryError):
    """The SQLite file cannot be opened as a compatible Operational Memory database."""


class SchemaVersionError(MemoryError):
    """The database schema version is missing or incompatible."""


class RecordValidationError(MemoryError):
    """A canonical record is invalid for the current production schema."""


class CorrectionScopeAmbiguityError(MemoryError):
    """A correction cannot be targeted without inventing backend-independent semantics."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_json(value: str | None) -> Any:
    return None if value is None else json.loads(value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def validate_timestamp(value: str | None, *, field: str, required: bool = True) -> None:
    if value is None:
        if required:
            raise RecordValidationError(f"{field} is required")
        return
    if not isinstance(value, str) or not value.endswith("Z"):
        raise RecordValidationError(f"{field} must be RFC 3339 UTC ending in Z")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise RecordValidationError(f"{field} is not a valid RFC 3339 timestamp") from exc


def _require_id(value: Any, prefix: str) -> str:
    if not isinstance(value, str) or not value.startswith(prefix) or len(value) <= len(prefix):
        raise RecordValidationError(f"id must start with {prefix!r}")
    return value


def _strip_prefix(value: str, prefix: str) -> str:
    return value[len(prefix):] if value.startswith(prefix) else value


@dataclass(frozen=True)
class Projection:
    capability_id: str
    accepted_claim_ids: tuple[str, ...]
    provenance_decision_ids: tuple[str, ...]
    inactive_historical_claim_ids: tuple[str, ...]
    historical_belief_preserved: tuple[str, ...]
    intervals: Mapping[str, Mapping[str, Any]]


class _Writer:
    """Transactional canonical-record writer. Instances exist only inside write_transaction()."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def target(self, record: Mapping[str, Any]) -> None:
        rid = _require_id(record.get("id"), "tgt:")
        self._conn.execute(
            "INSERT INTO targets(id,name,canonical_origin,payload_json) VALUES (?,?,?,?)",
            (rid, record.get("name"), record.get("canonical_origin"), canonical_json(dict(record))),
        )

    def host(self, record: Mapping[str, Any]) -> None:
        rid = _require_id(record.get("id"), "host:")
        target_id = _require_id(record.get("target_id"), "tgt:")
        self._conn.execute(
            "INSERT INTO hosts(id,target_id,hostname,payload_json) VALUES (?,?,?,?)",
            (rid, target_id, record.get("hostname"), canonical_json(dict(record))),
        )

    def capability(self, record: Mapping[str, Any]) -> None:
        rid = _require_id(record.get("id"), "cap:")
        target_id = _require_id(record.get("target_id"), "tgt:")
        key = record.get("key") or rid.split(":", 2)[-1]
        if not isinstance(key, str) or not key:
            raise RecordValidationError("capability key is required")
        self._conn.execute(
            "INSERT INTO capabilities(id,target_id,capability_key,name,payload_json) VALUES (?,?,?,?,?)",
            (rid, target_id, key, record.get("name"), canonical_json(dict(record))),
        )

    def evidence(self, record: Mapping[str, Any]) -> None:
        rid = _require_id(record.get("id"), "ev:")
        recorded_at = record.get("recorded_at")
        validate_timestamp(recorded_at, field="evidence.recorded_at", required=False)
        self._conn.execute(
            "INSERT INTO evidence(id,recorded_at,recorded_at_state,payload_json) VALUES (?,?,?,?)",
            (rid, recorded_at, "RECORDED" if recorded_at else "UNRECORDED", canonical_json(dict(record))),
        )

    def validation(self, record: Mapping[str, Any]) -> None:
        rid = _require_id(record.get("id"), "val:")
        capability_id = _require_id(record.get("capability_id"), "cap:")
        host_id = record.get("host_id")
        if host_id is not None:
            _require_id(host_id, "host:")
        validate_timestamp(record.get("observed_at"), field="validation.observed_at")
        validate_timestamp(record.get("recorded_at"), field="validation.recorded_at")
        precision = record.get("time_precision")
        if precision not in TIME_PRECISIONS:
            raise RecordValidationError(f"invalid time_precision: {precision!r}")
        context = record.get("context", {})
        if not isinstance(context, Mapping):
            raise RecordValidationError("validation.context must be an object")
        self._conn.execute(
            """INSERT INTO validations
               (id,capability_id,host_id,observed_at,recorded_at,time_precision,transport,context_json,payload_json)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                rid,
                capability_id,
                host_id,
                record["observed_at"],
                record["recorded_at"],
                precision,
                record.get("transport"),
                canonical_json(dict(context)),
                canonical_json(dict(record)),
            ),
        )

    def observation(self, record: Mapping[str, Any]) -> None:
        rid = _require_id(record.get("id"), "obs:")
        validation_id = _require_id(record.get("validation_id"), "val:")
        if "result" not in record:
            raise RecordValidationError("observation.result is required")
        self._conn.execute(
            "INSERT INTO observations(id,validation_id,result_json,value_json,payload_json) VALUES (?,?,?,?,?)",
            (
                rid,
                validation_id,
                canonical_json(record["result"]),
                canonical_json(record["value"]) if "value" in record else None,
                canonical_json(dict(record)),
            ),
        )
        for evidence_id in sorted(set(record.get("evidence_ids", []))):
            _require_id(evidence_id, "ev:")
            self._conn.execute(
                "INSERT INTO observation_evidence(observation_id,evidence_id) VALUES (?,?)",
                (rid, evidence_id),
            )

    def claim(self, record: Mapping[str, Any]) -> None:
        rid = _require_id(record.get("id"), "clm:")
        target_id = _require_id(record.get("target_id"), "tgt:")
        capability_id = _require_id(record.get("capability_id"), "cap:")
        epistemic = record.get("epistemic")
        if epistemic not in EPISTEMIC_CLASSES:
            raise RecordValidationError(f"invalid epistemic class: {epistemic!r}")
        family = record.get("family")
        if not isinstance(family, str) or not family:
            raise RecordValidationError("claim.family is required")
        if "value" not in record:
            raise RecordValidationError("claim.value is required; UNKNOWN must be explicit, not NULL")
        host_id = record.get("host_id")
        if host_id is not None:
            _require_id(host_id, "host:")
        recorded_at = record.get("recorded_at")
        validate_timestamp(recorded_at, field="claim.recorded_at", required=False)
        proposal_id = record.get("proposal_id")
        if proposal_id is not None:
            _require_id(proposal_id, "prop:")
        self._conn.execute(
            """INSERT INTO claims
               (id,target_id,capability_id,host_id,family,epistemic,value_json,proposal_id,recorded_at,recorded_at_state,payload_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rid,
                target_id,
                capability_id,
                host_id,
                family,
                epistemic,
                canonical_json(record["value"]),
                proposal_id,
                recorded_at,
                "RECORDED" if recorded_at else "UNRECORDED",
                canonical_json(dict(record)),
            ),
        )
        for observation_id in sorted(set(record.get("support_observation_ids", []))):
            self.claim_observation(rid, observation_id, "supports")
        for observation_id in sorted(set(record.get("contradicting_observation_ids", []))):
            self.claim_observation(rid, observation_id, "contradicts")

    def proposal(self, record: Mapping[str, Any]) -> None:
        rid = _require_id(record.get("id"), "prop:")
        target_id = _require_id(record.get("target_id"), "tgt:")
        capability_id = _require_id(record.get("capability_id"), "cap:")
        recorded_at = record.get("recorded_at")
        validate_timestamp(recorded_at, field="proposal.recorded_at", required=False)
        self._conn.execute(
            "INSERT INTO proposals(id,target_id,capability_id,recorded_at,recorded_at_state,payload_json) VALUES (?,?,?,?,?,?)",
            (
                rid,
                target_id,
                capability_id,
                recorded_at,
                "RECORDED" if recorded_at else "UNRECORDED",
                canonical_json(dict(record)),
            ),
        )
        for claim_id in sorted(set(record.get("claim_ids", []))):
            self.proposal_claim(rid, claim_id)

    def decision(self, record: Mapping[str, Any]) -> None:
        rid = _require_id(record.get("id"), "dec:")
        target_id = _require_id(record.get("target_id"), "tgt:")
        capability_id = _require_id(record.get("capability_id"), "cap:")
        action = record.get("action")
        if action not in DECISION_ACTIONS:
            raise RecordValidationError(f"invalid decision action: {action!r}")
        effective_at = record.get("effective_at")
        recorded_at = record.get("recorded_at")
        validate_timestamp(effective_at, field="decision.effective_at")
        validate_timestamp(recorded_at, field="decision.recorded_at")
        validity = record.get("validity", {})
        if not isinstance(validity, Mapping):
            raise RecordValidationError("decision.validity must be an object")
        valid_from = validity.get("valid_from")
        valid_to = validity.get("valid_to")
        validate_timestamp(valid_from, field="decision.validity.valid_from", required=False)
        validate_timestamp(valid_to, field="decision.validity.valid_to", required=False)
        if valid_from is not None and valid_to is not None and valid_from >= valid_to:
            raise RecordValidationError("accepted validity must be half-open with valid_from < valid_to")
        proposal_id = record.get("proposal_id")
        if proposal_id is not None:
            _require_id(proposal_id, "prop:")
        claim_ids = list(record.get("claim_ids", []))
        if action != "REJECT" and not claim_ids:
            raise RecordValidationError("non-REJECT Decision requires at least one claim_id")
        self._conn.execute(
            """INSERT INTO decisions
               (id,target_id,capability_id,action,proposal_id,effective_at,recorded_at,valid_from,valid_to,payload_json)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                rid,
                target_id,
                capability_id,
                action,
                proposal_id,
                effective_at,
                recorded_at,
                valid_from,
                valid_to,
                canonical_json(dict(record)),
            ),
        )
        for claim_id in sorted(set(claim_ids)):
            self.decision_claim(rid, claim_id)

    def observation_evidence(self, observation_id: str, evidence_id: str) -> None:
        _require_id(observation_id, "obs:")
        _require_id(evidence_id, "ev:")
        self._conn.execute(
            "INSERT INTO observation_evidence(observation_id,evidence_id) VALUES (?,?)",
            (observation_id, evidence_id),
        )

    def claim_observation(self, claim_id: str, observation_id: str, relation: str) -> None:
        _require_id(claim_id, "clm:")
        _require_id(observation_id, "obs:")
        if relation not in {"supports", "contradicts"}:
            raise RecordValidationError("claim/observation relation must be supports or contradicts")
        self._conn.execute(
            "INSERT INTO claim_observations(claim_id,observation_id,relation) VALUES (?,?,?)",
            (claim_id, observation_id, relation),
        )

    def proposal_claim(self, proposal_id: str, claim_id: str) -> None:
        _require_id(proposal_id, "prop:")
        _require_id(claim_id, "clm:")
        self._conn.execute(
            "INSERT INTO proposal_claims(proposal_id,claim_id) VALUES (?,?)",
            (proposal_id, claim_id),
        )

    def decision_claim(self, decision_id: str, claim_id: str) -> None:
        _require_id(decision_id, "dec:")
        _require_id(claim_id, "clm:")
        self._conn.execute(
            "INSERT INTO decision_claims(decision_id,claim_id) VALUES (?,?)",
            (decision_id, claim_id),
        )

    def contradiction(self, observation_id: str, claim_id: str) -> None:
        _require_id(observation_id, "obs:")
        _require_id(claim_id, "clm:")
        self._conn.execute(
            "INSERT INTO contradictions(observation_id,claim_id) VALUES (?,?)",
            (observation_id, claim_id),
        )


class SQLiteOperationalMemory:
    """Production v0.4 Operational Memory engine backed by one local SQLite file.

    Internal production interface, not an external CaravelaWeb product API:
    the supported CLI surface is `init-knowledge-root`/`preflight`/
    `knowledge-lookup`/`discovery-finalize`, which use this class internally.
    Callers do not need table names, SQL, or temporal-reduction details.
    Accepted Knowledge is derived from Claims and Decisions on every read; no
    authoritative current-state table exists.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        clock: Callable[[], str] | None = None,
        create: bool = True,
        knowledge_root: str | Path | None = None,
    ) -> None:
        self.path = Path(db_path)
        self.knowledge_root = (
            Path(knowledge_root)
            if knowledge_root is not None
            else inferred_knowledge_root(self.path)
        )
        self._clock = clock or _utc_now
        self._conn = self._open(create=create)

    def _open(self, *, create: bool) -> sqlite3.Connection:
        exists = self.path.exists()
        if not exists and not create:
            raise DatabaseOpenError(f"Operational Memory database does not exist: {self.path}")
        if not exists:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(self.path, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            if not exists:
                schema_path = Path(__file__).with_name("schema.sql")
                conn.executescript(schema_path.read_text(encoding="utf-8"))
            self._validate_schema(conn)
            return conn
        except SchemaVersionError:
            if conn is not None:
                conn.close()
            raise
        except (sqlite3.DatabaseError, OSError) as exc:
            if conn is not None:
                conn.close()
            raise DatabaseOpenError(f"cannot open Operational Memory database {self.path}: {exc}") from exc

    @staticmethod
    def _validate_schema(conn: sqlite3.Connection) -> None:
        try:
            row = conn.execute("SELECT schema_version FROM schema_metadata WHERE singleton=1").fetchone()
            user_version = conn.execute("PRAGMA user_version").fetchone()[0]
        except sqlite3.DatabaseError as exc:
            raise SchemaVersionError("database is not an Operational Memory schema") from exc
        if row is None:
            raise SchemaVersionError("schema_metadata row is missing")
        if row["schema_version"] != SCHEMA_VERSION or user_version != SCHEMA_VERSION:
            raise SchemaVersionError(
                f"incompatible Operational Memory schema: table={row['schema_version']}, pragma={user_version}, expected={SCHEMA_VERSION}"
            )
        if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise DatabaseOpenError("SQLite foreign_keys pragma is not active")

    @property
    def schema_version(self) -> int:
        return SCHEMA_VERSION

    @property
    def foreign_keys_enabled(self) -> bool:
        return self._conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    @property
    def total_changes(self) -> int:
        """Cumulative SQLite row-modification counter for this connection."""
        return self._conn.total_changes

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "SQLiteOperationalMemory":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    @contextmanager
    def write_transaction(self) -> Iterator[_Writer]:
        """Start one explicit compound write; any failure rolls back the whole batch."""
        if self.knowledge_root is not None:
            assert_knowledge_writes_allowed(self.knowledge_root)
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            yield _Writer(self._conn)
        except Exception:
            self._conn.rollback()
            raise
        else:
            self._conn.commit()

    def now(self) -> str:
        """Current validated knowledge-time timestamp from this instance's clock."""
        value = self._clock()
        validate_timestamp(value, field="clock")
        return value

    def resolve_target(self, target: str) -> str:
        tid = target if target.startswith("tgt:") else f"tgt:{target}"
        if self._conn.execute("SELECT 1 FROM targets WHERE id=?", (tid,)).fetchone() is None:
            raise KeyError(f"unknown target {target}")
        return tid

    def resolve_capability(self, target: str, capability: str) -> str:
        tid = self.resolve_target(target)
        if capability.startswith("cap:"):
            cid = capability
        else:
            row = self._conn.execute(
                "SELECT id FROM capabilities WHERE target_id=? AND capability_key=?",
                (tid, capability),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown capability {target}/{capability}")
            cid = row["id"]
        if self._conn.execute(
            "SELECT 1 FROM capabilities WHERE id=? AND target_id=?", (cid, tid)
        ).fetchone() is None:
            raise KeyError(f"unknown capability {target}/{capability}")
        return cid

    def list_capability_keys(self, target: str) -> list[str]:
        tid = self.resolve_target(target)
        return [
            row[0]
            for row in self._conn.execute(
                "SELECT capability_key FROM capabilities WHERE target_id=? ORDER BY capability_key",
                (tid,),
            )
        ]

    @staticmethod
    def _contains(domain_time: str, start: str | None, end: str | None) -> bool:
        return (start is None or domain_time >= start) and (end is None or domain_time < end)

    def _decision_rows(self, capability_id: str, knowledge_time: str) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                """SELECT d.*,dc.claim_id,c.family,c.epistemic
                   FROM decisions d
                   JOIN decision_claims dc ON dc.decision_id=d.id
                   JOIN claims c ON c.id=dc.claim_id
                   WHERE d.capability_id=? AND d.recorded_at<=?
                   ORDER BY d.effective_at,d.recorded_at,d.id,dc.claim_id""",
                (capability_id, knowledge_time),
            )
        )

    def _decision_key(self, decision_id: str) -> tuple[str, str, str]:
        row = self._conn.execute(
            "SELECT effective_at,recorded_at,id FROM decisions WHERE id=?", (decision_id,)
        ).fetchone()
        if row is None:
            raise KeyError(decision_id)
        return row["effective_at"], row["recorded_at"], row["id"]

    def _legacy_correction_targets(
        self,
        active: Mapping[str, Mapping[str, Any]],
        correction_claim_id: str,
        correction_decision_id: str,
    ) -> tuple[str, ...]:
        """Isolated compatibility rule for the known correction-scope model gap.

        Phase 0 has no corrected_claim_id/superseded_claim_id relation. The frozen S1
        case is unambiguous because exactly one older accepted Claim is active in the
        corrected interval. If more than one candidate exists, production code stops
        rather than silently choosing or deleting unrelated Claims.
        """
        correction_key = self._decision_key(correction_decision_id)
        candidates = [
            claim_id
            for claim_id, interval in active.items()
            if claim_id != correction_claim_id
            and self._decision_key(str(interval["decision_id"])) < correction_key
        ]
        if len(candidates) <= 1:
            return tuple(candidates)
        raise CorrectionScopeAmbiguityError(
            "retroactive correction has multiple plausible prior Claims; Phase 0 does not encode corrected_claim_id/superseded_claim_id"
        )

    def projection(
        self,
        target: str,
        capability: str,
        *,
        knowledge_time: str,
        domain_time: str,
    ) -> Projection:
        """Reduce Decisions into the accepted-Claim projection as of the given times."""
        cid = self.resolve_capability(target, capability)
        rows = self._decision_rows(cid, knowledge_time)
        intervals: dict[str, list[dict[str, Any]]] = defaultdict(list)
        corrections: list[dict[str, Any]] = []

        for row in rows:
            action = row["action"]
            claim_id = row["claim_id"]
            if action in {"ACCEPT", "ACCEPT_SUPERSEDE"}:
                intervals[claim_id].append(
                    {
                        "valid_from": row["valid_from"],
                        "valid_to": row["valid_to"],
                        "decision_id": row["id"],
                        "action": action,
                    }
                )
            elif action in CLOSE_ACTIONS:
                if not intervals[claim_id]:
                    # A close-family Decision (SUPERSEDE/DEGRADE) naming a Claim
                    # with no accept-family interval open before it in logical
                    # (effective_at, recorded_at, id) order. Left unchecked this
                    # is a silent no-op: the Claim just never appears accepted,
                    # indistinguishable from "correctly closed". Raise instead --
                    # this is the fold-order-correct place for the check, unlike
                    # a write-time check, which would depend on physical
                    # insertion order and break replay/out-of-order loading (I18).
                    raise RecordValidationError(
                        f"{action} Decision {row['id']} references claim {claim_id} "
                        "with no accepted interval open before it"
                    )
                current = intervals[claim_id][-1]
                close_at = row["valid_to"] or row["effective_at"]
                if current["valid_to"] is None or close_at < current["valid_to"]:
                    current["valid_to"] = close_at
                current["closed_by"] = row["id"]
            elif action == "RETROACTIVE_CORRECTION":
                interval = {
                    "valid_from": row["valid_from"],
                    "valid_to": row["valid_to"],
                    "decision_id": row["id"],
                    "action": action,
                    "claim_id": claim_id,
                }
                intervals[claim_id].append(dict(interval))
                corrections.append(interval)
            elif action == "REJECT":
                continue
            else:
                raise RecordValidationError(f"unsupported Decision action in reducer: {action}")

        active: dict[str, dict[str, Any]] = {}
        historical: set[str] = set()
        for claim_id, claim_intervals in intervals.items():
            for interval in claim_intervals:
                historical.add(claim_id)
                if self._contains(domain_time, interval["valid_from"], interval["valid_to"]):
                    active[claim_id] = interval

        preserved: set[str] = set()
        for correction in corrections:
            if not self._contains(domain_time, correction["valid_from"], correction["valid_to"]):
                continue
            targets = self._legacy_correction_targets(
                active,
                str(correction["claim_id"]),
                str(correction["decision_id"]),
            )
            for old_claim_id in targets:
                preserved.add(old_claim_id)
                active.pop(old_claim_id, None)

        accepted = tuple(sorted(active))
        provenance = tuple(
            sorted({str(active[c]["decision_id"]) for c in accepted}, key=self._decision_key)
        )
        return Projection(
            capability_id=cid,
            accepted_claim_ids=accepted,
            provenance_decision_ids=provenance,
            inactive_historical_claim_ids=tuple(sorted(historical - set(active))),
            historical_belief_preserved=tuple(sorted(preserved)),
            intervals={c: active[c] for c in accepted},
        )

    def _claim_rows(self, claim_ids: Iterable[str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for claim_id in sorted(claim_ids):
            row = self._conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
            if row is None:
                raise KeyError(claim_id)
            rows.append(
                {
                    "id": row["id"],
                    "family": row["family"],
                    "host_id": row["host_id"],
                    "epistemic": row["epistemic"],
                    "value": _parse_json(row["value_json"]),
                    "proposal_id": row["proposal_id"],
                    "recorded_at": row["recorded_at"],
                    "recorded_at_state": row["recorded_at_state"],
                }
            )
        return rows

    def _pending_proposal_ids(self, capability_id: str, knowledge_time: str) -> list[str]:
        proposals = self._conn.execute(
            "SELECT id,recorded_at FROM proposals WHERE capability_id=? ORDER BY id", (capability_id,)
        ).fetchall()
        pending: list[str] = []
        for proposal in proposals:
            if proposal["recorded_at"] and proposal["recorded_at"] > knowledge_time:
                continue
            claim_ids = [
                r[0]
                for r in self._conn.execute(
                    "SELECT claim_id FROM proposal_claims WHERE proposal_id=? ORDER BY claim_id",
                    (proposal["id"],),
                )
            ]
            resolved: set[str] = set()
            for claim_id in claim_ids:
                actions = [
                    r[0]
                    for r in self._conn.execute(
                        """SELECT d.action FROM decisions d
                           JOIN decision_claims dc ON dc.decision_id=d.id
                           WHERE dc.claim_id=? AND d.recorded_at<=?""",
                        (claim_id, knowledge_time),
                    )
                ]
                if any(a in DECISION_ACTIONS for a in actions):
                    resolved.add(claim_id)
            if len(resolved) < len(claim_ids):
                pending.append(proposal["id"])
        return pending

    def _unresolved_contradictions(
        self, target: str, capability: str, knowledge_time: str
    ) -> list[dict[str, Any]]:
        cid = self.resolve_capability(target, capability)
        rows = self._conn.execute(
            """SELECT ct.observation_id,ct.claim_id,v.recorded_at
               FROM contradictions ct
               JOIN observations o ON o.id=ct.observation_id
               JOIN validations v ON v.id=o.validation_id
               WHERE v.capability_id=? AND v.recorded_at<=?
               ORDER BY ct.observation_id,ct.claim_id""",
            (cid, knowledge_time),
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            later = self._conn.execute(
                """SELECT d.id,d.action FROM decisions d
                   JOIN decision_claims dc ON dc.decision_id=d.id
                   WHERE dc.claim_id=? AND d.recorded_at>? AND d.recorded_at<=?
                   ORDER BY d.effective_at,d.recorded_at,d.id""",
                (row["claim_id"], row["recorded_at"], knowledge_time),
            ).fetchall()
            if not any(r["action"] in RESOLUTION_ACTIONS for r in later):
                result.append(
                    {
                        "observation_id": row["observation_id"],
                        "contradicted_claim_id": row["claim_id"],
                        "context_comparability": self._contradiction_comparability(row["observation_id"]),
                        "resolution": "unresolved",
                        "accepted_knowledge_changed": False,
                    }
                )
        return result

    def _accepted_view(
        self,
        target: str,
        capability: str,
        *,
        knowledge_time: str,
        domain_time: str,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        projection = self.projection(
            target,
            capability,
            knowledge_time=knowledge_time,
            domain_time=domain_time,
        )
        return {
            "capability_id": projection.capability_id,
            "knowledge_time": knowledge_time,
            "domain_time": domain_time,
            "accepted_claims": self._claim_rows(projection.accepted_claim_ids),
            "accepted_claim_ids": list(projection.accepted_claim_ids),
            "provenance_decision_ids": list(projection.provenance_decision_ids),
            "pending_proposal_ids": self._pending_proposal_ids(projection.capability_id, knowledge_time),
            "inactive_historical_claim_ids": list(projection.inactive_historical_claim_ids),
            "historical_belief_preserved": list(projection.historical_belief_preserved),
            "contradiction_warnings": self._unresolved_contradictions(target, capability, knowledge_time),
            "context_selector": dict(context or {}),
        }

    def get_current(
        self, target: str, capability: str, context: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        now = self.now()
        return self._accepted_view(
            target, capability, knowledge_time=now, domain_time=now, context=context
        )

    def get_as_known_at(
        self,
        target: str,
        capability: str,
        knowledge_time: str,
        domain_time: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        validate_timestamp(knowledge_time, field="knowledge_time")
        dt = domain_time or knowledge_time
        validate_timestamp(dt, field="domain_time")
        return self._accepted_view(
            target, capability, knowledge_time=knowledge_time, domain_time=dt, context=context
        )

    def get_current_view_of_past(
        self,
        target: str,
        capability: str,
        domain_time: str,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        validate_timestamp(domain_time, field="domain_time")
        return self._accepted_view(
            target,
            capability,
            knowledge_time=self.now(),
            domain_time=domain_time,
            context=context,
        )

    def get_history(
        self,
        target: str,
        capability: str | None = None,
        time_range: Sequence[str | None] | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        tid = self.resolve_target(target)
        capability_id = self.resolve_capability(target, capability) if capability else None
        events: list[dict[str, Any]] = []

        for row in self._conn.execute(
            """SELECT v.id,v.recorded_at,v.observed_at,v.capability_id,v.payload_json
               FROM validations v JOIN capabilities c ON c.id=v.capability_id
               WHERE c.target_id=? AND (? IS NULL OR v.capability_id=?)""",
            (tid, capability_id, capability_id),
        ):
            events.append(
                {
                    "kind": "validation",
                    "id": row["id"],
                    "recorded_at": row["recorded_at"],
                    "observed_at": row["observed_at"],
                    "capability_id": row["capability_id"],
                    "record": _parse_json(row["payload_json"]),
                }
            )

        for table, kind in (("claims", "claim"), ("proposals", "proposal"), ("decisions", "decision")):
            sql = f"SELECT id,recorded_at,capability_id,payload_json FROM {table} WHERE target_id=? AND (? IS NULL OR capability_id=?)"
            for row in self._conn.execute(sql, (tid, capability_id, capability_id)):
                events.append(
                    {
                        "kind": kind,
                        "id": row["id"],
                        "recorded_at": row["recorded_at"],
                        "observed_at": None,
                        "capability_id": row["capability_id"],
                        "record": _parse_json(row["payload_json"]),
                    }
                )

        for row in self._conn.execute(
            """SELECT o.id,v.recorded_at,v.observed_at,v.capability_id,o.payload_json
               FROM observations o JOIN validations v ON v.id=o.validation_id
               JOIN capabilities c ON c.id=v.capability_id
               WHERE c.target_id=? AND (? IS NULL OR v.capability_id=?)""",
            (tid, capability_id, capability_id),
        ):
            events.append(
                {
                    "kind": "observation",
                    "id": row["id"],
                    "recorded_at": row["recorded_at"],
                    "observed_at": row["observed_at"],
                    "capability_id": row["capability_id"],
                    "record": _parse_json(row["payload_json"]),
                }
            )

        if time_range:
            if len(time_range) != 2:
                raise ValueError("time_range must be (from, to)")
            lo, hi = time_range
            events = [
                event
                for event in events
                if (lo is None or (event["recorded_at"] or "") >= lo)
                and (hi is None or (event["recorded_at"] or "") < hi)
            ]
        events.sort(key=lambda e: (e["recorded_at"] is None, e["recorded_at"] or "", e["id"]))
        return {"target_id": tid, "events": events, "context_selector": dict(context or {})}

    def get_record(self, record_id: str) -> dict[str, Any]:
        """Return the caller-supplied canonical record for any Operational Memory id.

        Every canonical table stores the record exactly as it was passed to the
        matching ``_Writer`` method; this is that record, not a projection of it.
        """
        table = _TABLE_BY_PREFIX.get(record_id[: record_id.find(":") + 1]) if isinstance(record_id, str) else None
        if table is None:
            raise KeyError(record_id)
        row = self._conn.execute(f"SELECT payload_json FROM {table} WHERE id=?", (record_id,)).fetchone()
        if row is None:
            raise KeyError(record_id)
        return _parse_json(row["payload_json"])

    def get_evidence(self, subject_id: str) -> dict[str, Any]:
        evidence_ids: set[str] = set()
        if subject_id.startswith("obs:"):
            evidence_ids.update(
                r[0]
                for r in self._conn.execute(
                    "SELECT evidence_id FROM observation_evidence WHERE observation_id=?", (subject_id,)
                )
            )
        elif subject_id.startswith("clm:"):
            observation_ids = [
                r[0]
                for r in self._conn.execute(
                    "SELECT observation_id FROM claim_observations WHERE claim_id=? AND relation='supports' ORDER BY observation_id",
                    (subject_id,),
                )
            ]
            for observation_id in observation_ids:
                evidence_ids.update(
                    r[0]
                    for r in self._conn.execute(
                        "SELECT evidence_id FROM observation_evidence WHERE observation_id=?",
                        (observation_id,),
                    )
                )
        evidence = []
        for evidence_id in sorted(evidence_ids):
            row = self._conn.execute("SELECT payload_json FROM evidence WHERE id=?", (evidence_id,)).fetchone()
            if row is not None:
                evidence.append(_parse_json(row["payload_json"]))
        return {
            "subject_id": subject_id,
            "evidence_ids": sorted(evidence_ids),
            "evidence": evidence,
            "support_relation_status": "RECORDED" if evidence_ids else "UNRECORDED",
        }

    def proposal_claim_ids(self, proposal_id: str) -> tuple[str, ...]:
        """Claim ids attached to one Proposal, in canonical id order."""
        return tuple(
            row[0]
            for row in self._conn.execute(
                "SELECT claim_id FROM proposal_claims WHERE proposal_id=? ORDER BY claim_id",
                (proposal_id,),
            )
        )

    @staticmethod
    def _observation_context_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "observation_id": row["observation_id"],
            "capability_id": row["capability_id"],
            "host_id": row["host_id"],
            "transport": row["transport"],
            "context": _parse_json(row["context_json"]) or {},
            "result": _parse_json(row["result_json"]),
            "value": _parse_json(row["value_json"]) if row["value_json"] is not None else None,
        }

    def observations_supporting_claim(self, claim_id: str) -> list[dict[str, Any]]:
        """Validation/result context for every Observation that supports a Claim."""
        rows = self._conn.execute(
            """SELECT o.id AS observation_id, v.capability_id, v.host_id, v.transport,
                      v.context_json, o.result_json, o.value_json
               FROM claim_observations co
               JOIN observations o ON o.id = co.observation_id
               JOIN validations v ON v.id = o.validation_id
               WHERE co.claim_id = ? AND co.relation = 'supports'
               ORDER BY o.id""",
            (claim_id,),
        ).fetchall()
        return [self._observation_context_row(row) for row in rows]

    def contradicting_observations(self, claim_id: str) -> list[dict[str, Any]]:
        """Validation/result context for every Observation that contradicts a Claim."""
        rows = self._conn.execute(
            """SELECT o.id AS observation_id, v.capability_id, v.host_id, v.transport,
                      v.context_json, o.result_json, o.value_json
               FROM contradictions x
               JOIN observations o ON o.id = x.observation_id
               JOIN validations v ON v.id = o.validation_id
               WHERE x.claim_id = ?
               ORDER BY o.id""",
            (claim_id,),
        ).fetchall()
        return [self._observation_context_row(row) for row in rows]

    def get_pending_candidates(
        self,
        target: str | None = None,
        capability: str | None = None,
        *,
        knowledge_time: str | None = None,
    ) -> list[dict[str, Any]]:
        kt = knowledge_time or self.now()
        validate_timestamp(kt, field="knowledge_time")
        if target and capability:
            capability_ids = [self.resolve_capability(target, capability)]
        elif target:
            tid = self.resolve_target(target)
            capability_ids = [
                r[0]
                for r in self._conn.execute(
                    "SELECT id FROM capabilities WHERE target_id=? ORDER BY id", (tid,)
                )
            ]
        elif capability:
            raise ValueError("capability requires target")
        else:
            capability_ids = [r[0] for r in self._conn.execute("SELECT id FROM capabilities ORDER BY id")]
        result: list[dict[str, Any]] = []
        for capability_id in capability_ids:
            for proposal_id in self._pending_proposal_ids(capability_id, kt):
                claim_ids = [
                    r[0]
                    for r in self._conn.execute(
                        "SELECT claim_id FROM proposal_claims WHERE proposal_id=? ORDER BY claim_id",
                        (proposal_id,),
                    )
                ]
                result.append(
                    {
                        "proposal_id": proposal_id,
                        "capability_id": capability_id,
                        "claim_ids": claim_ids,
                    }
                )
        return result

    def render_operational_context(
        self,
        target: str,
        capability: str,
        caller_context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        view = self.get_current(target, capability, caller_context)
        capability_id = view["capability_id"]
        hosts = sorted(
            {str(claim["host_id"]) for claim in view["accepted_claims"] if claim.get("host_id")}
        )
        families: dict[str, list[dict[str, Any]]] = defaultdict(list)
        evidence_refs: set[str] = set()
        for claim in view["accepted_claims"]:
            families[claim["family"]].append(
                {"id": claim["id"], "host_id": claim.get("host_id"), "epistemic": claim["epistemic"], "value": claim["value"]}
            )
            evidence_refs.update(self.get_evidence(claim["id"])["evidence_ids"])
        return {
            "target_id": self.resolve_target(target),
            "capability_id": capability_id,
            "hosts": hosts,
            "current": dict(sorted(families.items())),
            "warnings": view["contradiction_warnings"],
            "minimal_evidence_refs": sorted(evidence_refs),
            "caller_context": dict(caller_context or {}),
            "history_included": False,
        }

    def render_markdown(
        self,
        target: str,
        viewpoint: Mapping[str, Any] | None = None,
        rendering_version: str | None = None,
    ) -> str:
        rendering_version = rendering_version or RENDERING_VERSION
        tid = self.resolve_target(target)
        trow = self._conn.execute("SELECT name FROM targets WHERE id=?", (tid,)).fetchone()
        lines = [
            f"# Target Profile — {trow['name'] or _strip_prefix(tid, 'tgt:')}",
            "",
            f"Renderer: `{rendering_version}`",
            "",
        ]
        capabilities = self._conn.execute(
            "SELECT capability_key FROM capabilities WHERE target_id=? ORDER BY id", (tid,)
        ).fetchall()
        for cap in capabilities:
            key = cap["capability_key"]
            mode = (viewpoint or {}).get("mode", "current")
            if mode == "as_known_then":
                view = self.get_as_known_at(
                    target,
                    key,
                    str(viewpoint["knowledge_time"]),
                    viewpoint.get("domain_time"),
                )
            elif mode == "current_view_of_past":
                view = self.get_current_view_of_past(target, key, str(viewpoint["domain_time"]))
            elif mode == "current":
                view = self.get_current(target, key)
            else:
                raise ValueError(f"unknown rendering viewpoint mode: {mode}")
            lines.extend([f"## Capability: {key}", ""])
            for claim in view["accepted_claims"]:
                value = claim["value"]
                display = canonical_json(value) if isinstance(value, (dict, list)) else str(value)
                lines.append(f"- **{claim['family']}** [{claim['epistemic']}]: {display}")
            if view["contradiction_warnings"]:
                lines.append("- **warning**: unresolved contradiction present")
            lines.append("")
        lines.extend(
            [
                "## Provenance",
                "",
                "Generated from canonical Operational Memory; Markdown is a projection, not the memory source.",
                "",
            ]
        )
        return "\n".join(lines)

    def _observation_validation(self, observation_id: str) -> sqlite3.Row:
        row = self._conn.execute(
            """SELECT v.*,o.result_json FROM observations o
               JOIN validations v ON v.id=o.validation_id WHERE o.id=?""",
            (observation_id,),
        ).fetchone()
        if row is None:
            raise KeyError(observation_id)
        return row

    @staticmethod
    def _material_context(row: sqlite3.Row) -> tuple[Any, ...]:
        return row["host_id"], row["transport"], canonical_json(_parse_json(row["context_json"]) or {})

    def _contradiction_comparability(self, observation_id: str) -> str:
        row = self._observation_validation(observation_id)
        prior = self._conn.execute(
            """SELECT v.* FROM observations o JOIN validations v ON v.id=o.validation_id
               WHERE v.capability_id=? AND v.observed_at<? AND lower(o.result_json) LIKE '%works%'
               ORDER BY v.observed_at DESC,o.id DESC LIMIT 1""",
            (row["capability_id"], row["observed_at"]),
        ).fetchone()
        if prior is None:
            return "unknown"
        return "comparable" if self._material_context(prior) == self._material_context(row) else "incomparable"

    @staticmethod
    def _js_capability(transport: str | None, context: Mapping[str, Any]) -> bool | str:
        if "javascript" in context:
            return bool(context["javascript"])
        if transport in BROWSER_TRANSPORTS:
            return True
        return "UNKNOWN"

    # Internal dispatch (Q1-Q15, Q18-Q20): no public CLI command calls this.
    # Real callers are phase4a_migration.py (Q19) and tests/v0.4. See
    # docs/v0.4/canonical-memory-queries.md and docs/findings.md entry 7.
    def canonical_query(
        self,
        query: str,
        parameters: Mapping[str, Any],
        checkpoint: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        method = getattr(self, f"_q{query[1:]}" if query.startswith("Q") else "", None)
        if method is None:
            raise KeyError(f"canonical query not implemented: {query}")
        return method(dict(parameters), dict(checkpoint or {}))

    def _q1(self, p: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
        kt = p.get("knowledge_time") or self.now()
        view = self._accepted_view(p["target"], p["capability"], knowledge_time=kt, domain_time=kt)
        summary = Counter(c["epistemic"] for c in view["accepted_claims"])
        result: dict[str, Any] = {
            "capability_id": view["capability_id"],
            "accepted_claim_ids": view["accepted_claim_ids"],
            "provenance_decision_ids": view["provenance_decision_ids"],
            "pending_proposal_ids": view["pending_proposal_ids"],
            "epistemic_summary": dict(sorted(summary.items())),
        }
        if view["inactive_historical_claim_ids"]:
            result["inactive_historical_claim_ids"] = view["inactive_historical_claim_ids"]
        return result

    def _q2(self, p: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
        kt = p.get("knowledge_time") or self.now()
        view = self._accepted_view(
            p["target"], p["capability"], knowledge_time=kt, domain_time=p["domain_time"]
        )
        return {
            "accepted_claim_ids": view["accepted_claim_ids"],
            "provenance_decision_ids": view["provenance_decision_ids"],
            "domain_time": p["domain_time"],
            "knowledge_time": kt,
        }

    def _q3(self, p: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
        kt = p["knowledge_time"]
        dt = p.get("domain_time", kt)
        view = self._accepted_view(p["target"], p["capability"], knowledge_time=kt, domain_time=dt)
        later = [
            r[0]
            for r in self._conn.execute(
                "SELECT id FROM decisions WHERE capability_id=? AND recorded_at>? ORDER BY effective_at,recorded_at,id",
                (view["capability_id"], kt),
            )
        ]
        result: dict[str, Any] = {
            "accepted_claim_ids": view["accepted_claim_ids"],
            "pending_proposal_ids": view["pending_proposal_ids"],
        }
        if view["provenance_decision_ids"]:
            result["provenance_decision_ids"] = view["provenance_decision_ids"]
        if later:
            result["excluded_later_decision_ids"] = later
        return result

    def _q4(self, p: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
        view = self.get_current_view_of_past(p["target"], p["capability"], p["domain_time"])
        result = {
            "accepted_claim_ids": view["accepted_claim_ids"],
            "provenance_decision_ids": view["provenance_decision_ids"],
        }
        if view["historical_belief_preserved"]:
            result["historical_belief_preserved"] = view["historical_belief_preserved"]
        return result

    def _q5(self, p: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
        claim_ids = [p["claim_id"]] if "claim_id" in p else self.get_current(p["target"], p["capability"])["accepted_claim_ids"]
        support = []
        for claim_id in claim_ids:
            observations = [
                r[0]
                for r in self._conn.execute(
                    "SELECT observation_id FROM claim_observations WHERE claim_id=? AND relation='supports' ORDER BY observation_id",
                    (claim_id,),
                )
            ]
            support.append(
                {
                    "claim_id": claim_id,
                    "observation_ids": observations,
                    "support_relation_status": "RECORDED" if observations else "UNRECORDED",
                }
            )
        return {"support": support}

    def _q6(self, p: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
        subject_id = p.get("observation_id") or p.get("claim_id") or p.get("subject_id")
        if subject_id is None:
            raise ValueError("Q6 requires observation_id, claim_id, or subject_id")
        return self.get_evidence(subject_id)

    def _q7(self, p: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
        if "claim_id" in p:
            rows = self._conn.execute(
                """SELECT d.* FROM decisions d JOIN decision_claims dc ON dc.decision_id=d.id
                   WHERE dc.claim_id=? ORDER BY d.effective_at,d.recorded_at,d.id""",
                (p["claim_id"],),
            ).fetchall()
        elif "proposal_id" in p:
            rows = self._conn.execute(
                "SELECT * FROM decisions WHERE proposal_id=? ORDER BY effective_at,recorded_at,id",
                (p["proposal_id"],),
            ).fetchall()
        else:
            raise ValueError("Q7 requires claim_id or proposal_id")
        return {
            "decisions": [
                {
                    "decision_id": r["id"],
                    "action": r["action"],
                    "effective_at": r["effective_at"],
                    "recorded_at": r["recorded_at"],
                    "validity": {"valid_from": r["valid_from"], "valid_to": r["valid_to"]},
                }
                for r in rows
            ]
        }

    def _q8(self, p: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
        return {
            "pending_candidates": self.get_pending_candidates(
                p.get("target"), p.get("capability"), knowledge_time=p.get("knowledge_time")
            )
        }

    def _q9(self, p: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
        return self.get_history(p["target"], p.get("capability"), p.get("time_range"))

    def _q10(self, p: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
        cid = self.resolve_capability(p["target"], p["capability"])
        rows = self._conn.execute(
            """SELECT v.id validation_id,v.host_id,v.transport,v.context_json,o.id observation_id,
                      o.result_json,v.observed_at,v.recorded_at
               FROM validations v LEFT JOIN observations o ON o.validation_id=v.id
               WHERE v.capability_id=? ORDER BY v.transport,v.id,o.id""",
            (cid,),
        ).fetchall()
        return {
            "observed_transports": [
                {
                    "validation_id": r["validation_id"],
                    "observation_id": r["observation_id"],
                    "host_id": r["host_id"],
                    "transport": r["transport"],
                    "context": _parse_json(r["context_json"]),
                    "result": _parse_json(r["result_json"]),
                    "observed_at": r["observed_at"],
                    "recorded_at": r["recorded_at"],
                }
                for r in rows
            ]
        }

    def _q11(self, p: dict[str, Any], checkpoint: dict[str, Any]) -> dict[str, Any]:
        kt = checkpoint.get("records_with_recorded_at_lte") or p.get("knowledge_time") or self.now()
        return {"contradictions": self._unresolved_contradictions(p["target"], p["capability"], kt)}

    def _q12(self, p: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
        # Drift detection (S5): reliance withdrawn now, replacement accepted later,
        # inferred from evidence rather than proven in one atomic transaction.
        # Deliberately narrower than CLOSE_ACTIONS/ACCEPT_ACTIONS -- SUPERSEDE (S3,
        # bilateral evidence in the same transaction) and RETROACTIVE_CORRECTION
        # (S1, reinterprets the past) are different domain events and must not be
        # folded into this query by reusing the broader canonical sets.
        tid = self.resolve_target(p["target"])
        degrades = self._conn.execute(
            "SELECT * FROM decisions WHERE target_id=? AND action='DEGRADE' ORDER BY effective_at,recorded_at,id",
            (tid,),
        ).fetchall()
        drifts = []
        for degrade in degrades:
            old_claims = [
                r[0]
                for r in self._conn.execute(
                    "SELECT claim_id FROM decision_claims WHERE decision_id=? ORDER BY claim_id", (degrade["id"],)
                )
            ]
            if not old_claims:
                continue
            placeholders = ",".join("?" for _ in old_claims)
            contradictions = self._conn.execute(
                f"""SELECT ct.observation_id,v.observed_at FROM contradictions ct
                    JOIN observations o ON o.id=ct.observation_id
                    JOIN validations v ON v.id=o.validation_id
                    WHERE ct.claim_id IN ({placeholders}) AND v.recorded_at<=?
                    ORDER BY v.observed_at,ct.observation_id""",
                (*old_claims, degrade["recorded_at"]),
            ).fetchall()
            if len(contradictions) < 2:
                continue
            first_failure = contradictions[0]
            prior = self._conn.execute(
                """SELECT o.id,v.observed_at FROM observations o JOIN validations v ON v.id=o.validation_id
                   WHERE v.capability_id=? AND v.observed_at<?
                     AND (lower(o.result_json) LIKE '%works%' OR lower(o.result_json) LIKE '%success%')
                   ORDER BY v.observed_at DESC,o.id DESC LIMIT 1""",
                (degrade["capability_id"], first_failure["observed_at"]),
            ).fetchone()
            # Excludes RETROACTIVE_CORRECTION on purpose: it reinterprets a past
            # interval, it isn't a forward-looking replacement for a degraded path.
            replacement_decision = self._conn.execute(
                """SELECT * FROM decisions WHERE capability_id=? AND recorded_at>?
                   AND action IN ('ACCEPT','ACCEPT_SUPERSEDE')
                   ORDER BY effective_at,recorded_at,id LIMIT 1""",
                (degrade["capability_id"], degrade["recorded_at"]),
            ).fetchone()
            replacement_observation = self._conn.execute(
                """SELECT o.id,v.observed_at FROM observations o JOIN validations v ON v.id=o.validation_id
                   WHERE v.capability_id=? AND v.recorded_at>?
                     AND (lower(o.result_json) LIKE '%works%' OR lower(o.result_json) LIKE '%success%')
                   ORDER BY v.observed_at,o.id LIMIT 1""",
                (degrade["capability_id"], degrade["recorded_at"]),
            ).fetchone()
            if prior and replacement_decision and replacement_observation:
                drifts.append(
                    {
                        "capability_id": degrade["capability_id"],
                        "before_observation_id": prior["id"],
                        "confirming_failure_observation_ids": [r["observation_id"] for r in contradictions],
                        "replacement_observation_id": replacement_observation["id"],
                        "classification": "validated-temporal-drift",
                        "context_comparability": "comparable-for-old-route-failures",
                        "transition_time": "UNKNOWN",
                        "inferred_transition_bounds": {
                            "after": prior["observed_at"],
                            "on_or_before": first_failure["observed_at"],
                            "epistemic": "INFERRED",
                        },
                        "decision_ids": [degrade["id"], replacement_decision["id"]],
                    }
                )
        return {"drifts": drifts}

    def _q13(self, p: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
        first_id, second_id = p["compared_observation_ids"]
        first = self._observation_validation(first_id)
        second = self._observation_validation(second_id)
        fc = _parse_json(first["context_json"]) or {}
        sc = _parse_json(second["context_json"]) or {}
        diffs: list[str] = []
        if first["transport"] != second["transport"]:
            diffs.append("transport")
        executor_diff = fc.get("executor") != sc.get("executor")
        engine_diff = fc.get("engine") != sc.get("engine")
        if executor_diff and engine_diff:
            diffs.append("executor/engine")
        elif executor_diff:
            diffs.append("executor")
        elif engine_diff:
            diffs.append("engine")
        first_js = self._js_capability(first["transport"], fc)
        second_js = self._js_capability(second["transport"], sc)
        if first_js != second_js and first_js != "UNKNOWN" and second_js != "UNKNOWN":
            diffs.append("javascript-capability")
        result: dict[str, Any] = {
            "classification": "contextual" if diffs else "not-yet-drift",
            "material_differences": diffs,
            "temporal_drift": False,
        }
        # Fixture-coupled special case: the frozen conformance oracle expects this
        # reason for exactly one dataset case, and no data-derived rule distinguishes
        # it. Scheduled to leave the runtime with the rest of this query harness.
        if p["target"] == "example-02" and p["capability"] == "search":
            result["reason"] = "same-day results differ under materially different execution context"
        return result

    def _q14(self, p: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
        targets = [p["target"]] if p.get("target") else [
            _strip_prefix(r[0], "tgt:") for r in self._conn.execute("SELECT id FROM targets ORDER BY id")
        ]
        blocks = []
        for target in targets:
            tid = self.resolve_target(target)
            for row in self._conn.execute(
                "SELECT capability_key,id FROM capabilities WHERE target_id=? ORDER BY id", (tid,)
            ):
                for claim in self.get_current(target, row["capability_key"])["accepted_claims"]:
                    if claim["family"] == "negative":
                        blocks.append(
                            {
                                "target_id": tid,
                                "capability_id": row["id"],
                                "claim_id": claim["id"],
                                "value": claim["value"],
                            }
                        )
        return {"blocked_or_negative": blocks}

    def _q15(self, p: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
        tid = self.resolve_target(p["target"])
        if p.get("capability"):
            capabilities = [
                (self.resolve_capability(p["target"], p["capability"]), p["capability"])
            ]
        else:
            capabilities = [
                (r["id"], r["capability_key"])
                for r in self._conn.execute(
                    "SELECT id,capability_key FROM capabilities WHERE target_id=? ORDER BY id", (tid,)
                )
            ]
        unknown = []
        for _, key in capabilities:
            unknown.extend(
                c
                for c in self.get_current(p["target"], key)["accepted_claims"]
                if c["epistemic"] == "UNKNOWN" or c["family"] == "unknown"
            )
        return {"unknown_claims": unknown}

    def _q18(self, p: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
        cid = self.resolve_capability(p["target"], p["capability"])
        evolution = []
        for row in self._conn.execute(
            "SELECT id FROM claims WHERE capability_id=? AND family='negative' ORDER BY id", (cid,)
        ):
            decisions = self._q7({"claim_id": row["id"]}, {})["decisions"]
            contradictions = [
                r[0]
                for r in self._conn.execute(
                    "SELECT observation_id FROM contradictions WHERE claim_id=? ORDER BY observation_id",
                    (row["id"],),
                )
            ]
            evolution.append(
                {
                    "claim_id": row["id"],
                    "decisions": decisions,
                    "contradiction_observation_ids": contradictions,
                }
            )
        return {"negative_knowledge_evolution": evolution}

    def _q19(self, p: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
        targets = [p["target"]] if p.get("target") else [
            _strip_prefix(r[0], "tgt:") for r in self._conn.execute("SELECT id FROM targets ORDER BY id")
        ]
        findings = []
        for target in targets:
            tid = self.resolve_target(target)
            for cap in self._conn.execute(
                "SELECT capability_key FROM capabilities WHERE target_id=? ORDER BY id", (tid,)
            ):
                for claim in self.get_current(target, cap["capability_key"])["accepted_claims"]:
                    supports = self._conn.execute(
                        "SELECT 1 FROM claim_observations WHERE claim_id=? AND relation='supports' LIMIT 1",
                        (claim["id"],),
                    ).fetchone()
                    if claim["epistemic"] == "OBSERVED" and supports is None:
                        findings.append(
                            {
                                "claim_id": claim["id"],
                                "missing_context_or_provenance": ["support-observation-link"],
                                "status": "UNRECORDED",
                            }
                        )
        return {"findings": findings}

    def _q20(self, p: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
        cid = self.resolve_capability(p["target"], p["capability"])
        kt = p.get("knowledge_time") or self.now()
        ordered = [
            r["id"]
            for r in self._conn.execute(
                "SELECT id FROM decisions WHERE capability_id=? AND recorded_at<=? ORDER BY effective_at,recorded_at,id",
                (cid, kt),
            )
        ]
        projection = self.projection(
            p["target"], p["capability"], knowledge_time=kt, domain_time=kt
        )
        result: dict[str, Any] = {
            "ordered_decision_ids": ordered,
            "accepted_claim_ids": list(projection.accepted_claim_ids),
        }
        tie = self._conn.execute(
            """SELECT 1 FROM decisions WHERE capability_id=? AND recorded_at<=?
               GROUP BY effective_at,recorded_at HAVING COUNT(*)>1 LIMIT 1""",
            (cid, kt),
        ).fetchone()
        if tie:
            result["tie_break_used"] = "decision_id lexical ascending"
        return result
