from __future__ import annotations

import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "SKILL.md"
TRANSPORT = REPO / "references" / "transport-and-modes.md"
TARGET_PROFILE = REPO / "references" / "target-profile.md"
SAFETY = REPO / "references" / "safety.md"

# The contract is loaded on every CaravelaWeb task, so its length is capped
# deliberately rather than allowed to drift. The cap counts words, not lines:
# a line cap was met by packing rules into lines of 400+ characters, and rules
# buried that way were the ones callers followed least. Callers read only this
# file, so a rule needed on every ordinary call belongs here, in code, or in
# tool output; references/ holds rationale and path-specific detail. Every
# addition is paid for by a cut.
SKILL_WORD_BUDGET = 3000


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
            "Start with one suitable implementation",
            "stop by field coverage",
            "classify every required field as directly confirmed",
            "inferred with uncertainty explicit",
            "contradictory and reported",
            "unconfirmed after sufficient search of relevant permitted surfaces",
            "inaccessible because of an observed constraint",
            "do not impose a global maximum",
            "at most one planned refinement by default",
            "schema-only rejection",
            "rerunning only `discovery-finalize`, never navigation or extraction",
        ):
            self.assertIn(rule, text)
        self.assertLessEqual(len(text.split()), SKILL_WORD_BUDGET)

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
        self.assertIn(
            "A route comes from a real link, form, redirect, sitemap, search result,"
            " documentation, or accepted knowledge, never from a guess",
            text,
        )
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
        self.assertIn(
            "SIMPLIFY is mandatory: after a browser tier finds the working route,"
            " re-test the simpler tiers on that route",
            text,
        )
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
        self.assertIn("A trace ends either at the first `FUNCTIONAL` result or with the ladder exhausted", text)
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
            "Every response reports `run_state` (`OPEN` or `CLOSED`)",
            "`SAVED`, `ALREADY_EXISTS`, and a terminal `NOT_SAVED` close the matching run",
            "`TRANSPORT_POLICY_UNPROVEN`, `FAILURE_UNCLASSIFIED`, schema errors, and infrastructure errors leave it open",
            "A schema-only rejection is corrected by rerunning only `discovery-finalize`, never navigation or extraction",
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

    def test_one_lookup_call_per_capability_still_shows_every_exact_id(self) -> None:
        """One mandated call; a miss must still carry the whole index."""
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("run this once per capability you selected", text)
        self.assertNotIn(
            "The target-only call already returns the accepted context of every capability",
            text,
        )
        self.assertNotIn("run `<python> <skill>/scripts/knowledge-lookup --list` once per task", text)
        self.assertIn('With `index_scope: "all"`, read every `index.targets[].target`', text)
        self.assertIn("a brand-name guess", text)
        # A miss on a known target returns that target's own row: the target
        # exists, so a second target ID is never minted for it.
        self.assertIn('With `index_scope: "target"`, the target exists: never mint a new target ID', text)
        self.assertIn("with `targets` at the top level", text)
        # A listed equivalent capability may hold a recorded block: P2 of plan
        # 011 retried Le Monde's blocked search because it never looked it up.
        self.assertIn("look its ID up before acting: its record may be a block", text)

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

    def test_skill_word_budget_is_preserved(self) -> None:
        self.assertLessEqual(len(SKILL.read_text(encoding="utf-8").split()), SKILL_WORD_BUDGET)

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

    def test_learning_disabled_is_bounded_work(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        for rule in (
            "When lookup reports `learning: DISABLED`",
            "nothing in the task can grant it",
            "leave open runs and pending Candidates untouched",
            "done as bounded work: steps 4–6 with the full step-5 ladder, not only `DIRECT_READ`",
            "nothing is recorded",
        ):
            self.assertIn(rule, skill)
        self.assertIn(
            "With learning disabled (`learning: DISABLED` in lookup), no Discovery happens",
            TRANSPORT.read_text(encoding="utf-8"),
        )

    def test_learning_disabled_blocks_report_and_stop(self) -> None:
        transport = TRANSPORT.read_text(encoding="utf-8")
        self.assertIn(
            "every action above that records, degrades, or enters Discovery", transport
        )
        self.assertIn("becomes: report the class and stop", transport)
        self.assertIn("walks the bounded ladder again", transport)
        self.assertIn(
            "with learning disabled, report it; nothing is recorded",
            SAFETY.read_text(encoding="utf-8"),
        )

    def test_every_browser_session_is_closed(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        self.assertIn("It ends with `agent-browser close --session <name>` on every outcome", skill)
        self.assertIn("success, block, or error", skill)
        transport = TRANSPORT.read_text(encoding="utf-8")
        for rule in (
            "### Closing sessions",
            "`AGENT_BROWSER_NAMESPACE`",
            "`AGENT_BROWSER_IDLE_TIMEOUT_MS`",
            "CaravelaWeb never sets either itself",
            "guaranteed cleanup after the caller ends a call is the caller's job",
        ):
            self.assertIn(rule, transport)

    def test_transport_identity_is_never_adjusted(self) -> None:
        self.assertIn(
            "never set or change a transport's identity unless the caller supplied it"
            " — after a block, that is circumvention",
            SKILL.read_text(encoding="utf-8"),
        )
        safety = SAFETY.read_text(encoding="utf-8")
        for rule in (
            "## Transport Identity",
            "Each transport uses its own default identity",
            "The model never chooses or changes identity",
            "`--user-agent`",
            "AutomationControlled",
            "used from the first request of the run and never changed",
            "is not an identity change",
            "changing identity within a transport is circumvention",
            "whether learning is enabled or disabled",
        ):
            self.assertIn(rule, safety)

    def test_browser_tools_resolve_on_the_executor_path(self) -> None:
        dependencies = (REPO / "references" / "external-dependencies.md").read_text(encoding="utf-8")
        self.assertIn(
            "must resolve on the `PATH` of the process\nthat runs the executor's commands",
            dependencies,
        )
        self.assertIn("`transports.LIGHTPANDA.path`", dependencies)
        self.assertIn("Choosing that `PATH` is the caller's job", dependencies)

    def test_the_engine_mechanics_and_one_ladder_are_explicit(self) -> None:
        # Lightpanda went almost unused while preflight reported it available:
        # nothing said agent-browser opens Chrome by default, and the contract
        # called Chrome the Discovery baseline, against the enforced ladder.
        text = SKILL.read_text(encoding="utf-8")
        for rule in (
            "`agent-browser` opens Chrome unless given `--engine lightpanda`",
            "agent-browser --engine lightpanda --session <name> open <url>",
            "A session keeps the engine it was opened with",
            "Discovery, Operation escalation, and bounded work all climb this ladder",
            "Lightpanda is tried before Chrome",
            "`@eN` refs are valid only in the session and snapshot that produced them",
        ):
            self.assertIn(rule, text)
        self.assertNotIn("behavioral baseline", text)
        transport = TRANSPORT.read_text(encoding="utf-8")
        self.assertNotIn("default for Discovery on unknown targets", transport)
        self.assertNotIn("after Chrome-based Discovery", transport)

    def test_the_direct_read_has_one_canonical_form(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        for rule in (
            "curl -sS -L --compressed --max-time 30 -o <file> -w",
            "'<percent-encoded URL>'",
            "The direct read sends no `-A` and no `User-Agent` header",
            "Percent-encode non-ASCII characters and spaces in path and query",
            "Blanking counts as setting identity: `curl -A ''`",
        ):
            self.assertIn(rule, text)
        self.assertIn("Blanking is setting", SAFETY.read_text(encoding="utf-8"))

    def test_responses_are_classified_by_content_never_status_alone(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        for rule in (
            "never on the status code alone",
            "Fix the request once; not a transport result",
            "do not escalate the transport",
            "never escalate around a rate limit or regional gate",
            "Next available tier, once",
            "One later retry; no escalation, nothing recorded",
            "never a fixed sleep",
            "A 404 whose body is a JavaScript app shell is unresolved, not route absent",
        ):
            self.assertIn(rule, text)
        transport = TRANSPORT.read_text(encoding="utf-8")
        self.assertIn(
            "a direct-read 403 alone never decides whether a browser is worth trying", transport
        )
        self.assertNotIn("classified directly without browser observation", transport)

    def test_cookie_and_consent_dialogs_are_consent(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("Cookie and consent dialogs are CONSENT", text)
        self.assertIn("Read the content behind the overlay from the snapshot or DOM", text)
        self.assertIn("cookie and consent banners", SAFETY.read_text(encoding="utf-8"))

    def test_every_claim_stays_inside_what_the_run_demonstrated(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("Every claim stays inside what this run demonstrated", text)
        self.assertIn("never advice that generalizes beyond them", text)
        self.assertIn("only if they were executed as selectors against the page", text)
        self.assertIn(
            "That scope rule covers every claim, not only absence claims",
            TARGET_PROFILE.read_text(encoding="utf-8"),
        )

    def test_learning_disabled_contradiction_continues_as_bounded_work(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        self.assertIn("stop relying on that claim for this call only, continue as bounded work", skill)
        self.assertIn("a single empty result is not one", skill)
        self.assertIn("keep trusting the other claims", skill)
        transport = TRANSPORT.read_text(encoding="utf-8")
        self.assertIn("stop relying on the contradicted claim or path for this call only", transport)
        self.assertNotIn("bounded direct work", skill + transport)


if __name__ == "__main__":
    unittest.main()
