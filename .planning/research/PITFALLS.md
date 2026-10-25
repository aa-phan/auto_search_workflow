# Pitfalls Research

**Domain:** Fresh-job alert poller (ATS public APIs + Google Sheets ledger + Groq scoring + Telegram + Tavily), milestone v2.0 "Search-substitute volume" (adding recent backfill, a 72 h tracker window, 1,000+ boards, feedback-driven board cycling, Workday/iCIMS adapters, wider web search)
**Researched:** 2026-10-25
**Confidence:** MEDIUM-HIGH. External limits come from official docs fetched today or from live probes (HIGH). Behaviour of Workday/iCIMS at scale from GitHub Actions IPs, Ashby/Lever republish semantics and the Groq free-tier numbers for this account are not verified (MEDIUM/LOW, marked inline).

## Phase vocabulary used below (roadmapper may renumber)

| Tag | Phase | Contents |
|-----|-------|----------|
| P1 | Storage and limits foundation | D-43 Identity/Daily migration, quota and headroom instrumentation, Groq budget governance (GOV-01), baseline measurement |
| P2 | Freshness-safe backfill + 72 h tracker | D-05 change, new freshness class, age labelling, prioritised evaluation queue |
| P3 | Board scale + feedback-informed cycling | cap past 700, board-cycling score, exploration protection |
| P4 | New ATS adapters | Workday first (iCIMS only after a feasibility spike) |
| P5 | Wider web search | roles x sites rotation, credit use |
| P6 | Measurement | tracker rows/day, age, My_Feedback evaluation (starts in P1, not last) |

**Overriding finding:** the single most likely v2.0 failure is not a freshness bug but **Groq's free-tier daily token budget** (Pitfall 1). The 20-30 rows/day target needs roughly 3-4x more scoring calls than the free tier can carry. It decides phase order and whether the owner must approve a paid tier.

---

## Critical Pitfalls

### Pitfall 1: Groq free-tier daily token cap makes the volume target unreachable (and backfill starves live alerts)

**What goes wrong:** Scoring volume must rise about 3-4x (target 20-30 tracker rows/day; pilot funnel kept 47 of 260 scored = 18%, so about 110-165 scorings/day against 37/day measured in the pilot). Groq limits are per organization and per model. Documented base limits for `openai/gpt-oss-120b` and `-20b` are **30 RPM, 1K RPD, 8K TPM, 200K TPD**. Each call sends up to 7,000 chars of resume + up to 7,000 chars of job text (`RESUME_CHARS`/`JD_CHARS` in `hunter.py`) plus a system prompt, and reserves up to 1,000 output tokens that gpt-oss spends on hidden reasoning. That is about 3.5-5k tokens per call, so roughly **2 calls/minute (TPM) and about 40-55 calls/day (TPD)**. Pilot scoring (about 37/day) is already near that ceiling. A backfill wave (about 0.4 relevant jobs per board per 72 h at pilot rates, so +300 boards is roughly 100-300 jobs, more with the widened title Settings) consumes days of budget in one go. If backfill and live-fresh jobs share one FIFO, a verified-fresh job waits behind backfill, misses the 12 h alert window and the core value breaks.

**Why it happens:** Free-tier limits were fine at 3 alerts/day. Volume-over-precision multiplies calls, not alerts. Backfill is "one-time", so nobody budgets for it. The 429 fallback and `model_not_found` paths are mock-only (STATUS), and D-16 (model names) still has no owner OK.

**How to avoid:**
1. Treat Groq capacity as a first-class budget in P1: record per-run and per-day tokens (the `Runs` table already has `Groq_Calls`/`Groq_429`; add tokens used and tokens remaining from the `x-ratelimit-*` response headers).
2. **Strict priority queue:** `verified_fresh` (<= 12 h) first, then backfill newest-first. Cap backfill to a share of the remaining daily tokens (for example at most 50% and never when the remaining budget is under a reserve for live alerts). Backfill that cannot be scored stays pending and retryable (AGENTS rule 4), never converted to a permanent "skipped".
3. Keep prompt prefix identical across calls so Groq prompt caching applies: system prompt, target roles/locations and resume come first (the code already orders them so), job text last. Groq documents that `gpt-oss-120b` supports prefix caching (exact prefix match, 2 h TTL, minimum 128-1,024 tokens) and **cached tokens do not count toward rate limits**. Do not put timestamps or per-run values before the resume. A Settings edit that changes the resume or roles invalidates the cache.
4. Reduce tokens per call: cap `JD_CHARS` lower for the pre-screen, use deterministic hard rules first (already D-08), consider a cheap pre-screen on `gpt-oss-20b` (separate per-model limits) and only escalate plausible jobs to 120b. Changing prompts is a scorer change: AGENTS rule 7 gate applies, so this needs an owner decision (flag, do not just do it).
5. Put an explicit decision in front of the owner: a paid Groq plan raises limits (Groq lists the numbers above as the Developer-plan base; the free-plan numbers for the account are on the console limits page and were **not verifiable** here). At about 110-165 calls/day the dollar cost is small, but it is a recurring-cost and privacy decision (resume text goes to Groq on every call, CONCERNS "Personal data").

**Warning signs:** `Groq_429` > 0 in `Runs`; evaluated-to-seen lag growing; pending-evaluation count not returning to 0 between runs; rows/day plateau near 40-55 scorings; run duration inflating through `quota_retrying`-style waits (20/40/65 s) and 6 attempts per job; fallback model sticking for the 90 s hold repeatedly.

**Phase to address:** P1 (budget and instrumentation, owner decision GOV-01 and plan tier) before P2 (backfill). Re-check in P3 (more boards = more candidates).

---

### Pitfall 2: Backfill labels a job "recent" from a timestamp that is not its publication time

