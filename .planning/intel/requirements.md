# Requirements (synthesized intel)

Provenance note. The ingest set contains no PRD. Entries below are capability statements derived by reference from `SPEC.md` (the contract: Goal, Loops, Board registry, Discovery, Identity, Freshness, State model, Filtering, Delivery, Observability, Acceptance), with verification state taken from `STATUS.md`. The v2 candidates are derived from `STATUS.md` ("Next milestone", "Known gaps / risks") and `.planning/codebase/CONCERNS.md`. Nothing here is a new rule: the repo documents stay authoritative and each entry points at them.

Format note. Each entry has the standard fields plus one extension field requested for this ingest: `- verification:` (v1 entries only) with one of `live-verified`, `mocked-only`, `blocked`, followed by the evidence. STATUS.md "Blockers" is "None" (earlier credential and no-remote blockers were superseded by the 2026-10-15 deployment), so no v1 entry is currently `blocked`. "Live" means against production or real services, as STATUS states; "mocked" means offline fakes (`python -m unittest discover -s tests`, 525 tests per STATUS).

Status baseline: v1 shipped; pilot week 1 passed (2026-10-15 01:47 to 2026-10-22 01:47 UTC); post-pilot changes deployed 2026-10-23 (D-45, D-46) and 2026-10-24 (D-47).

## v1 requirements (shipped)

## REQ-fresh-window-alerts
- source: SPEC.md "Goal"; DECISIONS.md D-17; STATUS.md "Pilot week 1 result"
- description: Surface relevant jobs within `Fresh_Window_Hours` (default 12) of their source publication time to a non-technical user, with Google Sheets as the only interface (settings in, tracker out) and Telegram for push alerts of top matches.
- acceptance: SPEC "Acceptance": board poll -> new-ID detection -> keyword/eligibility gates -> scoring -> Sheet row -> Telegram alert, with baselining proven, freshness class correct per evidence, retries proven for scoring and alert failures, polling gaps recorded.
- scope: end-to-end product goal
- verification: live-verified. Pilot week 1: 20 alerts, 20 unique jobs, 0 duplicates, 0 failed sends; publication-to-detection median 29 min, p90 54 min (n=310 verified-fresh poll jobs); all time-precise relevant jobs 79% inside the window (n=402). Telegram receipt was not checked by the agent. Retry-for-failure parts: see REQ-state-ledger-retry (mocked-only).

## REQ-board-polling
- source: SPEC.md "Loops" (polling loop), "Honest limits"; DECISIONS.md D-06, D-34
- description: Poll every active board hourly, 24/7, listing all current jobs from the ATS public API and detecting job IDs not yet seen; detection is conditional (monitored, a scheduled poll ran, listing complete), not an hourly guarantee.
- acceptance: Polling gaps are recorded and late finds are labelled by class, not "fresh".
- scope: polling loop, five ATS adapters (Greenhouse, Lever, Ashby, Workable, SmartRecruiters)
- verification: live-verified. 168 of 168 hourly intervals had a successful poll in week 1; 207 runs all `ok`; 0.31% of 103,500 board polls failed. The hourly cadence is carried by an external trigger (168 `workflow_dispatch:external` vs 38 `schedule` runs, about every 4.4 h); only scheduled runs prove the GitHub schedule.

## REQ-freshness-classification
- source: SPEC.md "Freshness vocabulary", "Baselining", "Re-entry"; DECISIONS.md D-04, D-05, D-17, D-24
- description: Assign one freshness class (`verified_fresh`, `observed_new`, `recent`, `uncertain`, `stale`, `baseline`) at first observation from source publication evidence; update time, crawl time and search dates are never publication time; only `verified_fresh` alerts.
- acceptance: Boundary inclusive at 12 h 0 s; day-precision rule needs date within the last day AND board gap within window; re-entry pass follows D-24.
- scope: freshness, publication vs observation vs update vs republication
- verification: live-verified for the pilot population (reconciled counts in DECISIONS.md D-42: 25 verified-fresh jobs = 25 alerts); mocked for boundary cases (11:59 / 12:00 / 12:01, baseline exception, day precision, re-entry).

## REQ-job-identity-dedupe
- source: SPEC.md "Identity and dedupe", "Board registry"; DECISIONS.md D-01, D-12; AGENTS.md rule 3
- description: Job identity is ATS + board + posting ID (`ats|board(lowercase)|id`); URLs, hosts, slugs and tracking parameters are not identity; identity-bearing URL parameters are preserved; board identity is provider + region + identifier with provider-specific casing.
- acceptance: No duplicate alerts or tracker rows for the same posting.
- scope: identity, dedupe
- verification: live-verified for the outcome (0 duplicate alerts in 20; second manual run added 0 jobs); mocked-only for host/slug/URL-parameter variants (offline tests).

