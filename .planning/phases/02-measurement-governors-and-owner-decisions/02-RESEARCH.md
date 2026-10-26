# Phase 2: Measurement, governors and owner decisions - Research

**Researched:** 2026-10-26
**Domain:** Brownfield Python pipeline (GitHub Actions + Google Sheets state + Groq scoring + Telegram): run governors (token budget, deadlines), alert-recording fixes, a pure-reporting Dashboard yield view, and owner-decision records. No new libraries.
**Confidence:** HIGH on code seams and live read-only figures; MEDIUM on Groq limits (the account page has not been read; docs give a base table only); LOW on Groq daily-reset semantics and on combo-chart rendering until observed.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Groq token budget (MEAS-03)**
- **P2-01:** The daily budget is a new **Settings tab** row, `Groq_Daily_Token_Budget`, next to `Max_Active_Boards` and `Min_Alert_Score`, so the owner can change it without a deploy (e.g. after a plan change). Settings-row description must say what it limits and where the figure came from.
- **P2-02:** The default is **85% of the measured daily token limit** per model (MEAS-02 supplies the real figure; until it is measured, use the reported 200K/day as a provisional value and say so). The headroom covers estimation drift and manual `--url` / `--delivery-test` calls on the same key.
- **P2-03:** **Separate budget per model.** Groq counts each model's tokens separately. When the primary model (`gpt-oss-120b`)'s budget is spent, score with the fallback (`gpt-oss-20b`) until its own budget is spent; then stop evaluating for the day. The owner accepted this as the D-16 OK for budget-driven fallback use. Each evaluation records which model scored it, and the Dashboard can show the split. The scoring rule, prompt and threshold do not change (rule 7). — **Reversibility:** reversible — a Settings / code switch back to "primary only".
- **P2-04:** **Reserve for verified-fresh.** The last part of each model's daily budget (about 20%; the planner may set the exact figure, as a constant or Settings row) can be spent only on `verified_fresh` jobs, so search-found or Recent jobs cannot use up the budget before a later fresh alert candidate arrives. This becomes more important when Phase 4 adds backfill.
- Tokens are counted from Groq's `usage.total_tokens` (already read in `GroqClient.evaluate`) and recorded per run (a new `Runs` column) and per day, so the budget survives across runs. A job skipped by the budget stays pending and records nothing; this is not a failure, so it uses up no attempts (rule 4).

**Run deadlines and order (MEAS-04)**
- **P2-05:** **Staged cutoffs:** no new board poll starts after about **15 min** elapsed, and no new Groq call after about **20 min**, leaving about 5 min for state writes, alerts and the dashboard refresh within the 25-minute workflow timeout. Both cutoffs are configurable (the planner chooses Settings or constants), so they can be tuned from real `Runs` phase times.
- **P2-06:** **Polling order is longest-unpolled first**, so a board skipped by the cutoff goes first next run and no board falls behind for long. This protects the hourly freshness guarantee.
- **P2-07:** **Outcome is split by stage:** a polling cut makes the run `degraded` (via `pipeline.degraded_reason`; shows under Needs attention, because boards went unchecked); an evaluation cut or a spent budget leaves the run `ok`, with a note and a counter (jobs simply wait for the next run).
- **P2-08:** **`MAX_JOBS_PER_RUN` (30) stays** as a safety backstop; the budget and the deadline do the real limiting.
- Verified-fresh first within a run is already `ledger.priority`; keep it. Alerts (stage 4) still run after the evaluation cutoff.