**What goes wrong:** Backfill's whole premise is "published <= 72 h ago, with a source publication time". The ATS fields are not equally trustworthy:
- **Greenhouse:** `updated_at` and `first_published` are different. Live probe (airbnb board, 2026-10-25): `updated_at` 2026-09-29, `first_published` 2026-04-13. `first_published` is present in the list response, but Greenhouse's docs only show it in the *Retrieve a Job* example with no field description. It is therefore undocumented in the list endpoint and could disappear or be absent for some jobs. Falling back to `updated_at` would be an AGENTS rule 2 violation.
- **Ashby:** docs say `publishedAt` is when the job was "most recently published". A republish moves it later, so an evergreen job republished weekly looks new every week (verified from official docs; effect on any one board not measured).
- **Lever:** `createdAt` is not described in the postings-API README (cannot confirm whether it changes on republish; live probe timed out).
- **Workable:** day precision only. **Workday:** relative text plus date-only `startDate` (Pitfall 4). **SmartRecruiters:** `releasedDate` (parked, D-38).
Evergreen/continuously reposted jobs (staffing firms, retail, "talent community" postings) produce a new ID and a new publication time with unchanged content, so they pass every freshness check and flood the tracker. This is the exact failure the volume principle makes more likely, because the rule becomes "recent is enough".

**Why it happens:** Treating "has a timestamp" as "has publication evidence". Backfill widens from "<= 12 h" (where reposts are rare) to "<= 72 h" (where a weekly repost cycle lands inside the window).

**How to avoid:**
1. Keep the SPEC vocabulary strictly: publication vs first observation vs update vs republication. Add a per-adapter table of "which field, precision, can it move" in SPEC and a test per adapter that **a missing publication field yields `unverified`, never a fallback to an update field**.
2. Repost detection must exist before the 72 h window opens. Use an explicit repost key that is *not* identity: company + normalized title + location + (Greenhouse `requisition_id` / `internal_job_id`, Workday `jobReqId`, which are in the payloads) within a lookback of 30-60 days of ledger history. Label ("possible repost; first seen DATE") rather than silently dropping, except where the same requisition ID is re-seen. Identity stays ATS + board + posting ID (rule 3); this key is a secondary label. Needs a DECISIONS entry (it touches D-05/SPEC "Republication").
3. The ledger already logs "publication time moved later for a known ID" as Republication and does not re-alert; extend that to the tracker so a republished known ID never gets a new row.
4. Spot-check each adapter's "published within 72 h" population against first-observation time on live data before enabling (a job whose publication is 60 h old on the first poll of an old board is plausible; a board where 40% of "recent" jobs have been seen under another ID is not).

**Warning signs:** the same company/title appears 2+ times in the tracker within a week; `Republication` events per board high; one board supplying a large share of the day's rows; publication-to-first-seen latency for backfill rows clustered at exact multiples of a day.

**Phase to address:** P2 (repost key and per-adapter timestamp contract) and P4 (every new adapter repeats the contract).

---

### Pitfall 3: A tracker row's age is true when written and false when read; the 72 h boundary is misapplied at day precision

**What goes wrong:** (a) The tracker is append-only and user-owned; an "Age: 5 h" text written at append time is wrong two hours later and the user cannot tell that it is stale. Showing age as a static string recreates the "unverified age presented as fresh" problem. (b) Day-precision sources (Workable, Workday) cannot prove a 72 h boundary: a date D may be anywhere from 0 to about 48 h older than a naive reading, plus timezone uncertainty. The existing rule for alerts (day precision only if within the last day AND board gap <= window) is deliberately strict; copying a looser rule to the tracker window silently includes 4-5-day-old jobs labelled "<= 72 h".

**Why it happens:** Reusing the freshness class names for a different window. A new window needs new classes, not a widened `verified_fresh`.

**How to avoid:**
1. Add a distinct class (for example `recent_72h`, with a precision suffix) that is **never alertable** and never reported as verified-fresh; `verified_fresh` stays <= 12 h time-precision (SPEC unchanged).
2. Write the *publication timestamp and precision* into the row (not just a derived age), plus a visible precision tag such as "date only". Let the Sheet compute "age now" with a formula column (the app stays append-only for existing cells; check this does not collide with D-44 header-by-name writes and D-46).
3. For day precision use the **earliest possible instant** for the date (start of the date, with a documented timezone assumption); include in the 72 h window only if the upper-bound age is <= 72 h + one stated grace, or label as "<= 4 d (date only)". State the choice in SPEC.
4. Dashboard and pilot report must count 72 h rows separately from 12 h rows (they share per-job definitions today, see STATUS "Dashboard and pilot report agree").

**Warning signs:** user reports "this is old"; rows whose precision is `day` dominate the window; age column differs between dashboard and tracker.

**Phase to address:** P2.

---

### Pitfall 4: Workday relative-date text and date-only `startDate` parsed as precise publication times

**What goes wrong:** Verified live (NVIDIA tenant, 2026-10-25): the list response gives `postedOn` as text such as "Posted 12 Days Ago" and "Posted 30+ Days Ago"; the detail response gives `startDate` as a date only (`2026-10-12`, while "12 days ago" computes to 10-13, so the two disagree by a day). There is no time of day. Pitfalls: (1) "30+" is a lower bound, not 30; (2) "Posted Today / Yesterday / N Days Ago" is computed server-side at request time in an unstated timezone, so parsing it later (after a retry, after midnight) shifts the date by a day; (3) singular/plural and localized variants ("1 Day Ago", other languages) break regexes and a failed parse must become `unverified`, not "today"; (4) `startDate` semantics are not documented by Workday and may be a requisition start date in some tenants (not verified; tenant-dependent); (5) list totals saturate (scrapers report 2,000 on large boards) and the list is 20 per page, so a big employer costs dozens of requests per poll.

