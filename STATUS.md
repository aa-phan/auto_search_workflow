# STATUS

Last updated 2026-10-23 (pilot week 1 closed; graduation floor D-45; tracker header refusal D-46; before that 2026-10-17: watchdog, pilot-report corrections and storage scoping, D-42 and D-43; before that operational dashboard, D-40; before that search provider Serper -> Tavily, D-36; before that board slot allocation, D-23..D-30; before that the discovery rotation / 12-hour window change, D-17..D-21). Read `SPEC.md` (contract) and `DECISIONS.md` (why) first.

## Pilot week 1 result (2026-10-15 01:47 to 2026-10-22 01:47 UTC; measured live 2026-10-23 20:17 UTC)

All figures from the read-only `pilot_report` and `rebalance_report` workflow runs against the production Sheet (**live**). Window of the report: the last 168 h.

| Criterion (DEPLOY.md section 9) | Result |
|---|---|
| Seven full days of runs | 168 of 168 hourly intervals had a successful poll; no gap over 90 min; 207 runs, all `ok`; 0.31% of 103,500 board polls failed |
| Real alert through scoring, tracker and Telegram | 20 alerts, 20 unique jobs, 0 duplicates, 0 failed sends, 1 labelled late (Telegram receipt not checked by the agent) |
| Schedule fires | 38 `schedule` runs (about every 4.4 h) plus 168 `workflow_dispatch:external`: the external trigger carries the hourly cadence |
| Pending failures | 0 awaiting evaluation, 0 awaiting alert, 0 hydration retries |
| Search credits | 140 in 7 days (20/day: at the stop threshold, not over) |

**Freshness:** publication -> detection, verified-fresh poll jobs median 29 min, p90 54 min (n=310); search-found median 455 min (n=8); all time-precise relevant jobs 79% inside the 12 h window (n=402). Publication -> alert median 29.5 min. **Funnel (one cohort):** 19,380 new postings -> 472 relevant -> 212 rejected after reading (location 131, experience 71, language 10) -> 260 scored -> 47 kept -> 20 alerted (about 3 a day). **Limits:** run median 113 s, max 770 s (51% of the 25 min timeout); Sheets reads peak 12.4/min (quota ~60); no ATS or Groq 429s; Events 140,668 rows, ~2,900/day. **Coverage:** 500 monitored (all exploration trials), 849 relevant boards waiting, 33% of known relevant boards. **Re-checks:** 12,460 validated boards overdue (the daily budget cannot re-check ~21,000 boards weekly); 0.7% of re-checks gained relevant jobs and all 55 gainers still wait for a slot. **Feedback:** labelled on most tracker rows (the report could not read them until the header fix below).

