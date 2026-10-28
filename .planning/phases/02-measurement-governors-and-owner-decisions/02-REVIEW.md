---
phase: 02-measurement-governors-and-owner-decisions
reviewed: 2026-10-28T00:00:00Z
depth: standard
files_reviewed: 20
files_reviewed_list:
  - .github/workflows/job_hunter.yml
  - .github/workflows/inventory.yml
  - DECISIONS.md
  - DEPLOY.md
  - README.md
  - SPEC.md
  - STATUS.md
  - boards.py
  - dashboard.py
  - eval_budget.py
  - hunter.py
  - pilot.py
  - pipeline.py
  - reporting.py
  - state.py
  - tests/test_core.py
  - tests/test_governors.py
  - tests/test_hunter.py
  - tests/test_pilot.py
  - tests/test_reporting.py
findings:
  critical: 0
  warning: 4
  info: 6
  total: 10
status: issues_found
---

# Phase 2: Code Review Report

**Reviewed:** 2026-10-28
**Depth:** standard (diff 6631027..HEAD, each changed file read in context, call chains followed across hunter / pipeline / eval_budget / state / reporting / dashboard / pilot)
**Files Reviewed:** 20
**Status:** issues_found

## Summary

The phase adds a per-model daily Groq token budget (`eval_budget.py`, `GroqClient`, `pipeline.run_cycle`), run deadlines (poll 15 / eval 20 / alert 22 minutes from process start), alert-failure classification and redaction, new `Runs` columns, a tracker-yield view in reporting and the dashboard, and Groq measurement lines in the pilot report.

I traced the new control flow against the project rules (freshness never from crawl time; seen / evaluated / alerted separate and retryable; deferrals not recorded as failures). I found no correctness defect that loses data or breaks those rules:

- Deferrals (budget, deadline) record nothing and use no attempt.
- Deadline-skipped boards are left untouched and sort first next run.
- `RunRecord.from_row` indices 66-76 match `RUN_COLUMNS` and the dataclass field order.
- Header widening handles the grid growth.
- Telegram caps are applied before escaping, which is correct because Telegram counts the 4,096 limit after entity parsing.
- `save_budget` stays in sync with the other `discovery_state` writers.

The suite passes offline (`Ran 621 tests ... OK`). I did not run anything against live services; Sheets, Groq and Telegram behavior is mocked in the tests, as STATUS says.

The remaining findings are robustness, secret-handling consistency, and documentation or comment drift. No blockers.

Known items, not re-litigated: the `TokenBudget.wait` IndexError when one estimate exceeds 90% of the per-minute limit, and the pilot `completions per day` window divisor (both in deferred-items.md).

## Warnings

### WR-01: Persisted "spent per Groq" flag outlasts Groq's rolling window, so a model can stay locked for up to a day

**File:** `eval_budget.py:84-88`, `hunter.py:1058-1062`, `hunter.py:173-176`
**Issue:** `_is_daily_limit` marks a model exhausted for the rest of the UTC day. The flag is persisted in the Discovery record and cleared only when the UTC day changes (`_parse` returns an empty `exhausted` set only on a day mismatch). D-53 and STATUS established that Groq's daily window is rolling, not a midnight reset. A TPD 429 normally says "try again in N minutes". The code throws that information away and locks the model until 00:00 UTC.

The detector is also broader than a TPD signal. Any 429 with `retry-after > 60` (an outage or a long cool-down) or any body containing "per day", "TPD" or "RPD" triggers it. If both models are flagged by one such response each, scoring stops for the remainder of the UTC day. That contradicts the owner's stated goal (yield) and the "nothing is lost, waits for the next day" promise only in the sense that the wait can be far longer than Groq requires.
**Fix:** Store an expiry instead of a bare flag. For example, `exhausted: dict[str, str]` mapping model to an ISO instant of `now + retry_after`, or `now + 60 min` when no `retry-after` is present. `can_spend` then tests `now < expiry`. Persist the expiry in `to_json`, and keep the UTC-midnight rollover as an upper bound. Narrow `_is_daily_limit` so a long `retry-after` alone does not count unless the body also names a per-day limit.

