# Job Hunter

Every 2 hours during US business hours (Mon–Fri), this finds new job postings (Greenhouse, Lever, Ashby, Workable, SmartRecruiters), has an AI score each one against **your resume**, logs everything in **a Google Sheet**, and sends the best matches to **Telegram** on your phone.

**After the one-time setup below, you never touch code.** You change your search by editing the Google Sheet, and you track applications in the same sheet.

```
Google Sheet "Settings" tab ──► search (Serper) ──► read each posting ──► AI score (Groq) ──► Google Sheet "Job Tracker" tab ──► Telegram
```

## What you'll use (all have free tiers)

| Service | What it does | Where to get the key |
|---|---|---|
| Google Sheets | Your settings + your job tracker | a Google Cloud service account (step 1) |
| Serper | Searches Google for postings | https://serper.dev |
| Groq | The AI that scores each job | https://console.groq.com/keys |
| Telegram | Phone alerts | @BotFather in Telegram (step 4) |
| GitHub Actions | Runs it for you every 2 hours | this repository |

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

> **Use a private repository.** Your resume gets stored in your Google Sheet, but `resume.txt` (if you keep it) lives in the repo.

### 4. Telegram alerts (optional but recommended)
1. In Telegram, message **@BotFather**, send `/newbot`, follow the prompts, and copy the **token** it gives you.
2. Open a chat with your new bot and send it any message (like "hi").
3. In a browser, open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` (put your token in place of `<YOUR_TOKEN>`). Find `"chat":{"id":123456789` — that number is your **chat ID**.

### 5. First run
Go to the **Actions** tab → **Job Hunter** → **Run workflow**. The first run creates the tabs in your Sheet: **Settings** (filled with defaults), **Job Tracker**, and a hidden **Seen_Archive**. Open the Sheet, go to **Settings**, and **paste your resume into the `Resume_Text` row** (and adjust anything else). From then on it runs by itself every 2 hours, Monday to Friday, between 13:00 and 23:00 UTC.

## Using it day to day

**Settings tab** (edit any time; the next run uses the new values; blank cells fall back to defaults):

| Setting | What it does |
|---|---|
| `Resume_Text` | Your resume as plain text. The AI scores jobs against this. |
| `Target_Roles` | Job-title words to search for (comma-separated). |
| `Target_Levels` | Level words that should be in the title (Intern, Associate…). |
| `Excluded_Title_Words` | Titles containing these are skipped before the AI is used. |
| `Target_Locations` | Where you want to work. Include `US Remote` for US-wide remote jobs. |
| `Min_Alert_Score` | Jobs at or above this score are marked **To Apply** and sent to Telegram. |
| `Max_Job_Age_Days` | Jobs published longer ago than this are skipped as stale. |

**Job Tracker tab** only shows jobs worth your time (score 50 or higher). The script only ever *adds* rows, so your edits are safe:

| Column | Meaning |
|---|---|
| `Date_Found` / `Date_Posted` | When we found it / when the company actually published it |
| `My_Status` | Starts as **To Apply** (score at or above `Min_Alert_Score`) or **Stretch / Review** (score 50 up to the minimum). **Yours to change**: `Applied` → `Interviewing` → `Offer` / `Pass` |
| `AI_Score` | 0–100 fit with your resume |
| `Company_and_Title`, `Location` | The job |
| `AI_Verdict`, `Missing_Gaps` | One-sentence reason, and what you're missing |
| `Apply_URL` | Click to apply (don't delete this column: it's how duplicates are avoided) |
| `User_Notes` | **Yours** |

**Seen_Archive tab** (hidden): low scorers (under 50), closed postings, stale postings and errors are logged here with a one-line reason, only so the same job is never fetched twice. To see it: *View → Hidden sheets*. To make the script re-check a job, delete its row there.

**Telegram:** every new job scoring at or above `Min_Alert_Score` sends you a message with the title, company, location, score, a plain-English verdict, what you're missing, a direct **Apply** link, and a link to your tracker. *Stretch / Review* jobs are only in the Sheet.

### How scoring works
The AI reads your resume, your target roles and locations, and the full job posting, and scores 0–100:
- **80–100** strong early-career fit (0–2 years required; internships and projects count) in a target location or US-eligible Remote
- **65–79** stretch (about 2–3 years, or a couple of unfamiliar tools)
- **26–64** partial fit
- **0–25** hard no: 4+ years minimum, wrong location, a required language or license you don't have, or an unrelated field

## Good to know
- **Cost of mistakes.** Scores come from an AI reading the posting: treat them as a first filter, not a verdict.
- **Free-tier limits.** Groq's free tier caps requests and tokens per minute, so a run scores about 30 jobs at most (`MAX_JOBS_PER_RUN`). If the main model is rate-limited it automatically uses a smaller one. Jobs it couldn't score this run are retried on the next run.
- **Serper credits.** Each run uses about 4 searches (2 queries × 2 pages). Check your remaining credits at serper.dev.
- **Two-layer freshness.** (1) Search only looks at pages Google indexed in the **past 3 days** (`SEARCH_TBS`, default `qdr:d3`), so results rotate with new postings instead of repeating the same evergreen pages; the script runs every 2 hours and skips anything it has already seen. (2) Google's window follows page edits, not posting dates, so each new posting's **real publication date** is read from its job board, and anything older than `Max_Job_Age_Days` is archived as stale. Trade-off: a posting Google hasn't dated yet can be missed until it is. To backfill without the window, run `python hunter.py --no-tbs` (or set the `SEARCH_TBS` repository variable to `none`).
- **No Google Sheet?** If `GOOGLE_SHEET_ID` isn't set, it uses the default settings and a local `tracked_jobs.csv` instead.

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
 For `GOOGLE_SERVICE_ACCOUNT_JSON` you can use the path to the downloaded `.json` file.

```bash
python hunter.py --dry-run --url "https://boards.greenhouse.io/<board>/jobs/<id>"   # score one job, write nothing
python hunter.py                                                                     # full run
python -m unittest discover -s tests                                                 # offline tests
```

Environment variables (all optional unless noted): `SERPER_API_KEY` (required; the older name `SEARCH_API_KEY` also works), `GROQ_API_KEY` (required), `GOOGLE_SHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `ALERT_WEBHOOK_URL`, `GROQ_MODEL`, `GROQ_FALLBACK_MODEL`, `MAX_JOBS_PER_RUN`, `SEARCH_PAGES`, `SEARCH_TBS` (default `qdr:d3`).

The previous keyword-scoring version is kept in `legacy/` for reference.