**Dashboard yield view (MEAS-01)**
- **P2-09:** A tracker row counts toward the **day it was found** (`Date_Found`) in the **Settings `Timezone`**, matching the 20-30-a-day target and what the owner sees each morning. Publication time is shown as age, not used to bucket days.
- **P2-10:** **Age-when-found buckets:** `<=1h · 1-12h · 12-24h · 24-72h · older · unknown`. `unknown` (no time-precise publication time) is shown but never counted as fresh (rule 2).
- **P2-11:** **Cohorts:** each day's bar is split into verified-fresh / Recent / other, and the `My_Feedback` mix (Would apply / Maybe / Irrelevant / unlabelled) is shown for each cohort.
- **P2-12:** **Placement:** a "Tracker rows per day" chart takes the **top chart slot**, with the **20-30 target shown as a band**. The current "Relevant jobs per day" chart moves to a smaller slot or into the hidden data block (planner's call within the deliberately sparse page). A tracker-vs-ledger kept-job mismatch appears under **Needs attention only when it isn't 0**.
- First explain the 2 ledger-kept jobs missing from the tracker (STATUS.md reconciliation flag, 2026-10-25) before relying on the row count. Check in the real Sheet (success criterion 1).

**Alert recording (MEAS-05), as the success criteria define it**
- `alerted` is recorded only when a channel accepted the message (`send_alert` returned `True`). A send failure with no HTTP response is retried and stops after `ledger.MAX_ATTEMPTS` (5). The details are Claude's discretion (below).

**Owner decisions (GOV-01)**
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

### Deferred Ideas (OUT OF SCOPE)
- D-05 amendment / backfill: decided at Phase 4 (P2-17).
- Rule-7 lift for board-cycling scores: Phase 5, before CYC-02.
- Per-ATS adapter policy terms: Phase 6 / 7 starts.
- 20b pre-screen or prompt cuts to save tokens: scorer changes (rule 7), need their own owner decision; not in this phase.
- Formal read of the first weekly rebalance (~2026-10-29): EVID-01, Phase 5; Phase 2 only watches it in the daily checks.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MEAS-01 | Dashboard shows tracker rows per day, age when found, My_Feedback mix; backfilled/recent rows apart from verified-fresh | New pure `reporting._yield` joined to ledger facts; cohort from the tracker `Freshness` label (existing precedent `pilot.py:191-212`); the 2 missing rows have a hypothesis list and a diagnostic (Pitfall 1, Pattern 5) |
| MEAS-02 | Real Groq limits and tokens per call measured; plan decision recorded | Official docs facts (below), header and `usage` capture into `Runs`, owner reads the console limits page (human-action checkpoint), arithmetic template for evaluations/day and rows/day |
| MEAS-03 | Each run records Groq tokens; a daily token budget keeps runs under the limit | New pure `eval_budget.py` modelled on `search.SearchBudget`, persisted in the `Discovery` tab, per-model, reserve for verified-fresh, hooked into `GroqClient` and `run_cycle` stage 3 |
| MEAS-04 | Evaluation and polling stop before the 25-minute timeout; verified-fresh first; unscored stay retryable | Deadline cutoffs anchored at process start (not `run_cycle` start), cutoff inside `boards.poll_boards`, per-call deadline inside `GroqClient`, longest-unpolled-first order |
| MEAS-05 | `alerted` only when a channel accepted; no-HTTP-response failures bounded at 5 | `pipeline.py` stage 4 rewrite, exception classifier, token redaction, SPEC L93 change flagged (Open Question 1) |
| GOV-01 | Owner decisions recorded or listed with needed-by phase and default | Decision inventory table, D-number numbering note, doc-conflict list (DEPLOY, README, D-37, SPEC) |
</phase_requirements>

## Summary

Phase 2 is a governor-and-measurement phase on a codebase whose seams are clean and well tested (525 offline tests pass in about 5 s, [VERIFIED: `.venv/bin/python -m unittest discover -s tests` → "Ran 525 tests in 5.180s / OK"]). No new packages are needed. The work splits into five independent slices: (a) MEAS-05 alert recording in `pipeline.py` stage 4 and `hunter.send_alert`; (b) the governors (new `eval_budget.py`, token capture in `GroqClient`, run deadlines, poll order, new `Runs` columns); (c) the MEAS-01 yield view in `reporting.py` and `dashboard.py`; (d) measurement of the real Groq limits (needs one owner action) and the plan decision; (e) the GOV-01 documentation records.

Four findings change the plan versus a naive reading of CONTEXT. (1) `boards.poll_boards` is a blocking `list(pool.map(...))`, so the 15-minute poll cutoff must live inside `poll_boards`, not in the pipeline loop that consumes its results. (2) The workflow timeout of 25 minutes covers the whole job, including a state-lease wait of up to 600 s (`STATE_LEASE_WAIT_SECONDS: "600"`) that happens before `run_cycle` starts, so the cutoffs must be anchored at process start, and a single Groq call (up to 6 attempts with 60 s sleeps and an unbounded TPM wait loop) can outlive a cutoff unless the client also gets a deadline. (3) The "2 ledger-kept jobs missing" is at most partly explained by an unparseable URL: the live pilot report shows 88 real rows, 87 distinct parseable jobs and only 1 row without a recognizable job URL, so at least one missing job is genuinely absent from the tracker (hand deletion is the likeliest cause); a permanent mismatch under Needs attention would then be noise (Open Question 2). (4) MEAS-05's wording ("a send that fails without an HTTP response ... stops after 5 attempts") conflicts with SPEC L93, which lists "Sheets/Telegram errors" as transient and retried without bound, and with AGENTS rule 4; that is a rule-1 conflict to flag before implementing (Open Question 1). A fifth, security finding: `str(exc)` of a `requests` transport error contains the Telegram URL (bot token), and the new MEAS-05 path would newly write it into the ledger and the Dashboard.

The honest volume story: Groq is not the binding limit today. The pilot report shows 281 Groq calls in 7 days (about 40 a day), 0 HTTP 429, against a documented base of 200K tokens a day per model (about 44-57 calls at 3.5-4.5k tokens). Supply (title gate, no backfill) limits tracker rows to about 7 a day now; the budget governor exists so Phases 4-6 cannot add load past the limit. The 20-30 target needs about 111-167 Groq calls a day at the pilot's 18% keep rate, which exceeds even two free models at 85% (about 85 calls); that is the arithmetic the Groq plan decision rests on.

**Primary recommendation:** Build `eval_budget.py` (pure, per-model, UTC-day, persisted under a `Discovery` key like `search_budget`), plumb process-start deadlines into `poll_boards` and `GroqClient`, add `Runs` columns at the END of `RUN_COLUMNS`/`RunRecord`, fix stage 4 with an explicit exception classifier plus token redaction, build the yield view from the tracker joined to the ledger by identity key (stored-URL fallback), and write the GOV-01 records in one new `DECISIONS.md` entry; deploy in the order alert fix, governors, dashboard, and make the SmartRecruiters parking deployment a separate PILOT_LOG entry after the 2026-10-29 rebalance read.

## Architectural Responsibility Map

This is a single-process batch system, so "tiers" are the project's own layers.

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Daily Groq token ledger and reserve rule | Pure module (`eval_budget.py`) | `pipeline.py` loads/saves, `hunter.GroqClient` charges | Pure arithmetic, testable with no network; persistence follows the `search.SearchBudget` pattern (`Discovery` tab key) |
| Model choice and 429/daily-limit handling | `hunter.GroqClient` | `eval_budget` | The client already owns model switching (`_model`, `unavailable`, fallback hold) |
| Poll cutoff and poll order | `boards.poll_boards` (executes) | `pipeline.run_cycle` (sets deadline, sorts) | `poll_boards` materialises all results at once; only it can stop starting polls |
| Evaluation cutoff and `can_score` check | `pipeline.run_cycle` stage 3 | `GroqClient` per-call deadline | Loop-level check prevents starting; client deadline bounds an in-flight call |
| Alert recording and attempt bound | `pipeline.run_cycle` stage 4 | `ledger.failure_events` | Existing bounded-attempt mechanism; the classifier is new |
| Tokens/limits/cut counters per run | `state.RunRecord` / `Runs` tab | `meter.METER` | Same flow as `groq_calls` / `groq_429` |
| Yield view numbers | `reporting.py` (pure) | `dashboard.py` renders | AGENTS layout: reporting is pure, dashboard is read-only toward operational state |
| Tracker row presence, day, feedback | Job Tracker tab (read via `store.tracker_rows`) | Ledger join for age | Display strings are user-formatted; use the ledger for instants |
| Owner decisions | `DECISIONS.md` (+ SPEC, DEPLOY, README, STATUS) | `ROADMAP.md` table | Documents are the contract (AGENTS rule 1) |
| Measured Groq figures | `STATUS.md` + `PILOT_LOG.md` | `Runs` rows as the source | Rule 5: state which figures are live vs mocked |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib (`dataclasses`, `json`, `time`, `unittest`) | 3.12.13 [VERIFIED: `.venv/bin/python --version`] | Budget module, deadlines, tests | The project already uses nothing else for these |
| `requests` (existing) | pinned by `requirements.txt` | Groq/Telegram HTTP, exception types for the classifier | Already the HTTP layer; `requests.ConnectionError` / `requests.Timeout` are the transport classes |
| `gspread` (existing) | existing | Sheets store | Unchanged |

### Supporting
None. No package is added in this phase.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Budget in the `Discovery` tab (key-value JSON) | Sum new token columns from `Runs` | `Runs` undercounts when a run is killed (its record stays `started` with no tokens) and costs a full `Runs` read; the `Discovery` key is written at every flush and survives a crash, and mirrors `search_budget` |
| Budget enforced in `GroqClient` only | Pipeline-level `can_score` pre-check as well | Client-only means each pending job is still hydrated (an ATS request) before being skipped; the pre-check avoids that |
| Parsing the tracker's `Date_Found` text | Ledger `evaluated` time (same instant, same display zone) | Tracker cells are user-formatted display strings (see Pitfall 5); the ledger holds exact UTC |

**Installation:** none.

**Version verification:** not applicable (no new packages).

## Package Legitimacy Audit

No external packages are installed by this phase, so the audit is empty.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| (none) | - | - | - | - | - | - |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
process start (hunter.main)  ──► PROCESS_T0 = monotonic()   (deadlines anchor here, NOT at run_cycle start)
      │   (lease wait up to 600 s happens before run_cycle)
      ▼
run_cycle
  load Boards / Events / Runs / Discovery ─► GroqBudget.restore(discovery["groq_budget"], now)   [UTC day rollover]
  │
  ├─ stage 1 discovery (unchanged)
  │
  ├─ stage 2 poll:  active boards sorted by last_attempt_at asc (blank first)
  │        poll_boards(active, deadline=PROCESS_T0+15min)
  │            └─ one(): if clock() > deadline → PollResult(skipped_deadline=True)   (never reuses the 429 `skipped`)
  │        skipped_deadline > 0 → run.boards_skipped_deadline, note, outcome degraded
  │
  ├─ stage 3 evaluate: todo = sorted(needs_evaluation, key=lg.priority) [:max_jobs]
  │        for st in todo:
  │           now > PROCESS_T0+20min          → run.eval_cut=yes, break           (outcome stays ok)
  │           not d.can_score(st)             → run.eval_budget_skipped += 1, continue (no event, no attempt)
  │           out = d.evaluate(ident, st)  ── hydrate ─► gates ─► GroqClient.evaluate(fresh=?)
  │                  GroqClient: pick model by budget (primary, then fallback) → HTTP → read usage + x-ratelimit-*
  │                              charge(model, total_tokens); daily-limit 429 → mark model spent, no backoff loop
  │                              per-call deadline (also bounds TokenBudget.wait)
  │           out.kind: done | transient | failed | deferred(new: budget/deadline; no event, no attempt)
  │        every FLUSH_EVERY and in finally: write() + save groq_budget to Discovery
  │
  ├─ stage 4 alert: for st needing alert (runs after the eval cutoff)
  │        sent=True          → ALERTED(channel) , st.alerted = True
  │        sent=False         → NOT alerted; note "no alert channel"; alerts_failed++ ; no attempt
  │        HTTPError 4xx(≠429)→ failure_events (bounded 5)                      [unchanged]
  │        HTTPError 5xx/429  → retry, no attempt                                [unchanged]
  │        transport error    → retry, no attempt  (Open Question 1)
  │        any other exception→ failure_events (bounded 5), message REDACTED
  │
  └─ finally: Runs row gets tokens per model, prompt/cached tokens, limits JSON, cut + skipped counters

reporting.build_summary(tracker rows, ledger facts) ─► _yield (per-day cohorts, age buckets, feedback per cohort, reconcile)
dashboard.render: top chart "Tracker rows per day" + 20-30 band; Needs attention row when mismatch != 0
```

### Recommended Project Structure
```
eval_budget.py       # NEW pure: GroqBudget (restore/to_json/can_spend/charge/exhaust/pick_model)
boards.py            # poll_boards(deadline=...), PollResult.skipped_deadline
pipeline.py          # Deps additions, stage 2 sort+deadline, stage 3 checks, stage 4 classifier, Runs fields
state.py             # RunRecord + RUN_COLUMNS: new fields appended at the END only
hunter.py            # Settings rows + parse, GroqClient tokens/limits/deadline/model, send_alert truncation, wiring in main
reporting.py         # _yield(), reconcile() extension (names the missing keys), Groq usage in summary
dashboard.py         # top chart, band series, Needs attention mismatch row, hidden data block widening
pilot.py             # limits audit: Groq tokens/day, cached share, cuts
tests/test_governors.py   # NEW (budget, deadline, forced-limit, classifier)
DECISIONS.md / SPEC.md / DEPLOY.md / README.md / STATUS.md / PILOT_LOG.md   # same-change doc updates
```

### Recommended plan slices and order
1. **Slice A, MEAS-05 + redaction** (small, independent; `pipeline.py` stage 4, `hunter.send_alert`, SPEC L93 and "Delivery"). Deploy first.
2. **Slice B, governors** (`eval_budget.py`, `GroqClient`, `poll_boards`, stages 2-3, `RunRecord`, Settings rows). Depends on nothing in A but edits the same `run_cycle`; run after A to avoid merge churn. PILOT_LOG entry on deploy.
3. **Slice C, MEAS-01 yield view** (pure reporting then dashboard). Can be built in parallel with B; the Groq-token card needs B's `Runs` fields (add after B).
4. **Slice D, measurement and decisions** (needs B deployed for at least 1-2 UTC days, plus the owner reading the Groq console limits page): STATUS figures, Groq plan decision.
5. **Slice E, GOV-01 records and SmartRecruiters parking.** Record now; deploy the workflow edit (remove `ALLOW_SMARTRECRUITERS_BULK` at `job_hunter.yml:74` and `inventory.yml:76`) as its own PILOT_LOG entry **after the first weekly rebalance (about 2026-10-29 01:00 UTC) has been read**, because parking rewrites monitored rows and frees slots and would otherwise contaminate the first evidence about the D-30 choices (Open Question 5).

### Pattern 1: Budget object modelled on `SearchBudget`
**What:** A pure dataclass loaded from a JSON string, with day rollover, per-model counters, a verified-fresh reserve, and `to_json`. Precedent: `search.py:214-258` (`load` rolls over when `data.get("month") != month`; stored under `BUDGET_KEY = "search_budget"`, `search.py:39`).
**When to use:** all token accounting. `run_cycle` calls `restore(...)` at start and saves with the Discovery state at each flush and in `finally`; `GroqClient` holds the same object and calls `charge`.
**Example (design sketch, not existing code):**
```python
# eval_budget.py (sketch)
@dataclass
class GroqBudget:
    day: str                      # UTC "YYYY-MM-DD" (Open Question 6)
    budgets: dict[str, int]       # model -> daily token budget (Settings; default 85% of the limit)
    reserve_pct: int = 20         # last share of each model's budget only verified_fresh may spend
    used: dict[str, int] = field(default_factory=dict)
    exhausted: set[str] = field(default_factory=set)   # a real daily-limit 429 was seen: spent for the day

    def can_spend(self, model: str, *, fresh: bool) -> bool:
        if model in self.exhausted: return False
        cap = self.budgets[model] * (100 if fresh else 100 - self.reserve_pct) // 100
        return self.used.get(model, 0) < cap

    def pick_model(self, order: list[str], *, fresh: bool, unavailable: set[str]) -> str | None:
        return next((m for m in order if m not in unavailable and self.can_spend(m, fresh=fresh)), None)
```
Check `used < cap` before the call (not `used + estimate <= cap`): the 15% headroom (P2-02) absorbs the one-call overshoot of roughly 4-6k tokens.

### Pattern 2: Cutoff inside `poll_boards`
`poll_boards` ends in `with ThreadPoolExecutor(...) as pool: return list(pool.map(one, boards))` (`boards.py:650-651`), and the pipeline consumes the finished list (`pipeline.py:333`). Add `deadline: float | None` and use the existing injectable `clock` parameter (`boards.py:623`): inside `one()`, if `deadline is not None and clock() > deadline`, return `PollResult(rec, skipped_deadline=True, error="poll deadline")`. Add a NEW field on `PollResult`; do not reuse `skipped` (`boards.py:615`), because the pipeline treats `skipped` as "provider backoff after HTTP 429" (`pipeline.py:339-341`) and `degraded_reason` and `reporting._BACKOFF_RE` key on that note text. A deadline-skipped board must not call `apply_poll_result` (same as the 429 skip), so its `last_attempt_at` stays old and it sorts first next run. `pool.map` preserves submission order, so a pre-sorted list means the longest-unpolled boards start first.

### Pattern 3: Deadline into the Groq client
`GroqClient.evaluate` can run for minutes: `GROQ_ATTEMPTS = 6` (`hunter.py:732`), 429 sleeps up to 60 s, 5xx sleeps up to 30 s, `timeout=60` per request, and `TokenBudget.wait` is `while True` (`hunter.py:842-847`). Give the client an absolute monotonic `deadline` (set from `PROCESS_T0` by `main` before `run_cycle`, or via a `Deps` callback) and make `wait`, the retry loop and the sleeps stop at it by raising `TransientError` (which the evaluator already maps to `transient` with no attempt used, `hunter.py:1545-1546`). Without this, a call started at minute 19:59 can run past the workflow timeout.

### Pattern 4: New `Runs` fields go at the END
`RunRecord.to_row` iterates `fields(self)` (`state.py:145-150`) and `from_row` is positional (`state.py:164-169`), so new fields must be appended after `code_version` in both the dataclass and `RUN_COLUMNS`, and `from_row` extended by index. Tests that guard this: `tests/test_pools.py:904-911` (`from_row(full.to_row()) == full`), `tests/test_discovery.py:652-656`, `tests/test_pilot.py:297-300`. `_widen_header` only rewrites the header when it is a strict prefix of the new column list (`state.py:286`), which holds for an append. Verbatim current tail: `"Eval_Attempted", "Eval_Transient", "Eval_Failed", "Code_Version",` [VERIFIED: state.py:56]; the Runs tab currently has 66 columns [VERIFIED: `len(state.RUN_COLUMNS)` = 66 = number of `RunRecord` fields].

Suggested names (discretion): `Groq_Tokens_Primary`, `Groq_Tokens_Fallback`, `Groq_Prompt_Tokens`, `Groq_Cached_Tokens`, `Groq_Limits` (JSON: last seen `x-ratelimit-limit-requests`, `remaining-requests`, `reset-requests`, `limit-tokens` per model), `Eval_Budget_Skipped`, `Eval_Deadline_Skipped`, `Eval_Cut`, `Boards_Skipped_Deadline`. "Primary/Fallback" names stay valid if the model env vars change; the model id goes in the evaluated payload (`model` key), which `JobRow.from_payload` ignores safely (`hunter.py:1039-1044`).

### Pattern 5: MEAS-01 from tracker rows joined to the ledger
- Row presence, `My_Feedback`, and the cohort label come from the tracker (`store.tracker_rows()`, `hunter.py:1336-1342`; the cohort label precedent is `pilot.py:191-212`, `by_freshness_label`).
- Day, and age-when-found, come from the ledger via identity key: `parse_job_url(Apply_URL).key` first, then an exact-string match on the stored `evaluated` payload `url` as a fallback (diagnostic only, never identity or dedupe; AGENTS rule 3). Day = local day (display zone) of the `evaluated` event; age-when-found = `seen_at - published` when `precision == time`, else `unknown` (P2-10). `reporting.JobFacts` already holds `seen_at`, `published`, `precision`, `eval_at`, `freshness`, `eval_visible` (`reporting.py:117-140`).
- Reconcile counts both directions (ledger-kept not in tracker; tracker rows with no ledger match) and the new Needs-attention row reads those numbers. Extend `reconcile` to return the missing keys with their evaluated time and stored URL, so the owner can find them in the Sheet.

### Pattern 6: Band on the chart
`dashboard.Chart` and `chart_request` support only `line | column | stacked_column | bar | donut` (`dashboard.py:50-58`, `399-432`). A band needs a `COMBO` chart with per-series `type`. [CITED: developers.google.com/sheets/api/reference/rest/v4/spreadsheets/charts: `BasicChartSeries.type` is "Valid only if the chartType is COMBO", "Only LINE, AREA, and COLUMN are supported"; `stackedType` "Applies to Area, Bar, Column, Combo, and Stepped Area charts"]. Whether a stacked COMBO also stacks its LINE series is not stated, so render it in the real Sheet before relying on it (the project already inspects the Dashboard through the signed-in browser, STATUS "Operational dashboard (D-40)"). Fallback: one non-stacked column series (total rows per day) plus two flat LINE series (20 and 30), with the cohort split shown in the THIS WEEK table and the data block.

### Anti-Patterns to Avoid
- **Anchoring cutoffs at `run_cycle`'s `t_start`.** The lease wait precedes it; a poll that waited 10 minutes has about 14 minutes left of the 25. Anchor at process start.
- **Reusing `PollResult.skipped` or the "provider backoff after HTTP 429" note text** for the deadline skip: it would trip `degraded_reason`'s `provider` reason and `reporting._BACKOFF_RE`.
- **Recording anything for a budget-deferred job.** No `error` event, no `st.errors` increment (rule 4; the transient path at `pipeline.py:564-569` is the precedent).
- **Counting a no-channel alert as delivered** (today's `channel: "none"` event at `pipeline.py:598`). Old `channel: none` events exist as a legacy shape; keep `reporting.job_facts` handling them (`reporting.py:209-213`).
- **Parsing `Date_Found` display text as the primary source** (Pitfall 5).
- **Auto-writing new rows into the live Settings tab.** `bootstrap` only creates the tab when absent (`hunter.py:1200-1208`); an existing tab is not widened.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Bounded retry of a failed alert | A new counter | `ledger.failure_events` + `MAX_ATTEMPTS` | Writes `error` then `abandoned` events at attempt 5 (`ledger.py:194-201`); dashboard "alert failing for job" rows already read it |
| Persisted daily counter | A new tab | `Discovery` tab key + `save_discovery_state` | Tiny key-value tab already rewritten in one request (`state.py:445-451`); `CsvState` has the same API |
| Priority order and reserve eligibility | A second sort | `ledger.priority` (`_PRIORITY`, `ledger.py:125`) | `todo` is already sorted verified-fresh first; the reserve only needs `st.freshness == fr.VERIFIED_FRESH` |
| Per-run counters | New globals | `meter.METER.add("groq_...")` and `METER.since` | Same flow as `groq_calls` (`hunter.py:918-924`, `pipeline.py:616-620`) |
| Reconciliation | A new report | `reporting.reconcile` + `format_reconciliation` | Already reports the 2-missing figure, with rehearsal and fixture exclusion |
| Per-cohort feedback | A new parser | The `pilot.py:191-212` logic | Same tracker columns and labels |
| Time in tests | `time.sleep` | Injectable `clock` (`poll_boards(clock=...)`) and `Deps.now`; add one monotonic clock to `Deps` | Offline tests must not wait |

**Key insight:** every piece except the budget arithmetic and the deadline plumbing already exists as a mechanism in this repository; the risk is in wiring (which clock, which record, which note string), not in algorithms.

## Verified in-repo values (quoted verbatim; planner and executor may rely on these)

| Fact | Verbatim | Source |
|------|----------|--------|
| Attempt bound | `MAX_ATTEMPTS = 5` | [VERIFIED: ledger.py:26] |
| Priority map | `_PRIORITY = {fr.VERIFIED_FRESH: 0, fr.OBSERVED_NEW: 1, fr.RECENT: 2, fr.UNCERTAIN: 3}` | [VERIFIED: ledger.py:125] |
| Alertable class | `ALERTABLE = {VERIFIED_FRESH}`; `VERIFIED_FRESH = "verified_fresh"`; `RECENT = "recent"` | [VERIFIED: freshness.py:19-29] |
| Run outcomes | `OUTCOME_STARTED, OUTCOME_OK, OUTCOME_DEGRADED, OUTCOME_FAILED = "started", "ok", "degraded", "failed"` | [VERIFIED: state.py:61] |
| Discovery key precedent | `BUDGET_KEY = "search_budget"` | [VERIFIED: search.py:39] |
| Tracker columns | `"Date_Found", "Date_Posted", "My_Status", "AI_Score", "Company_and_Title", "Location", "AI_Verdict", "Missing_Gaps", "Apply_URL", "User_Notes", "Freshness", "Source", "My_Feedback"` | [VERIFIED: hunter.py:70-84] |
| Cohort labels on tracker rows | `fr.VERIFIED_FRESH: "Verified fresh"`, `fr.OBSERVED_NEW: "New on board (age unverified)"`, `fr.RECENT: "Recent"`, `fr.UNCERTAIN: "Age unverified"` | [VERIFIED: hunter.py:986-991] |
| Date display | `DISPLAY_FORMAT = "%m/%d/%Y %I:%M %p"`; day-precision shown as `%m/%d/%Y` | [VERIFIED: hunter.py:1087, display_time] |
| Tracker visibility threshold | `MIN_TRACKER_SCORE = 50` | [VERIFIED: hunter.py:91] |
| Groq constants | `JD_CHARS = 7000`, `RESUME_CHARS = 7000`, `MAX_OUTPUT_TOKENS = 1000`, `GROQ_ATTEMPTS = 6`, `FALLBACK_HOLD_SECONDS = 90` | [VERIFIED: hunter.py:729-733] |
| Model defaults | `env("GROQ_MODEL", "openai/gpt-oss-120b")`, `env("GROQ_FALLBACK_MODEL", "openai/gpt-oss-20b")`, `groq_tpm=_int_or(env("GROQ_TPM"), 8000)` | [VERIFIED: hunter.py:333-337] |
| Job timeout and lease wait | `timeout-minutes: 25`; `STATE_LEASE_WAIT_SECONDS: "600"`; `ALLOW_SMARTRECRUITERS_BULK: "1"` | [VERIFIED: job_hunter.yml:59, 71, 74] |
| Inventory override | `ALLOW_SMARTRECRUITERS_BULK: "1" # explicit user decision for the pilot (DECISIONS D-38); remove to park SmartRecruiters again`; `timeout-minutes: 40` | [VERIFIED: inventory.yml:76, 42] |
| Loop cap | `FLUSH_EVERY = 10`, `max_jobs: int = 30` | [VERIFIED: pipeline.py:41, 97] |
| Settings row style | `("Min_Alert_Score", "70", "Jobs scoring at or above this (0-100) ...")` and `("Max_Active_Boards", "500", "Most company boards checked every hour. ...")`; values parsed through `pick(key)` which falls back to the upper-cased env var then `SETTING_DEFAULTS` | [VERIFIED: hunter.py:160, 181, 248-249] |

## Live read-only evidence gathered this session (rule 5: nothing here touched Sheets, Groq or Telegram with credentials)

Source: the public log of the 2026-10-25 12:05 UTC `pilot_report` workflow run, read with `gh run view 40191573405 --log` [VERIFIED: gh run log]. Counts only.

| Figure | Value |
|--------|-------|
| Groq calls in the 168 h window | 281, HTTP 429: 0 (about 40 a day) |
| Scored / kept | 281 scored, 55 kept (27 verified fresh, 28 dated but older than the window, 0 no date) |
| Tracker (all time) | 90 rows = 2 labelled test fixtures + 88 real rows (87 distinct jobs, **1 without a recognizable job URL**) |
| Reconciliation | 87 distinct tracker jobs are ledger-kept; **ledger-kept jobs missing from the tracker: 2**; ledger-kept in the window 55, of which 53 are in the tracker |
| Run duration | 207 timed runs, median 124 s, p90 251 s, max 770 s (51.3% of the 1500 s timeout); phases: load 9 s, poll 100 s, evaluate+alert 2 s (medians) |
| Per-run ATS requests | median 1,106, p90 1,372; Sheets reads median 17 per run |
| Feedback by cohort (tracker `Freshness` label) | Verified fresh: Would apply 27, Maybe 0, Irrelevant 17; Recent: Would apply 20, Maybe 3, Irrelevant 1 |

Consequences: (1) the missing pair is in the 7-day window, only one tracker row is unparseable, so at least one missing job is genuinely not a row (or its row's URL maps to a different key); (2) evaluation takes about 2 s a run today, so the 20-minute evaluation cutoff only matters under backfill-sized queues, while the 15-minute poll cutoff (observed polls about 100 s) has a very large margin; (3) token governance is protective, not yet binding.

### Hypotheses for the 2 missing rows (to test with the diagnostic, in order)
1. **Hand deletion by the owner** (the tracker is the owner's sheet; the app only appends). Cannot be seen from the ledger. Likeliest for at least one job given only 1 unparseable row.
2. **URL does not parse to the ledger key** for the 1 unrecognized row: Greenhouse `absolute_url` can point at a customer domain; `parse_job_url` accepts `gh_jid` only on Greenhouse hosts (`boards.py:112-119`), so such a row would not match. The adapter takes `j.get("absolute_url") or ident.url` (`boards.py:236-237`) [VERIFIED: read], so the stored URL can be a non-ATS host. The stored `evaluated` payload `url` fallback in Pattern 5 would match it by exact string.
3. **Rows repaired by hand** after D-44 (rows 38-44) and D-46 (rows 76-79): a repaired row whose URL cell became a hyperlink label would read back as label text.
4. Key mismatch from board-alias casing (an embed URL `for=` token differing in case from the registry board key). Lower probability.
An append failure is NOT a candidate: `write()` appends tracker rows before events (`pipeline.py:179-190`), so a failed append leaves no `evaluated` event.

## Common Pitfalls

### Pitfall 1: "2 missing" is explained wrongly and then alarms forever
**What goes wrong:** If the cause is a hand-deleted row, a mismatch under Needs attention (P2-12) never returns to 0.
**Why:** the ledger is append-only and the tracker is user-owned.
**How to avoid:** first run the diagnostic (list the missing keys, stored URLs and evaluated times); decide with the owner whether deletions are tolerated (Open Question 2).
**Warning signs:** the same 2 keys stay missing across days; no new misses.

### Pitfall 2: Cutoff measured from the wrong zero
**What goes wrong:** run starts after a 10-minute lease wait; "20 minutes" of evaluation then ends at minute 30; the job is killed at 25 and the run record stays `started` ("interrupted").
**Why:** the lease wait (`STATE_LEASE_WAIT_SECONDS: "600"`, `job_hunter.yml:71`) happens before `run_cycle`; GitHub's setup steps (checkout, setup-python, pip install) also precede Python.
**How to avoid:** `PROCESS_T0 = time.monotonic()` at the top of `main`; compute both cutoffs from it; unit-test with a fake clock that starts "late".
**Warning signs:** `Runs.Duration_S` greater than 1,200 with `Outcome=started`.

### Pitfall 3: A Groq call outlives the cutoff
**What goes wrong:** the loop checks the clock before a call but the call retries for minutes.
**How to avoid:** client-side deadline (Pattern 3); stage 4 also gets a hard stop (suggest about 23 minutes of process time) so a Telegram outage with a backlog (each send has a 20 s `HTTP_TIMEOUT`, `hunter.py:127`, and may call two channels) cannot reach the timeout; unsent alerts stay pending with no attempt used.

### Pitfall 4: A real daily-limit 429 burns the run
**What goes wrong:** today a 429 on the fallback model sleeps `min(60, retry-after or 5*2**attempt)` and retries up to 6 attempts (`hunter.py:926-934`); with 30 queued jobs and a daily limit hit, that is minutes per job.
**How to avoid:** detect the daily case and mark the model spent for the rest of the day: treat a 429 whose body names a per-day limit, or whose `retry-after` exceeds 60 s (a per-minute window cannot exceed 60 s), as `GroqBudget.exhausted`; the next job then goes to the other model or is deferred. The error-body wording is not documented in the pages fetched here [ASSUMED: third-party descriptions say the message names "tokens per day (TPD)"], so key the classifier on both signals and unit-test both.

### Pitfall 5: Reading dates from the tracker's display strings
**What goes wrong:** cells are written `USER_ENTERED` (`hunter.py` `append_rows(... value_input_option="USER_ENTERED")`) in `DISPLAY_FORMAT`, then Sheets re-renders them in its own or the user's number format (the owner's own notes quote "10/22 10:03 PM", no year); `get_all_values` returns display text.
**How to avoid:** use ledger instants for day and age (Pattern 5); parse `Date_Found` only as an optional cross-check with several formats.

### Pitfall 6: Token-bearing exception text is persisted and shown
**What goes wrong:** the MEAS-05 fix writes `str(exc)[:300]` for no-response failures into the `error` event (`ledger.failure_events`, `ledger.py:198`), the Dashboard Needs-attention detail shows `msg[:160]` (`reporting.py:673-675` area), and `log.warning(... exc)` goes to the public Actions log. A `requests` transport error message includes the request path, and the Telegram path is `/bot<TOKEN>/sendMessage` (`hunter.py:1447`). [ASSUMED: urllib3/requests `ConnectionError` text includes the URL path; GitHub masks registered secrets in logs (seen live as `GROQ_API_KEY: ***`) but not in the Sheet.]
**How to avoid:** a `redact(message, secrets)` helper applied to every message stored or logged from the alert path (bot token, webhook URL, chat id); a test that raises a `ConnectionError` containing the token and asserts the stored detail and the log record do not.

### Pitfall 7: Multi-channel partial success duplicates messages
**What goes wrong:** Telegram accepts, the webhook then raises; the function raises; the retry sends Telegram again (up to 5 times). **How to avoid:** accept (documented at-least-once, SPEC L93) but note it in the SPEC edit; the bound limits it.

### Pitfall 8: SmartRecruiters parking confounds the first evidence read
**What goes wrong:** removing `ALLOW_SMARTRECRUITERS_BULK` makes `pools.sync_pools` park monitored SmartRecruiters boards the next run (status rewritten, history kept; not restored by reverting), changing monitored count, coverage and tracker yield right around the first weekly rebalance.
**How to avoid:** record the decision now, deploy the workflow edit as its own PILOT_LOG entry after the rebalance report is read; show tracker rows by ATS in the data block so the yield baseline is not lost.

### Pitfall 9: Live Settings tab does not get the new rows
**What goes wrong:** `Groq_Daily_Token_Budget` exists only in `DEFAULT_SETTINGS`; the live Settings tab (created earlier) will not show it.
**How to avoid:** the default applies; log the effective budget and its source (Settings vs default) in `Runs.Notes`; add a PLAN step for the owner (or the Sheets connector, as in D-46) to add the row with its description. Do not auto-write the user's Settings tab.

### Pitfall 10: Public repository, public logs
**What goes wrong:** new log lines or docs with job content, resume text or secrets. The repo is public [VERIFIED: `gh repo view --json visibility` → `{"isPrivate":false,"name":"auto_search_workflow","visibility":"PUBLIC"}`] and the Actions logs are readable (this research read them).
**How to avoid:** log counts and job keys only; the existing pattern (`Transient failure evaluating %s`, key only) is the model.

## Code Examples

### Stage 4 classifier (design sketch against `pipeline.py:585-603`)
```python
# Replace the `except Exception` body and the `sent` handling (verbatim current branch: pipeline.py:588-598)
import requests

def _classify_alert_failure(exc: Exception) -> str:
    resp = getattr(exc, "response", None)
    code = getattr(resp, "status_code", None)
    if code is not None:
        return "transient" if code >= 500 or code == 429 else "bounded"      # unchanged HTTP rules
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return "transient"        # DEFAULT PENDING Open Question 1: set to "bounded" if the owner wants the literal criterion
    return "bounded"              # ValueError / KeyError / formatting bugs: CONCERNS #2

# in the loop
sent = d.send_alert(payload)
if not sent:                      # no channel accepted: CONCERNS #1
    run.alerts_failed += 1
    run.notes += "no alert channel configured or accepted; " if "no alert channel" not in run.notes else ""
    continue                      # not recorded as alerted, no attempt used
```
Keep the existing `lg.failure_events(st.key, lg.STAGE_ALERT, redact(str(exc)), st, now, run.run_id)` call for the bounded case.

### Forced-limit test shape (offline; mirrors `tests/test_core.py` Harness)
```python
# budget = 0 (or tiny) -> every pending job stays pending, no events, no attempts; next UTC day picks them up
run = self.w.run(minutes_later=60, groq_budget=GroqBudget(day="2026-10-26", budgets={"m": 0}))
assert (run.evaluated, run.eval_budget_skipped, self.w.events(k, lg.ERROR)) == (0, 1, [])
run = self.w.run(minutes_later=60 * 24, groq_budget=GroqBudget(day="2026-10-26", budgets={"m": 10**6}))  # rolled over
assert self.w.events(k, lg.EVALUATED)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Per-minute `TokenBudget` only | Per-minute guard plus persisted daily per-model budget | this phase | The daily limit, not TPM, is the binding cap at volume |
| Alerted recorded when `send_alert` returns anything | Recorded only on `True` | this phase | Matches SPEC "Delivery: Telegram message accepted by the API" |
| Cutoffs absent (max run 770 s of 1500 s) | Process-anchored cutoffs | this phase | Needed before backfill/board growth |

**Deprecated/outdated:** `DEPLOY.md:11` says "Older commits still contain three CSVs ... Keep the repository private". [VERIFIED: `git log --all --name-only --pretty=format: -- '*.csv' 'tracked_jobs*' 'resume*' 'Resume*' '*.pdf'` returned no paths, across 53 commits] and the repo is public, so that text is stale, as are `DEPLOY.md:13-16` (private repo creation), `README.md:93` ("Use a private repository"), and D-37's "meant to be private".

## Groq facts for MEAS-02 (what is known and what needs the account page)

- Limits are per organization, not per key; the doc table shows `openai/gpt-oss-120b` and `openai/gpt-oss-20b` both at RPM 30, RPD 1K, TPM 8K, TPD 200K, but the page does not say which plan the extracted table reflects and says exact limits are on the account limits page [CITED: console.groq.com/docs/rate-limits].
- Headers: `x-ratelimit-limit-requests` / `remaining-requests` / `reset-requests` refer to requests per DAY; `x-ratelimit-limit-tokens` / `remaining-tokens` / `reset-tokens` refer to tokens per MINUTE; `retry-after` is set only on a 429 [CITED: console.groq.com/docs/rate-limits]. So the daily TOKEN limit is not in any header: it comes from the account page or from a 429 body. The code already reads `x-ratelimit-limit-tokens` (`hunter.py:885-892`), which is the per-minute figure.
- Daily reset semantics (rolling vs fixed) are not stated in the docs [CITED: same page]; one third-party guide says UTC midnight [ASSUMED]. Measure: record `x-ratelimit-reset-requests` from a real response at a known time (a fixed reset shows time-to-midnight, a rolling one does not).
- Cached prompt tokens: "Cached tokens do not count towards your rate limits", supported for both gpt-oss models, exact prefix, 2 h TTL, 50% input discount; `usage.prompt_tokens_details.cached_tokens` carries the count [CITED: console.groq.com/docs/prompt-caching]. The prompt already puts roles, locations and resume before the job text (`build_messages`, `hunter.py:814-823`), so a stable prefix exists. Counting `total_tokens` (P2) therefore OVER-counts; record `cached_tokens` separately so the owner can see true consumption (Open Question 6).
- Plan: Developer tier needs a payment method, takes effect immediately with no upfront charge, offers spend limits and "significantly increased rate limits" [CITED: console.groq.com/docs/billing-faqs]; the free-tier exact limits are not on that page.
- Price for the cost estimate: `openai/gpt-oss-120b` input $0.15, cached input $0.075, output $0.60 (the page does not label the unit; "6.7M / $1" implies per 1M tokens) [CITED: console.groq.com/docs/model/openai/gpt-oss-120b].
- A third-party blog lists `openai/gpt-oss-20b` at 500K tokens a day on the free tier [ASSUMED; single secondary source, contradicts the docs table], which is why the fallback budget needs its own setting (Pattern: blank = same as primary).

### Arithmetic template for STATUS.md (inputs are ASSUMED until Runs data exists)
- Tokens per call: input about 0.7k (system prompt) + resume (7,000-char cap; the Sheet value is not read here) + job text (7,000-char cap, typically 1-2k) ≈ 2.5-3.5k, output up to 1,000 (`MAX_OUTPUT_TOKENS`) including hidden reasoning ⇒ about 3.5-4.5k total [ASSUMED]; the SUMMARY's 3.5-5k agrees. Replace with the measured mean from the new `Runs` columns.
- Calls a day = (daily token budget summed over usable models) / tokens per call. Two models at 85% of 200K = 340K ⇒ about 75-97 calls; primary only = 170K ⇒ about 38-49 calls.
- Tracker rows a day = calls a day × keep rate. Pilot keep rate 55/281 = 19.6% this window (47/260 = 18% earlier, STATUS). Two models ⇒ about 15-19 rows a day maximum; primary only ⇒ about 7-10.
- Calls needed for 20-30 rows at 18-20% ⇒ about 100-167 a day ⇒ about 350-750K tokens a day: above two free models, so the 20-30 target is conditional on a paid tier, prompt/caching gains or a higher keep rate.
- Dollar cost if paid (120b, ASSUMED 3.2k in / 0.8k out per call): about $0.0010 per call ⇒ 165 calls ≈ $0.17 a day ≈ $5 a month; cached input halves the input share.
- Supply caveat to state next to the figure: today only about 40 jobs a day reach scoring, so the supported evaluations a day is not the current constraint; backfill (Phase 4) and boards (Phase 5) are what make it one.

## Runtime State Inventory

Not a rename/refactor phase, with one exception worth stating explicitly because it is a configuration change to live state (SmartRecruiters parking):

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | Monitored SmartRecruiters rows in the `Boards` tab (status `active`/`new`) rewritten to `deferred` on the first run without the override (STATUS "Migration requirements") | Data migration happens by code on the next run; reversal does not restore `active` (needs re-validation and a re-entry baseline); decide timing (Open Question 5) |
| Live service config | GitHub repository `ALLOW_SMARTRECRUITERS_BULK: "1"` in `job_hunter.yml:74` and `inventory.yml:76`; live Settings tab lacks `Groq_Daily_Token_Budget` | Edit both workflow lines in one commit; owner adds the Settings row |
| OS-registered state | External hourly trigger (cron-job.org) and the watchdog second trigger live outside the repo | None for this phase |
| Secrets/env vars | `GROQ_API_KEY`, `TELEGRAM_*`, `ALERT_WEBHOOK_URL` names unchanged; optional new env fallbacks follow the `pick()` pattern (`GROQ_DAILY_TOKEN_BUDGET`) | None |
| Build artifacts | `__pycache__` only | None |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Groq daily limits reset at UTC midnight (third-party guide) | Groq facts, Pattern 1 | Budget day boundary wrong; mitigated by 15% headroom and the daily-limit 429 handler; confirm with a recorded `x-ratelimit-reset-requests` |
| A2 | A per-day 429 body names "tokens per day (TPD)" and a `retry-after` above 60 s indicates a daily limit | Pitfall 4 | Classifier misses the daily case; mitigated by testing both signals and the budget itself |
| A3 | Tokens per call is about 3.5-4.5k (input 2.5-3.5k, output about 0.8-1k) | Arithmetic | Evaluations/day figure shifts; replaced by measured `Runs` data |
| A4 | `requests` transport-error text includes the request URL path (so the Telegram bot token) | Pitfall 6 | If not, the redaction is harmless extra safety |
| A5 | `openai/gpt-oss-20b` may have a 500K TPD free limit (single blog) | Groq facts | Only a reason to keep a separate fallback budget row; the account page decides |
| A6 | Telegram message limit is 4,096 characters after entity parsing (CONCERNS #3) | Slice A | Truncation fix cap is too tight/loose; low impact |
| A7 | A stacked COMBO chart keeps its LINE series un-stacked | Pattern 6 | Band renders wrong; fallback layout given; needs a real-Sheet look |
| A8 | The 1 unparseable tracker row is a Greenhouse custom-domain `absolute_url` | Hypotheses | Diagnostic names it; no code depends on this |
| A9 | The Sheet's `Resume_Text` length (not read) keeps the prompt within the assumed token range | Arithmetic | Measured tokens replace it |

## Open Questions

1. **MEAS-05: do transport errors (`requests.ConnectionError`, `requests.Timeout`) stop after 5 attempts?**
   - Known: success criterion 4 says "a send that fails without an HTTP response ... stops after 5 attempts"; SPEC L93 says "Transient failures (timeouts, 5xx, 429, Groq outage, Sheets/Telegram errors) are retried on later runs; rejected requests and permanent-looking failures are bounded at 5 attempts" and AGENTS rule 4 says do not turn transient errors into permanent records; today `tests/test_core.py` (`test_alert_failure_is_retried_and_sent_exactly_once`) retries a `ConnectionError` indefinitely and `test_rejected_alert_requests_are_bounded_but_outages_are_not` encodes the split.
   - Unclear: whether the owner meant a Telegram outage of 5+ hours should abandon pending alerts.
   - Recommendation: flag to the owner now (AGENTS rule 1). Default in the plan: non-transport exceptions (malformed rows, `KeyError`, formatting) are bounded at 5; transport errors stay retried without using attempts, counted in `alerts_failed`; make the policy one constant and test both. The criterion test must use a non-transport exception, and the doc change must edit SPEC L93 in the same change.
2. **Tracker-vs-ledger mismatch: what if the 2 are owner deletions?** Recommendation: run the diagnostic first; if deleted, show the figure as an informational line (not severity-0) or let the Needs-attention rule fire only for jobs evaluated in the last 24-48 h, so it stays meaningful.
3. **P2-09 says "day it was found (`Date_Found`)".** Recommendation: take the day from the ledger `evaluated` instant (same moment, same display zone) and use `Date_Found` only as a cross-check, because the cell is user-formatted text (Pitfall 5). Low risk; needs the planner's acceptance.
4. **D-number allocation.** `ROADMAP.md` Phase 4 entry gate says "D-05 amendment (D-48)". Phase 2 will record decisions first. Recommendation: Phase 2 takes the next free number(s) (D-48 onward) in one "Owner decisions for v2.0" entry, and the ROADMAP/REQUIREMENTS reference to "D-48" for the D-05 amendment is changed to "its own D-number when recorded".
5. **When to deploy SmartRecruiters parking.** Recommendation: record the decision in Phase 2, deploy the workflow edit after the first weekly rebalance report (about 2026-10-29) is read, with its own PILOT_LOG row.
6. **Budget counting basis and day boundary.** `total_tokens` over-counts cached tokens; UTC day is a stand-in until `x-ratelimit-reset-requests` is observed. Recommendation: count `total_tokens` now, record `cached_tokens` and the reset header from the first deployment, revisit after 1-2 days of data (a Settings-free constant change).
7. **Owner action required for MEAS-02.** Someone with the Groq console must read the limits page (tier, RPM, RPD, TPM, TPD per model) and paste the figures (no key material) so STATUS can record them with their source; there is no way to read them from headers (daily TOKEN limit is not a header).
8. **Combo-chart rendering** (A7): needs one live visual check; fallback layout defined.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python venv | tests, all code | yes | 3.12.13 | none needed |
| `git` | history check, commits | yes | - | - |
| `gh` CLI (authenticated) | reading Actions logs, `gh repo view` | yes | - | none needed (read-only use) |
| Groq credentials | live token measurement | not used by the researcher (`.env` not read) | - | Production `Runs` columns after deploy; owner reads the console page |
| Sheets credentials / connector | "checked in the real Sheet" (criterion 1) | not used here | - | Human or Sheets-connector checkpoint (as in D-46), or the read-only `pilot_report`/`dashboard` workflow inputs |
| Telegram credentials | live alert-path check | not used here | - | Mocked tests; one labelled `delivery_test` workflow run is the only live path |

**Missing dependencies with no fallback:** none for planning. Live Sheet, Groq and Telegram verification needs credentials or a human checkpoint; do not claim it otherwise (rule 5).

## Validation Architecture

Nyquist validation is enabled (`.planning/config.json` does not exist, so the key is absent and treated as enabled).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `unittest` (stdlib), Python 3.12.13 |
| Config file | none (discovery by directory) |
| Quick run command | `.venv/bin/python -m unittest tests.test_governors tests.test_core tests.test_hunter tests.test_reporting -q` |
| Full suite command | `.venv/bin/python -m unittest discover -s tests` (525 tests, about 5 s) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MEAS-05 | `send_alert` returning `False` records no `alerted` event, job stays pending, no attempt used | unit (Harness) | `.venv/bin/python -m unittest tests.test_core -k alert -q` | extend `tests/test_core.py` |
| MEAS-05 | Non-transport exception without a response: 5 failure events then `abandoned`; run 6 does not call `send_alert` | unit | same | extend |
| MEAS-05 | Transport error stays transient (policy constant); both policies tested | unit | same | extend |
| MEAS-05 | Stored and logged text contains no bot token | unit | same | extend |
| MEAS-03 | Budget rollover at UTC day, per-model counters, reserve blocks non-fresh at 80%, exhausted flag, JSON round trip | unit (pure) | `.venv/bin/python -m unittest tests.test_governors -q` | ❌ Wave 0 |
| MEAS-03 | `GroqClient` records `usage.total_tokens`, `prompt_tokens_details.cached_tokens`, limit headers per model; 429 with long `retry-after` marks the model spent with no backoff loop; falls to the other model | unit (FakeResponse, `tests/test_hunter.py` pattern) | `.venv/bin/python -m unittest tests.test_hunter -k Groq -q` | extend |
| MEAS-03 | Forced limit: budget 0 leaves jobs pending with no events and no `error`; next day they are scored; `Runs` token columns round-trip | unit (Harness) | `.venv/bin/python -m unittest tests.test_governors -k forced -q` | ❌ Wave 0 |
| MEAS-03 | New `Runs` columns: `from_row(to_row()) == full`, old short rows still load | unit | `.venv/bin/python -m unittest tests.test_pools tests.test_pilot tests.test_discovery -q` | extend |
| MEAS-04 | `poll_boards` with a fake clock past the deadline returns `skipped_deadline` for the rest, never calls `fetch` for them, leaves them untouched; order is longest-unpolled first | unit | `.venv/bin/python -m unittest tests.test_governors -k poll -q` | ❌ Wave 0 |
| MEAS-04 | Run outcome: poll cut ⇒ `degraded`; eval cut or spent budget ⇒ `ok` with note and counter | unit (Harness) | `.venv/bin/python -m unittest tests.test_governors -k outcome -q` | ❌ Wave 0 |
| MEAS-04 | Deadline anchored at process start (a fake clock that begins 10 minutes in cuts evaluation earlier); verified-fresh scored first | unit | same | ❌ Wave 0 |
| MEAS-04 | Client deadline: a stuck `TokenBudget.wait` or 429 loop raises `TransientError` at the deadline | unit | `.venv/bin/python -m unittest tests.test_hunter -k deadline -q` | extend |
| MEAS-01 | `_yield`: per-day counts by local day and cohort, age buckets incl. `unknown` for day precision, feedback per cohort, unmatched rows counted | unit (hand-built ledger and tracker, as in `test_reporting.py`) | `.venv/bin/python -m unittest tests.test_reporting -k yield -q` | extend |
| MEAS-01 | Reconcile names the missing keys; stored-URL fallback matches a non-ATS-host URL; mismatch 0 adds no Needs-attention row, mismatch > 0 adds one | unit | same | extend |
| MEAS-01 | Dashboard top chart is the tracker-rows chart; band series present; rerun identical (idempotent) | unit (grid and `requests_for`) | `.venv/bin/python -m unittest tests.test_reporting -k dashboard -q` | extend |
| GOV-01 | Every listed decision has an entry with needed-by phase and default | manual doc check + a grep test is optional | `grep -n "needed by" DECISIONS.md` | n/a (docs) |
| MEAS-02 | Figures written to STATUS with source and date; plan decision recorded | manual (owner action) | n/a | manual-only: needs the Groq console and real runs |

Mutation spot-checks are the project norm (STATUS entries): for each new behaviour, break the line (drop the reserve test, ignore the deadline, record `alerted` on `False`, reuse `skipped`) and confirm the suite fails.

### Sampling Rate
- **Per task commit:** the quick run command (a few seconds).
- **Per wave merge:** the full suite.
- **Phase gate:** full suite green, plus the live checks below, before `/gsd-verify-work`.

Live checks (mocked tests cannot prove these; each is a labelled checkpoint, rule 5): (1) after deploying slice B, `Runs` rows show token columns and the cut/skip counters for real runs, and one UTC-day total is compared with the Groq console usage; (2) the Dashboard renders the new chart and band in the real Sheet and the row count reconciles with the ledger (browser or connector, as done for D-41); (3) one `delivery_test` run if the alert path changed materially (needs the owner's tick); (4) forced-limit demonstration can be mocked, but "figures from a live run" must come from production `Runs`.

### Wave 0 Gaps
- [ ] `tests/test_governors.py`: budget, forced-limit, poll deadline and order, outcome split, process-start anchoring (new)
- [ ] A fake monotonic clock helper shared by `poll_boards`, `Deps` and `GroqClient` tests (the code already injects `clock` into `poll_boards`; add one `Deps.clock` and a client deadline hook)
- [ ] Extend `Harness` in `tests/test_core.py` so `send_alert` can return `False` and raise typed exceptions (it currently returns `True` or raises `alert_error`)
- [ ] No framework install needed

## Security Domain

`security_enforcement` is not set to false anywhere (no config file), so it applies.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no (no new authn) | - |
| V3 Session Management | no | - |
| V4 Access Control | yes (writer lease unchanged; dashboard stays read-only toward state) | Keep `dashboard` read-only; budget written only by the leased poller |
| V5 Input Validation | yes | Parse Groq `usage` and `x-ratelimit-*` defensively (missing, non-numeric); tolerate user-formatted tracker cells; never trust header text beyond int/float parsing |
| V6 Cryptography | no | - |
| V7 Error Handling and Logging | yes | Redact bot token, webhook URL and chat id from stored/logged exception text; counts and keys only in public logs |
| V8 Data Protection | yes | Resume text goes to Groq on every call (CONCERNS "Personal data", no recorded decision): the volume story raises exposure; list "Groq data handling" among the owner decisions (needed with the plan decision) |
| V14 Configuration | yes | Workflow edits (parking) reviewed as a deployment; no new secrets; keep `permissions: contents: read` |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Bot token leaking through exception text into the Sheet/Dashboard/logs | Information disclosure | `redact()` before `failure_events`, `log.warning` and `Runs.Notes`; test with a token-bearing `ConnectionError` |
| Public logs exposing job content or resume | Information disclosure | Log only counts and `ATS|board|id` keys; no titles, companies or prose |
| Budget bypass by manual `--url`/`--delivery-test` | Tampering (accidental) | 15% headroom (P2-02); these paths do not persist the budget |
| Formula injection from tracker/Settings text | Tampering | Existing `_safe_cell`; the dashboard writes only generated numbers |
| Alert-loop amplification (retry forever) | Denial of service (self) | Attempt bound at 5; stage-4 hard stop |

## GOV-01 decision inventory (for DECISIONS.md and the Owner Decisions table)

| Decision | State at Phase 2 | Needed by | Default if unanswered | Doc edits in the same change |
|----------|------------------|-----------|-----------------------|------------------------------|
| Groq plan and budget | Pending: measure, then owner chooses free/paid before the phase closes (P2-13); also D-16 OK for budget-driven fallback use is recorded (P2-03) | End of Phase 2 | Target stays conditional (about 7-20 rows a day) | STATUS figures with source; DECISIONS entry |
| SmartRecruiters | Record "parked" (P2-14) | Phase 2 | Parked | D-38 superseded note; remove the two workflow lines (timing: Open Question 5); SPEC "Provider limits" text; PILOT_LOG |
| Repository visibility | Record "public" (P2-15) | Phase 2 | Stay public, keep logs free of job content | `DEPLOY.md` (lines 11, 13-16, 105 and private-repo sections), `README.md:93`, D-37 amendment note, CONCERNS "Repository visibility", INGEST-CONFLICTS warning marked resolved, STATUS "private-then-public" wording |
| Date-only alerts (D-04c) | Record (user decision 2026-10-25, P2-16) | In force before the first Oracle row (Phase 6) | Tracker only, no alert | DECISIONS entry; SPEC when ADPT-07 lands |
| D-05 amendment (backfill) | List (P2-17) | Phase 4 | No backfill | DECISIONS "pending" list |
| Rule-7 lift (board-cycling scores only) | List | Before CYC-02 (Phase 5) | Score stays in shadow | same |
| Per-ATS policy (Paycom skipped, iCIMS deferred, Teamtailor/Personio/JOIN/SuccessFactors skipped; terms for Breezy, Gem, Oracle, Workday, Rippling, BambooHR) | List | Phase 6 start / Phase 7 start | Build only providers with a recorded decision | same |
| Storage design approval (D-43 amended; closes the D-03 200k review) | List and surface | Before Phase 3 executes (point reached about 2026-10-29) | Proceed with D-43; delete nothing before parity | same |
| Groq data handling (resume sent to Groq) | List (new, from CONCERNS "Personal data") | With the plan decision | Keep as is, record the account's retention setting | DECISIONS entry |

Format precedent for an open-items entry: `## D-22 Open items to confirm` and `## D-30 Open items to confirm` (`DECISIONS.md`); an entry that changes behaviour carries its own D-number and updates SPEC/STATUS (AGENTS rule 1). Behaviour changes in this phase that need D-numbers: the token budget and fallback policy, the deadlines and poll order, the alert-recording change (SPEC L93), the new dashboard definitions (SPEC "Operational dashboard" metric rules).

## Sources

### Primary (HIGH confidence)
- Repository files read this session: `pipeline.py` (full), `ledger.py`, `meter.py`, `state.py` (RunRecord, Sheet/CSV state), `hunter.py` (Settings, Config, GroqClient, tracker, send_alert, evaluator, main), `boards.py` (`poll_boards`, `parse_job_url`, adapters), `reporting.py` (job facts, build_summary, feedback, reconcile, failures), `dashboard.py` (render, charts, publish), `pilot.py` (limits audit, feedback), `freshness.py`, `search.py` (SearchBudget), `SPEC.md`, `DECISIONS.md` (D-03, D-16, D-37, D-38, D-43-D-47), `STATUS.md`, `PILOT_LOG.md`, `DEPLOY.md`, workflows, `.planning/*` including CONCERNS and INGEST-CONFLICTS
- `gh run view 40191573405 --log` (read-only pilot report of 2026-10-25 12:05 UTC); `gh repo view --json visibility`; `git log --all --name-only` history checks
- Offline suite: 525 tests pass

### Secondary (MEDIUM confidence)
- [console.groq.com/docs/rate-limits](https://console.groq.com/docs/rate-limits): headers, base table, cached tokens, organization scope
- [console.groq.com/docs/prompt-caching](https://console.groq.com/docs/prompt-caching): supported models, usage object shape
- [console.groq.com/docs/billing-faqs](https://console.groq.com/docs/billing-faqs): Developer plan mechanics
- [console.groq.com/docs/model/openai/gpt-oss-120b](https://console.groq.com/docs/model/openai/gpt-oss-120b): pricing (unit unlabelled)
- [developers.google.com/sheets/api/reference/rest/v4/spreadsheets/charts](https://developers.google.com/sheets/api/reference/rest/v4/spreadsheets/charts): COMBO series `type`, `stackedType` (the last 9k characters of the page were not read)

### Tertiary (LOW confidence)
- Third-party guides on Groq free-tier limits and UTC-midnight resets (klymentiev.com, benchlm.ai via search results); used only to justify measuring, not as fact

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH, no new packages; existing seams read in full
- Architecture: HIGH for the pipeline/`poll_boards`/`RunRecord` seams (read and test-guarded); MEDIUM for chart band rendering
- Pitfalls: HIGH for deadline anchoring, `poll_boards` blocking, `skipped` reuse, token leakage path; MEDIUM for the daily-429 wording
- Groq limits: MEDIUM (docs base table, plan unspecified); account figures need the owner

**Research date:** 2026-10-26
**Valid until:** 2026-11-02 for the live figures (the first weekly rebalance and the 200k-row Events point land about 2026-10-29); 30 days for the code-structure findings
