---
phase: 261014-olj-board-slot-allocation
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - boards.py
  - state.py
  - ledger.py
  - freshness.py
  - eligibility.py
  - pools.py
  - pipeline.py
  - inventory.py
  - hunter.py
  - .github/workflows/job_hunter.yml
  - .github/workflows/inventory.yml
  - tests/test_pools.py
  - tests/test_core.py
  - tests/test_inventory.py
  - tests/test_hunter.py
  - SPEC.md
  - DECISIONS.md
  - STATUS.md
  - README.md
  - AGENTS.md
autonomous: true
requirements: [REQ-1, REQ-2, REQ-3, REQ-4, REQ-5, REQ-6, REQ-7, REQ-LOG, REQ-DRYRUN, REQ-TEST, REQ-DOCS]

estimate:
  tokens: 260000
  raw_tokens: 260000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "A complete, successful hourly poll refreshes a monitored board's relevant-job count, US-eligible count and relevance time from the listing it already fetched; a partial listing, a failed poll or a suspicious empty listing changes none of them"
    - "New-posting activity (New_Relevant_7d / New_Relevant_30d, Last_New_Relevant_At) counts only first observations by polls of relevant jobs outside baseline and re-entry passes; it is blank (unknown) until the current monitoring stint is 7 days old and a real 0 afterwards; open-job counts are stored separately"
    - "Titles like 'Marketing Coordinator', 'Marketing Internship', 'Jr. Content Creator' and 'Entry-Level Social Media' pass the title gate, while 'Senior Marketing Internship' and 'Marketing Lead - Entry Level' are still rejected"
    - "Overdue revalidations are processed oldest-first in a queue with its own budget, interleaved with never-validated candidates, so an 18,500-board candidate backlog cannot starve them"
    - "Max_Active_Boards is split into an established pool (default 400) and an exploration pool (default 100); every board admitted to monitoring enters exploration on a 7-day trial; boards never tried before are admitted first"
    - "The weekly rebalance compares ended trials with the weakest established boards using one documented score, replaces at most Max_Replacements_Per_Rebalance established boards per cycle, never touches a board on an active trial, and never demotes on one empty, partial or failed fetch (complete-poll evidence and two consecutive weak cycles are required)"
    - "Rebalance_Mode defaults to 'report': the scheduled weekly rebalance only records a report until the user sets 'on'; `python hunter.py --rebalance-report` prints the plan and writes nothing"
    - "A board that leaves monitoring keeps its events, provenance, baseline history and pending scoring/alert retries; when it re-enters, its baseline is re-established and unseen gap jobs are judged by source publication evidence (undated ones are baseline, never 'new')"
    - "Monitored SmartRecruiters boards are parked (deferred) every run while the provider is parked, with history kept; blocked providers are never promoted"
    - "Pool transitions are made only by the hourly poller; the validation workflow never overwrites a row whose current status is new, active or disabled"
  artifacts:
    - path: "pools.py"
      provides: "Activity index, relevance/activity refresh, PoolPolicy, sync (policy parking, pool hygiene, legacy labels), score, plan_rebalance, apply_plan, rebalance_due, coverage, report formatting, dry-run preview"
    - path: "tests/test_pools.py"
      provides: "Offline tests for evidence refresh, baseline exclusion, incomplete fetches, re-entry, pools, bounded rebalance, trial protection, state preservation"
    - path: "state.py"
      provides: "31 Boards columns (13 appended), new Runs columns, status-guarded save_boards for the importer"
    - path: "inventory.py"
      provides: "Two independently budgeted validation queues, queue statistics, eligible counts at validation"
  key_links:
    - from: "pipeline.py"
      to: "pools.py"
      via: "run_cycle calls sync_pools before activation, refresh_relevance/refresh_activity in and after the poll loop, plan_rebalance/apply_plan when due"
      pattern: "pools\\.(sync_pools|refresh_relevance|refresh_activity|plan_rebalance|apply_plan)"
    - from: "pipeline.py"
      to: "boards.activate_waiting"
      via: "pool-aware vacancy fill with now, trial_days and the provider-policy predicate"
      pattern: "activate_waiting\\(.*blocked="
    - from: "hunter.py"
      to: "pools.PoolPolicy"
      via: "Settings rows Exploration_Share_Percent, Exploration_Days, Rebalance_Every_Days, Max_Replacements_Per_Rebalance, Rebalance_Mode build Deps.pool_policy"
      pattern: "pool_policy="
    - from: "hunter.run_inventory"
      to: "state.save_boards"
      via: "skip_if_status=inventory.POLLER_OWNED (compare-and-set on current status)"
      pattern: "skip_if_status"
---

<objective>
Fix the board allocation problem: today the first 500 qualifying boards keep their monitoring slots indefinitely (`boards.activate_waiting` only fills vacancies; `relevant_jobs` of monitored boards is never refreshed; revalidations starve behind ~18,500 never-validated candidates). Replace this with an incremental, configurable, auditable policy: refreshed evidence from complete hourly polls, two independently budgeted validation queues, established/exploration pools inside `Max_Active_Boards`, a weekly bounded rebalance (report-only until enabled), state-preserving demotion and re-entry, consistent SmartRecruiters parking, run logging, and a dry-run report.

Purpose: coverage = the boards we poll (SPEC "Honest limits"). Better boards must be able to enter, and boards must leave only on solid evidence, without losing freshness evidence or delivery state.

Output: new `pools.py` and `tests/test_pools.py`; changes to `boards.py`, `state.py`, `ledger.py`, `freshness.py`, `eligibility.py`, `pipeline.py`, `inventory.py`, `hunter.py`, both workflows; SPEC, DECISIONS, STATUS, README and AGENTS layout updated in the same change. No Serper redesign, no change to the Groq job scorer, no LLM calls for board ranking.
</objective>

<execution_context>
@~/.claude/gsd-core/workflows/execute-plan.md
@~/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/quick/261014-olj-board-slot-allocation/TASK.md
@AGENTS.md
@SPEC.md
@DECISIONS.md
@STATUS.md
@boards.py
@pipeline.py
@inventory.py
@state.py

Binding repo rules (AGENTS.md): read SPEC, DECISIONS, STATUS first; update affected docs in the same change as each behavior change; freshness is the product (never treat update/crawl/observation time as publication); identity = ATS + board + posting ID; keep seen/evaluated/alerted separate and retryable; say what is mocked vs live; never read, print or commit `.env`, `Resume.pdf`, `resume.txt` or service-account JSON; tests stay offline. Test command (used by the orchestrator, 201 tests passing at plan time): `cd <repo> && .venv/bin/python -m unittest discover -s tests`.

