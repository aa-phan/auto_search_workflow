# Technology Stack: v2.0 "Search-substitute volume" (new ATS adapters + ledger storage)

**Project:** Auto Search Workflow (existing Python 3.12 / GitHub Actions / Google Sheets poller)
**Researched:** 2026-10-25
**Scope:** only the additions needed for (1) new ATS adapters and (2) Events/identity storage that scales. Existing stack (requests, bs4, gspread, Groq, Tavily, Telegram) is NOT re-researched.
**Overall confidence:** MEDIUM-HIGH. Every endpoint below was hit with real requests on 2026-10-25 (HIGH for "this endpoint returns this shape"). All requests came from a macOS home IP, never from a GitHub Actions runner, so WAF/Cloudflare behaviour from Actions IPs is UNVERIFIED for every provider. Rate limits are undocumented everywhere; no 429 was seen in about 500 probe requests at about 1 request/s. Terms of service were not reviewed (the D-38 question applies to all of these).

## Bottom line

1. **Add five adapters in two waves, skip five ATSs.** Wave 1 (publication time is in the list response, no pipeline change): Workday, Breezy, Oracle Recruiting Cloud, plus Gem (bonus, 497 boards). Wave 2 (needs a new "enrich unseen, gate-passing IDs with a detail fetch" hook): Rippling, BambooHR. Wave 3 (optional): Recruitee, JazzHR, iCIMS. Skip: Paycom (robots.txt deny), Teamtailor, Personio, JOIN (about 0 to 7% US), SuccessFactors (HTML only, heterogeneous).
2. **Only Breezy, Recruitee, Rippling and Gem give a real timestamp (time-of-day, zone-aware).** Workday, Oracle, BambooHR, iCIMS, SuccessFactors and JazzHR give a calendar date at best. Workday's list gives only relative text ("Posted 3 Days Ago").
3. **Do not add a database for v2.0.** Implement the D-43 `Identity` + `Daily` tabs. The ledger problem is rows, not cells: 93 to 96% of Events rows are dedupe-only identities, and D-43 already measured that 59.6M characters load in about 8 s. An external store is warranted only by atomic-lease needs or more than about 3M identities; if that happens, Turso free is the first choice and Cloudflare R2 (conditional writes) is the lease fallback.
4. **No new Python dependency is required for the recommended path.** `requests` + `beautifulsoup4` + stdlib `json` cover everything.

## How freshness classes map (answer to "which ATS can alert")

Facts from `freshness.py` as it stands: `parse_instant` returns precision `time` only for epoch or ISO with a time of day; date-only, relative text and exact-midnight-UTC are `day`. `classify` yields `verified_fresh` for `time` precision within the 12 h window; for `day` precision it yields `verified_fresh` only under D-04(c): source date is today or yesterday (UTC) AND the board's previous successful poll was within the window; otherwise `recent`. No date at all gives `observed_new` (evaluated and tracker-eligible, never alerted) or `uncertain`.

| Precision of source publication | ATSs | Classes possible | Alert? |
|---|---|---|---|
| **Time-precise** (ISO or RFC-2822 with time and offset) | Breezy, Recruitee, Rippling (detail), Gem, Teamtailor, Personio, JOIN | `verified_fresh`, `recent`, `stale` | Yes, same as Greenhouse/Lever/Ashby |
| **Day-precise** (calendar date, or relative day text) | Workday, Oracle, BambooHR, iCIMS, SuccessFactors, JazzHR | `recent`, `stale`; `verified_fresh` only through D-04(c) | **Recommend: tracker only (`recent`, age shown in days) by default.** D-04(c) alert eligibility should be an explicit per-ATS opt-in the owner decides (it was accepted for Workable; extending it is a freshness-policy call under AGENTS rule 2) |
| **No date in list** (until a detail fetch) | BambooHR, Rippling, JazzHR, iCIMS, SuccessFactors list pages | `observed_new` / `uncertain` only, never alerts, until enriched | No |

**Strict reading of "no precise time means never alert":** Workday, Oracle, BambooHR, iCIMS, SuccessFactors and JazzHR produce `recent`/`uncertain` only. This still fully serves the v2.0 goal (72 h tracker window, age always shown, alerts unchanged).

