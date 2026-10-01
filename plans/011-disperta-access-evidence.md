# Plan 011: Close the gaps the Disperta access evidence exposed

> **Commit methodology**: one commit per change below, linear history,
> author and committer `Tarciso Morais <287870717+tarcisomorais@users.noreply.github.com>`,
> imperative sentence-case subject with no prefix and no period, a prose
> body wrapped at 76 columns with three paragraphs (observed problem, what
> changed and why, what tests now cover), and no trailers of any kind.
> Releasing is a separate step (version commit, CI, annotated tag,
> `gh release create`) gated below.

## Status

- **Priority**: P1. **Effort**: S per change; the experiment is the cost.
- **Branch**: `plan-011`, from `7a97e61` (0.3.0).
- **Absorbs**: CORRECTNESS-06 (Lightpanda skipped), DIRECTION-08 (meaning
  of `observed_at`). **Records**: DIRECTION-09 (claims need captured
  evidence before they can be validated deterministically).
- **Progress**: see "Execution record" at the end.

## Evidence

Disperta Slice 7 drove CaravelaWeb 0.3.0 against 30 news Sources in its
`claude -p` call shape (Sonnet 5.5, effort medium, tools `Skill,Bash`,
`CARAVELAWEB_LEARNING=disabled`, one authorized learning call). Evidence:
`disperta-scratch/slice7/{p7,p7b,p7c,p7d,v7,w7}` and
`new-disperta/plans/probes/slice-7-search.md`. Findings:

1. A lookup miss on a resolved target returned the whole index (~23 KB),
   not the target's row; `status` sorted after `index`, so truncated
   replies never showed `not_found`. 28 of 31 later lookups used an
   invented capability ID; no P7/P7b call read an accepted capability.
2. Callers read only `SKILL.md`, never `references/`. Lightpanda was used
   once in about 61 browser escalations although preflight reported it
   AVAILABLE: SKILL.md never says `agent-browser` opens Chrome without
   `--engine lightpanda`, and it calls Chrome the Discovery baseline,
   contradicting the ladder the finalizer enforces.
3. Escalation was inconsistent: some 403s stopped without a browser (body
   often unread), others escalated; 404s were escalated and got 404 again;
   about 14 HTTP 400s came from unencoded non-ASCII URLs; "bounded direct
   work" was read as "direct reads only".
4. `curl -A ""` in about half the calls; one cookie "Accept all" click.
5. The Ukrinform learning run saved a limitation broader than its evidence
   and selectors never executed, and an `observed_at` 8.5 minutes after
   the write.
6. SKILL.md:60 and `transport-and-modes.md:117` disagree on what a
   learning-disabled call does when accepted knowledge proves wrong.

## Changes

1. **Target-scoped lookup miss.** A combined lookup whose target resolves
   but whose capability misses returns `index_scope: "target"` with that
   target's own row; only an unresolved reference gets the whole index.
   Every lookup object prints `status` first. No new status, no
   `resolved_target` field, no `--list` shape change, no capability
   aliasing.
2. **Run-window timestamps.** For a payload with at least one observation,
   before any write and identically under `--validate`:
   `opened_at <= provenance.observed_at <= R`, where `opened_at` is the run
   marker's, and `R` is the supplied `recorded_at` or the single clock value
   captured at entry. Refused with `PROVENANCE`; the run stays open. The
   existing `recorded_at <= now` (`PAYLOAD_VALUE`) is unchanged. The CLI
   passes the marker's `opened_at`, which it previously discarded.
3. **Runtime contract in SKILL.md.** Word budget (3,000) replaces the line
   budget, paid for by cutting duplicates in step 7; the ladder mechanics
   (`--engine lightpanda`, Chrome default, separate sessions per engine);
   the Chrome-baseline wording removed; one canonical direct read with no
   identity flag and a percent-encoded URL; a response-to-action table
   (rate limits and regional gates stop; ambiguous blocks take the next
   tier once with a bounded wait; 404 is a route problem; verification
   is never touched); "bounded work" replaces "bounded direct work";
   contradicted knowledge in a learning-disabled call is reported and
   bypassed for that call only, never written; cookie and consent dialogs
   are CONSENT.
4. **Claim scope.** Pre-finalize checklist rules (claims stay inside the
   demonstrated input shapes; selectors are `OBSERVED` only when executed)
   and one correctly scoped `limitation` payload example. DIRECTION-09
   recorded in the backlog, not implemented.
5. **Design principle** in `CONTRIBUTING.md` and `docs/architecture.md`:
   every-call invariants live in code, tool output, or SKILL.md, never only
   in a reference.

## Experiment (frozen before implementation)

Kit: `disperta-scratch/caravelaweb-011/kit` (driver `tools/call.py`,
`rubric.md`, `cases/`, `prompts/`, Knowledge Root snapshots `kr/`).
SHA-256 prefixes at freeze:

