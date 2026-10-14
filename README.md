# Job Hunter

Watches company job boards around the clock, spots **newly published** jobs, has an AI score them against **your resume**, logs them in **a Google Sheet**, and pings **Telegram** on your phone when a strong, verifiably fresh match appears.

**After the one-time setup below, you never touch code.** You change your search by editing the Google Sheet, and you track applications in the same sheet.

> **Read this first: what it can and cannot promise.** It only sees jobs on company boards it has *discovered* (Greenhouse, Lever, Ashby, Workable and SmartRecruiters). Jobs on other systems, on company websites, or only on LinkedIn/Indeed are invisible to it, and it does **not** promise to beat those sites. What it does promise: for every board it watches, a new posting is noticed within about an hour (GitHub's scheduler can run late), and an alert is only labelled "fresh" when the company's own data proves the job was published in the last few hours.

```
Google Search (Serper) ──► finds company job boards ──► board list (grows over time)
                                                              │
                                  hourly: read every board ◄──┘
                                          │  new job IDs only
                                          ▼
                       filters (title, location, experience, language)
                                          ▼
                              AI score vs your resume (Groq)
                                          ▼
                   Google Sheet tracker  +  Telegram alert (fresh matches only)
```

## How freshness works (why you can trust the labels)

Every job gets one label the first time it is seen:

| Label in your tracker | Meaning | Telegram alert? |
|---|---|---|
| **Verified fresh** | The company's own timestamp says it was published within the last 12 hours (or, for boards that only give a date, it appeared right after our previous successful check). | **Yes** |
| New on board (age unverified) | It just appeared on a board we check, but the company gives no date. | No (Sheet only) |
| Recent | Published more than 12 hours ago, within `Max_Job_Age_Days`. | No (Sheet only) |
| Age unverified | No date and we had no recent check of that board. | No (Sheet only) |

Jobs already on a board when we first discover it are **not** treated as new: they are quietly recorded as the starting point. Jobs older than `Max_Job_Age_Days` are skipped. "Last updated" times are never mistaken for publication times.

If GitHub runs the job late or skips a run, the hidden `Runs` tab records the real gap, and jobs found after a long gap are labelled honestly (they will show as *Recent*, not *Verified fresh*).

## Where the list of boards comes from

Three sources feed one list: a rotating Google search (every 12 hours; see below), manual seeds, and two public company lists that are imported weekly: [open-ats-feed](https://github.com/veresk06/open-ats-feed) and [ats-scrapers](https://github.com/kalil0321/ats-scrapers) (MIT, see `NOTICE.md`). Together that is about **21,900 boards** on the five supported systems. Only the *names of boards* come from those lists: every job is read from the company's own board.

### How the Google search works (and what it cannot do)
- **Rotation.** Every 12 hours the app searches Google for a few combinations of *one job site x one role word x one location* (about 6 sites x your roles x your locations), restricted to pages Google indexed in the last 3 days (`qdr:d3`). Where it stopped is stored in the hidden `Discovery` tab, so each run continues with the next combinations and a full pass takes many days. Changing your Settings does not restart the rotation.
- **Search only finds candidates.** Google's 3-day filter says when a page was indexed or changed, never when the job was published. A job is only called fresh when the company's own board gives a publish time inside the window.
- **Every result is used twice.** Its *board* is added to the shared list (even if that job is old, already seen or excluded), and its *job*, if never seen, is read from the company's board and goes through the normal matching, scoring and alert steps.
- **One set of rules for every source.** Boards from Google, the public lists and manual seeds all go through the same checks: supported provider, valid identifier, validated against the company's own API, best matches first, and never beyond `Max_Active_Boards` / `Max_New_Boards_Per_Run`. SmartRecruiters boards stay parked whatever the source (see `DECISIONS.md` D-13), unless `ALLOW_SMARTRECRUITERS_BULK=1`.
- **Bounded.** A query stops paging after two pages in a row that add nothing new, and a run stops at its credit budget. It never keeps searching until something new appears.
- **What this does not promise.** A 12-hour search interval and a 12-hour freshness window do **not** guarantee that every new job is caught. Google may index a page late or never; the rotation covers only a slice of all combinations per run; results per query are capped; GitHub may start a run late or skip it; and a board is only polled once it has been admitted within the board budget. Jobs on boards we poll are detected within one successful hourly poll; jobs elsewhere are found only if search happens to surface them in time.

Not every listed board is checked every hour. New boards are first **validated** (does it exist? does it have jobs that match your targets?) by a separate workflow (**Board Inventory**, weekly refresh plus a daily validation pass), then the best matches are added to the hourly checks within the limit set by `Max_Active_Boards`. Each newly watched board is read once as a starting point, so its existing jobs never look "just posted". The hidden `Boards` tab shows every board, where it came from, and its status; the hidden `Runs` tab shows how many were discovered, validated and actively watched.

Providers these lists contain but this app cannot read yet (for example Breezy, Recruitee, Teamtailor, Workday, BambooHR, Personio) are counted in the import report and ignored. **SmartRecruiters** boards from the lists are parked rather than bulk-checked, because that company's own `robots.txt` asks automated tools to stay away.

## What you'll use (all have free tiers)

| Service | What it does | Where to get the key |
|---|---|---|
| Google Sheets | Your settings and your job tracker | a Google Cloud service account (step 1) |
| Serper | Searches Google to discover company job boards | https://serper.dev |
| Groq | The AI that scores each job | https://console.groq.com/keys |
| Telegram | Phone alerts | @BotFather in Telegram (step 4) |
| GitHub Actions | Runs it for you every hour | this repository |

## One-time setup (about 20 minutes)

### 1. Make the Google Sheet and a "robot" account that can edit it
1. Create a new, **blank** Google Sheet. Name it anything (e.g. "Job Hunter"). Copy its **Sheet ID** from the address bar: `docs.google.com/spreadsheets/d/`**`THIS_PART`**`/edit`.
2. Go to https://console.cloud.google.com → create a project (any name).
3. In that project, enable two APIs: **Google Sheets API** and **Google Drive API** (search for them under *APIs & Services → Library* and click *Enable*).
4. *APIs & Services → Credentials → Create credentials → Service account*. Give it any name and click through to finish.
5. Open the service account → **Keys** tab → *Add key → Create new key → JSON*. A `.json` file downloads. Keep it private.
6. Open that JSON file in a text editor and copy the `client_email` value (it looks like `name@project.iam.gserviceaccount.com`).
7. In your Google Sheet, click **Share**, paste that email, and give it **Editor** access.

### 2. Get the other keys
- **Serper:** sign up at https://serper.dev and copy your API key.
- **Groq:** sign up at https://console.groq.com/keys and create an API key.

### 3. Put the keys into GitHub
In this repository: **Settings → Secrets and variables → Actions → New repository secret**. Add each of these (name on the left):

| Secret name | Value |
|---|---|
| `SERPER_API_KEY` | your Serper key |
| `GROQ_API_KEY` | your Groq key |
| `GOOGLE_SHEET_ID` | the Sheet ID from step 1 |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | open the downloaded `.json` file, select **everything**, paste it here |
| `TELEGRAM_BOT_TOKEN` | from step 4 (optional) |
| `TELEGRAM_CHAT_ID` | from step 4 (optional) |

> **Use a private repository.**

### 4. Telegram alerts (optional but recommended)
1. In Telegram, message **@BotFather**, send `/newbot`, follow the prompts, and copy the **token** it gives you.
2. Open a chat with your new bot and send it any message (like "hi").
3. In a browser, open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` (put your token in place of `<YOUR_TOKEN>`). Find `"chat":{"id":123456789` — that number is your **chat ID**.

### 5. First run
Go to the **Actions** tab → **Job Hunter** → **Run workflow**, tick **"Also search Google for new company job boards right now"**, and run it. The first run creates the tabs in your Sheet: **Settings** (filled with defaults), **Job Tracker**, and three hidden internal tabs (**Boards**, **Events**, **Runs**). Open the Sheet, go to **Settings**, and **paste your resume into the `Resume_Text` row** (adjust anything else). From then on it runs by itself every hour.

The first runs mostly *learn* the boards (quietly recording what is already there), so don't expect alerts immediately. The list of watched boards grows each time discovery runs (every 12 hours by default). More boards means more coverage; see the hidden `Boards` tab (View → Hidden sheets) for what is being watched.

## Using it day to day

**Settings tab** (edit any time; the next run uses the new values; blank cells fall back to defaults):

| Setting | What it does |
|---|---|
| `Resume_Text` | Your resume as plain text. The AI scores jobs against this. |
| `Target_Roles` | Job-title words a title must contain (comma-separated). |
| `Target_Levels` | Level words a title must contain (Intern, Associate…). |
| `Excluded_Title_Words` | Titles containing these are skipped before any AI is used. |
| `Target_Locations` | Where you want to work. Include `US Remote` for US-wide remote jobs. |
| `Min_Alert_Score` | Jobs at or above this score are marked **To Apply**; fresh ones are sent to Telegram. |
| `Max_Job_Age_Days` | Jobs published longer ago than this are skipped. |
| `Fresh_Window_Hours` | How recent "verified fresh" must be (default 12). Your own value always wins. **If your Sheet still says 4, that is the old default and is kept as is: change it to 12 if you want the new window** (the hidden `Runs` tab notes it every run). |
| `Discovery_Every_Hours` | How often the rotating Google search runs (default 12). Independent of `Fresh_Window_Hours`. |
| `Timezone` | Time zone for the dates in your tracker, e.g. `America/Chicago`. Leave blank to use the Google Sheet's own time zone (File > Settings > Time zone). The app runs on a server, so it cannot see each viewer's own zone: set this once if the Sheet's zone is not yours. |
| `Discovery_Credit_Budget` | Most search credits one Google discovery run may spend (default 10). A hard cap. Sheets made before this setting existed use the default. |
| `Max_Active_Boards` | Most company boards checked every hour (default 500). Imported boards join gradually, best matches first, up to this limit. |
| `Max_New_Boards_Per_Run` | Most new boards added to the hourly checks in one run (default 50). |

**Job Tracker tab** shows jobs scoring 50 or higher. The script only ever *adds* rows, so your edits are safe:

| Column | Meaning |
|---|---|
| `Date_Found` / `Date_Posted` | When we found it / when the company published it (blank if the company gives none) |
| `My_Status` | Starts as **To Apply** (score at or above `Min_Alert_Score`) or **Stretch / Review**. **Yours to change**: `Applied` → `Interviewing` → `Offer` / `Pass` |
| `AI_Score`, `AI_Verdict`, `Missing_Gaps` | 0–100 fit, a one-sentence reason, and what you're missing |
| `Company_and_Title`, `Location` | The job |
| `Apply_URL` | Click to apply |
| `User_Notes` | **Yours** |
| `Freshness`, `Source` | How sure we are it's new (see the table above), and whether it came from a watched board or a search |

The hidden tabs are the app's memory (which jobs were seen, scored and alerted, which boards are watched, and a log of every run). Please don't edit them; to make the app re-check a job, ask a developer.

### How scoring works
Before the AI sees a job, simple checks remove clear mismatches: the title must contain a target role and level word and no excluded word; the location must not be outside the US; it must not demand 4+ years of experience or a language your resume doesn't show. The AI then scores the survivors 0–100 against your resume:
- **80–100** strong early-career fit in a target location or US-eligible Remote
- **65–79** stretch (about 2–3 years, or a couple of unfamiliar tools)
- **26–64** partial fit
- **0–25** hard no

## If something goes wrong
- **Telegram or the Sheet is down:** nothing is lost. A job is only marked "scored" or "alerted" after that step really worked, so the next hourly run retries it. A retry is never discarded because the job got older: if it is delivered after the 12-hour window it says so ("delivered late"). In rare cases an alert may arrive twice.
- **Groq rate limits:** it automatically falls back to a smaller model and retries later; jobs it couldn't score are picked up next run. A bad Groq key stops the run with a clear error in the Actions log.
- **No alerts for a while:** that can be normal. Check the hidden `Runs` tab: how many boards were polled, how many new jobs were found, and the gap since the previous run.

## Good to know
- **Free-tier limits.** Groq's free tier caps requests and tokens per minute, so a run scores about 30 jobs at most (`MAX_JOBS_PER_RUN`), freshest first.
- **Serper credits.** Discovery spends at most `Discovery_Credit_Budget` credits (default 10, one per results page) per run, twice a day by default: at most 20 a day. Polling boards uses no search credits. Unfiltered searches never run on the schedule; the manual `--backfill` option exists for a one-off broad sweep (`python hunter.py --backfill --backfill-credits 12`).
- **Very large boards** (for example job aggregators) are polled like any other; their jobs go through the same filters.

## Running it on your own computer (optional, for developers)
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```
Create a `.env` file (never commit it) with the same names as the secrets above:

```
SERPER_API_KEY=
GROQ_API_KEY=
GOOGLE_SHEET_ID=
GOOGLE_SERVICE_ACCOUNT_JSON=      # raw JSON, or the path to the downloaded .json file
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```
Without `GOOGLE_SHEET_ID` it uses default settings, `resume.txt`, and local files (`tracked_jobs.csv`, `state/`).

```bash
python hunter.py --seed greenhouse:gyde --dry-run   # poll one board, classify jobs, write and send nothing
python hunter.py --url "https://boards.greenhouse.io/<board>/jobs/<id>"   # run one job through the real gates and scorer
python hunter.py --discover                          # force a board-discovery pass now
python hunter.py --discover --no-tbs                 # discovery without the 3-day search window
python hunter.py --import-inventory                  # download both company lists and merge new boards (idempotent)
python hunter.py --validate --max-validations 500    # check unvalidated boards (Lever is limited to 1 request/second)
python hunter.py --inventory-report                  # counts: discovered / validated / actively monitored
python hunter.py --import-inventory --offline        # re-merge from the saved copies (no download)
python -m unittest discover -s tests                 # offline tests
```

Optional environment variables: `GROQ_MODEL` (default `openai/gpt-oss-120b`), `GROQ_FALLBACK_MODEL` (default `openai/gpt-oss-20b`), `ALLOW_SMARTRECRUITERS_BULK`, `MAX_JOBS_PER_RUN`, `SEARCH_PAGES` (pages per query for `--backfill` only), `SEARCH_TBS` (default `qdr:d3`; cannot unfilter scheduled discovery), `ALERT_WEBHOOK_URL`.

Project documents for contributors and agents: `SPEC.md` (requirements), `DECISIONS.md` (why), `STATUS.md` (what is verified), `AGENTS.md`. The earlier keyword-scoring version is kept in `legacy/`.
