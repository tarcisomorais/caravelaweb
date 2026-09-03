# Plan 002: Add `knowledge-resolve --reject-pending` so a stuck pending Candidate can be discarded

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 929c0b1..HEAD -- om_native_writes.py operational_memory/core.py scripts/ tests/test_public_runtime_boundary.py tests/test_om_native_writes.py docs/architecture.md docs/installation.md SKILL.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/001-surface-pending-candidates-and-name-conflicts.md (for the visible `proposal_id`; the code here does not import from it)
- **Category**: bug
- **Planned at**: commit `929c0b1`, 2026-09-02

## Why this matters

A pending Candidate (a Proposal whose Claims never received a Decision) is
never accepted, never expires, and blocks every later write for the same
capability whose values differ (`_has_conflict` counts pending values). The
schema already admits a `REJECT` decision and the projection already treats
`REJECT` as resolving a Claim, but no CLI can write one. Real memory today
holds 8 pending proposals; two capabilities are permanently unwritable. This
plan adds one narrow, authority-gated command that records a `REJECT`
Decision for one pending Proposal. It never asserts positive knowledge, so it
does not weaken the rule that only runtime proof earns `OPERATIONAL`.

## Current state

Relevant files:

- `operational_memory/core.py:23-26` — decision action sets.
- `operational_memory/core.py:390-436` — `_Writer.decision` validates and
  inserts a Decision; `REJECT` is the only action allowed with no `claim_ids`.
- `operational_memory/core.py:822-853` — `_pending_proposal_ids`: a Proposal
  is pending until every one of its Claims has a Decision in
  `DECISION_ACTIONS` linked through `decision_claims`.
- `om_native_writes.py:738-812` — `promote_candidate`: the existing pattern
  for an authority-gated, token-checked Decision write.
- `scripts/discovery-begin` — the smallest CLI in the repo; use it as the
  template for the new script.
- `tests/test_public_runtime_boundary.py:25-38, 82-88` — locks the runtime
  import closure and the list of entry points.

Excerpts as of commit `929c0b1`:

`operational_memory/core.py:23-26`
```python
ACCEPT_ACTIONS = {"ACCEPT", "ACCEPT_SUPERSEDE", "RETROACTIVE_CORRECTION"}
CLOSE_ACTIONS = {"DEGRADE", "SUPERSEDE"}
RESOLUTION_ACTIONS = CLOSE_ACTIONS | {"RETROACTIVE_CORRECTION"}
DECISION_ACTIONS = ACCEPT_ACTIONS | CLOSE_ACTIONS | {"REJECT"}
```

`operational_memory/core.py:412-415`
```python
        claim_ids = list(record.get("claim_ids", []))
        if action != "REJECT" and not claim_ids:
            raise RecordValidationError("non-REJECT Decision requires at least one claim_id")
```

`operational_memory/core.py:838-853` (inside `_pending_proposal_ids`)
```python
            resolved: set[str] = set()
            for claim_id in claim_ids:
                actions = [
                    r[0]
                    for r in self._conn.execute(
                        """SELECT d.action FROM decisions d
                           JOIN decision_claims dc ON dc.decision_id=d.id
                           WHERE dc.claim_id=? AND d.recorded_at<=?""",
                        (claim_id, knowledge_time),
                    )
                ]
                if any(a in DECISION_ACTIONS for a in actions):
                    resolved.add(claim_id)
            if len(resolved) < len(claim_ids):
                pending.append(proposal["id"])
```

Important consequence: a `REJECT` Decision resolves a Proposal **only if its
`claim_ids` list every Claim of that Proposal**, because resolution is
computed through `decision_claims`. A `REJECT` with empty `claim_ids` is
legal for the writer but leaves the Proposal pending.

