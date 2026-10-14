# DECISIONS

Newest context first within each topic. Each entry: decision, why (with evidence), consequence. Evidence refers to the baseline commit `affaaa4` and `.planning/codebase/CONCERNS.md` (claims re-verified by running the code).

## D-01 Refactor in place; do not restart

Keep, modify or replace by component:

| Component | Verdict | Evidence |
|---|---|---|
| Per-job ATS adapters (Greenhouse, Lever, Ashby, Workable, SmartRecruiters) | **Keep** | Live-verified; carry authoritative dates and locations; tested. Reused to hydrate new IDs. |
| Settings, query builder, Groq client (token budget, 429 fallback), Telegram formatting, Sheet bootstrap/styling, date parsing | **Keep** (small additions) | Tested; no defects found. |
| Identity / dedupe (`normalize_url`, `dedupe_key`, `Seen_Archive`) | **Replace** | Same Greenhouse job under `boards.` vs `job-boards.` hosts gives different keys; SmartRecruiters slug changes give different keys; a Greenhouse embed URL (identity in the query string) is not recognized at all. |
| State model (one `process()` result written once) | **Replace** with seen/evaluated/alerted ledger | Scoring failures (Groq 400/404, ATS 403, thin text) are written as permanent `Unjudged / Error` archive rows (never retried); an alert failure is only logged and never retried; a timeout loses up to 9 buffered rows. |
| Discovery (Serper top-20 -> evaluate) | **Modify** into two loops | Serper ranks by relevance, not date; in live runs ~29 of 30 unfiltered hits were stale. Direct polling removes the dependence on search ranking. |
| Freshness gate | **Modify** | `updated_at` and Serper crawl dates were used as publication dates; undated jobs passed. |
| CSV fallback + workflow | **Modify** | Workflow committed only `tracked_jobs.csv`; the archive was lost between runs. |
| Local keyword scorer in `legacy/` | **Keep archived**; reuse only deterministic eligibility rules | It was replaced by the LLM for calibration reasons; location, seniority, language and non-US rules are cheap and testable. |

Why not a rewrite: the adapters, Groq client, Sheet and alert code are sound. The defects are in identity, state, freshness and discovery, which are replaced.

## D-02 New code lives in separate modules

`boards.py` (identity, list adapters, registry), `freshness.py` (dates, classes), `ledger.py` (events, derived state, retry selection), `eligibility.py` (deterministic gates), `state.py` (Sheet/CSV persistence for Boards/Events/Runs), `pipeline.py` (one run: discover, poll, detect, evaluate, deliver; all side effects injected so failure cases are testable). `hunter.py` stays the entry point and holds config, per-job hydration, Groq scoring, the user-facing Sheet/CSV stores and alerts. Reason: `hunter.py` is already ~1,400 lines; new concerns are pure and unit-testable in isolation.

## D-03 State persistence: append-only event ledger in the Google Sheet

Actions runners are ephemeral and the user must not touch Git. State goes in hidden Sheet tabs: `Events` (append-only), `Boards` (one row per board, rewritten atomically in a single request), `Runs`. Seen/evaluated/alerted are derived by replaying events, so a crash can never mark a later stage done. `Seen_Archive` is retired (superseded by `Events`; rejected jobs and reasons live there). Consequence: Sheets cell/row limits bound history; revisit pruning when `Events` exceeds ~200k rows.

## D-04 Freshness classes

(Window default changed from 4 to 12 hours: see D-17. The rules below are window-relative.)

See SPEC. Key choices: (a) source publication time beats observation; (b) update time is never publication; (c) Workable is day-precision, so it is `verified_fresh` only when the date is within the last day AND the board gap is within the window; (d) `observed_new` (no date) is not alerted: it is evidence of recency, not verification; (e) a ledger hit means no re-alert on republication.

## D-05 Baseline newly discovered boards

First successful poll records every existing ID as `baseline`. Exception: jobs whose source time proves they are within the window are still evaluated, because the date is authoritative. Otherwise a new board would flood the user with its entire backlog.

## D-06 Polling cadence

Hourly (`17 * * * *`, off-peak minute), 24/7. Serper runs inside the discovery cadence, not every poll, to conserve credits (superseded by D-18: rotating, budgeted at 10 credits per run, at most 20 a day). A poll gap is recorded, never assumed away; alerts older than the window are labelled by class instead of being sent as "fresh".

## D-07 Retry semantics

Transient failures write an `error` event and leave later stages undone. After 5 attempts a job is `abandoned` (recorded, not retried). Tracker append happens before the `evaluated` event and is guarded by a tracker-key check, so a retry cannot duplicate rows. Alerts are at-least-once.

## D-08 Filtering order

