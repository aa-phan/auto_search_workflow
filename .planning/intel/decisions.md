# Decisions (synthesized intel)

Synthesized from `DECISIONS.md` (type ADR, manifest precedence 0; 47 entries D-01..D-47). Every entry is LOCKED by manifest assertion (the file is an append-only log with no per-entry status field). This file does NOT restate the rules as new rules: each entry is a pointer plus a one-line decision statement. The repo document remains authoritative; read the named D-number for the reasoning, evidence and consequences.

Reading rules applied (from the ingest brief):
- A later D-number that explicitly amends or supersedes an earlier one is not a contradiction. The latest in the chain is authoritative; the chain is recorded in `status`.
- Where `SPEC.md` and an older decision differ because a newer decision changed SPEC, SPEC (current contract) wins; recorded as auto-resolved in `.planning/INGEST-CONFLICTS.md`.
- `DECISIONS.md` lists D-10 after D-16 (file order is not numeric order); all of D-01..D-47 are present.
- Source path for every entry: `/Users/aphan/auto_search_workflow/DECISIONS.md`.

## D-01: Refactor in place; do not restart
- source: DECISIONS.md (D-01)
- status: locked
- decision: Keep ATS adapters, Settings/query builder/Groq client/Telegram/Sheet bootstrap/date parsing; replace identity/dedupe and the single-result state model (with a seen/evaluated/alerted ledger); modify discovery into two loops, the freshness gate and the CSV fallback; keep the `legacy/` keyword scorer archived and reuse only deterministic eligibility rules. Not a rewrite.
- scope: refactor scope, component keep/modify/replace verdicts

## D-02: New code lives in separate modules
- source: DECISIONS.md (D-02)
- status: locked
- decision: New concerns go in `boards.py`, `freshness.py`, `ledger.py`, `eligibility.py`, `state.py`, `pipeline.py` (all side effects injected); `hunter.py` stays the entry point (config, hydration, Groq scoring, user-facing Sheet/CSV stores, alerts). Later modules (`inventory.py`, `pools.py`, `reporting.py`, `dashboard.py`) are listed in AGENTS.md "Layout".
- scope: module layout

## D-03: State persistence: append-only event ledger in the Google Sheet
- source: DECISIONS.md (D-03)
- status: locked (the "Boards rewritten atomically in one request" detail is contradicted by D-15 row-level upserts; see conflicts report INFO)
- decision: State lives in hidden Sheet tabs `Events` (append-only), `Boards`, `Runs`; seen/evaluated/alerted are derived by replaying events; `Seen_Archive` is retired. Pruning to be revisited when `Events` exceeds about 200k rows (see D-43).
- scope: persistence, ledger, hidden tabs

## D-04: Freshness classes
- source: DECISIONS.md (D-04)
- status: locked (window default amended by D-17)
- decision: Source publication time beats observation; update time is never publication; Workable is day-precision (`verified_fresh` only within the last day AND board gap within window); `observed_new` (undated) is not alerted; a ledger hit means no re-alert on republication. Class rules are in SPEC "Freshness vocabulary".
- scope: freshness classification

## D-05: Baseline newly discovered boards
- source: DECISIONS.md (D-05)
- status: locked (amended by D-24 for re-entry)
- decision: A board's first successful poll records every existing ID as `baseline`; a job whose source time proves it inside the window is still evaluated.
- scope: baselining, new boards

## D-06: Polling cadence
- source: DECISIONS.md (D-06)
- status: locked (the Serper-credit part superseded by D-18; hourly 24/7 polling stands)
- decision: Poll hourly (`17 * * * *`), 24/7; a poll gap is recorded, never assumed away; alerts older than the window are labelled by class instead of sent as fresh.
- scope: polling cadence, gap recording

## D-07: Retry semantics
- source: DECISIONS.md (D-07)
- status: locked (part reversed by D-21: pending alerts are never discarded for age)
- decision: Transient failures write an `error` event and leave later stages undone; after 5 attempts a job is `abandoned`; tracker append precedes the `evaluated` event and is guarded by a tracker-key check; alerts are at-least-once.
- scope: retry, state stages, tracker duplicate guard

## D-08: Filtering order
- source: DECISIONS.md (D-08)
- status: locked (level matching widened narrowly by D-25)
- decision: Cheap title keyword/exclusion checks before any fetch; deterministic hard rules on the hydrated posting; Groq scores only survivors; hard rules are conservative, the LLM judges fit.
- scope: filtering order

