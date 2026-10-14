# Codebase Concerns

**Analysis Date:** 2026-10-14

Scope: `hunter.py` (1437 lines, the only live code path), `tests/test_hunter.py`, `.github/workflows/job_hunter.yml`, `README.md`, `.gitignore`, `requirements.txt`, and the CSV artifacts at the repo root. `legacy/` is an archived earlier version and is only noted where it creates debt. `.env`, `resume.txt` and `Resume.pdf` were intentionally not read.

Line numbers refer to `hunter.py` unless stated otherwise.

## Summary of Highest-Impact Issues

1. **Permanent archiving of transient or misconfigured failures.** Any non-transient error during hydration or scoring is written to the hidden `Seen_Archive` tab, which makes the URL permanently "seen". This contradicts the README promise that unscored jobs are retried on the next run. A single bad Groq model name or HTTP 403 from an ATS can silently archive every job it touches.
2. **CI backup of the CSV tracker is incomplete.** The workflow commits only `tracked_jobs.csv`. `seen_archive.csv` is neither committed nor gitignored, so in CSV mode the dedupe memory of rejected/closed/stale jobs is lost between runs.
3. **Freshness gate can be defeated.** Dates fall back from creation date to last-updated date to the search engine's date, and undated jobs pass the stale gate. Old postings that were recently edited or re-crawled are treated as fresh.
4. **Duplicate detection is URL-string based.** The same posting reached through different hostnames or slugs produces multiple tracker rows and multiple Telegram alerts.
5. **Silent failure.** Persistent outages (Groq, ATS, Serper) produce exit code 0 and log lines only. No alert reaches the user.

---

## Seen / Evaluated / Alerted State

### Three stores, one dedupe key, no transactions
- **Issue:** The "seen" set is rebuilt at startup from two columns: `Job Tracker` column I (`Apply_URL`, `URL_COLUMN` at line 61) and `Seen_Archive` column C (`ARCHIVE_URL_COLUMN`, line 65). See `SheetStore.seen_urls` (line 1119) and `CsvStore.seen_urls` (line 1186). A URL is "handled" if it appears in either place. Scored rows, archived rows and error rows all share this one set, so a transient state can never be distinguished from a final one.
- **Files:** `hunter.py` lines 61, 65, 1119-1123, 1186-1192.
- **Impact:** Any decision to re-process a job requires manual deletion from the sheet (README line 84).
- **Fix approach:** Store an explicit `status` plus `last_attempt` per URL in one place and make retry eligibility a function of status, not presence.

### Failures are archived as final (contradicts README retry promise)
- **Issue:** `process()` converts several non-transient failures into `STATUS_ERROR` rows with `score=None`. `flush()` (line 1392-1395) sends every row with `is_visible` false to `append_archive`. `archive_cells` (line 1005) keeps the URL forever. The affected paths are:
  - Hydration, generic exception: `process` line 1302-1304. This includes any `requests.HTTPError` that is not 404/410/429/5xx, such as 401/403 from bot protection (`hydrate_posting` re-raises at line 728).
  - Hydration, `ValueError("description too short")` at line 731-732. A JavaScript-only page or a temporarily thin response is archived permanently.
  - Groq HTTP 4xx other than `json_validate_failed`: `GroqClient.evaluate` raises `ValueError` at line 946, which `process` turns into `STATUS_ERROR` (line 1329-1331).
  - Groq exhausting parse retries: line 954-955.
- **Impact:** A decommissioned or misspelled `GROQ_MODEL` returns HTTP 400 or 404 on every call. Every job is archived as "Unjudged / Error" on that run and never re-evaluated after the model is fixed. Same outcome for any ATS that returns 403 to GitHub Actions IP ranges. The README (line 97) states "Jobs it couldn't score this run are retried on the next run," which is false for these paths.
- **Files:** `hunter.py` lines 722-732, 942-946, 1302-1304, 1329-1331, 1392-1397.
- **Fix approach:** Classify errors into `permanent` (404/410, closed, confirmed bad payload) and `retryable` (everything else, including config errors). Fail fast and do not archive when the Groq response is 4xx other than 429. Only archive after N consecutive failures for the same URL, and keep an attempt counter.

