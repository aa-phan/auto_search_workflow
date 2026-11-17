---
phase: 03-compact-storage
plan: 10
subsystem: compact-storage-integrity
tags: [identity, high-water-mark, identity_shrunk, WR-10, gap-closure, mocked]

requires:
  - phase: 03-compact-storage
    provides: "plan 03-09 and the WR-01..WR-09 review fixes (distinct_count == len(keys()), high-water mark, no acknowledgement input)"
provides:
  - "IdentitySet._reindex keeps only non-empty posting IDs: a bare kind letter holds no key, keys() and distinct_count() leave it out (mocked)"
  - "identity_entry still flags the bare entry; deleting it, its only repair, is not a counted identity_shrunk and does not hold the fold back (mocked)"
  - "storage_report.logical_counts mirrors the rule: a bare entry is no baseline job of its board"
  - "SPEC, D-57 and STATUS state the WR-10 rule; the WR-07-era held-key clause is gone"
affects: [a later deploy of the WR-01..WR-10 review fixes, 03-REVIEW-DISPOSITION.md (re-review)]

actuals:
  tokens: 14000
  tasks: 3
  commits: 5
plan_head_before: 155a8e8beff2325221d0d398ea5707692dc9eb55
plan_head_after: 7541c53e8c0d1f681f4cba684227dd42d257281a
commits: 5

tech-stack:
  added: []
  patterns:
    - "one place computes the figure (IdentitySet.distinct_count); the fix is made where the key set is built, so keys(), the count, copy and apply all follow"

key-files:
  created: []
  modified:
    - compact.py
    - parity.py
    - storage_report.py
    - tests/test_storage_parity.py
    - tests/test_storage_report.py
    - SPEC.md
    - DECISIONS.md
    - STATUS.md

key-decisions:
  - "WR-10: skip only the empty posting ID in IdentitySet._reindex; every non-empty ID, malformed or not, stays held, so WR-09 is unchanged (deleting xB is still a counted identity_shrunk)"
  - "storage_report.logical_counts gets the same guard so its 'as in IdentitySet' comment stays true (a discretion choice the plan named)"
  - "parity._seen_set (dual-mode layer 1) is not changed: a bare entry no longer appears there as an extra key `stem|`, which has no production effect because dual mode cannot return after the first fold (P3-06, WR-01) and restored mode runs no parity check"

requirements-completed: []  # STOR-01 is a phase requirement; this plan closes gap G-3-7 (mocked) and the agent does not mark the requirement complete

coverage:
  - id: D1
    description: "A bare kind letter holds no key: poller run on the Sheets fake flags identity_entry without raising the mark; deleting it gives an ok run with 0 counted differences, the next-day fold runs and --storage-parity exits 0 (MOCKED)"
    requirement: STOR-01
    verification:
      - kind: test
        ref: "tests/test_storage_parity.py#IntegrityTests.test_a_bare_kind_letter_is_flagged_raises_no_mark_and_deleting_it_is_no_shrink_so_the_fold_still_runs"
        status: pass
    human_judgment: false
  - id: D2
    description: "Pure pins: IdentitySet.from_rows, copy and apply leave a bare entry out; check_compact flags it without raising the figure; deleting it is not identity_shrunk; the pinned (3, 3) count is (2, 2) (MOCKED)"
    requirement: STOR-01
    verification:
      - kind: test
        ref: "tests/test_storage_parity.py#IntegrityCheckTests.test_a_bare_kind_letter_holds_no_key_so_it_never_raises_the_mark_and_deleting_it_is_not_a_shrink"
        status: pass
    human_judgment: false
  - id: D3
    description: "storage_report.logical_counts counts a bare b entry for nothing: {'g|a': 1} for `bA,b` (MOCKED)"
    requirement: STOR-01
    verification:
      - kind: test
        ref: "tests/test_storage_report.py#LogicalCountsTests.test_a_bare_kind_letter_is_not_a_baseline_job_of_its_board"
        status: pass
    human_judgment: false
  - id: D4
    description: "SPEC, D-57 and STATUS describe the WR-10 rule and label it mocked and not deployed"
    requirement: STOR-01
    verification:
      - kind: command
        ref: "grep -c WR-10 SPEC.md; awk '/^## D-57/,0' DECISIONS.md | grep -c WR-10; grep -c '^| WR-10' STATUS.md = 1"
        status: pass
    human_judgment: false
  - id: D5
    description: "Behaviour against the real Sheet, Groq and Telegram, and the deploy decision for WR-01..WR-10"
    requirement: STOR-01
    verification: []
    human_judgment: true
    rationale: "Nothing was deployed or dispatched; production stays on 68a7253 until the owner consents to a deploy, so every WR-10 claim is mocked"

duration: about 20 min of agent time
completed: 2026-11-17
status: complete
---

