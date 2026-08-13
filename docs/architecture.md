# Architecture

CaravelaWeb separates source code, local reusable knowledge, and web-action
authority. The repository root is the skill root; there is no nested skill
directory and no package-installation layer.

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

The repository is the unit of distribution. `.claude-plugin/marketplace.json`
publishes one plugin whose source is the repository root, and
`.claude-plugin/plugin.json` names it. The repository is therefore both the
marketplace and the plugin, and the root `SKILL.md` is loaded as the plugin's
single skill.

Claude Code copies an installed plugin into its own versioned cache, so the
skill root differs per install:

| Install | Skill root |
| --- | --- |
| Plugin | The cached copy, addressable as `${CLAUDE_PLUGIN_ROOT}` |
| Personal skill directory, or a link into it | The checkout |
| Checkout opened directly | The checkout |

The contract refers to that root as `<skill>` in every host, so no runtime path
is host-specific. The cached root is replaced on update and must never hold
state; every writable path CaravelaWeb owns lives under the Knowledge Root and
the per-user application directory instead.

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
