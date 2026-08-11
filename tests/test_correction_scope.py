from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[0]
sys.path.insert(0, str(REPO))

from operational_memory import CorrectionScopeAmbiguityError, SQLiteOperationalMemory

NOW = "2026-08-21T00:00:00Z"


class CorrectionScopeTests(unittest.TestCase):
    def test_ambiguous_retroactive_correction_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "memory.sqlite3"
            with SQLiteOperationalMemory(db, clock=lambda: NOW) as memory:
                with memory.write_transaction() as writer:
                    writer.target({"id": "tgt:scope-test", "name": "Scope Test"})
                    writer.capability({"id": "cap:scope-test:read", "target_id": "tgt:scope-test", "key": "read"})
                    for claim_id, family, value in (
                        ("clm:scope-test:read:entrypoint:a", "entrypoint", "A"),
                        ("clm:scope-test:read:transport:b", "transport", "B"),
                        ("clm:scope-test:read:unknown:correction", "unknown", "correction target not explicit"),
                    ):
                        writer.claim({
                            "id": claim_id,
                            "target_id": "tgt:scope-test",
                            "capability_id": "cap:scope-test:read",
                            "family": family,
                            "epistemic": "UNKNOWN" if family == "unknown" else "OBSERVED",
                            "value": value,
                        })
                    writer.decision({
                        "id": "dec:scope-test:read:20260801T100000Z:01",
                        "target_id": "tgt:scope-test",
                        "capability_id": "cap:scope-test:read",
                        "action": "ACCEPT",
                        "claim_ids": ["clm:scope-test:read:entrypoint:a", "clm:scope-test:read:transport:b"],
                        "effective_at": "2026-08-01T00:00:00Z",
                        "recorded_at": "2026-08-01T10:00:00Z",
                        "validity": {"valid_from": "2026-08-01T00:00:00Z", "valid_to": None},
                    })
                    writer.decision({
                        "id": "dec:scope-test:read:20260820T100000Z:01",
                        "target_id": "tgt:scope-test",
                        "capability_id": "cap:scope-test:read",
                        "action": "RETROACTIVE_CORRECTION",
                        "claim_ids": ["clm:scope-test:read:unknown:correction"],
                        "effective_at": "2026-08-01T00:00:00Z",
                        "recorded_at": "2026-08-20T10:00:00Z",
                        "validity": {"valid_from": "2026-08-01T00:00:00Z", "valid_to": "2026-08-02T00:00:00Z"},
                    })

                with self.assertRaises(CorrectionScopeAmbiguityError):
                    memory.get_current_view_of_past(
                        "scope-test", "read", "2026-08-01T12:00:00Z"
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
