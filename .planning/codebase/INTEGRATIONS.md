# External Integrations

**Analysis Date:** 2026-10-14

## APIs & External Services

**Web search (job discovery):**
- Serper (Google Search API) - Finds candidate job-posting URLs with `site:` filters for the supported ATS hosts.
  - Endpoint: `https://google.serper.dev/search` (`SERPER_URL` in `hunter.py` ~line 85)
  - Client: `requests.post` in the search function (`hunter.py` ~line 388), timeout `HTTP_TIMEOUT = 20`
  - Auth: `SERPER_API_KEY` (sent as request header; fallback env `SEARCH_API_KEY`)
  - Controls: `SEARCH_TBS` (default `qdr:d3`), `SEARCH_PAGES` (default 2), `SERPER_NUM` (default 0, Serper free tier rejects num > 10)
  - Note: `legacy/hunter_local_scoring.py` also supports Tavily (`https://api.tavily.com/search`). The active `hunter.py` does not.

**LLM scoring (job-to-resume fit):**
- Groq (OpenAI-compatible Chat Completions API) - Scores each posting 0-100 against the candidate's resume and returns JSON.
  - Endpoint: `https://api.groq.com/openai/v1/chat/completions` (`GROQ_URL` in `hunter.py` ~line 91)
  - Client: raw `requests` session (`self.http.post`), no Groq SDK. Timeout 60 s.
  - Auth: `Authorization: Bearer` header with `GROQ_API_KEY`
  - Models: primary `GROQ_MODEL` (default `llama-3.3-70b-versatile`), fallback `GROQ_FALLBACK_MODEL` (default `llama-3.1-8b-instant`). Switches to fallback on 429 from the primary, and holds there for `FALLBACK_HOLD_SECONDS = 90`.
  - Request shape: `temperature: 0.2`, `max_tokens: MAX_OUTPUT_TOKENS`, `response_format: {"type": "json_object"}`.
  - Rate control: per-model `TokenBudget` (`GROQ_TPM` 12000, `GROQ_FALLBACK_TPM` 6000), `LLM_MIN_INTERVAL_SECONDS` 2.2 pacing, exponential backoff, honors `retry-after`. Error text `json_validate_failed` triggers a retry.
  - Model JSON output is parsed defensively (tolerates code fences and surrounding prose).

**Job-board hydration (reading the full posting):**
Each ATS has a public, unauthenticated JSON API. `classify_url` (`hunter.py` ~line 278) maps a posting URL to an ATS reference, then the matching `_hydrate_*` function fetches it with `requests.get(..., headers={"User-Agent": USER_AGENT, "Accept": ...}, timeout=HTTP_TIMEOUT)`.

| ATS | Recognized host(s) | API endpoint template (`hunter.py` ~lines 86-90) |
|---|---|---|
| Greenhouse | `boards.greenhouse.io`, `job-boards.greenhouse.io` | `https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}` |
| Lever | `jobs.lever.co` | `https://api.lever.co/v0/postings/{company}/{posting_id}` |
| Ashby | `jobs.ashbyhq.com` | `https://api.ashbyhq.com/posting-api/job-board/{company}` |
| Workable | `apply.workable.com` | `https://apply.workable.com/api/v2/accounts/{company}/jobs/{shortcode}` |
| SmartRecruiters | `jobs.smartrecruiters.com` | `https://api.smartrecruiters.com/v1/companies/{company}/postings/{posting_id}` |

- Auth: none (public board APIs). Only a browser-like `USER_AGENT` header is sent.
- Results are used to check the real publication date (`Max_Job_Age_Days`) and the open/closed state.

**Notifications:**
- Telegram Bot API - Sends a formatted HTML alert for each new job at or above `Min_Alert_Score`.
  - Endpoint: `https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage` (`send_alert`, `hunter.py` ~line 1231)
  - Payload: `chat_id`, `text` (truncated to 4096 chars), `parse_mode: "HTML"`, `disable_web_page_preview: true`
  - Auth: bot token embedded in the URL path. Treat it as a secret. Do not log or echo the URL.
  - Optional: skipped when `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID` is empty.
- Generic webhook - POSTs JSON to `ALERT_WEBHOOK_URL` (`hunter.py` ~line 1243). Optional.
  - Payload fields: `title`, `company`, `score`, `verdict`, `missing_gaps`, `location`, `posted`, `url`, `tracker`.
  - Auth: none added. Any secret must be part of the URL itself.

## Data Storage