### Alerts are sent after the row is recorded, with no retry
- **Issue:** `flush()` appends rows first (line 1395-1396), then sends Telegram or webhook alerts (line 1399-1404). The comment says this prevents duplicate rows. The trade-off is that a failed alert is logged as a warning and never retried, and the job is never re-alerted because it is now "seen".
- **Files:** `hunter.py` lines 1385-1404, 1215-1261.
- **Impact:** A transient Telegram outage (or an invalid token) silently drops a "To Apply" alert. The user sees the row in the sheet only if they look.
- **Fix approach:** Add an `alerted` column or status flag written after successful send, and have the next run re-send alerts for `To Apply` rows where the flag is empty.

### Partial-batch loss on kill
- **Issue:** `pending` rows are only written every `FLUSH_EVERY = 10` jobs (line 1341, 1421-1422). The `finally` flush (line 1426-1427) does not run on SIGKILL or GitHub Actions timeout (`timeout-minutes: 30`, workflow line 12). Up to nine scored rows are lost per timeout and are re-scored (and re-billed in Groq tokens) on the next run.
- **Files:** `hunter.py` lines 1341, 1382, 1421-1427; `.github/workflows/job_hunter.yml` line 12.
- **Fix approach:** Flush after every row, or add a wall-clock budget that stops the loop before the Actions timeout.

### Data-dependent column positions
- **Issue:** Dedupe reads column I of the tracker and column C of the archive by position. The README says "don't delete this column" (line 81), but the user is allowed to reorder or insert columns in the sheet. Doing so silently breaks dedupe, so every job is re-scored and re-appended. The tracker itself is append-only, so duplicates accumulate.
- **Files:** `hunter.py` lines 49-65, 1121-1122.
- **Fix approach:** Locate columns by header name at startup and fail loudly if the header is missing.

### Settings fallback hides user errors
- **Issue:** `Settings.from_values` silently replaces blank or invalid values with environment variables and then defaults (`pick`, line 161-162). `_int_or` (line 140-144) silently returns the default for values like `"seventy"`. There is no way to intentionally set `Max_Job_Age_Days` to a blank value, and no warning is logged.
- **Files:** `hunter.py` lines 140-144, 158-172.
- **Fix approach:** Log a warning whenever a value is ignored or replaced, and validate the Settings tab at startup.

### Bootstrap does not migrate new settings
- **Issue:** `bootstrap` (line 1044) creates the Settings tab only if it is missing. Settings added to `DEFAULT_SETTINGS` in future releases are never written to an existing sheet, so they silently fall back to env or defaults.
- **Files:** `hunter.py` lines 107-132, 1048-1057.

---

## Duplicate Detection

### URL normalization misses same-job variants
- **Issue:** `normalize_url` (line 254) and `dedupe_key` (line 273) only strip query, fragment, trailing slash and a few suffixes. They do not unify:
  - `boards.greenhouse.io/<board>/jobs/<id>` and `job-boards.greenhouse.io/<board>/jobs/<id>`, which both appear in `ATS_SITES` (line 76-77) and `classify_url` (line 285). These produce two different keys for one posting.
  - SmartRecruiters slugs. `_SMARTRECRUITERS_PATH` (line 251) accepts an optional `-slug` suffix, but the slug is kept in the normalized URL. `/Co/743999-title` and `/Co/743999` are both valid and produce different keys.
  - Company-hosted career pages that link to an ATS board (no dedupe at all across hosts).
- **Impact:** Duplicate rows and duplicate Telegram alerts. The `ref.job_id` already identifies the posting, but it is not used for deduplication.
- **Files:** `hunter.py` lines 248-295, 1275-1289.
- **Fix approach:** Build the dedupe key from `(ats, company, job_id)` instead of the URL string, and keep the URL only for display.

