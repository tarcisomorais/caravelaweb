from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[0]
SKILL = REPO
sys.path.insert(0, str(SKILL))

from operational_memory import SQLiteOperationalMemory
from integration_bridge import BridgeError, KnowledgeLookupBoundary

NOW = "2026-07-26T16:00:00Z"
RECORDED_AT = "2026-07-26T12:00:00Z"


class IntegrationBridgeRuntimeLookupTests(unittest.TestCase):
    """Public lookup surface of the runtime bridge script.

    Seeded directly through Operational Memory write primitives rather than
    compatibility-only import machinery. The runtime bridge's controlled
    lookup contract remains independently covered.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "targets").mkdir()
        self.db = self.root / "memory.sqlite3"
        self.memory = SQLiteOperationalMemory(self.db, clock=lambda: NOW)
        self.addCleanup(self.memory.close)
        with self.memory.write_transaction() as writer:
            writer.target({"id": "tgt:example-radio", "name": "Example Radio"})
            writer.capability({"id": "cap:example-radio:search", "target_id": "tgt:example-radio", "key": "search"})
            writer.claim({
                "id": "clm:example-radio:search:transport:direct",
                "target_id": "tgt:example-radio",
                "capability_id": "cap:example-radio:search",
                "family": "transport",
                "epistemic": "OBSERVED",
                "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"},
                "recorded_at": RECORDED_AT,
            })
            writer.claim({
                "id": "clm:example-radio:search:completion:full",
                "target_id": "tgt:example-radio",
                "capability_id": "cap:example-radio:search",
                "family": "completion",
                "epistemic": "OBSERVED",
                "value": {"status": "COMPLETE"},
                "recorded_at": RECORDED_AT,
            })
            writer.claim({
                "id": "clm:example-radio:search:lifecycle:unverified",
                "target_id": "tgt:example-radio",
                "capability_id": "cap:example-radio:search",
                "family": "lifecycle",
                "epistemic": "OBSERVED",
                "value": "OPERATIONAL",
                "recorded_at": RECORDED_AT,
            })
            writer.decision({
                "id": "dec:example-radio:search:accept-transport",
                "target_id": "tgt:example-radio",
                "capability_id": "cap:example-radio:search",
                "action": "ACCEPT",
                "claim_ids": ["clm:example-radio:search:transport:direct"],
                "effective_at": RECORDED_AT,
                "recorded_at": RECORDED_AT,
                "validity": {"valid_from": RECORDED_AT, "valid_to": None},
            })
            writer.decision({
                "id": "dec:example-radio:search:accept-completion",
                "target_id": "tgt:example-radio",
                "capability_id": "cap:example-radio:search",
                "action": "ACCEPT",
                "claim_ids": ["clm:example-radio:search:completion:full"],
                "effective_at": RECORDED_AT,
                "recorded_at": RECORDED_AT,
                "validity": {"valid_from": RECORDED_AT, "valid_to": None},
            })
            writer.decision({
                "id": "dec:example-radio:search:accept-unverified-lifecycle",
                "target_id": "tgt:example-radio",
                "capability_id": "cap:example-radio:search",
                "action": "ACCEPT",
                "claim_ids": ["clm:example-radio:search:lifecycle:unverified"],
                "effective_at": RECORDED_AT,
                "recorded_at": RECORDED_AT,
                "validity": {"valid_from": RECORDED_AT, "valid_to": None},
            })

    def test_runtime_bridge_script_passes_controlled_lookup(self) -> None:
        script = SKILL / "scripts" / "knowledge-lookup"
        command = [
            sys.executable,
            str(script),
            "--knowledge-root",
            str(self.root),
            "--target",
            "example-radio",
            "--capability",
            "search",
            "--operational-memory-db",
            str(self.db),
            "--use-operational-memory",
        ]
        result = subprocess.run(command, check=True, text=True, capture_output=True)
        payload = json.loads(result.stdout)
        self.assertEqual("found", payload["status"])
        self.assertEqual("operational-memory", payload["source"])
        current = payload["operational_context"]["current"]
        self.assertIn("transport", current)
        self.assertIn("completion", current)
        self.assertNotIn("lifecycle", current)
        self.assertIn("lifecycle", payload)
        self.assertIsNone(payload["lifecycle"])

    def test_diagnostic_compatibility_remains_explicit(self) -> None:
        profile = self.root / "targets" / "example-radio.md"
        profile.write_text("# Example Radio\n", encoding="utf-8")
        state = self.root / ".caravelaweb"
        state.mkdir()
        (state / "read-authority-operational-memory").write_text("active\n", encoding="utf-8")

        result = KnowledgeLookupBoundary(self.root, self.db).lookup(
            "example-radio", use_legacy=True
        )
        self.assertEqual("legacy", result.source)
        self.assertEqual(str(profile), result.profile_path)
        with self.assertRaisesRegex(BridgeError, "mutually exclusive"):
            KnowledgeLookupBoundary(self.root, self.db).lookup(
                "example-radio", use_operational_memory=True, use_legacy=True
            )


class PendingCandidateVisibilityTests(unittest.TestCase):
    """Pending Candidates surface as a sibling of accepted knowledge."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "targets").mkdir()
        state = self.root / ".caravelaweb"
        state.mkdir()
        (state / "read-authority-operational-memory").write_text("active\n", encoding="utf-8")
        self.db = self.root / "memory.sqlite3"
        self.memory = SQLiteOperationalMemory(self.db, clock=lambda: NOW)
        self.addCleanup(self.memory.close)
        with self.memory.write_transaction() as writer:
            writer.target({"id": "tgt:example-news", "name": "Example News"})
            writer.capability({"id": "cap:example-news:topic-search", "target_id": "tgt:example-news", "key": "topic-search"})
            writer.claim({
                "id": "clm:example-news:topic-search:transport:direct",
                "target_id": "tgt:example-news",
                "capability_id": "cap:example-news:topic-search",
                "family": "transport",
                "epistemic": "OBSERVED",
                "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"},
                "recorded_at": RECORDED_AT,
            })
            writer.proposal({
                "id": "prop:example-news:topic-search:pending",
                "target_id": "tgt:example-news",
                "capability_id": "cap:example-news:topic-search",
                "recorded_at": RECORDED_AT,
                "claim_ids": ["clm:example-news:topic-search:transport:direct"],
            })

    def test_capability_lookup_returns_pending_candidates(self) -> None:
        result = KnowledgeLookupBoundary(self.root, self.db).lookup(
            "example-news", capability="topic-search", use_operational_memory=True,
        )
        self.assertIsNone(result.operational_context)
        self.assertEqual(1, len(result.pending_candidates))
        candidate = result.pending_candidates[0]
        self.assertEqual("prop:example-news:topic-search:pending", candidate["proposal_id"])
        self.assertEqual(
            "clm:example-news:topic-search:transport:direct", candidate["claims"][0]["id"],
        )

    def test_target_only_lookup_groups_pending_candidates_by_capability(self) -> None:
        result = KnowledgeLookupBoundary(self.root, self.db).lookup(
            "example-news", use_operational_memory=True,
        )
        self.assertEqual(["topic-search"], list(result.pending_candidates))
        self.assertEqual(1, len(result.pending_candidates["topic-search"]))
        self.assertEqual(
            "prop:example-news:topic-search:pending",
            result.pending_candidates["topic-search"][0]["proposal_id"],
        )

    def test_runtime_bridge_script_reports_pending_candidates(self) -> None:
        script = SKILL / "scripts" / "knowledge-lookup"
        command = [
            sys.executable, str(script),
            "--knowledge-root", str(self.root),
            "--target", "example-news",
            "--capability", "topic-search",
            "--operational-memory-db", str(self.db),
            "--use-operational-memory",
        ]
        result = subprocess.run(command, check=True, text=True, capture_output=True)
        payload = json.loads(result.stdout)
        self.assertEqual("not_found", payload["status"])
        self.assertIn("pending_candidates", payload)


