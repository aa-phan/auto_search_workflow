# Deployment and seven-day pilot

Nothing here has been run on GitHub yet: this repository has no remote. Follow the steps in order; each says what proves it worked. Never paste a secret value into a chat, an issue or a commit: the commands below read values from a file or a hidden prompt.

## 0. What is in the repository (checked)

- Git history contains no secrets (scanned for Tavily, Groq, Google, Telegram and GitHub token patterns and private keys: none).
- `.gitignore` excludes `.env*`, `*service-account*.json`, `*credentials*.json`, `Resume.pdf`, `resume.txt`, `state/`, `.venv/`, `tracked_jobs*.csv`, `legacy/*.csv`.
- The workflows have `contents: read` and contain no `git push` / `git commit`: nothing the system produces is ever written to the repository. State lives in the Google Sheet.
- Your resume lives only in the Sheet (`Settings > Resume_Text`), never in the repository.
- The repository is public (owner decision, DECISIONS D-48). Git history contains no job-search CSVs or resume files (checked 2026-10-26 with `git log --all --name-only`). Logs and documents carry counts and job keys only; job content and the resume live only in the Google Sheet.

## 1. Repository (already created, public)

```bash
gh repo create auto_search_workflow --public --source=. --remote=origin    # creates the repo, adds the remote; pushes nothing
git push -u origin main                                                    # the push is a separate, explicit step
```

The repository already exists (`aa-phan/auto_search_workflow`), so this step is history.

## 2. Google Sheet and service account (a TEST sheet first)