**Changes after the pilot (deployed 2026-10-23 20:52 UTC, commit 76726a6; see PILOT_LOG):**
- **D-45 graduation floor** (`pools.GRADUATION_FLOOR` = 2.0): a free established slot needs a score of at least 2; offline tests (the floor test fails when the floor is 0). The user set `Max_Active_Boards` to 700 and `Rebalance_Mode` to `on` in Settings at deployment. **Live, first run on 76726a6 (2026-10-23 21:00 UTC):** pools read "established 0/560, exploration 550/140, monitored 550/700, 799 relevant boards waiting, coverage 37%"; 50 waiting boards started trials, so 700 is in effect and the set fills by 50 a run (about 3 more runs to 700). That run added 7,424 new job IDs (mostly baselines of the new boards) and sent 0 alerts, so D-46 is still unverified live; `Rebalance_Mode` on is not visible until the rebalance runs. Without the floor all ~495 ended trials, including ~94 scoring 0-1, would take established slots. The next rebalance is due about 2026-10-29 01:00 UTC.
- **D-46 tracker header** (found live): row 1 had been cleared, so four rows (10/22 10:03 PM and three on 10/23) were written by fixed position and the report could not read the tracker. **Sheet repaired live** through the Sheets connector (header restored in the user's order, the four rows rewritten in place, read back and checked). Code now refuses to write without a header, reads every cell for duplicate protection, strips header names in reports and flags it on the dashboard; **mocked** tests only (520 offline pass; mutation checks on refusal and name stripping fail the suite). Not yet verified live: the next tracker row after deployment.


## State

Board polling -> new-ID detection -> freshness classification -> filters/scoring -> Sheet -> Telegram is implemented (D-01..D-09). This change adds the **inventory loop** (D-11..D-15): the registry is seeded from two public inventories, validated through the existing adapters, and promoted into hourly polling only within a budget. Groq model defaults changed because the requested models no longer exist for this key (D-16).

Latest change (D-23..D-30, quick task 261014-olj): board slot allocation. A complete hourly poll now refreshes each monitored board's relevant / eligible counts and new-posting activity from the listing it already fetched; `Max_Active_Boards` is split into an established pool (400) and an exploration pool (100) with 7-day trials; a weekly bounded rebalance compares ended trials with the weakest established boards (**report mode by default**; `python hunter.py --rebalance-report` previews it); demoted boards keep their ledger, baseline, provenance and pending retries and re-enter with a re-established baseline; monitored SmartRecruiters boards are parked every run (history kept); validation runs two independently budgeted queues so re-checks no longer starve behind the candidate backlog; the title gate accepts "Internship", "Jr.", "Entry-Level" and "New Grad" variants. **Everything for this change is verified only with offline mocks: no live Sheet, Groq, Telegram, Serper or GitHub Actions run, and no real ATS call, was made** (tests: 275 offline).

Previous change (D-17..D-21): scheduled discovery is a persistent rotation of date-windowed searches within a credit budget (unfiltered search is manual `--backfill` only); every source goes through one board-admission path; the freshness window is 12 hours (discovery interval is a separate setting); pending deliveries are no longer discarded when jobs age past the window. **Verified only with mocks** (offline tests); no live Serper call, Sheet, Groq or Telegram was made for this change.

## Tracker column order (D-44)

**Fixed:** the app wrote tracker rows by fixed position, so moving `My_Feedback` put seven new rows one column off (rows 38 to 44); it now writes and reads by header name. The seven rows were repaired by hand in the live Sheet and checked by screenshot (values under the right headers, dropdowns and colours intact, links restored). **516 offline tests** pass (8 new in `tests/test_hunter.py`; mutation checks on the three lookups fail the suite). **Not verified live:** no new tracker row has been written since the fix; the next real alert (or a `delivery_test`) will show it.

## Pilot reliability and reporting fixes (D-42, D-43; see PILOT_LOG.md for deployment times)

**Built:** `watchdog.py` + `.github/workflows/watchdog.yml` (independent missed-run watchdog), pilot-report corrections and a reconciliation section, `Runs.Code_Version`, `--storage-report` (read only), `PILOT_LOG.md`. **508 offline tests** pass (60 new: `tests/test_watchdog.py`, `tests/test_pilot_corrections.py`, `tests/test_storage_report.py`; mutation spot-checks on six watchdog behaviours fail the suite). Nothing in discovery, filtering, scoring, board capacity, allocation or `Rebalance_Mode` changed (the pipeline diff is the version tag).

| Check | Result | Live or mocked |
|---|---|---|
| Watchdog states: healthy, stale (failed / stalled / absent), running, recovered, unavailable, dedupe (one outage, one recovery), failed-send retry, dry run, threshold, rehearsal runs ignored, no hunter imports, own concurrency group | pass | **mocked** (fake store and notifier; nothing production was touched) |
| Watchdog read of the production `Runs` tab (`--dry-run`) | HEALTHY, last success 29 min earlier, nothing written or sent | **live**, read only |
| Watchdog Telegram delivery, incident tab creation, real outage / recovery | **not verified** | no outage has occurred; no test message was sent (none was requested) |
| Pilot report: elapsed denominator, distinct intervals, gaps, workflow vs board polls, latency sample, coverage populations, code versions, reconciliation | pass | **mocked** tests, then **live** (the pilot report run of 2026-10-17 19:31 UTC printed every section) |
| Dashboard and pilot report agree on the same window | pass | **mocked** (same window, same per-job definitions); not compared live at one instant |
| Storage report | pass | **mocked** tests, then **live** read only |

**Watchdog hosting:** GitHub Actions workflow `Watchdog` (own concurrency group, GitHub schedule every 15 minutes). **Notification:** Telegram to `TELEGRAM_CHAT_ID`. **Remaining setup (owner):** a second, external trigger for `watchdog.yml` (DEPLOY.md "Watchdog"), because GitHub's own schedule has fired only about every 4.7 hours here; optionally set the repository variable `WATCHDOG_WARN_HOURS`.

## Operational dashboard (D-40)

**Built:** `reporting.py` (pure summary), `dashboard.py` (render + one-batch publish), run-start records and the new `Runs` / ledger fields, `--dashboard` and `--dashboard --dry-run`, refresh after every poller run (contained). **448 offline tests** pass (50 new in `tests/test_reporting.py`: totals checked against hand-built ledgers and real pipeline runs for retries, duplicate observations, partial failures, missing dates, local-day boundaries, exclusions, idempotence; mutation spot-checks on nine behaviours each fail the suite).

| Check | Result | Live or mocked |
|---|---|---|
| Summary totals vs the ledger (unique vs attempts, alerts, rejections partition, freshness denominators, latency split, boundaries, rehearsal / fixture exclusion) | pass | **mocked** (fake ATS, CSV state) |
| Run-start record visible during a run; one record per run; failed / degraded outcomes; gap ignores interrupted runs | pass | **mocked** |
| Dashboard tab written in one batch, only that tab, tracker feedback untouched, rerun identical, failure contained | pass | **mocked** (fake spreadsheet: request shapes are NOT validated by the real Sheets API) |
| Charts, sparklines and the compact layout (D-41): every request validated against Google's Sheets v4 discovery schema (0 problems); chart data block, fixed ids and delete-then-add checked | pass | **mocked** + schema (not rendered) |
| Dashboard rendered in the real Sheet and inspected through the user's signed-in Chrome (fonts, hidden data block, four charts, cards, tables render; the Sheets API accepted the batch) | pass | **live** (one Sheet, one browser size) |
| Rendered tab inspected in a real Sheet (earlier note, superseded above); first refresh; `Runs` header widening to 65 columns; Actions run | **not verified** | no Sheet credentials / GitHub repository here |

**Remaining setup:** none required (the tab and the new `Runs` columns are created on the first run). Rows written before this change show `n/a` for the new fields. Open items: view the first real render (column widths, merged cells, colours) and adjust; the daily Telegram digest and the independent missed-run watchdog are documented in SPEC and not built.

## Deployment and pilot status (running log)

- **Deployed:** private-then-public repo, secrets set, Sheet connected, Telegram group delivery verified (labelled fixture), two manual polling runs (second added 0 jobs: no duplicates), a quota failure under back-to-back runs found and fixed (retry on HTTP 429), SmartRecruiters unparked by decision (D-38), Board Inventory enabled with its schedule.
- **Diagnostics for the limits audit** (this change): per-run duration and phase times, Google Sheets request counts and quota rejections, ATS and Groq request counts and 429s, and Events/Boards row counts are recorded in `Runs` and summarized in the pilot report (`LIMITS AUDIT`). Measured values only exist from this change onward.
- **Since then (2026-10-23):** the schedule fired (38 `schedule` runs in the last 7 days), 20 real alerts were delivered and the seven-day pilot is complete (see "Pilot week 1 result" above).

## Deployment preparation and pilot (D-37)

**Prepared, not yet deployed.** What exists: `DEPLOY.md` (private-repository setup, the exact secret names, Sheet/service-account/Telegram setup without sharing values, manual-run and schedule checks, the seven-day pilot protocol); read-only `--pilot-report` and a labelled `--delivery-test`; the user-owned `My_Feedback` column; 429 provider backoff; completeness by documented pagination behaviour; a flock-based local lease and the refusal of local production writes; workflows reduced to `contents: read` with no commit steps and a configuration check that names (never prints) missing secrets. **375 offline tests** pass.

| Check | Result | Live or mocked |
|---|---|---|
| Rotation duration from requests actually consumed (`--search-usage`) | 42 slots, 1.00 request per slot (Tavily cannot paginate), 1.00 credit per request, 10 slots per run -> **2.1 days per full pass, 600 credits a month** at 2 runs a day (inside the 800 scheduled allowance); the figure is recomputed from the ledger and the last discovery's per-query page counts, so pagination or a higher cost would lengthen it | measured from the 10-request live run |
| Lease: simultaneous acquisition | file lease: 12 threads and 2 processes -> exactly one holder (an earlier create-then-write version let 5 in; fixed with flock). **Sheet lease: not atomic** (a test shows two writers both verifying), so it is not relied on | mocked (real kernel locks for the file lease) |
| Lease: expiry during a long run, owner-only release | Sheet lease expires after its TTL (30 / 45 min, above the 25 / 40 min workflow timeouts, asserted); a run that outlives it logs an error; only the token holder releases | mocked |
| Local production writes | refused (exit 4) unless in GitHub Actions or `ALLOW_LOCAL_SHEET_WRITES=1` for a test Sheet | mocked |
| Provider backoff (429), completeness per endpoint | Workable 429 stops that provider for the run, skipped boards keep their state; Lever continued with `skip` at page-size lengths, Workable flagged possibly truncated, Greenhouse/Ashby documented unpaginated | mocked (Workable's 429 itself was seen live earlier) |
| Delivery fixture scoring | the fixture was scored by the real Groq model (90) | live (Groq only; the Sheet and Telegram steps are not configured) |
| Sheet migration, effective settings, 12 h window check in a real Sheet; Telegram delivery; Actions runs (manual twice, scheduled) | **blocked** | no Sheet, service account, Telegram credentials or GitHub repository yet |

**Counter correction.** "Eligible boards" counts validated or monitored boards among *all* boards the search results named, new or already known; the `Result_*` columns now make that explicit (see SPEC "Board counters").

## Search provider migrated to Tavily (D-36)

Serper is gone from the code, the workflow and the settings; discovery calls Tavily (`search.py`), every search path shares a persistent monthly credit ledger (default 1,000, 800 for scheduled runs), exhaustion skips discovery while polling continues, and the Serper-era rotation cursor is discarded (restart at slot 0, noted once in `Runs.Notes`). Registry, ledger, history and delivery code are unchanged. **333 offline tests** pass (30 new in `tests/test_search.py`; mutation spot-checks on every new behaviour fail the suite).

| Step | Result | Live or mocked |
|---|---|---|
| Request mapping (`include_domains`, `start_date`, `basic`, no answer/raw content), response normalisation, credit accounting, 401/429/432/433 handling | pass | **mocked** (fake HTTP) |
| Monthly ledger: shared paths, reserve, month rollover, account-counter merge, exhaustion skip, persistence on failure and dry run, cursor migration | pass | **mocked** |
| Tavily `/search` parameters: window, domain, credit cost per mode | checked against the current API reference and **live** (response `usage.credits` = 1 for basic and fast) | live |
| Window quality (Greenhouse, 7 roles, ATS publication times): no window 19% of dated jobs within 72 h; `start_date` -3 d 95%; `time_range=week` 66%; `fast`+window 0% | measured | live |
| Real pipeline run on the rehearsal registry (manual `--discover`, 10 slots) | 10 credits charged to the ledger. The results named **126 unique boards**: **41 new** to the registry and **85 already known** (from the public lists). "51 eligible" = validated or monitored boards among all 126: 10 of the new ones + 41 of the known ones (6+4 new, 36+5 known). The other 75 were 17 parked (SmartRecruiters), 14 new + 44 known awaiting validation (inline validation is capped at 40 per run). 9 promoted, 1 verified-fresh match, 3 jobs scored by real Groq (reconstructed from the registry's provenance; the `Result_*` columns now record this directly); the Serper-era cursor was reset; SmartRecruiters boards found were parked | live (rehearsal registry in a scratch directory; nothing in the repo or any Sheet was touched) |
| Tavily vs Serper, same 10 slots, 10 credits each | Tavily 181 URLs / 156 boards / 27 title-gate jobs (16 US-eligible); Serper 73 / 65 / 15 (8); board overlap 54, Tavily-only 102, Serper-only 11; 69% vs 68% of dated jobs published within 72 h, 10% vs 9% within 12 h | live, one day, one sample |
| Account credit counter (`GET /usage`) | still **0** after about 55 credits (the 54 measured by response `usage.credits`: 6 + 28 probe requests, 10 pipeline, 10 comparison); local ledger recorded the pipeline's 10 | live; the account counter cannot be used to verify cost yet |
| GitHub secret `TAVILY_API_KEY`, scheduled run | **not verified:** no GitHub remote exists for this repository | blocked |

**Other account usage the local counter cannot observe:** anything not made through this application (other keys or projects, the probes and comparison runs above: about 44 credits of the 54 were spent by hand scripts, not by the pipeline), and the day Tavily's billing cycle starts (undocumented in the API reference; the local count resets at the UTC month). `python hunter.py --search-usage` prints both counters. **Migration steps for you:** add `TAVILY_API_KEY` to `.env` and to the GitHub secrets (the old Serper key is no longer read), nothing else is required; the Settings rows `Search_Monthly_Credits` and `Search_Reserve_Credits` are optional.

## Correctness pass and live verification (D-31..D-35)

**Changed:** shared concurrency group + advisory writer lease + provenance reconciliation (D-31); cool-down, bounded trial rotation and slack fix in the allocation (D-32); observed-time rates, gap-discovery rule, Serper-found activity, Greenhouse completeness (D-33); discovery slot query reduced to site + role (D-35). 303 offline tests (28 new targeted ones in `tests/test_allocation_correctness.py`); mutation spot-checks on each fix fail the suite.

**Live, with the credentials that exist on this machine** (at that time `GROQ_API_KEY` and a Serper key under `SEARCH_API_KEY` were configured; `TAVILY_API_KEY` has since been added; no Sheet, no service account, no Telegram, no GitHub remote for this repo):

| Step | Result |
|---|---|
| Public inventory download + 760 real ATS validations (Greenhouse/Ashby/Lever) | 723 valid, 26 empty, 11 invalid, 0 transient; two validation queues reported separately |
| Hourly poll on a local rehearsal registry (CSV in a scratch directory, nothing in the repo touched) | 28 real boards promoted (3.7% of the first 749 validated boards had a job matching the default title gate; those boards were validated in priority order, not sampled at random, so this is not an estimate of the whole inventory), 3,579 existing jobs baselined, 39 time-verified fresh on the baseline pass, 0 evaluated before search added 1 |
| Real Groq scoring through the real gates (`--url`, a real 14-day-old Coinbase posting, age limit raised for the test only) | scored 45 -> "Filtered Out": the path ATS -> eligibility -> Groq works; `openai/gpt-oss-120b` answered |
| Real Serper rotation (the previous provider), 3 runs x 10 queries, cursor persisted between runs | cursor 10 -> 20 -> 30 of 42 in the state store; first two runs returned 0 results for all 20 queries (location/level/exclusion terms), after the fix 5 results from 10 queries, 2 new boards admitted, 1 promoted, 1 search-found job read and filtered |
| Real rebalance report | printed from the rehearsal registry: nothing due (all 29 boards are inside their first trial) |
| Sheet migration, effective settings in a real Sheet | **blocked:** no `GOOGLE_SHEET_ID` / `GOOGLE_SERVICE_ACCOUNT_JSON` |
| Telegram test message | **blocked:** no `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`, and no recipient was named as authorized |
| GitHub workflow run, scheduled run | **blocked:** this repository has no remote and no GitHub repository exists for it; nothing can run on Actions, so scheduled behaviour is **not** verified |

## Inventory: live numbers (2026-10-14, real downloads)

| Source | Rows (all providers) | Rows for supported providers | Rejected | Unique boards | Only in this source |
|---|---:|---:|---:|---:|---:|
| open-ats-feed (as of 2026-09-03) | 22,122 | 12,916 | 0 | 12,916 | 2,550 |
| ats-scrapers | 80,390 | 19,380 | 50 | 19,330 | 8,964 |

Overlap 10,366; **unique union 21,880** (Greenhouse 7,709, Workable 4,752, Ashby 4,041, SmartRecruiters 2,747, Lever 2,631). Case-only Lever/Workable variants across sources: 0. The 50 rejected rows are Ashby values with spaces (`hamming ai`): display names stored as slugs. Unsupported, reported and not imported: open-ats-feed 9,206 rows (Breezy 3,536, Teamtailor 2,840, Recruitee 2,830); ats-scrapers 61,010 rows across 42 providers (Join 23,547, BambooHR 5,632, Paycom 5,135, Workday 3,530, JazzHR 2,689, iCIMS 2,498, Personio 2,463, Rippling 1,923, ...). A second import changed **0 rows** (verified through the CLI).

## Validation: live sampling (not the full list)

Random sample, 25 boards per provider and source-group (250 total, SmartRecruiters excluded): 145 valid, 69 valid-empty, 36 invalid, 0 transient. Hit rate (valid with jobs): boards **both sources list 85%**, open-ats-feed only 60%, ats-scrapers only 36% (Ashby boards only ats-scrapers lists: 0 of 25 had jobs, 15 were invalid). Only 6 of 250 had a job matching the default title gate that day (2.4%; a 95% interval of roughly 1%-5%). **That sample does not establish how many relevant boards exist:** extrapolated to ~21,900 boards it spans a few hundred to over a thousand, and 6 hits is far too few to say whether 500 slots can be filled. Filling `Max_Active_Boards` is not a launch prerequisite: the pilot starts with whatever boards are validated and relevant. A balanced 600-board run (150 per provider, 174 s, Lever at its 1 req/s): 488 valid, 103 empty (Workable 85 of 150), 9 invalid. About 18,500 boards remain unvalidated; the daily workflow drains them.

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
| Real Tavily requests: slot request shape, credit use, hit rate of the rotation | see "Search provider migrated to Tavily" above | live (rehearsal) |
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
- Jobs first seen through web search count as board activity only when their own source time proves them fresh; partial listings are only detected for SmartRecruiters past 5,000 postings; a board's `Last_Job_Count` is still overwritten by a partial listing.
- Residual write window: the importer re-reads a row's status immediately before writing it, so a promotion landing in those milliseconds can still be overwritten (job state is unaffected: it lives in `Events`). Provenance updates of boards that are monitored at import time are skipped until they leave monitoring.
- Rebalancing never ran on the production registry (none exists yet: no Sheet credentials here). A real report exists only for a rehearsal registry built from the live inventory (below).

- **Search cannot promise full coverage of the 12-hour window.** Google indexing delay, a rotation that covers at most ~20 of 42 slots per day (default Settings), most of which return nothing in the window, the per-query page cap, the credit budget and late or skipped GitHub runs all cause misses. Only jobs on polled boards have the hourly-poll guarantee.
- A full rotation is 42 site x role slots (default roles) = about 2 days at 10 credits x 2 runs/day (see D-18, D-35); live, most slots return 0 results in the 3-day window, so search adds only a trickle of boards and jobs.
- Existing registries: SmartRecruiters boards activated by Serper are now parked on the first run (see Migration above); a Sheet still holding `Fresh_Window_Hours = 4` keeps 4 and is flagged each run. Sheets without `Discovery_Credit_Budget` use the default; the hidden `Discovery` tab and the new `Runs` columns are created / widened on the next run.
- Search credits come from each response's reported cost (1 per basic search); the provider's account counter lagged (still 0) so it cannot yet confirm them. Tavily has no pagination, so a slot yields at most 20 results.

- Validation is still draining: ~18,500 candidates unvalidated; the daily workflow works through them (Lever alone needs ~44 min per full pass at 1 req/s).
- Which boards are monitored depends on a snapshot of title relevance; a waiting board that posts a relevant job tomorrow is only re-checked weekly. Coverage = monitored boards, not all 21,900.
- Baseline jobs are never scored (no backfill): the first read of a board is a starting point only.
- SmartRecruiters: imported boards parked (robots.txt); existence of a SmartRecruiters board is unverifiable (API returns 200/empty for unknown companies).
- Inventory data is a snapshot: open-ats-feed `as_of` 2026-09-03; boards may have gone. Validation catches 404s only when it runs.
- `Events` grows with every observed ID (baselines included); a large activation wave adds thousands of rows.
- Existing Sheets created before this change keep the old registry header until the next run widens it; new Settings rows (`Max_Active_Boards`, `Max_New_Boards_Per_Run`) are absent from old Settings tabs, so defaults apply.
- Alerts are at-least-once. `.env.example` cannot be written in this environment (permission rule); the template is in the README.

## Blockers

None. (Superseded: the Sheets / Telegram credential and "never ran on GitHub" blockers ended with the deployment of 2026-10-15; the pilot ran live end to end, see "Pilot week 1 result".) Still owner setup: a second, external trigger for the watchdog (see "Pilot reliability and reporting fixes").

## Next milestone

Post-pilot week at 700 boards with `Rebalance_Mode` on (from 2026-10-23 20:52 UTC, PILOT_LOG):
1. **D-46 live check:** the first tracker row written after the deployment lands under the right headers.
2. **First real rebalance** (due about 2026-10-29 01:00 UTC): read the `rebalance_report` run and check graduations against the floor (D-45), replacements against the bound, and that no board moved on thin evidence. This is the first evidence about the D-30 operating choices.
3. **Limits at 700:** run duration against the 25 min timeout, Sheets reads per minute and Events growth (compare with the 500-board pilot and the storage report projection; not comparable across the 2026-10-23 change).

4. **Wider title and location Settings** (2026-10-23 21:21 UTC, PILOT_LOG; aim: 20-30 tracker rows a day, pilot was about 7): watch relevant jobs per day, the share scored 50+, tracker rows per day, Groq 429s, and whether sales / support / accounting titles still reach the tracker. Checked offline only against the title gate (sample titles); the live effect is unmeasured. The user's existing roles `Account`, `Digital`, `Community` and `Social` are broad; the new exclusions block the known leaks (accounts payable, digital sales, social worker) but not, for example, "Community Associate" (often front desk).

No score tuning or new features until these are read (AGENTS.md rule 7).
