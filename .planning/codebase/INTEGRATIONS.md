---
last_mapped_commit: aa1bab2d3c3e37ac119cd898b2e4f42a50f276fe
last_mapped_at: 2026-10-24
---
# External Integrations

**Analysis Date:** 2026-10-24

Secrets are referred to by variable name only. No values are recorded here. Live vs mocked status follows `STATUS.md`; the same rule applies in `AGENTS.md` rule 5.

## APIs & External Services

**Job board ATS public APIs (polling and validation; no auth):**
- Greenhouse Job Board API - `https://boards-api.greenhouse.io/v1/boards/{board}/jobs` (list) and `.../jobs/{job_id}` (hydrate). Adapter: `boards.py` (lines 27, 120). Verified live in `DECISIONS.md` D-33.
- Lever Postings API - `https://api.lever.co/v0/postings/{board}` (list) and `.../{posting_id}` (hydrate). Adapter: `boards.py` line 28; `hunter.py` line 121. Per-provider spacing 1 s (`inventory.py` `MIN_INTERVAL`), per Lever's `Crawl-delay`.
- Ashby Posting API - `https://api.ashbyhq.com/posting-api/job-board/{board}`. Adapter: `boards.py` line 29; `hunter.py` line 122.
- Workable - `https://apply.workable.com/api/v1/widget/accounts/{board}` (list, undocumented widget endpoint) and `https://apply.workable.com/api/v2/accounts/{company}/jobs/{shortcode}` (hydrate). Adapter: `boards.py` lines 30, 126, 152-154; `hunter.py` line 123. Completeness is unverified (`DECISIONS.md` D-33).
- SmartRecruiters Posting API - `https://api.smartrecruiters.com/v1/companies/{board}/postings` (list) and `.../postings/{posting_id}` (hydrate). Adapter: `boards.py` line 31; `hunter.py` line 124. **Policy:** `api.smartrecruiters.com/robots.txt` says `Disallow: /` for generic agents. The provider is parked by default, and polling is opted in for the pilot with `ALLOW_SMARTRECRUITERS_BULK=1` in `.github/workflows/job_hunter.yml`. Reversal steps are in `DECISIONS.md` D-38. Robots status is checked in `inventory.py` (line 343).
- Public job URLs that are stored as links, not fetched: `jobs.lever.co`, `jobs.ashbyhq.com`, `job-boards.greenhouse.io`, `jobs.smartrecruiters.com`, `apply.workable.com/{board}/j/{job_id}/` (`boards.py` line 97 and surrounding code).

**Search (candidate discovery only; `SPEC.md` "Discovery"):**
- Tavily Search API - `https://api.tavily.com/search` (POST) and `https://api.tavily.com/usage` (GET). Client: `search.py` (`TAVILY_API`, lines 32, 116-149), using `requests`. Auth: Bearer token from `TAVILY_API_KEY`. Rotating, date-windowed slots, budget-capped (`DECISIONS.md` D-18, D-36). Unfiltered `--backfill` is manual only. If the key is absent, discovery is skipped and polling still runs.
- Earlier Serper provider is retired (`DECISIONS.md` D-36). Not used by the current code.

**Board inventories (weekly and daily import; public, no auth):**
- `open-ats-feed` - `https://raw.githubusercontent.com/veresk06/open-ats-feed/main/actor/data/companies.json` (`inventory.py` line 47)
- `ats-scrapers` - `https://api.github.com/repos/kalil0321/ats-scrapers/contents/ats-companies?ref=main` (listing, line 48) and `https://raw.githubusercontent.com/kalil0321/ats-scrapers/main/ats-companies/{name}.csv` (line 49)
- Downloads are bounded by `MAX_DOWNLOAD_BYTES` (40 MB) and a shrink guard (`SHRINK_GUARD` 0.5) in `inventory.py`. User-Agent is set in `inventory.py` (line 59).