## D-09: Personal data and secrets
- source: DECISIONS.md (D-09)
- status: locked
- decision: `.env`, `Resume.pdf`, `resume.txt` are git-ignored; the resume lives in the Sheet (`Settings > Resume_Text`); `.env.example` could not be written, its template is in README.
- scope: secrets, personal data

## D-10: Open requirement conflicts to confirm with the user
- source: DECISIONS.md (D-10)
- status: locked (contains open items; SmartRecruiters item resolved by D-19, D-27, then D-38 for this deployment; Groq model item is D-16)
- decision: Records that these supersede earlier requests: hourly 24/7 instead of 2-hourly business days; only `verified_fresh` jobs alert; `Events` replaces hidden `Seen_Archive`; stale only when a source date exists (undated jobs labelled, never alerted); Groq models changed (D-16).
- scope: superseded early requirements

## D-11: Seed the registry from two public inventories
- source: DECISIONS.md (D-11)
- status: locked
- decision: Import board identifiers from `veresk06/open-ats-feed` and `kalil0321/ats-scrapers` (both MIT, attribution in `NOTICE.md`); only identifiers are used, postings still come from the ATS; unsupported providers are counted and reported, not imported.
- scope: board inventory sources, licensing

## D-12: Identity: provider + region + identifier, casing per provider
- source: DECISIONS.md (D-12)
- status: locked
- decision: Board keys keep case for Lever/Workable only; job keys are unchanged (`ats|board-lowercase|id`); `region` is part of the key when non-empty.
- scope: identity, board key, job key

## D-13: Validation semantics and provider policy
- source: DECISIONS.md (D-13)
- status: locked (SmartRecruiters policy changed by D-19, D-27, reversed for this deployment by D-38; 429 handling extended by D-37)
- decision: 404/410 -> `invalid`, 200+jobs -> `valid`, 200+none -> `valid_empty`, transient errors retried then `transient`; a provider failing 15 times in a row is paused for the run; per-provider spacing (Lever 1 s); SmartRecruiters imported boards parked unless `ALLOW_SMARTRECRUITERS_BULK=1`.
- scope: validation outcomes, provider policy

## D-14: Activation budget (what is "monitored")
- source: DECISIONS.md (D-14)
- status: locked (changed by D-19, D-23, D-26; latest authoritative for promotion: D-26 then D-45/D-47)
- decision: Validated boards wait; the poller promotes best-matching ones up to `Max_Active_Boards` (default 500) and `Max_New_Boards_Per_Run` (default 50).
- scope: activation budget, promotion

## D-15: Two writers, one registry
- source: DECISIONS.md (D-15)
- status: locked (amended by D-28 then D-31; latest authoritative: D-31)
- decision: Importer and poller write row-level upserts of only changed rows, never a full rewrite, each owning different rows.
- scope: registry writers

## D-16: Groq models (deviation from the original request, needs your OK)
- source: DECISIONS.md (D-16)
- status: locked (the "needs your OK" confirmation is not recorded anywhere in the ingested docs; see conflicts report WARNING)
- decision: Defaults are `openai/gpt-oss-120b` (primary) and `openai/gpt-oss-20b` (fallback) because the requested models return 404 for this account; override via `GROQ_MODEL` / `GROQ_FALLBACK_MODEL`; output cap 1,000 tokens; a nonexistent model is a configuration problem (switch models, else stop the run).
- scope: Groq models, scoring client

## D-17: Freshness window 4 h -> 12 h; discovery interval is a separate setting
- source: DECISIONS.md (D-17)
- status: locked (deliberate SPEC change; SPEC already reflects it)
- decision: `Fresh_Window_Hours` defaults to 12 and `Discovery_Every_Hours` defaults to 12, independent of each other; boundary inclusive; an explicit 4 in an old Sheet is kept and flagged every run.
- scope: freshness window, discovery interval, migration

## D-18: Scheduled discovery: rotating, budgeted, date-windowed; unfiltered search is manual only
- source: DECISIONS.md (D-18)
- status: locked (provider changed by D-36; slot query corrected by D-35; rotation, budget-per-run and manual-only backfill still hold)
- decision: A persistent cursor walks the slot list; each run stops at `Discovery_Credit_Budget` (default 10); unfiltered search exists only as manual `--backfill`.
- scope: discovery rotation, credit budget

## D-19: One admission path for every source
- source: DECISIONS.md (D-19)
- status: locked (SmartRecruiters existing-data clause changed by D-27)
- decision: Inventory import, search results and manual seeds share the same admission rules: sanity, `candidate` with provenance, provider policy, validation, relevance-ordered promotion within the budgets.
- scope: board admission

