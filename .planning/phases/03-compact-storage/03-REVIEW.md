---
phase: 03-compact-storage
reviewed: 2026-11-16T00:00:00Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - DECISIONS.md
  - SPEC.md
  - STATUS.md
  - compact.py
  - parity.py
  - storage_report.py
  - tests/test_storage_parity.py
  - tests/test_storage_report.py
findings:
  critical: 0
  warning: 1
  info: 12
  total: 13
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-11-16
**Depth:** standard (incremental re-review: `git diff 43bd2b3 HEAD` for gap-closure plan 03-10, WR-10, commits 559c479, 389789a, 0ac4de1, de57002, 7541c53; each hunk read in its surrounding code: `compact.IdentitySet` (`_reindex`, `copy`, `apply`, `keys`, `kind`, `distinct_count`, `plan_additions`), `compact.entry_well_formed`, `compact.stem_and_id`, `parity._seen_set` / `_kept_in_identity` / `_identity_invariants` / `_identity_loss`, `storage_report.logical_counts`, and the stem question the planner left out)
**Files Reviewed:** 8
**Status:** issues_found

## Summary

**WR-10 is resolved.** `_reindex` and `storage_report.logical_counts` both skip an empty posting ID, so a bare kind letter holds no key. I confirmed: `IdentitySet.from_rows([IdentityRow("g|a", 1, "t", 2, "bA,b")])` gives `keys() == {"g|a|A"}` and `distinct_count() == 1`. It holds through `copy()` (copies `_kinds`), `apply()` (calls `_reindex`) and `from_rows`. `plan_additions` already skipped `not entry[1:]` and looks up `self._kinds`, so the writer and the dedupe still agree. A bare entry is still flagged `identity_entry` (`entry_well_formed("b")` is False), it does not move the figure, and deleting it is not a counted `identity_shrunk` (the compact integration test runs the fold on the next UTC day after the deletion). The dedupe itself is unchanged, because no job key can equal `stem|`. `storage_report` and `IdentitySet` use the same first-wins, skip-empty rule. The docstrings, SPEC, D-57 and STATUS match the code, label the change mocked and not deployed, and make no live Sheets, Groq or Telegram claim. `.venv/bin/python -m unittest discover -s tests`: `Ran 945 tests ... OK`, matching STATUS. No rule 1 conflict.

**One new WARNING (WR-11), the hole the planner left out.** It is real and it has the same effect as WR-10: a hand-edited Identity stem that no job key can produce (no `|`, more than one `|`, or upper case) holds keys that never match a posting. It is flagged by nothing in compact mode, it raises the mark, and deleting it is a permanent `identity_shrunk`. I reproduced all three variants (details in WR-11). It is less likely than WR-10 (it needs a hand edit of the `Board_Key` column of a warning-protected hidden tab, not a cut cell), so the planner's scoping was reasonable, but a fix that closes only the empty-ID half of "a key no job can match" leaves the same false permanent alarm open.

**One new INFO (IN-12).** The WR-10 fix removes an incidental dual-mode detection of a bare entry.

Resolved:

| Earlier finding | Fix commit | Verification |
|---|---|---|
| WR-01 restore guard open after a partial fold | a2247a9 | Earlier review, unchanged. |
| WR-02 Identity loss undetected, `ensure()` recreates an empty tab | 58d9ec2 | Earlier review, unchanged. |
| WR-03 Tally write failure became a permanent undercount | 024319f | Earlier review, unchanged. See IN-08. |
| WR-04 stale Identity cache overwrote the sheet | 6648949 | Earlier review, unchanged. |
| WR-05 the fold ignored the same run's integrity check | 8b02697 | Earlier review, unchanged. |
| WR-06 `identity_shrunk` reported once, then the lower count became the reference | e83d563 | Earlier review, unchanged. |
| WR-07 the mark counted duplicate Identity entries | 9fd3383 | Earlier review, unchanged. |
| WR-08 the mark counted malformed Identity entries | c845065 | Superseded by WR-09. |
| WR-09 the count excluded malformed entries the dedupe still holds | e86993e | The count is `sum(len(kinds))`, exactly `len(keys())`. |
| WR-10 an entry with no posting ID counted as a held key, and its only repair, deletion, was a permanent `identity_shrunk` | 559c479, 389789a, 0ac4de1, de57002, 7541c53 | `if pid:` in `_reindex` and in `logical_counts`. Bare entry: not a key, not in the figure, still `identity_entry`, deleting it counts 0, the fold runs. Traced through `from_rows`, `copy`, `apply`, `keys`, `kind`, `distinct_count`, `plan_additions`, `_kept_in_identity`, `_identity_loss`, `logical_counts`. Three new tests (parity unit, compact integration, storage report), 945 tests pass. Residuals: WR-11 (a stem no job key can produce) and IN-12 (dual mode). |

