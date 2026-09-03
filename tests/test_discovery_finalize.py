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

import ast

from discovery_finalize import (
    EVIDENCE_LINKAGE, HOST_SCOPE, PAYLOAD_SHAPE, PAYLOAD_VALUE, PROVENANCE,
    TARGET_REFERENCE, TASK_DATA_REJECTED, TRANSPORT_TRACE,
    DiscoveryFinalizationError, finalize_discovery,
)
from discovery_runs import begin_discovery
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
                {"family": "transport", "value": {
                    "transport": "DIRECT_READ", "outcome": "FUNCTIONAL",
                }},
                {"family": "extraction", "value": {"structure": "JSON_LD"}},
            ],
            "evidence": [{"kind": "bounded-browser-validation", "locator": "https://www.example-news.com/busca/"}],
            "provenance": {"run_id": "run:example-news:001", "observed_at": RECORDED},
            "recorded_at": RECORDED,
        }

    def finalize(self, payload=None, *, dry_run=False):
        payload = payload or self.payload()
        arguments = {
            "target": payload["target"], "capability": payload["capability"],
            "observations": payload["observations"], "evidence": payload["evidence"],
            "provenance": payload["provenance"], "recorded_at": payload["recorded_at"],
            "dry_run": dry_run,
        }
        if "transport_trace" in payload:
            arguments["transport_trace"] = payload["transport_trace"]
        return finalize_discovery(self.memory, **arguments)

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

    def open_payload(self, payload):
        if isinstance(payload, Path):
            payload = json.loads(payload.read_text(encoding="utf-8"))
        return begin_discovery(
            self.root, payload["target"], payload["capability"],
            run_id=payload["provenance"]["run_id"], opened_at=RECORDED,
        )

    @staticmethod
    def transport_trace(*attempts, lightpanda="AVAILABLE", chrome="AVAILABLE"):
        return {
            "availability": {"LIGHTPANDA": lightpanda, "CHROME": chrome},
            "attempts": [
                {"transport": transport, "outcome": outcome, "evidence": [locator]}
                for transport, outcome, locator in attempts
            ],
        }

    @staticmethod
    def observing_validation(locator, transport="DIRECT_READ", outcome="OBSERVED"):
        """The validation an OBSERVED blocking/limitation claim must carry."""
        return {
            "transport": transport, "outcome": outcome,
            "engine": None if transport == "DIRECT_READ" else transport.lower(),
            "javascript": transport != "DIRECT_READ",
            "context": {"authentication": "PUBLIC", "environment": "PRODUCTION"},
            "evidence": [locator],
        }

    @staticmethod
    def transport_observation(transport, outcome, locator):
        return {
            "family": "transport",
            "value": {"transport": transport, "outcome": outcome},
            "validation": {
                "transport": transport,
                "outcome": outcome,
                "engine": None if transport == "DIRECT_READ" else transport.lower(),
                "javascript": transport != "DIRECT_READ",
                "context": {
                    "authentication": "PUBLIC", "environment": "PRODUCTION",
                },
                "evidence": [locator],
            },
        }

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
                {"family": "transport", "value": {
                    "transport": "DIRECT_READ", "outcome": "FUNCTIONAL",
                }},
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
        self.assertTrue(created.closes_run)
        self.assertEqual(2, len(self.memory.get_current("example-news", "topic-search")["accepted_claim_ids"]))
        repeated = self.finalize()
        self.assertEqual("ALREADY_EXISTS", repeated.status)
        self.assertTrue(repeated.closes_run)
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
        self.assertEqual("NO_REUSABLE_KNOWLEDGE", result.reason_code)
        self.assertTrue(result.closes_run)
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

    def test_new_scope_is_not_created_without_a_real_write_authority_marker(self):
        # Authority is derived solely from the real marker at
        # memory.knowledge_root -- there is no caller-supplied flag left to
        # assert or bypass it, so the fail-closed proof removes the marker
        # entirely rather than passing a fake "no authority" argument.
        payload = {
            "target": "example-portal", "capability": "world_section_access", "recorded_at": RECORDED,
            "provenance": {"run_id": "run:example-portal:world:001", "observed_at": RECORDED},
            "evidence": [{"kind": "direct-read-validation", "locator": "https://www.example-portal.com/mundo/"}],
            "observations": [{"family": "transport", "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"}}],
        }
        write_authority_path = self.root / ".caravelaweb/write-authority.json"
        original = write_authority_path.read_bytes()
        write_authority_path.unlink()
        try:
            with self.assertRaises(WriteAuthorityStateError):
                finalize_discovery(
                    self.memory, target=payload["target"], capability=payload["capability"],
                    observations=payload["observations"], evidence=payload["evidence"],
                    provenance=payload["provenance"], recorded_at=payload["recorded_at"],
                )
        finally:
            write_authority_path.write_bytes(original)
        self.assertIsNone(self.memory._conn.execute("SELECT 1 FROM targets WHERE id='tgt:example-portal'").fetchone())
        # The restored ACTIVE marker grants write authority again.
        self.assertEqual("SAVED", self.finalize(payload).status)

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
        self.open_payload(payload)
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

    def test_cli_blocked_capability_is_reusable_by_the_next_lookup(self):
        # The next run must find the recorded block and reuse the stop instead
        # of walking the same blocked ladder again.
        (self.root / ".caravelaweb/read-authority-operational-memory").write_text(
            "active", encoding="utf-8"
        )
        payload = self.root / "blocked-discovery.json"
        payload.write_text(json.dumps(self.blocked_ladder_payload()), encoding="utf-8")
        self.open_payload(payload)
        finalized = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root),
             "--input", str(payload)],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(0, finalized.returncode, finalized.stderr)
        self.assertEqual("SAVED", json.loads(finalized.stdout)["status"])
        lookup = subprocess.run(
            [sys.executable, str(LOOKUP), "--knowledge-root", str(self.root),
             "--target", "example-news", "--capability", "topic-search"],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(0, lookup.returncode, lookup.stderr)
        body = json.loads(lookup.stdout)
        self.assertEqual("found", body["status"])
        current = body["operational_context"]["current"]
        self.assertNotIn("lifecycle", current)
        self.assertIn("SITE_BLOCKING", json.dumps(current))
        self.assertIn("CHROME", json.dumps(current))

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
        self.open_payload(payload)
        before = tuple(self.memory._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("claims", "proposals"))
        result = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root), "--input", str(payload)],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(2, result.returncode)
        body = json.loads(result.stderr)
        self.assertEqual("NOT_SAVED", body["status"])
        self.assertEqual("PAYLOAD_VALUE", body["reason_code"])
        self.assertIn("not a reusable operational family", body["reason"])
        self.assertIn("transport", body["reason"])
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
        self.open_payload(payload)
        before = tuple(self.memory._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("claims", "proposals"))
        result = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root), "--input", str(payload)],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(2, result.returncode)
        body = json.loads(result.stderr)
        self.assertEqual("NOT_SAVED", body["status"])
        self.assertEqual("PAYLOAD_VALUE", body["reason_code"])
        self.assertIn("'prices'", body["reason"])
        self.assertIn("not a reusable operational family", body["reason"])
        self.assertIn("transport", body["reason"])
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
        self.open_payload(payload)
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
        self.open_payload(payload)
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
        # Root resolution (env var, then the fixed per-user default) must not
        # depend on the caller's cwd. It does NOT default to this repository
        # checkout -- H2 deliberately made a fresh clone unable to
        # auto-identify itself as a Knowledge Root, so the expectation here is
        # computed the same way the script computes it, not hardcoded to REPO
        # or to any particular resolved value.
        expected = resolve_knowledge_root(None)
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
        self.open_payload(payload)
        result = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root), "--input", str(payload)],
            cwd=consumer, text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("NOT_SAVED", json.loads(result.stdout)["status"])

    def test_missing_evidence_and_task_data_fail_closed(self):
        # Caller-asserted "wrong authority" is no longer a reachable case --
        # see test_new_scope_is_not_created_without_a_real_write_authority_marker
        # for the real-marker fail-closed proof.
        payload = self.payload()
        with self.assertRaises(DiscoveryFinalizationError):
            self.finalize({**payload, "evidence": []})
        with self.assertRaises(DiscoveryFinalizationError):
            self.finalize({**payload, "observations": [{"family": "extraction", "value": {"titles": ["not reusable"]}}]})

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
        locator = "https://www.example-news.com/busca/"
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
            }, "validation": self.observing_validation(locator)},
            {"family": "limitation", "value": {
                "kind": "FIELD_UNAVAILABLE", "constraint": "public pages omit private fields",
            }, "validation": self.observing_validation(locator)},
        ]
        result = self.finalize(self.payload(observations))
        self.assertEqual("SAVED", result.status)
        current = self.memory.get_current("example-news", "topic-search")
        self.assertEqual(7, len(current["accepted_claims"]))

    def test_transport_escalation_is_not_a_transport_conflict(self):
        locator = "https://www.example-news.com/search"
        payload = self.payload([
            self.transport_observation("DIRECT_READ", "FAILED", locator),
            self.transport_observation("LIGHTPANDA", "INSUFFICIENT", locator),
            self.transport_observation("CHROME", "FUNCTIONAL", locator),
        ])
        payload["evidence"] = [{
            "kind": "transport-validation", "locator": locator,
        }]
        payload["transport_trace"] = self.transport_trace(
            ("DIRECT_READ", "FAILED", locator),
            ("LIGHTPANDA", "INSUFFICIENT", locator),
            ("CHROME", "FUNCTIONAL", locator),
        )
        result = self.finalize(payload)
        self.assertEqual("SAVED", result.status)
        self.assertEqual(
            {"DIRECT_READ", "LIGHTPANDA", "CHROME"},
            {
                claim["value"]["transport"]
                for claim in self.memory.get_current(
                    "example-news", "topic-search"
                )["accepted_claims"]
            },
        )
        persisted = "\n".join(
            row[0]
            for table in (
                "claims", "proposals", "decisions", "validations",
                "observations", "evidence",
            )
            for row in self.memory._conn.execute(f"SELECT payload_json FROM {table}")
        )
        self.assertNotIn("transport_trace", persisted)
        self.assertNotIn("availability", persisted)

    def blocked_ladder_payload(self, locator="https://www.example-news.com/search"):
        """The Reuters shape: every transport in the ladder was blocked."""
        payload = self.payload([
            self.transport_observation("DIRECT_READ", "FAILED", locator),
            self.transport_observation("LIGHTPANDA", "FAILED", locator),
            self.transport_observation("CHROME", "FAILED", locator),
            {"family": "blocking", "value": {
                "failure_class": "SITE_BLOCKING",
                "signal": "INTERACTIVE_CHALLENGE",
                "condition": "a human-verification challenge replaces the page",
            }, "validation": self.observing_validation(
                locator, transport="CHROME", outcome="FAILED")},
        ])
        payload["evidence"] = [{"kind": "transport-validation", "locator": locator}]
        payload["transport_trace"] = self.transport_trace(
            ("DIRECT_READ", "FAILED", locator),
            ("LIGHTPANDA", "FAILED", locator),
            ("CHROME", "FAILED", locator),
        )
        return payload

    def test_fully_blocked_ladder_is_saved_with_its_transport_evidence(self):
        # An exhausted ladder proves the capability is blocked. Rejecting it
        # left the agent no way to record the block except by deleting the
        # browser evidence that proved it.
        result = self.finalize(self.blocked_ladder_payload())
        self.assertEqual("SAVED", result.status)
        claims = self.memory.get_current("example-news", "topic-search")["accepted_claims"]
        self.assertEqual(
            {"DIRECT_READ", "LIGHTPANDA", "CHROME"},
            {claim["value"]["transport"] for claim in claims if claim["family"] == "transport"},
        )
        self.assertEqual(
            ["SITE_BLOCKING"],
            [claim["value"]["failure_class"] for claim in claims if claim["family"] == "blocking"],
        )
        self.assertFalse(self.memory.has_verified_operational_lifecycle(
            "example-news", "topic-search"
        ))

    def test_a_blocked_chrome_ladder_saves_but_earns_no_operational_lifecycle(self):
        # One variable against test_complete_chrome_ladder_can_earn_operational
        # _lifecycle: the CHROME attempt is FAILED rather than FUNCTIONAL. The
        # proof, the authentication fact, and the evidence are identical.
        #
        # The refusal is over-determined, and deliberately so: a blocked ladder
        # has no FUNCTIONAL transport claim *and* its trace selects no
        # transport. Those are one fact seen twice, not two gates, so this
        # asserts the outcome rather than pretending to isolate a branch.
        target = "synthetic-chrome-blocked"
        locator = f"https://{target}.example/items"
        payload = self.operational_payload(target=target)
        proof = payload["observations"][2]
        proof["validation"].update({
            "transport": "CHROME", "engine": "chromium", "javascript": True,
        })
        payload["observations"] = [
            self.transport_observation("DIRECT_READ", "FAILED", locator),
            self.transport_observation("LIGHTPANDA", "INSUFFICIENT", locator),
            self.transport_observation("CHROME", "FAILED", locator),
            payload["observations"][1],
            proof,
            {"family": "blocking",
             "value": {"failure_class": "SITE_BLOCKING",
                       "condition": "a human-verification challenge replaces the page"},
             "validation": self.observing_validation(
                 locator, transport="CHROME", outcome="FAILED")},
        ]
        payload["transport_trace"] = self.transport_trace(
            ("DIRECT_READ", "FAILED", locator),
            ("LIGHTPANDA", "INSUFFICIENT", locator),
            ("CHROME", "FAILED", locator),
        )
        result = self.finalize(payload)
        self.assertEqual("SAVED", result.status)
        self.assertFalse(self.memory.has_verified_operational_lifecycle(
            target, payload["capability"]
        ))
        self.assertEqual(
            ["SITE_BLOCKING"],
            [
                claim["value"]["failure_class"]
                for claim in self.memory.get_current(target, payload["capability"])[
                    "accepted_claims"
                ]
                if claim["family"] == "blocking"
            ],
        )

    def test_a_ladder_stopped_before_exhaustion_stays_unproven(self):
        # Only DIRECT_READ was attempted while Lightpanda was available, so the
        # run proves neither a working path nor a blocked one.
        locator = "https://www.example-news.com/search"
        payload = self.payload([
            self.transport_observation("DIRECT_READ", "FAILED", locator),
        ])
        payload["evidence"] = [{"kind": "transport-validation", "locator": locator}]
        payload["transport_trace"] = self.transport_trace(
            ("DIRECT_READ", "FAILED", locator)
        )
        result = self.finalize(payload)
        self.assertEqual("NOT_SAVED", result.status)
        self.assertEqual("TRANSPORT_POLICY_UNPROVEN", result.reason_code)
        self.assertFalse(result.closes_run)
        self.assertEqual("OPEN", result.as_dict()["run_state"])

    def exhausted_direct_read_payload(self, classified=True):
        """One attempt, no browser on this machine, so the ladder is exhausted."""
        locator = "https://www.example-news.com/search"
        observations = [self.transport_observation("DIRECT_READ", "FAILED", locator)]
        if classified:
            observations.append({
                "family": "blocking",
                "value": {"failure_class": "AUTH_REQUIRED",
                          "condition": "the route redirects to a sign-in page"},
                "validation": self.observing_validation(locator, outcome="FAILED"),
            })
        payload = self.payload(observations)
        payload["evidence"] = [{"kind": "transport-validation", "locator": locator}]
        payload["transport_trace"] = self.transport_trace(
            ("DIRECT_READ", "FAILED", locator),
            lightpanda="PLATFORM_UNSUPPORTED", chrome="PLATFORM_UNSUPPORTED",
        )
        return payload

    def test_exhausted_direct_read_only_ladder_is_saved(self):
        self.assertEqual(
            "SAVED", self.finalize(self.exhausted_direct_read_payload()).status
        )

    def test_a_failed_ladder_without_a_durable_class_is_not_saved(self):
        # `FAILED` alone does not say whether the target blocked this run or
        # the network dropped one request. Only the second is target knowledge.
        result = self.finalize(self.exhausted_direct_read_payload(classified=False))
        self.assertEqual("NOT_SAVED", result.status)
        self.assertEqual("FAILURE_UNCLASSIFIED", result.reason_code)
        self.assertFalse(result.closes_run)
        self.assertEqual("OPEN", result.as_dict()["run_state"])

    def test_runtime_failure_classes_never_become_target_knowledge(self):
        for failure_class in (
            "TRANSIENT_NETWORK", "UPSTREAM_TOOL_ERROR", "LOCAL_ENVIRONMENT", "UNKNOWN",
        ):
            with self.subTest(failure_class=failure_class):
                payload = self.exhausted_direct_read_payload(classified=False)
                payload["observations"][0]["validation"]["failure_class"] = failure_class
                result = self.finalize(payload)
                self.assertEqual("NOT_SAVED", result.status)
                self.assertEqual("FAILURE_UNCLASSIFIED", result.reason_code)
        # PLATFORM_UNSUPPORTED never reaches that gate: an absent engine is
        # machine state, and the payload validator rejects it outright.
        payload = self.exhausted_direct_read_payload(classified=False)
        payload["observations"][0]["validation"]["failure_class"] = "PLATFORM_UNSUPPORTED"
        with self.assertRaises(DiscoveryFinalizationError):
            self.finalize(payload)

    def test_an_available_transport_left_untried_is_not_an_exhausted_ladder(self):
        # `next_transport` halts at an UNAVAILABLE Lightpanda tier even when
        # Chrome exists. Reaching that halt is not proof the target is blocked.
        locator = "https://www.example-news.com/search"
        payload = self.payload([
            self.transport_observation("DIRECT_READ", "FAILED", locator),
            {"family": "blocking",
             "value": {"failure_class": "SITE_BLOCKING"},
             "validation": self.observing_validation(locator, outcome="FAILED")},
        ])
        payload["evidence"] = [{"kind": "transport-validation", "locator": locator}]
        payload["transport_trace"] = self.transport_trace(
            ("DIRECT_READ", "FAILED", locator),
            lightpanda="UNAVAILABLE", chrome="AVAILABLE",
        )
        result = self.finalize(payload)
        self.assertEqual("NOT_SAVED", result.status)
        self.assertEqual("TRANSPORT_POLICY_UNPROVEN", result.reason_code)

    def test_an_empty_validation_object_does_not_satisfy_the_constraint_rule(self):
        # Every validation field is optional, so `{}` normalizes cleanly and
        # would otherwise pass a presence-only check.
        locator = "https://www.example-news.com/busca/"
        for validation in (
            {},
            {"outcome": "OBSERVED"},
            {"transport": "DIRECT_READ"},
            {"transport": "DIRECT_READ", "context": {"authentication": "PUBLIC"}},
            {"context": {"authentication": "PUBLIC", "environment": "PRODUCTION"}},
        ):
            with self.subTest(validation=validation), self.assertRaises(DiscoveryFinalizationError):
                self.finalize(self.payload([{
                    "family": "blocking",
                    "value": {"failure_class": "SITE_BLOCKING"},
                    "validation": validation,
                }]))
        self.assertEqual("SAVED", self.finalize(self.payload([{
            "family": "blocking",
            "value": {"failure_class": "AUTH_REQUIRED"},
            "validation": self.observing_validation(locator, outcome="FAILED"),
        }])).status)

    def test_observed_constraint_validation_requires_explicit_engine_and_javascript(self):
        locator = "https://www.example-news.com/busca/"
        direct_read = self.observing_validation(locator, outcome="FAILED")
        self.assertEqual("SAVED", self.finalize(self.payload([{
            "family": "blocking", "value": {"failure_class": "AUTH_REQUIRED"},
            "validation": direct_read,
        }])).status)
        for validation in (
            {key: value for key, value in direct_read.items() if key != "engine"},
            {key: value for key, value in direct_read.items() if key != "javascript"},
            {
                "transport": "CHROME", "outcome": "FAILED",
                "context": {"authentication": "PUBLIC", "environment": "PRODUCTION"},
                "evidence": [locator],
            },
        ):
            with self.subTest(validation=validation), self.assertRaises(DiscoveryFinalizationError):
                self.finalize(self.payload([{
                    "family": "blocking", "value": {"failure_class": "SITE_BLOCKING"},
                    "validation": validation,
                }]))

    def test_removing_a_validation_never_rescues_a_rejected_payload(self):
        # The failure that produced this gate: a rejected payload became
        # acceptable by deleting the evidence the finalizer refused to accept.
        locator = "https://www.example-news.com/search"
        rejected = self.blocked_ladder_payload(locator)
        del rejected["transport_trace"]
        result = self.finalize(rejected)
        self.assertEqual("NOT_SAVED", result.status)
        self.assertEqual("TRANSPORT_POLICY_UNPROVEN", result.reason_code)
        self.assertIn("Never drop an observation", result.reason)
        stripped = self.payload([{
            "family": "blocking",
            "value": rejected["observations"][-1]["value"],
        }])
        stripped["evidence"] = rejected["evidence"]
        with self.assertRaises(DiscoveryFinalizationError):
            self.finalize(stripped)

    def test_observed_constraint_requires_the_validation_that_observed_it(self):
        # `blocking` and `limitation` assert a constraint or an absence. An
        # unvalidated one may still be reported, but never as OBSERVED fact.
        locator = "https://www.example-news.com/busca/"
        for family, value in (
            ("blocking", {"failure_class": "SITE_BLOCKING"}),
            ("limitation", {"kind": "FIELD_UNAVAILABLE"}),
        ):
            with self.subTest(family=family, epistemic="OBSERVED"):
                with self.assertRaises(DiscoveryFinalizationError):
                    self.finalize(self.payload([{"family": family, "value": value}]))
            with self.subTest(family=family, epistemic="INFERRED"):
                result = self.finalize(self.payload([
                    {"family": family, "epistemic": "INFERRED", "value": value},
                ]))
                self.assertEqual("NOT_SAVED", result.status)
                self.assertEqual("INFERENCE_ONLY", result.reason_code)
            with self.subTest(family=family, validated=True):
                payload = self.payload([{
                    "family": family, "value": dict(value, condition="observed once"),
                    "validation": self.observing_validation(locator),
                }])
                payload["capability"] = f"{family}-scope"
                self.assertEqual("SAVED", self.finalize(payload).status)

    def test_available_lightpanda_cannot_be_skipped_before_chrome(self):
        locator = "https://www.example-news.com/search"
        payload = self.payload([
            self.transport_observation("DIRECT_READ", "FAILED", locator),
            self.transport_observation("CHROME", "FUNCTIONAL", locator),
        ])
        payload["evidence"] = [{
            "kind": "transport-validation", "locator": locator,
        }]
        payload["transport_trace"] = self.transport_trace(
            ("DIRECT_READ", "FAILED", locator),
            ("CHROME", "FUNCTIONAL", locator),
        )
        before = tuple(
            self.memory._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("claims", "proposals", "decisions", "evidence")
        )
        result = self.finalize(payload)
        self.assertEqual("NOT_SAVED", result.status)
        self.assertEqual("TRANSPORT_POLICY_UNPROVEN", result.reason_code)
        self.assertEqual(before, tuple(
            self.memory._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("claims", "proposals", "decisions", "evidence")
        ))

    def test_unavailable_lightpanda_does_not_authorize_chrome(self):
        locator = "https://www.example-news.com/search"
        payload = self.payload([
            self.transport_observation("DIRECT_READ", "INSUFFICIENT", locator),
            self.transport_observation("CHROME", "FUNCTIONAL", locator),
        ])
        payload["evidence"] = [{
            "kind": "transport-validation", "locator": locator,
        }]
        payload["transport_trace"] = self.transport_trace(
            ("DIRECT_READ", "INSUFFICIENT", locator),
            ("CHROME", "FUNCTIONAL", locator),
            lightpanda="UNAVAILABLE",
        )
        before = tuple(
            self.memory._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("claims", "proposals", "decisions", "evidence")
        )
        result = self.finalize(payload)
        self.assertEqual("NOT_SAVED", result.status)
        self.assertEqual("TRANSPORT_POLICY_UNPROVEN", result.reason_code)
        self.assertEqual(before, tuple(
            self.memory._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("claims", "proposals", "decisions", "evidence")
        ))

    def test_unproven_replacement_is_never_automatically_promoted(self):
        # An operational proof is exempt from the family conflict gate, so only
        # the contradiction gate keeps an unproven replacement out of the
        # accepted view.
        target, capability = "synthetic-unproven-replacement", "extract-items"
        locator = f"https://{target}.example/items"
        old_proof = {
            "entrypoint": locator,
            "required_action": "open the item list",
            "completion_condition": "the item collection is present",
            "critical_constraints": [],
        }
        new_proof = {**old_proof, "entrypoint": f"{locator}/v2"}
        context = {"authentication": "PUBLIC", "environment": "PRODUCTION"}

        def validation(outcome, evidence, **extra):
            return {
                "transport": "DIRECT_READ", "outcome": outcome, "engine": None,
                "javascript": False, "context": context,
                "evidence": [evidence], **extra,
            }

        first = {
            "target": target, "capability": capability,
            "observations": [
                {"family": "transport", "value": {
                    "transport": "DIRECT_READ", "outcome": "FUNCTIONAL",
                }},
                {"family": "authentication", "value": {"access_model": "PUBLIC"}},
                {
                    "family": "validation",
                    "value": {"operational_proof": old_proof},
                    "validation": validation("FUNCTIONAL", locator),
                },
            ],
            "evidence": [{"kind": "synthetic-validation", "locator": locator}],
            "provenance": {"run_id": f"run:{target}:001", "observed_at": RECORDED},
            "recorded_at": RECORDED,
        }
        self.assertEqual("SAVED", self.finalize(first).status)
        accepted = set(self.memory.get_current(target, capability)["accepted_claim_ids"])

        # A second unrelated new Claim keeps the delta above the single-Claim
        # replacement path, so no replacement Decision can prove the change.
        second = {
            "target": target, "capability": capability,
            "observations": [
                {
                    "family": "validation",
                    "value": {"operational_proof": new_proof},
                    "validation": validation("FUNCTIONAL", f"{locator}/new"),
                    "contradiction": {
                        "prior_value": {"operational_proof": old_proof},
                        "validation": validation(
                            "FAILED", f"{locator}/old",
                            failure_class="TARGET_CHANGED",
                        ),
                    },
                },
                {"family": "search_surface", "value": {"surface": "OFFICIAL_SEARCH"}},
            ],
            "evidence": [
                {"kind": "synthetic-validation", "locator": f"{locator}/new"},
                {"kind": "synthetic-validation", "locator": f"{locator}/old"},
            ],
            "provenance": {"run_id": f"run:{target}:002", "observed_at": RECORDED},
            "recorded_at": RECORDED,
        }
        result = self.finalize(second)
        self.assertEqual("NOT_SAVED", result.status)
        self.assertEqual("REPLACEMENT_UNPROVEN", result.reason_code)
        self.assertEqual(accepted, set(
            self.memory.get_current(target, capability)["accepted_claim_ids"]
        ))
        self.assertFalse(self.memory.has_verified_operational_lifecycle(
            target, capability
        ))

    def test_same_transport_incompatible_outcomes_remain_conflicting(self):
        result = self.finalize(self.payload([
            {"family": "transport", "value": {
                "transport": "DIRECT_READ", "outcome": "FAILED",
            }},
            {"family": "transport", "value": {
                "transport": "DIRECT_READ", "outcome": "FUNCTIONAL",
            }},
        ]))
        self.assertEqual("NOT_SAVED", result.status)
        self.assertEqual("CONFLICT_OR_AMBIGUITY", result.reason_code)

    def test_exact_multi_claim_pending_escalation_can_be_retried(self):
        direct_id = "clm:example-news:topic-search:pending-direct"
        chrome_id = "clm:example-news:topic-search:pending-chrome"
        proposal_id = "prop:example-news:topic-search:pending-escalation"
        with self.memory.write_transaction() as writer:
            for claim_id, transport, outcome in (
                (direct_id, "DIRECT_READ", "FAILED"),
                (chrome_id, "CHROME", "FUNCTIONAL"),
            ):
                writer.claim({
                    "id": claim_id,
                    "target_id": "tgt:example-news",
                    "capability_id": "cap:example-news:topic-search",
                    "family": "transport",
                    "epistemic": "OBSERVED",
                    "value": {"transport": transport, "outcome": outcome},
                    "proposal_id": proposal_id,
                    "recorded_at": RECORDED,
                })
            writer.proposal({
                "id": proposal_id,
                "target_id": "tgt:example-news",
                "capability_id": "cap:example-news:topic-search",
                "recorded_at": RECORDED,
                "claim_ids": [direct_id, chrome_id],
            })
        before = {
            table: self.memory._conn.execute(
                f"SELECT count(*) FROM {table}"
            ).fetchone()[0]
            for table in ("claims", "proposals")
        }

        locator = "https://www.example-news.com/search"
        payload = self.payload([
            self.transport_observation("DIRECT_READ", "FAILED", locator),
            self.transport_observation("CHROME", "FUNCTIONAL", locator),
        ])
        payload["evidence"] = [{
            "kind": "transport-validation", "locator": locator,
        }]
        payload["transport_trace"] = self.transport_trace(
            ("DIRECT_READ", "FAILED", locator),
            ("CHROME", "FUNCTIONAL", locator),
            lightpanda="PLATFORM_UNSUPPORTED",
        )
        result = self.finalize(payload)
        self.assertEqual("SAVED", result.status)
        self.assertEqual([], self.memory.get_pending_candidates(
            "example-news", "topic-search"
        ))
        self.assertEqual(
            {direct_id, chrome_id},
            set(self.memory.get_current(
                "example-news", "topic-search"
            )["accepted_claim_ids"]),
        )
        self.assertEqual(before, {
            table: self.memory._conn.execute(
                f"SELECT count(*) FROM {table}"
            ).fetchone()[0]
            for table in before
        })

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

    def test_cli_accepts_run_scoped_transport_trace(self):
        locator = "https://www.example-news.com/search"
        payload = self.payload([
            self.transport_observation("DIRECT_READ", "FAILED", locator),
            self.transport_observation("CHROME", "FUNCTIONAL", locator),
        ])
        payload["evidence"] = [{
            "kind": "transport-validation", "locator": locator,
        }]
        payload["transport_trace"] = self.transport_trace(
            ("DIRECT_READ", "FAILED", locator),
            ("CHROME", "FUNCTIONAL", locator),
            lightpanda="PLATFORM_UNSUPPORTED",
        )
        self.open_payload(payload)
        result = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root)],
            input=json.dumps(payload), text=True, capture_output=True,
            encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("SAVED", json.loads(result.stdout)["status"])

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
            {"family": "transport", "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"}},
            {"family": "extraction", "value": {"structure": "JSON_LD"}},
            {"family": "paywall", "value": {"signal": "PAYWALL_MARKER"}},
            {"family": "limitation", "value": {"mode": "METADATA_ONLY"},
             "validation": self.observing_validation(
                 "https://www.example-news.com/busca/")},
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
                self.transport_observation(
                    "DIRECT_READ", "FAILED", "https://maps.example.com/"
                ),
                {**self.transport_observation(
                    "CHROME", "FUNCTIONAL", "https://maps.example.com/"
                ), "value": {
                    "transport": "CHROME", "outcome": "FUNCTIONAL",
                    "requirement": "BROWSER_REQUIRED",
                }},
                {"family": "search_surface", "value": {"surface": "RESULT_FEED", "loading": "PROGRESSIVE"}},
                {"family": "extraction", "value": {"structure": "RESULT_CARDS"}},
                {"family": "validation", "value": {"rule": "GEOGRAPHIC_MATCH"}},
            ]}
        payload["transport_trace"] = self.transport_trace(
            ("DIRECT_READ", "FAILED", "https://maps.example.com/"),
            ("CHROME", "FUNCTIONAL", "https://maps.example.com/"),
            lightpanda="PLATFORM_UNSUPPORTED",
        )
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

    def test_failed_transport_cannot_support_operational_lifecycle(self):
        payload = self.operational_payload(target="synthetic-failed-transport")
        payload["observations"][0]["value"]["outcome"] = "FAILED"
        result = self.finalize(payload)
        self.assertEqual("SAVED", result.status)
        self.assertFalse(self.memory.has_verified_operational_lifecycle(
            payload["target"], payload["capability"]
        ))

    def test_complete_chrome_ladder_can_earn_operational_lifecycle(self):
        target = "synthetic-chrome-operational"
        locator = f"https://{target}.example/items"
        payload = self.operational_payload(target=target)
        proof = payload["observations"][2]
        proof["validation"].update({
            "transport": "CHROME", "engine": "chromium", "javascript": True,
        })
        payload["observations"] = [
            self.transport_observation("DIRECT_READ", "FAILED", locator),
            self.transport_observation("LIGHTPANDA", "INSUFFICIENT", locator),
            self.transport_observation("CHROME", "FUNCTIONAL", locator),
            payload["observations"][1],
            proof,
        ]
        payload["transport_trace"] = self.transport_trace(
            ("DIRECT_READ", "FAILED", locator),
            ("LIGHTPANDA", "INSUFFICIENT", locator),
            ("CHROME", "FUNCTIONAL", locator),
        )
        result = self.finalize(payload)
        self.assertEqual("SAVED", result.status)
        self.assertTrue(self.memory.has_verified_operational_lifecycle(
            target, payload["capability"]
        ))
        lifecycle = next(
            claim for claim in self.memory.get_current(
                target, payload["capability"]
            )["accepted_claims"]
            if claim["family"] == "lifecycle"
        )
        dependencies = [
            self.memory.get_record(claim_id)
            for claim_id in self.memory.get_record(
                lifecycle["id"]
            )["operational_proof"]["claim_ids"]
        ]
        self.assertEqual(
            [{"outcome": "FUNCTIONAL", "transport": "CHROME"}],
            [item["value"] for item in dependencies if item["family"] == "transport"],
        )

    def test_legacy_chrome_claim_cannot_be_promoted_by_proof_alone(self):
        target = "legacy-chrome"
        capability = "extract-items"
        with self.memory.write_transaction() as writer:
            writer.target({"id": f"tgt:{target}"})
            writer.capability({
                "id": f"cap:{target}:{capability}",
                "target_id": f"tgt:{target}",
                "key": capability,
            })
            for suffix, family, value in (
                ("transport", "transport", {
                    "transport": "CHROME", "outcome": "FUNCTIONAL",
                }),
                ("authentication", "authentication", {"access_model": "PUBLIC"}),
            ):
                claim_id = f"clm:{target}:{capability}:{suffix}"
                writer.claim({
                    "id": claim_id,
                    "target_id": f"tgt:{target}",
                    "capability_id": f"cap:{target}:{capability}",
                    "family": family,
                    "epistemic": "OBSERVED",
                    "value": value,
                    "recorded_at": RECORDED,
                })
                writer.decision({
                    "id": f"dec:{target}:{capability}:{suffix}",
                    "target_id": f"tgt:{target}",
                    "capability_id": f"cap:{target}:{capability}",
                    "action": "ACCEPT",
                    "claim_ids": [claim_id],
                    "effective_at": RECORDED,
                    "recorded_at": RECORDED,
                    "validity": {"valid_from": RECORDED, "valid_to": None},
                })

        payload = self.operational_payload(target=target)
        payload["observations"] = [payload["observations"][2]]
        payload["observations"][0]["validation"].update({
            "transport": "CHROME", "engine": "chromium", "javascript": True,
        })
        result = self.finalize(payload)
        self.assertEqual("NOT_SAVED", result.status)
        self.assertEqual("TRANSPORT_POLICY_UNPROVEN", result.reason_code)
        self.assertFalse(self.memory.has_verified_operational_lifecycle(
            target, capability
        ))

    def test_prior_accepted_facts_can_complete_a_later_operational_proof(self):
        first = self.operational_payload(observations=[
            {"family": "transport", "value": {
                "transport": "DIRECT_READ", "outcome": "FUNCTIONAL",
            }},
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
            "is not a reusable operational family",
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


    def test_cli_reports_run_state_closed_for_saved_and_open_for_unproven(self):
        payload = self.root / "unproven-discovery.json"
        locator = "https://www.example-news.com/search"
        body = self.payload([self.transport_observation("DIRECT_READ", "FAILED", locator)])
        body["evidence"] = [{"kind": "transport-validation", "locator": locator}]
        body["transport_trace"] = self.transport_trace(("DIRECT_READ", "FAILED", locator))
        payload.write_text(json.dumps(body), encoding="utf-8")
        self.open_payload(payload)
        result = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root), "--input", str(payload)],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        stdout = json.loads(result.stdout)
        self.assertEqual("NOT_SAVED", stdout["status"])
        self.assertEqual("TRANSPORT_POLICY_UNPROVEN", stdout["reason_code"])
        self.assertEqual("OPEN", stdout["run_state"])
        from discovery_runs import list_open_discoveries
        self.assertEqual(1, len(list_open_discoveries(self.root)))
        # A corrected payload under the same run_id can retry immediately.
        fixed = self.payload()
        fixed["provenance"]["run_id"] = body["provenance"]["run_id"]
        payload.write_text(json.dumps(fixed), encoding="utf-8")
        retried = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root), "--input", str(payload)],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(0, retried.returncode, retried.stderr)
        retried_body = json.loads(retried.stdout)
        self.assertEqual("SAVED", retried_body["status"])
        self.assertEqual("CLOSED", retried_body["run_state"])
        self.assertEqual([], list_open_discoveries(self.root))

    def test_cli_saved_result_reports_run_state_closed(self):
        payload = self.root / "saved-discovery.json"
        body = self.payload()
        payload.write_text(json.dumps(body), encoding="utf-8")
        self.open_payload(payload)
        result = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root), "--input", str(payload)],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("CLOSED", json.loads(result.stdout)["run_state"])

    def test_schema_error_reports_run_state_open(self):
        payload = self.root / "schema-invalid.json"
        payload.write_text(json.dumps({"target": "example-news", "capability": "topic-search"}), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root), "--input", str(payload)],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(2, result.returncode)
        self.assertEqual("OPEN", json.loads(result.stderr)["run_state"])

    def test_validate_predicts_saved_without_persisting(self):
        payload = self.root / "validate-discovery.json"
        body = self.payload()
        payload.write_text(json.dumps(body), encoding="utf-8")
        self.open_payload(payload)
        before_rows = {
            table: self.memory._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("claims", "proposals", "decisions", "evidence", "hosts")
        }
        from discovery_runs import list_open_discoveries
        markers_before = list_open_discoveries(self.root)
        result = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root),
             "--validate", "--input", str(payload)],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        stdout = json.loads(result.stdout)
        self.assertEqual(
            {"status": "VALID", "would_finalize_as": "SAVED", "would_reason_code": None, "run_state": "OPEN"},
            stdout,
        )
        after_rows = {
            table: self.memory._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("claims", "proposals", "decisions", "evidence", "hosts")
        }
        self.assertEqual(before_rows, after_rows)
        self.assertEqual(markers_before, list_open_discoveries(self.root))
        # Real finalization after validation still succeeds.
        real = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root), "--input", str(payload)],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(0, real.returncode, real.stderr)
        self.assertEqual("SAVED", json.loads(real.stdout)["status"])

    def test_validate_predicts_early_no_write_result_without_closing_marker(self):
        payload = self.root / "validate-empty.json"
        body = {
            "target": "new-target", "capability": "new-capability",
            "observations": [], "evidence": [],
            "provenance": {"run_id": "run:validate-empty:001", "observed_at": RECORDED},
            "recorded_at": RECORDED,
        }
        payload.write_text(json.dumps(body), encoding="utf-8")
        self.open_payload(payload)
        result = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root),
             "--validate", "--input", str(payload)],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({
            "status": "VALID", "would_finalize_as": "NOT_SAVED",
            "would_reason_code": "NO_REUSABLE_KNOWLEDGE", "run_state": "OPEN",
        }, json.loads(result.stdout))
        from discovery_runs import list_open_discoveries
        self.assertEqual(1, len(list_open_discoveries(self.root)))

    def test_dollar_root_field_path_is_accepted(self):
        payload = self.payload([
            {"family": "transport", "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"}},
            {"family": "extraction", "value": {
                "field_paths": {"headline": "$.headline", "body": "$.article.full_text"},
            }},
        ])
        self.assertEqual("SAVED", self.finalize(payload).status)

    def test_bare_field_name_is_rejected_with_explicit_root_hint(self):
        payload = self.payload([
            {"family": "transport", "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"}},
            {"family": "extraction", "value": {"field_paths": {"headline": "headline"}}},
        ])
        with self.assertRaises(DiscoveryFinalizationError) as ctx:
            self.finalize(payload)
        self.assertIn("$.headline", str(ctx.exception))

    def test_symbolic_value_error_explains_the_grammar(self):
        payload = self.payload([
            {"family": "transport", "value": {"transport": "not a symbol!", "outcome": "FUNCTIONAL"}},
        ])
        with self.assertRaises(DiscoveryFinalizationError) as ctx:
            self.finalize(payload)
        self.assertIn("SITE_BLOCKING", str(ctx.exception))
        self.assertIn("letters, digits", str(ctx.exception))

    def test_validation_context_error_lists_accepted_keys(self):
        payload = self.payload([
            {
                "family": "blocking",
                "value": {"failure_class": "SITE_BLOCKING"},
                "validation": {"bogus_key": "value"},
            },
        ])
        with self.assertRaises(DiscoveryFinalizationError) as ctx:
            self.finalize(payload)
        message = str(ctx.exception)
        self.assertIn("bogus_key", message)
        self.assertIn("transport", message)
        self.assertIn("evidence", message)

    def test_host_mismatch_error_reports_claimed_and_evidence_hosts(self):
        payload = self.payload([
            {"family": "transport", "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"},
             "host": "other.example-news.com"},
        ])
        with self.assertRaises(DiscoveryFinalizationError) as ctx:
            self.finalize(payload)
        message = str(ctx.exception)
        self.assertIn("other.example-news.com", message)
        self.assertIn("TARGET_SURFACE", message)
        self.assertIn("www.example-news.com", message)

    def test_validate_rolls_back_new_target_capability_and_host_association(self):
        # Covers the create_missing_scope=True capture_candidate path: a brand
        # new target, capability, and host all get created inside the same
        # rolled-back transaction. Compares every durable table plus the
        # discovery marker and write-authority bytes on disk, not just row
        # counts, so a dry-run leak in any one of them would be caught.
        payload_path = self.root / "validate-host-discovery.json"
        body = {
            "target": "example-validate-host", "capability": "article-read",
            "observations": [{
                "family": "transport",
                "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"},
                "host": "www.example-validate-host.example",
            }],
            "evidence": [{
                "kind": "direct-read-validation",
                "locator": "https://www.example-validate-host.example/articles/1",
                "scope": "TARGET_SURFACE",
            }],
            "provenance": {"run_id": "run:example-validate-host:001", "observed_at": RECORDED},
            "recorded_at": RECORDED,
        }
        payload_path.write_text(json.dumps(body), encoding="utf-8")
        self.open_payload(payload_path)

        db_before = self._table_snapshot()
        write_authority_path = self.root / ".caravelaweb/write-authority.json"
        write_authority_before = write_authority_path.read_bytes()
        marker_dir = self.root / ".caravelaweb/open-discovery"
        markers_before = {p.name: p.read_bytes() for p in marker_dir.iterdir()}

        validated = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root),
             "--validate", "--input", str(payload_path)],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(0, validated.returncode, validated.stderr)
        self.assertEqual(
            {"status": "VALID", "would_finalize_as": "SAVED",
             "would_reason_code": None, "run_state": "OPEN"},
            json.loads(validated.stdout),
        )
        self.assertEqual(db_before, self._table_snapshot())
        self.assertEqual(write_authority_before, write_authority_path.read_bytes())
        self.assertEqual(
            markers_before, {p.name: p.read_bytes() for p in marker_dir.iterdir()}
        )
        self.assertIsNone(self.memory._conn.execute(
            "SELECT 1 FROM targets WHERE id='tgt:example-validate-host'"
        ).fetchone())

        real = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root),
             "--input", str(payload_path)],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(0, real.returncode, real.stderr)
        real_body = json.loads(real.stdout)
        self.assertEqual("SAVED", real_body["status"])
        self.assertEqual("CLOSED", real_body["run_state"])
        self.assertIsNotNone(self.memory._conn.execute(
            "SELECT 1 FROM hosts WHERE hostname='www.example-validate-host.example'"
        ).fetchone())

    def test_validate_rolls_back_pending_candidate_enrichment(self):
        # Covers the enrich_candidate branch of write_transaction (pending
        # Candidate exists and the new delta matches it exactly), distinct
        # from the capture_candidate branch above.
        direct_id = "clm:example-news:topic-search:pending-direct"
        chrome_id = "clm:example-news:topic-search:pending-chrome"
        proposal_id = "prop:example-news:topic-search:pending-escalation"
        with self.memory.write_transaction() as writer:
            for claim_id, transport, outcome in (
                (direct_id, "DIRECT_READ", "FAILED"),
                (chrome_id, "CHROME", "FUNCTIONAL"),
            ):
                writer.claim({
                    "id": claim_id,
                    "target_id": "tgt:example-news",
                    "capability_id": "cap:example-news:topic-search",
                    "family": "transport",
                    "epistemic": "OBSERVED",
                    "value": {"transport": transport, "outcome": outcome},
                    "proposal_id": proposal_id,
                    "recorded_at": RECORDED,
                })
            writer.proposal({
                "id": proposal_id,
                "target_id": "tgt:example-news",
                "capability_id": "cap:example-news:topic-search",
                "recorded_at": RECORDED,
                "claim_ids": [direct_id, chrome_id],
            })
        before = self._table_snapshot()

        locator = "https://www.example-news.com/search"
        payload = self.payload([
            self.transport_observation("DIRECT_READ", "FAILED", locator),
            self.transport_observation("CHROME", "FUNCTIONAL", locator),
        ])
        payload["evidence"] = [{"kind": "transport-validation", "locator": locator}]
        payload["transport_trace"] = self.transport_trace(
            ("DIRECT_READ", "FAILED", locator),
            ("CHROME", "FUNCTIONAL", locator),
            lightpanda="PLATFORM_UNSUPPORTED",
        )
        predicted = self.finalize(payload, dry_run=True)
        self.assertEqual("SAVED", predicted.status)
        self.assertEqual(before, self._table_snapshot())
        self.assertEqual(
            {direct_id, chrome_id},
            {
                claim_id
                for proposal in self.memory.get_pending_candidates("example-news", "topic-search")
                for claim_id in proposal["claim_ids"]
            },
        )

        real = self.finalize(payload)
        self.assertEqual("SAVED", real.status)
        self.assertEqual([], self.memory.get_pending_candidates("example-news", "topic-search"))
        self.assertEqual(
            {direct_id, chrome_id},
            set(self.memory.get_current("example-news", "topic-search")["accepted_claim_ids"]),
        )

    def test_cli_failure_unclassified_stays_open_and_a_corrected_retry_saves(self):
        # The FAILURE_UNCLASSIFIED counterpart to the TRANSPORT_POLICY_UNPROVEN
        # CLI lifecycle test above: same run marker survives the rejection and
        # a classified retry under the same run_id saves and closes it.
        payload_path = self.root / "failure-unclassified-discovery.json"
        body = self.exhausted_direct_read_payload(classified=False)
        payload_path.write_text(json.dumps(body), encoding="utf-8")
        self.open_payload(payload_path)

        result = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root), "--input", str(payload_path)],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        stdout = json.loads(result.stdout)
        self.assertEqual("NOT_SAVED", stdout["status"])
        self.assertEqual("FAILURE_UNCLASSIFIED", stdout["reason_code"])
        self.assertEqual("OPEN", stdout["run_state"])
        from discovery_runs import list_open_discoveries
        open_runs = list_open_discoveries(self.root)
        self.assertEqual([body["provenance"]["run_id"]], [item["run_id"] for item in open_runs])

        fixed = self.exhausted_direct_read_payload(classified=True)
        fixed["provenance"]["run_id"] = body["provenance"]["run_id"]
        payload_path.write_text(json.dumps(fixed), encoding="utf-8")
        retried = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root), "--input", str(payload_path)],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(0, retried.returncode, retried.stderr)
        retried_body = json.loads(retried.stdout)
        self.assertEqual("SAVED", retried_body["status"])
        self.assertEqual("CLOSED", retried_body["run_state"])
        self.assertEqual([], list_open_discoveries(self.root))


