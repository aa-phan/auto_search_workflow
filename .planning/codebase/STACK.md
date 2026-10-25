---
last_mapped_commit: aa1bab2d3c3e37ac119cd898b2e4f42a50f276fe
last_mapped_at: 2026-10-24
---
# Technology Stack

**Analysis Date:** 2026-10-24

## Languages

**Primary:**
- Python 3.12 - all live code at the repository root: `hunter.py`, `boards.py`, `inventory.py`, `search.py`, `discovery.py`, `freshness.py`, `ledger.py`, `eligibility.py`, `state.py`, `pools.py`, `pipeline.py`, `reporting.py`, `dashboard.py`, `pilot.py`, `watchdog.py`, `storage_report.py`, `meter.py`
- Tests: `tests/*.py` (stdlib `unittest`, offline)

**Secondary:**
- YAML - GitHub Actions workflows in `.github/workflows/job_hunter.yml`, `.github/workflows/inventory.yml`, `.github/workflows/watchdog.yml`
- Markdown - operator and governance docs: `README.md`, `DEPLOY.md`, `SPEC.md`, `DECISIONS.md`, `STATUS.md`, `PILOT_LOG.md`, `AGENTS.md`

**Not live:**
- `legacy/` - archived earlier version, reference only. It is not mapped here and is not part of the runtime.

## Runtime

**Environment:**
- CPython 3.12 (pinned in every workflow via `actions/setup-python@v5` with `python-version: "3.12"`). Local venv `.venv/` was created from `/opt/homebrew/opt/python@3.12/bin` (Python 3.12.13).
- GitHub-hosted runner: `ubuntu-latest` for all three workflows.

**Package Manager:**
- pip, installed from `requirements.txt` (`pip install -r requirements.txt`). Workflows use `actions/setup-python` with `cache: pip`.
- Watchdog installs only its three packages inline (`gspread`, `google-auth`, `requests`) in `.github/workflows/watchdog.yml`.
- Lockfile: Missing. Dependencies are version-ranged (see below) with no pinned lock or hash file.

## Frameworks

There is no web framework. The app is a batch CLI run by GitHub Actions.

**Core:**
- Standard library orchestration: `argparse`, `csv`, `json`, `logging`, `fcntl` (local lease), `dataclasses`, `datetime`, `tempfile`, `uuid`. Entry point: `hunter.py`.
- `hunter.py` runs poll, discovery, backfill, rebalance, pilot, dashboard, storage-report and delivery-test modes via flags (for example `--discover`, `--backfill`, `--rebalance-report`, `--dashboard`, `--storage-report`, `--delivery-test`).
- `watchdog.py` is a separate, self-contained monitor with no hunter imports (per `STATUS.md` D-42).

**Testing:**
- `unittest` (stdlib). Run with `python -m unittest discover -s tests` (the command required by `AGENTS.md`). `tests/` holds 13 offline test modules. No network or credentials are needed.

**Build/Dev:**
- No build step. No linter or formatter configuration detected (no `pyproject.toml`, `setup.cfg`, `ruff`/`flake8`/`black` config found at root).

## Key Dependencies

Declared in `requirements.txt`:

**Critical:**
- `requests>=2.32,<3` - HTTP client for every ATS adapter, Tavily search, Groq chat, Telegram, GitHub download in inventory, and the watchdog. Used in `boards.py`, `hunter.py`, `search.py`, `inventory.py`, `watchdog.py`.
- `beautifulsoup4>=4.12,<5` - parses job-description HTML during hydration. Imported as `from bs4 import BeautifulSoup` in `hunter.py` (line 33). Its comment in `requirements.txt` says "parses job-description HTML".
- `gspread>=6.0,<7` - Google Sheets client (state, tracker, dashboard, Lock tab). Used in `hunter.py` (around line 1183) and `watchdog.py` (line 286).
- `google-auth>=2.30,<3` - service-account credentials that back gspread. Used indirectly through `gspread.service_account_from_dict`.

**Infrastructure:**
- `python-dotenv>=1.0,<2` - loads a local `.env` through `load_dotenv` in `hunter.py` (line 54/56). Production runs take secrets from GitHub Actions environment, not from a file. Do not read `.env` content.
- `pyyaml>=6.0,<7` - listed in `requirements.txt`, but no `import yaml` was found in the live Python modules. Treat it as a declared but unused dependency unless a later change adds a use.

**Standard library only (no install):** `csv`, `json`, `fcntl`, `logging`, sequential I/O. The app is single-threaded (`time.sleep` for backoff and per-provider spacing, for example `MIN_INTERVAL` in `inventory.py` line 341).

## Configuration

**Environment variables (names only; values are secrets or settings):**