### Cross-run duplicates are possible on concurrent writes
- **Issue:** `seen` is read once at startup (line 1369). The concurrency group in the workflow (`.github/workflows/job_hunter.yml` lines 9-11) prevents overlapping CI runs, but a local `python hunter.py` run against the same sheet, or a manual `workflow_dispatch` that waits for the previous run, can still race. Nothing re-reads `seen` before append.
- **Files:** `hunter.py` lines 1369, 1126-1136; `.github/workflows/job_hunter.yml` lines 9-11.

### `--url` mode bypasses dedupe entirely
- **Issue:** When `--url` is given, `seen` is set to an empty set (line 1369). Any URL passed is appended to the tracker even if it already exists.
- **Files:** `hunter.py` lines 1365-1369.
- **Fix approach:** Keep `--url` dedupe on by default and add an explicit `--force` flag.

---

## Freshness and Publication Dates

### Date fallback chain can make old postings look new
- **Issue:** The posting date is taken from the first available source:
  1. Greenhouse: `first_published`, else `updated_at` (line 532-533). `updated_at` is the last-edit date, so an old posting that was recently edited is treated as new.
  2. Lever `createdAt`, Ashby `publishedAt`, Workable `published`, SmartRecruiters `releasedDate`: these are reasonable.
  3. Search-result date (`hint_date`), used only when the posting gives no date (line 733-737). Serper's `date` is frequently the crawl or edit date, not the publication date.
  4. If there is still no date, `posted` is empty. `job_age_days` returns `None` (line 456-458), and the stale gate (line 1314) only fires when `age is not None`. Undated jobs always pass.
- **Impact:** The stale gate, described in the README as the "authoritative freshness check," is weakened by three fallbacks that are not publication dates.
- **Files:** `hunter.py` lines 521-534, 733-737, 1311-1317.
- **Fix approach:** Treat `updated_at` and `search_result` dates as advisory only. Archive undated postings as `Unknown date` with a visible flag, or require a confirmed publication date before scoring.

### Ashby fetches the page twice and swallows errors
- **Issue:** When the Ashby API gives no `publishedAt`, `_page_date_posted` (line 677-691) re-downloads the posting page. It catches `Exception` broadly and returns `""`, so network errors are indistinguishable from "no date". The page is also fetched a second time for the same description.
- **Files:** `hunter.py` lines 556-575, 677-691, 711-712.

### Relative and fuzzy date parsing is approximate
- **Issue:** `parse_posted` (line 416-448) maps "N months ago" to `30 * N` days and treats "N hours ago" as today. `datetime.fromisoformat(...).astimezone(timezone.utc)` (line 436) interprets naive timestamps as the local machine's timezone, so results differ between a developer laptop and the UTC GitHub runner.
- **Files:** `hunter.py` lines 416-448.
- **Impact:** Boundary-day misclassification around `Max_Job_Age_Days`. Low severity but non-deterministic across machines.

### Date_Found is a naive UTC string
- **Issue:** `_now()` (line 1013-1014) writes `YYYY-MM-DD HH:MM` without a timezone marker. The sheet's USER_ENTERED parsing may interpret it in the sheet's locale timezone.
- **Files:** `hunter.py` lines 1013-1014, 1126-1129.

---

## Failure and Retry Behavior

### Search failures can silently reduce coverage
- **Issue:** `search_ats` (line 367-410) breaks out of a query's pages on the first `RequestException` and logs a warning. A query with failing page 2 silently contributes only page 1. The run only aborts if every request failed.
- **Files:** `hunter.py` lines 367-410.
- **Also:** `resp.json()` on line 399 is not guarded. A non-JSON 200 response raises an uncaught `ValueError` inside the loop, which aborts startup with exit code 2 instead of skipping that page.

