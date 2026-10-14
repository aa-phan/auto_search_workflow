# SPEC: Fresh-job alerts for a non-technical user

Status of this file: the contract. Change behavior only after changing (or flagging a conflict with) this file.

## Goal

Surface relevant jobs **within 12 hours of their publication** (`Fresh_Window_Hours`, default 12) to a non-technical user. Google Sheets is the only interface (settings in, tracker out). Telegram delivers push alerts for top matches.

## Honest limits (read before promising anything)

- Coverage = the ATS boards we have **discovered and can poll** (Greenhouse, Lever, Ashby, Workable, SmartRecruiters). Jobs on other ATSs, company-hosted pages, LinkedIn, Indeed, etc. are not covered.
- We **cannot guarantee** earlier or broader coverage than LinkedIn/Indeed. We can only guarantee that, for a polled board, a job is detected within one successful polling interval and that its freshness is stated truthfully.
- GitHub Actions schedules are best-effort: runs can start late or be skipped. The 12-hour target holds only while successful polls keep occurring; the system records actual gaps and labels late finds as not fresh.

## Loops

1. **Discovery loop** (Serper; every `Discovery_Every_Hours`, default 12; a setting independent of the freshness window): a rotating set of date-windowed searches (`qdr:d3`) retrieves candidates. Unfiltered searches are never scheduled; they exist only as the explicit manual `--backfill`. See "Discovery".
2. **Polling loop** (hourly, 24/7 including nights and weekends): for every active board, list all current jobs from the ATS public API and detect job IDs we have not seen.

3. **Inventory loop** (weekly refresh + daily validation, separate workflow): two public company lists seed the same registry (see "Board registry"). It never scores or alerts.

The user never selects companies.

## Board registry

One persistent registry (hidden `Boards` tab) holds every board from every source: Serper discoveries, the `open-ats-feed` inventory, the `ats-scrapers` inventory, and manual seeds.

