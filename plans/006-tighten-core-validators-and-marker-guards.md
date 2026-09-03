# Plan 006: Canonical timestamps, short-form IP literals, and the run-marker symlink guard

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 929c0b1..HEAD -- operational_memory/core.py discovery_runs.py write_authority.py tests/test_production_memory_core.py tests/test_target_identity.py tests/test_discovery_runs.py tests/test_write_authority.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `929c0b1`, 2026-09-02

## Why this matters

Three small validator gaps, each verified by running the code:

1. `validate_timestamp` accepts `2024-01-01Z`, `20240101T000000Z`,
   `2024-01-01T00:00Z`, and fractional seconds, while every comparison of
   `recorded_at`/`effective_at`/validity is lexicographic. A payload using a
   non-canonical form reorders Decisions in the projection (`'2024-01-01Z' >
   '2024-01-01T00:00:00Z'` because `Z` sorts after `T`), which changes what
   lookup reports as accepted. This fails open.
2. `validate_public_hostname` promises to reject IP literals but accepts
   `127.1` and `0x7f.0.0.1`, which resolvers treat as loopback.
3. Discovery run markers (`.caravelaweb/open-discovery/*.json`) are read with
   `path.read_text()` and gated by `is_file()`, both of which follow
   symlinks; every other marker in the repo uses `os.lstat` +
   `safe_marker_stat`. The write-authority marker also re-opens by name
   after the `lstat` check (a check-then-read gap).

## Current state

`operational_memory/core.py:75-86`
```python
def validate_timestamp(value: str | None, *, field: str, required: bool = True) -> None:
    if value is None:
        if required:
            raise RecordValidationError(f"{field} is required")
        return
    if not isinstance(value, str) or not value.endswith("Z"):
        raise RecordValidationError(f"{field} must be RFC 3339 UTC ending in Z")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise RecordValidationError(f"{field} is not a valid RFC 3339 timestamp") from exc
```

Producers already emit the canonical form: `discovery_finalize.py:158-159`
and `discovery_runs.py:25-26` use
`datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")`.
The test fixture constant is `RECORDED = "2026-07-28T12:00:00Z"`.

`operational_memory/core.py:106-111`
```python
def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True
```
and the check at line 155: `if _is_ip_literal(host): raise TargetIdentityError(...)`.
Verified: `validate_public_hostname("127.1")` returns `"127.1"`;
`"0x7f.0.0.1"` returns `"0x7f.0.0.1"`; `"127.0.0.1"` is rejected.

`discovery_runs.py:84-99` (`_read_marker`) begins with
`value = json.loads(path.read_text(encoding="utf-8"))`;
`discovery_runs.py:111-112`: `if not marker.is_file(): raise DiscoveryRunError("no open Discovery marker matches provenance.run_id")`;
`discovery_runs.py:137`: `paths = sorted(_directory(root).glob("*.json"))`.

`write_authority.py:65-80` (`_read_marker`)
```python
    marker = write_authority_marker(root)
    try:
        stat = os.lstat(marker)
    except FileNotFoundError:
        return None
    ...
    if not safe_marker_stat(stat):
        raise WriteAuthorityStateError(f"unsafe write-authority marker: {marker}")
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
```

The safe pattern already in the repo, `installation_init.py:201-209`
(`_write_new_marker`): `os.open(path, flags | O_NOFOLLOW)` then
`os.fdopen`. `platform_adapter.safe_marker_stat(stat_result)` (line 137)
accepts a regular, single-link, non-reparse file. `os.O_NOFOLLOW` is absent
on Windows; guard with `hasattr(os, "O_NOFOLLOW")` as `installation_init`
does, and rely on `safe_marker_stat` (which checks the reparse-point
attribute) there.

