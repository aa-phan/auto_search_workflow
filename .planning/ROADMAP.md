# Roadmap: Auto Search Workflow

## Milestones

- ✅ **v1.0 Board-polling alerts** — shipped 2026-10-24 (pilot week 1 passed 2026-10-15..22)
- 🚧 **v2.0 Search-substitute volume** — Phases 2-7 (in progress)

## Overview

v2.0 turns the hourly verified-fresh alert poller into a substitute for manual searching: 20-30 relevant jobs posted within the last 72 hours reach the Job Tracker every day, while Telegram alerts stay verified-fresh within 12 hours. Volume over precision, as long as every job is recent.

Two limits shape the order. **Groq evaluation throughput is the binding limit** (about 40-55 evaluations a day per model on the published free-tier cap against about 110-165 needed; unverified for this account), so the milestone first measures and governs evaluation (Phase 2) and the 20-30 a day target stays conditional on the Groq plan decision (MEAS-02). **The Events ledger passes the D-03 200k-row review point about 2026-10-29** (186,430 rows on 2026-10-25, growing about 3,355 rows a day, 84.5% baseline identities), so compact storage (Phase 3) comes right after Phase 2 and before backfill, board growth and new adapters, all of which add rows or load.

The order is therefore: governors and decisions, compact storage, 72-hour window and backfill, evidence-led board growth, adapter registry and first-wave adapters, large-employer adapters and wider search.

## Phases

<details>
<summary>✅ v1.0 Board-polling alerts — SHIPPED 2026-10-24</summary>

Most of v1.0 predates GSD tracking; its history is the decision log (`DECISIONS.md` D-01..D-47), `STATUS.md` and `PILOT_LOG.md`, not phase directories.

- **Pre-GSD work (D-01..D-22, 2026-10-14):** board-polling pipeline with verified freshness and retryable delivery, inventory-seeded registry with validation, rotating budgeted discovery, 12 h window.
- **Phase 1: Board slot allocation** (quick task `261014-olj`, 2026-10-14, `.planning/quick/261014-olj-board-slot-allocation/`): pools, evidence refresh, bounded weekly rebalance, queues, SmartRecruiters parking (D-23..D-30). Complete.
- **Post-Phase-1 work (D-31..D-47, 2026-10-14..24):** correctness pass, Tavily, deployment and pilot tooling, dashboard, watchdog, tracker header fixes, graduation floor, early release.

Requirements validated: POLL-01..03, FRESH-01..02, STATE-01..02, DLVR-01..02, FILT-01..02, BRD-01..05, OPS-01..03, SEC-01 (see REQUIREMENTS.md for live vs mocked).

</details>

### 🚧 v2.0 Search-substitute volume (In Progress)

**Milestone Goal:** 20-30 relevant jobs posted within the last 72 hours reach the Job Tracker every day, enough to replace manual searching, while Telegram alerts stay verified-fresh within 12 hours.

**Phase Numbering:** v1.0 ended at Phase 1, so v2.0 starts at Phase 2. Integer phases are planned milestone work; decimal phases (2.1, 2.2) are urgent insertions.

- [x] **Phase 2: Measurement, governors and owner decisions** - See what reaches the tracker and what Groq can really evaluate, keep runs inside the Groq budget and the timeout, fix the two alert-recording bugs, record the owner decisions (completed 2026-10-28)
- [ ] **Phase 3: Compact storage** - Move baseline and identity-only rows to compact Identity and Tally tabs with proven parity, before any board growth
- [ ] **Phase 4: 72-hour window and recent backfill** - Recent jobs (up to 72 h) reach the tracker with their real age, including a newly admitted board's recent postings
- [ ] **Phase 5: Evidence-led board growth** - Read the first rebalance and the feedback evidence, then cycle boards by recent activity and feedback and grow the monitored set past 700 in measured steps
- [ ] **Phase 6: Adapter registry and first-wave adapters** - A registry with golden tests, then Breezy, Gem and Oracle Recruiting Cloud, with date-only admission rules in place
- [ ] **Phase 7: Large-employer adapters and wider search** - Workday, Rippling and BambooHR, and a yield-weighted search rotation that includes the new ATS hosts

## Phase Details

### Phase 2: Measurement, governors and owner decisions

