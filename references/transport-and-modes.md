# Transport Selection & Discovery/Operation Reference

## Discovery — Full Detail

**Entry conditions**: no reliable profile exists; requested capability is `UNKNOWN`; target is `DEGRADED`; known knowledge conflicts with observed behavior; a new, never-validated capability is requested; transport compatibility is unknown; reactivating a `RETIRED` target; intentionally simplifying an existing operational path.

**Not a reason to enter Discovery**: the target looks visually unfamiliar to the current agent; one transient failure; Chrome merely being available and convenient.

Discovery does not expand authority — see `safety.md`. When a question can't be answered within current authority, record it `UNKNOWN` and stop; don't cross the boundary to complete the profile.

Discovery executes and delivers the caller's actual task while it learns — it is not a preparatory or throwaway run before the real work.

### Five conceptual phases (not separate tools/commands)

1. **IDENTIFY** — canonical origin, actual entrypoint, requested capability, initial access state, immediate blockers. Don't explore unrelated sections yet.
2. **INSPECT** — the smallest surface needed for the capability (search entrypoint + query behavior + result structure for a search capability; direct-URL behavior + key fields for a detail capability). Prefer semantics (route, role, label, heading, URL, field meaning) over deep CSS selectors or DOM position.
3. **MAP** — describe how the capability works, small and declarative (`GET /projects?q={term}` → listing → `/project/{slug}` detail → `?page={n}` pagination), never an imperative click-script. Map only what the requested capability needs — not unrelated billing/messaging/settings pages.
4. **SIMPLIFY (mandatory)** — after Chrome-based Discovery, actively test: does DIRECT_READ satisfy the capability? If not, does LIGHTPANDA? Only fall back to "Chrome remains necessary" once both are checked and fail. Don't force simplification — a "simpler" path must actually preserve the required semantics, not just return 200 once.
5. **VALIDATE** — confirm the discovered path is strong enough to become reusable knowledge: entrypoint works, query produces expected results, required fields present, completion condition observable, no exploratory recovery was needed, caller authority preserved. Proportional to capability/consequence — not exhaustive whole-site testing.
6. **FINALIZE (mandatory)** — before declaring the Discovery complete, call `<python> <skill>/scripts/discovery-finalize` with reusable operational observations, evidence, and run provenance. Report only `SAVED`, `ALREADY_EXISTS`, or `NOT_SAVED`; successful knowledge is available to the next lookup immediately. A finalizer error leaves Discovery incomplete even if the task response can be delivered. Do not send task results, raw logs, or HTML to Operational Memory.

   Browser-backed finalization also supplies the run-scoped
   `transport_trace` from `SKILL.md`. The finalizer replays its evidenced
   attempts through the hierarchy before any Candidate write. The trace and
   preflight availability are discarded after validation; neither is target
   knowledge. An available Lightpanda tier cannot be omitted from a durable
   Chrome result.

   A trace ends at the first `FUNCTIONAL` transport or with the ladder
   exhausted. A capability blocked on every transport is finalized with the
   full trace, exactly as a working one is: it records the block and earns no
   operational transport. A run that stopped while an available transport was
   still untried proves neither, and stays unproven -- including the case
   where the transport policy itself halted first, which is not exhaustion.
   A ladder that reached no working transport must also carry a durable
   failure class from the list below; `TRANSIENT_NETWORK`,
   `UPSTREAM_TOOL_ERROR`, `LOCAL_ENVIRONMENT`, `PLATFORM_UNSUPPORTED`, and
   `UNKNOWN` describe this run or this machine, so they save nothing.

### Stop conditions

Success (capability reaches `UNDERSTOOD`/`OPERATIONAL`); authority boundary reached; external blocker (unavailable auth, human verification, blocked geography); path works too inconsistently to promote; target/capability proves unsuitable. Don't keep exploring just to produce more information.

### Bounded re-Discovery after degradation

Only investigate the affected capability (e.g. "search route changed" → rediscover search), not the entire site. Preserve everything still valid.

## Operation — Full Detail

Default sequence: receive task → resolve target+capability → read validated profile knowledge → select preferred transport → execute the known path → verify completion → return result or classify failure.

**Entry conditions**: target known; requested capability has adequate validated knowledge; capability is operational (or explicitly caller-approved at a lesser state for bounded execution); caller authority covers it; required transport available. Otherwise: Discovery, or stop at the authority boundary — don't improvise exploration mid-Operation.

