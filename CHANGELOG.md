# Changelog

All notable changes to CaravelaWeb will be documented in this file.

## Unreleased

### Changed

- The payload examples in `references/discovery-payload-examples.md` no
  longer carry `recorded_at`, so an agent that copies an example lets the
  finalizer stamp the write instant instead of stamping one itself. The
  field stays supported and its rule now reads the same in the payload
  reference and in `references/target-profile.md`: supply it only to
  record a different write instant on purpose, with a value at or before
  the current time. Runtime validation is unchanged -- a future
  `recorded_at` and a malformed one are still refused with
  `PAYLOAD_VALUE`.

## 0.2.1 - 2026-09-04

Cheaper Discovery finalization: a checklist in the contract for the four
payload traps that caused most refusals, and a reason code on every
refusal the finalizer decides, including the two that used to print the
generic message.

### Added

- SKILL.md step 7 carries a "Before you finalize" checklist covering the
  host literal, evidence scope and kind, the transport ladder, the
  validation block on OBSERVED blocking and limitation observations, and
  field path forms; the same list sits above example 1 of the payload
  reference. `--validate` stays optional and the contract now says when it
  pays: a payload with a `transport_trace`, a contradiction, or a
  replacement of accepted knowledge, where a terminal `NOT_SAVED` would
  close the run.

### Changed

- `discovery-finalize` reports a `reason_code` on every refusal it decides
  from the payload, the run marker, the Knowledge Root, or the state of the
  Operational Memory database, from a closed list of eleven: the eight
  payload codes of 0.2.0 plus `RUN_MARKER`, `KNOWLEDGE_ROOT_UNRESOLVED` and
  `OPERATIONAL_MEMORY_UNAVAILABLE`. An unresolved Knowledge Root used to fall
  through to the generic handler and print a refusal with no code at all;
  it now names the condition and how to repair it. `PAYLOAD_INVALID` is
  gone: `DiscoveryFinalizationError` no longer has a default code, so no
  refusal it raises can carry an unclassified one.
- Two more `discovery-finalize` refusals carry a code instead of the
  generic "Discovery could not be finalized in local Operational Memory."
  A `recorded_at` later than the current time is refused with
  `PAYLOAD_VALUE` before any write, so `--validate` reports it too; it used
  to be stored and then fail promotion, because a Proposal recorded in the
  future is invisible at knowledge time to its own write. An Operational
  Memory database that is locked by another process, unreadable, or not
  writable is refused with the new `OPERATIONAL_MEMORY_UNAVAILABLE`, which
  names the SQLite condition and not the database path. A malformed
  `recorded_at` now reports `PAYLOAD_VALUE` with the validator's own
  message.
- `init-knowledge-root` resolves where to initialize the same way every
  other command resolves where to read: `--knowledge-root`, then
  `CARAVELAWEB_KNOWLEDGE_ROOT`, then the fixed per-user default. With the
  environment variable set, it used to initialize the default location and
  then refuse a second run against it. The output now names which of the
  three sources was used, and `default_location` in `--json` output is true
  only for the per-user default.

## 0.2.0 - 2026-09-03

Visibility and repair for the two silent failures found in real use: a
pending Candidate that blocks every later write for its capability, and an
`OPERATIONAL` lifecycle that no capability had earned and no output
explained.

### Added

- `scripts/knowledge-resolve --reject-pending <proposal_id> --reason <text>`:
  records a `REJECT` Decision for one pending Candidate, so a stuck pending
  Proposal no longer blocks every later write for its capability. Nothing is
  deleted; the Proposal and its Claims stay as history.
- `scripts/knowledge-lookup --list`: an exact index of every target with its
  hosts and capability keys, and per capability whether accepted knowledge
  exists, how many Proposals are pending, and whether it is `OPERATIONAL`.
  Identity only: no Claim values, no fuzzy or prefix matching. The contract
  now asks for one `--list` call per task before minting a target or
  capability ID.
- `pending_candidates` on `knowledge-lookup` output, for a capability and
  for a target whose only knowledge is pending, mapping each Proposal ID to
  its families and values.
- `lifecycle` on every `SAVED` and `ALREADY_EXISTS` finalization and on a
  capability-scoped lookup: `OPERATIONAL`, or `null` with a `lifecycle_gap`
  code naming the first unmet proof condition, such as
  `NO_AUTHENTICATION_CLAIM`, `PROOF_VALIDATION_NOT_SUCCESS`, or
  `NO_FUNCTIONAL_TRANSPORT_CLAIM`. `SKILL.md` states the three conditions in
  one place, and example 8 in `references/discovery-payload-examples.md`
  earns `OPERATIONAL` in a single run.
