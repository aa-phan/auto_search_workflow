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
**Depth:** standard (incremental re-review: `git diff f4364d3 HEAD` for fix commit c845065 (WR-08) and its doc changes, each hunk read in its surrounding code: `compact.entry_well_formed`, `compact.IdentitySet` (`_reindex`, `copy`, `keys`, `kind`, `distinct_count`, `plan_additions`, `apply`), `StorageState.record_compact_check`, `parity._kept_in_identity` / `_identity_invariants` / `_identity_loss`, and the callers of `IdentitySet.keys()` (`retained_events`, `repair_plan`, `hunter` seen set, `storage_report`))
**Files Reviewed:** 6
**Status:** issues_found

## Summary

WR-08 is fixed as far as it was stated, and the mechanics are sound:

- **The predicate is unchanged.** `entry_well_formed` is `kind in DISPOSITION_OF and bool(pid) and encode_entry(kind, pid) == entry`, the same three tests `check_compact` ran inline before. `identity_entry` behaves as before, and it now calls the one function.
- **Mixed entries of one ID.** `_valid` is a per-stem set of posting IDs with at least one well-formed entry. I checked `bA,xB,b%2c` (count 1), `xB,bB` (count 1, the ID counts once although the malformed entry came first) and `bA,xB,b%2c,b%2C` (count 2: the `%2C` entry decodes to `,` and is well formed).
- **Consistency of the new record.** `_reindex` rebuilds `_kinds` and `_valid` together, and `apply` goes through `_reindex`. `copy()` copies `_valid` as it does `_kinds`. `from_rows` goes through `_reindex`. `plan_additions` only plans and writes nothing to either map. `_valid` is not read anywhere except `distinct_count`.
- **Performance.** 235,000 IDs in 100 stems took 0.08 s for `from_rows` plus `distinct_count`. The predicate decodes each entry a second time, which is immaterial at this size.
- **Tests.** `.venv/bin/python -m unittest discover -s tests`: `Ran 939 tests ... OK`, which matches STATUS (937 after WR-07, 939 after WR-08). The unit test pins the mixed entry, the predicate truth table, `copy()` and the compared figure. The integration test records N, adds `xB,b%2c`, sees the mark stay N and `identity_entry 1`, repairs by restoring the original cell, and sees 0 differences and exit 0.
- **Docs.** SPEC, D-57 and STATUS describe the change, label every check mocked and not deployed, and make no live Sheets, Groq or Telegram claim. No rule 1 conflict: the high-water mark and the absence of an acknowledgement input stand as decided.

**One new WARNING (WR-09).** The fix makes the figure count "well-formed" IDs, but the dedupe (`IdentitySet.keys()`) still holds every ID that a malformed entry carries. The code comment and all three docs say the count is "the identity the dedupe uses", which is no longer true, and the one repair the check invites for a malformed entry, deleting it, now loses a held ID without any `identity_shrunk`. The WR-08 text of the previous review said an `xB` entry "was never a usable key for the dedupe". I checked that and it was wrong: `keys()` and `plan_additions` use `_kinds`, which includes it. **No new INFO items.** IN-12 is resolved. IN-01..IN-11 are carried forward under their ids; IN-09 and IN-11 have updated text.

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
| IN-12 test comment claimed coverage it did not have | c845065 | The comment now says only what the fixture holds, and the WR-08 case (an unknown kind letter and a non-round-tripping escape) is in both new tests. The unit test still builds the duplicated ledger twice for a raw sum of 25 (a restated fixture, harmless). |

## Critical Issues

None.

## Warnings

### WR-09: The count excludes malformed entries that the dedupe still uses, so deleting one loses a held posting ID with no `identity_shrunk`

**File:** `compact.py:217-235` (`keys`, `distinct_count`, `_reindex`), `compact.py:243-251` (`plan_additions`), `compact.py:381`, `:441`, `:574`, `hunter.py:2145`, `storage_report.py:81` (callers of `keys()`), `SPEC.md` (the sentence "the identity the dedupe uses, counted over well-formed entries only"), `compact.py:231-234` (docstring)
**Issue:** `distinct_count` now counts `_valid`, but everything that dedupes reads `_kinds`. I confirmed with `IdentitySet.from_rows([IdentityRow("g|a", 1, "t", 3, "bA,xB,b%2c")])`: `distinct_count()` is 1, while `keys()` is `{g|a|A, g|a|B, g|a|%2c}`, so the ledger treats `B` and `%2c` as held. `plan_additions` also skips them as known (`pid in known`). `xB` is therefore an effective dedupe key (the kind letter `x` is not consulted by `seen()`; only `identity_kind`, which needs an Events row, looks at it). Trace:

