# Project Research Summary

**Project:** Auto Search Workflow — milestone v2.0 "Search-substitute volume"
**Domain:** Fresh-job alert poller (public ATS APIs, Google Sheets as datastore and UI, Groq scoring, Telegram, Tavily)
**Researched:** 2026-10-25
**Confidence:** MEDIUM (endpoints and integration points HIGH; every volume number and the Groq account limits LOW-MEDIUM)

## Executive Summary

v2.0 turns an hourly verified-fresh alert poller into a search substitute: pilot week 1 delivered about 3 alerts and 7 tracker rows a day; the target is 20-30 relevant jobs posted within 72 h reaching the tracker daily, while Telegram stays `verified_fresh` within 12 h. The system already works like a direct-ingestion aggregator, and recall is bounded by four levers: boards monitored (cap 700, about 53% of known relevant boards), ATS coverage (5 providers), filters, and the 12 h window at admission. Most features are small seams in existing modules (one `Tracker_Window_Hours` setting, backfill as `RECENT` plus a marker, age columns, measurement); two are structural (the D-43 storage migration and new ATS adapters behind a registry).

**The binding constraint is Groq evaluation throughput, and it bounds the whole milestone.** Reported limits for `gpt-oss-120b` / `-20b` are 30 RPM, 1K RPD, 8K TPM and **200K tokens per day per model**; at about 3.5-5k tokens per call that is **about 40-55 evaluations a day per model**, against **about 110-165 a day** needed (18% of scored jobs were kept in the pilot; the pilot already ran about 37/day). On that ceiling the tracker gets **about 7-10 kept rows/day per model** (about 14-20 if the fallback model's separate budget really works, unverified); more boards or adapters do not raise it. **The account tier is unverified**: ARCHITECTURE reads these figures as the free tier, PITFALLS says Groq documents them as the Developer-plan base and the free-plan figures for this account could not be checked; nobody has read the account's limits page or measured real tokens per call. Both are Phase 1 task 1; until the owner decides the Groq plan and budget, the 20-30 target is conditional.

Other risks in order: (1) backfill must never starve live alerts (strict priority queue, capped share of daily tokens, deadline before the 25 min timeout); (2) day-precision sources (Workday, Oracle, BambooHR) must never look time-precise: tracker admission by upper bound with a precision label, no alert by default; (3) Events reaches the D-03 review point (200k rows) in about two weeks, so storage must land before board growth or big-board adapters. Honest volume: the five current ATSs at full coverage supply about 12-55 relevant jobs/day (midpoint about 25); the target sits in the upper half, so adapters and wider search are what make it robust. Treat every volume number as an estimate until the Phase 1 measurement exists.

## Reconciliations (where the four files disagree, and the view adopted)

| Question | Views | Adopted | Why |
|---|---|---|---|
| New freshness class for backfill? | ARCHITECTURE: reuse `RECENT` + `detail.backfill`. PITFALLS: new non-alertable `recent_72h`. | **No new class**: `RECENT` + backfill marker, stored publication timestamp and precision, separate reporting cohort. | `ALERTABLE`, `counts_as_new_posting`, `priority` and the reporting partitions already treat `RECENT` correctly; a new class touches all of them. PITFALLS' goals (never alertable, latency populations split, precision visible) are met by marker + cohort. Add expiry with `reject="age"` and no Groq call, recorded as `aged_out`, not `abandoned`. |
| Detail fetch for list-less sources | STACK: enrichment hook for unseen, gate-passing IDs (BambooHR, Rippling). ARCHITECTURE assumes dates in lists. | STACK's hook, in the adapter phase; Phase 2 does not need it. | Cost is only the gate-passing few percent. |
| Storage vs backfill order | ARCHITECTURE: backfill then storage (routing depends on backfill semantics). PITFALLS/FEATURES: storage first. | **Governors → backfill at current scale → storage; no board growth, admission waves or big-board adapters until storage passes parity.** Start the storage design and Sheets spike early. | Backfill only moves in-window jobs from baseline to `PENDING` (about 500 operational rows/day); the flood and growth hazards come from board growth and re-baselining, which the gate blocks. If 200k rows arrives before storage, pause refills. Keep `Events_Legacy` until parity holds. |
| Workday precision and ordering | STACK: day precision, relative text in list, order unreliable (12/35), 2,000 cap, tracker-only. ARCHITECTURE: early-stop paging if newest-first (unverified). PITFALLS: parse as range, "30+" stale, robots gate, Actions-IP spike. FEATURES: Workday first. | **Tracker-only day precision, never alerting unless the owner opts in per ATS.** Parse "Posted Today/Yesterday/N Days Ago" as a range (±1 day zone skew), "30+" stale, unparsable unverified. No early stop on order. Build after the registry and cheaper adapters, after an Actions-runner spike and the policy decision. | STACK's live evidence refutes the early-stop assumption; FEATURES' "first" reflects volume, not cost or ToS risk. |
| Day-precision tracker admission | ARCHITECTURE: upper bound. FEATURES: within 2 calendar days. PITFALLS: earliest instant + grace or "<= 4 d". | **Admit when `now - start_of(D)` is within the window, label "date only, at most N h", never alert.** Grace is an owner decision. | Without it, day-precision adapters add zero backfill volume. |
| Which adapters | FEATURES: Workday, then a cheap batch (incl. Teamtailor, Recruitee). STACK: live-verified, skip Teamtailor/Personio/JOIN/Paycom/SuccessFactors, defer iCIMS. | **Follow STACK.** Wave 1: Breezy, Gem, Oracle, Workday. Wave 2: Rippling, BambooHR. Optional: Recruitee, JazzHR. **Defer iCIMS; skip Paycom** (robots `Disallow: /`). | STACK hit real endpoints; FEATURES' adapter facts are secondhand. The milestone text names iCIMS, so the owner should see this scope change. |
| Is 200K TPD the free tier? | ARCHITECTURE: yes. PITFALLS: Developer base, free unverified. | **Unresolved: Phase 1 task 1.** | Neither read the account's limits page. |

## Key Findings

### Recommended Stack

No new Python dependency (`requests`, `beautifulsoup4`, stdlib; Python 3.12). No database: the Events problem is rows, not cells (93-96% are dedupe-only identities), so D-43 `Identity` + per-run `Tally` tabs stay in Sheets. External store only on a named trigger (Identity above about 25 MB, load above about 60 s, or a double-writer incident): Turso first, R2 conditional writes for a lease. Rejected: D1, Supabase, Neon, SQLite in cache or repo.

Adapters (live-verified 2026-10-25 from a laptop IP, never from Actions):
- **Breezy**: `GET {slug}.breezy.hr/json`, time-precise, one request per board.
- **Gem**: Greenhouse-shaped, time-precise (`first_published_at`), one board verified.
- **Oracle Recruiting Cloud**: REST with a working server-side date sort; day precision; 35/35 boards OK.
- **Workday**: `POST .../wday/cxs/{tenant}/{site}/jobs`; 3,530 boards, highest US volume; relative text in the list, date-only `startDate` in detail; 20 per page, 2,000 cap, unreliable order; job ID is the requisition ID; HTTP 422 = invalid board.
- **Rippling, BambooHR**: date only in detail, need the enrichment hook; about 55% of BambooHR boards empty.

Precision traps needing adapter tests: iCIMS / SuccessFactors midnight-in-UTC stamps look time-precise (force day precision); Recruitee `published_at` is not ISO (normalize); the Workday `Posted ` prefix breaks `parse_instant` and `30+` is a floor. Integration: a per-ATS fetch-function table replaces the GET-only `LIST_APIS`; permanent errors map to invalid, not transient; keep 1 request/s per host.

### Expected Features

**Must have (P1):** measurement with backfill latency split from live latency; visible age on every row (timestamp, precision and source stored, age by Sheet formula); 72 h tracker window with alerts unchanged; tracker-only, capped, newest-first backfill (D-05 change); boards past 700 on scaled storage; evergreen and talent-pool exclusions.

**Should have (P2):** Workday and other adapters; repost labelling (label in tracker, suppress alert); wider search; feedback-informed cycling after the 2026-10-29 rebalance.

**Defer:** tiered cadence, closed-job marking, JSON-LD company pages, iCIMS, daily digest.

**Anti-features:** alerting on recent or backfilled jobs; aggregator dates as publication time; LinkedIn/Indeed scraping; lowering thresholds to hit the number; top-N tracker caps; URL dedupe; LLM-extracted dates.

**Volume:** 700 boards alone about 9-14 kept/day; all about 1,400 known relevant boards plus the widened Settings about 16-34; backfill is a one-time ramp of about one day's target, not the steady-state engine.

### Architecture Approach

One `Windows` value object (fresh 12 h, track 72 h) flows through `Observation` and `Deps` so no gate disagrees; `classify` returns `RECENT` on the baseline pass for a time-precise age inside the window; `observe_new` marks `detail.backfill`; the evaluator age gate moves to hours. The hidden bottleneck is evaluation: `GroqClient` paces at 8K TPM and nothing stops the evaluate loop before the 25 min timeout.

New or changed components:
1. `eval_budget.py`: daily token ledger + `eval_deadline_s`.
2. `freshness` / `ledger` / `pipeline`: windows, backfill marker, expiry without Groq, disposition routing.
3. `identity.py` + `Ledger.is_seen` facade: 40k-char chunked ID sets, per-run `Tally` rows, rename-swap to `Events_Legacy`, `--storage-parity`.
4. Adapter registry in its own module with golden tests proving the five existing providers produce byte-identical keys.
5. `feedback.py` + `pools.score_v2` in shadow beside v1, using listing-derived `Recent_Relevant_72h`.
6. Quick wins: share the loaded Events with the dashboard, compact `JobState`, append-only `Runs` columns.

### Critical Pitfalls

1. **Groq daily cap.** Track tokens per run and day; strict priority queue (`verified_fresh` first, then backfill newest-first with a capped share and a reserve); keep the prompt prefix stable (cached tokens do not count toward limits); unscored backfill stays pending until `aged_out`. A 20b pre-screen or prompt cuts are scorer changes (rule 7) and need an owner decision.
2. **"Recent" from a non-publication timestamp.** Greenhouse `first_published` is undocumented in the list endpoint (never fall back to `updated_at`); Ashby `publishedAt` is "most recently published" (republish looks new); Lever `createdAt` unconfirmed; evergreen reposts get new IDs. Repost key (company, normalized title, location, requisition ID, 30-60 days) as a label, per-adapter contract tests, missing field = unverified.
3. **Static or day-precision age misread.** Store timestamp and precision, compute age live, report 72 h rows separately from 12 h rows.
4. **Sheet limits.** 10M cells counts the allocated grid across all tabs; payloads under 2 MB (chunk by bytes); 60 reads/min per user; a timeout mid-baseline makes old jobs look new (mark baselined only after the last chunk); prove parity before deleting.
5. **Access and policy.** Actions-IP behaviour unverified for every new provider: per-tenant robots gate, circuit breaker, a WAF challenge never marks a board `invalid`; rate limits and ToS unknown.

Also: feedback cycling can starve new boards (shrinkage, minimum dwell, protected 20% exploration floor); Tavily needs about 10.8 days per pass for 216 slots against a 3-day window (use search mainly for board discovery); add a `Job_Key` tracker column (Apply_URL dedupe violates rule 3); fix CONCERNS #1 and #2 before volume multiplies them; the repo is public while DEPLOY.md says private.

## Implications for Roadmap

Suggested 8 phases (the roadmapper may merge or renumber):

### Phase 1: Measurement, evaluation governors, owner gates
**Delivers:** rows/day, age-at-found and feedback mix (backfill separated); `Runs` columns for tokens, bytes, load timers, skipped boards; `eval_deadline_s`, `eval_budget.py`, poll deadline with oldest-first order; shared dashboard load, compact `JobState`; confirmed Groq tier and real tokens per call; CONCERNS #1/#2 and Telegram truncation fixes; EVID-01 read (about 2026-10-29); Actions `workflow_dispatch` smoke probe of one board per candidate ATS; owner decisions surfaced.
**Avoids:** Pitfalls 1, 6, 11 (prerequisites), 12, 17.

### Phase 2: Windows, age columns, backfill, repost and evergreen handling
**Delivers:** `Tracker_Window_Hours` (72) via `Windows`; backfill as `RECENT` + marker; hours-based evaluator gate; expiry without Groq (`aged_out`); `Published`/`Precision`/`Source` columns with formula age, by header name; upper-bound day-precision rule; `Job_Key` column; repost label + alert suppression; evergreen Settings exclusions; priority queue with capped backfill share; D-48 + SPEC/DECISIONS/STATUS in the same change.
**Avoids:** Pitfalls 2, 3, 10, 11; tests for 71/73 h boundaries and re-entry.

### Phase 3: Storage migration (D-43 amended)
**Delivers:** `identity.py`, `Ledger` facade, Identity + per-run Tally tabs, dual write, `--storage-parity`, several days of parity, rename-swap to `Events_Legacy`, archive after 60-90 days, byte chunking and write ordering, allocated-cell report.
**Avoids:** Pitfall 5; must precede growth and big-board adapters.

### Phase 4: Cycling evidence in shadow, then score
**Delivers:** listing-derived `Recent_Relevant_72h`, `feedback.py`, v2 score shadowed then live, shorter `Exploration_Days`, exploration-floor test, minimum dwell. Needs Phase 2 and the first weekly rebalance.
**Avoids:** Pitfall 8; tuning on a moving baseline.

### Phase 5: Scale boards past 700
**Delivers:** `Max_Active_Boards` 700 → 1,000 → 1,400, each step gated on `Runs` metrics (p95 `Duration_S` below 12.5 min, `Load_S`, Sheets reads/min, `Eval_Transient`, tokens); per-provider time budgets; cadence tiers only if hourly cost blocks. Needs Phases 1, 3, 4.

### Phase 6: Adapter registry and Wave 1 adapters
**Delivers:** registry with golden tests (can start in parallel from Phase 2); Breezy and Gem (time-precise, can alert), then Oracle; inventory parsers; per-provider error mapping; recorded policy decisions; read-only yield measurement (title-gate pass rate on 20 boards per ATS) before spending pool slots.

### Phase 7: Workday and detail-enrichment adapters
**Delivers:** Workday (POST helper, composite `tenant/site` board id with `wdN` as region, requisition-ID identity, range parsing, bounded paging, robots gate, circuit breaker); enrichment hook; BambooHR and Rippling. Needs storage, an Actions spike and the policy decision; day-precision rows tracker-only.

### Phase 8: Wider Tavily search (may run parallel to 5-7)
**Delivers:** per-slot yield stats, yield-weighted rotation, `start_date` tied to the window, hydration cap as a setting, daily credit cap, board discovery, adapter hosts in `include_domains`. Acceptance: slots × revisit interval fits the window, or partial coverage is stated.

### Phase Ordering Rationale
Evaluation is the first bottleneck, so governors come first; backfill semantics precede storage routing; storage precedes growth. Phases 2 and 3 both touch `ledger.observe_new` and the run-cycle observation block, so they must not overlap. No tuning until the 2026-10-29 rebalance is read (the 2026-10-23 Settings change still mixes regimes). Every deployment that affects a measurement goes into PILOT_LOG.

### Owner decisions the roadmap must surface

| # | Decision | Needed by | Default if unanswered |
|---|---|---|---|
| 1 | **Groq plan and budget**: free vs paid, confirm limits, D-16 model OK, 20b pre-screen or prompt cuts (scorer changes, rule 7), more resume text sent to Groq at volume (privacy) | Phase 1; gates the target | Target conditional at about 7-20 kept/day |
| 2 | **D-05 amendment (D-48)**: backfill on first baseline and re-entry; close out-of-window `recent` evaluations without scoring (SPEC "State model" exception limited to non-alertable classes) | Phase 2 | No backfill |
| 3 | **Day-precision tracker admission**: upper-bound rule, grace, "date only" label, whether any day-precision ATS may alert via D-04(c) | Phase 2 and each adapter | Tracker only, never alert |
| 4 | **Per-ATS policy and robots**: ToS unreviewed for Workday, Oracle, Breezy, Gem, BambooHR, Rippling; **Paycom skip**; iCIMS deferred (changes milestone text); JOIN, Teamtailor, Personio, SuccessFactors skipped; reconfirm D-38 | Phase 1 (record), before each adapter | Build only providers with a recorded decision |
| 5 | **Partial rule-7 lift** for board-cycling scores only (not the Groq score or `Min_Alert_Score`), after the first weekly rebalance evidence | Phase 4 | No v2 score live |
| 6 | **Repo visibility**: public now vs DEPLOY.md private (public repos expose logs and disable schedules after 60 days of inactivity; private repos have an Actions-minutes limit) | Phase 1 | Stay public, keep logs free of job content, activity heartbeat |
| 7 | **SmartRecruiters post-pilot**: the D-38 override ended with the pilot; robots disallows | Phase 1 | Parked |
| 8 | Smaller: paid Tavily credits (about $8 / 1,000), one-time catch-up of already-baselined jobs, closed-job marking, daily digest | Phases 2, 8 | No spend, no catch-up |

### Research Flags

Need research during planning:
- **Phase 1:** Groq account limits and tokens per call; Actions-IP probe.
- **Phase 3:** Sheets behaviour on 100+ MB reads, chunk rewrite atomicity, rename-swap via gspread, `Load_S` at 150k/200k rows.
- **Phase 6:** second look at Gem and Oracle; Recruitee `published_at` and Rippling `createdOn` semantics before any alert relies on them.
- **Phase 7:** Workday order on 10+ tenants, requisition-ID field, `startDate` vs label zone skew, robots/ToS, the 422 cause (Walmart, Dell, Comcast), inventory row format.
- **Phase 8:** whether `include_domains` matches `*.myworkdayjobs.com`; credit arithmetic.

Standard patterns (skip research): Phase 2, Phase 4 (constants from Phase 1 data), Phase 5.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM-HIGH | Endpoints live-hit (HIGH) but from a home IP, not Actions; rate limits and ToS unknown; n=25-60 per ATS |
| Features | MEDIUM (LOW on numbers) | Mechanisms tied to the pilot funnel; ATS-share and volume figures are estimates on small or vendor-skewed bases |
| Architecture | HIGH on integration, MEDIUM on limits | Read from code and DECISIONS; Groq/Tavily limits from secondary sources |
| Pitfalls | MEDIUM-HIGH | Official docs fetched; Groq tier, Actions-IP behaviour and Workday ToS applicability unverified |

**Overall confidence:** MEDIUM. The design is well grounded; the target number is not, and it depends on an unverified Groq tier.

### Gaps to Address

- Groq tier, limits and tokens per call (Phase 1 task 1).
- Per-ATS relevant-job yield unmeasured: measure before spending pool slots.
- Actions-IP behaviour for all new providers: probe from a runner, circuit breaker.
- ToS for all new providers: owner decision.
- Repost and evergreen prevalence: label, never drop, measure.
- `Load_S` slope: one measured point (8.0 s at 121k rows).
- Greenhouse `first_published`, Ashby republish and Lever `createdAt` semantics: contract tests.
- The Settings-broadening multiplier and the first weekly rebalance are unread.
- Workday `startDate` semantics and the zone behind relative labels: calibrate per tenant.

## Sources

### Primary (HIGH confidence)
- Live endpoint probes of 2026-10-25 (see STACK.md); official Groq, Google Sheets, GitHub Actions, Tavily, Greenhouse, Ashby and storage-vendor docs; project SPEC, DECISIONS, STATUS, PILOT_LOG, PROJECT.md and source modules.

### Secondary (MEDIUM confidence)
- Third-party Groq limit tables; Workday CXS write-ups; BLS Occupational Outlook openings; crawl-scheduling literature.

### Tertiary (LOW confidence)
- ResumeGeni, Ongig and JobsPipe ATS shares; Lightcast duplicate claims; LinkedIn repost and ghost-job statistics; Apify listings.

Per-file source lists are in STACK.md, FEATURES.md, ARCHITECTURE.md and PITFALLS.md.

---
*Research completed: 2026-10-25*
*Ready for roadmap: yes*
