"""Clone-to-ready agent-host discovery, checked structurally.

A fresh clone must be usable by a supported agent host without any user-home
installation. That depends on tracked files: root instruction files, and one
thin skill-discovery adapter per host convention. These tests assert the shape
of that surface -- never the internals of a third-party host.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

ADAPTERS = (
    Path(".claude/skills/caravelaweb/SKILL.md"),  # Claude Code, and OpenCode
    Path(".agents/skills/caravelaweb/SKILL.md"),  # Codex, and OpenCode
)

# Directories a thin adapter must never re-create beside itself.
RUNTIME_TREES = ("scripts", "references", "operational_memory")


def frontmatter_name(path: Path) -> str | None:
    match = re.match(r"^---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.DOTALL)
    if not match:
        return None
    name = re.search(r"^name:\s*(\S+)\s*$", match.group(1), re.MULTILINE)
    return name.group(1) if name else None


def tracked() -> set[str]:
    output = subprocess.run(
        ["git", "-C", str(REPO), "ls-files"],
        text=True, capture_output=True, check=True,
    ).stdout
    return set(output.splitlines())


class AgentHostIntegrationTests(unittest.TestCase):
    def test_repository_root_stays_the_canonical_skill(self) -> None:
        self.assertEqual("caravelaweb", frontmatter_name(REPO / "SKILL.md"))

    def test_project_local_discovery_files_are_tracked(self) -> None:
        files = tracked()
        for relative in (Path("AGENTS.md"), Path("CLAUDE.md"), *ADAPTERS):
            with self.subTest(file=relative):
                self.assertTrue((REPO / relative).is_file(), f"missing: {relative}")
                # A .gitignore rule that hides an adapter breaks a fresh clone
                # while leaving this working tree healthy.
                self.assertIn(relative.as_posix(), files, f"untracked: {relative}")

    def test_adapters_are_thin_and_defer_to_the_repository_root(self) -> None:
        for relative in ADAPTERS:
            with self.subTest(adapter=relative):
                path = REPO / relative
                self.assertEqual("caravelaweb", frontmatter_name(path))
                body = path.read_text(encoding="utf-8")
                self.assertIn("canonical contract is `SKILL.md` at the repository root", body)
                self.assertIn("repository root", body)

                siblings = {child.name for child in path.parent.iterdir()}
                self.assertEqual({"SKILL.md"}, siblings, f"adapter is not thin: {siblings}")
                for tree in RUNTIME_TREES:
                    self.assertFalse(
                        (path.parent / tree).exists(),
                        f"duplicated runtime tree beside adapter: {tree}",
                    )

    def test_no_nested_historical_skill_root_returns(self) -> None:
        nested = [name for name in tracked() if "skills" in Path(name).parts]
        self.assertEqual(
            sorted(relative.as_posix() for relative in ADAPTERS),
            sorted(nested),
            "only the host discovery adapters may live under a nested skills/ path",
        )

    def test_bootstrap_files_stay_concise_and_share_one_policy(self) -> None:
        agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
        claude = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertLess(len(agents.splitlines()), 60)
        self.assertLess(len(claude.splitlines()), 20)
        # Claude Code does not read AGENTS.md; the text import keeps one policy
        # document without a Windows-hostile symlink.
        self.assertIn("@AGENTS.md", claude)


if __name__ == "__main__":
    unittest.main()