**Goal**: The owner can see how many recent relevant jobs reach the tracker each day and what Groq can really evaluate, and the evaluation and alert paths stay inside the Groq budget, the run timeout and the delivery contract before any change adds load.
**Depends on**: Nothing (first v2.0 phase; v1.0 shipped)
**Requirements**: MEAS-01, MEAS-02, MEAS-03, MEAS-04, MEAS-05, GOV-01
**Entry gates**: none.
**Notes**: (a) The Groq limits can only be read from the account page and from real call usage; no live Groq claim without credentials (AGENTS rule 5). (b) MEAS-01 counts tracker rows, so first explain the 2 ledger-kept jobs missing from the tracker (reconciliation flag in STATUS.md, 2026-10-25). (c) The Events 200k-row point and the first weekly rebalance (about 2026-10-29) arrive during this phase: watch them through the daily checks; the formal rebalance read is EVID-01 in Phase 5, the storage work is Phase 3. (d) Phase 3's design, Sheets large-read spike and parity tooling touch no shared code and may be planned while this phase executes.
**Success Criteria** (what must be TRUE):
  1. The Dashboard shows tracker rows per day, how old each job was when found, and the My_Feedback mix, with non-verified-fresh ("Recent") rows reported apart from verified-fresh rows, and the row count reconciles with the ledger's kept jobs (checked in the real Sheet).
  2. The Groq account's real limits (tier, requests, tokens per minute and per day) and the measured tokens per scoring call are written down with their source, the Groq plan decision is recorded, and STATUS.md states the evaluations per day that supports and the tracker rows per day the 20-30 target can honestly claim.
  3. Every run records the Groq tokens it used and stops evaluating at a daily token budget below the Groq limit; polling and evaluation stop before the 25-minute timeout, verified-fresh jobs are scored first, and every unscored job stays pending and is picked up by the next run (shown with a forced-limit test, and with figures from a live run).
  4. A job is recorded `alerted` only after a channel accepted the message; a send that fails without an HTTP response leaves the job unalerted, is retried, and stops after 5 attempts.
  5. Every owner decision the milestone needs is either recorded in DECISIONS.md or listed with its needed-by phase and its default if unanswered: Groq plan, D-05 amendment (before Phase 4), rule-7 lift for board-cycling scores only (before CYC-02 goes live), per-ATS policy (Paycom skipped, iCIMS deferred; before each adapter), SmartRecruiters after the pilot, repository public or private, date-only alerts (user decision 2026-10-25); the storage design approval that closes the D-03 review (before Phase 3 executes) is surfaced with them.

**Plans**: 9/9 plans complete (waves 1-9, sequential: every plan edits the contract documents)

Plans:
**Wave 1**
- [x] 02-01-PLAN.md — GOV-01: owner-decision inventory D-48 and public-repository doc corrections

**Wave 2** *(blocked on Wave 1 completion)*
- [x] 02-02-PLAN.md — MEAS-05: alerted only when a channel accepted; no-response sends bounded at 5 (P2-18); secret redaction; Telegram caps (D-49)

**Wave 3** *(blocked on Wave 2 completion)*
- [x] 02-03-PLAN.md — MEAS-03: per-model Groq daily token budget with verified-fresh reserve and fallback; token Runs columns (D-50)

**Wave 4** *(blocked on Wave 3 completion)*
- [x] 02-04-PLAN.md — MEAS-04: process-anchored poll / evaluation / alert cutoffs, longest-unpolled-first polling, Groq client deadline (D-51)

**Wave 5** *(blocked on Wave 4 completion)*
- [x] 02-05-PLAN.md — MEAS-01: Dashboard yield view (tracker rows per day by cohort with 20-30 band, age when found, feedback per cohort, reconciliation) (D-52)

**Wave 6** *(blocked on Wave 5 completion)*
- [x] 02-06-PLAN.md — MEAS-02/03: Groq read-outs on the Dashboard and in the pilot report; STATUS offline-verification section

**Wave 7** *(blocked on Wave 6 completion)*
- [x] 02-07-PLAN.md — Deploy with the owner's consent and record live evidence (Runs columns, Dashboard render, reconciliation, delivery test)

**Wave 8** *(blocked on Wave 7 completion)*
- [x] 02-08-PLAN.md — MEAS-02 / GOV-01: measured Groq usage, account limits read by the owner, Groq plan decision D-53, measured budget default

**Wave 9** *(blocked on Wave 8 completion)*
- [x] 02-09-PLAN.md — GOV-01: deploy SmartRecruiters parking after the first weekly rebalance read (superseded by D-54: owner kept SmartRecruiters; nothing deployed)

