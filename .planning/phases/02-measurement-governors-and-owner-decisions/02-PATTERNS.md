# Phase 2: Measurement, governors and owner decisions - Pattern Map

**Mapped:** 2026-10-26
**Files analyzed:** 14 (2 new, 12 modified)
**Analogs found:** 13 / 14 (all analogs are git-tracked root modules and `tests/`)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `eval_budget.py` (NEW) | utility (pure budget model) | batch / persisted counter | `search.py` `SearchBudget` (L214-258) | exact |
| `tests/test_governors.py` (NEW) | test | request-response (fake world) | `tests/test_core.py` `Harness` (L64-121) + `tests/test_search.py` | exact |
| `boards.py` (`poll_boards`, `PollResult`) | service | batch (concurrent poll) | itself (L610-651) | self-edit |
| `pipeline.py` stage 2/3 (order, cutoffs, budget skip) | service (orchestration) | batch | stage 3 transient branch (L555-570) | exact |
| `pipeline.py` stage 4 (MEAS-05 classifier) | service | event-driven | current stage 4 (L578-600) + `ledger.failure_events` | exact |
| `pipeline.py` `degraded_reason` | utility | transform | itself (L138-155) | self-edit |
| `state.py` (`RunRecord`, `RUN_COLUMNS`, `from_row`) | model | CRUD (Sheet row) | itself (L44-60, 140-170) | self-edit |
| `hunter.py` `GroqClient` (tokens, model pick, deadline) | service | request-response | itself (~L875-940) | self-edit |
| `hunter.py` Settings rows + `send_alert` truncation | config / service | request-response | `Min_Alert_Score` / `Max_Active_Boards` rows (L160-250); `send_alert` (L1427) | exact |
| `reporting.py` `_yield`, `reconcile` extension | service (pure report) | transform | `reporting.reconcile` (L835), `job_facts` (L184), `pilot.py` feedback block (L191-212) | exact |
| `dashboard.py` top chart, band, Needs-attention row | component (render) | transform | `Chart` / `chart_request` (L50, L399), NEEDS ATTENTION (L281) | exact |
| `pilot.py` limits audit | utility | transform | its own timed-runs block (~L213) | self-edit |
| `DECISIONS.md`, `SPEC.md`, `DEPLOY.md`, `README.md`, `STATUS.md`, `PILOT_LOG.md` | doc | n/a | existing entries in each | n/a |
| `.github/workflows/job_hunter.yml`, `inventory.yml` (remove `ALLOW_SMARTRECRUITERS_BULK`) | config | n/a | existing lines (job_hunter.yml:74, inventory.yml:76) | exact |

## Pattern Assignments

### `eval_budget.py` (NEW, pure budget, persisted counter)

**Analog:** `/Users/aphan/auto_search_workflow/search.py` L214-258. Copy the dataclass-plus-`load`/`to_json` shape: day rollover in `load`, tolerant JSON parse, fields not persisted are plain attributes.

```python
@dataclass
class SearchBudget:
    month: str
    used: int = 0
    ...
    @classmethod
    def load(cls, raw, now, *, cap=..., reserve=...) -> "SearchBudget":
        month = month_of(now)
        try:
            data = json.loads(raw) if raw else {}
        except ValueError:
            data = {}
        if not isinstance(data, dict) or data.get("month") != month:
            old = data.get("month", "") if isinstance(data, dict) else ""
            return cls(month, cap=cap, reserve=reserve, rolled_from=str(old))
        ...
    def to_json(self) -> str:
        return json.dumps({"month": ..., "used": ...}, separators=(",", ":"))
```

Adapt: key `day` (UTC `%Y-%m-%d`), `used: dict[model,int]`, `exhausted` persisted (a daily-limit 429 must survive across runs). `BUDGET_KEY` constant style: `search.BUDGET_KEY = "search_budget"` (search.py:39); use `GROQ_BUDGET_KEY = "groq_budget"`. Reserve rule: `cap = budget * (100 - reserve_pct)//100` unless `fresh` (RESEARCH Pattern 1 sketch).

**Persistence wiring** (`pipeline.py` L222-230 load; L289 save):
```python
discovery_state = d.state.load_discovery_state()
budget = search.SearchBudget.load(discovery_state.get(search.BUDGET_KEY), now, cap=..., reserve=...)
...
discovery_state[search.BUDGET_KEY] = budget.to_json()
```
Save via `d.state.save_discovery_state(values, stamp)` (state.py L441/445 for Sheets, L595/598 for CSV) at each `write()` flush and in `finally`.