Secrets (GitHub repository secrets, passed into workflow `env:` blocks):
- `GROQ_API_KEY` - Groq LLM scoring
- `TAVILY_API_KEY` - Tavily web-search discovery (optional; skipped with a warning when absent)
- `GOOGLE_SERVICE_ACCOUNT_JSON` - service-account JSON contents for gspread
- `GOOGLE_SHEET_ID` - target Google Sheet identifier
- `TELEGRAM_BOT_TOKEN` - Telegram bot token
- `TELEGRAM_CHAT_ID` - Telegram recipient chat
- `ALERT_WEBHOOK_URL` - optional outgoing alert webhook

Repository variables (`vars.`):
- `SEARCH_WINDOW_DAYS` - optional, default 3 days; scheduled discovery is always windowed (minimum 1)
- `WATCHDOG_WARN_HOURS` - optional watchdog threshold (default 2)

Workflow-set operational flags (fixed in YAML, not secrets):
- `TRIGGER_SOURCE` - from the `trigger_source` input (external trigger vs manual)
- `STATE_LEASE_WAIT_SECONDS` - `"600"` in `job_hunter.yml`; code default 300
- `ALLOW_SMARTRECRUITERS_BULK` - `"1"` in `job_hunter.yml`; explicit pilot decision (`DECISIONS.md` D-38)
- `GITHUB_ACTIONS`, `GITHUB_EVENT_NAME`, `GITHUB_SHA` - read by the code to label runs and record `Runs.Code_Version`
- `REBALANCE_MODE` - read by `hunter.py`; production setting lives in the Sheet Settings tab (`DECISIONS.md` D-45)

Optional code-read overrides (not set in workflows): `GROQ_MODEL` (default `openai/gpt-oss-120b`), `GROQ_FALLBACK_MODEL` (default `openai/gpt-oss-20b`), `GROQ_TPM` and `GROQ_FALLBACK_TPM` (default 8000 each), `WATCHDOG_WARN_HOURS`, `ALLOW_LOCAL_SHEET_WRITES` (set to `1` only for a TEST Sheet; `DECISIONS.md` D-37).

**Runtime settings:**
- Most behavioural settings (for example `Max_Active_Boards`, `Rebalance_Mode`, `Discovery_Every_Hours`, `Discovery_Credit_Budget`, `Search_Monthly_Credits`, `Min_Alert_Score`) live in the `Settings` tab of the Google Sheet, not in the repository. See `README.md` and `SPEC.md`.
- Code defaults for allocation are in `pools.py` (for example `GRADUATION_FLOOR` = 2.0, `DECISIONS.md` D-45).

**Persistent state:**
- Production: Google Sheet tabs `Boards`, `Events`, `Runs`, `Discovery`, `Inventory`, `Lock`, `Settings`, `Dashboard`, plus the user's tracker tab (`DECISIONS.md` D-03, D-31, D-40, D-44, D-46).
- Local development without a Sheet: CSV files under `state/` (`state/boards.csv`, `state/events.csv`, `state/runs.csv`, `state/discovery.csv`, `state/inventory.csv`, `state/lock.json`). `state/` is gitignored (`.gitignore`, `DEPLOY.md`). Writes to the production Sheet from a local machine are refused unless `ALLOW_LOCAL_SHEET_WRITES=1`.

**Build:**
- No build configuration. Dependencies are installed with pip only.
- Config files present: `requirements.txt`, `.gitignore`, `CLAUDE.md` (single `@AGENTS.md` import line), `.github/workflows/*.yml`.

## Platform Requirements

**Development:**
- Python 3.12 (matches CI), `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt` (`README.md`).
- `python -m unittest discover -s tests` before finishing work (`AGENTS.md` rule 8).
- Local runs of the production poller need Sheet and Telegram credentials; without them the tests use fakes (see `STATUS.md` for mocked vs live status).

**Production:**
- GitHub Actions only. Repository must be private (`DEPLOY.md`).
- Workflows:
  - `job_hunter.yml` - hourly poller (`cron: "17 * * * *"`) plus `workflow_dispatch` inputs (`discover`, `backfill`, `rebalance_report`, `pilot_report`, `trigger_source`, `storage_report`, `dashboard`, `delivery_test`). Timeout 25 min. Concurrency group `job-hunter-state`, `cancel-in-progress: false`.
  - `inventory.yml` - weekly refresh (`23 5 * * 1`) and daily validation (`41 6 * * 2-6,0`). Shares concurrency group `job-hunter-state`.
  - `watchdog.yml` - GitHub schedule every 15 minutes (`7,22,37,52 * * * *`), with a recommended external second trigger (`DEPLOY.md`).
- Scheduled runs are best-effort on GitHub. Pilot week 1 showed about 38 schedule runs plus 168 external dispatches (`STATUS.md`). The external hourly trigger is set up outside this repository.
- No container, server, or cloud compute of its own. Google Sheets is the database and the dashboard host.

---

*Stack analysis: 2026-10-24*
