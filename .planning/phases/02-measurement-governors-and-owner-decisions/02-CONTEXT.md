# Phase 2: Measurement, governors and owner decisions - Context

**Gathered:** 2026-10-25
**Status:** Ready for planning

<domain>
## Phase Boundary

The owner can see how many recent relevant jobs reach the tracker each day and what Groq can really evaluate, and the evaluation and alert paths stay inside the Groq budget, the 25-minute run timeout and the delivery contract before any later phase adds load. Requirements: MEAS-01..05, GOV-01.

In scope: the Dashboard yield view (and the reconciliation that makes it trustworthy), Groq limit measurement, the per-run token record, the daily token budget, the run deadlines, the two alert-recording bugs (CONCERNS #1, #2), and recording or listing the owner decisions.

Not in scope: the 72 h tracker window, backfill, storage migration, board growth, new adapters, any change to the Groq score, prompt or `Min_Alert_Score` (AGENTS rule 7).

Decision IDs below are local to this phase (`P2-xx`) so they do not collide with the project log (`DECISIONS.md` D-01..D-47). Behaviour changes that come from them get real D-numbers in `DECISIONS.md` in the same change (AGENTS rule 1).

</domain>

<decisions>
## Implementation Decisions

### Groq token budget (MEAS-03)
- **P2-01:** The daily budget is a new **Settings tab** row, `Groq_Daily_Token_Budget`, next to `Max_Active_Boards` and `Min_Alert_Score`, so the owner can change it without a deploy (e.g. after a plan change). Settings-row description must say what it limits and where the figure came from.
- **P2-02:** The default is **85% of the measured daily token limit** per model (MEAS-02 supplies the real figure; until it is measured, use the reported 200K/day as a provisional value and say so). The headroom covers estimation drift and manual `--url` / `--delivery-test` calls on the same key.
- **P2-03:** **Separate budget per model.** Groq counts each model's tokens separately. When the primary model (`gpt-oss-120b`)'s budget is spent, score with the fallback (`gpt-oss-20b`) until its own budget is spent; then stop evaluating for the day. The owner accepted this as the D-16 OK for budget-driven fallback use. Each evaluation records which model scored it, and the Dashboard can show the split. The scoring rule, prompt and threshold do not change (rule 7). — **Reversibility:** reversible — a Settings / code switch back to "primary only".
- **P2-04:** **Reserve for verified-fresh.** The last part of each model's daily budget (about 20%; the planner may set the exact figure, as a constant or Settings row) can be spent only on `verified_fresh` jobs, so search-found or Recent jobs cannot use up the budget before a later fresh alert candidate arrives. This becomes more important when Phase 4 adds backfill.
- Tokens are counted from Groq's `usage.total_tokens` (already read in `GroqClient.evaluate`) and recorded per run (a new `Runs` column) and per day, so the budget survives across runs. A job skipped by the budget stays pending and records nothing; this is not a failure, so it uses up no attempts (rule 4).

### Run deadlines and order (MEAS-04)
- **P2-05:** **Staged cutoffs:** no new board poll starts after about **15 min** elapsed, and no new Groq call after about **20 min**, leaving about 5 min for state writes, alerts and the dashboard refresh within the 25-minute workflow timeout. Both cutoffs are configurable (the planner chooses Settings or constants), so they can be tuned from real `Runs` phase times.
- **P2-06:** **Polling order is longest-unpolled first**, so a board skipped by the cutoff goes first next run and no board falls behind for long. This protects the hourly freshness guarantee.
- **P2-07:** **Outcome is split by stage:** a polling cut makes the run `degraded` (via `pipeline.degraded_reason`; shows under Needs attention, because boards went unchecked); an evaluation cut or a spent budget leaves the run `ok`, with a note and a counter (jobs simply wait for the next run).
- **P2-08:** **`MAX_JOBS_PER_RUN` (30) stays** as a safety backstop; the budget and the deadline do the real limiting.
- Verified-fresh first within a run is already `ledger.priority`; keep it. Alerts (stage 4) still run after the evaluation cutoff.

### Dashboard yield view (MEAS-01)
- **P2-09:** A tracker row counts toward the **day it was found** (`Date_Found`) in the **Settings `Timezone`**, matching the 20-30-a-day target and what the owner sees each morning. Publication time is shown as age, not used to bucket days.
- **P2-10:** **Age-when-found buckets:** `≤1h · 1-12h · 12-24h · 24-72h · older · unknown`. `unknown` (no time-precise publication time) is shown but never counted as fresh (rule 2).
- **P2-11:** **Cohorts:** each day's bar is split into verified-fresh / Recent / other, and the `My_Feedback` mix (Would apply / Maybe / Irrelevant / unlabelled) is shown for each cohort.
- **P2-12:** **Placement:** a "Tracker rows per day" chart takes the **top chart slot**, with the **20-30 target shown as a band**. The current "Relevant jobs per day" chart moves to a smaller slot or into the hidden data block (planner's call within the deliberately sparse page). A tracker-vs-ledger kept-job mismatch appears under **Needs attention only when it isn't 0**.
- First explain the 2 ledger-kept jobs missing from the tracker (STATUS.md reconciliation flag, 2026-10-25) before relying on the row count. Check in the real Sheet (success criterion 1).

### Alert recording (MEAS-05), as the success criteria define it
- `alerted` is recorded only when a channel accepted the message (`send_alert` returned `True`). A send failure with no HTTP response is retried and stops after `ledger.MAX_ATTEMPTS` (5). The details are Claude's discretion (below).
- **P2-18:** **Network errors are bounded too** (owner, during plan-phase, 2026-10-26). Every alert send that fails without an HTTP response, including `requests.ConnectionError` and `requests.Timeout` as well as malformed-row or code errors, records a failure event, uses one attempt, and is abandoned after `ledger.MAX_ATTEMPTS` (5). This deliberately amends SPEC.md L93 ("Sheets/Telegram errors" listed as transient) for the alert stage; SPEC.md and DECISIONS.md are updated in the same change (AGENTS rule 1). Accepted risk: a Telegram outage lasting 5 runs abandons those alerts.

### Owner decisions (GOV-01)
- **P2-13:** **Groq plan: measure first, then decide.** Phase 2 reads the account limits page (owner action, or with credentials) and measures real tokens per scoring call. The owner then picks free or paid before the phase closes, and the choice is recorded in `DECISIONS.md` with its source. Until then the 20-30 target is conditional (about 7-20 kept rows a day), and STATUS.md says so.
- **P2-14:** **SmartRecruiters: park it** (back to D-19 / D-27; the D-38 unpark ended with the pilot). Reasons: robots.txt, board existence can't be verified, and the unverified Alphabe Insight Inc rows. Record in `DECISIONS.md`, and make sure the deployed configuration (e.g. `ALLOW_SMARTRECRUITERS_BULK`) matches. — **Reversibility:** costly — parking rewrites monitored rows' status, reverting does not restore them to `active` (STATUS.md migration note), so unparking needs re-validation and a re-entry baseline.
- **P2-15:** **Repository stays public.** Fix `DEPLOY.md` (and any doc that says private) to match, and keep logs free of job content and secrets. Resolves the INGEST-CONFLICTS visibility warning.
- **P2-16:** **Date-only alerts:** already decided by the owner on 2026-10-25 (ADPT-07: tracker if within 72 h, labelled "date only"; alert only through the existing D-04c rule). Phase 2 just records it in `DECISIONS.md`; it takes effect before the first Oracle row (Phase 6).
- **P2-17:** **D-05 amendment (backfill): decide at Phase 4.** List it in `DECISIONS.md` with needed-by Phase 4 and the default "no backfill", so the owner decides with the Phase 2 token figures in hand.
- The remaining GOV-01 items are listed with their needed-by phase and default (ROADMAP "Owner Decisions" table): rule-7 lift for board-cycling scores only (before CYC-02, Phase 5; default: score stays in shadow), per-ATS policy (Paycom skipped, iCIMS deferred, Teamtailor / Personio / JOIN / SuccessFactors skipped; terms for each adapter before Phase 6 / 7; default: build only providers with a recorded decision), and the storage design approval that closes the D-03 200k review (before Phase 3 executes; default: proceed with D-43, delete nothing before parity).

### Claude's Discretion
- MEAS-05 mechanics: whether "no channel configured" writes a failure event (and so uses attempts) or a distinct non-attempt note; how exceptions are classified (network vs malformed); the Telegram 4096-character truncation fix (CONCERNS #3, cut before HTML is built), which is in the same function and may be folded in if small.
- Exact reserve share, cutoff values and whether they live in Settings or constants, within the ranges above.
- Day boundary for the token budget (rolling 24 h or calendar day), chosen to match how Groq actually resets once measured.
- Column names for the new `Runs` fields (tokens per model, budget-skipped count, cutoff flags).
- How the Groq limits are captured (account page read by the owner versus `x-ratelimit-*` response headers from real calls); record the source either way.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Contract and decisions
- `AGENTS.md` — rules 1-8 (flag conflicts, freshness, seen/evaluated/alerted, mocked vs live, secrets, no tuning, offline tests)
- `SPEC.md` — "Delivery" (delivered alert = channel accepted, ~L135), "Failures" (5-attempt bound), dashboard/pilot-report definitions (~L150)
- `DECISIONS.md` — D-04 (freshness classes, D-04c day-precision rule), D-05 (baseline), D-16 (Groq models), D-19/D-27/D-38 (SmartRecruiters), D-40 (dashboard), D-43 (storage), D-45..D-47 (latest)
- `STATUS.md` — 2026-10-25 daily check (reconciliation flag: 2 ledger-kept jobs missing from tracker; feedback mix; Groq ~40 calls/day, 0 429s; run max 770 s)
- `DEPLOY.md` — repository visibility text to correct (P2-15)

### Planning
- `.planning/ROADMAP.md` — Phase 2 details, success criteria, "Owner Decisions (GOV-01)" table, sequencing rules
- `.planning/REQUIREMENTS.md` — MEAS-01..05, GOV-01, ADPT-07 (date-only rule)
- `.planning/INGEST-CONFLICTS.md` — open warnings, incl. repository visibility
- `.planning/research/SUMMARY.md` — Groq throughput estimates, the `eval_budget.py` / `eval_deadline_s` suggestion, owner decision list
- `.planning/research/PITFALLS.md` — Groq tier ambiguity, cached prompt tokens
- `.planning/codebase/CONCERNS.md` — bugs #1 (alerted without channel), #2 (no-response exceptions never bounded), #3 (Telegram truncation)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `hunter.GroqClient` (`hunter.py` ~L860): already reads `usage.total_tokens`, keeps a per-model `TokenBudget` (per-minute only), learns the TPM limit from `x-ratelimit-limit-tokens`, and has 429 → fallback switching. The daily budget and the model choice once a budget is spent hook in here.
- `meter.METER` and `RunRecord` (`groq_calls`, `groq_429` already flow into `Runs`): add token counters the same way.
- `ledger.priority` (verified-fresh first, newest first) and `ledger.needs_evaluation`: reuse for the budget reserve.
- `ledger.failure_events` / `MAX_ATTEMPTS = 5`: the bounded-attempt mechanism MEAS-05 should use.
- `reporting.py` (pure summary) + `dashboard.py` (`render`, `Chart`, hidden data block, `section("NEEDS ATTENTION")`): the yield view goes here. `reporting.reconcile` (~L832, used by the pilot report) is the reconciliation to reuse.
- Settings rows are declared in `hunter.py` (~L160-200) with descriptions and parsed in `Settings` (~L257).

### Established Patterns
- Transient failures record nothing and use up no attempts (`pipeline.py` ~L562); budget and deadline skips should behave the same.
- `pipeline.degraded_reason(run)` decides `degraded` vs `ok`.
- Dashboard is read-only toward operational state, one-batch publish, deliberately sparse; dashboard windows are calendar days in the display time zone.
- Tests are offline with fakes; mutation spot-checks on new behaviour are the norm (see STATUS.md entries).

### Integration Points
- `pipeline.run_cycle` stage 2 (polling loop, ~L300): poll order and poll cutoff.
- `pipeline.run_cycle` stage 3 (evaluate, ~L545): budget/deadline check before each `d.evaluate`.
- `pipeline.run_cycle` stage 4 (alert, ~L578-600): the MEAS-05 fixes (`sent` handling, exception classification).
- `hunter.send_alert` (~L1427): return value semantics, truncation.
- `Runs` tab columns (`SheetStore`) for the new token, budget and cutoff fields; `--pilot-report` limits audit.

</code_context>

<specifics>
## Specific Ideas

- Early cohort evidence to show the owner: Irrelevant labels sit mostly on verified-fresh rows (17 of 44) and almost none on Recent rows (1 of 24). The per-cohort feedback mix should make this visible.
- The 20-30-a-day target is drawn as a band on the top chart, not a single line.
- Every measured Groq figure is written down with its source (account page, response headers, or measured usage), and nothing is called live without credentials (rule 5).
- A deployment that changes a measurement gets a `PILOT_LOG.md` entry.

</specifics>

<deferred>
## Deferred Ideas

- D-05 amendment / backfill: decided at Phase 4 (P2-17).
- Rule-7 lift for board-cycling scores: Phase 5, before CYC-02.
- Per-ATS adapter policy terms: Phase 6 / 7 starts.
- 20b pre-screen or prompt cuts to save tokens: scorer changes (rule 7), need their own owner decision; not in this phase.
- Formal read of the first weekly rebalance (~2026-10-29): EVID-01, Phase 5; Phase 2 only watches it in the daily checks.

</deferred>

---

*Phase: 02-measurement-governors-and-owner-decisions*
*Context gathered: 2026-10-25*