## D-20: Search results are processed twice, independently
- source: DECISIONS.md (D-20)
- status: locked
- decision: Every parsable board goes to admission; only unseen identities whose title passes the cheap gate are hydrated (max 20 a run) for authoritative publication evidence; temporary hydration failures are queued (max 60 jobs, 5 attempts, no credits).
- scope: search result processing, hydration retry queue

## D-21: Pending deliveries are never discarded for age (reverses part of D-07)
- source: DECISIONS.md (D-21)
- status: locked
- decision: A pending alert is retried until accepted or rejected 5 times by Telegram; one delivered after the window says "delivered late"; the freshness class is not re-judged later.
- scope: alert retry, late delivery

## D-22: Open items to confirm
- source: DECISIONS.md (D-22)
- status: locked (contains open items; SmartRecruiters item resolved by D-27)
- decision: Records open items: slot count and rotation length (later changed by D-35), SmartRecruiters (resolved), and `Min_Alert_Score` as the lever for alert volume at a 12-hour window.
- scope: open items

## D-23: Board evidence from complete hourly polls (changes D-14)
- source: DECISIONS.md (D-23)
- status: locked
- decision: Every complete successful poll refreshes `Relevant_Jobs`, `Eligible_Jobs`, `Relevance_At`, `Complete_Polls`; activity (`New_Relevant_7d/30d`) is computed from the ledger only; unknown is never zero (blank until the stint is 7 days old).
- scope: board evidence, activity, completeness

## D-24: Re-entry re-establishes the baseline (amends D-05 and SPEC "Baselining")
- source: DECISIONS.md (D-24)
- status: locked
- decision: A `new` board with a recorded baseline is re-entering; its first poll classifies by real board gap and source evidence (`freshness.classify(..., reentry=True)`); undated with gap longer than window -> `baseline`; a new stint then starts.
- scope: re-entry, baselining

## D-25: Title-gate audit: level matching (amends D-08 narrowly)
- source: DECISIONS.md (D-25)
- status: locked
- decision: Space and hyphen interchangeable inside a configured term; "Internship" and "Jr"/"Jr." match when Intern/Junior is targeted; default `Target_Levels` gains "Entry Level, New Grad" (existing Sheets keep explicit values); seniority exclusions unchanged.
- scope: title gate

## D-26: Established and exploration pools with a weekly bounded rebalance (changes D-14)
- source: DECISIONS.md (D-26)
- status: locked (floor added by D-45; early release added by D-47; findings fixed by D-32; weights flagged initial by D-30)
- decision: `Max_Active_Boards` splits into established (default 400) and exploration (default 100) pools; new boards enter on a 7-day trial; a weekly rebalance (`Rebalance_Every_Days` 7) graduates or replaces by one documented score with margin, two-cycle rule and replacement bound (20); no demotion on thin evidence; ships in report mode.
- scope: pools, rebalance, trials

## D-27: Monitored SmartRecruiters boards are parked (changes D-13 / D-19)
- source: DECISIONS.md (D-27)
- status: locked (reversed for this deployment by D-38)
- decision: `pools.sync_pools` parks any monitored board whose provider is blocked (`deferred`, history kept) every run; waiting boards are never promoted while the provider is blocked; `ALLOW_SMARTRECRUITERS_BULK=1` opts back in.
- scope: SmartRecruiters policy

## D-28: Pool transitions are made only by the poller (amends D-15)
- source: DECISIONS.md (D-28)
- status: locked (corrected by D-31 and D-34: the importer guard is best-effort, not an atomic compare-and-set)
- decision: Only the hourly poller promotes, graduates, demotes, parks or relabels boards; the importer skips rows whose status is `new`, `active` or `disabled`.
- scope: pool transitions, writer ownership

## D-29: Validation runs two independently budgeted queues
- source: DECISIONS.md (D-29)
- status: locked (workflow budget changed by D-47)
- decision: Candidates (cut to `--max-validations`) and re-checks (`validated` after 7 days, `invalid` after 30; cut to `--max-revalidations`, default 500) alternate strictly so neither starves.
- scope: validation queues

