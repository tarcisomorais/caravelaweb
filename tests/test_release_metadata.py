"""The two plugin manifests and CHANGELOG.md must agree on the release version.

docs/installation.md promises that both manifests declare the same semantic
version and that public releases bump it together with CHANGELOG.md. This
test locks that promise so a manifest bump without a CHANGELOG heading (or a
version mismatch between manifests) fails the suite instead of drifting.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class ReleaseMetadataTests(unittest.TestCase):
    def test_manifest_versions_match_and_changelog_has_a_heading(self) -> None:
        claude_manifest = json.loads(
            (REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        codex_manifest = json.loads(
            (REPO / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        claude_version = claude_manifest["version"]
        codex_version = codex_manifest["version"]
        self.assertEqual(
            claude_version,
            codex_version,
            "the two plugin manifests must declare the same version",
        )

        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        headings = re.findall(r"^## (\S+)", changelog, flags=re.MULTILINE)
        self.assertIn(
            claude_version,
            headings,
            f"CHANGELOG.md has no '## {claude_version}' heading",
        )


if __name__ == "__main__":
    unittest.main()
