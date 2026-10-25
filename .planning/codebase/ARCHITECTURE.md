---
last_mapped_commit: aa1bab2d3c3e37ac119cd898b2e4f42a50f276fe
last_mapped_at: 2026-10-24
---
<!-- refreshed: 2026-10-24 -->

# Architecture

**Analysis Date:** 2026-10-24

## System Overview

```text
 GitHub Actions (cron / dispatch)                 Google Sheet (the only UI + state store)
 ┌──────────────────────────────┐                 ┌────────────────────────────────────────┐
 │ job_hunter.yml  (hourly :17) │───read/write───▶│ Settings  Job Tracker (visible)        │
 │ inventory.yml   (weekly+daily)│                │ Boards Events Runs Discovery Lock      │
 │ watchdog.yml    (every 15m)  │──read Runs────▶│ Inventory Watchdog Dashboard (hidden/  │
 └──────┬───────────────┬───────┘                 │ generated)                             │
        │ python hunter.py       │ python watchdog.py └────────────────────────────────────────┘
        ▼                        ▼                               ▲
 ┌────────────────────────────────────────────┐                 │ Telegram (alerts + watchdog)
 │ hunter.py  entry / wiring / SheetStore      │─────────────────┘
 │   main() -> run_cycle(Deps) or inventory    │
 └──────┬─────────────────────────────────────┘
        ▼
 ┌────────────────────────────────────────────────────────────────────────────┐
 │ pipeline.py  run_cycle: 1 discovery -> 2 poll -> 3 evaluate -> 4 alert      │
 ├────────────┬───────────────┬──────────────┬─────────────┬──────────────────┤
 │ discovery.py│ boards.py     │ freshness.py │ ledger.py   │ eligibility.py   │
 │ search.py   │ (identity,    │ (classes,    │ (Events:    │ (title gate,     │
 │ (Tavily)    │  adapters,    │  timestamps) │  seen/eval/ │  hard gate)      │
 │             │  registry)    │              │  alerted)   │                  │
 ├─────────────┴───────┬───────┴──────────────┴─────────────┴──────────────────┤
 │ inventory.py (admission, validation, imports)  pools.py (evidence, pools,    │
 │                                                rebalance, early release)     │
 ├──────────────────────────────────────────────────────────────────────────────┤
 │ state.py (SheetState / CsvState, RunRecord, lease)   reporting.py (pure)     │
 │ dashboard.py (renders reporting -> Dashboard tab)    storage_report.py, pilot.py │
 └──────────────────────────────────────────────────────────────────────────────┘
        ▼ outbound HTTP (ATS public APIs, Tavily, Groq, Telegram, inventory downloads)
```

Line counts for orientation: `hunter.py` 1981, `reporting.py` 938, `inventory.py` 896, `pools.py` 792, `boards.py` 680, `pipeline.py` 633, `state.py` 615, `dashboard.py` 523, `pilot.py` 426, `search.py` 293, `discovery.py` 320, `watchdog.py` 369, `freshness.py` 174, `ledger.py` 201, `eligibility.py` 125, `storage_report.py` 212, `meter.py` 30.

## Pattern Overview

**Overall:** Batch pipeline with a single orchestrator function (`pipeline.run_cycle`) that is driven by dependency injection (`pipeline.Deps`), backed by an append-only event ledger and a mutable board registry, both stored in one Google Sheet. There is no server, no queue and no database; each GitHub Actions run loads all state, performs bounded work, writes it back, and exits.

