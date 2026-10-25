# Architecture Research: v2.0 "Search-substitute volume"

**Domain:** subsequent milestone on an existing batch pipeline (hourly GitHub Actions run, Google Sheet as the only datastore and UI)
**Researched:** 2026-10-25
**Confidence:** HIGH for integration points and cost model (read directly from the code and DECISIONS.md); MEDIUM for Groq/Tavily limits (provider docs via secondary sources, account tier unverified); LOW for new-ATS API details (community write-ups only, must be re-verified in phase research)

Scope: only how the six v2.0 features integrate with what exists. The v1.0 structure is in `.planning/codebase/ARCHITECTURE.md` and `STRUCTURE.md` and is not repeated.

## Bottom line (read this first)

1. **Four of the six features are small, local changes to existing seams.** Recent backfill and the 72 h tracker window are one new setting plus changes in `freshness.classify`, `ledger.Observation`/`observe_new`, the evaluator's age gate and `pipeline` (no new class, no new alert path). Board-cycling score is new evidence columns plus a new `pools.score` variant. Wider search is `discovery`/`search` parameters. None needs a new component beyond a pure `feedback.py`.
2. **Two are structural:** the Events storage migration (D-43) and new ATS adapters. Both are gated by things the user did not list: adapter work is gated by a **day-precision decision** (Workday-class sites publish only a date), and scaling is gated by an **evaluation-throughput limit** (Groq tokens), not by polling.
3. **The hidden bottleneck is evaluation, not polling.** `GroqClient` paces at 8,000 tokens/min by default and a call is roughly 4-5k tokens; 30 evaluations in one run can take ~20 minutes, and nothing in `run_cycle` stops evaluating before the 25-minute workflow timeout. Backfill creates exactly that burst (50 newly admitted boards in one run). A time budget and a daily token ledger come before backfill ships.
4. **Replay cost is driven by characters read from Sheets (twice per run), not by CPU.** The dashboard refresh reloads the whole Events tab after the run already loaded it. A process-level cache in `SheetState` halves reads with no behaviour change.
5. **Recommended storage design = D-43, with three amendments** (Section "Storage"): route by disposition, write per-run `Tally` rows instead of daily upserts, and swap in a rebuilt Events tab instead of deleting rows in place. Archive is needed sooner than D-43 assumed because v2 volume raises operational rows about 4-10x.
6. **Build order:** measure -> safety rails -> backfill + windows -> storage migration -> cycling evidence (shadow) then score -> raise board cap in steps -> adapter registry then first new ATS -> wider search. Reasons in "Build Order".

## Standard Architecture (v2.0 deltas on the hourly run)

Legend: `(NEW)` new component or step, `(MOD)` modified, unmarked = unchanged.

```
 hunter.py main -> Settings (MOD: Tracker_Window_Hours, Board_Score_Model, Poll/Eval budgets)
        |
        v
 pipeline.run_cycle
 ├─ load: boards, runs, events (MOD) + identity index (NEW, after STOR) ; events cached for dashboard (MOD state.py)
 ├─ 1 discovery   discovery.py/search.py (MOD: slot yield stats, window from Tracker_Window, credits)
 ├─ 2 poll        boards.poll_boards (MOD: oldest-first order, deadline guard, adapter registry)
 │      per board result:
 │        freshness.classify (MOD: baseline_pass + tracker window -> RECENT instead of BASELINE)
 │        ledger.observe_new  (MOD: detail.backfill, route -> Event row | Identity add + Tally)
 │        pools.refresh_relevance (MOD: + Recent_Relevant_72h from listing dates, no ledger needed)
 │      board evidence: pools.refresh_activity, feedback.tallies (NEW, pure) -> Boards columns (MOD)
 │      pools.score / score_v2 (NEW) -> sync_pools, plan_rebalance, early_releases, admission_order (MOD)
 ├─ 2b search hydration (MOD: MAX_SEARCH_HYDRATIONS becomes a Deps field)
 ├─ durable point: identity -> events + tally -> boards -> discovery state (MOD order, same rule 1)
 ├─ 3 evaluate    (MOD: deadline + daily token ledger; expire out-of-window RECENT without Groq)
 │      hunter.make_evaluator age gate in hours (MOD); EVALUATED payload gains age_min_found (MOD)
 └─ 4 alert       unchanged (ALERTABLE = verified_fresh, Fresh_Window_Hours = 12)

 tracker row: Date_Found, Date_Posted, Freshness label, Age_Hours (NEW optional column)
 reporting.py / dashboard.py / pilot.py (MOD, pure): rows/day, age-at-found, feedback by label
```

### Component Boundaries

| Component | Responsibility in v2.0 | New / Modified | Communicates with |
|-----------|------------------------|----------------|-------------------|
| `freshness.py` | `classify` gets a `track_window` (72 h) and a day-precision upper-bound rule; baseline pass can return RECENT | MOD | `ledger`, `hunter` evaluator |
| `ledger.py` | `Observation.track_window`, `detail.backfill`, routing of identity-only observations, `Tally`, `replay(events, identity)` facade, `is_seen()` | MOD | `pipeline`, `state`, `pools`, `reporting` |
| `identity.py` | Pure: per-board ID sets, 40k-char chunking, merge, optional retention | NEW (after STOR approval) | `ledger`, `state` |
| `pipeline.py` | Deps fields, observation block, durable-point order, evaluate deadline, expiry of stale RECENT, tally | MOD | everything |
| `hunter.py` | Settings keys, evaluator age gate (hours), `JobRow` age, Deps wiring, tracker column ensure, tracker read for feedback | MOD | `pipeline`, `feedback` |
| `state.py` | Identity and Tally tabs, events cache, `BOARD_COLUMNS` and `RUN_COLUMNS` appended at the end | MOD | Sheet / CSV |
| `pools.py` | Recent-relevant evidence, expected-useful-postings score (shadow then live), admission order | MOD | `boards`, `inventory`, `pipeline` |
| `feedback.py` | Pure: tracker rows -> per-board `My_Feedback` tallies via `parse_job_url` | NEW | `hunter` (reads tracker), `pools` |
| `boards.py` | Adapter registry, deadline-aware polling, new `BoardRecord` fields, Workday-style composite identifiers | MOD | `inventory`, `hunter` |
| `inventory.py` | `ValidationResult.recent`, `apply_validation` writes recency, `SUPPORTED_ATS`, ident sanity for composite ids, provider policy | MOD | `boards`, `pools` |
| `discovery.py` / `search.py` | Slot yield stats and weighting, `start_date` tied to the tracker window, hydration cap as a setting | MOD | `pipeline` |
| `eval_budget.py` | Persistent daily token ledger (same pattern as `search.SearchBudget`, stored in `Discovery` key `eval_budget`) | NEW | `pipeline`, `hunter` |
| `reporting.py`, `dashboard.py`, `pilot.py`, `storage_report.py` | New measures; parity command for the migration | MOD | read-only |

