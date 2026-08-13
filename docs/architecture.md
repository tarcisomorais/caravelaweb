# Architecture

CaravelaWeb separates source code, local reusable knowledge, and web-action
authority. The repository root is the canonical skill root; nested skill
directories contain discovery adapters only, and there is no package-installation
layer.

## Public runtime boundary

Four CLI entry points form the supported runtime surface:

- `scripts/init-knowledge-root`
- `scripts/preflight`
- `scripts/knowledge-lookup`
- `scripts/discovery-finalize`

Their production import closure is deliberately small:

- `discovery_finalize.py`
- `installation_init.py`
- `integration_bridge.py`
- `knowledge_write_freeze.py`
- `om_native_writes.py`
- `platform_adapter.py`
- `read_authority.py`
- `transport_policy.py`
- `write_authority.py`
- `operational_memory/__init__.py`
- `operational_memory/core.py`
- `operational_memory/schema.sql`

Everything under `tests/` is test-only infrastructure, including the frozen
conformance query harness and synthetic fixture.

## Distribution

The repository is the unit of distribution. Claude Code reads
`.claude-plugin/marketplace.json` and `.claude-plugin/plugin.json`. Codex reads
the native `.agents/plugins/marketplace.json` and `.codex-plugin/plugin.json`.
Both discover the shared `skills/caravelaweb/SKILL.md` plugin adapter and
publish the repository root, so runtime and references stay canonical and
unduplicated. The root `SKILL.md` remains the only contract.

Claude Code copies an installed plugin into its own versioned cache, so the
skill root differs per install:

| Install | Skill root |
| --- | --- |
| Claude plugin | The cached copy, addressable as `${CLAUDE_PLUGIN_ROOT}` |
| Codex plugin | `../..` from the installed `skills/caravelaweb/SKILL.md` adapter directory |
| Checkout through `.agents` | `../../..` from the `.agents/skills/caravelaweb/SKILL.md` adapter directory |
| Personal skill directory, or a link into it | The checkout |
| Checkout opened directly | The checkout |

The contract refers to that root as `<skill>` in every host. Its resolution is
the only host adapter: Claude retains its validated plugin-root variable;
installed plugins derive `../..` from the shared adapter; checkout-local Codex,
IDE, and OpenCode derive `../../..` from the `.agents` adapter. None use the
process working directory. The cached root must never hold state; every
writable path CaravelaWeb owns lives under the Knowledge Root and the per-user
application directory instead.

## Host registration

`scripts/register-host` (import closure: `host_registration.py`) is a
separate concern from the runtime surface above: it manages one link (a
POSIX symlink or Windows junction) at a supported agent host's per-user
skill directory, pointing at this repository root, so a checkout is
discoverable from unrelated repositories. It never copies runtime files,
never touches Knowledge Root state, and never installs browser
dependencies. It is developer tooling, not the public install path. See
[installation](installation.md#developer-mode).

## Runtime flow

```text
init-knowledge-root
  -> create Knowledge Root markers
  -> create local SQLite Operational Memory
  -> remember the selected root

knowledge-lookup
  -> resolve Knowledge Root
  -> verify read authority
  -> query accepted capability knowledge
  -> return found / not_found / fail-closed error

bounded Discovery
  -> DIRECT_READ, then optional browser escalation
  -> validate reusable observations, evidence, and run-scoped transport trace
  -> discovery-finalize
  -> pending or accepted Operational Memory state
  -> next knowledge-lookup sees accepted knowledge
```

## Boundaries

### Source checkout

Contains runtime, tests, policy references, and documentation. It must never
contain a user's target corpus, Operational Memory database, credentials, or
browser state.

### Knowledge Root

Contains installation-owned markers, SQLite state, and the local `targets/`
directory. Resolution order is explicit flag, environment variable,
remembered root, then marker walk-up.

### Web authority

CaravelaWeb records and applies operating knowledge; it does not grant
permission. Authentication, mutation, payment, upload, submission, and
external communication remain subject to caller authority on every run.

## Transport policy

Transport selection is capability-scoped and ordered:

```text
DIRECT_READ -> LIGHTPANDA -> CHROME
```

Direct reading is always attempted first. Escalation requires observed
insufficiency, and platform absence is runtime state rather than target
degradation. Chrome-based Discovery must test simpler available transports
before finalizing a durable path. The finalizer enforces that sequence at the
write boundary; it does not persist the trace or preflight availability as
target knowledge.

## Fail-closed behavior

- Invalid authority markers are errors.
- Unsafe marker links or reparse points are rejected.
- SQLite corruption and schema mismatches are reported rather than treated as
  absence.
- Operational Memory errors never cause an automatic fallback.
- Writes are transactional and respect the installation's write authority and
  freeze state.