## Critical Issues

None.

## Warnings

### WR-11: An Identity stem no job key can produce holds keys that match nothing, is not flagged, raises the mark, and deleting it is a permanent `identity_shrunk`

**File:** `compact.py:188-192` (`_reindex`, which filters only `pid`), `compact.py:217` (`keys()`), `compact.py:44-49` (`stem_and_id`), `parity.py:111-130` (`_identity_invariants`), `parity.py:300-330` (`_kept_in_identity`)
**Issue:** WR-10's rule is "an entry holds a key only if a job key can equal it", and the fix applies it to the posting ID only. `stem_and_id("ats|board|id")` returns `("ats|board", "id")` and builds a stem from exactly two segments of `key.split("|", 2)`, and `boards.py:85` lowers the board. So a stem can match a posting only if it has exactly one `|` and is lower case. `IdentityRow.from_row` rejects only a blank stem or a bad chunk (`identity_unreadable`); every other stem is accepted, and `IdentitySet._reindex` holds all its IDs as keys. Reproduced with the compact check helper (`IntegrityCheckTests`) by adding `IdentityRow(stem, 1, "t", 2, "bA,bB")`, with the mark recorded from the check and then the row deleted:

| Stem | Diffs from the check | `identity_entries` | After deleting the row, with the recorded mark |
|---|---|---|---|
| `greenhouse` (no `|`) | none | 26 (was 24) | `identity_shrunk 24 vs 26` |
| `greenhouse|acme|x` (extra `|`) | none | 26 | `identity_shrunk 24 vs 26` |
| `Greenhouse|Acme` (upper case) | none | 26 | `identity_shrunk 24 vs 26` |

Why nothing flags it in compact mode: `_kept_in_identity` compares only Events-held keys against Identity, the other direction is a documented limit (D-57), and `identity_entry` looks at entries, not stems. Dual mode does flag it, through `identity_extra` (`stored - keyable.keys()`), so the hole exists only after the cutover, which is where production runs. Trace, the same as WR-10:
1. A hand edit, a Sheets auto-format, a trailing space or a paste error puts a row such as `Greenhouse|Acme` or `greenhouse` into `Identity`. The stray IDs are counted, so the mark rises by their number.
2. The owner removes the row, the only repair that makes sense (a row that nothing can match has no canonical form).
3. The figure falls, `identity_shrunk` is counted on every later check by WR-06, every run is degraded, and the WR-05 gate holds the fold back with `Events` growing. The only exit is editing `storage.last_check.identity_entries` in Discovery by hand, which STATUS does not document. No ID that the dedupe could ever use was lost.
There is a worse variant of the same cause: a hand edit that changes a real stem to a non-matching one (case, whitespace) moves real IDs into keys that match nothing. The check then counts the old stem as `identity_shrunk` only if the mark was recorded before, and counts the new keys as held, so the figure can stay equal while the dedupe has lost every ID of that board. The check and the dedupe agree on the figure but the figure no longer measures what AGENTS rule 3 protects. Nothing flags the stem either way.
**Fix:** Apply the same rule to the stem, once per stem, in `_reindex`, so `keys()`, the figure, `copy()`, `apply()` and `logical_counts` (which should call a shared predicate) stay in agreement:
```python
def stem_holds_keys(stem: str) -> bool:
    """Can a job key produce this stem? `ats|board`: exactly one `|`, lower case (`stem_and_id`, `boards.JobIdentity.key`)."""
    return stem.count("|") == 1 and stem == stem.lower()
```
In `_reindex`, set `self._kinds[stem] = {}` when `not stem_holds_keys(stem)` and skip `logical_counts` for such a stem. Add a counted difference in `_identity_invariants` (`identity_stem`, ref the stem, layer 1) so a flagged stem is visible, and add a test per variant that adds the row, records the mark, deletes the row, and asserts no `identity_shrunk`. A smaller fix, if the owner prefers not to add a difference: flag only, with the key rule left as is, and document the manual mark edit in STATUS; but then WR-11 stays a permanent alarm. If the planner keeps this out of scope, record it in STATUS as an open known limit next to the "Identity-only ID" limit in SPEC, so it is found before an incident.

## Info

### IN-01: `parity.py` docstring is wrong about its imports

**File:** `parity.py:3-4` (imports at `:35-39`)
**Issue:** The docstring says the module "imports `compact` and `ledger` only (never state, pipeline or hunter)". It also imports `reporting`, `storage_report` (which imports `state`) and `boards`. There is no cycle today, but the stated invariant is false. Still open.
**Fix:** State the real constraint (no import of `pipeline` or `hunter`), or move the shared figure code so the claim becomes true.