**Why it happens:** Relative text is easy to parse into a number and a number looks like a timestamp.

**How to avoid:**
1. Parse relative text into a **range** anchored to the *observation time recorded at the response*, precision `day`, never `time`. "30+" maps to `old` (not eligible). Unknown text maps to `unverified`.
2. Send `Accept-Language: en-US`; log unparsed strings per tenant and fail loudly above a small rate.
3. Use `startDate` only after a per-tenant calibration against `postedOn` on live data, and only as `day` precision; never alert on Workday jobs from day precision unless the SPEC rule (date within the last day and board gap <= window) holds.
4. Paginate with a bounded request budget per board and stop when the list reaches "30+" only if the list order is verified newest-first for that tenant (not verified here); otherwise use `searchText` keywords drawn from the title gate to narrow results.
5. Golden-file tests from a recorded response, a clock-injection test (parse at 23:59 vs 00:01), and a test that "30+" never becomes recent.

**Warning signs:** Workday rows with age mismatches against the employer's own page; many identical "Posted Today" rows right after midnight UTC; parse-failure counter nonzero.

**Phase to address:** P4 (adapter + calibration); P2 supplies the day-precision rule.

---

### Pitfall 5: Events ledger and Sheet limits break at the planned scale (10M cells, whole-tab reads, partial baseline writes)

**What goes wrong:** Facts from the repo: Events about 150k rows, 93% baselines; D-43 measured about 146.6 baseline rows per admitted board; the full tab is read on every run and again by the dashboard and pilot report; the whole-workbook 10M-cell limit is for **all tabs together, and Google counts allocated grid cells, including empty ones** (third-party sources; the official limits page does not state a cell limit; the error text reports 10,000,000). Sheets API: **300 read and 300 write requests per minute per project, 60 per minute per user per project; payload recommended <= 2 MB; 180 s per request; 429 on overflow, backoff 2^n s + jitter up to 32-64 s; each batch counts as one request** (official, fetched today). The same page says charges for exceeding quota are planned for later in 2026, so watch for it.
Specific traps for v2.0:
- Baselines of 5-10k rows per run: the code chunks appends at 2,000 rows (`APPEND_CHUNK`); at the measured mean of about 486 chars a row that is about 1 MB per call, so within the 2 MB advice. If the Detail field grows (backfill adds scores, verdict text, publication evidence), chunks pass 2 MB and slow or time out. Size chunks by bytes, not rows.
- A run killed by the 25 min timeout between chunk 1 and chunk 3 leaves a board partially baselined. If the board is already marked baselined (verify the write order of `Boards` vs `Events`), the unwritten IDs look new next run: hydration and Groq are spent on old jobs. Alerts are still protected by the freshness gate, but the quota is not.
- Reading the whole Events tab (`get_all_values`) is one request but tens of MB of text (59.6M chars at 122k rows). Load time 7.5 -> 8.0 s now; it grows with rows and with memory on the runner. At 400k+ rows it is a risk to the timeout, not only to cells.
- 1,000+ boards adds replacement churn (admission = new baseline each time, re-entry = re-baseline D-24), so Events grows with *churn*, not just with board count.

**Why it happens:** The Sheet is an append-only database whose cost is dominated by rows that exist only for dedupe (96% of steady growth).

**How to avoid:**
1. **Do D-43 first** (P1): write the `Identity` (chunked IDs, 40k chars per cell, limit 50k) and `Daily` tabs in parallel, compare derived `seen` sets for several days, delete only with an exported copy. Note the new coupling: with backfill on, a lost identity set would not only re-observe baselines (flood) but re-evaluate everything <= 72 h. Keep the ledger copy until parity is proven.
2. Measure **allocated** cells per tab (grid rows x cols) in `--storage-report`, not only filled cells (the report counts about 7 per Events row, matching 7 columns, but Boards, Dashboard and Tracker grids count too).
3. Byte-sized chunking, one write ordering rule (Events identity written and verified before the board is marked baselined, or the board marked baselined only after the final chunk), and a test that kills the run between chunks.
4. Gate admission waves on measured Sheets reads/min and Events growth; keep `Sheets_Reads`, `Sheets_Writes`, `Sheets_429`, `Load_S` as P1 exit criteria.

**Warning signs:** `Sheets_429` > 0; `Load_S` > 15 s; Events rows crossing 200k (the D-03 review point; already near); the Sheets error "This action would increase the number of cells in the workbook above the limit of 10000000 cells" (the append is refused; the run fails).

**Phase to address:** P1 (before any increase in boards or backfill); P3 re-verifies at 1,000.

---

### Pitfall 6: GitHub Actions timeouts, dropped runs and schedule behaviour as run time grows

