---
phase: 261014-olj-board-slot-allocation
plan: 01
subsystem: board registry / polling budget / validation
tags: [pools, rebalance, board-evidence, reentry-baseline, validation-queues, provider-policy, title-gate]
requires: []
provides:
  - pools.py (activity index, evidence refresh, PoolPolicy, sync, score, plan_rebalance, apply_plan, dry-run report)
  - 13 new Boards columns, 9 new Runs columns, status-guarded save_boards
  - two independently budgeted validation queues
affects: [boards.py, state.py, ledger.py, freshness.py, eligibility.py, pipeline.py, inventory.py, hunter.py, workflows, SPEC, DECISIONS, STATUS, README, AGENTS]
tech-stack:
  added: []
  patterns: [pure planning function over recorded fields, report-mode-first rollout, compare-and-set on current status]
key-files:
  created: [pools.py, tests/test_pools.py]
  modified: [boards.py, state.py, ledger.py, freshness.py, eligibility.py, pipeline.py, inventory.py, hunter.py, .github/workflows/job_hunter.yml, .github/workflows/inventory.yml, tests/test_core.py, tests/test_hunter.py, tests/test_inventory.py, SPEC.md, DECISIONS.md, STATUS.md, README.md, AGENTS.md]
decisions: [D-23, D-24, D-25, D-26, D-27, D-28, D-29, D-30]
metrics:
  duration: single session
  completed: 2026-10-14
status: complete
estimate:
  tokens: 260000
  tasks: 3
actuals:
  tokens: 44600   # chars/4 over the realized diff (178,402 changed characters in code, tests and docs, excluding .planning)
  tasks: 3
  commits: 3
---

# Quick task 261014-olj: Board slot allocation Summary

Monitoring slots are now allocated by measured evidence instead of first come, first kept: complete hourly polls refresh each board's open-job counts and new-posting activity, `Max_Active_Boards` is split into established (400) and exploration (100) pools with 7-day trials, a weekly bounded rebalance compares ended trials with the weakest established boards (report mode by default), and validation re-checks no longer starve behind the candidate backlog.

Commits: `e8d03fd` (Task 1), `9ba427d` (Task 2), `f5d9fda` (Task 3). Docs artifacts (this file, STATE.md, PLAN.md, TASK.md) are intentionally uncommitted for the orchestrator. `tracked_jobs.csv` and secrets were not touched; nothing was pushed.

## What was implemented, per requirement

1. **Evidence refresh (REQ-1).** Every complete, successful poll sets `Relevant_Jobs` (unique IDs passing the title gate), `Eligible_Jobs` (relevant and not blocked by the shared US location rule, `eligibility.location_blocks`), `Relevance_At`, and `Complete_Polls`, from the listing already fetched. A partial listing (`boards.Listing.complete`, set False when SmartRecruiters paging stops short of `totalFound`), a failed poll and a suspicious-empty listing change none of these (a new ID on a partial listing is still observed). New-posting activity (`New_Relevant_7d/30d`, `Last_New_Relevant_At`) is derived from the ledger (`pools.ActivityIndex`): first observations from ordinary board polls, disposition `pending`, not a `baseline`/`reentry` pass, at or after `Activity_Since`; it is blank (unknown) until the stint is 7 days old and a real 0 afterwards. Open-job counts and activity are separate columns. No LLM involved. Baseline and flood re-baseline observations carry `pass: baseline` in the `seen` event.
2. **Title-gate audit (REQ-2).** Finding recorded in D-25: "Marketing Coordinator" already passed (Coordinator is a level word). Wrongly rejected: "...Internship", "Jr. ...", "Entry-Level ...", "New Grad ...". Changes: space/hyphen interchangeable inside a configured term; "Internship" matches Intern and "Jr"/"Jr." matches Junior only when those words are in `Target_Levels`; default `Target_Levels` gains "Entry Level, New Grad". Excluded words still checked first ("Senior Marketing Internship", "Marketing Lead - Entry Level" still rejected); a level keyword is still required.
3. **Two validation queues (REQ-3).** `inventory.run_validation` builds candidates (cut to `max_boards`) and revalidations (validated after 7 days, invalid after 30; oldest first by the timestamp they became due from; missing timestamp first; cut to the new `max_revalidations`), merged by strict alternation starting with a re-check. Summary/report show due counts, per-queue attempted counts, oldest waiting candidate and oldest overdue re-check. Validation also records `Eligible_Jobs`, `Relevance_At`, and starts the waiting clock (`Pool_Since`).
4. **Pools (REQ-4).** `PoolPolicy` (80/20 at 500, 7-day trials) via Settings; every promoted board enters exploration on a dated trial; never-tried boards enter first, then most open eligible jobs; admission never exceeds the cap or per-run limit; boards monitored before pools existed are labelled exploration trials (no tenure shortcut).
5. **Weekly rebalance (REQ-5).** `pools.plan_rebalance` (pure, deterministic): score = 2 x min(weekly new relevant postings, 5) + min(open eligible jobs, 5); margin 1.0; two consecutive weak cycles; at most `Max_Replacements_Per_Rebalance` per cycle; running trials never touched; evidence rule (>= `Exploration_Days x 12` complete polls, last poll OK, evidence < 24 h, known activity) protects thin boards and extends thin trials; capacity cut when the cap was lowered; losing trials return only up to the number of waiting boards. Default `Rebalance_Mode=report` records the plan (Discovery keys `rebalance`, `rebalance_report`; `Runs.Rebalance`) and moves nobody; `on` applies it. `python hunter.py --rebalance-report` and a workflow input print the dry run and write nothing.
6. **State-preserving demotion and re-entry (REQ-6).** Demotion returns a board to `validated` and resets only stint counters; ledger events, baseline, provenance, validation, counts and pending evaluation/alert retries are untouched (retries are driven by the ledger, not board status; tested with a failing alert and a transient evaluation across a demotion). A returning board (status `new` with a baseline) gets a re-entry pass: gap jobs judged by source publication evidence only (undated -> baseline when the gap exceeds the window; dated fresh -> verified_fresh; dated older -> recent/stale), flood rule skipped, new stint started, trial 2.
7. **Provider restrictions (REQ-7).** `pools.sync_pools` parks every `new`/`active`/`disabled` SmartRecruiters board each run while the provider is parked (`deferred`, history kept); `activate_waiting(blocked=...)` never promotes blocked boards; `run_validation` parks waiting ones.

