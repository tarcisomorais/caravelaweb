# Target Profile Reference

This reference defines reusable, capability-scoped operating knowledge. It is not executable browser code or a storage manual.

## Target ID Naming Convention

Target IDs are stable lowercase kebab-case identifiers derived from the public brand, not a URL path, capability, campaign, or consuming-project ID. Prefer the shortest unambiguous public name (`example-news`, `example-jobs`, `example-maps`). Keep an accepted ID stable. One evidence-backed target may span hosts; host differences belong in the capability context.

A caller passes a **target reference**: an already-known canonical ID, a
hostname, or a URL. `knowledge-lookup`, `discovery-finalize`, and every
Operational Memory access resolve that reference through one shared path to
the same **canonical target ID**, so a capability learned once under any
equivalent reference is found by any other -- but a hostname never becomes
the target ID by mechanical transformation (a hostname is not the brand,
and dots are not hyphens):

- A reference shaped like a canonical ID (no dot, e.g. `gtolab`,
  `example-jobs`) is used as that ID directly. It is never reinterpreted as
  a hostname, and an existing ID never changes shape.
- A reference shaped like a URL or hostname (contains a dot) is first
  normalized to a plain **host reference**: scheme, userinfo, path, query,
  fragment, port, and a leading `www.` label are dropped, so
  `example.com`, `www.example.com`, `https://example.com/`, and
  `https://www.example.com/` all normalize to the same host string
  `example.com` -- with its dots kept literally, never collapsed to
  hyphens, so `a.b.com` and `a-b.com` stay distinct. That host reference is
  then looked up against the **existing** target<->host associations
  already recorded in Operational Memory (the same `host` scope described
  below): exactly one match resolves to that target's canonical ID; zero
  matches never invent a target ID from the hostname; more than one match
  fails closed.
- A reference that cannot be parsed deterministically (credentials in the
  URL, an IP literal, an unsupported scheme) is refused rather than
  guessed.

First-time Discovery for a target that has no recorded host yet must supply
the stable canonical target ID directly (e.g. `target: "gtolab"`) together
with a `host` observation (e.g. `"host": "gtolab.com"`) to register the
association; the runtime never derives that ID by slugging a hostname. A
later lookup by `gtolab.com`, `www.gtolab.com`, or an equivalent URL then
resolves through that recorded association to `gtolab`.

`host` is a separate, per-capability scope for behavior that is not
target-wide (see Capability and Host Scope below). It is the same
mechanism target-reference resolution reads from, but it is never collapsed
into or derived from the target ID.

Because resolution reads these associations, adding a second host to a target
is a durable identity claim, not a convenience. Record it only from evidence
that the same operator serves that host for this brand -- a link, redirect, or
statement on an already-associated host, or matching operator identity on the
new host itself. Shared branding, a similar name, or a plausible relationship
is not evidence.

Two of those rules are machine-checked and the third is not. The finalizer
requires `TARGET_SURFACE` evidence whose locator is on the claimed hostname,
and it refuses a hostname another target already claims, because two
associations make that hostname unresolvable for both. Whether the operator is
genuinely the same is an executor judgment that no check can make for you:
evidence served *from* a hostname proves the hostname exists, never that it
belongs to this brand.

## Capability ID Naming Convention

Capability IDs are target-scoped, stable lower-kebab-case identifiers matching
`[a-z0-9]+(?:-[a-z0-9]+)*`. Spaces, underscores, and punctuation normalize to
hyphens, so `Instructor List`, `instructor-list`, `instructor_list`, and
`instructor / list` all become `instructor-list`; an empty normalized value is
invalid. Normalization never stems, singularizes, translates, removes words,
or uses fuzzy matching.

Before minting an ID, run the combined lookup below with the task's URL or
hostname. On a known target its `index` row lists every capability ID the
target already has, whatever capability ID was asked for; look a possibly
equivalent one up by its own ID and read its record first. Reuse one only
when the actual capability contract has the same reusable output or action,
material scope, authority/access boundary, and completion condition. Semantic
synonyms are never merged automatically: `instructors`, `coaches`, `team`, and
`instructor-directory` remain distinct when equivalence is absent or uncertain.