## D-30: Open items to confirm (initial operating choices, not proven)
- source: DECISIONS.md (D-30)
- status: locked (contains open items: 80/20 split, 7-day trials, weekly rebalance, 20 replacements, score weights, margin 1.0, two weak cycles, 84 complete polls, 24 h evidence age are initial choices; unproven)
- decision: Labels these as initial operating choices, all Settings, not tuned; `Rebalance_Mode` ships as `report`; AGENTS.md rule 7 respected (job scorer and `Min_Alert_Score` untouched).
- scope: pool parameters, open items

## D-31: Serialized registry writers; the importer guard is not a compare-and-set (corrects D-28)
- source: DECISIONS.md (D-31)
- status: locked
- decision: Both writing workflows share concurrency group `job-hunter-state` (`cancel-in-progress: false`); every writing command takes an advisory writer lease (hidden `Lock` tab or `state/lock.json`); the importer's skip guard stays as defence in depth with provenance merged.
- scope: writer serialization, lease

## D-32: Allocation correctness findings (confirmed by a multi-week simulation)
- source: DECISIONS.md (D-32)
- status: locked
- decision: Fixed oscillation (boards that had a stint cool down `2 x Exploration_Days`), unjudgeable trials (rotated out at `3 x Exploration_Days`) and a slack trap (one-hour slack in minimum observed time); weekly cadence making trials 7-14 days dismissed as accepted.
- scope: allocation correctness, cool-down, rotation

## D-33: Evidence semantics: observed time, gap discoveries, search-found jobs
- source: DECISIONS.md (D-33)
- status: locked (completeness reasoning refined by D-37)
- decision: Per-adapter completeness; 30-day rates use observed time excluding outages (`Outages` column); a first observation counts as activity only with recency evidence; search-found jobs count once when their own source time proves fresh. Workable completeness is unverified.
- scope: evidence, activity, completeness

## D-34: Wording corrected
- source: DECISIONS.md (D-34)
- status: locked
- decision: "Atomic compare-and-set" became "best-effort guard behind serialization"; "detected within one successful polling interval" became conditional (monitored, poll ran, complete listing).
- scope: documentation wording

## D-35: Discovery slot query is site + role only (corrects D-18)
- source: DECISIONS.md (D-35)
- status: locked (Google mechanics replaced by D-36; the no-location/no-level-in-query rule persists)
- decision: A slot is site x role only (42 slots with default roles instead of 336); location, level and excluded words are applied locally by the title gate, US location rule and scorer. "Rotate locations" removed from the earlier requirement.
- scope: discovery slots

## D-36: Search provider: Serper -> Tavily
- source: DECISIONS.md (D-36)
- status: locked
- decision: Discovery uses Tavily (`include_domains`, `start_date` = today - 3 d, `basic` depth, 1 request per slot, max 20 results, no pagination); persistent monthly credit ledger (cap 1,000, reserve 200, per-run 10); window is retrieval only; a Tavily `published_date` is never read; old Serper cursor discarded.
- scope: search provider, credit ledger, migration

## D-37: Deployment preparation: local production writes disabled, lease facts, backoff, completeness by documented behaviour
- source: DECISIONS.md (D-37)
- status: locked
- decision: Production writes happen only in the serialized GitHub workflows (local writing commands refuse, exit 4, unless `GITHUB_ACTIONS=true` or `ALLOW_LOCAL_SHEET_WRITES=1` for a test Sheet); file lease is `flock`; Sheet lease is not atomic and is not described as such; HTTP 429 triggers provider backoff; completeness per documented endpoint behaviour; CSVs of job-search data untracked; repository meant to be private.
- scope: deployment, lease, backoff, repository hygiene

## D-38: SmartRecruiters is polled for the pilot (explicit user decision; reverses D-13 / D-27 for this deployment)
- source: DECISIONS.md (D-38)
- status: locked
- decision: Owner unparked SmartRecruiters (`ALLOW_SMARTRECRUITERS_BULK=1` in both workflows) for the pilot despite `robots.txt` `Disallow: /`; whether the provider accepts read-only polling is unknown and was not asked; reversal is deleting the two workflow lines (monitored boards re-park, history kept).
- scope: SmartRecruiters policy override

## D-39: Measure the re-check interval before changing it (metric added; no behaviour change)
- source: DECISIONS.md (D-39)
- status: locked
- decision: Keep the 7-day re-check interval and measure flips (`revalidation_stats`, shown in the pilot report) to choose the next improvement.
- scope: re-check interval

## D-40: Operational dashboard: generated output, run-start records, reason codes
- source: DECISIONS.md (D-40)
- status: locked
- decision: A generated, output-only `Dashboard` tab (nothing reads it); run-start records rewritten in place by `Run_ID`; run IDs, outcomes, credit status and `reject` reason codes recorded going forward (never back-filled); refresh runs after the run, outside the lease, failures contained.
- scope: dashboard, run records

