# Plan 005: Make host association the default and compare evidence hostnames in the same IDNA form

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 929c0b1..HEAD -- discovery_finalize.py references/discovery-payload-examples.md references/target-profile.md SKILL.md tests/test_discovery_finalize.py tests/test_discovery_payload_examples.py tests/test_target_identity.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none (plan 004 touches nearby messages; merge either order)
- **Category**: bug
- **Planned at**: commit `929c0b1`, 2026-09-02

## Why this matters

A target is reachable by URL or hostname only through a recorded
target<->host association. Nothing requires one: a payload without
`observation.host` writes a target with zero host rows and no warning, and
the three examples an agent copies first carry no `host`. In the
maintainer's real memory 16 of 35 targets have no host, so
`knowledge-lookup --target www.npr.org` returns `not_found` while `npr`
returns `found`. Separately, the evidence-hostname check compares the
punycode form of `observation.host` against the raw Unicode hostname of the
locator, so an internationalized domain can never register a host. This
plan adds a non-fatal `warnings` entry when a target closes with no host,
puts `host` into the copied examples, normalizes both sides of the host
check the same way, and documents the `www.` asymmetry where the agent
reads the rules.

## Current state

`discovery_finalize.py:1017-1023` (`_host_plan` opening)
```python
def _host_plan(
    memory: SQLiteOperationalMemory, target: str, observations: Sequence[Mapping[str, Any]],
    evidence: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    hostnames = sorted({str(item["host"]) for item in observations if item.get("host")})
    if not hostnames:
        return {}, []
```

`discovery_finalize.py:1036-1057` (the literal compare and its message)
```python
        proven = any(
            source.get("scope") == "TARGET_SURFACE"
            and urlparse(str(source.get("locator", ""))).hostname
            and urlparse(str(source["locator"])).hostname.lower().rstrip(".") == hostname
            for source in evidence
        )
        if not proven:
            evidence_hostnames = sorted({
                urlparse(str(source["locator"])).hostname.lower().rstrip(".")
                for source in evidence
                if urlparse(str(source.get("locator", ""))).hostname
            })
            raise DiscoveryFinalizationError(
                f"a new observation host requires TARGET_SURFACE evidence from "
                f"that hostname. Claimed Observation Host: {hostname!r}. "
                f"Public hostnames found in evidence locators: {evidence_hostnames!r}. "
                "An evidence item's scope must be exactly 'TARGET_SURFACE', and "
                "its locator hostname must exactly match the literal Observation "
                "Host (a leading 'www.' is not normalized here, unlike target "
                "reference resolution)"
            )
```

`discovery_finalize.py:362-380` (`_normalize_hostname`) returns
`validate_public_hostname(value)`, which is the **ASCII IDNA** form
(`operational_memory/core.py:123-160`; verified:
`validate_public_hostname("münchen.de") == "xn--mnchen-3ya.de"` while
`urlparse("https://münchen.de/x").hostname == "münchen.de"`).

`discovery_finalize.py:116-125` — `DiscoveryFinalization` has no `warnings`
field; `as_dict` (138-147) emits `status`, `target`, `capability`, optional
`reason`/`reason_code`, `run_state`.

`references/discovery-payload-examples.md` examples 1-3 (lines 15-68) have
no `host`; example 4 (lines 71-95) shows the `host` + `scope: TARGET_SURFACE`
pair with `www.example-host-assoc.example` on both sides.

`references/target-profile.md:20-31` says host references normalize by
dropping `www.`; the observation-host literal rule appears only in the error
string above and in a private docstring. `SKILL.md:116` says only "the
finalizer checks hostname evidence and collisions".

Real-memory evidence: `hosts=[]` for `abc-news-australia`, `bloomberg`,
`cnn-international`, `euronews`, `flowco-com-br`, `nikkei-asia`, `npr`,
`npr-org`, `nytimes`, `pbs-org`, `politico-com`, `politico-eu`,
`politico-europe`, `scmp`, and two localhost targets.

Conventions: keep fail-closed on the evidence gate (a host claim is a
durable identity claim, `target-profile.md:48-61`); warnings are advisory
JSON, never a status change; tests through `self.finalize(...)` in
`tests/test_discovery_finalize.py`; IDN tests exist in
`tests/test_target_identity.py` (grep `idna` there for the style).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Full suite | `python3 -m unittest discover -s tests -p 'test_*.py'` | `OK` |
| Finalize | `python3 -m unittest tests.test_discovery_finalize -v` | pass |
| Examples | `python3 -m unittest tests.test_discovery_payload_examples -v` | pass |
| Whitespace | `git diff --check` | no output |

## Scope

**In scope**:
- `discovery_finalize.py` (`_host_plan`, a new `_evidence_hostname` helper, `DiscoveryFinalization.warnings`)
- `scripts/discovery-finalize` (only if `as_dict` plumbing is needed; expected none)
- `references/discovery-payload-examples.md`, `references/target-profile.md`, `SKILL.md`
- `tests/test_discovery_finalize.py`, `tests/test_discovery_payload_examples.py`

**Out of scope**:
- Making `host` mandatory (would break multi-host targets and the evidence gate).
- `operational_memory/core.py` (`normalize_host_reference`, `validate_public_hostname` stay as they are).
- `discovery_runs.py` / `discovery-begin` (a `--host` intent flag is a possible follow-up, not this plan).
- Backfilling hosts for existing targets.

## Git workflow

- Branch: `advisor/005-host-association`
- One imperative sentence per commit, sentence case, no prefix.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: One helper for evidence hostnames

Add near `_normalize_hostname`:

```python
def _evidence_hostname(locator: str) -> str | None:
    """Locator hostname in the same canonical (ASCII IDNA) form as observation.host."""
    raw = urlparse(str(locator)).hostname
    if not raw:
        return None
    try:
        return validate_public_hostname(raw)
    except TargetIdentityError:
        return None
```

Replace the three `urlparse(...).hostname.lower().rstrip(".")` expressions in
`_host_plan` with `_evidence_hostname(...)`. Print the canonical list in the
error message. Keep the literal (no `www.` stripping) comparison — that is
the documented rule; only the encoding is unified.

**Verify**: `python3 -m unittest tests.test_discovery_finalize -v` → pass.

### Step 2: Warn when a target closes with no host

Add `warnings: list[str] = field(default_factory=list)` to
`DiscoveryFinalization` (it is a dataclass; check the decorator at line 115
and import `field` from `dataclasses` if not already). In `as_dict`, emit
`"warnings"` only when non-empty. In `finalize_discovery`, just before the
`SAVED` return, compute:

```python
    has_host = bool(host_ids) or bool(
        list(memory._conn.execute("SELECT 1 FROM hosts WHERE target_id=? LIMIT 1", (f"tgt:{target}",)))
    )
    warnings = [] if has_host else [
        "NO_HOST_ASSOCIATION: this target has no recorded host, so a later "
        "lookup by URL or hostname cannot resolve it. A future Discovery can "
        "add one with observation.host plus TARGET_SURFACE evidence."
    ]
```

Pass `warnings=warnings` on the `SAVED` and `ALREADY_EXISTS` returns. Do not
change `status`.

**Verify**: seed a temp root, finalize example 1 (no host) → stdout JSON contains `"warnings": ["NO_HOST_ASSOCIATION: ..."]`; finalize example 4 → no `warnings` key.

### Step 3: Put `host` into examples 1-3

In `references/discovery-payload-examples.md`, add to each of examples 1, 2,
3 a `"host"` on the transport observation matching the locator host
(`example-direct-read.example`, `example-single-record.example`,
`example-collection.example`) and add `"scope": "TARGET_SURFACE"` to the
existing evidence item. Add one sentence under the file intro: "Every
first-run example records the host it observed; a target without a host is
never reachable by URL." Update
`tests/test_discovery_payload_examples.py::test_every_documented_example_finalizes_successfully`
to also assert `"warnings" not in body` for every example (they all carry a
host now).

**Verify**: `python3 -m unittest tests.test_discovery_payload_examples -v` → pass.

### Step 4: Document the `www.` asymmetry where the rules are read

`references/target-profile.md`, right after the wrapper/observation shape
paragraph (~line 134), add: "`observation.host` is a literal behavior scope:
`www.example.com` and `example.com` are distinct hosts there, and the
`TARGET_SURFACE` evidence locator must use the same literal hostname.
Target-reference resolution (above) drops `www.`; host scope does not. Both
sides are compared in canonical ASCII (IDNA) form, so a Unicode locator and
its punycode form match." `SKILL.md:116`: extend "the finalizer checks
hostname evidence and collisions" with ", comparing the literal
`observation.host` (no `www.` stripping) against the `TARGET_SURFACE`
evidence locator; a target saved without any host is reported in `warnings`
and cannot be found by URL later".

**Verify**: `python3 -m unittest tests.test_skill_adapter_parity tests.test_marker_parity tests.test_public_vocabulary -v` → pass.

### Step 5: Tests

`tests/test_discovery_finalize.py`:

- `test_unicode_evidence_locator_matches_punycode_observation_host`: host
  `münchen.example`, evidence locator `https://münchen.example/x` with
  `scope: TARGET_SURFACE` → `SAVED`; the same with locator
  `https://xn--mnchen-3ya.example/x` → `SAVED` too.
- `test_www_host_still_literal`: host `example-news.com`, evidence locator
  `https://www.example-news.com/` → raises `DiscoveryFinalizationError`
  whose message contains `www.example-news.com`.
- `test_saved_without_host_warns` and `test_saved_with_host_has_no_warning`.
- `test_already_existing_host_suppresses_warning`: seed a host row for the
  target, finalize a host-less payload → no warning.

**Verify**: `python3 -m unittest tests.test_discovery_finalize -v` → pass.

## Test plan

- Five new tests in `tests/test_discovery_finalize.py`; one assertion added
  to the examples test.
- Verification: full suite `OK`.

## Done criteria

- [ ] `python3 -m unittest discover -s tests -p 'test_*.py'` exits 0
- [ ] `grep -c 'hostname.lower().rstrip' discovery_finalize.py` is 0
- [ ] `grep -n "NO_HOST_ASSOCIATION" discovery_finalize.py SKILL.md` return hits
- [ ] Examples 1-3 in `references/discovery-payload-examples.md` contain `"host"` and `"scope": "TARGET_SURFACE"`
- [ ] `git diff --check` prints nothing
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `DiscoveryFinalization` is not a dataclass or `as_dict` is consumed by a
  test that compares the whole dict and cannot accept an optional key.
- Adding `host` to examples 1-3 makes any of them fail to finalize (report
  the refusal text; do not drop the `scope`).
- The IDNA test fails because `validate_public_hostname` rejects the
  Unicode form — that would contradict the verified behavior above.

## Maintenance notes

- Plan 007 (`--list`) shows host associations per target, which is how a
  maintainer finds the 16 host-less targets to repair.
- A future `discovery-begin --host` flag would record intent earlier; it is
  deliberately not in this plan.
- Reviewers: confirm the evidence gate still refuses a `www.` mismatch — the
  literal rule is intentional (`docs/discovery-finalization-redesign-plan.md:213-214`).