The capability ID identifies what reusable ability is learned; Operational
Memory records how that ability works; a task result contains the current
values returned by the ability. Thus `instructor-list` may retain a reusable
extraction procedure, but neither its identity nor its reusable knowledge may
contain the current instructor names. Reusability is a property of the
procedure, never of the result: a verification or QA action (does the page
render, is a field present) is as valid a capability as an extraction action,
even though its result differs every run. Capability identity stays semantic
-- never equated with a page, origin, transport, or the current result.

## Knowledge Lookup

Before treating a capability as unknown, run `knowledge-lookup` with the
concrete interpreter and skill path reported by preflight:

```text
<python> <skill>/scripts/knowledge-lookup --target example-jobs --capability project_listings
<python> <skill>/scripts/knowledge-lookup --target jobs.example.com --capability project_listings
<python> <skill>/scripts/knowledge-lookup --knowledge-root <explicit-root> --target example-jobs --capability project_listings
<python> <skill>/scripts/knowledge-lookup --list
<python> <skill>/scripts/knowledge-lookup --target example-jobs
```

The first form is the one call a task needs. `--target` accepts the canonical
ID, or a hostname or URL that resolves through a recorded target<->host
association. Pass the URL or hostname the task names: a caller's own key for a
site (a source ID in the consuming project) is not a target ID, and when it
differs from one it resolves to nothing. Use `--knowledge-root` only for a
caller-supplied override. The normal boundary returns accepted context for
the requested capability:

- `found` — read the accepted capability context.
- `not_found` — no accepted reusable knowledge exists under that capability ID; on a known target, the `index` row (below) names the capability IDs it does have.
- `unresolved` or `bridge_error` — accepted knowledge could not be consulted; stop rather than treating the target as checked.

A `--target` call combined with `--capability` also carries the readiness of
the installation and the target's index row, so the executor needs no
separate `preflight` or `--list` call before it decides:

- `readiness` — `READY`, or the status `preflight` reports on the same root.
- `index_scope` — `target`, `none`, or `unavailable`. The key is absent on an
  `unresolved` or `bridge_error` response, where no Operational Memory
  boundary was reached at all.
- `index` — with scope `target`, that target's single `--list` row: its
  hosts, and each capability ID with its lifecycle and pending count. Scopes
  `none` and `unavailable` carry no `index`: `none` means the reference
  resolved to no target; `unavailable` means no index is available on this
  path (the diagnostic legacy path, or an index read that failed).

The scope follows the target reference, never the capability. A reference
that resolves gets scope `target` whether the capability was found or not, so
a capability ID guessed before the executor saw the target's names still
shows the IDs the target has. The executor picks an equivalent one under the
equivalence rule and looks it up by that ID before acting, because only that
lookup returns the record, and the record may be a block. Nothing is matched
for it: names are never stemmed, aliased, or fuzzy-matched. A miss carries
the row and never the target's profile: callers batch one lookup per source
and cut each reply short, and plan 012 measured a profile on a miss being
cut before its routes in every case and pushing the batch past what the
caller's harness displays. A reference that resolves to no target gets scope
`none` and no index. Retry with the task's URL or hostname if another
reference was passed; otherwise the target is new to this installation, or
it was saved without a host and is found only by its ID or in `--list`. An
executor about to mint a target ID therefore first checks `--list` for an
exact ID to reuse. The finalizer independently refuses to give a hostname
another target already owns to a new target. Every reply prints `status`
first, then `target` and `capability`, then the small fields, and the bulky
`index`, `operational_context`, and `markdown_projection` last; only a hit
carries the last two.

`--list` and a bare `--target` keep their existing shape. `--list` returns an
exact index of every target with its hosts and capability keys, with no
`--target`, and is available on its own for browsing the index. It grows with
the installation, which is why a miss no longer carries it.

Lookup performs no web action, transport selection, knowledge mutation, or publication. It does not silently fall back to historical knowledge.

## Knowledge Boundary

Only reusable operating observations, evidence, and provenance belong in Discovery finalization. When a bounded Discovery has none, use `"observations": []`; this closes as `NOT_SAVED`. Never include task results, raw page dumps, runtime logs, browser-session state, credentials, private user data, business logic, editorial judgment, or speculative facts presented as truth.