**LLM scoring:**
- Groq OpenAI-compatible chat API - `https://api.groq.com/openai/v1/chat/completions` (`hunter.py` line 125). Models: primary `openai/gpt-oss-120b`, fallback `openai/gpt-oss-20b` (`hunter.py` lines 333-334; env overrides `GROQ_MODEL`, `GROQ_FALLBACK_MODEL`). Output cap 1,000 tokens (`DECISIONS.md` D-16). Auth: Bearer from `GROQ_API_KEY`. Retries: `GROQ_ATTEMPTS = 6` with linear backoff in the request loop (`hunter.py` lines 732, 900; generic sleep at line 488). Rate budget: `GROQ_TPM` / `GROQ_FALLBACK_TPM` (default 8000 each).
- Model discovery and error hint: `GET https://api.groq.com/openai/v1/models` (`hunter.py` line 943). Used only to tell the operator which models are usable when a model is rejected.
- Scoring applies only to jobs that pass the title gate and hard rules (`SPEC.md` "Filtering order"; `DECISIONS.md` D-08). The Groq model judges fit against the resume text. The resume is a personal file, not documented here.
- Verification: scoring is verified live on real postings per `DECISIONS.md` D-16 and the pilot log (`STATUS.md` pilot section). The delivery test (`delivery_test` input) exercises the real Groq path.

**Messaging:**
- Telegram Bot API - `https://api.telegram.org/bot{token}/sendMessage` with `parse_mode: "HTML"` (`hunter.py` lines 1447, 1451). Also used by `watchdog.py` (line 327) for one-per-incident outage and recovery messages. Auth: bot token in the URL path, from `TELEGRAM_BOT_TOKEN`. Recipient: `TELEGRAM_CHAT_ID`. Pending alerts are retried until accepted or rejected 5 times (`DECISIONS.md` D-21).
- Live Telegram delivery is **not verified** in `STATUS.md` (no token in that run), but the pilot log records real alerts sent during week 1 (`STATUS.md` pilot table). Treat delivery as live-verified only for the pilot period recorded there.

**Optional outgoing webhook:**
- `ALERT_WEBHOOK_URL` - generic alert webhook, read in `hunter.py` (`Config.webhook_url`, line 343). Receives the same alert content, including late-delivery labels (`DECISIONS.md` D-21). Not configured in the repository workflows beyond the secret pass-through.

## Data Storage

**Primary database: Google Sheets (via gspread):**
- Client: `gspread` with `gspread.service_account_from_dict(...)` (`hunter.py` ~line 1186; `watchdog.py` line 288). Sheet opened by `GOOGLE_SHEET_ID`.
- Credentials: service-account JSON in `GOOGLE_SERVICE_ACCOUNT_JSON` (repository secret). The code loads it through `load_service_account` and does not write it to disk.
- Tabs (names from code): `Boards` (one row per board, rewritten in batches), `Events` (append-only ledger, `DECISIONS.md` D-03), `Runs` (run records, `DECISIONS.md` D-40), `Discovery` (rotation and credit state), `Inventory` (import rows), `Lock` (advisory writer lease, D-31), `Settings` (user-editable knobs), `Dashboard` (generated summary, D-40/D-41), plus the user's tracker tab, written and read by header name (D-44, D-46). A tracker without its header is refused, not written by position.
- Sheets API schema: the dashboard requests are validated against Google's Sheets v4 discovery schema in offline tests (`STATUS.md`); the real Sheets API has rejected one chart shape (D-41).
- Limits: `DECISIONS.md` D-03 notes an Events revisit point at about 200k rows. `D-43` storage report is read only and proposes no change.
- Lease: the Sheet-based lease is write-then-verify, **not atomic** (`DECISIONS.md` D-31, D-37). Both workflows share `job-hunter-state` concurrency to serialize writes.

**Local file state (development only):**
- CSV and JSON files under `state/` when no Sheet is configured (`state/boards.csv`, `state/events.csv`, `state/runs.csv`, `state/discovery.csv`, `state/inventory.csv`, `state/lock.json`). The lease uses `fcntl` `flock` for local processes (`DECISIONS.md` D-37). The directory is gitignored.
- Historical scoring exports: `tracked_jobs.csv`, `tracked_jobs.gemini-scored.csv` at the root are gitignored (`DEPLOY.md`), contain personal scoring data, and must not be read or quoted.

**File storage:** Local filesystem only (`state/`, `.venv/`, `__pycache__/`). No object storage.

**Caching:** None external. Inventory download cache is local to the run within GitHub Actions cache (`inventory.yml` uses pip cache via `setup-python`).

