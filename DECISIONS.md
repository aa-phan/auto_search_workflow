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

See SPEC. Key choices: (a) source publication time beats observation; (b) update time is never publication; (c) Workable is day-precision, so it is `verified_fresh` only when the date is within the last day AND the board gap is within the window; (d) `observed_new` (no date) is not alerted: it is evidence of recency, not verification; (e) a ledger hit means no re-alert on republication.

## D-05 Baseline newly discovered boards

First successful poll records every existing ID as `baseline`. Exception: jobs whose source time proves they are within the window are still evaluated, because the date is authoritative. Otherwise a new board would flood the user with its entire backlog.

## D-06 Polling cadence

Hourly (`17 * * * *`, off-peak minute), 24/7. Serper runs inside the discovery cadence, not every poll, to conserve credits (about 16 credits/day at the defaults). A poll gap is recorded, never assumed away; alerts older than the window are labelled by class instead of being sent as "fresh".

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

404/410 -> `invalid`; 200+jobs -> `valid`; 200+none -> `valid_empty` (Greenhouse, Lever, Ashby and Workable distinguish this from 404; SmartRecruiters does not); timeouts/5xx/429/non-JSON/adapter errors -> retried (1.5 s, 3 s backoff) then `transient`, with exponential re-try spacing across runs. A provider that fails 15 times in a row is paused for the run. Per-provider spacing (Lever 1 s, per its `Crawl-delay`). **SmartRecruiters' API host `robots.txt` says `Disallow: /` for generic agents**; we park its imported boards (`deferred`) unless the user sets `ALLOW_SMARTRECRUITERS_BULK=1`. Existing behavior for SmartRecruiters boards found via Serper (a handful) is unchanged; flagged below.

## D-14 Activation budget (what is "monitored")

Importing ~22,000 boards must not become 22,000 hourly requests. Validated boards wait; the poller promotes the best-matching ones (most title-gate matches first) up to `Max_Active_Boards` (default 500) and `Max_New_Boards_Per_Run` (default 50). Serper-discovered boards keep the old behavior (monitored immediately) and count against the budget. Relevance is a snapshot, so a waiting board with nothing relevant today is re-validated weekly rather than polled hourly.

## D-15 Two writers, one registry

The importer (weekly/daily workflow) and the poller (hourly) can overlap. Registry writes are row-level upserts of only the rows a run changed, never a full rewrite, and each side owns different rows (importer: candidate/validated/invalid/deferred; poller: new/active/disabled). Each workflow has its own concurrency group so imports never delay polling.

## D-16 Groq models (deviation from the original request, needs your OK)

`llama-3.3-70b-versatile` and `llama-3.1-8b-instant` return 404 `model_not_found` for this account today. Defaults are now `openai/gpt-oss-120b` (primary) and `openai/gpt-oss-20b` (fallback); both verified live on real postings; override with `GROQ_MODEL` / `GROQ_FALLBACK_MODEL`. These are reasoning models, so the output cap rose from 400 to 1,000 tokens (400 truncated the JSON). A model Groq says does not exist is a configuration problem: the client switches models, and if neither works the run stops with a clear message; it no longer records per-job failures that would burn each job's retry attempts.

## D-10 Open requirement conflicts to confirm with the user

- Earlier request: run every 2 hours on business days only (`0 13-23/2 * * 1-5`). Superseded by the board-polling brief: hourly, 24/7 (`17 * * * *`), because new postings should be caught nights and weekends too. Serper discovery is separately throttled (default every 12 h).
- SmartRecruiters: imported boards are parked by `robots.txt` policy (D-13) while Serper-found ones are still polled. Say if you want both treated the same way.
- Groq models changed from the requested pair to the available `gpt-oss` pair (D-16).
- Earlier request: alert on every `To Apply` job. Now only `verified_fresh` jobs alert; others reach the tracker without a push (see SPEC).
- Earlier request: hidden `Seen_Archive` tab. Now replaced by `Events` (D-03). Same purpose (dedupe without cluttering the tracker), different identity key.
- Earlier request: `Date_Posted`-based stale gate for everything. Now: stale only when a source date exists; undated jobs are labelled `uncertain`/`observed_new` and never alerted.
