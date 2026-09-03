# Plan 001: Surface pending Candidates in lookup and name the conflicting Claims in `CONFLICT_OR_AMBIGUITY`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 929c0b1..HEAD -- operational_memory/core.py integration_bridge.py scripts/knowledge-lookup discovery_finalize.py SKILL.md references/target-profile.md tests/test_integration_bridge.py tests/test_discovery_finalize.py`
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

`knowledge-lookup` reports `not_found` for a capability that has pending
(never accepted) Claims, and `discovery-finalize` then refuses every new
observation for that capability with `CONFLICT_OR_AMBIGUITY` because the
pending values count as "other values" in the conflict gate. The executor
sees "nothing known" plus "conflict" and has no way to learn what conflicts.
In the maintainer's real memory this produced a permanently stuck capability
(`financial-times` / `article-full-text-access`, two pending proposals) and a
duplicate capability minted to escape it (`article-text-access`, accepted with
the same content). The same pattern hit `bloomberg` /
`international-geopolitics-rss-feed`. After this plan, lookup shows the
pending Candidates as a sibling of accepted knowledge, and the conflict
refusal names the exact Claims that block the write. Plan 002 adds the
command that discards a pending Candidate; this plan makes the state visible
and the refusal actionable.

## Current state

Relevant files:

- `operational_memory/core.py` — SQLite store. `get_pending_candidates`
  (line 1130) already computes pending proposals; `render_operational_context`
  (line 1172) builds the lookup payload from accepted Claims only.
- `integration_bridge.py` — `KnowledgeLookupBoundary.lookup` (line 44) turns
  an empty accepted view into a bare `not_found` result (lines 82-96).
- `scripts/knowledge-lookup` — CLI that prints the result as JSON (lines 44-59).
- `discovery_finalize.py` — `_has_conflict` (line 1181) returns a bool; the
  refusal is built at lines 1582-1601 with a fixed reason string.
- `SKILL.md` — step 2 result table (lines 46-55) maps `not_found` to "enter
  Discovery", and step 7 (line 132) says a pending Candidate can be enriched.

Excerpts as of commit `929c0b1`:

`integration_bridge.py:76-96`
```python
                try:
                    target_id = memory.resolve_target(target)
                except KeyError:
                    return LookupResult(source="operational-memory", target=target, capability=capability)
                if capability:
                    # A valid OM database with no such capability is an honest
                    # absence. Keep this catch around identity resolution only;
                    # query/schema/database failures remain bridge_error.
                    try:
                        memory.resolve_capability(target, capability)
                    except KeyError:
                        return LookupResult(source="operational-memory", target=target, capability=capability)
                    context = memory.render_operational_context(target, capability, caller_context)
                    if not any(context["current"].values()):
                        return LookupResult(source="operational-memory", target=target, capability=capability)
                else:
                    keys = memory.list_capability_keys(target)
                    contexts = {}
                    for key in keys:
                        rendered = memory.render_operational_context(target, key, caller_context)
                        if any(rendered["current"].values()):
                            contexts[key] = rendered
```

`scripts/knowledge-lookup:44-59`
```python
    open_discovery = list_open_discoveries(
        root, target=result.target, capability=result.capability,
    )
    visibility = {"open_discovery": open_discovery} if open_discovery else {}
    if result.source == "legacy":
        ...
    if result.operational_context is None:
        emit("not_found", source="operational-memory", target=args.target, **visibility)
        return 0
    emit("found", source="operational-memory", target=args.target, capability=result.capability, operational_context=result.operational_context, markdown_projection=result.markdown_projection, **visibility)
    return 0
```

`operational_memory/core.py:1130-1170` (`get_pending_candidates`) returns
`[{"proposal_id", "capability_id", "claim_ids"}]` for the pending proposals
of one target/capability. `core.py:802` `_claim_rows(claim_ids)` returns the
claim dicts (`id`, `family`, `epistemic`, `value`, `host_id`, ...) for a list
of IDs.

`operational_memory/core.py:1195-1206` (tail of `render_operational_context`)
```python
        return {
            "target_id": self.resolve_target(target),
            "capability_id": capability_id,
            "hosts": hosts,
            "current": dict(sorted(families.items())),
            "warnings": view["contradiction_warnings"],
            "minimal_evidence_refs": sorted(evidence_refs),
            "caller_context": dict(caller_context or {}),
            "history_included": False,
        }
```

