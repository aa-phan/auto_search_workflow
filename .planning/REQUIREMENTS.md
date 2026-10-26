# Requirements: Auto Search Workflow

**Defined:** 2026-10-24 (v1.0, ingested from repo docs; see `.planning/intel/requirements.md`); v2.0 scope added 2026-10-25
**Core Value:** A relevant job reaches the user within `Fresh_Window_Hours` (12) of its source publication, and nothing of unverified age is ever presented as fresh.

The repo documents are the authority: `SPEC.md` (contract), `DECISIONS.md` (D-01..D-47), `STATUS.md` (what is verified). Each requirement points at them; if one of these entries and those documents disagree, the documents win and this file is corrected.

Verification legend: **live** = checked against production or real services (STATUS.md); **mocked** = offline tests only (`python -m unittest discover -s tests`, 525 tests).

## Validated: v1.0 (shipped 2026-10-24; pilot week 1 passed 2026-10-15..22)

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

## v2.0 Requirements: Search-substitute volume

Goal: 20-30 relevant jobs posted within the last 72 hours reach the Job Tracker every day; Telegram alerts stay verified-fresh within 12 h. Principle: volume over precision as long as every job is recent. Research: `.planning/research/SUMMARY.md`. The Groq daily token cap bounds the target until MEAS-02 is settled.

### Measurement and governors

- [ ] **MEAS-01**: The Dashboard shows tracker rows per day, age when found and the My_Feedback mix, with backfilled / recent rows reported separately from verified-fresh rows
- [ ] **MEAS-02**: The Groq account's real limits and tokens per call are measured and the Groq plan decision is recorded
- [ ] **MEAS-03**: Each run records Groq tokens used; a daily token budget keeps runs under the Groq limit
- [ ] **MEAS-04**: Evaluation and polling stop before the 25-minute timeout; verified-fresh jobs are scored first and unscored jobs stay retryable
- [ ] **MEAS-05**: A job is recorded `alerted` only when a channel accepted the message, and alert failures without an HTTP response are bounded at 5 attempts (CONCERNS bugs 1 and 2)

### Evidence

- [ ] **EVID-01**: The first weekly rebalance (about 2026-10-29) is read before board cycling changes
- [ ] **EVID-05**: My_Feedback labels are compared with AI score, title, source and freshness before any score changes

### 72-hour window and backfill

- [ ] **WIN-01**: Relevant jobs published within 72 h (`Tracker_Window_Hours`) enter the tracker; alerts stay within the 12 h window
- [ ] **WIN-02**: A newly admitted or re-entering board's jobs posted within 72 h are scored and labelled instead of only baselined (amends D-05)
- [ ] **WIN-03**: Every tracker row shows its publication time, its precision (exact or date only) and a live age; a `Job_Key` column (ATS|board|ID) carries identity
- [ ] **WIN-04**: Reposted and evergreen jobs (repost key, talent-pool titles) are labelled in the tracker and never alerted
- [ ] **WIN-05**: Jobs that leave the 72 h window before scoring are closed without a Groq call (`aged_out`)

### Storage

- [ ] **STOR-01**: Baseline and identity-only rows are stored compactly (Identity and Tally tabs, D-43 amended), parity is proven before old rows retire, and Events stays below the D-03 review point

### Scale

- [ ] **SCALE-01**: `Max_Active_Boards` rises in measured steps (1,000, then 1,400), each step gated on run duration, Sheets and Groq metrics

### Board cycling

- [ ] **CYC-01**: The board score includes relevant postings from the last 72 h read from the listing, for waiting boards as well as monitored ones
- [ ] **CYC-02**: My_Feedback labels influence the board score (bounded weight, minimum label count), run in shadow beside the current score before going live
- [ ] **CYC-03**: Trials shorten and boards cycle faster once evidence supports it, with the exploration floor protected

### Search

- [ ] **SRCH-01**: The search rotation covers its role and site slots within the 72 h window, weights slots by past yield and includes the new ATS hosts

### New ATS adapters

- [ ] **ADPT-01**: An adapter registry exists; the five existing providers produce byte-identical job keys (golden tests); permanent errors mark a board invalid; each new provider has a robots gate and a circuit breaker
- [ ] **ADPT-02**: Breezy boards are polled (time-precise publication)
- [ ] **ADPT-03**: Gem boards are polled (time-precise publication)
- [ ] **ADPT-04**: Oracle Recruiting Cloud boards are polled (date only)
- [ ] **ADPT-05**: Workday boards are polled (date only, requisition-ID identity)
- [ ] **ADPT-06**: Rippling and BambooHR boards are polled via a per-job detail fetch for the date
- [ ] **ADPT-07**: Date-only jobs enter the tracker when their date falls within 72 h, labelled "date only", and may alert when posted today or yesterday on a board polled within 12 h (existing D-04c rule; user decision 2026-10-25)

### Governance

- [ ] **GOV-01**: Owner decisions are recorded in DECISIONS.md: Groq plan, the D-05 amendment, the rule-7 lift for board-cycling scores only, per-ATS policy (Paycom skipped, iCIMS deferred), SmartRecruiters after the pilot, repository public, date-only alerts

## Future Requirements (deferred)

- **FEAT-01**: Daily Telegram digest
- **FILT-03**: Further title-gate tuning (Settings-level; can happen any time)
- **MAINT-01**: Split `hunter.py` without behaviour change
- **MAINT-02**: Pin GitHub Actions and Python dependencies; drop unused `pyyaml`
- **REL-03**: Cap free-text fields before HTML escaping in Telegram messages
- **REL-04**: Second external watchdog trigger and a real test notification
- **REL-05**: Remaining live-test gaps (Groq 429 fallback, message entities)
- **EVID-06**: Re-check interval from flip statistics
- **ADPT-08**: iCIMS, Recruitee, JazzHR adapters
- **SCALE-02**: Polling cadence tiers; closed-job marking in the tracker

## Out of Scope

| Feature | Reason |
|---------|--------|
| Paycom adapter | robots.txt `Disallow: /` covers the listing API |
| Teamtailor, Personio, JOIN, SuccessFactors adapters | Little US volume, bot challenge or HTML-only on customer domains (research/STACK.md) |
| LinkedIn / Indeed scraping | Terms of service; aggregator dates are not publication time |
| Lowering Min_Alert_Score or the tracker threshold to hit the number | Rule 7: needs EVID-05 evidence and an owner decision |
| External database | Not needed while the compact Sheet design holds; revisit only on a named trigger (Identity > ~25 MB, load > ~60 s, double-writer incident) |
| Non-US markets, email / SMS, web UI | SPEC scope |
| Alerting on jobs not verified fresh within 12 h | Core value (date-only jobs alert only through the existing D-04c rule) |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| (filled by the roadmap) | | |

| v1.0 validated | Status |
|----------------|--------|
| POLL-01..03, FRESH-01..02, DLVR-01..02, FILT-01..02, BRD-01..04, OPS-01, OPS-03, SEC-01 | Validated (live) |
| STATE-01, STATE-02, BRD-05, OPS-02 | Validated (mocked only) |

**Coverage:** v2.0 requirements: 29 total; mapped to phases: 0 (pending roadmap).

---
*Requirements defined: 2026-10-24 (v1.0); v2.0 scope 2026-10-25*
