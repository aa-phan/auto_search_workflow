# Codebase Structure

**Analysis Date:** 2026-10-14

## Directory Layout

```
auto_search_workflow/
├── hunter.py                          # Entire active application (CLI pipeline, ~1,437 lines)
├── tests/
│   └── test_hunter.py                 # Offline unittest suite for hunter.py (~642 lines)
├── legacy/                            # Archived earlier version, kept for reference (not imported)
│   ├── hunter_local_scoring.py        # Earlier offline/local-scoring variant (~1,292 lines)
│   └── tracked_jobs.local-scoring.csv # Tracker output from the legacy variant
├── .github/
│   └── workflows/
│       └── job_hunter.yml             # Scheduled + manual GitHub Actions run
├── .planning/
│   └── codebase/                      # Generated codebase maps (this document lives here)
├── requirements.txt                   # Runtime dependencies (pinned by major range)
├── README.md                          # User-facing setup and usage guide
├── tracked_jobs.csv                   # Local tracker CSV (CSV fallback mode / CI backup)
├── tracked_jobs.gemini-scored.csv     # Tracker output from an earlier Gemini-scored run
├── .gitignore                         # Ignores secrets, resume files, .venv, __pycache__
├── .env                               # Local secrets (present; never read or committed)
├── resume.txt                         # Personal resume text (gitignored; never read)
├── Resume.pdf                         # Personal resume PDF (gitignored; never read)
└── .DS_Store                          # macOS metadata (ignored)
```

Generated at runtime (not present in the repo snapshot): `seen_archive.csv` (created by `CsvStore.bootstrap`, `hunter.py` ~L1149), `.venv/` and `__pycache__/` (ignored).

## Directory Purposes

**`/` (repository root):**
- Purpose: Holds the single application module, the requirements file, docs, and data/output CSVs.
- Contains: `hunter.py`, `requirements.txt`, `README.md`, CSV tracker files, personal/secret files that are gitignored.
- Key files: `hunter.py`, `requirements.txt`, `README.md`.

**`tests/`:**
- Purpose: Offline unit and integration-style tests for `hunter.py`.
- Contains: `unittest.TestCase` classes grouped by layer: `QueryTests`, `DedupeTests`, `SettingsTests`, `DateExtractionTests`, `HydrationErrorTests`, `ProcessTests`, `EndToEndTwoLayerTests`, `ParseTests`, `GroqTests`, `SheetTests`, `CsvTests`, `ServiceAccountTests`, `AlertTests`.
- Key files: `tests/test_hunter.py`.
- No `__init__.py` is present; tests are run with `python -m unittest discover -s tests`.

**`legacy/`:**
- Purpose: Archived earlier implementation (local scoring, function `score_job_locally`, `update_tracker`) kept for reference only.
- Contains: `hunter_local_scoring.py` (a separate, standalone script with its own `Config`, `search_ats`, `_hydrate_*`) and its CSV output.
- Generated: No. Committed: Yes.
- Do not import from `legacy/` in new code; it shares names with `hunter.py` but diverges in behavior (e.g. `_hydrate_ashby` vs `_hydrate_ashby_api`, `build_query` vs `build_queries`).

**`.github/workflows/`:**
- Purpose: CI automation.
- Contains: `job_hunter.yml` only.

**`.planning/codebase/`:**
- Purpose: Output directory for codebase mapping documents consumed by planning commands.
- Contains: `ARCHITECTURE.md`, `STRUCTURE.md`, and other focus-area documents when generated.

## Key File Locations

**Entry Points:**
- `hunter.py`: CLI entry (`main()`, `if __name__ == "__main__"` at ~L1436).
- `.github/workflows/job_hunter.yml`: scheduled entry (cron `0 13-23/2 * * 1-5`, UTC).

**Configuration:**
- `requirements.txt`: Python dependencies (`requests`, `beautifulsoup4`, `python-dotenv`, `gspread`, `google-auth`, `pyyaml`).
- `hunter.py` lines ~104-232: `DEFAULT_SETTINGS`, `Settings`, `Config`. Runtime settings live in the Google Sheet `Settings` tab, not in files.
- `.env` (local only, gitignored): environment variables for local runs. Do not read.
- `.gitignore`: secret and personal-file exclusions, `.venv/`, `__pycache__/`.

**Core Logic:**
- `hunter.py` lines ~236-296: URL normalization and ATS classification.
- `hunter.py` lines ~301-410: search query building and Serper client.
- `hunter.py` lines ~461-740: per-ATS hydration adapters.
- `hunter.py` lines ~743-957: Groq scoring client and prompt.
- `hunter.py` lines ~959-1210: tracker row model and storage backends.
- `hunter.py` lines ~1212-1261: alerts (Telegram, webhook).
- `hunter.py` lines ~1264-1437: pipeline orchestration.

**Testing:**
- `tests/test_hunter.py`: all automated tests.

**Documentation:**
- `README.md`: setup, Settings tab reference, scoring rubric, operations notes.

## Naming Conventions

**Files:**
- Python modules: `snake_case.py` (`hunter.py`, `hunter_local_scoring.py`).
- Test files: `test_<module>.py` (`test_hunter.py`).
- Data outputs: `tracked_jobs*.csv`, with a variant suffix describing the scoring mode (`.gemini-scored`, `.local-scoring`).
- Root-level docs: `UPPERCASE.md` (`README.md`) and generated maps in `.planning/codebase/` also `UPPERCASE.md`.
- Workflow files: `snake_case.yml` under `.github/workflows/` (`job_hunter.yml`).

