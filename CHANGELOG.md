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
- Project-local agent-host onboarding: `AGENTS.md`, a `CLAUDE.md` that imports
  it, and thin `caravelaweb` skill-discovery adapters under `.claude/skills/`
  and `.agents/skills/`. A fresh clone is discoverable by Claude Code, Codex,
  and OpenCode with no user-home installation, symlink, or junction.

### Changed

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
