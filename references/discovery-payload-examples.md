# Discovery payload examples

Complete, copyable `discovery.json` payloads for `scripts/discovery-finalize`.
Every field-level rule lives in `target-profile.md` and `transport-and-modes.md`;
this reference exists so an agent can copy a working payload instead of
re-deriving the schema from prose.

Each `provenance.run_id` below is a placeholder. A real payload uses the
`run_id` returned by `scripts/discovery-begin` for that exact target and
capability -- never a literal string. `tests/test_discovery_payload_examples.py`
extracts every JSON block below, opens a matching synthetic Discovery run, and
finalizes it for real: if a runtime rule changes, this file fails the suite
instead of silently drifting from the contract.

Every first-run example records the host it observed; a target without a
host is never reachable by URL.

## 1. Functional `DIRECT_READ`

```json
{
  "target": "example-direct-read",
  "capability": "article-read",
  "observations": [
    {
      "family": "transport", "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"},
      "host": "example-direct-read.example"
    }
  ],
  "evidence": [{
    "kind": "direct-read-validation",
    "locator": "https://example-direct-read.example/articles/1",
    "scope": "TARGET_SURFACE"
  }],
  "provenance": {"run_id": "<from discovery-begin>", "observed_at": "2026-08-14T12:00:00Z"},
  "recorded_at": "2026-08-14T12:00:00Z"
}
```

## 2. Single-record extraction using `$.field`

An explicit-root path names a field at the root of one record, not inside a
collection.

```json
{
  "target": "example-single-record",
  "capability": "article-read",
  "observations": [
    {
      "family": "transport", "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"},
      "host": "example-single-record.example"
    },
    {"family": "extraction", "value": {
      "structure": "JSON_LD",
      "field_paths": {"headline": "$.headline", "body": "$.article.full_text"}
    }}
  ],
  "evidence": [{
    "kind": "direct-read-validation",
    "locator": "https://example-single-record.example/articles/1",
    "scope": "TARGET_SURFACE"
  }],
  "provenance": {"run_id": "<from discovery-begin>", "observed_at": "2026-08-14T12:00:00Z"},
  "recorded_at": "2026-08-14T12:00:00Z"
}
```

## 3. Collection extraction using `items[].field`

```json
{
  "target": "example-collection",
  "capability": "topic-search",
  "observations": [
    {
      "family": "transport", "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"},
      "host": "example-collection.example"
    },
    {"family": "extraction", "value": {
      "structure": "JSON_LD",
      "field_paths": {"name": "items[].name", "url": "items[].url"}
    }}
  ],
  "evidence": [{
    "kind": "direct-read-validation",
    "locator": "https://example-collection.example/search?q=topic",
    "scope": "TARGET_SURFACE"
  }],
  "provenance": {"run_id": "<from discovery-begin>", "observed_at": "2026-08-14T12:00:00Z"},
  "recorded_at": "2026-08-14T12:00:00Z"
}
```

## 4. First-time host association with `scope: "TARGET_SURFACE"`

A brand-new observation host is accepted only from evidence whose locator
hostname exactly matches the literal Observation Host, with `scope` exactly
`"TARGET_SURFACE"`.

```json
{
  "target": "example-host-assoc",
  "capability": "article-read",
  "observations": [
    {
      "family": "transport", "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"},
      "host": "www.example-host-assoc.example"
    }
  ],
  "evidence": [{
    "kind": "direct-read-validation",
    "locator": "https://www.example-host-assoc.example/articles/1",
    "scope": "TARGET_SURFACE"
  }],
  "provenance": {"run_id": "<from discovery-begin>", "observed_at": "2026-08-14T12:00:00Z"},
  "recorded_at": "2026-08-14T12:00:00Z"
}
```

## 5. Browser escalation with a complete transport trace

`DIRECT_READ` fails, `LIGHTPANDA` proves functional; `transport_trace` records
both attempts and stops at the first `FUNCTIONAL` result.

```json
{
  "target": "example-browser-escalation",
  "capability": "article-read",
  "observations": [
    {
      "family": "transport", "value": {"transport": "DIRECT_READ", "outcome": "FAILED"},
      "host": "example-browser-escalation.example",
      "validation": {
        "transport": "DIRECT_READ", "outcome": "FAILED", "engine": null, "javascript": false,
        "context": {"authentication": "PUBLIC", "environment": "PRODUCTION"},
        "evidence": ["https://example-browser-escalation.example/articles/1"]
      }
    },
    {
      "family": "transport", "value": {"transport": "LIGHTPANDA", "outcome": "FUNCTIONAL"},
      "validation": {
        "transport": "LIGHTPANDA", "outcome": "FUNCTIONAL", "engine": "lightpanda", "javascript": true,
        "context": {"authentication": "PUBLIC", "environment": "PRODUCTION"},
        "evidence": ["https://example-browser-escalation.example/articles/1-rendered"]
      }
    }
  ],
  "evidence": [
    {
      "kind": "transport-validation",
      "locator": "https://example-browser-escalation.example/articles/1",
      "scope": "TARGET_SURFACE"
    },
    {"kind": "bounded-browser-validation", "locator": "https://example-browser-escalation.example/articles/1-rendered"}
  ],
  "transport_trace": {
    "availability": {"LIGHTPANDA": "AVAILABLE", "CHROME": "AVAILABLE"},
    "attempts": [
      {
        "transport": "DIRECT_READ", "outcome": "FAILED",
        "host": "example-browser-escalation.example",
        "evidence": ["https://example-browser-escalation.example/articles/1"]
      },
      {"transport": "LIGHTPANDA", "outcome": "FUNCTIONAL", "evidence": ["https://example-browser-escalation.example/articles/1-rendered"]}
    ]
  },
  "provenance": {"run_id": "<from discovery-begin>", "observed_at": "2026-08-14T12:00:00Z"},
  "recorded_at": "2026-08-14T12:00:00Z"
}
```

