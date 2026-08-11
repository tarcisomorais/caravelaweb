from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO
FINALIZER = SKILL / "scripts" / "discovery-finalize"
sys.path.insert(0, str(SKILL))

from operational_memory import SQLiteOperationalMemory
from write_authority import MIGRATED_WRITE_AUTHORITY_KIND


class CliPortabilityTests(unittest.TestCase):
    def test_finalizer_forces_utf8_under_a_non_utf8_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".caravelaweb-knowledge-root").write_text("\n", encoding="utf-8")
            (root / "targets").mkdir()
            state = root / ".caravelaweb"
            state.mkdir()
            with SQLiteOperationalMemory(state / "operational_memory.db"):
                pass
            (state / "write-authority.json").write_text(
                json.dumps(
                    {
                        "kind": MIGRATED_WRITE_AUTHORITY_KIND,
                        "status": "ACTIVE",
                        "write_authority": "OPERATIONAL_MEMORY",
                        "previous_write_authority": "LEGACY",
                        "om_authoritative_writes": 0,
                        "first_om_write": "NOT_PERFORMED",
                    }
                ),
                encoding="utf-8",
            )
            payload = root / "discovery.json"
            payload.write_text(
                json.dumps(
                    {
                        "target": "utf8-probe",
                        "capability": "public-homepage",
                        "observations": [
                            {
                                "family": "transport",
                                "value": {
                                    "transport": "DIRECT_READ",
                                    "outcome": "FUNCTIONAL",
                                },
                            }
                        ],
                        "evidence": [
                            {
                                "kind": "direct-read-validation",
                                "locator": "https://example.com/",
                            }
                        ],
                        "provenance": {
                            "run_id": "run:utf8:001",
                            "observed_at": "2026-08-08T00:00:00Z",
                        },
                    }
                ),
                encoding="utf-8",
            )
            environment = {**os.environ, "PYTHONIOENCODING": "cp1252"}
            command = [
                sys.executable,
                str(FINALIZER),
                "--knowledge-root",
                str(root),
                "--input",
                str(payload),
            ]
            first = subprocess.run(command, capture_output=True, env=environment)
            second = subprocess.run(command, capture_output=True, env=environment)
            self.assertEqual("SALVA", json.loads(first.stdout.decode("utf-8"))["status"])
            self.assertEqual("JÁ_EXISTENTE", json.loads(second.stdout.decode("utf-8"))["status"])

            body = json.loads(payload.read_text(encoding="utf-8"))
            body["target"] = "utf8-empty"
            body["observations"] = []
            body["evidence"] = []
            payload.write_text(json.dumps(body), encoding="utf-8")
            empty = subprocess.run(command, capture_output=True, env=environment)
            self.assertEqual("NÃO_SALVA", json.loads(empty.stdout.decode("utf-8"))["status"])


if __name__ == "__main__":
    unittest.main()