## REQ-baselining
- source: SPEC.md "Baselining"; DECISIONS.md D-05, D-24
- description: A newly admitted board's first successful poll records existing IDs as `baseline` (not evaluated, no backfill); only time-precise source dates inside the window are evaluated.
- acceptance: A new board never floods the user with its backlog.
- scope: new boards, re-entry
- verification: live-verified (production baselines: 113,549 baseline identities by 2026-10-17; 5,273 and 6,919 new IDs from the first D-47 refill runs, no alert flood).

## REQ-state-ledger-retry
- source: SPEC.md "State model"; DECISIONS.md D-03, D-07, D-21; AGENTS.md rule 4
- description: Seen, evaluated and alerted are separate, individually retryable stages derived from an append-only event ledger; a failure never marks a later stage done; transient failures are retried; permanent-looking failures are bounded at 5 attempts then abandoned; a pending retry is never dropped for age; delivery is at-least-once.
- acceptance: Retries proven for scoring and alert failures (SPEC Acceptance).
- scope: ledger, retries, delivery semantics
- verification: mocked-only. STATUS: "Transient-failure retry against a real outage: not observed"; pilot ended with 0 pending failures. CONCERNS.md records two code paths that conflict with this contract (see REQ-v2-alert-recording-fix and REQ-v2-alert-exception-bound).

## REQ-filtering-eligibility
- source: SPEC.md "Filtering order"; DECISIONS.md D-08, D-25
- description: Cheap title checks before any fetch, then hydrate the posting, then deterministic hard rules (age, excluded title, non-US location, minimum experience >= 4 years, required foreign language), then Groq scoring only for survivors.
- acceptance: Order preserved; seniority exclusions checked first.
- scope: title gate, eligibility rules
- verification: live-verified for the funnel (week 1: 19,380 new postings -> 472 relevant -> 212 rejected after reading -> 260 scored -> 47 kept -> 20 alerted); title-gate variants (Internship, Jr., Entry-Level) mocked plus sample titles only. The 2026-10-23 broadened Settings were checked offline against sample titles; live effect unmeasured.

## REQ-groq-scoring
- source: SPEC.md "Filtering order" step 4; DECISIONS.md D-16
- description: Score each surviving posting 0-100 against the resume in the Sheet using Groq (`openai/gpt-oss-120b` primary, `openai/gpt-oss-20b` fallback); a nonexistent model is a configuration problem.
- acceptance: Real postings scored with verdicts.
- scope: scoring client
- verification: live-verified for the success path (260 jobs scored in week 1); mocked-only for the 429 fallback and `model_not_found` handling. Owner OK for the model deviation (D-16) is not recorded.

## REQ-sheet-tracker-delivery
- source: SPEC.md "Delivery"; DECISIONS.md D-07, D-44, D-46
- description: Append-only `Job Tracker` of jobs scoring >= 50 (`To Apply` >= `Min_Alert_Score`, else `Stretch / Review`); user-owned columns (`My_Status`, `User_Notes`, `My_Feedback`) never written by the program; columns found by header name and may be reordered; a missing `Apply_URL` header stops the run (retryable) instead of writing by position.
- acceptance: Each value under its own header; header row intact; no duplicate rows on retry.
- scope: tracker, header contract
- verification: live-verified for header-name placement (D-46 verified live 2026-10-23 22:03 UTC, row 80, correct columns); mocked-only for the header-missing refusal path and duplicate scan (520+ offline tests, mutation checks). Two live data-placement defects (D-44, D-46) were repaired by hand before the code fixes.

## REQ-telegram-alerts
- source: SPEC.md "Delivery"; DECISIONS.md D-21
- description: One Telegram message per `verified_fresh` job scoring >= `Min_Alert_Score` (title, company, location, score, verdict, gaps, apply link, tracker link); late deliveries labelled "delivered late".
- acceptance: Alert marked delivered only after the channel accepted it.
- scope: alerts
- verification: live-verified (20 alerts sent, 0 failed, 1 labelled late). Not covered live: failure modes; CONCERNS.md Known Bugs 1-3.

