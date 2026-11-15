---
phase: 03-compact-storage
reviewed: 2026-11-15T00:00:00Z
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
  info: 12
  total: 13
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-11-15
**Depth:** standard (incremental re-review: `git diff 12effe1 HEAD` for fix commit 9fd3383 (WR-07) and its doc changes, each hunk read in its surrounding code: `compact.IdentitySet` (`_reindex`, `_kinds`, `distinct_count`, `plan_additions`), `compact.StorageState.record_compact_check`, `parity._identity_invariants` / `_identity_loss` / `check_compact`, `pipeline.storage_check`, `hunter.run_storage_parity`)
**Files Reviewed:** 6
**Status:** issues_found

## Summary

WR-07 is fixed for the case it names. `distinct_count()` counts distinct `(stem, posting ID)` pairs, and `_identity_invariants`, `_identity_loss` and so the recorded mark all use it. I checked the key against AGENTS rule 3:

- **Key.** Identity is ATS + board + posting ID. The stem is `ats|board`, so `(stem, pid)` is the right key. `_kinds` is keyed by posting ID within a stem and `setdefault` keeps the first kind, so the same ID under two kind letters counts once, as `keys()`, `kind()` and `plan_additions` treat it. `identity_duplicate` counts by ID alone, so the two views agree. Cross-chunk duplicates collapse in `_reindex`, and `identity_duplicate` also reads all chunks of the stem.
- **Casing and normalisation.** Neither the dedupe nor the count normalises the stem or the ID, so case differences are different identities in both. That is consistent.
- **Entries with no ID.** A bare kind letter yields an empty ID and is skipped. Skipped entries are also flagged by `identity_entry`, so nothing is silently hidden.
- **Unreadable rows.** Rows with no stem or a bad chunk are not in the set, so their IDs fall out of the count and `identity_unreadable` is counted too. Unchanged behaviour.
- **A loss behind a duplicate.** The raw sum could mask a lost ID with an added duplicate. The distinct count catches it.
- **Migration.** `git log main -S identity_entries -- compact.py` finds nothing, so production has never stored the raw figure. STATUS is right that no migration is needed.

The tests pin the fix: the integration test fails against the raw sum (the duplicate would raise the stored mark) and the unit tests cover a duplicate, the same ID in two stems, a bare kind letter and removal of a distinct ID. `.venv/bin/python -m unittest discover -s tests`: `Ran 937 tests ... OK`, which matches STATUS (934 after WR-06, 937 after WR-07). The docs match the code in what they describe, label every check mocked and not deployed, and make no live Sheets, Groq or Telegram claim. No rule 1 conflict, and the codec `Count` check is unchanged.

**One new WARNING (WR-08).** The fix counts every non-empty ID, including entries that `check_compact` itself flags as `identity_entry` (unknown kind letter, non-canonical escape). Repairing one of those repeats the WR-07 failure, and the doc text claims a stricter rule than the code has. **Two new INFO items (IN-11, IN-12).** IN-01..IN-10 are carried forward; IN-09 and IN-10 have updated line references and wording.

Resolved:

| Earlier finding | Fix commit | Verification |
|---|---|---|
| WR-01 restore guard open after a partial fold | a2247a9 | `storage_fold` saves `fold.started_day` before the first delete and skips the fold for the run if that save fails. `fold_record` turns the marker into `first_day`. `hunter.run_storage_restore` refuses on either field. `fold_touched` is set before the first request. The marker is taken back only when no request went out. |
| WR-02 Identity loss undetected, `ensure()` recreates an empty tab | 58d9ec2 | `ensure()` refuses a missing Identity or Tally tab in compact mode. `identity_shrunk` and `identity_unreadable` are counted. The one-shot weakness was WR-06, now fixed. See WR-07 for a remaining edge. |
| WR-03 Tally write failure became a permanent undercount | 024319f | `carry_tally` stores the counts-only row in `storage.pending_tally`. It is written at the next run start and deduplicated against the snapshot. See IN-08. |
| WR-04 stale Identity cache overwrote the sheet | 6648949 | `write_identity` drops the cache on any exception and re-reads Identity before the next plan. |
| WR-05 the fold ignored the same run's integrity check | 8b02697 | `storage_check` returns `report.counted`. The fold runs only when it is 0. |
| WR-06 `identity_shrunk` reported once, then the lower count became the reference | e83d563 | `record_compact_check` keeps `max(previous or 0, current)`. Traced for first check, failed check, growth, restore and dual modes, and every other writer. Tests, 934 in all, pass offline. Docs match. See WR-07 and IN-09 for residual points. |
| WR-07 the mark counted duplicate Identity entries | 9fd3383 | `IdentitySet.distinct_count()` counts distinct `(stem, posting ID)` pairs and feeds `compared["identity_entries"]`, the mark and `_identity_loss`. Key checked against AGENTS rule 3, duplicate, cross-stem and bare-kind cases traced, 937 offline tests pass, docs match. A residual for malformed entries remains: see WR-08. |