- `reason_code` on every `discovery-finalize` payload refusal, from a closed
  list of eight: `PAYLOAD_SHAPE`, `PAYLOAD_VALUE`, `TASK_DATA_REJECTED`,
  `HOST_SCOPE`, `EVIDENCE_LINKAGE`, `PROVENANCE`, `TRANSPORT_TRACE`, and
  `TARGET_REFERENCE`. A refusal for a closed set lists the accepted values.
- `warnings` on a `SAVED` or `ALREADY_EXISTS` finalization, present only
  when non-empty. `NO_HOST_ASSOCIATION` reports a target saved without any
  host, which a later lookup by URL cannot find.
- `preflight` reports an invocation for every skill script, including
  `init-knowledge-root` and `knowledge-resolve`, in JSON and text output.

### Changed

- A `CONFLICT_OR_AMBIGUITY` refusal names the conflicting Claims: source
  (`payload`, `accepted`, or `pending`), Claim ID, family, host, and value,
  up to ten conflicts.
- Evidence locator hostnames are compared with `observation.host` in
  canonical ASCII (IDNA) form, so a Unicode locator matches its punycode
  host. The `www.` rule is unchanged and now documented: target-reference
  resolution drops `www.`, host scope does not.
- Every payload example records its host with `TARGET_SURFACE` evidence.
- `docs/architecture.md` lists six entry points and the full runtime import
  closure; a test keeps the page and the runtime boundary in step. The
  installation page describes the shared manifest version, and README and
  installation note that macOS is not validated by CI.

### Fixed

- Timestamps must round-trip to the canonical `YYYY-MM-DDTHH:MM:SSZ` form;
  a naive or non-canonical value is refused instead of stored.
- A hostname whose labels are all numeric or hexadecimal is treated as an IP
  literal and refused as a public hostname.
- Discovery run markers and the write-authority marker are refused by a
  path check before the open and read through a checked descriptor after
  it, so a symlink at the marker path cannot redirect the read outside the
  Knowledge Root on any platform, including Windows, which has no
  `O_NOFOLLOW`.

## 0.1.0 - 2026-08-26

The first public release.

### Added

- Repository-root skill with five command-line entry points.
- Local SQLite Operational Memory with fail-closed read/write authority.
- Fresh Knowledge Root initialization and deterministic root resolution.
- Capability-scoped `DIRECT_READ -> LIGHTPANDA -> CHROME` transport policy.
- Bounded Discovery finalization with task-data rejection.
- Linux and native-Windows continuous integration.
- Public installation, architecture, platform, security, and contribution
  documentation.
- Checkout-local agent-host onboarding: `AGENTS.md`, a `CLAUDE.md` that
  imports it, and thin `caravelaweb` skill-discovery adapters under
  `.claude/skills/` and `.agents/skills/`. A host opened directly in a fresh
  clone discovers CaravelaWeb with no registration step.
- `scripts/register-host --host claude|codex|opencode`: one-time global
  registration of the canonical checkout with each host's documented per-user
  skill directory (a symlink on Linux/macOS/WSL2, a junction on native
  Windows), so CaravelaWeb is usable from unrelated repositories. Codex's
  native plugin distribution remains available separately.
- Claude Code plugin distribution: `.claude-plugin/marketplace.json` publishes
  the repository root as the `caravelaweb` plugin, and
  `.claude-plugin/plugin.json` names it. The public install is
  `/plugin marketplace add tarcisomorais/caravelaweb` followed by
  `/plugin install caravelaweb@caravelaweb`, identical on Windows, Linux,
  WSL2, and macOS, with no symlink, junction, or `PATH` change.
- Native Codex plugin distribution: `.agents/plugins/marketplace.json`
  publishes the repository root and `.codex-plugin/plugin.json` exposes the
  shared `skills/caravelaweb/` adapter. Codex CLI 0.147.0 and newer
  install it globally with `codex plugin marketplace add` followed by
  `codex plugin add`, without a symlink or duplicated runtime.
- One shared `skills/caravelaweb/SKILL.md` plugin adapter for Codex and Claude
  plugin installs. The root `SKILL.md` remains the only canonical contract;
  `.agents/skills/` and `.claude/skills/` remain checkout-local adapters.
