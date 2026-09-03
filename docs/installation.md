# Installation

The supported public installs are the native Codex and Claude Code plugins.
This page also covers alternative installs, developer mode, first-run behavior,
optional browser transports, and removal.

## Prerequisites

- Python 3.11 or newer, including the standard-library `sqlite3` module
- Codex CLI 0.147.0 or newer, or Claude Code 2.1.142 or newer
- Windows, Linux, WSL2, or macOS (macOS is not validated by CI; see
  docs/platform-support.md)

CaravelaWeb has no package-installation step and no Python dependencies.

## Install as a Codex plugin

From any project:

```bash
codex plugin marketplace add tarcisomorais/caravelaweb
codex plugin add caravelaweb@caravelaweb
```

The commands are identical on every supported platform. Codex copies the
plugin into its per-user cache and exposes the declared skill `caravelaweb` in
projects unrelated to this repository. Codex CLI 0.147.0 renders that installed
skill as `caravelaweb:caravelaweb` in model-visible prompt input. The first name
in `caravelaweb@caravelaweb` is the plugin; the second is the marketplace.

The Codex manifest carries an explicit semantic version. Public releases bump
that version. For a GitHub marketplace install, request a marketplace refresh
with:

```bash
codex plugin marketplace upgrade caravelaweb
```

CaravelaWeb does not use unchanged-version content replacement as a supported
release path.

## Install as a Claude Code plugin

From any project:

```text
/plugin marketplace add tarcisomorais/caravelaweb
/plugin install caravelaweb@caravelaweb
```

Or, without an interactive step:

```bash
claude plugin marketplace add tarcisomorais/caravelaweb
claude plugin install caravelaweb@caravelaweb
```

The commands are identical on every supported platform. No symlink, junction,
`PATH` entry, or elevated privilege is involved: Claude Code copies the plugin
into its own versioned cache and discovers
`skills/caravelaweb/SKILL.md`. That thin adapter reads the canonical root
`SKILL.md`; it does not duplicate the contract.

Both plugin manifests declare the same semantic version (`0.1.0` at this
release), and public releases bump it together with `CHANGELOG.md`.
`/plugin update caravelaweb@caravelaweb` moves you to the newest published
version of the marketplace entry.

## First run

The executor prepares readiness itself. On the first CaravelaWeb command of a
new installation it runs `preflight`, creates the Knowledge Root if none is
resolved, and reports where that local memory was created.

The default location is:

- Linux, WSL2, and macOS: `$XDG_DATA_HOME/caravelaweb/knowledge-root` when
  `XDG_DATA_HOME` is set, otherwise `~/.local/share/caravelaweb/knowledge-root`
- Native Windows: `%LOCALAPPDATA%\CaravelaWeb\knowledge-root`

That location is outside the plugin cache, so a plugin update never touches it.

To choose another location, or to inspect readiness yourself, use the runtime
commands below.

## Alternative install: personal skill directory

If you prefer a Git checkout you control, clone the repository straight into
Claude Code's personal skill directory:

```bash
git clone https://github.com/tarcisomorais/caravelaweb.git ~/.claude/skills/caravelaweb
```

On native Windows, the destination is
`%USERPROFILE%\.claude\skills\caravelaweb`.

Claude Code discovers it with no install step, and `git pull` inside that
directory updates it. Because the repository ships a plugin manifest, the entry
loads as `caravelaweb@skills-dir`. Removing the directory removes the skill.

Do not combine this with the plugin install: both would appear at once.

## Developer mode

To work on CaravelaWeb itself, load a checkout live instead of a cached copy:

```bash
claude --plugin-dir /path/to/caravelaweb
```

The repository also ships one-time global links for live checkout development:

```bash
python3 scripts/register-host --host claude --json
python3 scripts/register-host --host codex --json
python3 scripts/register-host --host opencode --json
```

