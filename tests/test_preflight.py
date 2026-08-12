from __future__ import annotations

import json
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def browser_diagnostics(
        self,
        commands: dict[str, str],
        *,
        version_returncode: int = 0,
        version: str = "agent-browser 1.0",
    ) -> dict[str, object]:
        api = runpy.run_path(str(PREFLIGHT))
        completed = subprocess.CompletedProcess(
            ["agent-browser", "--version"], version_returncode, stdout=version, stderr=""
        )
        with patch.object(api["shutil"], "which", side_effect=lambda name: commands.get(name)), patch.object(
            api["subprocess"], "run", return_value=completed
        ) as probe:
            result = api["_browser_diagnostics"](platform_name="win32")
        self.assertEqual(
            [[commands["agent-browser"], "--version"]] if "agent-browser" in commands else [],
            [call.args[0] for call in probe.call_args_list],
        )
        return result

    def test_json_report_is_ready_and_read_only(self) -> None:
        before = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        result = self.run_preflight("--knowledge-root", str(self.root), "--json")
        after = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual("READY", report["status"])
        self.assertEqual("AVAILABLE", report["transports"]["DIRECT_READ"]["status"])
        self.assertIn(report["browser_coverage"]["status"], {"COMPLETE", "INCOMPLETE"})
        self.assertEqual("NOT_CHECKED", report["browser_coverage"]["launch_runtime"])
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

    def test_windows_chrome_location_is_detected_without_path(self) -> None:
        program_files = self.root / "Program Files"
        chrome = program_files / "Google" / "Chrome" / "Application" / "chrome.exe"
        chrome.parent.mkdir(parents=True)
        chrome.touch()
        api = runpy.run_path(str(PREFLIGHT))
        with patch.dict(api["os"].environ, {"ProgramFiles": str(program_files)}, clear=True), patch.object(
            api["shutil"], "which", return_value=None
        ):
            engine = api["_chrome_engine"](platform_name="win32")
        self.assertEqual({"state": "DETECTED", "path": str(chrome)}, engine)

    def test_windows_browser_prerequisite_matrix_is_machine_readable(self) -> None:
        chrome = {"chrome": "/tools/chrome"}
        cases = (
            ({**chrome}, "DETECTED", "BROWSER_CONTROL_MISSING"),
            ({"agent-browser": "/tools/agent-browser"}, "NOT_DETECTED", "BROWSER_ENGINE_NOT_DETECTED"),
            ({**chrome, "agent-browser": "/tools/agent-browser"}, "DETECTED", None),
        )
        for commands, engine, reason in cases:
            with self.subTest(commands=commands):
                report = self.browser_diagnostics(commands)
                self.assertEqual(engine, report["browser_engine"]["state"])
                self.assertEqual(reason, report["browser_coverage"]["reason"])
                self.assertEqual("AVAILABLE" if reason is None else "UNAVAILABLE", report["transports"]["CHROME"]["status"])
                self.assertEqual("PLATFORM_UNSUPPORTED", report["transports"]["LIGHTPANDA"]["status"])

    def test_broken_agent_browser_and_edge_do_not_enable_chrome(self) -> None:
        broken = self.browser_diagnostics(
            {"agent-browser": "/tools/agent-browser", "chrome": "/tools/chrome"}, version_returncode=1
        )
        self.assertEqual("BROKEN", broken["browser_control"]["agent_browser"])
        self.assertEqual("BROWSER_CONTROL_BROKEN", broken["transports"]["CHROME"]["reason"])

        edge_only = self.browser_diagnostics({"agent-browser": "/tools/agent-browser", "msedge.exe": "/tools/msedge.exe"})
        self.assertEqual("NOT_DETECTED", edge_only["browser_engine"]["state"])
        self.assertEqual("BROWSER_ENGINE_NOT_DETECTED", edge_only["browser_coverage"]["reason"])

    def test_optional_browser_states_do_not_change_core_ready(self) -> None:
        api = runpy.run_path(str(PREFLIGHT))
        for commands in (
            {},
            {"agent-browser": "/tools/agent-browser"},
            {"chrome": "/tools/chrome"},
            {"agent-browser": "/tools/agent-browser", "chrome": "/tools/chrome"},
        ):
            with self.subTest(commands=commands):
                api["_browser_diagnostics"] = lambda: self.browser_diagnostics(commands)
                report = api["build_report"](str(self.root))
                self.assertEqual("READY", report["status"])


if __name__ == "__main__":
    unittest.main()
