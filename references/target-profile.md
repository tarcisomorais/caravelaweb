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

Before minting an ID, run target-only `knowledge-lookup --target <target-id>`
and inspect its accepted capability IDs. Reuse one only when the actual
capability contract has the same reusable output or action, material scope,
authority/access boundary, and completion condition. Semantic synonyms are
never merged automatically: `instructors`, `coaches`, `team`, and
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
<python> <skill>/scripts/knowledge-lookup --target example-jobs
<python> <skill>/scripts/knowledge-lookup --target example-jobs --capability project_listings
<python> <skill>/scripts/knowledge-lookup --knowledge-root <explicit-root> --target example-jobs --capability project_listings
```

Use `--knowledge-root` only for a caller-supplied override. The normal boundary returns accepted context for the requested capability:

- `found` — read the accepted capability context.
- `not_found` — no accepted reusable knowledge exists for that capability.
- `unresolved` or `bridge_error` — accepted knowledge could not be consulted; stop rather than treating the target as checked.

Lookup is capability-scoped and performs no web action, transport selection, knowledge mutation, or publication. It does not silently fall back to historical knowledge.

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
Operation creates no marker.

Local Operational Memory is writable by the installation's normal policy and is separate from web-action authority. Saving local knowledge never authorizes source-control publication, project-file changes, or external state changes. A successful, directly observed Discovery is available to the next lookup immediately; ambiguous or invalid knowledge is not used operationally. Diagnostic compatibility and repair procedures are not executor input.

An observation made during an active Discovery may guide that same Discovery, but it is accepted Operational Memory only once `discovery-finalize` succeeds. An earlier task's unfinalized observation -- something merely seen, not saved -- is never accepted knowledge: it does not satisfy `knowledge-lookup`, and it never substitutes for lookup or Discovery on a later task.

The public Discovery payload is a closed contract. Its wrapper is exactly
`target`, `capability`, `observations`, `evidence`, `provenance`, optional
`recorded_at`, and optional `transport_trace`. Each observation is exactly
`{family, value, epistemic?, host?, validation?, contradiction?}`; evidence is
`{kind, locator, scope?}` and provenance is `{run_id, observed_at}`. Unknown wrapper, evidence,
provenance, transport-trace, validation-context, contradiction-value, proof,
or family-value fields are rejected before Candidate construction.

Every payload refusal's `reason_code` is one of eight values:

- `PAYLOAD_SHAPE` — wrong type, or a missing/unsupported field.
- `PAYLOAD_VALUE` — a closed-set or pattern violation on an otherwise well-shaped field.
- `TASK_DATA_REJECTED` — raw or task-specific content, not reusable knowledge.
- `HOST_SCOPE` — an observation host is missing evidence or already claimed by another target.
- `EVIDENCE_LINKAGE` — an evidence item, or a reference to one, is malformed or unresolved.
- `PROVENANCE` — the run provenance wrapper is missing or malformed.
- `TRANSPORT_TRACE` — the transport ladder trace is malformed or inconsistent.
- `TARGET_REFERENCE` — the `target` argument cannot be resolved to one canonical target.

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

## Authentication

Knowledge may state where authentication is required or whether human-assisted auth is expected. It must never contain passwords, tokens, API secrets, recovery codes, MFA seeds, or reusable session cookies. Credentials remain in the consuming environment.
