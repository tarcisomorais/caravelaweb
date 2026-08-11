# CaravelaWeb

[![CI](https://github.com/tarcisomorais/caravelaweb/actions/workflows/ci.yml/badge.svg)](https://github.com/tarcisomorais/caravelaweb/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

CaravelaWeb is a repository-root skill for AI agents that perform web tasks.
It keeps validated, capability-scoped operating knowledge in a local SQLite
Operational Memory and applies a conservative transport order:

```text
DIRECT_READ -> LIGHTPANDA -> CHROME
```

The project is intentionally not a Python package or public SDK. Clone the
repository and use its four command-line entry points directly.

## Requirements

- Python 3.11 or newer, including the standard-library `sqlite3` module
- Linux, WSL2, or native Windows
- Optional browser transports: `agent-browser`, Lightpanda, and Chrome

`DIRECT_READ` has no browser dependency. Missing optional transports do not
prevent initialization or direct-read workflows.

## Quick start

```bash
git clone https://github.com/tarcisomorais/caravelaweb.git
cd caravelaweb
python3 scripts/init-knowledge-root --json
python3 scripts/preflight --json
python3 scripts/knowledge-lookup --target example-site --capability search
```

Examples use `python3`, which is the usual command on Linux and WSL2. On native
Windows, run the same commands with `python` (or `py`) instead:

```powershell
python scripts/init-knowledge-root --json
python scripts/preflight --json
```

Any Python 3.11 or newer works. Use one interpreter for every CaravelaWeb
command; `preflight` reports the exact interpreter path it ran under.

Initialization creates an installation-owned Knowledge Root and remembers it
for later commands. An explicit location is also supported:

```bash
python3 scripts/init-knowledge-root --knowledge-root /path/to/knowledge-root --json
```

Knowledge Root resolution is deterministic:

```text
explicit --knowledge-root
-> CARAVELAWEB_KNOWLEDGE_ROOT
-> remembered root
-> .caravelaweb-knowledge-root marker walk-up
```

A `not_found` lookup means no accepted knowledge exists for that capability.
If the caller authorizes bounded Discovery, follow [SKILL.md](SKILL.md), then
finalize reusable observations with:

```bash
python3 scripts/discovery-finalize --input discovery.json
```

## Commands

| Command | Purpose |
| --- | --- |
| `scripts/init-knowledge-root` | Create an empty local Knowledge Root and Operational Memory. |
| `scripts/preflight` | Report readiness, platform facts, and optional transport availability. |
| `scripts/knowledge-lookup` | Read accepted knowledge for one target and optional capability. |
| `scripts/discovery-finalize` | Validate and save reusable knowledge from a bounded Discovery. |

Use the same Python interpreter reported by `preflight`. Each script supports
`--help` for its exact command contract.

## Use with an agent host

Onboarding is three steps: clone the repository, initialize the Knowledge Root,
then open the checkout with a supported agent host. Step three needs no
user-home installation, symlink, or junction: the repository ships project-local
discovery files, and the repository root stays the canonical skill root.

| Host | Discovery file in this repository | Invocation |
| --- | --- | --- |
| Claude Code | `CLAUDE.md` and `.claude/skills/caravelaweb/SKILL.md` | `/caravelaweb`, or Claude loads it when relevant |
| Codex | `AGENTS.md` and `.agents/skills/caravelaweb/SKILL.md` | `/skills` or `$caravelaweb`, or implicit by description |
| OpenCode | `AGENTS.md` and the same two skill directories | the native `skill` tool, invoked by the agent |

`CLAUDE.md` imports `AGENTS.md`, so all three hosts read one set of project
instructions. Both skill files are thin discovery adapters: they carry no runtime
code and point back to the repository-root [SKILL.md](SKILL.md).

## Safety model

- Web reachability never grants authority for authentication, submission,
  payment, upload, or communication.
- Lookup fails closed; it does not silently substitute another knowledge
  source after an Operational Memory error.
- Knowledge writes require installation-owned authority and respect the
  write-freeze marker.
- Task results, raw HTML, logs, credentials, cookies, and browser-session
  state are rejected as reusable knowledge.
- A repository-root `targets/` directory is ignored because a checkout may
  also be used as a Knowledge Root. Its contents are local state, not source.

## Documentation

- [Installation](docs/installation.md)
- [Architecture](docs/architecture.md)
- [Operational Memory](docs/operational-memory.md)
- [Platform support](docs/platform-support.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

## License

Licensed under the [Apache License 2.0](LICENSE).