**Primary database: Google Sheets (via gspread)**
- Spreadsheet ID from `GOOGLE_SHEET_ID`. Opened with `gspread.service_account_from_dict(...).open_by_key(...)` in `SheetStore.__init__` (`hunter.py` ~line 1038-1041). Sheet URL: `https://docs.google.com/spreadsheets/d/{sheet_id}`.
- Tabs:
  - `Settings` (`SETTINGS_TAB`) - user-editable config and `Resume_Text`. Created with defaults if missing.
  - `Job Tracker` (`TRACKER_TAB`) - append-only (`append_rows`) list of scored jobs. Columns in `TRACKER_COLUMNS` (`hunter.py` ~lines 48-60), with `Apply_URL` as the dedupe key (column I, `URL_COLUMN`).
  - `Seen_Archive` (`ARCHIVE_TAB`, hidden) - rejected, closed, stale, and error URLs, used only to avoid re-fetching.
- Dedupe reads: `col_values(URL_COLUMN)` on the tracker and `col_values(ARCHIVE_URL_COLUMN)` on the archive.
- Writes use `append_rows`. Existing user edits are not overwritten.
- Empty default tabs are removed with `del_worksheet` during setup (~line 1082).

**Fallback: local CSV**
- Used when `GOOGLE_SHEET_ID` is unset. `Tracker` class (`hunter.py` ~line 1149) writes `tracked_jobs.csv`, with archive `ARCHIVE_PATH`. Mirrors the sheet column names (`TRACKER_COLUMNS`).
- Files: `tracked_jobs.csv` (live, git-tracked, backed up by CI), `tracked_jobs.gemini-scored.csv` (an earlier scoring run, not referenced by code).

**File storage:**
- Local filesystem only. `resume.txt` (`RESUME_PATH`) is read when `Resume_Text` is blank in the sheet. Do not quote or commit its contents.

**Caching:**
- None. Dedupe state lives in the sheet or CSV. In-memory `deque` for LLM call pacing only.

## Authentication & Identity

**Google (service account):**
- Mechanism: OAuth2 service-account JWT via `google-auth`, invoked through `gspread`.
- Credential: `GOOGLE_SERVICE_ACCOUNT_JSON` - full JSON text (GitHub Secret) or a path to a `.json` file (local). Parsed by `load_service_account` (`hunter.py` ~line 1022).
- Required setup: the Google Sheets API and Google Drive API enabled, and the sheet shared with the service account's `client_email` as Editor (per `README.md`).

**API keys:**
- Serper, Groq, and Telegram each use a static secret, supplied only through environment variables or GitHub Actions secrets. No key rotation logic in code.

**No end-user auth.** The app has no login, sessions, or user accounts. The "user" is the single operator who owns the sheet.

## Monitoring & Observability

**Error tracking:**
- None (no Sentry, Rollbar, or similar).

**Logs:**
- Python `logging` to stderr, logger name `hunter` (`log = logging.getLogger("hunter")`). Warnings for Groq 429s, request errors, and unusable responses. Final summary line: "Done. N added to the tracker, N archived, N will retry next run, ..."
- GitHub Actions run logs are the only persistent record.

**Alerting:**
- Telegram and webhook per-job alerts (see Notifications above). No run-failure alerting.

## CI/CD & Deployment

**Hosting:**
- GitHub Actions, `ubuntu-latest`. No separate server or cloud deployment.

**CI Pipeline:**
- `.github/workflows/job_hunter.yml`:
  - Triggers: `schedule` (`0 13-23/2 * * 1-5` UTC) and `workflow_dispatch`.
  - Steps: `actions/checkout@v4`, `actions/setup-python@v5` (Python 3.12, pip cache), `pip install -r requirements.txt`, `python hunter.py`, then a CSV backup commit.
  - Backup step: runs `always()` and only does work if `tracked_jobs.csv` changed. Commits as `github-actions[bot]` with `[skip ci]`, runs `git pull --rebase`, then `git push`.
  - Concurrency: group `job-hunter`, `cancel-in-progress: false`.
- Tests are not run in CI. The workflow has no test step.

## Environment Configuration

**Required env vars (GitHub Secrets; names only):**
- `SERPER_API_KEY`
- `GROQ_API_KEY`
- `GOOGLE_SHEET_ID`
- `GOOGLE_SERVICE_ACCOUNT_JSON`

**Optional secrets:**
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- `ALERT_WEBHOOK_URL` (wired in the workflow, not documented in `README.md`)

**Optional repository variable:**
- `SEARCH_TBS` (`vars.SEARCH_TBS`, default `qdr:d3`)

**Secrets location:**
- GitHub repository secrets (for scheduled runs).
- Local `.env` at the repo root (git-ignored, present, not read). Loaded by `python-dotenv` when available.
- The Google service-account JSON is also a secret. The README warns to keep the repository private because the resume text can end up in the sheet and in `resume.txt`.

## Webhooks & Callbacks

**Incoming:**
- None. The app makes outbound calls only and runs no server.

**Outgoing:**
- Telegram `sendMessage` (optional).
- Generic JSON webhook at `ALERT_WEBHOOK_URL` (optional).

---

*Integration audit: 2026-10-14*
