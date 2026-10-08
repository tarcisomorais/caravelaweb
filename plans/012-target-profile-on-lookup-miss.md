# Plan 012: Return the accepted target profile on a lookup miss

> **Commit methodology**: one commit for the three changes below, which
> define one lookup reply, then one for the execution record; linear history,
> author and committer `Tarciso Morais <287870717+tarcisomorais@users.noreply.github.com>`,
> imperative sentence-case subject with no prefix and no period, a prose
> body wrapped at 76 columns with three paragraphs (observed problem, what
> changed and why, what tests now cover), and no trailers of any kind.
> Releasing is a separate step (version commit, CI, annotated tag,
> `gh release create`). It is **not** part of this plan's execution: the
> owner reviews the test results and acceptance findings first.

## Status

- **Priority**: P1. **Effort**: S for the change; the acceptance
  comparison is the cost.
- **Branch**: `plan-012`, from `7b08c1e` (0.4.1).
- **Closes**: CORRECTNESS-10 (an unresolved lookup prints the whole
  index). **Supersedes**: DIRECTION-11 (a target-scoped miss lists IDs,
  not verdicts).
- **Progress**: see "Execution record" at the end.

## Evidence

A Disperta `open` over Israeli and Palestinian Sources (2026-10-08,
Sonnet 5.5 medium, CaravelaWeb 0.4.1, learning disabled) improvised
search routes for Sources whose `search-articles` capability is
`OPERATIONAL`, with routes that still worked when re-tested. A
reproduction that captured the event stream showed why:

1. The agent passed Disperta Source IDs as `--target`. Seven of the 15
   IL/PS IDs are not target IDs (`israelhayom` is `israel-hayom-he`).
   Each such lookup answered with the whole index: 222,820 bytes on a
   snapshot of the real Knowledge Root (549 targets). The agent cut every
   reply with `head -c 1500` and never saw the target again.
2. It invented the capability `search-results`. The accepted names vary
   per target (`search-articles` 401, `site-search` 29,
   `site-search-articles` 1). A miss on a resolved target answered
   637 bytes: capability IDs and lifecycle, no route.
3. Only the Sources whose ID happened to be a target ID got a second
   lookup with the right name, and only those worked. The original run
   skipped the second lookup. Plan 011 saw the same step fail (P2) or
   come too late (P3). Wording was already tried once (`9f254a1`).
4. In its second loop the agent batched nine lookups with `head -c 3500`;
   the 30.4 KB output was persisted by the harness and shown as a 2 KB
   preview, and the agent wrote its own extractor to recover the
   records. Truncation is a property of batched calls, not only of one
   reply.

