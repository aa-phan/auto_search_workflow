<!-- refreshed: 2026-10-14 -->
# Architecture

**Analysis Date:** 2026-10-14

## System Overview

```text
┌──────────────────────────────────────────────────────────────────────┐
│  Trigger: GitHub Actions `.github/workflows/job_hunter.yml` (cron) │
│           or manual `python hunter.py [--url ... --dry-run --no-tbs]` │
└───────────────────────────────┬──────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  `hunter.py :: main()`  (single-module pipeline orchestrator)        │
│   Config.from_env → make_store → Settings.from_values → build_queries│
└──────┬───────────────────┬──────────────────┬────────────────┬───────┘
       ▼                   ▼                  ▼                ▼
 ┌───────────┐     ┌────────────────┐  ┌─────────────┐  ┌─────────────────┐
 │ Discovery │     │ Hydration      │  │ Scoring     │  │ Persistence /   │
 │ search_ats│────▶│ hydrate_posting│─▶│ GroqClient  │─▶│ Alerts          │
 │ (Serper)  │     │ per-ATS fetch  │  │ .evaluate   │  │ SheetStore or   │
 └───────────┘     └────────────────┘  └─────────────┘  │ CsvStore;       │
                                                       │ send_alert      │
                                                       └─────────────────┘
        External: Serper API · ATS JSON APIs / job pages · Groq chat API ·
                  Google Sheets (gspread) · Telegram Bot API · optional webhook
```

Data stores are the Google Sheet (primary, when `GOOGLE_SHEET_ID` is set) or the local CSVs `tracked_jobs.csv` and `seen_archive.csv` (fallback). Everything lives in `hunter.py`; no other first-party Python modules exist outside `legacy/`.

## Pattern Overview

**Overall:** Single-process, sequential batch pipeline (ETL-style: extract → transform/score → load) with a thin orchestrator function and pluggable storage via duck typing. No web server, no queue, no database, no concurrency.

**Key Characteristics:**
- One module (`hunter.py`, ~1,437 lines) holds all layers; boundaries are expressed by section banners (`# ---- settings`, `# ---- URLs`, `# ---- search`, `# ---- dates`, `# ---- hydration`, `# ---- Groq scoring`, `# ---- tracker`, `# ---- alerts`, `# ---- pipeline`).
- Configuration is data-driven: the Google Sheet `Settings` tab is the user-facing control panel; secrets come from environment variables (GitHub Secrets in CI, `.env` locally via `python-dotenv`).
- Pure functions are favored for transformation logic (`normalize_url`, `classify_url`, `build_queries`, `parse_posted`, `parse_evaluation`, `build_messages`, `is_visible`), which is what `tests/test_hunter.py` exercises offline.
- Failure isolation per job: each job is processed inside `try/except`; errors become `STATUS_ERROR` rows, transient failures return `None` so the job is retried next run without being recorded.
- Append-only persistence: the script never rewrites user-editable columns (`My_Status`, `User_Notes`); it only appends to `Job Tracker` and `Seen_Archive`.
- Idempotence via dedupe: `seen_urls()` pulls every previously recorded URL (tracker column I + archive column C) and `pending_refs()` filters against it before any network fetch.

## Layers

**Configuration layer:**
- Purpose: Build runtime config from environment and the Settings sheet.
- Location: `hunter.py` lines ~104-232 (`DEFAULT_SETTINGS`, `Settings`, `Config`, `excluded_title_regex`).
- Contains: frozen dataclasses `Settings` and `Config`; `Config.from_env()` reads `SERPER_API_KEY`, `GROQ_API_KEY`, `GROQ_MODEL`, `GOOGLE_SHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON`, `TELEGRAM_*`, `ALERT_WEBHOOK_URL`, `MAX_JOBS_PER_RUN`, `SEARCH_TBS`, etc.
- Depends on: `os.environ`, `DEFAULT_SETTINGS` constants.
- Used by: `main()` and every layer below it.
- Precedence rule (`Settings.from_values`): Sheet value > env var of same upper-cased name > built-in default.

