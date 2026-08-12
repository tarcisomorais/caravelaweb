"""The skill-selection description stays identical across all three copies.

`SKILL.md` is the canonical contract; `.claude/skills/caravelaweb/SKILL.md` and
`.agents/skills/caravelaweb/SKILL.md` are thin discovery adapters that hold no
runtime code and defer to the root file for content. Their frontmatter
`description` is what a host's skill matcher actually reads to decide whether
CaravelaWeb applies to a task, so a copy that drifts from the root silently
changes skill selection without changing the contract. This is a targeted
parity gate over the frontmatter block only, not a full-file diff -- the
adapter bodies are intentionally different from the root contract.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

DESCRIPTION_FILES = (
    REPO / "SKILL.md",
    REPO / ".claude" / "skills" / "caravelaweb" / "SKILL.md",
    REPO / ".agents" / "skills" / "caravelaweb" / "SKILL.md",
)

DESCRIPTION_RE = re.compile(r"^description:\s*(.+)$", re.MULTILINE)


def frontmatter_description(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = DESCRIPTION_RE.search(text)
    assert match, f"no frontmatter description found in {path}"
    return match.group(1).strip()


class SkillAdapterParityTests(unittest.TestCase):
    def test_frontmatter_description_is_identical_across_all_copies(self) -> None:
        descriptions = {path: frontmatter_description(path) for path in DESCRIPTION_FILES}
        distinct = set(descriptions.values())
        self.assertEqual(
            1,
            len(distinct),
            f"frontmatter description drifted: {descriptions}",
        )

    def test_description_covers_live_web_target_scope_not_only_marketplace_lookups(self) -> None:
        description = frontmatter_description(REPO / "SKILL.md")
        self.assertIn("reads, navigates, or acts on a live web target", description)
        self.assertIn("QA, verification, or one-off checks", description)


if __name__ == "__main__":
    unittest.main()
