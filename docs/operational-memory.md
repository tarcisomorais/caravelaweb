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

The normal result strings are:

- `SAVED` — reusable knowledge was saved and is available to lookup.
- `ALREADY_EXISTS` — equivalent knowledge already exists.
- `NOT_SAVED` — no reusable knowledge was accepted.

These strings are part of the CLI contract. Error output includes a reason
without exposing internal paths or a traceback in the normal user flow.

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
