---
phase: 03-compact-storage
fixed_at: 2026-11-15T00:00:00Z
review_path: .planning/phases/03-compact-storage/03-REVIEW.md
iteration: 1
findings_in_scope: 1
fixed: 1
skipped: 0
status: all_fixed
---

# Phase 3: Code Review Fix Report

**Fixed at:** 2026-11-15
**Source review:** .planning/phases/03-compact-storage/03-REVIEW.md
**Iteration:** 1 (this `--fix` run: WR-07 only; WR-06 and WR-01..WR-05 were fixed by earlier runs and are kept below)

**Summary:**
- Findings in scope: 1 (WR-07; WR-01..WR-06 were already resolved and were not touched, the ten INFO findings IN-01..IN-10 were out of scope and stay open)
- Fixed: 1
- Skipped: 0

**Deployment.** Commit 9fd3383 is on the branch `gsd/phase-03-compact-storage` only. Nothing was pushed and no GitHub workflow was dispatched. Production does not have it until the owner consents to a deploy.

**Verification.**
- All checks are MOCKED (AGENTS rule 5): the Sheets fake in `tests/fake_sheets.py`, the CSV store and hand-built ledgers. Nothing touched the real Sheet, Groq or Telegram.
- The two new tests fail on the pre-fix `compact.py` and `parity.py` (stashed, run, restored) and pass after them.
- `.venv/bin/python -m unittest discover -s tests` printed `Ran 937 tests ... OK` (934 before WR-07).
- Where it ran: in the main checkout (`/Users/aphan/auto_search_workflow`) on the branch, with the project `.venv` interpreter, so it is reproducible from the tree you are looking at. No worktree was created.

## Fixed Issues

### WR-07: The high-water mark counts duplicate Identity entries, so repairing `identity_duplicate` becomes a permanent `identity_shrunk`

**Files modified:** `compact.py`, `parity.py`, `tests/test_storage_parity.py`, `SPEC.md`, `DECISIONS.md`, `STATUS.md`
**Commit:** 9fd3383
**Status:** fixed: requires human verification (a logic change to what the check counts and records; tests cover the paths, but nobody has run it against a real Sheet)
**Applied fix:**
- Approach chosen by the orchestrator, the first of the reviewer's two options: the Identity count behind the WR-02/WR-06 mark and behind the `identity_shrunk` comparison is the number of distinct (stem, posting ID) pairs, the identity the dedupe uses (AGENTS rule 3), not the raw entry sum. The reviewer's alternative (skip the raise when the check was dirty) was not taken.
- New `IdentitySet.distinct_count()` in `compact.py` counts the pairs from the set's own per-stem ID index (`_kinds`, built with `decode_entry`, so duplicates collapse). An entry with no posting ID after its kind letter counts for nothing. Rows that did not parse are not in the set (they are counted separately as `identity_unreadable`), and `decode_entry` never raises, so nothing can crash the count.
- `parity._identity_invariants` now returns the distinct count (it feeds `compared["identity_entries"]`, and through it `record_compact_check`), and `parity._identity_loss` compares the distinct count with the recorded mark. The codec `Count` invariant (`identity_count`) is unchanged and still compares `Count` with the entries of its own row. The WR-06 high-water-mark code in `record_compact_check` is unchanged (never lowered automatically, no acknowledgement input, AGENTS rule 7).
- Effect: a duplicate is counted `identity_duplicate` and does not raise the mark. Removing it, the correct repair, leaves the distinct count at the mark, so the next check counts 0.
- Docs changed in the same commit (AGENTS rule 1): SPEC.md compact-mode integrity check paragraph, DECISIONS.md D-57 (the WR-02/WR-06 sentence), STATUS.md (a WR-07 row labelled **mocked**, not deployed; test count 937).
- Deploy continuity: production (68a7253) has never written `last_check.identity_entries` (the key was added on this branch by WR-02), so no raw count is stored anywhere and the first compact check after a deploy records the distinct count. Because of that no migration code was added. If a raw figure higher than the distinct count had ever been recorded the mark would be stuck high, but that cannot happen in production. The parity report's `compared: identity_entries` figure now means distinct IDs; it equals the raw sum when there is no duplicate.
- Tests (`tests/test_storage_parity.py`; no WR-06 test relied on raw counts, so none was adjusted):
  - `IntegrityCheckTests.test_the_identity_count_is_distinct_posting_ids_so_a_duplicate_neither_raises_the_mark_nor_makes_its_removal_a_shrink`: a duplicate leaves `compared["identity_entries"]` at 24 while the raw sum is 25 and `identity_duplicate` is counted; the same ID in another stem counts separately; a bare kind letter counts nothing.
  - `IntegrityCheckTests.test_removing_a_duplicate_is_not_counted_identity_shrunk_but_removing_a_distinct_id_is`.
  - `IntegrityTests.test_a_duplicate_identity_entry_is_counted_and_its_removal_is_not_an_identity_shrunk` (end to end, Sheets fake): record N, inject one duplicate (counted `identity_duplicate`, run degraded, mark stays N), remove it, the next run is OK with 0 counted and the mark still N, and `--storage-parity` exits 0.