**Three parsing traps that would silently mislabel precision (must be handled in the adapters, with tests):**
- iCIMS JSON-LD `datePosted` is `2026-10-23T04:00:00.000Z` (local midnight expressed in UTC). `parse_instant` sees a non-zero hour and returns `time` precision. That would be a false "time-precise". SuccessFactors microdata is `Sat Oct 24 07:00:00 UTC 2026` (same issue, and not ISO). Adapters must force day precision (emit a date-only string).
- Recruitee `published_at` is `2026-10-23 16:16:22 UTC` (not ISO; `fromisoformat` fails and `parse_instant` returns unknown). Normalize to `2026-10-23T16:16:22Z` in the adapter.
- Workday list text is `Posted Today` / `Posted Yesterday` / `Posted 3 Days Ago` / `Posted 30+ Days Ago`. `parse_instant`'s regexes use `fullmatch`, so the `Posted ` prefix breaks them. Strip it in the adapter. `30+` is a floor, not a date: map it to stale. Also observed (one sample, MEDIUM): a job with `startDate` 2026-10-22 showed "Posted 2 Days Ago" at 2026-10-25 06:05 UTC, so Workday's relative label is computed in a zone behind UTC. Treat list-derived days as plus or minus 1 day; use the detail `startDate` when the exact date matters.

## Candidate ATS verdicts (live-verified 2026-10-25)

Board counts: user-supplied inventory totals; `ats-scrapers` CSV rows and `open-ats-feed` (as of 2026-09-03) were checked directly. Success rates are from random samples (n shown), not full validation.