`discovery_finalize.py:1181-1192` and `1246-1262` (`_has_conflict`)
```python
def _has_conflict(
    memory: SQLiteOperationalMemory,
    target: str,
    capability: str,
    delta: Sequence[Mapping[str, Any]],
    host_ids: Mapping[str, str],
) -> bool:
    """Keep conflicting observations out of automatic acceptance.
    ...
    return any(
        current_values.get((
            item["family"],
            host_ids.get(str(item.get("host"))) if item.get("host") else None,
            item["value"].get("transport") if item["family"] == "transport" else None,
        ), set()) - {
            json.dumps(
                item["value"], ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            )
        }
        for item in conflict_delta
    )
```

Note that `current_values` at line 1230-1245 is built from
`current_claim_ids | pending_claim_ids` and keeps only `family`, `value_json`,
`host_id`; the claim `id` is dropped, so the caller cannot name the
conflicting Claims today.

`discovery_finalize.py:1582-1601`
```python
    if not automatic and not replacement_ready:
        if any(item["epistemic"] != "OBSERVED" for item in delta):
            reason_code = "INFERENCE_ONLY"
        elif replacement_refusal:
            reason_code = replacement_refusal
        elif any(item.get("contradiction") for item in delta):
            reason_code = "REPLACEMENT_UNPROVEN"
        elif has_conflict:
            reason_code = "CONFLICT_OR_AMBIGUITY"
        else:
            reason_code = "CONFIRMATION_PENDING"
        return DiscoveryFinalization(
            "NOT_SAVED", target, capability, proposal_id, len(claims),
            reason="Conflicting or unconfirmed information blocked validation of a reusable path.",
            reason_code=reason_code,
        )
```