**Directories:**
- Lowercase, single word (`tests`, `legacy`, `codebase` under `.planning`).

**Python identifiers (observed in `hunter.py`):**
- Constants: `UPPER_SNAKE_CASE` (`TRACKER_COLUMNS`, `MIN_TRACKER_SCORE`, `ATS_SITES`, `SERPER_URL`, `GROQ_URL`, `STATUS_APPLY`).
- Classes: `PascalCase` (`Settings`, `Config`, `AtsRef`, `Posting`, `JobRow`, `GroqClient`, `SheetStore`, `CsvStore`, `TokenBudget`).
- Exceptions end in `Error` or describe a state: `GroqAuthError`, `TransientError`, `ClosedPosting`.
- Functions: `snake_case`; private helpers prefixed with `_` (`_hydrate_lever`, `_http_get`, `_safe_cell`, `_term`, `_group`).
- Hydrators: `_hydrate_<ats>` for each ATS (`greenhouse`, `lever`, `ashby_api`, `workable`, `smartrecruiters`), generic `_hydrate_page`.
- Regex module constants: leading underscore plus `_PATH` suffix (`_GH_PATH`, `_UUID_PATH`).
- Settings keys in the Sheet: `Title_Case_With_Underscores` (`Target_Roles`, `Min_Alert_Score`). Environment variables: `UPPER_SNAKE_CASE`.
- Tracker columns: `Title_Case_With_Underscores` (`AI_Score`, `Apply_URL`, `My_Status`).

**Status strings:**
- Constants defined once (`STATUS_APPLY = "To Apply"`, `STATUS_STRETCH = "Stretch / Review"`, `STATUS_FILTERED`, `STATUS_CLOSED`, `STATUS_ERROR`). Use the constants, never string literals, when adding statuses.

## Where to Add New Code

**New ATS platform:**
- Add the host to `ATS_SITES` (`hunter.py` ~L76-83) so search includes it.
- Add a path regex and a branch in `classify_url` (`hunter.py` ~L278-295).
- Add `_hydrate_<name>(ref: AtsRef) -> Posting` near the other hydrators (`hunter.py` ~L521-627) and a branch in `_hydrate` (~L694-714).
- Add tests in `tests/test_hunter.py` next to the hydration tests (`HydrationErrorTests`, `DateExtractionTests`).

**New Settings key:**
- Add a tuple to `DEFAULT_SETTINGS` (`hunter.py` ~L107-131), add a field to `Settings` and handling in `Settings.from_values` (`hunter.py` ~L157-172).
- Tests: `SettingsTests` in `tests/test_hunter.py`.
- Document it in the README Settings table.

**New tracker column:**
- Add to `TRACKER_COLUMNS` (`hunter.py` ~L49-60) and update `JobRow.cells()` (~L980-993), and the column widths and header range in `SheetStore.bootstrap` (~L1058-1062). Keep `Apply_URL` at its index (`URL_COLUMN` is derived from it).
- Migrations for existing CSVs belong in `CsvStore.bootstrap` and the `LEGACY` map (~L1144).

**New scoring behavior or prompt change:**
- Prompt: `SYSTEM_PROMPT` (`hunter.py` ~L751-788). Parsing: `parse_evaluation` (~L798-827). Request shape: `GroqClient.evaluate` (~L900-956).
- Tests: `ParseTests` and `GroqTests`.

**New alert channel:**
- Extend `send_alert` (`hunter.py` ~L1215-1261). Keep failures non-fatal at the call site in `flush()`.

**New storage backend:**
- Implement the same methods as `SheetStore`/`CsvStore` (`bootstrap`, `load_settings`, `seen_urls`, `append_jobs`, `append_archive`, `sheet_url`) and extend `make_store` (`hunter.py` ~L1203-1209). Add a test class modeled on `SheetTests`/`CsvTests`.

**New CLI flag:**
- Add to the `argparse` setup in `main()` (`hunter.py` ~L1345-1349) and apply it to `Config` with `dataclasses.replace` as `--no-tbs` does.

**New tests:**
- `tests/test_hunter.py`, adding a `unittest.TestCase` subclass in the matching layer group. Use the helpers `settings()`, `posting()`, `job()`, `groq_ok()`, `days_ago()`, and `FakeSpreadsheet`/`FakeWorksheet`. Tests must stay offline.

**Shared helpers:**
- There is no `utils` module. Pure helpers live in the section where they're used (for example `_split_list`, `_int_or` near `Settings`; `_now`, `_safe_cell` near `JobRow`). If a helper is needed by two sections, move it up near `Settings` rather than creating a new module, unless the file grows enough to justify splitting it.

## Special Directories

**`legacy/`:**
- Purpose: Archived earlier version.
- Generated: No.
- Committed: Yes.
- Note: Excluded from active development; do not add new features here.

**`.planning/`:**
- Purpose: GSD planning artifacts and codebase maps.
- Generated: Yes (by mapping and planning commands).
- Committed: Yes (`.planning/codebase/` documents are intended to be versioned).

**`.venv/` (local, not in repo snapshot):**
- Purpose: Local Python virtualenv per README.
- Generated: Yes. Committed: No (gitignored).

**`__pycache__/` (not in repo snapshot):**
- Purpose: Bytecode cache.
- Generated: Yes. Committed: No (gitignored).

---

*Structure analysis: 2026-10-14*
