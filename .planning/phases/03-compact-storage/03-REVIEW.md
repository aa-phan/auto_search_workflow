---
phase: 03-compact-storage
reviewed: 2026-11-16T00:00:00Z
depth: standard
files_reviewed: 6
files_reviewed_list:
  - DECISIONS.md
  - SPEC.md
  - STATUS.md
  - compact.py
  - parity.py
  - tests/test_storage_parity.py
findings:
  critical: 0
  warning: 1
  info: 11
  total: 12
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-11-16
**Depth:** standard (incremental re-review: `git diff b79be48 HEAD` for fix commit e86993e (WR-09) and its doc changes, each hunk read in its surrounding code: `compact.IdentitySet` (`__init__`, `_reindex`, `copy`, `keys`, `kind`, `__len__`, `distinct_count`, `plan_additions`), `compact.entry_well_formed`, `StorageState.last_identity_entries` / `record_compact_check`, `parity._kept_in_identity` / `_identity_invariants` / `_identity_loss` / `check_compact`, and every caller (`pipeline.py:234,250`, `hunter.py:2025`, `storage_report`))
**Files Reviewed:** 6
**Status:** issues_found

## Summary

**WR-09 is resolved.** The count is now `len(IdentitySet.keys())`, computed in one place, and the check and the dedupe agree by construction. The malformed-entry hole is closed: a lone `xB` entry counts 1, deleting it is a counted `identity_shrunk` on every later check, and rewriting an entry without changing its key (`bB` to `xB`, `b%2c` to `b%252c`) changes no count. The per-stem `_valid` record and its upkeep are gone, `__len__` returns the same value as before, `_identity_loss` takes the figure `_identity_invariants` already computed (this also settles the "computed in two places" half of IN-11), and `compared["identity_entries"]` is always set before `_identity_loss` reads it. `.venv/bin/python -m unittest discover -s tests`: `Ran 942 tests ... OK`, matching STATUS. The tests pin the lone `xB`, the mixed entry, `copy()`, deletion versus rewrite, and an integration path through the poller and `--storage-parity`. Docs (SPEC, D-57, STATUS) match the code, label every check mocked and not deployed, and make no live Sheets, Groq or Telegram claim. No rule 1 conflict.

**One new WARNING (WR-10).** The new rule says the repair of an `identity_entry` is to rewrite the entry to canonical form, never delete it. For an entry with no posting ID (a bare kind letter such as `b` or `x`) there is no canonical form to rewrite to, and the empty key it contributes (`stem|`) can never match a posting, because `stem_and_id` returns None for an empty ID. The only possible repair, deletion, is a permanent `identity_shrunk`. No new INFO items. IN-01..IN-11 are carried forward; IN-10 and IN-11 have updated text.

Resolved:

| Earlier finding | Fix commit | Verification |
|---|---|---|
| WR-01 restore guard open after a partial fold | a2247a9 | `storage_fold` saves `fold.started_day` before the first delete and skips the fold for the run if that save fails. `fold_record` turns the marker into `first_day`. `hunter.run_storage_restore` refuses on either field. `fold_touched` is set before the first request. The marker is taken back only when no request went out. |
| WR-02 Identity loss undetected, `ensure()` recreates an empty tab | 58d9ec2 | `ensure()` refuses a missing Identity or Tally tab in compact mode. `identity_shrunk` and `identity_unreadable` are counted. The one-shot weakness was WR-06, now fixed. |
| WR-03 Tally write failure became a permanent undercount | 024319f | `carry_tally` stores the counts-only row in `storage.pending_tally`. It is written at the next run start and deduplicated against the snapshot. See IN-08. |
| WR-04 stale Identity cache overwrote the sheet | 6648949 | `write_identity` drops the cache on any exception and re-reads Identity before the next plan. |
| WR-05 the fold ignored the same run's integrity check | 8b02697 | `storage_check` returns `report.counted`. The fold runs only when it is 0. |
| WR-06 `identity_shrunk` reported once, then the lower count became the reference | e83d563 | `record_compact_check` keeps `max(previous or 0, current)`. Traced for first check, failed check, growth, restore and dual modes, and every other writer. |
| WR-07 the mark counted duplicate Identity entries | 9fd3383 | `IdentitySet.distinct_count()` counts distinct `(stem, posting ID)` pairs and feeds `compared["identity_entries"]`, the mark and `_identity_loss`. Key checked against AGENTS rule 3, duplicate, cross-stem and bare-kind cases traced. |
| WR-08 the mark counted malformed Identity entries | c845065 | `compact.entry_well_formed` is the predicate `check_compact` used inline, unchanged, and `distinct_count` counts only IDs with a well-formed entry (`_valid`, kept by `_reindex`, `copy` and `apply`). Mixed entries of one ID traced, 235k IDs in 0.08 s, 939 offline tests pass, docs match. A residual remains for the other direction: see WR-09. |
| WR-09 the count excluded malformed entries the dedupe still holds | e86993e | `distinct_count` is now `sum(len(kinds))`, exactly `len(keys())`; `_valid` and its upkeep in `_reindex` and `copy` are removed, `entry_well_formed` stays only as the `identity_entry` predicate. `__len__` returns the same figure (same value as before). `check_compact` computes the figure once in `_identity_invariants`, stores it in `compared`, and `_identity_loss` takes it as a parameter (`_kept_in_identity` always sets the key, so no KeyError). Traced: `xB` alone counts 1 and deleting it is a counted `identity_shrunk`; rewriting `bB` to `xB` or `b%2c` to `b%252c` keeps the key and counts nothing; WR-08's old deletion repair now correctly shrinks. 942 offline tests pass. A residual remains for an entry with no posting ID: see WR-10. |
| IN-12 test comment claimed coverage it did not have | c845065 | The comment now says only what the fixture holds, and the WR-08 case (an unknown kind letter and a non-round-tripping escape) is in both new tests. The unit test still builds the duplicated ledger twice for a raw sum of 25 (a restated fixture, harmless). |