Each command creates a `caravelaweb` link in the host's documented per-user
skill directory: `~/.claude/skills` for Claude Code, `~/.agents/skills` for
[Codex](https://developers.openai.com/codex/skills/#where-to-save-skills), and
`~/.config/opencode/skills` for
[OpenCode](https://opencode.ai/docs/skills/#place-files). The link is a symlink
on Linux, macOS, and WSL2, or a junction on native Windows. Registration never
copies runtime files. It is a development convenience, not the public install
path; Codex's native plugin distribution remains the public install path.

OpenCode also loads global skills from `~/.claude/skills` and
`~/.agents/skills`, so a `claude` or `codex` registration already covers
OpenCode. Register the `opencode` host only when neither of those links exists.

Registration is idempotent and reports `ALREADY_REGISTERED` when correct. If
the checkout moves, repair the link from its new location:

```bash
python3 scripts/register-host --host codex --check --json
python3 scripts/register-host --host codex --relink --json
```

`--relink` only replaces a link that is already a CaravelaWeb-shaped
registration. It refuses, with or without `--relink`, to touch a plain file or
directory at that path.

Opening Claude Code, Codex, or OpenCode directly in the checkout also works
with no registration step, through the project-local files this repository
ships:

| Host | Discovery file in this repository | Invocation |
| --- | --- | --- |
| Claude Code | `CLAUDE.md` and `.claude/skills/caravelaweb/SKILL.md` | `/caravelaweb`, or Claude loads it when relevant |
| Codex | `AGENTS.md` and `.agents/skills/caravelaweb/SKILL.md` | `/skills` or `$caravelaweb`, or implicit by description |
| OpenCode | `AGENTS.md` and the same two skill directories | the native `skill` tool, invoked by the agent |

`CLAUDE.md` imports `AGENTS.md`, so all three hosts read one set of project
instructions. Both skill files are thin discovery adapters: they carry no
runtime code and point back to the repository-root [SKILL.md](../SKILL.md). A
checkout that is installed and also opened locally may show both entries; they
resolve to the same canonical file, so this is expected.

Codex IDE extensions do not load plugins; global registration and
checkout-local discovery remain available through the documented
`.agents/skills` convention.

## Runtime commands (advanced)

| Command | Purpose |
| --- | --- |
| `scripts/init-knowledge-root` | Create an empty local Knowledge Root and Operational Memory. |
| `scripts/preflight` | Report readiness, platform facts, and optional transport availability. |
| `scripts/knowledge-lookup` | Read accepted knowledge for one target and optional capability. |
| `scripts/discovery-begin` | Register the start of one bounded Discovery run and return its run_id. |
| `scripts/discovery-finalize` | Validate and save reusable knowledge from a bounded Discovery. |
| `scripts/register-host` | Link a checkout into Claude Code, Codex, or OpenCode's per-user skill directory (developer mode). |

Use one interpreter for every CaravelaWeb command; `preflight` reports the
exact interpreter path it ran under. On native Windows, use `python` or `py -3`
instead of `python3`. Each script supports `--help`.

To create and use another Knowledge Root:

```bash
python3 scripts/init-knowledge-root --knowledge-root /path/to/root --json
export CARAVELAWEB_KNOWLEDGE_ROOT=/path/to/root
```

Both lines are required. Creating a root elsewhere never makes it the
default, so the environment variable (or `--knowledge-root` on every command)
is what reaches it. This keeps concurrent sessions independent: no command
can change which Knowledge Root another session resolves.

Resolution is deterministic, and derives the default rather than storing it:

```text
explicit --knowledge-root
-> CARAVELAWEB_KNOWLEDGE_ROOT
-> the fixed per-user default location above
```

The initialized layout is installation-owned:

```text
knowledge-root/
├── .caravelaweb-knowledge-root
├── .caravelaweb/
│   ├── operational_memory.db
│   ├── read-authority-operational-memory
│   └── write-authority.json
└── targets/
```

Initialization refuses a location that already contains knowledge or
incompatible state. It does not overwrite or import that content.

`preflight` is read-only. A ready installation reports `"status": "READY"`, an
openable schema, and Operational Memory read/write authority. A first lookup
against an empty installation returns `not_found`, not an error.

## Optional browser transports

CaravelaWeb does not install or vendor browsers. `agent-browser`, Lightpanda,
and Chrome are optional upstream tools, and `DIRECT_READ` needs none of them.

`READY` means core storage is usable, not that browser coverage is complete.
Preflight can report **core READY; browser coverage incomplete** without
failing core setup. On native Windows, Lightpanda is `PLATFORM_UNSUPPORTED` and
Chrome requires both `agent-browser` and a detected Chrome engine.

With explicit user authorization, install `agent-browser` upstream, run
`agent-browser install` when browser provisioning is required, and use
`agent-browser doctor --json` for diagnosis. Preflight never performs those
actions or launches a browser. Do not replace a missing or broken
`agent-browser` with Playwright, Puppeteer, Selenium, CDP/MCP tooling, or
another browser-control stack.

See [platform support](platform-support.md) and
[`references/external-dependencies.md`](../references/external-dependencies.md).

## Uninstall

Codex:

```bash
codex plugin remove caravelaweb@caravelaweb
codex plugin marketplace remove caravelaweb
```

Claude Code:

Remove the plugin:

```text
/plugin uninstall caravelaweb@caravelaweb
```

Remove the marketplace entry too, if you no longer want it listed:

```text
/plugin marketplace remove caravelaweb
```

For the personal-skill-directory install, delete
`~/.claude/skills/caravelaweb`. For a developer-mode link, remove only the
host-specific link itself, never delete through it:

```bash
rm ~/.claude/skills/caravelaweb                  # Linux, macOS, WSL2
rm ~/.agents/skills/caravelaweb                  # Codex
rm ~/.config/opencode/skills/caravelaweb         # OpenCode
rmdir %USERPROFILE%\.claude\skills\caravelaweb   # native Windows (junction)
rmdir %USERPROFILE%\.agents\skills\caravelaweb  # Codex on native Windows
rmdir %USERPROFILE%\.config\opencode\skills\caravelaweb # OpenCode on native Windows
```

### Remove the local memory

Uninstalling never deletes your Knowledge Root. Delete it deliberately:

```bash
rm -rf ~/.local/share/caravelaweb                            # Linux, WSL2, macOS
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\CaravelaWeb"  # native Windows
```

This removes accepted knowledge for every target on this installation.

## Update a checkout

For the personal-skill-directory or developer-mode installs, update with Git
and rerun the suite:

```bash
git pull --ff-only
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 scripts/preflight --json
```

The Knowledge Root remains outside source history and is not replaced by an
update.