Existing tests: `tests/test_production_memory_core.py` covers timestamps
generally (grep `validate_timestamp`); `tests/test_target_identity.py`
covers hostname validation (grep `ip_literal` / `127.0.0.1`);
`tests/test_discovery_runs.py` and `tests/test_write_authority.py` cover
markers. `tests/test_marker_parity.py` asserts that marker handling is
uniform across modules — read it before Step 3; the new run-marker guard
must satisfy it.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Full suite | `python3 -m unittest discover -s tests -p 'test_*.py'` | `OK` |
| Core | `python3 -m unittest tests.test_production_memory_core tests.test_target_identity -v` | pass |
| Markers | `python3 -m unittest tests.test_discovery_runs tests.test_write_authority tests.test_marker_parity -v` | pass |
| Whitespace | `git diff --check` | no output |

## Scope

**In scope**:
- `operational_memory/core.py` (`validate_timestamp`, `_is_ip_literal`)
- `discovery_runs.py` (`_read_marker`, `require_open_discovery`, `list_open_discoveries`)
- `write_authority.py` (`_read_marker` read-through-descriptor)
- `tests/test_production_memory_core.py`, `tests/test_target_identity.py`, `tests/test_discovery_runs.py`, `tests/test_write_authority.py`

**Out of scope**:
- `read_authority.py`, `knowledge_write_freeze.py` (they never read content after the stat; no gap).
- Any schema migration. Existing databases written by this code already hold canonical timestamps.
- `scripts/*`.

## Git workflow

- Branch: `advisor/006-validators`
- One imperative sentence per commit, sentence case, no prefix.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Canonical timestamps

Replace the body of `validate_timestamp` after the `None` handling with:

```python
    if not isinstance(value, str) or not value.endswith("Z"):
        raise RecordValidationError(f"{field} must be RFC 3339 UTC ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise RecordValidationError(f"{field} is not a valid RFC 3339 timestamp") from exc
    canonical = parsed.isoformat(timespec="seconds").replace("+00:00", "Z")
    if canonical != value:
        raise RecordValidationError(
            f"{field} must be the canonical form YYYY-MM-DDTHH:MM:SSZ, for example {canonical}"
        )
```

Then run the full suite. If any fixture in `tests/` uses a non-canonical
timestamp (grep `T..:..Z"` patterns without seconds, or fractional
seconds), that fixture was relying on the gap: fix the fixture to canonical
form, never the validator.

**Verify**: `python3 -c "import sys; sys.path.insert(0,'.'); from operational_memory.core import validate_timestamp as v; [print(t, end=' ') or v(t, field='x') for t in ['2024-01-01T00:00:00Z']]"` → prints the value with no error; the same with `'2024-01-01Z'` → raises `RecordValidationError`.

### Step 2: Short-form IP literals

Replace `_is_ip_literal` with a check that also catches the legacy forms:

```python
_NUMERIC_LABEL = re.compile(r"^(0x[0-9a-f]+|0[0-7]*|[1-9][0-9]*)$")

def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    labels = host.split(".")
    if labels and all(_NUMERIC_LABEL.fullmatch(label) for label in labels):
        return True   # every label numeric or hex: a legacy/short IPv4 form, never a hostname
    return False
```

(`host` is already lower-cased by the caller.) Keep the docstring claim at
lines 134-141 accurate; it now is.

**Verify**: `python3 -c "import sys; sys.path.insert(0,'.'); from operational_memory.core import validate_public_hostname as v; [print(h, end=' ') or v(h) for h in ['127.1','0x7f.0.0.1','2130706433']]"` → each raises `TargetIdentityError`; `v('example.com')` still returns `example.com`; `v('1e100.net')` still returns `1e100.net` (a label with letters is not numeric).

### Step 3: Guard the run markers

In `discovery_runs.py` add:

```python
def _open_marker(path: Path) -> str:
    """Read a run marker only if it is a regular, singly linked file."""
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        if not safe_marker_stat(os.fstat(fd)):
            raise DiscoveryRunError("Discovery run marker is not a regular file")
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = -1
            return stream.read()
    finally:
        if fd != -1:
            os.close(fd)
```

