---
last_mapped_commit: aa1bab2d3c3e37ac119cd898b2e4f42a50f276fe
last_mapped_at: 2026-10-24
---
# Codebase Structure

**Analysis Date:** 2026-10-24

## Directory Layout

```
auto_search_workflow/                 # repository root (flat Python layout, no package)
├── hunter.py                         # entry point: CLI, Config/Settings, SheetStore/CsvStore, evaluator, alerts
├── pipeline.py                       # run_cycle: discovery -> poll -> evaluate -> alert
├── boards.py                         # board/job identity, ATS adapters, registry records, polling
├── inventory.py                      # inventory import, validation, shared admission path
├── pools.py                          # board evidence, established/exploration pools, rebalance, early release
├── ledger.py                         # Events model, replay, observe_new / observe_known
├── freshness.py                      # timestamp parsing and freshness classes
├── eligibility.py                    # title gate and hard (deterministic) gate
├── discovery.py                      # search rotation, cursor, query runner
├── search.py                         # Tavily client and monthly credit ledger
├── state.py                          # SheetState / CsvState, RunRecord, writer lease
├── reporting.py                      # pure operational summary (no I/O, no clock)
├── dashboard.py                      # renders reporting into the Dashboard tab
├── pilot.py                          # pilot measurements (read only)
├── storage_report.py                 # Events ledger sizing (read only)
├── watchdog.py                       # missed-run monitor, independent of the hunter modules
├── meter.py                          # process-wide request/usage counters
├── tests/                            # offline unittest suite (13 files)
├── legacy/                           # archived earlier version, reference only
├── state/                            # local CSV fallback state (gitignored, not tracked)
├── .github/workflows/                # job_hunter.yml, inventory.yml, watchdog.yml
├── .planning/                        # GSD planning docs: PROJECT.md, ROADMAP.md, STATE.md, quick/, codebase/
├── SPEC.md                           # behavior contract (authoritative)
├── DECISIONS.md                      # decision record D-01..D-47 (authoritative "why")
├── STATUS.md                         # verified / blocked / known gaps (authoritative "what is true now")
├── AGENTS.md / CLAUDE.md             # agent working rules (CLAUDE.md imports AGENTS.md)
├── README.md, DEPLOY.md, PILOT_LOG.md, NOTICE.md
├── requirements.txt                  # runtime dependencies
├── resume.txt, Resume.pdf            # personal data: never read, never committed (gitignored)
├── .env                              # local secrets: never read, never edited (gitignored)
├── tracked_jobs.csv, tracked_jobs.gemini-scored.csv   # old scratch copies (gitignored by pattern), not source
└── .venv/, __pycache__/              # local environment and bytecode (gitignored)
```

Tracked file count at the time of analysis: 58 (`git ls-files`). The `state/` directory and `.venv/` are not tracked.

## Directory Purposes

**Repository root (flat):**
- Purpose: all production modules sit at the top level. There is no `src/` directory and no package `__init__.py`. Imports are plain (`import boards as bd`, `import pipeline as pl`), so every module must run from the repository root.
- Contains: 17 Python modules (total ~9,200 lines), docs, requirements.
- Key files: `hunter.py` (entry point), `pipeline.py` (orchestrator).

**`tests/`:**
- Purpose: offline unit and scenario tests. All tests run with `python -m unittest discover -s tests` (AGENTS rule 8).
- Contains: one file per module or concern. Counts of `def test_` per file at analysis time: `test_inventory.py` 72, `test_hunter.py` 57, `test_discovery.py` 51, `test_core.py` 49, `test_reporting.py` 51, `test_pools.py` 66, `test_deployment.py` 33, `test_pilot.py` 31, `test_search.py` 30, `test_watchdog.py` 32, `test_allocation_correctness.py` 28, `test_pilot_corrections.py` 17, `test_storage_report.py` 10.
- Key files: `tests/test_core.py` (run_cycle behavior), `tests/test_pools.py` and `tests/test_allocation_correctness.py` (pool and allocation rules, D-32), `tests/test_deployment.py` (deployment-related checks; read its own docstrings before relying on what it covers).
- Note: `tests/__pycache__/` is present locally and ignored.