### IN-02: Removing `Events_Legacy` silently flips a compact system back to dual writing

**File:** `compact.py:604-620` (`effective_mode`, `NOTE_COMPACT_WITHOUT_LEGACY` at `:589`)
**Issue:** If the stored mode is compact and `Events_Legacy` is gone, the poller writes as dual. Baselines go back into Events, and the fold and the check stop. DECISIONS P3-08 describes removing `Events_Legacy` as a later owner decision "with an export plan". As written, that decision cannot be carried out without a code change. `_compact_mode_stored` calls `effective_mode(..., legacy_present=True)`, so the `ensure()` guard also assumes the legacy tab exists. Still open.
**Fix:** Before the owner removes the tab, add a recorded state (for example `storage.legacy_retired_at` or a `--storage-retire-legacy` step) that `effective_mode` and `_compact_mode_stored` honour. Until then, note it in DEPLOY.md.

### IN-03: The workflow lets `storage_cutover` and `storage_restore` run in one job

**File:** `.github/workflows/job_hunter.yml:40-44` and the step guards
**Issue:** The CLI makes the two flags mutually exclusive, but each is a separate workflow step guarded only by its own input. Ticking both runs the cutover and then the restore in the same dispatch. Still open (workflow unchanged).
**Fix:** Add a first step that fails when more than one of the owner-step or report inputs is true.

### IN-04: The cutover checksum covers only `key|time|event`

**File:** `compact.py:391-396` (`rows_checksum`)
**Issue:** The comment says the checksum compares "the rows it meant to copy" with the rows read back. It hashes three of the seven columns, so a changed `Freshness`, `Disposition`, `Published` or `Detail` passes. `Events_Legacy` stays whole, so this is not a data-loss path. Still open.
**Fix:** Hash `"\x1f".join(ev.to_row())` per row.

### IN-05: Dead variable and unused imports

**File:** `reporting.py:492` (`first_event`), `storage_report.py:10,18` (`json`, `fr`)
**Issue:** `first_event` is assigned and never read, and `json` and `fr` are imported and never used (I grepped `json.` and `fr.` in `storage_report.py`: no use). Still open. `storage_report.py` changed in this diff but not these lines.
**Fix:** Delete them.

### IN-06: Read-only commands read three tabs sequentially without the lease

**File:** `state.py:608` and `state.py:893` (`load_ledger`), `hunter.py` (`run_storage_parity`, `run_storage_report`, `run_pilot_report`), `dashboard.py:594`
**Issue:** `load_ledger` reads Events, then Identity, then Tally with separate calls. A manual `--storage-parity` or `--dashboard` that overlaps a poller run can see Events from before the run and Tally or Identity from after it, which gives counted differences that disappear on the next run. `--storage-parity` also compares the Identity count against `last_check.identity_entries`, which a racing poller run advances. After WR-06 the mark only grows, so a racing read can only produce a false `identity_shrunk` in the direction of an old snapshot against a newer mark. Mitigated by the one-run-at-a-time concurrency group. Still open.
**Fix:** Document that a parity difference should be re-run before it is trusted, or read all three tabs in one `values_batch_get`.

### IN-07: `first_day` is dated by the fold that ends, not by the one that started

**File:** `compact.py:485` (`fold_record`)
**Issue:** `first = previous.get("first_day") or (_utc_day(now) if rows > 0 or previous.get("started_day") else "")`. When a fold fails after its first delete on day D and finishes on day D+1, `first_day` becomes D+1 although rows went on D. The restore guard is unaffected, because it also honours the marker until the fold ends. `storage_report.py:317` and `:350` read `fold.first_day` as the start of the "after the cutover and first fold" window and `first_fold_day`. The window then starts later than the truth, which is the conservative direction, but the reported `first_fold_day` is wrong. Still open.
**Fix:** Prefer the marker's day: `previous.get("first_day") or previous.get("started_day") or (_utc_day(now) if rows > 0 else "")`.

### IN-08: The Tally carry holds zero-total rows and drops the newest row when full

**File:** `compact.py:726-734` (`keep_tally`), `pipeline.py:371-383` (`carry_tally`)
**Issue:** Two small quality points on the WR-03 carry.
1. Every run appends a Tally row, including runs that observed nothing (`total` 0). A zero-count row has nothing to lose, because no baseline count is missing and `repair_plan` has nothing to rebuild. Carrying it spends one of the 20 slots for nothing and adds a Discovery write per failing run.
2. When the carry is full, the newest row is the one left out (`keep_tally` returns False). The newest row is the one most likely to hold fresh baseline counts, so the permanent undercount WR-03 fixed comes back after 20 consecutive failures. Realistically a Tally outage that long also fails the Discovery save that persists the carry. The cap is deliberate, so this is a robustness note, not a defect.
**Fix:** In `carry_tally`, return early when `row.total == 0`. When the carry is full, either drop the oldest zero-count row first or log and note `storage tally carry full` in `run.notes`.