- A **First run** section in `SKILL.md`: the executor runs `preflight` and, if
  no Knowledge Root resolves, `init-knowledge-root`, so neither is a user
  setup step. A `knowledge-lookup` result of `unresolved` now retries once
  after that sequence instead of stopping immediately.
- `run_state` (`"OPEN"` or `"CLOSED"`) on every `scripts/discovery-finalize`
  response, so a caller no longer infers marker state from the exit code,
  output stream, status, or reason code. `TRANSPORT_POLICY_UNPROVEN` and
  `FAILURE_UNCLASSIFIED` now leave the matching run open: a corrected payload
  can be resubmitted under the same `run_id` instead of losing the run.
- `scripts/discovery-finalize --validate --input <discovery.json>`: predicts
  the real finalization result by running the identical write path and
  rolling it back before commit. It never calls `close_discovery` and never
  persists a database or marker change.
- `$.field` explicit-root form for `field_paths` (for example `$.headline`,
  `$.article.full_text`), so a single-record extraction can name a field at
  the root of the record without a synthetic wrapper.
- `references/discovery-payload-examples.md`: complete, copyable
  `discovery.json` payloads for functional `DIRECT_READ`, single-record and
  collection extraction, first-time host association, browser escalation,
  a fully blocked ladder, and an observed limitation constraint. A
  deterministic test finalizes every documented payload for real.

### Fixed

- Registration state on native Windows now recognizes its own junction.
  `os.readlink` reports a junction target with the extended-length prefix
  (`\\?\C:\...`); the unstripped prefix made an equal path compare unequal,
  so a second `register-host` run refused a correct registration as
  `CONFLICT`. Link targets are now compared with the prefix stripped and
  with case-normalized resolved paths, and the registration tests assert
  through the same helper on every platform.
- The CI path gate now matches the root-as-skill layout that the plugin
  distribution introduced: `skills/caravelaweb/SKILL.md` is the one allowed
  nested adapter, and the gate fails when anything else grows under
  `skills/`. The old gate asserted that `skills/` must not exist and had
  failed on every push since the adapter landed.
- Knowledge Root resolution no longer depends on shared mutable state, so
  concurrent sessions on one machine stay independent. `init-knowledge-root`
  used to record every initialized root, including one passed with
  `--knowledge-root`, in a single per-user pointer file. Any session that
  initialized a root therefore silently moved the default of every other
  session, across unrelated projects. Resolution also walked up from the
  running script's own path, which could select the source checkout as a
  Knowledge Root. Both mechanisms are removed: the chain is now
  `--knowledge-root`, then `CARAVELAWEB_KNOWLEDGE_ROOT`, then the fixed
  per-user default location, which is derived and never stored. An explicit
  root is used for that call only and changes nothing for later commands. An
  existing pointer file is ignored, not deleted.
- Discovery now opens a run-scoped local marker before target work. The
  finalizer requires the matching canonical target, capability, and `run_id`;
  every returned verdict closes only that run, while payload or infrastructure
  errors remain visible through lookup and preflight. Run IDs identify
  executions only and never Candidate or Claim identity.
- A fully blocked transport ladder can be finalized. `discovery-finalize`
  required a trace to end at a `FUNCTIONAL` transport, so a capability blocked
  on every transport was rejected with `TRANSPORT_POLICY_UNPROVEN` and the only
  accepted payload was one with the browser observations deleted. A trace now
  ends either at a `FUNCTIONAL` transport or with the ladder exhausted; an
  exhausted ladder saves its block and earns no operational transport. A run
  that stopped while an available transport was untried is still unproven.
- A ladder that reached no working transport must classify why. `FAILED` alone
  does not distinguish a target that blocked the run from a network that
  dropped one request, and `references/transport-and-modes.md` has always
  required classifying before mutating knowledge. `TRANSIENT_NETWORK`,
  `UPSTREAM_TOOL_ERROR`, `LOCAL_ENVIRONMENT`, and `UNKNOWN` now save nothing
  (`FAILURE_UNCLASSIFIED`); `PLATFORM_UNSUPPORTED` was already rejected
  outright.
- Exhausting the transport policy is no longer treated as exhausting the
  ladder. `next_transport` halts at an `UNAVAILABLE` Lightpanda tier even when
  Chrome exists, so a run that never reached Chrome can no longer report the
  capability as blocked.