### WR-02: Bot token can reach the log through the uncaught exception in `--delivery-test`; the redaction in D-49 does not cover this path

**File:** `hunter.py:1875`
**Issue:** `run_delivery_test` calls `send_alert(...)` with no `try`. `send_alert` raises `requests.HTTPError` through `raise_for_status()`, whose text is `... for url: https://api.telegram.org/bot<TOKEN>/sendMessage`. `requests` connection errors embed the same URL path. The exception propagates out of `main()` as a traceback.

D-49 states "Nothing raw (exception object, str(exc)) reaches the ledger, the notes or the log", and D-48 and DEPLOY now say the repository is public, so Actions logs are public. GitHub masks values registered as secrets, which mitigates the Actions case. Local runs and any log that reformats the token (for example URL-encoded) are not covered. The `--delivery-test` path was used live in this phase (STATUS), so it is exercised.
**Fix:** Catch the exception in `run_delivery_test` and print `pl.redact(str(exc) or type(exc).__name__, (cfg.telegram_token, cfg.telegram_chat_id, cfg.webhook_url))`, then return 1:
```python
try:
    alerted = send_alert(cfg, row, store.sheet_url)
except Exception as exc:
    log.error("Delivery test: send failed: %s", pl.redact(str(exc) or type(exc).__name__, (cfg.telegram_token, cfg.telegram_chat_id, cfg.webhook_url)))
    return 1
```

### WR-03: A mistyped or unparseable budget silently becomes the default while `Runs.Notes` claims it came from the Settings tab

**File:** `hunter.py:59-60`, `hunter.py:77-86`, `hunter.py:227-231`
**Issue:**
- `Settings.from_values` parses the budget with `_int_or(pick("Groq_Daily_Token_Budget"), DEFAULT_GROQ_DAILY_TOKENS)`. Any value that is not a plain number, such as "150,000" (a natural way to type it, and how the owner wrote "100,000" in D-53) or "100k", silently becomes 100000.
- `groq_budget_note` then reports "100000 / 100000 per UTC day from Settings tab", because it only checks that the raw row is non-blank. The note is the mechanism D-50 and D-53 rely on so the owner can see which value is in force, and here it is wrong.
- `_int_or` also lets `OverflowError` escape for "inf" (`int(float("inf"))`). This is reachable from the owner-edited Settings cell and would end the run as "Startup failed" (exit 2). I confirmed it: `hunter._int_or("inf", 1)` raises `OverflowError`.
**Fix:** In `groq_budget_note`, detect an unparseable value. For example, try `int(float(value.replace(",", "")))`, and when it fails say "Settings tab value 'X' not a number; default 100000 in force". Add `OverflowError` to the `except` in `_int_or`. Optionally accept thousands separators in the budget settings.

### WR-04: Groq `json_validate_failed` response body is logged (240 characters) in a now-public repository

**File:** `hunter.py:1087` (the `log.warning("Groq (%s) produced invalid JSON: %s", ...)` line; the line is unchanged in this diff but its exposure changed with D-48)
**Issue:** Groq's `json_validate_failed` 400 body carries the model's raw output in `failed_generation`, which is the verdict and gaps about the candidate and job. About 240 characters are written to the log, which covers the error message and the start of `failed_generation`. DEPLOY.md (changed in this phase) says "Logs and documents carry counts and job keys only; job content and the resume live only in the Google Sheet". The Actions log of a public repository is public. This line contradicts that statement, and the phase made the claim and the visibility change.
**Fix:** Log only the error code and the length, for example `log.warning("Groq (%s) produced invalid JSON (response %d chars)", model, len(resp.text))`. Apply the same restraint to the `Groq HTTP {code}: {resp.text[:200]}` text. That one goes to the private Events/Sheet, so it is acceptable there, but it must not be echoed to the log.

## Info

