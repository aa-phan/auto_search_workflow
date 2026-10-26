---
last_mapped_commit: aa1bab2d3c3e37ac119cd898b2e4f42a50f276fe
last_mapped_at: 2026-10-24
---
# Codebase Concerns

**Analysis Date:** 2026-10-24

Scope: full repository (`/Users/aphan/auto_search_workflow`); `legacy/` is archived reference only. Starting points were `STATUS.md` ("Known gaps / risks", "Next milestone"), `DECISIONS.md` (D-01..D-47), `PILOT_LOG.md`, `SPEC.md` and `AGENTS.md`; each item below was then checked in code. Items are marked **verified in code** (read in the named file) or **from docs** (stated in STATUS/DECISIONS/SPEC and not re-measured here). `.env`, `Resume.pdf`, `resume.txt` and service-account JSON were not read; only their existence and git status were checked.

## Priority Summary

| # | Concern | Severity | Area |
|---|---------|----------|------|
| 1 | Alert path marks a job `alerted` even when no channel delivered it | Medium (contract; not live: production has Telegram configured) | Known bugs |
| 2 | Non-HTTP alert exceptions retry forever with no bound | High | Known bugs |
| 3 | Events ledger growth toward the 10M-cell limit; storage fix (D-43) unbuilt | High | Scaling |
| 4 | SmartRecruiters polling enabled against `robots.txt` `Disallow: /` (D-38) | High (owner-accepted) | Security / compliance |
| 5 | Unproven operating choices now acting live (floor 2.0, D-47 early release) | Medium | Fragile areas |
| 6 | `hunter.py` monolith (1,981 lines) and long functions | Medium | Tech debt |
| 7 | Sheet lease is not atomic; relies on the GitHub concurrency group | Medium | Fragile areas |
| 8 | Validation and re-check backlog; waiting-list freshness | Medium | Performance / coverage |
| 9 | Resume text sent to Groq on every scoring call; no recorded decision | Medium | Security / privacy |
| 10 | Telegram text truncated after HTML is built | Low | Known bugs |
| 11 | Watchdog and hourly cadence depend on external triggers outside the repo | Medium | Fragile areas |
| 12 | Coverage limits (search, title gate, relevance snapshot) | Medium (by design) | Known bugs / coverage |

---

## Tech Debt

**`hunter.py` is a single 1,981-line module:**
- Issue: entry point, configuration, Sheet store, Groq client, Telegram/webhook delivery, inventory and discovery glue and the CLI all live in one file. The largest units are `SheetStore` (182 lines, `hunter.py` ~L1190-1380), `main()` (170 lines), `GroqClient` (136 lines), `hydrate_posting` (75 lines), `Settings` (68 lines) and `send_alert` (57 lines, `hunter.py` L1427).
- Files: `hunter.py`, with the other large modules `pools.py` (792 lines), `reporting.py` (938), `inventory.py` (896), `boards.py` (680), `pipeline.py` (633), `state.py` (615), `dashboard.py` (523).
- Impact: review and mutation testing of one behaviour touch a file that every subsystem shares; a regression in delivery code is hard to isolate. `AGENTS.md` pins `hunter.py` as the entry/orchestration file, so any split must keep that role.
- Fix approach: move pure pieces out without behaviour change first: Groq client to its own module, Sheet store to `sheets.py`, alert delivery to `delivery.py`. Keep `hunter.py` as the CLI. Cover the move with the existing 527 test functions in `tests/` before and after.