**What goes wrong:** Poller timeout 25 min (median 113 s, max 770 s at 500 boards), lease TTL 30 min, inventory job 40 min (1,121 s for 5,000 re-checks). More boards, Workday pagination (dozens of requests per board), backfill scoring (Groq waits of 20-65 s per 429) and bigger baselines all lengthen runs. Facts from official docs (fetched today): a concurrency group allows one running and **one pending run; a newer pending run replaces (drops) the older one**; a new `queue: max` option allows up to 100 pending runs in FIFO order (cannot combine with `cancel-in-progress: true`); scheduled workflows can be delayed or **dropped under high load, especially at the start of each hour**; in a **public** repository scheduled workflows are **disabled after 60 days without repository activity**. The repo is currently PUBLIC (checked with `gh repo view`), while `DEPLOY.md` says to keep it private; the hourly cadence already comes from an external trigger (GitHub's own schedule fired about every 4.4 h). Private repos get only 2,000 free minutes/month on a Free plan, public repos with standard runners are free; at 113 s x 720 runs plus daily inventory runs, a private repo would be close to the limit. Do not rely on that if the visibility is ever switched back.
Failure modes: a long inventory import makes one hourly poll replaced by the next (known, SPEC); a run killed by timeout leaves partial work; a backfill-heavy run that takes 24 min sits right at the timeout and then 2-3 hourly intervals are lost.

**Why it happens:** Time budgets were set for a 100 s workload. Per-phase budgets do not exist for evaluation, so one slow phase eats the rest.

**How to avoid:**
1. Per-phase wall-clock budgets inside the run (poll, hydrate, evaluate/backfill, write) with a hard stop at about 70% of the timeout; unfinished backfill stays pending (retryable), live-fresh evaluation is always run first.
2. Do not use `queue: max` for the poller: a queue of stale hourly polls adds no value and delays fresh ones. Consider it only for the inventory workflow if its drops matter.
3. Keep the external trigger on a different scheduler from the watchdog (still not set up, STATUS), and keep a commit/activity cadence or a heartbeat so the public-repo 60-day schedule disabling cannot silently stop the schedule path.
4. Track `Duration_S` against 60% of the timeout as a P1/P3 exit gate.

**Warning signs:** `Duration_S` p90 over 15 min; watchdog "stale" alerts; two consecutive hourly runs where the second never started; GitHub run list shows "canceled" pending runs.

**Phase to address:** P1 (budgets and gates), P3 (re-verify at 1,000 boards), P4 (Workday request volume).

---

### Pitfall 7: Workday/iCIMS access: anti-bot blocks, robots.txt per tenant, and terms of service

**What goes wrong:** Workday and iCIMS are enterprise sites with WAFs; Greenhouse/Lever/Ashby/Workable expose public JSON for third-party use. Observed (laptop, residential IP, 2026-10-25): Workday's unauthenticated `/wday/cxs/{tenant}/{site}/jobs` endpoint answered a POST with JSON; the per-tenant `robots.txt` of two sampled tenants (NVIDIA, Salesforce) allows the career-site path and disallows `/refreshFacet/` (and a few other paths), without disallowing `/wday/`. **Not verified:** behaviour from GitHub-hosted runner IPs (cloud IP ranges are frequently challenged or 403'd by WAFs; unknown here), per-tenant variation across thousands of tenants, and rate limits. Workday's site terms (workday.com) prohibit scraping and ignoring robots.txt; whether they cover customer `myworkdayjobs.com` career sites is unclear (not legal advice; no court outcome found). iCIMS has no documented public listing API; scrapers parse server-rendered HTML (`/jobs/search?ss=1&in_iframe=1`) or a per-tenant JSON endpoint, with portal layouts differing (10 vs 50 jobs/page, posting date in different places). A nonexistent iCIMS host returns a "gone" HTML page with a 4xx/5xx-ish body, so "exists" detection needs care. iCIMS `robots.txt` was not retrievable on a live tenant here; `datePosted` JSON-LD availability is unconfirmed.
Repeating D-38 (polling against `Disallow: /`) would normalize ignoring robots.txt for large corporations with legal departments.

**How to avoid:**
1. Make robots compliance a hard per-board gate: fetch each tenant's `robots.txt`, evaluate the exact request path for the exact user agent, cache it, and park the board (as SmartRecruiters is parked) on `Disallow`. No automatic override; any override stays an explicit owner decision recorded in DECISIONS (revisit D-38 in P1 as GOV-01 already says).
2. Use an identifying User-Agent, a per-host rate limit (start at 1 request/s per host, one host-family at a time), backoff on 403/429, and a **circuit breaker**: three consecutive 403/challenge responses disable that adapter for the run and write a failure event (not a permanent "invalid board"; AGENTS rule 4).
3. **Feasibility spike before building**: run 20-50 tenants from an Actions run (not a laptop) and record status codes, latency and challenge pages. Only then commit to P4 scope. Build Workday first; treat iCIMS as conditional (HTML parsing, no documented API, date field unverified).
4. Keep polling load proportional: Workday boards are polled with narrowed `searchText` and bounded pages, not full crawls.
5. Owner reads Workday/iCIMS terms and decides risk; record it (like D-38).

**Warning signs:** 403/429 or HTML "challenge" bodies instead of JSON; `ATS_429` rising; Workday boards flipping between valid/invalid (a challenge page must never mark a board `invalid`).

**Phase to address:** P4 (spike first; may shrink scope), P1 (D-38 reconfirmation).

---

### Pitfall 8: Feedback-driven board cycling is a rich-get-richer loop that starves new boards (and churn multiplies storage cost)