- Not covered: a multi-day run, and the pre-fix behaviour on a real Sheet.

## Previous fix run (WR-06)

The report of the earlier `--fix` run that fixed WR-06, kept unchanged. Its high-water-mark semantics stand; WR-07 above changes only which count the mark holds.

**Fixed at:** 2026-11-14 (earlier run)
**Iteration:** 1 (earlier run)

**Summary:**
- Findings in scope: 1 (WR-06)
- Fixed: 1
- Skipped: 0

**Deployment.** Commit e83d563 is on the branch only; not pushed, no workflow dispatched.

**Verification.** All checks MOCKED. `Ran 934 tests ... OK` (931 before WR-06). The three new or changed tests failed on the pre-fix `compact.py` and pass after it.

### WR-06: `identity_shrunk` is reported once, then the lowered count becomes the new reference

**Files modified:** `compact.py`, `tests/test_storage_parity.py`, `SPEC.md`, `DECISIONS.md`, `STATUS.md`
**Commit:** e83d563
**Status:** fixed: requires human verification (a logic change to what the check records; tests cover the paths, but nobody has run it against a real Sheet)
**Applied fix:**
- Owner decision (via the orchestrator): high-water mark only, no new owner input. `StorageState.record_compact_check` now stores `max(previous or 0, identity_entries)` when this check counted Identity, and keeps the previous figure when it did not (a failed check). A lower count never replaces the mark.
- Effect: an Identity loss nobody repairs is counted `identity_shrunk` on every compact check, keeps the run degraded and, through the existing WR-05 gate, holds the fold back until the missing IDs are restored to Identity (for example from `Events_Legacy`). This is the same reported-every-run behaviour `tally_negative` has. A count that grows back to or above the mark counts 0 and raises the mark. The first check after a deploy (no recorded count) records the current count, unchanged.
- No `--storage-ack-identity` flag, workflow input or other acknowledgement mechanism was added (AGENTS rule 7). The reviewer's suggested acknowledgement step was deliberately not taken.
- Docs changed in the same commit (AGENTS rule 1, because this deliberately changes documented behaviour): SPEC.md compact-mode integrity check paragraph, DECISIONS.md D-57 (the WR-02 sentence about the lower count becoming the reference, with the WR-06 reasoning), STATUS.md (a WR-06 row labelled **mocked**, not deployed, and the cost).
- The cost, as written in STATUS.md: a loss nobody repairs keeps runs degraded, the fold stopped and `Events` growing. The repair is restoring the missing IDs to Identity. There is no automated way to accept a loss, so a deliberate Identity rebuild needs a code or state change first.
- Tests (`tests/test_storage_parity.py`):
  - `test_an_id_that_only_identity_holds_and_was_removed_is_counted_identity_shrunk_on_the_next_run` now asserts the mark stays at `recorded` (it asserted `recorded - 1`), and that `--storage-parity` still exits 1.
  - New `test_a_loss_nobody_repairs_is_counted_on_every_later_check_and_a_grown_count_clears_it_and_raises_the_mark`: three later runs each count `identity_shrunk` and stay degraded; after the ID is restored the run is OK, counts 0 and the mark holds at the restored count; `--storage-parity` exits 0.
  - New `test_the_recorded_identity_count_is_a_high_water_mark` (unit): first check records the current count, a fall does not lower it (twice), a failed or uncounted check keeps it, equal keeps it, a higher count raises it.
  - New `test_a_first_check_with_no_identity_count_to_record_records_none`.
- Not covered: the fold actually being held back for several days by a persistent `identity_shrunk` is covered by the existing WR-05 gate tests plus this change (the check counts it every run); I did not add a multi-day end-to-end test.

## Previous fix run (WR-01..WR-05)

The report of the earlier `--fix` run, kept unchanged except where marked. Its WR-02 note about the lower count becoming the reference is superseded by WR-06 above.

**Fixed at:** 2026-11-14 (earlier run)
**Iteration:** 1 (earlier run)

**Summary:**
- Findings in scope: 5 (WR-01..WR-05; the six INFO findings were out of scope and stay open)
- Fixed: 5
- Skipped: 0

