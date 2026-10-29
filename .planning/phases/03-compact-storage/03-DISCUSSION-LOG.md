# Phase 3: Compact storage - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-10-29
**Phase:** 3-Compact storage
**Areas discussed:** What leaves Events, Parity bar and cutover, What reports must keep, D-43 parts in or out

---

## What leaves Events

| Option | Description | Selected |
|--------|-------------|----------|
| Baselines + gated + stale | D-43 as written; steady growth about 26k -> 1.3k cells a day | ✓ |
| Baselines only | Simplest; Events keeps growing several thousand rows a day | |
| You decide | | |

**User's choice:** Baselines + gated + stale

| Option | Description | Selected |
|--------|-------------|----------|
| At once, ID only | Smallest storage; no gate-rejection audit trail | |
| Full row 30 days, then compact | Covers every report window; a month of audit | ✓ (later revised to 7 days) |
| You decide | | |

**User's choice:** 30 days, then revised (see below).

| Option | Description | Selected |
|--------|-------------|----------|
| Straight to Identity | Baselines are 93% of rows, arrive in admission bursts, no report reads their titles | ✓ |
| Same 30-day rule as gated | One rule, but admission waves sit in Events for a month | |

| Option | Description | Selected |
|--------|-------------|----------|
| Hidden + warning protection | Hand edits ask for confirmation; service account writes normally | ✓ |
| Hidden only | As Events today | |
| You decide | | |

**Revision (raised by Claude before writing context):** at D-43's 7.17 identity-only rows per board per day, a 30-day window holds about 150k rows at 700 boards and breaks "well below 200k" once Phase 5 grows the board count. Folded rows must also really be deleted (copying them to Events_Legacy saves no cells).

| Option | Description | Selected |
|--------|-------------|----------|
| 7 days | About 35k rows at 700 boards; covers 7-day views; Tally gives 8-30-day totals | ✓ |
| Keep 30 days | Roadmap wording needs changing; breaks with Phase 5 growth | |
| At once, ID only | Smallest; no audit trail | |

---

## Parity bar and cutover

| Option | Description | Selected |
|--------|-------------|----------|
| 3 full UTC days, every run | About 72 runs, at least one admission or refill | ✓ |
| 7 full days | Covers a weekly rebalance; about 65k more rows meanwhile | |
| You decide | | |

| Option | Description | Selected |
|--------|-------------|----------|
| You trigger it | Dashboard / STATUS say ready; workflow input; own PILOT_LOG row | ✓ |
| Automatic once the bar is met | Faster, unwatched | |

| Option | Description | Selected |
|--------|-------------|----------|
| Degraded run, clock resets | Old Events authoritative; NEEDS ATTENTION with keys | ✓ |
| Log only, clock resets | Quieter, easier to miss | |

| Option | Description | Selected |
|--------|-------------|----------|
| Keep it, decide later | Hidden, restorable; removal is a later owner decision | ✓ |
| Delete after N days with an export | Frees cells; needs an export target; rollback floods | |

| Option | Description | Selected |
|--------|-------------|----------|
| First run after deploy | Seeds from the loaded ledger under the lease; no owner step | ✓ |
| Separate command you dispatch | More control; one more owner step | |
| You decide | | |

---

## What reports must keep

| Option | Description | Selected |
|--------|-------------|----------|
| Every reported number | Seen set, state counts, Dashboard, pilot funnel, storage report identical | ✓ |
| Seen set + Dashboard only | Smaller Tally; reports drift in labelled ways | |

| Option | Description | Selected |
|--------|-------------|----------|
| Counts from Tally, labelled | Totals exact; per-job detail beyond the kept window labelled unavailable | ✓ |
| Cap reports at 30 days | Loses all-time funnel and long pilot reports | |

---

## D-43 parts in or out

| Option | Description | Selected |
|--------|-------------|----------|
| Archiving out, deferred | Operational rows about 164 a day; a second migration not needed now | ✓ |
| Archiving in Phase 3 | Bigger phase touching alert and retry rows | |

| Option | Description | Selected |
|--------|-------------|----------|
| `Tally`, one row per run | Matches roadmap; run-level exclusion and parity | ✓ |
| `Daily`, one row per day | Fewer rows; runs can't be excluded | |

---

## Claude's Discretion

Tally column encoding; Identity row layout and keying of board-less search jobs; enforcement of the last-chunk rule; fold batching and deadline fit; `--storage-parity` output and where the clock is stored; cutover input wiring; how replay and reports merge Identity with kept rows.

## Deferred Ideas

- Archiving terminal operational rows (D-43 step 3)
- Removing Events_Legacy from the Sheet (export target, timing)