**Key Characteristics:**
- **One orchestrator, injected I/O.** `run_cycle(d: Deps)` in `pipeline.py` never imports a network client directly for its boundaries. `hunter.main()` builds `Deps` with concrete callables (`store.append_jobs`, `make_evaluator`, `send_alert`, `make_discovery`, `fetch_board`), and tests pass fakes. This is the seam that keeps tests offline (AGENTS.md rule 8).
- **Storage is swappable behind one interface.** `hunter.make_store()` returns `SheetStore` (Google Sheets via gspread, when `GOOGLE_SHEET_ID` is set) or `CsvStore` (local `state/*.csv`, defaults only). Both expose `.state` (`state.SheetState` or `state.CsvState`) with `load_boards / save_boards / load_events / append_events / load_runs / begin_run / finish_run / load_discovery_state / save_discovery_state / load_inventory`.
- **Separate stage records (AGENTS rule 4, SPEC "State model").** Seen, evaluated and alerted are independent facts on each job's ledger key. `ledger.replay()` folds events into `JobState`; `needs_evaluation` and `needs_alert` decide what each later stage still owes, so a failure in one stage never marks another done.
- **Immutable-ish ledger, mutable registry with row ownership.** Events (`Events` tab) are append-only. Boards (`Boards` tab) are rewritten per row, but only rows touched by the current run (`dirty` dict in `run_cycle`) are written back.
- **Identity, not URLs.** `boards.JobIdentity.key` is `ats|board|id`; `boards.BoardId.key` is provider + region + identifier with per-provider casing (`boards.CASE_SENSITIVE_ATS` = Lever, Workable).
- **Serialized writers.** Every writing command takes an advisory writer lease (`state.Lease`, `Lock` tab or `state/lock.json`) through `hunter.writer_lease`; GitHub's concurrency group `job-hunter-state` serializes the workflows (SPEC "Board registry", D-31).
- **Reporting is a pure read-side layer.** `reporting.build_summary` takes Runs, Events, Boards, Discovery and tracker rows and returns a dict, with no clock of its own and no writes. `dashboard.refresh` renders that dict to the Dashboard tab. Nothing in the pipeline reads the Dashboard (SPEC "Operational dashboard").

## Layers

**Entry and wiring (`hunter.py`):**
- Purpose: parse CLI flags, load Config/Settings, pick the store, build `pl.Deps`, dispatch to one of: `run_cycle`, `run_inventory`, `run_pilot_report`, `run_search_usage`, `run_rebalance_report`, `run_dashboard`, `run_delivery_test`, the `--url` single-job check, or `storage_report`.
- Location: `hunter.py` (`main` at line ~1812; `Config.from_env` at ~309; `Settings.from_values` at ~215).
- Contains: `SheetStore` (~1176), `CsvStore` (~1358), `make_store` (~1415), `TRACKER_COLUMNS` (~70), GroqClient (~860), ATS hydrators (`hydrate_posting` ~701), `make_evaluator` (~1500), `send_alert` (~1427), `JobRow` (~996), `writer_lease` (~1620).
- Depends on: every module below.
- Used by: GitHub workflows (`.github/workflows/job_hunter.yml`, `inventory.yml`), local CLI.

**Orchestration (`pipeline.py`):**
- Purpose: the hourly run. `run_cycle` (line ~158) is the only place that sequences the four loops and decides what is written when.
- Contains: `Deps` (~84), `DiscoveryContext` (~58), `EvalOutcome` (~70), `discovery_due` (~126), `degraded_reason` (~138), exceptions `FatalRunError`, `RetryableHydration`.
- Depends on: `boards`, `inventory`, `pools`, `ledger`, `freshness`, `discovery`, `search`, `state`, `meter` (`METER`).
- Used by: `hunter.main`, tests (`tests/test_core.py`, `tests/test_pools.py`, `tests/test_allocation_correctness.py`).

**Board domain (`boards.py`):**
- Purpose: everything about a board as an entity, except its pool policy: identity parsing (`parse_job_url` ~101, `parse_board_url` ~135), per-ATS listing adapters (`fetch_board` ~327, `parse_greenhouse`, `parse_lever`, `parse_ashby`, `parse_workable`, `parse_smartrecruiters`), the `BoardRecord` dataclass (~394), provenance merging (`add_provenance` ~447, `merge_candidates` ~461), waiting-queue ordering (`admission_order` ~562, `activate_waiting` ~572), polling (`poll_boards` ~618, `apply_poll_result` ~654).
- Status constants: `candidate`, `validated`, `new`, `active`, `invalid`, `deferred`, `disabled` (`boards.py` ~380). `MONITORED = {new, active}`.
- Errors: `BoardGone` (404/410), `BoardError`, `BoardRateLimited` (429, with `Retry-After`).

**Inventory and admission (`inventory.py`):**
- Purpose: seed the registry from two public lists, validate boards through the ATS adapters, and provide the single admission path used by imports, search results and manual seeds.
- Key functions: `import_inventories` (~813), `load_source` (~297), `parse_open_ats_feed` (~144), `parse_ats_scrapers_csv` (~172), `overlap_report` (~316), `policy_blocks` (~348, SmartRecruiters parking), `validate_board` (~385), `apply_validation` (~422), `validation_due` (~459), `run_validation` (~619, two queues with separate budgets), `admit_boards` (~738), `HostLimiter` (~354, per-host spacing).
- Cache: `InventoryCache` (~73) keeps last-known-good downloads; `SHRINK_GUARD = 0.5` rejects a download with under half the cached rows.

