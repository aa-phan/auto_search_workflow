# STATUS

Last updated 2026-10-29 (Phase 3 dual-write storage deployed 17:46 UTC (f8c8263), first live evidence in "Phase 3 live verification (dual write)", D-57; before that 2026-10-29: plans 03-01..03-04 built and verified offline only; before that 2026-10-28: Groq plan decided, D-53: stay free, budget default 100,000 per model; before that 2026-10-26: Phase 2 governors and measurement built and verified offline only, owner decisions D-48..D-52; before that 2026-10-23: pilot week 1 closed; graduation floor D-45; tracker header refusal D-46; before that 2026-10-17: watchdog, pilot-report corrections and storage scoping, D-42 and D-43; before that operational dashboard, D-40; before that search provider Serper -> Tavily, D-36; before that board slot allocation, D-23..D-30; before that the discovery rotation / 12-hour window change, D-17..D-21). Read `SPEC.md` (contract) and `DECISIONS.md` (why) first.

## Phase 3 compact storage (D-57; plans 03-01..03-04)

Written 2026-10-29. **Built and verified offline (mocked); deployed to production 2026-10-29 17:46 UTC (f8c8263): what the live runs showed is in "Phase 3 live verification (dual write)" below, and every row of this table stays mocked unless that section says otherwise.** Nothing in the table below touched the real Google Sheet, Groq or Telegram: every check below ran against the CSV store, the in-memory Sheets fake (`tests/fake_sheets.py`), hand-built ledgers and fake ATS listings. `.venv/bin/python -m unittest discover -s tests` printed `Ran 787 tests ... OK` at the end of plan 03-04 (767 after 03-03; 20 new tests in this plan).

| Check | Result | Live or mocked |
|---|---|---|
| Identity and Tally write order (Events, Identity, Tally, Boards), the Identity codec (kind letters, `%` escapes), the 40,000-character cell and 1,000,000-character request limits (plan 03-01) | pass | **mocked** |
| Compact-mode write (no baseline Events row) and the interrupted baseline: a cut-off Identity write is a baseline pass again, nothing alerted, each ID once (ROADMAP success criterion 4) | pass | **mocked** |
| Seed and repair: the first run builds Identity and the historical Tally from the loaded ledger; an interrupted seed is completed without writing an ID or a run twice | pass | **mocked** |
| Parity layers 1 to 4 (seen set, Tally recount, state counts, reported figures) with a mutation test per named difference kind; declared classes listed, not counted | pass | **mocked** (synthetic ledgers up to 194,000 rows; real size untested) |
| The parity clock: 3 complete UTC days, 12 checked runs each, one admission, a difference restarts it, today never counts | pass | **mocked** |
| Reports read the merged view (Dashboard, pilot reconciliation, storage counts): same figures from all Events rows and from Identity + Tally + kept rows, in UTC and America/Chicago | pass | **mocked** |
| Dashboard Storage line, `READY TO CUT OVER` (dual mode, bar met only), NEEDS ATTENTION row `storage parity difference`, the P3-11 note (plan 03-04) | pass | **mocked** (rendered grid inspected as data; not rendered in a Sheet) |
| `--storage-parity` read-only command: exit 0 / 1 / 2, zero writes asserted by a full snapshot of the Sheets fake, no writer lease (plan 03-04) | pass | **mocked** |
| Workflow input `storage_parity` (boolean, fixed command, excluded from the poller and from `REQUIRE_TELEGRAM`) | pass | **mocked** (static test of the workflow file; the workflow was never run) |

**Mutation checks** (each applied with the bytecode cache off, observed failing, then reverted): listed per plan in the 03-01..03-04 SUMMARY files. Plan 03-04's: readiness without the dual-mode condition, all stored differences shown instead of three, the sanitiser removed, the P3-11 note always shown, a row for declared-only differences, the exit code always 0, a Discovery write inside `--storage-parity`, a writer lease taken, the 50-line limit raised, the not-seeded refusal removed. One mutant survived: dropping `seeded is not None` from the readiness test, because `StorageState.bar` already returns not met for an unseeded state (a redundant guard, kept on purpose).

**Not verified live (each is a plan 03-05 observation or an owner check):**
- Whether a warning-only protection on `Identity` still lets the service account write (research assumption A2). If it does not, the first run after deploy fails its Identity write: in dual mode the run is `degraded` and `Events` stays authoritative.
- The seed's size and time at about 200,000 rows (about 190,000 IDs, a few hundred cells) and how Sheets stores a 40,000-character `IDs` cell.
- The parity check's seconds and memory at about 200,000 rows, plus its extra Job Tracker read per run (an offline scale check took 6.4 s on a synthetic 194,000-row ledger).
- The Sheet render of the new Storage line and of the NEEDS ATTENTION row.
- That the `storage_parity` input appears and runs in GitHub Actions. Its `Check configuration` step still lists `GROQ_API_KEY` as required (as for every other report), although `--storage-parity` itself needs no Groq key.
- Everything after the dual-writing deploy: the cutover, the fold and the restore are plans 03-06 and 03-07 and are not built yet.

**Migration notes for the first run after deploy (plan 03-05):**
- Two hidden tabs appear, `Identity` and `Tally`. `Identity` is protected with a warning, so Sheets asks for confirmation before a hand edit; do not edit it (a removed ID can make an old job look new).
- The `Discovery` tab gains the key `storage` (JSON: mode, seed time, the parity days, the last check). Do not edit it; a damaged key restarts the clock and is never read as ready.
- The first run seeds about 200,000 IDs into `Identity` and the historical `Tally` (one row per run and run time) from the ledger it already loads, under the writer lease. Nothing in `Events` is changed or deleted, and detection, evaluation and alerts do not depend on the new tabs.
- The parity clock starts the next full UTC day after the seed day (the seed day never counts). Three clean complete days, each with at least 12 checked runs, and one board admission among them are needed before the Dashboard says `READY TO CUT OVER`; the cutover is a separate owner step (plan 03-06).
- `Events` keeps growing at today's rate until the cutover, plus `Identity` and `Tally`.

## Phase 3 live verification (dual write)

Pushed `main` (`c8c559d..f8c8263`) at 2026-10-29 17:46:37 UTC on the owner's choice `deploy-and-dispatch`. Everything marked **live** below was read from public GitHub Actions logs (`gh`) of runs on f8c8263; the agent has no Sheet credentials, so anything inside the Sheet is an **owner check pending**. Log values below are counts, run ids and setting names only; the three logs were scanned for secret patterns before quoting (0 matches each). The workflow conclusion is the only outcome read: the run outcome cell (`ok` / `degraded`) lives in `Runs` and is not in the public log.

| Check | Result | Live or mocked |
|---|---|---|
| Deployment | `main` fast-forwarded and pushed 17:46:37 UTC; first run on f8c8263 is the dispatch below | **live** (git, `gh run list` headSha) |
| Seed run 40924656021 (manual dispatch 17:47:21 UTC, finished about 17:52) | workflow `success`; log: `Created the hidden Identity tab`, `Created the hidden Tally tab`, `Storage seed: 201789 IDs written in 991 Identity rows for 947 boards, 424 Tally runs written`; the seed took about 30 s (log time 17:47:47 to 17:48:16 UTC); `Run: boards 693 ok / 7 failed of 700, new jobs 211 (190 verified fresh), evaluated 4, alerts 0 sent / 0 failed`; no `storage write failed` or `storage repair failed` note anywhere in the log; no storage check line (a seed run does not check). The process ran about 4 min 25 s (17:47:31 to 17:51:56), inside the 15 min poll cutoff | **live** (public log) |
| Research assumption A2 (the warning-only protection on `Identity` does not block the service account) | the seed wrote 991 Identity rows without a write-failure note and the next run's check read all of them back (203,200 job keys compared, 0 differences), so the writes succeeded; the **confirmation prompt itself** is a Sheet-side fact | **live** for the service account's writes; prompt: owner check pending |
| First check run 40926644214 (the hourly external dispatch, 18:00:08 UTC, finished about 18:05) | workflow `success`; log line `Storage: mode=dual, 0 counted and 0 declared differences, 203200 job keys and 425 Tally runs compared, 1 checked runs today, 0 of 3 complete days toward the bar, admission seen no, check took 24.6 s`; `Run: boards 695 ok / 5 failed of 700, new jobs 34 (32 verified fresh), evaluated 2, alerts 0 sent / 0 failed`; no storage note. Counted differences as read: **0**; declared as read: **0** | **live** (public log) |
| Read-only parity run 40927423338 (`storage_parity=true`, 18:05:01 UTC) | workflow `success` (exit 0); report: `mode dual, seeded 2026-10-29T17:47:52Z`; compared: figures_logical 981, figures_reconcile_7d 46, figures_reconcile_all 46, figures_summary 1023, identity_entries 202028, seen_keys 203234, state_counters 4, tally_groups 426; `0 counted differences, 0 declared (listed, never counted); the check took 24.75 s`; `clock: 0 of 3 clean complete UTC days, admission seen no, bar met no`. Nothing was written (no poll, no lease) | **live** (public log) |
| Seconds the check adds | 24.6 s in the poller run and 24.75 s in the read-only run, both against the 22 min skip limit (`STORAGE_CHECK_CUTOFF_S`), well inside it; the offline estimate was 6.4 s on a synthetic 194,000-row ledger, so the live figure is about four times higher (the real Sheet read and the extra Job Tracker read are in it) | **live** |
| Whole-run time | the seed run and the first check run both took about 4 min 25 s of process time (the check run: 18:00:19 to 18:04:43 UTC); no poll, evaluation or alert cutoff note in either log | **live** |
| Storage line, NEEDS ATTENTION row, `Storage` Dashboard render, hidden tabs, Events row count | not readable from a public log | owner check pending (below) |