Import `safe_marker_stat` from `platform_adapter`. Use it in `_read_marker`
instead of `path.read_text`. In `require_open_discovery` replace
`marker.is_file()` with an `os.lstat` + `safe_marker_stat` check (missing →
the existing "no open Discovery marker" error; unsafe → "Discovery run
marker is invalid"). `list_open_discoveries` already routes through
`_read_marker`, so a symlinked marker becomes `{"status": "INVALID", ...}`
there, matching its existing invalid-marker branch.

**Verify**: `python3 -m unittest tests.test_discovery_runs tests.test_marker_parity -v` → pass.

### Step 4: Read the write-authority marker through the checked descriptor

In `write_authority.py::_read_marker`, replace the `os.lstat` + `read_text`
pair with the same descriptor-first pattern: `os.open(marker, O_RDONLY |
O_NOFOLLOW)`, `safe_marker_stat(os.fstat(fd))`, read through `os.fdopen`.
Keep the exception mapping exactly: `FileNotFoundError → None`, other
`OSError → WriteAuthorityStateError("... cannot be inspected ...")`,
unsafe → `WriteAuthorityStateError("unsafe write-authority marker: ...")`,
bad JSON → `WriteAuthorityStateError("invalid write-authority marker: ...")`.

**Verify**: `python3 -m unittest tests.test_write_authority tests.test_marker_parity tests.test_fresh_install_lifecycle -v` → pass.

### Step 5: Tests

- `tests/test_production_memory_core.py`: `test_timestamps_must_be_canonical`
  — the four accepted-today variants raise; the canonical form passes; the
  error message names the canonical example.
- `tests/test_target_identity.py`: `test_short_form_and_hex_ipv4_are_rejected`
  for `127.1`, `0x7f.0.0.1`, `2130706433`, `0177.0.0.1`; and a positive case
  for `1e100.net`.
- `tests/test_discovery_runs.py`: `test_symlinked_run_marker_is_refused`
  (create a real marker in a temp dir, `os.symlink` it into
  `open-discovery/<digest>.json`, assert `require_open_discovery` raises
  `DiscoveryRunError` and `list_open_discoveries` reports `INVALID`). Skip
  with a reason on platforms where `os.symlink` raises `OSError`, following
  the skip style in `tests/test_platform_adapter.py:113-139`.
- `tests/test_write_authority.py`: `test_symlinked_marker_is_unsafe` if not
  already present (grep first); if present, no new test.

**Verify**: `python3 -m unittest discover -s tests -p 'test_*.py'` → `OK`.

## Test plan

- Four to five new tests as listed in Step 5.
- Verification: full suite `OK`.

## Done criteria

- [ ] `python3 -m unittest discover -s tests -p 'test_*.py'` exits 0
- [ ] `validate_timestamp('2024-01-01Z', field='x')` raises
- [ ] `validate_public_hostname('127.1')` raises
- [ ] `grep -n "read_text" discovery_runs.py write_authority.py` returns no marker read
- [ ] `git diff --check` prints nothing
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- More than three test fixtures use non-canonical timestamps (that suggests
  a deliberate tolerance you should confirm with the maintainer).
- `tests/test_marker_parity.py` requires a helper signature different from
  the one in Step 3; adopt its required shape instead of inventing one, and
  stop if that is unclear.
- The Windows CI job (see `.github/workflows/ci.yml`) is expected to run
  these tests; `O_NOFOLLOW` is absent there — the code must still import and
  pass. If you cannot run Windows locally, say so in the report.

## Maintenance notes

- Any new marker file type must use `_open_marker`-style reads; consider
  moving the helper into `platform_adapter.py` in a later cleanup so all four
  marker modules share it (deferred to keep this plan small).
- The canonical-timestamp rule is now part of the payload contract; mention
  it in `CHANGELOG.md` under Unreleased.
