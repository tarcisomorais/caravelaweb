from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[0]
sys.path.insert(0, str(REPO))

from operational_memory import (
    DatabaseOpenError,
    RecordValidationError,
    SchemaVersionError,
    SQLiteOperationalMemory,
)
from conformance_harness import ConformanceMemory
from memory_lab_adapter import compare_minimum, load_memory_lab

FIXTURE = REPO / "tests" / "fixtures" / "memory-lab-v1.json"
EXPECTED = REPO / "tests" / "fixtures" / "memory-lab-v1.expected.json"
TEST_NOW = "2026-08-21T00:00:00Z"


def clock() -> str:
    return TEST_NOW


def run_oracle(memory: ConformanceMemory) -> dict:
    oracle = json.loads(EXPECTED.read_text(encoding="utf-8"))
    results = []
    for item in oracle["expected"]:
        actual = memory.canonical_query(item["query"], item["parameters"], item.get("checkpoint"))
        diffs = compare_minimum(item["result"], actual)
        results.append(
            {
                "id": item["id"],
                "query": item["query"],
                "status": "PASS" if not diffs else "FAIL",
                "diff": diffs,
                "actual": actual,
            }
        )
    return {"status": "PASS" if all(r["status"] == "PASS" for r in results) else "FAIL", "results": results}


def query_smoke(memory: ConformanceMemory) -> dict[str, str]:
    examples = {
        "Q1": {"target": "example-01", "capability": "project-listings"},
        "Q2": {"target": "example-06", "capability": "read", "domain_time": "2026-08-05T00:00:00Z"},
        "Q3": {"target": "example-08", "capability": "read", "knowledge_time": "2026-08-15T00:00:00Z", "domain_time": "2026-08-01T12:00:00Z"},
        "Q4": {"target": "example-08", "capability": "read", "domain_time": "2026-08-01T12:00:00Z"},
        "Q5": {"target": "example-01", "capability": "project-listings"},
        "Q6": {"observation_id": "obs:example-01:project-listings:20260725:01"},
        "Q7": {"claim_id": "clm:example-01:project-listings:entrypoint:categoria-tested"},
        "Q8": {"target": "example-01", "capability": "project-listings", "knowledge_time": "2026-07-25T20:59:59Z"},
        "Q9": {"target": "example-06", "capability": "read"},
        "Q10": {"target": "example-02", "capability": "search"},
        "Q11": {"target": "example-06", "capability": "read"},
        "Q12": {"target": "example-06"},
        "Q13": {"target": "example-02", "capability": "search", "compared_observation_ids": ["obs:example-02:search:20260725:01", "obs:example-02:search:20260725:03"]},
        "Q14": {"target": "example-04"},
        "Q15": {"target": "example-11", "capability": "request-detail"},
        "Q18": {"target": "example-07", "capability": "read"},
        "Q19": {"target": "example-02"},
        "Q20": {"dataset_version": "memory-lab-v1", "target": "example-09", "capability": "read", "knowledge_time": TEST_NOW},
    }
    result = {}
    for query, parameters in examples.items():
        try:
            memory.canonical_query(query, parameters)
            result[query] = "PASS"
        except Exception as exc:  # test diagnostic
            result[query] = f"FAIL: {type(exc).__name__}: {exc}"
    return result