<interfaces>
Verified at plan time (line numbers approximate):
- boards.py: `BoardRecord` dataclass fields in order: ats, board, discovered_at, source, status, baselined_at, last_attempt_at, last_success_at, consecutive_failures, last_job_count, last_error, region, name, validation, last_validated_at, relevant_jobs, provenance. Statuses: candidate, validated, new, active, invalid, deferred, disabled; `MONITORED = {new, active}`. Validation outcomes `V_VALID, V_EMPTY, V_INVALID, V_TRANSIENT, V_DEFERRED`. `STAMP = "%Y-%m-%dT%H:%M:%SZ"`. `activate_waiting(registry, *, max_monitored, per_run)` (line 423). `PollResult(board, jobs, ok, gone, error)`. `poll_boards(boards, *, fetch, workers)`. `apply_poll_result(res, *, now) -> (rec_copy, gap)` sets last_success_at, last_job_count, validation, last_validated_at on success; disables after `DISABLE_AFTER_FAILURES = 72`. `fetch_board` pages SmartRecruiters and stops at offset > 5000 (a truncated listing).
- state.py: `BOARD_COLUMNS` (18 names, Provenance last, index 17); `board_to_row` / `board_from_row` are positional; `SheetState._widen_header(tab, columns)` widens a prefix-matching header; `SheetState.save_boards(records)` upserts by `_row_of`, re-reads the sheet only for unknown keys; `CsvState.save_boards` rewrites the file atomically with the full header. `RUN_COLUMNS` (27 names) and `RunRecord` with positional `from_row` (indices 0..26).
- ledger.py: `Observation(now, board_gap, board_baselined, baseline_pass, source, fresh_window, max_age_days)` frozen; `observe_new(job, obs, title_gate)` builds detail keys source, board, title, url, location, published_field, precision, evidence, gate, age_min, gap_min, updated; dispositions `PENDING, BASELINED, FILTERED, STALED`; `replay(events) -> dict[key, JobState]` with seen_time, seen_detail, disposition, freshness.
- freshness.py: `classify(published, precision, *, now, board_gap, board_baselined, baseline_pass=False, fresh_window, max_age_days)`; classes VERIFIED_FRESH, OBSERVED_NEW, RECENT, UNCERTAIN, STALE, BASELINE.
- eligibility.py: `_term_re(terms)` builds `(?<![A-Za-z0-9])(?:t1|t2)s?(?![A-Za-z0-9])`; `title_gate(title, roles, levels, excluded, *, require_level=True)`; `hard_gate(title, location, text, resume)` starts with the non-US location rule using `_NON_US_RE` and `_US_CASE_SENSITIVE`.
- pipeline.py: `Deps` dataclass (max_monitored_boards=500, max_new_boards_per_run=50, allow_smartrecruiters, dry_run, ...); `run_cycle` order: seeds/discovery admission -> `activate_waiting` (line ~209) -> SmartRecruiters count note (line ~213) -> poll loop (line ~220: suspicious empty -> failure, `apply_poll_result`, flood re-baseline at `FLOOD_MIN_JOBS`, `lg.Observation`, `observe_new`, baseline sets baselined_at + active) -> registry counts -> Serper hydration -> save events, then boards, then Discovery tab values (`save_values`, saved only if changed) -> evaluate -> alert.
- inventory.py: `validate_board` returns `ValidationResult(outcome, jobs, relevant, error)`; `apply_validation(rec, res, now)` refuses new/active/disabled rows; `validation_due` (candidate backoff 2^n h capped 48 h; validated after `REVALIDATE_VALID_AFTER` 7 d; invalid after 30 d; deferred when policy allows); `_priority`; `interleave_by_ats`; `run_validation(registry, *, save, now, fetch, title_gate, max_boards=500, max_seconds=900, workers=8, wave=200, allow_smartrecruiters, limiter, sleep, clock, breaker_after=15)`; `policy_blocks(ats, *, allow_smartrecruiters) -> str | None`; `ValidationSummary`; `format_report`.
- hunter.py: `DEFAULT_SETTINGS` list of (key, default, note) (Max_New_Boards_Per_Run last, line ~154); `Settings` frozen dataclass + `from_values` with `pick()` and `_int_or`; `settings_notes(raw)`; `run_inventory(args, store, settings, excluded)` with a `save` closure; `main()` argparse (inventory group, `inventory_mode` skips the GROQ key check); `pl.Deps(...)` built at line ~1549.
- tests: `tests/test_core.py` has `T0`, `ago()`, `job()`, `gate()`, `Harness` (real pipeline + CsvState in a temp dir, `run(minutes_later, seeds, **deps_kw)`, `events()`, `states()`), `HarnessCase` (`self.w`, `key()`, `baseline()`). `tests/test_inventory.py` has `FakeWs` / `FakeSh` (no `col_values`), `listed()`, `CliTests` (CsvStore with `make_store` patched). `tests/test_hunter.py` has `FakeWorksheet` (has `col_values`) / `FakeSpreadsheet`, `SettingsTests`.
</interfaces>
</context>

<conflicts>
Flagged per AGENTS.md rule 1. Every item is a deliberate change the user explicitly requested in TASK.md items 1-7; each task updates the named docs in the same commit, and the executor lists these conflicts in the SUMMARY.

- C-1 D-14 ("Relevance is a snapshot ... re-validated weekly rather than polled hourly") and SPEC "Polling budget" (vacancy-only promotion): monitored boards' relevance is now refreshed on every complete poll; promotion becomes pool-based; boards can leave monitoring through a weekly rebalance. Docs: SPEC "Board registry" / "Polling budget"; new D-23 and D-26; D-14 annotated "Changed by D-23/D-26". (Tasks 1, 2)
- C-2 D-15 ("importer owns candidate/validated/invalid/deferred; poller owns new/active/disabled"): the poller now also writes demotions into `validated` rows and performs every pool transition; the importer gains a compare-and-set guard. Docs: new D-28 (Task 2) extended in Task 3; D-15 annotated.
- C-3 D-13 / D-19 "Existing data" / D-10 / D-22 (SmartRecruiters boards already monitored are not demoted, only counted in Runs.Notes): they are now parked every run while the provider is parked, history kept. Docs: new D-27; D-10 and D-22 bullets marked resolved; D-19 annotated; SPEC "Provider limits". (Task 2)
- C-4 D-05 and SPEC "Baselining" (baseline only on the first poll): a re-entering board gets a re-established baseline with source-evidence judgement of gap jobs. Docs: new D-24; SPEC "Freshness vocabulary / Baselining" and "Statuses". (Task 1)
- C-5 D-08 and SPEC "Filtering order" step 1 (level keyword required): level matching gains morphological variants and space/hyphen tolerance; default Target_Levels gains "Entry Level, New Grad". Seniority exclusions unchanged. Docs: new D-25; SPEC "Filtering order"; README Settings. (Task 1)
- C-6 AGENTS.md rule 7 ("Do not tune scores or add features until freshness and delivery are proven"): this task adds allocation features at the user's explicit request. It does not touch the Groq job scorer, `Min_Alert_Score`, or Serper. The board-ranking score is not a job score; its weights are labelled initial operating choices (D-30). Scheduled rebalancing ships in `report` mode.
- C-7 SPEC "Observability": new Boards and Runs columns. (Tasks 1, 2)
</conflicts>

<design>
Shared reference for all three tasks. Implement exactly this; where something is unspecified, choose the simplest deterministic option and record it in the SUMMARY.

**D1. New BoardRecord fields** (append to the dataclass after `provenance`, all with defaults; append the Boards columns in this order after `Provenance`; old 18-column rows must load with these defaults):

