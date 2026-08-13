# Operational Memory

Operational Memory is CaravelaWeb's local SQLite store for reusable web
operating knowledge. It is installation state, not a shared service, public
database, or Python SDK.

## Location

Each Knowledge Root owns one database:

```text
<knowledge-root>/.caravelaweb/operational_memory.db
```

The mandatory schema resource is
`operational_memory/schema.sql`. The runtime verifies both schema metadata and
SQLite `user_version` before using an existing database.

## Model

The store records targets, host scopes, capabilities, evidence, validations,
observations, claims, proposals, and decisions. Accepted knowledge is derived
from Claims and Decisions at read time; there is no independently authoritative
current-state table.

Key properties:

- Knowledge is capability-scoped; one target can use different transports for
  different capabilities.
- Host-specific behavior remains host-scoped.
- `OBSERVED`, `INFERRED`, and `UNKNOWN` remain distinct.
- Pending proposals do not silently become accepted knowledge.
- Historical decisions remain available for projection without appearing in
  the default compact operational context.
- Ambiguous corrections fail closed.

## Discovery writes

`scripts/discovery-finalize` accepts a bounded JSON record containing reusable
observations, evidence, and run provenance. It rejects task results, raw page
content, logs, credentials, private data, browser sessions, and platform-only
state.

Browser-backed results additionally require an evidenced, ordered
`transport_trace`. The finalizer validates the current run's preflight
availability and attempts before writing, but does not persist that trace or
availability as a Claim or other target knowledge. Failed or insufficient
transport observations may justify escalation; only a functional transport
may support an operational lifecycle.

The normal result strings are:

- `SAVED` — reusable knowledge was saved and is available to lookup.
- `ALREADY_EXISTS` — equivalent knowledge already exists.
- `NOT_SAVED` — no reusable knowledge was accepted.

These strings are part of the CLI contract. Error output includes a reason
without exposing internal paths or a traceback in the normal user flow.
Neither `SAVED` nor lookup `found` means operational readiness. The Discovery
finalizer generates an `OPERATIONAL` lifecycle Claim only after the canonical
reusable-path proof is complete, successful, explicitly evidenced, and
consistent with accepted transport and access facts. Its Claim payload records
the supporting Claim IDs; lookup trusts it only while those Claims remain
current and uncontradicted. Partial accepted knowledge remains lookup-visible.
The public finalizer accepts only documented wrapper and family-value fields.
Extraction output is represented as field-path/selector schema maps, never as
returned records; unknown structured fields are rejected before persistence.
An exact historical multi-Claim Candidate can be enriched and promoted on a
later valid retry without duplicating its Claims or Proposal.

## Authority and safety

Fresh installation establishes `NONE -> OPERATIONAL_MEMORY` authority.
Compatibility state from an imported installation remains distinguishable so
the runtime never invents prior authority.

Writes require:

- a valid installation-owned write-authority marker;
- the Operational Memory destination;
- reusable-knowledge write authority at the operation boundary; and
- no active or malformed knowledge-write freeze.

Writes use SQLite transactions. Candidate promotion checks a stable review
token and rolls back on any failure. The database, WAL, journal, marker, and
lock files are ignored by Git.

## Backups

Stop active writers before copying a Knowledge Root. Back up the complete
`.caravelaweb` state together rather than copying only the main database while
WAL activity may exist. Restore into a native local filesystem and run
`preflight` before use.