## Feature 1 and 2: recent backfill and the 72 h tracker window

### What the code does today (verified in `freshness.py`, `ledger.py`, `pipeline.py`, `hunter.py`)

- `classify(baseline_pass=True)` returns `VERIFIED_FRESH` only when the time-precise age is within `fresh_window`; everything else is `BASELINE` (disposition `baseline`, never evaluated).
- **Re-entry already does most of the backfill.** For a re-entering board the dated unseen job outside the window is `RECENT` (or `STALE` past `Max_Job_Age_Days`, default 14) and is evaluated. Only the **first** baseline pass and the flood re-baseline are blind. Ordinary polls also already evaluate dated jobs up to 14 days old as `RECENT`, so today the tracker is not limited to 72 h at all (it accepts up to `Max_Job_Age_Days`).
- The evaluator's age gate (`hunter.make_evaluator`, `job_age_days`) is in whole days, so it cannot express 72 h for time-precise dates.
- `RECENT` is not alertable (`ALERTABLE = {verified_fresh}`) and `pools.counts_as_new_posting` already excludes `recent` and baseline/re-entry passes, so a backfilled job cannot become an alert or fake "new-posting activity".

### Integration (no new freshness class)

1. **One new setting** `Tracker_Window_Hours` (default 72) next to `Fresh_Window_Hours` (12). It replaces `Max_Job_Age_Days` as the effective stale boundary: `stale_after = min(Tracker_Window_Hours, Max_Job_Age_Days * 24)`. Backfill and tracker use the same number (backfilling beyond the tracker window would just be `STALE`). The two windows are already separate in code (`Deps.fresh_window`, `Deps.max_age_days`); add `Deps.tracker_window` and pass one `Windows` pair through `Observation` so no gate can disagree.
2. **`freshness.classify`:** in the `baseline_pass` branch, a time-precise age inside `track_window` returns `RECENT` with the evidence line "published N h ago (source timestamp) on a board being baselined; inside the 72 h tracker window". Older -> `BASELINE`. Time-precise ages beyond the tracker window on ordinary polls become `STALE` instead of `RECENT`.
3. **`ledger.observe_new`:** add `detail["backfill"] = True` when the baseline pass produced the class (the `pass` key already records "baseline"/"reentry"). Reporting separates these jobs the way `pilot.py` already separates baseline-pass jobs.
4. **Evaluator age gate:** hours-based for `precision == time`, days-based for date-only. `reject="age"` keeps its meaning.
5. **Age always shown:** compute `age_min_found` at tracker-write time (`now - last_published`) in `pipeline` and store it in the `EVALUATED` payload; `hunter.JobRow` renders it. Two options: put it in the existing `Freshness` text ("Recent, 31 h old when found", no tracker migration) and/or add a numeric `Age_Hours` column. A new column must be appended by header name (find the first empty header cell), never by position, and `tracker_row_for_header` must keep dropping values whose header is missing, so a user who deletes the column cannot fail a run (D-44, D-46).
6. **Evaluation queue hygiene (conflict to flag, see below):** a backfilled or `RECENT` job that waits in the queue past the tracker window should be closed out without a Groq call (`EVALUATED` with `reject="age"`, no hydrate). `lg.priority` is newest-first, so under overload the oldest sink and would otherwise be hydrated and rejected one by one forever.

### Day-precision decision (blocks new adapters)

Workable is day-precision today and Workday-class sites expose only a date or relative text ("Posted 3 Days Ago", parsed by `parse_instant` as `DAY`). The milestone text says "time-precise". A date `D` bounds the age: `age <= now - start_of(D)`. Admitting day-precision jobs whose **upper bound** is within the window is verified evidence, not a guess (`D > (now - 72 h).date()`), and the label must say "date only, at most N h". Without this rule Workday-class adapters contribute **zero** backfill volume. Decide this in phase 2 so that phase 6 does not rework it. Default recommendation: allow it for the tracker (never for alerts: alerts keep the existing day-precision rule that needs gap <= 12 h).

### Contract changes to flag first (AGENTS rule 1)

| Item | Conflict | Doc to update |
|------|----------|---------------|
| Backfill on first baseline pass | D-05, SPEC "Baselining" ("no backfill") | new D-48, SPEC "Baselining" and "Freshness vocabulary" (RECENT rule) |
| `Max_Job_Age_Days` 14 -> 72 h effective tracker window | SPEC "Freshness vocabulary" (`recent`, `stale` rules) | D-48, SPEC |
| Closing out out-of-window `recent` evaluations without scoring | SPEC "State model" ("a pending retry is never dropped because its job aged past the window") | Restrict to non-alertable classes; `verified_fresh` retries unchanged. D-48 |
| Day-precision admission to the tracker | SPEC "Freshness vocabulary" | D-48 |

## Feature 3: scaling monitored boards past 700

### Where the cost really is (measured numbers from STATUS/D-43; extrapolations labelled)