## Critical Issues

None.

## Warnings

### WR-10: An entry with no posting ID counts as a held key, and the only repair for it, deletion, is a permanent `identity_shrunk`

**File:** `compact.py:225-235` (`distinct_count`, with `keys()` at `:217`), `compact.py:176-188` (`_reindex`), `parity.py:324-327` (`identity_entry`), `tests/test_storage_parity.py` (the comment "a bare kind letter holds the empty key `s1|`")
**Issue:** `decode_entry("b")` returns `("b", "")`, and `_reindex` does `kinds.setdefault("", "b")`, so a bare kind letter adds the key `stem|` to `keys()` and to the figure. I confirmed: `IdentitySet.from_rows([IdentityRow("g|a", 1, "t", 2, "bA,b")])` gives `distinct_count() == 2` and `keys() == {"g|a|", "g|a|A"}`. That key is not something the dedupe can hold in any useful sense: `stem_and_id` (`compact.py:44-49`) returns None for an empty posting ID, so no job key ever equals `stem|`, and the writer never produces it (`plan_additions` skips `not entry[1:]`). The docstring and the three docs claim the figure is "exactly the set the dedupe holds" and tell the owner to repair a flagged `identity_entry` by rewriting it to canonical form. An entry with no posting ID has no canonical form. Trace:
1. A stray `b` or `x` entry (a hand edit, a cell cut mid-entry) is in `Identity`. It is flagged `identity_entry` and counted in the figure, so the mark rises by 1.
2. The owner removes it, the only possible repair.
3. The figure falls by 1, `identity_shrunk` is counted, and by WR-06 and the no-acknowledgement decision the mark never comes down: every later run is degraded, NEEDS ATTENTION, and the WR-05 gate holds the fold back with `Events` growing, for an entry that held no identity at all. The same applies to a hand-written garbage entry that nobody can map back to a real ID. The only exit is editing `storage.last_check.identity_entries` in Discovery by hand, which STATUS does not document.
The test comment and assertion (`(3, 3)`) pin the empty key as intended, so this is a decision the fix made implicitly, not an accident, and the user should confirm it. It is a false permanent alarm rather than a lost ID, so it is a WARNING and not a BLOCKER.
**Fix:** Exclude the empty posting ID from the figure and from `keys()`, in the one place both are built, so the check and the dedupe still agree: in `_reindex`, `if pid: kinds.setdefault(pid, kind)` (nothing can match the empty key, so the dedupe is unchanged). Then a bare-kind entry is flagged `identity_entry`, counts for nothing, and deleting it is not a shrink. Change the test case to `(2, 2)` for the bare-kind letter, add one that deletes a bare entry after the mark was recorded and asserts no `identity_shrunk`, and drop "exactly" from the claim only if some other key class is found that cannot match a posting.

## Info

### IN-01: `parity.py` docstring is wrong about its imports