## D-41: Dashboard visuals: Sheets-native charts, not an external analytics tool (refines D-40)
- source: DECISIONS.md (D-41)
- status: locked (including its after-render amendment: four charts, hidden data block, Inter font)
- decision: Use Sheets-native charts and `SPARKLINE`; no external analytics service; workflow gained a `dashboard` input to rebuild only the tab.
- scope: dashboard visuals

## D-42: Independent missed-run watchdog and pilot-report corrections
- source: DECISIONS.md (D-42)
- status: locked
- decision: Separate `watchdog.yml` + standalone `watchdog.py` (imports nothing from the hunter) judges the last successful production run against a 2-hour default threshold; one outage and one recovery Telegram message; unreadable data is "monitoring unavailable" (exit 3, nothing sent); a second external trigger is recommended and is the owner's to create. Pilot report now measures from the first production run with distinct hourly intervals.
- scope: watchdog, pilot-report corrections

## D-43: Storage: measurement and proposal only
- source: DECISIONS.md (D-43)
- status: locked (the proposal itself is NOT decided or implemented: "Decision requested: none yet")
- decision: Nothing pruned, compacted, archived or migrated; measured Events growth recorded; proposal is an `Identity` tab of chunked posting IDs, a `Daily` counter tab and archiving terminal operational rows, with a parallel-run migration order.
- scope: Events storage, Sheets cell limit

## D-44: The tracker is written and read by header name
- source: DECISIONS.md (D-44)
- status: locked (fallback to standard order removed by D-46)
- decision: Tracker values are placed under their own header; `tracked_keys`, status dropdown and row colours find columns by name; the program stays append-only and never writes `My_Status`, `User_Notes` or `My_Feedback`.
- scope: tracker layout

## D-45: Graduation floor; capacity 700 and rebalancing on after the pilot (changes SPEC "Weekly rebalance")
- source: DECISIONS.md (D-45)
- status: locked (user decision 2026-10-23)
- decision: A free established slot needs a score of at least `GRADUATION_FLOOR` = 2.0 (initial choice); a trial below it is handled like a losing trial; user set `Max_Active_Boards` 700 and `Rebalance_Mode` on in the Sheet; code defaults stay 500 / report.
- scope: graduation floor, capacity

## D-46: A tracker without its header is refused, never written by position (changes SPEC "Delivery")
- source: DECISIONS.md (D-46)
- status: locked
- decision: A header without `Apply_URL` raises `TrackerLayoutError` and the run fails before the job's evaluation and alert are recorded (retryable); no alert is sent while the header is missing (accepted trade-off); dashboard lists "tracker header missing".
- scope: tracker header guard

## D-47: Ended trials below the graduation floor give their slot back between weekly cycles; faster re-check pass (changes SPEC "Weekly rebalance")
- source: DECISIONS.md (D-47)
- status: locked (user request 2026-10-24)
- decision: In `on` mode, each non-cycle poll run returns ended trials whose weekly-plan decision is `return` with score below the floor (`pools.early_releases`, `pools.apply_releases`; marked `release <day>:`, weekly interval not reset); inventory re-check budget 2,000 -> 5,000 per run. Capacity, floor, weights, margin, two-cycle rule, replacement bound and scorer unchanged.
- scope: early release, re-check budget

## Supersession chains (for the roadmapper)

- Freshness window: D-04 -> D-17.
- Baselining: D-05 -> D-24.
- Cadence and discovery: D-06 -> D-18 -> D-35 -> D-36.
- Retry and delivery: D-07 -> D-21.
- Filtering levels: D-08 -> D-25.
- SmartRecruiters policy: D-13 -> D-19 -> D-27 -> D-38 (deployment override; default policy still in SPEC).
- Activation and pools: D-14 -> D-23 -> D-26 -> D-30 (initial values) -> D-32 (fixes) -> D-45 (floor) -> D-47 (early release).
- Registry writers: D-15 -> D-28 -> D-31 -> D-34 (wording) -> D-37 (local writes refused).
- Validation queues: D-29 -> D-47 (budget).
- Tracker layout: D-44 -> D-46.
- Dashboard: D-40 -> D-41.
- Open items still open in the log: D-16 (owner OK), D-22 (confirm slot count; mostly overtaken by D-35), D-30 (initial operating choices), D-43 (storage decision).