---

### `boards.py` `poll_boards` (batch, concurrent)

**Analog:** itself, L610-651. Add `deadline: float | None = None` next to the already injectable `clock`, and a NEW `PollResult.skipped_deadline: bool = False` (do not reuse `skipped`).

```python
def one(rec: BoardRecord) -> PollResult:
    with lock:
        until = backoff.get(rec.ats, 0.0)
    if until > clock():
        return PollResult(rec, skipped=True, error=f"provider backoff after HTTP 429 ({rec.ats})")
```
Insert the deadline check first (`if deadline is not None and clock() > deadline: return PollResult(rec, skipped_deadline=True, error="poll deadline")`). `pool.map` keeps submission order, so sort the input list in `pipeline` stage 2 by `last_attempt_at` ascending (blank first). The pipeline must not call `apply_poll_result` for deadline-skipped boards (same as the 429 skip at pipeline.py ~L339).

---

### `pipeline.py` stage 3 (evaluation cutoff, budget skip) (batch)

**Analog:** the transient branch, L555-570. Budget and deadline skips behave identically: record nothing, add no attempt.

```python
elif out.kind == "transient":
    # A temporary outage records nothing: it must neither mark the job done nor
    # use up its bounded retry attempts. The next run simply tries again.
    run.eval_transient += 1
    log.warning("Transient failure evaluating %s (will retry): %s", st.key, out.message)
    run.notes += "transient evaluation failures; " if "transient evaluation" not in run.notes else ""
```
Differences: do NOT bump `run.eval_transient` (it feeds `degraded_reason` "scoring"); use new counters `eval_budget_skipped` / `eval_cut`, and a `run.notes += ... if ... not in run.notes` note (same idempotent-note idiom). The pre-check `if not d.can_score(st): run.eval_budget_skipped += 1; continue` goes before `d.evaluate` so the job is not hydrated. Keep `if i % FLUSH_EVERY == 0: write()` (FLUSH_EVERY = 10) and mind that `continue` must not skip it incorrectly.

**`degraded_reason`** (L138-155): add only the poll-cut reason, following the string-match idiom:
```python
if "provider backoff after HTTP 429" in run.notes:
    reasons.append("provider")
```
Add `if run.boards_skipped_deadline: reasons.append("poll cutoff")` (a counter, not a notes substring). Evaluation cut and budget skip add nothing (P2-07).

**Deadline clock:** `run_cycle` currently uses `t_start = time.monotonic()` (L~162); the cutoffs anchor at process start instead (RESEARCH Pitfall 2). Add an injectable monotonic clock to `Deps` (as `now` is injected) so tests can use a fake.

---

### `pipeline.py` stage 4 (MEAS-05) (event-driven)