**`legacy/`:**
- Purpose: archived earlier version of the scorer. Reference only; nothing imports it.
- Contains: `legacy/hunter_local_scoring.py` (tracked), `legacy/tracked_jobs.local-scoring.csv` (gitignored by `legacy/*.csv`).
- Do not add imports from `legacy/` into production modules.

**`state/` (local only, gitignored):**
- Purpose: local CSV fallback when `GOOGLE_SHEET_ID` is unset (`hunter.CsvStore`) and the last-known-good inventory cache (`state/inventory`, the default for `--inventory-cache`).
- Contains: `boards.csv`, `events.csv`, `runs.csv`, `discovery.csv`, `inventory.csv`, plus `lock.json` for the local writer lease.
- Generated: yes, by local runs. Committed: no (the `.gitignore` says CI force-adds it only when Sheets is not configured; the workflows here do not).

**`.github/workflows/`:**
- Purpose: the three scheduled and manual entry points.
- Contains: `job_hunter.yml` (hourly poll, `cron: "17 * * * *"`, `timeout-minutes: 25`, `concurrency: job-hunter-state`), `inventory.yml` (weekly refresh Monday 05:23 UTC plus daily validate-only at 06:41 UTC), `watchdog.yml` (every 15 minutes at :07, :22, :37, :52).
- These workflows are read-only toward the repository (`permissions: contents: read`); state lives in the Sheet.

**`.planning/`:**
- Purpose: GSD project-management artifacts for the work on this repo. Not read by the application.
- Contains: `PROJECT.md`, `ROADMAP.md`, `STATE.md`, `quick/<id>-<slug>/` task folders (for example `quick/261014-olj-board-slot-allocation/` with `TASK.md`, `PLAN.md`, `SUMMARY.md`), and `codebase/` (these generated maps).
- Generated: `codebase/` is generated by the mapper; the other files are authored.

**`.venv/`:** local virtual environment. Ignored. Do not add source here.

**Root documentation (authoritative order, from AGENTS.md):**
- `SPEC.md`: the contract. Change behavior only after changing or flagging it here.
- `DECISIONS.md`: the decision log, one `## D-NN <title>` heading per decision.
- `STATUS.md`: what is verified (mocked vs live), what is blocked, and known gaps.
- `README.md`, `DEPLOY.md`, `PILOT_LOG.md`, `NOTICE.md`: setup, deployment steps, pilot log, data-source licences.

## Key File Locations

**Entry Points:**
- `hunter.py`: the poller, inventory, reports and single-job check. Run with `python hunter.py [flags]`. `main()` near the end of the file.
- `watchdog.py`: `python watchdog.py [--dry-run] [--warn-hours N]`.
- `inventory` mode is in `hunter.py` (`run_inventory`), not a separate file.

**Configuration:**
- `requirements.txt`: runtime dependencies (gspread, google-auth, requests, as pinned in the workflows).
- `hunter.py` (`Config`, `Settings`, `DEFAULT_SETTINGS`): the Settings keys and defaults. Settings live in the Sheet `Settings` tab, not in files.
- `.github/workflows/*.yml`: schedules, timeouts, concurrency group, and the `ALLOW_SMARTRECRUITERS_BULK=1` decision (D-38).
- `.env`: local environment variables. Not read and not documented here (AGENTS rule 6).

**Core Logic:**
- `pipeline.py` (`run_cycle`): orchestration of the hourly run.
- `boards.py` (`fetch_board`, `poll_boards`, `apply_poll_result`, `activate_waiting`): board polling and promotion.
- `inventory.py` (`admit_boards`, `run_validation`, `import_inventories`): admission and validation.
- `pools.py` (`sync_pools`, `plan_rebalance`, `apply_plan`, `early_releases`): pool policy.
- `ledger.py` (`replay`, `observe_new`, `needs_evaluation`, `needs_alert`): ledger semantics.
- `freshness.py` (`classify`, `parse_instant`): freshness classes.
- `eligibility.py` (`title_gate`, `hard_gate_coded`): deterministic filters.
- `discovery.py` and `search.py`: Tavily rotation, budget, and client.
- `hunter.py` (`make_evaluator`, `GroqClient`, `hydrate_posting` and the `_hydrate_*` functions, `send_alert`, `JobRow`): scoring, hydration, delivery.
- `state.py` (`SheetState`, `CsvState`, `RunRecord`, `Lease`): persistence.

