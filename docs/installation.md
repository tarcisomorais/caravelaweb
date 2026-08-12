# Installation

CaravelaWeb runs directly from a repository checkout. It does not require or
provide a package installation step.

## Prerequisites

- Git
- Python 3.11 or newer with standard-library SQLite support
- An optional browser stack only when a capability cannot be satisfied by
  direct reading

Clone the repository:

```bash
git clone https://github.com/tarcisomorais/caravelaweb.git
cd caravelaweb
python3 --version
```

On native Windows, the command is normally `python` or `py -3`. Any Python 3.11
or newer works. Keep using that same interpreter for every CaravelaWeb command;
`preflight` reports the exact interpreter path it ran under.

## Create a Knowledge Root

The normal path requires no location decision:

```bash
python3 scripts/init-knowledge-root --json
```

The default data location is:

- Linux and WSL2: `$XDG_DATA_HOME/caravelaweb/knowledge-root` when
  `XDG_DATA_HOME` is set, otherwise
  `~/.local/share/caravelaweb/knowledge-root`
- Native Windows: `%LOCALAPPDATA%\CaravelaWeb\knowledge-root`

Initialization also stores a small remembered-root pointer in the same
per-user application directory. To create or temporarily select another
root, use an explicit flag or environment variable:

```bash
python3 scripts/init-knowledge-root --knowledge-root /path/to/root --json
export CARAVELAWEB_KNOWLEDGE_ROOT=/path/to/root
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

## Verify readiness

```bash
python3 scripts/preflight --json
```

A ready installation reports `"status": "READY"`, an openable schema, and
Operational Memory read/write authority. Preflight is read-only.

Then verify the empty lookup boundary:

```bash
python3 scripts/knowledge-lookup --target example-site --capability search
```

The expected initial result is `not_found`, not an error.

## Register with an agent host

Normal use is from your own project, not from inside this checkout, so
CaravelaWeb needs a one-time global registration with the agent host. This
creates a single link at the host's per-user skill directory that points at
this repository root; it never copies runtime files.

For Claude Code:

```bash
python3 scripts/register-host --host claude --json
```

This creates `~/.claude/skills/caravelaweb` as:

- a symlink to the repository root on Linux, macOS, and WSL2;
- a junction to the repository root on native Windows (no symlink privilege
  required).

Registration is idempotent: rerunning it when already correctly registered
reports `ALREADY_REGISTERED` and changes nothing. `git pull` in this checkout
updates every project that uses the global registration; no re-registration
is needed after an update.

If the checkout is moved or deleted, the link goes stale. Check and repair it
from the new checkout location:

```bash
python3 scripts/register-host --host claude --check --json
python3 scripts/register-host --host claude --relink --json
```

`--relink` only replaces a link that is already a CaravelaWeb-shaped
registration (pointing elsewhere, or pointing at a target that no longer
exists). It refuses, with or without `--relink`, to touch a plain file or
directory already at that path — remove it by hand first if you intend to
register there.

To uninstall, remove only the link itself (never delete through it):

```bash
rm ~/.claude/skills/caravelaweb          # Linux, macOS, WSL2
rmdir %USERPROFILE%\.claude\skills\caravelaweb   # native Windows (junction)
```

Codex and OpenCode do not yet have a documented equivalent one-time global
registration in this repository; their supported discovery model is
checkout-local only (below) until verified.

## Checkout-local discovery (contributors, or work inside this repository)

Opening Claude Code, Codex, or OpenCode directly in this repository checkout
works without any registration step: each host reads the project-local
instruction and skill-discovery files this repository ships (`CLAUDE.md`,
`AGENTS.md`, and the two `SKILL.md` adapters). See
[Use with an agent host](../README.md#use-with-an-agent-host) for the file and
invocation table.

If this checkout is also globally registered (the normal case for its own
maintainer), a session opened at or near the checkout may see both the
global `caravelaweb` entry and the project-local adapter. Both resolve to the
same canonical `SKILL.md`, so this is expected and harmless. From an
unrelated project, only the global entry is present.

## Optional browser transports

CaravelaWeb does not install or vendor browsers. `agent-browser`, Lightpanda,
and Chrome are optional upstream tools. Preflight reports their observed
availability; see [platform support](platform-support.md) and
[`references/external-dependencies.md`](../references/external-dependencies.md).

## Update the checkout

Update source with Git, then rerun the deterministic suite and preflight:

```bash
git pull --ff-only
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 scripts/preflight --json
```

The Knowledge Root remains outside source history and is not replaced by an
update.