`om_native_writes.py:738-812` (`promote_candidate`, abridged)
```python
def promote_candidate(memory, *, target, capability, proposal_id, reviewed_token,
                      decision_id, recorded_at, effective_at, _writer=None) -> Promotion:
    _require_boundary(memory)
    target_id, capability_id = _identity(memory, target, capability)
    validate_timestamp(recorded_at, field="promotion.recorded_at")
    validate_timestamp(effective_at, field="promotion.effective_at")
    ...
    if review_token(memory, target=target, capability=capability) != reviewed_token:
        raise OMStaleBaseError("reviewed Operational Memory projection is stale")
    metadata = _operation_metadata(operation="PROMOTION", ...)
    with _write_scope(memory, _writer) as writer:
        if review_token(...) != reviewed_token:
            raise OMStaleBaseError(...)
        proposal = memory.get_record(proposal_id)          # KeyError -> OMProposalError
        ... scope checks ...
        claim_ids = memory.proposal_claim_ids(proposal_id)
        ... ownership checks ...
        pending_ids = {item["proposal_id"] for item in memory.get_pending_candidates(target, capability)}
        if proposal_id not in pending_ids:
            raise OMProposalError("Proposal is already resolved")
        writer.decision({
            "id": decision_id, "target_id": target_id, "capability_id": capability_id,
            "action": "ACCEPT", "proposal_id": proposal_id, "claim_ids": list(claim_ids),
            "effective_at": effective_at, "recorded_at": recorded_at,
            "validity": {"valid_from": effective_at, "valid_to": None},
            "write_metadata": metadata,
        })
    return Promotion(decision_id, claim_ids, metadata)
```

`scripts/discovery-begin` (whole file is 40 lines) — resolves the root with
`resolve_knowledge_root(args.knowledge_root)`, prints one JSON line with
`ensure_ascii=False, sort_keys=True`, exits 2 on refusal with a JSON line on
stderr.

Write authority gate used by the finalizer, `discovery_finalize.py:1289-1293`:
```python
    assert_om_native_write_authority(memory)
```
(`om_native_writes.py:97`). It requires `memory.knowledge_root` to be set;
`SQLiteOperationalMemory(db, create=False, knowledge_root=root)` as in
`scripts/discovery-finalize:63`.

Conventions:

- Every CLI: `SKILL_ROOT = Path(__file__).resolve().parents[1]`,
  `sys.path.insert(0, ...)`, `configure_utf8_stdio()`, argparse, JSON line
  output, exit 0/2. Copy `scripts/discovery-begin`.
- Statuses are UPPER_SNAKE English. Do not reuse `SAVED`/`NOT_SAVED` here.
- `docs/architecture.md:8-32` lists the runtime CLIs and import closure and
  must list the new script (see also plan 008, which fixes the count).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Full suite | `python3 -m unittest discover -s tests -p 'test_*.py'` | `OK` |
| Boundary | `python3 -m unittest tests.test_public_runtime_boundary -v` | pass |
| Writes | `python3 -m unittest tests.test_om_native_writes -v` | pass |
| Whitespace | `git diff --check` | no output |

## Scope

**In scope**:
- `om_native_writes.py` (new `reject_candidate` + `Rejection` dataclass)
- `scripts/knowledge-resolve` (new, executable, no extension, `#!/usr/bin/env python3`)
- `tests/test_public_runtime_boundary.py` (add the entry point to the list at lines 82-88)
- `tests/test_om_native_writes.py`, new `tests/test_knowledge_resolve.py`
- `docs/architecture.md`, `docs/installation.md` (runtime command tables)
- `SKILL.md` (public runtime sentence at lines 143-144, and the step 2 row added by plan 001)
- `CHANGELOG.md` (Unreleased section; create it if absent)

**Out of scope**:
- Any positive decision (`ACCEPT`, `DEGRADE`, `SUPERSEDE`) — not this command.
- Deleting Claims or Proposals rows. A rejection is a Decision; history stays.
- `discovery_finalize.py` — it needs no change; `_has_conflict` already reads
  pending state through `get_pending_candidates`.
- `.gitattributes` — new script must be LF; the existing rule already forces
  it for published files, do not edit the rule.

## Git workflow

- Branch: `advisor/002-knowledge-resolve`
- One imperative sentence per commit, sentence case, no prefix.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add `reject_candidate` to `om_native_writes.py`

Below `promote_candidate`, add:

```python
@dataclass(frozen=True)
class Rejection:
    decision_id: str
    claim_ids: tuple[str, ...]
    metadata: dict[str, Any]


def reject_candidate(
    memory: SQLiteOperationalMemory,
    *,
    target: str,
    capability: str,
    proposal_id: str,
    reason: str,
    reviewed_token: str,
    decision_id: str,
    recorded_at: str,
    effective_at: str,
    _writer: Any | None = None,
) -> Rejection:
    """Resolve exactly one pending Proposal with a REJECT Decision.

    A rejection asserts nothing positive: the Claims stay in history, are
    never accepted, and stop counting as pending. Only a pending Proposal
    of this target/capability may be rejected.
    """
```

