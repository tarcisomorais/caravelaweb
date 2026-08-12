@AGENTS.md

## Claude Code

Use the `caravelaweb` skill for web tasks. From an unrelated project, this
requires a one-time global registration:
`python3 <checkout>/scripts/register-host --host claude --json`. Opened
directly in this checkout, `.claude/skills/caravelaweb/` is discovered with no
registration step. Either way the repository-root `SKILL.md` stays the
canonical contract, and the runtime always resolves from the repository root.
