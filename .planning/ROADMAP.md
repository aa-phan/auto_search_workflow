# Roadmap: Auto Search Workflow

## Milestones

- ✅ **v1.0 Board-polling alerts** — shipped 2026-10-24 (pilot week 1 passed 2026-10-15..22)
- 📋 **v2** — to be defined with `/gsd-new-milestone` (candidates in `.planning/REQUIREMENTS.md`)

## Phases

<details>
<summary>✅ v1.0 Board-polling alerts — SHIPPED 2026-10-24</summary>

Most of v1.0 predates GSD tracking; its history is the decision log (`DECISIONS.md` D-01..D-47), `STATUS.md` and `PILOT_LOG.md`, not phase directories.

- **Pre-GSD work (D-01..D-22, 2026-10-14):** board-polling pipeline with verified freshness and retryable delivery, inventory-seeded registry with validation, rotating budgeted discovery, 12 h window.
- **Phase 1: Board slot allocation** (quick task `261014-olj`, 2026-10-14, `.planning/quick/261014-olj-board-slot-allocation/`): pools, evidence refresh, bounded weekly rebalance, queues, SmartRecruiters parking (D-23..D-30). Complete.
- **Post-Phase-1 work (D-31..D-47, 2026-10-14..24):** correctness pass, Tavily, deployment and pilot tooling, dashboard, watchdog, tracker header fixes, graduation floor, early release.

Requirements validated: POLL-01..03, FRESH-01..02, STATE-01..02, DLVR-01..02, FILT-01..02, BRD-01..05, OPS-01..03, SEC-01 (see REQUIREMENTS.md for live vs mocked).

</details>

### 📋 v2 (planned)

Not yet scoped. Run `/gsd-new-milestone` to choose goals from the v2 candidates and create phases. Evidence items (EVID-01..06) come first under AGENTS.md rule 7; the first weekly rebalance is due about 2026-10-29 01:00 UTC.

## Progress

| Milestone | Phases | Status | Shipped |
|-----------|--------|--------|---------|
| v1.0 Board-polling alerts | 1 tracked (+ pre/post-GSD work) | Complete | 2026-10-24 |
| v2 | — | Not started | — |
