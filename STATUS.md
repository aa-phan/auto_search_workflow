# STATUS

Last updated 2026-10-14 (board slot allocation, D-23..D-30; before that the discovery rotation / 12-hour window change, D-17..D-21). Read `SPEC.md` (contract) and `DECISIONS.md` (why) first.

## State

Board polling -> new-ID detection -> freshness classification -> filters/scoring -> Sheet -> Telegram is implemented (D-01..D-09). This change adds the **inventory loop** (D-11..D-15): the registry is seeded from two public inventories, validated through the existing adapters, and promoted into hourly polling only within a budget. Groq model defaults changed because the requested models no longer exist for this key (D-16).

Latest change (D-23..D-30, quick task 261014-olj): board slot allocation. A complete hourly poll now refreshes each monitored board's relevant / eligible counts and new-posting activity from the listing it already fetched; `Max_Active_Boards` is split into an established pool (400) and an exploration pool (100) with 7-day trials; a weekly bounded rebalance compares ended trials with the weakest established boards (**report mode by default**; `python hunter.py --rebalance-report` previews it); demoted boards keep their ledger, baseline, provenance and pending retries and re-enter with a re-established baseline; monitored SmartRecruiters boards are parked every run (history kept); validation runs two independently budgeted queues so re-checks no longer starve behind the candidate backlog; the title gate accepts "Internship", "Jr.", "Entry-Level" and "New Grad" variants. **Everything for this change is verified only with offline mocks: no live Sheet, Groq, Telegram, Serper or GitHub Actions run, and no real ATS call, was made** (tests: 275 offline).

Previous change (D-17..D-21): scheduled discovery is a persistent rotation of date-windowed searches within a credit budget (unfiltered search is manual `--backfill` only); every source goes through one board-admission path; the freshness window is 12 hours (discovery interval is a separate setting); pending deliveries are no longer discarded when jobs age past the window. **Verified only with mocks** (offline tests); no live Serper call, Sheet, Groq or Telegram was made for this change.

## Inventory: live numbers (2026-10-14, real downloads)

| Source | Rows (all providers) | Rows for supported providers | Rejected | Unique boards | Only in this source |
|---|---:|---:|---:|---:|---:|
| open-ats-feed (as of 2026-09-03) | 22,122 | 12,916 | 0 | 12,916 | 2,550 |
| ats-scrapers | 80,390 | 19,380 | 50 | 19,330 | 8,964 |

Overlap 10,366; **unique union 21,880** (Greenhouse 7,709, Workable 4,752, Ashby 4,041, SmartRecruiters 2,747, Lever 2,631). Case-only Lever/Workable variants across sources: 0. The 50 rejected rows are Ashby values with spaces (`hamming ai`): display names stored as slugs. Unsupported, reported and not imported: open-ats-feed 9,206 rows (Breezy 3,536, Teamtailor 2,840, Recruitee 2,830); ats-scrapers 61,010 rows across 42 providers (Join 23,547, BambooHR 5,632, Paycom 5,135, Workday 3,530, JazzHR 2,689, iCIMS 2,498, Personio 2,463, Rippling 1,923, ...). A second import changed **0 rows** (verified through the CLI).

## Validation: live sampling (not the full list)

Random sample, 25 boards per provider and source-group (250 total, SmartRecruiters excluded): 145 valid, 69 valid-empty, 36 invalid, 0 transient. Hit rate (valid with jobs): boards **both sources list 85%**, open-ats-feed only 60%, ats-scrapers only 36% (Ashby boards only ats-scrapers lists: 0 of 25 had jobs, 15 were invalid). Only 6 of 250 had a job matching the default title gate today (~2.4%): expect on the order of 500 relevant boards among ~21,900 at any moment. A balanced 600-board run (150 per provider, 174 s, Lever at its 1 req/s): 488 valid, 103 empty (Workable 85 of 150), 9 invalid. About 18,500 boards remain unvalidated; the daily workflow drains them.

