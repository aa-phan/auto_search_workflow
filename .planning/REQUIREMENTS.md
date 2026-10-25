# Requirements: Auto Search Workflow

**Defined:** 2026-10-24 (ingested from repo docs; see `.planning/intel/requirements.md` for the full derivation)
**Core Value:** A relevant job reaches the user within `Fresh_Window_Hours` (12) of its source publication, and nothing of unverified age is ever presented as fresh.

The repo documents are the authority: `SPEC.md` (contract), `DECISIONS.md` (D-01..D-47), `STATUS.md` (what is verified). Each requirement points at them; if one of these entries and those documents disagree, the documents win and this file is corrected.

Verification legend: **live** = checked against production or real services (STATUS.md); **mocked** = offline tests only (`python -m unittest discover -s tests`, 525 tests).

## v1 Requirements (shipped 2026-10-24; pilot week 1 passed 2026-10-15..22)

### Polling and identity

- [x] **POLL-01**: Poll every monitored board hourly through the ATS public APIs (Greenhouse, Lever, Ashby, Workable, SmartRecruiters) and detect unseen job IDs; gaps recorded, detection conditional (SPEC "Loops", "Honest limits"; D-06, D-34). *Live: 168/168 hourly intervals, 0.31% of 103,500 board polls failed; hourly cadence carried by the external trigger.*
- [x] **POLL-02**: Job identity is ATS + board + posting ID; URLs and tracking parameters are not identity (SPEC "Identity and dedupe"; D-01, D-12; AGENTS rule 3). *Live outcome (0 duplicate alerts); URL variants mocked.*
- [x] **POLL-03**: A newly admitted or re-entering board is baselined, never backfilled (SPEC "Baselining"; D-05, D-24). *Live: 113k+ baseline identities, D-47 refill runs added 5,273 and 6,919 IDs with no alert flood.*

### Freshness

- [x] **FRESH-01**: One freshness class at first observation from source publication evidence; update, crawl and search dates are never publication time (SPEC "Freshness vocabulary"; D-04, D-05, D-17, D-24; AGENTS rule 2). *Live for the pilot population (D-42 reconciliation); boundary cases mocked.*
- [x] **FRESH-02**: Only `verified_fresh` jobs inside the 12 h window alert (SPEC "Goal"; D-17). *Live: publication -> detection median 29 min, p90 54 min (n=310).*

### State and delivery

- [x] **STATE-01**: Seen / evaluated / alerted are separate retryable stages from an append-only ledger; transient failures retried, permanent ones bounded at 5; at-least-once delivery (SPEC "State model"; D-03, D-07, D-21; AGENTS rule 4). *Mocked only: no real outage observed. Two code paths conflict with this contract, see REL-01, REL-02.*
- [x] **STATE-02**: One registry writer at a time (shared concurrency group, advisory lease, local production writes refused) (D-28, D-31, D-37). *Mocked only; the Sheet lease is not atomic.*
- [x] **DLVR-01**: Append-only Job Tracker of jobs scoring >= 50, columns found by header name, user columns never written, missing header stops the run (SPEC "Delivery"; D-07, D-44, D-46). *Live: header-name placement verified 2026-10-23 22:03 UTC; header-missing refusal mocked.*
- [x] **DLVR-02**: One Telegram alert per verified-fresh job scoring >= `Min_Alert_Score`, late deliveries labelled (SPEC "Delivery"; D-21). *Live: 20 sent, 0 failed, 1 labelled late.*

### Filtering and scoring

- [x] **FILT-01**: Title gate before fetch, then hydration, then hard rules (age, excluded words, non-US, 4+ years, foreign language) (SPEC "Filtering order"; D-08, D-25). *Live funnel: 19,380 -> 472 relevant -> 260 scored -> 47 kept -> 20 alerted; broadened Settings of 2026-10-23 checked offline only.*
- [x] **FILT-02**: Groq scores survivors 0-100 against the resume in the Sheet (`openai/gpt-oss-120b`, fallback `gpt-oss-20b`) (D-16). *Live success path (260 scored); 429 fallback and model-not-found mocked.*

### Board registry and allocation

- [x] **BRD-01**: Persistent `Boards` registry seeded from two public inventories, validated through the adapters with two budgeted queues (D-11, D-13, D-15, D-29). *Live: 5,000-board re-check run 2026-10-24, 176 boards gained relevant jobs.*
- [x] **BRD-02**: One admission path for every source; promotion only within `Max_Active_Boards` and `Max_New_Boards_Per_Run` (D-14, D-19). *Live: 50 per run up to 700.*
- [x] **BRD-03**: Established / exploration pools, 7-day trials, weekly bounded rebalance with graduation floor 2.0, early release of below-floor ended trials (SPEC "Weekly rebalance"; D-23, D-26, D-30, D-32, D-45, D-47). *Live: early release (220 trials, 2026-10-24 08:00 UTC); the weekly cycle itself mocked until about 2026-10-29.*
- [x] **BRD-04**: Tavily discovery rotation within a persistent monthly credit ledger (D-18, D-20, D-35, D-36). *Live: 140 credits in 7 days.*
- [x] **BRD-05**: Provider limits honoured: Lever crawl delay, 429 stops a provider for the run, SmartRecruiters parked by default (unparked by D-38) (D-13, D-27, D-37, D-38). *Mocked only for 429 and parking; SmartRecruiters polling live.*

### Operations

