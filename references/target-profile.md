# Target Profile Reference

This reference defines reusable, capability-scoped operating knowledge. It is not executable browser code or a storage manual.

## Target ID Naming Convention

Target IDs are stable lowercase kebab-case identifiers derived from the public brand, not a URL path, capability, campaign, or consuming-project ID. Prefer the shortest unambiguous public name (`example-news`, `example-jobs`, `example-maps`). Keep an accepted ID stable. One evidence-backed target may span hosts; host differences belong in the capability context.

## Knowledge Lookup

Before treating a capability as unknown, run `knowledge-lookup` with the
concrete interpreter and skill path reported by preflight:

```text
<python> <skill>/scripts/knowledge-lookup --target example-jobs --capability project_listings
<python> <skill>/scripts/knowledge-lookup --knowledge-root <explicit-root> --target example-jobs --capability project_listings
```

Use `--knowledge-root` only for a caller-supplied override. The normal boundary returns accepted context for the requested capability:

- `found` — read the accepted capability context.
- `not_found` — no accepted reusable knowledge exists for that capability.
- `unresolved` or `bridge_error` — accepted knowledge could not be consulted; stop rather than treating the target as checked.

Lookup is capability-scoped and performs no web action, transport selection, knowledge mutation, or publication. It does not silently fall back to historical knowledge.

## Knowledge Boundary

Only reusable operating observations, evidence, and provenance belong in Discovery finalization. When a bounded Discovery has none, use `"observations": []`; this closes as `NÃO_SALVA`. Never include task results, raw page dumps, runtime logs, browser-session state, credentials, private user data, business logic, editorial judgment, or speculative facts presented as truth.

Local Operational Memory is writable by the installation's normal policy and is separate from web-action authority. Saving local knowledge never authorizes source-control publication, project-file changes, or external state changes. A successful, directly observed Discovery is available to the next lookup immediately; ambiguous or invalid knowledge is not used operationally. Diagnostic compatibility and repair procedures are not executor input.

## Epistemic Classes

Every meaningful claim is one of:

- **OBSERVED** — directly established.
- **INFERRED** — reasonable but not validated.
- **UNKNOWN** — not established.

Inference must never silently become an operational dependency, and unknowns must not be hidden to make a report look complete.

## Lifecycle States

```text
UNKNOWN -> DISCOVERING -> UNDERSTOOD -> OPERATIONAL -> DEGRADED -> (DISCOVERING)
any state -> RETIRED -> (DISCOVERING, on explicit reactivation)
```

- **UNKNOWN** — no trusted transport, route, or authentication assumption.
- **DISCOVERING** — bounded investigation is in progress; evidence may remain insufficient.
- **UNDERSTOOD** — behavior and constraints are mapped, but no routine path is validated.
- **OPERATIONAL** — this capability has a sufficiently validated routine path; it does not authorize other capabilities or actions.
- **DEGRADED** — a validated assumption was contradicted; stop trusting that part and rediscover only the affected capability.
- **RETIRED** — intentionally not used; do not resume on stale assumptions.

`UNDERSTOOD + BLOCKED` reuses the recorded blocker while relevant conditions remain unchanged. A target-level state is only a summary: always use the capability's state. One timeout, DNS failure, 5xx, browser crash, tool bug, expired auth, isolated rate limit, or interstitial does not itself degrade knowledge; classify it first.

## Capability and Host Scope

Capabilities are the unit of knowledge: evidence for `search` never validates `detail`, `login`, or `application_submission`. A target can contain operational and unknown capabilities at the same time.

For a multi-host target, record the affected host when behavior differs. Transport compatibility and blocking are host-scoped: a pass or block on one host does not generalize to another host without separate validation.

## Completion Semantics

An `OPERATIONAL` capability records enough evidence to reproduce the requested path: target and capability, access model, transport, entrypoint, observable completion condition, required output or action, critical constraints, and validation evidence. Browser-backed evidence also records the actually observed `agent-browser` and engine context when material.

Readiness says a surface is ready to inspect; completion says the requested capability produced the required result. Use an observable readiness condition and bounded timeout when readiness is needed. A page load, HTTP 200, or elapsed sleep is never sufficient proof of completion.

A well-understood blocked capability records its lifecycle, availability, relevant host, blocker/failure class, observed evidence, and conditions that would need to change. Do not invent operational fields that were never reached.

## Authentication

Knowledge may state where authentication is required or whether human-assisted auth is expected. It must never contain passwords, tokens, API secrets, recovery codes, MFA seeds, or reusable session cookies. Credentials remain in the consuming environment.
