from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[0]
SKILL = REPO
sys.path.insert(0, str(SKILL))

from discovery_finalize import DiscoveryFinalizationError, finalize_discovery
from om_native_writes import (
    OMProposalError,
    capture_candidate,
    replace_candidate,
    review_token,
)
from operational_memory.core import SQLiteOperationalMemory
from write_authority import MIGRATED_WRITE_AUTHORITY_KIND

T1 = "2026-07-28T12:00:00Z"
T2 = "2026-07-29T12:00:00Z"
NEW_EVIDENCE = "https://app.example.com/new-path"
OLD_EVIDENCE = "https://app.example.com/old-path-failure"


class ContinuousLearningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".caravelaweb").mkdir()
        (self.root / "targets").mkdir()
        (self.root / ".caravelaweb/write-authority.json").write_text(json.dumps({
            "kind": MIGRATED_WRITE_AUTHORITY_KIND, "status": "ACTIVE",
            "previous_write_authority": "LEGACY", "write_authority": "OPERATIONAL_MEMORY",
            "om_authoritative_writes": 0, "first_om_write": "NOT_PERFORMED",
        }), encoding="utf-8")
        self.memory = SQLiteOperationalMemory(
            self.root / ".caravelaweb/operational_memory.db", knowledge_root=self.root
        )
        self.addCleanup(self.memory.close)

    # All durable Operational Memory tables `--validate` must leave untouched.
    _SNAPSHOT_TABLES = (
        "targets", "hosts", "capabilities", "evidence", "validations",
        "observations", "observation_evidence", "claims", "claim_observations",
        "proposals", "proposal_claims", "decisions", "decision_claims",
        "contradictions",
    )

    def _table_snapshot(self):
        return {
            table: sorted(
                json.dumps(dict(row), sort_keys=True, default=str)
                for row in self.memory._conn.execute(f"SELECT * FROM {table}").fetchall()
            )
            for table in self._SNAPSHOT_TABLES
        }

    def finalize(self, observation, *, at=T1, run="001", evidence=None, dry_run=False):
        transport_trace = None
        validation = observation.get("validation", {})
        contradiction = observation.get("contradiction", {})
        old_validation = contradiction.get("validation", {})
        if (
            validation.get("transport") in {"LIGHTPANDA", "CHROME"}
            and old_validation.get("transport") == "DIRECT_READ"
            and validation.get("evidence")
            and old_validation.get("evidence")
        ):
            host = ({"host": observation["host"]} if observation.get("host") else {})
            transport_trace = {
                "availability": {
                    "LIGHTPANDA": (
                        "AVAILABLE"
                        if validation["transport"] == "LIGHTPANDA"
                        else "PLATFORM_UNSUPPORTED"
                    ),
                    "CHROME": "AVAILABLE",
                },
                "attempts": [
                    {
                        "transport": "DIRECT_READ", "outcome": "FAILED",
                        "evidence": old_validation["evidence"], **host,
                    },
                    {
                        "transport": validation["transport"],
                        "outcome": "FUNCTIONAL",
                        "evidence": validation["evidence"], **host,
                    },
                ],
            }
        return finalize_discovery(
            self.memory, target="example", capability="search",
            observations=[observation],
            evidence=evidence or [
                {
                    "kind": "new-path-validation", "locator": NEW_EVIDENCE,
                    "scope": "TARGET_SURFACE",
                },
                {
                    "kind": "old-path-failure", "locator": OLD_EVIDENCE,
                    "scope": "TARGET_SURFACE",
                },
            ],
            provenance={"run_id": f"run:example:{run}", "observed_at": at},
            recorded_at=at,
            transport_trace=transport_trace,
            dry_run=dry_run,
        )

    @staticmethod
    def observed(
        transport, *, family="transport", value=None, host=None, context=None,
        engine=None, javascript=False, evidence=None,
    ):
        item = {
            "family": family,
            "value": value or {"transport": transport, "outcome": "FUNCTIONAL"},
            "validation": {
                "transport": transport, "outcome": "FUNCTIONAL",
                "engine": engine, "javascript": javascript,
                "context": context or {
                    "authentication": "PUBLIC", "environment": "PRODUCTION",
                },
                "evidence": evidence if evidence is not None else [NEW_EVIDENCE],
            },
        }
        if host:
            item["host"] = host
        return item

    def replacement(
        self, *, family="transport", prior_value=None, new_value=None, host=None,
        context=None, failure_class="TARGET_CHANGED", prior_transport="DIRECT_READ",
        new_transport="CHROME", old_engine=None, new_engine=None,
        old_javascript=False, new_javascript=False, new_evidence=None,
        old_evidence=None,
    ):
        item = self.observed(
            new_transport, family=family, value=new_value, host=host,
            context=context, engine=new_engine, javascript=new_javascript,
            evidence=new_evidence if new_evidence is not None else [NEW_EVIDENCE],
        )
        item["contradiction"] = {
            "prior_value": prior_value or {
                "transport": prior_transport, "outcome": "FUNCTIONAL",
            },
            "validation": {
                "transport": prior_transport, "outcome": "FAILED",
                "failure_class": failure_class,
                "engine": old_engine, "javascript": old_javascript,
                "context": context or {
                    "authentication": "PUBLIC", "environment": "PRODUCTION",
                },
                "evidence": old_evidence if old_evidence is not None else [OLD_EVIDENCE],
            },
        }
        return item

    def route_observed(self, *, context=None):
        return self.observed(
            "DIRECT_READ", family="search_surface", value={"path": "/old"},
            context=context,
        )

    def route_replacement(self, **overrides):
        return self.replacement(
            family="search_surface", prior_value={"path": "/old"},
            new_value={"path": "/new"}, prior_transport="DIRECT_READ",
            new_transport="DIRECT_READ", **overrides,
        )

    def test_safe_replacement_changes_current_and_preserves_history_idempotently(self):
        self.assertEqual("SAVED", self.finalize(self.observed("DIRECT_READ")).status)
        old_id = self.memory.get_current("example", "search")["accepted_claim_ids"][0]
        replaced = self.finalize(self.replacement(), at=T2, run="002")
        self.assertEqual("SAVED", replaced.status)
        current = self.memory.get_current("example", "search")
        self.assertNotIn(old_id, current["accepted_claim_ids"])
        self.assertEqual("CHROME", current["accepted_claims"][0]["value"]["transport"])
        replacement_validations = list(self.memory._conn.execute(
            "SELECT transport,context_json FROM validations WHERE recorded_at=? ORDER BY id", (T2,)
        ))
        self.assertEqual({"CHROME", "DIRECT_READ"}, {
            row["transport"] for row in replacement_validations
        })
        self.assertEqual({"FUNCTIONAL", "FAILED"}, {
            json.loads(row["context_json"])["outcome"] for row in replacement_validations
        })
        history = self.memory.get_history("example", "search")["events"]
        self.assertIn(old_id, {event["id"] for event in history})
        counts = tuple(self.memory._conn.execute(
            f"SELECT count(*) FROM {table}"
        ).fetchone()[0] for table in ("claims", "proposals", "decisions"))
        self.assertEqual("ALREADY_EXISTS", self.finalize(self.replacement(), at=T2, run="003").status)
        self.assertEqual(counts, tuple(self.memory._conn.execute(
            f"SELECT count(*) FROM {table}"
        ).fetchone()[0] for table in ("claims", "proposals", "decisions")))

    def test_validate_rolls_back_the_replace_candidate_branch(self):
        # `dry_run` must roll back replace_candidate exactly like any other
        # write inside the same transaction: distinct from the enrichment and
        # capture_candidate branches covered in test_discovery_finalize.py.
        self.assertEqual("SAVED", self.finalize(self.observed("DIRECT_READ")).status)
        old_id = self.memory.get_current("example", "search")["accepted_claim_ids"][0]
        before = self._table_snapshot()

        predicted = self.finalize(self.replacement(), at=T2, run="002", dry_run=True)
        self.assertEqual("SAVED", predicted.status)
        self.assertEqual(before, self._table_snapshot())
        current = self.memory.get_current("example", "search")
        self.assertEqual([old_id], current["accepted_claim_ids"])
        self.assertEqual("DIRECT_READ", current["accepted_claims"][0]["value"]["transport"])

        real = self.finalize(self.replacement(), at=T2, run="002")
        self.assertEqual("SAVED", real.status)
        current = self.memory.get_current("example", "search")
        self.assertNotIn(old_id, current["accepted_claim_ids"])
        self.assertEqual("CHROME", current["accepted_claims"][0]["value"]["transport"])

    def test_replacement_failure_rolls_back_candidate_and_decisions(self):
        self.finalize(self.observed("DIRECT_READ"))
        self.memory._conn.execute("""CREATE TRIGGER refuse_supersede BEFORE INSERT ON decisions
            WHEN NEW.action='SUPERSEDE' BEGIN SELECT RAISE(ABORT, 'fixture'); END""")
        before = tuple(self.memory._conn.execute(
            f"SELECT count(*) FROM {table}"
        ).fetchone()[0] for table in ("claims", "proposals", "decisions", "validations", "observations"))
        with self.assertRaises(Exception):
            self.finalize(self.replacement(), at=T2, run="002")
        after = tuple(self.memory._conn.execute(
            f"SELECT count(*) FROM {table}"
        ).fetchone()[0] for table in ("claims", "proposals", "decisions", "validations", "observations"))
        self.assertEqual(before, after)
        self.assertEqual("DIRECT_READ", self.memory.get_current(
            "example", "search"
        )["accepted_claims"][0]["value"]["transport"])

    def assert_change_stays_pending(self, change):
        self.finalize(self.observed("DIRECT_READ"))
        result = self.finalize(change, at=T2, run="002")
        self.assertEqual("NOT_SAVED", result.status)
        self.assertEqual("DIRECT_READ", self.memory.get_current(
            "example", "search"
        )["accepted_claims"][0]["value"]["transport"])

    def test_transient_failure_stays_pending(self):
        self.assert_change_stays_pending(
            self.replacement(failure_class="TRANSIENT_NETWORK")
        )

    def test_different_material_context_stays_pending(self):
        self.assert_change_stays_pending(
            self.replacement(context={"authentication": "PUBLIC", "environment": "STAGING"})
        )

    def test_transport_mismatch_stays_pending(self):
        self.assert_change_stays_pending(
            self.replacement(prior_transport="LIGHTPANDA")
        )

    def test_concurrent_proposal_stays_pending(self):
        self.finalize(self.observed("DIRECT_READ"))
        inferred = self.observed(
            "DIRECT_READ", family="limitation", value={"state": "UNCONFIRMED"}
        )
        inferred["epistemic"] = "INFERRED"
        self.assertEqual("NOT_SAVED", self.finalize(inferred, at=T2, run="002").status)
        self.assertEqual("NOT_SAVED", self.finalize(
            self.replacement(), at="2026-07-30T12:00:00Z", run="003"
        ).status)

    def test_mixed_incompatible_delta_stays_pending(self):
        direct = self.observed("DIRECT_READ")
        chrome = self.observed("CHROME")
        direct["validation"]["evidence"] = ["https://app.example.com/search"]
        chrome["validation"]["evidence"] = ["https://app.example.com/search"]
        result = finalize_discovery(
            self.memory, target="example", capability="search",
            observations=[
                direct,
                chrome,
            ],
            evidence=[{
                "kind": "browser-validation", "locator": "https://app.example.com/search",
                "scope": "TARGET_SURFACE",
            }],
            provenance={"run_id": "run:example:mixed", "observed_at": T1},
            recorded_at=T1,
        )
        self.assertEqual("NOT_SAVED", result.status)
        self.assertEqual("TRANSPORT_POLICY_UNPROVEN", result.reason_code)
        self.assertEqual(0, self.memory._conn.execute(
            "SELECT count(*) FROM targets"
        ).fetchone()[0])

    def test_multiple_plausible_prior_claims_prevent_replacement(self):
        self.finalize(self.observed("DIRECT_READ"))
        with self.memory.write_transaction() as writer:
            writer.claim({
                "id": "clm:example:search:duplicate-prior",
                "target_id": "tgt:example", "capability_id": "cap:example:search",
                "family": "transport", "epistemic": "OBSERVED",
                "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"},
                "recorded_at": T1,
            })
            writer.decision({
                "id": "dec:example:search:duplicate-prior",
                "target_id": "tgt:example", "capability_id": "cap:example:search",
                "action": "ACCEPT", "claim_ids": ["clm:example:search:duplicate-prior"],
                "effective_at": T1, "recorded_at": T1,
                "validity": {"valid_from": T1, "valid_to": None},
            })
        result = self.finalize(self.replacement(), at=T2, run="002")
        self.assertEqual("NOT_SAVED", result.status)
        self.assertEqual(2, len(self.memory.get_current(
            "example", "search"
        )["accepted_claim_ids"]))

    def test_host_is_created_reused_and_linked_to_claim_and_validation(self):
        observation = self.observed("DIRECT_READ", host="App.Example.COM.")
        result = self.finalize(observation)
        self.assertEqual("SAVED", result.status)
        host = self.memory._conn.execute(
            "SELECT id,hostname FROM hosts WHERE target_id='tgt:example'"
        ).fetchone()
        self.assertEqual("app.example.com", host["hostname"])
        self.assertEqual(host["id"], self.memory._conn.execute(
            "SELECT host_id FROM claims"
        ).fetchone()[0])
        self.assertEqual(host["id"], self.memory._conn.execute(
            "SELECT host_id FROM validations"
        ).fetchone()[0])
        self.assertEqual("ALREADY_EXISTS", self.finalize(
            observation, at=T2, run="002"
        ).status)
        self.assertEqual(1, self.memory._conn.execute("SELECT count(*) FROM hosts").fetchone()[0])

    def test_target_scope_and_two_hosts_remain_distinct(self):
        self.assertEqual("SAVED", self.finalize(self.observed("DIRECT_READ")).status)
        host_result = self.finalize(
            self.observed("DIRECT_READ", host="app.example.com"), at=T2, run="002"
        )
        self.assertEqual("SAVED", host_result.status)
        claims = self.memory.get_current("example", "search")["accepted_claims"]
        self.assertEqual({None, self.memory._conn.execute(
            "SELECT id FROM hosts"
        ).fetchone()[0]}, {claim["host_id"] for claim in claims})

    def test_external_evidence_does_not_create_target_host(self):
        observation = self.observed("DIRECT_READ", host="app.example.com")
        observation["validation"]["evidence"] = ["https://third.example/source"]
        with self.assertRaises(DiscoveryFinalizationError):
            self.finalize(
                observation,
                evidence=[{"kind": "search-result", "locator": "https://third.example/source"}],
            )
        self.assertEqual(0, self.memory._conn.execute("SELECT count(*) FROM hosts").fetchone()[0])

    def test_two_hosts_with_two_transports_in_one_payload_are_saved(self):
        app = self.observed(
            "CHROME", host="app.example.com", evidence=["https://app.example.com/search"]
        )
        app_direct = self.observed(
            "DIRECT_READ", host="app.example.com",
            evidence=["https://app.example.com/search"],
        )
        app_direct["value"]["outcome"] = "FAILED"
        app_direct["validation"]["outcome"] = "FAILED"
        help_center = self.observed(
            "DIRECT_READ", host="help.example.com",
            evidence=["https://help.example.com/search"],
        )
        result = finalize_discovery(
            self.memory, target="example", capability="search",
            observations=[app_direct, app, help_center],
            evidence=[
                {
                    "kind": "browser-validation", "locator": "https://app.example.com/search",
                    "scope": "TARGET_SURFACE",
                },
                {
                    "kind": "direct-validation", "locator": "https://help.example.com/search",
                    "scope": "TARGET_SURFACE",
                },
            ],
            provenance={"run_id": "run:example:two-hosts", "observed_at": T1},
            recorded_at=T1,
            transport_trace={
                "availability": {
                    "LIGHTPANDA": "PLATFORM_UNSUPPORTED", "CHROME": "AVAILABLE",
                },
                "attempts": [
                    {
                        "transport": "DIRECT_READ", "outcome": "FAILED",
                        "host": "app.example.com",
                        "evidence": ["https://app.example.com/search"],
                    },
                    {
                        "transport": "CHROME", "outcome": "FUNCTIONAL",
                        "host": "app.example.com",
                        "evidence": ["https://app.example.com/search"],
                    },
                ],
            },
        )
        self.assertEqual("SAVED", result.status)
        current = self.memory.get_current("example", "search")["accepted_claims"]
        self.assertEqual(3, len(current))
        self.assertEqual({"CHROME", "DIRECT_READ"}, {
            claim["value"]["transport"] for claim in current
        })

    def assert_non_transport_replacement(self, family, prior_value, new_value):
        baseline = self.observed(
            "DIRECT_READ", family=family, value=prior_value,
        )
        self.assertEqual("SAVED", self.finalize(baseline).status)
        changed = self.replacement(
            family=family, prior_value=prior_value, new_value=new_value,
            prior_transport="DIRECT_READ", new_transport="DIRECT_READ",
        )
        self.assertEqual("SAVED", self.finalize(changed, at=T2, run="002").status)
        current = self.memory.get_current("example", "search")["accepted_claims"]
        self.assertEqual(new_value, current[0]["value"])

    def test_search_surface_replacement_does_not_depend_on_value_transport(self):
        self.assert_non_transport_replacement(
            "search_surface",
            {"path": "/search", "method": "GET"},
            {"path": "/busca", "method": "GET"},
        )

    def test_extraction_replacement_does_not_depend_on_value_transport(self):
        self.assert_non_transport_replacement(
            "extraction",
            {"structure": "JSON_LD", "field_paths": {"name": "item.name"}},
            {"structure": "EMBEDDED_JSON", "field_paths": {"name": "data.name"}},
        )

    def test_only_new_path_evidence_stays_pending(self):
        self.finalize(self.route_observed())
        result = self.finalize(
            self.route_replacement(old_evidence=[]), at=T2, run="002"
        )
        self.assertEqual("NOT_SAVED", result.status)
        self.assertEqual("INSUFFICIENT_BILATERAL_EVIDENCE", result.reason_code)

    def test_pending_unilateral_is_enriched_and_replaced_by_bilateral_discovery(self):
        self.finalize(self.route_observed())
        old_id = self.memory.get_current("example", "search")["accepted_claim_ids"][0]
        unilateral = self.finalize(
            self.route_replacement(old_evidence=[]), at=T2, run="002"
        )
        self.assertEqual("NOT_SAVED", unilateral.status)
        pending = self.memory.get_pending_candidates("example", "search")
        self.assertEqual(1, len(pending))
        proposal_id = pending[0]["proposal_id"]
        claim_id = pending[0]["claim_ids"][0]
        before = {
            table: self.memory._conn.execute(
                f"SELECT count(*) FROM {table}"
            ).fetchone()[0]
            for table in ("claims", "proposals")
        }

        completed = self.finalize(
            self.route_replacement(), at=T2, run="003"
        )
        self.assertEqual("SAVED", completed.status)
        self.assertEqual(proposal_id, completed.proposal_id)
        self.assertEqual(before["claims"], self.memory._conn.execute(
            "SELECT count(*) FROM claims"
        ).fetchone()[0])
        self.assertEqual(before["proposals"], self.memory._conn.execute(
            "SELECT count(*) FROM proposals"
        ).fetchone()[0])
        current = self.memory.get_current("example", "search")
        self.assertEqual([claim_id], current["accepted_claim_ids"])
        self.assertNotIn(old_id, current["accepted_claim_ids"])
        self.assertIn(old_id, {
            event["id"] for event in self.memory.get_history(
                "example", "search"
            )["events"]
        })
        counts = {
            table: self.memory._conn.execute(
                f"SELECT count(*) FROM {table}"
            ).fetchone()[0]
            for table in (
                "claims", "proposals", "evidence", "observations", "decisions"
            )
        }
        repeated = self.finalize(
            self.route_replacement(), at=T2, run="004"
        )
        self.assertEqual("ALREADY_EXISTS", repeated.status)
        self.assertEqual(counts, {
            table: self.memory._conn.execute(
                f"SELECT count(*) FROM {table}"
            ).fetchone()[0]
            for table in counts
        })

    def test_exact_pending_repeat_returns_already_pending_without_writes(self):
        self.finalize(self.route_observed())
        change = self.route_replacement(old_evidence=[])
        self.assertEqual("NOT_SAVED", self.finalize(
            change, at=T2, run="002"
        ).status)
        before = {
            table: self.memory._conn.execute(
                f"SELECT count(*) FROM {table}"
            ).fetchone()[0]
            for table in (
                "claims", "proposals", "evidence", "validations",
                "observations", "decisions",
            )
        }
        repeated = self.finalize(
            change, at=T2, run="003"
        )
        self.assertEqual("NOT_SAVED", repeated.status)
        self.assertEqual("ALREADY_PENDING", repeated.reason_code)
        self.assertEqual(before, {
            table: self.memory._conn.execute(
                f"SELECT count(*) FROM {table}"
            ).fetchone()[0]
            for table in before
        })

    def test_multi_claim_pending_repeat_returns_already_pending_without_writes(self):
        self.finalize(self.route_observed())
        change = self.route_replacement(old_evidence=[])
        self.finalize(change, at=T2, run="002")
        pending = self.memory.get_pending_candidates("example", "search")[0]
        extra_claim_id = "clm:example:search:pending-extra"
        with self.memory.write_transaction() as writer:
            writer.claim({
                "id": extra_claim_id,
                "target_id": "tgt:example",
                "capability_id": "cap:example:search",
                "family": "limitation",
                "epistemic": "INFERRED",
                "value": {"state": "UNCONFIRMED"},
                "proposal_id": pending["proposal_id"],
                "recorded_at": T2,
            })
            writer.proposal_claim(pending["proposal_id"], extra_claim_id)
        before = {
            table: self.memory._conn.execute(
                f"SELECT count(*) FROM {table}"
            ).fetchone()[0]
            for table in (
                "claims", "proposals", "evidence", "validations",
                "observations", "contradictions", "decisions",
            )
        }
        repeated = self.finalize(change, at=T2, run="003")
        self.assertEqual("NOT_SAVED", repeated.status)
        self.assertEqual("ALREADY_PENDING", repeated.reason_code)
        self.assertEqual(before, {
            table: self.memory._conn.execute(
                f"SELECT count(*) FROM {table}"
            ).fetchone()[0]
            for table in before
        })

    def test_insufficient_enrichment_is_preserved_once_and_remains_pending(self):
        self.finalize(self.route_observed())
        staging = {"authentication": "PUBLIC", "environment": "STAGING"}
        self.finalize(self.route_replacement(
            context=staging, old_evidence=[]
        ), at=T2, run="002")
        enriched_change = self.route_replacement(context=staging)
        enriched = self.finalize(
            enriched_change, at=T2, run="003"
        )
        self.assertEqual("NOT_SAVED", enriched.status)
        self.assertEqual("INCOMPARABLE_MATERIAL_CONTEXT", enriched.reason_code)
        self.assertEqual(1, len(self.memory.get_pending_candidates(
            "example", "search"
        )))
        before = tuple(self.memory._conn.execute(
            f"SELECT count(*) FROM {table}"
        ).fetchone()[0] for table in (
            "claims", "proposals", "evidence", "validations", "observations"
        ))
        repeated = self.finalize(
            enriched_change, at=T2, run="004"
        )
        self.assertEqual("ALREADY_PENDING", repeated.reason_code)
        self.assertEqual(before, tuple(self.memory._conn.execute(
            f"SELECT count(*) FROM {table}"
        ).fetchone()[0] for table in (
            "claims", "proposals", "evidence", "validations", "observations"
        )))

    def test_competing_different_pending_proposal_blocks_enriched_promotion(self):
        self.finalize(self.route_observed())
        self.finalize(self.route_replacement(old_evidence=[]), at=T2, run="002")
        competing = self.observed(
            "DIRECT_READ", family="limitation", value={"state": "UNCONFIRMED"}
        )
        competing["epistemic"] = "INFERRED"
        self.finalize(
            competing, at=T2, run="003"
        )
        result = self.finalize(
            self.route_replacement(), at=T2, run="004"
        )
        self.assertEqual("NOT_SAVED", result.status)
        self.assertEqual(2, len(self.memory.get_pending_candidates(
            "example", "search"
        )))
        self.assertEqual({"path": "/old"}, self.memory.get_current(
            "example", "search"
        )["accepted_claims"][0]["value"])

    def test_enrichment_and_promotion_failure_roll_back_together(self):
        self.finalize(self.route_observed())
        self.finalize(self.route_replacement(old_evidence=[]), at=T2, run="002")
        before = tuple(self.memory._conn.execute(
            f"SELECT count(*) FROM {table}"
        ).fetchone()[0] for table in (
            "claims", "proposals", "evidence", "validations",
            "observations", "contradictions", "decisions",
        ))
        self.memory._conn.execute("""CREATE TRIGGER refuse_enriched_supersede
            BEFORE INSERT ON decisions WHEN NEW.action='SUPERSEDE'
            BEGIN SELECT RAISE(ABORT, 'fixture'); END""")
        with self.assertRaises(Exception):
            self.finalize(
                self.route_replacement(), at=T2, run="003"
            )
        self.assertEqual(before, tuple(self.memory._conn.execute(
            f"SELECT count(*) FROM {table}"
        ).fetchone()[0] for table in (
            "claims", "proposals", "evidence", "validations",
            "observations", "contradictions", "decisions",
        )))

    def test_only_old_failure_evidence_stays_pending(self):
        self.finalize(self.route_observed())
        result = self.finalize(
            self.route_replacement(new_evidence=[]), at=T2, run="002"
        )
        self.assertEqual("NOT_SAVED", result.status)
        self.assertEqual("INSUFFICIENT_BILATERAL_EVIDENCE", result.reason_code)

    def test_engine_difference_stays_pending(self):
        self.finalize(self.observed(
            "DIRECT_READ", family="search_surface",
            value={"path": "/old"}, engine="chrome",
        ))
        result = self.finalize(self.replacement(
            family="search_surface", prior_value={"path": "/old"},
            new_value={"path": "/new"},
            prior_transport="DIRECT_READ", new_transport="DIRECT_READ",
            old_engine="chrome", new_engine="firefox",
        ), at=T2, run="002")
        self.assertEqual("NOT_SAVED", result.status)
        self.assertEqual("INCOMPARABLE_MATERIAL_CONTEXT", result.reason_code)

    def test_javascript_difference_stays_pending(self):
        self.finalize(self.observed(
            "DIRECT_READ", family="extraction",
            value={"structure": "OLD"}, javascript=False,
        ))
        result = self.finalize(self.replacement(
            family="extraction", prior_value={"structure": "OLD"},
            new_value={"structure": "NEW"},
            prior_transport="DIRECT_READ", new_transport="DIRECT_READ",
            old_javascript=False, new_javascript=True,
        ), at=T2, run="002")
        self.assertEqual("NOT_SAVED", result.status)
        self.assertEqual("INCOMPARABLE_MATERIAL_CONTEXT", result.reason_code)

    def test_prior_claim_without_material_baseline_stays_pending(self):
        old = {
            "family": "search_surface", "value": {"path": "/search"},
        }
        self.assertEqual("SAVED", self.finalize(old).status)
        result = self.finalize(self.replacement(
            family="search_surface", prior_value={"path": "/search"},
            new_value={"path": "/busca"}, prior_transport="DIRECT_READ",
            new_transport="DIRECT_READ",
        ), at=T2, run="002")
        self.assertEqual("NOT_SAVED", result.status)
        self.assertEqual("INSUFFICIENT_MATERIAL_BASELINE", result.reason_code)

    def direct_candidate(
        self, *, family="transport", host_id=None,
        contradiction_locator=OLD_EVIDENCE,
    ):
        self.finalize(self.observed("DIRECT_READ"))
        old_id = self.memory.get_current("example", "search")["accepted_claim_ids"][0]
        if host_id:
            with self.memory.write_transaction() as writer:
                writer.host({
                    "id": host_id, "target_id": "tgt:example",
                    "hostname": "other.example.com",
                })
        proposal_id = f"prop:example:search:direct-{family}-{host_id or 'target'}"
        claim_id = f"clm:example:search:direct-{family}-{host_id or 'target'}"
        captured = capture_candidate(
            self.memory, target="example", capability="search",
            proposal_id=proposal_id,
            claims=[{
                "id": claim_id, "family": family, "epistemic": "OBSERVED",
                "value": {"state": "NEW"}, "host_id": host_id,
            }],
            provenance={"run_id": "run:direct", "observed_at": T2},
            recorded_at=T2,
            supporting_evidence={claim_id: [{
                "id": f"ev:direct:new:{family}:{host_id or 'target'}",
                "kind": "new-path", "locator": NEW_EVIDENCE, "recorded_at": T2,
            }]},
            validation_contexts={claim_id: {
                "transport": "DIRECT_READ", "observed_at": T2,
                "context": {
                    "engine": None, "javascript": False,
                    "authentication": "PUBLIC", "environment": "PRODUCTION",
                    "outcome": "FUNCTIONAL",
                },
            }},
            contradicting_claims={claim_id: [old_id]},
            contradiction_contexts={claim_id: {
                "transport": "DIRECT_READ", "observed_at": T2,
                "context": {
                    "engine": None, "javascript": False,
                    "authentication": "PUBLIC", "environment": "PRODUCTION",
                    "outcome": "FAILED", "failure_class": "TARGET_CHANGED",
                },
                "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"},
            }},
            contradicting_evidence={claim_id: [{
                "id": f"ev:direct:old:{family}:{host_id or 'target'}",
                "kind": "old-path", "locator": contradiction_locator,
                "recorded_at": T2,
            }]},
        )
        return old_id, captured.proposal_id

    def test_direct_replace_rejects_cross_family(self):
        old_id, proposal_id = self.direct_candidate(family="extraction")
        with self.assertRaises(OMProposalError):
            replace_candidate(
                self.memory, target="example", capability="search",
                proposal_id=proposal_id, replaced_claim_ids=[old_id],
                reviewed_token=review_token(
                    self.memory, target="example", capability="search"
                ),
                decision_id="dec:example:search:direct-family",
                recorded_at=T2, effective_at=T2,
            )

    def test_direct_replace_rejects_cross_host(self):
        old_id, proposal_id = self.direct_candidate(host_id="host:example:other")
        with self.assertRaises(OMProposalError):
            replace_candidate(
                self.memory, target="example", capability="search",
                proposal_id=proposal_id, replaced_claim_ids=[old_id],
                reviewed_token=review_token(
                    self.memory, target="example", capability="search"
                ),
                decision_id="dec:example:search:direct-host",
                recorded_at=T2, effective_at=T2,
            )

    def test_direct_replace_rejects_distinct_ids_with_same_locator(self):
        old_id, proposal_id = self.direct_candidate(
            contradiction_locator=NEW_EVIDENCE
        )
        with self.assertRaises(OMProposalError):
            replace_candidate(
                self.memory, target="example", capability="search",
                proposal_id=proposal_id, replaced_claim_ids=[old_id],
                reviewed_token=review_token(
                    self.memory, target="example", capability="search"
                ),
                decision_id="dec:example:search:direct-same-locator",
                recorded_at=T2, effective_at=T2,
            )