### IN-01: Stale "15% headroom" wording after the D-53 amendment

**File:** `eval_budget.py:75`, `hunter.py:2080`, `DECISIONS.md:335`, `DECISIONS.md:337`
**Issue:** Comments and D-50 text still say the overshoot of one answer, the over-count on missing usage, and the unbudgeted `--url` / `--delivery-test` calls are absorbed by "the 15% headroom of the default budget". D-53 changed the default to 50% of the limit, so the headroom is 50% and the rationale (85% of the limit) no longer applies.
**Fix:** Reword to "the headroom between the default budget and Groq's limit (D-53)".

### IN-02: SPEC layout claim is stronger than the evidence for the new dashboard content

**File:** `SPEC.md:118`, `STATUS.md:180`, `dashboard.py:33`
**Issue:**
- The SPEC says the layout is "checked in a real Sheet" while it now describes the combo chart, the age chart, and the TRACKER ROWS table. STATUS line 23 and `BAND_LINES_STACK` (assumption A7) say these were not verified live, which is the mocked-versus-live separation AGENTS rule 5 asks for.
- STATUS line 180 still says "Runs header widening to 65 columns", but there are now 77 columns.

**Fix:** Qualify the SPEC sentence ("the earlier layout was checked in a real Sheet; the yield charts and table are mocked only until the owner check in STATUS passes"). Update the column count in STATUS.

### IN-03: Alerted events always carry `channel: "telegram"`, including webhook-only deliveries

**File:** `pipeline.py:712`
**Issue:** `send_alert` returns True when either Telegram or the webhook accepted the message. The event hardcodes `"channel": "telegram"`. D-49 documents this as the label reporting counts, so it is a known trade-off. A deployment with only a webhook records a delivery on a channel that was never used.
**Fix:** Have `send_alert` return the channel name or a list, or record `"channel": "telegram"` only when the token is configured; otherwise record `"webhook"` and let reporting accept both. Alternatively, document the limitation in D-49's accepted risk.

### IN-04: Startup reads the Settings tab three times

**File:** `hunter.py:2007`, `hunter.py:2013`, `hunter.py:2081`
**Issue:** `main` calls `store.load_settings()` for `Settings.from_values`, again for `settings_notes`, and now a third time for `groq_budget_note`. Each is a Sheets read counted against the per-minute read quota, which this project already measures (`sheets_reads`).
**Fix:** Load once (`raw_settings = store.load_settings()`) and pass it to all three.

### IN-05: Alert cutoff is a constant with no ordering check against the configurable eval cutoff

**File:** `hunter.py:388-390`, `pipeline.py:48`
**Issue:** `EVAL_CUTOFF_MINUTES` and `POLL_CUTOFF_MINUTES` are free environment knobs with only a one-minute floor. An `EVAL_CUTOFF_MINUTES` of 22 or more defers every alert for jobs scored near the cutoff on every such run, and a poll cutoff above the eval cutoff is allowed. D-51 documents "keep EVAL below 22" as a convention only.
**Fix:** In `Config.from_env`, clamp `eval_cutoff_s` below `pl.ALERT_CUTOFF_S` and `poll_cutoff_s` to at most `eval_cutoff_s`, and log a config note when clamping.

### IN-06: Stored-URL fallback in `tracker_join` can pair two distinct ledger jobs with the same tracker row

**File:** `reporting.py:~826-850` (`tracker_join`)
**Issue:** `by_url.setdefault(u, key)` keeps the alphabetically first key per URL. If two ledger jobs share a stored URL, for example a search result that stored a careers-page URL, every tracker row with that URL maps to one key. That can hide a "missing from tracker" job and inflate `duplicate_rows`. It is labelled a diagnostic only and it is not used for identity or dedupe, so AGENTS rule 3 is respected. The risk is a wrong reconciliation line, not wrong behavior.
**Fix:** In the fallback, skip any URL that more than one ledger key stores (count it as `unmatched`), instead of picking the first.

---

_Reviewed: 2026-10-28_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