### Discovery run markers

After the mode decision and caller authorization, `discovery-begin` creates one
local marker per run and returns its `run_id`. Concurrent runs for the same
target and capability remain distinct. The finalizer refuses to write unless
target, capability, and `provenance.run_id` match that open marker.

Every returned `SAVED`, `ALREADY_EXISTS`, or `NOT_SAVED` verdict closes only
its matching run. Payload and infrastructure errors leave it open. Lookup and
preflight expose unfinished runs, but a marker is never accepted knowledge.
The `run_id` identifies only the execution: Candidate and Claim identity stay
semantic, so a later run with a new ID may enrich an earlier pending Candidate.
Operation creates no marker. `knowledge-lookup` lists pending Candidates under
`pending_candidates`, beside accepted `current` knowledge, never merged into
it; a `CONFLICT_OR_AMBIGUITY` refusal names the accepted or pending Claims
that block the write. Re-running the same pending Claim set without new
material returns `NOT_SAVED`; a later run that adds the missing Validation,
evidence, contradiction, or transport-trace material completes that exact
Candidate, which is then promoted atomically.

Local Operational Memory is writable by the installation's normal policy, unless the caller disables learning for the call (`CARAVELAWEB_LEARNING=disabled`), and is separate from web-action authority. Saving local knowledge never authorizes source-control publication, project-file changes, or external state changes. A successful, directly observed Discovery is available to the next lookup immediately; ambiguous or invalid knowledge is not used operationally. Diagnostic compatibility and repair procedures are not executor input.

An observation made during an active Discovery may guide that same Discovery, but it is accepted Operational Memory only once `discovery-finalize` succeeds. An earlier task's unfinalized observation -- something merely seen, not saved -- is never accepted knowledge: it does not satisfy `knowledge-lookup`, and it never substitutes for lookup or Discovery on a later task.

The public Discovery payload is a closed contract. Its wrapper is exactly
`target`, `capability`, `observations`, `evidence`, `provenance`, optional
`recorded_at`, and optional `transport_trace`. Each observation is exactly
`{family, value, epistemic?, host?, validation?, contradiction?}`; evidence is
`{kind, locator, scope?}` and provenance is `{run_id, observed_at}`. Unknown wrapper, evidence,
provenance, transport-trace, validation-context, contradiction-value, proof,
or family-value fields are rejected before Candidate construction.

`recorded_at` and `provenance.observed_at` are canonical RFC 3339 UTC, in
the form `YYYY-MM-DDTHH:MM:SSZ`. Omit `recorded_at` and the finalizer stamps
the current time; a caller supplies it only to record a different write
instant on purpose, and then only with a value at or before the current
time. `recorded_at` is never later than the current time: a Proposal
recorded in the future is invisible to its own write, so the finalizer
refuses it with `PAYLOAD_VALUE` before writing anything.
`provenance.observed_at` is the instant of observation, never a time taken
from the evidence, so it falls inside the run window: no earlier than the
`opened_at` that `discovery-begin` returned and no later than the write
(`recorded_at`, or the current time when it is omitted). The finalizer
refuses one outside that window with `PROVENANCE` before writing anything.

`observation.host` is a literal behavior scope: `www.example.com` and
`example.com` are distinct hosts there, and the `TARGET_SURFACE` evidence
locator must use the same literal hostname. Target-reference resolution
(above) drops `www.`; host scope does not. Both sides are compared in
canonical ASCII (IDNA) form, so a Unicode locator and its punycode form
match.

Every refusal decided from the payload, the run marker, the Knowledge Root,
or the state of the Operational Memory database carries a `reason_code` from
this closed list of eleven:

- `PAYLOAD_SHAPE` — wrong type, or a missing/unsupported field.
- `PAYLOAD_VALUE` — a closed-set or pattern violation on an otherwise well-shaped field.
- `TASK_DATA_REJECTED` — raw or task-specific content, not reusable knowledge.
- `HOST_SCOPE` — an observation host is missing evidence or already claimed by another target.
- `EVIDENCE_LINKAGE` — an evidence item, or a reference to one, is malformed or unresolved.
- `PROVENANCE` — the run provenance wrapper is missing or malformed, or its `observed_at` is outside the run window.
- `TRANSPORT_TRACE` — the transport ladder trace is malformed or inconsistent.
- `TARGET_REFERENCE` — the `target` argument cannot be resolved to one canonical target.
- `RUN_MARKER` — no open Discovery run marker matches this target, capability, and `run_id`.
- `KNOWLEDGE_ROOT_UNRESOLVED` — no Knowledge Root resolved, so nothing was read or written.
- `OPERATIONAL_MEMORY_UNAVAILABLE` — the Operational Memory database is locked by another process, unreadable, or not writable.

A `NOT_SAVED` decided against accepted knowledge carries a code from a
different closed list, also of eleven values: `NO_REUSABLE_KNOWLEDGE`,
`TRANSPORT_POLICY_UNPROVEN`, `FAILURE_UNCLASSIFIED`, `ALREADY_PENDING`,
`INFERENCE_ONLY`, `CONFIRMATION_PENDING`, `CONFLICT_OR_AMBIGUITY`,
`REPLACEMENT_UNPROVEN`, `INSUFFICIENT_BILATERAL_EVIDENCE`,
`INSUFFICIENT_MATERIAL_BASELINE`, and `INCOMPARABLE_MATERIAL_CONTEXT`.

An observation's `contradiction` is `{prior_value, validation}`: the exact
accepted value it contradicts, and the validation whose `outcome` is
`FAILED` and whose `failure_class` names the cause. It supersedes that
accepted Claim only as one new observation, with no other pending
Candidate, under the same material context as the Claim's own validation,
and with evidence on each side that shares no locator with the other.
The cause then decides:

- `TARGET_CHANGED` -- the target moved, so the old path stopped working.
  The new side must be `FUNCTIONAL`, and replacement is automatic.
- `PROFILE_INCORRECT` -- the accepted Claim was wrong when recorded. The
  new side must be `FUNCTIONAL` or `OBSERVED`, and replacement needs
  `discovery-finalize --authorize-replacement <claim-id>` naming that exact
  Claim, passed only when the caller explicitly authorized replacing it.
  Without it the result is `REPLACEMENT_UNPROVEN` and the new Claim stays
  pending. An authorization the payload cannot use -- another Claim, another
  cause, a failing new side, or a competing pending Candidate -- is refused
  with `PAYLOAD_VALUE` before any write, and the run stays open.

Any other cause leaves the new Claim pending. Never relabel a wrong Claim as
`TARGET_CHANGED` to make it replace automatically: the stored cause is the
audit trail. A replacement closes the old Claim with `SUPERSEDE` and accepts
the new one with `ACCEPT_SUPERSEDE`; both stay in history.

A browser-backed result also carries the run-scoped `transport_trace` defined in
`SKILL.md`; the finalizer validates its preflight availability and evidenced
attempt order before writing, then discards it rather than storing runtime
availability as target knowledge. Family values use only:

- `transport`: `transport`, `outcome`, `requirement`;
- `search_surface`: `surface`, `path`, `entrypoint`, `method`, `loading`;
- `extraction`: `structure`, `field_paths`, `selectors`, `transport`, `outcome`, `evidence_quality`;
- `pagination`: `mode`, `parameter`, `path`, `next_path`, `stop_condition`;
- `paywall`: `signal`, `state`, `condition`;
- `authentication`: `access_model`, `entrypoint`, `condition`;
- `blocking`: `failure_class`, `signal`, `state`, `condition`;
- `limitation`: `kind`, `mode`, `state`, `condition`, `constraint`;
- `unknown`: `state`, `subject`, `condition`;
- `validation`: exactly one of `rule` or `operational_proof`.

`field_paths` and `selectors` are maps from output-field identifiers to source
paths/selectors. Thus `{"name":"items[].name"}` is legal inside `field_paths`,
while `{"name":"Current Person"}` is not a legal extraction value. Structured
result objects and arrays have no public persistence position.