# Phase 3 Plan 10: WR-10 bare kind letter holds no key Summary

**`IdentitySet._reindex` now skips an empty posting ID, so a bare kind letter (`b`) holds no key, is still flagged `identity_entry`, and deleting it is no longer a permanent counted `identity_shrunk` that holds the fold back (gap G-3-7 / WR-10, resolved, mocked).**

## Accomplishments

- Task 1 (tracer): RED test on the Sheets fake failed on the mark (16 != 15), then `if pid:` in `_reindex` fixed it. A bare `b` appended to the `greenhouse|acme` row degrades the run with `identity_entry 1` and leaves the mark at 15. Deleting it gives an `ok` run on the next UTC day, 0 counted differences, mark unchanged, `fold.last_day == 2026-10-20`, `--storage-parity` exit 0. The pinned pure count went from (3, 3) to (2, 2).
- Task 2: pure pins for `from_rows`, `copy`, `apply` and `check_compact`; `storage_report.logical_counts` got the same guard (the new test gave `{'g|a': 2}` before and gives `{'g|a': 1}` after); `parity._identity_loss` docstring only.
- Task 3: SPEC (integrity check paragraph), D-57 (the WR-07-era "counts like any held key" clause replaced by a WR-10 clause) and STATUS (heading, history line, WR-10 row labelled mocked and not deployed, behaviour paragraph) were updated in the same change (AGENTS rule 1).
- WR-06 and WR-09 behaviour is untouched: the high-water mark, the codec `Count` check, the lack of an acknowledgement input and IN-10 are unchanged, and the WR-09 tests (deleting `xB` is still `identity_shrunk`) pass unchanged.

## Verification

All of these are MOCKED (the Sheets fake in `tests/fake_sheets.py`, the CSV store, hand-built `IdentitySet`s). Nothing touched the real Sheet, Groq or Telegram.

- `.venv/bin/python -m unittest discover -s tests` printed `Ran 945 tests in 17.562s` and `OK` (942 before, plus 3 new tests; the plan required at least 944). STATUS quotes 945.
- Task acceptance criteria re-run: `if pid` in `_reindex` = 1, in `logical_counts` = 1, the `(2, 2)` pin = 1, `-k bare_kind_letter` runs 3 tests, `git diff` on `parity.py` is a docstring change only, `WR-01..WR-10` appears twice in STATUS, the removed phrases (`counts like any held key`, `holds the empty key`) appear in none of the five files.

## Task Commits

| Task | Commit | Type |
|------|--------|------|
| 1 RED | 559c479 | test(03-10): end-to-end bare-entry test and pinned (2, 2) |
| 1 GREEN | 389789a | feat(03-10): `_reindex` keeps only non-empty posting IDs |
| 2 RED | 0ac4de1 | test(03-10): pure pins and storage report test |
| 2 GREEN | de57002 | feat(03-10): `logical_counts` guard, `_identity_loss` docstring |
| 3 | 7541c53 | docs(03-10): SPEC, D-57, STATUS |

## Deviations from Plan

None - plan executed exactly as written. The pure `check_compact` pin in Task 2 passed on first run because the Task 1 fix already covered it, so only the storage report test was a true RED in that task.

**Total deviations:** 0.

## Dual-mode `_seen_set` consequence

`parity._seen_set` (the dual-mode layer 1) is unchanged. A bare entry no longer appears there as an extra key `stem|`. That has no production effect: dual mode cannot return after the first fold (the restore is refused, P3-06 and WR-01), and restored mode runs no parity check.

## Not pushed, not deployed, not dispatched

Nothing was pushed, deployed or dispatched: no poller, storage_parity, storage_report, cutover or restore workflow ran, and nothing touched the real Sheet, Groq or Telegram. Commits are local on `gsd/phase-03-compact-storage`. Production stays on 68a7253 until the owner consents to a deploy. WR-10 is **mocked, not deployed**.

## Open items

- `03-REVIEW-DISPOSITION.md` still lists WR-10 as open until a re-review records it fixed.
- The INFO findings (IN-01..IN-11) were not in scope and are open; IN-10's runbook line was not added.

## Known Stubs

None.

## Threat Flags

None. No new network endpoint, auth path, file access or schema change. T-03-38 to T-03-41 are mitigated as planned (T-03-40: only `pid == ""` is skipped, WR-09 tests unchanged).

## Self-Check: PASSED

- Modified files exist: compact.py, parity.py, storage_report.py, tests/test_storage_parity.py, tests/test_storage_report.py, SPEC.md, DECISIONS.md, STATUS.md.
- Commits 559c479, 389789a, 0ac4de1, de57002 and 7541c53 are on the branch; `git rev-list --count 155a8e8..7541c53` is 5.
- Full suite OK at 945 tests.
