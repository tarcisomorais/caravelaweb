"""The skill-selection description stays identical across all four copies.

`SKILL.md` is the canonical contract; `skills/caravelaweb/SKILL.md`,
`.claude/skills/caravelaweb/SKILL.md`, and
`.agents/skills/caravelaweb/SKILL.md` are thin discovery adapters that hold no
runtime code and defer to the root file for content. Their frontmatter
`description` is what a host's skill matcher actually reads to decide whether
CaravelaWeb applies to a task, so a copy that drifts from the root silently
changes skill selection without changing the contract. This is a targeted
parity gate over the frontmatter block only, not a full-file diff -- the
adapter bodies are intentionally different from the root contract.

The second gate below pins one piece of root `SKILL.md` body text: the
pre-finalize checklist. It exists because the checklist is the cheapest
defence against the four payload traps that produced most Discovery
refusals, and a silent deletion would restore them without failing anything.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

DESCRIPTION_FILES = (
    REPO / "SKILL.md",
    REPO / "skills" / "caravelaweb" / "SKILL.md",
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


class SkillLookupStepTests(unittest.TestCase):
    """Step 2 mandates one lookup call and reads the index it returns."""

    def test_step_two_pins_the_single_combined_call(self) -> None:
        skill = (REPO / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("index_scope", skill)
        self.assertIn(
            "scripts/knowledge-lookup --target <target-id> --capability <capability>",
            skill,
        )
        self.assertNotIn("once per task and read the exact IDs it returns", skill)


class SkillPreFinalizeChecklistTests(unittest.TestCase):
    def test_skill_md_carries_the_pre_finalize_checklist_and_keeps_validate_optional(self) -> None:
        skill = (REPO / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("**Before you finalize**", skill)
        self.assertNotIn("before every real finalize", skill)


if __name__ == "__main__":
    unittest.main()
