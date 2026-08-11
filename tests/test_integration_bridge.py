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

NOW = "2026-07-26T16:00:00Z"
RECORDED_AT = "2026-07-26T12:00:00Z"


class IntegrationBridgeRuntimeLookupTests(unittest.TestCase):
    """Public lookup surface of the runtime bridge script.

    Seeded directly through Operational Memory write primitives rather than
    a legacy corpus/importer: legacy_fixture and legacy_profile_adapter are
    both excluded from this repo (they only ever supported the historical
    migration path), but the runtime bridge's controlled-lookup contract
    still needs coverage.
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


class IntegrationBridgePublicInterfaceTests(unittest.TestCase):
    """integration_bridge must not re-export legacy_profile_adapter parsing symbols."""

    LEGACY_NAMES = (
        "ImportResult",
        "ParsedLegacyProfile",
        "SemanticItem",
        "import_legacy_profile",
        "parse_legacy_profile",
        "semantic_round_trip",
    )

    def test_legacy_parsing_symbols_are_not_reexported(self) -> None:
        import integration_bridge

        for name in self.LEGACY_NAMES:
            self.assertNotIn(name, integration_bridge.__all__)
            self.assertFalse(hasattr(integration_bridge, name))


if __name__ == "__main__":
    unittest.main(verbosity=2)
