from __future__ import annotations

import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "SKILL.md"
TRANSPORT = REPO / "references" / "transport-and-modes.md"
TARGET_PROFILE = REPO / "references" / "target-profile.md"


class DiscoveryEnforcementContractTests(unittest.TestCase):
    def test_discovery_requires_the_finalizer_before_completion(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("If a run entered **Discovery**, it must call `scripts/discovery-finalize`", text)
        self.assertIn("before it can be declared complete", text)
        self.assertIn("`SAVED`", text)
        self.assertIn("`ALREADY_EXISTS`", text)
        self.assertIn("`NOT_SAVED`", text)

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

    def test_live_web_target_scope_is_not_exempted_by_task_shape(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("Any task that reads, navigates, or acts on a live web target is in scope here", text)
        self.assertIn("not ruled out for being read-only, quick, QA, one-off", text)
        self.assertIn("Skip this skill only when no live web target is involved at all", text)

    def test_skill_line_budget_is_preserved(self) -> None:
        self.assertLessEqual(len(SKILL.read_text(encoding="utf-8").splitlines()), 125)

    def test_capability_identity_is_procedure_not_result(self) -> None:
        text = TARGET_PROFILE.read_text(encoding="utf-8")
        self.assertIn("Reusability is a property of the\nprocedure, never of the result", text)
        self.assertIn("even though its result differs every run", text)
        self.assertIn(
            "Capability identity stays semantic\n-- never equated with a page, origin, transport, or the current result",
            text,
        )

    def test_unfinalized_observation_is_not_accepted_knowledge(self) -> None:
        text = TARGET_PROFILE.read_text(encoding="utf-8")
        self.assertIn("accepted Operational Memory only once `discovery-finalize` succeeds", text)
        self.assertIn("never accepted knowledge", text)
        self.assertIn("never substitutes for lookup or Discovery on a later task", text)

    def test_discovery_delivers_the_real_task_not_a_dry_run(self) -> None:
        text = TRANSPORT.read_text(encoding="utf-8")
        self.assertIn("Discovery executes and delivers the caller's actual task while it learns", text)
        self.assertIn("not a preparatory or throwaway run before the real work", text)


if __name__ == "__main__":
    unittest.main()
