@AGENTS.md

## Claude Code

Use the `caravelaweb` skill for web tasks. From an unrelated project, install
the published plugin: `/plugin marketplace add tarcisomorais/caravelaweb`, then
`/plugin install caravelaweb@caravelaweb`. Opened directly in this checkout,
`.claude/skills/caravelaweb/` is discovered with no install step; to load a
live checkout globally instead, use `claude --plugin-dir <checkout>` or
`scripts/register-host`. Every path resolves from the skill root, which the
contract calls `<skill>`, and the repository-root `SKILL.md` stays canonical.
