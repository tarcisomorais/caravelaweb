from pathlib import Path
import unittest


REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "SKILL.md"
SAFETY = REPO / "references" / "safety.md"


class RobotsPolicyTests(unittest.TestCase):
    def test_public_discovery_does_not_stop_for_named_bot_disallow(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        safety = SAFETY.read_text(encoding="utf-8")
        self.assertIn("`robots.txt` is not an executor-facing authority or stop condition", skill)
        self.assertIn("do not fetch it as a prerequisite", skill)
        self.assertIn("not an executor-facing gate", safety)
        self.assertIn("request `robots.txt` as a navigation prerequisite", safety)
        self.assertIn("`ClaudeBot`, `GPTBot`, `OAI-SearchBot`", safety)
        self.assertIn("Never invent or attribute a crawler token", safety)

    def test_real_boundaries_remain_binding(self) -> None:
        safety = SAFETY.read_text(encoding="utf-8")
        for boundary in ("authentication", "paywalls", "CAPTCHA", "technical blocking", "rate limits", "regional restrictions", "prohibition on evasion"):
            self.assertIn(boundary, safety)


if __name__ == "__main__":
    unittest.main()
