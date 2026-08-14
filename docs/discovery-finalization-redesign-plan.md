# Discovery Finalization Improvement Plan

## Objective

Fix the agent-facing Discovery finalization problems without rewriting the
existing host, replacement, conflict, authority, or Operational Memory policy.

The implementation should preserve the current `finalize_discovery()` flow and
its transactional write path. The work focuses on six verified problems:

1. callers cannot tell whether a `NOT_SAVED` response closed the run;
2. correctable transport-policy results consume the run;
3. `field_paths` cannot name a field at the root of a single record;
4. four common validation messages do not explain the accepted form;
5. there is no non-mutating way to test the real finalization path;
6. the documentation lacks complete, executable payload examples.

## Constraints

Preserve:

- the `DIRECT_READ -> LIGHTPANDA -> CHROME` policy;
- existing accepted and pending knowledge semantics;
- the Operational Memory database schema;
- transactional rollback and idempotent retry behavior;
- fail-closed write authority and marker handling;
- task-data rejection;
- Linux and native Windows behavior;
- the public finalization statuses `SAVED`, `ALREADY_EXISTS`, and
  `NOT_SAVED`.

Do not introduce new runtime modules, a second validator, a mutation-plan
abstraction, or new normal-mode finalization statuses. `VALID` exists only in
the explicitly requested validation mode.

## 1. Make run state explicit

Add `run_state` to every `scripts/discovery-finalize` response:

```json
{"run_state":"OPEN|CLOSED"}
```

The CLI must no longer require the caller to infer marker state from the exit
code, output stream, status, or reason code.

### Terminal results

These results close the matching run and return `run_state: "CLOSED"`:

- `SAVED`;
- `ALREADY_EXISTS`;
- terminal `NOT_SAVED` results such as `NO_REUSABLE_KNOWLEDGE`,
  `ALREADY_PENDING`, `INFERENCE_ONLY`, replacement refusal, conflict, or
  confirmation pending.

### Retryable results

These current results are correctable and must keep the matching run open:

- `TRANSPORT_POLICY_UNPROVEN`;
- `FAILURE_UNCLASSIFIED`.

They keep `status: "NOT_SAVED"` for compatibility and add
`run_state: "OPEN"`. The same corrected payload may then be submitted with the
same `run_id`.

Keep the retryable reason-code set beside `DiscoveryFinalization`, not as a
duplicate list in the CLI. The result should expose whether it closes the run;
the CLI should only execute that decision.

### Errors and close failures

- schema, marker, authority, and infrastructure errors return
  `run_state: "OPEN"`;
- a marker-close failure after a committed knowledge write returns
  `run_state: "OPEN"` plus the completed `knowledge_status`;
- retrying that payload remains idempotent: knowledge resolves to
  `ALREADY_EXISTS`, then the marker closes.

Keep the existing exit-code behavior unless a regression test proves a caller
requires a change. `run_state` is the new authoritative retry signal.

## 2. Add non-mutating `--validate`

Add:

```text
python3 scripts/discovery-finalize --validate --input discovery.json
```

Validation must execute the same `finalize_discovery()` code as a real write.
Do not copy its schema or policy into a separate validation path.

### Implementation

Add a private `dry_run: bool = False` parameter to `finalize_discovery()` and a
private sentinel exception used only to roll back its existing transaction:

```python
try:
    with memory.write_transaction() as writer:
        # existing capture / enrich / replace / promote body
        if dry_run:
            raise _DryRunRollback
except _DryRunRollback:
    pass

# existing result classification continues unchanged
```

The sentinel must be caught immediately outside `write_transaction()`. No
broader exception handler may swallow it. Early no-write results continue to
return normally.

`--validate`:

1. uses the existing `read_input()` wrapper validation;
2. resolves the same Knowledge Root and open run marker;
3. calls `finalize_discovery(..., dry_run=True)`;
4. never calls `close_discovery()`;
5. reports the result the real call would produce and `run_state: "OPEN"`;
6. performs no persistent database or filesystem mutation.

Use a validation-mode envelope that cannot imply knowledge was saved:

```json
{
  "status": "VALID",
  "would_finalize_as": "SAVED",
  "would_reason_code": null,
  "run_state": "OPEN"
}
```