`field_paths` accepts dotted paths (`post.headline`), collection paths
(`items[].name`, `items[0].name`), and an explicit-root path starting with
`$` (`$.headline`, `$.article.full_text`) for a field at the root of a single
record. A bare word such as `headline` is rejected -- it is indistinguishable
from a one-word task result -- and its error names `$.headline` as the fix.

## Epistemic Classes

Every meaningful claim is one of:

- **OBSERVED** — directly established.
- **INFERRED** — reasonable but not validated.
- **UNKNOWN** — not established.

Inference must never silently become an operational dependency, and unknowns must not be hidden to make a report look complete.

## Lifecycle States

```text
UNKNOWN -> DISCOVERING -> UNDERSTOOD -> OPERATIONAL -> DEGRADED -> (DISCOVERING)
any state -> RETIRED -> (DISCOVERING, on explicit reactivation)
```

- **UNKNOWN** — no trusted transport, route, or authentication assumption.
- **DISCOVERING** — bounded investigation is in progress; evidence may remain insufficient.
- **UNDERSTOOD** — behavior and constraints are mapped, but no routine path is validated.
- **OPERATIONAL** — this capability has a sufficiently validated routine path; it does not authorize other capabilities or actions.
- **DEGRADED** — a validated assumption was contradicted; stop trusting that part and rediscover only the affected capability.
- **RETIRED** — intentionally not used; do not resume on stale assumptions.

`UNDERSTOOD + BLOCKED` reuses the recorded blocker while relevant conditions remain unchanged. A target-level state is only a summary: always use the capability's state. One timeout, DNS failure, 5xx, browser crash, tool bug, expired auth, isolated rate limit, or interstitial does not itself degrade knowledge; classify it first.

## Capability and Host Scope

Capabilities are the unit of knowledge: evidence for `search` never validates `detail`, `login`, or `application_submission`. A target can contain operational and unknown capabilities at the same time.

For a multi-host target, record the affected host when behavior differs. Transport compatibility and blocking are host-scoped: a pass or block on one host does not generalize to another host without separate validation.

## Completion Semantics

An `OPERATIONAL` capability records enough evidence to reproduce the requested path: target and capability, access model, transport, entrypoint, observable completion condition, required output or action, critical constraints, and validation evidence. Browser-backed evidence also records the actually observed `agent-browser` and engine context when material.

Discovery cannot assert lifecycle directly. The finalizer earns `OPERATIONAL` from accepted `OBSERVED` transport and authentication facts plus one canonical `validation` value: `{"operational_proof":{"entrypoint":"...","required_output":{"field_paths":{"field":"items[].field"}},"completion_condition":"...","critical_constraints":[]}}`; a string `required_action` may replace the output schema, but exactly one is required. Entrypoint and completion condition are strings; constraints are strings, with an empty array meaning none material were observed. Its validation outcome must be exactly `SUCCESS`, evidence references must be explicit, and browser transports require explicit engine and JavaScript context. The generated lifecycle Claim records its supporting Claim IDs. Lookup suppresses an unverified lifecycle assertion, or one whose supporting Claims are no longer current or are contradicted.

A `SAVED` response that does not earn `OPERATIONAL` reports `lifecycle_gap`, one of:

- `CANDIDATE_NOT_AUTOMATIC` — the Candidate did not qualify for automatic promotion, so no proof was evaluated.
- `PROOF_SHAPE_INVALID` — the `operational_proof` value is not canonical, is missing a required key, or has both or neither of `required_output`/`required_action`.
- `PROOF_VALIDATION_NOT_SUCCESS` — the proof's `validation.outcome` is not exactly `SUCCESS`, or it carries no evidence.
- `PROOF_CONTRADICTED` — the proof Claim is itself a contradicted Claim.
- `PROOF_EVIDENCE_UNREFERENCED` — the proof's evidence references are not in the payload, or not previously recorded.
- `PROOF_CONTEXT_INCOMPLETE` — the proof's validation names no transport or no `context.authentication`.
- `PROOF_BROWSER_CONTEXT_INCOMPLETE` — a browser-transport proof is missing its engine or JavaScript context.
- `SUPPORTING_CLAIM_NOT_OBSERVED` — a transport or authentication Claim in scope is not `OBSERVED` and canonical.
- `TRANSPORT_LADDER_UNPROVEN` — a browser transport was not proven by this run's `transport_trace`.
- `NO_FUNCTIONAL_TRANSPORT_CLAIM` — no accepted transport fact reports the proof's transport as `FUNCTIONAL`.
- `NO_AUTHENTICATION_CLAIM` — no accepted authentication fact matches the proof's `access_model`.
- `SUPPORTING_FACTS_AMBIGUOUS` — more than one distinct transport or access model is in scope for this proof.
- `NO_OPERATIONAL_PROOF` — the run had no eligible `operational_proof` at all.
- `MULTIPLE_ELIGIBLE_PROOFS` — more than one proof was independently eligible, so none was chosen automatically.