- [x] **OPS-01**: Output-only Dashboard tab rebuilt after each run from pure `reporting.py` (D-40, D-41). *Live: rendered and inspected in the real Sheet.*
- [x] **OPS-02**: Independent missed-run watchdog with one outage and one recovery message (D-42). *Mocked only; live read path dry-run verified; Telegram delivery and a real outage not verified.*
- [x] **OPS-03**: Read-only pilot, storage and rebalance reports with windows and populations on every figure (D-39, D-42, D-43). *Live: run against the production Sheet.*

### Security and data

- [x] **SEC-01**: Secrets and personal data never read, printed or committed; resume lives only in the Sheet; workflows read-only toward the repo (AGENTS rule 6; D-09, D-37). *Live repo scan. Repository is public (checked 2026-10-24) and no job-search CSV exists anywhere in git history.*

## v2 Candidates (unscheduled; scope chosen by `/gsd-new-milestone`)

Items marked **[gated]** tune scores or add features and are held by AGENTS.md rule 7 / STATUS.md until the evidence items are read; lifting the gate is an owner decision recorded in DECISIONS.md.

### Evidence (read before changing parameters)

- [ ] **EVID-01**: Read the first weekly rebalance (about 2026-10-29 01:00 UTC): graduations vs the floor, replacements vs the bound, no move on thin evidence (STATUS "Next milestone"; D-30, D-45).
- [ ] **EVID-02**: Limits at 700 boards: run duration vs the 25 min timeout, Sheets reads per minute, Events growth (STATUS "Next milestone"; CONCERNS "Run duration").
- [ ] **EVID-03**: Live effect of the broadened Settings: relevant jobs per day, share scored 50+, tracker rows per day against the 20-30 target, leaks of sales / support titles (PILOT_LOG 2026-10-23 21:21).
- [ ] **EVID-04**: D-47 follow-up: early releases at the weekly cycle, refill, baseline-driven Events growth (D-47).
- [ ] **EVID-05**: Evaluate the user's `My_Feedback` labels against AI score, title, location, freshness and source, to decide whether the 50 / 70 cut-offs fit (user request 2026-10-24; read-only).
- [ ] **EVID-06**: Use re-check flip statistics to choose the re-check interval and budget (D-39; CONCERNS "Validation backlog").

### Reliability (contract fixes)

- [ ] **REL-01**: Record `alerted` only when a channel accepted the message (CONCERNS bug 1; SPEC "Delivery"; AGENTS rule 4).
- [ ] **REL-02**: Bound alert failures without an HTTP response at 5 attempts (CONCERNS bug 2; SPEC "State model").
- [ ] **REL-03**: Cap free-text fields before HTML escaping instead of cutting the joined message at 4,096 characters (CONCERNS bug 3).
- [ ] **REL-04**: Second external trigger for the watchdog plus one real test notification (DEPLOY "Watchdog"; owner action).
- [ ] **REL-05**: Close live-test gaps: Groq 429 fallback, weekly rebalance at 700, message length and entities, replay and dashboard time at 100k+ Events rows (CONCERNS "Test Coverage Gaps").

### Storage

- [ ] **STOR-01**: Decide and, if approved, build the D-43 storage proposal (Identity tab, Daily counters, archive) with the parallel-run migration, before Events nears the D-03 review point and the 10M-cell limit (D-03, D-43).

### Features and filtering [gated]

- [ ] **FEAT-01**: Daily Telegram digest (SPEC "Not built"). [gated]
- [ ] **FILT-03**: Title-gate leaks such as "Community Associate" (CONCERNS bug 5; Settings-level). [gated]

### Maintenance

- [ ] **MAINT-01**: Split `hunter.py` (1,981 lines) into Groq client, Sheet store and alert modules with no behaviour change; narrow broad exception handlers in the state path (CONCERNS "Tech Debt").
- [ ] **MAINT-02**: Pin GitHub Actions by commit SHA and lock Python dependency versions; drop unused `pyyaml` (CONCERNS "Supply chain"; STACK.md).

### Governance

- [ ] **GOV-01**: Record open owner decisions in DECISIONS.md: OK for the Groq models (D-16); resume text sent to Groq in every scoring call; SmartRecruiters polling after the pilot (D-38 was scoped to the pilot); repository public with clean history; D-30 values confirmed or changed; D-43 storage decision.

## Out of Scope

From SPEC.md "Out of scope for now" unless an owner decision changes it:

| Feature | Reason |
|---------|--------|
| Tuning scores | AGENTS.md rule 7 gate; needs EVID-05 evidence and an owner decision first |
| Additional ATSs (Workday, BambooHR, ...) | SPEC scope; inventories list them but no adapters |
| Non-US markets | Hard gate excludes them by design (D-08) |
| Email / SMS, web UI | The Sheet and Telegram are the only interfaces (SPEC "Goal") |
| Parity with job boards | SPEC "Honest limits": only polled boards have the hourly guarantee |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| POLL-01..03, FRESH-01..02, DLVR-01..02, FILT-01..02, BRD-01..04, OPS-01, OPS-03, SEC-01 | v1.0 (pre-GSD work, Phase 1) | Validated (live) |
| STATE-01, STATE-02, BRD-05, OPS-02 | v1.0 | Validated (mocked only) |
| EVID-01..06, REL-01..05, STOR-01, FEAT-01, FILT-03, MAINT-01..02, GOV-01 | v2 (to be scoped) | Candidate |

**Coverage:** v1 20 validated; v2 17 candidates, 0 mapped to phases yet.

---
*Requirements defined: 2026-10-24 by /gsd-ingest-docs (merge)*
