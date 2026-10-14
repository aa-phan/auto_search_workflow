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

The user never selects companies.

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