Body: copy `promote_candidate` line for line, with these differences:
`operation="REJECTION"` in `_operation_metadata`; `reason` validated as a
non-empty string of at most 500 characters (raise `OMProposalError`
otherwise) and stored in the decision record as `"reason": reason`;
`"action": "REJECT"`; `"validity": {"valid_from": None, "valid_to": None}`
(a rejection has no accepted validity window; confirm `_Writer.decision`
accepts `None` for both — it calls `validate_timestamp(..., required=False)`
so it does). Keep the double `review_token` check. `claim_ids` MUST be the
full `memory.proposal_claim_ids(proposal_id)` so the Proposal resolves (see
"Important consequence" above). Add `"Rejection"`, `"reject_candidate"` to
`__all__`. Check whether `_operation_metadata` validates `operation` against
a fixed set; if so, add `"REJECTION"` to it.

**Verify**: `python3 -c "import om_native_writes as m; print(m.reject_candidate)"` → prints the function.

### Step 2: Prove resolution in `tests/test_om_native_writes.py`

Add `test_reject_candidate_resolves_pending_proposal_without_accepting`:
capture a candidate through `capture_candidate` (pattern:
`test_valid_promotion_creates_decision_for_exact_proposal_claims`, line 251),
call `reject_candidate` with `review_token(memory, target=..., capability=...)`,
then assert:

- `memory.get_pending_candidates(target, capability) == []`;
- `memory.get_current(target, capability)["accepted_claim_ids"]` does not
  contain any of the proposal's claims;
- the decision record (`memory.get_record(decision_id)`) has
  `action == "REJECT"`, `reason == <given>`, and `claim_ids` equal to the
  proposal's claims;
- a second `reject_candidate` on the same Proposal raises `OMProposalError`
  ("Proposal is already resolved");
- a stale `reviewed_token` raises `OMStaleBaseError` and writes nothing
  (pattern: `test_stale_token_blocks_promotion_without_partial_write`, line 274).

**Verify**: `python3 -m unittest tests.test_om_native_writes -v` → pass.

### Step 3: Create `scripts/knowledge-resolve`

Arguments: `--knowledge-root` (optional), `--target` (required),
`--capability` (required), `--reject-pending <proposal_id>` (required for
now; the flag name leaves room for other resolutions later), `--reason`
(required, non-empty), `--json` not needed (always JSON, like `discovery-begin`).

Flow:

```python
root = resolve_knowledge_root(args.knowledge_root)
if root is None: emit stderr {"status": "NOT_RESOLVED", "reason": "no usable CaravelaWeb knowledge root could be resolved"}; return 2
db = root / ".caravelaweb" / "operational_memory.db"
with SQLiteOperationalMemory(db, create=False, knowledge_root=root) as memory:
    target = _resolve_target_argument(memory, args.target)      # from discovery_finalize (already public in that module and used by scripts/discovery-finalize)
    capability = normalize_capability_id(args.capability)      # operational_memory.core
    assert_om_native_write_authority(memory)                    # om_native_writes
    token = review_token(memory, target=target, capability=capability)
    now = <UTC now, "%Y-%m-%dT%H:%M:%SZ">
    result = reject_candidate(memory, target=target, capability=capability,
        proposal_id=args.reject_pending, reason=args.reason, reviewed_token=token,
        decision_id=f"dec:{target}:{capability}:reject-{<sha256 of proposal_id + now, first 20 hex>}",
        recorded_at=now, effective_at=now)
print JSON {"status": "REJECTED", "target": target, "capability": capability,
            "proposal_id": args.reject_pending, "decision_id": result.decision_id,
            "claim_ids": list(result.claim_ids)}
```

Catch `OMProposalError`, `OMStaleBaseError`, `OMNativeWriteError`,
`DiscoveryFinalizationError`, `RecordValidationError`, `KeyError`,
`MemoryError` (from `operational_memory`), `OSError`: print
`{"status": "NOT_REJECTED", "reason": str(exc)}` to stderr, return 2. Do not
print tracebacks. `chmod +x scripts/knowledge-resolve` and check the first
line is `#!/usr/bin/env python3`.

**Verify**: `python3 scripts/knowledge-resolve --help` → usage text, exit 0.

### Step 4: Register the entry point in the boundary test