class RefusalMessageTests(unittest.TestCase):
    """Every closed-set refusal names the rejected value and accepted set.

    Plan 004: the payload contract is the product's public API and an LLM
    agent is its only client, so an opaque refusal costs retries. Each test
    below covers one row of the plan's "Opaque sites to fix" table. This
    duplicates a minimal slice of `DiscoveryFinalizeTests`' fixture rather
    than subclassing it, so it runs only its own tests, not the whole suite
    a second time.
    """

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
                {"family": "transport", "value": {
                    "transport": "DIRECT_READ", "outcome": "FUNCTIONAL",
                }},
                {"family": "extraction", "value": {"structure": "JSON_LD"}},
            ],
            "evidence": [{"kind": "bounded-browser-validation", "locator": "https://www.example-news.com/busca/"}],
            "provenance": {"run_id": "run:example-news:001", "observed_at": RECORDED},
            "recorded_at": RECORDED,
        }

    def finalize(self, payload=None, *, dry_run=False):
        payload = payload or self.payload()
        arguments = {
            "target": payload["target"], "capability": payload["capability"],
            "observations": payload["observations"], "evidence": payload["evidence"],
            "provenance": payload["provenance"], "recorded_at": payload["recorded_at"],
            "dry_run": dry_run,
        }
        if "transport_trace" in payload:
            arguments["transport_trace"] = payload["transport_trace"]
        return finalize_discovery(self.memory, **arguments)

    @staticmethod
    def transport_trace(*attempts, lightpanda="AVAILABLE", chrome="AVAILABLE"):
        return {
            "availability": {"LIGHTPANDA": lightpanda, "CHROME": chrome},
            "attempts": [
                {"transport": transport, "outcome": outcome, "evidence": [locator]}
                for transport, outcome, locator in attempts
            ],
        }

    @staticmethod
    def transport_observation(transport, outcome, locator):
        return {
            "family": "transport",
            "value": {"transport": transport, "outcome": outcome},
            "validation": {
                "transport": transport,
                "outcome": outcome,
                "engine": None if transport == "DIRECT_READ" else transport.lower(),
                "javascript": transport != "DIRECT_READ",
                "context": {
                    "authentication": "PUBLIC", "environment": "PRODUCTION",
                },
                "evidence": [locator],
            },
        }

    def test_every_raise_passes_an_explicit_code(self):
        # Every `raise DiscoveryFinalizationError(...)` call must pass
        # `code=` explicitly. A site that cannot be classified may keep the
        # class default `PAYLOAD_INVALID` only through this explicit
        # allowlist, which must stay empty.
        ALLOWED_DEFAULT_CODE_LINES: frozenset[int] = frozenset()
        source = (SKILL / "discovery_finalize.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        missing: list[int] = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "DiscoveryFinalizationError"
            ):
                has_code = any(keyword.arg == "code" for keyword in node.keywords)
                if not has_code and node.lineno not in ALLOWED_DEFAULT_CODE_LINES:
                    missing.append(node.lineno)
        self.assertEqual([], missing, f"raise sites missing code=: {missing}")

    def test_unsupported_transport_names_value_and_accepted_set(self):
        payload = self.payload([
            {"family": "transport", "value": {
                "transport": "CARRIER_PIGEON", "outcome": "FUNCTIONAL",
            }},
        ])
        with self.assertRaises(DiscoveryFinalizationError) as ctx:
            self.finalize(payload)
        self.assertEqual(PAYLOAD_VALUE, ctx.exception.code)
        message = str(ctx.exception)
        self.assertIn("CARRIER_PIGEON", message)
        self.assertIn("DIRECT_READ", message)
        self.assertIn("CHROME", message)

    def test_unsupported_family_names_value_and_accepted_set(self):
        payload = self.payload([
            {"family": "weather", "value": {"transport": "DIRECT_READ"}},
        ])
        with self.assertRaises(DiscoveryFinalizationError) as ctx:
            self.finalize(payload)
        self.assertEqual(PAYLOAD_VALUE, ctx.exception.code)
        message = str(ctx.exception)
        self.assertIn("'weather'", message)
        self.assertIn("transport", message)
        self.assertIn("extraction", message)

    def test_invalid_epistemic_class_names_value_and_accepted_set(self):
        payload = self.payload([
            {
                "family": "transport",
                "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"},
                "epistemic": "GUESSED",
            },
        ])
        with self.assertRaises(DiscoveryFinalizationError) as ctx:
            self.finalize(payload)
        self.assertEqual(PAYLOAD_VALUE, ctx.exception.code)
        message = str(ctx.exception)
        self.assertIn("'GUESSED'", message)
        self.assertIn("OBSERVED", message)
        self.assertIn("INFERRED", message)

    def test_evidence_kind_pattern_violation_names_value_and_example(self):
        payload = self.payload()
        payload["evidence"] = [
            {"kind": "Direct_Read", "locator": "https://www.example-news.com/busca/"},
        ]
        with self.assertRaises(DiscoveryFinalizationError) as ctx:
            self.finalize(payload)
        self.assertEqual(EVIDENCE_LINKAGE, ctx.exception.code)
        message = str(ctx.exception)
        self.assertIn("'Direct_Read'", message)
        self.assertIn("lowercase letter", message)
        self.assertIn("direct-read-validation", message)

    def test_transport_trace_availability_status_names_value_and_accepted_set(self):
        locator = "https://www.example-news.com/busca/"
        payload = self.payload([
            self.transport_observation("DIRECT_READ", "FUNCTIONAL", locator),
        ])
        payload["transport_trace"] = self.transport_trace(
            ("DIRECT_READ", "FUNCTIONAL", locator),
            lightpanda="MAYBE_AVAILABLE", chrome="AVAILABLE",
        )
        with self.assertRaises(DiscoveryFinalizationError) as ctx:
            self.finalize(payload)
        self.assertEqual(TRANSPORT_TRACE, ctx.exception.code)
        message = str(ctx.exception)
        self.assertIn("MAYBE_AVAILABLE", message)
        self.assertIn("AVAILABLE", message)
        self.assertIn("PLATFORM_UNSUPPORTED", message)

    def test_transport_trace_attempt_outcome_names_value_and_accepted_set(self):
        locator = "https://www.example-news.com/busca/"
        payload = self.payload([
            self.transport_observation("DIRECT_READ", "FUNCTIONAL", locator),
        ])
        trace = self.transport_trace(("DIRECT_READ", "FUNCTIONAL", locator))
        trace["attempts"][0]["outcome"] = "TIMEOUT"
        payload["transport_trace"] = trace
        with self.assertRaises(DiscoveryFinalizationError) as ctx:
            self.finalize(payload)
        self.assertEqual(TRANSPORT_TRACE, ctx.exception.code)
        message = str(ctx.exception)
        self.assertIn("'TIMEOUT'", message)
        self.assertIn("FAILED", message)
        self.assertIn("FUNCTIONAL", message)

    def test_unsupported_fields_names_rejected_and_accepted_fields(self):
        payload = self.payload([
            {
                "family": "transport",
                "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"},
                "surprising_field": "x",
            },
        ])
        with self.assertRaises(DiscoveryFinalizationError) as ctx:
            self.finalize(payload)
        self.assertEqual(PAYLOAD_SHAPE, ctx.exception.code)
        message = str(ctx.exception)
        self.assertIn("surprising_field", message)
        self.assertIn("Accepted fields:", message)
        self.assertIn("family", message)
        self.assertIn("value", message)

    def test_missing_required_fields_names_missing_and_required_optional(self):
        payload = self.payload([
            {"family": "transport"},
        ])
        with self.assertRaises(DiscoveryFinalizationError) as ctx:
            self.finalize(payload)
        self.assertEqual(PAYLOAD_SHAPE, ctx.exception.code)
        message = str(ctx.exception)
        self.assertIn("value", message)
        self.assertIn("Required:", message)
        self.assertIn("optional:", message)

    def test_raw_content_length_violation_names_the_rule_that_fired(self):
        payload = self.payload([
            {"family": "search_surface", "value": {"path": "x" * 501}},
        ])
        with self.assertRaises(DiscoveryFinalizationError) as ctx:
            self.finalize(payload)
        self.assertEqual(TASK_DATA_REJECTED, ctx.exception.code)
        message = str(ctx.exception)
        self.assertIn("over 500 characters", message)
        self.assertIn("501", message)


if __name__ == "__main__":
    unittest.main()