### Groq retry budget can exceed the Actions timeout
- **Issue:** `GroqClient.evaluate` allows `GROQ_ATTEMPTS = 6` attempts (line 748, 906). 429s on the fallback model sleep `min(60, retry_after or 5 * 2**attempt)` seconds (line 933-935), which can total roughly 195 seconds per job. There is no global deadline. Under a daily-quota 429, 30 jobs can take over 90 minutes, which exceeds the 30-minute `timeout-minutes` (workflow line 12).
- **Files:** `hunter.py` lines 745-749, 900-956; `.github/workflows/job_hunter.yml` line 12.
- **Fix approach:** Distinguish per-minute limits (short wait) from daily-quota limits (stop the run, return a non-zero exit, and alert).

### Mixed failure modes collapse into "permanent"
- **Issue:** If any attempt produced a parse failure, the final result is `ValueError` (line 954-955), even if the other attempts were rate-limits. That `ValueError` is then archived permanently by `process`.
- **Files:** `hunter.py` lines 954-956, 1329-1331.

### Silent successful exit on persistent outage
- **Issue:** `main` returns 0 at line 1433 after a run where every job hit `TransientError` (counted as "will retry next run"). Only logs record that nothing was scored. `ALERT_WEBHOOK_URL` and Telegram are used only for matches, so there is no operational alert.
- **Files:** `hunter.py` lines 1406-1433.
- **Fix approach:** Return a non-zero code, or send an operational alert, when the number of retryable failures reaches a threshold.

### Uncaught exceptions during flush
- **Issue:** `flush()` has no try/except around `store.append_archive` and `store.append_jobs` (line 1395-1397). A Sheets API quota error (HTTP 429 from Google) propagates out of the `finally` clause and crashes the run with a traceback. Rows in `batch` are dropped; they are not recorded, so they will be retried, but the crash hides the cause.
- **Files:** `hunter.py` lines 1385-1404, 1426-1427.

---

## Security Considerations

### Telegram bot token can leak into error messages and logs
- **Risk:** The bot token is embedded in the request URL (`hunter.py` line 1232). `resp.raise_for_status()` (line 1241) raises an `HTTPError` whose message includes the full URL, and `send_alert` is called inside `flush` with `except Exception` (line 1402-1404), which logs `exc`. The token is then written to the console.
- **Files:** `hunter.py` lines 1231-1241, 1402-1404.
- **Current mitigation:** GitHub Actions masks registered secrets in logs, so the CI risk is low. Local runs (`python hunter.py`) print the token.
- **Recommendations:** Catch `requests.RequestException` in `send_alert` and log only the status code.

### Prompt injection can influence alerts
- **Risk:** Job descriptions and the resume are inserted directly into the Groq prompt (`build_messages`, line 830-839). The system prompt tells the model to ignore instructions in them (line 780), but the output `score` directly controls whether a job is marked `To Apply` and sent to Telegram (line 1332-1338). A posting containing instructions to score 100 would trigger an alert.
- **Files:** `hunter.py` lines 751-788, 830-839, 1332-1338.
- **Recommendations:** Validate the score against deterministic gates (experience years extracted by regex, location match) before setting `To Apply`. Log scores that disagree with the gates.

### Resume stored in the sheet and in CI
- **Risk:** The resume (personal data) is stored in the Google Sheet's Settings tab (`hunter.py` line 108). Anyone with edit access to that sheet sees it. The README (line 48) recommends a private repository, but the repository's tracked CSVs contain job data and verdicts, which are committed to git on every CI run.
- **Files:** `hunter.py` lines 107-108, 1044-1057; `.github/workflows/job_hunter.yml` lines 45-58; `README.md` line 48.
- **Current mitigation:** `.gitignore` excludes `Resume.pdf` and `resume.txt` (lines 10-12) and secret-like filenames (lines 4-6).

### Spreadsheet formula injection is partially mitigated
- **Mitigation in place:** `_safe_cell` (line 1017-1019) prefixes `=`, `+`, `-`, `@`, tab and CR with an apostrophe. It is applied to the label, location, verdict and gaps (line 987-991), but not to `self.posted` or `self.url`. Those are generated by the script or constrained to `https` by `normalize_url`, so the risk is low.
- **Files:** `hunter.py` lines 980-993, 1017-1019.

