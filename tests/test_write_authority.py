"""Both legitimate write-authority origins, and fail-closed malformed state."""

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

from write_authority import (
    FRESH_INSTALL_WRITE_AUTHORITY_KIND,
    MIGRATED_WRITE_AUTHORITY_KIND,
    WriteAuthorityStateError,
    assert_om_write_authority,
    automatic_legacy_rollback_allowed,
    current_write_authority,
    write_authority_marker,
)


def _write(root: Path, payload: dict) -> None:
    marker = write_authority_marker(root)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(payload), encoding="utf-8")


MIGRATED = {
    "kind": MIGRATED_WRITE_AUTHORITY_KIND, "status": "ACTIVE",
    "previous_write_authority": "LEGACY", "write_authority": "OPERATIONAL_MEMORY",
    "om_authoritative_writes": 0, "first_om_write": "NOT_PERFORMED",
}
MIGRATED_AFTER_FIRST_WRITE = {
    **MIGRATED, "om_authoritative_writes": 1, "first_om_write": "PERFORMED",
    "first_om_write_receipt": "receipt.json", "first_om_write_receipt_sha256": "a" * 64,
}
# The canonical fresh-install shape: no om_authoritative_writes/first_om_write/
# receipt fields at all. Those record the historical Phase 4 migration's
# one-shot first-write ceremony; a fresh installation never runs it.
FRESH = {
    "kind": FRESH_INSTALL_WRITE_AUTHORITY_KIND, "status": "ACTIVE",
    "previous_write_authority": "NONE", "write_authority": "OPERATIONAL_MEMORY",
}


class WriteAuthorityCompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_migrated_authority_grants_om_writes_with_legacy_provenance(self) -> None:
        _write(self.root, MIGRATED)
        self.assertEqual("OPERATIONAL_MEMORY", current_write_authority(self.root))
        payload = assert_om_write_authority(self.root)
        self.assertEqual("LEGACY", payload["previous_write_authority"])

    def test_fresh_install_authority_grants_om_writes_without_legacy_fabrication(self) -> None:
        _write(self.root, FRESH)
        self.assertEqual("OPERATIONAL_MEMORY", current_write_authority(self.root))
        payload = assert_om_write_authority(self.root)
        self.assertEqual("NONE", payload["previous_write_authority"])
        self.assertNotIn("om_authoritative_writes", payload)
        self.assertNotIn("first_om_write", payload)

    def test_rollback_allowed_semantics_differ_by_provenance(self) -> None:
        # No marker at all: still LEGACY, nothing to roll back from.
        self.assertTrue(automatic_legacy_rollback_allowed(self.root))
        # Migrated, pre-first-write: rollback to LEGACY is still meaningful.
        _write(self.root, MIGRATED)
        self.assertTrue(automatic_legacy_rollback_allowed(self.root))
        # Migrated, after the historical first write: irreversible.
        _write(self.root, MIGRATED_AFTER_FIRST_WRITE)
        self.assertFalse(automatic_legacy_rollback_allowed(self.root))
        # Fresh install: never had LEGACY authority, so never "rollback
        # allowed" -- true from initialization onward, unaffected by how many
        # ordinary OM writes have since happened (fresh markers don't and
        # shouldn't track a write count).
        _write(self.root, FRESH)
        self.assertFalse(automatic_legacy_rollback_allowed(self.root))

    def test_migrated_marker_still_requires_first_write_ceremony_fields(self) -> None:
        incomplete = {k: v for k, v in MIGRATED.items() if k not in ("om_authoritative_writes", "first_om_write")}
        _write(self.root, incomplete)
        with self.assertRaises(WriteAuthorityStateError):
            current_write_authority(self.root)

    def test_absent_marker_is_legacy(self) -> None:
        self.assertEqual("LEGACY", current_write_authority(self.root))

    def test_fresh_install_marker_cannot_claim_legacy_provenance(self) -> None:
        _write(self.root, {**FRESH, "previous_write_authority": "LEGACY"})
        with self.assertRaises(WriteAuthorityStateError):
            current_write_authority(self.root)

    def test_migrated_marker_cannot_claim_no_prior_authority(self) -> None:
        _write(self.root, {**MIGRATED, "previous_write_authority": "NONE"})
        with self.assertRaises(WriteAuthorityStateError):
            current_write_authority(self.root)

    def test_unknown_kind_fails_closed(self) -> None:
        _write(self.root, {**FRESH, "kind": "made-up-kind"})
        with self.assertRaises(WriteAuthorityStateError):
            current_write_authority(self.root)

    def test_malformed_json_fails_closed(self) -> None:
        marker = write_authority_marker(self.root)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("{not json", encoding="utf-8")
        with self.assertRaises(WriteAuthorityStateError):
            current_write_authority(self.root)


if __name__ == "__main__":
    unittest.main()