| # | Column | Field | Type, default | Meaning |
|---|---|---|---|---|
| 19 | Eligible_Jobs | eligible_jobs | int or None, None | relevant listed jobs (unique IDs) whose listing location is not excluded by the US location rule; None = never measured |
| 20 | Relevance_At | relevance_at | str, "" | when Relevant_Jobs / Eligible_Jobs were last measured (complete poll or validation) |
| 21 | Activity_Since | activity_since | str, "" | start of the current continuous monitoring stint; "" = no observation history |
| 22 | Complete_Polls | complete_polls | int, 0 | complete successful polls since Activity_Since |
| 23 | Last_New_Relevant_At | last_new_relevant_at | str, "" | first-observation time of the board's latest new relevant posting |
| 24 | New_Relevant_7d | new_relevant_7d | int or None, None | new relevant postings first observed in the last 7 days; None = unknown |
| 25 | New_Relevant_30d | new_relevant_30d | int or None, None | same over min(30 days, stint length); None = unknown |
| 26 | Pool | pool | str, "" | "established", "exploration" or "" (not monitored) |
| 27 | Pool_Since | pool_since | str, "" | when it entered its current pool, or became waiting / left monitoring |
| 28 | Trial_Until | trial_until | str, "" | end of the exploration trial |
| 29 | Trials | trials | int, 0 | exploration trials started |
| 30 | Weak_Streak | weak_streak | int, 0 | consecutive rebalance cycles in which this established board was a replacement target |
| 31 | Pool_Reason | pool_reason | str, "" | last admission / graduation / demotion / park reason (max 200 chars) |

Persist None as a blank cell and 0 as "0"; parse a blank or non-numeric cell back to None for the three nullable int fields and to 0 for the plain int fields. `relevant_jobs` keeps its column but is now refreshed by complete polls too.

**D2. Evidence.** "Relevant" = passes the title gate. "Eligible" = relevant and `eligibility.location_blocks(location)` is None (same rule as the hard gate; an empty listing location is not excluded). A poll is *complete* when the fetch succeeded, was not converted to a failure by the suspicious-empty rule, and the adapter did not truncate the listing (`boards.Listing.complete`, False only for SmartRecruiters past 5,000 postings). "New relevant posting" = a ledger `seen` state with `seen_detail.source == "poll"`, disposition `pending`, and `seen_detail.pass` not in {"baseline", "reentry"}; its time is the first-observation time. Counts only include observations at or after Activity_Since. `ACTIVITY_MIN_DAYS = 7`: both counts are None while the stint is shorter than 7 days. Activity is computed from the ledger (`lg.replay` states), never from search dates or update times. Serper-first observations are not activity (documented limitation).

