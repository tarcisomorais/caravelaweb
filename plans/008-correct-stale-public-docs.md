# Plan 008: Correct the stale public documentation claims

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 929c0b1..HEAD -- docs/architecture.md docs/installation.md docs/platform-support.md README.md CHANGELOG.md scripts/preflight tests/test_public_runtime_boundary.py tests/test_preflight.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (plan 002 adds one more script; if it landed first, count six entry points instead of five)
- **Category**: docs
- **Planned at**: commit `929c0b1`, 2026-09-02

## Why this matters

For this project the docs are the user interface: an agent reads them and
acts. Four statements are wrong today and each one has a concrete cost:
the architecture page lists four runtime CLIs and omits the mandatory
`discovery-begin`; the installation page says the plugin declares no
version while both manifests say `0.1.0`; README and installation promise
macOS while the platform page disclaims it and CI never runs it; and
`preflight` prints ready-to-run invocation strings for four scripts but not
for `init-knowledge-root`, the one command the agent must run next on a
cold install. Each fix is small and this plan adds tests so two of them
cannot drift again.

## Current state

`docs/architecture.md:8-16`
```markdown
## Public runtime boundary

Four CLI entry points form the supported runtime surface:

- `scripts/init-knowledge-root`
- `scripts/preflight`
- `scripts/knowledge-lookup`
- `scripts/discovery-finalize`
```
and its import-closure list (lines 18-32) omits `discovery_runs.py`, which
`tests/test_public_runtime_boundary.py:25-38` includes in
`EXPECTED_RUNTIME_CLOSURE`. `SKILL.md:143-144` lists five scripts including
`discovery-begin`. `CHANGELOG.md:11` says "four command-line entry points".
`docs/installation.md` "Runtime commands (advanced)" table (~lines 259-266)
has no `discovery-begin` row.

`docs/installation.md:63-66`
```markdown
The plugin declares no `version`, so Claude Code versions it by the source
commit. `/plugin update caravelaweb@caravelaweb` therefore moves you to the
latest commit of the default branch. A numbered release policy is not yet
established; see [CHANGELOG](../CHANGELOG.md).
```
but `.claude-plugin/plugin.json:3` and `.codex-plugin/plugin.json:3` both
declare `"version": "0.1.0"`, `CHANGELOG.md:5` has `## 0.1.0 - 2026-08-26`,
and the same page says at lines 30-31 "The Codex manifest carries an explicit
semantic version."

macOS: `docs/platform-support.md:10` — "Not currently CI validated ... no
support claim is made without CI evidence"; `docs/installation.md:11` —
"Windows, Linux, WSL2, or macOS"; `README.md:41` — "The same two commands
work on Windows, Linux, WSL2, and macOS."; `.github/workflows/ci.yml` runs
`ubuntu-latest` and `windows-latest` only.

`scripts/preflight:271-276`
```python
        "invocation": {
            "preflight": f'"{sys.executable}" "{Path(__file__).resolve()}"',
            "knowledge_lookup": f'"{sys.executable}" "{SKILL_ROOT / "scripts" / "knowledge-lookup"}"',
            "discovery_begin": f'"{sys.executable}" "{SKILL_ROOT / "scripts" / "discovery-begin"}"',
            "discovery_finalize": f'"{sys.executable}" "{SKILL_ROOT / "scripts" / "discovery-finalize"}"',
        },
```
and the text mode prints only `invocation: {preflight}` (line ~309).
`SKILL.md:20-21`: "When no Knowledge Root resolves, run
`<python> <skill>/scripts/init-knowledge-root` once".

Conventions: docs are ASCII English, wrapped at ~80 columns; tests are
`unittest`; `tests/test_preflight.py` runs the script by subprocess with
`--json`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Full suite | `python3 -m unittest discover -s tests -p 'test_*.py'` | `OK` |
| Boundary | `python3 -m unittest tests.test_public_runtime_boundary -v` | pass |
| Preflight | `python3 -m unittest tests.test_preflight -v` | pass |
| Whitespace | `git diff --check` | no output |

## Scope

**In scope**:
- `docs/architecture.md`, `docs/installation.md`, `docs/platform-support.md`, `README.md`, `CHANGELOG.md`
- `scripts/preflight`
- `tests/test_public_runtime_boundary.py`, `tests/test_preflight.py`