The root is a regression from 0.2.2. Plan 009 change 5 (`6856e87`)
collapsed `--list`, a target-only `--target` read ("the target-only call
already returns the accepted context of every capability") and the
capability call into one combined call. Since then the executor must
name a capability before it has seen the target's names, and a miss
withholds the record. CORRECTNESS-10 and DIRECTION-11 are its two
symptoms.

Disperta committed the caller half on 2026-10-08 (`88d21f7`): its
prompts identify a target by the hostname of the Source's `website`,
never by its ID, and name no capability. With that fix every IL/PS
Source resolves, but each still lands on the 637-byte row.

Measured on the Knowledge Root snapshot: the Markdown target profile
that every hit already carries is median 2.0 KB, p99 5.7 KB, max 11.1 KB
(`vpipe`, 15 capabilities). A miss carrying it would be median 2.7 KB
and max 13.6 KB, and a miss is always the hit minus one capability's
JSON, so it never exceeds a hit on the same target.

## Changes

1. **Profile on a resolved miss.** A combined `--target`/`--capability`
   lookup whose reference resolves carries that target's
   `markdown_projection` whether the capability is found or not. A hit
   already carries it (`integration_bridge.py`, `render_markdown(target)`
   renders the whole target). The miss gains the same field from the
   same function, with the same lifecycle trust filter. `status` stays
   `not_found`; the `index` row is unchanged. No new projection, no new
   status, no capability matching.
2. **Compact unresolved miss.** A combined lookup whose reference
   resolves to no target answers `index_scope: "none"` with no `index`.
   `"all"` is no longer produced. `--list` and the bare `--target` call
   keep their shape.
3. **Contract.** `SKILL.md` step 2: pass the task's URL or hostname,
   never a caller's own source ID; the `index_scope: "target"` row says
   `markdown_projection` holds every capability's accepted record and
   drops "look its ID up before acting"; the `index_scope: "none"` row
   says to retry with the URL or hostname, and to mint a target ID only
   after `--list` shows no exact one. No other wording is added: the
   acceptance comparison measures the deterministic change, not new
   instructions. `references/target-profile.md` is reconciled with that
   flow: its "run target-only `knowledge-lookup` before minting" rule
   predates 0.2.2 and is replaced by the combined call's profile, and
   the Knowledge Lookup section documents the new scope and field.

## Requirements added by the owner (2026-10-08)

**R1. Truncation is an acceptance risk, measured on real agent
behavior.** The fix only works if the accepted route reaches the model
before it navigates. A per-command cut (`head -c N`, `cut`, a Python
slice) or harness persistence of a large batched output (the 2 KB
preview) can hide the profile even when CaravelaWeb returns it. The
acceptance comparison scores exposure from the tool results the model
actually received, not from what CaravelaWeb printed. If the candidate
does not reliably expose the accepted knowledge before navigation,
**stop and reassess the response design**; do not add prompt wording.

**R2. The effect of the CaravelaWeb change is isolated.** Both arms run
the same Disperta version (`88d21f7`, which includes its hostname fix),
the same captured search-call input, the same Knowledge Root snapshot and
the same environment; only the plugin directory differs (baseline
`7b08c1e`, candidate this branch). Scored per arm: knowledge reuse,
transport selection, truncation, premature navigation and unnecessary
improvisation.

**R3. New-source Discovery does not regress.** Dropping the whole index
from the unresolved miss removes a soft duplicate guard. What remains,
and is tested:

- A task with a URL or hostname resolves an existing target through its
  recorded host, so its ID is never re-minted (scope `target`).
- The finalizer refuses to give a hostname that another target already
  owns to a new target (`HOST_SCOPE`, `discovery_finalize.py` host plan),
  so a duplicate that observes a known host cannot be saved.
- A reference that resolves to nothing gets scope `none`; the row tells
  the executor to retry with the URL or hostname, and to mint only after
  `--list`, which is unchanged, shows no exact ID to reuse.
- A first-time Discovery for a new target still begins, finalizes and is
  then found by its hostname with the profile on the miss.

Known residual, not introduced here: 11 targets in the real Knowledge
Root have no recorded host and cannot be found by hostname (filed as a
backlog item). The whole index did not prevent the apparent duplicates
already there (`npr`/`npr-org`, `politico-eu`/`politico-europe`,
`the-guardian`/`theguardian-com`).

## Tests

In `tests/test_target_identity.py` (synthetic roots):

1. Known target, wrong capability: scope `target`, its row, and a
   `markdown_projection` byte-equal to a hit's on the same target.
2. Bare `--target` keeps its shape, and its projection equals the miss's.
3. Unknown target ID: scope `none`, no `index`, no other target or host
   in the output, and the same bytes after 30 more targets are seeded.
4. A hostname or URL resolving to a known target: as test 1.
5. A target with several capabilities: every capability heading in the
   projection and every capability in the row.
6. `OPERATIONAL` and blocked capabilities on one target (payload examples
   8 and 6): the projection shows the trusted lifecycle under one and the
   `SITE_BLOCKING` fact under the other; the row shows `OPERATIONAL` and
   `null`.
7. Size: the unresolved reply stays under 512 bytes; a target-scoped miss
   is shorter than every hit on the same target.
8. Learning enabled and disabled: tests 1 and 3 answer identically apart
   from `learning`, and the database bytes are unchanged by lookups.
9. A pending-only capability: the existing test plus the projection.
10. Ordering and determinism: `status` leads, bulky values last, a `none`
    case added.
11. Disperta-shaped regression: `israel-hayom-he` on
    `www.israelhayom.co.il` with `search-articles` (Lightpanda
    `FUNCTIONAL`, direct read `FAILED`, an entrypoint): the Source ID
    `israelhayom` answers scope `none`; the URL with `search-results`
    carries `search-articles`, `LIGHTPANDA` and the entrypoint.
12. New-source Discovery (R3): a new target is begun and finalized after
    a scope-`none` miss and is then found by hostname; a duplicate target
    that observes a known host is refused with `HOST_SCOPE`.

In `tests/test_discovery_enforcement.py`: the step-2 pins follow the new
rows; the word budget holds.

## Acceptance comparison (frozen before any run)

**Input.** Disperta `88d21f7`, built from a clean export into a scratch
target directory. Its `open --discovery 000004 --topic 3` search call
(the reproduction's 22 GB/IL/PS Sources) is captured once (argv, prompt,
environment) and replayed byte-identical in both arms. Only
`--plugin-dir` differs. Each call gets a fresh copy of the Knowledge Root
snapshot, `CARAVELAWEB_LEARNING=disabled`, its own working directory and
browser namespace, and the same `PATH` Disperta builds.

**Runs.** Three pairs. The two calls of a pair start together, so both
arms meet the sites in the same window.

**Anchors.** Fixed from the captured prompt before any run: every Source
whose `website` hostname resolves to a target with an `OPERATIONAL`
search capability (an ID among `search-articles`, `site-search`,
`site-search-articles`; scoring vocabulary only, not product logic), and
every Source whose search capability records a block. The recorded
route token (a distinctive part of the entrypoint) and transport of each
anchor are listed in the execution record before the runs.

**Metrics** (per anchor per call, scored from the event stream):

| ID | Metric |
|---|---|
| E1 | exposure: the anchor's route token, or its block, appears in a tool result the model received before its first request to that host |
| E2 | reuse: the first request to the host uses the recorded route |
| E3 | transport: the first request uses the recorded working tier, skipping a tier recorded as failed |
| E4 | premature navigation: any request to the host before E1 holds |
| E5 | improvisation: a request to an unrecorded route before the recorded one |
| E6 | truncation: lookup output cut by the command or persisted by the harness, and whether an anchor's route was lost to it |
| O | the Source's status (`ok`, `no_route`, `failed`) and item count |

Also recorded: lookup calls, total tool calls, cost, Knowledge Root
copy unchanged (sha256), browser sessions closed.

**Gates.**

- **G1 exposure (R1)**: every candidate call has E1 on every anchor. A
  miss caused by truncation (E6) means **stop and reassess the response
  design**, not wording. A miss with another cause is recorded and
  assessed before any decision.
- **G2 isolation (R2)**: candidate ≥ baseline on E1, E2 and E3, and ≤
  baseline on E4 and E5, summed over the three pairs.
- **G3 safety**: no Knowledge Root write, no consent or verification
  interaction, no learning call.

## Out of scope

Fuzzy or semantic capability matching, new lifecycle states, a new
lookup projection, `--list` changes, Disperta changes, Knowledge Root
maintenance (host-less targets), the release and its tag.

## Execution record

**Commits** (branch `plan-012`): `26dce07` plan, `0c0b1ae` changes 1-3
with tests and contract (436 tests OK; the new tests fail on `7b08c1e`).
Nothing released or tagged.

**Harness.** Kit at `disperta-scratch/caravelaweb-012/`: Disperta
`88d21f7` exported and built into `target/`; its `open --discovery 000004
--topic 3` search call captured by a wrapper that records and fails it
(`capture/`), then replayed by `kit/run-call.sh` with only `--plugin-dir`
changed. Each call: a fresh export of the arm's commit, a fresh copy of
the KR snapshot (dump identical to the real root, `e5dee5a3...`),
`CARAVELAWEB_LEARNING=disabled`, its own namespace, Disperta's `PATH` and
1,200 s ceiling. Anchors frozen in `kit/anchors.json`; scored by
`kit/score.py` from the tool results the model received.

**Runs.** One pair, both calls started 2026-10-08T16:55:40Z. The owner
stopped pairs 2 and 3 once pair 1 and a deterministic measurement had
settled the R1 question (below). A CPU-bound job unrelated to the probe
held about 7 of 8 cores during the pair; both arms shared it.

| Metric | baseline `7b08c1e` (p1-a) | candidate `0c0b1ae` (p1-b) |
|---|---|---|
| E1 exposure before first request | 16/16 | 16/16 |
| E2 recorded route first | 16/16 | 16/16 |
| E3 recorded tier first | 16/16 | 16/16 |
| E4 premature navigation | 0 | 0 |
| E5 improvised requests | 0 | 0 |
| block anchors seen before a request | 1/2 (curled Sky search first) | 2/2 |
| lookup commands / cut by the command / persisted | 6 / 6 / 1 | 5 / 5 / 2 |
| first batched lookup reply received | 13.2 KB, every row visible | 36.4 KB persisted, 2 KB preview (one row) |
| Sources ok / no_route | 18 / 4 | 20 / 2 |
| tool calls, duration, cost | 63, 972 s, $1.74 | 46, 857 s, $1.28 |
| KR unchanged, leftover sessions, plugin-dir writes | yes, none, none | yes, none, none |

**Mechanism.** Both agents ran `--list | head -100` (one 219 KB line,
persisted), then one loop over all 21 hostnames with the invented
`search-results` and `head -c 1800` per reply, then name-specific lookups
built from the index rows, which hit. Every anchor was exposed by those
hits, in both arms. The candidate's profile never reached the model: on
the snapshot each anchor's route sits 2,218-3,673 bytes into its miss
reply, beyond the 1,800-byte cut for all 18 anchors, and the loop's 21
replies summed to 36.4 KB, which the harness persisted. The candidate's
second-round extractor did fall back to `markdown_projection` on a miss,
but every lookup it made was a hit, so the fallback never ran. Source
outcome differences (Sky News, Al-Quds) are search effort, not knowledge
reuse.

**Gates.** G1 holds by the letter (16/16) but not by its intent: the
change did not expose the knowledge; the agent's second lookups did, as
in the baseline. G2: candidate equals baseline on E1-E5. G3 passes. R1
therefore triggers: **STOP, reassess the response design; no wording
added.** Unresolved references (`index_scope: "none"`) were not exercised
live, because every hostname resolved.

**Findings for the reassessment.**

1. The agent's read budget is about 1.5-1.8 KB per reply and about 30 KB
   per batched command (13.2 and 24 KB were delivered, 30.4 and 36.4 KB
   persisted). A miss payload that must work in a batch has to put its
   decision facts in the first ~1.5 KB and stay near 1 KB per target.
2. The full Markdown profile (median 2.0 KB, routes 2.2-3.7 KB in) cannot
   meet that budget, and in a batch it hid even the index rows.
3. With Disperta's hostname fix, the baseline reached every record by the
   second lookup this run. This morning's skipped second lookup followed
   first replies dominated by whole-index dumps for unresolved Source IDs.
4. A compact per-capability summary (lifecycle, working and failed tiers,
   entrypoint, block class) measures median 421 bytes, p99 658, max 1,897
   per target on the snapshot, and 14.2 KB for the 21-Source batch. It
   drops long constraints (ynet's fill-and-Enter), so the name-specific
   hit stays useful. It is a new projection and is not built.

**Recommendation (owner decision).** Keep change 2 (`index_scope:
"none"`, closing CORRECTNESS-10) and the step-2 identity rule; revert
change 1 (profile on a miss) and restore the target row's instruction to
look the listed equivalent ID up before acting. Keep DIRECTION-11 open
with findings 1 and 4 and a reopening condition: a hostname-resolved
anchor whose second lookup is skipped in a live call.
