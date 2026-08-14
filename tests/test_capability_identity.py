from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from discovery_finalize import DiscoveryFinalizationError, finalize_discovery
from integration_bridge import KnowledgeLookupBoundary
from operational_memory import RecordValidationError, SQLiteOperationalMemory
from operational_memory.core import normalize_capability_id
from write_authority import MIGRATED_WRITE_AUTHORITY_KIND

RECORDED = "2026-08-12T12:00:00Z"


class CapabilityIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        state = self.root / ".caravelaweb"
        state.mkdir()
        (self.root / "targets").mkdir()
        (state / "write-authority.json").write_text(json.dumps({
            "kind": MIGRATED_WRITE_AUTHORITY_KIND, "status": "ACTIVE",
            "previous_write_authority": "LEGACY", "write_authority": "OPERATIONAL_MEMORY",
            "om_authoritative_writes": 0, "first_om_write": "NOT_PERFORMED",
        }), encoding="utf-8")
        (state / "read-authority-operational-memory").write_text("active", encoding="utf-8")
        self.memory = SQLiteOperationalMemory(
            state / "operational_memory.db", knowledge_root=self.root
        )
        self.addCleanup(self.memory.close)

    def finalize(self, capability: str, run: str = "001"):
        return finalize_discovery(
            self.memory, target="synthetic-academy", capability=capability,
            observations=[{
                "family": "extraction",
                "value": {
                    "structure": "INSTRUCTOR_CARDS",
                    "field_paths": {"name": "cards[].name"},
                },
            }],
            evidence=[{"kind": "synthetic-validation", "locator": "https://academy.example/instructors"}],
            provenance={"run_id": f"run:capability:{run}", "observed_at": RECORDED},
            recorded_at=RECORDED,
        )

    def test_lower_kebab_normalization_converges_and_rejects_empty(self) -> None:
        variants = ("Instructor List", "instructor-list", "instructor_list", "instructor / list")
        self.assertEqual({"instructor-list"}, {normalize_capability_id(value) for value in variants})
        for value in ("", " / _ "):
            with self.subTest(value=value), self.assertRaises(RecordValidationError):
                normalize_capability_id(value)

    def test_semantic_synonyms_remain_distinct(self) -> None:
        values = ("instructors", "coaches", "team", "instructor-directory")
        self.assertEqual(set(values), {normalize_capability_id(value) for value in values})

    def test_lookup_and_finalization_use_identical_normalization(self) -> None:
        self.assertEqual("SAVED", self.finalize("Instructor List").status)
        self.assertEqual("ALREADY_EXISTS", self.finalize("instructor_list", "002").status)
        lookup = KnowledgeLookupBoundary(self.root)
        for value in ("Instructor List", "instructor-list", "instructor_list"):
            with self.subTest(value=value):
                result = lookup.lookup("synthetic-academy", capability=value)
                self.assertEqual("instructor-list", result.capability)
                self.assertIsNotNone(result.operational_context)

    def test_target_only_lookup_exposes_distinct_accepted_capability_ids(self) -> None:
        for index, capability in enumerate(("instructors", "coaches", "team")):
            self.assertEqual("SAVED", self.finalize(capability, str(index)).status)
        result = KnowledgeLookupBoundary(self.root).lookup("synthetic-academy")
        self.assertEqual(
            {"instructors", "coaches", "team"},
            set(result.operational_context["capabilities"]),
        )

    def test_task_results_cannot_supply_capability_identity(self) -> None:
        with self.assertRaises(DiscoveryFinalizationError):
            finalize_discovery(
                self.memory, target="synthetic-academy", capability=" / _ ",
                observations=[{
                    "family": "extraction",
                    "value": {"results": ["Ada Example", "Grace Example"]},
                }],
                evidence=[{"kind": "synthetic-validation", "locator": "https://academy.example/instructors"}],
                provenance={"run_id": "run:capability:results", "observed_at": RECORDED},
                recorded_at=RECORDED,
            )
        self.assertEqual(
            0,
            self.memory._conn.execute("SELECT count(*) FROM capabilities").fetchone()[0],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