1. Create an empty Google Sheet. Open **File > Settings** and set its time zone (the tracker's dates use it unless `Settings > Timezone` says otherwise).
2. In Google Cloud: create a project, enable the **Google Sheets API** and **Google Drive API**, create a **service account**, create a **JSON key** and download it (keep it outside the repository, e.g. `~/secrets/job-hunter-sa.json`).
3. Share the Sheet with the service account's email address as **Editor**.
4. The Sheet id is the long string in its URL: `https://docs.google.com/spreadsheets/d/<SHEET_ID>/edit`.

## 3. Telegram

1. In Telegram, message `@BotFather`: `/newbot`, follow the prompts, keep the bot token.
2. Send any message to your new bot from the account that should receive alerts, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and read `message.chat.id` (a number). That number is the one authorized recipient.

## 4. Repository secrets (exact names)

| Secret | Required | Value |
|---|---|---|
| `TAVILY_API_KEY` | yes (without it discovery is skipped; polling still runs) | your Tavily key (`tvly-...`) |
| `GROQ_API_KEY` | yes | your Groq key |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | yes | the whole contents of the service-account JSON file |
| `GOOGLE_SHEET_ID` | yes | the Sheet id from step 2.4 |
| `TELEGRAM_BOT_TOKEN` | yes | the bot token from step 3 |
| `TELEGRAM_CHAT_ID` | yes | the chat id from step 3 |
| `ALERT_WEBHOOK_URL` | no | leave unset |

Repository variable (optional): `SEARCH_WINDOW_DAYS` (default 3).

Set them without echoing a value (run each in your own terminal; the first form prompts and hides what you type):

```bash
gh secret set TAVILY_API_KEY
gh secret set GROQ_API_KEY
gh secret set GOOGLE_SHEET_ID
gh secret set TELEGRAM_BOT_TOKEN
gh secret set TELEGRAM_CHAT_ID
gh secret set GOOGLE_SERVICE_ACCOUNT_JSON < ~/secrets/job-hunter-sa.json
gh secret list                                             # names only
```

The workflow's **Check configuration** step fails with the missing names (never values) if any required secret is absent.

## 5. First configuration check (before anything is sent)

Run **Actions > Job Hunter > Run workflow** with `pilot_report` ticked. It creates the hidden tabs (`Boards`, `Events`, `Runs`, `Discovery`, `Inventory`, `Lock`) and the `Settings` and `Job Tracker` tabs if they do not exist, then prints the report. Then in the Sheet:

- `Settings`: paste your resume into `Resume_Text`. Check `Fresh_Window_Hours` (default **12**; a value of 4 is the old default and is kept, and flagged in `Runs.Notes`: change it to 12 yourself) and that `Rebalance_Mode` stays `report` (the row is created only if you add it: absent means `report`).
- `Job Tracker`: the `My_Feedback` column (dropdown: Would apply / Maybe / Irrelevant) is yours; the program never writes it.

## 6. Delivery check

Run **Job Hunter** with `delivery_test` ticked (ticking it authorizes `TELEGRAM_CHAT_ID` as the recipient). It scores one clearly labelled synthetic posting with the real Groq model, appends one tracker row (Source and Freshness say `TEST FIXTURE (not a real job)`) and sends one Telegram message whose first line says so. It writes no ledger event, no board row and no counter: it proves the plumbing only; it says nothing about real jobs. A real job passing through the same three steps is the only real-job validation: look for the first real alert in the pilot.

## 7. Manual runs (twice) and the schedule

1. Run **Job Hunter** manually (no boxes ticked). Inspect: `Runs` (a new row, `Notes` contains `trigger=workflow_dispatch`), `Boards` (monitored boards, pool columns), `Events`, `Job Tracker`.
2. Run it again. Inspect for: no duplicate tracker rows, no repeated alerts, `New_Jobs` near zero, and that the second run started only after the first finished (the two runs share one concurrency group; their `Run_At` times must not overlap).
3. **A manual success is not proof of the schedule.** The schedule is proven when `Runs.Notes` shows `trigger=schedule` rows at about hourly intervals: `python hunter.py --pilot-report` (or the `pilot_report` run) counts runs by trigger. GitHub can delay the first scheduled run of a new repository and may skip runs; the report shows both.
4. Retry behaviour is proven by the offline tests (scoring, alert and hydration retries, restart safety); on GitHub it will show only if a real outage happens, as `error` events and `awaiting ... now` counts in the pilot report.

## 8. Local use after deployment

Local commands that **write** to the Sheet are refused (exit 4) unless `GITHUB_ACTIONS=true` or you set `ALLOW_LOCAL_SHEET_WRITES=1` for a TEST sheet that no workflow writes: the Sheet lease is a read followed by a write, not an atomic lock (see DECISIONS D-37). Read-only commands work locally with the same credentials in `.env`: `--pilot-report`, `--rebalance-report`, `--search-usage`, `--inventory-report`, `--url`, `--dry-run`.

## 9. The seven-day pilot

Start: the first scheduled run after step 7 (note its `Run_At`). Keep unchanged for seven days: `Rebalance_Mode=report`, `Max_Active_Boards`, the title/level/exclusion/location settings, `Min_Alert_Score`, `Discovery_Credit_Budget`, and the code. Allocation and discovery changes wait for the pilot evidence.

- Daily (2 minutes): open `Job Tracker`, set **My_Feedback** on any row you looked at (Would apply / Maybe / Irrelevant). Unlabelled rows are simply not counted.
- Any day: run **Job Hunter** with `pilot_report` ticked (or `python hunter.py --pilot-report 7` locally). It reports polling gaps and late runs, runs by trigger, relevant fresh jobs by source, publication-to-first-seen and publication-to-alert latency, late/duplicate alerts, pending failures, search credits (local counter) and board coverage, and your feedback.
- The report's **LIMITS AUDIT** section is the evidence for the limits (timeout, Google Sheets quota, provider rate limits, Events growth). Runs recorded before the diagnostics existed have no durations and are left out.
- The **RE-CHECK FLIPS** section needs time: boards are first re-checked 7 days after their first validation, so it fills in during the second week. It shows how many boards gained relevant jobs between two checks, which is how many the 7-day interval brought in late.
- Day 7: the report is the evidence. The pilot is **not** complete before seven full days of scheduled runs have elapsed; "complete" also needs at least one real alert to have gone through scoring, tracker and Telegram.
- Stop and investigate if: runs by trigger shows no `schedule` runs after 24 hours, a duplicate alert appears, `awaiting alert now` stays above zero for more than a few hours, or search credits per day exceed 20.

## Governor test (run deadlines; D-56)

To see the D-51 cutoffs fire, run **Job Hunter** by hand with `poll_cutoff_minutes` and/or `eval_cutoff_minutes` set (whole minutes, at least 1; for example both `1`). Leave every other box unticked and both fields empty for normal runs. A poll cut records the run `degraded` and leaves the cut boards for the next run; an evaluation cut leaves jobs pending with no attempt used. Read the result in that run's `Runs` row (`Boards_Skipped_Deadline`, `Eval_Cut`, `Eval_Deadline_Skipped`, Notes "poll cutoff" / "evaluation cutoff") and add a PILOT_LOG row naming the run, because its numbers are not a normal measurement. The alert cutoff and the 5-attempt alert bound have no test input on purpose.

## Compact storage (D-57)

Phase 3 adds two hidden tabs that the hourly run writes beside `Events` (dual writing; nothing is deleted):

- **`Identity`**: the posting IDs of baseline, title-gated and stale observations, per board (`ats|board`). It carries a warning-only protection: Sheets asks for confirmation before a hand edit. **Do not edit it**; a removed ID can make an old job look new. The service account writes it normally (not yet verified live: STATUS "Phase 3 compact storage", assumption A2).
- **`Tally`**: one row per run with counts of what that run observed, which the Dashboard and the pilot report use once old `Events` rows are compacted.

The Discovery tab gains one key, `storage` (the mode, the seed time and the parity days). On the first run after a deploy the program seeds both tabs from the ledger it loads, under the writer lease; every later run checks the previous runs' writes against `Events` and records the result.

**Reading it.** The Dashboard's SYSTEM line **Storage** shows the mode, the seed date, the last check's differences, `k of 3 clean complete days` and whether a board admission was seen. A difference appears under NEEDS ATTENTION as `storage parity difference` (the old `Events` rows stay authoritative, nothing was deleted, the 3-day clock restarted). **`READY TO CUT OVER`** means three clean complete UTC days (each with at least 12 checked runs) including one board admission, recomputed from the recorded days; it never appears from elapsed time alone. The cutover itself is a separate owner step (below); nothing retires automatically.

**Checking on demand.** Run **Job Hunter** with `storage_parity` ticked (or `python hunter.py --storage-parity`). It is read only: it takes no lock, writes nothing and needs no Groq key (the workflow's configuration step still asks for the usual secrets). It prints the compared counts, up to 50 differences and the parity clock, and exits 0 (no counted differences), 1 (differences) or 2 (it cannot be checked: not seeded yet, or the mode is `restored`). In `compact` mode (after the cutover) it runs the integrity check of Identity and Tally against the rows `Events` keeps instead of the dual comparison.

**Cutting over (owner step, plan 03-06).** Do it only when the Dashboard Storage line says **READY TO CUT OVER**. It replaces `Events` by a copy without the baseline rows and without gated or stale rows older than 7 days, and keeps the old tab whole as the hidden `Events_Legacy`; it deletes nothing.

1. **Pick the time.** Prefer early in a UTC day: the first fold (plan 03-07) runs on the first poller run of the next UTC day, and **the first fold is the point of no return** for the restore (below). Until then the cutover can be undone.
2. **Look first (optional).** With the Sheet credentials in your local `.env`, `python hunter.py --storage-cutover --dry-run` prints the gate and the plan (how many rows stay, the checksum, the before snapshot) and writes nothing.
3. **Run it.** Actions > Job Hunter > Run workflow, tick **`storage_cutover`** only. It takes the same lock as the hourly run (hourly runs queue behind it) and refuses with one line naming the unmet condition when the bar is not met, the stores are not seeded, `Events_Legacy` already exists, the mode is not `dual`, or a fresh parity check counts a difference (exit 1, nothing written). A copy that does not read back identically, or would not pass parity, also refuses with `Events` untouched.
4. **Read the log.** Success ends with `STORAGE CUTOVER done ...: mode compact`, the number of rows now in `Events` and in `Events_Legacy`, a checksum and the before snapshot (Events rows, allocated cells, median load seconds, median daily growth). Then check the Sheet: `Events` is much shorter, a hidden `Events_Legacy` tab exists (do not edit or delete it), and the Dashboard Storage line says `compact since <date>`. If the log says `failed after the tab swap`, run `storage_cutover` again: it finishes the record without copying (until then the hourly run writes as dual and says `storage cutover incomplete` in its notes). Add a PILOT_LOG row for the cutover (its own deployment row, P3-06).

**Restoring (emergency only).** If the hourly runs misbehave after the cutover (for example old jobs look new), and **only while no fold has run**, tick **`storage_restore`**. It appends the rows written since the cutover to `Events_Legacy`, then renames `Events` to `Events_Failed` and `Events_Legacy` to `Events` in one step and sets the mode `restored`: every observation is written to `Events` again, no parity check runs, and `--storage-cutover` refuses until a new owner decision. Do **not** rename the tabs by hand: that would lose every row written after the cutover and could alert old jobs twice. Once the first fold has run the command refuses and says a replay of `Events_Legacy`, the post-cutover `Events` and `Identity` is needed; that is a separate piece of work, not a button.

## Watchdog (missed-run alerts; D-42)

The **Watchdog** workflow (`.github/workflows/watchdog.yml`) checks every 15 minutes (GitHub schedule) that a production polling run finished successfully within **2 hours**, and sends **one** Telegram message when it did not and **one** when polling recovers, to `TELEGRAM_CHAT_ID`. It reads the `Runs` tab only, keeps its own incident record in a hidden `Watchdog` tab, and never restarts anything or changes Settings. No new secret is needed.

1. **Check it without sending anything:** Actions > Watchdog > Run workflow with `dry_run` ticked. The log line `WATCHDOG HEALTHY | last success ...` shows what it sees; nothing is written or sent.
2. **Make it independent of the hunter's trigger (recommended).** GitHub's own schedule is best-effort (here the hunter's scheduled runs fired about every 4.7 hours), so also create a **second** job on the external scheduler you use for the hourly hunter dispatch, calling the dispatch API for `watchdog.yml` every 10 to 15 minutes (`POST /repos/<owner>/<repo>/actions/workflows/watchdog.yml/dispatches` with body `{"ref":"main"}`, a token with Actions write permission, kept in the scheduler's secret store, never in this repository). Use a separate job so the two triggers fail independently.
3. **Threshold:** default 2 hours; set the repository variable `WATCHDOG_WARN_HOURS` (or the `warn_hours` input of a manual run) to change it.
4. **Reading its messages:** an outage message names the cause (**failed** newest run, **stalled** run that never finished, **absent** run) and the last success; the recovery message says when polling resumed. `Exit 3` / a failed Watchdog run means *monitoring unavailable* (the Runs tab could not be read), which is not evidence that the hunter stopped.
5. **Shared dependencies that remain:** GitHub Actions, the Google Sheets API, Telegram, and the external scheduler if it is the same account for both triggers. Nothing outside these watches the watchdog; the `Watchdog` tab's `last_checked_at` shows whether it is running.

## Approval needed

Creating the repository and pushing (steps 1) are outward-facing actions that have not been authorized yet (done; the repository is public, D-48). They are the first thing to approve; secrets, the Sheet and the Telegram bot are created by you and never shared in chat.
