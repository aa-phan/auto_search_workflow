# Constraints (synthesized intel)

Synthesized from `SPEC.md` (type SPEC, manifest precedence 1) with pointers to the locking decisions in `DECISIONS.md`. `SPEC.md` is the current contract and was updated in the same change as each decision, so where it differs from an older decision it wins. Entries point to the section and D-number; they do not restate the full rules. The agent-rules entry is sourced from `AGENTS.md` (type DOC by manifest) because `SPEC.md` and `.planning/PROJECT.md` defer to it as binding.

## Freshness vocabulary and classes
- source: SPEC.md "Freshness vocabulary", "Baselining", "Re-entry"; DECISIONS.md D-04, D-17, D-24; AGENTS.md rule 2
- type: schema
- content: Terms: source publication time (precision `time` or `day`; Workable day-only), first observation, update, republication, board gap. Classes: `verified_fresh`, `observed_new`, `recent`, `uncertain`, `stale`, `baseline`; only `verified_fresh` alerts; assigned once at first observation with evidence recorded. Window `Fresh_Window_Hours` default 12, boundary inclusive. Update time, crawl time, search dates and first observation are never publication time.

## Job and board identity
- source: SPEC.md "Identity and dedupe", "Board registry"; DECISIONS.md D-12; AGENTS.md rule 3
- type: schema
- content: Job key `ats|board(lowercase)|id`; board identity is provider + region/API host + identifier with provider casing (Lever and Workable case-sensitive; Greenhouse, Ashby, SmartRecruiters compared lowercase). Never dedupe on URL strings; preserve identity-bearing URL parameters (Greenhouse embed `for`/`token`, `gh_jid`); ignore tracking parameters (`utm_*`, `gh_src`, `lever-source`).

## Board registry statuses and evidence columns
- source: SPEC.md "Board registry", "Observability"; DECISIONS.md D-03, D-23, D-26
- type: schema
- content: Hidden `Boards` tab; statuses `candidate`, `validated`, `new`, `active`, `invalid`, `deferred`, `disabled`; rows never deleted; demotion and policy parking keep baseline, last success, validation, counts, provenance and ledger events. Evidence columns (`Relevant_Jobs`, `Eligible_Jobs`, `Relevance_At`, `Complete_Polls`, activity fields, `Outages`, pool state) are refreshed only by complete successful polls; unknown is blank, never 0.

## State model: seen, evaluated, alerted
- source: SPEC.md "State model"; DECISIONS.md D-03, D-07, D-21; AGENTS.md rule 4
- type: protocol
- content: Three separate retryable stages derived from the append-only `Events` ledger; a failure at one stage never marks later stages done; transient failures retried; rejected or permanent-looking failures bounded at 5 attempts then abandoned with reason; pending retries never dropped for age (late alerts labelled "delivered late"); delivery at-least-once; stages belong to the job's ledger, not its board.

## Filtering order
- source: SPEC.md "Filtering order"; DECISIONS.md D-08, D-25
- type: protocol
- content: (1) cheap listing checks (roles, levels, excluded words, class); (2) hydrate posting; (3) deterministic hard rules (age, excluded title, non-US location, min experience >= 4 years, required foreign language); (4) Groq scoring only for survivors. Space and hyphen interchangeable in configured terms; a level keyword still required; seniority exclusions first.

## Polling cadence and schedule reliability
- source: SPEC.md "Loops", "Honest limits"; DECISIONS.md D-06, D-34, D-42; STATUS.md "Pilot week 1 result"
- type: nfr
- content: Hourly 24/7 polling target; GitHub Actions schedules are best-effort (observed about every 4.4-4.7 h) and the hourly cadence is carried by an external trigger outside the repo; the freshness guarantee is conditional (monitored board, a poll actually ran, complete listing); coverage is limited to discovered, pollable boards on the five supported ATSs; no parity guarantee with LinkedIn or Indeed.

## Discovery: Tavily request contract and rotation
- source: SPEC.md "Discovery"; DECISIONS.md D-18, D-20, D-35, D-36
- type: api-contract
- content: Slot = ATS host x role term; request query `<role> job`, `include_domains=[host]`, `start_date = today - 3 days`, `basic` depth (1 credit), no answer or raw content, `include_usage` on, one request per slot, at most 20 results, no pagination; location, level and excluded words not in the query. Search is candidate retrieval only; a Tavily `published_date` is never used. Unfiltered search only as manual `--backfill`.

