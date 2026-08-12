# Changelog

All notable changes to CaravelaWeb will be documented in this file.

The project has not established a numbered public release. Entries accumulate
under **Unreleased** until a version and tag are intentionally chosen.

## Unreleased

### Added

- Repository-root skill with four command-line entry points.
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
- `scripts/register-host --host claude`: one-time global registration of the
  canonical checkout with Claude Code's per-user skill directory (a symlink
  on Linux/macOS/WSL2, a junction on native Windows), so CaravelaWeb is
  usable from unrelated repositories. Codex and OpenCode global registration
  is not yet implemented.
- Claude Code plugin distribution: `.claude-plugin/marketplace.json` publishes
  the repository root as the `caravelaweb` plugin, and
  `.claude-plugin/plugin.json` names it. The public install is
  `/plugin marketplace add tarcisomorais/caravelaweb` followed by
  `/plugin install caravelaweb@caravelaweb`, identical on Windows, Linux,
  WSL2, and macOS, with no symlink, junction, or `PATH` change.
- A **First run** section in `SKILL.md`: the executor runs `preflight` and, if
  no Knowledge Root resolves, `init-knowledge-root`, so neither is a user
  setup step. A `knowledge-lookup` result of `unresolved` now retries once
  after that sequence instead of stopping immediately.

### Changed

- The plugin manifest declares no `version`, so Claude Code versions the plugin
  by source commit until a numbered release policy is chosen.
- `<skill>` in the contract is defined as the skill root for any host: the
  cached plugin directory (`${CLAUDE_PLUGIN_ROOT}`) when installed as a Claude
  Code plugin, and the repository root from a checkout or a link to one. No
  runtime path became host-specific.
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
