# Plan 009: Reduce the Discovery ceremony cost

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 7fbb6c3..HEAD -- SKILL.md scripts/discovery-finalize scripts/knowledge-lookup scripts/preflight discovery_finalize.py discovery_runs.py installation_init.py references/target-profile.md references/discovery-payload-examples.md CHANGELOG.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.
>
> **Commit methodology**: one commit per change below, linear history,
> author and committer `Tarciso Morais <287870717+tarcisomorais@users.noreply.github.com>`,
> imperative sentence-case subject with no prefix and no period, a prose
> body wrapped at 76 columns with three paragraphs (observed problem, what
> changed and why, what tests now cover), and no trailers of any kind.

## Status

- **Priority**: P1 for changes 1–2, P2 for changes 3–5, P3 for change 6
- **Effort**: S (1, 2), M (3, 4, 5), L (6)
- **Risk**: LOW (1, 2), MED (3, 4, 5), HIGH (6)
- **Depends on**: none for 1–2; 3–5 depend on the re-measurement gate in
  Step 0; 6 depends on 3–5 having landed and been re-measured
- **Category**: developer experience, agent-facing contract
- **Planned at**: commit `7fbb6c3`, 2026-09-03
- **Re-measured**: 2026-09-03, gate FAIL. Runs on 0.2.0+ (released
  2026-09-03T02:34:40Z): 1 of 10 required, in 1 of 3 sessions required,
  1 project (disperta). Changes 3–5 stay BLOCKED (insufficient data, not
  rejected). The one run: 3 real finalize calls, 1 `--validate`, 3
  refusals, 0 `SAVED`; refusals 2 and 3 and the `--validate` returned the
  generic no-`reason_code` message that change 2 fixes. Script:
  `plans/measure-step0` (read-only, no arguments, prints the gate block
  and exits before computing metrics when the gate fails).
- **Live run 2026-09-04** (repo session, excluded from the gate by the
  script; recorded as method evidence only): 10 read-only runs,
  `ai-headlines-list`, on `main` `cc371fa`, live Knowledge Root. 10/10
  `SAVED` and `OPERATIONAL`; 7 DIRECT_READ, 2 LIGHTPANDA, 1 CHROME. Real
  finalize calls mean 1.7, max 2; 3/10 = 30% with zero refusals; 7
  refusals, all uncoded (6/10 runs from a future `recorded_at`, 1 from a
  locked database), 0 from the change 1 trap cluster. 45 `--validate`
  calls, 42 of them diagnosing those two refusals. Fixed on `main` as
  `02be2ab`. 21 lookup calls preceded the first fetch (supports change 5).
- **Re-measured 2026-09-04, gate PASS** on release 0.2.1 (`c0d7f77`,
  tag `v0.2.1`): 17 runs, 5 consumer sessions, 2 projects (disperta,
  quintace-toolbox); 16 of them from four dispatched sessions vetting four
  sources each, all read-only, all on the installed 0.2.1 plugin. Real
  finalize per run median/mean/max 1 / 1.35 / 3; saved on first real
  finalize 12/17 = 71%; runs needing 4+ calls 0/17 = 0%; zero-refusal runs
  12/17 = 71%; `--validate` 1 call in 1/17 runs. Refusals: `PAYLOAD_VALUE`
  4 (all one session, `recorded_at` a few seconds ahead of the clock),
  `HOST_SCOPE` 1, uncoded 2 (0.2.0 session, pre-hotfix). Payloads
  recovered 17/17. Change 4: (a) 2/3 = 67% duplicated blocks, under the
  10-item floor; (b) 0/16 = 0% proof-carrying runs without
  `authentication`; 16/17 reached `OPERATIONAL`, no `lifecycle_gap`.
  Change 5: lookups 3.35 per run, 11.4 per session, 1 + 4 + 4 = 9 before
  the first run in every four-source session, 32/57 = 56% answered
  `not_found`; 0 duplicate-by-naming targets minted. Verdicts: change 3
  REJECTED (not needed), change 4 REJECTED (not needed on (b); (a) has
  insufficient data), change 5 PROCEED, change 6 waits on change 5 and a
  second re-measurement. Primary KPI already met on this sample. Method:
  `plans/measure-step0` counts runs and finalize results from tool
  results, since the agents ran the CLI in shell loops; lookups are
  counted over the whole session including post-save verification.
- **Change 5 landed 2026-09-04** as `6856e87` (reviewed): one lookup call
  per capability with `readiness`, `index`, `index_scope`; readiness rules
  extracted to `readiness.py` shared with `preflight`; SKILL.md step 2
  shrank 26 to 19 lines, file 151 to 144, budget untouched. DX-05 landed
  as `9374df3`. Next: release, then a second re-measurement on the new
  contract before change 6 is considered.