## Critical Issues

None.

## Warnings

### WR-08: A malformed Identity entry still raises the mark, so removing it is a permanent `identity_shrunk` (WR-07 only fixed duplicates)

**File:** `compact.py:217-221` (`IdentitySet.distinct_count`), `parity.py:333-338` (`identity_entry` check in `check_compact`), `compact.py:759-763` (`record_compact_check`)
**Issue:** `distinct_count` counts every non-empty posting ID that `decode_entry` yields, whatever the kind letter and whatever the escaping. `check_compact` counts an entry as `identity_entry` (a Difference, run degraded, fold held back) when its kind letter is not in `DISPOSITION_OF`, its ID is empty, or `encode_entry(decode_entry(e)) != e`. Such an entry still enters `_kinds` and raises the count. I confirmed with `IdentitySet.from_rows([IdentityRow("g|a", 1, "t", 3, "bA,xB,b%2c")]).distinct_count()`, which returns 3 for one valid entry (`bA`), one with an unknown kind letter (`xB`) and one non-canonical escape (`b%2c`). The WR-07 trace then repeats:

1. A hand edit or bad write leaves `xB` in a chunk. The count rises by one, the check counts `identity_entry 1`, and the mark records the higher count.
2. The owner deletes the malformed entry, which is the repair for the flagged difference.
3. The count falls below the mark, so `identity_shrunk` is counted on every later run. Nothing is lost: `xB` was never a usable key for the dedupe, because `kind` and the decode of the entry did not round-trip.

The WR-07 review text named "removing a malformed or duplicated entry" and the fix handles only the duplicate. The tests pin the duplicate and the bare kind letter, not this. It is the same class of defect, narrower: it needs a corrupt entry rather than a duplicate. The fix commit and the doc text ("an entry with no posting ID after its kind letter counts for nothing") describe a stricter rule than the code applies.
**Fix:** Count only entries that `check_compact` would accept as well-formed, so the figure is the set of IDs the dedupe can actually use. Either skip an entry in `_reindex` when `kind not in DISPOSITION_OF or not pid or encode_entry(kind, pid) != entry` (then check that `keys()`, `kind()` and `plan_additions` still behave for the valid entries, and whether a malformed existing ID should count as known), or add a `valid_distinct_count()` used only by the mark and `_identity_loss`. Add a test: record N, add an `xB` entry (counted `identity_entry`, mark stays N), remove it, assert 0 differences.

## Info

### IN-01: `parity.py` docstring is wrong about its imports

**File:** `parity.py:3-4`
**Issue:** The docstring says the module "imports `compact` and `ledger` only (never state, pipeline or hunter)". It also imports `reporting`, `storage_report` (which imports `state`) and `boards`. There is no cycle today, but the stated invariant is false and will not protect a future change. Still open, unchanged by this fix set.
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
**Issue:** `load_ledger` reads Events, then Identity, then Tally with separate calls. A manual `--storage-parity` or `--dashboard` that overlaps a poller run can see Events from before the run and Tally or Identity from after it, which gives counted differences that disappear on the next run. The WR-02 fix now also compares the Identity entry count in `--storage-parity` against `last_check.identity_entries`, which a racing poller run advances. After WR-06 the mark only grows, so a racing read can only produce a false `identity_shrunk` in the direction of an old snapshot against a newer mark. Mitigated by the one-run-at-a-time concurrency group. Still open.
**Fix:** Document that a parity difference should be re-run before it is trusted, or read all three tabs in one `values_batch_get`.

### IN-07: `first_day` is dated by the fold that ends, not by the one that started

**File:** `compact.py:466` (`fold_record`)
**Issue:** `first = previous.get("first_day") or (_utc_day(now) if rows > 0 or previous.get("started_day") else "")`. When a fold fails after its first delete on day D and finishes on day D+1, `first_day` becomes D+1 although rows went on D. The restore guard is unaffected, because it also honours the marker until the fold ends. `storage_report.py:316` and `:349` read `fold.first_day` as the start of the "after the cutover and first fold" window and `first_fold_day`. The window then starts later than the truth, which is the conservative direction, but the reported `first_fold_day` is wrong.
**Fix:** Prefer the marker's day: `previous.get("first_day") or previous.get("started_day") or (_utc_day(now) if rows > 0 else "")`.

### IN-08: The Tally carry holds zero-total rows and drops the newest row when full