`tests/test_public_runtime_boundary.py:82-88`: add `"knowledge-resolve"` to
the tuple of entry points. The import closure must stay equal to
`EXPECTED_RUNTIME_CLOSURE`; the new script imports only modules already in
that set, so no set change is expected.

**Verify**: `python3 -m unittest tests.test_public_runtime_boundary -v` → pass. If it reports `entered=[...]`, you imported something outside the closure: STOP.

### Step 5: CLI test `tests/test_knowledge_resolve.py`

Model on `tests/test_discovery_runs.py:20-70` (temp root with authority
marker, `run_cli` helper via `subprocess.run([sys.executable, script,
"--knowledge-root", root, ...])`). Cases:

1. Seed a pending proposal by running the real `discovery-begin` +
   `discovery-finalize` twice with conflicting `blocking` values so the
   second returns `CONFLICT_OR_AMBIGUITY` — or, simpler and deterministic,
   seed through `SQLiteOperationalMemory.write_transaction()` exactly as
   `tests/test_integration_bridge.py:29-96` does but without a decision.
   Run `knowledge-resolve --target ... --capability ... --reject-pending <prop> --reason "stale"`
   → exit 0, stdout JSON `status == "REJECTED"`.
2. Run it again → exit 2, stderr JSON `status == "NOT_REJECTED"`.
3. Unknown proposal id → exit 2.
4. Missing write authority marker (delete `.caravelaweb/write-authority.json`) → exit 2, no decision row written
   (`SELECT count(*) FROM decisions` unchanged).
5. After case 1, `knowledge-lookup --target ... --capability ...` no longer
   lists that proposal under `pending_candidates` (this assertion depends on
   plan 001; if plan 001 is not merged, assert instead through
   `memory.get_pending_candidates(...) == []`).

**Verify**: `python3 -m unittest tests.test_knowledge_resolve -v` → pass.

### Step 6: Documentation

- `SKILL.md:143-144`: the public runtime sentence gains `knowledge-resolve`.
  Add one sentence after the step 2 table row from plan 001 (or, if plan 001
  is absent, at the end of step 2): "`<python> <skill>/scripts/knowledge-resolve --target <target-id> --capability <capability> --reject-pending <proposal_id> --reason <text>` records a `REJECT` Decision for one pending Candidate. It asserts nothing positive and needs caller authorization like any other local write."
- `docs/architecture.md`: add `scripts/knowledge-resolve` to the entry-point
  list (plan 008 fixes the count wording; if plan 008 already landed, just add
  the bullet and bump the number).
- `docs/installation.md` "Runtime commands (advanced)" table: add a row.
- `CHANGELOG.md`: under a new `## Unreleased` heading, one bullet.

**Verify**: `python3 -m unittest tests.test_skill_adapter_parity tests.test_public_vocabulary tests.test_marker_parity -v` → pass.

## Test plan

- `tests/test_om_native_writes.py`: one new test (Step 2) covering resolve,
  non-acceptance, double-reject refusal, stale token.
- `tests/test_knowledge_resolve.py`: five CLI cases (Step 5).
- Verification: full suite `OK` with at least 6 new tests.

## Done criteria

- [ ] `python3 -m unittest discover -s tests -p 'test_*.py'` exits 0
- [ ] `test -x scripts/knowledge-resolve` succeeds and `head -1 scripts/knowledge-resolve` is `#!/usr/bin/env python3`
- [ ] `grep -n '"REJECT"' om_native_writes.py` shows the new decision write
- [ ] `grep -n "knowledge-resolve" SKILL.md docs/architecture.md docs/installation.md tests/test_public_runtime_boundary.py` returns a hit in each
- [ ] `git diff --check` prints nothing
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `_Writer.decision` rejects `validity` with both fields `None` (then report
  the error text; do not fabricate a validity window for a rejection).
- `_operation_metadata` refuses `operation="REJECTION"` and the fix would
  require changing token semantics in `_token_payload`.
- The boundary test reports a module entering the closure.
- `_pending_proposal_ids` does not resolve the Proposal after a REJECT that
  lists all its Claims (this would mean the excerpt above is stale).

## Maintenance notes

- This is the first negative Decision writer. If a `DEGRADE`/`RETIRE`
  command is added later (direction finding DIRECTION-04), reuse this
  function's shape and the `REJECTION` metadata pattern.
- A rejected Claim still exists in `claims`; `render_markdown` and
  `get_history` may show it as historical. That is correct and expected.
- Reviewers should check that no path in this command can write an `ACCEPT`.