def stress_checks(memory: ConformanceMemory) -> list[tuple[str, bool]]:
    checks: list[tuple[str, bool]] = []
    q3 = memory.canonical_query("Q3", {"target": "example-08", "capability": "read", "knowledge_time": "2026-08-15T00:00:00Z", "domain_time": "2026-08-01T12:00:00Z"})
    q4 = memory.canonical_query("Q4", {"target": "example-08", "capability": "read", "domain_time": "2026-08-01T12:00:00Z"})
    checks.append(("retroactive correction", q3["accepted_claim_ids"] != q4["accepted_claim_ids"]))

    pre = memory.canonical_query("Q3", {"target": "example-01", "capability": "project-listings", "knowledge_time": "2026-07-25T20:59:59Z", "domain_time": "2026-07-25T20:59:59Z"})
    post = memory.canonical_query("Q1", {"target": "example-01", "capability": "project-listings", "knowledge_time": TEST_NOW})
    checks.append(("promotion", "prop:example-01:project-listings:categoria-extension" in pre["pending_proposal_ids"] and not post["pending_proposal_ids"] and len(post["accepted_claim_ids"]) > len(pre["accepted_claim_ids"])))

    old = memory.canonical_query("Q2", {"target": "example-06", "capability": "read", "domain_time": "2026-08-05T00:00:00Z"})
    current = memory.canonical_query("Q1", {"target": "example-06", "capability": "read", "knowledge_time": TEST_NOW})
    checks.append(("supersession", "clm:example-06:read:entrypoint:old-route" in old["accepted_claim_ids"] and "clm:example-06:read:entrypoint:new-route" in current["accepted_claim_ids"]))

    contradiction = memory.canonical_query("Q11", {"target": "example-06", "capability": "read"}, {"records_with_recorded_at_lte": "2026-08-10T23:59:59Z"})
    checks.append(("contradiction", len(contradiction["contradictions"]) == 1 and contradiction["contradictions"][0]["accepted_knowledge_changed"] is False))

    degraded = memory.canonical_query("Q2", {"target": "example-06", "capability": "read", "domain_time": "2026-08-11T18:00:00Z"})
    checks.append(("degradation", degraded["accepted_claim_ids"] == []))

    drift = memory.canonical_query("Q12", {"target": "example-06"})
    checks.append(("drift", len(drift["drifts"]) == 1 and drift["drifts"][0]["transition_time"] == "UNKNOWN"))

    false_drift = memory.canonical_query("Q13", {"target": "example-05", "capability": "read", "compared_observation_ids": ["obs:example-05:read:20260805:01", "obs:example-05:read:20260805:02"]})
    checks.append(("false drift", false_drift["classification"] == "contextual" and false_drift["temporal_drift"] is False))
    checks.append(("as known then", q3["accepted_claim_ids"] == ["clm:example-08:read:entrypoint:route-x"]))
    checks.append(("as currently believed about then", q4["accepted_claim_ids"] == ["clm:example-08:read:unknown:route-x-day1-corrected"]))

    negative_current = memory.canonical_query("Q1", {"target": "example-07", "capability": "read", "knowledge_time": TEST_NOW})
    negative_past = memory.canonical_query("Q2", {"target": "example-07", "capability": "read", "domain_time": "2026-08-10T00:00:00Z"})
    checks.append(("negative knowledge evolution", "clm:example-07:read:negative:blocked" in negative_past["accepted_claim_ids"] and "clm:example-07:read:negative:blocked" in negative_current.get("inactive_historical_claim_ids", [])))

    example12_www = memory.canonical_query("Q10", {"target": "example-12", "capability": "static-public-content"})["observed_transports"]
    example12_help = memory.canonical_query("Q10", {"target": "example-12", "capability": "help-center"})["observed_transports"]
    checks.append(("multi-host isolation", {row["host_id"] for row in example12_www} == {"host:example-12:www"} and {row["host_id"] for row in example12_help} == {"host:example-12:help"}))

    unknown = memory.canonical_query("Q15", {"target": "example-11", "capability": "request-detail"})
    checks.append(("explicit UNKNOWN", any(claim["id"] == "clm:example-11:request-detail:unknown:authenticated-detail" for claim in unknown["unknown_claims"])))

    tie = memory.canonical_query("Q20", {"dataset_version": "memory-lab-v1", "target": "example-09", "capability": "read", "knowledge_time": TEST_NOW})
    checks.append(("Decision tie-break", tie.get("tie_break_used") == "decision_id lexical ascending" and tie["ordered_decision_ids"] == sorted(tie["ordered_decision_ids"])))
    return checks