**Freshness and eligibility (`freshness.py`, `eligibility.py`):**
- `freshness.py`: `parse_instant` (~44) returns `(datetime, precision)`; `classify` (~112) assigns one of `verified_fresh | observed_new | recent | uncertain | stale | baseline`; `detect_changes` (~165) distinguishes updates and republications. `ALERTABLE = {verified_fresh}` (line 29).
- `eligibility.py`: `title_gate` (~69) is the cheap keyword gate (roles, levels, excluded words; space/hyphen interchangeable); `hard_gate_coded` (~106) returns `(stage, reason)` for location, experience (`min_years_required` ~88) and language; `hard_gate` (~122) is the uncoded form.

**Ledger (`ledger.py`):**
- Purpose: the append-only Events model and its replay into per-job state.
- Event kinds (lines 18-19): `SEEN`, `EVALUATED`, `ALERTED`, `ERROR`, `ABANDONED`, `UPDATED`, `REPUBLISHED`. Dispositions: `PENDING`, `BASELINED`, `FILTERED`, `STALED`. Stages for retry accounting: `STAGE_EVALUATE`, `STAGE_ALERT`.
- Key functions: `observe_new` (~153, creates the `seen` event with class and evidence), `observe_known` (~181), `replay` (~78), `needs_evaluation` (~103), `needs_alert` (~107), `failure_events` (~194, bounded at 5 attempts for permanent-looking failures).

**Pool policy and evidence (`pools.py`):**
- Purpose: turn listing evidence into pool decisions. `refresh_relevance` (~132), `refresh_activity` (~183, new-posting counts from `ActivityIndex` ~80), `PoolPolicy` (~224), `sync_pools` (~325, every run), `plan_rebalance` (~410, weekly), `apply_plan` (~560), `early_releases` (~599, D-47 between cycles), `apply_releases` (~609), `coverage` (~652), `rebalance_due` (~627).
- Transitions are made only inside `run_cycle` (D-28). The rebalance plan is recorded to the `Discovery` tab under `rebalance` and `rebalance_report`.

**Discovery (`discovery.py`, `search.py`):**
- `search.py`: Tavily client. `request_body` (~79) builds `query = "<role> job"`, `include_domains=[host]`, `start_date`; `search` (~109) performs one request; `account_usage` (~145) reads the free usage endpoint; `SearchBudget` (~214) is the persistent monthly credit ledger (`search_budget` key).
- `discovery.py`: `Slot` (~50) and `make_slots` (~62) form the rotation (sites vary fastest); `RotationState` (~75) is the cursor; `plan_slots` (~109), `advance` (~117), `advance_backfill` (~130); `run_queries` (~196) drives requests and stop conditions; pending-hydration queue via `load_pending` / `dump_pending` (~294-316).
- Wiring: `hunter.make_discovery` (~393) and `rotation_slots` (~367).

**Reporting and presentation (`reporting.py`, `dashboard.py`, `pilot.py`, `storage_report.py`, `watchdog.py`):**
- `reporting.py`: `build_summary` (~270) returns the operational dict; `headline` (~766), `format_text` (~812), `reconcile` (~835). No clock: periods are passed in via `make_periods` (~85).
- `dashboard.py`: `render` (~122) produces a `Grid`; `requests_for` (~435) builds batch-update requests; `publish_sheet` (~473) deletes its own four charts and writes the tab in one batch; `refresh` (~513) is contained and never raises into the run; `publish_csv` (~487) for local output.
- `pilot.py`: pilot measurements (`--pilot-report`), read only.
- `storage_report.py`: sizes the Events ledger (`--storage-report`), read only.
- `watchdog.py`: standalone missed-run monitor. Its module docstring and imports exclude the hunter's modules (SPEC D-42). It reads only `Runs` (`parse_runs` ~81, `evaluate` ~118) and writes only its own `Watchdog` tab (`STATE_TAB`) and Telegram.

**Persistence (`state.py`):**
- `RunRecord` (~68) with `to_row` / `from_row`; `board_to_row` (~172) / `board_from_row` (~193); `Lease` (~232); `SheetState` (~249) and `CsvState` (~465), exposing the same interface. Tab names and column lists at lines 28-44: `BOARD_COLUMNS`, `LOCK_COLUMNS`, `DISCOVERY_COLUMNS`, `INVENTORY_COLUMNS`, `RUN_COLUMNS`.
- `SheetState.ensure` (~255) creates any missing tab and widens headers.