| Cost | Today | Scales with | Binding when |
|------|-------|-------------|--------------|
| Board polls | 3-6.5 min at 700 = 0.26-0.56 s per board (wall, 8 workers) | boards, linear | ~1,400 boards uses 6-13 min; keep below 50% of the 25 min timeout (12.5 min) |
| Evaluation (Groq) | run median 113 s at 500 boards; pilot ~37 evaluations/day | evaluations per run, TPM/TPD | first (see below) |
| Events load | `Load_S` 7.5 s at 118k rows, 8.0 s at 121k (includes the 22k-row Boards tab); slope not measured | characters in Events (60M chars at 122k rows), read **twice** per run | payload size, memory, API timeouts well before CPU |
| Boards writes | every polled board is rewritten each run (`apply_poll_result` stamps `Last_Attempt_At`), ~32 cells x N rows in chunks of 500 | boards | harmless: 3 requests/run at 1,400 boards. Do not "fix" it with dirty-on-change; the timestamp makes it unavoidable |
| Sheet cells | 854k cells at 122k rows (8.5% of 10M) | rows x 7 | ~1.4M rows |

**Groq is the first wall (MEDIUM confidence).** `Config.groq_tpm` defaults to 8,000 and `TokenBudget` paces at 90% of it; each call carries up to 7,000 resume chars + 7,000 JD chars + system prompt + up to 1,000 output tokens (about 4-5k tokens). At that pacing one evaluation costs ~35-40 s of wall time, so `max_jobs=30` can approach 20 minutes. The free-tier table for `openai/gpt-oss-120b` is reported as 30 RPM, 1,000 RPD, 8,000 TPM and 200,000 TPD (sources below; confirm in the Groq console). At ~5k tokens per call that is about 40 evaluations a day per model, versus roughly 100-150 a day implied by 20-30 kept jobs (pilot kept rate 47/260). Two models (primary plus fallback) roughly double that. If the account is on the free tier, evaluation volume, not board count, caps the target. Required before scaling:

- `Deps.eval_deadline_s`: stop the evaluate loop when elapsed run time passes a budget (for example 15 min); the rest stay `PENDING` and are retried (the loop already flushes every 10 jobs, so progress is durable).
- `eval_budget.py`: persistent daily token ledger (copy of `search.SearchBudget`: month -> day), fed by `usage.total_tokens` that `GroqClient` already reads. When the day is spent, evaluation is skipped like search discovery is when credits run out; `Eval_Transient` stays a signal, not a permanent `degraded` outcome (today any transient scoring failure marks the run `degraded`).
- Order evaluation by value: `lg.priority` already puts `verified_fresh` first; add the board's expected-useful-postings score as a tie-breaker (needs feature 5 evidence).
- Cut calls before the LLM: the title gate, `hard_gate_coded` (location, experience, language) already run before Groq; the 72 h window removes 3-14 day old `RECENT` jobs from the queue entirely.

### Scaling mechanics to add

1. **Poll deadline and fair ordering.** `poll_boards` currently maps a fixed list; under a deadline the same tail boards would starve. Sort by `last_attempt_at` ascending, add `deadline` to `poll_boards` (remaining boards come back `skipped`, keep their state, counted in a new `Runs.Boards_Skipped_Deadline`). Gaps are already handled correctly by `board_gap` classification.
2. **Raise `Max_Active_Boards` in measured steps** through Settings (700 -> 1,000 -> 1,400), each step gated on `Runs` metrics for several days: p95 `Duration_S` < 12.5 min, `Load_S`, `Sheets_Reads`/min (quota ~60), `Events_Rows`, `Eval_Transient`. No code change per step.
3. **Share loaded state with the dashboard.** `hunter.main` calls `dashboard.refresh(store, settings)` after the run, and `dashboard.build` calls `load_events`, `load_boards`, `load_runs` again. Add an in-process cache to `SheetState.load_events` that `append_events` extends (same for boards via `save_boards`). Halves Sheets reads and memory churn, no behaviour change, testable with the existing fake worksheet.
4. **Compact `JobState`.** `replay` keeps `seen_detail` (title, url, location, JSON) for every one of 150k keys. Keep it only for `PENDING` or evaluated jobs; baseline/filtered/stale keys need `seen`, `freshness`, `disposition`. Cuts memory several-fold before any storage change.
5. **Add the missing measurements** to `RUN_COLUMNS` (append at the end only): `Events_Bytes` (characters read), `Load_Events_S`, `Load_Boards_S`, `Boards_Skipped_Deadline`, `Eval_Tokens`. EVID-02 and REL-05 need a second and third point on the `Load_S` curve (150k, 200k rows) before any threshold is trusted.
6. **Optional tiering (decision for requirements, not assumed):** a tracker target of "everything posted in 72 h" does not need hourly polling of every board; one poll per day finds every dated posting inside the window and `classify` already labels late finds correctly (time-precise jobs use source time, undated ones become `uncertain`). A cadence tier would roughly cut poll cost for breadth boards by 24x while the hourly tier keeps the 12 h alert guarantee. **Cost:** `pools.observed_days`/`MAX_COVERED_GAP` treat gaps over 6 h as outages, so evidence for a daily-polled board would always read "unknown" and the pool score would need a cadence parameter. Take this path only if measured hourly cost, not the evaluation limit, blocks the board count the target needs. Back-of-envelope with pilot ratios (47 kept / 500 boards / 7 days = 0.013 kept per board-day, **before** the 2026-10-23 Settings broadening): 25 kept/day needs 1,000-1,900 boards covered; about 1,350 relevant boards are known today (about 700 waiting).

## Feature 4: new ATS adapters in the adapter/registry/identity model

### What an adapter touches today (grep-verified; there is no registry, only parallel `if/elif`)

| Concern | Where | New-ATS work |
|---------|-------|--------------|
| Name and list URL | `boards.ATS_LIST`, `LIST_APIS`, `fetch_board` (if/elif) | `LIST_APIS` is GET-only with one `{board}` placeholder |
| Job identity | `JobIdentity.key/url`, `parse_job_url`, `parse_board_url`, `_prefix`, `CASE_SENSITIVE_ATS` | decide id and case rules |
| Posting hydration | `hunter._hydrate` if/elif, `_hydrate_<ats>`, `_hydrate_page` (JSON-LD fallback) | detail call or JSON-LD |
| Inventory | `inventory.SUPPORTED_ATS = set(ATS_LIST)`, `parse_ats_scrapers_csv`, `IDENT_RE` (identifier sanity), `policy_blocks` | import rows, allow `/` in ids |
| Search | `hunter.ATS_SITES`, `discovery.make_slots` | add host |
| Completeness | `boards.Listing(complete=...)`, `looks_capped` | per-provider rule |