## REQ-board-registry-inventory
- source: SPEC.md "Board registry"; DECISIONS.md D-11, D-13, D-15, D-29
- description: One persistent hidden `Boards` registry seeded from two public inventories (about 21,900 boards on five supported providers), validated through the ATS adapters (`valid`, `valid_empty`, `invalid`, `transient`), with two independently budgeted validation queues; imports additive and idempotent.
- acceptance: Re-import changes 0 rows; rows never deleted.
- scope: registry, inventory loop, validation
- verification: live-verified (public downloads, real ATS validations, a 5,000-board re-check run in 1,121 s on 2026-10-24: 176 gained, 67 lost relevant jobs). Weekly/daily inventory workflow is running on GitHub per STATUS deployment log.

## REQ-board-admission-promotion
- source: SPEC.md "Board admission (all sources)", "Polling budget and pools"; DECISIONS.md D-14, D-19
- description: Every source uses the same admission steps; promotion only within `Max_Active_Boards` and `Max_New_Boards_Per_Run`, most open eligible jobs first, never-tried boards first.
- acceptance: No source starts monitoring directly.
- scope: admission, promotion
- verification: live-verified (50 boards admitted per run through 700 cap; monitored 480 -> 679 of 700 on 2026-10-24).

## REQ-board-pools-rebalance
- source: SPEC.md "Polling budget and pools", "Weekly rebalance"; DECISIONS.md D-23, D-26, D-30, D-32, D-45, D-47
- description: Established/exploration pools, 7-day trials, board evidence from complete polls, weekly bounded rebalance with graduation floor 2.0, no decision on thin evidence, early release of below-floor ended trials between cycles when `Rebalance_Mode` is `on`.
- acceptance: SPEC "Weekly rebalance" rules; no board moves on thin evidence; replacement bound honoured.
- scope: slot allocation
- verification: live-verified for pool labelling, admission at 700 and D-47 early release (run 40076316737 released 220 trials, report predicted 221). mocked-only for the weekly cycle (graduation of about 274 trials, replacements, weak streaks): the first real weekly cycle is due about 2026-10-29 01:00 UTC. The D-30 parameters are unproven initial choices.

## REQ-discovery-rotation-search
- source: SPEC.md "Discovery", "Loops" (discovery loop); DECISIONS.md D-18, D-20, D-35, D-36
- description: Tavily rotation of site x role slots with a 3-day `start_date`, one request per slot, candidate retrieval only (freshness always from ATS hydration), boards and jobs processed independently, persistent monthly credit ledger (1,000 cap, 200 reserve, 10 per run).
- acceptance: Credits never exceed caps; exhaustion skips discovery while polling continues.
- scope: discovery, search credits
- verification: live-verified for request shape, credit use and pilot spend (140 credits in 7 days); the Tavily account counter lagged (still 0) so it cannot confirm local counts; search adds only a trickle by design.

## REQ-writer-serialization
- source: SPEC.md "Polling budget and pools" (Serialization); DECISIONS.md D-28, D-31, D-37
- description: Registry-writing workflows share concurrency group `job-hunter-state` (`cancel-in-progress: false`); every writing command takes an advisory writer lease; local writes against a production Sheet are refused (exit 4) unless explicitly allowed for a test Sheet.
- acceptance: One writer at a time; a running job is never cancelled.
- scope: concurrency, lease
- verification: mocked-only for the lease and local-write refusal (file lease uses real kernel locks in tests; the Sheet lease is documented as not atomic). The concurrency group is in production use but overlap behaviour was not specifically measured.

## REQ-provider-policy-backoff
- source: SPEC.md "Provider limits honoured", "Board registry"; DECISIONS.md D-13, D-27, D-37, D-38
- description: Lever `Crawl-delay: 1` enforced; HTTP 429 stops that provider for the run; SmartRecruiters is parked by default and unparked for this deployment by explicit owner decision (D-38).
- acceptance: Skipped boards keep state and are not counted as failures.
- scope: provider policy, rate limits
- verification: mocked-only for 429 backoff and parking (pilot had no ATS or Groq 429s); SmartRecruiters polling itself is live (94 of the first 500 monitored boards). Provider acceptance of polling is unknown (D-38).

## REQ-dashboard
- source: SPEC.md "Operational dashboard (D-40)"; DECISIONS.md D-40, D-41
- description: A generated, output-only `Dashboard` tab rewritten in one batch after each poller run (cards, four charts, today/7/30-day table, system lines, needs-attention list); nothing in the pipeline reads it; a refresh failure is contained.
- acceptance: Numbers computed by pure `reporting.py`; internal consistency checks printed; metric rules 1-8 in SPEC.
- scope: operational reporting
- verification: live-verified (rendered in a real Sheet and inspected in the signed-in Chrome; one Sheet, one browser size); request shapes mocked plus Google discovery-schema check; first-render tuning items remain open per STATUS.