1. An entry `xB` exists in `Identity` and is the only entry for posting `B`. Its figure counts 0, it is flagged `identity_entry`, the run is degraded and the fold is held back.
2. The owner repairs the flagged difference by deleting the malformed entry, the repair the previous review and the fix commit both describe.
3. `B` drops out of `keys()`. The count is unchanged (0 before, 0 after), so no `identity_shrunk`. A baseline that `B` stood for is no longer held, and the posting can come back as a new observation, which is the freshness failure AGENTS rule 2 and rule 3 exist to prevent. Nothing in the check names it, and the Events row is already folded, so `identity_missing` cannot see it either.

The same hole is a quieter version of the original WR-02 loss: a held ID leaves Identity unnoticed. WR-08 fixed a false alarm by making the figure blind to a class of real keys. The docs now state something the code does not do: SPEC, D-57, STATUS and the `distinct_count` docstring call the figure the identity "the dedupe uses" or "can use", but `keys()` is the dedupe and holds the malformed IDs too. The corrupted-then-edited direction is also asymmetric: rewriting `bB` to `xB` (a damaged kind letter) lowers the figure by one and counts `identity_shrunk` although the ID is still held.
**Fix:** Pick one rule and make the code and the docs say it.
- Keep the mark on well-formed IDs and add a second high-water mark over `len(identity)` (all held IDs, the figure `keys()` yields), recorded next to `identity_entries` (for example `identity_held`) and compared in `_identity_loss` as its own difference. A malformed entry that is deleted still lowers the held figure and is named.
- Or name the repair in the check output and the docs as "correct the entry to canonical form, do not delete it", and say in the docstring and SPEC that deleting a malformed entry whose ID has no well-formed twin drops a held ID undetected.
- In either case, change the sentence "the identity the dedupe uses" to what the code does, and add a test: record N, add `xB` (mark stays N, `identity_entry 1`), delete it, and assert the chosen behaviour (a named difference, or a documented silent drop).

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
**Issue:** The docs give "restore the missing IDs to `Identity`, for example from `Events_Legacy`" as the only repair. No command does it. The poller's start-of-run repair rebuilds only Tally groups, not Identity, and `Identity` is a codec cell (chunked, escaped entries with a `Count` column), so a hand edit is error-prone, which the tests need several lines of cell surgery to do. Also, because the mark can only rise, a single over-read (a transient read that returns extra rows) leaves it stuck high for good. After WR-08 a malformed entry no longer raises the mark, which removes one cause. The user chose not to add an acknowledgement input, so this is only an operational cost, not a defect. It is better recorded than discovered during an incident.
**Fix:** Add a short runbook note to DEPLOY.md or STATUS ("to clear a stuck `identity_shrunk`, set `last_check.identity_entries` in the Discovery `storage` key to the true count, after confirming nothing is lost"), and consider a read-only `--storage-parity` line that prints the mark and the current count, so the owner can see which side moved.

### IN-11: The figure keeps the name "entries" and is computed in two places

**File:** `compact.py:745-747` (`last_identity_entries`), `compact.py:751` (`identity_entries` parameter), `parity.py:107`, `:329`, `:365` (`compared["identity_entries"]`, `entries`, `entries_before`), `parity.py:375`, `:380` (`identity_entries_before`)
**Issue:** The docstrings were reworded by c845065 (`last_identity_entries`, `record_compact_check`, `_identity_invariants`), so the wording is now honest. What remains: the persisted key, the `compared` key, the parameter names and the `entries` variables all still say "entries" for what is a distinct well-formed ID count, and `_identity_loss` still recomputes the figure from `ledger.identity.distinct_count()` while `_identity_invariants` returns the same call. They agree today because both read the same set, but one change to either breaks the invariant that the mark and the comparison use the same figure, and no test compares them directly. The persisted key name is a Discovery-state contract, so a rename needs care.
**Fix:** Have `_identity_loss` take the count that `check_compact` already got from `_identity_invariants`, or assert equality in a test, so there is one source. Leave the persisted key name alone.

---

_Reviewed: 2026-11-15_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