- **Identity:** provider + region/API host + board identifier. The default region is empty, so existing keys are unchanged. Casing follows the provider: Lever and Workable identifiers are case-sensitive (kept exactly); Greenhouse, Ashby and SmartRecruiters are not (compared lowercase, first-seen spelling used for API calls). Each unique board is polled once, however many sources list it.
- **Provenance:** every source that listed a board is recorded with its first-seen time; `Discovered_At` is the first time any source knew it; `Last_Validated_At` is the last time its adapter call succeeded.
- **Statuses:** `candidate` (imported, unvalidated) -> `validated` (exists; waiting for a monitoring slot) -> `new` (activated, not yet baselined) -> `active`. Also `invalid` (404/410), `deferred` (blocked by policy), `disabled` (monitored board that kept failing). Rows are never deleted, and an upstream list dropping a board changes nothing. Two transitions leave monitoring without deleting anything: a **demotion** (`active`/`new` -> `validated`, by the weekly rebalance, see "Polling budget") and a **policy parking** (`new`/`active`/`disabled` -> `deferred`, every run, see "Provider limits"). Both keep the board's baseline, last success, validation, counts, provenance and every ledger event; a board that leaves monitoring resets only its monitoring-stint counters (`Activity_Since`, `Complete_Polls`, activity counts). A `new` board that already has a baseline is **re-entering** monitoring (it was monitored before, left, and was promoted again): its next successful poll re-establishes the baseline (see "Baselining").
- **Board evidence (refreshed by every complete, successful hourly poll, from the listing already fetched; no LLM):** `Relevant_Jobs` (unique posting IDs passing the title gate), `Eligible_Jobs` (those whose listing location is not excluded by the US location rule), `Relevance_At`, `Last_Success_At`, `Complete_Polls`, and the activity fields `Last_New_Relevant_At`, `New_Relevant_7d`, `New_Relevant_30d`. A poll is *complete* when it succeeded, was not rejected as a suspicious empty listing, and the adapter did not truncate the listing (SmartRecruiters past 5,000 postings). A partial listing, a failed poll or a suspicious empty listing changes none of these. Open-job counts and new-posting activity are separate facts.
- **New-posting activity** counts only the first observation of a relevant job by an ordinary board poll (not a baseline or re-entry pass, not a search-found job, not a stale job), at or after the start of the board's current monitoring stint (`Activity_Since`). It is **unknown (blank) until the stint is 7 days old** and a real 0 afterwards: a board with no history is never read as a board with no activity.
- **Validation outcomes:** `valid` (jobs listed), `valid_empty` (exists, no jobs), `invalid` (404/410), `transient` (timeouts, 5xx, 429, bad payload: retried with backoff, never read as closed).
- **Imports are additive and idempotent:** re-importing an unchanged inventory writes nothing and never alters polling history, posting IDs, alert state or Serper discoveries. A failed or malformed download keeps the last-known-good copy.
- **Polling budget and pools:** only `new`/`active` boards are polled, at most `Max_Active_Boards` (default 500). That cap is split into an **established** pool (default 400) and an **exploration** pool (default 100; `Exploration_Share_Percent`, an initial operating choice, not a proven optimum). Validated boards are promoted by the poller (the same rule for every source), at most `Max_New_Boards_Per_Run` at a time and never beyond the cap. Every promoted board enters exploration on a trial of `Exploration_Days` (default 7). Boards **never tried before are admitted first** (the route in for a board with no observation history), then boards with the most open eligible jobs; a board with nothing open for the user's targets keeps waiting.
- **Weekly rebalance (transparent, bounded):** every `Rebalance_Every_Days` (default 7) the poller compares trials that have ended with the weakest established boards. Board score = 2 x min(new relevant postings per week, 5) + min(open eligible jobs, 5), from the evidence columns (rate per observed day, no tenure term, caps so aggregators cannot dominate). A trial graduates to established when established has a free slot, or replaces an established board only when it beats it by more than 1.0 and that board has been the weakest target in **two consecutive** cycles; at most `Max_Replacements_Per_Rebalance` (default 20) established boards leave per cycle; trials still running are never touched; a trial that loses returns to the waiting list only as far as boards are actually waiting. **No board is demoted, shed or graduated on thin evidence:** a decision needs at least `Exploration_Days x 12` complete polls, a successful last poll, evidence refreshed within 24 hours and a known (7-day) activity count; one empty, partial or failed fetch can never be enough. A rebalance runs in **report mode by default** (`Rebalance_Mode`): it records the plan (hidden `Discovery` tab, keys `rebalance`, `rebalance_report`; `Runs.Rebalance`) and moves nobody until the setting is `on`. `python hunter.py --rebalance-report` prints the plan and writes nothing.
- **Transitions are made only by the hourly poller** (promotion, graduation, demotion, trial changes, policy parking); the validation workflow never overwrites a row whose current status is `new`, `active` or `disabled`.
- **Baselining applies to imported boards exactly as to discovered ones:** the first poll records the existing jobs as `baseline` (not evaluated, no backfill); only a job whose source timestamp proves it fresh is evaluated.
- **Provider limits honoured:** Lever's `Crawl-delay: 1` is enforced; SmartRecruiters' API host disallows generic crawlers in `robots.txt`, so bulk validation of its imported boards is off by default (`ALLOW_SMARTRECRUITERS_BULK=1` opts in). SmartRecruiters also answers 200/empty for unknown companies, so its boards cannot be proven to exist. While the provider is parked, **monitored SmartRecruiters boards are parked too, every run** (`deferred`, history kept, not polled) and parked or waiting ones are never promoted; opting in restores the old behavior for new promotions.

## Discovery (search is candidate retrieval only)