**Out of scope**:
- Adding a macOS CI job (a maintainer decision; this plan aligns the text to
  the current CI, and notes the alternative).
- `SKILL.md` (already correct on these points).
- The plugin manifests.

## Git workflow

- Branch: `advisor/008-docs-corrections`
- One imperative sentence per commit, sentence case, no prefix.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Five entry points, and the closure list

`docs/architecture.md`: change "Four" to "Five", add `scripts/discovery-begin`
between `knowledge-lookup` and `discovery-finalize`, and add
`discovery_runs.py` to the import-closure list in alphabetical position.
`docs/installation.md` runtime table: add a row
`| scripts/discovery-begin | Register the start of one bounded Discovery run and return its run_id. |`.
`CHANGELOG.md:11`: "five command-line entry points". (If plan 002 already
added `knowledge-resolve`, write "six" and include it.)

Then lock it: in `tests/test_public_runtime_boundary.py` add
`test_architecture_doc_lists_the_runtime_closure`: read
`docs/architecture.md`, collect every backticked `*.py` and `scripts/*`
token between the headings `## Public runtime boundary` and
`## Distribution`, and assert that the module set equals
`{m.replace('.', '/') + '.py' for m in EXPECTED_RUNTIME_CLOSURE}` (with
`operational_memory` mapping to `operational_memory/__init__.py`) plus
`operational_memory/schema.sql`, and that the script set equals the entry
points tuple used in `test_public_runtime_import_closure_is_exact`
(hoist that tuple to a module constant `RUNTIME_ENTRY_POINTS` first).

**Verify**: `python3 -m unittest tests.test_public_runtime_boundary -v` → pass.

### Step 2: Version paragraph

Replace `docs/installation.md:63-66` with: "Both plugin manifests declare
the same semantic version (`0.1.0` at this release), and public releases
bump it together with `CHANGELOG.md`. `/plugin update caravelaweb@caravelaweb`
moves you to the newest published version of the marketplace entry." Add a
test in `tests/test_preflight.py` (or a new `tests/test_release_metadata.py`)
asserting that `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json`
carry equal `version` values and that `CHANGELOG.md` contains a heading
`## <that version>`.

**Verify**: `python3 -m unittest tests.test_release_metadata -v` (or the file you chose) → pass.

### Step 3: macOS wording

Add to `README.md:41` and `docs/installation.md:11` a short caveat: "macOS
is not validated by CI; see docs/platform-support.md." Keep
`docs/platform-support.md` as the authority. Record in the plan report that
the alternative is a `macos-latest` job copied from the Linux job in
`.github/workflows/ci.yml`; do not add it here.

**Verify**: `grep -n "macOS" README.md docs/installation.md` shows the caveat on both lines.

### Step 4: `preflight` invocation strings

In `scripts/preflight` add
`"init_knowledge_root": f'"{sys.executable}" "{SKILL_ROOT / "scripts" / "init-knowledge-root"}"'`
to the `invocation` dict, and in the text branch print every invocation
line (`invocation_<name>: ...`) instead of only `preflight`. In
`tests/test_preflight.py` add `test_invocation_covers_every_skill_script`:
run with `--json`, and assert that for every `scripts/<name>` file except
`register-host`, `invocation[name.replace('-', '_')]` exists and ends with
that script's absolute path.

**Verify**: `python3 -m unittest tests.test_preflight -v` → pass; `python3 scripts/preflight` prints an `invocation_init_knowledge_root:` line.

## Test plan

- Three new tests (architecture closure lock, release metadata, preflight
  invocation coverage).
- Verification: full suite `OK`.

## Done criteria

- [ ] `python3 -m unittest discover -s tests -p 'test_*.py'` exits 0
- [ ] `grep -n "Four CLI" docs/architecture.md` returns nothing
- [ ] `grep -n "declares no" docs/installation.md` returns nothing
- [ ] `grep -n "init_knowledge_root" scripts/preflight` returns a hit
- [ ] `git diff --check` prints nothing
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The two manifests carry different versions (report; do not pick one).
- `tests/test_agent_host_integration.py` asserts the exact text-mode
  output of `preflight` and the extra lines break it in a way that is not a
  one-line assertion update.

## Maintenance notes

- The architecture-closure test means every new runtime module or script
  must be added to `docs/architecture.md` in the same change; that is the
  intent.
- The release-metadata test means a version bump must touch both manifests
  and the changelog together.