## Search credit budget
- source: SPEC.md "Discovery" (Budget); DECISIONS.md D-36
- type: nfr
- content: Per run `Discovery_Credit_Budget` (default 10); monthly `Search_Monthly_Credits` (default 1,000) with `Search_Reserve_Credits` (default 200) withheld from scheduled runs; persistent ledger in the `Discovery` tab by search path; exhaustion skips discovery and polling continues; 432/433 blocks spending until the UTC month rolls over; the local counter cannot see usage by other keys or projects.

## Polling budget, pools and weekly rebalance
- source: SPEC.md "Polling budget and pools", "Weekly rebalance"; DECISIONS.md D-26, D-30, D-32, D-45, D-47
- type: protocol
- content: Only `new`/`active` boards polled, at most `Max_Active_Boards` (code default 500; production 700 per D-45), split established / exploration (default 80/20, `Exploration_Share_Percent` 20); trial `Exploration_Days` 7; weekly rebalance (`Rebalance_Every_Days` 7) with score = 2 x min(new relevant per week, 5) + min(open eligible jobs, 5), margin 1.0, two consecutive weak cycles, `Max_Replacements_Per_Rebalance` 20, graduation floor 2.0, cool-down 14 days, rotation at 21 days, evidence minimum `Exploration_Days x 12` complete polls with evidence under 24 h old; `Rebalance_Mode` default `report` (production `on`); early release of below-floor trials between cycles (D-47). The D-30 values are initial operating choices, not proven or tuned.

## Writer serialization
- source: SPEC.md "Polling budget and pools" (Serialization); DECISIONS.md D-28, D-31, D-37
- type: protocol
- content: Only the hourly poller makes pool transitions; every registry-writing workflow shares concurrency group `job-hunter-state` with `cancel-in-progress: false`; every writing `hunter.py` command takes an advisory writer lease (hidden `Lock` tab or `state/lock.json`; TTL poller 30 min, inventory 45 min, above workflow timeouts 25 and 40 min); the Sheet lease is write-then-verify and NOT atomic; GitHub keeps only the newest waiting run per group; read-only commands take no lease; the importer skip guard is best-effort.

## Production writes only in the serialized workflows
- source: SPEC.md "Pilot measurements and deployment (D-37)"; DECISIONS.md D-37; DEPLOY.md section 8
- type: protocol
- content: Local commands that would write to a Sheet refuse (exit 4) unless `GITHUB_ACTIONS=true` or `ALLOW_LOCAL_SHEET_WRITES=1` for a test Sheet no workflow writes; read-only commands (`--dry-run`, `--url`, `--rebalance-report`, `--search-usage`, `--inventory-report`, `--pilot-report`) are unaffected; workflows are read-only toward the repository (`contents: read`).

## Provider limits and ATS adapter completeness
- source: SPEC.md "Board registry" (evidence, provider limits); DECISIONS.md D-13, D-27, D-33, D-37, D-38
- type: api-contract
- content: Lever `Crawl-delay: 1` enforced. SmartRecruiters API host `robots.txt` says `Disallow: /`; default is parked, but D-38 (owner decision) polls it for this deployment via `ALLOW_SMARTRECRUITERS_BULK=1`; provider acceptance unknown; SmartRecruiters answers 200/empty for unknown companies. HTTP 429 stops the provider for `Retry-After` (default 5 min, max 15). Completeness by documented pagination: Greenhouse and Ashby unpaginated; SmartRecruiters `totalFound`; Lever continued with `skip` at page-size lengths; Workable widget undocumented (flagged possibly truncated, size unverified). Source publication fields: Lever `createdAt`, Greenhouse `first_published`, Ashby `publishedAt`, Workable `published`, SmartRecruiters `releasedDate`.

## Tracker schema and header-name contract
- source: SPEC.md "Delivery"; DECISIONS.md D-44, D-46
- type: schema
- content: `Job Tracker` is append-only; jobs scoring >= 50; `My_Status` choices To Apply and Stretch / Review (app) and Applied, Interviewing, Offer, Pass, Rejected (user); `My_Status`, `User_Notes`, `My_Feedback` never written or overwritten; columns found by header name (reorderable, do not rename); row 1 must stay the header: without `Apply_URL` the app writes nothing, the run fails and jobs are retried after the header is restored.

## Hidden state tabs and run records
- source: SPEC.md "Delivery" (hidden tabs), "Observability", "Operational dashboard (D-40)"; DECISIONS.md D-03, D-40
- type: schema
- content: Hidden tabs `Boards`, `Events` (append-only), `Runs`, `Discovery`, `Inventory`, `Lock`, `Watchdog`; `Runs` row per run with run-start record completed in place by `Run_ID` and fields `Outcome` (`ok`, `degraded`, `failed`, `started`), `Run_Kind` (`production`, `rehearsal`), `Code_Version`, credit status and timing/limits columns; ledger events carry `detail.run`; evaluations carry `reject` stage code. Fields recorded going forward are never back-filled; blank/`n/a` means unknown, not zero.