**URL classification layer:**
- Purpose: Normalize URLs and decide which ones are individual job postings on supported ATS hosts.
- Location: `hunter.py` lines ~236-296 (`AtsRef`, `normalize_url`, `dedupe_key`, `classify_url`, regexes `_GH_PATH`, `_UUID_PATH`, `_WORKABLE_PATH`, `_SMARTRECRUITERS_PATH`).
- Contains: `AtsRef` (frozen dataclass: `ats`, `url`, `company`, `job_id`, `hint_title`, `hint_date`).
- Depends on: `urllib.parse`.
- Used by: `pending_refs()`, `hydrate_posting()`.

**Discovery layer (search):**
- Purpose: Turn Settings into Google-style Serper queries and fetch candidate URLs.
- Location: `hunter.py` lines ~301-410 (`build_queries`, `search_ats`, `SearchHit`).
- Contains: query builder that enforces a 30-word budget (`GOOGLE_QUERY_WORD_LIMIT`), splits roles across up to `MAX_QUERIES = 4` queries, and falls back to dropping location terms when needed.
- Depends on: `requests` (POST to `SERPER_URL`), `Config.search_tbs`, `Config.search_pages`.
- Used by: `main()`.

**Date layer:**
- Purpose: Best-effort parsing of publication dates from heterogeneous sources and age computation.
- Location: `hunter.py` lines ~416-458 (`parse_posted`, `_posted_iso`, `job_age_days`).
- Accepts epoch seconds/ms, ISO-8601, `"Sep 3, 2026"`, and relative strings like `"3 days ago"`.

**Hydration layer (ATS adapters):**
- Purpose: Fetch the full posting text and metadata for one `AtsRef`.
- Location: `hunter.py` lines ~461-740. One function per ATS, dispatched by `_hydrate()`:
  - `_hydrate_greenhouse` (public boards API), `_hydrate_lever` (postings API), `_hydrate_ashby` path via `_hydrate_ashby_api` with page fallback, `_hydrate_workable`, `_hydrate_smartrecruiters`, generic `_hydrate_page` (JSON-LD `JobPosting`, then visible text, then meta description).
- Public entry: `hydrate_posting(ref) -> Posting`, which translates HTTP status into domain exceptions (`ClosedPosting` for 404/410, `TransientError` for timeouts/5xx/429) and enforces `MIN_JD_CHARS = 200`.
- Depends on: `_http_get` (3 attempts with backoff, retries 429/5xx only), `BeautifulSoup`.
- Used by: `process()`.

**Scoring layer (LLM):**
- Purpose: Score a posting 0–100 against the resume using Groq's OpenAI-compatible chat endpoint.
- Location: `hunter.py` lines ~743-957 (`SYSTEM_PROMPT`, `Evaluation`, `parse_evaluation`, `build_messages`, `TokenBudget`, `GroqClient`).
- Depends on: `requests.Session`, `Config.groq_*` models and TPM budgets.
- Behavior: primary model `llama-3.3-70b-versatile`; on 429 it switches to fallback `llama-3.1-8b-instant` for `FALLBACK_HOLD_SECONDS = 90`. Pacing via `LLM_MIN_INTERVAL_SECONDS` and a sliding 60-second `TokenBudget` at 90% of TPM. A bad API key raises `GroqAuthError`, which aborts the whole run (exit code 2).
- Output contract: model must return JSON with `score`, `verdict`, `missing_gaps`; `parse_evaluation` tolerates code fences and surrounding prose.
- Used by: `process()`.

**Storage layer (duck-typed stores):**
- Purpose: Read settings and dedupe set; append tracker and archive rows.
- Location: `hunter.py` lines ~1033-1200.
- Implementations:
  - `SheetStore` (`gspread`): tabs `Settings`, `Job Tracker`, hidden `Seen_Archive`; `bootstrap()` creates missing tabs with defaults, styling, and a status dropdown.
  - `CsvStore`: local fallback to `tracked_jobs.csv` and `seen_archive.csv`; also performs one-time schema migration from legacy column names (`LEGACY` map) and moves low scorers to the archive.