**Recommendation: introduce an adapter registry before the first new adapter, not after.** One `AdapterSpec` per ATS (`parse_job_url`, `parse_board_url`, `list(board) -> Listing`, `hydrate(ref) -> Posting`, `identity rules`, `completeness rule`, `politeness`) in `boards.py`, with the five existing providers moved behind it under golden tests that prove byte-identical keys and parse results (the `tests/test_inventory.py` and `tests/test_core.py` fixtures). Without it every new ATS edits five if/elif chains in three modules, and that is where identity bugs (rule 3) would come from. D-02 applies: new code goes in a new module (`adapters/` or `ats_*.py`), not into the 1,981-line `hunter.py`.

### Fit of the identity model (identity = ATS + board + posting ID)

- `BoardId(ats, board, region)` already carries a "region/API host" slot (SPEC: "provider + region/API host + board identifier"). For Workday-style sites the cluster host (`wd1`, `wd5`) maps to `region`; the board identifier must carry **tenant and site** (e.g. `tenant/site`), which needs `IDENT_RE` and `_clean_ident` to allow a separator. Job ID must be the requisition ID, not the URL path (path embeds a title slug that can change). Rule 3 is satisfied only if the key never uses a URL.
- Casing: pick explicitly (`CASE_SENSITIVE_ATS`); verify live like Lever/Workable were.
- `JobIdentity.url` must build a canonical apply URL for the ATS (used when the payload has none).

### What this milestone's adapters break in the current model (flag for phase research)

1. **GET-only, one request per board.** Workday's public jobs endpoint is reported as an undocumented POST (`limit`, `offset`, `searchText`, `appliedFacets`) with 20 results per page, and the total only on the first page. A large tenant is dozens to hundreds of requests per poll. Hourly polling of many such boards does not fit the 25 min budget. Needs (a) `_post_json`, (b) a `since`/early-stop hint so paging stops at a page of out-of-window jobs **if** the order is newest-first (unverified), (c) `Listing(complete=False)` for early-stopped listings. `complete=False` already means "observe new IDs, never change relevance/activity evidence", which is the right semantic.
2. **Day-precision only** (see decision above). Hydration (`CXS` detail or JSON-LD `datePosted`) is also date-only.
3. **Baseline cost.** Big-employer boards hold hundreds to thousands of IDs. With the current one-row-per-ID ledger a Workday board costs 5-20x an average board. **Storage migration must land before bulk Workday admission.**
4. **Provider policy.** `inventory.policy_blocks`/D-13/D-38 treat robots.txt and ToS per provider; each new provider needs an explicit decision recorded in DECISIONS.md (GOV-01). Unknown: Workday ToS and `robots.txt`.
5. **Inventory coverage.** The ats-scrapers inventory lists Workday 3,530 and iCIMS 2,498 rows (STATUS, 2026-10-14), the open-ats-feed lists Breezy 3,536, Teamtailor 2,840, Recruitee 2,830. Their row format for Workday (tenant, site, cluster) is not verified; `parse_ats_scrapers_csv` needs a fixture-driven parser. iCIMS has no verified public listing API (portal HTML), so it is an HTML/JSON-LD adapter and the most fragile; Breezy/Recruitee/Teamtailor are API-like but are small-company boards, not the "big employer" goal. Which to build is for phase research (STACK); the architecture supports one adapter at a time behind the registry.

## Feature 5: board-cycling score from recent postings and My_Feedback

### Key insight: recency evidence is available from the listing, not from the ledger

Today board evidence (`Relevant_Jobs`, `Eligible_Jobs`, `New_Relevant_7d/30d`) needs a monitoring stint (`min_complete_polls = Exploration_Days x 12`, 7-day observed-time rules) and the activity part is derived from first-observation rows in the ledger. For dated sources the listing itself says when each posting was published. `pools.relevance_counts(jobs, title_gate)` and `inventory.validate_board` already walk the same listing; extend both with `recent_relevant_72h` (title-gate passing, US-eligible, time-precise or date-bound within the window) and a timestamp. Consequences:

- A **waiting** board gets a recency measure at every validation re-check (D-47 budget 5,000/run, a full pass in about two days) with no monitoring slot; `admission_order` can rank by it directly (today: never-tried first, then open eligible jobs).
- A **trial** gets a rate from its first poll; trials can be shortened in Settings (`Exploration_Days`) without new code. Thin-evidence protection (`evidence_problem`) stays; it measures polls, and that is the right guard.
- The score aligns with the goal: **expected useful postings per day** = `(recent_relevant_72h / 3)` x shrunk precision, where precision is a Beta-smoothed share of the board's evaluated jobs that were kept or labelled `Would apply`, with a global prior so cold-start boards are not penalised. Cap terms like `OPEN_CAP`/`RATE_CAP` so aggregators cannot dominate; keep the exploration pool so unlabelled boards still get tried.

### Feedback integration

- New pure module `feedback.py`: tracker rows -> per-board tallies. Row -> board via the existing `boards.parse_job_url(Apply_URL).board_id.key` (the same function `tracked_keys` uses). Unparseable URLs are skipped, never guessed. A missing `Apply_URL` header yields an empty tally (never fail the run, D-46).
- `hunter.SheetStore.tracker_rows()` already reads the whole tracker (a few thousand rows, cheap). Call it at most once a day or at rebalance time from `run_cycle` through a new `Deps.board_feedback` callable (injected, so tests stay offline). The program stays read-only toward `My_Feedback`.
- Store tallies as appended `Boards` columns (`Fb_Pos`, `Fb_Neg`) next to `Recent_Relevant_72h` and `Recent_At`. `board_from_row` is positional, so **append at the end of `BOARD_COLUMNS` only**; `SheetState._widen_header` already adds header names and grid columns to an older tab.
- Labels are sparse (a board has 1-3 rows). Use Bayesian shrinkage and a bounded effect, and treat feedback as board-level evidence only. Using it to change the job scorer or `Min_Alert_Score` is EVID-05 and stays gated (AGENTS rule 7); this milestone lifts the gate for board-cycling scores only.