**Deployment.** Production runs `main` in compact mode (the cutover ran 2026-11-02 and `fold.first_day` is already set by the 2026-11-03 fold). These commits are on the branch `gsd/phase-03-compact-storage` only. Nothing was pushed and no GitHub workflow was dispatched. The fixes reach production only through a later deploy that the owner consents to.

**Verification.**
- Every fix has an offline test that failed on the pre-fix code and passes after. For each fix I stashed the source change, ran the new tests and saw them fail, then restored it.
- Everything is MOCKED (AGENTS rule 5): the Sheets fake in `tests/fake_sheets.py`, the CSV store and hand-built ledgers. Nothing touched the real Sheet, Groq or Telegram.
- `.venv/bin/python -m unittest discover -s tests` printed `Ran 931 tests ... OK` after the last commit (910 before the fixes). It was also green after each fix commit.
- The runs happened in the isolated worktree `.claude/worktrees/rf-03-*`, using the main checkout's `.venv` interpreter. The worktree has no `.venv` of its own. The numbers can be reproduced from the main checkout once the branch is fast-forwarded.
- SPEC.md and DECISIONS.md D-57 were updated in the same commit as each behavior change (AGENTS rule 1). None of the five fixes contradicts SPEC or DECISIONS. Each refines a documented behavior. STATUS.md has a dated note that the fixes are mocked and not deployed.

**Earlier run, fixed issues:**

### WR-01: A fold that deleted rows but did not record `first_day` leaves the restore guard open