## REQ-watchdog
- source: SPEC.md "Missed-run watchdog (D-42)"; DECISIONS.md D-42; DEPLOY.md "Watchdog"
- description: Independent `watchdog.yml` + `watchdog.py` judging the last successful production run against a 2-hour threshold, with one outage and one recovery Telegram message and its own hidden `Watchdog` tab.
- acceptance: Unreadable data sends nothing and exits 3.
- scope: missed-run detection
- verification: mocked-only for the state machine and delivery (fake store and notifier); the read path was verified live read-only (dry run: HEALTHY, last success 29 min earlier). Telegram delivery, incident tab creation and a real outage/recovery are not verified. The recommended second external trigger is not set up (owner action).

## REQ-pilot-measurement
- source: SPEC.md "Pilot measurements and deployment (D-37)"; DECISIONS.md D-39, D-42, D-43; PILOT_LOG.md
- description: Read-only `--pilot-report` (also a workflow input) measuring from the first production run, with distinct hourly intervals, latency with sample sizes, coverage with populations, limits audit, re-check flips and a reconciliation of headline counts; plus `--storage-report`, `--delivery-test` and the user-owned `My_Feedback` column.
- acceptance: Every figure carries its window and population; rehearsal runs and fixtures excluded.
- scope: pilot reporting
- verification: live-verified (reports run against the production Sheet, 2026-10-17 and 2026-10-23).

## REQ-secrets-and-data-hygiene
- source: AGENTS.md rule 6; DECISIONS.md D-09, D-37; DEPLOY.md section 0; SPEC.md "Pilot measurements and deployment"
- description: Never read, print or commit `.env`, `Resume.pdf`, `resume.txt`, service-account JSON; resume lives only in the Sheet; job-search CSVs untracked; workflows `contents: read` with no commit steps.
- acceptance: Git history scan finds no secrets; ignore rules cover the files.
- scope: secrets, personal data
- verification: live-verified by repository scan (D-37, CONCERNS.md positive checks); git history still contains three older job-search CSVs (repository intended private; see conflicts report on visibility).

## v2 candidates (from STATUS "Next milestone", "Known gaps / risks" and CONCERNS.md)

All v2 entries are unscheduled candidates, not decided scope. Items that tune scores or add features are gated by AGENTS.md rule 7 and STATUS.md ("No score tuning or new features until these are read"); the gate is flagged in the conflicts report.

## REQ-v2-first-weekly-rebalance-review
- source: STATUS.md "Next milestone" item 2; DECISIONS.md D-30, D-45
- description: Read the first real `rebalance_report` (due about 2026-10-29 01:00 UTC) and check graduations against the floor, replacements against the bound, and that no board moved on thin evidence.
- acceptance: Evidence recorded about the D-30 operating choices before any threshold changes.
- scope: allocation evidence

## REQ-v2-limits-at-700
- source: STATUS.md "Next milestone" item 3; CONCERNS.md "Run duration and quota headroom"
- description: Check run duration against the 25-minute timeout, Sheets reads per minute and Events growth at 700 boards, compared with the 500-board pilot (not directly comparable across 2026-10-23).
- acceptance: Measured values from `Runs` timing columns.
- scope: capacity limits

## REQ-v2-wider-settings-observation
- source: STATUS.md "Next milestone" item 4; PILOT_LOG.md (2026-10-23 21:21 UTC)
- description: Observe the live effect of the broadened title and location Settings: relevant jobs per day, share scored 50+, tracker rows per day (aim 20-30, pilot was about 7), Groq 429s, and whether sales/support/accounting titles still reach the tracker.
- acceptance: Live numbers replace the offline-only check.
- scope: Settings effect

## REQ-v2-d47-follow-up
- source: STATUS.md "Next milestone" item 5; DECISIONS.md D-47
- description: Watch the 2026-10-29 weekly cycle (about 274 graduations expected), Events growth from admitted boards' baselines, and tracker rows per day.
- acceptance: Recorded in STATUS.
- scope: D-47 verification

## REQ-v2-events-storage
- source: DECISIONS.md D-03, D-43; STATUS.md "Known gaps / risks"; CONCERNS.md "Events ledger growth"
- description: Decide and, if approved, implement the D-43 proposal (`Identity` tab of chunked IDs, `Daily` counters, archive of terminal operational rows) before Events nears the D-03 review point (about 200k rows; 140,668 rows at end of pilot) and the 10M-cell limit, using the D-43 parallel-run migration order.
- acceptance: Derived `seen` set, state counts and dashboard figures identical between old and new readers for several days before any deletion.
- scope: storage, scaling