### Non-ATS URLs are allowed to reach the sheet only through ATS classification
- **Mitigation in place:** `classify_url` (line 278-295) restricts hydration to six ATS hosts. `_hydrate_page` (line 644) fetches arbitrary pages only after classification. This is sound but depends on the host allowlist remaining correct.

### Service account JSON accepted as a file path
- **Risk:** `load_service_account` (line 1022-1030) accepts either raw JSON or a filesystem path. A misconfigured environment could read an unintended file.
- **Files:** `hunter.py` lines 1022-1030.
- **Impact:** Low, since the variable is set by the operator.

---

## Performance Bottlenecks

### Ashby board re-downloaded per job
- **Problem:** `_hydrate_ashby_api` (line 556-561) fetches the entire company job board JSON for every posting. Ten postings from one company cause ten identical full-board requests.
- **Files:** `hunter.py` lines 556-561.
- **Improvement path:** Cache board responses per company within a run (a dict keyed by company).

### Groq pacing is fixed and conservative
- **Problem:** `_pace` enforces `llm_interval = 2.2` seconds between every call (line 894-898, 219), and `TokenBudget` reserves 90% of TPM (line 861). A 30-job run therefore takes at least about 66 seconds of pacing plus hydration time.
- **Files:** `hunter.py` lines 219, 846-866, 894-898.
- **Impact:** Acceptable at current volumes; becomes the bottleneck if `MAX_JOBS_PER_RUN` is raised.

### Full-column reads each run
- **Problem:** `seen_urls` reads entire tracker and archive columns on every run (line 1121-1122). `bootstrap` also calls `worksheets()` and `get_all_values()` on each run (line 1046, 1081).
- **Files:** `hunter.py` lines 1046, 1081, 1119-1123.
- **Impact:** Adds Sheets read calls (per-minute quota). Grows linearly with the Seen_Archive size, which is unbounded.

### Input truncation drops requirement text
- **Problem:** The job description is truncated to 7000 characters (`JD_CHARS`, line 745; used at line 837) and the resume to 7000 characters (`RESUME_CHARS`, line 746; used at line 834). Many postings place "Requirements" after long "About us" sections, so the experience gate can be silently dropped. Long resumes lose their final sections (often skills or projects).
- **Files:** `hunter.py` lines 745-746, 830-839.
- **Fix approach:** Extract the requirements section, or truncate from the middle with a logged warning, and log when truncation occurs.

---

## Fragile Areas

### Hydration relies on ATS-specific JSON shapes
- **Files:** `hunter.py` lines 521-627 (Greenhouse, Lever, Ashby, Workable, SmartRecruiters).
- **Why fragile:** Field names such as `first_published`, `descriptionPlain`, `publishedAt` and `sections.jobDescription.text` are undocumented or semi-public. A rename degrades to empty fields without an exception, so `hydrate_posting` may pass through a posting with no date or an empty location. The only guard is the 200-character description minimum.
- **Safe modification:** Add a per-ATS fixture test that asserts the required fields are non-empty.
- **Test coverage:** `tests/test_hunter.py` contains `HydrationErrorTests` (line 239) and `ParseTests` (line 424). Live API behavior is not tested.

### Ashby "not on board" fallback can accept closed pages
- **Files:** `hunter.py` lines 703-713.
- **Why fragile:** If the Ashby board API returns no matching job, the code scrapes the posting page and treats any page with more than 200 characters of text as open. Closed-job pages with boilerplate can exceed this threshold.
- **Safe modification:** Check for the ATS's known closed-job markers, or require a `JobPosting` JSON-LD block.

### Single global Groq fallback flag
- **Files:** `hunter.py` lines 749, 887, 889-892, 929-932.
- **Why fragile:** `_fallback_until` is set on any 429 from the primary model and holds for 90 seconds across all jobs. If `GROQ_MODEL` equals `GROQ_FALLBACK_MODEL` (misconfiguration), `self.budgets` collapses into one entry (line 882-885) and the fallback logic silently has no effect.
- **Safe modification:** Validate that the two model names differ at startup.