**File:** `parity.py:3-4`
**Issue:** The docstring says the module "imports `compact` and `ledger` only (never state, pipeline or hunter)". It also imports `reporting`, `storage_report` (which imports `state`) and `boards`. There is no cycle today, but the stated invariant is false and will not protect a future change. Still open.
**Fix:** State the real constraint (no import of `pipeline` or `hunter`), or move the shared figure code so the claim becomes true.

### IN-02: Removing `Events_Legacy` silently flips a compact system back to dual writing

**File:** `compact.py:585-600` (`effective_mode`)
**Issue:** If the stored mode is compact and `Events_Legacy` is gone, the poller writes as dual. Baselines go back into Events, and the fold and the check stop. DECISIONS P3-08 describes removing `Events_Legacy` as a later owner decision "with an export plan". As written, that decision cannot be carried out without a code change. The WR-02 fix adds a related, deliberate coupling: `_compact_mode_stored` calls `effective_mode(..., legacy_present=True)`, so the `ensure()` guard also assumes the legacy tab exists. Still open.
**Fix:** Before the owner removes the tab, add a recorded state (for example `storage.legacy_retired_at` or a `--storage-retire-legacy` step) that `effective_mode` and `_compact_mode_stored` honour. Until then, note it in DEPLOY.md.

### IN-03: The workflow lets `storage_cutover` and `storage_restore` run in one job

**File:** `.github/workflows/job_hunter.yml:170-175` (and the `inputs` block)
**Issue:** The CLI makes the two flags mutually exclusive, but each is a separate workflow step guarded only by its own input. Ticking both runs the cutover and then the restore in the same dispatch. Still open (workflow unchanged).
**Fix:** Add a first step that fails when more than one of the owner-step or report inputs is true.

### IN-04: The cutover checksum covers only `key|time|event`

**File:** `compact.py:372-377` (`rows_checksum`)
**Issue:** The comment says the checksum compares "the rows it meant to copy" with the rows read back. It hashes three of the seven columns, so a changed `Freshness`, `Disposition`, `Published` or `Detail` passes. `Events_Legacy` stays whole, so this is not a data-loss path. Still open.
**Fix:** Hash `"\x1f".join(ev.to_row())` per row.

### IN-05: Dead variable and unused imports

**File:** `reporting.py:492` (`first_event`), `storage_report.py:10,18` (`json`, `fr`)
**Issue:** `first_event` is assigned and never read, and `json` and `fr` are imported and never used. Still open (neither file changed).
**Fix:** Delete them.

### IN-06: Read-only commands read three tabs sequentially without the lease

**File:** `state.py:608-621` and `state.py:893-906` (`load_ledger`), `hunter.py` (`run_storage_parity`, `run_storage_report`, `run_pilot_report`), `dashboard.py:594`
**Issue:** `load_ledger` reads Events, then Identity, then Tally with separate calls. A manual `--storage-parity` or `--dashboard` that overlaps a poller run can see Events from before the run and Tally or Identity from after it, which gives counted differences that disappear on the next run. `--storage-parity` also compares the Identity count against `last_check.identity_entries`, which a racing poller run advances. After WR-06 the mark only grows, so a racing read can only produce a false `identity_shrunk` in the direction of an old snapshot against a newer mark. Mitigated by the one-run-at-a-time concurrency group. Still open.
**Fix:** Document that a parity difference should be re-run before it is trusted, or read all three tabs in one `values_batch_get`.

### IN-07: `first_day` is dated by the fold that ends, not by the one that started

**File:** `compact.py:466` (`fold_record`)
**Issue:** `first = previous.get("first_day") or (_utc_day(now) if rows > 0 or previous.get("started_day") else "")`. When a fold fails after its first delete on day D and finishes on day D+1, `first_day` becomes D+1 although rows went on D. The restore guard is unaffected, because it also honours the marker until the fold ends. `storage_report.py:316` and `:349` read `fold.first_day` as the start of the "after the cutover and first fold" window and `first_fold_day`. The window then starts later than the truth, which is the conservative direction, but the reported `first_fold_day` is wrong. Still open.
**Fix:** Prefer the marker's day: `previous.get("first_day") or previous.get("started_day") or (_utc_day(now) if rows > 0 else "")`.

### IN-08: The Tally carry holds zero-total rows and drops the newest row when full