**Reporting:**
- `reporting.py` (`build_summary`, `headline`, `reconcile`): operational numbers.
- `dashboard.py` (`render`, `refresh`, `publish_sheet`): the Dashboard tab.
- `pilot.py`: `--pilot-report`.
- `storage_report.py`: `--storage-report`.

**Testing:**
- `tests/test_*.py`: as listed above. Run all with `python -m unittest discover -s tests` from the repository root.

## Naming Conventions

**Files:**
- Modules: lowercase single words, `snake_case` only if needed: `pipeline.py`, `inventory.py`, `reporting.py`. No package prefixes.
- Tests: `test_<module or concern>.py`, for example `test_pools.py`, `test_pilot_corrections.py`.
- Workflows: `snake_case.yml` under `.github/workflows/`, named after their function (`job_hunter.yml`).
- Planning artifacts: `<yymmdd>-<3 letters>-<slug>/` for quick tasks (`261014-olj-board-slot-allocation`).

**Functions and variables:**
- `snake_case` throughout. Private helpers start with an underscore (`_hydrate_greenhouse`, `_parse_stamp`, `_day`).
- Pure, testable helpers take injected callables (`fetch`, `title_gate`, `sleep`, `now`) with defaults (`fetch: Callable = bd.fetch_board`).

**Classes:**
- `PascalCase` dataclasses for records and configuration: `BoardRecord`, `BoardId`, `JobIdentity`, `ListedJob`, `Deps`, `EvalOutcome`, `RunRecord`, `PoolPolicy`, `RebalancePlan`.
- Exceptions end in `Error` or describe the stop: `BoardGone`, `BoardRateLimited`, `TransientError`, `FatalRunError`, `RetryableHydration`, `WriterBusy`.

**Constants:**
- `UPPER_SNAKE_CASE` at module top: `STATUS_*` (in `boards.py`), `TRACKER_COLUMNS`, `BOARD_COLUMNS`, `*_TAB`, `*_KEY` (Discovery-tab keys), `DEFAULT_*`.
- Sheet tab names are constants: `TRACKER_TAB = "Job Tracker"` and `SETTINGS_TAB` in `hunter.py`; `BOARDS_TAB`, `EVENTS_TAB`, `RUNS_TAB`, `LOCK_TAB`, `DISCOVERY_TAB`, `INVENTORY_COLUMNS` in `state.py`; `STATE_TAB = "Watchdog"` and `RUNS_TAB` in `watchdog.py`; `DASHBOARD_TAB = "Dashboard"` in `dashboard.py`.

**Identity keys:**
- Job key: `ats|board|id` (lowercase board for case-insensitive providers). Built by `JobIdentity.key` in `boards.py`.
- Board key: provider + region + identifier, built by `BoardId.key` and `_prefix` in `boards.py`.

**Tab and column names (Sheet):**
- Tab names are Title Case with a space where needed: `Job Tracker`, `Settings`, `Boards`, `Events`, `Runs`, `Discovery`, `Lock`, `Inventory`, `Watchdog`, `Dashboard`.
- Column headers are `Underscore_Words` (`Date_Found`, `My_Status`, `Apply_URL`, `Relevant_Jobs`). The program locates tracker columns by header name (D-44). Do not rename a header the program looks up (`Apply_URL`, `My_Status`).

## Where to Add New Code

**New ATS provider:**
- Identity parsing: `boards.py` (`parse_job_url`, `parse_board_url`, `_prefix`, `ATS_LIST`, `LIST_APIS`, `CASE_SENSITIVE_ATS` if casing matters).
- Listing adapter and parser: `boards.py` (`fetch_board`, a `parse_<ats>` function, add to `LIST_APIS`).
- Posting hydration: `hunter.py` (`_hydrate_<ats>` next to `_hydrate_greenhouse` and friends, dispatched in `_hydrate` / `hydrate_posting`).
- Inventory source (if any): `inventory.py` (`parse_*`, `load_source`), and `SUPPORTED_ATS`.
- Tests: `tests/test_core.py` or `tests/test_inventory.py` (parser tests with recorded fixture payloads, no live calls).
- Decision: any provider change must be recorded in `DECISIONS.md` and `SPEC.md` (AGENTS rule 1).