### Where the score is consumed (all in `pools.py` and `boards.py`)

`pools.score` -> `plan_rebalance.sc`, `early_releases` (via the plan), `weekly_rate`/`evidence_problem`, `boards.admission_order`/`activate_waiting`, `format_plan`, `plan_json`, plus `pilot.py`/`reporting` coverage lines. Introduce `Board_Score_Model` (`v1` default | `v2`) in Settings and `PoolPolicy.score_model`, with a **shadow mode** that computes v2 decisions beside v1 into `rebalance_report` (same machinery as `Rebalance_Mode=report`). v2 gets its own floor constant, not the v1 `GRADUATION_FLOOR` (2.0 is on the v1 scale). Cycling speed is already tunable (`Exploration_Days`, `Max_New_Boards_Per_Run`, D-47 early release, `cooldown`); the code change is evidence plus score, not new machinery.

Interaction to respect: every faster cycle is a baseline pass, which (with backfill) now triggers evaluations and adds storage rows. So cycling speed is bounded by evaluation throughput and by the storage design, in that order.

## Feature 6: wider Tavily search

- Today: 6 sites x 36 roles = 216 slots, 10 credits a run, 12 h interval = about 20 credits/day, so a full rotation takes about 11 days (`STATUS`: 42 slots took 2.1 days when it was 6 x 7). A slot's `start_date` window is 3 days, so each slot sees roughly 3 of every 11 days of postings (about 27%). Free plan: 1,000 credits/month renewing on the 1st (Tavily docs, MEDIUM-HIGH); scheduled use is capped at 800 (`Search_Reserve_Credits` 200). Paid pay-as-you-go is $0.008/credit (documented).
- Full 72 h coverage of 216 slots needs every slot every <= 3 days = 72 credits/day (2,160/month). Options, in order: (1) **compress slots** (several roles per query, measured against recall), (2) **yield weighting**: persist per-slot stats (`Discovery` key `slot_stats`: unseen jobs, new boards, passes the title gate) and let `discovery.plan_slots` run high-yield slots more often, (3) use the whole 800 allowance (`Discovery_Credit_Budget`, `Discovery_Every_Hours` are existing settings), (4) paid credits only if the user decides.
- Tie `search.request_body`'s `start_date` to `Tracker_Window_Hours` (3 days is already that value; remove the literal).
- `MAX_SEARCH_HYDRATIONS = 20` (pipeline constant) and `MAX_PENDING_JOBS = 60` (discovery) become settings; hydration is an ATS request per job and competes for the same run time as evaluation.
- Search-found jobs have no board gap (`board_gap=None`), so they are `verified_fresh` only with a time-precise source date and otherwise `RECENT`/`uncertain`; the 72 h gate applies identically (`source=search` is kept as provenance). Board names found by search keep flowing through `inv.admit_boards`, so search also feeds the board-cycling pool.
- Adding `myworkdayjobs.com` to `ATS_SITES` depends on whether Tavily `include_domains` matches tenant subdomains (unverified).

## Storage: D-43 vs alternatives, and replay cost vs Events rows

### How replay works and what it costs (verified in `pipeline.run_cycle`, `state.py`, `ledger.py`)

Every run does `load_events()` (one `get_all_values` of the whole tab, returns every cell as a string), builds an `Event` per row (`json.loads` of the detail), and folds them into a `JobState` per key. The dashboard does the same again after the run. Cost model:

| Quantity | Value | Source |
|----------|-------|--------|
| Rows now | ~150k (122k at D-43 on 2026-10-17) | PROJECT, D-43 |
| Characters | 59.6M at 122k rows (mean baseline row 486 chars) | D-43 |
| Reads of Events per run | 2 (run + dashboard) | `pipeline.py`, `dashboard.build` |
| Load time | 7.5 s at <118k, 8.0 s at 121k (incl. Boards) | CONCERNS, D-43 |
| Growth, legacy design | 3,750 rows/day at 500 boards, 5,250/day at 700 (steady) + ~147 rows per admitted board once | D-43 |
| Cell limit | 10M cells = ~1.4M rows at 7 cells/row | D-43 |

Linear extrapolation from the one measured point (0.13 s per MB of Events, labelled assumption): 300 MB (~600k rows) is about 40 s per read, 80 s per run, plus memory of several hundred MB per replay. CPU is not the limit; **response size, memory and unknown Sheets API behaviour on 100+ MB responses are the risk**, and the 1.4M-row cell cap is the hard wall.

| Boards | Legacy rows/day | Days from 150k to 1.4M rows | With Identity tab: Events growth | Identity read payload growth |
|--------|-----------------|------------------------------|----------------------------------|------------------------------|
| 700 | ~5,250 | ~240 | ~1.3k cells/day (D-43) | ~100-150k chars/day (estimate) |
| 1,400 | ~10,500 | ~120 | ~2.6k cells/day | ~200-300k chars/day |
| 2,100 | ~15,750 | ~80 | ~4k cells/day | ~300-450k chars/day |

Admission waves add to the legacy column: +200 boards is +29k rows (D-43), the D-47 refills already added 5.3k and 6.9k rows in single runs, and a Workday-class board is 5-20x an average board. D-43's own revisit point (200k rows) arrives within about two weeks at current growth.

### Options

