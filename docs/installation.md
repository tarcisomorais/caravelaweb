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

On Windows, use `python` or `py -3.11` if that is how Python is installed.
Keep using that same interpreter for every CaravelaWeb command.

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
