---
phase: 02-measurement-governors-and-owner-decisions
plan: 07
subsystem: deployment-live-verification
tags: [deploy, pilot-log, status, live-evidence, delivery-test, meas-01, meas-03, meas-04, meas-05]

requires:
  - phase: 02-measurement-governors-and-owner-decisions
    provides: "D-49..D-52 code and offline tests (plans 02-02..02-06), 620 tests passing"
provides:
  - "Phase 2 code deployed to production by pushing main (fc197c1, 2026-10-26 18:25 UTC)"
  - "PILOT_LOG timeline row for the deployment with the measurements that are not comparable across it"
  - "STATUS section 'Phase 2 live verification (2026-10-26)': each check labelled live, mocked or owner check pending, with run ids"
affects: [02-08, 02-09, pilot, status]

actuals:
  tokens: 9000
  tasks: 3
  commits: 1
plan_head_before: fc197c1735f948c791ff619ac2f96c60fd61ab22
plan_head_after: f4a989bf1ff61a881c1f724cd20db8f108520338

tech-stack:
  added: []
  patterns:
    - "Live evidence is read only from public Actions logs via gh; Sheet-only checks stay with the owner (AGENTS rule 5)"
    - "Log excerpts copied into public docs are counts, run ids, job keys and setting names only, after a secret-pattern scan"

key-files:
  created: []
  modified:
    - PILOT_LOG.md
    - STATUS.md

key-decisions:
  - "No new decision record: this plan deploys D-49..D-52 and records evidence"
  - "The Groq budget note with its source is Runs.Notes only (not in the public log), so its source (default) is recorded as inferred, not verified live"
  - "The delivery test's telegram_sent is recorded as live for the send path; arrival and an uncut message stay an owner check"

requirements-completed: [MEAS-01, MEAS-03, MEAS-04, MEAS-05]

coverage:
  - id: D1
    description: "Phase 2 code deployed (push of main) after the owner's decision, with a PILOT_LOG boundary row"
    requirement: "MEAS-05"
    verification:
      - kind: command
        ref: "git fetch origin main && test origin/main = HEAD; grep -c 'D-49), Groq daily token budget (D-50)' PILOT_LOG.md"
        status: pass
    human_judgment: false
  - id: D2
    description: "First production run on fc197c1 (40382764588) concluded success with no cutoff note; pilot report 40384832233 prints the Groq and governor lines and the reconciliation's missing key; Code_Version fc197c17 recorded"
    requirement: "MEAS-03"
    verification:
      - kind: live-log
        ref: "gh run view 40382764588 --log; gh run view 40384832233 --log"
        status: pass
    human_judgment: false
  - id: D3
    description: "Dashboard render in the real Sheet (new top chart, band at 20 and 30, TRACKER ROWS table, Groq line), Runs row cell values and Notes, NEEDS ATTENTION row, Telegram message arrival and uncut text"
    requirement: "MEAS-01"
    verification: []
    human_judgment: true
    rationale: "These live inside the Google Sheet and the owner's Telegram chat; the agent has no Sheet credentials and cannot see the chat (AGENTS rule 5). Four owner checks are listed in STATUS."
  - id: D4
    description: "One labelled delivery test (40385017743): telegram_sent true, tracker_row_appended true"
    requirement: "MEAS-05"
    verification:
      - kind: live-log
        ref: "gh run view 40385017743 --log (telegram_sent line)"
        status: pass
    human_judgment: true
    rationale: "telegram_sent records that the channel accepted the message; only the owner can confirm it arrived and no line was cut"

duration: "about 1 h (continuation from the push at 18:25 UTC; about 35 min was waiting for the 19:00 hourly run)"
completed: 2026-10-26
status: complete
---

# Phase 2 Plan 07: Deploy and live verification Summary

**Phase 2 governors pushed to production (fc197c1); first production run, a read-only pilot report and one labelled delivery test confirm the new code runs and records without any cut or failure, while the Sheet render and Telegram arrival remain owner checks.**

## Owner decision (Task 2)

Owner's reply, verbatim: "deploy-with-delivery-test". The owner was told before answering that the push publishes the roughly 53 `.planning/` files to the public repo and touches `.github/workflows/job_hunter.yml` (needs `workflow` scope).

## Task 1 (pre-deploy gate, no artifacts, no commit)

620 tests OK offline; secret scan of `git diff origin/main..HEAD`: 0 matches outside `.planning/`, 3 known false positives inside `.planning/` (placeholder `bot123456:ABC...` in 02-02-PLAN.md and the literal scan pattern in 02-07-PLAN.md); no forbidden files in the outgoing list; origin/main aa1bab2, local fc197c1, 50 commits, 72 files. Before pushing, HEAD was re-checked: still fc197c1, origin still aa1bab2, token has `workflow` scope.

## Task 3 (push and live evidence)