| Option | What | Replay effect | Verdict |
|--------|------|---------------|---------|
| 0. Do nothing | keep one row per ID | grows linearly with boards x time; wall at ~1.4M rows | Reject: board scale-up and Workday would hit it within months |
| 1. D-43 (Identity tab, daily counters, archive) | IDs compacted to 40k-char cells per board, operational rows kept | read payload ~20x smaller today (523 rows vs 113k) | **Recommended, with amendments** |
| 2. Ledger-native batch events (`seen_ids` rows per run) | keep one append-only tab, batch identity into per-run rows | keeps append-only and crash safety; payload grows forever (3.6M IDs/year at 10k/day) | Fallback if a mutable Identity tab proves risky; needs a periodic compaction event anyway |
| 3. Date-derived identity | do not store identity for time-precise jobs outside the window; reclassify each poll from the source date | smallest state; independent of board count | **Defer.** Breaks D-04(e): a republished old job (date reset by Ashby/SmartRecruiters) would look new and could alert. Safe only for non-relevant (title-gated) jobs; and it changes the "jobs first observed" reporting cohort |
| 4. External database (D1, Supabase, Turso) or Drive blobs | move state off Sheets | removes the cell cap and bulk reads | Reject now: new secrets and failure domain, loses the user's visibility; revisit only if Identity exceeds ~2M IDs or `Load_S` > 2 min |
| 5. Repo or Actions-cache state | commit or cache state | cache is evictable (not durable); workflows are `contents: read` (D-37); user must not touch Git | Reject |
| Hash-truncated IDs (inside Option 1) | store 8-byte hashes | ~2-3x smaller than raw IDs | Optional later; opaque for audits |

### Recommended design: D-43 with amendments

D-43 as written holds up: it preserves identity (replay seeds `seen` from the Identity set), keeps pending evaluations and alert retries in operational rows that are never archived, keeps board evidence reading operational `seen` rows within 30 days, and migrates in parallel before deleting. Amendments:

1. **Route by disposition at write time, not by row type afterwards.** `BASELINED`, `FILTERED`, `STALED` -> Identity add (+ Tally). `PENDING` -> `Events` row. With backfill, baseline-pass jobs inside 72 h are now `PENDING` and stay operational, so the routing rule must be implemented after phase 2, not before.
2. **Per-run `Tally` rows, not daily upserts.** D-43's "Daily counters" implies read-modify-write of a day row. Append one `Tally` row per run (run id, date, one JSON cell of counts by ATS, source, class, disposition, gate). Append-only, idempotent by run id, written in the same step as the events; reports sum by day. About 24 rows/day, negligible. `reporting.job_facts`'s per-day cohort partition (baseline, each rejection stage, kept, waiting) must read Tally for days whose rows were compacted.
3. **Swap, do not delete in place.** Build a new Events tab (operational rows only) and rename the old one `Events_Legacy` (hidden, outside the replay path, kept until parity has held for days). This replaces "delete baseline and identity-only rows in batches" and removes the flood-on-rollback risk (rollback is renaming tabs back).
4. **Identity writes follow rule 1.** `Identity` -> `Events`+`Tally` -> `Boards` -> `Discovery`. Identity holds only non-`PENDING` IDs, so a crash after the Identity write loses no job; a crash before it re-observes IDs as new, and the existing `FLOOD_MIN_JOBS` guard plus date classification contain that.
5. **A `Ledger` facade in `ledger.py`.** `replay(events, identity=None) -> Replayed` with `.states` (operational) and `.is_seen(key)`. Replace the four `states.get(k) and states[k].seen` sites in `pipeline.py` (discovery `is_unseen_job`, `unseen`, per-job loop, search hydration) and the one in `hunter.py` (`run_rebalance_report`) with `is_seen`. `CsvState` gets matching `identity.csv` and `tally.csv`. Parity test: the same synthetic ledger through both readers yields identical `seen` sets, `needs_evaluation`/`needs_alert` sets and `reporting` totals (add `--storage-parity`, read-only, beside `--storage-report`).
6. **Retention is a year-2 concern.** The Identity set grows ~100-150k characters/day at 700 boards, so it reaches today's 60 MB payload in about 1.5 years (about 9 months at 1,400 boards). Add retention (drop IDs absent from the listing for > 60 days, keep tombstones with a date) only when the payload passes a threshold; it is also what keeps an old republished ID from re-entering as new.
7. **Archive sooner than D-43 assumed.** D-43 measured operational rows at 0.4% (164 rows/day) at pilot volume. Raising kept jobs from 7 to 25 a day and adding backfill takes that to roughly 500-600 rows/day with ~1 KB `evaluated` payloads (~18 MB a month, estimate), so operational rows alone match today's payload in about 3-4 months. Archive terminal rows older than 60-90 days into `Events_Archive_YYYY_MM` (reports use <= 30 days), and shrink non-visible `EVALUATED` payloads (score < 50 needs `reject`, `status`, `score`, not verdict and gaps).

### Quick wins that do not need the migration (do in phase 1)

Shared load for the dashboard (halves reads), compact `JobState` (memory), `Events_Bytes` and split load timers in `Runs`, and a stored-vs-parsed row check in `storage_report`.

## Data Flow Changes

### Hourly run, v2.0

1. Startup, load (events cached), settings include `Tracker_Window_Hours`, score model, budgets.
2. Discovery (yield-weighted slots, window from setting) -> admission (unchanged single path).
3. Poll, oldest-first, deadline-aware. Per result: `classify` with the tracker window; `observe_new` -> `Event` (operational) or Identity add + Tally; `refresh_relevance` also fills `Recent_Relevant_72h`.
4. Evidence: `refresh_activity` from operational `seen` rows; `feedback` tallies (daily) -> Boards columns; pools score (v1 live, v2 shadow, then v2 live).
5. Durable point: Identity -> Events + Tally -> Boards -> Discovery.
6. Evaluate: priority = class, then (board score, newest); loop honours the deadline and the daily token ledger; expired `RECENT` closed without Groq; `EVALUATED` payload carries `age_min_found`.
7. Alert: unchanged.
8. Dashboard: reuses the already loaded Events and Boards.

### Validation and inventory (separate workflow)

`validate_board` also returns `recent` (72 h relevant count); `apply_validation` writes `Recent_Relevant_72h`/`Recent_At` for `validated` boards. Still never scores, alerts or promotes; the importer guard for poller-owned rows is unchanged.

### Key invariants preserved

Seen, evaluated, alerted stay separate and retryable; alerts only for `verified_fresh` inside `Fresh_Window_Hours`; identity is `ats|board|id`; publication time is never update, crawl or search time; the tracker stays append-only and written by header name; reporting and dashboard stay read-only toward operational state; secrets and personal data untouched.

## Patterns to Follow

### Pattern 1: Reuse the existing class, mark provenance in `detail`

