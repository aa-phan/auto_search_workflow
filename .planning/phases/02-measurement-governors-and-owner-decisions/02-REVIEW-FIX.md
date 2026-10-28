---
phase: 02-measurement-governors-and-owner-decisions
fixed_at: 2026-10-28T22:30:00Z
review_path: .planning/phases/02-measurement-governors-and-owner-decisions/02-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 4
skipped: 0
status: all_fixed
---

# Phase 2: Code Review Fix Report

**Fixed at:** 2026-10-28
**Source review:** .planning/phases/02-measurement-governors-and-owner-decisions/02-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 4 (fix_scope `critical_warning`: 0 critical, 4 warning; the 6 Info findings IN-01 to IN-06 were out of scope and not touched)
- Fixed: 4
- Skipped: 0

## Fixed Issues

### WR-01: Persisted "spent per Groq" flag outlasts Groq's rolling window

**Files modified:** `eval_budget.py`, `hunter.py`, `reporting.py`, `tests/test_governors.py`, `tests/test_hunter.py`, `tests/test_reporting.py`, `DECISIONS.md`
**Commit:** 60c6ad1
**Status:** fixed: requires human verification (logic change)
**Applied fix:** A daily-limit 429 now records an expiry (`exhausted_until`, ISO instant) next to the existing `exhausted` list. The lock lasts as long as Groq's own `retry-after` (capped at 24 h), or one hour when Groq gave no usable wait (`hunter._daily_lock_until`). `GroqBudget.exhaust(model, until=None)` stores it; `eval_budget.still_spent` drops expired locks when the budget is restored at the start of each run, and `reporting._budget_today` uses the same helper so the dashboard stops showing SPENT after the expiry. A record with no expiry (an older record, or a naive/unreadable timestamp) still locks until the UTC day ends, and the UTC-midnight rollover remains the upper bound. The persisted JSON only gains the `exhausted_until` key when an expiry exists, so the existing `{"day","used","exhausted","budgets"}` shape is unchanged otherwise.
**Not applied:** the review's second suggestion, narrowing `_is_daily_limit` so a long `retry-after` alone does not count. D-50 documents that detector explicitly (retry-after over 60 s, or per day / TPD / RPD wording). With the expiry in place the lock is now exactly as long as Groq's own wait, so the overlong-lock harm is gone without changing the documented detector.
**Docs:** D-50 "Counting basis" gets an amendment sentence (consistent with D-53's rolling window; no D-53 headroom or budget value changed). In-run behavior is unchanged: a model locked during a run stays locked until the next run restores the budget.

### WR-02: Bot token can reach the log through the uncaught exception in `--delivery-test`

**Files modified:** `hunter.py`, `tests/test_pilot.py`
**Commit:** 5c6ae3f
**Applied fix:** `run_delivery_test` now wraps `send_alert` in `try/except Exception`, logs `Delivery test: send failed: <pl.redact(...)>` with the Telegram token, chat id and webhook URL as secrets, and returns 1 instead of letting the traceback escape. A new offline test raises an error containing the bot-token URL and asserts the token is absent from the log and the return code is 1. The existing `tests/test_pilot.py` `cfg()` helper was changed to accept a `telegram_token` override.

### WR-03: A mistyped or unparseable budget silently becomes the default while `Runs.Notes` claims it came from the Settings tab

**Files modified:** `hunter.py`, `tests/test_hunter.py`
**Commit:** 0878ce6
**Applied fix:** `_int_or` now also catches `OverflowError` (`"inf"` no longer ends the run as "Startup failed"). The budget settings accept thousands separators such as `150,000` (only the strict `1,234,567` pattern; `1,5` is still unreadable). `groq_budget_note` now detects an unreadable Settings or environment value and says `<source> value 'X' is not a number, default 100000 in force` instead of "from Settings tab"; an unreadable fallback value is named too ("the primary budget applies to both models"). The note text for valid values is unchanged. The thousands-separator acceptance is the review's "optional" part; it is a small parsing leniency and does not change any default, budget or decision value.

### WR-04: Groq `json_validate_failed` response body is logged in a now-public repository

**Files modified:** `hunter.py`, `tests/test_hunter.py`
**Commit:** 3fc4e21
**Applied fix:** The invalid-JSON warning now logs only the model and the response length. The sibling `Unusable Groq response` warning logged `str(exc)`, and `parse_evaluation` quotes the first 120 characters of the model output in one message, so it now logs only the reason before the first `:`. The `Groq HTTP {code}: {resp.text[:200]}` ValueError was left as is: it is not echoed to the log (it becomes the failed outcome and goes to the private Events tab, as the review accepts). A new offline test feeds a `json_validate_failed` body and an unusable 200 body containing a marker string and asserts the marker is absent from the log.

## Skipped Issues

None.

## Verification

- Where it ran: the isolated review-fix git worktree (`.claude/worktrees/rf-02-*`, branch `gsd-reviewfix/02-*`, fast-forwarded into `main` afterwards), using the project virtualenv's Python 3.12 (`/Users/aphan/auto_search_workflow/.venv/bin/python`). The system `python3` is 3.9 without `gspread` and is not suitable for this suite.
- `python -m unittest discover -s tests`: **Ran 629 tests, OK** (621 before the fixes plus 8 new offline tests).
- All checks are mocked and offline. Nothing in this report was verified live against Sheets, Groq or Telegram; the WR-01 lock expiry in particular follows the `retry-after` header as the mocked tests supply it, and has not been seen against a real Groq daily-limit 429.
- Info findings IN-01 to IN-06 (including the stale "15% headroom" wording and the SPEC layout claim) were out of scope for this run and remain open.

---

_Fixed: 2026-10-28_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
