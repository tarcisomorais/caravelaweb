from __future__ import annotations

import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "SKILL.md"
TRANSPORT = REPO / "references" / "transport-and-modes.md"
TARGET_PROFILE = REPO / "references" / "target-profile.md"
SAFETY = REPO / "references" / "safety.md"

# The contract is loaded on every CaravelaWeb task, so its length is capped
# deliberately rather than allowed to drift. Detail belongs in references/.
# Raised from 125 when the First run readiness sequence moved into the
# contract: it must be read before the first command, so a reference file
# cannot carry it. Raised again from 140 for the blocked-ladder stop rule: an
# agent decides whether to leave CaravelaWeb at the moment a transport is
# blocked, which is before it would open a reference file.
SKILL_LINE_BUDGET = 143


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
        self.assertIn("Operation calls neither `discovery-begin` nor `discovery-finalize`", text)
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
        self.assertLessEqual(len(text.splitlines()), SKILL_LINE_BUDGET)

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
        self.assertIn("Operation calls neither `discovery-begin` nor `discovery-finalize`", text)
        self.assertIn("`transport_trace` is required", text)
        self.assertIn("never stored as Claims or other target knowledge", text)

    def test_a_blocked_ladder_stops_instead_of_switching_to_another_tool(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("report the block and stop", text)
        self.assertIn("A blocked capability may simply remain unsupported", text)
        for substitute in (
            "web-search tool", "an external index", "a cached or mirrored copy",
        ):
            self.assertIn(substitute, text)
        self.assertIn("none of them is a CaravelaWeb transport", text)
        # The same stop is stated where an agent classifies the block and where
        # it reads the blocking policy, not only in the contract.
        transport = TRANSPORT.read_text(encoding="utf-8")
        self.assertIn("**Stopping means stopping.**", transport)
        self.assertIn("None of them is a transport in this hierarchy", transport)
        safety = SAFETY.read_text(encoding="utf-8")
        self.assertIn(
            "Routing around the block is the same decision as bypassing it", safety
        )
        self.assertIn("third-party republisher", safety)

    def test_search_output_is_a_lead_and_never_target_evidence(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("only a read of a target surface supports a claim about the target", text)
        self.assertIn("search output is a lead, never evidence", text)
        self.assertIn("no functional feed was found on the surfaces reached", text)

    def test_a_fully_blocked_ladder_is_finalized_with_its_evidence(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("A trace ends either at that `FUNCTIONAL` result or with the ladder exhausted", text)
        self.assertIn("A fully blocked ladder is therefore finalized normally", text)
        self.assertIn("it records the block and earns no operational transport", text)
        self.assertIn("fix the payload, never the evidence", text)
        profile = TARGET_PROFILE.read_text(encoding="utf-8")
        self.assertIn(
            "A ladder with no `FUNCTIONAL` transport is still a complete result when it was\nexhausted",
            profile,
        )
        self.assertIn("Never delete an\nobservation", profile)
        self.assertIn(
            "A trace ends at the first `FUNCTIONAL` transport or with the ladder",
            TRANSPORT.read_text(encoding="utf-8"),
        )

    def test_an_observed_constraint_names_what_observed_it(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn(
            "explicit transport, engine, JavaScript, authentication, and environment context",
            text,
        )
        profile = TARGET_PROFILE.read_text(encoding="utf-8")
        self.assertIn("durable identity claim, not a convenience", profile)
        self.assertIn("Shared branding, a similar name, or a plausible relationship\nis not evidence", profile)
        self.assertIn("Claiming `OBSERVED`\nfor one therefore requires a `validation`", profile)
        self.assertIn("Keep the claim inside what\nwas actually seen", profile)
        self.assertIn("Shared branding, a similar name, or a plausible relationship\nis not evidence", profile)

    def test_the_unenforceable_half_of_the_host_rule_is_marked_as_such(self) -> None:
        self.assertIn(
            "not that operator judgment",
            SKILL.read_text(encoding="utf-8"),
        )
        profile = TARGET_PROFILE.read_text(encoding="utf-8")
        self.assertIn("Two of those rules are machine-checked and the third is not", profile)
        self.assertIn(
            "evidence served *from* a hostname proves the hostname exists, never that it\nbelongs to this brand",
            profile,
        )

    def test_discovery_runs_are_visible_execution_identity_only(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        for rule in (
            "scripts/discovery-begin --target <target-id> --capability <capability>",
            "Use its `run_id` as `provenance.run_id`",
            "if the run cannot be registered, stop",
            "Any returned `SAVED`, `ALREADY_EXISTS`, or `NOT_SAVED` verdict closes only the matching run",
            "schema or infrastructure errors leave it open",
            "run identity is never knowledge identity",
        ):
            self.assertIn(rule, text)
        profile = TARGET_PROFILE.read_text(encoding="utf-8")
        self.assertIn("Concurrent runs for the same\ntarget and capability remain distinct", profile)
        self.assertIn("Candidate and Claim identity stay\nsemantic", profile)

    def test_a_failed_ladder_must_classify_why_it_failed(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("Reaching the policy's last step is not the same as exhausting the ladder", text)
        self.assertIn("must also name the durable class it observed", text)
        self.assertIn(
            "a transient, tool, local-environment, or unclassified failure is runtime state",
            text,
        )
        profile = TARGET_PROFILE.read_text(encoding="utf-8")
        self.assertIn("Such a ladder must also classify why it failed", profile)
        self.assertIn(
            "`FAILED` alone does not distinguish a target that\nblocked this run from a network that dropped one request",
            profile,
        )
        transport = TRANSPORT.read_text(encoding="utf-8")
        self.assertIn("which is not exhaustion", transport)
        self.assertIn("describe this run or this machine, so they save nothing", transport)

    def test_the_two_lookup_calls_have_distinct_stated_purposes(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn(
            "The target-only call already returns the accepted context of every capability",
            text,
        )
        self.assertIn("Run it once per capability you selected", text)

    def test_missing_browser_control_never_authorizes_a_substitute_stack(self) -> None:
        for text in (SKILL.read_text(encoding="utf-8"), TRANSPORT.read_text(encoding="utf-8")):
            self.assertIn("Playwright", text)
            self.assertIn("Puppeteer", text)
            self.assertIn("Selenium", text)
            self.assertIn("explicit user authorization", text)
            self.assertIn("substitute", text)

    def test_live_web_target_scope_is_not_exempted_by_task_shape(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("Any task that reads, navigates, or acts on a live web target is in scope here", text)
        self.assertIn("not ruled out for being read-only, quick, QA, one-off", text)
        self.assertIn("Skip this skill only when no live web target is involved at all", text)

    def test_skill_line_budget_is_preserved(self) -> None:
        self.assertLessEqual(len(SKILL.read_text(encoding="utf-8").splitlines()), SKILL_LINE_BUDGET)

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