### IN-09: The tests do not pin the claim that matters most for the fix, "the fold stays held back"

**File:** `tests/test_storage_parity.py` (the WR-06 loss tests and the WR-08 integration test, around `:777-822` and `:927-958` before this diff)
**Issue:** The WR-06 purpose, stated in SPEC, D-57 and STATUS, is that an unrepaired loss "holds the fold back" on every later run. The WR-06 tests assert the note, the degraded outcome, the counted figure and the mark across three runs. None asserts `storage fold skipped: integrity check counted 1 differences` or that no rows were deleted for `identity_shrunk` specifically. The code path is right (`storage_check` returns `report.counted`, `pipeline` gates on it, and `tests/test_storage_cutover.py` covers the gate with another difference), but a future change to how `identity_shrunk` counts would not fail any test that names the fold. The new WR-10 integration test does the opposite check well (it asserts `storage fold skipped` is absent and `fold.last_day` advances), which makes the missing positive case more visible. Still open.
**Fix:** In `test_a_loss_nobody_repairs_is_counted_on_every_later_check...`, assert each degraded run's notes contain `storage fold skipped` when a fold is due, or add one test in the fold case class that removes a baseline-only ID and checks the Events row count is unchanged across two runs.

### IN-10: The documented repair path has no tooling and the mark can be stuck high by a transient over-read

**File:** `STATUS.md` (WR-06 cost paragraph), `SPEC.md:111`, `compact.py:758-775`
**Issue:** The docs give "restore the missing IDs to `Identity`, for example from `Events_Legacy`" as the only repair. No command does it. The poller's start-of-run repair rebuilds only Tally groups, not Identity, and `Identity` is a codec cell (chunked, escaped entries with a `Count` column), so a hand edit is error-prone. Also, because the mark can only rise, a single over-read (a transient read that returns extra rows) leaves it stuck high for good. A malformed entry with a posting ID still raises the mark (it is a held key, WR-09), and so does a stem no job key can produce (WR-11). The user chose not to add an acknowledgement input, so this is only an operational cost, not a defect. It is better recorded than discovered during an incident.
**Fix:** Add a short runbook note to DEPLOY.md or STATUS ("to clear a stuck `identity_shrunk`, set `last_check.identity_entries` in the Discovery `storage` key to the true count, after confirming nothing is lost"), and consider a read-only `--storage-parity` line that prints the mark and the current count, so the owner can see which side moved.

### IN-11: The figure keeps the name "entries" and the Discovery key cannot be renamed lightly

**File:** `compact.py:758-775` (`last_identity_entries`, `identity_entries` parameter), `parity.py:107`, `:329` (`compared["identity_entries"]`), `parity.py:360` (`entries`, `entries_before`)
**Issue:** The persisted key, the `compared` key, the parameters and the variables all say "entries" for what is a count of distinct held keys. `check_compact` also reads `compared["identity_entries"]` that `_kept_in_identity` writes, an implicit coupling through a dict (safe today because `_kept_in_identity` always sets it). The persisted key name is a Discovery-state contract.
**Fix:** Leave the persisted key name alone. Optionally have `_kept_in_identity` return the count instead of reading it back out of `compared`.

### IN-12: The WR-10 fix removes an incidental dual-mode detection of a bare entry, and dual mode has no `identity_entry` check

**File:** `parity.py:82-108` (`_seen_set`), `parity.py:324-327` (`identity_entry` exists only in `_kept_in_identity`), `compact.py:188-192`
**Issue:** Before the fix, a bare `b` entry in the dual-mode check produced `identity_extra stem|` (the empty key was in `stored` and not in `keyable`). Now the entry holds no key, so `_seen_set` raises nothing. I reproduced it with the `Synthetic` harness (`MutationTests`): adding `,b` or `,x` to an Identity row gives no counted difference and `identity_entries` stays 24, while adding `,b999` still gives `identity_extra`. The first compact check after the cutover would flag it as `identity_entry`, so the entry is caught late, not never, and a bare entry cannot affect the dedupe. It is still a counted difference that became silent in the mode where the parity bar is earned, and the dual-mode tests (`test_one_identity_id_added`) do not cover a bare entry.
**Fix:** Run the `identity_entry` loop from `_identity_invariants` so both modes flag a malformed entry (then drop the copy in `_kept_in_identity`), and add a dual-mode test with a bare `b`. The same change would also give WR-11's `identity_stem` a home that both modes share.

---

_Reviewed: 2026-11-16_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