def invariant_checks(memory: ConformanceMemory) -> list[tuple[str, bool]]:
    q3 = memory.canonical_query("Q3", {"target": "example-08", "capability": "read", "knowledge_time": "2026-08-15T00:00:00Z", "domain_time": "2026-08-01T12:00:00Z"})
    q4 = memory.canonical_query("Q4", {"target": "example-08", "capability": "read", "domain_time": "2026-08-01T12:00:00Z"})
    q13 = memory.canonical_query("Q13", {"target": "example-02", "capability": "search", "compared_observation_ids": ["obs:example-02:search:20260725:01", "obs:example-02:search:20260725:03"]})
    current99 = memory.canonical_query("Q1", {"target": "example-01", "capability": "project-listings", "knowledge_time": TEST_NOW})
    support99 = memory.canonical_query("Q5", {"claim_id": "clm:example-01:project-listings:entrypoint:categoria-tested"})
    evidence99 = memory.canonical_query("Q6", {"observation_id": "obs:example-01:project-listings:20260725:01"})
    pending_pre = memory.canonical_query("Q8", {"target": "example-01", "capability": "project-listings", "knowledge_time": "2026-07-25T20:59:59Z"})
    contradiction = memory.canonical_query("Q11", {"target": "example-06", "capability": "read"}, {"records_with_recorded_at_lte": "2026-08-10T23:59:59Z"})
    drift = memory.canonical_query("Q12", {"target": "example-06"})
    negative_current = memory.canonical_query("Q1", {"target": "example-07", "capability": "read", "knowledge_time": TEST_NOW})
    markdown = memory.render_markdown("example-02")

    checks = {
        "I1": q3["accepted_claim_ids"] != q4["accepted_claim_ids"] and "clm:example-08:read:entrypoint:route-x" in q4.get("historical_belief_preserved", []),
        "I2": bool(evidence99["evidence_ids"]),
        "I3": q13["classification"] == "contextual",
        "I4": support99["support"][0]["support_relation_status"] in {"RECORDED", "UNRECORDED"},
        "I5": current99["epistemic_summary"].get("INFERRED") == 1,
        "I6": current99["epistemic_summary"].get("UNKNOWN") == 1,
        "I7": bool(pending_pre["pending_candidates"]),
        "I8": len(current99["provenance_decision_ids"]) == 2,
        "I9": contradiction["contradictions"][0]["accepted_knowledge_changed"] is False,
        "I10": memory.canonical_query("Q2", {"target": "example-06", "capability": "read", "domain_time": "2026-08-11T18:00:00Z"})["accepted_claim_ids"] == [],
        "I11": q4.get("historical_belief_preserved") == ["clm:example-08:read:entrypoint:route-x"],
        "I12": "clm:example-07:read:negative:blocked" in negative_current.get("inactive_historical_claim_ids", []),
        "I13": drift["drifts"][0]["transition_time"] == "UNKNOWN",
        "I14": q13["temporal_drift"] is False,
        "I15": drift["drifts"][0]["classification"] == "validated-temporal-drift",
        "I16": {row["host_id"] for row in memory.canonical_query("Q10", {"target": "example-12", "capability": "help-center"})["observed_transports"]} == {"host:example-12:help"},
        "I17": memory.resolve_capability("example-02", "search") != memory.resolve_capability("example-02", "detail"),
        "I18": memory.canonical_query("Q20", {"dataset_version": "memory-lab-v1", "target": "example-09", "capability": "read", "knowledge_time": TEST_NOW})["tie_break_used"] == "decision_id lexical ascending",
        "I19": "Generated from canonical Operational Memory" in markdown,
        "I20": "Markdown is a projection" in markdown,
        "I21": memory.schema_version == 2,
        "I22": drift["drifts"][0]["transition_time"] == "UNKNOWN",
        "I23": memory.canonical_query("Q13", {"target": "example-05", "capability": "read", "compared_observation_ids": ["obs:example-05:read:20260805:01", "obs:example-05:read:20260805:02"]})["classification"] == "contextual",
        "I24": "clm:example-07:read:negative:blocked" in negative_current.get("inactive_historical_claim_ids", []),
    }
    return [(key, checks[key]) for key in [f"I{i}" for i in range(1, 25)]]


class FrozenConformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "memory.sqlite3"
        self.memory = ConformanceMemory(self.db, clock=clock)
        load_memory_lab(self.memory, FIXTURE)

    def tearDown(self) -> None:
        self.memory.close()
        self.temp.cleanup()

    def test_frozen_oracle_12_of_12(self) -> None:
        result = run_oracle(self.memory)
        self.assertEqual("PASS", result["status"], json.dumps(result, indent=2))
        self.assertEqual(12, len(result["results"]))

    def test_q1_q20(self) -> None:
        result = query_smoke(self.memory)
        self.assertEqual({f"Q{i}" for i in range(1, 21)} - {"Q16", "Q17"}, set(result))
        self.assertTrue(all(value == "PASS" for value in result.values()), result)

    def test_semantic_stress_13_of_13(self) -> None:
        checks = stress_checks(self.memory)
        self.assertEqual(13, len(checks))
        self.assertTrue(all(ok for _, ok in checks), checks)

    def test_invariants_i1_i24(self) -> None:
        checks = invariant_checks(self.memory)
        self.assertEqual([f"I{i}" for i in range(1, 25)], [name for name, _ in checks])
        self.assertTrue(all(ok for _, ok in checks), checks)

    def test_rendering_five_views(self) -> None:
        current = self.memory.get_current("example-02", "search")
        historical = self.memory.get_as_known_at("example-08", "read", "2026-08-15T00:00:00Z", "2026-08-01T12:00:00Z")
        timeline = self.memory.get_history("example-06", "read")
        compact = self.memory.render_operational_context("example-02", "search", {"authority": ["READ", "NAVIGATE"]})
        markdown = self.memory.render_markdown("example-02")
        self.assertTrue(current["accepted_claim_ids"])
        self.assertTrue(historical["accepted_claim_ids"])
        self.assertTrue(timeline["events"])
        self.assertFalse(compact["history_included"])
        self.assertNotIn("events", compact)
        self.assertIn("# Target Profile", markdown)

    def test_physical_order_does_not_change_oracle(self) -> None:
        normal = run_oracle(self.memory)
        second_db = Path(self.temp.name) / "reverse.sqlite3"
        with ConformanceMemory(second_db, clock=clock) as reverse:
            load_memory_lab(reverse, FIXTURE, reverse=True)
            reversed_result = run_oracle(reverse)
        self.assertEqual("PASS", normal["status"])
        self.assertEqual("PASS", reversed_result["status"])
        self.assertEqual(
            [item["actual"] for item in normal["results"]],
            [item["actual"] for item in reversed_result["results"]],
        )


class ProductionInfrastructureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_create_and_reopen_existing_database(self) -> None:
        db = self.root / "memory.sqlite3"
        with SQLiteOperationalMemory(db, clock=clock) as memory:
            self.assertEqual(2, memory.schema_version)
            self.assertTrue(memory.foreign_keys_enabled)
        with SQLiteOperationalMemory(db, clock=clock, create=False) as reopened:
            self.assertEqual(2, reopened.schema_version)

    def test_missing_database_with_create_false_is_explicit(self) -> None:
        with self.assertRaises(DatabaseOpenError):
            SQLiteOperationalMemory(self.root / "missing.sqlite3", create=False)

    def test_incompatible_schema_version_fails_explicitly(self) -> None:
        db = self.root / "memory.sqlite3"
        with SQLiteOperationalMemory(db, clock=clock):
            pass
        conn = sqlite3.connect(db)
        conn.execute("UPDATE schema_metadata SET schema_version=999 WHERE singleton=1")
        conn.commit()
        conn.close()
        with self.assertRaises(SchemaVersionError):
            SQLiteOperationalMemory(db, clock=clock, create=False)

    def test_foreign_keys_are_active(self) -> None:
        db = self.root / "memory.sqlite3"
        with SQLiteOperationalMemory(db, clock=clock) as memory:
            self.assertTrue(memory.foreign_keys_enabled)
            with self.assertRaises(sqlite3.IntegrityError):
                with memory.write_transaction() as writer:
                    writer.host({"id": "host:missing:www", "target_id": "tgt:missing", "hostname": "example.invalid"})

    def test_failed_compound_write_rolls_back(self) -> None:
        db = self.root / "memory.sqlite3"
        with SQLiteOperationalMemory(db, clock=clock) as memory:
            with self.assertRaises(sqlite3.IntegrityError):
                with memory.write_transaction() as writer:
                    writer.target({"id": "tgt:rollback", "name": "Rollback"})
                    writer.host({"id": "host:rollback:www", "target_id": "tgt:does-not-exist", "hostname": "example.invalid"})
            count = memory._conn.execute("SELECT COUNT(*) FROM targets WHERE id='tgt:rollback'").fetchone()[0]
            self.assertEqual(0, count)

    def test_write_close_reopen_query_persists(self) -> None:
        db = self.root / "memory.sqlite3"
        with ConformanceMemory(db, clock=clock) as memory:
            load_memory_lab(memory, FIXTURE)
            before = memory.canonical_query("Q1", {"target": "example-01", "capability": "project-listings", "knowledge_time": TEST_NOW})
        with ConformanceMemory(db, clock=clock, create=False) as reopened:
            after = reopened.canonical_query("Q1", {"target": "example-01", "capability": "project-listings", "knowledge_time": TEST_NOW})
        self.assertEqual(before, after)

    def test_two_local_databases_are_isolated(self) -> None:
        first = self.root / "first.sqlite3"
        second = self.root / "second.sqlite3"
        with SQLiteOperationalMemory(first, clock=clock) as a, SQLiteOperationalMemory(second, clock=clock) as b:
            with a.write_transaction() as writer:
                writer.target({"id": "tgt:only-a", "name": "Only A"})
            self.assertIsNotNone(a._conn.execute("SELECT 1 FROM targets WHERE id='tgt:only-a'").fetchone())
            self.assertIsNone(b._conn.execute("SELECT 1 FROM targets WHERE id='tgt:only-a'").fetchone())

    def test_non_sqlite_file_fails_explicitly(self) -> None:
        db = self.root / "corrupt.sqlite3"
        db.write_bytes(b"not a sqlite database")
        with self.assertRaises(DatabaseOpenError):
            SQLiteOperationalMemory(db, clock=clock, create=False)