Use the *known* path (known route, known semantic locator, known completion condition) — never "search the whole page" or "click around until something works." If the known path stops working, classify the failure (below); don't silently drift into open-ended exploration.

Output discipline: return only what the capability requires — structured fields, not full DOM/accessibility-tree/network-log dumps.

## Transport Hierarchy

```
DIRECT READ / HTTP → LIGHTPANDA → CHROME
```

Selection is **capability-scoped** — one target can legitimately use DIRECT_READ for search, Lightpanda for detail, and Chrome for an authenticated dashboard simultaneously. Don't force one engine across an entire domain.

`PLATFORM_UNSUPPORTED` means an engine cannot exist on this platform. It is
runtime state, not a transport attempt or target failure. `DIRECT_READ` still
runs first; only after it is observed insufficient may selection pass an
unsupported Lightpanda tier and test Chrome. Emit no observation, evidence,
Candidate, lifecycle change, or degradation for the absent engine. During
SIMPLIFY, test `DIRECT_READ` and each simpler engine that physically exists;
claim nothing about one that does not.

- **DIRECT_READ** — preferred whenever readable HTML/Markdown/`llms.txt`/a stable endpoint/an appropriate API satisfies the capability without JS execution. Lowest overhead, easiest reproducibility. Not used merely because it's possible — only when it preserves the required information. A successful HTTP response alone doesn't validate it.
- **LIGHTPANDA** — preferred once validated for the specific required capability. Good fits: public search/listings/detail pages, predictable navigation, DOM extraction. Never assumed equivalent to Chrome — a target can be Lightpanda-operational for search/listing/detail while still needing Chrome for login/upload/complex account flows.
- **CHROME** — default for Discovery on unknown targets (avoids confusing "site behavior" with "engine limitation"), authenticated/persistent-profile workflows, proven Lightpanda incompatibility. A valid *permanent* choice, not an architecture failure — the goal is avoiding unnecessary Chrome dependence, not eliminating Chrome altogether.

### Escalation / de-escalation

Escalate (`DIRECT_READ → LIGHTPANDA → CHROME`) only when evidence shows the simpler path can't satisfy the capability — stop as soon as the required capability works reliably; never escalate "for convenience." De-escalate (`CHROME → LIGHTPANDA → DIRECT_READ`) only after Discovery/revalidation proves the simpler path works, then update the profile.

For finalization, `FAILED` and `INSUFFICIENT` are escalation evidence only;
`FUNCTIONAL` is the sole candidate for the operational transport. A failed
Direct Read and functional Chrome result are therefore compatible facts when
the intervening available tiers were tested. Conflicting outcomes for the
same transport, host, and material context still fail closed.

### Fallback policy

A fallback is a *validated alternative path*, not an automatic retry with a bigger tool. State: what failed, why the preferred transport can't do it, which alternative addresses that specific limitation, whether the fallback itself was validated. "Lightpanda failed once → always use Chrome" is invalid reasoning. Multiple independently-validated transports for the same capability may be recorded as parallel options rather than a forced fallback chain (see `target-profile.md`).

## Failure Classification (before changing transport, lifecycle, or profile)

```
TRANSIENT_NETWORK    → retry within caller policy; no engine/profile change
AUTH_REQUIRED         → resolve per caller policy; don't assume incompatibility
AUTH_EXPIRED          → restore auth; keep target knowledge unless contradicted
TARGET_CHANGED        → affected capability → DEGRADED → bounded Discovery
PROFILE_INCORRECT     → stop relying on the wrong assumption; Discovery/revalidate
ENGINE_INCOMPATIBILITY→ move to next validated transport
UPSTREAM_TOOL_ERROR   → diagnose the tool; don't build new infrastructure reflexively
SITE_BLOCKING         → record constraint; do not bypass (see safety.md)
LOCAL_ENVIRONMENT     → repair environment; don't mutate target knowledge
PLATFORM_UNSUPPORTED  → report the machine limit; write no target knowledge
AUTHORITY_BOUNDARY    → stop; report; don't mark target degraded
UNKNOWN               → stop escalating; preserve evidence; request bounded Discovery if it matters
```

Lifecycle mutation follows the *cause*, not the symptom — e.g. a Lightpanda 404 is not automatically `TARGET_CHANGED` until classified.

### Bot-protection-flavored 403 handling

A DIRECT_READ request may return HTTP 403 with a bot-protection-looking page (e.g. Cloudflare "Just a moment..."). This response is **evidence of possible bot protection, not yet a final failure classification** — the ambiguity is real: the same 403 page can precede either an auto-resolving JavaScript challenge or an interactive CAPTCHA / Turnstile / human-verification gate.