Reproduction on a scratch copy of a real memory (do not run against the
user's root): `discovery-finalize --validate` for
`financial-times`/`article-full-text-access` returned
`{"would_finalize_as": "NOT_SAVED", "would_reason_code": "CONFLICT_OR_AMBIGUITY"}`
while `knowledge-lookup --target financial-times --capability article-full-text-access`
returned `not_found`.

Conventions to honor:

- Documented invariant, `docs/operational-memory.md:29`: "Pending proposals
  do not silently become accepted knowledge." Pending data must therefore be a
  **sibling** of `current`, never merged into it.
- `SKILL.md:55`: lookup "returns accepted knowledge without silently
  substituting historical knowledge". Keep `status` values `found` /
  `not_found` unchanged; add fields.
- JSON output uses `json.dumps(..., ensure_ascii=False, sort_keys=True)`; see
  `scripts/knowledge-lookup:22-23` (`emit`).
- Tests are `unittest`, one class per surface, seeded through
  `memory.write_transaction()`; model new tests on
  `tests/test_integration_bridge.py:20-121` and
  `tests/test_discovery_finalize.py:36-80`.
- Vocabulary: reason codes are UPPER_SNAKE English; keys are lower_snake.
  `tests/test_public_vocabulary.py` scans every tracked file for retired
  Portuguese identifiers, so never reintroduce those.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Full suite | `python3 -m unittest discover -s tests -p 'test_*.py'` | `OK`, 319+ tests |
| One file | `python3 -m unittest tests.test_integration_bridge -v` | all pass |
| Whitespace | `git diff --check` | no output |
| Lookup smoke | `python3 scripts/knowledge-lookup --knowledge-root <tmp> --target x` | JSON line |

## Scope

**In scope** (the only files you should modify):
- `operational_memory/core.py`
- `integration_bridge.py`
- `scripts/knowledge-lookup`
- `discovery_finalize.py`
- `SKILL.md`
- `references/target-profile.md`
- `tests/test_integration_bridge.py`
- `tests/test_discovery_finalize.py`

**Out of scope** (do NOT touch, even though they look related):
- `om_native_writes.py` — no write-path change here; discarding pending
  Candidates is plan 002.
- The conflict *rule* itself (which values count as conflicting). This plan
  only reports what the rule found.
- `skills/caravelaweb/SKILL.md`, `.claude/skills/...`, `.agents/skills/...` —
  thin adapters; `tests/test_skill_adapter_parity.py` guards them.

## Git workflow

- Branch: `advisor/001-pending-visibility`
- Commit per step. Message style: one imperative sentence, sentence case, no
  prefix (`git log` examples: "Harden transport finalization invariants",
  "Derive the Knowledge Root instead of remembering it").
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add `pending_candidates` to `render_operational_context`

In `operational_memory/core.py`, inside `render_operational_context`
(line 1172), after `evidence_refs` is filled and before the `return`, build:

```python
        pending = []
        for candidate in self.get_pending_candidates(target, capability):
            claims = self._claim_rows(candidate["claim_ids"])
            pending.append({
                "proposal_id": candidate["proposal_id"],
                "claims": [
                    {"id": c["id"], "family": c["family"], "epistemic": c["epistemic"],
                     "host_id": c.get("host_id"), "value": c["value"]}
                    for c in claims
                ],
            })
```

Add `"pending_candidates": pending,` to the returned dict as a sibling of
`"current"`. Check the exact shape returned by `_claim_rows` (line 802) and
adapt the key names if they differ; the output keys above are the contract.

**Verify**: `python3 -m unittest tests.test_production_memory_core tests.test_continuous_learning -v` → all pass (existing tests compare `current`, not the whole dict; if one compares the whole dict, update that assertion to include the new key).

### Step 2: Return pending state from the lookup boundary

In `integration_bridge.py`:

1. Add a field to `LookupResult`: `pending_candidates: Any = None`.
2. Capability lookup (lines 84-90): when `not any(context["current"].values())`,
   return `LookupResult(source="operational-memory", target=target,
   capability=capability, pending_candidates=context["pending_candidates"] or None)`.
   When accepted knowledge exists, pass `pending_candidates=context["pending_candidates"] or None` too.
3. Target-only lookup (lines 91-104): build `pending = {}`; for every key,
   if `rendered["pending_candidates"]` is non-empty, set
   `pending[key] = rendered["pending_candidates"]`. Include the key in the
   `context` dict as `"pending_candidates": pending`, and pass
   `pending_candidates=pending or None` on the result. A target whose
   capabilities are **all** pending-only still returns a context (status
   `found` at the CLI is fine only if `contexts` is non-empty; otherwise the
   CLI emits `not_found` with `pending_candidates`).

**Verify**: `python3 -m unittest tests.test_integration_bridge -v` → all pass.

### Step 3: Emit `pending_candidates` from the CLI

In `scripts/knowledge-lookup`, extend `visibility` after line 47:

```python
    if result.pending_candidates:
        visibility["pending_candidates"] = result.pending_candidates
```

Both the `not_found` and `found` emits already spread `**visibility`, so no
other change is needed.

**Verify**: seed a temp root with one pending proposal (see test in Step 5),
run `python3 scripts/knowledge-lookup --knowledge-root <tmp> --target example-news --capability topic-search`
→ output contains `"status": "not_found"` and a non-empty `"pending_candidates"`.

### Step 4: Make `_has_conflict` return the conflicting Claims

In `discovery_finalize.py`:

1. Change `_has_conflict` to return `list[dict[str, Any]]` (empty list means
   no conflict). Keep the name, or rename to `_conflicting_claims` and update
   the two call sites (`finalize_discovery` line ~1428 assigns
   `has_conflict = _has_conflict(...)`; line ~1437 uses `not has_conflict`;
   line ~1590 uses `elif has_conflict`). Truthiness of a list keeps those
   sites working.
2. In the intra-delta check (line ~1212, `any(len(values) > 1 ...)`) return
   `[{"source": "payload", "family": family, "host_id": host, "values": sorted(values)}]`
   for each key with more than one value.
3. In the stored-values loop (line ~1230), also keep `row["id"]` by selecting
   `id` in the SQL and storing `(claim_id, canonical_value)` pairs. Return one
   entry per conflicting stored claim:
   `{"source": "accepted" | "pending", "claim_id": ..., "family": ..., "host_id": ..., "value": <parsed>}`.
   Determine `source` by membership in `current_claim_ids` vs `pending_claim_ids`.
4. In the refusal at lines 1582-1601, when `reason_code == "CONFLICT_OR_AMBIGUITY"`,
   build the reason as:
   `"Conflicting values for the same family and host block automatic acceptance. Conflicts: " + json.dumps(conflicts[:10], ensure_ascii=False, sort_keys=True)`
   followed by `" A pending Claim is not accepted knowledge; a later run may enrich it, or it can be discarded (see knowledge-resolve)."`
   Keep the existing reason string for the other codes. Cap at 10 entries.

**Verify**: `python3 -m unittest tests.test_discovery_finalize -v` → all pass
(`test_same_transport_incompatible_outcomes_remain_conflicting` at line 996
still asserts the code; it does not assert the prose).

### Step 5: Tests

Add to `tests/test_integration_bridge.py` a new class
`PendingCandidateVisibilityTests` that seeds, through `write_transaction()`,
one target, one capability, one claim, and one proposal linked by
`writer.proposal_claim(...)` with **no** decision (pattern: the seeding in
`IntegrationBridgeRuntimeLookupTests.setUp`, lines 29-96, but omit the
`writer.decision(...)` call). Assert:

- capability lookup → `operational_context is None`, `pending_candidates`
  has one entry whose `proposal_id` and `claims[0]["id"]` match the seed;
- target-only lookup → `pending_candidates == {"<key>": [...]}`;
- the CLI (subprocess, pattern at lines 99-121) prints `"status": "not_found"`
  and `"pending_candidates"`.

Add to `tests/test_discovery_finalize.py`:

- `test_conflict_refusal_names_pending_claims`: seed a pending proposal with
  a `blocking` claim (value A) for the capability, finalize a payload with a
  `blocking` observation (value B, with the required `validation`), assert
  `reason_code == "CONFLICT_OR_AMBIGUITY"` and that `result.reason` contains
  the pending claim ID and the string `"pending"`.
- `test_no_conflict_returns_empty_list`: call the conflict function directly
  on a fresh capability and assert `== []`.

**Verify**: `python3 -m unittest discover -s tests -p 'test_*.py'` → `OK`.

### Step 6: Contract text

`SKILL.md`, step 2 result table (lines 46-53): add one row after `not_found`:

| `not_found` with `pending_candidates` | Do not mint a sibling capability ID. Read the pending Claims: a later authorized run may resubmit them with the missing material under a new `run_id` to enrich that exact Candidate, or discard them with `knowledge-resolve` (plan 002). |

`references/target-profile.md`, "Discovery run markers" section (line ~119),
add one sentence: "`knowledge-lookup` lists pending Candidates under
`pending_candidates`, beside accepted `current` knowledge, never merged into
it; a `CONFLICT_OR_AMBIGUITY` refusal names the accepted or pending Claims
that block the write."

**Verify**: `python3 -m unittest tests.test_skill_adapter_parity tests.test_public_vocabulary tests.test_marker_parity -v` → all pass.

## Test plan

- New tests listed in Step 5, in `tests/test_integration_bridge.py` and
  `tests/test_discovery_finalize.py`.
- Pattern: `tests/test_integration_bridge.py` (seed via `write_transaction`,
  assert on JSON via subprocess) and `tests/test_discovery_finalize.py`
  (`self.finalize(...)` helper).
- Verification: full suite passes with at least 4 new tests.

## Done criteria

- [ ] `python3 -m unittest discover -s tests -p 'test_*.py'` exits 0
- [ ] `grep -n "pending_candidates" scripts/knowledge-lookup integration_bridge.py operational_memory/core.py SKILL.md` returns a hit in each file
- [ ] A capability with only pending Claims prints `"pending_candidates"` in the CLI output
- [ ] A `CONFLICT_OR_AMBIGUITY` refusal reason contains at least one `clm:` ID
- [ ] `git diff --check` prints nothing
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" does not match the excerpts.
- `_claim_rows` (core.py:802) does not return `id`, `family`, `epistemic`,
  `value`; report its real shape instead of inventing one.
- An existing test asserts equality on the whole dict returned by
  `render_operational_context` and cannot be updated without changing a
  documented contract.
- The fix appears to require changing which values `_has_conflict` treats as
  conflicting.

## Maintenance notes

- Plan 002 (`knowledge-resolve --reject-pending`) consumes the `proposal_id`
  this plan exposes; keep that key name stable.
- Plan 007 (`knowledge-lookup --list`) should reuse the same
  `pending_candidates` shape per capability.
- Reviewers should confirm pending data never appears inside `current` and
  that `markdown_projection` is unchanged (it stays accepted-only).
- Deferred: changing the conflict key so that `blocking` claims validated
  under different transports are not conflicts. That is a design decision;
  record it as a follow-up if the maintainer wants it.