| ATS | Boards | Public JSON/XML list per board? | Endpoint (verified) | Publication time | Pagination | robots.txt | US relevance (sample) | Verdict |
|---|---|---|---|---|---|---|---|---|
| **Workday** | 3,530 (ats-scrapers) | Yes, unauthenticated POST | `POST https://{tenant}.{wdN}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` body `{"appliedFacets":{},"limit":20,"offset":0,"searchText":""}`; detail `GET .../wday/cxs/{tenant}/{site}{externalPath}` | List: relative text only (`postedOn`; absent on some tenants, 3 of 58 sampled, e.g. Zoom). Detail: `startDate` `YYYY-MM-DD` (date-only). **Day precision** | Page size max 20 (limit 50 gives HTTP 400). `total` only on offset 0 (0 on later pages; offset beyond total repeats page 1). Hard cap about 2,000 (Target, NVIDIA, Capital One show `total` 2000 or 2003; CVS has 19k jobs but pages stop at 2,000). **Order is not reliably newest-first** (12 of 35 sampled boards had out-of-order `postedOn`: pinned or featured jobs first, mixed order) | 3M tenant: `Allow: /Search/`, `Disallow: /private/`, `/refreshFacet/`; `/wday/cxs/` not disallowed | High: big US employers, Campus/early-career sites. 3M US share 367 of 760 | **BUILD (Wave 1).** Highest US entry-level volume. 58 of 60 sampled boards OK, 2 empty, 0 errors. Walmart, Dell and Comcast inventory entries returned HTTP 422 (stale site names), so map 422 to invalid |
| **Breezy** | 4.9k union; ats-scrapers 1,385; open-ats-feed 2,077 live + 1,459 empty | Yes, GET, one request per board | `GET https://{slug}.breezy.hr/json` | **`published_date` ISO with ms and Z: time precision** | None (whole board in one array; largest sampled 203) | Disallows only asset paths | Jobs 79% US in sample (1,054 of 1,338), but only 11 of 36 boards had any US job | **BUILD (Wave 1).** Best API quality. 76% of sampled slugs answered (6 of 25 returned 404). List has no description: hydrate from the page (`div.position-description`, no JSON-LD date there) |
| **Oracle Recruiting Cloud** | 1,280 | Yes, GET REST | `GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.secondaryLocations&finder=findReqs;siteNumber={site},limit=50,offset=0,sortBy=POSTING_DATES_DESC`. Site comes from inventory URL (`CX`, `CX_1001`, ...) | `PostedDate` `YYYY-MM-DD`: **day precision**. Also `PrimaryLocationCountry`, `WorkplaceType`, `Id` | `limit` (50 works), `offset`; `TotalJobsCount` on every page; **server-side `POSTING_DATES_DESC` sort works** (order is reliable, so poll only the first page(s)) | Host robots.txt returns 404 (no restrictions stated) | 624 of 1,173 returned jobs were US (53%) | **BUILD (Wave 1).** 35 of 35 sampled boards OK. `expand=requisitionList...` is mandatory or `requisitionList` comes back empty. Description needs a separate detail call |
| **Gem (bonus, not on the user's list)** | 497 | Yes, Greenhouse-shaped | `GET https://api.gem.com/job_board/v0/{slug}/job_posts/` (array) | `first_published_at` ISO ms Z: **time precision** (also `created_at`, `updated_at`) | None | `api.gem.com/robots.txt` answers `{"message":"Forbidden"}` (uninformative) | US startups (location strings like "Buffalo, United States") | **BUILD (Wave 1, trivial).** Copy of the Greenhouse parser. Verified on 1 board only |
| **Rippling** | 1,924 | Yes, GET | `GET https://api.rippling.com/platform/api/ats/v1/board/{slug}/jobs` (array: `uuid`, `name`, `department`, `url`, `workLocation`); detail `GET .../board/{slug}/jobs/{uuid}` | Detail only: **`createdOn` `2026-10-06T16:36:07.947000-07:00` (time precision, zone-aware)**. List has none. Caveat: it is job-post creation time, may precede going live (MEDIUM) | **Unpaginated**: the Rippling board returned all 649 jobs in one array. A paged variant exists at `ats.rippling.com/api/v2/board/{slug}/jobs?page=0&pageSize=20` (`items[]` with `locations[].countryCode`) | `ats.rippling.com`: `Disallow: /internal/`; `api.rippling.com` has no robots.txt | US-centred SMBs (state codes in `workLocation`); country field not sampled | **BUILD (Wave 2).** 29 of 30 sampled slugs OK; 10 of 29 boards empty, median about 3 jobs. Needs the detail-enrichment hook |
| **BambooHR** | 5,633 | Yes, GET | `GET https://{slug}.bamboohr.com/careers/list` -> `{"meta":{"totalCount":N},"result":[{id, jobOpeningName, departmentLabel, employmentStatusLabel, location{city,state}, atsLocation{country,...}, isRemote, locationType}]}`; detail `GET https://{slug}.bamboohr.com/careers/{id}/detail` -> `result.jobOpening{datePosted, minimumExperience, description, ...}` | Detail only: `datePosted` `YYYY-MM-DD`: **day precision**. List has none. IDs are small sequential integers per company | None (whole list) | Disallows only `/jobs/embed.php`, `/jobs/embed2.php` | 95% US-ish (135 of 142). Bonus: `minimumExperience` (e.g. "Mid-level") is a free entry-level signal | **BUILD (Wave 2).** 35 of 40 sampled OK (2 HTTP 401 and 3 non-JSON: careers disabled, treat as invalid); 19 of 35 answering boards were empty (about 55%), so effective board count is about 2.5k |
| **Recruitee** | 2,809 (OAF 2,444 live) | Yes, GET | `GET https://{slug}.recruitee.com/api/offers/` -> `{"offers":[...]}` (includes full `description`/`requirements`, `experience_code` e.g. `entry_level`, `locations[].country_code`) | `published_at` `2026-10-23 16:16:22 UTC` (**time precision after normalising**), also `created_at`, `updated_at`. In the one sample published equals updated and is later than created, so it behaves as last-publish time (republication shows as a later time) | None (largest 186) | Disallows only `/v/` | Only 19% of jobs US (131 of 702), 9 of 40 boards with any US job | **Wave 3 (optional).** Great API, low US yield. Cheap to add because no hydration call is needed |
| **JazzHR** | 2,689 in inventory; **7,521 companies / 110k jobs** in its sitemap | No per-board JSON. Company pages are HTML (`https://{slug}.applytojob.com/apply`). Global sitemap feeds `https://app.jazz.co/feeds/google/xml/{0..4}` (about 4 MB each, 22k URLs each, 5 files) list every job URL | Detail page JSON-LD `JobPosting.datePosted` `YYYY-MM-DD` (seen on 3 of 4 pages fetched; one page had only an Organization block) | **Day precision**, detail only. Sitemap `lastmod` is always today (useless) | Sitemap files | `Disallow: /cb` (plus some bots) and the sitemaps are declared | US SMB, but heavy on staffing, inspection, blue-collar | **Wave 3 / defer.** The sitemap is a cheap global new-job detector (title is in the URL slug, so the title gate can run before any fetch) and a board discoverer, but 20 MB per pass and low marketing yield |
| **iCIMS** | 2,499 | **No JSON.** HTML cards at `https://careers-{slug}.icims.com/jobs/search?ss=1&in_iframe=1&pr={page}` ("Page 1 of 7"); detail page JSON-LD | Detail JSON-LD `datePosted` `2026-10-23T04:00:00.000Z` = local midnight in UTC: **day precision** (see parsing trap). List cards have location, ID, title and snippet but no date | Page param `pr` | Disallows referral, login, candidate, connect paths; `/jobs/search` allowed | US enterprise and healthcare. Inventory has dead entries (`careers-142designgroup` redirects to Greenhouse) | **Defer.** HTML scraping, a detail fetch per job, fragile |
| **SuccessFactors** | 1,393 | **No JSON.** Customer-branded domains (`careers.dteenergy.com`, `*.jobs2web.com`, `*.successfactors.com`). HTML `/search/?q=&sortColumn=referencedate&sortDirection=desc&startrow=0`; `/sitemap.xml` has job URLs with `lastmod` (update time, not publication) | Detail microdata `datePosted` `Sat Oct 24 07:00:00 UTC 2026`: **day precision** | `startrow` | `Disallow: /services/` (RSS) etc.; `/search/` and `/sitemap.xml` allowed | Mixed, many non-US | **Skip for v2.0.** Slugs are arbitrary domains, one scraper per template |
| **Teamtailor** | 4.3k (OAF 2,334 live) | Yes, RSS `https://{slug}.teamtailor.com/jobs.rss` | `pubDate` RFC 2822 with time and offset (time precision) | None | robots empty | US about 7% (31 of 469 jobs; 3 of 36 boards) | **Skip.** Wrong market (also needs RFC-2822 parsing) |
| **Personio** | 2,464 | Yes, XML `https://{slug}.jobs.personio.com/xml?language=en` | `createdAt` ISO with offset (time precision) | None | `Allow: /` | **0 of 127** jobs US | **Skip.** DACH |
| **JOIN** | 23,548 | No. HTML Next.js page; `__NEXT_DATA__` -> `initialState.jobs.items[].createdAt` (time precision) | | | `/companies/sitemap-jobs-index.xml` served a Cloudflare "Attention Required" challenge | DACH/EU (US share not measured) | **Skip.** Bot challenge plus market mismatch. 23.5k boards is raw count, not fit |
| **Paycom** | 5,136 | No usable listing. The career page is a JS app whose list API is not allowlisted | | | | **`User-agent: *` / `Disallow: /`** with an allowlist that covers only the portal page, `/api/ats/job-postings/` (detail), `portal-settings`, `company-name`. The listing path is not on it | US SMB | **Do not build.** Same posture as D-13/D-38 SmartRecruiters, except here no allowlisted listing exists at all |

### Ranking (US entry-level relevance x board count x API quality, each scored 1 to 3)

| Rank | ATS | US fit | Boards (effective) | API quality (time precision, cost) | Product | Wave |
|---|---|---|---|---|---|---|
| 1 | Workday | 3 | 3 | 2 (JSON, day, unreliable order, 2,000 cap) | 18 | 1 |
| 1 | Breezy | 2 | 3 | 3 (time, 1 request) | 18 | 1 |
| 3 | BambooHR | 3 | 2.5 (45% non-empty) | 1.5 (day, 2-step) | 11 | 2 |
| 4 | Oracle RC | 2 | 2 | 2.5 (day, server sort) | 10 | 1 |
| 4 | Rippling | 2 | 2 | 2.5 (time, 2-step) | 10 | 2 |
| 6 | Recruitee | 1 | 3 | 3 | 9 | 3 |
| 7 | iCIMS | 3 | 2 | 1 (HTML, day) | 6 | 3 / defer |
| 8 | Teamtailor | 0.5 | 3 | 3 | 4.5 | skip |
| 9 | JazzHR | 1.5 | 2.5 | 1 | 3.75 | 3 / defer |
| 10 | SuccessFactors | 2 | 1.5 | 1 | 3 | skip |
| , | Personio, JOIN | about 0 | 3 | 3 | about 0 | skip |
| , | Paycom | , | , | , | , | blocked by robots |

The scores are judgement calls on small samples (n of 25 to 60 per ATS); ties are broken by build cost (Wave 1 needs no pipeline change). Build order differs from pure rank because Wave 1 adapters carry their date in the list response, which fits `observe_new` (it classifies from `ListedJob.published` at first sight).

## Recommended Stack

### Core framework (unchanged)
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Python | 3.12 | Runtime | Already pinned in every workflow |
| requests | >=2.32,<3 (latest 2.34.2) | All new adapters | Already used by `_get_json`; Workday needs `requests.post(json=...)`, the rest are GET. No async or new HTTP client needed |
| beautifulsoup4 | >=4.12,<5 (latest 4.15.0) | Breezy/BambooHR/JazzHR/iCIMS hydration (description from HTML, JSON-LD `datePosted`) | Already used; `hunter._page_date_posted` already extracts JSON-LD `datePosted` generically |

### Adapter integration points (existing code, files read)
| Where | Change | Why |
|---|---|---|
| `boards.py` `ATS_LIST`, `LIST_APIS`, `CASE_SENSITIVE_ATS`, `JobIdentity.url`, `parse_*` | New constants and one `parse_<ats>` per ATS returning `ListedJob`. `LIST_APIS` is a single `str.format(board=...)` GET URL, so it cannot express Workday (POST + tenant + wdN + site), Oracle (host + site number), BambooHR/Rippling (list + detail). Add a per-ATS fetch function table instead of forcing the template | Existing registry shape |
| `BoardId` (`ats`, `board`, `region`) | Workday: `region`=`wdN`, `board`=`tenant/site`. Oracle: `region`=host (or encode `host|site` in `board`). `region` is already part of both board and job keys and defaults empty, so existing keys are unchanged (D-12) | Identity stays ATS + board + posting ID (AGENTS rule 3); never URL strings |
| Job IDs | Workday: `bulletFields[0]` = job req ID (e.g. `R01172154`), NOT the `externalPath` suffix: reposts carry `-1`, `-2` suffixes on the same req ID (MEDIUM, observed on several paths). Oracle: `Id`. Breezy: `id` (12-hex). Rippling: `uuid` lowercased. BambooHR: integer `id`. Gem: `id` | Reposts must dedupe to one identity |
| `_get_json` error mapping | Workday 422 and BambooHR 401 and non-JSON 200 are permanent. Today anything 4xx except 404/410/429 becomes `BoardError` (transient, retried forever with exponential spacing). Map these to `BoardGone`/invalid per provider | D-13: permanent must not look transient |
| `inventory.py` `SUPPORTED_ATS`, importer | Parse Workday slug+URL into tenant/wdN/site (slug is lowercase `tenant/site`; the `wdN` lives only in the URL). Parse Oracle host and site from the URL. Inventory slugs are lowercased; Workday sites answered when lowercased (3M `search`) but the real site name comes from `externalUrl`, so keep the URL's spelling | Case is data (D-12) |
| `pipeline.py` / `ledger.observe_new` | `observe_new` classifies from `ListedJob.published` at first sight, before hydration. For BambooHR/Rippling (and JazzHR/iCIMS later) the date exists only in a detail response. **Add a hook that, for unseen IDs that pass the title gate, fetches the detail and fills `published`/`published_field` before `observe_new`.** Cost is only the gate-passing fraction (titles are gated first, D-08), roughly a few percent of listings. Without it these boards produce only `observed_new` | Needed for Wave 2; also what makes 72 h recent backfill possible for them |
| Workday listing walk | Do not trust order. Walk pages until a full page has no job within the window or the 2,000 cap, keep `total` from offset 0, stop at offset >= total. For boards over 2,000 jobs, read the first response's `facets` (tenant-specific IDs; e.g. `jobFamilyGroup` "Marketing", country) and re-query with `appliedFacets`, or use `searchText`. Verified: US + Marketing facets on 3M returned 18 of 760. Mark such listings `complete=False` so relevance counts are not trusted (the `Listing` class already supports this) | The facet IDs differ per tenant (mastercard, salesforce, disney, capital one have different facet sets and no `startDate` facet), so a global "last 24 h" filter does not exist |
| Per-provider spacing | Keep the 1 s per-provider spacing style of `MIN_INTERVAL`. Workday spreads across `wdN` clusters and tenants (parallel across tenants is fine, about 1 request/s per tenant host). Poll cost: about 1 to 5 requests per Workday board per run, so Workday needs pool limits like every other provider; do not poll all 3.5k hourly | The 25 min run cap and unknown rate limits |
| `freshness.py` | Add an adapter-level precision override (emit date-only strings for iCIMS/SF/Workday), a `Posted ...` prefix strip, and a `... UTC` normaliser | The three traps above |

### Database / storage
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Google Sheets + D-43 `Identity` and `Daily` tabs | gspread >=6.0,<7 (6.2.1) | Keep Events for operational rows only (about 0.4 to 4% of today's rows); identity set as chunked ID lists; daily counters for report continuity | Zero new infrastructure, secrets or failure modes; keeps the single datastore and the writer lease intact |
| Turso (libSQL) free plan, only if a trigger below fires | `libsql` 0.1.11 (2025-09-02; young, 0.x) or plain `requests` against its HTTP API (not live-tested, no credentials) | Indexed identity table | SQLite semantics, no documented inactivity pause |
| Cloudflare R2 free plan, only if atomic lease is needed | `boto3` 1.43.118 (2026-10-22) | Object store for a SQLite or JSON snapshot, with `If-Match`/`If-None-Match` conditional writes as a real compare-and-swap lease | The Sheet lease is write-then-verify and not atomic (D-31) |

### Infrastructure
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| GitHub Actions (unchanged) | `contents: read` stays | Runner | No repository writes needed under the recommended path |

### Supporting libraries
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| stdlib `email.utils.parsedate_to_datetime` | , | RFC-2822 dates | Only if Teamtailor is ever added (not recommended) |
| `defusedxml` | 0.7.1 (2021-03-08, stable but old) | Safe XML parsing | Only if an XML ATS (Teamtailor RSS, Personio, JazzHR sitemap) is added; stdlib `xml.etree` is not hardened against hostile XML. JazzHR's sitemaps are simple enough for a regex or `defusedxml` |

## Ledger storage: should the Events ledger leave Google Sheets?

**Recommendation: not for v2.0. Do the D-43 migration (Identity set, Daily counters, 90-day archive) and keep Sheets. Revisit only on a named trigger.**

### Why (numbers from D-43 and today's checks)
- The problem D-43 measured is row count, not the 10M-cell cap: 122,003 Events rows = 854,021 cells (8.5% of 10M); **93.1% of rows are baseline identities and 96% of steady growth is identity-only rows**. The D-03 review point is 200k rows; it arrives in about 9 days at 700 boards.
- D-43's `Identity` tab stores posting IDs comma-joined in chunks of at most 40,000 characters (cell limit 50,000): 113,549 baselines fit in 523 rows = 2,615 cells (a 99.7% cell saving). Rough scale: at an average of about 18 characters per ID, 1M identities is about 18 MB, about 450 chunk rows, about 2,300 cells.
- Read time is the real limit. D-43 measured Events plus the 22k-row Boards registry at 7.5 to 8.0 s for about 59.6M characters. An 18 MB identity read is smaller than what is read today. Sheets API limits (official, fetched 2026-10-25): 300 read requests/min per project, 60/min per user per project, 180 s request timeout, recommended payload 2 MB with no hard cap, so read the Identity tab in ranged `batchGet` calls of about 100 rows rather than one huge value read. The 10M-cell limit is spreadsheet-wide (all tabs).
- Workday adds large listings but the 2,000-page cap bounds baselines at about 2,000 IDs per board. Boards of 2,000-plus jobs (CVS 19,192, Capital One 2,003) should be facet- or keyword-filtered, which also bounds ledger growth.
- Migration order and rollback hazard (deleting identity rows before parity is proven floods the user with every baseline job as new) are already specified in D-43. Follow it: write `Identity`/`Daily` first, run both readers in parallel, compare, only then delete.

### Options with concrete limits (all checked 2026-10-25)

| Option | Limits | Fit with `contents: read` and ephemeral runners | Verdict |
|---|---|---|---|
| **Sheets `Identity` + `Daily` tabs (D-43)** | 10M cells per spreadsheet; 300 reads/min per project; 2 MB recommended payload; cell 50,000 chars | Already works; no new secret | **Recommended** |
| **Turso (libSQL) free** ([pricing](https://turso.tech/pricing.md)) | 100 databases, **5 GB**, **500M rows read/month**, **10M rows written/month**, 3 GB syncs/month, 1-day PITR; exceeding any limit **blocks** the database (no overage on Free); no inactivity pause is documented; restore of a deleted Free database not guaranteed | Remote DB over HTTPS with a token secret; works from any runner. New secret and failure mode (a blocked DB stops polling) | **First choice if an external DB is triggered.** Budget the read quota: a dedupe lookup reads each of a board's identity rows, so 700 boards x 228 IDs x 720 runs is about 115M reads/month, and about 3,000 monitored boards x 228 would be about 490M, i.e. the Free ceiling. Writes: baselines of 200 boards (about 29k rows) are trivial against 10M |
| **Cloudflare D1 free** ([pricing](https://developers.cloudflare.com/d1/platform/pricing/)) | 5M rows read/**day**, 100,000 rows written/day, 5 GB account-wide; reads count rows **scanned**; each indexed write counts extra; over limit queries **fail until 00:00 UTC** | REST API from Actions | **No.** 5M reads/day is about 208k/hour; a full-board dedupe scan at 700 boards is already about 160k/hour, and 2,000 boards would fail daily |
| **Cloudflare R2 free** ([pricing](https://developers.cloudflare.com/r2/pricing/), [S3 compat](https://developers.cloudflare.com/r2/platform/s3-compatibility/api/)) | 10 GB-month, 1M Class A, 10M Class B ops/month, free egress; conditional `PutObject` (`If-Match`/`If-None-Match`) is evaluated atomically (at most one concurrent writer wins, others get 412) | S3 API with access keys. Pattern: download one snapshot per run, write at end with `If-Match` on the ETag | **Fallback for the atomic lease and for a snapshot-style ledger.** 720 snapshot writes a month is far below 1M ops. Heavier to build (snapshot format, versioned copies for rollback) |
| **Supabase free** ([pricing](https://supabase.com/pricing.md)) | 500 MB database, 2 active projects, **paused after 1 week of inactivity** (hourly writes keep it alive; a missed week needs a manual unpause in the dashboard) | **GitHub Actions is IPv4-only and Supabase direct connections are IPv6-only** ([Supabase doc](https://supabase.com/docs/guides/troubleshooting/supabase--your-network-ipv4-and-ipv6-compatibility-cHe3BP.md)): must use the Supavisor session pooler (`...pooler.supabase.com:5432`, user `postgres.<ref>`), `psycopg` 3.3.6 | Works but the most moving parts (pooler, pause rule, Postgres driver); smaller free storage than Turso |
| **Neon free** ([pricing](https://neon.com/pricing)) | 1 GB per project, 100 CU-hours/project/month then **compute suspends**, scale-to-zero after 5 min, 6 h history | Postgres over public IPv4 | Not recommended: hourly wake-ups burn CU-hours and the cap suspends compute |
| **SQLite file in `actions/cache`** ([changelog](https://github.blog/changelog/2025-11-20-github-actions-cache-size-can-now-exceed-10-gb-per-repository/)) | 10 GB per repo, entries unused for 7 days are evicted, LRU eviction on size; entries are immutable per key (secondary source), so every run needs a new key plus `restore-keys` | Works with `contents: read` | **No as the system of record.** A cache miss means losing the ledger and re-flooding baselines. Acceptable only as a read-through accelerator over a durable copy |
| **SQLite committed to the repo** | 100 MB per file, repo about 1 GB recommended | Needs `contents: write` and a push token; contradicts the "no Git for the user" and `contents: read` posture | **No.** A 50 MB binary rewritten hourly adds about 36 GB of history a month |
| **Actions artifacts** (`actions/upload-artifact`/`download-artifact` v4) | Retention 1 to 90 days; cross-run download needs `actions: read`, run-id lookup and a token; private-repo storage quota is small (MEDIUM, not re-verified) | Possible with extra permissions | **No.** Poor durability, awkward lookup |

### Triggers to leave Sheets (decide with data, from `--storage-report`)
1. Identity tab above about 25 MB (about 1.4M IDs) or Events plus Identity load time above about 60 s of a 25 min run budget.
2. Evidence that the non-atomic lease (D-31) caused a double writer. Then add R2 conditional-write locking, not a full DB migration.
3. A need for cross-run queries the Sheet cannot serve (it can already serve the dashboard and reports).

If a trigger fires: Turso first (SQLite semantics, 5 GB, no pause), R2 snapshot + CAS for the lease. Keep the tracker, Settings, Boards and Dashboard in Sheets regardless: they are the user interface (the Sheet is the only interface).

A cheap compaction to defer: key identities by a 64-bit hash of `ats|board|id` (about 11 base64 characters, collision odds for 1M IDs about 3e-8) instead of raw IDs (UUIDs are 36 characters on Lever, Ashby and Rippling). Not needed below about 1M IDs; it loses human-readable debugging, so keep raw IDs now.

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Workday listing | `wday/cxs/.../jobs` JSON | Scrape career-site HTML, or sitemap `https://{tenant}.wd1.myworkdayjobs.com/{Site}/siteMap.xml` (listed in tenant robots) | JSON is cleaner. The sitemap is a possible cheap new-ID detector (not tested here; `lastmod` is update time) |
| Date for list-less ATSs | Detail fetch only for unseen, title-gate-passing IDs | Detail-fetch every listed job | BambooHR would cost one request per listed job per run for nothing |
| Paycom | Skip | Page scraping | robots.txt `Disallow: /` and the list API is not allowlisted |
| JazzHR | Sitemap new-URL detection (Wave 3) | Per-board HTML scraping of 2.7k boards | The 5 sitemap files already enumerate 7.5k companies |
| iCIMS/SuccessFactors | Defer | Headless browser | Not available on the runner, and the price is more fragility; Actions budget is 25 min |
| Ledger store | Sheets + D-43 | Move to Turso now | Adds a secret, a vendor, a block-on-quota failure mode and a migration, for a problem D-43 removes without them |
| Ledger store | Sheets + D-43 | D1 / Neon / Supabase | Read quota (D1), compute-hour suspension (Neon), IPv6/pause (Supabase), see table |

## What NOT to add

- **No Playwright/Selenium, no proxies, no CAPTCHA or Cloudflare bypass.** JOIN's Cloudflare challenge and Paycom's robots deny are a stop sign, not an engineering problem (D-13, D-38 precedent).
- **No Paycom, Teamtailor, Personio or JOIN adapters in v2.0.** About 35k boards by count, near zero US entry-level yield, or blocked.
- **No new HTTP client, async framework, ORM or queue.** The poller is single-process, thread-pooled `requests`.
- **No external database now.** See above.
- **No "recent" or "posted N days ago" text from search engines or aggregators as publication time** (AGENTS rule 2). Workday relative text is the ATS's own label and is acceptable as day-precision evidence only.
- **No score tuning** (AGENTS rule 7). Board-cycling scores are in scope; the Groq scorer is not.
- **Do not make any day-precision ATS alert-capable by default.** Owner decision per ATS.

## Installation

```bash
# Recommended path: no new packages. requirements.txt unchanged.

# Only if a storage trigger fires (pick one, not both):
pip install "libsql>=0.1.11,<0.2"      # Turso embedded/remote client (young 0.x; or use requests against the HTTP API)
pip install "boto3>=1.40,<2"           # Cloudflare R2 via S3 API (conditional-write lease)

# Only if an XML ATS is ever added:
pip install "defusedxml>=0.7.1,<0.8"
```

## Gaps and unverified items (carry into phase research)

- **GitHub Actions IP behaviour is unverified for every provider.** First task of each adapter phase: a manual `workflow_dispatch` smoke run that hits one board per ATS from a runner and records status codes. Workday, Breezy, Rippling, Gem and BambooHR sit behind Cloudflare or similar.
- **Rate limits are undocumented for all.** Start at 1 request/s per host and let `BoardRateLimited` back off (already implemented). Measure 429s via `meter` before scaling past the pool budget.
- **Terms of service were not read** for any of these (same open question as D-38). Per AGENTS rule 5, this research is live-endpoint evidence only.
- **Workday**: whether `startDate` can be backdated by employers, how reposts are represented beyond the `-1`/`-2` suffix, and the exact time zone behind "Posted Yesterday" are unverified. The default sort is demonstrably not newest-first, so the listing walk must be validated on 10 or more tenants. 422 cause for Walmart, Dell and Comcast (probably stale site names in the inventory) not diagnosed.
- **Rippling `createdOn`** may be requisition creation, not go-live time (one detail fetch). Verify against a job that is first seen live before treating it as alert-grade.
- **Recruitee** `published_at` semantics (equals `updated_at` in the one sample) need a second look before alerts rely on it.
- **Gem** verified on one board; **Rippling** country share not measured; **JOIN** US share not measured (DACH assumed from board names and the sampled company page).
- **Turso Python client maturity** (`libsql` 0.1.x) and its HTTP API were not exercised (no credentials). Treat as MEDIUM.
- **Relevant-job yield per ATS is unmeasured.** The ranking uses US share and board counts, not counts of marketing/content/design entry-level postings. Phase 1 of the adapters should include a read-only yield measurement (title-gate pass rate on the first poll of 20 boards per ATS) before spending pool slots.

## Sources

- Live requests, 2026-10-25 (HIGH): Workday `3m.wd1.myworkdayjobs.com/wday/cxs/3m/search/jobs` and detail; 60-board Workday sample; sort test on 40 boards; Oracle `ebwg.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions` and 35-board sample; `api.rippling.com/platform/api/ats/v1/board/{slug}/jobs` (+detail); `{slug}.breezy.hr/json`; `{slug}.recruitee.com/api/offers/`; `{slug}.bamboohr.com/careers/list` and `/careers/{id}/detail`; `{slug}.applytojob.com` and `app.jazz.co/feeds/google/xml/{0..4}`; `careers-{slug}.icims.com/jobs/search`; `careers.dteenergy.com` (SuccessFactors); `{slug}.teamtailor.com/jobs.rss`; `{slug}.jobs.personio.com/xml`; `join.com/companies/{slug}`; `api.gem.com/job_board/v0/{slug}/job_posts/`; Paycom robots.txt and `sprawl.json`.
- Inventories (HIGH): [kalil0321/ats-scrapers `ats-companies`](https://github.com/kalil0321/ats-scrapers/tree/main/ats-companies) (CSV row counts, URL formats and its README), [veresk06/open-ats-feed `companies.json`](https://github.com/veresk06/open-ats-feed) (as of 2026-09-03: breezy 2,077 live, recruitee 2,444, teamtailor 2,334).
- Secondary, MEDIUM, consistent with live results: [Workday CXS write-up (DEV)](https://dev.to/glitchbound/workdays-job-api-tells-you-there-are-2000-jobs-then-says-0-on-page-two-2c8e), [Workday JSON API (DEV)](https://dev.to/udaninn/workday-job-boards-have-a-json-api-too-its-just-better-hidden-23fl), [Recruitee API overview](https://100hires.com/recruitee-api.html), [BambooHR scraper listing](https://apify.com/bibian/bamboohr-jobs-scraper), [Breezy scraper listing](https://apify.com/jtpalms/breezy-jobs.md). None is official documentation for these public endpoints; no official docs were found for the Workday CXS, Breezy `/json`, BambooHR `/careers/list` or Rippling board API (all are the endpoints the vendors' own career pages use).
- Storage (official pages, HIGH for the numbers): [Turso pricing](https://turso.tech/pricing.md), [Cloudflare D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/), [Cloudflare R2 pricing](https://developers.cloudflare.com/r2/pricing/), [R2 S3 API compatibility](https://developers.cloudflare.com/r2/platform/s3-compatibility/api/), [Neon pricing](https://neon.com/pricing), [Supabase pricing](https://supabase.com/pricing.md), [Supabase IPv4/IPv6](https://supabase.com/docs/guides/troubleshooting/supabase--your-network-ipv4-and-ipv6-compatibility-cHe3BP.md), [Google Sheets API limits](https://developers.google.com/workspace/sheets/api/limits), [GitHub Actions cache changelog](https://github.blog/changelog/2025-11-20-github-actions-cache-size-can-now-exceed-10-gb-per-repository/). Package versions from PyPI JSON on 2026-10-25.
- Project context: `/Users/aphan/auto_search_workflow/DECISIONS.md` (D-03, D-12, D-13, D-38, D-43), `boards.py`, `freshness.py`, `ledger.py`, `pipeline.py`, `inventory.py`, `.planning/PROJECT.md`, `.planning/codebase/STACK.md`, `.planning/codebase/INTEGRATIONS.md`.