Registry after a real CLI run (450 validated, then the hourly run): 21 boards promoted and polled (the ones with relevant jobs), 1,809 existing jobs recorded as baseline, 5 verified-fresh jobs all rejected by the title gate, 0 alerts; the next poll found 0 new IDs.

## Verification: mocked vs live

| Area | Result | How |
|---|---|---|
| Identity (casing per provider, region, unchanged job keys), parsers, last-known-good cache, schema-change and shrink guards, merge idempotence, provenance, overlap math | pass | **Mocked** (`tests/test_inventory.py`), 145 offline tests in total |
| Validation outcomes valid / empty / invalid / transient, retries and backoff, breaker, rate limits, SmartRecruiters policy, interleaving, batching | pass | **Mocked** |
| Activation budget (ceiling, surge cap, relevance order), baselining of imported boards, row-level writes, concurrent importer+poller | pass | **Mocked** |
| Rotation persistence and wrap, fixed credit budget, stall-based pagination stop, repeated-result counting, independent board/job processing, shared admission (SmartRecruiters parked for every source, activation ceiling across sources, one row and provenance per board), 12-hour boundaries (11:59 / 12:00 / 12:01, baseline exception, day precision), explicit 4 h kept and flagged, pending alert/scoring/hydration retries surviving age | pass | **Mocked** (`tests/test_discovery.py`, plus updated `test_core.py` / `test_hunter.py`): 200 offline tests in total |
| Board evidence (relevant / eligible counts, 7/30-day activity, unknown vs zero, baseline and re-entry exclusion, partial / failed / suspicious-empty polls change nothing), re-entry baseline, title-gate variants | pass | **Mocked** (`tests/test_pools.py`, `tests/test_core.py`) |
| Pools (labels, admission order, caps), weekly rebalance (score, margin, two weak cycles, replacement bound, trial protection, thin-evidence protection, capacity cut, determinism, report mode, crash safety), state preservation across demotion and re-entry, provider parking of monitored boards, Runs columns | pass | **Mocked** (`tests/test_pools.py`) |
| Two validation queues, importer write guard (Sheet and CSV stores), Settings, dry-run `--rebalance-report` leaves state files byte-identical | pass | **Mocked** (`tests/test_inventory.py`, `tests/test_hunter.py`); the Sheet store runs against a fake gspread worksheet only |
| Real Serper requests (query syntax per slot, `tbs`, credit use, result shape), real hit rate of rotating queries | not verified | needs `SERPER_API_KEY` |
| Downloading both inventories, parsing, merging, re-import, CLI (`--import-inventory`, `--validate`, `--offline`) | pass | **Live** (public GitHub + ATS endpoints) |
| Validation against real ATS endpoints, per-provider limits | pass | **Live**, sampled (above) |
| Transient-failure retry against a real outage | not observed | **Mocked** only (no outage occurred in live runs) |
| Groq scoring success path | pass | **Live** with the new default models: real job scored (15), real verdict; 429 -> fallback and `model_not_found` handling are **mocked** |
| Weekly/daily Board Inventory workflow, hourly schedule, GitHub cache | not verified | YAML parses; never run on GitHub |
| Google Sheets (tabs, hidden tabs, row-level upsert, header widening) | not verified live | **Mocked** (fake gspread): service account / Sheet not provided (backlogged) |
| Telegram delivery | not verified live | **Mocked**: token not provided (backlogged) |

## Migration requirements (board slot allocation)

