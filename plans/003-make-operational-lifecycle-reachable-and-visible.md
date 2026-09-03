# Plan 003: Make the `OPERATIONAL` lifecycle reachable and visible

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 929c0b1..HEAD -- discovery_finalize.py operational_memory/core.py integration_bridge.py scripts/knowledge-lookup scripts/discovery-finalize references/discovery-payload-examples.md references/target-profile.md SKILL.md tests/test_discovery_finalize.py tests/test_discovery_payload_examples.py tests/test_integration_bridge.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `929c0b1`, 2026-09-02

## Why this matters

The contract's whole point is that a capability, once proven, runs in
**Operation** mode without re-Discovery (`SKILL.md:61`). In three weeks of
real use (46 accepted Decisions, 19 capabilities carrying an
`operational_proof`), **zero** capabilities earned the `OPERATIONAL`
lifecycle. The finalizer silently drops the lifecycle Claim whenever any of
about twelve conditions fails (most often: no `authentication` observation,
or the proof's `validation.outcome` is `FUNCTIONAL` instead of `SUCCESS`),
the response still says `SAVED`, and lookup output has no lifecycle field at
all. The executor cannot tell that the proof was discarded, so it repeats
the full Discovery ceremony every time. This plan makes the finalizer say
whether `OPERATIONAL` was earned and why not, makes lookup say the lifecycle
state, and adds one documented, tested payload that earns it.

## Current state

Relevant files:

- `discovery_finalize.py:509-654` — `_operational_proof_dependencies`
  returns the proving Claim IDs or `None`, with `continue` on every failed
  condition and no reason.
- `discovery_finalize.py:1442-1462` — the lifecycle Claim is appended only
  when that function returned IDs.
- `discovery_finalize.py:116-147` — `DiscoveryFinalization.as_dict` (the CLI
  response shape).
- `operational_memory/core.py:1172-1206` — `render_operational_context`;
  `core.py:1230-1245` — `has_verified_operational_lifecycle`.
- `references/discovery-payload-examples.md` — 7 examples; none earns
  `OPERATIONAL`. `tests/test_discovery_payload_examples.py` finalizes each
  and asserts `SAVED` only.
- `references/target-profile.md:200` — the only prose describing the recipe.

Excerpts as of commit `929c0b1`:

`discovery_finalize.py:1442-1462`
```python
    proof_claim_ids = (
        _operational_proof_dependencies(
            memory, target, capability, claims, clean_evidence,
            validated_transport,
        )
        if automatic else None
    )
    if proof_claim_ids and not memory.has_verified_operational_lifecycle(target, capability):
        lifecycle_id = (
            f"clm:{target}:{capability}:lifecycle-operational-"
            f"{_digest(proof_claim_ids)}"
        )
        claims.append({
            "id": lifecycle_id,
            "family": "lifecycle",
            "epistemic": "OBSERVED",
            "value": "OPERATIONAL",
            "operational_proof": {
                "version": _OPERATIONAL_PROOF_VERSION,
                "claim_ids": list(proof_claim_ids),
            },
        })
```

The `continue` sites inside `_operational_proof_dependencies` (lines
509-654), in order, and the reason each stands for:

| Line (approx.) | Condition | Reason code to emit |
|---|---|---|
| 540-552 | proof value not canonical / missing required keys / both or neither of `required_output`,`required_action` | `PROOF_SHAPE_INVALID` |
| 554-559 | entrypoint / completion_condition / output empty | `PROOF_SHAPE_INVALID` |
| 560-566 | `validation.outcome != "SUCCESS"` or no `validation.evidence` | `PROOF_VALIDATION_NOT_SUCCESS` |
| 567-569 | proof claim contradicted | `PROOF_CONTRADICTED` |
| 570-579 | evidence references not in payload / not recorded | `PROOF_EVIDENCE_UNREFERENCED` |
| 581-585 | validation has no transport or no `context.authentication` | `PROOF_CONTEXT_INCOMPLETE` |
| 586-590 | browser transport without engine / javascript | `PROOF_BROWSER_CONTEXT_INCOMPLETE` |
| 604-618 | a transport or authentication claim in scope is not OBSERVED / canonical | `SUPPORTING_CLAIM_NOT_OBSERVED` |
| 623-626 | browser transport not proven by this run's trace | `TRANSPORT_LADDER_UNPROVEN` |
| 635-650 | `transports != {transport}` or `access_models != {access_model}` | `NO_FUNCTIONAL_TRANSPORT_CLAIM` when `transports` is empty; `NO_AUTHENTICATION_CLAIM` when `access_models` is empty; otherwise `SUPPORTING_FACTS_AMBIGUOUS` |
| 654 | `len(eligible) != 1` | `NO_OPERATIONAL_PROOF` when 0 proofs were found at all; `MULTIPLE_ELIGIBLE_PROOFS` when > 1 |

Proven on a scratch memory: a payload with `transport` FUNCTIONAL +
`authentication {"access_model":"PUBLIC"}` + `validation.operational_proof`
whose `validation` has `outcome: "SUCCESS"` earns a `lifecycle` claim visible
under `current.lifecycle` in lookup. The identical payload minus the
`authentication` observation still returns `SAVED` and earns nothing.

`discovery_finalize.py:138-147` (`as_dict`)
```python
    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status, "target": self.target, "capability": self.capability,
        }
        if self.status == "NOT_SAVED" and self.reason:
            result["reason"] = self.reason
        if self.status == "NOT_SAVED" and self.reason_code:
            result["reason_code"] = self.reason_code
        result["run_state"] = "CLOSED" if self.closes_run else "OPEN"
        return result
```

`operational_memory/core.py:1230-1245` — `has_verified_operational_lifecycle(target, capability) -> bool` already exists and is the read-side truth.

`references/target-profile.md:200` (the recipe, prose only): "The finalizer
earns `OPERATIONAL` from accepted `OBSERVED` transport and authentication
facts plus one canonical `validation` value: `{"operational_proof": {...}}`
... Its validation outcome must be exactly `SUCCESS` ...".

Conventions:

- Response keys lower_snake; codes UPPER_SNAKE English.
- `tests/test_discovery_payload_examples.py:50-70` runs every fenced JSON
  block of the examples file through the real CLIs and asserts `SAVED` and
  `CLOSED`. Adding an example there is the way to keep docs and code locked.
- Existing test `tests/test_integration_bridge.py:99-121` asserts
  `assertNotIn("lifecycle", current)` for an unverified lifecycle claim; keep
  `current` semantics unchanged and add a **new** top-level key instead.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Full suite | `python3 -m unittest discover -s tests -p 'test_*.py'` | `OK` |
| Examples | `python3 -m unittest tests.test_discovery_payload_examples -v` | pass |
| Finalize | `python3 -m unittest tests.test_discovery_finalize -v` | pass |
| Whitespace | `git diff --check` | no output |

## Scope

**In scope**:
- `discovery_finalize.py`
- `scripts/discovery-finalize` (no logic change expected; only if `as_dict` output needs plumbing)
- `operational_memory/core.py` (`render_operational_context` only)
- `integration_bridge.py`, `scripts/knowledge-lookup` (surface the new key)
- `references/discovery-payload-examples.md`, `references/target-profile.md`, `SKILL.md`
- `tests/test_discovery_finalize.py`, `tests/test_discovery_payload_examples.py`, `tests/test_integration_bridge.py`

**Out of scope**:
- Relaxing any eligibility rule (for example accepting `FUNCTIONAL` as a
  proof outcome). This plan reports; it does not loosen.
- `om_native_writes.py`, `discovery_runs.py`.
- Migrating existing memories (a later Discovery can add the missing
  `authentication` fact and earn the lifecycle on the same Candidate).

## Git workflow

- Branch: `advisor/003-operational-visibility`
- One imperative sentence per commit, sentence case, no prefix.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Return a reason from `_operational_proof_dependencies`

Change the signature to return `tuple[tuple[str, ...] | None, str | None]`:
`(claim_ids, None)` on success, `(None, <code>)` otherwise, using the code
table above. Implement by tracking `gap: str | None` — set it at the first
`continue` reached for the *last-considered* proof, and set
`"NO_OPERATIONAL_PROOF"` when `proofs` is empty. Keep the eligibility logic
byte-for-byte otherwise. Update the single call site (line ~1443):

```python
    proof_claim_ids, lifecycle_gap = (
        _operational_proof_dependencies(...) if automatic else (None, "CANDIDATE_NOT_AUTOMATIC")
    )
```

Also: when `proof_claim_ids` is truthy but
`memory.has_verified_operational_lifecycle(target, capability)` is already
true, set `lifecycle_gap = None` and mark `lifecycle_state = "OPERATIONAL"`
(already earned earlier).

**Verify**: `python3 -m unittest tests.test_discovery_finalize -v` → pass (no behavior change yet).

### Step 2: Report lifecycle in the finalize response

Add two fields to `DiscoveryFinalization`: `lifecycle: str | None = None`
and `lifecycle_gap: str | None = None`. In `finalize_discovery`, on the
`SAVED` return (line ~1603) pass `lifecycle="OPERATIONAL"` when the lifecycle
Claim was appended in this run or already verified, else `lifecycle=None,
lifecycle_gap=<code>`. In `as_dict`, for `status == "SAVED"` (and
`ALREADY_EXISTS`), always emit `"lifecycle"` (value or `null`) and emit
`"lifecycle_gap"` only when `lifecycle` is `null`. Leave `NOT_SAVED`
responses unchanged.

**Verify**: run the scratch reproduction: seed a temp root (pattern
`tests/test_discovery_runs.py:20-60`), finalize the operational payload from
Step 5 → stdout contains `"lifecycle": "OPERATIONAL"`; finalize the same
payload without the `authentication` observation under a new capability →
`"lifecycle": null, "lifecycle_gap": "NO_AUTHENTICATION_CLAIM"`.

### Step 3: Report lifecycle in lookup

`operational_memory/core.py`, `render_operational_context`: add
`"lifecycle": "OPERATIONAL" if self.has_verified_operational_lifecycle(target, capability) else None`
to the returned dict (top level, sibling of `current`). Do **not** change
`current`. In `scripts/knowledge-lookup`, for a capability-scoped `found`,
also emit `lifecycle=result.operational_context["lifecycle"]` at the top
level of the JSON line so the executor does not need to dig. For
target-only lookups, each capability context already carries the key.

**Verify**: `python3 -m unittest tests.test_integration_bridge -v` → pass; `assertNotIn("lifecycle", current)` at line 121 still holds.

### Step 4: Contract text

- `SKILL.md` step 3 table (line 59-65): the first row's condition becomes
  "`lifecycle` is `OPERATIONAL` in lookup and task authority is sufficient".
- `SKILL.md` step 7, after line 115 ("`SAVED` and lookup `found` mean
  accepted context exists, not that the capability is `OPERATIONAL`"), add:
  "Every `SAVED` response reports `lifecycle`: `OPERATIONAL`, or `null` with
  a `lifecycle_gap` code naming the first missing proof condition
  (`NO_AUTHENTICATION_CLAIM`, `PROOF_VALIDATION_NOT_SUCCESS`,
  `NO_FUNCTIONAL_TRANSPORT_CLAIM`, ...). To earn `OPERATIONAL` in one run,
  the payload needs: one `transport` observation with outcome `FUNCTIONAL`;
  one `authentication` observation with `access_model` equal to the proof
  validation's `context.authentication`; and one `validation` observation
  carrying `operational_proof` whose own `validation` has
  `outcome: "SUCCESS"` and evidence from the payload's evidence list. See
  example 8 in `references/discovery-payload-examples.md`."
- `references/target-profile.md:200`: append the list of `lifecycle_gap`
  codes with one line each.

**Verify**: `python3 -m unittest tests.test_skill_adapter_parity tests.test_marker_parity tests.test_public_vocabulary -v` → pass.

### Step 5: Example 8 in the payload reference, with a test that it earns the lifecycle

Append to `references/discovery-payload-examples.md`:

```json
{
  "target": "example-operational",
  "capability": "article-read",
  "observations": [
    {
      "family": "transport", "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"},
      "validation": {
        "transport": "DIRECT_READ", "outcome": "FUNCTIONAL", "engine": null, "javascript": false,
        "context": {"authentication": "PUBLIC", "environment": "PRODUCTION"},
        "evidence": ["https://example-operational.example/articles/1"]
      }
    },
    {"family": "authentication", "value": {"access_model": "PUBLIC"}},
    {
      "family": "validation",
      "value": {"operational_proof": {
        "entrypoint": "https://example-operational.example/articles/{id}",
        "required_output": {"field_paths": {"headline": "$.headline"}},
        "completion_condition": "HTTP 200 whose HTML carries a headline element",
        "critical_constraints": []
      }},
      "validation": {
        "transport": "DIRECT_READ", "outcome": "SUCCESS", "engine": null, "javascript": false,
        "context": {"authentication": "PUBLIC", "environment": "PRODUCTION"},
        "evidence": ["https://example-operational.example/articles/1"]
      }
    }
  ],
  "evidence": [{"kind": "direct-read-validation", "locator": "https://example-operational.example/articles/1"}],
  "provenance": {"run_id": "<from discovery-begin>", "observed_at": "2026-08-14T12:00:00Z"},
  "recorded_at": "2026-08-14T12:00:00Z"
}
```

Heading: "## 8. A complete operational proof that earns `OPERATIONAL`", with
two sentences naming the three required observations and the `SUCCESS`
outcome. In `tests/test_discovery_payload_examples.py`, add
`test_the_operational_example_earns_the_lifecycle`: finalize only the payload
whose target is `example-operational` (reuse the loop body), assert
`body["lifecycle"] == "OPERATIONAL"`, then run `scripts/knowledge-lookup`
for it and assert the top-level `lifecycle == "OPERATIONAL"`. Also bump the
count assertion at line 47 from 7 to 8.

**Verify**: `python3 -m unittest tests.test_discovery_payload_examples -v` → pass.

### Step 6: Gap-code tests

In `tests/test_discovery_finalize.py`, add a class `LifecycleGapTests` using
the file's `payload()`/`finalize()` helpers with the example-8 observations
adapted to `example-news`/`topic-search`:

- full payload → `result.lifecycle == "OPERATIONAL"`, `lifecycle_gap is None`;
- without `authentication` → `lifecycle_gap == "NO_AUTHENTICATION_CLAIM"`;
- proof validation `outcome: "FUNCTIONAL"` → `"PROOF_VALIDATION_NOT_SUCCESS"`;
- no `validation` family observation at all → `"NO_OPERATIONAL_PROOF"`;
- transport outcome `FAILED` only → `"NO_FUNCTIONAL_TRANSPORT_CLAIM"`.

**Verify**: `python3 -m unittest tests.test_discovery_finalize -v` → pass.

## Test plan

- Step 5: one example test; Step 6: five gap tests; Step 3 covered by the
  bridge suite plus one new assertion that `"lifecycle"` is a top-level key
  in the capability-scoped CLI output (add to
  `test_runtime_bridge_script_passes_controlled_lookup`).
- Verification: full suite `OK`, at least 7 new tests.

## Done criteria

- [ ] `python3 -m unittest discover -s tests -p 'test_*.py'` exits 0
- [ ] `grep -c '"lifecycle"' discovery_finalize.py` ≥ 2 and `grep -n "lifecycle_gap" discovery_finalize.py SKILL.md` return hits
- [ ] Example 8 exists in `references/discovery-payload-examples.md` and the examples test asserts `lifecycle == "OPERATIONAL"` for it
- [ ] `git diff --check` prints nothing
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The `continue` sites in `_operational_proof_dependencies` do not match the
  table above (line drift); report the real structure.
- Making the example-8 payload earn `OPERATIONAL` requires changing any
  eligibility rule.
- `tests/test_integration_bridge.py:121` (`assertNotIn("lifecycle", current)`)
  starts failing — that means lifecycle leaked into `current`.

## Maintenance notes

- Every new `continue` added to `_operational_proof_dependencies` must set a
  gap code; add a test asserting no `continue` leaves `gap` unset (a simple
  guard: the function must never return `(None, None)`).
- The gap code is diagnostic only; it is never stored in Operational Memory.
- Follow-up (not in this plan): the maintainer's existing memory has 19
  proof-bearing capabilities with no `authentication` claim. A later
  Discovery on each can add it and earn the lifecycle without re-proving the
  transport.
