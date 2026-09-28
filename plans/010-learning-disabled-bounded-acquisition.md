# Plan 010: Caller guarantees for bounded, learning-disabled acquisition

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Owner decisions first**: change 4 cannot start until the owner has
> answered decision OD-1 below. Changes 1–3 and 5 carry a recommended
> default for OD-2 and OD-3; if the owner has not answered, apply the
> recommendation and say so in the commit body.
>
> **Drift check (run first)**: `git diff --stat 89f701e..HEAD -- SKILL.md platform_adapter.py discovery_runs.py operational_memory/core.py installation_init.py readiness.py scripts/ references/ docs/installation.md CHANGELOG.md tests/test_discovery_enforcement.py tests/test_public_runtime_boundary.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.
>
> **Commit methodology**: one commit per change below, linear history,
> author and committer `Tarciso Morais <287870717+tarcisomorais@users.noreply.github.com>`,
> imperative sentence-case subject with no prefix and no period, a prose
> body wrapped at 76 columns with three paragraphs (observed problem, what
> changed and why, what tests now cover), and no trailers of any kind.
> Releasing is a separate step (version commit, CI, annotated tag,
> `gh release create`) and is not part of this plan.

## Status

- **Priority**: P1 (changes 1–3), P2 (changes 4–5), P1 (change 6, the
  acceptance gate)
- **Effort**: M (1), S (2, 3, 4, 5), M (6)
- **Risk**: MED (1: touches every write path), LOW (2–5: contract text),
  MED (6: live calls)
- **Depends on**: none for 1; 2 depends on 1 (it names the lookup field);
  3 and 5 are independent; 4 depends on OD-1; 6 depends on 1–5
- **Category**: caller contract, safety
- **Planned at**: commit `89f701e`, 2026-09-28

## Why this matters

Disperta runs CaravelaWeb through headless `claude -p` subprocesses to
acquire one article page per call. It needs four guarantees CaravelaWeb
does not give today. Its probe and the investigation on 2026-09-28 found:

- **No per-call "learning disabled" mode exists.** SKILL.md's "if the
  caller authorizes it" is prose only; `discovery-begin` opens a run for
  anyone. The probe's model (Haiku) ran `discovery-begin` and
  `discovery-finalize` despite an explicit prohibition in its prompt. It
  saved a full ladder (DIRECT_READ, LIGHTPANDA, CHROME all `FAILED`) and
  a `SITE_BLOCKING` fact for `sky-news/read-article`, recorded
  2026-09-28T22:25:17Z. The existing alternatives do not fit:
  - The write-freeze marker is root-wide, has no public command, flips
    `readiness` to `NOT_READY`, and does not stop `discovery-begin`
    (verified on a scratch copy: a run opened on a frozen root).
  - A read-only Knowledge Root avoids writes: `preflight` stays `READY`,
    lookup works, and `discovery-begin` refuses. But `SKILL.md:60` then
    says to stop, so an unknown capability is never fetched at all.
- **Browser processes outlive the call.** SKILL.md requires a named
  `--session` but never says to close it. With agent-browser 0.33.0:
  - the daemon detaches into its own process session and is re-parented
    to init;
  - Lightpanda runs as `serve --timeout 604800`;
  - `AGENT_BROWSER_IDLE_TIMEOUT_MS` is off by default.
- **Blocks are saved by design.** The failure-class table says
  `SITE_BLOCKING → record constraint`, and says to enter bounded
  Discovery for `TARGET_CHANGED` and `UNKNOWN`. Saved blocks apply to one
  capability only: `sky-news` already had a saved block on
  `rss-feed-audit`, but `read-article` was still investigated.
- **The model picks transport identity.** On about half of its direct
  reads, the probe's model set a generic Chrome User-Agent without being
  asked. No identity change after a block was observed.
- **PATH lookup is implicit.** `preflight` resolves agent-browser,
  Lightpanda and Chrome by name on PATH (`shutil.which`). The daemon then
  finds Lightpanda through the PATH it inherits. With a minimal
  `PATH=/usr/bin:/bin`, `preflight` reports `BROWSER_CONTROL_MISSING`.

## Contract tensions

Each item: where the change strains the existing contract, and how this
plan resolves it (or why it is an owner decision).

1. **Discovery authorization prose** (`SKILL.md:44`, `:56`, `:58`, `:60`).
   Discovery depends on "if the caller authorizes it", and that
   authorization lives in the prompt, which a model can misread.
   **Resolution**: the process environment becomes a second, stronger
   channel. When lookup reports `learning: DISABLED`, Discovery is not
   authorized, whatever the prompt says, and the runtime refuses it
   anyway. The prompt-based rule stays as it is for learning-enabled
   calls.

2. **"Discovery executes and delivers the caller's actual task while it
   learns"** (`references/transport-and-modes.md:11`). Today this is the
   only defined way to serve an unknown capability. The sentence is
   pinned by
   `tests/test_discovery_enforcement.py::test_discovery_delivers_the_real_task_not_a_dry_run`.
   **Resolution**: keep the sentence, which stays true with learning
   enabled. Add one mode-scoped sentence after it. The pinned test is
   untouched.

3. **Unknown capability without Discovery.** The step-3 table sends
   `UNKNOWN`, absent and contradicted capabilities to Discovery; with no
   authorization, the contract is silent. **Resolution**: a new step-3
   rule defines the learning-disabled outcome as bounded direct work
   under the existing steps 4–6. No new mode name is introduced; it is
   the direct work that the step-5 "Stopping rules for direct work"
   already govern.

4. **Failure-class table and "record"**
   (`references/transport-and-modes.md:98-113`, `SKILL.md:64` "a
   constraint to record", `references/safety.md:74` "record as a target
   constraint and stop"). `SITE_BLOCKING → record constraint`;
   `TARGET_CHANGED`, `PROFILE_INCORRECT` and `UNKNOWN` lead to Discovery.
   **Resolution**: one note under the table. With learning disabled,
   every action that records, degrades or enters Discovery becomes
   "report the class and stop". "Record" in `SKILL.md:64` and
   `safety.md:74` then means reporting the block in the answer. Nothing
   else in the table changes. Reusing an accepted blocking fact
   (`SKILL.md:55`) is a read, so it still applies.

5. **Readiness semantics.** `READY` means "the core Knowledge Root and
   Operational Memory are usable" (`references/external-dependencies.md`),
   and `SKILL.md:44` ties readiness to "the write path". **Resolution**:
   `READY` keeps meaning the installation is healthy. Learning is a
   separate field, never an error, and never changes `status`.
   `readiness.py` is not touched, so lookup's `readiness` value is
   computed exactly as today.
   - An *uninitialized* root under learning-disabled mode: `First run`
     calls `init-knowledge-root`, which now refuses. `preflight` is then
     still not `READY`, and `SKILL.md:21-22` already says to stop and
     report the blocker. This is OD-3.

6. **Write-freeze marker.** Both are "no writes" states, so reusing the
   freeze is tempting. **Resolution**: keep them separate.
   - The freeze is persistent, root-wide installation maintenance state:
     it makes the root `NOT_READY` and has no public switch.
   - Learning mode is per process, chosen by the caller, and leaves the
     root `READY`.
   - Both are checked in `write_transaction`, learning first, so a call
     with both reports `LEARNING_DISABLED` deterministically.
   - The freeze's gaps (it does not gate `discovery-begin`; a frozen
     finalize prints an uncoded refusal) are recorded in the backlog, not
     fixed here.

7. **`knowledge-resolve` and root creation.** Rejecting a pending
   Candidate is curation, not learning, and creating a root is
   installation. The variable is named `CARAVELAWEB_LEARNING`, but
   acceptance criterion A needs "no supported path writes to the
   Knowledge Root". **Resolution**: the documented meaning of `disabled`
   is "no public command writes to the Knowledge Root", so both refuse.
   The name stays as agreed.

8. **Existing authority concepts.** There are three, and the new mode is
   none of them:
   - `read_authority.py` and `write_authority.py` hold installation-owned
     markers. They record *which store is authoritative* (`LEGACY` versus
     `OPERATIONAL_MEMORY`), not whether a caller may write.
   - Caller authority in `references/safety.md` is web-action authority
     (`READ`, `NAVIGATE`, …).
   - `references/target-profile.md:152` says local Operational Memory "is
     writable by the installation's normal policy and is separate from
     web-action authority".

   **Resolution**: the new mode is a third, per-call dimension, a
   caller's knowledge-write permission. It is not implemented as a
   write-authority state: that would persist, apply to the whole root,
   and make `current_write_authority` report `LEGACY`, which is false.
   `target-profile.md:152` gets one clause naming the caller's per-call
   override.

9. **Pending Candidates and open runs.** `SKILL.md:44` tells the model to
   enrich a pending Candidate or discard it with `knowledge-resolve`.
   **Resolution**: the new step-3 rule says to leave open runs and
   pending Candidates untouched in this mode. They stay visible in
   lookup output, which is a read.

10. **Finalize refusal shape.** Every finalize refusal prints
    `"run_state": "OPEN"` (`scripts/discovery-finalize:171-183`). Under
    this mode, no run was touched and often none exists. **Resolution**:
    keep the existing shape, where `OPEN` means "this call closed
    nothing"; adding a new `run_state` value would change the public
    vocabulary for a call the model should never make.

11. **Browser session reuse** (`SKILL.md:80`: "A bounded workflow may
    reuse its own session"). **Resolution**: a session is closed when its
    workflow ends, not between that workflow's steps. The two rules
    compose.

12. **Transport identity.** `SKILL.md:65` says "The model provider does
    not define the transport's HTTP identity", but no rule says who does,
    and the probe's model chose one itself. Two further points:
    - WebFetch-style host fetch tools carry an identity set by the host,
      not by the model or CaravelaWeb.
    - `transport-and-modes.md` (bot-protection decision rule, around line
      121) deliberately escalates a 403 challenge to a browser, whose
      engine has a different identity.

    **Resolution**: see OD-1. Whatever the default, ladder escalation
    with each transport's *own* default identity is the defined
    progression, not an identity change. Changing identity *within* a
    transport after a block is circumvention.

13. **Unrecognized values fail open.** The agreed rule is that anything
    other than `disabled` means enabled, so a caller who writes
    `CARAVELAWEB_LEARNING=off` silently gets learning. This is OD-2.

14. **SKILL.md line budget.** `SKILL_LINE_BUDGET = 151`
    (`tests/test_discovery_enforcement.py:22`); SKILL.md is 144 lines.
    Changes 2–4 add about four lines. **Resolution**: fit within 151; if
    not, STOP (raising the budget is an owner decision, as each earlier
    raise was).

15. **The guarantee's limit.** The mode is enforced in code at every
    supported write path, and the environment variable is inherited by
    every shell command the model runs, so no model cooperation is
    needed. But a model with shell access can still:
    - clear the variable in its own command
      (`env -u CARAVELAWEB_LEARNING …`), or
    - write to the SQLite file or the marker directory with `sqlite3`,
      Python or the shell.

    CaravelaWeb cannot prevent that without OS-level enforcement, and this
    plan adds none. The honest statement, written into
    `docs/installation.md`: the mode is a hard guarantee for every public
    CaravelaWeb command, and a model that deliberately bypasses those
    commands is outside it. A caller can *detect* a bypass cheaply by
    hashing the Knowledge Root before and after the call, which is the
    same check change 6 performs.

## Owner decisions

**Answered by the owner on 2026-09-28:**

- **OD-1: option (a).** Each transport uses its own default identity. The
  model never sets or changes User-Agent or other identity headers. A
  caller-supplied identity in the task is used from the first request and
  never changed. Moving up the ladder with each transport's own default
  identity is not an identity change. Changing identity within a transport
  after a block is circumvention and ends the run as a block. This applies
  with learning enabled and disabled. WebFetch: allowed under (a) in
  general; it is not relevant to Disperta, whose calls allow only `Skill`
  and `Bash`.
- **OD-2: recommendation accepted.** The value is read case-insensitively
  after trimming whitespace. `preflight` warns about an unrecognized
  non-empty value, and learning stays `ENABLED`.
- **OD-3: recommendation accepted.** Stop, as today: root creation is
  refused, `preflight` is not `READY`, and the executor reports the
  blocker. Callers set up their root outside acquisition calls.

The options as they were presented:

- **OD-1 — Default transport identity (blocks change 4).** Which
  User-Agent and identity headers does each transport use, and may the
  model choose them?
  - **(a) Recommended**: each transport's own default. The model never
    sets or changes identity; a caller-supplied identity in the task (the
    "acquisition policy" in `references/safety.md`) is used from the
    first request and never changed.
    - Honest, and consistent with `SKILL.md:65`.
    - Cost: some sites refuse a plain HTTP client's default User-Agent,
      so more reads escalate to Lightpanda or Chrome.
  - **(b)** One fixed, self-identifying User-Agent declared by the
    contract (for example `CaravelaWeb/<version> (+<repo URL>)`) on
    `DIRECT_READ`. It is transparent, but it makes the model set a
    header on every read, and some sites block unknown bots harder.
  - **(c)** One fixed browser-like User-Agent declared by the contract.
    Fewer 403s on `DIRECT_READ`, but it is impersonation by policy and
    strains `references/safety.md` ("Do not add stealth, evasion, or
    anti-bot bypass behavior").
  - **Sub-question**: is a host fetch tool (WebFetch) an acceptable
    `DIRECT_READ` implementation? Its identity is not the model's to set
    (fine under (a)). It passes page content through a host-side model,
    which matters for change 6's "no Haiku" rule. Recommendation: allowed
    under (a); change 6 disallows it only if it drives a Haiku call (see
    the change 6 STOP conditions).
- **OD-2 — Unrecognized values.** Recommended: treat the value
  case-insensitively after trimming whitespace, so ` Disabled ` disables.
  Any other non-empty value leaves learning enabled, as agreed, but adds a
  `preflight` warning: `CARAVELAWEB_LEARNING=<value> is not recognized;
  learning is ENABLED`. The alternative, failing closed on any non-empty
  value other than `enabled`, would contradict agreed scope item 7.
- **OD-3 — Uninitialized root while learning is disabled.** Recommended:
  stop, as today. Root creation is refused, `preflight` stays not `READY`,
  and the executor reports the blocker. Disperta provisions its root
  outside acquisition calls. The alternative, acquiring with no memory at
  all, would add a new contract path for a state a provisioned caller
  never reaches.

## Current state

### Every write to the Knowledge Root (confirmed at `89f701e`)

Found by grepping the runtime closure (`EXPECTED_RUNTIME_CLOSURE` in
`tests/test_public_runtime_boundary.py:27-41`) plus `scripts/`. The search
covered `write_transaction`, `executescript`, SQL `INSERT`/`UPDATE`/`DELETE`,
`.commit()`, `write_text`, `.mkdir(`, `os.replace`, `.unlink(`, file opens
in modes `w`, `a` or `x`, and `os.open`. Every SQL write in `core.py`
(lines 266–498) sits inside `class _Writer` (lines 257–502). A `_Writer` is
only built by `write_transaction`.

| Write | Location | Reached from | This plan |
| --- | --- | --- | --- |
| Open-run marker creation | `discovery_runs.py:70-75` (`begin_discovery`) | `discovery-begin` | gate |
| Open-run marker removal | `discovery_runs.py:150` (`close_discovery`) | `discovery-finalize` after a closing verdict, including an empty `NOT_SAVED` that never opens a transaction | gate |
| All Operational Memory rows | `operational_memory/core.py:595-606` (`write_transaction`) | `discovery_finalize.py:1745` (also `--validate`, which rolls back); `om_native_writes.py:40` `_write_scope` → capture/replace/enrich/promote/reject → `knowledge-resolve` | gate |
| Database creation | `operational_memory/core.py:531-544` (`_open`, `create=True`: `mkdir` + `executescript`) | `installation_init.py:138` only | gate |
| Root layout and markers | `installation_init.py:127-170` (`initialize_knowledge_root`) | `init-knowledge-root` | gate |
| Freeze marker | `knowledge_write_freeze.py:54-67` (`enable_freeze`, `disable_freeze`) | no public command (tests only) | not public; not gated |
| Authority lock file | `write_authority.py:47-60` (`authority_lock`) | no runtime caller | not reachable; not gated |
| Host skill links | `host_registration.py:84`, `:131` | `register-host` (developer mode, outside the runtime closure) | writes host skill directories, never the Knowledge Root; not gated |

Reads open SQLite read-write (`operational_memory/core.py:539`, reached
from `integration_bridge.py:79` and `:154`) but execute only `SELECT` and
`PRAGMA foreign_keys`. The database uses the default rollback journal (no
WAL pragma anywhere), so a read-only call leaves no bytes behind. `readiness.py`
opens with `mode=ro`. Change 1's hash test proves this.

### Excerpts

`platform_adapter.py:16-19`:

```python
# An advanced, session-scoped override -- e.g. to point at a second
# installation temporarily without disturbing the fixed per-user default.
KNOWLEDGE_ROOT_ENV = "CARAVELAWEB_KNOWLEDGE_ROOT"
```

`operational_memory/core.py:594-606`:

```python
    @contextmanager
    def write_transaction(self) -> Iterator[_Writer]:
        """Start one explicit compound write; any failure rolls back the whole batch."""
        if self.knowledge_root is not None:
            assert_knowledge_writes_allowed(self.knowledge_root)
        try:
            self._conn.execute("BEGIN IMMEDIATE")
```

`discovery_runs.py:49-58` (`begin_discovery` opens with identity checks,
then writes the marker at 70-75 with no authorization check).

`scripts/discovery-finalize:184-192`: any exception that is not a
`DiscoveryFinalizationError` or `DiscoveryRunError` prints
`{"status":"NOT_SAVED","run_state":"OPEN","reason":"Discovery could not
be finalized in local Operational Memory."}` with no `reason_code`. A
`KnowledgeWriteFrozenError` lands here today.

`scripts/discovery-begin:32-34`: a refusal prints
`{"status":"NOT_OPEN","reason":...}`, with no `reason_code`.
`scripts/knowledge-resolve:63-75`: prints
`{"status":"NOT_REJECTED","reason":...}`, with no `reason_code`.
`scripts/init-knowledge-root:43-48`: prints
`{"status":"REFUSED","reason":...}`, with no `reason_code`.

`scripts/knowledge-lookup:61-62`: readiness is added only on the combined
`--target` + `--capability` call:

```python
    combined = bool(args.target and args.capability)
    readiness = {"readiness": readiness_status(args.knowledge_root)} if combined else {}
```

`SKILL.md:65`:
> The model provider does not define the transport's HTTP identity; never
> invent a crawler token.

`SKILL.md:80`:
> Every browser workflow uses an explicit isolated session:
> `agent-browser --session <name>`. A bounded workflow may reuse its own
> session; unrelated or concurrent workflows may not share one.

`references/transport-and-modes.md:11`:
> Discovery executes and delivers the caller's actual task while it
> learns — it is not a preparatory or throwaway run before the real work.

`references/transport-and-modes.md:98-113`: the failure-class table
(`SITE_BLOCKING → record constraint; do not bypass`, `TARGET_CHANGED →
… bounded Discovery`, `UNKNOWN → … request bounded Discovery if it
matters`).

`references/transport-and-modes.md:139-164`: "Browser Session Isolation"
(sessions are mandatory, reuse rules, `DIRECT_READ` unaffected). Nothing
about closing a session anywhere in the repository.

`references/external-dependencies.md:17-24`: "Check the shell directly
(`agent-browser --version`) … CaravelaWeb does not wrap, vendor, install,
pin, or track these tools." No statement about which process's PATH
matters.

`references/safety.md:36-45` ("`robots.txt` and Crawler Identity") and
`:72-76` ("Target Blocking"): no rule on User-Agent choice beyond crawler
tokens; "A caller may also supply an acquisition policy".

Upstream facts observed locally (agent-browser 0.33.0, 2026-09-28; used
by changes 3 and 6, not re-verified by tests):

- `agent-browser close --session <name>` exits 0 even for a session that
  was never opened, so an unconditional close is safe.
- `AGENT_BROWSER_NAMESPACE` scopes `close --all`: closing namespace A left
  namespace B's session running.
- The daemon's environment carries `AGENT_BROWSER_NAMESPACE` and
  `AGENT_BROWSER_SESSION`.
- `AGENT_BROWSER_IDLE_TIMEOUT_MS` is "disabled by default" (`agent-browser
  --help`).

## Commands you will need

```bash
# Full deterministic suite. Unset the variable: most CLI tests inherit
# os.environ, so an exported CARAVELAWEB_LEARNING=disabled would fail them.
env -u CARAVELAWEB_LEARNING python3 -m unittest discover -s tests -p 'test_*.py'
# Baseline at 89f701e: "Ran 386 tests ... OK".

# One module
env -u CARAVELAWEB_LEARNING python3 -m unittest tests.test_learning_disabled -v

# Scratch copy for any manual check (never the real root)
S=$(mktemp -d) && cp -a ~/.local/share/caravelaweb/knowledge-root "$S/kr"
export CARAVELAWEB_KNOWLEDGE_ROOT="$S/kr"

# Tree hash of a root
( cd "$S/kr" && find . -type f -print0 | sort -z | xargs -0 sha256sum ) | sha256sum
```

## Scope

**In scope** (the only files an executor may touch):

- Runtime: `platform_adapter.py`, `discovery_runs.py`,
  `operational_memory/core.py`, `installation_init.py`,
  `scripts/discovery-begin`, `scripts/discovery-finalize`,
  `scripts/knowledge-resolve`, `scripts/init-knowledge-root`,
  `scripts/knowledge-lookup`, `scripts/preflight`
- Contract and docs: `SKILL.md`, `references/transport-and-modes.md`,
  `references/safety.md`, `references/target-profile.md`,
  `references/external-dependencies.md`, `docs/installation.md`,
  `CHANGELOG.md`
- Tests: `tests/test_learning_disabled.py` (new),
  `tests/test_discovery_enforcement.py` (new test methods only)
- `plans/010-learning-disabled-bounded-acquisition.md` (status section
  only) and `plans/README.md` (status row only)

**Out of scope**: guaranteed post-call cleanup after a caller kills a
call; the caller's PATH; plugin-dir location or versioning; any SDK, HTTP
service, or Disperta-specific code; any change to Discovery,
Operational Memory schema, the transport ladder, `readiness.py`, the
write-freeze semantics, or the thin skill adapters. Do not touch the real
Knowledge Root, its `sky-news/read-article` entry, or its three abandoned
open runs.

## Git workflow

Work on a branch from `main` (`git switch -c learning-disabled-mode`).
One commit per change 1–5 in order; change 6 records results in this
plan's status section and commits that alone. No merge, tag, or release.

## Steps

### Change 1: `CARAVELAWEB_LEARNING=disabled` enforced at every write path

**Step 1.1 — the reader.** In `platform_adapter.py`, below
`KNOWLEDGE_ROOT_ENV`:

```python
# A per-process caller choice: "disabled" means no public command writes to
# the Knowledge Root in this process. Session-scoped like the root override.
LEARNING_ENV = "CARAVELAWEB_LEARNING"
LEARNING_DISABLED = "LEARNING_DISABLED"  # reason_code on every refusal


class LearningDisabledError(RuntimeError):
    """The caller disabled Knowledge Root writes for this process."""


def learning_mode(environ: Mapping[str, str] | None = None) -> str:
    """"DISABLED" when the variable says so (OD-2 normalization), else "ENABLED"."""


def assert_learning_enabled(environ: Mapping[str, str] | None = None) -> None:
    """Raise LearningDisabledError naming LEARNING_ENV when learning is DISABLED."""
```

Add the new names to `__all__`. Keep the logic in `platform_adapter.py`
so the runtime closure gains no module
(`EXPECTED_RUNTIME_CLOSURE` stays unchanged).

**Verify**: `env CARAVELAWEB_LEARNING=disabled python3 -c "import platform_adapter as p; print(p.learning_mode())"` → `DISABLED`; without the variable → `ENABLED`.

**Step 1.2 — library gates** (defense in depth for Python callers):

- `discovery_runs.begin_discovery` and `close_discovery`: call
  `assert_learning_enabled()` first. Re-raise as
  `DiscoveryRunError(str(exc))`, keeping `LearningDisabledError` as
  `__cause__` so the CLIs can map it to the coded refusal.
- `SQLiteOperationalMemory.write_transaction`: call
  `assert_learning_enabled()` before the freeze check (tension 6), so the
  learning refusal wins when both apply.
- `SQLiteOperationalMemory._open`: when `create` is true and the file does
  not exist, call `assert_learning_enabled()` before `mkdir`.
- `installation_init.initialize_knowledge_root`: call
  `assert_learning_enabled()` before `assert_initializable`. Raise it as
  is; the CLI maps it.

**Step 1.3 — coded CLI refusals.** Each script checks
`learning_mode()` immediately after `parse_args()`, before resolving a
root or reading input, so the reason code never depends on payload or run
state:

| Script | Output (stderr unless noted) | Exit |
| --- | --- | --- |
| `discovery-begin` | `{"status":"NOT_OPEN","reason":…,"reason_code":"LEARNING_DISABLED"}` | 2 |
| `discovery-finalize` (also `--validate`) | `{"status":"NOT_SAVED","run_state":"OPEN","reason":…,"reason_code":"LEARNING_DISABLED"}` | 2 |
| `knowledge-resolve` | `{"status":"NOT_REJECTED","reason":…,"reason_code":"LEARNING_DISABLED"}` | 2 |
| `init-knowledge-root --json` | stdout `{"status":"REFUSED","reason":…,"reason_code":"LEARNING_DISABLED"}`; text mode prints `status: REFUSED` and `reason_code: LEARNING_DISABLED` | 2 |

The `reason` names the variable: `knowledge writes are disabled for this
process by CARAVELAWEB_LEARNING=disabled`. Also add an explicit
`except LearningDisabledError` (or a `DiscoveryRunError` whose
`__cause__` is one) ahead of the generic branch in
`scripts/discovery-finalize`. Other refusals keep their current shape.
Do not add `reason_code` to them; that would change learning-enabled
output (item 7).

**Step 1.4 — reporting.**

- `scripts/knowledge-lookup`: when `learning_mode() == "DISABLED"`, add
  `"learning": "DISABLED"` to every `emit(...)` output (found, not_found,
  unresolved, bridge_error, listed). When it is enabled, add nothing, so
  learning-enabled output stays byte-identical.
- `scripts/preflight`: add a top-level `"learning": "ENABLED"|"DISABLED"`
  to the JSON report, a `learning: …` text line after `open_discovery:`,
  and the OD-2 warning for unrecognized values (appended to `warnings`).
  `status` and the exit code do not change. Preflight reports the value
  in both modes, because a caller's deployment check needs to see that
  the variable took effect. The field is additive.
- Do not touch `readiness.py` (tension 5).

**Step 1.5 — docs.** `docs/installation.md`, beside the
`CARAVELAWEB_KNOWLEDGE_ROOT` block:
- the variable and its OD-2 value rule;
- what it refuses (the four commands and their code);
- that lookup and preflight stay `READY`;
- the honest limit from tension 15.

`CHANGELOG.md`: a new `## Unreleased` section with an `### Added` entry.

**Step 1.6 — tests: `tests/test_learning_disabled.py`.** Follow
`tests/test_discovery_runs.py`:
- build a fresh root in a temp directory through `init-knowledge-root`
  with the variable unset;
- run the CLIs with `subprocess.run`, passing an explicit `env` built as
  `{k: v for k, v in os.environ.items() if k != "CARAVELAWEB_LEARNING"}`
  plus the case's own value;
- hash the root with a helper equal to the tree hash above.

Cases:

1. `learning_mode` truth table per OD-2: unset, `""`, `enabled`, `off`
   → `ENABLED`; `disabled`, ` Disabled ` → `DISABLED`.
2. `discovery-begin` refused with `LEARNING_DISABLED`, exit 2, no
   `.caravelaweb/open-discovery/` entry created, root hash unchanged.
3. With learning enabled, open a run. Then, with learning disabled,
   finalize a valid SAVED-shaped payload and separately an
   `"observations": []` payload, and run `--validate`. All three are
   refused with `LEARNING_DISABLED`, the run marker still exists, and the
   root hash is unchanged. The empty payload covers the `close_discovery`
   path that never opens a transaction.
4. `knowledge-resolve --reject-pending <id>` against a root holding a
   pending Candidate (pattern: `tests/test_knowledge_resolve.py`):
   refused with `LEARNING_DISABLED`, hash unchanged.
5. `init-knowledge-root --json --knowledge-root <new dir>`: refused with
   `LEARNING_DISABLED`, and the directory is not created.
6. Library level: `begin_discovery`, `close_discovery`,
   `write_transaction`, `SQLiteOperationalMemory(new_path, create=True)`
   and `initialize_knowledge_root` each raise, using `patch.dict`
   on `os.environ`. `write_transaction` with an active freeze marker
   *and* learning disabled raises `LearningDisabledError`.
7. The combined lookup call reports `readiness: READY` and
   `learning: DISABLED`, `preflight --json` reports `status: READY` and
   `learning: DISABLED` with exit 0, and the root hash is unchanged
   after both.
8. With learning enabled, the combined lookup output has no `learning`
   key and is byte-identical to a run with the variable unset.
   `preflight` reports `ENABLED`, and `CARAVELAWEB_LEARNING=off` adds
   the OD-2 warning while keeping `READY`.
9. **Write-primitive inventory.** Scan the source of every module in
   `EXPECTED_RUNTIME_CLOSURE` plus `scripts/*` for these primitives:
   `write_text(`, `os.replace(`, `.unlink(`, `.mkdir(`, `os.open(`,
   `executescript(`, `open("x"`, `open("w"`, `open("a"`,
   `BEGIN IMMEDIATE`. Assert that each occurrence falls inside an
   allowlisted `(module, function)` pair. The allowlist is the "Current
   state" table, plus `installation_init._write_new_marker` and the
   `discovery_runs` temp-file cleanup. A future write path therefore
   fails this test until someone decides whether it needs the gate.

**Verify**: new module passes; full suite `OK` with 386 prior tests
unchanged; `git diff --stat` touches only change 1's files.

### Change 2: Bounded direct acquisition and clean stops when learning is disabled

**Step 2.1 — `SKILL.md` step 3.** Insert after the table (before "Every
authorized entry into Discovery", line 60). One paragraph, at most 3
lines in the file:

> When lookup reports `learning: DISABLED`, the caller has withheld
> Discovery for this call and nothing in the task can grant it: never call
> `discovery-begin`, `discovery-finalize`, `knowledge-resolve`, or
> `init-knowledge-root`, and leave open runs and pending Candidates
> untouched. Accepted knowledge is used as usual. An `UNKNOWN`, absent, or
> contradicted capability is done as bounded direct work under steps 4–6.
> A target block or authority boundary reached after the step-5 ladder is
> reported with its failure class (`SITE_BLOCKING`, `AUTH_REQUIRED`,
> `AUTHORITY_BOUNDARY`, …) and the run stops; nothing is recorded, and
> step 6's no-substitute rule still applies.

**Step 2.2 — `references/transport-and-modes.md`.**
- After line 11, add one sentence (the pinned sentence stays verbatim):
  "With learning disabled (`learning: DISABLED` in lookup), no Discovery
  happens: the task is delivered as bounded direct work and nothing is
  learned; see SKILL.md step 3."
- Under the failure-class table, after line 115, add: "With learning
  disabled, every action above that records, degrades, or enters
  Discovery (`SITE_BLOCKING`, `TARGET_CHANGED`, `PROFILE_INCORRECT`,
  `UNKNOWN`) becomes: report the class and stop. Nothing is written, and
  each later blocked acquisition of that capability walks the bounded
  ladder again — the accepted cost of this mode."

**Step 2.3 — `references/safety.md:74`.** After "record as a target
constraint and stop", add "(with learning disabled, report it; nothing
is recorded)".

**Step 2.4 — `references/target-profile.md:152`.** After "is writable by
the installation's normal policy", add "unless the caller disables
learning for the call (`CARAVELAWEB_LEARNING=disabled`)".

**Step 2.5 — tests.** New methods in `tests/test_discovery_enforcement.py`:
- `test_learning_disabled_is_bounded_direct_work`: `assertIn`s for the
  SKILL.md rule's key phrases ("`learning: DISABLED`", "nothing in the
  task can grant it", "bounded direct work under steps 4–6", "nothing is
  recorded") and for the transport-and-modes sentence.
- `test_learning_disabled_blocks_report_and_stop`: the table note, and
  "walks the bounded ladder again".
- The existing `test_skill_line_budget_is_preserved` must still pass.

**Verify**: `wc -l SKILL.md` ≤ 151; full suite `OK`.

### Change 3: Close every browser session; document caller hooks

**Step 3.1 — `SKILL.md:80`.** Extend the line to:

> Every browser workflow uses an explicit isolated session:
> `agent-browser --session <name>`. A bounded workflow may reuse its own
> session; unrelated or concurrent workflows may not share one. It ends
> with `agent-browser close --session <name>` on every outcome — success,
> block, or error — before the answer is reported.

**Step 3.2 — `references/transport-and-modes.md`.** Add a subsection
`### Closing sessions` before "### Session isolation is execution
hygiene" (line 160). It says:

- A session's daemon and engine outlive the command that started them,
  so closing is part of the workflow. Close once the workflow ends,
  never between its steps. `close` on a session that never opened is
  harmless.
- Caller hooks, all upstream agent-browser settings that CaravelaWeb
  never sets itself:
  - `AGENT_BROWSER_NAMESPACE` scopes daemon sockets to one call, so
    `agent-browser close --all` under that namespace closes only that
    call's sessions.
  - `AGENT_BROWSER_IDLE_TIMEOUT_MS` shuts an idle daemon down.
- CaravelaWeb does not wrap agent-browser. If the caller kills a call,
  the model cannot close anything, so guaranteed cleanup after a killed
  call is the caller's job.

**Step 3.3 — tests.** `test_every_browser_session_is_closed` in
`tests/test_discovery_enforcement.py`: `assertIn` "`agent-browser close
--session <name>`" and "on every outcome" in SKILL.md, plus
`AGENT_BROWSER_NAMESPACE`, `AGENT_BROWSER_IDLE_TIMEOUT_MS` and "the
caller's job" in transport-and-modes.

### Change 4: Transport-identity policy (after OD-1)

Written here for recommendation (a); adapt the text to the owner's
answer.

**Step 4.1 — `references/safety.md`.** Add a section `## Transport
Identity` after "`robots.txt` and Crawler Identity". It states:

- Identity means User-Agent, client-hint headers (`Sec-CH-UA*`), `From`,
  and any header, flag, launch argument, proxy or profile chosen so the
  request looks like a different client.
- Per transport, by default:
  - `DIRECT_READ` uses the HTTP client's own default identity; a host
    fetch tool's identity is set by the host.
  - `LIGHTPANDA` and `CHROME` use agent-browser's engine defaults.
- The model does not choose or change identity: no `-A`/`User-Agent`
  header, no `--user-agent` or `AGENT_BROWSER_USER_AGENT`, no stealth
  launch arguments such as `--disable-blink-features=AutomationControlled`,
  no `--headed` to avoid headless detection, and no `--proxy`,
  `--profile` or `--auto-connect` to borrow another identity.
- Content negotiation (`Accept`, `Accept-Language`) is not identity.
- A caller-supplied identity (acquisition policy) is used from the first
  request of the run and never changed.
- Moving along the `DIRECT_READ -> LIGHTPANDA -> CHROME` ladder, with each
  transport's own default identity, is not an identity change.
- After a block, changing identity within a transport is circumvention:
  the run ends as that block.

**Step 4.2 — `SKILL.md:65`.** Replace the last clause with "The model
provider does not define the transport's HTTP identity; never invent a
crawler token, and never set or change a transport's identity unless the
caller supplied it — after a block, that is circumvention (see
`references/safety.md`)." (It stays on the same line; no line-count
change.)

**Step 4.3 — tests.** `test_transport_identity_is_never_adjusted` in
`tests/test_discovery_enforcement.py`. It asserts the SKILL.md clause and,
in safety.md, "`--user-agent`", "AutomationControlled" and "is not an
identity change". The existing `tests/test_robots_policy.py` assertions
must still pass unchanged.

### Change 5: PATH clarification in the dependency reference

This belongs in CaravelaWeb because it documents CaravelaWeb's own
detection rule (`preflight`'s `shutil.which`) and the transport it relies
on. Choosing the PATH stays the caller's job.

**Step 5.1 — `references/external-dependencies.md`**, after the "Check
the shell directly" paragraph:

> `agent-browser` and `lightpanda` must resolve on the `PATH` of the
> process that runs the executor's commands — the first `agent-browser`
> command of a session passes that `PATH` to its daemon, which finds
> Lightpanda there — and `preflight --json` reports the resolved paths
> (`transports.agent-browser.path`, `transports.LIGHTPANDA.path`,
> `transports.CHROME.path`).

**Step 5.2 — test.** `test_browser_tools_resolve_on_the_executor_path`
in `tests/test_discovery_enforcement.py`: `assertIn` the sentence's key
phrase and `transports.LIGHTPANDA.path`.

### Change 6: Live acceptance run in the caller's real shape

No code. This produces the evidence for criteria A–H and records it in
this plan's status section.

**Owner amendment (2026-09-28): run it in Disperta's exact call shape.**
Where it differs from the original text below, the amendment wins.

```bash
/home/tarciso/.nvm/versions/node/v24.16.0/bin/claude -p \
  --output-format stream-json --verbose --include-partial-messages \
  --no-session-persistence --setting-sources "" --strict-mcp-config \
  --settings '{"autoMemoryEnabled":false}' --plugin-dir <plugin root under test> \
  --tools "Skill,Bash" --allowedTools "Skill,Bash" \
  --model claude-sonnet-5-5 --effort medium \
  --json-schema '{"type":"object","additionalProperties":false,"required":["status","final_url","path","representation","error"],"properties":{"status":{"type":"string","enum":["ok","failed"]},"final_url":{"type":["string","null"]},"path":{"type":["string","null"]},"representation":{"type":["string","null"],"enum":["html","rendered_dom",null]},"error":{"type":["string","null"]}}}'
```

- The executable is invoked by the absolute path above.
- The prompt goes on stdin. It asks Claude to use the CaravelaWeb skill to
  acquire one URL and write the page file into the working directory,
  with learning disabled. (This replaces "the prompt does not mention
  learning".)
- A fresh, empty working directory per call.
- The environment is only `HOME`, a `PATH` that includes the agent-browser
  and Lightpanda directories, `CARAVELAWEB_LEARNING=disabled`, and
  `CARAVELAWEB_KNOWLEDGE_ROOT=<scratch copy>`; never the real root. (This
  replaces the per-call `AGENT_BROWSER_NAMESPACE`: leftovers are found by
  comparing the process table before and after the call.)
- `<plugin root under test>` must load the modified working tree, not the
  installed plugin (`…/caravelaweb/0.2.2`). Confirm in the transcript that
  the loaded SKILL.md contains the new rules. If the checkout cannot be
  loaded as a plugin directly, STOP and report how it can be.
- Cases:
  - direct: the `requested_url` in
    `/home/tarciso/projects/disperta-scratch/slice1/corpus/guardian-drc-ebola-politician/manifest.json`;
  - rendered: a page that needs a rendered DOM, chosen and justified at
    run time, not Sky;
  - blocked: the `requested_url` in
    `/home/tarciso/projects/disperta-scratch/slice1/corpus/wsj-egypt-warned-netanyahu/manifest.json`;
  - unknown: a host with no capability in the scratch root.
- For each case, record:
  - the scratch root's tree hash before and after;
  - the result envelope and the page file (exists, non-empty, HTML);
  - the failure class on the block;
  - that no `discovery-begin` or `discovery-finalize` ran;
  - the model usage, which must show no Haiku;
  - that no session and no process from the call remain after a normal
    exit.
- Clean up any leftover so the machine ends clean.
- With `--tools` limited to `Skill` and `Bash`, the WebFetch-to-Haiku STOP
  condition should not trigger. If it does, STOP.

**Setup**, per call:

- a fresh scratch copy of the real root, with its pre-call tree hash
  recorded;
- `CARAVELAWEB_LEARNING=disabled`;
- `CARAVELAWEB_KNOWLEDGE_ROOT=<copy>`;
- `AGENT_BROWSER_NAMESPACE=plan010-<case>-<uuid>`, used here to *find*
  leftovers, not to clean them;
- **no** `AGENT_BROWSER_IDLE_TIMEOUT_MS`, which would mask a missing
  close.

**Command shape** (Disperta's):

```bash
claude -p "<acquisition prompt>" --model claude-sonnet-5-5 --effort medium \
  --plugin-dir /home/tarciso/projects/caravelaweb \
  --output-format stream-json --verbose <Disperta's permission flags>
```

- Never pass `--fallback-model`.
- The prompt asks for one article page and does **not** mention
  learning, Discovery, sessions or identity. The contract alone must
  produce the behavior.
- Record the exact command line in the status section.

**Cases** (choose live URLs at run time and record them):

| Case | Selection rule | Expect |
| --- | --- | --- |
| direct | an article whose text is in the server HTML | `DIRECT_READ` success, no browser |
| rendered | an article whose text needs JS (the `DIRECT_READ` body lacks it) | Lightpanda or Chrome success, session closed |
| blocked | a known-blocking host under a capability ID that lookup on the copy answers `not_found` (for example a `sky-news` article with a capability other than `read-article` or `rss-feed-audit`) | ladder walked once, class reported, stop |
| unknown | any target/capability `not_found` in the copy | acquired as direct work, no `discovery-begin` |

Optional fifth case: the accepted `sky-news/read-article` block on the
copy, which should be reused with no transport attempt (`SKILL.md:55`).

**Checks per call** (from the stream-json transcript and the shell):

- **A**:
  - no tool call ran `discovery-begin`, `discovery-finalize`,
    `knowledge-resolve` or `init-knowledge-root`, or any it ran was
    refused with `LEARNING_DISABLED`;
  - the copy's tree hash is unchanged after the call.
- **B**: the first lookup result in the transcript carries
  `readiness: READY` and `learning: DISABLED`.
- **C**: the unknown and direct cases return the page content.
- **D**: the blocked case reports a failure class. There is no web-search
  or fetch call to another host, no retry with changed identity, and the
  hash is unchanged.
- **E**:
  - after `claude -p` exits 0,
    `AGENT_BROWSER_NAMESPACE=<ns> agent-browser session list` prints no
    active session;
  - no process whose `/proc/<pid>/environ` carries that namespace
    remains (`agent-browser`, `lightpanda`, `chrome`/`chromium`);
  - every `agent-browser` command in the transcript that opened a
    session is followed by `close --session <same name>`.
- **F**: no tool input contains `User-Agent`, `-A `, `--user-agent`,
  `AGENT_BROWSER_USER_AGENT`, `AutomationControlled` or `--proxy`, unless
  the prompt supplied an identity.
- **H**: the init event's model is `claude-sonnet-5-5`, and
  `modelUsage` in the result event lists no Haiku model.

**G** (learning enabled unchanged): repeat the **unknown** case once more
on its own copy, with the variable unset and a prompt that authorizes
Discovery. `discovery-begin` and `discovery-finalize` must run as today,
and the copy's hash *changes*.

After each case, if a leftover process was found, close its namespace
(`AGENT_BROWSER_NAMESPACE=<ns> agent-browser close --all`) so the machine
is clean. Record the leftover as an E failure. Delete the scratch copies
at the end.

## Test plan

- `tests/test_learning_disabled.py`: nine cases (change 1), covering
  every row of the write table, both reporting surfaces, the enabled-mode
  identity of output, and the write-primitive inventory.
- `tests/test_discovery_enforcement.py`: five new contract tests
  (changes 2–5); the line-budget test and every existing assertion are
  unchanged.
- No existing test is expected to change. The only test that pins
  wording near these edits is
  `test_discovery_delivers_the_real_task_not_a_dry_run`, and this plan
  keeps its sentence verbatim. The others near these edits,
  `test_skill_line_budget_is_preserved` and
  `tests/test_robots_policy.py`, stay green without edits. If any
  existing test needs editing, that is a STOP.
- Live: change 6's four required cases plus the G control.

## Done criteria (caller guarantees)

- [ ] **A** — `tests/test_learning_disabled.py` cases 2–6 and 9 pass; change 6 shows no refused-or-not write command succeeding and an unchanged copy hash for every disabled-mode case.
- [ ] **B** — cases 7–8 pass; change 6's first lookup shows `READY` + `DISABLED`.
- [ ] **C** — change 6 "unknown" and "direct" return the page with no `discovery-begin` in the transcript.
- [ ] **D** — change 6 "blocked" reports a failure class, stops, no fallback call, no identity change, hash unchanged; change 2 tests pass.
- [ ] **E** — change 3 test passes; change 6 finds no session and no process in the call's namespace after a normal exit, for all cases.
- [ ] **F** — change 4 test passes (after OD-1); change 6 transcripts contain none of the identity markers.
- [ ] **G** — `env -u CARAVELAWEB_LEARNING python3 -m unittest discover -s tests -p 'test_*.py'` exits 0 with the 386 prior tests unchanged; the change 6 control learns as today.
- [ ] **H** — change 6 ran on `claude-sonnet-5-5`, effort medium, headless, on scratch copies, with no Haiku in `modelUsage`.
- [ ] `wc -l SKILL.md` ≤ 151; `git diff --check` prints nothing; `git status` shows only in-scope files.
- [ ] `plans/README.md` row updated.

## STOP conditions

Stop and report back (do not improvise) if:

- OD-1 is unanswered when change 4 is reached (changes 1–3 and 5 may
  still land).
- Any write path is found that is missing from the "Current state"
  table, or the inventory test in case 9 flags an occurrence the table
  does not explain.
- Gating `_open(create=True)` or `write_transaction` breaks any existing
  test (it means a learning-enabled path reads the variable incorrectly).
- An existing test needs editing, or SKILL.md cannot stay ≤ 151 lines.
- Change 6: the first lookup does not show `learning: DISABLED`. The
  environment did not reach the model's shell; report how Claude Code
  passed it, and do not work around it.
- Change 6: any Haiku model appears in `modelUsage`, or the init event
  names another model. Report which tool drove it, and do not rerun until
  the owner decides (for example, disallowing WebFetch).
- Change 6: the copy's hash changes in disabled mode. Keep the copy and
  the transcript, and report which command wrote.
- Change 6: a disabled-mode call calls `discovery-begin` at all, even
  though it is refused. Record it: the runtime held, but the contract
  text did not steer the model. Report before any wording change.
- Any step would touch the real Knowledge Root.

## Maintenance notes

- The mode is a process-environment contract. New scripts that write to
  the Knowledge Root must check `learning_mode()` first. The case 9
  inventory test enforces this for the runtime closure.
- Reviewers: check that no learning-enabled output changed (case 8), and
  that the finalize generic branch can no longer swallow
  `LearningDisabledError`.
- E is a contract-level guarantee: it holds when the model follows
  SKILL.md and the call ends normally. A call that hits a turn limit, or
  is killed mid-browse, leaves the session to the caller's namespace
  sweep. That is the caller's job by agreement, and this plan documents
  the hooks.

## Backlog (found, vetted, not planned here)

- **DEBT-07** The write-freeze marker does not gate `discovery-begin`, and a
  frozen finalize falls into the uncoded generic `NOT_SAVED` branch
  (`scripts/discovery-finalize:184-192`). The same class as the 2026-09-04
  uncoded refusals. Effort S.
- **DEBT-08** `discovery-begin`, `knowledge-resolve` and
  `init-knowledge-root` refusals carry no `reason_code` outside this
  plan's new code. Effort S; changes learning-enabled output, so it needs
  its own plan.