class DecisionActionHardeningTests(unittest.TestCase):
    """Audit 2: a close-family Decision naming a Claim with no accepted interval
    open before it must surface loudly, never silently produce a misleading
    accepted projection.

    The check lives in the projection reducer, not the Decision writer: the
    reducer already re-sorts every Decision into logical (effective_at,
    recorded_at, id) order before folding, which is the only order this
    invariant can be checked in without depending on physical insertion
    order (see test_physical_order_does_not_change_oracle / invariant I18 --
    Operational Memory data may be loaded or replayed in any physical order).
    A write-time check keyed on "does a prior accept already exist in the
    table" would reject legitimate out-of-order/replayed writes.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "memory.sqlite3"
        self.memory = SQLiteOperationalMemory(self.db, clock=clock)
        with self.memory.write_transaction() as writer:
            writer.target({"id": "tgt:demo"})
            writer.capability({"id": "cap:demo:read", "target_id": "tgt:demo", "key": "read"})
            writer.claim({
                "id": "clm:demo:old", "target_id": "tgt:demo", "capability_id": "cap:demo:read",
                "family": "entrypoint", "epistemic": "OBSERVED", "value": "/old",
            })
            writer.decision({
                "id": "dec:demo:accept-old", "target_id": "tgt:demo", "capability_id": "cap:demo:read",
                "action": "ACCEPT", "claim_ids": ["clm:demo:old"],
                "effective_at": "2026-08-01T00:00:00Z", "recorded_at": "2026-08-01T00:00:00Z",
                "validity": {"valid_from": "2026-08-01T00:00:00Z", "valid_to": None},
            })

    def tearDown(self) -> None:
        self.memory.close()
        self.temp.cleanup()

    def test_close_action_on_never_accepted_claim_surfaces_loudly(self) -> None:
        with self.memory.write_transaction() as writer:
            writer.claim({
                "id": "clm:demo:never-accepted", "target_id": "tgt:demo", "capability_id": "cap:demo:read",
                "family": "entrypoint", "epistemic": "OBSERVED", "value": "/pending",
            })
            writer.decision({
                "id": "dec:demo:bad-degrade", "target_id": "tgt:demo", "capability_id": "cap:demo:read",
                "action": "DEGRADE", "claim_ids": ["clm:demo:never-accepted"],
                "effective_at": "2026-08-05T00:00:00Z", "recorded_at": "2026-08-05T00:00:00Z",
                "validity": {"valid_from": None, "valid_to": "2026-08-05T00:00:00Z"},
            })
        # The write itself succeeds (this is checked in logical fold order,
        # not at write time -- see class docstring). The very next read must
        # raise, not silently omit clm:demo:never-accepted as though nothing
        # were wrong.
        with self.assertRaises(RecordValidationError):
            self.memory.get_current("demo", "read")

    def test_bare_supersede_naming_old_and_new_claim_surfaces_loudly(self) -> None:
        """The historical failure mode: memory-contract.md's SUPERSEDE wording read
        literally (one Decision, two claim_ids, two effects) instead of the paired
        SUPERSEDE+ACCEPT_SUPERSEDE representation. Before this hardening, this
        silently vaporized clm:demo:old with no error at all (accepted_claim_ids
        went to []). It must now fail loudly instead."""
        with self.memory.write_transaction() as writer:
            writer.claim({
                "id": "clm:demo:new", "target_id": "tgt:demo", "capability_id": "cap:demo:read",
                "family": "entrypoint", "epistemic": "OBSERVED", "value": "/new",
            })
            writer.decision({
                "id": "dec:demo:bare-supersede", "target_id": "tgt:demo", "capability_id": "cap:demo:read",
                "action": "SUPERSEDE", "claim_ids": ["clm:demo:old", "clm:demo:new"],
                "effective_at": "2026-08-05T00:00:00Z", "recorded_at": "2026-08-05T00:00:00Z",
                "validity": {"valid_from": "2026-08-05T00:00:00Z", "valid_to": None},
            })
        with self.assertRaises(RecordValidationError):
            self.memory.get_current("demo", "read")

    def test_degrade_after_accept_is_allowed(self) -> None:
        with self.memory.write_transaction() as writer:
            writer.decision({
                "id": "dec:demo:degrade-old", "target_id": "tgt:demo", "capability_id": "cap:demo:read",
                "action": "DEGRADE", "claim_ids": ["clm:demo:old"],
                "effective_at": "2026-08-05T00:00:00Z", "recorded_at": "2026-08-05T00:00:00Z",
                "validity": {"valid_from": None, "valid_to": "2026-08-05T00:00:00Z"},
            })
        self.assertEqual([], self.memory.get_current("demo", "read")["accepted_claim_ids"])

    def test_withdraw_reliance_is_not_a_valid_action(self) -> None:
        with self.assertRaises(RecordValidationError):
            with self.memory.write_transaction() as writer:
                writer.decision({
                    "id": "dec:demo:withdraw", "target_id": "tgt:demo", "capability_id": "cap:demo:read",
                    "action": "WITHDRAW_RELIANCE", "claim_ids": ["clm:demo:old"],
                    "effective_at": "2026-08-05T00:00:00Z", "recorded_at": "2026-08-05T00:00:00Z",
                    "validity": {"valid_from": None, "valid_to": "2026-08-05T00:00:00Z"},
                })


class JsCapabilityTransportSourceTests(unittest.TestCase):
    """Pin _js_capability to transport_policy.BROWSER_TRANSPORTS, its single source."""

    def test_browser_transports_infer_javascript_capable(self) -> None:
        from transport_policy import BROWSER_TRANSPORTS

        for transport in BROWSER_TRANSPORTS:
            with self.subTest(transport=transport):
                self.assertIs(True, ConformanceMemory._js_capability(transport, {}))

    def test_direct_read_is_unknown_without_explicit_context(self) -> None:
        from transport_policy import DIRECT_READ

        self.assertEqual("UNKNOWN", ConformanceMemory._js_capability(DIRECT_READ, {}))

    def test_explicit_context_overrides_transport_inference(self) -> None:
        from transport_policy import DIRECT_READ, LIGHTPANDA

        self.assertIs(True, ConformanceMemory._js_capability(DIRECT_READ, {"javascript": True}))
        self.assertIs(False, ConformanceMemory._js_capability(LIGHTPANDA, {"javascript": False}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