## 6. A fully blocked ladder with durable failure classification

Every available transport was attempted and none worked. The ladder is
exhausted, not abandoned, and the failure names a durable class -- so this
still finalizes with `SAVED`, recording the block for reuse.

```json
{
  "target": "example-blocked-ladder",
  "capability": "article-read",
  "observations": [
    {
      "family": "transport", "value": {"transport": "DIRECT_READ", "outcome": "FAILED"},
      "host": "example-blocked-ladder.example",
      "validation": {
        "transport": "DIRECT_READ", "outcome": "FAILED", "engine": null, "javascript": false,
        "context": {"authentication": "PUBLIC", "environment": "PRODUCTION"},
        "evidence": ["https://example-blocked-ladder.example/articles/1"]
      }
    },
    {
      "family": "blocking",
      "value": {
        "failure_class": "SITE_BLOCKING",
        "condition": "every request receives an interstitial challenge page"
      },
      "validation": {
        "transport": "DIRECT_READ", "outcome": "FAILED", "engine": null, "javascript": false,
        "context": {"authentication": "PUBLIC", "environment": "PRODUCTION"},
        "evidence": ["https://example-blocked-ladder.example/articles/1"]
      }
    }
  ],
  "evidence": [{
    "kind": "transport-validation",
    "locator": "https://example-blocked-ladder.example/articles/1",
    "scope": "TARGET_SURFACE"
  }],
  "transport_trace": {
    "availability": {"LIGHTPANDA": "PLATFORM_UNSUPPORTED", "CHROME": "PLATFORM_UNSUPPORTED"},
    "attempts": [
      {"transport": "DIRECT_READ", "outcome": "FAILED", "evidence": ["https://example-blocked-ladder.example/articles/1"]}
    ]
  },
  "provenance": {"run_id": "<from discovery-begin>", "observed_at": "2026-08-14T12:00:00Z"},
  "recorded_at": "2026-08-14T12:00:00Z"
}
```

## 7. An observed limitation with complete validation context

An `OBSERVED` `blocking` or `limitation` constraint requires a `validation`
that names the transport, engine, JavaScript, and authentication/environment
context that actually observed it -- an empty or partial `validation` never
satisfies this.

```json
{
  "target": "example-observed-limitation",
  "capability": "article-read",
  "observations": [
    {
      "family": "transport", "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"},
      "host": "example-observed-limitation.example"
    },
    {
      "family": "limitation",
      "value": {"kind": "RATE_LIMIT", "condition": "more than 30 requests per minute return HTTP 429"},
      "validation": {
        "transport": "DIRECT_READ", "outcome": "OBSERVED", "engine": null, "javascript": false,
        "context": {"authentication": "PUBLIC", "environment": "PRODUCTION"},
        "evidence": ["https://example-observed-limitation.example/articles/1"]
      }
    }
  ],
  "evidence": [{
    "kind": "direct-read-validation",
    "locator": "https://example-observed-limitation.example/articles/1",
    "scope": "TARGET_SURFACE"
  }],
  "provenance": {"run_id": "<from discovery-begin>", "observed_at": "2026-08-14T12:00:00Z"},
  "recorded_at": "2026-08-14T12:00:00Z"
}
```

## 8. A complete operational proof that earns `OPERATIONAL`

This payload carries the three observations the finalizer requires to earn
the `OPERATIONAL` lifecycle in one run: a `FUNCTIONAL` transport, a matching
`authentication` fact, and a `validation` observation whose own nested
`validation` reports outcome `SUCCESS`.

```json
{
  "target": "example-operational",
  "capability": "article-read",
  "observations": [
    {
      "family": "transport", "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"},
      "host": "example-operational.example",
      "validation": {
        "transport": "DIRECT_READ", "outcome": "FUNCTIONAL", "engine": null, "javascript": false,
        "context": {"authentication": "PUBLIC", "environment": "PRODUCTION"},
        "evidence": ["https://example-operational.example/articles/1"]
      }
    },
    {"family": "authentication", "value": {"access_model": "PUBLIC"}},
    {
      "family": "validation",
      "value": {"operational_proof": {
        "entrypoint": "https://example-operational.example/articles/{id}",
        "required_output": {"field_paths": {"headline": "$.headline"}},
        "completion_condition": "HTTP 200 whose HTML carries a headline element",
        "critical_constraints": []
      }},
      "host": "example-operational.example",
      "validation": {
        "transport": "DIRECT_READ", "outcome": "SUCCESS", "engine": null, "javascript": false,
        "context": {"authentication": "PUBLIC", "environment": "PRODUCTION"},
        "evidence": ["https://example-operational.example/articles/1"]
      }
    }
  ],
  "evidence": [{
    "kind": "direct-read-validation",
    "locator": "https://example-operational.example/articles/1",
    "scope": "TARGET_SURFACE"
  }],
  "provenance": {"run_id": "<from discovery-begin>", "observed_at": "2026-08-14T12:00:00Z"},
  "recorded_at": "2026-08-14T12:00:00Z"
}
```

## Abandoned runs

If a caller abandons a retryable or invalid finalization -- for example it
stops after a `TRANSPORT_POLICY_UNPROVEN` result without resubmitting -- its
marker remains open and stays visible through `knowledge-lookup` and
`preflight`. This is current, deliberate behavior, not a bug: markers are not
expired or cleaned up automatically. Automatic marker cleanup is a separate
lifecycle feature and is added only from observed need.