### Phase 3: Compact storage

**Goal**: The Events ledger stops growing toward its limit: baseline and identity-only postings live in compact Identity and Tally tabs with parity proven against the old rows, so board growth and new adapters can be admitted safely.
**Depends on**: Phase 2
**Requirements**: STOR-01
**Entry gates**: storage design approved and recorded (D-43 amended; this closes the D-03 200k-row review). Phase 3 never overlaps Phase 4: both touch `ledger.observe_new` and the run-cycle observation block.
**Notes**: Clock: about 2026-10-29 Events passes 200k rows. D-43 already measured and proposed this design, and cell headroom is large (13.1% of the 10M-cell limit, load time 10 s at 186k rows against a 25-minute timeout), so crossing the point first is a recorded review state, not an outage. Until parity is accepted there is no board growth beyond 700, no admission waves beyond the existing refill and no new-adapter boards. Keep `Events_Legacy` until parity holds; nothing is deleted before then.
**Success Criteria** (what must be TRUE):
  1. A hidden `Identity` tab holds each board's baseline and identity-only posting IDs in chunks under the cell limit, and each run writes a `Tally` row with the counts the reports need; a poller run on the new storage detects no already-seen job as new and sends no alert twice.
  2. A read-only `--storage-parity` check reports zero differences between the seen set, state counts and Dashboard figures derived from the old Events rows and from Identity and Tally, on every run for several consecutive days of dual writing.
  3. Only after parity: baseline and identity-only rows are retired by swapping the old tab to `Events_Legacy` (kept and restorable), Events is back well below the D-03 review point, and the storage report shows rows, allocated cells and load time before and after with the daily growth in cells falling by an order of magnitude (D-43 estimate: about 26,200 to about 1,300 cells a day).
  4. A run interrupted in the middle of a board's baseline never makes that board's old postings look new on the next run (a board counts as baselined only after its last chunk is written).

**Plans**: 5/9 plans executed (waves 1-9, sequential: shared storage modules and contract documents; 03-05, 03-08 and 03-09 are live and need the owner)

Plans:
**Wave 1**
- [x] 03-01-PLAN.md — Dual-write core: compact.py (Identity codec, Tally, merged view), Identity/Tally tabs, Events -> Identity -> Tally -> Boards, interrupted baseline (SC4), D-57

**Wave 2** *(blocked on Wave 1 completion)*
- [x] 03-02-PLAN.md — Seed and repair, in-run parity layers 1-3, the 3-day parity clock, degraded on a difference (P3-05, P3-07, P3-09)

**Wave 3** *(blocked on Wave 2 completion)*
- [x] 03-03-PLAN.md — Every report from the merged view (Dashboard, pilot reconciliation, storage counts) and parity layer 4 (P3-10, P3-11)

**Wave 4** *(blocked on Wave 3 completion)*
- [x] 03-04-PLAN.md — Dashboard Storage line / READY TO CUT OVER / NEEDS ATTENTION, read-only --storage-parity and its input, docs and STATUS before deploy

**Wave 5** *(blocked on Wave 4 completion)*
- [x] 03-05-PLAN.md — Deploy dual writing with the owner's consent; live seed and first parity result

**Wave 6** *(blocked on Wave 5 completion)*
- [ ] 03-06-PLAN.md — Owner-triggered cutover (copy, verify, atomic tab swap to Events_Legacy) and the pre-fold restore (P3-06, P3-08, P3-14)

**Wave 7** *(blocked on Wave 6 completion)*
- [ ] 03-07-PLAN.md — 7-day fold, storage report before/after with allocated cells, compact-mode integrity check (P3-01, P3-03, P3-12)

**Wave 8** *(blocked on Wave 7 completion)*
- [ ] 03-08-PLAN.md — Deploy the cutover tooling with the owner's consent (dual mode unchanged)

**Wave 9** *(blocked on Wave 8 completion and the parity bar)*
- [ ] 03-09-PLAN.md — Owner's cutover, first fold and the measured before/after (live)

### Phase 4: 72-hour window and recent backfill