**Metering (`meter.py`):** 30-line counter (`METER`) for Sheets reads/writes/429s, ATS requests and Groq calls, used by `run_cycle` to fill the limits-audit columns in `Runs`.

## Data Flow

### Primary Request Path: the hourly run

Triggered by `.github/workflows/job_hunter.yml` (cron `17 * * * *`, `timeout-minutes: 25`, concurrency group `job-hunter-state`). The workflow's `env` supplies secrets and `ALLOW_SMARTRECRUITERS_BULK=1` (D-38).

1. **Startup** (`hunter.main`, `hunter.py` ~1812): `Config.from_env()`, `make_store(cfg)`, `store.bootstrap(resume)` creates missing tabs, `Settings.from_values(store.load_settings())` reads the `Settings` tab, `resolve_timezone`. A startup failure returns exit code 2. Settings problems become `config_notes`.
2. **Deps assembly** (`hunter.py` ~1900-1960): `make_evaluator` (Groq), `make_discovery` (Tavily, only if `TAVILY_API_KEY`), `title_gate` closure over `Settings`, `send_alert`, `append_tracker`, `pool_policy`, `trigger` from `GITHUB_EVENT_NAME` / `TRIGGER_SOURCE`, `run_kind` (production when `GITHUB_ACTIONS=true`).
3. **Writer lease** (`hunter.writer_lease(store, "poller")`): refuses with exit 3 if another live lease exists.
4. **`pipeline.run_cycle(deps)`** (`pipeline.py` ~158):
   - `ensure()`, `load_boards()`, `load_events()` -> `ledger.replay()` builds `states`, `load_runs()`. A `RunRecord` with `Outcome=started` is written first (`begin_run`), so a killed run stays visible.
   - **Discovery loop (step 1):** if `discovery_due` (12 h since the last discovery run) and `SearchBudget` allows, `d.discover(ctx)` runs `discovery.run_queries`. Returned boards go through `admit` -> `inv.admit_boards`. Returned job IDs are queued for hydration in step 2b. Rotation cursor advances only after boards are saved (rule: "a crash repeats a search, never skips one").
   - **Polling loop (step 2):**
     - `pools.sync_pools` (every run): applies provider policy, clears stale labels.
     - `activate_waiting` promotes validated boards into `exploration` up to `max_monitored_boards` and `max_new_boards_per_run`.
     - `poll_boards(active)` fetches every monitored board concurrently (`workers=8`), with 429 backoff per provider.
     - For each result: `apply_poll_result` updates board health; unseen IDs become `observe_new` events (classes from `freshness.classify` with the board gap); known IDs get `observe_known`. Baseline and re-entry passes set `baselined_at` and start a stint (`pools.start_stint`). A complete listing refreshes relevance (`pools.refresh_relevance`).
     - Weekly rebalance when `rebalance_due`: `plan_rebalance` -> `apply_plan` (only if `Rebalance_Mode=on`), else a report is recorded. Between cycles, `early_releases` / `apply_releases` (D-47) return trials below the graduation floor.
     - Coverage and registry counts are computed for the Runs row.
   - **Search-hydration pass (step 2b):** pending plus new search jobs are title-gated, policy-checked and hydrated with `d.hydrate_listed` (max `MAX_SEARCH_HYDRATIONS = 20`). Closed postings are skipped; `RetryableHydration` goes to the bounded retry queue (`dsc.pending_entry`).
   - **Durability point (rule 1):** `state.append_events(pending_events)`, then `state.save_boards(dirty)`, then `save_discovery_state` (rotation cursor, budget, pending queue, rebalance stamps). Skipped in `--dry-run`.
   - **Evaluate (step 3):** `todo = needs_evaluation` jobs sorted by `lg.priority`, capped at `max_jobs` (default 30). `d.evaluate` (from `make_evaluator`) returns an `EvalOutcome`:
     - `done` -> payload with `freshness`, `source`, `alert`, `run`, and `reject` stage -> `pending_rows` (visible tracker row if score >= 50 and not already tracked) and an `EVALUATED` event.
     - `transient` -> nothing recorded; retried next run without consuming attempts.
     - `failed` -> `failure_events` (bounded retry, abandoned after 5).
     - Writes are flushed every `FLUSH_EVERY = 10` jobs. Tracker rows are written before events (rule 2).
   - **Alert (step 4):** every state where `needs_alert` is true (verified_fresh, To Apply, evaluated, not yet alerted) calls `d.send_alert`. Late deliveries are labelled. Telegram errors are retried without consuming attempts; 4xx (except 429) is bounded. An `ALERTED` event is written immediately after each success.
   - **Finalize** (`finally` block): final `write()`, timing and METER counters, `outcome` = `failed` on exception, `degraded` by `degraded_reason`, else `ok`. `finish_run` completes the start record in place.