- **Second sample 2026-09-04, release 0.2.2** (`0130703`, tag `v0.2.2`):
  21 runs, 3 consumer sessions, 2 projects (quintace-toolbox, tarsila),
  each session vetting three targets for two capabilities plus one
  single-capability control. Real finalize per run median/mean/max
  1 / 1.14 / 2; saved on first real finalize 18/21 = 86%; zero-refusal
  runs 18/21 = 86%; refusals `TASK_DATA_REJECTED` 2, `PAYLOAD_SHAPE` 1;
  `--validate` 3 calls in 2 runs. 16/21 = 76% reached `OPERATIONAL`; the
  5 gaps are all `NO_OPERATIONAL_PROOF` on paywalled or Cloudflare-blocked
  article bodies, recorded as constraints within read-only authority.
  Change 5 effect: lookups 2.10 per run (was 3.35 on 0.2.1), 14.7 per
  seven-run session; `not_found` 18/44 = 41%; pre-fetch CLI calls per
  task median 21. Change 6 residual: 9/12 targets carried two
  capabilities; second capabilities cost 9 extra begins, 13 extra
  finalizes, 3 repeated lookups, 25/92 = 27% of ceremony calls; their
  evidence repeated the first capability's in 4/27 = 15% of items
  (evidence 1/10, transport 3/11, validation 0/6); marginal wall-clock
  43 s and 5 tool calls outside the first capability's windows, because
  sessions batched both capabilities in one loop. Read: the duplicated
  cost is ceremony (one begin/finalize round per capability), not repeated
  proof work; the shared-evidence half of the change 6 design would save
  almost nothing. Decision on change 6 is the maintainer's.

## Why this matters

The ceremony cost was measured on 2026-09-03 from three sources: the
maintainer's friction log, the Claude Code session logs of four consumer
projects (22 sessions, 2026-08-09 to 2026-09-02, all before release 0.2.0),
and a copy of the live Operational Memory. Method and numbers are also kept
in the maintainer's memory as "ceremony-cost-investigation-2026-09-03".

Per Discovery run in real use (50 runs tracked). "Real finalize" excludes
`--validate` calls; "refusal" is a `NOT_SAVED` response to a real call:

| Metric | Value |
| --- | --- |
| Real finalize calls per run, median / mean / max | 1 / 2.5 / 14 |
| Runs saved on the first real finalize | 26 of 50 |
| Runs needing 4 or more real finalize calls | 11 of 50 |
| Refusals per run, median / mean | 1 / 1.9 |
| Runs with zero refusals | 16 of 50 |
| Minutes from begin to last finalize, median / p75 / max | 1.7 / 3.9 / 33 |
| `--validate` use | 20 calls in 6 of 50 runs |

The median run already finalizes in one call. The cost is in the tail: 11
runs of 50 needed four or more calls, and 14 of 50 collected three or more
refusals. Every metric below must exclude `--validate` calls, or a
recommended `--validate` inflates the count it is meant to lower.

Across all 22 sessions: 519 web fetches against 349 skill CLI calls, 114
greps of `discovery_finalize.py`, and 33 reads of SKILL.md or a reference.
Ceremony roughly equals real work in tool calls, and agents read the
validator source to learn the schema.

Refusals after the 2026-08-14 redesign, top causes (91 total): ladder
unproven 15, host needs `TARGET_SURFACE` evidence 14, conflict 8,
`evidence.kind` format 7, OBSERVED constraint needs a validation block 5,
no open marker 5, `field_paths` 5. Four of these are one trap cluster
(host literal, evidence scope and kind, ladder proof, validation block):
41 of 91 refusals.

Live memory: 50 capabilities, 64 proposals, 14 capabilities took two full
runs, 42 have a `FUNCTIONAL` transport claim, 7 have an `authentication`
claim, 0 are `OPERATIONAL`. Per proposal: 22 of 37 `blocking` or
`limitation` claims carry a validation block identical, apart from
`outcome`, to a transport claim's in the same proposal; 13 of 19 proposals
with a `FUNCTIONAL` transport and an `operational_proof` lack the
`authentication` claim and missed `OPERATIONAL` for that alone. The 67
payloads recovered from session logs agree: 10 of 29 and 12 of 19.