**Files modified:** `compact.py`, `pipeline.py`, `state.py`, `hunter.py`, `tests/test_storage_cutover.py`, `SPEC.md`, `DECISIONS.md`
**Commit:** a2247a9
**Status:** fixed: requires human verification (a logic and ordering change; tests cover the paths, but nobody has run it against a real Sheet)
**Applied fix:**
- The reviewer suggested setting `first_day` before the delete. I did not do that, because it would set `first_day` for a fold that deleted nothing, for example when the pre-delete freshness check refuses.
- `storage_fold` now writes a separate marker, `fold.started_day`, with a `save` callback before the first delete request. If that save fails the fold is skipped for the run: nothing was deleted, and `storage write failed` degrades the run.
- `--storage-restore` refuses on `first_day` or `started_day`.
- `compact.fold_record` turns the marker into `first_day` when a fold ends cleanly, even one that finds nothing left to delete (the reviewer's second path). The marker is gone from the result.
- `SheetState.fold_events` and `CsvState.fold_events` set `fold_touched` just before the first request. A failure with `fold_touched` False proves nothing was sent, so the marker is taken back (best effort) and the restore stays possible. A failure after a request went out keeps the marker, because the reply may have been lost with the rows already gone.
- Tests:
  - A fold that fails after its first batch closes the restore until a fold ends cleanly.
  - A fold whose record save failed gets `first_day` from the next run.
  - A refusal before any request leaves no marker and the restore possible (`first_day` unset).
  - A marker that cannot be saved skips the fold.
  - A `fold_record` unit test for the marker.
  - The earlier test that locked in `fold == {}` after a half-folded run now expects the marker.
- Known residual: a partial fold that fails does not add its confirmed deletions to `rows_total`. Only the restore guard, not the count, is exact. The reviewer mentioned the undercount, and it is cosmetic.

### WR-02: The compact integrity check cannot detect Identity loss, and `ensure()` quietly recreates a deleted Identity tab

**Files modified:** `compact.py`, `parity.py`, `pipeline.py`, `state.py`, `hunter.py`, `tests/test_storage_parity.py`, `SPEC.md`, `DECISIONS.md`
**Commit:** 58d9ec2
**Status:** fixed: requires human verification (new refusal in `ensure()` and a new counted-difference class)
**Applied fix:** all three parts of the suggestion.
1. `last_check.identity_entries` is recorded by every compact check. `parity.check_compact` takes `identity_entries_before` and counts a smaller entry count as `identity_shrunk` (numbers only). `--storage-parity` uses the same recorded figure.
2. `load_ledger` counts Identity rows that hold something but did not parse (`Ledger.identity_unreadable`). The check counts them as `identity_unreadable`. Blank rows are not counted.
3. `SheetState.ensure()` and `CsvState.ensure()` raise, like the missing-`Events` guard, when the stored mode is `compact`, `Events_Legacy` exists and the Identity or Tally tab is missing. The message names `Events_Legacy` as the recovery source. `dual` and `restored` keep create-if-missing, because Events can rebuild the tabs there.
- Tests: the pure `identity_shrunk` and `identity_unreadable` checks; end-to-end, a removed baseline-only ID (which no kept Events row could name) and an unreadable row, each counted on the next compact run; a missing Identity or Tally tab refused in Sheet and CSV with nothing created; restored mode still recreates.
- Two existing assertions changed legitimately. Hand-removing a kept key's Identity entry is now also a shrunk Identity, so that scenario counts 2 differences (`identity_missing` and `identity_shrunk`), not 1.
- Behavior to know:
  - **Superseded by WR-06 (see above):** `identity_shrunk` was reported for the run that sees it, and the lower count then became the reference (I followed the reviewer's "compare against the previous value"). It does not stay flagged. A high-water mark would flag forever with no way to reset it.
  - The first compact check after deploy has no recorded count, so shrink detection starts from the second check.
  - With a missing tab in compact mode, every run now stops at `ensure()` until the tab is restored.

### WR-03: A Tally write failure in compact mode becomes a permanent undercount (AGENTS rule 4)

**Files modified:** `compact.py`, `pipeline.py`, `tests/test_storage_cutover.py`, `SPEC.md`, `DECISIONS.md`
**Commit:** 024319f
**Status:** fixed: requires human verification (new persisted field and run-start ordering)
**Applied fix:**
- I took the reviewer's first option: carry the row. The alternative, writing Tally before Identity, would not have worked, because the next run would observe nothing for the jobs already in Events and the repair would again write a shorter row.
- A failed `append_tally` keeps the `TallyRow` (counts only, no key, title or URL) as `storage.pending_tally`, at most 20 rows, and saves the `storage` key. It does so only after the Discovery body was loaded, so it never overwrites keys the run did not see.
- At run start, before `repair_plan`, the carried rows are appended and the key is cleared.
  - A row whose (`Run_ID`, `Run_At`) group is already in the snapshot is dropped, not written twice. That covers an append that went through while the clearing save was lost.
  - The snapshot learns the written rows, so the repair and the check see the group.
  - If the append fails again, the rows stay, and the repair is prevented from writing a shorter row for a waiting group.
- Tests:
  - A run that baselines a new board and sees one gated job: the carried row has total 3, and the next run writes total 3 once. The repair alone would have written 1.
  - An already-written carried row is not duplicated.
  - A still-failing append keeps the rows.
  - A healthy run carries nothing and leaves no `pending_tally` key.
  - The carry is bounded and malformed entries are ignored.
- Residual: if the `storage` key itself cannot be saved at the moment of the Tally failure, the row is lost as before (the run note `storage write failed` remains).

### WR-04: `write_identity` rewrites rows from its in-memory cache without checking the sheet

**Files modified:** `state.py`, `tests/test_compact.py`
**Commit:** 6648949
**Status:** fixed: requires human verification (error-path behavior)
**Applied fix:**
- `SheetState.write_identity` now drops `self._identity` on any exception and re-raises. The next call re-reads only the Identity tab through the new `_load_identity` helper, which `load_ledger` also uses, so it does not reload Events and Tally. The plan is then built from what the sheet holds.
- The CSV store is unchanged: it replaces the file atomically, so it has no lost-reply case.
- Tests:
  - A `batch_update` the sheet applied with the reply lost (`TimeoutError`): the next write no longer drops the earlier entries.
  - An `append_rows` that went through with the read-back failed: no second row for the same chunk.
  - The existing "failed request leaves the cache equal to the sheet" test now asserts the cache is dropped and the redo is still idempotent.
- No SPEC or DECISIONS text described this internal detail, so none changed.

### WR-05: The fold does not consult the integrity check the same run just ran

**Files modified:** `pipeline.py`, `tests/test_storage_cutover.py`, `SPEC.md`, `DECISIONS.md`
**Commit:** 8b02697
**Status:** fixed: requires human verification (changes when the destructive step runs)
**Applied fix:**
- `storage_check` now returns its counted differences (a check that raised counts 1). The fold runs only when that value is 0.
- A check that counted a difference skips the fold with the note `storage fold skipped: integrity check counted N differences`. A check that raised or did not run also skips it. Nothing is recorded, `fold.last_day` stays unset, and the next clean run folds. Declared differences do not hold it back.
- Tests:
  - An Identity ID removed, a Tally group removed, a Tally count lowered, and a check that raised all skip the whole fold, with no deletes.
  - A declared-only report does not skip it.
  - The next clean run folds everything, including rows that had been durable the day before.
- Three existing pipeline tests asserted per-key partial folding while the check was inconsistent (3 rows folded, 1 kept). They are rewritten, because the check now runs first and sees every one of those damages. The per-key durability rule itself stays pinned by the unchanged `FoldPlanTests` unit tests.
- Behavior to know: a difference that nobody repairs, such as a lowered `Tally` count (which is reported on every run), now holds the fold back, and `Events` grows until someone repairs it. This is the trade the review proposed, and SPEC and DECISIONS state it.

---

_Fixed: 2026-11-14_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