- Interface (implicit, not an ABC): `bootstrap(resume_text)`, `load_settings()`, `seen_urls()`, `append_jobs(rows)`, `append_archive(rows)`, and `sheet_url` attribute. Selected by `make_store(cfg)`.
- Visibility split: `is_visible()` decides whether a row goes to the visible tracker (score ≥ `min(50, Min_Alert_Score)`) or to the archive.

**Alerting layer:**
- Purpose: Notify the user about `To Apply` jobs.
- Location: `hunter.py` lines ~1215-1261 (`send_alert`).
- Channels: Telegram `sendMessage` (HTML parse mode) when token and chat ID are set; generic JSON webhook when `ALERT_WEBHOOK_URL` is set. Both can fire. Only rows with `status == STATUS_APPLY` are alerted.

**Pipeline / orchestration layer:**
- Purpose: Wire all layers and manage batching, flushing and counts.
- Location: `hunter.py` lines ~1264-1437 (`load_resume_file`, `pending_refs`, `process`, `main`).
- `process(settings, groq, ref, excluded) -> JobRow | None` runs per job in this order: hydrate → stale-age gate → excluded-title gate on full title → Groq score → status assignment (`To Apply` / `Stretch / Review` / `Filtered Out`).
- `main()` buffers rows and calls `flush()` every `FLUSH_EVERY = 10` jobs and in a `finally` block. `flush()` writes archive rows first, then tracker rows, then sends alerts, so a failed alert cannot produce duplicate rows on the next run.

## Data Flow

### Primary Request Path (one scheduled run)

1. Load env and `.env` (`load_dotenv()` at import time, `hunter.py` ~L34-39); `main()` builds `Config.from_env()` (`hunter.py` ~L1352).
2. `make_store(cfg)` chooses `SheetStore` or `CsvStore` (`hunter.py` ~L1203); `store.bootstrap(resume_file)` creates missing tabs/files.
3. `Settings.from_values(store.load_settings(), resume_fallback=...)` builds frozen settings (`hunter.py` ~L1362). Startup aborts with exit 2 if the resume is shorter than 200 characters.
4. `build_queries(settings)` → `search_ats(cfg, queries)` returns `SearchHit`s from Serper (`hunter.py` ~L1368).
5. `store.seen_urls()` builds the dedupe set; `pending_refs()` drops seen, unclassifiable, and title-excluded URLs and caps the list at `MAX_JOBS_PER_RUN` (default 30) (`hunter.py` ~L1369-1377).
6. For each `AtsRef`: `process()` hydrates the posting, applies gates, calls Groq, and returns a `JobRow` (or `None` for retry) (`hunter.py` ~L1292-1338).
7. `pending.append(row)`; every 10 rows `flush()` writes to the store and sends Telegram/webhook alerts (`hunter.py` ~L1385-1404).
8. Summary counts are logged; exit 0 (`hunter.py` ~L1428-1433).

### Manual single-URL path

- `python hunter.py --url <job-url> [--dry-run]` replaces search with `[SearchHit(u) for u in args.url]` and sets `seen = set()`, so the job is always evaluated. `--dry-run` skips all writes and alerts (`flush()` returns early).

### Persistence Data Flow

- CI runs `python hunter.py` with secrets as env vars; the Google Sheet is the single source of truth for settings and tracker state (`.github/workflows/job_hunter.yml`).
- Without `GOOGLE_SHEET_ID`, CI commits `tracked_jobs.csv` back to the repo (`.github/workflows/job_hunter.yml` "Commit CSV backup" step).

**State Management:**
- No in-memory state persists across runs. Per-run state is held in `GroqClient` (`_fallback_until`, `_last_call`, `TokenBudget.events`) and the `pending` buffer in `main()`.
- Durable state is the Sheet's `Job Tracker` and `Seen_Archive` tabs (or the two CSVs).

## Key Abstractions

**`Settings` (frozen dataclass):**
- Purpose: Typed view of the user-editable Settings tab.
- Examples: `hunter.py` ~L147-176.
- Pattern: Factory classmethod `from_values` applies precedence rules; `stale_status` is derived.

