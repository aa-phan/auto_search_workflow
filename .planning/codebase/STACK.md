# Technology Stack

**Analysis Date:** 2026-10-14

## Languages

**Primary:**
- Python 3.12 - All application code: `hunter.py` (single-module CLI, ~1400 lines), `tests/test_hunter.py`. CI pins 3.12 in `.github/workflows/job_hunter.yml`.

**Secondary:**
- YAML - GitHub Actions workflow `.github/workflows/job_hunter.yml` (cron schedule, secrets wiring).
- Markdown - `README.md` (user setup guide, doubles as operator documentation).
- CSV - Local tracker fallback `tracked_jobs.csv`, scored snapshot `tracked_jobs.gemini-scored.csv`.

**Archived (not part of the active app):**
- `legacy/hunter_local_scoring.py` - earlier variant. Differs from the active code: supports Tavily search (`TAVILY_URL = "https://api.tavily.com/search"`, selected when a key starts with `tvly-`) and does not use Groq as the scorer. Its `legacy/tracked_jobs.local-scoring.csv` is a data artifact. Do not treat `legacy/` as the source of truth.

## Runtime

**Environment:**
- CPython 3.12 (CI: `actions/setup-python@v5` with `python-version: "3.12"` on `ubuntu-latest`).
- Local development: a `.venv/` directory exists (git-ignored, not analyzed). No `.python-version`, `runtime.txt`, or `pyproject.toml` present, so the minimum Python version is implied, not declared. The code uses `from __future__ import annotations`, PEP 604 unions (`X | None`) in annotations, and walrus operators, so Python 3.10+ is required in practice.

**Package Manager:**
- pip. Dependencies declared only in `requirements.txt` (floor and ceiling pins, no lockfile).
- Lockfile: missing. No `requirements.lock`, `Pipfile.lock`, `poetry.lock`, or `uv.lock`. CI runs `pip install -r requirements.txt` on every run, so transitive versions float within the declared ranges.

## Frameworks

**Core:**
- None. Plain procedural/OOP Python script. Entry point is `hunter.py` (`python hunter.py`, with flags such as `--dry-run`, `--url`, `--no-tbs`).

**Testing:**
- `unittest` (standard library). Run with `python -m unittest discover -s tests` per the docstring in `tests/test_hunter.py`. Offline only, no network or credentials required. No pytest config present.

**Build/Dev:**
- No build step. No linter/formatter config detected (no `ruff.toml`, `.flake8`, `pyproject.toml`, `.pre-commit-config.yaml`).
- GitHub Actions (`.github/workflows/job_hunter.yml`) - scheduled runner and manual `workflow_dispatch`.

## Key Dependencies

All declared in `requirements.txt`:

**Critical:**
- `requests>=2.32,<3` - Every HTTP call: Serper search (`SERPER_URL`), ATS job-board APIs (hydration), Groq chat completions (`GROQ_URL`), Telegram `sendMessage`, and the generic alert webhook. Used directly in `hunter.py` (lines ~388, 494, 1231, 1244).
- `beautifulsoup4>=4.12,<5` - Parses job-description HTML into plain text for the LLM prompt. Imported as `from bs4 import BeautifulSoup` in `hunter.py`.
- `gspread>=6.0,<7` - Google Sheets client. Used via `gspread.service_account_from_dict(...)` and `open_by_key(...)` in `SheetStore` (`hunter.py` ~line 1038-1041). Holds the Settings tab, Job Tracker tab, and hidden Seen_Archive tab.
- `google-auth>=2.30,<3` - Service-account credential handling. Not imported directly in `hunter.py`; it is the auth backend that `gspread` uses.

**Infrastructure:**
- `python-dotenv>=1.0,<2` - Optional `.env` loading. `hunter.py` calls `load_dotenv()` inside a `try/except ImportError` at import time (lines ~34-38). Local development only; CI supplies env vars directly.
- `pyyaml>=6.0,<7` - Declared but not imported anywhere in `hunter.py` or `tests/test_hunter.py`. Candidate for removal.

**Standard library modules in use (no install needed):** `argparse`, `csv`, `html`, `json`, `logging`, `os`, `re`, `sys`, `time`, `collections.deque`, `dataclasses`, `datetime`, `pathlib`, `typing`, `urllib.parse`, `unittest`, `tempfile`, `unittest.mock`.

## External Services (called over HTTPS)

Documented in detail in `.planning/codebase/INTEGRATIONS.md`. Endpoint constants live in `hunter.py` lines ~85-91:
- `SERPER_URL = "https://google.serper.dev/search"`
- `GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"`
- ATS APIs: `GREENHOUSE_API`, `LEVER_API`, `ASHBY_API`, `WORKABLE_API`, `SMARTRECRUITERS_API`

## Configuration

**Environment variables (names only; values are secrets and are never stored in the repo):**
- Read through `Config.from_env()` in `hunter.py` (~lines 203-232):
  - `SERPER_API_KEY` (fallback `SEARCH_API_KEY`)
  - `GROQ_API_KEY`, `GROQ_MODEL` (default `llama-3.3-70b-versatile`), `GROQ_FALLBACK_MODEL` (default `llama-3.1-8b-instant`), `GROQ_TPM` (default 12000), `GROQ_FALLBACK_TPM` (default 6000), `LLM_MIN_INTERVAL_SECONDS` (default 2.2)
  - `GOOGLE_SHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON` (raw JSON or path to a `.json` file)
  - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
  - `ALERT_WEBHOOK_URL`
  - `MAX_JOBS_PER_RUN` (default 30), `SEARCH_PAGES` (default 2), `SERPER_NUM` (default 0), `SEARCH_TBS` (default `qdr:d3`; `none` disables the date filter)
- Sheet-level settings (take precedence over env vars of the same upper-cased name, then built-in defaults): `Resume_Text`, `Target_Roles`, `Target_Levels`, `Excluded_Title_Words`, `Target_Locations`, `Min_Alert_Score` (default 70), `Max_Job_Age_Days` (default 14). Resolved in `Settings.from_values` (`hunter.py` ~lines 157-170).
- Local fallback files: `tracked_jobs.csv` (`TRACKER_PATH`), `resume.txt` (`RESUME_PATH`), both relative to `BASE_DIR`.
- A `.env` file exists at the repo root for local runs. It is git-ignored and was not read for this analysis.

**Build/Dev config:**
- `.gitignore` - excludes local secrets and generated files.
- No `Dockerfile`, `Makefile`, `docker-compose.yml`, or `pyproject.toml`.

## Platform Requirements

**Development:**
- Python 3.10+ (3.12 recommended to match CI).
- `pip install -r requirements.txt`, then `python hunter.py --dry-run --url <posting>` to test one job without writing.
- Offline tests: `python -m unittest discover -s tests`.

**Production:**
- GitHub Actions, `ubuntu-latest`, 30-minute job timeout. Schedule: `cron: "0 13-23/2 * * 1-5"` (every 2 hours, 13:00-23:00 UTC, Mon-Fri). Concurrency group `job-hunter`, `cancel-in-progress: false`.
- Requires `contents: write` permission, used only by the CSV-backup commit step that runs when `GOOGLE_SHEET_ID` is unset.

---

*Stack analysis: 2026-10-14*