### Regex-based title exclusion has edge cases
- **Files:** `hunter.py` lines 179-184.
- **Why fragile:** Whole-word matching with `(?<![A-Za-z0-9])` excludes words adjacent to underscores or hyphens differently from the search query builder, which uses `-intitle:` and does not match the same boundaries. A title such as "Senior-Marketing" is excluded locally but may appear in search results.
- **Test coverage:** `QueryTests` (line 50) and `ProcessTests` (line 267) cover some cases. Hyphenated and punctuation-adjacent titles are not evident.

### Legacy file diverges from live code
- **Files:** `legacy/hunter_local_scoring.py` (1292 lines), `legacy/tracked_jobs.local-scoring.csv`.
- **Why fragile:** The archived script is a separate implementation with the older CSV schema (`Date_Found_UTC`, `Score`, `Status`, ...). Nothing imports it, but future changes could be applied to the wrong copy.
- **Recommendation:** Keep `legacy/` out of any search or refactor scope, or move it to a git tag.

---

## Dependencies at Risk

### Groq model defaults
- **Risk:** Defaults are `llama-3.3-70b-versatile` and `llama-3.1-8b-instant` (`hunter.py` lines 214-215). Model names are retired by providers over time, and a retired name currently causes permanent archiving (see Failure and Retry Behavior).
- **Impact:** All scoring fails and rows are archived as errors.
- **Migration plan:** Pin the model in the sheet or env, validate it at startup with a single test call, and fail fast with a non-archiving error.

### Python version and unpinned transitive dependencies
- **Risk:** CI uses Python 3.12 (`.github/workflows/job_hunter.yml` line 22). `requirements.txt` uses ranges (`requests>=2.32,<3`, `gspread>=6.0,<7`, etc.) with no lockfile and no hashes.
- **Impact:** Upstream releases within the ranges can change behavior silently (for example, `gspread` 6.x changes to `append_rows` or `batch_update`).
- **Migration plan:** Commit a lockfile (`pip-compile` or `uv lock`) and pin the CI install to it.

### Google Sheets as the only database
- **Risk:** Sheets API quotas (read and write requests per minute) and the 2000-row limit on the status dropdown (line 1104) make the sheet a scaling bottleneck. The dropdown silently stops covering rows beyond 2000.
- **Migration plan:** Keep the sheet as a view, and move the seen-state into a small local store committed to the repo or into a persistent cache keyed by `(ats, company, job_id)`.

---

## Missing Critical Features

### No operational alerting
- **Problem:** The only outbound notifications are job matches. Startup failures (exit 2), persistent Groq or ATS outages and daily-quota exhaustion produce no notification. The user has to open the Actions tab to discover a silent failure.
- **Blocks:** Reliable unattended operation.

### No retry state for failed jobs
- **Problem:** There is no column or store that records an attempt count or last error, so a job cannot be retried after a fix without manually deleting its archive row.
- **Blocks:** The retry behavior described in the README.

### No re-evaluation when the resume or settings change
- **Problem:** Archived jobs (scores under 50, stale, closed, errors) are never revisited. Editing `Resume_Text` or `Target_Roles` does not re-score them.
- **Blocks:** Benefiting from resume improvements on jobs already seen.

### No alert retry or "alerted" state
- **Problem:** See Seen / Evaluated / Alerted State above.
- **Blocks:** Trustworthy notifications.

---

## Test Coverage Gaps

### Test suite was not executed for this analysis
- **What's not tested here:** The suite in `tests/test_hunter.py` (46 test methods across 13 classes) was read but not run. Pass or fail status is unknown.
- **Files:** `tests/test_hunter.py`.
- **Risk:** Any of the gaps below may already be partially covered; verify before writing new tests.
- **Priority:** High (run before refactoring).

