# Plan 004: Name the accepted set in every closed-set refusal and attach a machine-readable code

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 929c0b1..HEAD -- discovery_finalize.py scripts/discovery-finalize tests/test_discovery_finalize.py tests/test_discovery_payload_examples.py SKILL.md references/target-profile.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `929c0b1`, 2026-09-02

## Why this matters

The payload contract is the product's public API and an LLM agent is its
only client. Of 53 `raise DiscoveryFinalizationError(...)` sites, about 14
name the offending value or the accepted set; the rest say only that a rule
was broken. The maintainer's friction log from real runs records 5+ retries
per capability on formatting alone, driven by exactly these messages
("observation family is not reusable operational knowledge" lists no
family; "must be a symbolic value" gives no grammar). The CLI also emits
`reason_code: null` for every payload refusal, so `RETRYABLE_REASON_CODES`
cannot classify the failures that actually happen. After this plan, every
closed-set refusal names the rejected value and the allowed values, and
every payload refusal carries a `reason_code`.

## Current state

`discovery_finalize.py:34-35`
```python
class DiscoveryFinalizationError(ValueError):
    """Discovery output is not reusable operational knowledge."""
```

`scripts/discovery-finalize:97-107`
```python
    except (DiscoveryFinalizationError, DiscoveryRunError) as exc:
        # Payload validation refusals already carry a specific, non-internal
        # reason. ...
        print(json.dumps({
            "status": "NOT_SAVED",
            "run_state": "OPEN",
            "reason": str(exc),
        }, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
```

Closed-set constants already present in `discovery_finalize.py`:

```python
RETRYABLE_REASON_CODES = frozenset({"TRANSPORT_POLICY_UNPROVEN", "FAILURE_UNCLASSIFIED"})   # line 46
OPERATIONAL_FAMILIES = { ... 10 families ... }                                            # line 49
_TRANSPORTS = {DIRECT_READ, LIGHTPANDA, CHROME}                                            # line 75
_SYMBOL = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]*$")                                        # line 73
_EVIDENCE_KIND = re.compile(r"^[a-z][a-z0-9-]*$")                                          # line 74
_FAMILY_FIELDS = { family: {allowed keys} }                                                 # line 306
```
and `EPISTEMIC_CLASSES = {"OBSERVED", "INFERRED", "UNKNOWN"}` in
`operational_memory/core.py:27`.

Opaque sites to fix (verified at commit `929c0b1`):

| Line | Current message | Must add |
|---|---|---|
| 218 | `{field} is not a supported transport` | rejected value + `DIRECT_READ, LIGHTPANDA, CHROME` |
| 448 | `observation family is not reusable operational knowledge` | rejected family + sorted `OPERATIONAL_FAMILIES` |
| 455 | `observation epistemic class is invalid` | rejected value + `OBSERVED, INFERRED, UNKNOWN` |
| 683 | `evidence.kind must be a lowercase symbolic value` | rejected value + pattern `[a-z][a-z0-9-]*` + example `direct-read-validation` |
| 730 | `transport_trace availability contains an unsupported status` | rejected value + `AVAILABLE, UNAVAILABLE, PLATFORM_UNSUPPORTED` |
| 737-770 | attempt shape/outcome refusals | rejected value + allowed `FAILED, INSUFFICIENT, FUNCTIONAL` where applicable |
| 192 (`_exact_keys` unknown fields) | `{field} contains unsupported fields: X` | append `Accepted fields: <required ∪ optional>` |
| 188 (`_exact_keys` missing) | `{field} is missing required fields: X` | append `Required: ...; optional: ...` |
| 177 | `{field} contains task-specific or raw content` | which rule fired: `over 500 characters` or `matches raw-content pattern <pattern name>` |

Sites already good (keep as the style to copy): 207-210 (`_symbol`), 231-235
(`_schema_map`), 394-397 (`_normalize_validation` unsupported keys),
1048-1057 (`_host_plan`).

`_exact_keys` at lines 180-196 is the shared helper; fixing it fixes every
wrapper/observation/evidence/provenance/trace/context "unsupported fields"
message at once.

Existing tests assert on `reason_code` for the non-exception path
(`tests/test_discovery_finalize.py:1004`) and on message *fragments* in only
7 `assertRaisesRegex` calls repo-wide, none of which cover the sites above,
so message changes are safe.

`--validate` path, `scripts/discovery-finalize:76-83`, prints
`would_reason_code` from `result.reason_code`; a payload refusal never reaches
it because the exception is raised earlier — so `--validate` today reports
`NOT_SAVED` with no code for a shape error.

Conventions: codes UPPER_SNAKE English; keep `reason` free text; JSON output
`ensure_ascii=False, sort_keys=True`; tests via `self.finalize(...)` and
`self.assertRaises(DiscoveryFinalizationError)` in
`tests/test_discovery_finalize.py`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Full suite | `python3 -m unittest discover -s tests -p 'test_*.py'` | `OK` |
| Finalize tests | `python3 -m unittest tests.test_discovery_finalize -v` | pass |
| Vocabulary gate | `python3 -m unittest tests.test_public_vocabulary -v` | pass |
| Whitespace | `git diff --check` | no output |

## Scope

**In scope**:
- `discovery_finalize.py`
- `scripts/discovery-finalize`
- `tests/test_discovery_finalize.py`, `tests/test_discovery_payload_examples.py`
- `SKILL.md` (one sentence in step 7), `references/target-profile.md` (code list)

**Out of scope**:
- Aggregating multiple errors per run (explicitly deferred in
  `docs/discovery-finalization-redesign-plan.md:385`); keep raise-on-first.