Schema-invalid validation keeps the existing structured error behavior and
adds `run_state: "OPEN"`.

### Accepted trade-off

Validation briefly takes the existing SQLite write lock and requires a writable
Knowledge Root. This is acceptable for the single-installation local store and
ensures validation cannot drift from real finalization.

Tests must compare persisted rows and marker files before and after validation.
Do not use SQLite `total_changes` as the assertion because it counts rolled-back
row operations.

The top-level field allow-list in `read_input()` remains the single wrapper
schema for both modes. Do not add another allow-list inside `--validate`.

## 3. Support single-record field paths

Extend the existing field-path grammar to accept an explicit root:

```text
$.headline
$.article.full_text
```

Keep all currently accepted dotted and bracket paths:

```text
post.headline
items[].name
items[0].name
```

A bare word such as `headline` remains invalid because it is indistinguishable
from a one-word task result. Its error must tell the caller to use
`$.headline`.

Implement this in the existing `_SCHEMA_FIELD_PATH` validation. Do not add a
JSONPath dependency or claim full JSONPath compatibility.

## 4. Improve the observed opaque diagnostics

Change the four messages that caused the reported retry loops.

### Symbolic values

`_symbol()` must explain that the value starts with a letter and may contain
letters, digits, `_`, `.`, `:`, or `-`. Include a safe example such as
`SITE_BLOCKING`.

### Schema field paths

`_schema_map()` must include accepted examples:

```text
$.headline, post.headline, items[].name
```

It must not echo raw article text or other rejected task data.

### Validation context

`_normalize_validation()` must name unsupported keys and list the accepted
top-level validation keys. Nested context errors continue to use
`_exact_keys()`.

### Host evidence mismatch

`_host_plan()` must report:

- the claimed Observation Host;
- the public hostnames found in evidence locators;
- that `scope` must be exactly `"TARGET_SURFACE"`;
- that the evidence hostname must exactly match the literal Observation Host.

Keep the semantic distinction:

- target references normalize a leading `www.` for identity lookup;
- Observation Hosts remain literal behavior scopes because apex and `www`
  hosts may behave differently.

Do not broaden this change into an aggregated-error validator. Reassess that
only if agents still need repeated correction cycles after `--validate`, the
targeted diagnostics, and executable examples are available.

## 5. Add executable payload examples

Create `references/discovery-payload-examples.md` with complete, copyable
payloads for:

1. functional `DIRECT_READ`;
2. single-record extraction using `$.field`;
3. collection extraction using `items[].field`;
4. first-time host association with `scope: "TARGET_SURFACE"`;
5. browser escalation with a complete transport trace;
6. a fully blocked ladder with durable failure classification;
7. an observed blocking or limitation constraint with complete validation
   context.

Add a deterministic test that extracts every JSON payload from the reference,
opens its synthetic Discovery run, and finalizes it successfully. Documentation
must fail the suite when it drifts from the runtime contract.

Update:

- `SKILL.md`;
- `references/target-profile.md`;
- `references/transport-and-modes.md`;
- `CHANGELOG.md`.

Explicitly replace the pinned contract sentence:

```text
Any returned SAVED, ALREADY_EXISTS, or NOT_SAVED verdict closes only the matching run.
```

The new rule must state:

- every response reports `run_state`;
- `SAVED`, `ALREADY_EXISTS`, and terminal `NOT_SAVED` close the matching run;
- `TRANSPORT_POLICY_UNPROVEN`, `FAILURE_UNCLASSIFIED`, schema errors, and
  infrastructure errors leave it open;
- a schema-only rejection is corrected by rerunning only
  `discovery-finalize`, never navigation or extraction.

Update the exact assertion in
`tests/test_discovery_enforcement.py::test_discovery_runs_are_visible_execution_identity_only`
and the run-lifecycle tests in `tests/test_discovery_runs.py`.

### Abandoned runs

Document the current behavior: if a caller abandons a retryable or invalid
finalization, its marker remains open and visible through lookup and preflight.
This change does not add expiration or automatic cleanup. Marker cleanup is a
separate lifecycle feature and should be based on observed need.