5. **Dashboard refresh** (`hunter.py`, after `run_cycle` returns, skipped in dry run): `dashboard.refresh(store, settings)`, contained.
6. Exit 0 (or 2 on `FatalRunError`, 3 when the lease is busy, 4 when a local run would write to a production Sheet without `ALLOW_LOCAL_SHEET_WRITES=1`).

### Inventory path (`inventory.yml`, separate workflow, same `job-hunter-state` group)

1. `hunter.main` with `--import-inventory` and/or `--validate` takes `writer_lease(store, "inventory")` and calls `run_inventory` (`hunter.py` ~1651).
2. `inventory.import_inventories` (~813): for each source, `load_source` downloads through `http_get_bytes` (~99) into `InventoryCache`. A bad download keeps the last-known-good copy. Parsed `Candidate`s are de-duplicated (`_dedupe` ~200), overlap is reported (`overlap_report` ~316), then `inventory.admit_boards` (~738) runs the shared admission steps: identifier sanity, `merge_candidates` (provenance only for existing boards), `policy_blocks`, inline validation bounded by `max_inline_validations`.
3. `inventory.run_validation` (~619): parks disallowed providers, then merges two queues by strict alternation. Candidate queue uses `--max-validations` (default 500); re-check queue (validated every 7 days, invalid every 30 days, oldest first) uses `--max-revalidations` (default 500). Each call goes through `validate_board` -> `bd.fetch_board` with `HostLimiter` spacing. Results go through `apply_validation`. Flip statistics are saved under `revalidation_stats` in `Discovery`.
4. Saves go through `state.save_boards`, but the importer skips any row whose current status is `POLLER_OWNED` (`new`, `active`, `disabled`) and merges its provenance instead (D-31, best effort).
5. The inventory run never scores or alerts, and never promotes boards to monitoring. Promotion is only done by `boards.activate_waiting` inside `run_cycle`.

### Watchdog path (`watchdog.yml`, every 15 minutes at :07,:22,:37,:52)

1. `watchdog.main` reads `Runs` only (`SheetStore` ~282 inside `watchdog.py`).
2. `evaluate` (~118) classifies the last successful production run (`ok` or `degraded`) as healthy, running, or outage (`failed`, `stalled`, `absent`), or `unavailable` (exit 3).
3. `step` (~191) saves the incident to its own `Watchdog` tab before sending, then sends one outage and one recovery message via Telegram (`telegram_notifier` ~323). It does not take the writer lease and does not write the hunter's tabs.

### Reporting path (read-only)

`hunter.py --pilot-report`, `--rebalance-report`, `--storage-report`, `--search-usage`, `--dashboard` each load state through the same stores and print or publish. `reporting.build_summary` is called by `dashboard.build` (~498) and by `pilot.py`.

### State Management

- **Durable state** lives in the Sheet tabs (listed below). In CSV mode it lives in `state/*.csv` (`boards.csv`, `events.csv`, `runs.csv`, `discovery.csv`, `inventory.csv`), which is the only persistence used when `GOOGLE_SHEET_ID` is unset.
- **In-memory per run:** `boards` (registry dict), `states` (ledger replay), `dirty` (changed boards), `pending_events`, `pending_rows`, `discovery_state` (a dict of JSON strings keyed by `Discovery` key).
- **Ordering rules:** observations are durable before the registry says `baselined` (`run_cycle` step "Rule 1"). Tracker rows are written before the events that describe them (`write()`, rule 2). Rotation cursor moves after the boards it found are saved.

## Sheet Tabs (what each one holds)