Keyword and exclusion checks on listing titles run before any fetch (most board jobs are irrelevant); deterministic hard rules run on the hydrated posting; Groq scores only what survives. Hard rules are conservative (reject only on clear signals); the LLM remains the judge of fit.

## D-09 Personal data and secrets

`.env`, `Resume.pdf` and `resume.txt` are git-ignored. The resume lives in the Sheet (`Settings > Resume_Text`). `.env.example` could not be written in this environment (permission rule); its template is in the README.

## D-11 Seed the registry from two public inventories

`veresk06/open-ats-feed` (`actor/data/companies.json`: Greenhouse, Ashby, Lever + three providers we do not support) and `kalil0321/ats-scrapers` (`ats-companies/*.csv`: 47 providers, five supported). Both MIT; attribution in `NOTICE.md`. Only board identifiers are used; postings still come from the ATS. Unsupported providers (Breezy, Recruitee, Teamtailor, Workday, Join, BambooHR, ...) are counted and reported, not imported. The feed's README calls its data "public domain" but its LICENSE is MIT; we follow the license.

## D-12 Identity: provider + region + identifier, casing per provider

Verified live: Lever and Workable APIs 404 on a re-cased slug; Greenhouse, Ashby, SmartRecruiters ignore case. So board keys keep case for Lever/Workable only. **Job keys are unchanged** (`ats|board-lowercase|id`; IDs are globally unique per provider), so every existing event and tracker row stays valid. `region` is part of the board and job key when non-empty; neither inventory has regional hosts and no regional adapter is added in this task.

## D-13 Validation semantics and provider policy

404/410 -> `invalid`; 200+jobs -> `valid`; 200+none -> `valid_empty` (Greenhouse, Lever, Ashby and Workable distinguish this from 404; SmartRecruiters does not); timeouts/5xx/429/non-JSON/adapter errors -> retried (1.5 s, 3 s backoff) then `transient`, with exponential re-try spacing across runs. A provider that fails 15 times in a row is paused for the run. Per-provider spacing (Lever 1 s, per its `Crawl-delay`). **SmartRecruiters' API host `robots.txt` says `Disallow: /` for generic agents**; we park its imported boards (`deferred`) unless the user sets `ALLOW_SMARTRECRUITERS_BULK=1`. Serper-found SmartRecruiters boards were originally exempt; D-19 removes that exemption.

## D-14 Activation budget (what is "monitored")

Importing ~22,000 boards must not become 22,000 hourly requests. Validated boards wait; the poller promotes the best-matching ones (most title-gate matches first) up to `Max_Active_Boards` (default 500) and `Max_New_Boards_Per_Run` (default 50). (Changed by D-19: Serper-discovered boards no longer skip validation and the budget.) Relevance is a snapshot, so a waiting board with nothing relevant today is re-validated weekly rather than polled hourly.

## D-15 Two writers, one registry

The importer (weekly/daily workflow) and the poller (hourly) can overlap. Registry writes are row-level upserts of only the rows a run changed, never a full rewrite, and each side owns different rows (importer: candidate/validated/invalid/deferred; poller: new/active/disabled). Each workflow has its own concurrency group so imports never delay polling.

## D-16 Groq models (deviation from the original request, needs your OK)

`llama-3.3-70b-versatile` and `llama-3.1-8b-instant` return 404 `model_not_found` for this account today. Defaults are now `openai/gpt-oss-120b` (primary) and `openai/gpt-oss-20b` (fallback); both verified live on real postings; override with `GROQ_MODEL` / `GROQ_FALLBACK_MODEL`. These are reasoning models, so the output cap rose from 400 to 1,000 tokens (400 truncated the JSON). A model Groq says does not exist is a configuration problem: the client switches models, and if neither works the run stops with a clear message; it no longer records per-job failures that would burn each job's retry attempts.

## D-10 Open requirement conflicts to confirm with the user

- Earlier request: run every 2 hours on business days only (`0 13-23/2 * * 1-5`). Superseded by the board-polling brief: hourly, 24/7 (`17 * * * *`), because new postings should be caught nights and weekends too. Serper discovery is separately throttled (default every 12 h).
- SmartRecruiters: RESOLVED by D-19 (parked for every source). Boards that Serper had already activated before D-19 are not demoted automatically; each run notes how many remain monitored.
- Groq models changed from the requested pair to the available `gpt-oss` pair (D-16).
- Earlier request: alert on every `To Apply` job. Now only `verified_fresh` jobs alert; others reach the tracker without a push (see SPEC).
- Earlier request: hidden `Seen_Archive` tab. Now replaced by `Events` (D-03). Same purpose (dedupe without cluttering the tracker), different identity key.
- Earlier request: `Date_Posted`-based stale gate for everything. Now: stale only when a source date exists; undated jobs are labelled `uncertain`/`observed_new` and never alerted.

