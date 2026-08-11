from __future__ import annotations

import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "SKILL.md"
TRANSPORT = REPO / "references" / "transport-and-modes.md"


class DiscoveryEnforcementContractTests(unittest.TestCase):
    def test_discovery_requires_the_finalizer_before_completion(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("If a run entered **Discovery**, it must call `scripts/discovery-finalize`", text)
        self.assertIn("before it can be declared complete", text)
        self.assertIn("`SALVA`", text)
        self.assertIn("`JÁ_EXISTENTE`", text)
        self.assertIn("`NÃO_SALVA`", text)

    def test_operation_is_exempt_and_finalizer_failure_is_incomplete(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("Runs that stayed in **Operation** do not call the finalizer", text)
        self.assertIn("**Discovery finalization is incomplete**", text)
        self.assertIn("must never be silently described as a completed Discovery", text)

    def test_task_data_remains_outside_operational_memory(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        for forbidden in ("found articles", "shop lists", "current results or prices", "raw logs", "complete HTML"):
            self.assertIn(forbidden, text)
        self.assertIn("**FINALIZE (mandatory)**", TRANSPORT.read_text(encoding="utf-8"))

    def test_direct_work_stops_by_required_field_coverage(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        for rule in (
            "Start with one suitable direct implementation",
            "stop by field coverage",
            "classify every required field as directly confirmed",
            "inferred with uncertainty explicit",
            "contradictory and reported",
            "unconfirmed after sufficient search of relevant permitted surfaces",
            "inaccessible because of an observed constraint",
            "do not impose a global maximum",
            "at most one planned refinement by default",
            "schema-only rejection",
            "never repeat navigation or extraction",
        ):
            self.assertIn(rule, text)
        self.assertLessEqual(len(text.splitlines()), 125)

    def test_one_page_absence_does_not_end_permitted_search(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("Absence from one page is not evidence of absence from the permitted scope", text)
        self.assertIn("relevant permitted surfaces already discovered", text)
        self.assertIn("limited search for another relevant surface", text)
        self.assertIn("no pending link, result, documentation, or contradiction", text)
        self.assertIn("unexamined permitted source", text)
        self.assertIn("permit reporting absence rather than estimating", text)

    def test_additional_calls_must_add_coverage_or_confidence(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("incomplete, ambiguous, or contradictory field", text)
        self.assertIn("distinct source or evidence", text)
        self.assertIn("materially increase confidence", text)
        self.assertIn("plausibly complementary permitted source is distinct coverage", text)
        self.assertIn("do not revalidate a supported field", text)

    def test_same_content_reread_targets_a_concrete_gap(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("Do not reread the same page through another implementation", text)
        self.assertIn("target a concrete field or passage", text)
        self.assertIn("truncated, summarized, omitted, left ambiguous or contradictory", text)

    def test_routes_need_observed_evidence(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("Do not guess endpoints or paths from heuristics alone", text)
        self.assertIn("real link, observed redirect, search result, documentation, sitemap/index", text)
        self.assertIn("inspect links or run a limited search first", text)

    def test_legitimate_multi_source_investigation_remains_allowed(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        for allowed in (
            "complementary permitted sources",
            "contradiction resolution",
            "transport escalation after observed failure",
            "browser use for JavaScript",
            "omitted-detail extraction",
            "extra validation for sensitive tasks or weak evidence",
        ):
            self.assertIn(allowed, text)

    def test_transport_and_mode_invariants_remain_visible(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("DIRECT_READ -> LIGHTPANDA -> CHROME", text)
        self.assertIn("After Chrome-based Discovery, SIMPLIFY is mandatory", text)
        self.assertIn("Runs that stayed in **Operation** do not call the finalizer", text)


if __name__ == "__main__":
    unittest.main()