Decision rule when authority permits ordinary browser observation:

1. **Observe once** through an appropriate browser transport (Lightpanda or Chrome, per the transport hierarchy) and classify based on the actual outcome.
2. If the browser passes transparently and the capability works → classify based on the **capability outcome** (e.g. `ENGINE_INCOMPATIBILITY` for DIRECT_READ if the content is JS-rendered, not `SITE_BLOCKING`).
3. If an interactive CAPTCHA / Turnstile / human-verification challenge appears → classify `SITE_BLOCKING`, record the evidence, and stop.
4. **Never interact with or bypass human-verification controls** merely to complete Discovery — that stays outside this skill regardless of how convenient it would be.
5. **Stopping means stopping.** Once the ladder is exhausted, do not continue the same investigation through a web-search tool, an external index, a cached or mirrored copy, or a third-party republisher. None of them is a transport in this hierarchy, and none observes the target. Report the block. A limited search may still locate a route to try through the hierarchy; the search output is a lead, never evidence about the target.

This is not a generic "every 403 requires Chrome" rule. Classification remains evidence-driven and capability-scoped — a 403 from a genuinely blocked endpoint (rate limit, geo-restriction, permanent ban) should be classified directly without browser observation. The browser observation step applies specifically when the 403 page content suggests an auto-resolvable challenge rather than a hard block.

## Upstream Dependency Boundary

CaravelaWeb selects engines and interprets results; it does not implement them. `agent-browser` is the browser-operation interface; Lightpanda and Chrome are engines it spawns (`--engine lightpanda`, or Chrome by default). CaravelaWeb does not fork, vendor, or duplicate their command references — use current upstream docs for exact invocation syntax. Every compatibility claim should record the exact versions actually observed (agent-browser / engine versions), not versions inferred from documentation.

`agent-browser` is a shell CLI, not a registered agent tool/MCP entry. Never conclude "Chrome/Lightpanda unavailable" from an empty tool/MCP registry search — that only checks whether the host agent has a native browser tool, not whether the runtime dependency exists. Check the shell directly (e.g. `agent-browser --version`) before recording a browser transport as unavailable.

If `agent-browser` is unavailable or broken, browser coverage is incomplete. Report the local prerequisite and stop: do not install, bootstrap, or substitute Playwright, Puppeteer, Selenium, Chrome DevTools/CDP/MCP tooling, or another browser-control stack merely to continue the task. The only supported remediation is upstream `agent-browser` setup, proposed or performed only with explicit user authorization.

## Browser Session Isolation

Browser-backed transports (Lightpanda, Chrome) run through a stateful `agent-browser` session. **Every browser-backed workflow must use an explicit `--session <name>`** — no session name means shared default state, which causes collisions in concurrent environments.

### Why sessions are mandatory

An `agent-browser` session holds navigation state, open pages, cookies, and other browser context for the lifetime of the session. Without explicit session names, concurrent or sequential operations land in the same default session and silently share this state. This causes:

- pages from target A appearing in target B's context;
- cookies or auth state leaking between unrelated operations;
- navigation side-effects (redirects, popups, consent dialogs) from one workflow disrupting another.

### Concurrent versus intentional reuse

- **Concurrent or unrelated workflows must use distinct sessions.** Different targets, different capabilities, or parallel agent investigations each get their own `--session <name>`. Do not share a session across independent Discoveries or Operations merely for convenience.
- **A single bounded workflow may intentionally reuse its own session** when continuity is part of that workflow. Example: a multi-step authenticated flow on the same target where cookies and navigation state must persist across steps. The session name is consistent across the workflow's steps; it is not shared with other workflows.

### DIRECT_READ is unaffected

`DIRECT_READ` uses plain HTTP requests with no browser runtime and no session. It needs no `--session` flag and has no session state to isolate.

### Session isolation is execution hygiene, not evidence

Session isolation prevents runtime context collisions. It does not imply that browser state (cookies, localStorage, session tokens) belongs in reusable Target knowledge. Target Profiles capture capability-level behavior and access patterns — never browser session artifacts. Profiles may record "authentication required" or "session needed," never session cookies or tokens.

No rigid session-name format is imposed. The requirement is **uniqueness and isolation** — each independent workflow must be identifiable by its session name so that concurrent operations cannot reasonably be interpreted as sharing one default session.