**Broad exception handlers in the state path:**
- Issue: 13 `except Exception` in `hunter.py`, 8 in `pipeline.py`, 4 in `inventory.py`, 3 in `state.py`, 1 each in `boards.py` and `dashboard.py`. Several are intentional containment (dashboard refresh, lease release), but the alert path (below, Known Bugs #2) classifies failures from the exception shape.
- Files: `hunter.py`, `pipeline.py` (around L586-600), `inventory.py`, `state.py`.
- Impact: a programming error is indistinguishable from a transient outage unless the handler checks the exception type.
- Fix approach: narrow handlers to the request and parse errors each stage expects, and let programming errors fail the run loudly (the run then shows as `failed` in `Runs`).

**Long functions with many responsibilities:**
- `main()` in `hunter.py` (170 lines) selects modes, takes the writer lease and runs the poll; `make_evaluator` (57 lines) builds the scorer closure.
- Fix approach: split CLI modes into functions with one entry each; keep `writer_lease` wrapping behaviour identical.

---

## Known Bugs

**1. A job is recorded as `alerted` when no delivery channel accepted it (contract conflict):**
- Symptoms: with neither Telegram nor the webhook configured, `send_alert` returns `False` (`hunter.py` ~L1427-1484) and the poller still records the job as `alerted` with `channel: "none"`, then sets `st.alerted = True`, so no retry is scheduled.
- Files: `pipeline.py` (around L594-600: `sent = d.send_alert(...)`, `pending_events.append(lg.Event(... lg.ALERTED ...))`, `st.alerted = True`); `hunter.py` (`send_alert`, `ALERT_WEBHOOK_URL`, `TELEGRAM_*`).
- Trigger: a run with the Telegram secrets missing or empty. Not reproduced live; the code path is verified by reading.
- Contract: `AGENTS.md` rule 4 (seen / evaluated / alerted kept separate; a failure leaves later stages undone and retryable) and `SPEC.md` "Delivery" (a failed alert is retried; "delivered alert = an alerted event whose channel accepted the message", `SPEC.md` ~L135). The dashboard's definition already excludes `channel: "none"`, but the ledger state does not.
- Orchestrator check (2026-10-24): confirmed in code, but scope is narrow. `send_alert` returns `False` only when NO channel is configured; a real Telegram or webhook failure raises (`raise_for_status`) and is retried. Production has Telegram configured (20 of 20 pilot alerts sent), so no live alert has been lost this way. It matters only for a deployment without any channel.
- Workaround: the workflow's configuration check names missing secrets (`STATUS.md` line 74); whether that check blocks the run before the poll was not verified in this pass.
- Recommendation (finding, not a fix): record `alerted` only when `sent` is `True`; otherwise write a failure event and leave the job retryable. Owner to confirm, because it changes SPEC-visible retry behaviour.

**2. Non-HTTP alert exceptions retry without limit:**
- Symptoms: the alert `except` branch (`pipeline.py` ~L586-596) decides whether to bound a failure with `getattr(getattr(exc, "response", None), "status_code", 500) < 500`. For any exception without an HTTP response (a `ValueError` from formatting a malformed row, a `KeyError`, a JSON encode error) the default is 500, so the condition is false and the failure is not recorded. The job is retried on every run and never reaches the 5-attempt bound in SPEC "Failures".
- Files: `pipeline.py` L593; `hunter.py` `send_alert`.
- Impact: one deterministic bug in alert formatting keeps one job failing forever, with a warning in the log and `alerts_failed` counted each run; the run may show `degraded` without a clear cause.
- Fix approach: treat exceptions without a response as bounded permanent failures after N attempts, or classify them explicitly (network errors transient, everything else bounded). Add a mutation test on the classifier.

**3. Telegram text cut after HTML is built:**
- Symptoms: `send_alert` joins HTML lines and truncates with `"\n".join(lines)[:4096]` (`hunter.py` ~L1452). A cut inside a tag such as `<a href=...>` or an entity makes Telegram return 400 "can't parse entities". The rejection is a 4xx and is bounded to 5 attempts, after which the alert is abandoned.
- Likelihood: low. The verdict length cap upstream was not confirmed in this pass.
- Fix approach: cap each free-text field (`verdict`, `gaps`, title) before escaping, and never cut the joined HTML.

**4. Alerts are at-least-once (documented, still open):**
- Symptoms: a crash between `send_alert` and the Sheets/Events write produces a duplicate alert on the next run. `SPEC.md` "Failures" says so; `STATUS.md` pilot week 1 measured 0 duplicates in 20 alerts.
- Fix approach: none planned; the risk is accepted in the contract. The tracker's duplicate protection (`tracked_keys`) limits duplicate rows but not duplicate messages.

**5. Coverage limits by design (documented in SPEC/STATUS):**
- Search cannot promise full coverage of the 12-hour window (`STATUS.md` ~L173); live, most search slots return 0 results (`STATUS.md` ~L174).
- A board's relevance is a snapshot: a waiting board that posts a relevant job is re-checked only on the validation cycle (`STATUS.md` ~L179). At the pilot, 12,460 validated boards were overdue (`STATUS.md` line 17).
- Title-gate leaks: "Community Associate" (often front desk) passes the broadened Settings; the exclusion list does not cover it (`STATUS.md` ~L198).
- Baseline jobs are never scored (`SPEC.md` baselining). This is intended, but it means a relevant job posted before a board's first read is never alerted.

---

## Security Considerations

**SmartRecruiters polling against `robots.txt` (owner-accepted, D-38):**
- Risk: `api.smartrecruiters.com/robots.txt` says `User-agent: *` / `Disallow: /` (per D-38, fetched 2026-10-15). Polling is enabled in production by `ALLOW_SMARTRECRUITERS_BULK: "1"` in `.github/workflows/job_hunter.yml` (line 74) and `.github/workflows/inventory.yml` (line 76). `SPEC.md` ~L41 says bulk validation is off by default and that the override is opt-in.
- Files: `.github/workflows/job_hunter.yml`, `.github/workflows/inventory.yml`, `boards.py` (parking logic), `SPEC.md` ~L41, `DECISIONS.md` D-38.
- Current mitigation: only monitored boards are polled hourly; validation spacing for SmartRecruiters is raised to 1.0 s; the override is written to `Runs.Notes`; a 429 triggers provider backoff.
- Recommendations: this is a recorded decision, so it is flagged, not changed. Owner to reconfirm the D-38 risk acceptance, and set the reversal (remove the two lines) as the pre-agreed response if SmartRecruiters objects. Note that `SPEC.md` ~L41 still describes the default, not the deployed override.

**Personal data sent to a third-party LLM:**
- Risk: the resume text (stored in the Sheet's `Settings > Resume_Text`) is sent to Groq in each scoring prompt (`hunter.py` `GroqClient`, around L895-940). `DECISIONS.md` D-09 covers storage and git ignores only; it records no decision on sending the resume to a third-party model.
- Current mitigation: the Groq key is a secret; the endpoint is `https://api.groq.com/openai/v1/chat/completions` (`hunter.py` L125); the Sheet is private.
- Recommendations: record an explicit decision on Groq's data handling for the account in use; confirm the Groq account's retention settings.

**Webhook payload:**
- Risk: `ALERT_WEBHOOK_URL` receives the title, company, score, verdict, gaps, location and apply URL of every alert (`hunter.py` `send_alert`, `cfg.webhook_url`). There is no allowlist or signature, and the URL is a secret whose value is not in the repository.
- Recommendation: keep the URL in secrets only (already the case in `job_hunter.yml` line 67); if the webhook is ever shared, rotate it.

**Repository visibility:**
- Resolved 2026-10-26 (D-48): the repository is public by owner decision; history holds no job-search CSVs; keep logs free of job content and secrets.

**Positive checks (verified in code):**
- Secrets are environment variables and GitHub secrets only. `git ls-files` lists no `.env`, `Resume.pdf`, `resume.txt`, service-account JSON or `tracked_jobs*.csv`; `.gitignore` covers all of them (`.env`, `.env.*`, `*service-account*.json`, `*credentials*.json`, `Resume.pdf`, `resume.txt`, `tracked_jobs*.csv`, `state/`).
- Local files that do exist and are ignored: `.env` (contents not read), `Resume.pdf`, `resume.txt`, `tracked_jobs.csv` (mode 600), `state/*.csv` (local copies of the registry and ledger, job data).
- Telegram HTML is escaped with `html.escape` before it is sent (`hunter.py` `send_alert`).
- No `shell=True`, `verify=False`, `eval(`, `pickle` or `yaml.load(` was found in the Python files.
- Workflows declare `permissions: contents: read` (`job_hunter.yml` L46, `inventory.yml` L25, `watchdog.yml` L26).

**Supply chain:**
- Actions are pinned by tag (`actions/checkout@v4`, `actions/setup-python@v5`, `actions/cache@v4`), not by commit SHA (`.github/workflows/*.yml`). Dependencies are in `requirements.txt` (147 bytes) ; no lockfile appears in the repository listing.
- Fix approach: pin actions by SHA; add a lockfile or pinned versions for `requests`, `gspread` and the Google auth packages.

---

## Performance Bottlenecks

**Events ledger growth (the largest structural risk):**
- Problem: the `Events` tab is append-only and holds every observed job ID, including the baselines of admitted boards. Pilot week 1: 140,668 rows, about 2,900 rows a day (`STATUS.md` line 17). Storage measurements (`DECISIONS.md` D-43, 2026-10-17): 122,003 rows = 854,021 cells, about 7 cells per row; 93% of rows are baselines and 6.6% are identity-only rows (title-gated or stale postings), 0.4% operational.
- Files: `state.py` (ledger, `replay`), `hunter.py` (the Events write path), `storage_report.py`, `reporting.py`, `dashboard.py`.
- Cause: every run replays the whole ledger to rebuild `seen`; `Load_S` rose from 7.5 s at fewer than 118k rows to 8.0 s at 121k (no per-row slope yet).
- Projection: the 10,000,000-cell limit is about 1.4M rows at 7 cells per row. Admission waves are large: the first refill runs added 5,273 and 6,919 job IDs (`STATUS.md` ~L200), and D-43 estimates +200 boards would add about 29,300 rows at admission. The dashboard and the pilot report read the whole Events tab after each run.
- Status: the fix in D-43 (an `Identity` tab with ID chunks, a `Daily` counter tab, archiving terminal rows) is proposed and **not implemented**; `DECISIONS.md` D-43 says the review is "after the pilot", and the pilot ended 2026-10-22 without a recorded decision.
- Fix approach: follow the D-43 migration order (write the new tabs in parallel, compare derived `seen` sets for several days, delete only with an exported copy kept). Schedule the decision now that the pilot has ended; `STATUS.md` names Events growth as a watch item.

**Run duration and quota headroom:**
- Problem: run median 113 s, max 770 s against the 25-minute poll timeout (51%) (`STATUS.md` line 17). The inventory validation run took 1,121 s for 5,000 re-checks, inside its 1,500 s `--max-seconds` budget and the 40-minute job timeout (`STATUS.md` ~L200).
- Limits: Google Sheets reads peak at 12.4 per minute against a quota of about 60 (`STATUS.md` line 17); `quota_retrying` waits 20, 40 and 65 seconds (`hunter.py` ~L1149). Growing to 700 boards raises per-run reads and writes.
- Fix approach: keep `Runs` timing columns under review after each capacity change (`Duration_S`, `Sheets_Reads`, `Sheets_429`); the existing pilot report already measures them.

**Validation backlog:**
- Problem: about 21,000 validated boards must be re-checked; the 5,000-board daily budget is about two days per full pass after D-47 (`DECISIONS.md` D-47). Lever's `Crawl-delay: 1` limits validation to about 44 minutes per full pass (`STATUS.md` ~L178).
- Impact: a waiting board's relevance can be up to one pass old when it is admitted (`STATUS.md` ~L179).
- Fix approach: measure re-check flip rates (`revalidation_stats` in the Discovery tab, already recorded) before raising budgets further.

---

## Fragile Areas

**Unproven operating choices now act on live data:**
- Files: `pools.py` (`GRADUATION_FLOOR` = 2.0, weekly rebalance, `early_releases`, `apply_releases`), `DECISIONS.md` D-30, D-45, D-47.
- Why fragile: `D-30` lists 80/20 pools, 7-day trials, 20 replacements, the score weights, margin 1.0, two weak cycles and 84 complete polls as unproven. `D-45` sets the floor at 2.0. `D-47` moved the floor from the weekly cycle into every poll run, so 221 trials were released on 2026-10-24 before the first weekly cycle had produced evidence (`STATUS.md` ~L200). `AGENTS.md` rule 7 forbids tuning scores or adding features until freshness and delivery are proven; the pilot criteria were met (`STATUS.md` line 17), but the pool rules have not been tested by a real weekly cycle.
- Safe modification: keep `Rebalance_Mode` and `Max_Active_Boards` as Settings changes, not code edits. Read the first real `rebalance_report` (due about 2026-10-29 01:00 UTC; about 274 graduations expected) before changing any threshold.
- Test coverage: 3 unit tests (`EarlyReleaseTests`) and 2 pipeline tests for D-47; the weekly cycle at 700 boards has no live run yet.

**Sheet lease is not atomic:**
- Files: `state.py` (`SheetState.acquire_lease`, `holds_lease`, `release_lease`, L303-335), `hunter.py` (`LEASE_TTL`, `writer_lease`, L1588-1648).
- Why fragile: the Sheet has no conditional write, so acquisition is write-then-verify and two writers starting within about 3 seconds could both proceed (`SPEC.md` ~L39). A run that outlives its TTL (30 min poller, 45 min inventory) logs an error (`hunter.py` ~L1641-1644).
- Current mitigation: the shared GitHub concurrency group `job-hunter-state` (`job_hunter.yml` L52-54, `inventory.yml` L35-37, `cancel-in-progress: false`); local writes to a production Sheet are refused (exit 4, `hunter.py` ~L1601-1609); the file lease is a real `flock` (`state.py` ~L551-591).
- Safe modification: never run a writing command against the production Sheet from a laptop. Keep the concurrency group identical in every workflow that writes the registry.
- Residual window (from docs): the inventory importer re-reads a row's status just before writing, so a promotion in those milliseconds can be overwritten; job state is unaffected because it lives in `Events` (`STATUS.md` ~L170).

**GitHub drops waiting runs in a shared group:**
- Why fragile: GitHub keeps only the newest waiting run per concurrency group. A long inventory import can cause one hourly poll to be replaced by the next (`SPEC.md` ~L39). Gaps are detected by the watchdog and `Runs`, not prevented.
- Fix approach: keep the inventory run short (already bounded by `--max-seconds 1500`) and keep the watchdog's threshold (`WATCHDOG_WARN_HOURS`) visible.

**Header-name dependence in the tracker and Settings:**
- Files: `hunter.py` (`append_jobs`, `tracked_keys`, `tracker_rows`, `_tracker_header`), `SPEC.md` ~L105.
- Why fragile: renaming `Apply_URL`, `My_Status` or a Settings row breaks lookups. Since D-46, a missing `Apply_URL` stops the run before evaluation and alerts (`D-46` trade-off: no alert is sent while the header is missing). `STATUS.md` line 17 records the 2026-10-22 header clearing that caused this.
- Safe modification: never rename headers; the user may reorder columns. A second header-protection rule in the Sheet (owner action) would prevent a repeat.

**Dependence on external triggers outside the repository:**
- Files: `.github/workflows/job_hunter.yml` (`cron: "17 * * * *"`, `workflow_dispatch` with `trigger_source`), `.github/workflows/watchdog.yml` (`cron: "7,22,37,52 * * * *"`), `DEPLOY.md`.
- Why fragile: the hourly cadence comes from an external trigger (documented as cron-job.org in the workflow input description), not from GitHub's schedule. GitHub's own scheduled runs fired about every 4.7 hours (`DECISIONS.md` D-42). The watchdog runs on the same GitHub Actions platform and sends alerts through the same Telegram bot, so one platform outage can stop both.
- Status (from docs): a second, external trigger for `watchdog.yml` is recommended and **not set up** (`STATUS.md` line 49). The watchdog's Telegram delivery, incident tab and a real outage were **not verified live** (`STATUS.md` ~L44).
- Fix approach: owner to configure the external watchdog trigger on a different scheduler from the hunter's trigger, and to send one real test notification.

**Groq model names and behaviour:**
- Files: `hunter.py` L333-337 (defaults `openai/gpt-oss-120b` and `openai/gpt-oss-20b`), `GroqClient` (L861-940), `GROQ_ATTEMPTS = 6`, `FALLBACK_HOLD_SECONDS = 90`.
- Why fragile: the requested models returned 404 `model_not_found` for this key (`DECISIONS.md` D-16, which still says "needs your OK"). Reasoning models need a 1,000-token output cap (D-16). The 429 fallback and `model_not_found` handling are mocked only (`STATUS.md` ~L152).
- Fix approach: record the owner's OK on D-16; add a live smoke check to the configuration step.

**Single 1,981-line module shared by every writer:** see Tech Debt above; a bad commit to `hunter.py` can break polling, delivery and reporting together. The watchdog avoids this by importing nothing from the hunter (`DECISIONS.md` D-42; asserted by a test).

---

## Scaling Limits

**Google Sheets as the database:**
- Current capacity: 10,000,000 cells per spreadsheet. Measured 854,021 cells for 122,003 Events rows (`DECISIONS.md` D-43), plus the `Boards` registry (about 22,000 rows of candidates).
- Limit: about 1.4M Events rows at 7 cells per row, before the `Boards` and tracker tabs.
- Scaling path: the D-43 proposal (identity chunks, daily counters, archive of terminal rows), then a real database if the Sheet becomes the bottleneck. The Sheets API quota (about 60 reads per minute per user) is the other limit (`STATUS.md` line 17).

**Monitored boards:**
- Current capacity: `Max_Active_Boards` = 700 (set by the user, `Rebalance_Mode` on; `STATUS.md` ~L193). Admission is 50 boards per run (`Max_New_Boards_Per_Run`).
- Limit: coverage is 53% of relevant boards after the 2026-10-24 refill (`STATUS.md` ~L200), and per-run ATS requests and Events growth grow with the monitored set.
- Scaling path: raise the cap only after the first weekly cycle and a run-duration check against the 25-minute timeout.

**Search budget:**
- Current capacity: 1,000 Tavily credits a month, 800 for scheduled runs (`SPEC.md` ~L46); 10 credits a run; a full rotation of 42 slots takes about 2.1 days (`DECISIONS.md` D-36). At 6 sites by 36 roles, the rotation is longer (`PILOT_LOG.md` 2026-10-23 21:21).
- Limit: search adds only a trickle of boards; "140 credits in 7 days, 20 a day, at the stop threshold" (`STATUS.md` line 15).
- Scaling path: none planned; the credit cap is a deliberate cost control.

---

## Dependencies at Risk

**Google Sheets API via `gspread`:**
- Risk: no conditional write (see Fragile Areas); quotas per minute; request shapes for charts and the dashboard were checked against the discovery schema but not against the real API (`STATUS.md` ~L59-60).
- Impact: a Sheets API change breaks reads and writes in every workflow.
- Migration plan: none; keep the store behind `SheetStore` / `CsvStore` so a database backend can replace it.

**Groq free tier:**
- Risk: tokens-per-minute budgets (`GROQ_TPM` default 8000, `hunter.py` L336); model names change (D-16).
- Impact: scoring falls back or stops; a transient failure is retried, but a stopped model is a configuration problem.
- Migration plan: keep the model names as settings (already environment variables) and the fallback model.

**Tavily search:**
- Risk: the account counter lagged (still 0 after about 55 credits, `STATUS.md` ~L100); cost is read from each response; a 432/433 blocks all spending until the month rolls over.
- Impact: credit accounting is local and can undercount usage made outside the app.

---

## Missing Critical Features

**Verified delivery on the real channel is not in place for the watchdog:**
- Problem: the watchdog's Telegram message, incident tab and a real outage/recovery have not been exercised live (`STATUS.md` ~L44).
- Blocks: trusting the "no outage for 2 hours" monitor during a real outage.

**No daily digest or structured operator alert (documented as not built):**
- Problem: `STATUS.md` line 64 lists the daily Telegram digest as "documented in SPEC and not built".
- Blocks: a daily check of delivery without opening the dashboard.

**Schedule for the storage decision:**
- Problem: D-43 has no decision date and the pilot is over.
- Blocks: safe growth past roughly 1.4M Events rows.

---

## Test Coverage Gaps

**Live integrations are mocked:**
- What's not tested live: Sheets writes beyond the one-off pilot runs (fake gspread worksheet in `tests/test_inventory.py` and `tests/test_hunter.py`); Telegram delivery of an alert from a real run (only the labelled delivery test); the Groq 429 fallback and `model_not_found` path; the watchdog's Telegram message, incident tab and real outage/recovery; the weekly rebalance at 700 boards (no real run yet).
- Files: `tests/test_hunter.py`, `tests/test_inventory.py`, `tests/test_watchdog.py`, `tests/test_pools.py`, `tests/test_core.py` and `tests/test_pools.py` (pipeline behaviour).
- Risk: the alert-classification defects (Known Bugs #1 and #2) would not be caught by live runs because they only fire when delivery fails.
- Priority: High for alert classification; Medium for the rest.

**Tests do not cover the alert-recording branch with no channel:**
- What's not tested: `send_alert` returning `False` and `pipeline.py` marking the job `alerted`.
- Risk: a silent drop when configuration is incomplete.
- Priority: High.

**Non-HTTP alert exceptions:**
- What's not tested: exceptions without a `response` attribute in the alert `except` branch (`pipeline.py` ~L593).
- Risk: unbounded retries (Known Bugs #2).
- Priority: High.

**Telegram length and entity limits:**
- What's not tested: messages near 4,096 characters containing HTML entities.
- Priority: Low.

**Event volume and load time:**
- What's not tested: replay and dashboard time at 100k+ Events rows with the 700-board mix (measured only at 121k rows, single point).
- Priority: Medium.

---

*Concerns audit: 2026-10-24*