| Tab | Visibility | Written by | Read by | Contents |
|---|---|---|---|---|
| `Job Tracker` | visible | `hunter.SheetStore.append_jobs` (pipeline evaluate step) | user; `tracked_keys` on startup; reporting feedback | One row per visible job (score >= 50). Columns from `TRACKER_COLUMNS` (`hunter.py` ~70). Located by header name (D-44); refuses writes if `Apply_URL` header is missing (D-46). User-owned: `My_Status`, `User_Notes`, `My_Feedback`. |
| `Settings` | visible | user (created with defaults by `bootstrap`) | `Settings.from_values` on every run | Keyword lists, thresholds, pool sizes, `Rebalance_Mode`, time zone, search budget. Defaults are written by `bootstrap` only when the tab is first created. |
| `Boards` | hidden | `save_boards` (poller and importer) | `load_boards` | One row per board: identity, status, provenance, validation, pool state, evidence columns, `Outages`. |
| `Events` | hidden | `append_events` (`pipeline.run_cycle`) | `load_events` -> `ledger.replay` | Append-only ledger: `seen`, `evaluated`, `alerted`, `error`, `abandoned`, `updated`, `republished`. Detail JSON includes `run` and `reject`. |
| `Runs` | hidden | `begin_run` / `finish_run` (run start and completion, same `Run_ID`) | `load_runs` (gap, discovery due, watchdog, reports) | One row per run: outcome, counters, timings, METER counts, pool membership, `Notes`. |
| `Discovery` | hidden | `save_discovery_state` | `load_discovery_state` | Key/value rows: `rotation`, `search_budget`, `pending` retry queue, `last_run`, `backfill_cursor`, `rebalance`, `rebalance_report`, `revalidation_stats`. |
| `Lock` | hidden | `Lease` acquire/release | `writer_lease` | One row: the advisory writer lease (`Holder`, `Label`, `Acquired_At`, `Expires_At`). |
| `Inventory` | hidden | `save_inventory` | `load_inventory` | Per-source fetch record: `Fetched_At`, `SHA256`, `Rows`, `Status`. |
| `Watchdog` | hidden | `watchdog.SheetStore` | `watchdog.step` | Incident state and `last_checked_at`. Never read by the hunter. |
| `Dashboard` | visible, generated | `dashboard.publish_sheet` after each run | nothing in the pipeline | Status cards, four charts, one table, system lines, and a hidden data block (columns K:U). Output only. |

## Key Abstractions

**`pipeline.Deps`:**
- Purpose: the complete set of collaborators for one run (store, evaluator, alert sender, discovery, title gate, clock, budgets, policies).
- Location: `pipeline.py` ~84.
- Pattern: plain dataclass of callables and settings; tests construct it with fakes. `dry_run` and `run_kind` are fields here, not globals.

**`boards.BoardRecord` and `boards.BoardId`:**
- Purpose: the registry row and its identity.
- Location: `boards.py` ~394 and ~57.
- Pattern: dataclass with `key` (board key) and `status`. Casing is applied by `_prefix` (~50) and `CASE_SENSITIVE_ATS`.

**`boards.JobIdentity` and `ListedJob`:**
- Purpose: one posting from a listing (`ListedJob`, ~163) and its identity (`JobIdentity`, ~69).
- Pattern: `JobIdentity.key` = `ats|board|id`. Never a URL (AGENTS rule 3).

**`ledger.Event` and `ledger.JobState`:**
- Purpose: the event row and its replayed per-job view (`seen`, `evaluated`, `alerted`, errors, `last_published`, `freshness`, `seen_detail`).
- Location: `ledger.py` ~36 and ~62.
- Pattern: events are rows of `[time, key, event, freshness, disposition, published, detail-json]`; `replay` is the only reducer.

**`pipeline.EvalOutcome`:**
- Purpose: the three-way result of evaluating one job (`done`, `transient`, `failed`). This is how AGENTS rule 4 is enforced in code: only `done` records an `EVALUATED` event.
- Location: `pipeline.py` ~70.

**`inventory.AdmissionResult` / `ValidationResult` / `ValidationSummary`:**
- Purpose: report types for the admission and validation paths (`inventory.py` ~724, ~377, ~599).

**`pools.PoolPolicy`, `pools.Decision`, `pools.RebalancePlan`:**
- Purpose: pool configuration (`max_active`, `established_target`, `exploration_target`, `exploration_days`, `graduation floor`, `mode`), one planned action, and the full weekly plan (`pools.py` ~224, ~374, ~383).

**`discovery.Slot`, `RotationState`, `DiscoveryResult`:**
- Purpose: one rotation position (site x role), its persistent cursor, and the outcome of one discovery run (`discovery.py` ~50, ~75, ~165).

