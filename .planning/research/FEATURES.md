# Feature Research

**Domain:** Job-alert / job-aggregation system for one entry-level marketing, content and design seeker (v2.0 "Search-substitute volume")
**Researched:** 2026-10-25
**Confidence:** MEDIUM on feature categories and mechanisms; LOW on every volume and ATS-share number (estimates, basis shown)

Scope: only the NEW v2.0 features (recent backfill, 72 h tracker window with age labels, boards past 700, faster/feedback-informed cycling, new ATS adapters, wider search, measurement). Existing v1.0 behaviour is the baseline and is not re-researched. Everything below respects SPEC.md and AGENTS.md rules 1-8. Where a feature conflicts with them it is flagged as **CONFLICT / DECISION**.

---

## 1. How aggregators and alert systems get high recall of recent postings

Practice, reduced to what applies here (sources at the end; confidence in brackets):

| Technique used by aggregators | What it buys | Already in this system? |
|---|---|---|
| **Direct source ingestion first** (ATS APIs, employer XML feeds, sitemaps, JSON-LD `JobPosting` on employer pages), crawling/search only to find sources | Authoritative dates, low latency, no scraping of third-party boards. Google's own job index is built on employer-supplied `JobPosting` markup with `datePosted`/`validThrough` [MEDIUM, Google docs] | Yes for 5 ATSs (poll). Search = candidate retrieval only (D-17..D-21) |
| **Wide source discovery** (company lists, search, public inventories) feeding a **source registry** | Recall is bounded by how many sources you know and can poll | Yes: 21,880 validated-or-candidate boards, 2 inventories, Tavily rotation |
| **Per-source change-rate estimation and priority recrawl** (Cho and Garcia-Molina style optimal freshness; Google K-armed adversarial bandit over recrawl strategies beats LambdaCrawl, most under tight budgets; estimate quality of change rate dominates the gain) [MEDIUM] | More fresh finds per fetch when fetches are scarce | Partly: pool score = 2 x min(new relevant/wk,5) + min(open eligible,5), 20% exploration trials, weekly rebalance |
| **Cross-source dedupe on normalised title + company + location over a window** (Lightcast: 60 days; "up to 80%" of collected postings are duplicates, vendor claim) [LOW-MEDIUM] | A pile of N rows is N distinct jobs, not N/3 | Identity ATS+board+ID only (D rule 3). No cross-source or repost logic |
| **Repost / ghost handling**: LinkedIn shows "Reposted" and resets the displayed date; vendors flag "same normalised title + city under a new ID" as the strongest ghost signal [LOW, third-party/anecdotal] | Stops old roles posing as new | Not built |
| **Age shown on every listing** ("2 hours ago"), plus "newest first" and early-applicant framing (LinkedIn claims first-25 applicants are "up to 3x" more likely to be hired, company claim, unverified study) [LOW] | Users triage by age; early matters | `Freshness` column only; no age |

Key implication: the system is already architected like a direct-ingestion aggregator. Recall is limited by (1) boards monitored (cap 700, ~53% of known relevant boards), (2) ATS coverage (5 providers), (3) filters (title gate, location, experience), and (4) the 12 h window discarding everything at admission. v2.0's levers map one-to-one to those four.

---

## 2. Realistic volume (ESTIMATES; basis shown; do not present as measured)

### 2a. Bottom-up from the pilot (LIVE data, STATUS.md; the strongest basis)

Pilot week 1, 500 boards (all trials), 33% of ~1,350 known relevant boards monitored:

| Stage | 7-day count | Per day |
|---|---|---|
| New postings seen (mostly baselines) | 19,380 | n/a |
| Passed title gate ("relevant") | 472 | ~67 |
| Rejected after reading (location 131, experience 71, language 10) | 212 | ~30 |
| Scored by Groq | 260 | ~37 |
| Kept (score >= 50, tracker) | 47 | ~6.7 |
| Alerted | 20 | ~2.9 |

Yields: title-pass to kept = 10%; scored to kept = 18%; location+experience hard rules remove 43% of title-passers (the largest single loss).