class ListIndexTests(unittest.TestCase):
    """`--list` returns an exact index of every target, host, and capability."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "targets").mkdir()
        state = self.root / ".caravelaweb"
        state.mkdir()
        (state / "read-authority-operational-memory").write_text("active\n", encoding="utf-8")
        self.db = self.root / "memory.sqlite3"
        self.memory = SQLiteOperationalMemory(self.db, clock=lambda: NOW)
        self.addCleanup(self.memory.close)
        with self.memory.write_transaction() as writer:
            writer.target({"id": "tgt:example-radio", "name": "Example Radio"})
            writer.host({"id": "host:example-radio:main", "target_id": "tgt:example-radio", "hostname": "example-radio.example"})
            writer.capability({"id": "cap:example-radio:search", "target_id": "tgt:example-radio", "key": "search"})
            writer.claim({
                "id": "clm:example-radio:search:transport:direct",
                "target_id": "tgt:example-radio",
                "capability_id": "cap:example-radio:search",
                "family": "transport",
                "epistemic": "OBSERVED",
                "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"},
                "recorded_at": RECORDED_AT,
            })
            writer.decision({
                "id": "dec:example-radio:search:accept-transport",
                "target_id": "tgt:example-radio",
                "capability_id": "cap:example-radio:search",
                "action": "ACCEPT",
                "claim_ids": ["clm:example-radio:search:transport:direct"],
                "effective_at": RECORDED_AT,
                "recorded_at": RECORDED_AT,
                "validity": {"valid_from": RECORDED_AT, "valid_to": None},
            })
            writer.target({"id": "tgt:example-jobs", "name": "Example Jobs"})
            writer.capability({"id": "cap:example-jobs:listings", "target_id": "tgt:example-jobs", "key": "listings"})
            writer.claim({
                "id": "clm:example-jobs:listings:transport:direct",
                "target_id": "tgt:example-jobs",
                "capability_id": "cap:example-jobs:listings",
                "family": "transport",
                "epistemic": "OBSERVED",
                "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"},
                "recorded_at": RECORDED_AT,
            })
            writer.proposal({
                "id": "prop:example-jobs:listings:pending",
                "target_id": "tgt:example-jobs",
                "capability_id": "cap:example-jobs:listings",
                "recorded_at": RECORDED_AT,
                "claim_ids": ["clm:example-jobs:listings:transport:direct"],
            })

    def test_list_index_reports_hosts_and_capability_state_in_id_order(self) -> None:
        index = KnowledgeLookupBoundary(self.root, self.db).list_index()
        self.assertEqual(["tgt:example-jobs", "tgt:example-radio"], [row["target_id"] for row in index])

        jobs = index[0]
        self.assertEqual([], jobs["hosts"])
        self.assertEqual(1, len(jobs["capabilities"]))
        jobs_cap = jobs["capabilities"][0]
        self.assertEqual("listings", jobs_cap["capability"])
        self.assertFalse(jobs_cap["accepted"])
        self.assertIsNone(jobs_cap["lifecycle"])
        self.assertEqual(1, jobs_cap["pending_proposals"])

        radio = index[1]
        self.assertEqual(["example-radio.example"], radio["hosts"])
        self.assertEqual(1, len(radio["capabilities"]))
        radio_cap = radio["capabilities"][0]
        self.assertEqual("search", radio_cap["capability"])
        self.assertTrue(radio_cap["accepted"])
        self.assertIsNone(radio_cap["lifecycle"])
        self.assertEqual(0, radio_cap["pending_proposals"])

    def test_runtime_bridge_script_list_flag(self) -> None:
        script = SKILL / "scripts" / "knowledge-lookup"
        result = subprocess.run(
            [sys.executable, str(script), "--knowledge-root", str(self.root), "--operational-memory-db", str(self.db), "--list"],
            check=True, text=True, capture_output=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual("listed", payload["status"])
        self.assertEqual(2, payload["count"])

    def test_list_with_target_is_an_argument_error(self) -> None:
        script = SKILL / "scripts" / "knowledge-lookup"
        result = subprocess.run(
            [sys.executable, str(script), "--knowledge-root", str(self.root), "--operational-memory-db", str(self.db), "--list", "--target", "example-radio"],
            text=True, capture_output=True,
        )
        self.assertNotEqual(0, result.returncode)


class IntegrationBridgePublicInterfaceTests(unittest.TestCase):
    """Only the current lookup boundary is exposed by integration_bridge."""

    LEGACY_NAMES = (
        "ImportResult",
        "ParsedLegacyProfile",
        "SemanticItem",
        "import_legacy_profile",
        "parse_legacy_profile",
        "semantic_round_trip",
        "BridgeStaleBaseError",
        "KnowledgeWriteAuthorityRequired",
        "map_candidate_markdown",
        "promote_mapped_candidate",
    )

    def test_retired_migration_symbols_are_not_reexported(self) -> None:
        import integration_bridge

        for name in self.LEGACY_NAMES:
            self.assertNotIn(name, integration_bridge.__all__)
            self.assertFalse(hasattr(integration_bridge, name))


if __name__ == "__main__":
    unittest.main(verbosity=2)