**`search.SearchBudget`:**
- Purpose: monthly credit ledger shared by the rotation, manual, and backfill paths. `remaining(scheduled=...)` enforces the reserve for scheduled runs (SPEC "Discovery", budget).

**`state.RunRecord`:**
- Purpose: one `Runs` row, with `run_at`, `run_id`, `outcome` (`started | ok | degraded | failed`), `completed` property, and all counters.
- Location: `state.py` ~68.

**`reporting` periods:**
- `Period` objects from `make_periods` (~85) define Today, 7 days and 30 days. Days are calendar days in the display time zone (SPEC "Operational dashboard").

## Entry Points

**`hunter.py` `main()`:**
- Location: `hunter.py` line ~1812; script guard at the end of the file.
- Triggers: `job_hunter.yml` (hourly, and `workflow_dispatch` with inputs `discover`, `backfill`, `rebalance_report`, `pilot_report`, `storage_report`, `dashboard`, `delivery_test`), `inventory.yml`, local CLI.
- Responsibilities: parse flags; choose inventory mode vs poll mode; enforce local-write refusal; build `Deps`; run; refresh dashboard; set exit code.

**`hunter.run_inventory()`:**
- Location: `hunter.py` ~1651.
- Triggers: `--import-inventory`, `--validate`, `--inventory-report`, `--rebalance-report` (also `--rebalance-report` is read-only).

**`watchdog.main()`:**
- Location: `watchdog.py` ~336.
- Triggers: `watchdog.yml` every 15 minutes; `workflow_dispatch` with `dry_run`.

**`pipeline.run_cycle()`:**
- Location: `pipeline.py` ~158.
- Triggers: called only from `hunter.main` (poll mode).

**`dashboard.refresh()` and `hunter.py --dashboard`:**
- Location: `dashboard.py` ~513.
- Triggers: after every poll run; manual rebuild with `--dashboard` (or the `dashboard` workflow input).

## Architectural Constraints