**What:** backfill is `RECENT` plus `detail.pass = "baseline"` and `detail.backfill = true`, not a new class.
**Why:** `ALERTABLE`, `counts_as_new_posting`, reporting partitions and `priority` already do the right thing for `RECENT`; a new class touches every one of them.

### Pattern 2: One windows value object

```python
@dataclass(frozen=True)
class Windows:
    fresh: timedelta   # alert window, Fresh_Window_Hours (12)
    track: timedelta   # tracker/backfill window, Tracker_Window_Hours (72)
# passed through Observation and Deps; classify, the evaluator gate, search start_date and expiry read it
```

**Why:** the 72 h boundary would otherwise live in four places (`classify`, evaluator, `search.request_body`, queue expiry) and drift.

### Pattern 3: Shadow mode before a score goes live

Compute v2 beside v1 and record both in `rebalance_report`; switch with `Board_Score_Model`. This is the existing `Rebalance_Mode` report/on idiom, so measurement precedes tuning.

### Pattern 4: Append-only schema growth

New `Boards` and `Runs` columns are added only at the end (`board_from_row`/`RunRecord.from_row` are positional); `SheetState._widen_header` and `add_cols` do the rest. New tracker columns are found and appended by header name.

### Pattern 5: Budget ledgers in the `Discovery` tab

`search_budget` already shows the shape. `eval_budget` (daily tokens) and `slot_stats` follow it: JSON value, loaded each run, saved after the durable point, never required for correctness.

## Anti-Patterns to Avoid

### Anti-Pattern 1: Counting a backfilled job as new-posting activity
**What:** letting `refresh_activity` count `recent` or baseline-pass jobs as the board's rate.
**Why bad:** presents a discovery as a publication (rule 2) and inflates board scores.
**Instead:** keep `counts_as_new_posting` as is; use listing-derived `Recent_Relevant_72h` as a separate, labelled measure.

### Anti-Pattern 2: Treating day-precision as time-precise
**What:** admitting date-only jobs as if their age were known.
**Instead:** admit by upper bound only, label "date only, at most N h", never alert on it.

### Anti-Pattern 3: Rewriting or deleting ledger rows in place during migration
**What:** `deleteDimension` on 140k rows with no way back.
**Instead:** build the new tab, parallel-run, rename-swap, keep `Events_Legacy`.

### Anti-Pattern 4: Raising the board cap before the evaluation and poll deadlines exist
**What:** more boards, backfill bursts and a 25 min timeout with unbounded evaluation.
**Instead:** deadlines and token ledger first, then step the cap.

### Anti-Pattern 5: Tuning on a moving baseline
**What:** changing the score while Settings broadening (2026-10-23), D-47 and the first weekly rebalance (about 2026-10-29) still mix regimes in the data (PILOT_LOG).
**Instead:** record each change in PILOT_LOG, collect evidence in shadow columns first.

### Anti-Pattern 6: Dropping user data through a positional tracker write
**What:** adding `Age_Hours` by position.
**Instead:** by header name, optional, ignored if absent (D-44, D-46).

## Build Order (dependency-aware)

| # | Phase | Contents | Must come after | Why this position |
|---|-------|----------|-----------------|-------------------|
| 1 | **Measurement and safety rails** (no behaviour change) | tracker rows/day, age-at-found (`Date_Found` minus `Date_Posted` already exists in the tracker), feedback mix in `reporting`/`dashboard`/`pilot`; new `Runs` columns; shared dashboard load; compact `JobState`; read EVID-01 (about 2026-10-29), EVID-02..05; confirm Groq tier and tokens per call | - | A target cannot be proven without a baseline; later phases need the load, token and age numbers to set thresholds |
| 2 | **Evaluation governors** | `eval_deadline_s`, `eval_budget.py`, poll deadline and oldest-first order, `Boards_Skipped_Deadline` | 1 | Backfill and cycling both create evaluation bursts; without a deadline a burst can hit the 25 min timeout and the watchdog |
| 3 | **Windows and recent backfill** | `Tracker_Window_Hours`, `classify`, `observe_new` marker, evaluator hours gate, `age_min_found`, tracker age, queue expiry, day-precision rule, D-48 + SPEC edits | 1, 2 | Core value of the milestone; independent of storage; defines which dispositions are operational, which the storage routing needs |
| 4 | **Storage migration (STOR-01)** | `identity.py`, `Ledger` facade, Identity + Tally tabs (Sheet and CSV), dual write, parity command, parity run of several days, rename-swap, then archive | 3 | Routing depends on phase 3 semantics; must precede board growth, faster cycling and big-board adapters because they multiply baseline rows |
| 5 | **Cycling evidence in shadow, then score** | `Recent_Relevant_72h` at poll and validation, `feedback.py`, Boards columns, v2 score in shadow beside v1, then `Board_Score_Model=v2`, then shorter `Exploration_Days` | 1 (EVID-01, EVID-05), 3 | Evidence needs the recency semantics from 3; one week of shadow data is the "measure before tuning" step; fast cycling needs 4 |
| 6 | **Scale boards past 700** | step `Max_Active_Boards` 700 -> 1,000 -> 1,400 in Settings, each gated on `Runs` metrics; decide on cadence tiers only if hourly cost blocks | 2, 4, 5 | Storage and governors must exist; the score decides which boards deserve slots |
| 7 | **Adapter registry, then first new ATS** | registry with golden tests for the five existing providers; then one adapter (Workday-class or the research pick) with POST, composite id, early-stop, day precision, provider policy (GOV-01), inventory parser | 3 (day precision), 4 (big boards) | Rule of two: refactor once before adding; storage before large boards |
| 8 | **Wider Tavily search** | slot compression and yield stats, window from setting, hydration cap setting, credit budget decision | 2 (eval capacity), 3 | Search adds evaluations; independent otherwise, so it can run in parallel with 6-7 |

Parallelism: phase 8 and the adapter-registry refactor (7a) have no dependency on 4-6 and can overlap them; phases 3 and 4 touch `ledger.observe_new` and the observation block of `run_cycle` and should not overlap.

