# SPEC: Fresh-job alerts for a non-technical user

Status of this file: the contract. Change behavior only after changing (or flagging a conflict with) this file.

## Goal

Surface relevant jobs **within 4 hours of their publication** to a non-technical user. Google Sheets is the only interface (settings in, tracker out). Telegram delivers push alerts for top matches.

## Honest limits (read before promising anything)

- Coverage = the ATS boards we have **discovered and can poll** (Greenhouse, Lever, Ashby, Workable, SmartRecruiters). Jobs on other ATSs, company-hosted pages, LinkedIn, Indeed, etc. are not covered.
- We **cannot guarantee** earlier or broader coverage than LinkedIn/Indeed. We can only guarantee that, for a polled board, a job is detected within one successful polling interval and that its freshness is stated truthfully.
- GitHub Actions schedules are best-effort: runs can start late or be skipped. The 4-hour target holds only while successful polls keep occurring; the system records actual gaps and labels late finds as not fresh.

## Loops

1. **Discovery loop** (Serper; every `Discovery_Every_Hours`, default 12): unfiltered role searches find job and board URLs; every `(ATS, board)` found is added to a persistent **Boards registry**. A second, date-windowed Serper search (`qdr:d3`) is **supplemental job discovery** for jobs on boards we may not poll yet.
2. **Polling loop** (hourly, 24/7 including nights and weekends): for every active board, list all current jobs from the ATS public API and detect job IDs we have not seen.

3. **Inventory loop** (weekly refresh + daily validation, separate workflow): two public company lists seed the same registry (see "Board registry"). It never scores or alerts.

The user never selects companies.

## Board registry

One persistent registry (hidden `Boards` tab) holds every board from every source: Serper discoveries, the `open-ats-feed` inventory, the `ats-scrapers` inventory, and manual seeds.

- **Identity:** provider + region/API host + board identifier. The default region is empty, so existing keys are unchanged. Casing follows the provider: Lever and Workable identifiers are case-sensitive (kept exactly); Greenhouse, Ashby and SmartRecruiters are not (compared lowercase, first-seen spelling used for API calls). Each unique board is polled once, however many sources list it.
- **Provenance:** every source that listed a board is recorded with its first-seen time; `Discovered_At` is the first time any source knew it; `Last_Validated_At` is the last time its adapter call succeeded.
- **Statuses:** `candidate` (imported, unvalidated) -> `validated` (exists; waiting for a monitoring slot) -> `new` (activated, not yet baselined) -> `active`. Also `invalid` (404/410), `deferred` (blocked by policy), `disabled` (monitored board that kept failing). Rows are never deleted, and an upstream list dropping a board changes nothing.
- **Validation outcomes:** `valid` (jobs listed), `valid_empty` (exists, no jobs), `invalid` (404/410), `transient` (timeouts, 5xx, 429, bad payload: retried with backoff, never read as closed).
- **Imports are additive and idempotent:** re-importing an unchanged inventory writes nothing and never alters polling history, posting IDs, alert state or Serper discoveries. A failed or malformed download keeps the last-known-good copy.
- **Polling budget:** only `new`/`active` boards are polled. Validated boards are promoted by the poller, at most `Max_New_Boards_Per_Run` at a time and never beyond `Max_Active_Boards`, boards with jobs matching the user's targets first. Counts (discovered / validated / monitored) are logged per run.
- **Baselining applies to imported boards exactly as to discovered ones:** the first poll records the existing jobs as `baseline` (not evaluated, no backfill); only a job whose source timestamp proves it fresh is evaluated.
- **Provider limits honoured:** Lever's `Crawl-delay: 1` is enforced; SmartRecruiters' API host disallows generic crawlers in `robots.txt`, so bulk validation of its imported boards is off by default (`ALLOW_SMARTRECRUITERS_BULK=1` opts in). SmartRecruiters also answers 200/empty for unknown companies, so its boards cannot be proven to exist.

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
| `verified_fresh` | Time-precision source publication age <= `Fresh_Window_Hours` (default 4); or day-precision date within the last day AND the board gap <= window. | Yes |
| `observed_new` | No source date; new ID on a baselined board with gap <= window. Age unverified. | No (tracker only) |
| `recent` | Source date known, older than the window, within `Max_Job_Age_Days`. | No (tracker only) |
| `uncertain` | No source date and no usable board gap (e.g. Serper-only). | No (tracker only) |
| `stale` | Source date older than `Max_Job_Age_Days`. | No, not evaluated |
| `baseline` | Already on a board when it was first polled. Not treated as new. | No, not evaluated |

**Baselining:** the first successful poll of a newly discovered board records all existing IDs as `baseline`; only jobs with a verified-fresh source time are evaluated.

## State model (separate, individually retryable)

- **Seen**: first observation recorded (with class and evidence).
- **Evaluated**: gates and scoring completed; outcome stored.
- **Alerted**: Telegram message accepted by the API.

A failure at one stage never marks later stages done. Transient failures (timeouts, 5xx, 429, Groq outage, Sheets/Telegram errors) are retried on later runs, up to 5 attempts, then abandoned with a recorded reason. Delivery is at-least-once (a duplicate alert is possible if the process dies between sending and recording).

## Filtering order

1. Cheap checks on listing data (before any fetch): roles keyword in title, level keyword in title, excluded title words, freshness class.
2. Hydrate the full posting from the ATS (authoritative date, location, text).
3. Hard eligibility rules (deterministic): age, excluded title (full), non-US location, minimum experience >= 4 years, required foreign language.
4. Resume-fit scoring (Groq) only for postings that pass 1-3.

## Delivery

- **Job Tracker** tab (visible): jobs scoring >= 50; `To Apply` (>= `Min_Alert_Score`) or `Stretch / Review`; columns include `Freshness` and `Source`. Append-only; user edits to `My_Status` / `User_Notes` are never overwritten.
- **Telegram**: one message per `verified_fresh` job scoring >= `Min_Alert_Score`, with title, company, location, score, verdict, gaps, apply link, tracker link.
- Hidden tabs hold internal state: `Boards`, `Events` (append-only ledger), `Runs`.

## Observability

Each run appends a `Runs` row: boards polled/failed, new jobs by class, alerts sent/failed, gap since the previous run, worst board gap, max alert lag. Per-board `Last_Success_At` is kept in `Boards`.

## Out of scope for now

Tuning scores, additional ATSs, non-US markets, email/SMS, a web UI, guaranteeing parity with job boards.

## Acceptance (smallest complete path)

Board poll -> new-ID detection -> keyword/eligibility gates -> scoring -> Sheet row -> Telegram alert, with: baselining proven, freshness class correct per evidence, retries proven for scoring and alert failures, polling gaps recorded. Live verification of Sheets, Groq and Telegram requires the user's credentials; until then they are reported as mocked-only.