Eight of the ten friction-log items no longer reproduce on 0.2.0 (verified
by replaying each against a throwaway root). What remains is structural:
call count, payload repetition, first-error-only diagnostics, and one
ceremony per capability. Two inconsistencies were also found: an
unresolved Knowledge Root yields a generic finalize error with no reason
code, and the CLI emits two reason codes the documented closed list omits.

No consumer session has run on 0.2.0 yet. Changes 1 and 2 are cheap and
safe to land now. Changes 3–6 are gated on re-measurement (Step 0) so the
0.2.0 fixes are counted before more machinery is added.

## Current state

`SKILL.md:103-134` is step 7 of the executor flow. It states every rule the
trap cluster violates, but spread over eight paragraphs of roughly 20 KB
that load on every skill trigger. The `www.` rule is in line 116, the
`TARGET_SURFACE` scope rule in line 116, the ladder rule in line 127, and
the validation-block rule in line 116 (last sentence). `--validate` is
described in line 111 as optional. Since the 2026-08-14 redesign, every
schema refusal and both retryable policy refusals leave the run open, so
`--validate` only prevents a terminal `NOT_SAVED` (no reusable knowledge,
already pending, inference only, replacement refusal, conflict) from
closing the run, and none of those is fixed by resubmitting the same
payload. Mandating it would add one call to every happy path for little
protection.

`SKILL.md:30-46` (step 2) mandates three lookup calls per task before
Discovery: `knowledge-lookup --list`, `knowledge-lookup --target <id>`,
and `knowledge-lookup --target <id> --capability <cap>`. `SKILL.md:15-25`
adds `preflight` on first run. `discovery-begin` is the fifth call before
any web work on a cold task.

`scripts/discovery-finalize:58-59`
```python
        if root is None:
            raise OSError("no usable CaravelaWeb knowledge root could be resolved")
```
That `OSError` reaches the generic `except Exception` at
`scripts/discovery-finalize:113-121`, which prints
`{"status":"NOT_SAVED","run_state":"OPEN","reason":"Discovery could not be finalized in local Operational Memory."}`
with no `reason_code`. Verified by setting `CARAVELAWEB_KNOWLEDGE_ROOT` to an
empty directory. In the same state, `scripts/init-knowledge-root` with no
flag refuses with "already an initialized knowledge root: <default>",
because `installation_init.py:83-104` resolves only the flag or the
default, never the environment variable that `platform_adapter.py:105`
honours for every other command.

`scripts/discovery-finalize:104-109` emits `reason_code` `RUN_MARKER` for a
`DiscoveryRunError` and `PAYLOAD_INVALID` for a `DiscoveryFinalizationError`
with no code (the default at `discovery_finalize.py:37`). The wrapper
allow-list in `scripts/discovery-finalize:24-39` raises with no code, so an
unknown top-level field reports `PAYLOAD_INVALID`.
`references/target-profile.md:151-160` and `CHANGELOG.md:34-37` say the
closed list has exactly eight values and list neither.

`discovery_finalize.py:533-617` (`_normalize_observations`) validates one
observation at a time and raises on the first defect. Every validator it
calls (`_exact_keys`, `_normalize_family_value`, `_normalize_validation`,
`_symbol`, `_schema_map`) raises `DiscoveryFinalizationError` immediately.
`_validate_evidence` (`:818`), `_validate_provenance` (`:803`), and
`_normalize_transport_trace` (`:849`) do the same. A payload with three
defects costs three round trips.

`discovery_finalize.py:576-594`: an OBSERVED `blocking` or `limitation`
observation must carry its own complete `validation` block (transport,
engine, javascript, context.authentication, context.environment) or the
payload is refused. A `transport` observation in the same payload usually
carries an identical block.

`discovery_finalize.py:625-800` (`_operational_proof_dependencies`)
requires, for `OPERATIONAL`, one `FUNCTIONAL` transport claim, one
`authentication` claim whose `access_model` equals the proof validation's
`context.authentication`, and one `validation` claim with
`operational_proof` whose validation outcome is `SUCCESS`. The gap order at
`:791-794` is `NO_FUNCTIONAL_TRANSPORT_CLAIM`, then
`NO_AUTHENTICATION_CLAIM`, then `SUPPORTING_FACTS_AMBIGUOUS`. The
`authentication` observation restates a value the transport observation's
`validation.context.authentication` already carries; 35 capabilities in the
live memory have the transport and lack the claim. Whether that
restatement should stay required is a model decision, not a normalization
shortcut; this plan keeps it required and makes the gap message name the
missing observation verbatim.