**Goal**: A relevant job published within the last 72 hours reaches the tracker with its real age, including the recent jobs of a newly admitted or re-entering board, without being presented as verified-fresh and without delaying any real alert.
**Depends on**: Phase 2, Phase 3
**Requirements**: WIN-01, WIN-02, WIN-03, WIN-04, WIN-05
**Entry gates**: D-05 amendment recorded under its own D-number (listed as pending in D-48) and the Groq plan known (Phase 2); storage parity accepted (Phase 3). SPEC "Baselining" and "State model", DECISIONS and STATUS change in the same change as the code; PILOT_LOG entry for the deployment (it changes the rows per day measurement).
**Notes**: No new freshness class: backfilled jobs are `RECENT` with a backfill marker, a stored publication time and precision, and a separate reporting cohort (research reconciliation). Backfill never starves live alerts: verified-fresh jobs are scored first and backfill takes a capped share of the daily token budget (Phase 2). Boundary tests at 71, 72 and 73 hours and for board re-entry.
**Success Criteria** (what must be TRUE):
  1. A relevant job published 13 to 72 hours ago (by its source publication time) appears in the Job Tracker (`Tracker_Window_Hours`, default 72), while a Telegram alert is still sent only for a verified-fresh job inside the 12-hour window.
  2. Every tracker row shows its publication time, its precision (exact or date only) and an age that keeps advancing in the Sheet, and carries a `Job_Key` column (ATS|board|ID); rows already in the tracker keep working because columns are found by header name.
  3. When a board is first admitted or re-enters, its postings with a source publication time within 72 hours are scored newest first and labelled with their real age instead of being baselined silently; older postings are still baselined; none of them alerts, and a verified-fresh job detected during the same run is still scored first and alerted inside 12 hours.
  4. A recent job that leaves the 72-hour window before it is scored is closed as `aged_out` with no Groq call and is not counted as abandoned or failed.
  5. Reposted and evergreen postings (repost key, talent-pool titles) are labelled in the tracker and never alerted.

**Plans**: TBD

### Phase 5: Evidence-led board growth

**Goal**: More of the boards that actually post recent relevant jobs are polled, chosen by their recent activity and the user's feedback, at a monitored-set size that run duration, the Sheet and Groq can carry.
**Depends on**: Phase 2, Phase 3, Phase 4
**Requirements**: EVID-01, EVID-05, CYC-01, CYC-02, CYC-03, SCALE-01
**Entry gates**: storage parity accepted (Phase 3) before any `Max_Active_Boards` step; backfill live (Phase 4) so a newly admitted board's recent jobs are scored instead of baselined away; the rule-7 lift for board-cycling scores only (not the Groq score or `Min_Alert_Score`) recorded before CYC-02 goes live.
**Notes**: Order inside the phase: evidence read first (EVID-01, EVID-05), then CYC-01, then the 1,000 step with CYC-02 shadowing during its soak, then CYC-02 live and CYC-03, then the 1,400 step. D-30 values are provisional until the first weekly rebalance is read. Research suggests p95 run duration below 12.5 minutes (half the timeout) as a step gate; Phase 2 data sets the real constants. Mocked tests prove the score arithmetic and the floor; only live runs prove step behaviour.
**Success Criteria** (what must be TRUE):
  1. The first weekly rebalance report (due about 2026-10-29) has been read (graduations against the 2.0 floor, replacements against the bound, no board moved on thin evidence) and the My_Feedback labels have been compared with AI score, title, source and freshness; both findings are written into STATUS.md before any cycling change.
  2. A waiting board's score and a monitored board's score both include its relevant postings from the last 72 hours read from the listing, and the rebalance or pool report shows that component per board.
  3. The feedback-influenced board score runs in shadow beside the current score with a bounded weight and a minimum label count, the report shows which boards each score would admit or release, and it goes live only after that comparison is read.
  4. Trials end sooner and boards cycle faster, while the 20% exploration floor still admits new boards every cycle (a report and a feedback-dominated test show the exploration slots filled).
  5. `Max_Active_Boards` rises 700 to 1,000 to 1,400 one step at a time; each step records p95 run duration, load time, Sheets reads per minute, Groq tokens and transient errors, and the next step starts only when they are inside their limits (a step that is not is rolled back).

**Plans**: TBD

### Phase 6: Adapter registry and first-wave adapters