**What goes wrong:** Boards are ranked from "recent relevant posting activity" and `My_Feedback`. Problems:
- **Selection bias:** feedback exists only on jobs already shown; boards that were never shown have no label, so they can never earn one.
- **Small samples:** feedback labels per board are few (tens of rows/day over hundreds of boards); a raw rate on n=2 is noise. Large employers post more, so volume-based activity favours them regardless of fit.
- **Evergreen amplification:** a board that reposts constantly looks "active" (Pitfall 2).
- **Starvation and churn:** faster cycling shortens trials (D-30 7-day trials, floor 2.0 per D-45) and each admission costs a baseline (Pitfall 5), a re-entry baseline and the loss of its activity history. D-47 already released 220 trials on thin evidence before the first weekly cycle (2026-10-29) produced any evidence.
- **Moving target:** the cycle scores are tuned while the first weekly report (D-30's proof) has not been read; you cannot attribute a change in rows/day to cycling vs the Settings broadening of 2026-10-23.
- **Scope bleed:** the rule 7 exemption is for board-cycling scores only; using feedback to alter the Groq score or `Min_Alert_Score` is not allowed.

**How to avoid:**
1. Read the first real `rebalance_report` (about 2026-10-29) and the 2 weeks after before changing cycling (the gate AGENTS rule 7 is built for this).
2. Shrink estimates toward a prior (Bayesian/Wilson lower bound) and require a minimum number of observed relevant jobs and labelled rows before a feedback term can demote a board; no demotion on feedback alone for the first N days.
3. Count **unique first-seen requisitions**, not postings or reposts, and normalize activity per open job and per day-observed.
4. Reserve a protected exploration share that cycling cannot touch (D-30 has 20%; keep it a floor in code and a test), plus a small random sample of admissions so the system can measure counterfactuals.
5. Hysteresis and minimum dwell time: a board that was admitted cannot be demoted within X days; cap replacements per cycle (already bounded); count churn (admissions/day, baseline rows/day) as a metric with a ceiling.
6. Store scorer version and cycle-score version separately; keep the board-cycling score fields out of the Groq prompt and out of `Min_Alert_Score` logic.

**Warning signs:** top-20 boards hold a growing share of rows; the share of rows from boards admitted in the last 14 days falls; churn/day rises with no rise in rows/day; `My_Feedback` positive rate flat while volume grows; an operating choice nobody can attribute.

**Phase to address:** P3 (after P6 baseline is collected and the first weekly cycle is read).

---

### Pitfall 9: Wider web search cannot cover a 72 h window with the free Tavily budget

**What goes wrong:** Tavily free plan: 1,000 credits/month (basic search 1 credit, advanced 2, extract 1 per 5 successful URLs; pay-as-you-go $0.008/credit) (official docs, fetched today; the page does not document free-plan exhaustion behaviour, the project already handles 432/433). The project allows 800 scheduled credits/month, 10 per run, about 20/day, one request per slot, <= 20 results per request, no pagination. Rotation = slots / (credits per day). 42 slots = about 2.1 days; "6 sites x 36 roles" = 216 slots = about **10.8 days per pass** at 20 credits/day. A slot visited every 10 days with a 3-day `start_date` window sees at most 30% of that slot's postings. Wider roles would therefore reduce coverage per slot while consuming the same credits. Also: search-found jobs had median 455 min detection latency (n=8), search snippet dates and search-engine dates are not publication evidence (AGENTS rule 2); jobs found through search must be hydrated from the ATS to get a source publication time, which costs ATS requests and Groq tokens.
The account counter lagged (still 0 after about 55 credits), so local accounting can undercount; 432/433 blocks all spending until month rollover.

**How to avoid:**
1. Do the arithmetic as a gate: `slots x (days between passes) <= window` or accept partial coverage explicitly; with 800 credits/month (about 26/day) and a 3-day window the full rotation must be <= about 78 slots.
2. Use search mainly to **discover boards** (feeds the registry via the one admission path; a board then gets hourly polls) rather than to fetch individual jobs, and prioritize slots by historical yield (log yield per slot; most slots return 0 in the window).
3. Keep the reserve (200 credits) and the stop threshold; add a hard daily cap so a wide rotation cannot spend the month in 10 days; keep the credit ledger as authority and reconcile with `GET /usage` daily.
4. Make the owner decision explicit about paying for credits (about $8 per extra 1,000 credits at the documented rate) rather than silently exhausting the free tier.

**Warning signs:** `Result_*` counters flat; credits at the stop threshold before mid-month; a long tail of slots with 0 results; search-found latency far above poll-found latency.

**Phase to address:** P5 (slots/credit arithmetic as an acceptance test); P1 for accounting.

---

### Pitfall 10: Cross-ATS and cross-board duplicates, and tracker duplicate protection by URL

**What goes wrong:** Identity is ATS + board + posting ID, which is right for state but leaves the *same job* appearing as several identities: the same employer on two ATSs during a migration (Greenhouse board still live next to a new Workday site), two boards for one company (regional or brand boards), a search hit and a board hit, an aggregator or a reposted ID. The tracker's duplicate protection (`tracked_keys`) is keyed on `Apply_URL`; AGENTS rule 3 says never dedupe on URL strings. New adapters make this worse: Workday/iCIMS URLs carry locale, session, `source=` or tracking parameters and different hosts per site (URL differs, job the same; or URL same, job different via a query parameter). Over-merging is also real: two different "Marketing Associate" roles in different cities are different jobs.

**How to avoid:**
1. Add an identity-based key column (`Job_Key`: ATS|board|posting ID) in the tracker (hidden or visible) and make `tracked_keys` use it; keep `Apply_URL` for the user. This is a behaviour change to SPEC "Job Tracker" (AGENTS rule 1: update docs in the same change; D-44/D-46 header-by-name rules apply).
2. Secondary cross-source grouping on normalized company + title + location (+ requisition ID where present) over 30-60 days, applied as a **label** ("also posted on X") and not a delete, until the false-merge rate is measured. Company normalization needs a board-to-company map in the registry.
3. Test: same job through two ATSs yields one tracker row with both sources noted; two jobs with the same title in different cities yield two rows.

**Warning signs:** identical titles/companies in consecutive tracker rows with different hosts; the user marking duplicates in `User_Notes`; `Apply_URL` differing only by query parameters.

**Phase to address:** P2 (key column + label; done before P4), P4 (adapter URL normalization tests).

---

### Pitfall 11: Backfill state handling breaks "seen / evaluated / alerted" (re-entry, retries, replays)

**What goes wrong:** Backfill makes the ledger do something it did not do before: evaluate jobs that were previously only identity rows. Failure modes: (a) a re-entering board (D-24) re-baselines and the backfill re-evaluates jobs already evaluated before demotion; (b) a transient Groq failure turns a backfill job into an `abandoned` record after 5 attempts (D-07), permanently losing a job that is only 40 h old; (c) the existing known bug where non-HTTP alert exceptions never reach the 5-attempt bound (CONCERNS #2) or an alert marked `alerted` with `channel: none` (CONCERNS #1) would now repeat at 5-10x the volume; (d) one-time catch-up of jobs already baselined on existing boards (700 boards, jobs <= 72 h that were baselined) can create a day-one wave; (e) measurement contamination: backfill rows have publication-to-detection latency of 20-70 h, which would wreck the headline "median 29 min" if mixed into the same population.

**How to avoid:**
1. Backfill eligibility keys off the ledger's `seen`/`evaluated` state, never "first read of a board"; add a test for re-entry and replay.
2. A distinct disposition/source value (`backfill`) so reports, dashboard and pilot report can split latency populations from day one (P6 starts in P1/P2).
3. Backfill failures stay retryable until the job ages out of 72 h, then record an explicit `aged_out` disposition (not `abandoned`).
4. Fix CONCERNS #1 and #2 first (small, high priority) so more volume does not multiply them.
5. Decide explicitly whether to catch up existing baselines (default: only boards admitted after deploy plus a bounded, owner-approved one-off), with a per-run cap.

**Warning signs:** pending evaluation count spikes after an admission wave; tracker rows appear for jobs on boards admitted weeks ago; headline latency changes after deploy without a poll change.

**Phase to address:** P2 (with the two CONCERNS fixes done in P1).

---

## Moderate Pitfalls

### Pitfall 12: Google Sheets quota arithmetic is fine until the dashboard, pilot report and tracker duplicate reads add up
**What goes wrong:** Reads peak at 12.4/min against 60/user/min today; a poll that does more per-board writes, tracker reads for duplicate protection (every cell is read) and a dashboard refresh after every run can combine in the same minute with an inventory run (same service account = same user quota). **Prevention:** count requests per phase in `Runs`, share one read of Events per run (cache), batch dashboard writes (already one batch), serialize heavy readers. **Phase:** P1/P3.

### Pitfall 13: Per-provider rate limits scale linearly with boards
**What goes wrong:** Lever has `Crawl-delay: 1` (live robots.txt) so each Lever board costs at least 1 s; Workable returned 429 earlier; Ashby's `robots.txt` answers 401; Greenhouse disallows only `/embed/`. At 1,000 boards a provider's share can exceed the run budget. **Prevention:** per-provider time budgets in the poll loop, interleave providers, keep 429 backoff stopping only that provider (exists, mocked), record `ATS_Seconds` by provider. **Phase:** P3.

### Pitfall 14: Title gate and Settings broadening versus volume expectations
**What goes wrong:** "Community Associate" (front desk) and similar leaks pass the broadened Settings; more volume under "volume over precision" means more noise at the tracker, and recent-job noise cannot be filtered by date. **Prevention:** keep hard-rule exclusions as a Settings-level change; rely on My_Feedback to find leaks; do not touch the scorer (rule 7). **Phase:** P6 (evaluate), P2 (Settings only).

### Pitfall 15: Re-check backlog makes waiting boards stale
**What goes wrong:** 21,000 validated boards, 5,000 re-checks/run budget, a board's relevance is a snapshot; scaling boards by admitting the "waiting list" uses stale evidence. **Prevention:** use re-check flip rates (`revalidation_stats`) to prioritize re-checks for boards with fresh activity; do not raise `Max_Active_Boards` until flip rates are read. **Phase:** P3.

### Pitfall 16: Public repository drift
**What goes wrong:** The repo is PUBLIC while DEPLOY.md says private-then-public only after a history rewrite. Workflow logs for a wider scrape (titles, companies, errors) and the public schedule are visible; Actions minutes are free in public repos but the activity-based schedule disabling applies (Pitfall 6). **Prevention:** owner confirms visibility; keep logs free of job content and personal data; no secrets in logs. **Phase:** P1 (GOV-01).

---

## Minor Pitfalls

### Pitfall 17: Telegram message truncated mid-HTML tag
`"\n".join(lines)[:4096]` can cut a tag and produce a 400 "can't parse entities" (CONCERNS #3). Backfill alerts are rare (alerts unchanged), so low priority, but longer verdicts from new adapters raise odds. Cap each field before escaping. **Phase:** P1.

### Pitfall 18: Tracker grid growth
Tracker `add_worksheet(rows=1000)`; at 30 rows/day it passes 1,000 rows in about a month (append auto-expands rows; fine) but the whole-tab duplicate read grows. **Prevention:** read only the key column(s) by name. **Phase:** P2.

### Pitfall 19: Doc drift at behaviour change
D-05, SPEC "Baselining", "Freshness vocabulary", "Job Tracker" and "Honest limits" all change. AGENTS rule 1 requires updating them in the same change; stale SPEC text (as with SmartRecruiters at SPEC ~L41) misleads the next agent. **Phase:** every phase.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Fall back to `updated_at` when `first_published` is missing | More jobs "dated" | Violates AGENTS rule 2; reposts and edits look new | Never |
| Parse "Posted N Days Ago" as an exact date/time | Quick Workday adapter | Day-off errors, false "fresh" | Never; use day-precision range |
| Widen `verified_fresh` to 72 h | No new class | Alerts of old jobs; core value broken | Never |
| Add rows to Events for backfill without D-43 | Skip a migration | 10M-cell/replay-time wall within weeks | Only for a short, capped test |
| Dedupe on `Apply_URL` for new ATSs | Reuses existing guard | Rule 3 violation; wrong merges and duplicates | Never for the new ATSs |
| Tune board scores with raw feedback rates | Quick personalisation | Noise, starvation, unattributable results | Only after shrinkage and a protected exploration floor |
| Override robots.txt for big employers | More coverage | Legal and reputational exposure; sets precedent after D-38 | Only as an explicit owner decision per provider |
| Grow `hunter.py` further for adapters | Fast | 1,981 lines; hard to test | Put new adapters in their own module |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Groq | Counting only requests, not tokens; resume and JD at 7k chars each; ignoring cached-token rules | Track tokens from `x-ratelimit-*`; stable prefix first; cap backfill share; separate per-model budgets |
| Google Sheets | Counting filled cells instead of allocated grid; chunking by rows | Measure grid size per tab; chunk by bytes (<= 2 MB); 429 backoff with jitter |
| GitHub Actions | Assuming `queue: max` helps hourly polls; assuming the schedule is reliable | Keep single pending slot for the poller; external trigger + watchdog; heartbeat for public repo inactivity |
| Greenhouse | Using `updated_at`; assuming `first_published` is documented in the list response | `first_published` only; absent means `unverified`; contract test |
| Ashby | Treating `publishedAt` as first publication | Documented as "most recently published"; use with repost key |
| Workday | Parsing `postedOn` text as a timestamp; one request per board; trusting `total` | Range with day precision; bounded pagination; `searchText`; per-tenant robots check |
| iCIMS | Assuming a JSON API exists | Spike first; HTML parsing; layouts differ; verify date field |
| Tavily | More slots at the same credit budget | Slots x revisit interval <= window; use for board discovery |
| Telegram | Truncating built HTML | Cap fields pre-escape |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Whole-Events replay per run | `Load_S` rising; memory | D-43 Identity set | About 300-400k rows or when `Load_S` > 15 s |
| Baseline wave of 50 boards/run x 147 rows | Run duration, write time | Byte-chunking, ordering rule, admission cap by headroom | When a 5-10k row write plus polling approaches 60% of timeout |
| Groq daily tokens | 429s, growing pending queue | Priority queue, budget, plan tier | About 40-55 scorings/day on the documented 200K TPD |
| Workday pagination | `ATS_Seconds` per board high | Narrow searches, page cap | Boards with >200 open jobs |
| Per-provider crawl delay | Lever time per run | Interleave, per-provider budgets | About 400+ Lever boards at 1 s |
| Dashboard and pilot report whole-tab reads after each run | Quota spikes with the inventory run | Reuse the loaded events | 1,000 boards and 300k+ rows |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Scraping against robots.txt/terms for new ATSs | Legal and reputational (D-38 precedent) | Per-tenant robots gate, owner-recorded decisions |
| Logging job text or resume in public Actions logs | Personal data and job data exposed (repo is public) | Log counts and IDs only; scrub error bodies |
| Sending more resume text to Groq at higher volume | Larger privacy surface (no recorded decision, CONCERNS) | Record the Groq data-handling decision (GOV-01) |
| Challenge/WAF pages stored as board "invalid" | Silent permanent loss of boards | Circuit breaker; transient classification |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Static age text in tracker | Old rows read as fresh | Publication timestamp + live formula age; precision tag |
| 72 h rows mixed with 12 h alerts | Trust in "fresh" erodes | Separate class/column; alerts unchanged |
| Volume without grouping | Duplicate-looking rows | "Also on" label, repost label |
| Evergreen reposts | Time wasted | Repost label with first-seen date |

## "Looks Done But Isn't" Checklist

- [ ] **Backfill:** often missing the replay/re-entry guard; verify a board re-entering does not re-score evaluated jobs.
- [ ] **72 h tracker:** often missing precision handling; verify a day-precision job 4 days old is not labelled <= 72 h.
- [ ] **Groq budget:** often missing a priority queue; verify live-fresh jobs are scored before backfill when budget is short (test with a fake 429 stream).
- [ ] **Storage migration:** often missing parity proof; verify derived `seen` sets match for several days before any delete, and that the export exists.
- [ ] **Workday adapter:** often missing the Actions-IP check; verify against a real Actions run, not only a laptop.
- [ ] **Repost handling:** often missing a lookback; verify a reposted ID with unchanged content is labelled, not scored as new.
- [ ] **Board cycling:** often missing an exploration floor test; verify a new board cannot be demoted within its minimum dwell time.
- [ ] **Search:** often missing the coverage arithmetic; verify rotation days <= window.
- [ ] **Measurement:** often missing the split of backfill from live latency; verify the headline median excludes backfill.
- [ ] **Docs:** SPEC, DECISIONS, STATUS updated in the same change (AGENTS rule 1) with live vs mocked labelled (rule 5).

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Groq quota exhausted | LOW | Pause backfill (setting), pending jobs stay retryable; pick up after reset or plan change |
| Partial baseline after timeout | MEDIUM | Detect boards with Boards.baselined but missing identity rows; re-baseline without scoring |
| Lost identity set after migration | HIGH | Restore from the kept ledger copy/export; otherwise flood of re-observations and re-evaluation |
| Wrong "recent" rows in tracker | LOW | Rows are append-only; mark with `User_Notes`/cleanup list; fix classifier; add regression test |
| Events at 10M cells | HIGH | Archive terminal rows to a new spreadsheet; stop admissions; finish D-43 |
| WAF blocks Actions IPs | MEDIUM | Disable adapter, mark boards `deferred` (not invalid), revisit scope |
| Feedback loop starved new boards | MEDIUM | Raise exploration floor, restore minimum dwell, recompute from ledger |
| Tavily credits exhausted | LOW | Skip discovery until rollover (existing behaviour); consider paid credits |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| 1 Groq daily token cap, backfill starvation | P1 (budget), P2 (queue) | Tokens/day recorded; live-fresh priority test; no pending growth over 7 days |
| 2 Timestamp semantics, reposts | P2, P4 | Per-adapter contract tests; repost label on live sample |
| 3 Static age, day precision | P2 | Tracker rows carry timestamp + precision; boundary tests |
| 4 Workday relative dates | P4 | Golden files; clock-injection; "30+" test |
| 5 Sheet limits, partial baselines | P1 (then P3) | Allocated-cell report; kill-between-chunks test; `Load_S` < threshold |
| 6 Actions timeouts/drops | P1, P3 | `Duration_S` p90 < 60% of timeout; no dropped hourly intervals |
| 7 Workday/iCIMS access | P4 (spike first) | Actions-run probe; robots gate; breaker test |
| 8 Feedback loop | P3 (after P6 baseline) | Shrinkage test; exploration floor; share of new-board rows |
| 9 Tavily coverage | P5 | Rotation days <= window or explicit partial-coverage statement |
| 10 Dedupe, URL tracker key | P2, P4 | Job_Key column; same-job-two-ATS test |
| 11 Backfill state handling | P2 (after CONCERNS #1/#2 fixes in P1) | Re-entry/replay tests; `aged_out` disposition |
| 12-16 Moderate | P1/P3 | Per-run request counts; per-provider budgets; visibility decision |
| 17-19 Minor | P1/P2 | Unit tests; doc diff in each change |

## Sources

Official / HIGH confidence (fetched 2026-10-25):
- Groq rate limits (per organization; first limit wins; cached tokens do not count; base table 30 RPM / 1K RPD / 8K TPM / 200K TPD for gpt-oss-120b/20b): https://console.groq.com/docs/rate-limits
- Groq prompt caching (gpt-oss-120b/20b supported; exact prefix; 2 h TTL; 50% discount; cached tokens not counted against limits): https://console.groq.com/docs/prompt-caching
- Google Sheets API limits (300/min per project, 60/min per user, 2 MB recommended payload, 180 s timeout, backoff, quota charges planned later in 2026): https://developers.google.com/workspace/sheets/api/limits
- GitHub concurrency (one running + one pending, newest replaces older pending; `queue: max` up to 100): https://docs.github.com/en/actions/using-jobs/using-concurrency
- GitHub scheduled events (delays and drops at high load, 60-day inactivity disable in public repos): https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- GitHub Actions billing (2,000 free minutes private Free plan; free for public repos on standard runners): https://docs.github.com/en/billing/managing-billing-for-your-products/managing-billing-for-github-actions/about-billing-for-github-actions
- Tavily credits (1,000 free/month; basic 1, advanced 2; extract per 5 URLs; PAYG $0.008): https://docs.tavily.com/documentation/api-credits
- Greenhouse Job Board API (`first_published` only in the Retrieve-a-Job example, no field descriptions): https://docs.greenhouse.io/job-board.html
- Ashby posting API (`publishedAt` = most recently published; `isListed`): https://developers.ashbyhq.com/docs/public-job-posting-api
- Lever postings API (no date field documented; `skip`/`limit`): https://github.com/lever/postings-api

Live probes by this researcher (HIGH for the observation itself, one sample each, 2026-10-25, run from a laptop, not from GitHub Actions):
- Greenhouse airbnb list: `first_published` 2026-04-13 vs `updated_at` 2026-09-29 (both present in list response).
- Workday NVIDIA tenant: list `postedOn` = "Posted 12 Days Ago"/"Posted 30+ Days Ago"; detail `startDate` = `2026-10-12` (date only); total 792 jobs; robots.txt of NVIDIA and Salesforce tenants allow career-site paths and disallow `/refreshFacet/`.
- robots.txt: `api.lever.co` Crawl-delay 1; `boards-api.greenhouse.io` Disallow `/embed/`; `apply.workable.com` Disallow empty; `api.ashbyhq.com` returns 401.

Third-party / MEDIUM-LOW (cited for context, not authoritative):
- Google Sheets 10M cells across all tabs, empty cells counted: https://workspaceupdates.googleblog.com/2022/03/ten-million-cells-google-sheets.html (10M announcement, HIGH); allocated-grid claim from https://fast.io/resources/google-sheets-row-limit.md and https://www.sheetgo.com/blog/spreadsheets-tips/google-sheets-cell-limit (MEDIUM; the same sources mention an unverified 20M figure).
- Workday CXS behaviour (2,000 total saturation, detail call for exact date): Apify scraper pages, for example https://apify.com/crawlerbros/workday-jobs-scraper (LOW).
- iCIMS scraping approaches and layout variants: https://apify.com/hirebase/icims-jobs.md, https://apify.com/usestring/icims-jobs.md (LOW).
- Workday site terms (scraping and robots.txt bypass prohibited; scope for career sites unclear): https://workday.com/en-us/legal/site-terms.html (HIGH for the text, unknown for applicability).
- Groq free-plan figures: the account's own limits page governs; third-party tables (for example https://benchlm.ai/free-tier/groq) agree with the Developer-plan base numbers but call them samples (MEDIUM).

Project sources: `.planning/PROJECT.md`, `.planning/codebase/CONCERNS.md`, `STATUS.md`, `DECISIONS.md` (D-05, D-16, D-24, D-30, D-38, D-43, D-44, D-45, D-46, D-47), `SPEC.md` (Freshness vocabulary, Discovery budget), `hunter.py` (`RESUME_CHARS`, `JD_CHARS`, `MAX_OUTPUT_TOKENS`, `GROQ_ATTEMPTS`), `state.py` (`APPEND_CHUNK` = 2,000), `.github/workflows/*.yml`.

---
*Pitfalls research for: Search-substitute volume (v2.0) on an ATS-polling job alert system*
*Researched: 2026-10-25*