**The parity clock.** The seed time is 2026-10-29T17:47:52Z. The seed day never counts, so the first countable UTC day is **2026-10-30**. The bar needs three clean complete UTC days (2026-10-30, 2026-10-31, 2026-11-01), each with at least 12 checked runs and no counted difference, and one board admission among them; the earliest the Dashboard can say `READY TO CUT OVER` is therefore 2026-11-02 00:00 UTC, and any counted difference restarts it. The first check counted no differences, so the clock is running.

**Owner checks pending in the real Sheet (the agent cannot see the Sheet):**
1. `Identity` and `Tally` exist as hidden tabs (right-click a tab name, "Show hidden sheets").
2. Editing a cell in `Identity` asks for a confirmation (the warning-only protection). Do not actually change it.
3. The `Events` row count did not go down (it keeps growing; nothing in `Events` was shortened).
4. Dashboard: the Storage line shows dual mode with 0 differences and there is no `storage parity difference` row under NEEDS ATTENTION; no `READY TO CUT OVER` yet.
5. `Discovery` has the key `storage` (mode `dual`, `seeded_at` 2026-10-29T17:47:52Z). Do not edit it.
6. `Runs.Notes` of the 17:47 and 18:00 UTC runs contain no `storage` note.

**Not verified live:** the seed's behaviour when interrupted, repair of a removed ID, a counted difference (each only ever produced by mutation tests), the Dashboard render, and the cutover, fold and restore (plans 03-06 and 03-07, not built).

**Observations to carry forward (not acted on, AGENTS rule 7):** the parity run read 202,028 Identity entries and 203,234 seen keys against the seed's 201,789 IDs (the difference is the new postings the runs since the seed observed, as the zero-difference check implies; the entry and key counts are not the same unit as the seed's ID count and were not reconciled further here); two runs were dispatched by hand (the seed run at 17:47 and the parity run at 18:05), so the run statistics for 2026-10-29 17:00 to 18:10 UTC include them.

## Phase 2 governors and measurement (D-49..D-52; plans 02-02..02-06)

**Built and verified offline (mocked); deployed to production 2026-10-26 18:25 UTC (fc197c1). Live evidence is in "Phase 2 live verification" below; everything not listed there as live stays mocked.** Run `.venv/bin/python -m unittest discover -s tests` for the current count: **620 tests pass offline** at the end of plan 02-06 (612 at the end of 02-05; 520 offline tests were last recorded before this phase).