- An `OBSERVED` `blocking` or `limitation` observation is checked for a
  validation that names a transport and a complete authentication/environment
  context. Every validation field is individually optional, so the previous
  presence-only check accepted `{}` and proved nothing.
- A second target can no longer claim a hostname already associated with
  another target. The write is refused while the caller can still correct it,
  instead of silently creating the collision that made the hostname
  permanently unresolvable. The read-side guard is unchanged.

### Changed

- The Operational-Memory write boundary (`finalize_discovery`,
  `capture_candidate`, `enrich_candidate`, `replace_candidate`,
  `promote_candidate`) no longer accepts `knowledge_write_authority`,
  `write_destination`, or `authority_at_operation` arguments. Write authority
  is derived solely from the real write-authority marker at
  `memory.knowledge_root`; no caller could previously assert or bypass it in
  a way that changed persisted behavior, and the parameters are removed along
  with the synthetic `prop:authority-check` Candidate call that exercised
  them. This is an internal Python API change only -- the CLI flags, output
  contract, and public finalization statuses are unchanged.
- Four validation errors now name the accepted form instead of stating only
  that a value was rejected: a symbolic-value error shows the grammar and an
  example; a rejected schema field path lists the accepted `$.field`,
  dotted, and collection forms; a validation-context error names the
  unsupported keys and lists the accepted ones; a host-evidence mismatch
  reports the claimed Observation Host, the public hostnames found in
  evidence, and the exact `scope`/hostname match it requires.
- A blocked capability is a complete answer. When the ladder is exhausted and
  the result is a target block or an authority boundary, the contract requires
  reporting the block and stopping. Continuing the same investigation through a
  web-search tool, an external index, or a cached or mirrored copy is out of
  scope: none of them is a CaravelaWeb transport. A limited search may still
  locate a route to try; its output is a lead, never evidence about the target.
- An `OBSERVED` `blocking` or `limitation` observation requires a `validation`
  naming the transport and the authentication/environment context that saw it.
  These two families assert a constraint or an absence, so an unvalidated one
  is reported as `INFERRED` rather than stored as accepted fact.
- The host-association rules state which half is machine-checked. The finalizer
  verifies the evidence locator's hostname and refuses a hostname another
  target claims; whether the operator is genuinely the same stays an executor
  judgment, and the references now say so instead of implying enforcement.
- The contract states that the target-only `knowledge-lookup` already returns
  the accepted context of every capability, so the per-capability call confirms
  one exact ID rather than fetching withheld knowledge.
- The Claude plugin manifest declares no `version`, so Claude Code versions it
  by source commit. The Codex manifest uses explicit SemVer, starting at
  `0.1.0`; this change creates no Git tag.
- `<skill>` in the contract is defined as the skill root for any host: the
  cached plugin directory (`${CLAUDE_PLUGIN_ROOT}`) when installed as a Claude
  Code plugin, `../..` from the shared plugin adapter, `../../..` from the
  checkout-local `.agents` adapter, and the repository root otherwise. No path
  resolves from the process working directory.
- `scripts/register-host` is documented as developer tooling rather than the
  install path. Its behavior is unchanged.
- Every tracked file is checked out with LF endings. A CRLF checkout, the Git
  for Windows default, made Claude Code miss the `name:` frontmatter of the
  cloned `SKILL.md` and name the skill after the install directory, so the
  plugin skill was not invocable as `caravelaweb` on native Windows.
- `init-knowledge-root` names the `CARAVELAWEB_KNOWLEDGE_ROOT` environment
  variable instead of printing POSIX `export` syntax, which was wrong on the
  native-Windows shells that now see this output during first run.
- The README leads with the two-command install and a single prerequisite.
  Knowledge Root resolution, runtime command contracts, browser transports,
  and registration moved to the installation documentation.

- Preflight no longer reports the `maintenance_tooling` optional component,
  which the standalone public runtime does not ship.
- The public Discovery finalizer vocabulary is English. Statuses are `SAVED`,
  `ALREADY_EXISTS`, and `NOT_SAVED`; refusal output uses the `reason` and
  `reason_code` keys; reason codes are English `UPPER_SNAKE_CASE`. Semantics,
  acceptance criteria, and authority behavior are unchanged. This normalization
  lands before the first public release, so no released contract is broken.

### Security

- Installation-owned Operational Memory and target corpora are excluded from
  repository tracking.
- Authority markers reject unsafe links and reparse points.