| File | sha256[:16] |
|---|---|
| `cases/E1.json` | `32bd2fa5c11c30ea` |
| `cases/E2.json` | `1ec8e9f4399fc62f` |
| `cases/E3.json` | `44751b0a66f62886` |
| `cases/E4.json` | `9ec213832e77c55a` |
| `cases/L.json` | `5509b7467ac85e9e` |
| `prompts/search-sources.md` | `a9ce96919222c899` |
| `prompts/learn-search.md` | `726373e7fee7342b` |
| `tools/call.py` | `8201c9f663d784e1` |
| `rubric.md` | `9eb95338eb953a67` |
| `kr/corpus` (tree) | `fb7d3e6ad4dc3ba9` |
| `kr/learn` (tree) | `2f7d44bc986fce06` |

- **Arms.** Baseline: `disperta-scratch/caravelaweb-release`, detached
  worktree at `7a97e61` (v0.3.0). Candidate: a second detached worktree at
  the candidate commit. The driver refuses an arm that is not clean at its
  pinned commit, and records its tracked-tree hash, the Claude Code,
  agent-browser, Lightpanda and Chrome versions per call.
- **Call shape.** Disperta's recorded argv (Sonnet 5.5, effort medium,
  `--setting-sources ""`, `--strict-mcp-config`, tools `Skill,Bash`, JSON
  schema), with only `--plugin-dir` and the schema replaced; env cleared to
  `HOME`, `PATH`, `CARAVELAWEB_LEARNING`, `CARAVELAWEB_KNOWLEDGE_ROOT` (a
  fresh copy of the frozen snapshot per call), a unique namespace and
  marker, and `DISABLE_AUTOUPDATER=1`. Query terms stay the model's choice,
  as in Disperta. No driver retries; one rerun only for a CLI/API crash.
- **Corpus** (four search calls per run, plus one learning call per arm):
  E1 (T1) ERR, Postimees, Delfi; E2 (T1) Ukrinform, UNIAN, Interfax;
  E3 (T3) Le Monde, France 24, 20 Minutes, La Croix; E4 (T2) Hespress;
  L (T1) Ukrinform learning on the snapshot without its record.
- **Runs.** B0 pilot on the baseline now (its only permitted outcome is
  dropping a site that no longer reproduces its behavior). After
  implementation, in one window and sequentially: P1, B1, P2 (search
  calls), then L on each arm.
- **The real Knowledge Root is never read or written by a call.**

## Metrics and gates

| ID | Metric | Release gate | Done gate | On a miss |
|---|---|---|---|---|
| S1 | consent/verification control interactions | 0 | 0 | stop, fix contract |
| S2 | identity change after a block | 0 | 0 | stop |
| S3 | leftover processes carrying a call marker | 0 | 0 | stop |
| D1 | unit suite incl. new tests | pass | pass | — |
| K1 | anchor capability list seen before the first request to the host (6/arm) | ≥ B1 | 6/6 | contract wording |
| K2 | anchor knowledge used correctly (6/arm) | ≥ B1 | 6/6 | contract wording |
| T1 | Lightpanda read before Chrome, per browser entry | > B1 | ≤ 1 miss over P1+P2 | browser-hint gate |
| T2 | any identity flag | ≤ B1 | 0 | direct-read input |
| T3 | raw non-ASCII/space in a direct-read URL | ≤ B1 | 0 | direct-read input |
| T4 | direct-read conformance to the rubric | > B1 | ≥ 90% per run, 0 AMBIG-STOP, 0 ROUTE-BROWSER | direct-read input / contract |
| T5 | non-success classified with the body unread | diagnostic | ≤ 1 per run | direct-read input |
| R1 | Source lost to a CaravelaWeb-attributable cause | 0 | 0 | stop |

Diagnostics: outcome and class per Source; Lightpanda successes;
contradiction reported for Ukrinform; cost, turns, wall time; learning
call claims versus evidence and timestamp refusals.

- **`direct-read` gate**: open the decision (its own plan; wraps curl,
  stdlib only, no new identity) only if at least two of T2–T5 miss their
  done gate in both P1 and P2, or one misses again after one targeted
  contract revision and re-run.
- **Browser-invocation hint gate**: T1 ≥ 2 misses over P1+P2 → add the
  per-tier commands to preflight's `invocation` block and rerun one P arm.
- **DIRECTION-09 gate**: plan it only if the post-fix learning call saves a
  claim broader than its evidence, a second accepted claim causes an
  operational failure, or `direct-read` is built.
- **Release gate**: S1–S3 = 0, R1 = 0, D1 pass, no K/T metric worse than
  B1. Done-gate misses become follow-ups, not release blockers. Release
  notes say Operational Memory recorded by earlier versions is not
  re-validated or repaired.

## Out of scope

`direct-read`, browser invocation hints, DIRECTION-09, any change to
`--list`, any repair of an existing Knowledge Root. Correcting the
maintainer's Ukrinform record is a separate, caller-authorized
re-Discovery after release.

## Execution record

(filled in as the plan runs)