- **Rotation:** the slot list is every supported ATS site x role term x location (sites vary fastest). A persistent cursor (hidden `Discovery` tab) selects the next slots each run; editing Settings changes the list and the cursor continues modulo the new length. A run in which every request failed does not advance the cursor. A full cycle takes many runs by design.
- **Budget:** each run spends at most `Discovery_Credit_Budget` credits (default 10; one credit per results page). A query stops paging after 2 consecutive pages that add neither a board candidate nor an unseen job candidate, after a short page, or after 3 pages. These bounds are hard: search never continues "until something new appears".
- **Candidate retrieval only:** the 3-day filter says when Google indexed a page, not when a job was published. Freshness comes from hydrating the posting at its ATS (source publication evidence, with the publication / republication / update / unknown distinctions above). Search-result dates and first observation are never publication time.
- **Two independent paths per result:** (1) its board identifier is submitted to board admission whether or not the job is seen, stale or excluded; (2) if the job identity is unseen and its title passes the cheap gate, it is hydrated and enters the normal evaluate/deliver pipeline. A temporary hydration failure is queued (bounded) and retried without spending credits.
- **Logging:** per query (identity, pages, credits, results, repeated, new boards, unseen jobs, stop reason) in the log and the hidden `Discovery` tab; per run in `Runs`: queries, pages, credits, repeated results, new unique boards, eligible boards, promoted boards, unique verified-fresh matches.
- **Coverage is not complete.** A 12-hour interval and a 12-hour window do not guarantee that everything inside the window is caught: indexing delay, a rotation that covers only part of the space per run, per-query result limits and late or skipped scheduled runs all cause misses. Only jobs on polled boards carry the polling guarantee.

## Board admission (all sources)

Inventory imports, Serper results and manual seeds follow the same steps with the same functions (`merge_candidates`, `policy_blocks`, `validate_board` / `apply_validation`, `activate_waiting`). Search results and manual seeds run them inline per run (`inventory.admit_boards`); the importer runs them in batch (import, then the validation job): identifier sanity and supported provider -> registered as `candidate` with provenance -> provider policy (SmartRecruiters parked) -> validation through the ATS adapter (bounded inline for search/seed boards; the validation workflow handles the rest) -> prioritisation (most title-gate matches first) -> promotion only within `Max_Active_Boards` and `Max_New_Boards_Per_Run`. No source starts monitoring directly. A board already in the registry only gains provenance. Each unique board is polled once per run.

## Identity and dedupe

- Job identity = **ATS + board + posting ID**. Key: `ats|board(lowercase)|id`. URLs, hosts (`boards.` vs `job-boards.`), slugs and tracking parameters are not identity.
- Identity-bearing URL parameters are preserved when parsing (Greenhouse embed `for` and `token`, `gh_jid`). Tracking parameters (`utm_*`, `gh_src`, `lever-source`, ...) are ignored.

## Freshness vocabulary

| Term | Meaning |
|---|---|
| Source publication time | The ATS's creation/publish timestamp (Lever `createdAt`, Greenhouse `first_published`, Ashby `publishedAt`, Workable `published`, SmartRecruiters `releasedDate`). Precision is `time` or `day` (Workable is day-only). |
| First observation | When this system first saw the ID on a poll or search. |
| Update | The source's last-modified field changed (e.g. Greenhouse `updated_at`). Never treated as publication. |
| Republication | The source publication time moved later for a known ID, or an ID reappeared after absence. Logged; the job is not re-alerted. |
| Board gap | Time since the board's previous successful poll. A new ID on a baselined board was not visible at that earlier poll. |

Freshness classes (assigned once, at first observation, with the evidence recorded):

| Class | Rule | Alert? |
|---|---|---|
| `verified_fresh` | Time-precision source publication age <= `Fresh_Window_Hours` (default 12; the boundary itself counts as inside); or day-precision date within the last day AND the board gap <= window. | Yes |
| `observed_new` | No source date; new ID on a baselined board with gap <= window. Age unverified. | No (tracker only) |
| `recent` | Source date known, older than the window, within `Max_Job_Age_Days`. | No (tracker only) |
| `uncertain` | No source date and no usable board gap (e.g. Serper-only). | No (tracker only) |
| `stale` | Source date older than `Max_Job_Age_Days`. | No, not evaluated |
| `baseline` | Already on a board when it was first polled. Not treated as new. | No, not evaluated |

**Baselining:** the first successful poll of a newly admitted board records all existing IDs as `baseline`; only jobs whose time-precision source publication time is inside the window are evaluated. Day-precision dates cannot prove a 12-hour window on a first poll, so those stay `baseline`.