## D-17 Freshness window 4 h -> 12 h; discovery interval is a separate setting (deliberate SPEC change)

`Fresh_Window_Hours` defaults to 12 (was 4) everywhere it is used: classification, the first-poll baseline exception, the day-precision rule, alert eligibility, Settings defaults, docs, tests. `Discovery_Every_Hours` also defaults to 12 but is independent: neither setting reads the other. Hourly ATS polling is unchanged. The boundary is inclusive (12 h 0 s is inside). **Migration:** the old template wrote `Fresh_Window_Hours = 4` into every Sheet, so an old default cannot be told from a deliberate 4. The value is kept (explicit values always win) and flagged in the log and in `Runs.Notes` every run until the user changes it. Nothing rewrites the user's Settings tab. Environment `FRESH_WINDOW_HOURS=4` is flagged the same way. A wider window means more `verified_fresh` alerts per run and a longer tail of late-labelled ones, not more coverage.

## D-18 Scheduled discovery: rotating, budgeted, date-windowed; unfiltered search is manual only

Evidence for the change: the unfiltered searches returned established boards (and ~29 of 30 stale jobs) and cost 2-3 pages per query on every run, while the public inventories already supply broad board coverage. Now: the slot list is ATS site x role x location; a persistent cursor (hidden `Discovery` tab) walks it; each run stops at `Discovery_Credit_Budget` credits (default 10) and each query at 2 consecutive no-gain pages or 3 pages. `SEARCH_TBS` cannot disable the window for scheduled runs (blank/`none` falls back to `qdr:d3` with a warning); the old unfiltered pass survives only as `--backfill` (boards only, own credit cap, never scheduled, does not move the cursor). Cursor moves after the found boards are saved and not at all when every request failed. Credits are counted as one per request; Serper's real billing is not verified here. Consequence: with defaults (6 sites x 7 roles x 8 locations = 336 slots, at most 10 queries per run, 2 runs/day) a full pass takes about 17 days at best and longer whenever a query pages. That is slow on purpose; the inventories carry the broad coverage and search only adds recent and unlisted boards.

## D-19 One admission path for every source

Inventory import, Serper results and manual seeds now share the same rules: identifier sanity and supported provider, `candidate` with provenance, provider policy (SmartRecruiters parked), validation, relevance-ordered promotion within `Max_Active_Boards` / `Max_New_Boards_Per_Run`. Serper boards used to become `new` (polled at once) without validation or budget; seeds likewise. Consequences: (a) a search-found board with nothing matching the user's titles waits (validated) instead of being polled; (b) a search-found board needs one extra validation request (bounded to 40 per run, the rest stay candidates for the validation job); (c) tests that seed a board now need a title that passes the gate (the default test fixtures do). SmartRecruiters jobs found by search are also not hydrated while the provider is parked (the per-job API is on the same disallowed host). **Existing data:** SmartRecruiters boards that Serper had already activated stay monitored (rows are never silently changed); the run notes count them so the user can decide.

## D-20 Search results are processed twice, independently

Board path: every result with a parsable board is submitted to admission, even if its job is seen, stale or excluded. Job path: only unseen identities whose title passes the cheap gate are hydrated (max 20 per run) for authoritative publication evidence; Google's date and the first observation are never publication. A temporary hydration failure is queued in the Discovery tab (max 60 jobs, 5 attempts, no credits) because rotation would not resurface the result for weeks; a closed posting is dropped. "Unique verified-fresh matches" = unique result jobs whose ledger state is `verified_fresh` and passed the title gate (whenever first observed).

## D-21 Pending deliveries are never discarded for age (reverses part of D-07)

D-07/ledger abandoned a retried alert once the job was more than 12 h past evaluation ("no longer fresh news"). That silently dropped alerts after any outage longer than half a day. Now a pending alert is retried until it is accepted (or, as before, rejected 5 times by Telegram); one delivered after the window carries "delivered late: published about N h ago (verified fresh when first seen)" in Telegram and the webhook. Scoring retries were never age-limited and still are not. The freshness class itself is not re-judged later.

## D-22 Open items to confirm

- Slot count (336 with default Settings) and a 17-day-plus rotation cycle at the default budget: raise `Discovery_Credit_Budget` or narrow roles/locations if faster rotation is wanted (cost: credits).
- Whether to park or demote SmartRecruiters boards that Serper had already activated (D-19).
- A 12-hour window sends more alerts than 4 hours did; `Min_Alert_Score` is the lever (scores are not tuned: STATUS blockers apply).
