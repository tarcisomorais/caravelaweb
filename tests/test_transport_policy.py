from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))

from discovery_finalize import DiscoveryFinalizationError, _normalize_observations
from operational_memory import SQLiteOperationalMemory
from transport_policy import (
    AVAILABLE,
    CHROME,
    DIRECT_READ,
    INSUFFICIENT,
    LIGHTPANDA,
    PLATFORM_UNSUPPORTED,
    SATISFIED,
    TransportPolicyError,
    next_transport,
    platform_limit_report,
    simplify_transports,
)


class TransportPolicyTests(unittest.TestCase):
    def test_direct_read_is_always_first(self) -> None:
        self.assertEqual(
            DIRECT_READ,
            next_transport({}, {LIGHTPANDA: AVAILABLE, CHROME: AVAILABLE}),
        )

    def test_chrome_follows_direct_when_lightpanda_cannot_exist(self) -> None:
        self.assertEqual(
            CHROME,
            next_transport(
                {DIRECT_READ: INSUFFICIENT},
                {LIGHTPANDA: PLATFORM_UNSUPPORTED, CHROME: AVAILABLE},
            ),
        )

    def test_chrome_is_unreachable_without_a_direct_attempt(self) -> None:
        with self.assertRaisesRegex(TransportPolicyError, "DIRECT_READ must be attempted first"):
            next_transport(
                {CHROME: SATISFIED},
                {LIGHTPANDA: PLATFORM_UNSUPPORTED, CHROME: AVAILABLE},
            )

    def test_platform_limit_is_not_knowledge_or_degradation(self) -> None:
        report = platform_limit_report("example", LIGHTPANDA, "win32")
        self.assertEqual([], report["knowledge_observations"])
        self.assertFalse(report["target_degraded"])
        self.assertNotIn(LIGHTPANDA, simplify_transports({LIGHTPANDA: PLATFORM_UNSUPPORTED}))

    def test_platform_runtime_state_is_rejected_at_the_write_boundary(self) -> None:
        with self.assertRaisesRegex(DiscoveryFinalizationError, "platform runtime state"):
            _normalize_observations(
                [{"family": "transport", "value": {"transport": PLATFORM_UNSUPPORTED}}]
            )

    def test_platform_limit_leaves_operational_memory_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "memory.db"
            with SQLiteOperationalMemory(db) as memory:
                with memory.write_transaction() as writer:
                    writer.target({"id": "tgt:example", "name": "Example"})
            before = db.read_bytes()
            report = platform_limit_report("example", LIGHTPANDA, "win32")
            self.assertEqual([], report["knowledge_observations"])
            self.assertEqual(before, db.read_bytes())


if __name__ == "__main__":
    unittest.main()