**New pipeline stage or step in `run_cycle`:**
- Implementation: `pipeline.py`, inside the stage it belongs to, with its own `run.*` counter in `state.RunRecord` (`RUN_COLUMNS` in `state.py`) and its own `Deps` callable if it touches external I/O.
- Respect the ordering rules: observations before registry, tracker before events, cursor after saves.
- Tests: `tests/test_core.py` (behavior through `run_cycle` with fakes).

**New pool rule or evidence column:**
- Pool logic: `pools.py`. Board columns: `state.py` (`BOARD_COLUMNS`, `board_to_row`, `board_from_row`). Activity and relevance: `pools.refresh_relevance` / `refresh_activity`.
- Tests: `tests/test_pools.py` and `tests/test_allocation_correctness.py`.
- A change to thresholds or the graduation floor changes SPEC.md "Weekly rebalance" and needs a DECISIONS.md entry (for example D-45).

**New freshness or eligibility rule:**
- Freshness: `freshness.py` (`classify`). Title and hard gates: `eligibility.py`.
- Each change to a filter order or class needs SPEC.md "Freshness vocabulary" or "Filtering order" updated in the same change.
- Tests: `tests/test_core.py`, `tests/test_hunter.py`.

**New Sheet tab:**
- Add the tab name constant and its columns in `state.py` (for hidden operational state) or `hunter.py` (for visible tabs). Register it in `SheetState.ensure` (state.py ~255-275) or `SheetStore.bootstrap` (hunter.py ~1200-1240).
- Add the CSV equivalent in `CsvState` so local runs keep working.
- Reading it must not affect polling, admission, scoring or alerts unless the SPEC says so. A generated output tab follows the `Dashboard` pattern: read by nothing in the pipeline.

**New report or dashboard metric:**
- Computation: `reporting.py` (pure: add a field to `build_summary`, no I/O, no clock). Keep `periods` as the only time source.
- Presentation: `dashboard.py` (`render`), and `pilot.py` for the pilot report.
- Tests: `tests/test_reporting.py`, `tests/test_pilot.py`.

**New CLI flag:**
- Parser and dispatch: `hunter.main` (`argparse` block near line ~1820; dispatch before `pl.Deps` construction). A read-only command must not take `writer_lease`; a writing one must.
- Workflow input: add to `.github/workflows/job_hunter.yml` `workflow_dispatch.inputs` and the step's conditional.

**New scheduled job:**
- A new workflow file under `.github/workflows/`, with its own concurrency group only if it writes nothing shared. Writers must join `job-hunter-state` (SPEC "Board registry", serialization).

**Utilities and shared helpers:**
- Timestamp and freshness helpers: `freshness.py`.
- Board and identity helpers: `boards.py`.
- Counters: `meter.py` (`METER`).
- There is no general `utils.py`. Add a helper to the module that owns its concept; do not create a catch-all.

**Tests:**
- Offline only. No real Sheets, Groq, Tavily or Telegram calls. Use fakes for `store`, `evaluate`, `send_alert`, `fetch`, `discover` (see `pipeline.Deps`) and a no-op `sleep`.
- Name new files `tests/test_<concern>.py`. The discovery command is `python -m unittest discover -s tests`.

## Special Directories

**`state/`:**
- Purpose: local CSV fallback state and inventory cache.
- Generated: yes (by `CsvStore`, and by `--import-inventory` with the default cache).
- Committed: no (gitignored). Never edit by hand in a production context.

**`.planning/codebase/`:**
- Purpose: these generated maps, read by GSD planning commands.
- Generated: yes (by `/gsd-map-codebase`).
- Committed: yes when the orchestrator commits.

**`legacy/`:**
- Purpose: archived earlier scorer and its scratch output.
- Generated: no.
- Committed: the `.py` file yes; `legacy/*.csv` no (gitignored).

**`__pycache__/` and `tests/__pycache__/`:**
- Purpose: Python bytecode.
- Generated: yes. Committed: no.

**`.venv/`:**
- Purpose: local virtual environment.
- Generated: yes. Committed: no.

---

*Structure analysis: 2026-10-24*