**`Config` (frozen dataclass):**
- Purpose: All environment-driven runtime knobs and secrets.
- Examples: `hunter.py` ~L187-232.
- Pattern: `from_env()` classmethod; `dataclasses.replace` is used to override (e.g. `--no-tbs` sets `search_tbs=""`).

**`AtsRef` / `Posting` / `JobRow` / `Evaluation` / `SearchHit` (frozen dataclasses):**
- Purpose: Immutable value objects passed between layers. `AtsRef` = a classified URL; `Posting` = hydrated job; `Evaluation` = LLM output; `JobRow` = one tracker/archive row with `cells()` and `archive_cells()` serializers.
- Examples: `hunter.py` ~L238-244, ~L472-487, ~L791-795, ~L360-367, ~L962-1005.

**Exception taxonomy (control flow):**
- `ClosedPosting`, `TransientError`, `GroqAuthError`, plus standard `ValueError` for permanent per-job failures.
- Pattern: exceptions are mapped at layer boundaries (`hydrate_posting`, `GroqClient.evaluate`) so `process()` can choose between "record as closed", "retry next run", "record as error", or "abort run".

**Store duck-typing:**
- `SheetStore` and `CsvStore` implement the same method set without a base class; `main()` only calls the shared methods. Adding a store means implementing the same five members plus `sheet_url`.

**ATS adapter functions:**
- Pattern: one `_hydrate_<ats>(ref) -> Posting` per platform, with a shared `_hydrate` dispatcher. Adding a platform requires: a regex in `classify_url`, an entry in `ATS_SITES`, a `_hydrate_*` function, and a branch in `_hydrate`.

## Entry Points

**CLI script:**
- Location: `hunter.py`, guarded by `if __name__ == "__main__": sys.exit(main())` (~L1436).
- Triggers: `python hunter.py`, with flags `--url` (repeatable), `--dry-run`, `--no-tbs`.
- Responsibilities: full pipeline run; exit 0 on completion, 2 on startup failure or Groq auth failure.

**Scheduled CI job:**
- Location: `.github/workflows/job_hunter.yml`.
- Triggers: cron `0 13-23/2 * * 1-5` (UTC) and `workflow_dispatch`.
- Responsibilities: checkout, Python 3.12, `pip install -r requirements.txt`, run `hunter.py` with secrets, serialize runs via `concurrency: job-hunter`, and optionally commit `tracked_jobs.csv` when the Sheet is not configured.

**Test entry:**
- Location: `tests/test_hunter.py`, run with `python -m unittest discover -s tests`. It imports `hunter` via `sys.path.insert` of the repo root; no network or credentials are needed.

## Architectural Constraints

- **Threading:** Single-threaded, fully synchronous. `time.sleep` is used for pacing and backoff (`GroqClient._pace`, `TokenBudget.wait`, `_http_get`). No async, no worker threads.
- **Global state:** Module-level constants (`TRACKER_COLUMNS`, `DEFAULT_SETTINGS`, `SYSTEM_PROMPT`, `ATS_SITES`, `BASE_DIR`, `TRACKER_PATH`, `RESUME_PATH`, `ARCHIVE_PATH`) in `hunter.py`. `load_dotenv()` mutates `os.environ` at import time (`hunter.py` ~L34-39). The only mutable module-level state is none; mutable state is confined to `GroqClient` and `TokenBudget` instances.
- **Circular imports:** None. `hunter.py` imports only third-party packages and the standard library. `legacy/hunter_local_scoring.py` is standalone and not imported by `hunter.py`.
- **Monolith boundary:** All layers live in one file. Layer boundaries are conventions, not enforced by packages or interfaces.
- **Configuration coupling:** `Settings.from_values` falls back to environment variables with the same upper-cased name, so Sheet keys and env vars share a namespace.
- **Prompt-injection posture:** `SYSTEM_PROMPT` instructs the model to treat resume and posting as untrusted data (`hunter.py` ~L780). Sheet formula injection is mitigated by `_safe_cell()` (`hunter.py` ~L1017-1019).
- **Dedupe key is URL-based:** `dedupe_key()` lowercases and strips query/fragment and `/apply` suffixes. Editing a URL in the tracker's `Apply_URL` column changes dedupe behavior.

## Anti-Patterns

