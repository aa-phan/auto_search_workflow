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

`boards.py` (identity, list adapters, registry), `freshness.py` (dates, classes), `ledger.py` (events, derived state, retry selection), `state.py` (Sheet/CSV persistence for Boards/Events/Runs). `hunter.py` stays the entry point and orchestrator. Reason: `hunter.py` is already ~1,400 lines; new concerns are pure and unit-testable in isolation.

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

## D-10 Open requirement conflicts to confirm with the user

- Earlier request: hidden `Seen_Archive` tab. Now replaced by `Events` (D-03). Same purpose (dedupe without cluttering the tracker), different identity key.
- Earlier request: `Date_Posted`-based stale gate for everything. Now: stale only when a source date exists; undated jobs are labelled `uncertain`/`observed_new` and never alerted.