- **Boards / Runs headers widen automatically** on the next run (13 new Boards columns, 9 new Runs columns; header row only, no data row is touched). Old rows load with unknown evidence (blank, never 0). A CSV state file with the old header is rewritten with the full header on the first save.
- **First hourly run after deploying:** every monitored SmartRecruiters board is parked (`deferred`, history kept; `ALLOW_SMARTRECRUITERS_BULK=1` + validation brings them back through a re-entry baseline); every board that was already monitored is labelled an exploration trial (7 days), so no board is demoted by the first weekly rebalance on tenure grounds and **nothing can leave monitoring through rebalancing until its trial has ended and evidence exists**. Activity counts stay blank until a board's stint is 7 days old.
- **New Settings rows are optional** (`Exploration_Share_Percent`, `Exploration_Days`, `Rebalance_Every_Days`, `Max_Replacements_Per_Rebalance`, `Rebalance_Mode`); a Sheet without them uses the defaults. The importer and the workflow arguments need no change (`--max-revalidations 2000` is already in `inventory.yml`).
- **To enable rebalancing:** review `python hunter.py --rebalance-report` (or run the Job Hunter workflow with `rebalance_report` ticked), then set `Rebalance_Mode` to `on` in Settings. Reverting is a Settings change; demoted boards are only `validated` rows and re-enter by the normal route.
- **Reversibility:** parking monitored SmartRecruiters rows rewrites their status; reverting the code does not restore them to `active`.
- Workflow files changed (`job_hunter.yml` input, `inventory.yml` argument): they have not run on GitHub.

## Known gaps / risks

- **Initial operating choices are unproven** (D-30): 80/20, 7-day trials, 20 replacements, the score weights, margin 1.0, two weak cycles and 84 complete polls. Pools only act once trials end, and the first real weekly report is the first evidence about them.
- Jobs first seen through Serper are not counted as board activity; partial listings are only detected for SmartRecruiters past 5,000 postings; a board's `Last_Job_Count` is still overwritten by a partial listing.
- Residual write window: the importer re-reads a row's status immediately before writing it, so a promotion landing in those milliseconds can still be overwritten (job state is unaffected: it lives in `Events`). Provenance updates of boards that are monitored at import time are skipped until they leave monitoring.
- Rebalancing never ran on real boards: report-mode output on a real registry has not been seen.

- **Search cannot promise full coverage of the 12-hour window.** Google indexing delay, a rotation that covers at most ~20 of 336 slots per day (default Settings), the per-query page cap, the credit budget and late or skipped GitHub runs all cause misses. Only jobs on polled boards have the hourly-poll guarantee.
- A full rotation takes about 17 days at best (10 credits x 2 runs/day) (see D-18); slot count depends on Settings.
- Existing registries: SmartRecruiters boards activated by Serper are now parked on the first run (see Migration above); a Sheet still holding `Fresh_Window_Hours = 4` keeps 4 and is flagged each run. Sheets without `Discovery_Credit_Budget` use the default; the hidden `Discovery` tab and the new `Runs` columns are created / widened on the next run.
- Serper credits are counted as one per page request; actual billing was not checked.

- Validation is still draining: ~18,500 candidates unvalidated; the daily workflow works through them (Lever alone needs ~44 min per full pass at 1 req/s).
- Which boards are monitored depends on a snapshot of title relevance; a waiting board that posts a relevant job tomorrow is only re-checked weekly. Coverage = monitored boards, not all 21,900.
- Baseline jobs are never scored (no backfill): the first read of a board is a starting point only.
- SmartRecruiters: imported boards parked (robots.txt); existence of a SmartRecruiters board is unverifiable (API returns 200/empty for unknown companies).
- Inventory data is a snapshot: open-ats-feed `as_of` 2026-09-03; boards may have gone. Validation catches 404s only when it runs.
- `Events` grows with every observed ID (baselines included); a large activation wave adds thousands of rows.
- Existing Sheets created before this change keep the old registry header until the next run widens it; new Settings rows (`Max_Active_Boards`, `Max_New_Boards_Per_Run`) are absent from old Settings tabs, so defaults apply.
- Alerts are at-least-once. `.env.example` cannot be written in this environment (permission rule); the template is in the README.

## Blockers

Sheets and Telegram credentials (backlogged at your request) for a full live end-to-end run; GitHub workflows have not run on GitHub.

## Next milestone

First run of both workflows on GitHub with a real Sheet: import, validate for a few days, watch `Runs` (discovered / validated / monitored, gaps) and confirm the hourly poller stays within its time budget as the monitored set grows toward `Max_Active_Boards`. Then Telegram.
