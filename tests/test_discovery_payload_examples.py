"""Every payload in references/discovery-payload-examples.md must finalize."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FINALIZER = REPO / "scripts" / "discovery-finalize"
BEGIN = REPO / "scripts" / "discovery-begin"
LOOKUP = REPO / "scripts" / "knowledge-lookup"
REFERENCE = REPO / "references" / "discovery-payload-examples.md"

from write_authority import MIGRATED_WRITE_AUTHORITY_KIND

sys.path.insert(0, str(REPO))
from operational_memory.core import SQLiteOperationalMemory

_JSON_BLOCK = re.compile(r"```json\n(.*?)\n```", re.S)


def _payloads() -> list[dict]:
    text = REFERENCE.read_text(encoding="utf-8")
    return [json.loads(match) for match in _JSON_BLOCK.findall(text)]


class DiscoveryPayloadExamplesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".caravelaweb").mkdir()
        (self.root / ".caravelaweb/write-authority.json").write_text(json.dumps({
            "kind": MIGRATED_WRITE_AUTHORITY_KIND, "status": "ACTIVE",
            "previous_write_authority": "LEGACY", "write_authority": "OPERATIONAL_MEMORY",
            "om_authoritative_writes": 0, "first_om_write": "NOT_PERFORMED",
        }), encoding="utf-8")
        (self.root / "targets").mkdir()
        with SQLiteOperationalMemory(
            self.root / ".caravelaweb/operational_memory.db", knowledge_root=self.root
        ):
            pass

    def test_the_reference_documents_at_least_the_seven_required_examples(self) -> None:
        self.assertGreaterEqual(len(_payloads()), 8)

    def test_every_documented_example_finalizes_successfully(self) -> None:
        for payload in _payloads():
            with self.subTest(target=payload["target"], capability=payload["capability"]):
                begun = subprocess.run(
                    [sys.executable, str(BEGIN), "--knowledge-root", str(self.root),
                     "--target", payload["target"], "--capability", payload["capability"]],
                    text=True, capture_output=True, encoding="utf-8",
                )
                self.assertEqual(0, begun.returncode, begun.stderr)
                payload["provenance"]["run_id"] = json.loads(begun.stdout)["run_id"]
                finalized = subprocess.run(
                    [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root),
                     "--input", "-"],
                    input=json.dumps(payload), text=True, capture_output=True, encoding="utf-8",
                )
                self.assertEqual(0, finalized.returncode, finalized.stderr)
                body = json.loads(finalized.stdout)
                self.assertEqual("SAVED", body["status"])
                self.assertEqual("CLOSED", body["run_state"])
                self.assertNotIn("warnings", body)

    def test_a_malformed_example_reports_a_reason_code(self):
        payload = _payloads()[0]
        observations = payload["observations"]
        payload["observations"] = [
            {**observations[0], "family": "nope"},
            *observations[1:],
        ]
        begun = subprocess.run(
            [sys.executable, str(BEGIN), "--knowledge-root", str(self.root),
             "--target", payload["target"], "--capability", payload["capability"]],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(0, begun.returncode, begun.stderr)
        payload["provenance"]["run_id"] = json.loads(begun.stdout)["run_id"]
        finalized = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root),
             "--input", "-"],
            input=json.dumps(payload), text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(2, finalized.returncode, finalized.stdout)
        body = json.loads(finalized.stderr)
        self.assertEqual("NOT_SAVED", body["status"])
        self.assertEqual("PAYLOAD_VALUE", body["reason_code"])
        self.assertIn("'nope'", body["reason"])

        # The wrapper is a closed contract too, and the run is still open:
        # an unknown top-level field reports the same shape code an unknown
        # nested field reports.
        payload["observations"] = observations
        payload["notes"] = "not part of the payload contract"
        rejected = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root),
             "--input", "-"],
            input=json.dumps(payload), text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(2, rejected.returncode, rejected.stdout)
        body = json.loads(rejected.stderr)
        self.assertEqual("NOT_SAVED", body["status"])
        self.assertEqual("PAYLOAD_SHAPE", body["reason_code"])
        self.assertIn("notes", body["reason"])

    def test_the_operational_example_earns_the_lifecycle(self) -> None:
        payload = next(
            item for item in _payloads() if item["target"] == "example-operational"
        )
        begun = subprocess.run(
            [sys.executable, str(BEGIN), "--knowledge-root", str(self.root),
             "--target", payload["target"], "--capability", payload["capability"]],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(0, begun.returncode, begun.stderr)
        payload["provenance"]["run_id"] = json.loads(begun.stdout)["run_id"]
        finalized = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(self.root),
             "--input", "-"],
            input=json.dumps(payload), text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(0, finalized.returncode, finalized.stderr)
        body = json.loads(finalized.stdout)
        self.assertEqual("SAVED", body["status"])
        self.assertEqual("OPERATIONAL", body["lifecycle"])
        looked_up = subprocess.run(
            [sys.executable, str(LOOKUP), "--knowledge-root", str(self.root),
             "--target", payload["target"], "--capability", payload["capability"],
             "--use-operational-memory"],
            text=True, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(0, looked_up.returncode, looked_up.stderr)
        looked_up_body = json.loads(looked_up.stdout)
        self.assertEqual("OPERATIONAL", looked_up_body["lifecycle"])


if __name__ == "__main__":
    unittest.main()