**D3. Pools and targets.** `PoolPolicy(max_active=500, exploration_pct=20, exploration_days=7, rebalance_every_days=7, max_replacements=20, mode="report")`; `exploration_target = round(max_active * exploration_pct / 100)` (100), `established_target = max_active - exploration_target` (400), `min_complete_polls = exploration_days * 12` (84, half of the hourly polls of one trial). Hard rule: total monitored never exceeds `max_active` through admission. Established never grows past its target through graduation. Every board admitted into monitoring enters `exploration` on a trial; exploration may temporarily exceed its target only while established has free slots (so no slot is ever left idle, matching today's fill behavior). `Deps.max_monitored_boards` stays the single source of truth for `max_active`.

**D4. Score (transparent; initial operating choice, not tuned).** `open = min(eligible_jobs if not None else relevant_jobs, OPEN_CAP=5)`. `weekly_rate = new_relevant_30d * 7 / min(30, stint_days)` when new_relevant_30d is not None, else None. `score = RATE_WEIGHT(2.0) * min(weekly_rate, RATE_CAP=5.0) + open` (range 0..15); None when weekly_rate is None. Rates are per observed day, so a longer history never raises a score; there is no tenure term; ties break on board key. Caps stop an aggregator board with hundreds of matching jobs from dominating.

**D5. Evidence check** `evidence_problem(rec, now, policy) -> str | None` (None = sufficient): score is None ("activity unknown: stint shorter than 7 days"); `complete_polls < policy.min_complete_polls` ("N complete polls, need M"); `consecutive_failures > 0` ("last poll failed"); relevance_at missing or older than `EVIDENCE_MAX_AGE = 24 h` ("evidence older than 24 h"). Boards without sufficient evidence are never demoted, never shed, never graduated.

**D6. Admission order (hourly vacancy fill, `boards.activate_waiting`).** Waiting candidate = status validated, validation valid, `open > 0` (eligible if known, else relevant), provider not blocked. Room = min(per_run, max_active - monitored). Sort key: (trials > 0, -open_uncapped, -relevant_jobs, last_job_count, key): boards never tried before always come first (the fair route for boards without observation history), then the most eligible open jobs. Promotion sets status new, pool exploration, trials += 1, trial_until = now + exploration_days, pool_since = now, weak_streak = 0, and pool_reason "explore YYYY-MM-DD: trial until DATE; E eligible / R relevant open jobs (first trial | re-entry, trial N)".

**D7. Every-run sync (`pools.sync_pools`, before activation, all modes).** (a) Provider policy: any new/active/disabled board whose provider is blocked becomes `deferred`, validation `deferred`, last_error = the policy text, pool "", pool_since = now, activity_since "", complete_polls 0, weak_streak 0, pool_reason "parked YYYY-MM-DD: provider policy (SmartRecruiters robots.txt); history kept". baselined_at, last_success_at, last_validated_at, relevant/eligible counts, provenance and all events are kept. (b) Pool hygiene: a non-monitored board with a pool label gets pool "", trial_until "", weak_streak 0, pool_since = now, pool_reason "left monitoring YYYY-MM-DD: <status>" (e.g. disabled after N consecutive failures). (c) Legacy label: a monitored board with pool "" (monitored before pools existed) becomes exploration with trials += 1, trial_until = now + exploration_days, pool_since = now, pool_reason "migrated YYYY-MM-DD: monitored before pools existed; trial until DATE". No tenure shortcut: legacy boards earn established status by the same measured trial. Iterate in board-key order.

**D8. Weekly rebalance (`pools.plan_rebalance`, pure, reads record fields only).** Due when the last rebalance is missing or at least `rebalance_every_days * 24 h - SLACK (1 h)` ago; "last" = the later of the Discovery-tab key `rebalance` ("at") and the newest pool_since among rows whose pool_reason starts with "rebalance " (so a crash after rows are saved cannot repeat replacements). Steps, all lists sorted with board key as the final tie-break:
1. Waiting count W = waiting candidates (D6 definition).
2. Trial-enders = exploration boards with trial_until <= now + SLACK. Those with an evidence problem -> `extend` (trial_until = now + exploration_days; reason "trial extended (<problem>)"). The rest, sorted by score descending, form G.
3. V = established boards without an evidence problem, sorted by score ascending. Established boards with an evidence problem are protected this cycle and their weak_streak resets to 0. Exploration boards on an active trial are never in G or V.
4. Capacity cut, only if monitored > max_active: remove the lowest-scoring members of G first (action `shed`, not counted against the bound), then members of V (action `shed`, counted against the bound), until within the cap or out of evidence-backed boards or bound. Reason "capacity cut to Max_Active_Boards=N (score S)".
5. Pairing with vacancies = established_target - established count and a replacement counter: for g in G: if vacancies > 0 -> `graduate` (no victim). Else, if the next unused v in V satisfies score(v) + MARGIN (1.0) < score(g): v is marked weak this cycle (new streak = weak_streak + 1); if new streak >= WEAK_CYCLES_TO_DEMOTE (2) and replacements < max_replacements -> `replace` (g graduates, v returns to waiting, replacements += 1); else `defer` (g keeps its exploration slot and trial_until so it is judged again next cycle; reason names v and whether v needs a second weak cycle or the bound was reached). Else -> trial lost: `return` to waiting if fewer than W boards have returned so far this cycle (never free more slots than there are boards waiting), otherwise `keep` (trial_until = now + exploration_days; reason "trial ended, kept (no relevant board waiting)").
6. Every V member not marked weak this cycle gets weak_streak 0.
`max_replacements` bounds how many established boards leave per cycle (replacements plus established capacity cuts). Ended trials leaving is the purpose of a trial and is bounded by W instead.

**D9. Applying a plan (`pools.apply_plan`, mode "on" only).** graduate / replace-in: pool established, pool_since now, trial_until "", weak_streak 0. replace-out / return / shed: `demote` = status validated (waiting), pool "", pool_since now, weak_streak 0, activity_since "", complete_polls 0, new_relevant_7d / 30d None; validation, last_validated_at, relevant/eligible counts, baselined_at, last_success_at, last_new_relevant_at, provenance and the ledger are untouched. extend / keep: trial_until updated. defer: reason only. Every reason starts "rebalance YYYY-MM-DD: ". Return the changed records.

**D10. Re-entry.** A board is re-entering when its status is new and baselined_at is set (only possible after a demotion or policy unpark). Its next successful poll is a re-entry pass: `freshness.classify(..., reentry=True)` returns BASELINE ("appeared while the board was not monitored; no source date") for an undated job when the board gap is not within the window; every other case uses the normal rules with the real gap (time-fresh -> verified_fresh and alertable; dated within Max_Job_Age_Days -> recent, evaluated, tracker only; older -> stale; future-dated -> uncertain; gap within window -> observed_new). The flood re-baseline rule is skipped for re-entry passes. Observations carry `pass = "reentry"`. After the pass: status active, baselined_at = now, a new stint starts (activity_since = now, complete_polls 0, counts None). A failed re-entry poll leaves the board in status new for the next run.

**D11. Ownership and overlap.** All pool transitions (promotion, graduation, demotion, trial updates, policy parking of monitored rows, legacy labels) happen only inside the hourly poller (`job-hunter` concurrency group, never concurrent with itself); the weekly rebalance is a step of an hourly run, not a new workflow. The validation workflow saves with `skip_if_status = POLLER_OWNED = {new, active, disabled}`: before writing, the store re-reads the current Status of the target rows and drops rows another process has promoted. The dry-run report is read-only. Residual risk (documented): the milliseconds between that read and the write; consequence bounded because job state lives in Events.

**D12. Logging.** Runs columns appended after Verified_Fresh_Matches in this order: Pool_Established, Pool_Exploration, Waiting_Relevant, Oldest_Waiting_Hours, Relevant_Coverage_Pct, Graduated, Demoted, Parked_Policy, Rebalance. Waiting_Relevant = waiting candidates (D6). Oldest_Waiting_Hours = hours since pool_since (fallback last_validated_at) of the longest-waiting one; blank if none. Relevant_Coverage_Pct = round(100 * monitored boards with open > 0 / (that + Waiting_Relevant)); blank if the denominator is 0. Graduated / Demoted = transitions applied this run; Parked_Policy = monitored boards parked this run; Rebalance = "" (not due), "report" or "applied". One log line per transition ("Pool <key>: <from> -> <to> (<reason>)") plus a pools summary line each run.
</design>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: Board evidence end to end: new registry columns, complete-poll relevance and activity refresh, re-entry baseline, title-gate audit</name>
  <files>boards.py, state.py, ledger.py, freshness.py, eligibility.py, pools.py, pipeline.py, hunter.py, tests/test_pools.py, tests/test_core.py, SPEC.md, DECISIONS.md</files>
  <read_first>AGENTS.md; SPEC.md ("Board registry", "Freshness vocabulary", "Filtering order"); DECISIONS.md D-05, D-08, D-14, D-15; boards.py lines 276-499; state.py lines 25-125 and 161-170; ledger.py lines 137-170; freshness.py lines 112-153; eligibility.py; pipeline.py lines 205-255; tests/test_core.py lines 1-137 and 284-306; tests/test_inventory.py lines 618-672 (FakeWs/FakeSh)</read_first>
  <behavior>
    - Old 18-column Boards rows (CsvState and SheetState) load with pool "", eligible_jobs None, new_relevant_7d/30d None, complete_polls 0; a SheetState header of 18 names widens to all 31; a record with new_relevant_7d None and another with 0 round-trip as None and 0 respectively.
    - Tracer path: after a complete poll of a baselined board listing "Marketing Intern" (Remote), "Marketing Intern" (London) and "Software Engineer" (Remote), the persisted row has relevant_jobs 2, eligible_jobs 1, relevance_at = run time, complete_polls incremented.
    - A listing returned as Listing(..., complete=False), a failed poll (BoardError), and a suspicious empty listing each leave relevant_jobs, eligible_jobs, relevance_at and complete_polls unchanged; a new ID on the partial listing is still observed.
    - The first baseline pass starts a stint (activity_since = now, complete_polls 1 after that poll); its observations, including a time-fresh one, carry pass "baseline" and are not activity; flood re-baseline observations also carry pass "baseline".
    - Before the stint is 7 days old both counts are None but last_new_relevant_at is set when a new relevant job is observed; a run more than 7 days after that observation shows new_relevant_7d 0 and new_relevant_30d 1; a new job failing the title gate, a stale job and a search-found job never count.
    - A legacy board (baselined_at set, activity_since "") gets activity_since = baselined_at at its first complete poll; complete_polls counts from then.
    - Re-entry (status new + baselined_at set, last success 3 days earlier): undated unseen job -> baseline, not evaluated; job dated 2 days ago -> recent, evaluated, not alerted; job published 30 min ago -> verified_fresh, evaluated and alerted; already-seen IDs produce no new seen event; after the poll the board is active with baselined_at and activity_since = now; re-entry observations carry pass "reentry" and are not activity; the flood rule is not applied.
    - Title gate: pass "Marketing Coordinator", "Marketing Internship", "Social Media Internship - Summer 2027", "Jr. Content Creator", "Jr Content Creator", "Marketing - Entry Level", "Entry-Level Social Media", "New Grad Marketing Program"; reject "Senior Marketing Internship", "Marketing Lead - Entry Level", "Social Media Marketing", "Marketing Strategist", "Content Creator", "International Marketing Manager".
  </behavior>
  <action>
Write the failing tests first (new file tests/test_pools.py importing `T0, ago, job, gate, Harness, HarnessCase` from test_core and `FakeSh` from test_inventory, as test_discovery does with test_hunter fakes), then implement:

1. boards.py: add the 13 fields of design D1 to `BoardRecord` after `provenance`. Add `class Listing(list)` carrying a `complete` attribute (default True; constructor accepts the jobs and `complete=`). In `fetch_board`, return `Listing(parsed, complete=False)` for SmartRecruiters when paging stopped at the 5,000 cap while `totalFound` was larger; every other path stays a plain list. Add `complete: bool = True` to `PollResult`; `poll_boards` sets it from `getattr(jobs, "complete", True)`.
2. state.py: append the 13 column names of D1 to `BOARD_COLUMNS`; extend `board_to_row` (None -> "") and `board_from_row` (padded rows; blank or non-numeric nullable ints -> None, plain ints -> 0). No other persistence change in this task.
3. eligibility.py: extract the hard gate's non-US location rule into a public `location_blocks(location) -> str | None` returning the same message; `hard_gate` calls it (behavior identical; `test_hard_gate_is_conservative` must still pass). Title-gate audit per D-25 below: (a) inside a configured term, a space and a hyphen are interchangeable (split each term on runs of spaces/hyphens, escape the tokens, join them with a pattern accepting one or more spaces or hyphens); (b) level matching also accepts morphological variants of the user's own configured level words via a small table: Intern also matches Internship/Internships, Junior also matches Jr and Jr. (whole word, the period optional); variants apply only when that word is in the configured levels. The excluded-word check stays first and unchanged. Do not relax the requirement for a level signal.
4. hunter.py: change only the default value of Target_Levels to "Coordinator, Associate, Specialist, Intern, Assistant, Junior, Entry Level, New Grad" (existing Sheets keep their explicit value; Task 3 documents it in README).
5. ledger.py: add `pass_kind: str = ""` and `reentry: bool = False` at the end of `Observation`. `observe_new` passes `reentry=obs.reentry` to `fr.classify` and adds `"pass": obs.pass_kind` to the seen detail when pass_kind is non-empty.
6. freshness.py: add `reentry: bool = False` to `classify`; implement D10 (only the undated-and-gap-not-within-window case changes, returning BASELINE with the evidence text "appeared while the board was not monitored (last successful poll N min earlier); no source date"); all other rules unchanged.
7. pools.py (new module, pure, no I/O; imports boards, ledger, eligibility only): `ACTIVITY_MIN_DAYS = 7`; `board_key_for_job(job_key, board_spelling) -> str` (ats and optional `@region` from the job-key prefix, board from the seen detail as spelled, so Lever/Workable case matches the registry key); `ActivityIndex.from_states(states)` collecting first-observation datetimes per board key for the D2 definition, plus `times(board_key)`; `refresh_relevance(rec, jobs, title_gate, now)` (unique IDs; sets relevant_jobs, eligible_jobs, relevance_at; complete_polls += 1); `start_stint(rec, now)` (activity_since = now, complete_polls 0, both counts None); `refresh_activity(rec, index, now)` (counts per D2 or None; last_new_relevant_at = latest indexed time if any, else unchanged).
8. pipeline.py poll loop: compute `reentry = was_baselined and res.board.status == STATUS_NEW`; skip the flood rule when reentry; pass_kind = "baseline" for a first or flood baseline pass, "reentry" for re-entry, else ""; build the Observation with pass_kind and reentry. After the jobs are observed: when this poll started a stint (first baseline completed, or reentry) set baselined_at = now, status active, and call `pools.start_stint`; otherwise, if activity_since is empty and baselined_at is set (legacy board), set activity_since = baselined_at. Then, only when `res.ok and res.complete`, call `pools.refresh_relevance(rec, res.jobs, d.title_gate, now)`. After the poll loop, build `pools.ActivityIndex.from_states(states)` once and call `pools.refresh_activity` for every board in `boards` whose status is monitored, adding each to `dirty`. Keep rule 1 (events saved before boards).
9. tests: tests/test_pools.py classes `BoardColumnsTests`, `RelevanceRefreshTests`, `ActivityTests`, `ReentryTests` covering every behavior bullet (simulate days by `self.w.run(minutes_later=...)`; inject a partial listing by putting `bd.Listing([...], complete=False)` into `self.w.listings`; simulate re-entry by editing the saved row's status to new with `self.w.state.save_boards`). tests/test_core.py: add `test_title_gate_audit` to `EligibilityTests` with the exact titles above.
10. Docs (same commit, AGENTS rule 1): SPEC "Board registry" (status `new` with an existing baseline means re-entry; relevance refreshed on complete polls; activity fields and unknown-vs-zero), SPEC "Baselining" (re-entry rule), SPEC "Filtering order" step 1 (variants). DECISIONS: add D-23 "Board evidence from complete polls" (fields, complete-poll definition, activity definition, baseline/re-entry exclusion, unknown vs zero, Serper-first limitation; annotate D-14 "Changed by D-23"), D-24 "Re-entry re-establishes the baseline" (amends D-05), D-25 "Title-gate audit" (finding: "Marketing Coordinator" already passes because Coordinator is a level word; rejected suitable titles were "...Internship", "Jr. ...", "Entry-Level ...", "New Grad ..."; titles with no level signal such as "Content Creator", "Web Designer", "Social Media Marketing", "Marketing Strategist" stay rejected on purpose; exclusions unchanged; default Target_Levels change affects only new Sheets and blank cells).
  </action>
  <verify>
    <automated>cd <repo> && .venv/bin/python -m unittest discover -s tests -p "test_pools.py" -v && .venv/bin/python -m unittest discover -s tests</automated>
  </verify>
  <done>All behavior bullets have passing tests in tests/test_pools.py and tests/test_core.py; the full offline suite passes (201 original tests plus the new ones); a complete hourly poll persists refreshed relevance and activity evidence in the 31-column Boards tab; SPEC and DECISIONS (D-23, D-24, D-25, D-14 annotation) describe the change; committed atomically.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Pools: provider parking, pool-aware admission, weekly bounded rebalance, state-preserving demotion, run logging</name>
  <files>pools.py, boards.py, pipeline.py, state.py, tests/test_pools.py, SPEC.md, DECISIONS.md</files>
  <read_first>design sections D3-D12 above; pools.py and tests/test_pools.py as left by Task 1; boards.py activate_waiting; pipeline.py lines 205-345 (activation, SmartRecruiters note, Discovery-tab save_values); state.py RUN_COLUMNS / RunRecord; tests/test_inventory.py ActivationTests (lines 495-536, must keep passing); tests/test_discovery.py lines 325-360 and 630-641; tests/test_core.py RetryTests lines 372-430 (alert-retry patterns)</read_first>
  <behavior>
    - Policy parking: a seeded monitored SmartRecruiters board (active, baselined, with seen events and provenance) becomes deferred in the next run with pool "", Parked_Policy 1 and history kept (baselined_at, last_success_at, provenance, events unchanged), and is not fetched in the following run; with allow_smartrecruiters=True it stays active; a validated SmartRecruiters board is never activated while blocked.
    - Capacity: vacancy fill never exceeds max_active or per_run, labels promoted boards exploration with trial_until = now + exploration_days and trials incremented; never-tried boards enter before boards that had a trial; a board whose eligible_jobs is 0 waits; legacy monitored boards with no pool are labelled exploration trials; existing ActivationTests still pass.
    - Plan, first weak cycle: a strong ended trial versus a weak established board with weak_streak 0 gives `defer`, the board's streak becomes 1, nothing leaves.
    - Bounded replacement: 50 strong ended trials versus 60 weak established boards with weak_streak 1 and max_replacements 20 give exactly 20 `replace` decisions and 30 `defer`.
    - Trial protection: exploration boards with trial_until in the future never appear in any decision; ended trials with 10 complete polls (need 84) are `extend`ed, not returned.
    - No demotion on thin evidence: established boards with consecutive_failures > 0, relevance_at older than 24 h, or score None are never replaced or shed and their weak_streak resets to 0.
    - Margin: score difference of 1.0 or less never replaces.
    - Free established slots graduate ended trials without any victim.
    - Losing ended trials `return` only up to the number of waiting candidates, the rest `keep`.
    - Capacity cut after lowering max_active: sheds lowest scores, counts established sheds against the bound, never sheds an active trial or an unevidenced board.
    - Score neutrality: two boards with the same weekly rate and open jobs but stints of 10 and 300 days have equal scores.
    - Determinism: the same registry built in two insertion orders yields identical decision lists.
    - Report mode (default): a due rebalance changes no board row, sets Runs.Rebalance "report", writes Discovery keys `rebalance` and `rebalance_report`; a run one hour later does not rebalance again.
    - Crash safety: after an applied rebalance whose Discovery-tab save failed, the next run is not due (row evidence).
    - State preservation (mode on, Harness): a job evaluated "To Apply" whose alert failed stays pending; its board is replaced and returns to waiting; when the alert channel recovers the alert is delivered exactly once; a pending evaluation on the demoted board is still evaluated; the Events count is unchanged by the demotion; provenance and baselined_at are kept; when the board is promoted again it gets trial 2 and a re-entry pass.
    - Runs row records Pool_Established, Pool_Exploration, Waiting_Relevant, Oldest_Waiting_Hours, Relevant_Coverage_Pct; RUN_COLUMNS length equals the RunRecord row length; old short rows still load.
  </behavior>
  <action>
Write the failing tests first (append to tests/test_pools.py: `PolicyParkingTests`, `AdmissionPoolTests`, `RebalancePlanTests` as pure tests building BoardRecord dicts with metrics set directly, `RebalancePipelineTests` on the Harness with `pool_policy=pools.PoolPolicy(mode="on", ...)` and small numbers, e.g. max_monitored_boards 3, exploration_pct 34, exploration_days 1, rebalance_every_days 1, max_replacements 1; seed metrics by saving rows and seen events directly through `self.w.state`), then implement:

1. pools.py: add `PoolPolicy` (frozen; fields and derived properties of D3), constants POOL_ESTABLISHED, POOL_EXPLORATION, OPEN_CAP, RATE_CAP, RATE_WEIGHT, MARGIN, WEAK_CYCLES_TO_DEMOTE, EVIDENCE_MAX_AGE, SLACK, REBALANCE_KEY = "rebalance", REBALANCE_REPORT_KEY = "rebalance_report"; `open_jobs`, `weekly_rate`, `score` (D4); `evidence_problem` (D5); `is_waiting_candidate(rec, blocked)` (D6); `sync_pools(registry, policy, now, blocked) -> SyncResult(changed, parked, migrated, cleared)` (D7); `Decision` (key, action, score, partner, reason) and `RebalancePlan` (decisions plus counts: targets, W, protected trials, unevidenced established, replacements used); `plan_rebalance(registry, policy, now, blocked)` (D8, pure, reads fields only, iterates in key order); `apply_plan(registry, plan, now)` and a shared `demote(rec, now, reason)` (D9); `rebalance_due(stamp_json, registry, now, policy)` (D8 due rule); `coverage(registry, now, blocked) -> dict` (D12 numbers); `format_plan(plan, cov, policy) -> list[str]` (human-readable lines: targets vs actual, each decision with scores and reason, protected and unevidenced counts); `plan_json(plan, now, mode) -> str` (compact JSON, at most 45,000 characters, truncating the decision list with a count). `blocked` is a callable ats -> bool so pools never imports inventory.
2. boards.py: extend `activate_waiting` with keyword-only `now=None` (None -> current UTC time, for existing direct callers), `trial_days=7`, `blocked=None`; implement D6 filter, order and labelling. Keep the function name: SPEC names it as the only way into monitoring.
3. pipeline.py: add `pool_policy: pools.PoolPolicy = field(default_factory=pools.PoolPolicy)` to `Deps`; in `run_cycle` derive `policy` with `max_active = d.max_monitored_boards` (dataclasses.replace) and `blocked` from `inv.policy_blocks(..., allow_smartrecruiters=d.allow_smartrecruiters)`. Before activation call `pools.sync_pools`, add changed rows to `dirty`, set `run.parked_policy`, and add a note "N monitored SmartRecruiters boards parked by provider policy (history kept)"; replace the old parked_monitored warning block. Pass now, trial_days and blocked to `activate_waiting`. After the activity refresh from Task 1: if `pools.rebalance_due(discovery_state.get(REBALANCE_KEY), boards, now, policy)`: build the plan, log each line of `format_plan`; in mode "on" apply it, add changed rows to `dirty`, set run.graduated / run.demoted and run.rebalance "applied", and log one line per transition; otherwise set run.rebalance "report" and add a one-line summary note ("rebalance report: would graduate N, replace M (bound B), defer D, extend E, return R; W relevant boards waiting"). Unless dry_run, put REBALANCE_KEY (JSON with at, mode, counts) and REBALANCE_REPORT_KEY (`plan_json`) into `save_values` so they are saved after the boards (existing order). Then fill the D12 coverage fields on `run` and log a pools summary line. Pending evaluations and alerts stay state-driven and independent of board status (verify, do not change).
4. state.py: append the nine D12 columns to `RUN_COLUMNS` and the matching `RunRecord` fields (ints default 0; Oldest_Waiting_Hours and Relevant_Coverage_Pct default None; Rebalance str ""), and extend `from_row` positionally (indices 27-35, row[35] for Rebalance).
5. Docs (same commit): SPEC "Board registry" statuses (demotion active -> validated; policy parking monitored -> deferred; rows never deleted still holds), "Polling budget" rewritten for pools, trials, weekly bounded rebalance, report mode, score formula reference; "Provider limits" (monitored SmartRecruiters boards parked every run); "State model" (pending retries survive demotion); "Observability" (new Runs columns). DECISIONS: D-26 "Established and exploration pools with a weekly bounded rebalance" (D3-D9 summarised, defaults labelled initial operating choices; annotate D-14 "Changed by D-26"), D-27 "Monitored SmartRecruiters boards are parked" (resolves the D-10 SmartRecruiters bullet and the D-22 second bullet, mark both RESOLVED; annotate D-19 "Existing data"), D-28 "Pool transitions are made only by the poller" (D11 first half; annotate D-15; Task 3 adds the importer guard).
  </action>
  <reversibility rating="costly">Policy parking rewrites the status of existing monitored SmartRecruiters rows to deferred on the first run; reverting the code does not restore them to active (ALLOW_SMARTRECRUITERS_BULK=1 plus validation does). History and events are kept, so nothing is lost.</reversibility>
  <verify>
    <automated>cd <repo> && .venv/bin/python -m unittest discover -s tests -p "test_pools.py" -v && .venv/bin/python -m unittest discover -s tests</automated>
  </verify>
  <done>Every behavior bullet has a passing offline test; the full suite passes; in default report mode no board leaves monitoring because of rebalancing, while policy parking and pool labels apply every run; SPEC and DECISIONS (D-26, D-27, D-28 plus annotations on D-10, D-14, D-15, D-19, D-22) are updated; committed atomically.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Two validation queues, importer write guard, Settings, dry-run rebalance report, workflows, STATUS/README</name>
  <files>inventory.py, state.py, hunter.py, pools.py, .github/workflows/job_hunter.yml, .github/workflows/inventory.yml, tests/test_inventory.py, tests/test_hunter.py, tests/test_pools.py, SPEC.md, DECISIONS.md, STATUS.md, README.md, AGENTS.md</files>
  <read_first>design D6, D11, D12 above; inventory.py lines 365-555 and 684-716; state.py save_boards (both classes); hunter.py lines 117-230 and 1436-1585; both workflow files; tests/test_inventory.py RunValidationTests (lines 400-485), SheetBoardsTests and CliTests (lines 674-773); tests/test_hunter.py SettingsTests (lines 47-63); README.md "Where the list of boards comes from", "Using it day to day", "Running it on your own computer"; STATUS.md</read_first>
  <behavior>
    - Queue fairness: 1,000 due candidates plus 5 overdue validated boards with max_boards 10 and max_revalidations 3 -> the 3 most overdue are revalidated and 10 candidates are validated in the same run; with max_revalidations 0 no revalidation happens; within one provider revalidations run oldest-first (last_validated_at ascending, invalid boards by last_attempt_at).
    - The summary reports candidates_due, revalidations_due, per-queue attempted counts, oldest_candidate_hours and oldest_overdue_hours; `format_report` prints both queue lines; `remaining_due` sums both queues.
    - Waiting (validated) SmartRecruiters boards are parked to deferred by run_validation while blocked.
    - Validation stores eligible_jobs (unique IDs, location rule) and relevance_at; a board's first transition to validated sets pool_since and pool_reason "validated YYYY-MM-DD: waiting for a slot"; a revalidation does not reset pool_since.
    - Writer guard: a SheetState and a CsvState importer save with skip_if_status = POLLER_OWNED drops a row whose current stored status is new (promoted by another process after the importer loaded it) and returns its key; other rows are written.
    - Settings: defaults Exploration_Share_Percent 20, Exploration_Days 7, Rebalance_Every_Days 7, Max_Replacements_Per_Rebalance 20, Rebalance_Mode "report"; share clamps to 0..100, days to >= 1, replacements to >= 0; an unknown mode falls back to "report" and settings_notes reports it.
    - `hunter.main(["--rebalance-report"])` with a CSV store holding monitored and waiting boards exits 0 without a Groq key, prints pool targets, coverage, validation queue ages and the planned decisions, and leaves every state file byte-identical.
  </behavior>
  <action>
Write the failing tests first, then implement:

1. inventory.py: `POLLER_OWNED = frozenset({STATUS_NEW, STATUS_ACTIVE, STATUS_DISABLED})`. `validate_board`: count relevant over unique IDs and add `eligible` (relevant and `eligibility.location_blocks(location)` is None) to `ValidationResult`. `apply_validation`: on valid/valid_empty set eligible_jobs and relevance_at too; when the status changes to validated from another status and pool_since is empty, set pool_since = now and pool_reason "validated YYYY-MM-DD: waiting for a slot". `run_validation`: new keyword `max_revalidations: int = 500`; extend the policy-parking loop to STATUS_VALIDATED rows; build two queues: candidates (status candidate or deferred and due; `_priority` then `interleave_by_ats`, cut to max_boards) and revalidations (status validated or invalid and due; sorted by the timestamp they became due from, oldest first, unparseable or missing first, then key; `interleave_by_ats`; cut to max_revalidations); merge them by strict alternation starting with a revalidation, continuing with whichever queue remains; everything else (waves, time budget, breaker, batched saves) unchanged. Add `queue_stats(registry, now, *, allow_smartrecruiters) -> dict` (due counts and the two ages) used by run_validation and the CLI report; add the new summary fields and two report lines ("candidates: due X, validated Y, oldest waiting Z h" and "revalidations: overdue X, done Y, oldest overdue Z h").
2. state.py: `save_boards(records, *, skip_if_status=frozenset())` on both stores returns the list of skipped keys. SheetState: when skip_if_status is non-empty, read current keys and statuses with `col_values(1)` and `col_values(4)` when the worksheet has `col_values` (fall back to `get_all_values`), drop records whose current status is in the set, learn row numbers for the rest, then write as today. CsvState: compare against the current file. Add `col_values` to `FakeWs` in tests/test_inventory.py.
3. hunter.py: append five DEFAULT_SETTINGS rows (Exploration_Share_Percent "20", Exploration_Days "7", Rebalance_Every_Days "7", Max_Replacements_Per_Rebalance "20", Rebalance_Mode "report") with plain-language notes stating that 80/20 and 7 days are starting choices, not proven best values, and that report mode only writes a weekly report; add the matching Settings fields and parsing with the clamps above; `settings_notes` flags an unknown Rebalance_Mode; build `pools.PoolPolicy` from Settings and pass `pool_policy=` to `pl.Deps`. `run_inventory`: the save closure passes `skip_if_status=inventory.POLLER_OWNED` and logs how many rows were skipped; pass `max_revalidations=args.max_revalidations`. Add CLI flags `--max-revalidations` (inventory group, default 500) and `--rebalance-report` (treated like inventory mode: no Groq key needed); `--rebalance-report` calls a new `run_rebalance_report(store, settings)` that loads boards, events and the Discovery tab, calls `pools.preview(...)`, prints `pools.format_report(...)` plus the inventory queue lines, writes nothing, and returns 0.
4. pools.py: add `preview(registry, states, policy, now, blocked, stamp_json) -> (sync, plan, cov, due)` that works on a deep copy (sync, activity refresh for monitored boards, plan as if due now, coverage) and `format_report(...) -> str` (header with mode and policy numbers and the score formula; coverage; what sync would change: SmartRecruiters parking and legacy labels; the plan; the next 20 boards in the admission order; whether a scheduled rebalance is due; a closing line "dry run: nothing was written").
5. Workflows: job_hunter.yml adds a workflow_dispatch boolean input `rebalance_report` ("Print the dry-run board rebalance report; changes nothing"); when true run `python hunter.py --rebalance-report` instead of the normal step (same job, same concurrency group). inventory.yml adds `--max-revalidations 2000` to ARGS and updates its header comment to say revalidations have their own budget.
6. Tests: tests/test_inventory.py `ValidationQueueTests` (fairness, oldest-first, independent budgets, queue ages and report lines, waiting SmartRecruiters parked, eligible and pool_since at validation), writer-guard tests for SheetState and CsvState, and CliTests `test_rebalance_report_prints_the_plan_and_writes_nothing` (compare state file bytes before and after); tests/test_hunter.py `SettingsTests.test_pool_settings_defaults_clamps_and_mode_note`.
7. Docs (same commit): SPEC "Board registry" (two validation queues, oldest-first revalidation, independent budgets), "Board admission" paragraph (pool entry; importer guard). DECISIONS: D-29 "Validation runs two independently budgeted queues"; extend D-28 with the importer compare-and-set guard and its residual window; D-30 "Open items to confirm" (80/20 split, 7-day trials, 20 replacements per cycle, weights 2 x rate + open, caps 5/5, margin 1.0, two weak cycles, 84 complete polls are initial operating choices; Rebalance_Mode default report and how to enable; whether to add Entry Level / New Grad to existing Sheets; provenance updates for monitored boards are deferred until they are no longer monitored because the importer skips poller-owned rows). STATUS: latest-change paragraph, verification table rows (all new areas mocked/offline; nothing live), migration requirements (automatic Boards/Runs header widening, old rows load with unknown evidence, first run parks monitored SmartRecruiters boards and labels legacy boards as exploration trials, new Settings rows optional with defaults, enable with Rebalance_Mode=on after reviewing `--rebalance-report` or the Actions input), known gaps (weights unproven, Serper-first jobs not counted as activity, partial listings only detected for SmartRecruiters past 5,000 postings, residual write window, pools only act once trials end). README: pools and weekly rebalance in plain language in "Where the list of boards comes from"; the five new Settings rows and the Target_Levels note; developer commands `--rebalance-report` and `--max-revalidations`. AGENTS.md "Layout": add `pools.py` to the core module list.
  </action>
  <verify>
    <automated>cd <repo> && .venv/bin/python -m unittest discover -s tests -v 2>&1 | tail -5 && .venv/bin/python -c "import yaml,sys; [yaml.safe_load(open(p)) for p in ('.github/workflows/job_hunter.yml','.github/workflows/inventory.yml')]; print('workflows parse')"</automated>
  </verify>
  <done>Queue fairness, writer guard, Settings and dry-run report tests pass; the full offline suite passes; both workflow files parse (if PyYAML is missing in .venv, the executor reports that and checks the YAML with the available tooling instead); SPEC, DECISIONS (D-28 extension, D-29, D-30), STATUS (with migration requirements and mocked-vs-live), README and AGENTS layout reflect the shipped behavior; committed atomically.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| ATS public APIs -> poller | Untrusted listing data (titles, locations, counts) now drives board ranking |
| Google Sheet Settings / hidden tabs -> runs | User-editable values (pool settings, Rebalance_Mode, hand-edited Boards cells) are untrusted input |
| Validation workflow <-> hourly workflow | Two processes write the same Boards tab with row-level upserts |
| GitHub workflow_dispatch input -> runner | The new `rebalance_report` boolean selects a read-only command |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-olj-01 | Tampering | state.save_boards called by hunter.run_inventory | high | mitigate | `skip_if_status=POLLER_OWNED` compare-and-set; all pool transitions only in the hourly poller (one concurrency group); residual window documented in D-28 |
| T-olj-02 | Denial of service | pools.plan_rebalance demoting good boards after outages | high | mitigate | Evidence rule D5 (84 complete polls, last poll OK, evidence under 24 h), two consecutive weak cycles, margin 1.0, replacement bound, active trials protected, report mode by default |
| T-olj-03 | Tampering | hunter.Settings pool rows | medium | mitigate | Clamp share to 0..100, days to >= 1, replacements to >= 0; unknown Rebalance_Mode falls back to report and is flagged in Runs.Notes |
| T-olj-04 | Tampering | state.board_from_row on hand-edited cells | low | mitigate | Blank or non-numeric values parse to None/0, never raise; unknown pool labels are corrected by sync_pools hygiene |
| T-olj-05 | Denial of service | pools.score with aggregator boards | medium | mitigate | OPEN_CAP 5 and RATE_CAP 5 bound any single board's score |
| T-olj-06 | Repudiation | pool transitions | medium | mitigate | Pool_Reason on every changed row, one log line per transition, Runs counters, Discovery-tab `rebalance_report` JSON |
| T-olj-07 | Spoofing (freshness claim) | freshness.classify re-entry pass | high | mitigate | Gap jobs judged by source publication evidence only; undated ones become baseline; never verified_fresh or observed_new without evidence |
| T-olj-08 | Elevation of privilege (policy) | polling SmartRecruiters against robots.txt | medium | mitigate | sync_pools parks monitored SmartRecruiters boards every run; activate_waiting and run_validation honour the same predicate |
| T-olj-09 | Information disclosure | `--rebalance-report` output, logs | low | accept | Prints board keys, counts and reasons only; reads no `.env`, resume or service-account file beyond the existing credential loading |
| T-olj-SC | Tampering | package installs | low | accept | No new dependencies (PyYAML use in verify is optional and only if already installed) |
</threat_model>

<source_audit>
| Source | Item | Covered by |
|---|---|---|
| GOAL | Better boards can enter; boards leave only on evidence; first 500 no longer hold slots indefinitely | Tasks 1-3 |
| REQ-1 | Relevance refresh on complete polls: relevant count, location eligibility, last successful poll (existing Last_Success_At), last new relevant posting, 7/30-day counts, open vs activity separate, baseline excluded, unknown vs zero, no LLM | Task 1 (D1, D2) |
| REQ-2 | Title-gate audit ("Marketing Coordinator" passes; narrow changes; exclusions kept; documented) | Task 1 (D-25) |
| REQ-3 | Separate, independently budgeted queues; overdue revalidations oldest-first | Task 3 |
| REQ-4 | Established/exploration pools, 80/20 (400/100), 7-day exploration, configurable, labelled initial choices, fair route for boards without history | Task 2 (D3, D6), Task 3 (Settings, D-30) |
| REQ-5 | Weekly transparent rebalance on availability and activity, compares with monitored boards, bounded, trials protected, no tenure bias, no demotion on one empty/partial/failed fetch | Task 2 (D4, D5, D8) |
| REQ-6 | Preserve IDs, evidence, provenance, delivery state on demotion; re-entry baseline with source-evidence judgement; pending retries survive | Task 1 (D10), Task 2 (D9, state-preservation tests) |
| REQ-7 | SmartRecruiters restrictions for existing and new boards; existing monitored ones parked with history | Task 2 (D7), Task 3 (waiting boards parked at validation) |
| REQ-LOG | Pool membership, reasons, queue age, relevant waiting candidates, coverage; deterministic, overlap-safe transitions | Task 2 (D12, D8 ordering), Task 3 (queue ages, writer guard) |
| REQ-DRYRUN | Dry-run report before enabling scheduled rebalancing | Task 2 (report mode default), Task 3 (`--rebalance-report`, workflow input) |
| REQ-TEST | Queue fairness, capacity, bounded replacement, trial protection, baseline exclusion, incomplete fetch, state preservation | Task 1 (baseline, incomplete), Task 2 (capacity, bound, trials, preservation), Task 3 (queues) |
| REQ-DOCS | SPEC, DECISIONS, STATUS, README updated; verification and migration reported | Tasks 1-3 (docs in the same commit as each behavior) |
| Exclusions | No Serper redesign; no job-scorer change; no score tuning beyond the board-ranking policy the user asked for | not planned (out of scope) |
</source_audit>

<verification>
- `cd <repo> && .venv/bin/python -m unittest discover -s tests` passes after each task (offline; 201 original tests plus the new ones).
- `.venv/bin/python hunter.py --rebalance-report` against local CSV state (no Sheet) prints a report and changes no file under `state/` (manual smoke check; must not read `.env` contents into output).
- Everything above is mocked or offline. Nothing in this task is verified against live Sheets, Groq, Telegram, Serper or GitHub Actions; STATUS says so.
</verification>

<success_criteria>
- Monitored boards carry refreshed relevance and activity evidence; waiting boards can displace weaker established boards through measured trials, at most 20 per weekly cycle, with no demotion on transient evidence.
- Revalidations no longer starve behind the candidate backlog.
- SmartRecruiters is parked consistently for monitored, waiting and new boards, with history kept.
- Demotion and re-entry keep every job ID, freshness class, provenance and pending retry; re-entry never presents gap jobs as newly published without source evidence.
- Scheduled rebalancing ships in report mode with a dry-run CLI and Actions input; docs list the conflicts, the initial operating choices and the migration steps.
</success_criteria>

<output>
Create `.planning/quick/261014-olj-board-slot-allocation/261014-olj-SUMMARY.md` when done. It must list: the conflicts C-1..C-7 and the docs updated for each; what was verified offline/mocked and that nothing was verified live; the migration requirements (header widening, SmartRecruiters parking and legacy labels on the first run, optional Settings rows, how to switch Rebalance_Mode to on); any deviation from the design sections with the reason.
</output>