**Goal**: Jobs from Breezy, Gem and Oracle Recruiting Cloud boards reach the tracker under the same identity, freshness and retry rules as the five existing providers, with date-only sources admitted by the agreed rule.
**Depends on**: Phase 3, Phase 4
**Requirements**: ADPT-01, ADPT-02, ADPT-03, ADPT-04, ADPT-07
**Entry gates**: storage parity accepted (Phase 3) before any new-adapter board is admitted; per-ATS policy decision recorded for each provider before its adapter is built (Paycom skipped, iCIMS deferred); date-only rule (ADPT-07) live before the first Oracle row reaches the tracker. This phase starts with an Actions-runner smoke probe.
**Notes**: The registry work (ADPT-01) touches `boards.py`, not the ledger, and may start during Phase 5's soak periods. All endpoints were verified only from a laptop IP: the probe from a GitHub Actions runner decides whether each adapter is viable. Gem and Oracle need a second look before an alert relies on them. Wave 1 comes before Phase 7.
**Success Criteria** (what must be TRUE):
  1. Golden tests show the five existing providers produce byte-identical job keys through the adapter registry; a permanent error marks a board invalid while a bot challenge or transient error never does; every new provider has a per-tenant robots gate and a circuit breaker.
  2. Before any board is admitted, a `workflow_dispatch` probe from a GitHub Actions runner has recorded HTTP status and payload shape for one board per new ATS in STATUS.md, and a read-only yield check (title-gate pass rate on about 20 boards per ATS) says how many pool slots each deserves.
  3. Breezy and Gem boards are polled hourly, and their time-precise postings enter the tracker with exact precision and alert only when verified fresh within 12 hours.
  4. Oracle Recruiting Cloud boards are polled, and their postings carry a date only.
  5. A date-only job enters the tracker when its date falls within 72 hours, labelled "date only", and alerts only when it was posted today or yesterday on a board polled within 12 hours (the D-04c rule).

**Plans**: TBD

### Phase 7: Large-employer adapters and wider search

**Goal**: The biggest employer sites (Workday), the detail-fetch providers (Rippling, BambooHR) and the boards the poller does not monitor (web search) contribute recent jobs to the tracker, bounded by recorded policy and by what the free tiers allow.
**Depends on**: Phase 5, Phase 6
**Requirements**: ADPT-05, ADPT-06, SRCH-01
**Entry gates**: Actions-runner smoke probe for Workday, Rippling and BambooHR recorded; per-ATS policy (Workday robots and terms, Rippling, BambooHR) recorded before each adapter; ADPT-07 live (Phase 6) before any Workday row reaches the tracker; storage parity accepted (Phase 3).
**Notes**: Workday has 3,530 boards, a 2,000-posting cap per board, an unreliable listing order (no early stop on order) and relative-text dates in the list, so Phase 5's cycling decides which boards get slots. Rippling and BambooHR need a per-job detail fetch for the date, limited to unseen postings that pass the title gate. SRCH-01 has no code dependency on Workday and may be planned in parallel with Phases 5-6; only its host list is extended last. Search is mainly a board-discovery path: at about 10.8 days per pass over 216 slots against a 72-hour window, the plan must state partial coverage if slots times revisit interval do not fit.
**Success Criteria** (what must be TRUE):
  1. Workday boards are polled with a stable requisition-ID identity, "Posted Today", "Yesterday" and "N Days Ago" read as a date range, "30+ Days Ago" never treated as fresh, and paging bounded by the 2,000 cap; its rows are labelled "date only" and alert only under the D-04c rule.
  2. Rippling and BambooHR boards are polled, the per-job detail is fetched only for unseen postings that pass the title gate, and a posting whose date is missing or unparsable stays unverified and is never shown as fresh.
  3. The search rotation covers its role and site slots, weights slots by their past yield, stays inside the Tavily credit budget and the 72-hour window (or states the partial coverage), and includes the new ATS hosts.

**Plans**: TBD

## Sequencing Rules (every phase inherits these)

- **Documents stay authoritative.** SPEC.md, DECISIONS.md and STATUS.md are updated in the same change as any behaviour change (AGENTS rule 1); a conflict is flagged to the owner before behaviour changes.
- **Tests and honesty.** `.venv/bin/python -m unittest discover -s tests` passes offline before a phase is finished; each phase states which checks were mocked and which hit real services, and makes no live claim for Sheets, Groq or Telegram without credentials (AGENTS rule 5).
- **PILOT_LOG.** Every deployment that affects a measurement gets a PILOT_LOG.md entry.
- **Scope gate.** The Groq score and `Min_Alert_Score` stay untuned (AGENTS rule 7) unless EVID-05 evidence and an owner decision say otherwise; board-cycling scores are in scope only after the recorded rule-7 lift.
- **No parallel ledger work.** Phase 3 and Phase 4 both touch `ledger.observe_new` and the run-cycle observation block and never overlap.
- **Board growth is gated.** No `Max_Active_Boards` step, admission wave or new-adapter board before storage parity (Phase 3); growth comes after backfill (Phase 4) so admitted boards' recent jobs are scored.
- **Adapters.** The registry (ADPT-01) precedes every new adapter; wave 1 (Phase 6) precedes Workday and the detail-fetch adapters (Phase 7); each adapter phase opens with an Actions-runner smoke probe; ADPT-07 precedes any Oracle or Workday row reaching the tracker.

