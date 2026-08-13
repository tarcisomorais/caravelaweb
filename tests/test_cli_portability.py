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
BEGIN = SKILL / "scripts" / "discovery-begin"
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
            def open_run(body):
                opened = subprocess.run([
                    sys.executable, str(BEGIN), "--knowledge-root", str(root),
                    "--target", body["target"], "--capability", body["capability"],
                ], capture_output=True, env=environment)
                self.assertEqual(0, opened.returncode, opened.stderr.decode("utf-8"))
                body["provenance"]["run_id"] = json.loads(
                    opened.stdout.decode("utf-8")
                )["run_id"]
                payload.write_text(json.dumps(body), encoding="utf-8")

            command = [
                sys.executable,
                str(FINALIZER),
                "--knowledge-root",
                str(root),
                "--input",
                str(payload),
            ]
            body = json.loads(payload.read_text(encoding="utf-8"))
            open_run(body)
            first = subprocess.run(command, capture_output=True, env=environment)
            open_run(body)
            second = subprocess.run(command, capture_output=True, env=environment)
            self.assertEqual("SAVED", json.loads(first.stdout.decode("utf-8"))["status"])
            self.assertEqual("ALREADY_EXISTS", json.loads(second.stdout.decode("utf-8"))["status"])

            body["target"] = "utf8-empty"
            body["observations"] = []
            body["evidence"] = []
            open_run(body)
            empty = subprocess.run(command, capture_output=True, env=environment)
            self.assertEqual("NOT_SAVED", json.loads(empty.stdout.decode("utf-8"))["status"])


if __name__ == "__main__":
    unittest.main()