## Dashboard is output only
- source: SPEC.md "Operational dashboard (D-40)"; DECISIONS.md D-40, D-41
- type: protocol
- content: Generated `Dashboard` tab rewritten in one batched write after each poller run; nothing in `pipeline`, `pools`, `inventory` or `hunter` reads it; refresh failure logged and contained; `reporting.py` pure (no clock, no LLM); metric rules 1-8 (unique vs attempts, source vs provider, denominators, latency split, coverage of known eligible boards only, exclusions, zero vs unknown, no cross-cohort funnel).

## Missed-run watchdog
- source: SPEC.md "Missed-run watchdog (D-42)"; DECISIONS.md D-42; DEPLOY.md "Watchdog"
- type: protocol
- content: `watchdog.py` imports nothing from the hunter, own workflow and concurrency group, reads only `Runs`; states healthy / running / outage (failed, stalled, absent) / unavailable; default threshold 2 h; one outage and one recovery message to `TELEGRAM_CHAT_ID`; unreadable data sends nothing and exits 3; never restarts workflows, changes Settings, takes the writer lease or writes the repository; shares GitHub Actions, Sheets API and Telegram with the hunter.

## Telegram delivery
- source: SPEC.md "Delivery"; DECISIONS.md D-21
- type: api-contract
- content: One message per `verified_fresh` job scoring >= `Min_Alert_Score`, with title, company, location, score, verdict, gaps, apply link, tracker link; accepted-by-API means alerted; late delivery labelled; a pending alert retried until accepted or rejected 5 times.

## Groq scoring client
- source: SPEC.md "Filtering order" step 4; DECISIONS.md D-16
- type: api-contract
- content: Defaults `openai/gpt-oss-120b` primary and `openai/gpt-oss-20b` fallback (override `GROQ_MODEL`, `GROQ_FALLBACK_MODEL`); output cap 1,000 tokens; 429 falls back; a nonexistent model switches models and, if neither works, stops the run with a clear message without burning per-job attempts. Scoring bands per README. Resume text is sent to Groq on each scoring call (no recorded data-handling decision).

## Google Sheets limits
- source: SPEC.md "Pilot measurements and deployment" (limits audit); DECISIONS.md D-03, D-43; STATUS.md "Pilot week 1 result"
- type: nfr
- content: 10,000,000 cells per spreadsheet; about 60 reads a minute per user (peak observed 12.4/min); quota 429 retried after the window; run timeout 25 min (poller) and 40 min (inventory, `--max-seconds 1500`); `Events` pruning review point about 200k rows (D-03); `Events` was 140,668 rows (about 2,900 a day) at end of pilot.

## Secrets and personal data
- source: AGENTS.md rule 6; DECISIONS.md D-09, D-37; DEPLOY.md sections 0 and 4
- type: nfr
- content: Never read, print or commit `.env`, `Resume.pdf`, `resume.txt` or service-account JSON; do not edit `.env`; resume lives only in the Sheet; secrets only as GitHub secrets (names in DEPLOY.md section 4); `tracked_jobs*.csv` and `legacy/*.csv` untracked; repository meant to be private.

## Agent operating rules (binding by reference)
- source: AGENTS.md rules 1-8 (type DOC by manifest; referenced as binding by .planning/PROJECT.md)
- type: nfr
- content: Read SPEC.md, DECISIONS.md, STATUS.md before changing behaviour; flag conflicts with SPEC/DECISIONS first and update docs in the same change; freshness is the product; keep seen/evaluated/alerted separate; separate mocked from live (no live claims for Sheets, Groq or Telegram without credentials); no score tuning or new features until freshness and delivery are proven (see STATUS); run `python -m unittest discover -s tests` before finishing and keep tests offline.

## Scope exclusions
- source: SPEC.md "Out of scope for now", "Honest limits"
- type: nfr
- content: Out of scope: tuning scores, additional ATSs, non-US markets, email/SMS, a web UI, guaranteeing parity with job boards. Jobs on other ATSs, company-hosted pages, LinkedIn and Indeed are not covered; unsupported inventory providers are counted, not imported.

## Pilot measurement conventions
- source: SPEC.md "Pilot measurements and deployment (D-37)"; DECISIONS.md D-42; PILOT_LOG.md
- type: protocol
- content: Measure from the first production run; coverage as distinct hourly intervals with a successful poll; workflow outcomes apart from board polls; latency over all time-precise relevant postings with n and unknown-date counts; coverage always with its population and never as market coverage; rehearsal runs and fixtures excluded; PILOT_LOG.md must be updated in the same change as any deployment that could affect a measurement.
