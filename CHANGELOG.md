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
- Discovery finalizer refusal messages are English. The `SALVA`,
  `JÁ_EXISTENTE`, and `NÃO_SALVA` status tokens are unchanged.

### Security

- Installation-owned Operational Memory and target corpora are excluded from
  repository tracking.
- Authority markers reject unsafe links and reparse points.
