from __future__ import annotations

import json
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO
PREFLIGHT = SKILL / "scripts" / "preflight"
sys.path.insert(0, str(SKILL))

from operational_memory import SQLiteOperationalMemory
from write_authority import MIGRATED_WRITE_AUTHORITY_KIND


class PreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / ".caravelaweb-knowledge-root").write_text("\n", encoding="utf-8")
        (self.root / "targets").mkdir()
        state = self.root / ".caravelaweb"
        state.mkdir()
        with SQLiteOperationalMemory(state / "operational_memory.db"):
            pass
        (state / "read-authority-operational-memory").write_text("active\n", encoding="utf-8")
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

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_preflight(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(PREFLIGHT), *arguments],
            text=True,
            capture_output=True,
        )

    def test_json_report_is_ready_and_read_only(self) -> None:
        before = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        result = self.run_preflight("--knowledge-root", str(self.root), "--json")
        after = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual("READY", report["status"])
        self.assertEqual("AVAILABLE", report["transports"]["DIRECT_READ"]["status"])
        self.assertEqual(2, report["operational_memory"]["schema_version"])
        self.assertEqual(before, after)

    def test_human_report_and_missing_database_fail_specifically(self) -> None:
        (self.root / ".caravelaweb" / "operational_memory.db").unlink()
        result = self.run_preflight("--knowledge-root", str(self.root))
        self.assertEqual(2, result.returncode)
        self.assertIn("status: NOT_READY", result.stdout)
        self.assertIn("Operational Memory database is absent", result.stdout)

    def test_root_requires_exact_targets_case(self) -> None:
        (self.root / "targets").rename(self.root / "Targets")
        result = self.run_preflight("--knowledge-root", str(self.root), "--json")
        self.assertEqual(2, result.returncode)
        self.assertEqual("NOT_READY", json.loads(result.stdout)["status"])

    def test_boundary_warning_is_informational(self) -> None:
        root_warning = runpy.run_path(str(PREFLIGHT))["_root_warning"]
        wsl_warning = root_warning(
            Path("/mnt/c/knowledge"), "boundary-crossing", platform_name="linux"
        )
        windows_warning = root_warning(
            Path("//wsl.localhost/Ubuntu/knowledge"),
            "boundary-crossing",
            platform_name="win32",
        )
        self.assertIn("disk I/O failure", wsl_warning)
        self.assertIn("SQLite lock failures", windows_warning)
        self.assertIn("does not refuse", wsl_warning)
        self.assertIn("does not refuse", windows_warning)


if __name__ == "__main__":
    unittest.main()