### Permanent-archive paths
- **What's not tested (to verify):** That a Groq HTTP 400 that is not `json_validate_failed` archives the job permanently; that an HTTP 403 from an ATS archives the job permanently; that a short description archives the job permanently.
- **Files:** `hunter.py` lines 722-732, 942-946, 1302-1304, 1329-1331.
- **Risk:** Silent loss of every job during a misconfiguration.
- **Priority:** High.

### Alert failure path
- **What's not tested (to verify):** That a Telegram failure after `append_jobs` leaves the row recorded and sends no retry.
- **Files:** `hunter.py` lines 1399-1404.
- **Priority:** High.

### Duplicate variants
- **What's not tested (to verify):** `boards.greenhouse.io` vs `job-boards.greenhouse.io` for one job; SmartRecruiters with and without slug.
- **Files:** `hunter.py` lines 248-295.
- **Priority:** Medium.

### Date fallback behavior
- **What's not tested (to verify):** An old Greenhouse posting with a recent `updated_at` and no `first_published`; an undated posting passing the stale gate; naive timestamp handling in `parse_posted`.
- **Files:** `hunter.py` lines 416-448, 521-534, 1311-1317.
- **Priority:** Medium.

### CSV mode across CI runs
- **What's not tested:** That `seen_archive.csv` survives a CI run in CSV mode. The workflow does not commit it (see below), so this would have caught the loss.
- **Files:** `.github/workflows/job_hunter.yml` lines 46-59, `hunter.py` lines 1139-1200.
- **Priority:** High.

---

## Workflow and Repository Hygiene

### Seen_Archive is not persisted in CSV mode
- **Issue:** In CSV mode (`GOOGLE_SHEET_ID` unset), `CsvStore` writes rejected and closed URLs to `seen_archive.csv` (`ARCHIVE_PATH`, `hunter.py` line 66). The workflow runs `git add tracked_jobs.csv` only (`.github/workflows/job_hunter.yml` line 54). `seen_archive.csv` is not in `.gitignore`, so it is also not ignored. The result is that every CI run starts with no archive, re-fetches and re-scores previously rejected jobs, and spends Groq tokens on them. The `legacy` migration path (`hunter.py` lines 1162-1181) also moves rows into this file, so migrated low scorers are lost in the same way.
- **Files:** `.github/workflows/job_hunter.yml` line 54; `.gitignore`; `hunter.py` lines 66, 1139-1200.
- **Fix approach:** Add `seen_archive.csv` to the `git add` line in the workflow, or make the CSV-mode CI path rely on the sheet only and fail fast when `GOOGLE_SHEET_ID` is absent.

### Tracked CSV uses an outdated schema
- **Issue:** The committed `tracked_jobs.csv` header is `Date_Found_UTC,Score,Status,Company_or_Title,Verdict,Missing_Gaps,URL,Date_Posted`, which differs from `TRACKER_COLUMNS` (`hunter.py` lines 49-60). Every CSV-mode run triggers the migration branch (`CsvStore.bootstrap`, line 1162). The `tracked_jobs.gemini-scored.csv` file is not referenced anywhere in the code.
- **Files:** `tracked_jobs.csv`, `tracked_jobs.gemini-scored.csv`, `hunter.py` lines 1162-1181.
- **Fix approach:** Migrate the committed CSV once, commit the result, and delete unreferenced artifacts.

### Stray and duplicated artifacts
- **Issue:** `tracked_jobs.gemini-scored.csv` (root) and `legacy/tracked_jobs.local-scoring.csv` contain job data that is committed to git. `legacy/hunter_local_scoring.py` duplicates much of the pipeline logic.
- **Files:** `tracked_jobs.gemini-scored.csv`, `legacy/`.
- **Fix approach:** Remove or archive to a tag.

### Workflow runs the CSV commit step even in Sheet mode
- **Issue:** The "Commit CSV backup" step runs on every execution (`if: always()`, line 47). In Sheet mode it is a no-op because the CSV is not modified, but it still performs a `git pull --rebase` only when there is a diff. This is low risk; the comment in the workflow states the intent.
- **Files:** `.github/workflows/job_hunter.yml` lines 47-59.

---

*Concerns audit: 2026-10-14*