`discovery_runs.py:49-57` (`begin_discovery`) opens one run for one
`(target, capability)`. `scripts/discovery-begin:23-24` requires both
flags. `scripts/discovery-finalize:24-39` accepts one `capability` per
payload. Vetting one source with two capabilities is two complete
ceremonies.

`scripts/knowledge-lookup:28-34`: `--list` and `--target` are exclusive
modes; readiness comes only from `scripts/preflight`.

## Commands you will need

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m unittest tests.test_discovery_finalize tests.test_discovery_payload_examples tests.test_discovery_runs tests.test_skill_adapter_parity tests.test_public_vocabulary
git diff --check
python3 scripts/discovery-finalize --help
python3 scripts/knowledge-lookup --help
```

Throwaway root for manual checks:

```bash
R=$(mktemp -d); python3 scripts/init-knowledge-root --knowledge-root "$R"
python3 scripts/discovery-begin --knowledge-root "$R" --target example-news --capability article-read
python3 scripts/discovery-finalize --knowledge-root "$R" --validate --input payload.json
```

## Scope

In scope: `SKILL.md`, `scripts/discovery-finalize`, `scripts/knowledge-lookup`,
`scripts/preflight`, `scripts/init-knowledge-root`, `discovery_finalize.py`,
`discovery_runs.py`, `installation_init.py`, `references/target-profile.md`,
`references/discovery-payload-examples.md`, `CHANGELOG.md`, and the tests
named in each step.

Out of scope: the Operational Memory schema, the transport policy, the
authority and marker model, replacement and conflict semantics, the
accepted/pending Claim semantics, and any change to what counts as
reusable knowledge. Do not add a second validator, a JSON Schema
dependency, or a new normal-mode finalization status.

## Git workflow

Work on a branch from `main`. One commit per change, in the order below.
Run the full suite before every commit. Rebase, never merge. Cherry-pick
linearly onto `main` when the maintainer approves.

## Steps

### Step 0: Re-measurement gate (before changes 3–6)

Changes 1 and 2 do not need this gate. Everything measured on 2026-09-03
predates release 0.2.0, which shipped reason codes, accepted-set messages,
pending-candidate visibility, and `knowledge-resolve`. Those fixes must be
counted before more machinery is added, and the count must be large
enough to mean something.

**Sample-size gate.** Re-measure only when the logs hold, on 0.2.0 or
later:

- at least 10 Discovery runs (a `discovery-begin` followed by at least one
  real `discovery-finalize`);
- across at least 3 consumer sessions;
- preferably across at least 2 consumer projects. With one project only,
  note it in the status row and treat every threshold below as advisory.

Two runs, one of them with four finalize calls, authorize nothing.

**Measurement.** On those runs only:

1. Count, per run, the number of `discovery-finalize` calls without
   `--validate` between one `discovery-begin` and the next. Count
   `--validate` calls separately and never add them to the first number.
2. Count refusals per run: `NOT_SAVED` responses to real calls, excluding
   `would_finalize_as` responses. Count refusal reasons.
3. From the payloads those runs submitted (Write contents and Bash
   heredocs in the logs) or from the proposals they created in the live
   memory, count:
   - OBSERVED `blocking` or `limitation` observations whose `validation`
     block, ignoring `outcome`, equals a `transport` observation's block
     in the same payload;
   - runs with a `FUNCTIONAL` transport and an `operational_proof` but no
     `authentication` observation.
4. Count lookup calls per task and how many `not_found` results were
   followed by a `discovery-begin` for a target ID that differed from an
   existing ID only by naming.
5. For change 4's secondary KPI: for each `SAVED` with a `lifecycle_gap`,
   whether the same capability reached `OPERATIONAL` on its next run, and
   whether a reference read or a source grep occurred between the two.
6. Compare with the baseline table in "Why this matters".

**Per-change thresholds.**

- **Change 3** proceeds if the mean real finalize calls per run is still
  2 or more, or any run needs 4 or more, or fewer than 50% of runs have
  zero refusals (baseline 16/50 = 32%).
- **Change 4** proceeds if, among at least 10 relevant items on 0.2.0+,
  at least 33% of `blocking`/`limitation` observations duplicate a
  transport validation block on the same host (baseline 22/37 = 59% in
  memory, 10/29 = 34% in logs), or at least 33% of proof-carrying runs
  lack the `authentication` observation (baseline 13/19 = 68% in memory,
  12/19 = 63% in logs). Do not use the total count of `OPERATIONAL` capabilities in the
  live memory; that total is dominated by knowledge written before 0.2.0
  and measures historical debt, not the defect this change addresses.
- **Change 5** proceeds if the lookup sequence is still 3 or more calls
  per task on average, or any duplicate-by-naming target was minted.

Otherwise mark the corresponding change `REJECTED (re-measured, not
needed)` in `plans/README.md` with the numbers, and stop.

### Change 1: Pre-finalize checklist in SKILL.md

**Effort S, risk LOW.** Covers 41 of 91 measured refusals. Adds no call to
the happy path.

1. In `SKILL.md`, immediately after the `discovery-finalize` command block
   in step 7 (after line 107), insert a short list titled
   **Before you finalize**:
   - `observation.host` is the literal hostname the evidence locator uses.
     No `www.` is added or dropped. `www.example.com` and `example.com` are
     two hosts.
   - Every evidence item for a first-time host has `"scope": "TARGET_SURFACE"`
     and a lowercase `kind` such as `direct-read-validation`.
   - A browser-backed result needs a complete `transport_trace` that starts
     at `DIRECT_READ` and stops at the first `FUNCTIONAL` transport. A
     `DIRECT_READ`-only result needs no trace.
   - An OBSERVED `blocking` or `limitation` observation carries its own
     `validation` block with transport, engine, javascript, and both context
     keys.
   - `field_paths` use `$.field`, `a.b`, or `items[].field`. `structure`,
     `state`, `signal`, and similar fields are single symbolic tokens.
2. Keep each bullet to one line of 25 words or fewer. Do not move or
   reword the existing paragraphs; the checklist is a pointer, the
   paragraphs stay canonical.
3. Leave `--validate` optional. Reword line 111 to say when it pays: a
   payload that carries a `transport_trace`, a contradiction, or a
   replacement of accepted knowledge, where a terminal `NOT_SAVED` would
   close the run. For every other payload, call `discovery-finalize`
   directly; a refusal leaves the run open and costs the same one call.
4. Mirror the same list in `references/discovery-payload-examples.md`
   above example 1 so an agent that opens the examples first sees it.

Tests: `tests/test_skill_adapter_parity.py` and
`tests/test_public_vocabulary.py` pin SKILL.md content and vocabulary. Run
them; if a pinned excerpt changed, update the assertion to the new text and
say so in the commit body. Add one assertion that SKILL.md contains the
heading "Before you finalize" and does not contain "before every real
finalize".

### Change 2: Reason-code and Knowledge Root consistency

**Effort S, risk LOW.**

1. In `scripts/discovery-finalize:58-59`, replace the bare `OSError` for an
   unresolved root with a `DiscoveryFinalizationError` carrying a new code
   `KNOWLEDGE_ROOT_UNRESOLVED` and the message "no CaravelaWeb Knowledge
   Root resolved; run preflight, then init-knowledge-root once, or pass
   --knowledge-root". Add the constant beside the others at
   `discovery_finalize.py:59-66`.
2. Make the code mandatory. Change the constructor at
   `discovery_finalize.py:34-40` to `DiscoveryFinalizationError(message, *,
   code: str)` with no default, and delete the `PAYLOAD_INVALID` string
   from the module and from `scripts/discovery-finalize:104-109`. Only two
   raise sites lack a code today, both in the wrapper allow-list at
   `scripts/discovery-finalize:28` and `:35`; give them `PAYLOAD_SHAPE` so
   an unknown top-level field reports the same code as an unknown nested
   field. Promote `RUN_MARKER` to a named constant beside the others. The
   invariant "every refusal carries a code" is then enforced by the
   constructor, not by inspection; replace the AST allowlist test at
   `tests/test_discovery_finalize.py:2079-2080` with one assertion that the
   constructor rejects a call without `code` (`TypeError`).
3. Update `references/target-profile.md:151` to list the full set:
   the eight existing codes plus `RUN_MARKER` and
   `KNOWLEDGE_ROOT_UNRESOLVED`, each with one line. `PAYLOAD_INVALID` is
   not in the list because it can no longer be produced. Update the
   `CHANGELOG.md` `Unreleased` section (create it above 0.2.0) with one
   bullet.
4. In `installation_init.py:83-104`, resolve the root as flag, then
   `CARAVELAWEB_KNOWLEDGE_ROOT`, then default, using the same order as
   `platform_adapter.resolve_knowledge_root`. Keep the rule that an explicit
   location is never recorded as anyone's default. Update the message at
   `scripts/init-knowledge-root:45-55` to say which of the three sources was
   used.

Tests: in `tests/test_discovery_finalize.py`, add a case that runs the CLI
with `CARAVELAWEB_KNOWLEDGE_ROOT` pointing at an empty directory and
asserts `reason_code` is `KNOWLEDGE_ROOT_UNRESOLVED` and `run_state` is
`OPEN`. In `tests/test_fresh_install_lifecycle.py`, add a case that
initializes through the environment variable and asserts the default
location is untouched. In `tests/test_discovery_payload_examples.py`,
extend `test_a_malformed_example_reports_a_reason_code` with a top-level
unknown field expecting `PAYLOAD_SHAPE`.

### Change 3: Aggregated payload diagnostics

**Effort M, risk MED.** Gated on Step 0. Collapses the 4-to-14-call tail.

1. Add a private collector to `discovery_finalize.py`: a list of
   `(field, message, code)` gathered during payload normalization. Wrap the
   per-observation body of `_normalize_observations` (lines 540-611), the
   per-item body of `_validate_evidence`, and `_normalize_transport_trace`
   so that a `DiscoveryFinalizationError` raised for one item is recorded
   and the loop continues with the next item. Do not change the validators
   themselves; they keep raising.
2. After all payload-shape validation and before any Operational Memory
   read, if the collector is non-empty raise one
   `DiscoveryFinalizationError` whose `code` is the code of the first
   defect and whose message lists every defect, one per line, in payload
   order, capped at 20. Add `"defects": [...]` to the CLI refusal JSON in
   `scripts/discovery-finalize:104-109` as a list of
   `{"field", "reason", "reason_code"}`; keep `reason` and `reason_code`
   for the first defect so existing callers and tests still work.
3. Semantic refusals that need memory (host plan, conflict, replacement,
   transport policy) stay single-error; they run only when the payload
   shape is clean.
4. Document the `defects` list in `SKILL.md` step 7 (one sentence) and in
   `references/target-profile.md` beside the reason-code list.

Tests: in `tests/test_discovery_finalize.py`, a payload with three
independent defects (bare field path, bad family, unknown blocking key)
returns all three in `defects` in one call, with `reason_code` equal to
the first. A payload with one defect returns a one-item list. A clean
payload has no `defects` key. Every existing refusal test still passes
unchanged.

### Change 4: Explicit shorthand for repeated blocks, and a gap message that names the missing observation

**Effort M, risk MED.** Gated on Step 0. Removes one repeated block and
makes the path to `OPERATIONAL` a copy-paste, without writing anything the
executor did not declare.

Design rule for this change: the finalizer never persists a Claim, a
validation record, or an evidence link that the payload does not state.
An abbreviation is acceptable only when the executor writes it in the
payload and the finalizer expands it to the concrete form before
validation; the stored record is then identical to the long form. The
first draft of this plan proposed synthesizing an `authentication`
observation from `validation.context.authentication`; that was reusable
knowledge the executor never declared, and it is withdrawn.

1. **Declared validation reuse.** Accept, on an OBSERVED `blocking` or
   `limitation` observation, the literal string
   `"validation": "SAME_AS_TRANSPORT"` in place of the block. In
   `_normalize_observations`, before `_normalize_validation`, resolve the
   string to the `validation` of the one `transport` observation in the
   same payload whose `host` equals this observation's `host`, compared
   after `_normalize_hostname` on both sides. Exactly one match expands;
   zero or more than one refuses with the existing message plus
   "SAME_AS_TRANSPORT needs exactly one transport observation with host
   <host> in the payload; found N". There is no fallback to the only
   transport observation in the payload: a blocking fact on
   `api.example.com` never borrows a validation observed on
   `www.example.com`. An observation with no `host` matches only a
   transport observation with no `host`. Validate and store the expanded
   block exactly as if the executor had written it. No implicit
   inheritance: an absent `validation` is refused as today.
2. **Gap message with the missing observation.** When
   `_operational_proof_dependencies` returns `NO_AUTHENTICATION_CLAIM`,
   add to the `SAVED` and `--validate` responses a `lifecycle_hint` field
   carrying the exact observation the executor may add in a later run, with
   the `access_model` value taken from the proof validation's
   `context.authentication`:
   `{"family":"authentication","value":{"access_model":"PUBLIC"}}`.
   The hint is text in the response, never a write. Do the same for
   `NO_FUNCTIONAL_TRANSPORT_CLAIM` (name the transport the proof used) and
   `PROOF_VALIDATION_NOT_SUCCESS` (name the outcome that was found).
3. Add one bullet to the change 1 checklist: "To earn `OPERATIONAL`, the
   payload declares three observations: `transport` FUNCTIONAL,
   `authentication` with the same `access_model` as the proof's validation
   context, and `validation` with `operational_proof`. See example 8."
4. Show the expanded `SAME_AS_TRANSPORT` block in `--validate` output so the
   caller sees what will be written. Document the shorthand in
   `references/target-profile.md` beside the validation-block rule and in
   `SKILL.md:116`; add example 7b to the payload reference using it.
5. Record in `plans/README.md` backlog a separate model question for the
   maintainer, not for this plan: whether the proof validation's own
   `context.authentication` should count as the access-model fact, so that
   the third observation is no longer required. That is a change to what
   earns `OPERATIONAL` and needs an explicit decision.

Tests: `tests/test_discovery_finalize.py` gains cases for
`SAME_AS_TRANSPORT` with one transport on the same host (stored block
equals the long form byte for byte), two transports on the same host
(refused, count named), one transport on a different host as the only
transport in the payload (refused), no transport (refused), both sides
without `host` (expands), and a string other than the sentinel (refused as
today). A case asserts that a `SAVED` response with gap
`NO_AUTHENTICATION_CLAIM` carries `lifecycle_hint` with the context's
value, and that no `authentication` Claim row exists afterwards.
`tests/test_discovery_payload_examples.py` must still finalize every
example; add 7b. `tests/test_om_native_writes.py` must stay green: the
expanded block goes through the same write path as an explicit one.

### Change 5: One lookup call per task that still shows every exact ID on a miss

**Effort M, risk MED.** Gated on Step 0. Saves two to three calls per task
without losing the duplicate guard that `--list` provides.

Design rule for this change: a miss must show the executor every exact
target ID the standalone `--list` would show, in the same response. The
first draft returned only the row for the guessed ID, or `known: false`.
That hides `sky-news-world` from an executor that guessed `sky-news`, which
is the duplicate `--list` was created to prevent (friction log, Sky News).
Withdrawn.

1. Extend `scripts/knowledge-lookup --target <ref> --capability <cap>` so
   the response always carries two extra keys:
   - `"readiness"`: `READY` or the preflight status string, computed with
     the same function `scripts/preflight` uses; no duplicated logic.
   - `"index"`: on a resolved target, the single `--list` row for that
     target; on `not_found` or `unresolved`, the complete `--list` payload
     (`count` and every `targets` row, identical to the standalone call).
     Measured on the maintainer's memory: 36 targets, 9.8 KB. Add
     `"index_scope": "target" | "all"` so the executor cannot mistake one
     row for the whole index.
2. Keep `--list`, `--target` alone, and `scripts/preflight` unchanged for
   callers that want them. `--capability` without `--target` stays an
   error.
3. Rewrite `SKILL.md` step 2 (lines 30-46) to one mandated call per
   capability: `knowledge-lookup --target <ref> --capability <cap>`, where
   `<ref>` is the URL or hostname the task already has whenever one exists,
   because host-reference resolution is exact and never guesses. Then:
   - `found`: read the accepted context; `readiness` not `READY` means run
     **First run** once and retry.
   - `not_found` with `index_scope: "all"`: read every `targets[].target`
     and `hosts` before minting an ID; reuse an exact ID only under the
     equivalence rule; a brand-name guess is never an ID.
   - `unresolved`: run **First run** once, then retry.
   Keep the equivalence-rule text verbatim. Move the standalone `--list` to
   an "also available" sentence for browsing the index on its own.
4. Update `docs/architecture.md:85-96` if it enumerates the call sequence,
   and `references/target-profile.md` "Knowledge Lookup" (line 89) to show
   the combined response.

Tests: in `tests/test_target_identity.py`, a combined call on a known
target returns `index_scope: "target"` with one row; a call on an unknown
brand guess returns `index_scope: "all"` whose `targets` equals the
standalone `--list` output byte for byte; a hostname reference resolves to
the associated target without touching the index; an unresolved root
returns `readiness` not `READY` and the full index absent.
`tests/test_preflight.py` asserts the `readiness` value matches
`scripts/preflight` on the same root. `tests/test_skill_adapter_parity.py`
pins step 2 text; update the assertion.

### Change 6: One run for several capabilities of one target

**Effort L, risk HIGH.** Gated on changes 3–5 landing and a second
re-measurement. Do not start without the maintainer's explicit go.

Design outline only; write a separate plan before executing:

- `discovery-begin --target <id> --capability <a> --capability <b>` opens
  one marker per capability under one shared `run_id` suffix, so
  `require_open_discovery` and `close_discovery` stay per capability.
- `discovery-finalize` accepts `"capabilities": [{...}, {...}]` where each
  entry is today's payload minus `target`, `provenance`, and top-level
  `evidence`; shared evidence is declared once at the top level.
- Finalization runs today's `finalize_discovery` once per entry inside one
  outer transaction; any entry's refusal rolls back all and reports per
  entry; each entry's run closes independently on `SAVED`.
- Lookup output is unchanged.

The friction log and the live memory (14 capabilities on two runs, the
NYT and The Diplomat double ceremony) justify the design, not yet the
cost. Re-measure after change 5 first.

## Test plan

- Full suite green after every change:
  `python3 -m unittest discover -s tests -p 'test_*.py'`.
- Every documented payload example still finalizes.
- `git diff --check` clean.
- Manual: replay the ten friction-log mistakes against a throwaway root
  after change 3; every refusal must arrive in one call.
- Manual after change 4: finalize example 8 without the `authentication`
  observation, confirm `lifecycle` is `null`, `lifecycle_gap` is
  `NO_AUTHENTICATION_CLAIM`, and `lifecycle_hint` carries the exact
  observation; add it in a second run and confirm `OPERATIONAL`.

## Done criteria

- Change 1: SKILL.md carries the checklist, `--validate` stays optional
  with a stated use case, parity tests pass.
- Change 2: no finalize path prints a refusal without `reason_code`; the
  constructor cannot be called without a code; the documented code list
  equals the set the code can emit; init honours the environment variable.
- Change 3: a multi-defect payload is refused in one call with every
  defect listed.
- Change 4: `SAME_AS_TRANSPORT` expands to the long form and stores the
  same record; a `SAVED` response short of `OPERATIONAL` names the exact
  missing observation; no Claim, validation, or evidence row exists that
  the payload did not state.
- Change 5: SKILL.md mandates one lookup call per capability; a miss
  returns every exact target ID the standalone `--list` returns, byte for
  byte; a hit returns readiness plus that target's row.
- Change 6: separate plan written, not executed.
- Primary KPI, after changes 1, 3, and 5, measured on real finalize calls
  only: mean at or below 1.5, no run at 4 or more, and at least 70% of
  runs with zero refusals. `--validate` calls are reported beside these
  numbers, never inside them.
- Secondary KPI for change 4, which a `SAVED` run cannot lower: among
  proof-carrying capabilities that received a `lifecycle_hint`, at least
  70% reach `OPERATIONAL` on their next Discovery run, and that next run
  is preceded by no read of a reference file and no grep of
  `discovery_finalize.py` in the same session. Baseline before the hint:
  13 of 19 proof-carrying proposals (68%) stopped at
  `NO_AUTHENTICATION_CLAIM`, and 0 reached `OPERATIONAL`.
- Every threshold in this plan is a rate. Record each measurement as raw
  count and percentage, for example `35/50 = 70%` or `9/12 = 75%`; the
  next window will not hold exactly 50 runs.

## STOP conditions

- Any in-scope file differs from a "Current state" excerpt.
- A change would alter what is stored as a Claim value, a Decision, or the
  Operational Memory schema.
- Change 4 would persist any record the payload does not state, or expand
  `SAME_AS_TRANSPORT` when the candidate transport observation is not
  unique; refuse instead.
- Change 3 would require a validator to stop raising; keep them raising and
  collect at the loop level only.
- Any existing refusal test needs its expected `reason_code` changed for a
  reason other than the two wrapper sites moving from `PAYLOAD_INVALID` to
  `PAYLOAD_SHAPE` in change 2.
- The Windows CI job goes red on a symlink, path, or encoding difference.

## Maintenance notes

- Re-run the session-log measurement after every landed change and record
  the numbers in this plan's status row. Always split real finalize calls
  from `--validate` calls; the first measurement on 2026-09-03 mixed them
  and overstated the median as 2. The measurement script is
  `plans/measure-step0`. Session logs store compound one-liners
  (`S=...; python3 $S/scripts/discovery-begin ...; grep ...`), so the
  script splits each Bash command into single CLI invocations (script name
  up to the next `;`, `|`, `&&`, or newline) and reads `--validate`,
  `--help`, `--target`, and `--capability` from that invocation only. A
  flag test over the whole command string drops real runs and merges a
  `--validate` with the real finalize beside it.
- `plans/README.md` backlog items DIRECTION-05 (`--lint` and
  `--explain-schema`) and DIRECTION-06 (multi-capability ceremonies) are
  superseded by changes 3 and 6 here.
- If change 3 lands, reconsider the deferred "aggregated diagnostics"
  entry at the end of `docs/discovery-finalization-redesign-plan.md`; it
  was deferred pending evidence, and the evidence has arrived.
