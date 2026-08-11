"""Evidence probes for the native-Windows compatibility audit.

These pin down, as re-checkable facts, which runtime modules import without
`fcntl` and that the maintenance-only authority lock fails explicitly when the
platform does not provide it.
"""

from __future__ import annotations

import builtins
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[0]
SKILL = REPO


def _run_without_fcntl(source: str) -> subprocess.CompletedProcess[str]:
    """Run source with `import fcntl` forced to fail.

    Runs in a subprocess so the simulated absence of `fcntl` cannot leak into
    (or be polluted by) this test process's real module cache.
    """
    script = (
        "import sys, builtins\n"
        f"sys.path.insert(0, {str(SKILL)!r})\n"
        "real_import = builtins.__import__\n"
        "def fake_import(name, *a, **k):\n"
        "    if name == 'fcntl':\n"
        "        raise ModuleNotFoundError(\"No module named 'fcntl'\")\n"
        "    return real_import(name, *a, **k)\n"
        "builtins.__import__ = fake_import\n"
        + source
    )
    return subprocess.run(
        [sys.executable, "-c", script], text=True, capture_output=True
    )


class WindowsCompatProbeTests(unittest.TestCase):
    def test_active_modules_import_without_fcntl(self) -> None:
        for module_name in (
            "discovery_finalize",
            "integration_bridge",
            "om_native_writes",
            "write_authority",
        ):
            with self.subTest(module=module_name):
                result = _run_without_fcntl(f"import {module_name}\n")
                self.assertEqual(0, result.returncode, result.stderr)

    def test_read_only_modules_do_not_require_fcntl(self) -> None:
        # These do not import write_authority and should remain importable
        # even without fcntl -- confirming the blocker is localized to the
        # write-authority lock, not a repo-wide POSIX dependency.
        for module_name in (
            "operational_memory.core",
            "knowledge_write_freeze",
            "read_authority",
        ):
            with self.subTest(module=module_name):
                result = _run_without_fcntl(f"import {module_name}\n")
                self.assertEqual(0, result.returncode, result.stderr)

    def test_authority_lock_fails_explicitly_without_fcntl(self) -> None:
        result = _run_without_fcntl(
            "from write_authority import authority_lock, AuthorityLockUnavailableError\n"
            "try:\n"
            "    with authority_lock('.', exclusive=True):\n"
            "        pass\n"
            "except AuthorityLockUnavailableError:\n"
            "    pass\n"
            "else:\n"
            "    raise AssertionError('authority lock unexpectedly available')\n"
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_scripts_directory_uses_extensionless_python_shebangs(self) -> None:
        # Confirms the CLI entry points rely on `#!/usr/bin/env python3` +
        # the executable bit + no file extension -- a combination that
        # PowerShell/cmd.exe cannot invoke directly (no shebang support, no
        # file association for extensionless files).
        scripts_dir = SKILL / "scripts"
        scripts = [p for p in scripts_dir.iterdir() if p.is_file() and p.suffix == ""]
        self.assertTrue(scripts, "expected extensionless scripts under scripts/")
        for script in scripts:
            with self.subTest(script=script.name):
                first_line = script.read_text(encoding="utf-8").splitlines()[0]
                self.assertTrue(first_line.startswith("#!"), f"{script.name} has no shebang")


if __name__ == "__main__":
    unittest.main()