**File:** `compact.py:707-715` (`keep_tally`), `pipeline.py:372-383` (`carry_tally`)
**Issue:** Two small quality points on the WR-03 carry.
1. Every run appends a Tally row, including runs that observed nothing (`total` 0). `test_a_carried_row_stays_until_it_can_be_written...` shows this: the carry holds `[3, 0]`. A zero-count row has nothing to lose, because no baseline count is missing and `repair_plan` has nothing to rebuild. Carrying it spends one of the 20 slots for nothing and adds a Discovery write per failing run.
2. When the carry is full, the newest row is the one left out (`keep_tally` returns False). The newest row is the one most likely to hold fresh baseline counts, so the permanent undercount WR-03 fixed comes back after 20 consecutive failures. Realistically a Tally outage that long also fails the Discovery save that persists the carry. The cap is deliberate, so this is a robustness note, not a defect.
**Fix:** In `carry_tally`, return early when `row.total == 0`. When the carry is full, either drop the oldest zero-count row first or log and note `storage tally carry full` in `run.notes`, so the owner sees the gap. The log line is currently the only trace.

### IN-09: The new tests do not pin the claim that matters most for the fix, "the fold stays held back"

**File:** `tests/test_storage_parity.py:777-822` and `:927-958`
**Issue:** The WR-06 purpose, stated in SPEC, D-57 and STATUS, is that an unrepaired loss "holds the fold back" on every later run. The WR-06 tests assert the note, the degraded outcome, the counted figure and the mark across three runs. None asserts `storage fold skipped: integrity check counted 1 differences` or that no rows were deleted for `identity_shrunk` specifically. The code path is right: `storage_check` returns `report.counted` and `pipeline` gates on it, and `tests/test_storage_cutover.py:984-1018` cover the gate with another difference. A future change to how `identity_shrunk` counts, or marking it declared, would not fail any test that names the fold. The stray blank line in `IntegrityTests` was removed by c845065; the main point is still open, and the WR-08 integration test has the same shape (no assertion on the fold).
**Fix:** In `test_a_loss_nobody_repairs_is_counted_on_every_later_check...`, assert each degraded run's notes contain `storage fold skipped` when a fold is due, or add one test in the fold case class that removes a baseline-only ID and checks the Events row count is unchanged across two runs.

### IN-10: The documented repair path has no tooling and the mark can be stuck high by a transient over-read

**File:** `STATUS.md` (WR-06 cost paragraph), `SPEC.md:111`, `compact.py:754`
**Issue:** The docs give "restore the missing IDs to `Identity`, for example from `Events_Legacy`" as the only repair. No command does it. The poller's start-of-run repair rebuilds only Tally groups, not Identity, and `Identity` is a codec cell (chunked, escaped entries with a `Count` column), so a hand edit is error-prone, which the tests need several lines of cell surgery to do. Also, because the mark can only rise, a single over-read (a transient read that returns extra rows) leaves it stuck high for good. After WR-09 a malformed entry whose posting ID the dedupe holds raises the mark again (it is a held key), so a stray entry is another way to stick it high (see WR-10 for the entry with no posting ID). The user chose not to add an acknowledgement input, so this is only an operational cost, not a defect. It is better recorded than discovered during an incident.
**Fix:** Add a short runbook note to DEPLOY.md or STATUS ("to clear a stuck `identity_shrunk`, set `last_check.identity_entries` in the Discovery `storage` key to the true count, after confirming nothing is lost"), and consider a read-only `--storage-parity` line that prints the mark and the current count, so the owner can see which side moved.

### IN-11: The figure keeps the name "entries" and the Discovery key cannot be renamed lightly

**File:** `compact.py:756-775` (`last_identity_entries`, `identity_entries` parameter), `parity.py:107`, `:329` (`compared["identity_entries"]`), `parity.py:360` (`entries`, `entries_before`)
**Issue:** The "computed in two places" half is fixed by e86993e: `_identity_invariants` returns `distinct_count()` once and `check_compact` passes it to `_identity_loss`. What remains is naming: the persisted key, the `compared` key, the parameters and the variables all say "entries" for what is now a count of distinct held keys, and `check_compact` reads `compared["identity_entries"]` that `_kept_in_identity` writes, an implicit coupling through a dict (safe today because `_kept_in_identity` always sets it). The persisted key name is a Discovery-state contract.
**Fix:** Leave the persisted key name alone. Optionally have `_kept_in_identity` return the count instead of reading it back out of `compared`.

---

_Reviewed: 2026-11-16_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