## Authentication & Identity

**Google:**
- Service account (gspread). Auth flow: JSON key from `GOOGLE_SERVICE_ACCOUNT_JSON`. The Sheet must be shared with the service account. Scope and identity specifics are in code (`hunter.py`, `watchdog.py`).

**Telegram:**
- Bot token auth in the request URL (`hunter.py` line 1447).

**Groq / Tavily:**
- Bearer-token API keys in request headers (`hunter.py` and `search.py`).

**ATS boards:** No auth. Public endpoints only.

**Application users:** None. No login, sessions or user accounts exist in this repository.

## Monitoring & Observability

**Error tracking:** None (no Sentry or similar detected).

**Logs:**
- Python `logging` to the GitHub Actions log. Run outcomes and counters are written to the `Runs` tab (`DECISIONS.md` D-40).
- Operator-facing summaries: `Dashboard` tab (`dashboard.py`, `reporting.py`), `--pilot-report`, `--rebalance-report`, `--storage-report` (read only).

**Missed-run watchdog:**
- `watchdog.py` reads the Sheet `Runs` tab (read only in `--dry-run`) and sends Telegram messages on stale or recovered states. Workflow: `.github/workflows/watchdog.yml`, GitHub schedule every 15 minutes, threshold 2 h (`WATCHDOG_WARN_HOURS` overrides). A second external trigger is recommended (`DEPLOY.md` "Watchdog"). Telegram delivery and real incident tabs are **not verified live** (`STATUS.md`).

## CI/CD & Deployment

**Hosting:** GitHub Actions on `ubuntu-latest`. The repository is private (`DEPLOY.md`). No hosting platform, container or server.

**CI Pipeline:**
- `.github/workflows/job_hunter.yml` - hourly poll, manual inputs for discovery, backfill, reports, dashboard, delivery test
- `.github/workflows/inventory.yml` - weekly import (Monday 05:23 UTC) and daily validation
- `.github/workflows/watchdog.yml` - 15-minute watchdog
- `actions/checkout@v4`, `actions/setup-python@v5` (Python 3.12, pip cache). No test step runs in the workflows; tests are run locally (`AGENTS.md` rule 8).
- Workflow permissions: `contents: read`. The repository writes nothing; state lives in the Sheet.

**External trigger:** An hourly external scheduler dispatches `job_hunter.yml` with `trigger_source` set to `external` (pilot evidence in `STATUS.md`: 168 `workflow_dispatch:external` runs in the week). The scheduler service is not configured in the repository (`DEPLOY.md`).

**Secrets management:** GitHub repository secrets and variables only. Names are listed in the Environment Configuration section below.

## Environment Configuration

**Required in production (GitHub repository secrets):**
- `GROQ_API_KEY` - required by `job_hunter.yml` "Check configuration" step
- `GOOGLE_SERVICE_ACCOUNT_JSON` - required
- `GOOGLE_SHEET_ID` - required
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` - required for any run that can deliver (scheduled poll, delivery test); not required for pilot, rebalance, dashboard or storage reports
- `TAVILY_API_KEY` - optional (warning only)
- `ALERT_WEBHOOK_URL` - optional

**Repository variables:** `SEARCH_WINDOW_DAYS` (optional), `WATCHDOG_WARN_HOURS` (optional).

**Secrets location:** GitHub Actions secrets for the repository. Local development uses a `.env` file that is loaded by `python-dotenv`. The file is gitignored and must never be read or committed (`AGENTS.md` rule 6, `DEPLOY.md`). Document only the variable names.

## Webhooks & Callbacks

**Incoming:**
- `workflow_dispatch` on the three workflows (manual, and the external hourly trigger). No HTTP endpoint is served by this repository.

**Outgoing:**
- Telegram `sendMessage` (`hunter.py`, `watchdog.py`)
- `ALERT_WEBHOOK_URL` POST (optional, `hunter.py` config)
- Board API GET requests (Greenhouse, Lever, Ashby, Workable, SmartRecruiters)
- Tavily POST and GET (`search.py`)
- Groq POST and GET models (`hunter.py`)
- Google Sheets API (gspread)
- GitHub API and raw content (inventory download only)

---

*Integration audit: 2026-10-24*