## REQ-v2-alert-recording-fix
- source: CONCERNS.md "Known Bugs" 1; SPEC.md "Delivery"; AGENTS.md rule 4
- description: Record `alerted` only when a channel accepted the message (today `send_alert` returning False with no channel configured still records `alerted`, channel "none").
- acceptance: With no channel configured the job stays retryable; a test covers the branch. Owner to confirm because it changes SPEC-visible retry behaviour.
- scope: alert state

## REQ-v2-alert-exception-bound
- source: CONCERNS.md "Known Bugs" 2; SPEC.md "State model"
- description: Bound alert failures whose exception has no HTTP response (currently default status 500, so never recorded and retried forever).
- acceptance: Such failures reach the 5-attempt bound; mutation test on the classifier.
- scope: alert retry

## REQ-v2-telegram-truncation
- source: CONCERNS.md "Known Bugs" 3
- description: Cap free-text fields before escaping instead of cutting the joined HTML at 4,096 characters.
- acceptance: A message near the limit with entities is accepted by Telegram.
- scope: alert formatting (low likelihood)

## REQ-v2-watchdog-external-trigger
- source: STATUS.md "Pilot reliability and reporting fixes", "Blockers"; DEPLOY.md "Watchdog"; CONCERNS.md "Dependence on external triggers"
- description: Owner creates a second, external trigger for `watchdog.yml` on a scheduler different from the hunter's, and sends one real test notification so Telegram delivery, the incident tab and recovery are verified.
- acceptance: Watchdog delivery moves from mocked-only to live-verified.
- scope: monitoring independence

## REQ-v2-daily-digest
- source: SPEC.md "Not built (documented for later)"; STATUS.md "Operational dashboard (D-40)"
- description: Daily Telegram digest (documented in SPEC, not built).
- acceptance: not specified in the source.
- scope: operator reporting (feature: gated by AGENTS.md rule 7)

## REQ-v2-recheck-interval-evidence
- source: DECISIONS.md D-39; STATUS.md "Pilot week 1 result" (re-checks), "Known gaps / risks"; CONCERNS.md "Validation backlog"
- description: Use the recorded re-check flip statistics (`revalidation_stats`) to decide whether the 7-day re-check interval or budget should change; about 21,000 validated boards need re-checking.
- acceptance: Next improvement chosen from measured evidence (D-39).
- scope: waiting-list freshness

## REQ-v2-title-gate-leaks
- source: STATUS.md "Next milestone" item 4; CONCERNS.md "Known Bugs" 5
- description: Known title-gate leak: "Community Associate" (often front desk) passes the broadened Settings; exclusion list does not cover it.
- acceptance: not specified in the source.
- scope: filtering (tuning: gated by AGENTS.md rule 7; Settings-level change)

## REQ-v2-live-test-gaps
- source: CONCERNS.md "Test Coverage Gaps"; STATUS.md "Verification: mocked vs live"
- description: Close mocked-only gaps: Groq 429 fallback and `model_not_found`, weekly rebalance at 700 boards, alert-recording branches (no channel, non-HTTP exception), message length/entities, replay and dashboard time at 100k+ Events rows with the 700-board mix.
- acceptance: Each gap covered by a test or a labelled live check.
- scope: verification

## REQ-v2-hunter-modularization
- source: CONCERNS.md "Tech Debt"; AGENTS.md "Layout"; DECISIONS.md D-02
- description: Split `hunter.py` (1,981 lines) without behaviour change (Groq client, Sheet store, alert delivery to own modules), keeping `hunter.py` as the entry point; narrow broad `except Exception` handlers in the state path.
- acceptance: Existing tests pass before and after; behaviour identical.
- scope: tech debt

## REQ-v2-supply-chain-pinning
- source: CONCERNS.md "Supply chain"
- description: Pin GitHub Actions by commit SHA and pin or lock Python dependency versions.
- acceptance: not specified in the source.
- scope: supply chain

## REQ-v2-owner-decisions-record
- source: CONCERNS.md "Security Considerations", "Fragile Areas"; DECISIONS.md D-16, D-38; STATUS.md "Deployment and pilot status"
- description: Record owner decisions that are open or unrecorded: OK for the Groq model deviation (D-16); Groq handling of resume text sent in every scoring prompt (D-09 covers storage only); reconfirmation of the D-38 SmartRecruiters risk with the pre-agreed reversal; intended repository visibility; a second protection rule on the tracker header row (owner action).
- acceptance: Each recorded in DECISIONS.md.
- scope: governance