**Analog:** the current block, L578-600 (the code being replaced). Current bugs: `"channel": "telegram" if sent else "none"` plus `st.alerted = True` even when `sent` is False (CONCERNS #1), and the `except` records only for responses with `status_code < 500` and not 429, so no-response exceptions are never bounded (CONCERNS #2).

```python
except Exception as exc:
    run.alerts_failed += 1
    log.warning("Alert failed for %s (will retry): %s", st.key, exc)
    if getattr(getattr(exc, "response", None), "status_code", 500) < 500 and ... != 429:
        pending_events += lg.failure_events(st.key, lg.STAGE_ALERT, str(exc), st, now, run.run_id)
    continue
```
Reuse `lg.failure_events` (`ledger.py` L194-201; `message[:300]`, abandons at `MAX_ATTEMPTS = 5`) unchanged. Add `_classify_alert_failure` per RESEARCH "Stage 4 classifier" and gate on `if not sent: run.alerts_failed += 1; note; continue`. Apply a `redact(str(exc), secrets)` helper before both `failure_events` and `log.warning` (token appears in the Telegram URL path). Keep the legacy `channel: none` reading in `reporting.job_facts` (L209-213). SPEC L93 conflict (Open Question 1) must be flagged before behaviour changes (AGENTS rule 1).

---

### `state.py` `RunRecord` / `RUN_COLUMNS` (CRUD)

**Analog:** itself. Append new fields AFTER `code_version` (tail `"Eval_Attempted", "Eval_Transient", "Eval_Failed", "Code_Version",`, state.py:56) in both the dataclass and `RUN_COLUMNS`; extend `from_row` by index (currently ends `..., num(64) or 0, row[65])`):

```python
return cls(row[0], row[1] == "yes", ..., row[61], num(62) or 0, num(63) or 0, num(64) or 0, row[65])  # fmt: skip
# new: , num(66) or 0, num(67) or 0, ...
```
`to_row` iterates `fields(self)` so it needs no change. Guard tests to keep green/extend: `tests/test_pools.py:904-911`, `tests/test_discovery.py:652-656`, `tests/test_pilot.py:297-300`. Counters flow like `groq_calls`/`groq_429`: `METER.add(...)` in `GroqClient` and `METER.since(meter0)` at run end (pipeline.py ~L616-620).

---

### `hunter.py` `GroqClient.evaluate` (request-response)

**Analog:** itself. Existing seams to hook:
- Model choice `_model()` (L875-878) returns `groq_fallback_model` if the primary is `unavailable` or in fallback hold. Extend with `eval_budget.pick_model(...)`, returning `None` to raise `TransientError`-like "deferred" without an attempt.
- Header learning `_learn_limit` (L888-895) reads `x-ratelimit-limit-tokens` (per-minute). Copy this shape to capture `x-ratelimit-limit-requests` / `remaining-requests` / `reset-requests` into the `Groq_Limits` JSON.
- Metering idiom: `METER.add("groq_calls")` after each response, `METER.add("groq_429")`. Add `METER.add("groq_tokens_primary", n)` from `resp.json()["usage"]["total_tokens"]`, plus `prompt_tokens_details.cached_tokens`.
- 429 handling (L920-934): switch primary to fallback; fallback sleeps `min(60.0, _retry_after(resp) or 5 * 2**attempt)`. Add the daily-limit detection (retry-after > 60 s or body names per-day) to call `budget.exhaust(model)` instead of sleeping.
- Deadline: `self.budgets[model].wait(est)` and `time.sleep` calls must stop at the absolute deadline by raising `TransientError` (already mapped to `transient` at hunter.py ~L1545).

---

### `hunter.py` Settings rows and `send_alert`

**Settings analog:** `("Min_Alert_Score", "70", "Jobs scoring at or above this (0-100) ...")` and `("Max_Active_Boards", "500", "Most company boards checked every hour. ...")` (hunter.py ~L160, L181); parsed via `pick(key)` falling back to the upper-cased env var then `SETTING_DEFAULTS` (~L248-257). Add `Groq_Daily_Token_Budget` (and optionally the reserve and cutoff minutes) the same way; description must state what it limits and where the figure came from. Live tab is not auto-widened (`bootstrap`, ~L1200), so log the effective value and its source in `Runs.Notes`.

**`send_alert` analog:** itself (L1427-1470). Returns `sent` (False if neither channel configured). Truncation fix (CONCERNS #3): the current `"\n".join(lines)[:4096]` can cut inside an HTML tag; build the shortened body before adding tags (truncate the `verdict`/`gaps` text via `esc(...)` of a pre-cut string) rather than slicing the final HTML.

---

### `reporting.py` `_yield` / `reconcile` (pure transform)

**Analog 1:** `reporting.reconcile` (L835+): same `clean_inputs(runs, events, tracker)`, `job_facts(clean.events)`, and `kept` set logic; extend to return the missing keys with `eval_at` and stored URL (Pattern 5) and to count both directions.

**Analog 2:** `pilot.py` L191-212 cohort feedback block (copy this loop for the per-cohort `My_Feedback` mix):
```python
for row in tracker:
    label = (row.get("My_Feedback") or "").strip()
    fresh = row.get("Freshness") or "?"
    if not label:
        unlabelled += 1
        continue
    if label in labelled:
        labelled[label] += 1
        by_fresh.setdefault(fresh, {k: 0 for k in FEEDBACK})[label] += 1
```
**Day and age source:** `JobFacts` fields `seen_at`, `published`, `precision`, `eval_at`, `freshness`, `eval_visible` (reporting.py L117-140). Day = local day of the `evaluated` event in the Settings `Timezone`; age bucket only when `precision == "time"`, else `unknown`. Join tracker to ledger with `boards.parse_job_url(Apply_URL).key`, fallback exact stored-URL match (never dedupe on URL, rule 3). Keep the module free of Sheets I/O.

---

### `dashboard.py` (render, read-only)

**Chart analog:** `Chart` dataclass (L50-59) and `chart_request` (L399-432). `kind` supports only `line | column | stacked_column | bar | donut`; the band needs a new `combo` kind: `"chartType": "COMBO"` with per-series `"type": "LINE"` / `"COLUMN"` (RESEARCH Pattern 6; verify in the real Sheet). Fallback: a non-stacked `column` series plus two flat `line` series (20, 30) fed from new columns in the hidden data block. Series colours go through `_rgb(name)`; header row names each series (`r0 -= 1`).

**Needs attention analog:** L281-290; rows come from `F["table"]` with `{"what","ref","detail","action","severity"}` and severity chips. Add the tracker-vs-ledger mismatch as a new row in whatever builds `F["table"]` (in `reporting.py`), only when the number is non-zero.

---

### `tests/test_governors.py` (NEW)

**Analog:** `/Users/aphan/auto_search_workflow/tests/test_core.py` `Harness` (L64-121): CSV `CsvState` in a temp dir, fake `fetch`/`evaluate`/`send_alert`, injectable `now`, and `run(minutes_later=..., **kw)` passing extra `Deps` kwargs. Extend `Harness` (or subclass) with a fake monotonic clock and `groq_budget`. Copy the assertion style `self.events(key, lg.ERROR)` and `self.states()`. Use `HarnessCase` (L122) as the base. Required cases: forced zero budget (no events, no attempts, next UTC day picks up), reserve for verified-fresh only, poll cutoff gives `degraded` and the skipped board sorts first next run, eval cutoff leaves `ok`, late-start clock (lease wait), `send_alert` returning False is not `alerted`, transport exception bounded or retried per the Open Question 1 decision, token redaction. Mutation spot-checks per STATUS.md norm. Run `python -m unittest discover -s tests` (525 tests today).

## Shared Patterns

### Transient / skipped work records nothing (rule 4)
**Source:** `pipeline.py` L555-570 (transient branch). **Apply to:** budget skip, evaluation cutoff, poll cutoff, no-channel alert. No `error` event, no `st.errors` increment.

### Bounded attempts
**Source:** `ledger.failure_events` / `MAX_ATTEMPTS = 5` (`ledger.py` L26, L194-201). **Apply to:** MEAS-05 bounded failures only.

### Per-run counters
**Source:** `meter.METER.add(...)` in `GroqClient` and `METER.since(meter0)` in pipeline (~L616-620). **Apply to:** all new `Runs` token and cutoff counters.

### Idempotent run notes
**Source:** `run.notes += "..." if "..." not in run.notes else ""` (pipeline L568, L590s). **Apply to:** budget/cut/no-channel notes; keep wording distinct from `"provider backoff after HTTP 429"`, which `degraded_reason` and `reporting._BACKOFF_RE` key on.

### Persisted key-value state
**Source:** `Discovery` tab via `load_discovery_state`/`save_discovery_state` (state.py L441, L445, L595, L598); key constants like `search.BUDGET_KEY`. **Apply to:** `groq_budget`.

### Public repo logging
**Source:** `log.warning("Transient failure evaluating %s ...", st.key, ...)` logs key only. **Apply to:** all new log lines; counts and keys only, redact secrets (repo and Actions logs are public).

### Rule 1 doc updates in the same change
New behaviour gets D-numbers in `DECISIONS.md` (latest is D-47); SPEC L93 ("Sheets/Telegram errors" transient) and the "Delivery" section; DEPLOY.md L11-16 and README.md L93 ("private repository") and D-37 are stale.

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| Combo (band) chart in `dashboard.chart_request` | component | transform | No existing chart type uses per-series `type`; needs the Sheets API COMBO spec and a visual check in the real Sheet |
| Exception classifier and `redact()` helper | utility | event-driven | No existing transport-vs-malformed classification or secret redaction helper; use RESEARCH "Stage 4 classifier" sketch |

## Metadata

**Analog search scope:** root `*.py` modules, `tests/`, `.planning/phases/02-*` docs
**Files scanned:** about 12 (targeted reads and greps; large modules read by range)
**Tracked-source check:** all named analogs are root-level tracked modules, no capability mirrors involved
**Pattern extraction date:** 2026-10-26