- **Push:** plain `git push origin main` (no force): `aa1bab2..fc197c1` at 2026-10-26 18:25 UTC. Not refused.
- **First production run on fc197c1:** run 40382764588, started 19:00:09 UTC (the next hourly dispatch; none ran between the push and then), about 12.5 min, workflow `success`. Log: `boards 699 ok / 1 failed of 700, new jobs 92 (84 verified fresh), evaluated 11, alerts 0 sent / 0 failed`; no poll / evaluation / alert cutoff note, no budget-reached note. Log line `groq budget 2026-10-26 UTC: openai/gpt-oss-120b 30826/170000, openai/gpt-oss-20b 0/170000`. Secret-pattern scan of the full log: 0 matches.
- **Pilot report:** run 40384832233 (read-only), `success`. Groq calls 307, 0 HTTP 429; primary tokens 30,826 over 1 run that recorded tokens; tokens per scoring call 3082.6 (n=10, one run only: too few to use); governors all 0; `Code_Version` fc197c17 recorded for 1 run; all 206 runs in the window `ok`; latest `x-ratelimit-*` values printed. Reconciliation: tracker 97 rows (2 fixtures plus 95 real), 55 ledger-kept in the window and 54 in the tracker; one ledger-kept job missing: `greenhouse|nadiacare|4459849009`, evaluated 2026-10-23T02:00:32Z (STATUS had recorded 2 on 2026-10-25; one tracker row is now matched by exact stored URL, which probably explains the drop, not confirmed).
- **Delivery test:** run 40385017743 (one, as authorized), `success`; JSON line `telegram_sent: true`, `tracker_row_appended: true`, label `TEST FIXTURE (not a real job)`. It added a third labelled fixture row to the tracker (reports exclude fixtures).
- **Records:** PILOT_LOG timeline row (18:25 UTC, fc197c1) and STATUS `## Phase 2 live verification (2026-10-26)` with the check table and four owner Sheet checks; three stale statements in the Phase 2 STATUS section corrected ("nothing verified live", "not yet deployed", the not-verified-live table row). Committed `f4a989b` and pushed (origin/main equals HEAD).

## Live versus not live

- **Live (public logs, run ids above):** the push and deployment time; production run `success` with no cut; budget persistence and values in force; Groq and governor lines in the pilot report; `Code_Version` and outcome counts read from the Sheet by the report; reconciliation's missing key; `telegram_sent: true`.
- **Owner check pending (inside the Sheet or Telegram):** Dashboard render and `BAND_LINES_STACK` assumption A7; the newest Runs row's cell values and Notes; the NEEDS ATTENTION row; whether the Telegram test arrived uncut; whether the missing tracker row was deleted by hand.
- **Still mocked:** the 15 / 20 / 22 minute cutoffs, budget skip, fallback model, alert deferral and the five-attempt bound (nothing was cut in the run on the new code, so the governors never fired).

## Deviations from Plan

### Auto-fixed Issues

None.

### Findings that differ from the plan's assumptions (no code changed, AGENTS rule 7)

1. The plan expected the `Groq daily token budget ... from ...` note in the run log. `hunter.groq_budget_note` is appended to the run's notes after the settings notes are logged (`hunter.py` lines 2018 and 2079), so the note (value and source) reaches `Runs.Notes` only. The log shows the value in force (170000 / 170000, the default) through the `groq budget ...` line instead. STATUS records the source as inferred and the note as an owner check. Logging the note publicly would be a small follow-up for a later plan, not done here.
2. The delivery test also appends a labelled fixture row to the tracker (`tracker_row_appended: true`); reports exclude it, the owner may want to delete it.

**Total deviations:** 0 auto-fixed; 2 findings recorded. **Impact:** none on the plan's goal.

## Authentication Gates

None. The token had the `workflow` scope and the push was accepted.

## Known Stubs

None (documentation only).

## Threat Flags

None (no code or endpoints changed).

## Issues Encountered

None blocking. The first production run on the new commit appeared at 19:00 UTC, 35 minutes after the push, because the hourly dispatch runs on the hour.

## Observations carried forward (not acted on)

- Events rows are 189,830, close to the D-03 200k review point (plan 02-08).
- The Groq console shows `x-ratelimit-limit-tokens=8000` (a per-minute figure) for gpt-oss-120b; the daily budget does not govern it.
- Tokens per scoring call needs a day or more of runs before it is a usable figure (plan 02-08).

## Next Phase Readiness

Plan 02-08 (read the Groq console and the first day of tokens per call, the Events 200k point) and plan 02-09 (SmartRecruiters parking) can start once the owner has answered the Sheet checks in STATUS (or asked for gap-closure items).

## Self-Check: PASSED

- PILOT_LOG.md and STATUS.md modified and present: FOUND
- Commit f4a989b is an ancestor of HEAD and equals origin/main: FOUND
- `grep -c "D-49), Groq daily token budget (D-50)" PILOT_LOG.md` = 1; `grep -c "## Phase 2 live verification" STATUS.md` = 1