Transport outcomes have asymmetric roles: `FAILED` and `INSUFFICIENT` prove
why escalation was needed, while only `FUNCTIONAL` identifies a possible
operational transport. Distinct transports may therefore coexist without
conflict. A browser transport can support a new lifecycle only when the same
finalization run proves the complete available ladder; a legacy browser Claim
cannot gain `OPERATIONAL` from a later proof-only payload.

A ladder with no `FUNCTIONAL` transport is still a complete result when it was
exhausted -- every available transport attempted, each with its evidence. That
finalizes normally and records the block; it identifies no operational
transport, so it earns no `OPERATIONAL` lifecycle. Only a ladder abandoned
while an available transport was untried stays unproven. Reaching the last
step the transport policy permits is not exhaustion on its own: the policy
halts at an `UNAVAILABLE` Lightpanda tier even when Chrome exists on the
machine, and a run that never reached Chrome cannot report the capability as
blocked.

Such a ladder must also classify why it failed, using the vocabulary in
`transport-and-modes.md`. `FAILED` alone does not distinguish a target that
blocked this run from a network that dropped one request. Only a durable class
saves: `TRANSIENT_NETWORK`, `UPSTREAM_TOOL_ERROR`, `LOCAL_ENVIRONMENT`,
`PLATFORM_UNSUPPORTED`, and `UNKNOWN` describe the runtime or the machine, not
the target, so a run classified that way records nothing. Never delete an
observation, a `validation`, or an evidence item to satisfy the finalizer: a
rejection means the payload is wrong, never that the evidence is unwelcome.

`SAVED` and lookup `found` remain acceptance signals. Partial reusable facts keep both properties without becoming `OPERATIONAL`; a later Discovery may complete the proof from the current accepted facts plus its new delta.

Readiness says a surface is ready to inspect; completion says the requested capability produced the required result. Use an observable readiness condition and bounded timeout when readiness is needed. A page load, HTTP 200, or elapsed sleep is never sufficient proof of completion.

A well-understood blocked capability records its lifecycle, availability, relevant host, blocker/failure class, observed evidence, and conditions that would need to change. Do not invent operational fields that were never reached.

`blocking` and `limitation` assert a constraint or an absence -- the claims
that are easiest to overstate and hardest to reread later. Claiming `OBSERVED`
for one therefore requires a `validation` naming the transport, engine, and
context that saw it. Without that, report the constraint as `INFERRED`: an
inference alone never becomes accepted knowledge. Keep the claim inside what
was actually seen. "No functional feed was found on the surfaces reached" is
supportable; "no official feed exists" claims the whole permitted scope and
needs evidence covering it.

That scope rule covers every claim, not only absence claims: each one stays
inside what this run demonstrated. A `condition` or `constraint` states the
observed behavior and the input shapes it was seen with, such as "the single-term
query tried returned results; the two- and five-term queries returned
none". It never gives advice that generalizes beyond them, such as "use one
or two distinctive terms" when no two-term query succeeded. Its `validation`
cites the requests that actually showed the constraint, not only the one that
succeeded; example 9 in `discovery-payload-examples.md` is shaped this way.
`extraction.selectors` are `OBSERVED` only when they were executed as
selectors against the page. A structure inferred from markup was not observed:
leave it out of an `OBSERVED` extraction.

## Authentication

Knowledge may state where authentication is required or whether human-assisted auth is expected. It must never contain passwords, tokens, API secrets, recovery codes, MFA seeds, or reusable session cookies. Credentials remain in the consuming environment.