### Hand-rolled store interface without a contract

**What happens:** `SheetStore` and `CsvStore` (`hunter.py` ~L1033, ~L1139) share five methods and a `sheet_url` attribute by convention only. `CsvStore.load_settings()` returns `{}` and `CsvStore.sheet_url = ""` to mimic the Sheet.
**Why it's wrong:** Signature drift between the two stores is only caught at runtime, and only if a test covers that path. `tests/test_hunter.py` covers both (`SheetTests`, `CsvTests`), but nothing enforces parity.
**Do this instead:** When adding a storage method, add it to both classes and add a parallel test in `SheetTests` and `CsvTests`. Consider a `typing.Protocol` for `make_store`'s return type.

### Module-level side effects on import

**What happens:** `load_dotenv()` runs when `hunter.py` is imported (`hunter.py` ~L34-39), and `log = logging.getLogger("hunter")` plus path constants are computed at import.
**Why it's wrong:** Importing the module from tests or other tools mutates the process environment. The test file works around this with `mock.patch.dict(os.environ)` (`tests/test_hunter.py` ~L25-30).
**Do this instead:** Keep `load_dotenv()` inside `main()` or behind an explicit call so imports are side-effect free.

### Broad `except Exception` at boundaries

**What happens:** `main()` wraps each `process()` call in `except Exception` (`hunter.py` ~L1413), and `send_alert` callers and `SheetStore` styling swallow exceptions with `log.warning`.
**Why it's wrong:** Intentional for run resilience, but it also hides programming errors in the pipeline; they surface only as `STATUS_ERROR` rows.
**Do this instead:** Keep the per-job isolation, and when adding new code paths make sure a bug produces a logged traceback (`log.exception`, as `main()` already does) rather than a silent row.

### Pipeline-as-procedural `main()`

**What happens:** `main()` (`hunter.py` ~L1344-1433) combines argument parsing, startup, search, dedupe, the per-job loop, batching, and summary logging in ~90 lines with nested closures (`flush`).
**Why it's wrong:** Hard to test the loop directly; the end-to-end behavior is only covered through `EndToEndTwoLayerTests` (`tests/test_hunter.py` ~L342).
**Do this instead:** When extending the pipeline, put new logic in a pure helper (like `pending_refs` or `process`) and keep `main()` as wiring only.

## Error Handling

**Strategy:** Classify failures into retryable vs. permanent at the boundary, record permanent outcomes as rows, and skip retryable ones so they are retried on the next run.

**Patterns:**
- HTTP 404/410 → `ClosedPosting` → row with `STATUS_CLOSED` (archived, never re-fetched).
- Timeouts, connection errors, 5xx, 429 → `TransientError` → `process()` returns `None` → not recorded (`counts["retry"]`).
- Thin or missing description (<200 chars) → `ValueError` → `STATUS_ERROR` row ("Could not read the posting").
- Groq 429 → fallback model, then backoff; Groq 401/403 → `GroqAuthError` aborts run with exit 2.
- Sheet and alert failures → logged, not fatal (`_style`, `_status_dropdown`, `send_alert` call site).

## Cross-Cutting Concerns

**Logging:** Standard library `logging`, logger `hunter`, configured in `main()` at INFO with timestamp format (`hunter.py` ~L1351). Per-job lines are `log.info("  -> %s score=%s | ...")`. No structured logging or log files.

**Validation:** Settings are validated by coercion (`_int_or`, `_split_list`) rather than rejected; startup requires a resume of at least `MIN_JD_CHARS` characters and a non-empty `Target_Roles` (`build_queries` raises). LLM output is validated in `parse_evaluation` (score clamped to 0–100, verdict and gaps truncated to 400 and 600 characters).

**Authentication:** Secrets only from environment variables. Google auth uses a service account via `gspread.service_account_from_dict` (`hunter.py` ~L1041), accepting either raw JSON or a file path (`load_service_account`). Serper uses `X-API-KEY`; Groq uses a Bearer token; Telegram uses the token in the URL path. No user authentication exists; the Sheet's sharing settings are the access control.

---

*Architecture analysis: 2026-10-14*
