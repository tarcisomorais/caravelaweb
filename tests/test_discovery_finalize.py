from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[0]
SKILL = REPO
FINALIZER = SKILL / "scripts" / "discovery-finalize"
LOOKUP = SKILL / "scripts" / "knowledge-lookup"
sys.path.insert(0, str(SKILL))

from discovery_finalize import DiscoveryFinalizationError, finalize_discovery
from om_native_writes import OMNativeWriteError, OMWriteAuthorityRequired, WRITE_DESTINATION
from operational_memory.core import SQLiteOperationalMemory
from platform_adapter import resolve_knowledge_root
from write_authority import MIGRATED_WRITE_AUTHORITY_KIND, WriteAuthorityStateError

RECORDED = "2026-07-28T12:00:00Z"


def authority(root: Path) -> None:
    (root / ".caravelaweb").mkdir()
    (root / ".caravelaweb/write-authority.json").write_text(json.dumps({
        "kind": MIGRATED_WRITE_AUTHORITY_KIND, "status": "ACTIVE",
        "previous_write_authority": "LEGACY", "write_authority": "OPERATIONAL_MEMORY",
        "om_authoritative_writes": 0, "first_om_write": "NOT_PERFORMED",
    }), encoding="utf-8")


class DiscoveryFinalizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        authority(self.root)
        (self.root / "targets").mkdir()
        self.db = self.root / ".caravelaweb/operational_memory.db"
        self.memory = SQLiteOperationalMemory(self.db, knowledge_root=self.root)
        self.addCleanup(self.memory.close)
        with self.memory.write_transaction() as writer:
            writer.target({"id": "tgt:example-news"})
            writer.capability({"id": "cap:example-news:topic-search", "target_id": "tgt:example-news", "key": "topic-search"})

    def payload(self, observations=None):
        return {
            "target": "example-news", "capability": "topic-search",
            "observations": observations or [
                {"family": "transport", "value": {"transport": "CHROME", "outcome": "FUNCTIONAL"}},
                {"family": "extraction", "value": {"structure": "JSON_LD"}},
            ],
            "evidence": [{"kind": "bounded-browser-validation", "locator": "https://www.example-news.com/busca/"}],
            "provenance": {"run_id": "run:example-news:001", "observed_at": RECORDED},
            "recorded_at": RECORDED,
        }

    def finalize(self, payload=None):
        payload = payload or self.payload()
        return finalize_discovery(
            self.memory, target=payload["target"], capability=payload["capability"],
            observations=payload["observations"], evidence=payload["evidence"], provenance=payload["provenance"],
            recorded_at=payload["recorded_at"], knowledge_write_authority=True,
            write_destination=WRITE_DESTINATION,
        )

    def operational_payload(
        self, *, target="synthetic-operational", capability="extract-items",
        outcome="SUCCESS", proof=None, evidence_references=True,
        observations=None,
    ):
        locator = f"https://{target}.example/items"
        proof = proof if proof is not None else {
            "entrypoint": locator,
            "required_output": {"field_paths": {"name": "items[].name"}},
            "completion_condition": "the item collection is present",
            "critical_constraints": [],
        }
        return {
            "target": target,
            "capability": capability,
            "observations": observations or [
                {"family": "transport", "value": {"transport": "DIRECT_READ"}},
                {"family": "authentication", "value": {"access_model": "PUBLIC"}},
                {
                    "family": "validation",
                    "value": {"operational_proof": proof},
                    "validation": {
                        "transport": "DIRECT_READ",
                        "outcome": outcome,
                        "engine": None,
                        "javascript": False,
                        "context": {"authentication": "PUBLIC"},
                        **({"evidence": [locator]} if evidence_references else {}),
                    },
                },
            ],
            "evidence": [{"kind": "synthetic-validation", "locator": locator}],
            "provenance": {"run_id": f"run:{target}:001", "observed_at": RECORDED},
            "recorded_at": RECORDED,
        }

    def accept(self, observation):
        with self.memory.write_transaction() as writer:
            writer.claim({"id": "clm:example-news:topic-search:accepted", "target_id": "tgt:example-news", "capability_id": "cap:example-news:topic-search", "family": observation["family"], "epistemic": observation.get("epistemic", "OBSERVED"), "value": observation["value"], "recorded_at": RECORDED})
            writer.decision({"id": "dec:example-news:topic-search:accepted", "target_id": "tgt:example-news", "capability_id": "cap:example-news:topic-search", "action": "ACCEPT", "claim_ids": ["clm:example-news:topic-search:accepted"], "effective_at": RECORDED, "recorded_at": RECORDED, "validity": {"valid_from": RECORDED, "valid_to": None}})

    def test_new_knowledge_and_repeat_are_deterministic(self):
        created = self.finalize()
        self.assertEqual("SAVED", created.status)
        self.assertEqual(2, len(self.memory.get_current("example-news", "topic-search")["accepted_claim_ids"]))
        repeated = self.finalize()
        self.assertEqual("ALREADY_EXISTS", repeated.status)
        self.assertEqual([], self.memory.get_pending_candidates("example-news", "topic-search"))

    def test_accepted_knowledge_is_not_recaptured(self):
        payload = self.payload()
        for index, observation in enumerate(payload["observations"]):
            if index:
                # A separate accepted Claim/Decision is enough for the semantic check.
                with self.memory.write_transaction() as writer:
                    writer.claim({"id": f"clm:example-news:topic-search:accepted-{index}", "target_id": "tgt:example-news", "capability_id": "cap:example-news:topic-search", "family": observation["family"], "epistemic": "OBSERVED", "value": observation["value"], "recorded_at": RECORDED})
                    writer.decision({"id": f"dec:example-news:topic-search:accepted-{index}", "target_id": "tgt:example-news", "capability_id": "cap:example-news:topic-search", "action": "ACCEPT", "claim_ids": [f"clm:example-news:topic-search:accepted-{index}"], "effective_at": RECORDED, "recorded_at": RECORDED, "validity": {"valid_from": RECORDED, "valid_to": None}})
            else:
                self.accept(observation)
        self.assertEqual("ALREADY_EXISTS", self.finalize(payload).status)

    def test_empty_observations_close_discovery_without_a_candidate(self):
        payload = {
            "target": "new-target", "capability": "new-capability",
            "observations": [], "evidence": [],
            "provenance": {"run_id": "run:empty:001", "observed_at": RECORDED},
            "recorded_at": RECORDED,
        }
        result = self.finalize(payload)
        self.assertEqual("NOT_SAVED", result.status)
        self.assertEqual(0, self.memory._conn.execute("SELECT count(*) FROM proposals").fetchone()[0])

    def test_new_example_portal_target_is_saved_and_immediately_usable(self):
        payload = {
            "target": "example-portal", "capability": "rss_feed", "recorded_at": RECORDED,
            "provenance": {"run_id": "run:example-portal:rss:001", "observed_at": RECORDED},
            "evidence": [{"kind": "direct-read-validation", "locator": "https://rss.example-portal.com/"}],
            "observations": [{"family": "transport", "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"}}],
        }
        self.assertIsNone(self.memory._conn.execute("SELECT 1 FROM targets WHERE id='tgt:example-portal'").fetchone())
        created = self.finalize(payload)
        self.assertEqual("SAVED", created.status)
        self.assertEqual(1, len(self.memory.get_current("example-portal", "rss-feed")["accepted_claim_ids"]))
        self.assertEqual([], self.memory.get_pending_candidates("example-portal", "rss-feed"))

    def test_new_scope_is_not_created_without_knowledge_write_authority(self):
        payload = {
            "target": "example-portal", "capability": "world_section_access", "recorded_at": RECORDED,
            "provenance": {"run_id": "run:example-portal:world:001", "observed_at": RECORDED},
            "evidence": [{"kind": "direct-read-validation", "locator": "https://www.example-portal.com/mundo/"}],
            "observations": [{"family": "transport", "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"}}],
        }
        with self.assertRaises(OMWriteAuthorityRequired):
            finalize_discovery(
                self.memory, target=payload["target"], capability=payload["capability"],
                observations=payload["observations"], evidence=payload["evidence"], provenance=payload["provenance"],
                recorded_at=payload["recorded_at"], knowledge_write_authority=False,
                write_destination=WRITE_DESTINATION,
            )
        self.assertIsNone(self.memory._conn.execute("SELECT 1 FROM targets WHERE id='tgt:example-portal'").fetchone())

    def test_cli_finalizes_a_new_example_portal_scope_and_lookup_stays_not_found(self):
        (self.root / ".caravelaweb/read-authority-operational-memory").write_text("active", encoding="utf-8")
        initial_lookup = subprocess.run(
            [sys.executable, str(LOOKUP), "--knowledge-root", str(self.root), "--target", "example-portal", "--capability", "rss_feed"],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(0, initial_lookup.returncode, initial_lookup.stderr)
        self.assertEqual("not_found", json.loads(initial_lookup.stdout)["status"])
        self.assertIsNone(self.memory._conn.execute("SELECT 1 FROM targets WHERE id='tgt:example-portal'").fetchone())
        payload = self.root / "example-portal-discovery.json"
        payload.write_text(json.dumps({
            "target": "example-portal", "capability": "rss_feed", "recorded_at": RECORDED,
            "provenance": {"run_id": "run:example-portal:cli:001", "observed_at": RECORDED},
            "evidence": [{"kind": "direct-read-validation", "locator": "https://rss.example-portal.com/"}],
            "observations": [{"family": "transport", "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"}}],
        }), encoding="utf-8")
        finalized = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root), "--input", str(payload)],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(0, finalized.returncode, finalized.stderr)
        self.assertEqual("SAVED", json.loads(finalized.stdout)["status"])
        before_lookup = self.memory._conn.execute("SELECT count(*) FROM targets").fetchone()[0]
        lookup = subprocess.run(
            [sys.executable, str(LOOKUP), "--knowledge-root", str(self.root), "--target", "example-portal", "--capability", "rss_feed"],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(0, lookup.returncode, lookup.stderr)
        lookup_body = json.loads(lookup.stdout)
        self.assertEqual("found", lookup_body["status"])
        self.assertNotIn("lifecycle", lookup_body["operational_context"]["current"])
        self.assertEqual(before_lookup, self.memory._conn.execute("SELECT count(*) FROM targets").fetchone()[0])

    def test_cli_errors_are_structured_without_a_traceback(self):
        payload = self.root / "invalid-discovery.json"
        payload.write_text(json.dumps({"target": "example-portal", "capability": "rss_feed"}), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root), "--input", str(payload)],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(2, result.returncode)
        self.assertEqual("NOT_SAVED", json.loads(result.stderr)["status"])
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_reports_specific_reason_for_missing_family(self):
        payload = self.root / "missing-family-discovery.json"
        payload.write_text(json.dumps({
            "target": "example-news", "capability": "topic-search", "recorded_at": RECORDED,
            "provenance": {"run_id": "run:missing-family:001", "observed_at": RECORDED},
            "evidence": [{"kind": "direct-read-validation", "locator": "https://example.com/"}],
            "observations": [{"value": {"transport": "DIRECT_READ"}}],
        }), encoding="utf-8")
        before = tuple(self.memory._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("claims", "proposals"))
        result = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root), "--input", str(payload)],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(2, result.returncode)
        body = json.loads(result.stderr)
        self.assertEqual("NOT_SAVED", body["status"])
        self.assertEqual("observation family is not reusable operational knowledge", body["reason"])
        self.assertNotIn("Traceback", result.stderr)
        after = tuple(self.memory._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("claims", "proposals"))
        self.assertEqual(before, after)

    def test_cli_reports_specific_reason_for_invalid_family(self):
        payload = self.root / "invalid-family-discovery.json"
        payload.write_text(json.dumps({
            "target": "example-news", "capability": "topic-search", "recorded_at": RECORDED,
            "provenance": {"run_id": "run:invalid-family:001", "observed_at": RECORDED},
            "evidence": [{"kind": "direct-read-validation", "locator": "https://example.com/"}],
            "observations": [{"family": "prices", "value": {"transport": "DIRECT_READ"}}],
        }), encoding="utf-8")
        before = tuple(self.memory._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("claims", "proposals"))
        result = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root), "--input", str(payload)],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(2, result.returncode)
        body = json.loads(result.stderr)
        self.assertEqual("NOT_SAVED", body["status"])
        self.assertEqual("observation family is not reusable operational knowledge", body["reason"])
        self.assertNotIn("Traceback", result.stderr)
        after = tuple(self.memory._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("claims", "proposals"))
        self.assertEqual(before, after)

    def test_cli_still_saves_a_valid_payload_after_specific_error_reporting(self):
        payload = self.root / "valid-after-fix-discovery.json"
        payload.write_text(json.dumps({
            "target": "example-portal", "capability": "rss_feed", "recorded_at": RECORDED,
            "provenance": {"run_id": "run:example-portal:valid-after-fix:001", "observed_at": RECORDED},
            "evidence": [{"kind": "direct-read-validation", "locator": "https://rss.example-portal.com/"}],
            "observations": [{"family": "transport", "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"}}],
        }), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root), "--input", str(payload)],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        body = json.loads(result.stdout)
        self.assertEqual("SAVED", body["status"])
        self.assertNotIn("reason", body)

    def test_cli_authority_failure_returns_generic_reason_without_internals(self):
        marker = self.root / ".caravelaweb/write-authority.json"
        marker.write_text(json.dumps({
            "kind": MIGRATED_WRITE_AUTHORITY_KIND, "status": "SUSPENDED",
            "previous_write_authority": "LEGACY", "write_authority": "OPERATIONAL_MEMORY",
            "om_authoritative_writes": 0, "first_om_write": "NOT_PERFORMED",
        }), encoding="utf-8")
        payload = self.root / "authority-failure-discovery.json"
        payload.write_text(json.dumps(self.payload()), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root), "--input", str(payload)],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(2, result.returncode)
        body = json.loads(result.stderr)
        self.assertEqual("NOT_SAVED", body["status"])
        self.assertEqual("Discovery could not be finalized in local Operational Memory.", body["reason"])
        for forbidden in ("Claim", "Proposal", "Decision", "OPERATIONAL_MEMORY", "LEGACY", str(self.root)):
            self.assertNotIn(forbidden, result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_default_root_resolution_is_independent_of_the_consumer_cwd(self):
        # Root resolution (env/remembered-default/marker-walk from the
        # script's own path) must not depend on the caller's cwd. It does
        # NOT default to this repository checkout -- H2 deliberately made a
        # fresh clone unable to auto-identify itself as a Knowledge Root, so
        # the expectation here is computed the same way the script computes
        # it, not hardcoded to REPO or to any particular resolved value.
        expected = resolve_knowledge_root(None, start=str(FINALIZER))
        consumer = self.root / "consumer"
        consumer.mkdir()
        previous_cwd = Path.cwd()
        self.addCleanup(os.chdir, previous_cwd)
        os.chdir(consumer)
        finalizer = runpy.run_path(str(FINALIZER))
        self.assertEqual(expected, finalizer["resolve_root"](None))

    def test_cli_uses_the_explicit_fixture_root_without_per_run_authority(self):
        consumer = self.root / "consumer"
        consumer.mkdir()
        payload = consumer / "discovery.json"
        payload.write_text(json.dumps({
            "target": "example-listings", "capability": "project-listings",
            "observations": [], "evidence": [],
            "provenance": {"run_id": "run:root:001", "observed_at": RECORDED},
            "recorded_at": RECORDED,
        }), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root), "--input", str(payload)],
            cwd=consumer, text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("NOT_SAVED", json.loads(result.stdout)["status"])

    def test_missing_evidence_wrong_authority_and_task_data_fail_closed(self):
        payload = self.payload()
        with self.assertRaises(DiscoveryFinalizationError):
            self.finalize({**payload, "evidence": []})
        with self.assertRaises(DiscoveryFinalizationError):
            self.finalize({**payload, "observations": [{"family": "extraction", "value": {"titles": ["not reusable"]}}]})
        with self.assertRaises(OMNativeWriteError):
            finalize_discovery(self.memory, target=payload["target"], capability=payload["capability"], observations=payload["observations"], evidence=payload["evidence"], provenance=payload["provenance"], recorded_at=RECORDED, knowledge_write_authority=True, write_destination=WRITE_DESTINATION, authority_at_operation="LEGACY")
        with self.assertRaises(OMWriteAuthorityRequired):
            finalize_discovery(self.memory, target=payload["target"], capability=payload["capability"], observations=payload["observations"], evidence=payload["evidence"], provenance=payload["provenance"], recorded_at=RECORDED, knowledge_write_authority=False, write_destination=WRITE_DESTINATION)

    def test_extraction_schema_field_path_is_reusable_not_task_data(self):
        result = self.finalize(self.payload([
            {"family": "extraction", "value": {"structure": "JSON_LD", "field_paths": {"title": "post.title"}}},
        ]))
        self.assertEqual("SAVED", result.status)

    def test_extraction_actual_title_content_is_still_rejected(self):
        payload = self.payload([
            {"family": "extraction", "value": {"field_paths": {"title": "Governo anuncia novo pacote econômico"}}},
        ])
        with self.assertRaises(DiscoveryFinalizationError):
            self.finalize(payload)

    def test_schema_field_path_exemption_does_not_apply_outside_extraction(self):
        payload = self.payload([
            {"family": "transport", "value": {"transport": "CHROME", "title": "post.title"}},
        ])
        with self.assertRaises(DiscoveryFinalizationError):
            self.finalize(payload)

    def test_result_shaped_observation_values_fail_closed_without_writes(self):
        cases = {
            "unknown-key": {"instructor_name": "Current Person"},
            "nested-object": {"container": {"members": [{"name": "Current Person"}]}},
            "result-array": {"people": ["Current Person"]},
            "generic-data": {"data": {"value": "Current Person"}},
        }
        before = tuple(self.memory._conn.execute(
            f"SELECT count(*) FROM {table}"
        ).fetchone()[0] for table in ("claims", "proposals", "evidence"))
        for name, value in cases.items():
            with self.subTest(case=name), self.assertRaises(DiscoveryFinalizationError):
                self.finalize(self.payload([{"family": "extraction", "value": value}]))
        after = tuple(self.memory._conn.execute(
            f"SELECT count(*) FROM {table}"
        ).fetchone()[0] for table in ("claims", "proposals", "evidence"))
        self.assertEqual(before, after)

    def test_persisted_wrappers_reject_unknown_structured_fields(self):
        payload = self.payload([{
            "family": "validation", "value": {"rule": "OUTPUT_PRESENT"},
            "validation": {
                "transport": "DIRECT_READ", "outcome": "FUNCTIONAL",
                "context": {"people": ["Current Person"]},
            },
        }])
        cases = (
            payload,
            {**self.payload(), "evidence": [{
                "kind": "synthetic-validation", "locator": "https://example.com/",
                "records": [{"name": "Current Person"}],
            }]},
            {**self.payload(), "provenance": {
                "run_id": "run:result:001", "observed_at": RECORDED,
                "people": ["Current Person"],
            }},
            self.payload([{
                "family": "transport", "value": {"transport": "DIRECT_READ"},
                "returned_data": ["Current Person"],
            }]),
            self.payload([{
                "family": "extraction", "value": {"structure": "JSON_LD"},
                "contradiction": {
                    "prior_value": {"people": ["Current Person"]},
                    "validation": {
                        "transport": "DIRECT_READ", "outcome": "FAILED",
                        "failure_class": "TARGET_CHANGED",
                        "context": {
                            "authentication": "PUBLIC", "environment": "PRODUCTION",
                        },
                    },
                },
            }]),
        )
        for index, case in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(DiscoveryFinalizationError):
                self.finalize(case)

    def test_canonical_public_family_values_remain_accepted(self):
        observations = [
            {"family": "transport", "value": {
                "transport": "DIRECT_READ", "outcome": "FUNCTIONAL",
            }},
            {"family": "authentication", "value": {"access_model": "PUBLIC"}},
            {"family": "search_surface", "value": {
                "surface": "OFFICIAL_SEARCH", "path": "/search", "method": "GET",
            }},
            {"family": "pagination", "value": {
                "mode": "QUERY_PARAMETER", "parameter": "page",
                "stop_condition": "the next-page link is absent",
            }},
            {"family": "paywall", "value": {"signal": "PAYWALL_MARKER"}},
            {"family": "blocking", "value": {
                "failure_class": "TARGET_BLOCK", "condition": "a challenge page is shown",
            }},
            {"family": "limitation", "value": {
                "kind": "FIELD_UNAVAILABLE", "constraint": "public pages omit private fields",
            }},
        ]
        result = self.finalize(self.payload(observations))
        self.assertEqual("SAVED", result.status)
        current = self.memory.get_current("example-news", "topic-search")
        self.assertEqual(7, len(current["accepted_claims"]))

    def test_extraction_paths_selectors_and_operational_constraints_remain_reusable(self):
        extraction = self.payload([{
            "family": "extraction",
            "value": {
                "structure": "RESULT_CARDS",
                "field_paths": {"name": "items[].name"},
                "selectors": {"profile_url": "article a[href]"},
            },
        }])
        self.assertEqual("SAVED", self.finalize(extraction).status)

        operational = self.operational_payload(
            target="synthetic-constrained",
            proof={
                "entrypoint": "https://synthetic-constrained.example/items",
                "required_output": {
                    "field_paths": {"name": "items[].name"},
                    "selectors": {"profile_url": "article a[href]"},
                },
                "completion_condition": "the requested item collection is present",
                "critical_constraints": ["pagination must reach the final page"],
            },
        )
        self.assertEqual("SAVED", self.finalize(operational).status)
        self.assertTrue(self.memory.has_verified_operational_lifecycle(
            operational["target"], operational["capability"]
        ))

    def test_operational_proof_rejects_result_shaped_structures(self):
        base = {
            "entrypoint": "https://synthetic-proof.example/items",
            "required_output": {"field_paths": {"name": "items[].name"}},
            "completion_condition": "the requested item collection is present",
            "critical_constraints": [],
        }
        proofs = (
            {**base, "required_output": {"people": ["Current Person"]}},
            {**base, "critical_constraints": [{"members": ["Current Person"]}]},
            {**base, "entrypoint": {"data": ["Current Person"]}},
            {**base, "required_output": ["Current Person"]},
            {**base, "returned_data": ["Current Person"]},
        )
        for index, proof in enumerate(proofs):
            with self.subTest(case=index), self.assertRaises(DiscoveryFinalizationError):
                self.finalize(self.operational_payload(
                    target=f"synthetic-result-proof-{index}", proof=proof
                ))

    def test_required_action_proof_remains_operational(self):
        payload = self.operational_payload(
            target="synthetic-action",
            proof={
                "entrypoint": "https://synthetic-action.example/search",
                "required_action": "submit the bounded public search query",
                "completion_condition": "the result surface is present",
                "critical_constraints": ["caller authority remains read-only"],
            },
        )
        self.assertEqual("SAVED", self.finalize(payload).status)
        self.assertTrue(self.memory.has_verified_operational_lifecycle(
            payload["target"], payload["capability"]
        ))

    def test_cli_rejects_unknown_top_level_fields(self):
        payload = self.root / "unknown-wrapper.json"
        payload.write_text(json.dumps({
            **self.payload(), "returned_data": [{"name": "Current Person"}],
        }), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root), "--input", str(payload)],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("unsupported fields", json.loads(result.stderr)["reason"])

    def test_invalid_payload_has_no_partial_write(self):
        before = tuple(self.memory._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("claims", "proposals", "evidence"))
        payload = self.payload([{"family": "transport", "value": {"html": "<html>bad</html>"}}])
        with self.assertRaises(DiscoveryFinalizationError):
            self.finalize(payload)
        after = tuple(self.memory._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("claims", "proposals", "evidence"))
        self.assertEqual(before, after)

    def test_transaction_failure_has_no_partial_write(self):
        self.memory._conn.execute("""CREATE TRIGGER refuse_discovery_proposal
            BEFORE INSERT ON proposals BEGIN SELECT RAISE(ABORT, 'fixture failure'); END""")
        before = tuple(self.memory._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("claims", "proposals", "evidence", "observations"))
        with self.assertRaises(Exception):
            self.finalize()
        after = tuple(self.memory._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("claims", "proposals", "evidence", "observations"))
        self.assertEqual(before, after)

    def test_decision_failure_rolls_back_capture(self):
        self.memory._conn.execute("""CREATE TRIGGER refuse_discovery_decision
            BEFORE INSERT ON decisions BEGIN SELECT RAISE(ABORT, 'fixture decision failure'); END""")
        before = tuple(self.memory._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("claims", "proposals", "evidence", "observations", "decisions"))
        with self.assertRaises(Exception):
            self.finalize()
        after = tuple(self.memory._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("claims", "proposals", "evidence", "observations", "decisions"))
        self.assertEqual(before, after)

    def test_rejected_claim_does_not_block_new_observation(self):
        with self.memory.write_transaction() as writer:
            writer.claim({
                "id": "clm:example-news:topic-search:rejected",
                "target_id": "tgt:example-news",
                "capability_id": "cap:example-news:topic-search",
                "family": "transport", "epistemic": "OBSERVED",
                "value": {"transport": "CHROME"}, "recorded_at": RECORDED,
            })
            writer.decision({
                "id": "dec:example-news:topic-search:rejected",
                "target_id": "tgt:example-news",
                "capability_id": "cap:example-news:topic-search",
                "action": "REJECT", "claim_ids": ["clm:example-news:topic-search:rejected"],
                "effective_at": RECORDED, "recorded_at": RECORDED,
                "validity": {"valid_from": RECORDED, "valid_to": None},
            })
        self.assertEqual("SAVED", self.finalize(self.payload([
            {"family": "transport", "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"}},
        ])).status)

    def test_every_non_saved_path_has_a_human_reason(self):
        empty = self.finalize({
            "target": "new-target", "capability": "new-capability", "observations": [], "evidence": [],
            "provenance": {"run_id": "run:reason:empty", "observed_at": RECORDED}, "recorded_at": RECORDED,
        })
        self.assertTrue(empty.as_dict()["reason"])
        inferred = self.finalize(self.payload([
            {"family": "transport", "epistemic": "INFERRED", "value": {"transport": "DIRECT_READ"}},
        ]))
        self.assertTrue(inferred.as_dict()["reason"])
        conflict = self.finalize(self.payload([
            {"family": "transport", "value": {"transport": "DIRECT_READ"}},
        ]))
        self.assertEqual("SAVED", conflict.status)
        conflict = self.finalize(self.payload([
            {"family": "transport", "value": {"transport": "CHROME"}},
        ]))
        self.assertTrue(conflict.as_dict()["reason"])

    def test_example_news_fixture_retains_only_operational_facts(self):
        fixture = self.payload([
            {"family": "search_surface", "value": {"surface": "OFFICIAL_SEARCH"}},
            {"family": "transport", "value": {"transport": "CHROME", "outcome": "FUNCTIONAL"}},
            {"family": "extraction", "value": {"structure": "JSON_LD"}},
            {"family": "paywall", "value": {"signal": "PAYWALL_MARKER"}},
            {"family": "limitation", "value": {"mode": "METADATA_ONLY"}},
        ])
        self.assertEqual("SAVED", self.finalize(fixture).status)
        text = "\n".join(row[0] for row in self.memory._conn.execute("SELECT payload_json FROM claims"))
        self.assertNotIn("title", text.lower())
        self.assertNotIn("article", text.lower())

    def test_example_maps_fixture_retains_no_store_names(self):
        with self.memory.write_transaction() as writer:
            writer.target({"id": "tgt:example-maps"})
            writer.capability({"id": "cap:example-maps:local-search", "target_id": "tgt:example-maps", "key": "local-search"})
        payload = {"target": "example-maps", "capability": "local-search", "recorded_at": RECORDED,
            "provenance": {"run_id": "run:maps:001", "observed_at": RECORDED},
            "evidence": [{"kind": "bounded-browser-validation", "locator": "https://maps.example.com/"}],
            "observations": [
                {"family": "transport", "value": {"transport": "CHROME", "requirement": "BROWSER_REQUIRED"}},
                {"family": "search_surface", "value": {"surface": "RESULT_FEED", "loading": "PROGRESSIVE"}},
                {"family": "extraction", "value": {"structure": "RESULT_CARDS"}},
                {"family": "validation", "value": {"rule": "GEOGRAPHIC_MATCH"}},
            ]}
        self.assertEqual("SAVED", self.finalize(payload).status)
        text = "\n".join(row[0] for row in self.memory._conn.execute("SELECT payload_json FROM claims WHERE target_id='tgt:example-maps'"))
        self.assertNotIn("store", text.lower())

    def test_public_direct_read_discoveries_are_saved_without_per_run_authority(self):
        for target, capability in (("example-portal", "rss-feed"), ("example-daily", "home-feed"), ("example-wire", "search")):
            result = self.finalize({
                "target": target,
                "capability": capability,
                "observations": [{"family": "transport", "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"}}],
                "evidence": [{"kind": "direct-read-validation", "locator": f"https://{target}.example/"}],
                "provenance": {"run_id": f"run:{target}:001", "observed_at": RECORDED},
                "recorded_at": RECORDED,
            })
            self.assertEqual("SAVED", result.status)
            self.assertTrue(self.memory.get_current(target, capability)["accepted_claim_ids"])
            self.assertEqual("ALREADY_EXISTS", self.finalize({
                "target": target,
                "capability": capability,
                "observations": [{"family": "transport", "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"}}],
                "evidence": [{"kind": "direct-read-validation", "locator": f"https://{target}.example/"}],
                "provenance": {"run_id": f"run:{target}:002", "observed_at": RECORDED},
                "recorded_at": RECORDED,
            }).status)

    def test_partial_knowledge_is_saved_and_rendered_without_operational_lifecycle(self):
        payload = self.operational_payload(observations=[
            {"family": "transport", "value": {"transport": "DIRECT_READ"}},
        ])
        self.assertEqual("SAVED", self.finalize(payload).status)
        context = self.memory.render_operational_context(
            payload["target"], payload["capability"]
        )
        self.assertIn("transport", context["current"])
        self.assertNotIn("lifecycle", context["current"])

    def test_incomplete_operational_proof_is_saved_without_lifecycle(self):
        payload = self.operational_payload(proof={
            "entrypoint": "https://synthetic-operational.example/items",
            "required_output": {"field_paths": {"name": "items[].name"}},
            "completion_condition": "the item collection is present",
        })
        self.assertEqual("SAVED", self.finalize(payload).status)
        self.assertFalse(self.memory.has_verified_operational_lifecycle(
            payload["target"], payload["capability"]
        ))

    def test_complete_verified_path_earns_generated_operational_lifecycle(self):
        payload = self.operational_payload()
        result = self.finalize(payload)
        self.assertEqual("SAVED", result.status)
        self.assertTrue(self.memory.has_verified_operational_lifecycle(
            payload["target"], payload["capability"]
        ))
        lifecycle = next(
            claim for claim in self.memory.get_current(
                payload["target"], payload["capability"]
            )["accepted_claims"]
            if claim["family"] == "lifecycle"
        )
        record = self.memory.get_record(lifecycle["id"])
        self.assertEqual("OPERATIONAL", record["value"])
        self.assertEqual(1, record["operational_proof"]["version"])
        self.assertEqual(3, len(record["operational_proof"]["claim_ids"]))
        self.assertNotIn("items[].name", json.dumps(record["operational_proof"]))

    def test_prior_accepted_facts_can_complete_a_later_operational_proof(self):
        first = self.operational_payload(observations=[
            {"family": "transport", "value": {"transport": "DIRECT_READ"}},
            {"family": "authentication", "value": {"access_model": "PUBLIC"}},
        ])
        self.assertEqual("SAVED", self.finalize(first).status)
        self.assertFalse(self.memory.has_verified_operational_lifecycle(
            first["target"], first["capability"]
        ))
        complete = self.operational_payload()
        complete["observations"] = [complete["observations"][2]]
        complete["provenance"]["run_id"] = "run:synthetic-operational:002"
        self.assertEqual("SAVED", self.finalize(complete).status)
        self.assertTrue(self.memory.has_verified_operational_lifecycle(
            first["target"], first["capability"]
        ))

    def test_incomplete_proof_can_be_completed_by_a_later_discovery(self):
        incomplete = self.operational_payload(
            target="synthetic-proof-completion",
            proof={
                "entrypoint": "https://synthetic-proof-completion.example/items",
                "required_output": {"field_paths": {"name": "items[].name"}},
                "completion_condition": "the item collection is present",
            },
        )
        self.assertEqual("SAVED", self.finalize(incomplete).status)
        complete = self.operational_payload(target="synthetic-proof-completion")
        complete["observations"] = [complete["observations"][2]]
        complete["provenance"]["run_id"] = "run:synthetic-proof-completion:002"
        self.assertEqual("SAVED", self.finalize(complete).status)
        self.assertTrue(self.memory.has_verified_operational_lifecycle(
            complete["target"], complete["capability"]
        ))

    def test_caller_supplied_lifecycle_cannot_self_promote(self):
        payload = self.operational_payload(observations=[
            {"family": "lifecycle", "value": {"state": "OPERATIONAL"}},
        ])
        with self.assertRaisesRegex(
            DiscoveryFinalizationError,
            "observation family is not reusable operational knowledge",
        ):
            self.finalize(payload)

    def test_non_success_outcomes_do_not_earn_operational_lifecycle(self):
        for outcome in ("FOUND", "FUNCTIONAL"):
            with self.subTest(outcome=outcome):
                target = f"synthetic-{outcome.lower()}"
                payload = self.operational_payload(target=target, outcome=outcome)
                self.assertEqual("SAVED", self.finalize(payload).status)
                self.assertFalse(self.memory.has_verified_operational_lifecycle(
                    target, payload["capability"]
                ))

    def test_success_without_explicit_evidence_stays_partial(self):
        payload = self.operational_payload(evidence_references=False)
        self.assertEqual("SAVED", self.finalize(payload).status)
        self.assertFalse(self.memory.has_verified_operational_lifecycle(
            payload["target"], payload["capability"]
        ))

    def test_required_output_choice_must_be_exactly_one(self):
        base = {
            "entrypoint": "https://synthetic-proof.example/items",
            "completion_condition": "the requested operation completed",
            "critical_constraints": [],
        }
        for suffix, proof in (
            ("neither", base),
            ("both", {**base, "required_output": {"field_paths": {"name": "items[].name"}}, "required_action": "submit"}),
        ):
            with self.subTest(case=suffix):
                payload = self.operational_payload(
                    target=f"synthetic-proof-{suffix}", proof=proof
                )
                self.assertEqual("SAVED", self.finalize(payload).status)
                self.assertFalse(self.memory.has_verified_operational_lifecycle(
                    payload["target"], payload["capability"]
                ))

    def test_degraded_proof_dependency_stops_rendering_operational_lifecycle(self):
        payload = self.operational_payload(target="synthetic-degraded")
        self.assertEqual("SAVED", self.finalize(payload).status)
        lifecycle = next(
            claim for claim in self.memory.get_current(
                payload["target"], payload["capability"]
            )["accepted_claims"]
            if claim["family"] == "lifecycle"
        )
        proof_claim_id = self.memory.get_record(lifecycle["id"])["operational_proof"]["claim_ids"][0]
        with self.memory.write_transaction() as writer:
            writer.decision({
                "id": "dec:synthetic-degraded:extract-items:degrade-proof",
                "target_id": "tgt:synthetic-degraded",
                "capability_id": "cap:synthetic-degraded:extract-items",
                "action": "DEGRADE",
                "claim_ids": [proof_claim_id],
                "effective_at": "2026-07-29T12:00:00Z",
                "recorded_at": "2026-07-29T12:00:00Z",
                "validity": {"valid_from": RECORDED, "valid_to": "2026-07-29T12:00:00Z"},
            })
        context = self.memory.render_operational_context(
            payload["target"], payload["capability"]
        )
        self.assertNotIn("lifecycle", context["current"])


if __name__ == "__main__":
    unittest.main()