- **D-49 alert recording:** `alerted` is written only when a channel accepted the message; an alert no channel accepted stays pending and the run is `degraded`; sends without an HTTP response are bounded at 5 attempts; secrets are redacted from everything stored or logged; Telegram free text is capped before escaping.
- **D-50 Groq daily token budget per model (MEAS-03):** a persisted UTC-day budget per model (default was 170,000, provisional; **100,000 per model since D-53, 2026-10-28**, pushed 2026-10-28 20:02 UTC (`1d63416`); the owner read a post-push run reporting 100000 / 100000 in the Runs tab, 02-UAT test 3) with the last 20% reserved for verified-fresh jobs, fallback from the primary to the second model, budget-skipped jobs left pending with nothing recorded, and seven new Runs columns for tokens, cached tokens, completions and the `x-ratelimit-*` response header values.
- **D-51 run deadlines (MEAS-04):** board polling stops starting boards 15 min after the process started, Groq calls stop at 20 min and alert sends at 22 min, inside the 25 min workflow timeout; boards are polled longest-unpolled first; a poll or alert cut makes the run `degraded`, an evaluation cut leaves it `ok`; nothing is recorded against a cut board, job or alert.
- **D-52 Dashboard yield view (MEAS-01):** tracker rows per found-day by cohort with the 20-30 band, age when found, My_Feedback mix per cohort, and a tracker-versus-ledger reconciliation that names ledger-kept jobs missing from the tracker.
- **Groq read-outs (this plan, MEAS-02 / MEAS-03 visibility):** a Groq SYSTEM line on the Dashboard (today's UTC-day tokens per model against its budget, the 7-day split of scored evaluations by model, tokens per scoring call with its n, cached share, budget skips, evaluation cuts, poll cuts, alerts deferred) and Groq lines in the read-only pilot report's limits audit (tokens per scoring call with n, tokens per UTC day per model, cached share, governor counters, run duration p95, latest rate-limit header values) so measured consumption can be read from the public workflow log without credentials. Runs recorded before the token columns existed are not counted as zero-token runs (figures cover only runs that recorded tokens, and the line says how many).

- **D-55 owner-deleted tracker rows (2026-10-28):** the owner keeps `greenhouse|nadiacare|4459849009` deleted from the Job Tracker. A new Settings row `Tracker_Deleted_Keys` acknowledges such keys so they leave the NEEDS ATTENTION row and are counted apart. Offline-tested (mocked); **owner step:** add the row to the live Settings tab with that key (it is not added automatically).
- **D-56 governor test inputs (2026-10-28):** manual `poll_cutoff_minutes` / `eval_cutoff_minutes` dispatch inputs so the D-51 cutoffs can be fired live; scheduled runs leave them empty (defaults 15 / 20). The alert cutoff and the 5-attempt alert bound stay untestable live on purpose. Live result (run 40792640070, 2026-10-29 00:13 UTC; PILOT_LOG): the poll cutoff fired (214 of 700 boards skipped, all polled by the next run, worst board gap 60 min); the evaluation cutoff did not fire (no job was awaiting scoring); the alert cutoff and the 5-attempt bound are still unobserved live.

| Check | Result | Live or mocked |
|---|---|---|
| Alert recording and bounding (D-49): no accepting channel leaves the alert pending and the run degraded; five attempts without an HTTP response; 4xx/5xx handling | pass | **mocked** |
| Redaction of secrets from stored and logged text; Telegram free-text cap | pass | **mocked** |
| Daily budget, 20% reserve, fallback model, budget-skip leaves the job pending, forced-limit runs (budget at 0 and the next UTC day) (D-50) | pass | **mocked** |
| Deadlines and poll order (D-51): process-start anchor, poll / evaluation / alert cutoffs, Groq client deferral at the deadline, longest-unpolled first | pass | **mocked** (injected monotonic clock; no real run was cut) |
| Yield view (D-52): found-day buckets, local midnight, age buckets, feedback per cohort, reconciliation, four charts with fixed ids | pass | **mocked** (fake spreadsheet, requests checked offline; not rendered) |
| Groq read-outs: Dashboard Groq line, pilot limits-audit lines, counts-only public log | pass | **mocked** (hand-built Runs, ledger and Discovery records) |
| Dashboard render in the real Sheet (band lines flat at 20 and 30, new Groq line, four charts, `BAND_LINES_STACK` assumption A7), Groq console figures | **not verified live yet** (owner check pending / plan 02-08); the `Runs` columns and the delivery test were verified live, see below | plan 02-07 / 02-08 |

**Mutation checks (each applied, observed failing, then reverted):** 27 across plans 02-02..02-06 (5 on alert recording, bounding and redaction; 7 on budget, reserve, pre-check, persistence, daily-limit 429 and charging; 7 on deadlines, poll order and the process-start anchor; 5 on the yield view; 3 here: counting runs without recorded tokens in tokens per call fails the Dashboard 7-day test, removing the `x-ratelimit-*` filter fails the counts-only log test, and counting every timed run as a token run fails both audit tests). Details are in the 02-02..02-06 SUMMARY files.

**Migration notes:**
- **The `Runs` header widens by 11 columns, to 77, on the first run after deploy** (the new Groq token, limits, skip and cut columns); rows written before it stay as they are and read as unknown.
- **The Settings rows `Groq_Daily_Token_Budget` and `Groq_Fallback_Daily_Token_Budget` are optional** and absent from the live Settings tab; the run note names the value in force.
- **The Discovery tab gains the key `groq_budget`** (the persisted per-model budget for the UTC day).
- **SmartRecruiters stays polled** (D-54, 2026-10-28: the owner kept it; plan 02-09's parking is superseded and was not deployed).
- Deployed 2026-10-26 18:25 UTC (fc197c1): D-49..D-52 run in production from the 19:00 UTC run (see "Phase 2 live verification"). The Groq console figures (plan 02-08) are still to be read.

## Phase 2 live verification (2026-10-26)

Pushed `main` (fc197c1) at 2026-10-26 18:25 UTC on the owner's choice `deploy-with-delivery-test`. Everything marked **live** below was read from public GitHub Actions logs (`gh`) of runs on fc197c1; the agent has no Sheet credentials, so anything inside the Sheet is an **owner check pending**. Log excerpts below are counts, run ids, job keys and setting names only; the three logs were scanned for secret patterns (0 matches).

| Check | Result | Live or mocked |
|---|---|---|
| First production run on fc197c1 (run 40382764588, started 19:00:09 UTC, finished about 19:12:50) | workflow `success`; `Run: boards 699 ok / 1 failed of 700, new jobs 92 (84 verified fresh), evaluated 11, alerts 0 sent / 0 failed`; no poll, evaluation or alert cutoff note, no budget-reached note, no "no alert channel" note; the run took about 12.5 min, inside the 15 min poll cutoff | **live** (public log) |
| Run outcome and code version (pilot report 40384832233) | `workflow runs by outcome: 'ok': 206`, no unfinished run-start record; `Code_Version` fc197c17 recorded for 1 run from 2026-10-26T19:00:30Z, so the newest `Runs` row exists with the new code | **live** (read by the report from the Sheet; the cell values themselves are an owner check) |
| Groq daily budget (D-50) value in force | log line `groq budget 2026-10-26 UTC: openai/gpt-oss-120b 30826/170000, openai/gpt-oss-20b 0/170000 (last 20% for verified-fresh jobs)`: the persisted per-model budget works and the day's tokens are being counted | **live** |
| Groq budget note with its source ("... per UTC day from <source>") | **not in the public log**: `hunter.groq_budget_note` is appended to the run's notes after the settings notes are logged, so it is written to `Runs.Notes` only. Value 170000 / 170000 equals the code default, and the Settings rows are known to be absent, so the source is the default by inference | not verified live (owner check: `Runs.Notes` of the 19:00 run) |
| Cut and skip counters (D-51, D-49, D-50) | pilot report: `budget skips 0, deadline skips 0, runs with an evaluation cut 0, boards cut by the poll deadline 0, alerts deferred 0` over 206 timed runs (runs before the new columns count 0); 1 run has the columns, so this is "nothing was cut in the one run on the new code", not a test of the cutoffs | **live**, but the governors never fired: cutoffs, budget skip, fallback and deferral stay **mocked** |
| Pilot report Groq lines (run 40384832233) | `Groq calls 307 (HTTP 429: 0)`; `tokens: primary 30826, fallback 0 over 1 of 206 timed runs that recorded tokens; tokens per scoring call 3082.6 (n=10); completions per day 1.4; cached 19% of prompt tokens`; `Groq tokens per UTC day: 2026-10-26 primary 30826 / fallback 0`; the latest `x-ratelimit-*` header values for gpt-oss-120b are printed (requests limit 1000, remaining 990; tokens limit 8000, remaining 4841). `n=10` is one run's scored jobs: **not enough for a tokens-per-call figure**, a day or more of runs is needed (plan 02-08) | **live** |
| Reconciliation (same report) | tracker 97 rows = 2 labelled fixtures + 95 real rows (95 distinct jobs); 55 ledger-kept in the window, 54 in the tracker; **1 ledger-kept job missing from the tracker** (STATUS recorded 2 on 2026-10-25 without their keys). Missing key: `greenhouse|nadiacare|4459849009`, evaluated 2026-10-23T02:00:32Z. `1 tracker row(s) were placed by their exact stored URL` (the new diagnostic fallback), which probably accounts for the drop from 2 to 1; not confirmed because the earlier keys were not saved | **live**; whether the row was deleted by hand is an owner question |
| Delivery test (run 40385017743, 19:15 UTC) | workflow `success`; JSON line `scored: 90, status: To Apply, tracker_row_appended: true, telegram_sent: true, label: TEST FIXTURE (not a real job)`. The send path accepted the message (HTTP-level success is what `telegram_sent` records); **whether the message arrived uncut is an owner check**. The fixture also added a third labelled test row to the tracker (reports exclude fixtures) | **live** for `telegram_sent`; arrival and text cut: owner check pending |
| Pilot report run itself (read-only) | run 40384832233 at 19:13 UTC, `success`; no secret pattern in its log | **live** |

**Owner checks in the real Sheet (pending; the agent cannot see the Sheet):**
1. Dashboard tab: first chart "Tracker rows per day · target 20-30", bars in three colours, two dashed amber lines flat at 20 and 30 (if the upper line sits near 50 or rides on the bars, say "band stacked": the fix is the `BAND_LINES_STACK` switch in `dashboard.py`); second chart "How old jobs were when found · 7d"; a "TRACKER ROWS · 7 DAYS" table with Would apply / Maybe / Irrelevant / Unlabelled per cohort; the Groq SYSTEM line.
2. Runs tab: the newest row (19:00 UTC run, Code_Version fc197c17...) has values under `Groq_Tokens_Primary` .. `Alerts_Deferred` (zeros are fine where nothing was scored; the header should now be 77 columns), and its Notes contain the "Groq daily token budget ... from ..." note.
3. NEEDS ATTENTION: "tracker missing kept jobs" should name `greenhouse|nadiacare|4459849009`. Say whether you deleted that row by hand (keep it deleted, restore it, or decide a different rule).
4. Telegram: the labelled TEST FIXTURE message arrived and no line is cut off.

**Not verified live and still mocked:** the 15 / 20 / 22 minute cutoffs, budget-skip and fallback behaviour, deferral of an unsent alert, the five-attempt bound without an HTTP response, and the Dashboard render (until you confirm item 1). The first weekly rebalance is due about 2026-10-29 01:00 UTC and is unchanged by this deployment.

**Observations to carry forward (not acted on, AGENTS rule 7):** Events rows are now 189,830 (the D-03 200k review point is near, plan 02-08); the live Groq headers show `x-ratelimit-limit-tokens=8000` for gpt-oss-120b, which is a per-minute figure the budget does not govern; and the budget source note not reaching the public log means a future "which budget is in force" check needs the Sheet.

## Groq limits and plan (MEAS-02)

Measured by plan 02-08 Task 1 on 2026-10-28 (UTC); **decided by the owner the same day in D-53: stay on the free plan now, revisit before Phase 4 starts.** The new budget default (100,000 per model) was **pushed on 2026-10-28 20:02 UTC (`f4a989b..1d63416`)**; no production run after the push has been read yet, and the live Settings tab keeps whatever it has until the owner edits it. Every number below is labelled live (read-only, public workflow log), derived (arithmetic on live figures) or owner-read.

### Measured usage (live, read-only)

Source: read-only `pilot_report` run 40606970912 (`job_hunter.yml -f pilot_report=true`, 2026-10-28 00:09:47 UTC, `success`, Code_Version f4a989bf, which is docs-only on top of fc197c17: `git diff fc197c1 HEAD` on `*.py` and `.github` is empty). Report window 2026-10-21T00:10:03Z to 2026-10-28T00:10:03Z (168 h); the Groq token columns only exist from the first run on fc197c1 (2026-10-26 19:00 UTC), so the Groq token figures cover **25 runs, about 29 hours, UTC 2026-10-26 19:00 to 2026-10-27 23:00**, not the 7 days. The complete UTC day 2026-10-27 has production runs on f4a989b on every hour (00:00 to 23:00 UTC, all `success`). Log scanned for key material: only the counts and header values below were copied.

| Figure | Value | Sample | Live or derived |
|---|---|---|---|
| Tokens per scoring call (both models together) | **2,653.9** | **n = 95 scoring calls** in 25 runs, about 1.2 UTC days; the first run alone read 3,082.6 (n=10), so the figure is still settling | live (report line `tokens per scoring call 2653.9 (n=95)`) |
| Tokens per UTC day, 2026-10-27 (complete day) | primary `openai/gpt-oss-120b` **171,329**, fallback `openai/gpt-oss-20b` **26,564**, total 197,893 | one full UTC day | live |
| Tokens, 2026-10-26 (partial: from 19:00 UTC) | primary 54,224, fallback 0 | 5 h | live |
| Scoring calls per UTC day | 2026-10-27 about **75** (197,893 / 2,653.9 = 74.6), 2026-10-26 from 19:00 about 20 | derived from tokens and the per-call mean; the two days add to 95 = n | derived. The report's own `completions per day 13.7` divides 95 calls by the whole 7-day window and so understates the rate; it is not used here (logged in deferred-items.md) |
| Primary budget on 2026-10-27 | 171,329 used against the 170,000 budget (one call over, the check is made before the call), so the **primary model's budget was reached and the fallback took over** (26,564 tokens) | one day | live: first live sight of budget-driven fallback (it was mocked before) |
| Groq calls / HTTP 429 | 319 calls in the window, **0 HTTP 429** | 7 days | live |
| Cached share of prompt tokens | 9% (19% in the first run) | n = 95 calls | live |
| Governors | budget skips 0, deadline skips 0, runs with an evaluation cut 0, boards cut by the poll deadline 0, alerts deferred 0 (budget skip stays 0 because the fallback absorbed the primary's budget) | 206 timed runs, 25 of them with the columns | live |
| Run duration | median 135 s, p90 277 s, **p95 343 s, max 941 s (62.7% of the 1,500 s workflow timeout)** | 206 timed runs | live |
| Scored and kept | **319 scored, 52 kept for the tracker = keep rate 16.3%** (pilot week 1: 18-20%); 27 of the 52 verified fresh; 22 alerts delivered | 7 days | live |
| Scored per day, kept per day | 319 / 7 = 45.6 scored a day and 52 / 7 = **7.4 kept a day** over the window; 2026-10-27 alone scored about 75 (derived above) | 7 days | live / derived |
| Events rows | 195,793, about 9,489 rows a day (was 3,355 on 2026-10-25), so the D-03 200k point arrives within about a day | report line | live |

**Latest `x-ratelimit-*` header values (live, from the `Runs` columns, read by the report):**

| Run (`at`) | Model | requests limit / remaining / reset | tokens limit / remaining / reset |
|---|---|---|---|
| 2026-10-26T19:00:30Z (report 40384832233) | `openai/gpt-oss-120b` | 1000 / 990 / **14m24s** | 8000 / 4841 / 23.692s |
| 2026-10-27T23:00:26Z (report 40606970912) | `openai/gpt-oss-20b` | 1000 / 999 / **1m26.4s** | 8000 / 5856 / 16.08s |

**Daily window: rolling, not a fixed moment (for requests).** 10 requests used (1000 - 990) gives a reset of 14m24s = 864 s = 10 x 86.4 s, and 1 request used (1000 - 999) gives 1m26.4s = 86.4 s, and 86.4 s is exactly 24 h / 1000. The reset time scales with the requests used and lands on different clock moments (19:14:54 and 23:01:52 UTC), so the requests-per-day allowance refills continuously instead of resetting at one fixed time (UTC midnight would give hours, the same instant each time). Two stamps, two models, so this rests on two points. **The tokens-per-day window is not in any header;** that it refills the same way is an inference, not a measurement. Consequence (adopted in D-53): the window is treated as rolling, so the budget default is half the limit (100,000 per model), not 85%; the arithmetic below shows both.

**Arithmetic, with the measured 2,653.9 tokens per call (n = 95) and keep rate 16.3% (52 / 319):**

evaluations per day = sum over usable models of (share x daily token limit) / tokens per call; tracker rows per day = evaluations per day x keep rate. The limit is the 200K tokens per day per model that the owner read from the account page (below). Groq's public docs table shows the same 200K, but that table is **public table, not this account** and is not what the arithmetic rests on.

| Case | Budget per model | Evaluations a day | Tracker rows a day (16.3%) | (at the pilot's 19.6%) |
|---|---|---|---|---|
| primary only, plan rule (85%) | 170,000 | about **64** | about **10** | about 12.5 |
| primary + fallback, plan rule (85%) | 170,000 each | about **128** | about **21** | about 25 |
| primary only, rolling window (50%) | 100,000 | about 38 | about 6 | about 7 |
| **primary + fallback, rolling window (50%): chosen in D-53** | 100,000 each | **about 75** | **about 12** | about 15 |

The 20-30 a day target needs about 123-184 evaluations a day at 16.3% (20 / 0.163 to 30 / 0.163). With the free figures only the plan-rule case with both models at 85% reaches the bottom of the band (about 21 rows), and it does so only if scoring volume rises from today's 45.6 a day (7-day mean; about 75 on 2026-10-27) to about 128 a day; under the rolling treatment even both free models stop at about 12 rows. The RESEARCH estimate that the free tier cannot support the target rested on an assumed 3.5-4.5k tokens per call; the measured 2.65k per call is lower, which moves the free ceiling up but not to the middle of the band. **Supply caveat:** the limit that binds today is the number of jobs reaching scoring (the title gate stops 96% of new postings), not Groq: on 2026-10-27 the primary model's budget was reached, but that day's volume (about 75) was well above the week's mean, and the kept rate has been 7.4 a day. Per-minute limits (8K tokens a minute = about 3 calls a minute per model at 2.65k each) were not hit: 0 HTTP 429 in 319 calls. Phase 4 backfill competes for the same daily budget.

### Account limits

**Owner-read from the account limits page** (console.groq.com, Settings, Limits and Data controls) on **2026-10-26**, relayed by the owner in chat; figures only, no key; confirmed by the owner at the D-53 decision on 2026-10-28. Label: owner-read from the account limits page, 2026-10-26; not measured by the app and not seen by the agent.

| Item | Value |
|---|---|
| Plan / tier | free |
| `openai/gpt-oss-120b` | 30 requests per minute, 1,000 per day, 8,000 tokens per minute, 200,000 tokens per day |
| `openai/gpt-oss-20b` | 30 requests per minute, 1,000 per day, 8,000 tokens per minute, 200,000 tokens per day |
| Data retention | zero data retention **not** enabled (neither the global setting nor the inference API setting) |
| Daily window | requests per day: rolling (see above, live headers); tokens per day: not determined (not in any header) |

**Decision (D-53, owner, 2026-10-28):** plan **free-revisit** (stay free now, revisit before Phase 4 starts); data handling **"resume to Groq: ok"** (the resume text is sent to Groq on every scoring call, with zero data retention not enabled); budget **"100,000 (plan rule)"** per model per UTC day (half of the 200,000 limit because the window is rolling), replacing the provisional 170,000. `hunter.GROQ_TPD_PRIMARY` / `GROQ_TPD_FALLBACK` hold the owner-read limits and the default derives from them (offline-tested, mocked).

**What the free plan supports, with the account's figures (live tokens per call 2,653.9, n = 95; keep rate 16.3%):** with the free plan the app can evaluate about **75** jobs a day (100,000 tokens per model, both models, tokens per call 2,653.9), which at the measured keep rate of **16.3%** supports about **12** tracker rows a day (about 15 at the pilot's 19.6%); the 20-30 a day target is **conditional, not met**: it needs about 123-184 evaluations a day, which the free plan does not supply at this budget, and the live inflow is about 7.4 tracker rows a day because scoring volume (about 45.6 a day over 7 days), not Groq, is the limit today. The target needs paid limits, a higher keep rate or a cheaper call, and the plan choice is revisited before Phase 4 starts (backfill competes for the same budget).

**Deployed; read by the owner, not by the agent:** the 100,000 default was pushed on 2026-10-28 20:02 UTC (`1d63416`); runs from then use it unless the Settings tab says otherwise. The owner follow-up (add or edit the `Groq_Daily_Token_Budget` row in the live Settings tab, or ask for it through the Sheets connector) makes the note in `Runs.Notes` say "from Settings tab". Not verified live: that the token window rolls (inference from the request window). The new default in a production run was read by the owner in the Sheet (02-UAT test 3), not by the agent. The code-review fixes WR-01..WR-04 (02-REVIEW-FIX.md) are committed locally and not yet pushed.

## Pilot week 1 result (2026-10-15 01:47 to 2026-10-22 01:47 UTC; measured live 2026-10-23 20:17 UTC)

All figures from the read-only `pilot_report` and `rebalance_report` workflow runs against the production Sheet (**live**). Window of the report: the last 168 h.

| Criterion (DEPLOY.md section 9) | Result |
|---|---|
| Seven full days of runs | 168 of 168 hourly intervals had a successful poll; no gap over 90 min; 207 runs, all `ok`; 0.31% of 103,500 board polls failed |
| Real alert through scoring, tracker and Telegram | 20 alerts, 20 unique jobs, 0 duplicates, 0 failed sends, 1 labelled late (Telegram receipt not checked by the agent) |
| Schedule fires | 38 `schedule` runs (about every 4.4 h) plus 168 `workflow_dispatch:external`: the external trigger carries the hourly cadence |
| Pending failures | 0 awaiting evaluation, 0 awaiting alert, 0 hydration retries |
| Search credits | 140 in 7 days (20/day: at the stop threshold, not over) |

**Freshness:** publication -> detection, verified-fresh poll jobs median 29 min, p90 54 min (n=310); search-found median 455 min (n=8); all time-precise relevant jobs 79% inside the 12 h window (n=402). Publication -> alert median 29.5 min. **Funnel (one cohort):** 19,380 new postings -> 472 relevant -> 212 rejected after reading (location 131, experience 71, language 10) -> 260 scored -> 47 kept -> 20 alerted (about 3 a day). **Limits:** run median 113 s, max 770 s (51% of the 25 min timeout); Sheets reads peak 12.4/min (quota ~60); no ATS or Groq 429s; Events 140,668 rows, ~2,900/day. **Coverage:** 500 monitored (all exploration trials), 849 relevant boards waiting, 33% of known relevant boards. **Re-checks:** 12,460 validated boards overdue (the daily budget cannot re-check ~21,000 boards weekly); 0.7% of re-checks gained relevant jobs and all 55 gainers still wait for a slot. **Feedback:** labelled on most tracker rows (the report could not read them until the header fix below).

**Changes after the pilot (deployed 2026-10-23 20:52 UTC, commit 76726a6; see PILOT_LOG):**
- **D-45 graduation floor** (`pools.GRADUATION_FLOOR` = 2.0): a free established slot needs a score of at least 2; offline tests (the floor test fails when the floor is 0). The user set `Max_Active_Boards` to 700 and `Rebalance_Mode` to `on` in Settings at deployment. **Live, first run on 76726a6 (2026-10-23 21:00 UTC):** pools read "established 0/560, exploration 550/140, monitored 550/700, 799 relevant boards waiting, coverage 37%"; 50 waiting boards started trials, so 700 is in effect and the set fills by 50 a run (about 3 more runs to 700). That run added 7,424 new job IDs (mostly baselines of the new boards) and sent 0 alerts. **D-46 verified live** by the 22:00 UTC run (40030703127): its alert's tracker row was appended at row 80 (10/23 5:03 PM Central), each value under its own header in the user's column order (score under `AI_Score`, `My_Feedback` blank, URL under `Apply_URL`), header row intact; `Rebalance_Mode` on is not visible until the rebalance runs. Without the floor all ~495 ended trials, including ~94 scoring 0-1, would take established slots. The next rebalance is due about 2026-10-29 01:00 UTC.
- **D-46 tracker header** (found live): row 1 had been cleared, so four rows (10/22 10:03 PM and three on 10/23) were written by fixed position and the report could not read the tracker. **Sheet repaired live** through the Sheets connector (header restored in the user's order, the four rows rewritten in place, read back and checked). Code now refuses to write without a header, reads every cell for duplicate protection, strips header names in reports and flags it on the dashboard; **mocked** tests only (520 offline pass; mutation checks on refusal and name stripping fail the suite). Verified live 2026-10-23 22:03 UTC (row 80, correct columns).


## State

Board polling -> new-ID detection -> freshness classification -> filters/scoring -> Sheet -> Telegram is implemented (D-01..D-09). This change adds the **inventory loop** (D-11..D-15): the registry is seeded from two public inventories, validated through the existing adapters, and promoted into hourly polling only within a budget. Groq model defaults changed because the requested models no longer exist for this key (D-16).

Latest change (D-23..D-30, quick task 261014-olj): board slot allocation. A complete hourly poll now refreshes each monitored board's relevant / eligible counts and new-posting activity from the listing it already fetched; `Max_Active_Boards` is split into an established pool (400) and an exploration pool (100) with 7-day trials; a weekly bounded rebalance compares ended trials with the weakest established boards (**report mode by default**; `python hunter.py --rebalance-report` previews it); demoted boards keep their ledger, baseline, provenance and pending retries and re-enter with a re-established baseline; monitored SmartRecruiters boards are parked every run (history kept); validation runs two independently budgeted queues so re-checks no longer starve behind the candidate backlog; the title gate accepts "Internship", "Jr.", "Entry-Level" and "New Grad" variants. **Everything for this change is verified only with offline mocks: no live Sheet, Groq, Telegram, Serper or GitHub Actions run, and no real ATS call, was made** (tests: 275 offline).

Previous change (D-17..D-21): scheduled discovery is a persistent rotation of date-windowed searches within a credit budget (unfiltered search is manual `--backfill` only); every source goes through one board-admission path; the freshness window is 12 hours (discovery interval is a separate setting); pending deliveries are no longer discarded when jobs age past the window. **Verified only with mocks** (offline tests); no live Serper call, Sheet, Groq or Telegram was made for this change.

## Tracker column order (D-44)

**Fixed:** the app wrote tracker rows by fixed position, so moving `My_Feedback` put seven new rows one column off (rows 38 to 44); it now writes and reads by header name. The seven rows were repaired by hand in the live Sheet and checked by screenshot (values under the right headers, dropdowns and colours intact, links restored). **516 offline tests** pass (8 new in `tests/test_hunter.py`; mutation checks on the three lookups fail the suite). **Not verified live:** no new tracker row has been written since the fix; the next real alert (or a `delivery_test`) will show it.

## Pilot reliability and reporting fixes (D-42, D-43; see PILOT_LOG.md for deployment times)

**Built:** `watchdog.py` + `.github/workflows/watchdog.yml` (independent missed-run watchdog), pilot-report corrections and a reconciliation section, `Runs.Code_Version`, `--storage-report` (read only), `PILOT_LOG.md`. **508 offline tests** pass (60 new: `tests/test_watchdog.py`, `tests/test_pilot_corrections.py`, `tests/test_storage_report.py`; mutation spot-checks on six watchdog behaviours fail the suite). Nothing in discovery, filtering, scoring, board capacity, allocation or `Rebalance_Mode` changed (the pipeline diff is the version tag).

| Check | Result | Live or mocked |
|---|---|---|
| Watchdog states: healthy, stale (failed / stalled / absent), running, recovered, unavailable, dedupe (one outage, one recovery), failed-send retry, dry run, threshold, rehearsal runs ignored, no hunter imports, own concurrency group | pass | **mocked** (fake store and notifier; nothing production was touched) |
| Watchdog read of the production `Runs` tab (`--dry-run`) | HEALTHY, last success 29 min earlier, nothing written or sent | **live**, read only |
| Watchdog Telegram delivery, incident tab creation, real outage / recovery | **not verified** | no outage has occurred; no test message was sent (none was requested) |
| Pilot report: elapsed denominator, distinct intervals, gaps, workflow vs board polls, latency sample, coverage populations, code versions, reconciliation | pass | **mocked** tests, then **live** (the pilot report run of 2026-10-17 19:31 UTC printed every section) |
| Dashboard and pilot report agree on the same window | pass | **mocked** (same window, same per-job definitions); not compared live at one instant |
| Storage report | pass | **mocked** tests, then **live** read only |

**Watchdog hosting:** GitHub Actions workflow `Watchdog` (own concurrency group, GitHub schedule every 15 minutes). **Notification:** Telegram to `TELEGRAM_CHAT_ID`. **Remaining setup (owner):** a second, external trigger for `watchdog.yml` (DEPLOY.md "Watchdog"), because GitHub's own schedule has fired only about every 4.7 hours here; optionally set the repository variable `WATCHDOG_WARN_HOURS`.

## Operational dashboard (D-40)

**Built:** `reporting.py` (pure summary), `dashboard.py` (render + one-batch publish), run-start records and the new `Runs` / ledger fields, `--dashboard` and `--dashboard --dry-run`, refresh after every poller run (contained). **448 offline tests** pass (50 new in `tests/test_reporting.py`: totals checked against hand-built ledgers and real pipeline runs for retries, duplicate observations, partial failures, missing dates, local-day boundaries, exclusions, idempotence; mutation spot-checks on nine behaviours each fail the suite).

| Check | Result | Live or mocked |
|---|---|---|
| Summary totals vs the ledger (unique vs attempts, alerts, rejections partition, freshness denominators, latency split, boundaries, rehearsal / fixture exclusion) | pass | **mocked** (fake ATS, CSV state) |
| Run-start record visible during a run; one record per run; failed / degraded outcomes; gap ignores interrupted runs | pass | **mocked** |
| Dashboard tab written in one batch, only that tab, tracker feedback untouched, rerun identical, failure contained | pass | **mocked** (fake spreadsheet: request shapes are NOT validated by the real Sheets API) |
| Charts, sparklines and the compact layout (D-41): every request validated against Google's Sheets v4 discovery schema (0 problems); chart data block, fixed ids and delete-then-add checked | pass | **mocked** + schema (not rendered) |
| Dashboard rendered in the real Sheet and inspected through the user's signed-in Chrome (fonts, hidden data block, four charts, cards, tables render; the Sheets API accepted the batch) | pass | **live** (one Sheet, one browser size) |
| Rendered tab inspected in a real Sheet (earlier note, superseded above); first refresh; `Runs` header widening to 65 columns; Actions run | **not verified** | no Sheet credentials / GitHub repository here |

**Remaining setup:** none required (the tab and the new `Runs` columns are created on the first run). Rows written before this change show `n/a` for the new fields. Open items: view the first real render (column widths, merged cells, colours) and adjust; the daily Telegram digest and the independent missed-run watchdog are documented in SPEC and not built.

## Deployment and pilot status (running log)

- **Deployed:** public repo (D-48), secrets set, Sheet connected, Telegram group delivery verified (labelled fixture), two manual polling runs (second added 0 jobs: no duplicates), a quota failure under back-to-back runs found and fixed (retry on HTTP 429), SmartRecruiters unparked by decision (D-38), Board Inventory enabled with its schedule.
- **Diagnostics for the limits audit** (this change): per-run duration and phase times, Google Sheets request counts and quota rejections, ATS and Groq request counts and 429s, and Events/Boards row counts are recorded in `Runs` and summarized in the pilot report (`LIMITS AUDIT`). Measured values only exist from this change onward.
- **Since then (2026-10-23):** the schedule fired (38 `schedule` runs in the last 7 days), 20 real alerts were delivered and the seven-day pilot is complete (see "Pilot week 1 result" above).

## Deployment preparation and pilot (D-37)

**Prepared, not yet deployed.** What exists: `DEPLOY.md` (private-repository setup, the exact secret names, Sheet/service-account/Telegram setup without sharing values, manual-run and schedule checks, the seven-day pilot protocol); read-only `--pilot-report` and a labelled `--delivery-test`; the user-owned `My_Feedback` column; 429 provider backoff; completeness by documented pagination behaviour; a flock-based local lease and the refusal of local production writes; workflows reduced to `contents: read` with no commit steps and a configuration check that names (never prints) missing secrets. **375 offline tests** pass.

| Check | Result | Live or mocked |
|---|---|---|
| Rotation duration from requests actually consumed (`--search-usage`) | 42 slots, 1.00 request per slot (Tavily cannot paginate), 1.00 credit per request, 10 slots per run -> **2.1 days per full pass, 600 credits a month** at 2 runs a day (inside the 800 scheduled allowance); the figure is recomputed from the ledger and the last discovery's per-query page counts, so pagination or a higher cost would lengthen it | measured from the 10-request live run |
| Lease: simultaneous acquisition | file lease: 12 threads and 2 processes -> exactly one holder (an earlier create-then-write version let 5 in; fixed with flock). **Sheet lease: not atomic** (a test shows two writers both verifying), so it is not relied on | mocked (real kernel locks for the file lease) |
| Lease: expiry during a long run, owner-only release | Sheet lease expires after its TTL (30 / 45 min, above the 25 / 40 min workflow timeouts, asserted); a run that outlives it logs an error; only the token holder releases | mocked |
| Local production writes | refused (exit 4) unless in GitHub Actions or `ALLOW_LOCAL_SHEET_WRITES=1` for a test Sheet | mocked |
| Provider backoff (429), completeness per endpoint | Workable 429 stops that provider for the run, skipped boards keep their state; Lever continued with `skip` at page-size lengths, Workable flagged possibly truncated, Greenhouse/Ashby documented unpaginated | mocked (Workable's 429 itself was seen live earlier) |
| Delivery fixture scoring | the fixture was scored by the real Groq model (90) | live (Groq only; the Sheet and Telegram steps are not configured) |
| Sheet migration, effective settings, 12 h window check in a real Sheet; Telegram delivery; Actions runs (manual twice, scheduled) | **blocked** | no Sheet, service account, Telegram credentials or GitHub repository yet |

**Counter correction.** "Eligible boards" counts validated or monitored boards among *all* boards the search results named, new or already known; the `Result_*` columns now make that explicit (see SPEC "Board counters").

## Search provider migrated to Tavily (D-36)

Serper is gone from the code, the workflow and the settings; discovery calls Tavily (`search.py`), every search path shares a persistent monthly credit ledger (default 1,000, 800 for scheduled runs), exhaustion skips discovery while polling continues, and the Serper-era rotation cursor is discarded (restart at slot 0, noted once in `Runs.Notes`). Registry, ledger, history and delivery code are unchanged. **333 offline tests** pass (30 new in `tests/test_search.py`; mutation spot-checks on every new behaviour fail the suite).

| Step | Result | Live or mocked |
|---|---|---|
| Request mapping (`include_domains`, `start_date`, `basic`, no answer/raw content), response normalisation, credit accounting, 401/429/432/433 handling | pass | **mocked** (fake HTTP) |
| Monthly ledger: shared paths, reserve, month rollover, account-counter merge, exhaustion skip, persistence on failure and dry run, cursor migration | pass | **mocked** |
| Tavily `/search` parameters: window, domain, credit cost per mode | checked against the current API reference and **live** (response `usage.credits` = 1 for basic and fast) | live |
| Window quality (Greenhouse, 7 roles, ATS publication times): no window 19% of dated jobs within 72 h; `start_date` -3 d 95%; `time_range=week` 66%; `fast`+window 0% | measured | live |
| Real pipeline run on the rehearsal registry (manual `--discover`, 10 slots) | 10 credits charged to the ledger. The results named **126 unique boards**: **41 new** to the registry and **85 already known** (from the public lists). "51 eligible" = validated or monitored boards among all 126: 10 of the new ones + 41 of the known ones (6+4 new, 36+5 known). The other 75 were 17 parked (SmartRecruiters), 14 new + 44 known awaiting validation (inline validation is capped at 40 per run). 9 promoted, 1 verified-fresh match, 3 jobs scored by real Groq (reconstructed from the registry's provenance; the `Result_*` columns now record this directly); the Serper-era cursor was reset; SmartRecruiters boards found were parked | live (rehearsal registry in a scratch directory; nothing in the repo or any Sheet was touched) |
| Tavily vs Serper, same 10 slots, 10 credits each | Tavily 181 URLs / 156 boards / 27 title-gate jobs (16 US-eligible); Serper 73 / 65 / 15 (8); board overlap 54, Tavily-only 102, Serper-only 11; 69% vs 68% of dated jobs published within 72 h, 10% vs 9% within 12 h | live, one day, one sample |
| Account credit counter (`GET /usage`) | still **0** after about 55 credits (the 54 measured by response `usage.credits`: 6 + 28 probe requests, 10 pipeline, 10 comparison); local ledger recorded the pipeline's 10 | live; the account counter cannot be used to verify cost yet |
| GitHub secret `TAVILY_API_KEY`, scheduled run | **not verified:** no GitHub remote exists for this repository | blocked |

**Other account usage the local counter cannot observe:** anything not made through this application (other keys or projects, the probes and comparison runs above: about 44 credits of the 54 were spent by hand scripts, not by the pipeline), and the day Tavily's billing cycle starts (undocumented in the API reference; the local count resets at the UTC month). `python hunter.py --search-usage` prints both counters. **Migration steps for you:** add `TAVILY_API_KEY` to `.env` and to the GitHub secrets (the old Serper key is no longer read), nothing else is required; the Settings rows `Search_Monthly_Credits` and `Search_Reserve_Credits` are optional.

## Correctness pass and live verification (D-31..D-35)

**Changed:** shared concurrency group + advisory writer lease + provenance reconciliation (D-31); cool-down, bounded trial rotation and slack fix in the allocation (D-32); observed-time rates, gap-discovery rule, Serper-found activity, Greenhouse completeness (D-33); discovery slot query reduced to site + role (D-35). 303 offline tests (28 new targeted ones in `tests/test_allocation_correctness.py`); mutation spot-checks on each fix fail the suite.

**Live, with the credentials that exist on this machine** (at that time `GROQ_API_KEY` and a Serper key under `SEARCH_API_KEY` were configured; `TAVILY_API_KEY` has since been added; no Sheet, no service account, no Telegram, no GitHub remote for this repo):

| Step | Result |
|---|---|
| Public inventory download + 760 real ATS validations (Greenhouse/Ashby/Lever) | 723 valid, 26 empty, 11 invalid, 0 transient; two validation queues reported separately |
| Hourly poll on a local rehearsal registry (CSV in a scratch directory, nothing in the repo touched) | 28 real boards promoted (3.7% of the first 749 validated boards had a job matching the default title gate; those boards were validated in priority order, not sampled at random, so this is not an estimate of the whole inventory), 3,579 existing jobs baselined, 39 time-verified fresh on the baseline pass, 0 evaluated before search added 1 |
| Real Groq scoring through the real gates (`--url`, a real 14-day-old Coinbase posting, age limit raised for the test only) | scored 45 -> "Filtered Out": the path ATS -> eligibility -> Groq works; `openai/gpt-oss-120b` answered |
| Real Serper rotation (the previous provider), 3 runs x 10 queries, cursor persisted between runs | cursor 10 -> 20 -> 30 of 42 in the state store; first two runs returned 0 results for all 20 queries (location/level/exclusion terms), after the fix 5 results from 10 queries, 2 new boards admitted, 1 promoted, 1 search-found job read and filtered |
| Real rebalance report | printed from the rehearsal registry: nothing due (all 29 boards are inside their first trial) |
| Sheet migration, effective settings in a real Sheet | **blocked:** no `GOOGLE_SHEET_ID` / `GOOGLE_SERVICE_ACCOUNT_JSON` |
| Telegram test message | **blocked:** no `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`, and no recipient was named as authorized |
| GitHub workflow run, scheduled run | **blocked:** this repository has no remote and no GitHub repository exists for it; nothing can run on Actions, so scheduled behaviour is **not** verified |

## Inventory: live numbers (2026-10-14, real downloads)

| Source | Rows (all providers) | Rows for supported providers | Rejected | Unique boards | Only in this source |
|---|---:|---:|---:|---:|---:|
| open-ats-feed (as of 2026-09-03) | 22,122 | 12,916 | 0 | 12,916 | 2,550 |
| ats-scrapers | 80,390 | 19,380 | 50 | 19,330 | 8,964 |

Overlap 10,366; **unique union 21,880** (Greenhouse 7,709, Workable 4,752, Ashby 4,041, SmartRecruiters 2,747, Lever 2,631). Case-only Lever/Workable variants across sources: 0. The 50 rejected rows are Ashby values with spaces (`hamming ai`): display names stored as slugs. Unsupported, reported and not imported: open-ats-feed 9,206 rows (Breezy 3,536, Teamtailor 2,840, Recruitee 2,830); ats-scrapers 61,010 rows across 42 providers (Join 23,547, BambooHR 5,632, Paycom 5,135, Workday 3,530, JazzHR 2,689, iCIMS 2,498, Personio 2,463, Rippling 1,923, ...). A second import changed **0 rows** (verified through the CLI).

## Validation: live sampling (not the full list)

Random sample, 25 boards per provider and source-group (250 total, SmartRecruiters excluded): 145 valid, 69 valid-empty, 36 invalid, 0 transient. Hit rate (valid with jobs): boards **both sources list 85%**, open-ats-feed only 60%, ats-scrapers only 36% (Ashby boards only ats-scrapers lists: 0 of 25 had jobs, 15 were invalid). Only 6 of 250 had a job matching the default title gate that day (2.4%; a 95% interval of roughly 1%-5%). **That sample does not establish how many relevant boards exist:** extrapolated to ~21,900 boards it spans a few hundred to over a thousand, and 6 hits is far too few to say whether 500 slots can be filled. Filling `Max_Active_Boards` is not a launch prerequisite: the pilot starts with whatever boards are validated and relevant. A balanced 600-board run (150 per provider, 174 s, Lever at its 1 req/s): 488 valid, 103 empty (Workable 85 of 150), 9 invalid. About 18,500 boards remain unvalidated; the daily workflow drains them.

Registry after a real CLI run (450 validated, then the hourly run): 21 boards promoted and polled (the ones with relevant jobs), 1,809 existing jobs recorded as baseline, 5 verified-fresh jobs all rejected by the title gate, 0 alerts; the next poll found 0 new IDs.

## Verification: mocked vs live

| Area | Result | How |
|---|---|---|
| Identity (casing per provider, region, unchanged job keys), parsers, last-known-good cache, schema-change and shrink guards, merge idempotence, provenance, overlap math | pass | **Mocked** (`tests/test_inventory.py`), 145 offline tests in total |
| Validation outcomes valid / empty / invalid / transient, retries and backoff, breaker, rate limits, SmartRecruiters policy, interleaving, batching | pass | **Mocked** |
| Activation budget (ceiling, surge cap, relevance order), baselining of imported boards, row-level writes, concurrent importer+poller | pass | **Mocked** |
| Rotation persistence and wrap, fixed credit budget, stall-based pagination stop, repeated-result counting, independent board/job processing, shared admission (SmartRecruiters parked for every source, activation ceiling across sources, one row and provenance per board), 12-hour boundaries (11:59 / 12:00 / 12:01, baseline exception, day precision), explicit 4 h kept and flagged, pending alert/scoring/hydration retries surviving age | pass | **Mocked** (`tests/test_discovery.py`, plus updated `test_core.py` / `test_hunter.py`): 200 offline tests in total |
| Board evidence (relevant / eligible counts, 7/30-day activity, unknown vs zero, baseline and re-entry exclusion, partial / failed / suspicious-empty polls change nothing), re-entry baseline, title-gate variants | pass | **Mocked** (`tests/test_pools.py`, `tests/test_core.py`) |
| Pools (labels, admission order, caps), weekly rebalance (score, margin, two weak cycles, replacement bound, trial protection, thin-evidence protection, capacity cut, determinism, report mode, crash safety), state preservation across demotion and re-entry, provider parking of monitored boards, Runs columns | pass | **Mocked** (`tests/test_pools.py`) |
| Two validation queues, importer write guard (Sheet and CSV stores), Settings, dry-run `--rebalance-report` leaves state files byte-identical | pass | **Mocked** (`tests/test_inventory.py`, `tests/test_hunter.py`); the Sheet store runs against a fake gspread worksheet only |
| Real Tavily requests: slot request shape, credit use, hit rate of the rotation | see "Search provider migrated to Tavily" above | live (rehearsal) |
| Downloading both inventories, parsing, merging, re-import, CLI (`--import-inventory`, `--validate`, `--offline`) | pass | **Live** (public GitHub + ATS endpoints) |
| Validation against real ATS endpoints, per-provider limits | pass | **Live**, sampled (above) |
| Transient-failure retry against a real outage | not observed | **Mocked** only (no outage occurred in live runs) |
| Groq scoring success path | pass | **Live** with the new default models: real job scored (15), real verdict; 429 -> fallback and `model_not_found` handling are **mocked** |
| Weekly/daily Board Inventory workflow, hourly schedule, GitHub cache | not verified | YAML parses; never run on GitHub |
| Google Sheets (tabs, hidden tabs, row-level upsert, header widening) | not verified live | **Mocked** (fake gspread): service account / Sheet not provided (backlogged) |
| Telegram delivery | not verified live | **Mocked**: token not provided (backlogged) |

## Migration requirements (board slot allocation)

- **Boards / Runs headers widen automatically** on the next run (13 new Boards columns, 9 new Runs columns; header row only, no data row is touched). Old rows load with unknown evidence (blank, never 0). A CSV state file with the old header is rewritten with the full header on the first save.
- **First hourly run after deploying:** every monitored SmartRecruiters board is parked (`deferred`, history kept; `ALLOW_SMARTRECRUITERS_BULK=1` + validation brings them back through a re-entry baseline); every board that was already monitored is labelled an exploration trial (7 days), so no board is demoted by the first weekly rebalance on tenure grounds and **nothing can leave monitoring through rebalancing until its trial has ended and evidence exists**. Activity counts stay blank until a board's stint is 7 days old.
- **New Settings rows are optional** (`Exploration_Share_Percent`, `Exploration_Days`, `Rebalance_Every_Days`, `Max_Replacements_Per_Rebalance`, `Rebalance_Mode`); a Sheet without them uses the defaults. The importer and the workflow arguments need no change (`--max-revalidations 2000` is already in `inventory.yml`).
- **To enable rebalancing:** review `python hunter.py --rebalance-report` (or run the Job Hunter workflow with `rebalance_report` ticked), then set `Rebalance_Mode` to `on` in Settings. Reverting is a Settings change; demoted boards are only `validated` rows and re-enter by the normal route.
- **Reversibility:** parking monitored SmartRecruiters rows rewrites their status; reverting the code does not restore them to `active`.
- Workflow files changed (`job_hunter.yml` input, `inventory.yml` argument): they have not run on GitHub.

## Known gaps / risks

- **Initial operating choices are unproven** (D-30): 80/20, 7-day trials, 20 replacements, the score weights, margin 1.0, two weak cycles and 84 complete polls. Pools only act once trials end, and the first real weekly report is the first evidence about them.
- Jobs first seen through web search count as board activity only when their own source time proves them fresh; partial listings are only detected for SmartRecruiters past 5,000 postings; a board's `Last_Job_Count` is still overwritten by a partial listing.
- Residual write window: the importer re-reads a row's status immediately before writing it, so a promotion landing in those milliseconds can still be overwritten (job state is unaffected: it lives in `Events`). Provenance updates of boards that are monitored at import time are skipped until they leave monitoring.
- Rebalancing never ran on the production registry (none exists yet: no Sheet credentials here). A real report exists only for a rehearsal registry built from the live inventory (below).

- **Search cannot promise full coverage of the 12-hour window.** Google indexing delay, a rotation that covers at most ~20 of 42 slots per day (default Settings), most of which return nothing in the window, the per-query page cap, the credit budget and late or skipped GitHub runs all cause misses. Only jobs on polled boards have the hourly-poll guarantee.
- A full rotation is 42 site x role slots (default roles) = about 2 days at 10 credits x 2 runs/day (see D-18, D-35); live, most slots return 0 results in the 3-day window, so search adds only a trickle of boards and jobs.
- Existing registries: SmartRecruiters boards activated by Serper are now parked on the first run (see Migration above); a Sheet still holding `Fresh_Window_Hours = 4` keeps 4 and is flagged each run. Sheets without `Discovery_Credit_Budget` use the default; the hidden `Discovery` tab and the new `Runs` columns are created / widened on the next run.
- Search credits come from each response's reported cost (1 per basic search); the provider's account counter lagged (still 0) so it cannot yet confirm them. Tavily has no pagination, so a slot yields at most 20 results.

- Validation is still draining: ~18,500 candidates unvalidated; the daily workflow works through them (Lever alone needs ~44 min per full pass at 1 req/s).
- Which boards are monitored depends on a snapshot of title relevance; a waiting board that posts a relevant job tomorrow is only re-checked weekly. Coverage = monitored boards, not all 21,900.
- Baseline jobs are never scored (no backfill): the first read of a board is a starting point only.
- SmartRecruiters: imported boards parked (robots.txt); existence of a SmartRecruiters board is unverifiable (API returns 200/empty for unknown companies).
- Inventory data is a snapshot: open-ats-feed `as_of` 2026-09-03; boards may have gone. Validation catches 404s only when it runs.
- `Events` grows with every observed ID (baselines included); a large activation wave adds thousands of rows.
- Existing Sheets created before this change keep the old registry header until the next run widens it; new Settings rows (`Max_Active_Boards`, `Max_New_Boards_Per_Run`) are absent from old Settings tabs, so defaults apply.
- Alerts are at-least-once. `.env.example` cannot be written in this environment (permission rule); the template is in the README.

## Blockers

None. (Superseded: the Sheets / Telegram credential and "never ran on GitHub" blockers ended with the deployment of 2026-10-15; the pilot ran live end to end, see "Pilot week 1 result".) Still owner setup: a second, external trigger for the watchdog (see "Pilot reliability and reporting fixes").

## Next milestone

Post-pilot week at 700 boards with `Rebalance_Mode` on (from 2026-10-23 20:52 UTC, PILOT_LOG):
1. ~~**D-46 live check**~~ done 2026-10-23 22:03 UTC (see above).
2. **First real rebalance** (due about 2026-10-29 01:00 UTC): read the `rebalance_report` run and check graduations against the floor (D-45), replacements against the bound, and that no board moved on thin evidence. This is the first evidence about the D-30 operating choices.
3. **Limits at 700:** run duration against the 25 min timeout, Sheets reads per minute and Events growth (compare with the 500-board pilot and the storage report projection; not comparable across the 2026-10-23 change).

4. **Wider title and location Settings** (2026-10-23 21:21 UTC, PILOT_LOG; aim: 20-30 tracker rows a day, pilot was about 7): watch relevant jobs per day, the share scored 50+, tracker rows per day, Groq 429s, and whether sales / support / accounting titles still reach the tracker. Checked offline only against the title gate (sample titles); the live effect is unmeasured. The user's existing roles `Account`, `Digital`, `Community` and `Social` are broad; the new exclusions block the known leaks (accounts payable, digital sales, social worker) but not, for example, "Community Associate" (often front desk).

5. **Early release and faster re-checks (D-47, deployed 2026-10-24 07:42 UTC, b14a1a0):** live before the change, 700/700 monitored since 2026-10-23 23:00, all trials, 651 relevant boards waiting, `+0` boards per run; the read-only rebalance report would return 221 ended trials below the floor but was not due until about 2026-10-29. Now each run returns those trials (up to the number waiting) and the next runs admit 50 a run; the inventory workflow re-checks 5,000 boards per run instead of 2,000. 525 offline tests and mutation checks; **live, run 40076316737 (2026-10-24 08:00 UTC, b14a1a0): 220 ended trials released** (`release 2026-10-24: trial lost: score 0.0 is below the graduation floor`; the dry-run report had predicted 221), monitored 700 -> 480, 651 relevant boards waiting, run succeeded, no weekly cycle triggered. Refill at 50 a run from the next run. Inventory run 40078741166 (manual, 08:37 UTC; it also re-downloaded the inventories because the manual input defaults to refresh) is the first with the 5,000 re-check budget. **Live follow-up (2026-10-24 09:00-11:00 UTC):** inventory run 40078741166 re-checked 5,000 boards in 1,121 s (budget reached, inside --max-seconds), 176 gained relevant open jobs and 67 lost them (the previous 2,000-board run: 14 and 12), so the broadened title Settings are reaching the waiting list (651 -> 710 waiting after it); the next four polls admitted 50 boards each (monitored 480 -> 529 -> 579 -> 629 -> 679 of 700, relevant-board coverage 41% -> 53%, against 47% before the release), all runs succeeded. Still to watch: the 2026-10-29 weekly cycle (about 274 graduations expected), Events growth from the admitted boards' baselines (5,273 and 6,919 new job IDs in the first two refill runs) and tracker rows per day.

**Daily check 2026-10-25 12:05 UTC (live, read-only: 33 poller runs, pilot report, storage report, tracker rows 80-94):**
- **Tracker inflow is still about 7 rows/day** (14 rows from 2026-10-23 21:06 to 2026-10-25 19:23 Central; 55 kept in the 7-day window). The target of 20-30 is not met; Oct 24-25 is a weekend, when fewer jobs are posted. In the last 24 h only about 25 jobs were scored.
- **The title gate is the main filter:** of 19,711 new postings in 7 days, 18,874 (96%) were stopped by it; 462 relevant -> 181 rejected after reading (location 143) -> 281 scored -> 55 kept.
- **Feedback (88 real rows):** 51 Would apply, 3 Maybe, 18 Irrelevant, 16 unlabelled (71% Would apply). Irrelevant labels sit mostly on verified-fresh rows (17 of 44), almost none on 'Recent' rows (1 of 24).
- **Keyword leaks since the broadening:** no sales / customer-service titles. Borderline: a 'Talent Pool' row (evergreen) and 'Remote Client Account Specialist' (the user's `Account` role). One employer (Alphabe Insight Inc, SmartRecruiters) produced 6 of the 14 rows, all score 90, with near-identical titles across cities; worth the user checking it is a genuine employer.
- **Groq:** 281 calls in 7 days (about 40/day), 0 HTTP 429. **Runs:** 207 ok, no gap over 90 min, max 770 s (51% of the timeout), 0 ATS 429s.
- **Storage (needs action soon):** Events 186,430 rows (13.1% of the 10M-cell limit), growing about 3,355 rows/day at 700 boards: **the D-03 200k-row review point is about 4 days away**, and 84.5% of rows are baseline identities. Load time 10 s at 186k rows (slope about 4 s per 100k rows).
- **Re-checks (D-47):** the faster re-check pass cleared the overdue queue (12,308 -> 0); 250 more boards gained relevant open jobs; 747 relevant boards wait.
- **Reconciliation flag:** 2 ledger-kept jobs are missing from the tracker (should be 0); not yet investigated.
- **Target status (updated 2026-10-28, D-53):** the 20-30 a day target stays conditional: with the free plan (decided in D-53) the app can evaluate about 75 jobs a day, which at the measured keep rate of 16.3% supports about 12 tracker rows a day. The "about 7-20" written here on 2026-10-25 rested on assumed token costs; measured figures replaced it (the measured volume is about 45.6 scored a day over 7 days, about 75 on 2026-10-27, not about 40).

No score tuning or new features until these are read (AGENTS.md rule 7).