## 6. Separate authority cleanup

After the agent-facing fixes ship, make one independent change that:

- removes the synthetic `prop:authority-check` Candidate call;
- derives write authority from the Knowledge Root at the write seam;
- removes pass-through authority parameters where production callers always
  supply the same values;
- rewrites authority tests to create real marker states instead of asserting
  authority through arguments.

This cleanup is valid but is not a prerequisite for `run_state`, `--validate`,
field paths, diagnostics, or examples. Review and land it separately so any
authority regression is isolated.

## Implementation order

### Change 1 — Run lifecycle

1. Add exact regression tests for retryable and terminal results.
2. Add `run_state` to every CLI response.
3. Keep the run open for `TRANSPORT_POLICY_UNPROVEN` and
   `FAILURE_UNCLASSIFIED`.
4. Update the pinned contract sentence and tests.

### Change 2 — Validation and diagnostics

1. Add rollback-based `--validate`.
2. Add `$.field` support.
3. Improve the four targeted messages.
4. Prove validation leaves database contents and marker files unchanged.

### Change 3 — Executable documentation

1. Add the payload-example reference.
2. Test every documented payload.
3. Update the skill, target profile, transport reference, and changelog.
4. Document abandoned open markers.

### Change 4 — Independent authority cleanup

Remove the fake authority call and pass-through in a separate reviewable
change.

Keep the deterministic suite green after every change.

## Test matrix

### Run lifecycle

- schema error: `NOT_SAVED`, `OPEN`, same run remains usable;
- `TRANSPORT_POLICY_UNPROVEN`: `NOT_SAVED`, `OPEN`, corrected payload succeeds;
- `FAILURE_UNCLASSIFIED`: `NOT_SAVED`, `OPEN`, corrected payload succeeds;
- `NO_REUSABLE_KNOWLEDGE`: `NOT_SAVED`, `CLOSED`;
- pending/inference/conflict terminal result: `NOT_SAVED`, `CLOSED`;
- `SAVED`: `CLOSED`;
- `ALREADY_EXISTS`: `CLOSED`;
- close failure after commit: `FINALIZATION_INCOMPLETE`, `OPEN`, retry closes.

### Validation

- successful `--validate` predicts the real finalization result;
- early no-write outcomes are predicted without closing the marker;
- mutating paths roll back every table change;
- host creation, evidence, validation, Candidate, Claim, Proposal, Decision,
  enrichment, promotion, and replacement paths leave no persisted dry-run
  delta;
- validation never removes or rewrites the run marker;
- real finalization after validation still succeeds;
- validation requires the same authority and writable Knowledge Root as the
  real command;
- concurrent write-lock behavior remains bounded and deterministic.

### Payload and diagnostics

- `$.headline` and `$.article.full_text` are accepted;
- existing dotted/bracket paths remain accepted;
- a bare `headline` is rejected with the explicit-root hint;
- symbolic-value errors show the grammar;
- validation-context errors show unsupported and accepted keys;
- host mismatch errors show claimed/evidence hosts and `TARGET_SURFACE`;
- rejected task data is never echoed;
- every documented example finalizes successfully.

## Required verification

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
git diff --check
python3 scripts/preflight --help
python3 scripts/discovery-finalize --help
```

## Completion criteria

The work is complete when:

- every finalization response states whether the run is open or closed;
- correctable policy results reuse the same `run_id`;
- `--validate` exercises the real write path and leaves no persistent change;
- single-record extraction uses `$.field` without a synthetic wrapper;
- the four reported opaque errors provide the accepted form;
- agents can copy complete valid payloads from one reference;
- documentation examples are enforced by tests;
- abandoned-run behavior is documented;
- all existing transport, authority, transaction, task-data, Linux, and Windows
  guarantees remain green.

## Explicitly deferred

Defer until new evidence justifies them:

- splitting `discovery_finalize.py` into contract, gate, and applier modules;
- replacing exception-based validation with aggregated diagnostics;
- expanding `_FAMILY_FIELDS` into a generic declarative schema framework;
- adding new finalization statuses for retryable results;
- adding run expiration or automatic cleanup;
- changing Operational Memory or transport policy.