**Re-entry:** when a board that left monitoring is promoted again, its next successful poll is a re-entry pass. Already-seen IDs stay as they are (no new `seen` event). For an unseen ID the real board gap applies: a job with a time-precision source date inside the window is `verified_fresh` (alertable); a dated job outside the window is `recent` or `stale` as usual (a future date is `uncertain`); an **undated** job is `baseline` when the gap is longer than the window ("appeared while the board was not monitored; no source date"), never `observed_new` or `verified_fresh`. The pass then re-establishes the baseline and starts a new monitoring stint; re-entry observations are not new-posting activity.

## State model (separate, individually retryable)

- **Seen**: first observation recorded (with class and evidence).
- **Evaluated**: gates and scoring completed; outcome stored.
- **Alerted**: Telegram message accepted by the API.

A failure at one stage never marks later stages done. These stages belong to the job's ledger, not to its board: a pending evaluation or alert retry survives the board being demoted, parked or disabled. Transient failures (timeouts, 5xx, 429, Groq outage, Sheets/Telegram errors) are retried on later runs; rejected requests and permanent-looking failures are bounded at 5 attempts, then abandoned with a recorded reason. **A pending retry is never dropped because its job aged past the window**: the freshness class was verified at first observation and stays; an alert delivered after the window is labelled "delivered late". Delivery is at-least-once (a duplicate alert is possible if the process dies between sending and recording).

## Filtering order

1. Cheap checks on listing data (before any fetch): roles keyword in title, level keyword in title, excluded title words, freshness class. A space and a hyphen are interchangeable inside a configured term ("Entry Level" matches "Entry-Level"), and when `Target_Levels` contains Intern or Junior, "Internship" and "Jr"/"Jr." also match. A level keyword is still required; seniority exclusions are checked first and unchanged.
2. Hydrate the full posting from the ATS (authoritative date, location, text).
3. Hard eligibility rules (deterministic): age, excluded title (full), non-US location, minimum experience >= 4 years, required foreign language.
4. Resume-fit scoring (Groq) only for postings that pass 1-3.

## Delivery

- **Job Tracker** tab (visible): jobs scoring >= 50; `To Apply` (>= `Min_Alert_Score`) or `Stretch / Review`; columns include `Freshness` and `Source`. Append-only; user edits to `My_Status` / `User_Notes` are never overwritten.
- **Telegram**: one message per `verified_fresh` job scoring >= `Min_Alert_Score`, with title, company, location, score, verdict, gaps, apply link, tracker link.
- Hidden tabs hold internal state: `Boards`, `Events` (append-only ledger), `Runs`, `Discovery` (rotation cursor, hydration retry queue, last run's queries).

## Observability

Each run appends a `Runs` row: boards polled/failed, new jobs by class, alerts sent/failed, gap since the previous run, worst board gap, max alert lag. The Runs row also records pool membership (`Pool_Established`, `Pool_Exploration`), the relevant waiting list (`Waiting_Relevant`, `Oldest_Waiting_Hours`), `Relevant_Coverage_Pct` (monitored boards with open relevant jobs as a share of those plus the relevant boards still waiting), `Graduated`, `Demoted`, `Parked_Policy` and `Rebalance` (blank = not due, `report`, `applied`); every pool transition is logged with its reason. Per-board `Last_Success_At` is kept in `Boards`, together with its evidence columns (`Eligible_Jobs`, `Relevance_At`, `Activity_Since`, `Complete_Polls`, `Last_New_Relevant_At`, `New_Relevant_7d`, `New_Relevant_30d`) and its pool state (`Pool`, `Pool_Since`, `Trial_Until`, `Trials`, `Weak_Streak`, `Pool_Reason`). Older rows without these columns load with unknown evidence (blank, never 0).

## Out of scope for now

Tuning scores, additional ATSs, non-US markets, email/SMS, a web UI, guaranteeing parity with job boards.

## Acceptance (smallest complete path)

Board poll -> new-ID detection -> keyword/eligibility gates -> scoring -> Sheet row -> Telegram alert, with: baselining proven, freshness class correct per evidence, retries proven for scoring and alert failures, polling gaps recorded. Live verification of Sheets, Groq and Telegram requires the user's credentials; until then they are reported as mocked-only.