- **Threading:** `poll_boards` and `run_validation` use `ThreadPoolExecutor` (`workers=8` default; `inventory.py` imports `ThreadPoolExecutor` and a `threading` lock). The pipeline body itself is single-threaded. `HostLimiter` serializes per-host spacing.
- **Global state:** module-level `METER` (`meter.py`) is shared by all stores and clients in a process and is snapshotted per run (`meter0` / `METER.since`). `DEFAULT_TZ` and `TRACKER_COLUMNS` are module constants in `hunter.py`. `log = logging.getLogger("hunter")` is shared by all modules.
- **Circular imports:** none known. Dependency direction is one-way: `hunter` -> `pipeline` -> {`inventory`, `pools`, `boards`, `ledger`, `freshness`, `discovery`, `search`, `state`} -> `boards`/`freshness`/`eligibility` at the leaves. `watchdog.py` and `reporting.py` import only leaf modules (`watchdog` imports none of the hunter's modules, by design, D-42). `dashboard` imports `reporting`.
- **No writes from reporting or dashboard into operational state:** `dashboard.py` writes only its own tab; `reporting.py` writes nothing. Verified by the design, not by a test that enforces it.
- **Sheets has no atomic conditional write:** the writer lease is write-then-verify (SPEC "Board registry", D-31). Two writers started within about 3 seconds could both proceed.
- **Run time budget:** the hunter workflow has `timeout-minutes: 25`; `run_cycle` caps evaluation at `max_jobs` and search hydration at 20 per run. Overruns are visible in `Runs.Duration_S` and in `pilot.py`.
- **Tracker is append-only for the user's columns:** the program writes new rows and never rewrites user columns (SPEC "Delivery").

## Anti-Patterns

### Writing back the whole registry each run

**What happens:** `run_cycle` tracks `dirty` and writes only changed boards through `save_boards`, but several callers pass the full `boards.values()` for activity refresh (the loop that calls `pools.refresh_activity` on every monitored board sets `dirty[b.key] = b` for all of them).
**Why it's wrong here:** the `Boards` tab is the largest rewrite target and Google Sheets write quota is limited (SPEC "Pilot measurements" tracks `Sheets_Writes` and `Sheets_429`). Updating every monitored row every hour grows writes linearly with the pool size (`Max_Active_Boards`, default 500, target 700 per D-45).
**Do this instead:** keep the `dirty` contract: mark a board dirty only when its own fields changed (see `pools.refresh_activity` and `save_boards` in `state.py`). Measure with the limits-audit columns before changing it.

### Evaluating in the discovery step

**What happens:** candidate job URLs from search are hydrated inside step 2b of `run_cycle`, between polling and evaluation.
**Why it's wrong here:** a search-found job can bypass a board's polling state, so its freshness must come from hydration and never from a search date (SPEC "Discovery", candidate retrieval only).
**Do this instead:** keep the hydrator as the only path for search jobs (`make_search_hydrator`), and pass them through `observe_new`, which records `source = search`.

### Conflating transient and permanent failures

**What happens:** `hunter.make_evaluator` returns `pl.EvalOutcome("failed")` for a non-transient exception, and `failure_events` bounds those at 5 attempts. Telegram errors take a different path (`run_cycle` step 4) that does not consume attempts unless the response is a 4xx other than 429.
**Why it's wrong here:** a transient error recorded as a permanent one would drop a job for good (AGENTS rule 4, SPEC "State model").
**Do this instead:** return `EvalOutcome("transient", ...)` for timeouts, 5xx, 429 and quota errors (see `GroqClient` and `TransientError`). Only the `failed` kind counts toward the 5-attempt bound.

## Error Handling

**Strategy:** each stage catches its own failures and records them, so the rest of the run continues. Only `FatalRunError` (for example an invalid Groq key) stops the run. Discovery, dashboard, alerts and the final write are individually contained.

**Patterns:**
- `run_cycle` wraps the whole body in `try/finally`. `finally` always writes pending state, computes outcome from `crashed` and `degraded_reason`, and completes the run record. A failing final write is recorded in `Runs.Notes` and logged.
- Discovery: any exception becomes a note (`discovery failed: ...`) and sets `credit_status = unresolved`; polling still runs (`run_cycle` step 1).
- Board fetch: `BoardGone` -> `invalid`; `BoardRateLimited` -> provider backoff for the rest of the run (`skipped` results); other `BoardError` -> failed poll, counted in `Runs.Boards_Failed`.
- Hydration: `RetryableHydration` -> bounded queue (`MAX_HYDRATION_ATTEMPTS`); `None` -> closed posting, nothing observed.
- Sheets quota: `quota_retrying` (`hunter.py` ~1152) wraps gspread calls with backoff.
- Dashboard: `dashboard.refresh` returns `False` on failure and logs it. It never raises into job processing.

## Cross-Cutting Concerns

**Logging:** standard `logging` with the `hunter` logger; `main` configures `INFO` with a `%(asctime)s %(levelname)s` format. Per-query and per-pool decisions are logged (`run_cycle` logs each pool transition, each rebalance line and each query). No external logging service.

**Validation:** identifier sanity in `inventory._clean_ident` (~139, `IDENT_RE` at ~63); URL and identity parsing in `boards.parse_job_url`; Settings parsing and notes in `hunter.Settings` and `settings_notes` (~283); board completeness in `boards.looks_capped` (~321, `CAP_SIZES`).

**Authentication:** environment variables only (`GROQ_API_KEY`, `TAVILY_API_KEY`, `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_SHEET_ID`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `ALERT_WEBHOOK_URL`), supplied by GitHub Actions secrets. The Google service account is loaded by `hunter.load_service_account` (~1133). Local `.env` is not read by the code paths described here and is not quoted in this document (AGENTS rule 6).

**Time:** all instants are UTC `datetime`s; `lg.stamp` writes `STAMP` (`%Y-%m-%dT%H:%M:%SZ`, `boards.py` line 390). Display conversions use `hunter.resolve_timezone` (default `America/Chicago`, `hunter.py` ~70 area).

**Decision record:** architecture changes are recorded in `DECISIONS.md` (D-01 to D-47). The most architecture-relevant entries are D-02 (new code in separate modules), D-03 (append-only ledger in the Sheet), D-15 and D-28 and D-31 (two writers, pool transitions only by the poller, serialized writers), D-19 and D-20 (one admission path; search results processed twice), D-26 and D-45 (pool model and capacity), D-37 (deployment and lease facts), D-40 to D-42 (dashboard, watchdog), D-44 and D-46 (tracker by header name).

**Operating contract:** `SPEC.md` is the authority for behavior; `AGENTS.md` lists the layout and the ten working rules, including "flag conflicts before changing behavior".

---

*Architecture analysis: 2026-10-24*