Logging/ownership: Runs columns `Pool_Established`, `Pool_Exploration`, `Waiting_Relevant`, `Oldest_Waiting_Hours`, `Relevant_Coverage_Pct`, `Graduated`, `Demoted`, `Parked_Policy`, `Rebalance`; one log line per transition (`Pool <key>: <from> -> <to> (<reason>)`) and a pools summary line each run; `Pool_Reason` on every changed row. All pool transitions happen only in the hourly poller; the importer/validation save passes `skip_if_status=POLLER_OWNED` (Sheet and CSV stores).

## Flagged conflicts (AGENTS rule 1) and the docs updated for each

- **C-1** D-14 "relevance is a snapshot" / vacancy-only promotion: now refreshed each complete poll and promotion is pool-based. D-23, D-26 added; D-14 annotated; SPEC "Board registry"/"Polling budget".
- **C-2** D-15 two writers: the poller now also writes demotions into `validated` rows; importer gains the compare-and-set guard. D-28 added; D-15 annotated.
- **C-3** D-13/D-19/D-10/D-22 (monitored SmartRecruiters boards left polling): now parked every run, history kept. D-27 added; D-10 and D-22 bullets marked RESOLVED; D-19 annotated; SPEC "Provider limits".
- **C-4** D-05/SPEC "Baselining" (baseline only on the first poll): re-entry re-establishes it. D-24 added; D-05 annotated; SPEC "Baselining"/"Re-entry"/"Statuses".
- **C-5** D-08/SPEC "Filtering order" step 1: variants and default `Target_Levels`. D-25 added; D-08 annotated; SPEC; README Settings.
- **C-6** AGENTS rule 7 (no tuning/features before freshness and delivery are proven): allocation features added at the user's explicit request; the Groq job scorer, `Min_Alert_Score` and Serper untouched; board-score weights are labelled initial choices (D-30); rebalancing ships in report mode.
- **C-7** SPEC "Observability": new Boards (13) and Runs (9) columns documented.

## Verification: mocked vs live