Projection to the 25 rows/day target (ESTIMATE, arithmetic only):
- Known relevant boards today about 1,390 (679 monitored + 710 waiting). Monitoring all of them versus the pilot's 500 is x2.8 in boards; waiting boards are ranked lower (open eligible jobs first), so effective gain is about x2.0-2.5 => about 13-17 kept/day at the pilot's title gate.
- Widened Settings (2026-10-23) multiplier is unmeasured: assume x1.2-2.0 => about 16-34 kept/day. **Target 20-30 is reachable only with roughly all known relevant boards monitored (cap well above 700, about 1,400+) plus the wider Settings.** At 700 boards alone the same arithmetic gives about 9-14/day.
- Backfill (72 h on admission) adds a one-time pile, not a rate: 700 boards x 3 days x 0.05-0.13 relevant/board/day = 100-270 title-passers x 10% kept = about 10-27 rows in total (roughly one day's target) spread across the fill, plus the same 3 days for every board that re-enters monitoring through rebalance. Treat it as a ramp and a floor on re-entry, not the steady-state engine.
- The 72 h window itself adds little on already-polled boards: they are detected within about 30 min (median 29 min) and are already `verified_fresh`. It matters for baseline/re-entry passes, search-found jobs (median detection 455 min) and day-precision dates (Workable).

### 2b. Top-down market ceiling (LOW confidence, Fermi estimate)

| Step | Figure | Basis |
|---|---|---|
| US annual openings in the four closest BLS occupations (2025-35 average) | about 133,000/yr = about 364/day | BLS OOH: market research analysts and marketing specialists 82,000; graphic designers 16,000; PR specialists 23,000; writers and authors 11,900 [HIGH for the BLS numbers; they are separations plus growth, a proxy for hires] |
| Add editors, technical writers, art directors, web/digital designers, producers, social/community roles | +20-40% | Not retrieved; assumption => about 440-510/day all levels |
| Entry-level / 0-2 year requirement share | 25-40% | Assumption. Only an explicit "entry level" label is measurable: 11.6% of marketing postings on one index (JobsPipe, 2026-09-09, 10 boards, unlabelled postings stay in the denominator), so 11.6% is a floor, not the share |
| Distinct postings per hire after dedupe | about 1.0-1.5 | Assumption (reposts, multi-location, ghost jobs) |
| Geography: TX + NY + US remote/hybrid | 30-40% of US | Assumption |
| => Distinct relevant postings per day, all channels | **about 35-100/day** | product of the above |
| On the 5 supported ATSs | 35-55% of those | see 3 below (LOW) |
| => reachable today (all 5 ATSs, all boards) | **about 12-55/day, midpoint about 25** | |
| With 53% of relevant boards monitored | about 7-30/day, midpoint about 13 | |
| Adding Workday/iCIMS/Oracle-class big-employer sites | ceiling about 20-80/day | +20-30% of postings |

Reading: 20-30 verified-recent rows/day is plausible but sits in the **upper half of what five ATSs can supply even at full coverage**; adding big-employer adapters and wider search raises the ceiling and is what makes the target robust. A product that returns 40+ is probably including senior or off-target rows. Calibrate with the measurement feature (below) before promising a number.

### 2c. Context only
JOLTS (secondary sources, LOW): about 7.1M US job openings and 5.2M hires in August 2026. Not used in the estimates.

---

## 3. ATS split: supported five vs big-employer / SMB systems (LOW; no posting-weighted public source exists)

| Evidence | Greenhouse / Lever / Ashby / Workable / SmartRecruiters | Workday / iCIMS / Oracle / others | Notes |
|---|---|---|---|
| ResumeGeni, 2026-10-25, 2,605 "top-rated" employers, count of employers by detected careers flow | 49.2 / 8.9 / 8.3 / 0.3 / 0.5 => **67.2%** | Workday 22.9, Oracle HCM 3.2, Phenom 2.4, SuccessFactors 0.6, iCIMS 0.2, other 3-4 | Tech-skewed curated sample; counts employers, not postings; not US-only |
| Ongig, older, ~1,063 enterprise employers by installs | GH 7.8, Lever 2.9 (others not shown) | Workday 21.9, Taleo 14.7, SuccessFactors 11.6, iCIMS 8.9 | Enterprise-skewed, undated, installs |
| This project's inventories (boards, not postings) | 21,880 supported boards (GH 7,709; Workable 4,752; Ashby 4,041; SR 2,747; Lever 2,631) | Unsupported rows: Join 23,547, BambooHR 5,632, Paycom 5,135, Workday 3,530, JazzHR 2,689, iCIMS 2,498, Personio 2,463, Rippling 1,923, Breezy 3,536, Teamtailor 2,840, Recruitee 2,830 | Supported = 24% of the ats-scrapers rows, 58% of open-ats-feed rows; inventories are biased to what those scrapers cover |

Working assumption for entry-level marketing/content/design in TX/NY/remote (ESTIMATE, LOW): **35-55% on the supported five** (startups and mid-size marketing orgs cluster on Greenhouse/Lever/Ashby), **20-30% on Workday/iCIMS/Oracle/Taleo/SuccessFactors-class** (large employers hire many entry-level marketers per employer but each tenant is one board), **15-25% on SMB systems** (BambooHR, Paycom, Paylocity, JazzHR, UKG, ADP, Rippling), **5-15% company-hosted/custom or LinkedIn-only.** Board counts understate Workday: few boards, many postings each. Verify with a one-off measurement (see Measurement) rather than trusting this split.

---

## Feature Landscape

### Table Stakes (a "substitute for manual search" is not credible without these)

| Feature | Why expected | Complexity | Notes / dependency on existing system |
|---|---|---|---|
| **Visible posting age on every tracker row**, with precision honesty ("time" vs "date only" vs "unknown") | LinkedIn/Indeed show "Posted 3h ago"; skimming a pile depends on it | LOW-MED | Store `Published` (ISO) + `Precision` + `Source` per row; show age through a Sheet formula (`NOW()-Published`) so it never goes stale in an append-only tab. New headers must be added (D-44/D-46 header-name writes make this safe; the app must create the header once like `My_Feedback`). Never show an age for `uncertain`/`baseline`-without-date rows (rule 2) |
| **72-hour tracker window for relevant jobs** | The user's explicit target; manual search filters "past 3 days" | LOW | Mostly configuration: SPEC already has class `recent` (dated, older than 12 h, within `Max_Job_Age_Days`, tracker only, no alert). So 72 h is `Max_Job_Age_Days=3` for the tracker plus the backfill exception below. Alerts unchanged (12 h, `verified_fresh`) |
| **Recent backfill on board admission and re-entry** (time-precise publication <= 72 h evaluated, class `recent`, tracker only, labelled with real age) | Without it every newly admitted board contributes nothing for its first jobs; rotation re-baselines boards repeatedly | MED | **CONFLICT / DECISION:** changes D-05 and SPEC "Baselining"/"Re-entry" (baseline exception today = inside 12 h). Update SPEC, DECISIONS, STATUS in the same change (rule 1). Day-precision (Workable): the posting date D cannot prove <= 72 h exactly; accept only when D is within the last 2 calendar days and label "date only". Undated jobs stay `baseline` (rule 2). Re-entry pass: dated <= 72 h backfill, undated stays baseline (existing rule) |
| **Backfill must never alert** and must be rate-bounded | Admission waves (50 boards/run) would flood Telegram and tracker, and burn Groq free-tier budget | LOW-MED | Backfilled jobs are `recent`, so no alert by existing rules; add a per-run cap on backfill evaluations and order newest-first; run hard rules (location, experience) before Groq as today. Groq daily/RPM budget is the real constraint: confirm limits before sizing (not verified here) |
| **Dedupe across sources and identities already seen** | Pile must be N distinct jobs | LOW (exists) | ATS+board+ID identity holds; search-found and polled jobs share a key. Keep. Do not dedupe on URL |
| **Measurement of the target**: tracker rows per day, age at write, share <= 72 h, per source/provider, My_Feedback mix | Cannot claim "replaces manual search" without it; AGENTS rule 5/7 require evidence | MED | Extend `reporting.py` (pure) and Dashboard; report from the Events ledger + tracker. Separate cohorts (rule 8 of metric rules: no cross-cohort ratios). A daily "rows added today / median age / % labelled Would apply" line is enough |
| **Boards past 700 with storage that scales** | Largest single volume lever (2a: about x2 from coverage alone) | HIGH | Blocked on D-43 Events migration (150k rows now, 5-7k new job IDs per refill run from baselines, 10M-cell sheet cap). Run time: median 113 s at 500 boards, max 770 s of a 25 min timeout; linear extrapolation to about 1,400 boards gives median about 5-6 min but the max is a risk. Likely design: stop writing one Events row per baseline ID (store per-board baseline summary), keep full events only for evaluated/alerted jobs |
| **Evergreen/talent-pool title exclusion** ("General Application", "Talent Community", "Future Opportunities", "Pipeline", "Evergreen", "Rolling") | Users distrust "always open" listings; vendor-reported ghost shares 18-27% (LOW) | LOW | Add to the exclusion terms in Settings (user data) or a built-in short list; not a score change |
| **Closed-job handling does not poison the tracker** | Applying to a closed role wastes the one action the user takes | LOW (minimum) | At minimum keep current behaviour: only open IDs are seen on poll. A visible "closed since" mark is a differentiator (below) |

### Differentiators (where this beats LinkedIn/Indeed for this one user)

| Feature | Value proposition | Complexity | Notes / dependency |
|---|---|---|---|
| **Source-verified age with precision labels** (never aggregator-derived) | LinkedIn resets dates on reposts and rounds to "1 month ago"; this product's whole claim is honest age | LOW-MED | Already the core value; v2 exposes it. Keep freshness vocabulary (publication / first observation / update / republication) distinct in columns |
| **Repost and evergreen flagging** ("likely repost: same board, normalised title and location first seen N days ago under a different ID") | Removes the most common reason a "new" row is old; Lightcast uses title+company+location over 60 days | MED | Requires a normalised-title+location key per seen job (check whether Events stores title; otherwise add to the seen event or a compact side index). **Tracker: label, do not drop** (volume over precision). **Alerts: suppress** suspected reposts (never alert on republication, SPEC already says republication is not re-alerted for known IDs; this extends it to new IDs). Needs a false-positive guard: multi-location roles with distinct IDs are not reposts if locations differ |
| **Adaptive polling cadence (tiered) instead of a hard slot cap** | Alerts need hourly polls only on boards that post often; the 72 h tracker window is satisfied by a 6-24 h poll on quiet boards. Removes the eviction logic's pressure and the baseline churn it causes | MED-HIGH | Uses existing evidence columns (`Last_New_Relevant_At`, `New_Relevant_7d/30d`, `Last_Success_At`). Core value (alert <= 12 h) holds as long as a board polled every <= 6 h stays alert-capable; define the tiers so the alert guarantee is only claimed for the hourly tier. Interacts with D-30 pools and the 2026-10-29 first rebalance; do not build before EVID-01 |
| **Feedback-informed board cycling** (My_Feedback as reward) | Cycles toward boards whose rows the user would apply to, not just boards that post relevant titles | MED-HIGH | Reward = kept rows weighted by feedback (Would apply +1, Maybe +0.3, Irrelevant -1) plus new-relevant rate. Standard approach: per-board Beta/Thompson sampling or UCB with decayed counts (half-life weeks, hiring is seasonal) and a prior from ATS/title evidence (cold start). **Pitfalls:** feedback is sparse (about 7-25 labels/day across hundreds of boards), selection-biased (only boards that produced rows have labels), and "Irrelevant" often reflects title/location, not the board. Keep exploration trials (20%), require a minimum label count before a board-level feedback term applies, otherwise use company/role-level aggregation. Lifts rule 7 for board-cycling scores only, as the milestone states |
| **Closed-job marking** (poll sees the ID gone: mark the tracker row "closed") | LinkedIn shows "no longer accepting"; saves wasted applications | MED | **DECISION:** today the tracker is append-only and user edits are never overwritten; this needs an app-owned column the app may update. Poll already knows presence; only the write path is new. Defer unless user asks |
| **New adapters for big employers** (Workday first) | Raises the ceiling by 20-30% of postings (3) | MED per adapter | See adapter ranking below |
| **Wider web search as candidate retrieval** (more roles, JSON-LD on company-hosted pages, curated APIs for board discovery) | Reaches boards and jobs not in inventories | MED | See search section; stays candidate retrieval + ATS hydration (rule 2) |
| **One-line daily digest** (count added today, median age, link) rather than per-row pings | Closes the loop on volume without Telegram flooding | LOW | SPEC documents it as "not built"; optional |

### Anti-Features (do not build; alternatives given)

| Anti-Feature | Why requested | Why problematic | Alternative |
|---|---|---|---|
| Alerting on backfilled or merely "recent" (12-72 h) jobs | Volume; "don't miss anything" | Violates Core Value and the 12 h promise; admission waves would flood Telegram | Tracker only, labelled with age; alerts stay `verified_fresh` >= `Min_Alert_Score` |
| Using aggregator dates (Adzuna `created`, Tavily/Google page date, LinkedIn relative age, Muse `publication_date`) as publication time | Convenient, always present | Breaks AGENTS rule 2; LinkedIn resets on repost; index date is not publication | Use them only to find candidates, then hydrate at the ATS for the authoritative date |
| Scraping LinkedIn or Indeed | They are the incumbent | ToS/blocking, fragile on GitHub Actions IPs, contradicts SPEC "Honest limits"; a robots.txt precedent already cost a decision (D-38) | Stay on public ATS endpoints; use search only for discovery |
| Silently lowering score thresholds or retuning Groq to hit 20-30 | Fastest way to more rows | Rule 7 gate; hides precision loss | Make it an explicit decision backed by My_Feedback evidence (EVID-05). If the user wants a looser tier, use the existing `Stretch / Review` status deliberately |
| Capping or pruning the tracker to "top N per day" | Avoid overload | Contradicts the user's principle (volume over precision as long as recent) | Sort and colour by score and age; filters, not deletion |
| Dedupe on URL, title only, or by dropping reposts | Cleaner list | Violates rule 3; drops real jobs | Identity stays ATS+board+ID; reposts are labelled, not removed |
| HTML scraping of iCIMS/Workday career pages with browser automation at scale | Only route for some portals | Fragile, IP blocking, slow in 25 min runs | Adapters only where a JSON/feed endpoint with a real date exists; otherwise skip the ATS |
| LLM-extracted dates from page text | Fills undated gaps | Unverifiable age; rule 2 | Undated stays `uncertain`/`baseline` |
| Per-minute or sub-hourly polling | "Faster is better" | p90 detection is already 54 min; extra load at 700+ boards for no alert benefit | Tiered cadence (above) |
| Treating a successful poll of a board as proof of full coverage (partial/truncated lists) | Simpler | Silent misses, especially Workable and Workday (page cap of 20, total may saturate near 2,000, MEDIUM) | Keep the completeness rules per provider |

---

## New ATS adapters: ranking for this user (details are third-party descriptions; each needs a live spike before commitment)

| Candidate | Boards in project inventory | Date quality | Access | Entry-level marketing relevance (ESTIMATE) | Priority |
|---|---|---|---|---|---|
| **Workday** (`/wday/cxs/{tenant}/{site}/jobs`, POST) | 3,530 | List `postedOn` is a localized display string ("Posted Today", "Posted 5 Days Ago", "30+ Days Ago"): enough to pre-filter <= 72 h but **not** source publication; detail GET gives `startDate` (YYYY-MM-DD, day precision), one request per job. Send explicit `Accept-Language`. [MEDIUM, community docs] | Unauthenticated JSON, 20 per page (`limit` > 20 returns empty with 200), shard `wdN` and site name must be known per tenant, total may saturate | High: large employers, many entry-level roles | **1** |
| Teamtailor / Recruitee / Breezy | 2,840 / 2,830 / 3,536 | Reportedly real publish dates (RSS, JSON) [LOW, unconfirmed field names] | Public feeds, simple | Lower (Europe-heavy), but cheapest to build | **2** (cheap batch) |
| BambooHR | 5,632 | `date_posted` on the detail record, not the list [LOW] | `/careers/list` and `/careers/{id}/detail` JSON | Medium: many US SMBs | **2** |
| iCIMS | 2,498 | Unclear; no public jobs API [LOW]; dates only via page markup | HTML | High relevance, but fragile | **3** (spike for JSON-LD first; drop if absent) |
| Oracle Recruiting Cloud, UKG, Paylocity, Paycom, JazzHR, Rippling, Personio | 5,135 (Paycom), 2,689, 1,923, 2,463 | Unverified | Unverified | Mixed | **4** (research per adapter later) |

Rule for adapter acceptance: it must supply a source publication time or date; otherwise its jobs are `uncertain` and never reach alerts, and the adapter adds volume but little verified age. One adapter per phase step; the identity (ATS+board+ID, plus Workday's tenant/site/shard) and completeness semantics must be defined before activation (Workday board identity is more than one token).

---

## Wider web search (candidate retrieval only)

| Feature | Complexity | Notes |
|---|---|---|
| More role terms and use of the full Tavily credit budget (800 scheduled/month; the 10-credit/run default leaves a 42-slot rotation about 2.1 days per pass) | LOW | Config and rotation size; live evidence: search found median 455 min detection, 8 jobs in the pilot week, so expect a **trickle**. Value is mainly board discovery (126 boards from 10 slots, 41 new) |
| Add more ATS domains to the search rotation (the 5 supported plus any new adapter's host) | LOW | Each new adapter should add its host to `include_domains` at the same time |
| Curated board-discovery APIs (The Muse: category Marketing/Design, level Entry Level, ISO `publication_date`; Adzuna: `max_days_old`, limit 250 hits/day, 2,500/month) | MED | Use job URLs to extract the ATS board id and hand it to board admission, then hydrate at the ATS. Dates from these APIs are never freshness proof. Check each API's ToS and limits first (Muse limits and Adzuna category tags unverified) |
| JSON-LD `JobPosting` parsing on company-hosted career pages | MED-HIGH | `datePosted` is the employer's claim; treat date-only as day precision, and note republication resets it. Candidate retrieval for companies with no supported ATS. Defer behind Workday |

---

## How others choose which boards to monitor (and what to do here)

- **Search engines / aggregators:** recrawl priority from estimated change rate, with exploration for sources with little history; the literature finds the quality of change-rate estimation matters more than the scheduling formula, and bandit mixtures of strategies win when budgets are tight (Google adversarial-bandit work; restless-bandit index policies; Cho and Garcia-Molina). [MEDIUM]
- **This system today:** already an explore/exploit design (20% exploration pool, 7-day trials, evidence score, floor 2.0, early release D-47). Weaknesses visible in STATUS: 220 of 700 trials scored 0 and were released; 12,460 validated boards overdue for re-check; only 0.7% of re-checks gained relevant jobs (pilot), 176 of 5,000 after the wider Settings.
- **Recommendation (opinionated):** (1) raise coverage first (cap past 700, then tiered cadence) because slots, not ranking, are the binding constraint when 700-1,400 known relevant boards exist; (2) rank the waiting list by recent relevant activity with decayed counts; (3) add feedback only as a bounded term after the first weekly rebalance (due about 2026-10-29) and enough labels; (4) keep the 20% exploration share for unseen boards; (5) do not adopt a learned change-rate model: labels and activity are too sparse for one user.

---

## Feature Dependencies

```
Measurement (rows/day, age, feedback)
    └──enables──> every other v2 feature's go/no-go (calibrate the 20-30 target first)

Events storage migration (D-43)
    └──requires──> Boards past 700
                       └──requires──> run-time check (25 min timeout) and Sheets read quota
                       └──enhances──> Recent backfill (more admissions)
                       └──enables──> Tiered polling cadence

Age columns (Published, Precision) + header migration
    └──requires──> nothing new in freshness.py (data exists in the seen event)
    └──required by──> 72 h tracker window being usable
    └──required by──> Recent backfill (rows must show real age)

Recent backfill ──requires──> SPEC/DECISIONS change to D-05 (rule 1)
    └──requires──> per-run evaluation cap (Groq budget)
    └──conflicts──> alerting (backfilled jobs must stay tracker-only)

New ATS adapters ──requires──> source publication time/date in the adapter
    └──requires──> board identity and completeness definition
    └──enhances──> Wider search (add host to include_domains)

Repost/evergreen flags ──requires──> normalised title+location key stored per seen job
    └──enhances──> Alert suppression, Measurement (unique jobs vs reposts)

Feedback-informed cycling ──requires──> first real rebalance evidence (EVID-01, ~2026-10-29)
    └──requires──> enough My_Feedback labels (measurement shows count)
    └──conflicts──> broad score tuning (rule 7 stays for Groq score / Min_Alert_Score)

Tiered cadence ──conflicts──> fixed pools and weekly rebalance semantics (D-30); decide one model
```

### Dependency Notes

- **Backfill requires age columns:** a backfilled row without a visible real age would look fresh; that breaks rule 2. Ship age display in the same phase or earlier.
- **Scaling requires storage first:** each admitted board adds thousands of baseline IDs to Events (5,273 and 6,919 IDs in the first two refill runs); the 10M-cell cap makes this the gating item.
- **Tiered cadence vs pools:** both decide which boards are polled; building both doubles the logic. Pick tiering as the long-term answer only if the first rebalance shows slot scarcity is the problem.
- **Adapters multiply backfill and storage load:** Workday boards are few but big; per-job detail requests (one GET per job for a real date) cost runtime; use list `postedOn` to pre-filter <= 3 days, then fetch details only for those.

---

## MVP Definition

### Launch With (v2.0 core, in this order)

- [ ] **Measurement**: daily rows, age at write, % <= 72 h, feedback mix, per provider/source (without it the target cannot be proven or tuned)
- [ ] **Age columns + 72 h tracker window** (`Published`, `Precision`, formula age; `Max_Job_Age_Days` = 3 for the tracker; alerts untouched)
- [ ] **Recent backfill** (D-05 amendment documented; tracker-only; capped per run; newest first)
- [ ] **Storage migration, then cap raised stepwise toward about 1,400** (watch run time, Sheets reads, cells) since coverage is the biggest lever (2a)
- [ ] **Evergreen/talent-pool exclusions** (Settings list, no code risk)

### Add After Validation (v2.x)

- [ ] **Workday adapter** (then BambooHR / Teamtailor / Recruitee / Breezy as a cheap batch) once the measurement shows the ceiling, not the filters, is the limit
- [ ] **Repost flagging** (label in tracker, suppress alert) once age columns exist and a title+location key is stored
- [ ] **Wider search** config increases (roles, hosts) immediately; curated-API board discovery after the Workday adapter
- [ ] **Feedback-informed cycling** after the 2026-10-29 rebalance and enough labels

### Future Consideration

- [ ] Tiered polling cadence (only if slots remain the constraint after the cap is raised)
- [ ] Closed-job marking (needs an app-owned column; decision on append-only rule)
- [ ] JSON-LD parsing of company-hosted pages; iCIMS (only if a JSON-LD date is present)
- [ ] Daily digest message

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---|---|---|---|
| Measurement of rows/age/feedback | HIGH | MEDIUM | P1 |
| Age columns and 72 h tracker window | HIGH | LOW-MED | P1 |
| Recent backfill (tracker only) | HIGH | MEDIUM | P1 |
| Boards past 700 (storage migration, cap raise) | HIGH | HIGH | P1 |
| Evergreen / talent-pool exclusions | MEDIUM | LOW | P1 |
| Workday adapter | HIGH | MEDIUM | P2 |
| Cheap-feed adapters (BambooHR, Teamtailor, Recruitee, Breezy) | MEDIUM | MEDIUM | P2 |
| Repost flagging and alert suppression | MEDIUM | MEDIUM | P2 |
| Wider search (config, hosts) | MEDIUM | LOW | P2 |
| Wider search (curated-API board discovery) | MEDIUM | MEDIUM | P2 |
| Feedback-informed board cycling | MEDIUM | MEDIUM-HIGH | P2 (after EVID-01) |
| Tiered polling cadence | MEDIUM | MEDIUM-HIGH | P3 |
| Closed-job marking | LOW-MED | MEDIUM | P3 |
| JSON-LD company-page parsing | LOW | MEDIUM-HIGH | P3 |
| iCIMS adapter | MEDIUM | HIGH (unclear) | P3 |
| Daily digest | LOW | LOW | P3 |

**Priority key:** P1 = must have for v2.0; P2 = should have, after P1 evidence; P3 = defer.

## Competitor / Comparable Feature Analysis

| Feature | LinkedIn / Indeed | Aggregators (Adzuna, Lightcast-type) | Direct-ATS aggregators (HiringCafe, scraper actors) | Our approach |
|---|---|---|---|---|
| Source of jobs | Employer posts + feeds + crawling | Crawl + feeds, dedupe | Employer career pages / ATS | Public ATS APIs, hourly, 5 providers (+ Workday etc.) |
| Date shown | Relative age; resets on repost, rounds old dates | Own first-seen/created date | Best-effort snapshot (vendor characterisation) | Source publication time with precision label; never update/crawl time |
| Dedupe | Internal; reposts labelled | Normalised title+company+location, 60 days | Varies | ATS+board+ID identity; add repost label (new) |
| Alerts | Email/push, instant alerts | API only | Mostly none | Telegram for verified-fresh <= 12 h only; tracker for the rest |
| Personalisation | Profile and behaviour | None | Filters | Resume-scored; My_Feedback to steer board cycling (new) |
| Coverage claim | Broad | Broad | Employer sites | Honest: only polled boards (SPEC "Honest limits") |

## Sources

- Project (LIVE data): `/Users/aphan/auto_search_workflow/STATUS.md` (pilot week 1 funnel, coverage, inventory counts, D-45..D-47), `SPEC.md` (freshness classes, baselining, pools), `.planning/PROJECT.md` [HIGH for project facts]
- BLS Occupational Outlook Handbook, openings 2025-35: market research analysts and marketing specialists (https://www.bls.gov/ooh/business-and-financial/market-research-analysts.htm), graphic designers (https://www.bls.gov/ooh/arts-and-design/graphic-designers.htm), public relations specialists (https://www.bls.gov/ooh/media-and-communication/public-relations-specialists.htm), writers and authors (https://www.bls.gov/ooh/media-and-communication/writers-and-authors.htm) [HIGH for figures, MEDIUM as a proxy for postings]
- ResumeGeni ATS market share (2,605 employers, refreshed 2026-10-25): https://resumegeni.com/research/ats-market-share-2026 [LOW-MEDIUM: vendor sample, employers not postings]
- Ongig ATS installs report: https://blog.ongig.com/applicant-tracking-system/top-applicant-tracking-systems-ats-software/ [LOW: undated]
- JobsPipe marketing postings index (entry-level 11.6%, counted 2026-09-09): https://jobspipe.dev/postings/marketing.md [LOW: vendor, explicit-label share only]
- Lightcast duplicate handling (60-day normalised-field matching, up to 80% duplicates): https://docs.lightcast.io/data/docs/how-does-lightcast-handle-duplicate-postings [MEDIUM for method, LOW for the 80% vendor claim]
- Google JobPosting structured data (datePosted, validThrough, canonical URLs): https://developers.google.com/search/docs/appearance/structured-data/job-posting [MEDIUM; reposting rules not confirmed]
- Crawl scheduling: Google Research, Adversarial Bandits Policy for Crawling Commercial Web Content (https://research.google/pubs/adversarial-bandits-policy-for-crawling-commercial-web-content/); Horvitz et al. crawl-scheduling paper (https://www.erichorvitz.com/Crawl_1801519115.full.pdf, abstract not read); Cho and Garcia-Molina line of work (via search summaries) [MEDIUM]
- Workday CXS endpoint behaviour (POST, 20 per page, `postedOn` display string, detail `startDate`): https://dev.to/udaninn/workday-job-boards-have-a-json-api-too-its-just-better-hidden-23fl and Apify Workday scraper listings [MEDIUM: community, undocumented API]
- BambooHR, iCIMS, Breezy, Teamtailor, Recruitee, Personio adapter facts: Apify actor pages and JobsPipe (https://jobspipe.dev/sources/breezy.md) [LOW: secondhand, verify live]
- The Muse and Adzuna APIs: Apify listings; Adzuna terms (25 hits/min, 250/day, 1,000/week, 2,500/month) at https://developer.adzuna.com/docs/terms_of_service [LOW-MEDIUM]
- LinkedIn "Reposted" behaviour, ghost-job shares (18-27%), first-25-applicants claim: third-party blogs and news (onmsft, Fishbowl, Blind, vendor blogs) [LOW: anecdotal/vendor]
- HiringCafe description: Business Insider and review pages (freshness characterisation is a competitor's) [LOW]

---
*Feature research for: job-alert / aggregation system, milestone v2.0 Search-substitute volume*
*Researched: 2026-10-25*
