# Plan 007: Add `knowledge-lookup --list`, a memory-wide index of targets, hosts, and capabilities

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 929c0b1..HEAD -- operational_memory/core.py integration_bridge.py scripts/knowledge-lookup SKILL.md references/target-profile.md docs/installation.md tests/test_integration_bridge.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (pairs well with 001 and 005)
- **Category**: direction
- **Planned at**: commit `929c0b1`, 2026-09-02

## Why this matters

`SKILL.md` step 2 tells the executor to inspect existing capabilities before
minting an ID, but `knowledge-lookup` requires `--target`, so the guard only
works when the target ID guess is already right. Real memory now holds
`npr` and `npr-org`; `politico-com`, `politico-eu`, `politico-europe`; four
`article-*-read/access` variants and five `rss-feed-*` variants. There is no
way to see what the store already knows without guessing into it. A
read-only listing of exact IDs is the cheapest surface that respects the
"no fuzzy matching" rule (`SKILL.md:34-38`) while making it followable.

## Current state

`scripts/knowledge-lookup:26-33`
```python
    parser.add_argument("--knowledge-root")
    parser.add_argument("--target", required=True)
    parser.add_argument("--capability")
    parser.add_argument("--operational-memory-db", help="diagnostic DB override ...")
    parser.add_argument("--use-operational-memory", action="store_true", help="deprecated ...")
    parser.add_argument("--use-legacy", action="store_true", help="diagnostic-only ...")
```

`operational_memory/core.py:646-655`
```python
    def list_capability_keys(self, target: str) -> list[str]:
        tid = self.resolve_target(target)
        return [
            row[0]
            for row in self._conn.execute(
                "SELECT capability_key FROM capabilities WHERE target_id=? ORDER BY capability_key",
                (tid,),
            )
        ]
```

There is no `list_targets`. Tables (`operational_memory/schema.sql`):
`targets(id, name, canonical_origin, payload_json)`,
`hosts(id, target_id, hostname, payload_json)`,
`capabilities(id, target_id, capability_key, name, payload_json)`.
`has_verified_operational_lifecycle(target, capability)` at `core.py:1230`.
`get_pending_candidates(target, capability)` at `core.py:1130`.

`integration_bridge.py:44-60` opens the DB with
`SQLiteOperationalMemory(self.memory_db, create=False)` after checking
`read_cutover_active`; the `--target` path is the only public path.

`docs/installation.md` "Runtime commands (advanced)" table describes
`knowledge-lookup` as "Read accepted knowledge for one target and optional
capability."

Conventions: JSON line output via `emit(status, **fields)`; statuses are
lower_snake for lookup (`found`, `not_found`, `unresolved`, `bridge_error`);
tests seed via `write_transaction()` and call the CLI by subprocess
(`tests/test_integration_bridge.py:99-121`).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Full suite | `python3 -m unittest discover -s tests -p 'test_*.py'` | `OK` |
| Bridge | `python3 -m unittest tests.test_integration_bridge -v` | pass |
| Smoke | `python3 scripts/knowledge-lookup --knowledge-root <tmp> --list` | JSON line, `"status": "listed"` |
| Whitespace | `git diff --check` | no output |

## Scope

**In scope**:
- `operational_memory/core.py` (new `list_targets`)
- `integration_bridge.py` (new `list_index` method)
- `scripts/knowledge-lookup` (`--list` flag; `--target` no longer `required=True` but required unless `--list`)
- `SKILL.md` (step 2), `references/target-profile.md` (Knowledge Lookup section), `docs/installation.md` (table row)
- `tests/test_integration_bridge.py`

**Out of scope**:
- Any fuzzy or prefix matching, suggestions, or auto-merge. The index is exact IDs only.
- `discovery-begin` collision warnings (a possible follow-up).
- Claim values in the listing (keep it an index, not a dump).

## Git workflow

- Branch: `advisor/007-lookup-list`
- One imperative sentence per commit, sentence case, no prefix.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: `list_targets` in core

Add after `list_capability_keys`:

```python
    def list_targets(self) -> list[dict[str, Any]]:
        """Exact index of every target with its hosts and capability keys. Read-only."""
        result: list[dict[str, Any]] = []
        for row in self._conn.execute("SELECT id, name FROM targets ORDER BY id"):
            tid = row["id"]
            hosts = [h[0] for h in self._conn.execute(
                "SELECT hostname FROM hosts WHERE target_id=? ORDER BY hostname", (tid,))]
            capabilities = []
            for cap in self._conn.execute(
                "SELECT capability_key FROM capabilities WHERE target_id=? ORDER BY capability_key", (tid,)):
                key = cap[0]
                capabilities.append({
                    "capability": key,
                    "lifecycle": "OPERATIONAL" if self.has_verified_operational_lifecycle(tid, key) else None,
                    "accepted": bool(self.get_current(tid, key)["accepted_claim_ids"]),
                    "pending_proposals": len(self.get_pending_candidates(tid, key)),
                })
            result.append({
                "target_id": tid,
                "target": tid.removeprefix("tgt:"),
                "name": row["name"],
                "hosts": hosts,
                "capabilities": capabilities,
            })
        return result
```