- **Offline/mocked (all of it):** `.venv/bin/python -m unittest discover -s tests` -> **275 tests, OK** (201 original + 74 new in `tests/test_pools.py`, `tests/test_core.py`, `tests/test_inventory.py`, `tests/test_hunter.py`). Fake ATS listings, fake scorer/alert channel, CSV state in temp dirs, a fake gspread worksheet for the Sheet store (including header widening and the write guard). Mutation spot-checks (ignoring `res.complete`, removing the weak-cycle rule, the replacement bound, trial protection, never-tried ordering, provider parking) each made tests fail.
- **Dry-run CLI:** exercised through `hunter.main(["--rebalance-report"])` in a test (no Groq key, state files byte-identical) and once manually against a temporary CSV state directory (not the repo's `state/`, to leave `tracked_jobs.csv` alone). The report output was read and looks right.
- **Workflows:** both YAML files parse (PyYAML in `.venv`); they have never run on GitHub.
- **Nothing was verified live:** no real Google Sheet, Groq, Telegram, Serper, GitHub Actions run, or real ATS endpoint was used. The Sheet store ran only against a fake worksheet; report-mode output on a real registry has not been seen.

## Migration requirements

- Boards (13) and Runs (9) headers widen automatically on the next run; old rows load with unknown (blank) evidence; an old CSV header is rewritten on the first save.
- First hourly run: every monitored SmartRecruiters board is parked (`deferred`, history kept; not undone by reverting the code); every already-monitored board is labelled an exploration trial (7 days); activity counts stay blank until a board's stint is 7 days old. No board can leave through rebalancing until its trial has ended and evidence exists.
- New Settings rows (`Exploration_Share_Percent`, `Exploration_Days`, `Rebalance_Every_Days`, `Max_Replacements_Per_Rebalance`, `Rebalance_Mode`) are optional; existing Sheets keep using defaults until the rows are added by hand (rows are only created with a new Settings tab). Existing Sheets keep their `Target_Levels`; add "Entry Level, New Grad" to use them.
- To enable rebalancing: review `python hunter.py --rebalance-report` (or run Job Hunter with `rebalance_report` ticked), then set `Rebalance_Mode` to `on`.
- `inventory.yml` already passes `--max-revalidations 2000`; no secret or env change.

## Deviations from the plan design

1. **[Rule 2/safety] No-victim trials are deferred, not lost.** If no evidence-backed established board is available but some established boards exist without enough evidence, an ended trial is `defer`red ("no evidence-backed established board to compare with") instead of D8's literal "trial lost". Reason: never lose a good trial because the *other* side lacks evidence.
2. **Losing trials return weakest first.** D8 iterates strongest-first and would return the best losers; the implementation returns the weakest losers up to the number of waiting boards and keeps the rest.
3. **`blocked` returns the policy text (truthy) rather than a plain bool**, so `sync_pools` can store the real `last_error` while `pools` still does not import `inventory`.
4. **Policy-parked rows also clear `trial_until` and the activity counts**; a stale pool label on a non-monitored row is cleared without touching evidence counters.
5. **`Listing.complete` is False whenever SmartRecruiters paging ends with fewer postings than `totalFound`**, not only past 5,000 (covers an empty page mid-listing too).
6. **Crash-safety evidence** for `rebalance_due` falls back to the reason's date at midnight when `Pool_Since` is not from the same day (rows changed only by `defer`/`extend`/`keep` keep their old `Pool_Since`).
7. **Existing test updated:** `test_default_queries_fit_google_limit_and_cover_every_ats` now expects 4 backfill queries (was 2) because the two new default levels no longer fit in two; manual `--backfill` therefore spends more credits with default Settings (also noted in D-25). Rotation slot queries carry two more level terms.
8. **The first-ever run records a rebalance timestamp** even though no trial can have ended, so the first real weekly cycle lines up with the first 7-day trials ending.
9. **TDD ordering:** tests were written together with or just after the implementation rather than as separate failing-test commits (commits are per task, as the plan specifies); the mutation spot-checks above show the tests do bite.

## Remaining limitations and unproven operating choices

- 80/20 split, 7-day trials, weekly cadence, 20 replacements/cycle, score weights (2 x rate + open), caps 5/5, margin 1.0, two weak cycles, and 84 complete polls are initial choices, not proven (D-30). Pools only act once trials end; weak streaks only advance when the plan is applied (report mode never advances them).
- Jobs first seen through Serper are not counted as board activity; partial-listing detection exists only for SmartRecruiters; `Last_Job_Count` is still set from a partial listing (pre-existing).
- Residual window: the importer re-reads a row's status immediately before writing; provenance updates of currently monitored boards are skipped until they leave monitoring.
- Sheet-store `col_values` guard is only fake-tested; `Max_Active_Boards` lowered with `Rebalance_Mode=report` does not shed anyone.

## Known Stubs

None.

## Self-Check: PASSED

- Created files exist: `pools.py`, `tests/test_pools.py`, this summary.
- Commits exist: `e8d03fd`, `9ba427d`, `f5d9fda` (verified with `git log`).
- Full offline suite green (275 tests) after each task and at the end; no tracked files deleted; `tracked_jobs.csv` unmodified.