- Changing any acceptance rule. Messages and codes only.
- `discovery_runs.py` errors (`DiscoveryRunError`) — separate class; may get
  a fixed code `RUN_MARKER` in the CLI catch block, nothing more.

## Git workflow

- Branch: `advisor/004-refusal-codes`
- One imperative sentence per commit, sentence case, no prefix.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Give `DiscoveryFinalizationError` a `code`

```python
class DiscoveryFinalizationError(ValueError):
    """Discovery output is not reusable operational knowledge."""

    def __init__(self, message: str, *, code: str = "PAYLOAD_INVALID") -> None:
        super().__init__(message)
        self.code = code
```

Define the code vocabulary as module constants near line 46:
`PAYLOAD_SHAPE` (wrong types, missing/unsupported keys), `PAYLOAD_VALUE`
(closed-set or pattern violation), `TASK_DATA_REJECTED` (raw/task content),
`HOST_SCOPE` (host/evidence association), `EVIDENCE_LINKAGE`,
`PROVENANCE`, `TRANSPORT_TRACE`, `TARGET_REFERENCE`. Every raise site gets
one of these; a site you cannot classify keeps the default
`PAYLOAD_INVALID`. Add a test that walks the module's AST and asserts every
`raise DiscoveryFinalizationError(...)` call passes `code=` (allow the
default only through an explicit allowlist that must be empty by the end).

**Verify**: `python3 -m unittest tests.test_discovery_finalize -v` → pass.

### Step 2: Rewrite the opaque messages

Apply the table in "Current state". Template:

```python
raise DiscoveryFinalizationError(
    f"observation.family {family!r} is not a reusable operational family. "
    f"Accepted families: {', '.join(sorted(OPERATIONAL_FAMILIES))}",
    code=PAYLOAD_VALUE,
)
```

For `_exact_keys`, append `Accepted fields: a, b, c` (sorted union of
`required | optional`) to the unsupported-fields message and
`Required: ...; optional: ...` to the missing-fields message. For
`_reject_unsafe_content` (line 162-178) name the rule that fired. Keep every
message on one line of prose (no newlines) so the JSON stays readable.

**Verify**: `python3 -m unittest tests.test_discovery_finalize -v` → pass.

### Step 3: Emit the code from the CLI

`scripts/discovery-finalize:97-107`: add
`"reason_code": getattr(exc, "code", "RUN_MARKER" if isinstance(exc, DiscoveryRunError) else "PAYLOAD_INVALID")`
to the stderr JSON. Keep exit code 2 and `run_state: "OPEN"`.

**Verify**: seed a temp root (pattern `tests/test_discovery_runs.py:20-60`), begin a run, finalize `{"target": ..., "capability": ..., "observations": [{"family": "nope", "value": {"x": "y"}}], ...}` → stderr JSON has `"reason_code": "PAYLOAD_VALUE"` and the reason lists the ten families.

### Step 4: Tests

`tests/test_discovery_finalize.py`, new class `RefusalMessageTests`, one test
per row of the table: build the offending payload with `self.payload(...)`,
`with self.assertRaises(DiscoveryFinalizationError) as ctx: self.finalize(...)`,
then assert `ctx.exception.code == <code>` and that `str(ctx.exception)`
contains both the rejected value and at least two members of the accepted
set. Add the AST test from Step 1 to the same file.

`tests/test_discovery_payload_examples.py`: add
`test_a_malformed_example_reports_a_reason_code` — take example 1, set
`family` to `"nope"`, run the CLI, assert exit 2 and `reason_code` in stderr.

**Verify**: `python3 -m unittest tests.test_discovery_finalize tests.test_discovery_payload_examples -v` → pass.

### Step 5: Contract text

`SKILL.md` step 7 (after line 109): "A payload refusal is printed to stderr
as `{"status":"NOT_SAVED","run_state":"OPEN","reason":...,"reason_code":...}`;
its `reason` names the rejected value and the accepted set, so correct the
payload from the message without rereading the reference."
`references/target-profile.md` "Knowledge Boundary" (~line 135): list the
eight refusal codes with one line each.

**Verify**: `python3 -m unittest tests.test_skill_adapter_parity tests.test_marker_parity tests.test_public_vocabulary -v` → pass.

## Test plan

- Nine message tests + one AST guard + one CLI test (Step 4).
- Pattern: `tests/test_discovery_finalize.py` helpers.
- Verification: full suite `OK`, at least 11 new tests.

## Done criteria

- [ ] `python3 -m unittest discover -s tests -p 'test_*.py'` exits 0
- [ ] `grep -c "code=" discovery_finalize.py` ≥ 50
- [ ] `grep -n "Accepted families" discovery_finalize.py` returns a hit
- [ ] The CLI stderr JSON for a bad family contains `reason_code`
- [ ] `git diff --check` prints nothing
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Any existing test asserts the exact old text of a message you must change
  and the new text cannot satisfy it (report which; do not weaken the test
  silently).
- `tests/test_public_vocabulary.py` flags a new identifier (it scans for
  retired Portuguese names; a hit means you copied one).
- Implementing a code requires changing which payloads are accepted.

## Maintenance notes

- Future raise sites must pass `code=`; the AST test enforces it.
- The `reason_code` field on stderr is now part of the CLI contract; document
  changes in `CHANGELOG.md`.
- Plan 001 changes the `CONFLICT_OR_AMBIGUITY` reason text; the two plans
  touch different lines and merge cleanly in either order.