Confirm `get_current` and `has_verified_operational_lifecycle` accept a
`tgt:`-prefixed ID (`resolve_target` at line 611 handles the prefix).

**Verify**: `python3 -m unittest tests.test_production_memory_core -v` → pass.

### Step 2: Bridge method

In `integration_bridge.py`, add `KnowledgeLookupBoundary.list_index(self) -> list[dict]`
that performs the same `read_cutover_active` check as `lookup`, raises
`BridgeError` when the cutover is inactive (the legacy path has no index),
opens the memory, and returns `memory.list_targets()`. Wrap
`sqlite3.DatabaseError`, `json.JSONDecodeError`, `OperationalMemoryError`
into `BridgeError` exactly as `lookup` does.

**Verify**: `python3 -c "import sys; sys.path.insert(0,'.'); import integration_bridge as b; print(b.KnowledgeLookupBoundary.list_index)"` → prints the function.

### Step 3: CLI flag

In `scripts/knowledge-lookup`: `parser.add_argument("--list", action="store_true", help="index every target with its hosts and capability keys; no --target")`;
change `--target` to `required=False` and after parsing: if not `args.list`
and not `args.target`, `parser.error("--target is required unless --list is given")`.
When `--list`: resolve the root (emit `unresolved` if `None`), call
`boundary.list_index()`, and `emit("listed", targets=<list>, count=len(<list>))`;
map `BridgeError`/`MemoryError` to `bridge_error` exactly as the existing
path does. `--list` with `--target` or `--capability` is a `parser.error`.

**Verify**: `python3 scripts/knowledge-lookup --help` shows `--list`; on a temp root with two seeded targets the output has `"count": 2`.

### Step 4: Contract text

`SKILL.md` step 2 (line 30): change "Before minting a capability ID, inspect
accepted capabilities with `... --target <target-id>`" to "Before minting a
target or capability ID, run `<python> <skill>/scripts/knowledge-lookup --list`
once per task and read the exact IDs it returns; then inspect the chosen
target with `... --target <target-id>`. The index is exact IDs only: reuse an
ID only under the equivalence rule below, never by resemblance."
`references/target-profile.md` "Knowledge Lookup" section (line 89): add the
`--list` command line and one sentence. `docs/installation.md` table row:
"Read accepted knowledge for one target and optional capability, or index
every target with `--list`."

**Verify**: `python3 -m unittest tests.test_skill_adapter_parity tests.test_marker_parity tests.test_public_vocabulary -v` → pass.

### Step 5: Tests

`tests/test_integration_bridge.py`, new class `ListIndexTests`: seed two
targets (one with a host row and one capability with an accepted decision;
one with no host and a pending-only capability), then assert
`list_index()` returns both in ID order with `hosts`, `capabilities[].accepted`,
`capabilities[].pending_proposals`, `capabilities[].lifecycle` as seeded;
CLI subprocess with `--list` → `status == "listed"`, `count == 2`;
`--list --target x` → non-zero exit (argparse error, exit 2).

**Verify**: `python3 -m unittest tests.test_integration_bridge -v` → pass.

## Test plan

- Three new tests (bridge, CLI, arg conflict).
- Verification: full suite `OK`.

## Done criteria

- [ ] `python3 -m unittest discover -s tests -p 'test_*.py'` exits 0
- [ ] `python3 scripts/knowledge-lookup --knowledge-root <tmp> --list` prints `"status": "listed"`
- [ ] `grep -n "\-\-list" SKILL.md docs/installation.md references/target-profile.md` return hits
- [ ] `git diff --check` prints nothing
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `get_current` or `has_verified_operational_lifecycle` refuse a `tgt:`
  prefixed ID; report and do not strip the prefix ad hoc.
- A test in `tests/test_agent_host_integration.py` or
  `tests/test_public_runtime_boundary.py` parses `knowledge-lookup`'s
  argparse and breaks on `--target` becoming optional.
- Listing a 35-target memory takes more than 2 seconds (then note it; do not
  optimize in this plan).

## Maintenance notes

- Keep `--list` free of claim values; it is an identity index, so its output
  stays small and never leaks operating detail.
- Plan 001's `pending_candidates` and this plan's `pending_proposals` count
  are two views of `get_pending_candidates`; keep them consistent.
- A future `discovery-begin` warning ("targets sharing a token prefix
  exist") should read this same index.