**File:** `compact.py:707-715` (`keep_tally`), `pipeline.py:372-383` (`carry_tally`)
**Issue:** Two small quality points on the WR-03 carry.
1. Every run appends a Tally row, including runs that observed nothing (`total` 0). `test_a_carried_row_stays_until_it_can_be_written...` shows this: the carry holds `[3, 0]`. A zero-count row has nothing to lose, because no baseline count is missing and `repair_plan` has nothing to rebuild. Carrying it spends one of the 20 slots for nothing and adds a Discovery write per failing run.
2. When the carry is full, the newest row is the one left out (`keep_tally` returns False). The newest row is the one most likely to hold fresh baseline counts, so the permanent undercount WR-03 fixed comes back after 20 consecutive failures. Realistically a Tally outage that long also fails the Discovery save that persists the carry. The cap is deliberate, so this is a robustness note, not a defect.
**Fix:** In `carry_tally`, return early when `row.total == 0`. When the carry is full, either drop the oldest zero-count row first or log and note `storage tally carry full` in `run.notes`, so the owner sees the gap. The log line is currently the only trace.

### IN-09: The new tests do not pin the claim that matters most for the fix, "the fold stays held back"

**File:** `tests/test_storage_parity.py:777-822` and `:927-958`
**Issue:** The WR-06 purpose, stated in SPEC, D-57 and STATUS, is that an unrepaired loss "holds the fold back" on every later run. The new tests assert the note, the degraded outcome, the counted figure and the mark across three runs. None asserts `storage fold skipped: integrity check counted 1 differences` or that no rows were deleted for `identity_shrunk` specifically. The code path is right: `storage_check` returns `report.counted` and `pipeline` gates on it, and `tests/test_storage_cutover.py:984-1018` cover the gate with another difference. A future change to how `identity_shrunk` counts, or marking it declared, would not fail any test that names the fold. There is also a stray second blank line in `IntegrityTests` (about `tests/test_storage_parity.py:957`, now before the WR-07 integration test, which was added after it).
**Fix:** In `test_a_loss_nobody_repairs_is_counted_on_every_later_check...`, assert each degraded run's notes contain `storage fold skipped` when a fold is due, or add one test in the fold case class that removes a baseline-only ID and checks the Events row count is unchanged across two runs. Remove the extra blank line.

### IN-10: The documented repair path has no tooling and the mark can be stuck high by a transient over-read

**File:** `STATUS.md` (WR-06 cost paragraph), `SPEC.md:111`, `compact.py:754`
**Issue:** The docs give "restore the missing IDs to `Identity`, for example from `Events_Legacy`" as the only repair. No command does it. The poller's start-of-run repair rebuilds only Tally groups, not Identity, and `Identity` is a codec cell (chunked, escaped entries with a `Count` column), so a hand edit is error-prone, which the test itself needs seven lines of cell surgery to do. Also, because the mark can only rise, a single over-read (a transient read that returns extra rows, or a malformed entry as in WR-08) leaves it stuck high for good. The user chose not to add an acknowledgement input, so this is only an operational cost, not a defect. It is better recorded than discovered during an incident.
**Fix:** Add a short runbook note to DEPLOY.md or STATUS ("to clear a stuck `identity_shrunk`, set `last_check.identity_entries` in the Discovery `storage` key to the true count, after confirming nothing is lost"), and consider a read-only `--storage-parity` line that prints the mark and the current count, so the owner can see which side moved.

### IN-11: The figure keeps the name "entries" but now counts distinct IDs, and is computed in two places

**File:** `compact.py:745-747` (`last_identity_entries`), `compact.py:751` (`identity_entries` parameter), `parity.py:107`, `:330`, `:366` (`compared["identity_entries"]`, `entries`, `entries_before`), `parity.py:361-364` (`_identity_loss` docstring)
**Issue:** After WR-07 the value behind `last_check.identity_entries`, `compared["identity_entries"]` and `identity_entries_before` is a distinct-ID count. The names, the `last_identity_entries` docstring ("The Identity entry count") and the `_identity_loss` docstring still say "entries". `_identity_loss` also recomputes the figure from `ledger.identity.distinct_count()` while `_identity_invariants` returns the same call. The two agree today because both read the same set, but one change to either breaks the invariant that the mark and the comparison use the same figure, and no test compares them directly. The persisted key name is a Discovery-state contract, so a rename needs care.
**Fix:** Update the docstrings now ("distinct posting IDs"). Have `_identity_loss` take the count that `check_compact` already got from `_identity_invariants`, or assert equality in a test, so there is one source.

### IN-12: The new unit test claims coverage it does not have and builds its fixture twice

**File:** `tests/test_storage_parity.py:777-791`
**Issue:** The comment says "a bare kind letter (no posting ID) and an unparsed entry count for nothing". Only the bare kind letter (`b`) is in the fixture; there is no unparsed or malformed entry. That gap is exactly WR-08, and the comment hides it. The same test builds the duplicated ledger twice (`self.check(rows=...)` and `self.ledger(rows=...)`) to assert a raw sum of 25, which is a restatement of the fixture and not a check of the code.
**Fix:** Correct the comment, and add the WR-08 case (an entry with an unknown kind letter) so the comment is true.

---

_Reviewed: 2026-11-15_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
