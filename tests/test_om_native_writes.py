from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[0]
SKILL = REPO
sys.path.insert(0, str(SKILL))

from knowledge_write_freeze import KnowledgeWriteFrozenError, enable_freeze
from om_native_writes import (
    OMAmbiguousCandidateError,
    OMProposalError,
    OMStaleBaseError,
    capture_candidate,
    promote_candidate,
    review_token,
)
from operational_memory.core import SQLiteOperationalMemory
from write_authority import MIGRATED_WRITE_AUTHORITY_KIND, WriteAuthorityStateError

NOW = "2030-01-01T00:00:00Z"
RECORDED = "2026-07-28T12:00:00Z"


def seed(memory: SQLiteOperationalMemory, *, reverse: bool = False) -> None:
    claims = [
        {
            "id": "clm:alpha:read:entrypoint:a",
            "target_id": "tgt:alpha",
            "capability_id": "cap:alpha:read",
            "family": "entrypoint",
            "epistemic": "OBSERVED",
            "value": {"route": "/a", "flags": ["x", "y"]},
            "recorded_at": "2026-01-01T00:00:00Z",
        },
        {
            "id": "clm:alpha:read:constraint:b",
            "target_id": "tgt:alpha",
            "capability_id": "cap:alpha:read",
            "family": "constraint",
            "epistemic": "INFERRED",
            "value": {"limit": 10},
            "recorded_at": "2026-01-01T00:00:01Z",
        },
    ]
    decisions = [
        {
            "id": "dec:alpha:read:accept-a",
            "target_id": "tgt:alpha",
            "capability_id": "cap:alpha:read",
            "action": "ACCEPT",
            "claim_ids": ["clm:alpha:read:entrypoint:a"],
            "effective_at": "2026-01-01T00:00:00Z",
            "recorded_at": "2026-01-01T00:00:00Z",
            "validity": {"valid_from": "2026-01-01T00:00:00Z", "valid_to": None},
        },
        {
            "id": "dec:alpha:read:accept-b",
            "target_id": "tgt:alpha",
            "capability_id": "cap:alpha:read",
            "action": "ACCEPT",
            "claim_ids": ["clm:alpha:read:constraint:b"],
            "effective_at": "2026-01-01T00:00:01Z",
            "recorded_at": "2026-01-01T00:00:01Z",
            "validity": {"valid_from": "2026-01-01T00:00:00Z", "valid_to": None},
        },
    ]
    if reverse:
        claims.reverse()
        decisions.reverse()
    with memory.write_transaction() as writer:
        writer.target({"id": "tgt:alpha", "name": "Alpha"})
        writer.capability(
            {
                "id": "cap:alpha:read",
                "target_id": "tgt:alpha",
                "key": "read",
                "name": "Read",
            }
        )
        for claim in claims:
            writer.claim(claim)
        for decision in decisions:
            writer.decision(decision)


class OMNativeWritesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / ".caravelaweb").mkdir()
        (self.root / ".caravelaweb" / "write-authority.json").write_text(
            json.dumps(
                {
                    "kind": MIGRATED_WRITE_AUTHORITY_KIND,
                    "status": "ACTIVE",
                    "previous_write_authority": "LEGACY",
                    "write_authority": "OPERATIONAL_MEMORY",
                    "om_authoritative_writes": 0,
                    "first_om_write": "NOT_PERFORMED",
                }
            ),
            encoding="utf-8",
        )
        (self.root / "targets").mkdir()
        (self.root / "candidates").mkdir()
        self.profile = self.root / "targets" / "alpha.md"
        self.candidate_file = self.root / "candidates" / "legacy.md"
        self.profile.write_text("legacy accepted\n", encoding="utf-8")
        self.candidate_file.write_text("legacy candidate\n", encoding="utf-8")
        self.memory = SQLiteOperationalMemory(
            self.root / ".caravelaweb" / "operational_memory.db",
            clock=lambda: NOW,
        )
        seed(self.memory)
        self.legacy_before = self._legacy_bytes()

    def tearDown(self) -> None:
        self.memory.close()
        self.temp.cleanup()

    def _legacy_bytes(self) -> tuple[bytes, bytes]:
        return self.profile.read_bytes(), self.candidate_file.read_bytes()

    @staticmethod
    def claims() -> list[dict]:
        return [
            {
                "id": "clm:alpha:read:entrypoint:candidate-c",
                "family": "entrypoint",
                "epistemic": "OBSERVED",
                "value": {"route": "/c"},
            },
            {
                "id": "clm:alpha:read:unknown:candidate-limit",
                "family": "unknown",
                "epistemic": "UNKNOWN",
                "value": {"limit": "UNKNOWN"},
            },
        ]

    def capture(self, *, proposal_id: str = "prop:alpha:read:candidate-c"):
        return capture_candidate(
            self.memory,
            target="alpha",
            capability="read",
            proposal_id=proposal_id,
            claims=self.claims(),
            provenance={"source": "reviewed structured candidate", "actor": "test"},
            recorded_at=RECORDED,
        )

    def promote(self, proposal_id: str, token: str, decision_id: str = "dec:alpha:read:promote-c"):
        return promote_candidate(
            self.memory,
            target="alpha",
            capability="read",
            proposal_id=proposal_id,
            reviewed_token=token,
            decision_id=decision_id,
            recorded_at="2026-07-28T13:00:00Z",
            effective_at="2026-07-28T13:00:00Z",
        )

    def test_review_token_is_stable_and_independent_of_physical_order(self) -> None:
        first = review_token(self.memory, target="alpha", capability="read")
        self.assertEqual(first, review_token(self.memory, target="alpha", capability="read"))
        self.memory._conn.execute("PRAGMA reverse_unordered_selects=ON")
        self.assertEqual(first, review_token(self.memory, target="alpha", capability="read"))

        other_root = self.root / "other"
        other_root.mkdir()
        with SQLiteOperationalMemory(
            other_root / "memory.db", clock=lambda: NOW
        ) as other:
            seed(other, reverse=True)
            self.assertEqual(first, review_token(other, target="alpha", capability="read"))

    def test_review_token_changes_when_accepted_state_changes(self) -> None:
        before = review_token(self.memory, target="alpha", capability="read")
        with self.memory.write_transaction() as writer:
            writer.claim(
                {
                    "id": "clm:alpha:read:constraint:new",
                    "target_id": "tgt:alpha",
                    "capability_id": "cap:alpha:read",
                    "family": "constraint",
                    "epistemic": "OBSERVED",
                    "value": {"new": True},
                    "recorded_at": "2026-07-28T12:30:00Z",
                }
            )
            writer.decision(
                {
                    "id": "dec:alpha:read:accept-new",
                    "target_id": "tgt:alpha",
                    "capability_id": "cap:alpha:read",
                    "action": "ACCEPT",
                    "claim_ids": ["clm:alpha:read:constraint:new"],
                    "effective_at": "2026-07-28T12:30:00Z",
                    "recorded_at": "2026-07-28T12:30:00Z",
                    "validity": {
                        "valid_from": "2026-07-28T12:30:00Z",
                        "valid_to": None,
                    },
                }
            )
        self.assertNotEqual(before, review_token(self.memory, target="alpha", capability="read"))

    def test_capture_is_transactional_pending_only_and_never_touches_markdown(self) -> None:
        accepted_before = self.memory.get_current("alpha", "read")["accepted_claim_ids"]
        result = self.capture()
        self.assertEqual(tuple(sorted(item["id"] for item in self.claims())), result.claim_ids)
        pending = self.memory.get_pending_candidates("alpha", "read")
        self.assertEqual([result.proposal_id], [item["proposal_id"] for item in pending])
        current = self.memory.get_current("alpha", "read")
        self.assertEqual(accepted_before, current["accepted_claim_ids"])
        self.assertTrue(set(result.claim_ids).isdisjoint(current["accepted_claim_ids"]))
        self.assertEqual(self.legacy_before, self._legacy_bytes())
        self.assertEqual("CANDIDATE_CAPTURE", result.metadata["operation"])
        self.assertFalse(result.metadata["first_om_authoritative_write"])

        before_counts = tuple(
            self.memory._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("claims", "proposals")
        )
        bad = self.claims()
        bad[1]["id"] = bad[0]["id"]
        with self.assertRaises(OMAmbiguousCandidateError):
            capture_candidate(
                self.memory,
                target="alpha",
                capability="read",
                proposal_id="prop:alpha:read:bad",
                claims=bad,
                provenance={"source": "test"},
                recorded_at=RECORDED,
            )
        after_counts = tuple(
            self.memory._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("claims", "proposals")
        )
        self.assertEqual(before_counts, after_counts)

    def test_valid_promotion_creates_decision_for_exact_proposal_claims(self) -> None:
        captured = self.capture()
        token = review_token(self.memory, target="alpha", capability="read")
        promoted = self.promote(captured.proposal_id, token)
        row = self.memory._conn.execute(
            "SELECT proposal_id,payload_json FROM decisions WHERE id=?",
            (promoted.decision_id,),
        ).fetchone()
        self.assertEqual(captured.proposal_id, row["proposal_id"])
        self.assertEqual(captured.claim_ids, promoted.claim_ids)
        payload = json.loads(row["payload_json"])
        self.assertEqual(token, payload["write_metadata"]["review_token"])
        self.assertEqual(
            set(captured.claim_ids),
            set(self.memory.get_current("alpha", "read")["accepted_claim_ids"])
            - {
                "clm:alpha:read:entrypoint:a",
                "clm:alpha:read:constraint:b",
            },
        )
        self.assertEqual([], self.memory.get_pending_candidates("alpha", "read"))
        self.assertEqual(self.legacy_before, self._legacy_bytes())

    def test_stale_token_blocks_promotion_without_partial_write(self) -> None:
        captured = self.capture()
        stale = review_token(self.memory, target="alpha", capability="read")
        with self.memory.write_transaction() as writer:
            writer.claim(
                {
                    "id": "clm:alpha:read:constraint:concurrent",
                    "target_id": "tgt:alpha",
                    "capability_id": "cap:alpha:read",
                    "family": "constraint",
                    "epistemic": "OBSERVED",
                    "value": {"concurrent": True},
                    "recorded_at": "2026-07-28T12:30:00Z",
                }
            )
            writer.decision(
                {
                    "id": "dec:alpha:read:concurrent",
                    "target_id": "tgt:alpha",
                    "capability_id": "cap:alpha:read",
                    "action": "ACCEPT",
                    "claim_ids": ["clm:alpha:read:constraint:concurrent"],
                    "effective_at": "2026-07-28T12:30:00Z",
                    "recorded_at": "2026-07-28T12:30:00Z",
                    "validity": {
                        "valid_from": "2026-07-28T12:30:00Z",
                        "valid_to": None,
                    },
                }
            )
        decisions_before = self.memory._conn.execute(
            "SELECT count(*) FROM decisions"
        ).fetchone()[0]
        with self.assertRaises(OMStaleBaseError):
            self.promote(captured.proposal_id, stale)
        self.assertEqual(
            decisions_before,
            self.memory._conn.execute("SELECT count(*) FROM decisions").fetchone()[0],
        )
        self.assertEqual(
            [captured.proposal_id],
            [
                item["proposal_id"]
                for item in self.memory.get_pending_candidates("alpha", "read")
            ],
        )

    def test_wrong_or_resolved_proposal_and_scope_mismatch_are_rejected(self) -> None:
        captured = self.capture()
        token = review_token(self.memory, target="alpha", capability="read")
        with self.assertRaises(OMProposalError):
            self.promote("prop:alpha:read:wrong", token)
        self.promote(captured.proposal_id, token)
        with self.assertRaises(OMProposalError):
            self.promote(
                captured.proposal_id,
                review_token(self.memory, target="alpha", capability="read"),
                "dec:alpha:read:second",
            )

        with self.memory.write_transaction() as writer:
            writer.capability(
                {
                    "id": "cap:alpha:other",
                    "target_id": "tgt:alpha",
                    "key": "other",
                }
            )
        with self.assertRaises(OMProposalError):
            promote_candidate(
                self.memory,
                target="alpha",
                capability="other",
                proposal_id=captured.proposal_id,
                reviewed_token=review_token(
                    self.memory, target="alpha", capability="other"
                ),
                decision_id="dec:alpha:other:wrong",
                recorded_at="2026-07-28T14:00:00Z",
                effective_at="2026-07-28T14:00:00Z",
            )
        with self.assertRaises(OMAmbiguousCandidateError):
            capture_candidate(
                self.memory,
                target="alpha",
                capability="read",
                proposal_id="prop:alpha:read:mismatch",
                claims=[
                    {
                        **self.claims()[0],
                        "id": "clm:alpha:read:mismatch",
                        "capability_id": "cap:alpha:other",
                    }
                ],
                provenance={"source": "test"},
                recorded_at=RECORDED,
            )

    def test_promote_candidate_treats_close_action_decisions_as_resolved(self) -> None:
        """Regression test for the Audit 1 Decision Action divergence.

        promote_candidate's "already resolved" check must agree with the
        canonical resolution rule Operational Memory already uses everywhere
        else (get_pending_candidates: ACCEPT_ACTIONS | CLOSE_ACTIONS |
        REJECT). An out-of-band Decision against a pending Proposal's sole
        Claim must block promotion exactly like an ACCEPT would. A
        promote_candidate that only recognized a hardcoded action subset (the
        pre-Audit-1 behavior) would miss this and double-decide the Claim.

        Uses REJECT rather than a close action (DEGRADE/SUPERSEDE): Audit 2
        added a write-time guard rejecting close-family Decisions against a
        Claim with no prior accepted interval, so a still-pending Claim can no
        longer reach that state via DEGRADE/SUPERSEDE at all. REJECT has no
        such precondition and reaches the same "resolved but not through
        ACCEPT" state this test exists to cover.
        """
        proposal_id = "prop:alpha:read:degrade-regression"
        claim_id = "clm:alpha:read:entrypoint:degrade-regression"
        capture_candidate(
            self.memory,
            target="alpha",
            capability="read",
            proposal_id=proposal_id,
            claims=[
                {
                    "id": claim_id,
                    "family": "entrypoint",
                    "epistemic": "OBSERVED",
                    "value": {"route": "/degrade-regression"},
                }
            ],
            provenance={"source": "test"},
            recorded_at=RECORDED,
        )
        with self.memory.write_transaction() as writer:
            writer.decision(
                {
                    "id": "dec:alpha:read:out-of-band-reject",
                    "target_id": "tgt:alpha",
                    "capability_id": "cap:alpha:read",
                    "action": "REJECT",
                    "claim_ids": [claim_id],
                    "effective_at": "2026-07-28T12:45:00Z",
                    "recorded_at": "2026-07-28T12:45:00Z",
                    "validity": {"valid_from": None, "valid_to": None},
                }
            )
        # The canonical rule (already used by get_pending_candidates
        # elsewhere) considers the Proposal resolved.
        self.assertEqual([], self.memory.get_pending_candidates("alpha", "read"))
        decisions_before = self.memory._conn.execute(
            "SELECT count(*) FROM decisions"
        ).fetchone()[0]
        with self.assertRaises(OMProposalError):
            promote_candidate(
                self.memory,
                target="alpha",
                capability="read",
                proposal_id=proposal_id,
                reviewed_token=review_token(self.memory, target="alpha", capability="read"),
                decision_id="dec:alpha:read:degrade-regression-promote",
                recorded_at="2026-07-28T13:00:00Z",
                effective_at="2026-07-28T13:00:00Z",
            )
        self.assertEqual(
            decisions_before,
            self.memory._conn.execute("SELECT count(*) FROM decisions").fetchone()[0],
        )

    def test_missing_malformed_and_suspended_markers_fail_closed_with_no_partial_write(
        self,
    ) -> None:
        # Authority is now derived solely from the real marker at
        # memory.knowledge_root -- there is no caller-supplied flag left to
        # assert or bypass it. Detailed marker-parsing edge cases (unknown
        # kind, absent-marker-is-LEGACY, ...) are covered exhaustively in
        # test_write_authority.py; this proves the write *boundary* actually
        # consults that real state before touching any table.
        write_authority_path = self.root / ".caravelaweb" / "write-authority.json"
        original = write_authority_path.read_bytes()
        before = tuple(
            self.memory._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("targets", "capabilities", "claims", "proposals", "decisions")
        )
        cases = {
            "missing": None,
            "malformed": "not json",
            "suspended": json.dumps({
                "kind": MIGRATED_WRITE_AUTHORITY_KIND, "status": "SUSPENDED",
                "previous_write_authority": "LEGACY", "write_authority": "OPERATIONAL_MEMORY",
                "om_authoritative_writes": 0, "first_om_write": "NOT_PERFORMED",
            }),
        }
        try:
            for label, body in cases.items():
                with self.subTest(marker=label):
                    if body is None:
                        write_authority_path.unlink()
                    else:
                        write_authority_path.write_text(body, encoding="utf-8")
                    with self.assertRaises(WriteAuthorityStateError):
                        capture_candidate(
                            self.memory, target="alpha", capability="read",
                            proposal_id=f"prop:alpha:read:authority-{label}",
                            claims=self.claims(), provenance={"source": "test"},
                            recorded_at=RECORDED,
                        )
                    with self.assertRaises(WriteAuthorityStateError):
                        self.promote("prop:alpha:read:authority-nonexistent", "irrelevant-token")
        finally:
            write_authority_path.write_bytes(original)
        after = tuple(
            self.memory._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("targets", "capabilities", "claims", "proposals", "decisions")
        )
        self.assertEqual(before, after)
        self.assertEqual(self.legacy_before, self._legacy_bytes())
        # The restored ACTIVE marker grants write authority again.
        captured = self.capture()
        self.assertEqual(
            [captured.proposal_id],
            [item["proposal_id"] for item in self.memory.get_pending_candidates("alpha", "read")],
        )

    def test_write_freeze_blocks_capture_and_promotion_with_no_partial_write(self) -> None:
        captured = self.capture()
        token = review_token(self.memory, target="alpha", capability="read")
        enable_freeze(self.root, reason="read validation remains active")
        before = tuple(
            self.memory._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("claims", "proposals", "decisions")
        )
        with self.assertRaises(KnowledgeWriteFrozenError):
            capture_candidate(
                self.memory, target="alpha", capability="read",
                proposal_id="prop:alpha:read:frozen", claims=self.claims(),
                provenance={"source": "test"}, recorded_at=RECORDED,
            )
        with self.assertRaises(KnowledgeWriteFrozenError):
            self.promote(captured.proposal_id, token)
        after = tuple(
            self.memory._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("claims", "proposals", "decisions")
        )
        self.assertEqual(before, after)
        self.assertEqual(self.legacy_before, self._legacy_bytes())


if __name__ == "__main__":
    unittest.main()
