from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "knowledge-resolve"
LOOKUP = REPO / "scripts" / "knowledge-lookup"
sys.path.insert(0, str(REPO))

from operational_memory import SQLiteOperationalMemory
from write_authority import MIGRATED_WRITE_AUTHORITY_KIND

RECORDED = "2026-08-13T19:02:11Z"


class KnowledgeResolveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "targets").mkdir()
        state = self.root / ".caravelaweb"
        state.mkdir()
        self.db = state / "operational_memory.db"
        with SQLiteOperationalMemory(self.db) as memory:
            with memory.write_transaction() as writer:
                writer.target({"id": "tgt:example-news", "name": "Example News"})
                writer.capability({
                    "id": "cap:example-news:topic-search",
                    "target_id": "tgt:example-news",
                    "key": "topic-search",
                })
                writer.claim({
                    "id": "clm:example-news:topic-search:blocking:candidate",
                    "target_id": "tgt:example-news",
                    "capability_id": "cap:example-news:topic-search",
                    "family": "blocking",
                    "epistemic": "OBSERVED",
                    "value": {"blocking": True},
                    "proposal_id": "prop:example-news:topic-search:candidate",
                    "recorded_at": RECORDED,
                })
                writer.proposal({
                    "id": "prop:example-news:topic-search:candidate",
                    "target_id": "tgt:example-news",
                    "capability_id": "cap:example-news:topic-search",
                    "claim_ids": ["clm:example-news:topic-search:blocking:candidate"],
                    "recorded_at": RECORDED,
                })
        (state / "write-authority.json").write_text(json.dumps({
            "kind": MIGRATED_WRITE_AUTHORITY_KIND, "status": "ACTIVE",
            "write_authority": "OPERATIONAL_MEMORY",
            "previous_write_authority": "LEGACY",
            "om_authoritative_writes": 0, "first_om_write": "NOT_PERFORMED",
        }), encoding="utf-8")

    def run_cli(self, script: Path, *args: str):
        return subprocess.run(
            [sys.executable, str(script), "--knowledge-root", str(self.root), *args],
            text=True, capture_output=True, encoding="utf-8",
        )

    def resolve(self, *args: str):
        return self.run_cli(
            SCRIPT,
            "--target", "example-news",
            "--capability", "topic-search",
            "--reject-pending", "prop:example-news:topic-search:candidate",
            "--reason", "stale",
            *args,
        )

    def decision_count(self) -> int:
        with SQLiteOperationalMemory(self.db) as memory:
            return memory._conn.execute("SELECT count(*) FROM decisions").fetchone()[0]

    def test_reject_pending_proposal_succeeds(self) -> None:
        result = self.resolve()
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("REJECTED", payload["status"])
        self.assertEqual(
            ["clm:example-news:topic-search:blocking:candidate"], payload["claim_ids"]
        )

    def test_rejecting_the_same_proposal_again_fails(self) -> None:
        first = self.resolve()
        self.assertEqual(0, first.returncode, first.stderr)
        second = self.resolve()
        self.assertEqual(2, second.returncode)
        payload = json.loads(second.stderr)
        self.assertEqual("NOT_REJECTED", payload["status"])

    def test_unknown_proposal_id_fails(self) -> None:
        result = self.run_cli(
            SCRIPT,
            "--target", "example-news",
            "--capability", "topic-search",
            "--reject-pending", "prop:example-news:topic-search:does-not-exist",
            "--reason", "stale",
        )
        self.assertEqual(2, result.returncode)
        payload = json.loads(result.stderr)
        self.assertEqual("NOT_REJECTED", payload["status"])

    def test_missing_write_authority_marker_fails_without_writing(self) -> None:
        (self.root / ".caravelaweb" / "write-authority.json").unlink()
        before = self.decision_count()
        result = self.resolve()
        self.assertEqual(2, result.returncode)
        payload = json.loads(result.stderr)
        self.assertEqual("NOT_REJECTED", payload["status"])
        self.assertEqual(before, self.decision_count())

    def test_lookup_no_longer_lists_the_rejected_proposal_as_pending(self) -> None:
        result = self.resolve()
        self.assertEqual(0, result.returncode, result.stderr)
        with SQLiteOperationalMemory(self.db, knowledge_root=self.root) as memory:
            self.assertEqual([], memory.get_pending_candidates("example-news", "topic-search"))
        lookup = self.run_cli(
            LOOKUP, "--target", "example-news", "--capability", "topic-search"
        )
        self.assertEqual(0, lookup.returncode, lookup.stderr)
        payload = json.loads(lookup.stdout)
        pending = payload.get("pending_candidates", [])
        self.assertNotIn(
            "prop:example-news:topic-search:candidate",
            [item.get("proposal_id") for item in pending],
        )


if __name__ == "__main__":
    unittest.main()