**Research flags for phases:**
- Phase 4 (storage): needs deeper design and a spike: Sheets API behaviour on 100+ MB `get_all_values`, whether a `batchUpdate` on cells is atomic enough for chunk rewrites, rename-swap mechanics through gspread.
- Phase 7 (new ATS): needs its own research: Workday endpoint behaviour (ordering, id field, ToS and robots), inventory row format, which ATS gives the best volume per request.
- Phase 5: standard patterns (scoring, shadow mode); research is the choice of prior and shrinkage constants, to be taken from the phase 1 numbers.
- Phases 1-3, 6, 8: standard patterns in this codebase.

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 700 boards (now) | Add governors and measurement; Identity migration before the next refill wave; hourly polling stays |
| 1,400 boards | Poll 6-13 min, so deadline and fair ordering are mandatory; Identity tab; archive; Groq paid tier or heavy pre-LLM filtering; optional cadence tiers |
| 2,100+ boards | Cadence tiers (hourly for high-yield, daily for breadth); Boards tab split into hot and cold; retention on Identity; consider an external store only if `Load_S` > 2 min |

### Scaling priorities

1. **First bottleneck:** evaluation throughput (Groq TPM/TPD and the unbounded evaluate loop). Fix: deadline, daily token ledger, value ordering, 72 h window pruning the queue.
2. **Second bottleneck:** Events payload per read (twice per run) and growth from baselines. Fix: shared load, compact state, Identity + Tally, archive.
3. **Third:** poll wall time past ~1,400 boards. Fix: deadline and fair ordering, then cadence tiers.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Google Sheets | `SheetState` single `get_all_values` per tab, appended rows, header-name tracker writes | New Identity/Tally tabs are hidden like the others; the tracker stays user-owned; ~60 reads/min quota |
| Groq | `GroqClient` with TPM pacing and 429 fallback | Add a daily token ledger; free-tier limits reported as 8k TPM, 200k TPD per model (verify in console) |
| Tavily | `search.py`, persistent credit ledger | 1,000 credits/month free, renewal on the 1st; slot yield stats are local state |
| ATS public APIs | `boards.fetch_board`, `hunter._hydrate_*` | Workday-style POST and pagination break the GET-only helper (`_get_json`) |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `pipeline` <-> `ledger` | `replay` returns a facade with `is_seen`; `observe_new` returns an `Event`, routing decides row or identity | Keep `ledger` pure; persistence in `state` |
| `pipeline` <-> `hunter` | `Deps` callables (`evaluate`, `board_feedback`, `append_tracker`) | Add fields, never import network clients into `pipeline` |
| `pools` <-> `inventory` | shared `relevance_counts`; add `recent_relevant` in one place | Poller owns pool transitions (D-28) |
| `reporting` <-> everything | pure read-side | Needs Tally for compacted days |
| `watchdog.py` | independent | Must not import any new module (D-42) |

## Tests (offline, per AGENTS rule 8)

New: `tests/test_backfill.py` (baseline pass at 71/73 h, day-precision bound, clock skew, alert unchanged), `tests/test_windows.py` (one windows value through all gates), `tests/test_identity_parity.py` (legacy vs compact replay), `tests/test_feedback.py` (URL to board, missing header, shrinkage), `tests/test_eval_budget.py`, `tests/test_adapters_golden.py` (five providers byte-identical keys after the registry). Mutation checks as in D-45/D-47 (remove the window, ignore the mode, drop the routing).

## Sources

- Code and docs read directly (HIGH): `freshness.py`, `ledger.py`, `pipeline.py`, `state.py`, `boards.py`, `pools.py`, `inventory.py`, `hunter.py` (Settings, evaluator, Groq client, tracker store), `dashboard.py`, `storage_report.py`; `SPEC.md`; `DECISIONS.md` D-03, D-05, D-24, D-43, D-45, D-47; `STATUS.md`; `PILOT_LOG.md`; `.planning/codebase/ARCHITECTURE.md`, `STRUCTURE.md`, `CONCERNS.md`; `.planning/REQUIREMENTS.md`.
- Groq free-tier limits (MEDIUM, secondary sources citing Groq): [Free LLM API Comparison 2026](https://blogs.novita.ai/free-llm-api-comparison-2026/), [benchlm.ai Groq free tier](https://benchlm.ai/free-tier/groq), [Groq pricing in 2026](https://eesel.ai/blog/groq-pricing)
- Tavily credits and pricing (MEDIUM-HIGH, official docs): [API credits](https://docs.tavily.com/documentation/api-credits.md), [FAQ](https://docs.tavily.com/faq), [pricing help](https://help.tavily.com/articles/8816424538-pricing)
- Workday public jobs endpoint (LOW, community write-ups, unofficial and undocumented): [Workday job boards have a JSON API too](https://dev.to/udaninn/workday-job-boards-have-a-json-api-too-its-just-better-hidden-23fl), [Workday's job API tells you there are 2000 jobs, then says 0 on page two](https://dev.to/glitchbound/workdays-job-api-tells-you-there-are-2000-jobs-then-says-0-on-page-two-2c8e), [Workday Jobs Scraper](https://apify.com/crawlerbros/workday-jobs-scraper)
- Breezy HR feed (LOW, conflicting sources, no date field confirmed): [Breezy HR Jobs API](https://apify.com/careersignal/breezy-jobs-api), [JobsPipe Breezy](https://jobspipe.dev/sources/breezy.md). Recruitee and Teamtailor: no official documentation found.

## Open Questions and Gaps

- Groq account tier and actual tokens per evaluation (read `usage.total_tokens` from `Runs`/logs in phase 1).
- Whether the Sheets API handles a 100+ MB `get_all_values` reliably (spike in phase 4).
- Workday: result ordering, requisition ID field, robots.txt/ToS, inventory row format (phase 7 research).
- Whether the user accepts day-precision admission to the tracker (decision for phase 3).
- Whether closing out out-of-window `recent` evaluations without scoring is acceptable under SPEC "State model" (flag in D-48).
- Whether Tavily `include_domains` matches `*.myworkdayjobs.com` tenant hosts.

---
*Architecture research for: auto_search_workflow v2.0 integration*
*Researched: 2026-10-25*