## Owner Decisions (GOV-01) and When Each Is Needed

All are surfaced in Phase 2. Each is recorded in DECISIONS.md before the work it gates. The list, with each item's state, is DECISIONS.md D-48 (2026-10-26).

| Decision | Recorded before | Default if unanswered |
|----------|-----------------|-----------------------|
| Groq plan and budget (free or paid, limits, D-16 model OK) | Recorded: D-53 (2026-10-28): free now, revisit before Phase 4; budget 100,000 per model | Decided; the 20-30 a day target stays conditional (about 12 kept rows a day at the measured figures) |
| Storage design (D-43 amended; closes the D-03 200k review) | Phase 3 execution (point reached about 2026-10-29) | Proceed with the D-43 design; nothing is deleted before parity |
| D-05 amendment (backfill on first baseline and re-entry; out-of-window jobs closed without scoring) | Phase 4 (WIN-02) | No backfill; the rest of Phase 4 can proceed |
| Date-only alerts through the D-04c rule (user decision 2026-10-25) | Phase 2 record; in force before the first Oracle row (Phase 6) | Tracker only, no alert |
| Per-ATS policy: Paycom skipped, iCIMS deferred, Teamtailor, Personio, JOIN and SuccessFactors skipped; terms for Breezy, Gem, Oracle, Workday, Rippling, BambooHR | Phase 6 start (wave 1), Phase 7 start (Workday, Rippling, BambooHR) | Build only providers with a recorded decision |
| Rule-7 lift for board-cycling scores only | Before CYC-02 goes live (Phase 5) | The feedback score stays in shadow |
| SmartRecruiters after the pilot | Phase 2 | Recorded: D-54 (2026-10-28), kept and polled (reverses P2-14) |
| Repository visibility (public now, DEPLOY.md says private) | Phase 2 | Stay public, keep logs free of job content |

## Requirement Coverage

| Phase | Requirements | Count |
|-------|--------------|-------|
| 2. Measurement, governors and owner decisions | MEAS-01, MEAS-02, MEAS-03, MEAS-04, MEAS-05, GOV-01 | 6 |
| 3. Compact storage | STOR-01 | 1 |
| 4. 72-hour window and recent backfill | WIN-01, WIN-02, WIN-03, WIN-04, WIN-05 | 5 |
| 5. Evidence-led board growth | EVID-01, EVID-05, CYC-01, CYC-02, CYC-03, SCALE-01 | 6 |
| 6. Adapter registry and first-wave adapters | ADPT-01, ADPT-02, ADPT-03, ADPT-04, ADPT-07 | 5 |
| 7. Large-employer adapters and wider search | ADPT-05, ADPT-06, SRCH-01 | 3 |
| **Total** | | **26 of 26 mapped** |

## Progress

**Execution Order:**
Phases execute in numeric order: 2 → 3 → 4 → 5 → 6 → 7 (decimal insertions run between their integers). Allowed overlaps: Phase 3 planning and spikes during Phase 2; ADPT-01 and SRCH-01 work during Phase 5's soak periods. Phases 3 and 4 never overlap.

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Board slot allocation | v1.0 | 1/1 | Complete | 2026-10-14 |
| 2. Measurement, governors and owner decisions | v2.0 | 9/9 | Complete    | 2026-10-28 |
| 3. Compact storage | v2.0 | 5/9 | In Progress | - |
| 4. 72-hour window and recent backfill | v2.0 | 0/TBD | Not started | - |
| 5. Evidence-led board growth | v2.0 | 0/TBD | Not started | - |
| 6. Adapter registry and first-wave adapters | v2.0 | 0/TBD | Not started | - |
| 7. Large-employer adapters and wider search | v2.0 | 0/TBD | Not started | - |
