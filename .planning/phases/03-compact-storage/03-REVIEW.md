---
phase: 03-compact-storage
reviewed: 2026-11-17T00:00:00Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - DEPLOY.md
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
  warning: 3
  info: 14
  total: 17
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-11-17
**Depth:** standard (incremental re-review of docs only: `git diff 98c19d8 HEAD -- DEPLOY.md STATUS.md`, commits 5d1d421 and 0c7a001. The runbook was checked against `compact.StorageState.record_compact_check` / `last_identity_entries`, `parity._kept_in_identity` / `_identity_loss` / `check_compact` / `format_report`, `hunter.run_storage_parity`, `pipeline.storage_check` and the `pipeline` Discovery load and save path, `compact.effective_mode`, `StorageState.load`. STATUS was checked against the public Actions logs of runs 44043039789, 44044724225, 44051541803 and 43990083983 (read with `gh run view --log`; counts and run ids only, no secret read), `gh api .../activity` for the push time, and `git diff --stat 68a7253 bc3bea2`. No source code changed since the last review, so nothing else was re-reviewed.)
**Files Reviewed:** 9 (DEPLOY.md and STATUS.md are the scope of this pass; the other seven carry their earlier review)
**Status:** issues_found

## Summary

**The runbook names the right key and the right figure.** `last_check.identity_entries` is a field inside the JSON value of the Discovery row whose key is `storage` (`compact.py:758-777`; the poller loads and saves that row as one string, `pipeline.py:424`, `state.py:721-731`). The figure `storage_parity` prints in compact mode, `compared: identity_entries N`, is `entries` from `_identity_invariants`, i.e. `IdentitySet.distinct_count()`, the same number `record_compact_check` max-folds into the mark (`pipeline.py:250`). `format_report` prints `compared` sorted by name (`parity.py:404`), so the line exists in the output. Setting the mark to that figure makes the next check compare equal, so `identity_shrunk` stops. The pre-step is also right: `run_storage_parity` passes `identity_entries_before=storage.last_identity_entries()` (`hunter.py:2025`), so a `storage_parity` run does show `identity_shrunk` before the edit and shows it gone after. The WR-11 sentence matches the table in the earlier review (all three stem variants raise the figure, deleting the row gives `identity_shrunk`). IN-10 is addressed in substance.

**The procedure is not yet safe as written (WR-12).** It tells the owner to hand-edit a JSON string that the poller treats as the whole storage state, with no guard against a syntax slip (which silently turns a compact system into a dual-mode one and overwrites the cutover and fold records on the next run), no instruction to edit between runs (a run in progress writes the whole Discovery body back and discards the edit), and no check after the edit.

**STATUS keeps mocked and live apart for the deploy section and every cited run id checks out** (push 2026-11-17T07:07:33Z `68a7253 -> bc3bea2`, no `.github` file in the diff, the three runs are `success` on headSha bc3bea2 at 08:00:09, 08:12:13 and 09:00:08 UTC, the printed counts match: 22319 kept job keys / 939 Tally runs, `identity_entries 295385`, 22509 / 940). The WR-01..WR-10 table rows are correctly "mocked; deployed bc3bea2, not exercised live". Problems are in what the new paragraph says about the storage report (WR-13: a headline figure that omits its scope, and two older statements left standing that contradict it) and in two evidence labels (IN-14).

No rule 1 conflict: no behaviour changed. No secrets or personal data in either diff.

Resolved or addressed:

| Earlier finding | Fix commit | Verification |
|---|---|---|
| WR-01 .. WR-10 | a2247a9, 58d9ec2, 024319f, 6648949, 8b02697, e83d563, 9fd3383, c845065 (superseded), e86993e, 559c479 .. 7541c53 | Earlier reviews, unchanged. Deployed in bc3bea2. |
| IN-10 the repair path for a stuck mark is undocumented | 5d1d421 | The runbook paragraph exists and names the right key and figure. Two residuals: WR-12 (the edit is not safe as written) and IN-13 (the repair half and the worse WR-11 variant). |

## Critical Issues

None.

## Warnings

### WR-11: An Identity stem no job key can produce holds keys that match nothing, is not flagged, raises the mark, and deleting it is a permanent `identity_shrunk`

**Status: accepted by the owner 2026-11-17 (UAT 8, option b); disposition skipped; not fixed. The runbook now documents the manual exit.**
**File:** `compact.py:188-192` (`_reindex`, which filters only `pid`), `compact.py:217` (`keys()`), `compact.py:44-49` (`stem_and_id`), `parity.py:111-130` (`_identity_invariants`), `parity.py:300-330` (`_kept_in_identity`)
**Issue:** WR-10's rule is "an entry holds a key only if a job key can equal it", and the fix applies it to the posting ID only. A stem can match a posting only if it has exactly one `|` and is lower case (`boards.py:85`). `IdentityRow.from_row` rejects only a blank stem or a bad chunk, so every other stem is accepted and `_reindex` holds all its IDs as keys. Reproduced earlier with the compact check helper: stems `greenhouse`, `greenhouse|acme|x` and `Greenhouse|Acme` each raise `identity_entries` from 24 to 26 with no difference, and deleting the row gives `identity_shrunk 24 vs 26` from then on. Dual mode flags it (`identity_extra`), compact mode does not (`_kept_in_identity` compares only Events-held keys against Identity). There is a worse variant: a hand edit that changes a real board's stem into a non-matching form leaves the figure unchanged while the dedupe loses every ID of that board (see IN-13).
**Fix:** Unchanged from the earlier review: apply the rule to the stem in `_reindex` (`stem.count("|") == 1 and stem == stem.lower()`), add a counted `identity_stem` difference, add a test per variant. If it stays out of scope, the DEPLOY.md paragraph is the documented exit (WR-12 says how to make it safe).

### WR-12: The documented hand edit of the `storage` key has no safe-edit protocol: a syntax slip flips a compact system to dual and erases its records, a run in progress discards the edit, and nothing checks the result

**File:** `DEPLOY.md:121` (the "Clearing a stuck `identity_shrunk`" paragraph), against `compact.py:691-715` (`StorageState.load`), `compact.py:604-620` (`effective_mode`), `pipeline.py:476-478` and `:512-533` (load at run start and seed save), `pipeline.py:424` (`save_storage`), `state.py:725-731` (`save_discovery_state`)
**Issue:** The paragraph says to set `last_check.identity_entries` in the Discovery `storage` key and "change nothing else in the key". The key is one cell holding compact, sorted JSON. Three gaps, each traced in the code:
1. **A JSON slip is destructive, not just ineffective.** `StorageState.load` and `effective_mode` both swallow `ValueError` and treat the text as `{}`. In production (Events_Legacy present) that gives `ModeDecision(MODE_DUAL, NOTE_CUTOVER_INCOMPLETE)`; the poller writes as dual, notes `storage cutover incomplete`, and because the parsed state has `seeded_at is None` it re-runs the repair and then saves a fresh default `StorageState` (`pipeline.py:524-533`: `storage.seeded_at = ...; storage.to_json()`), which replaces the whole value. The `cutover` record, `fold.last_day` / `first_day`, `last_check` and every other field of a working compact system are gone. A missing comma or a stray quote, or Sheets turning a typed number into text inside a hand-retyped cell, is enough. Recovery is "run `storage_cutover` again" (the interrupted-cutover path), which the runbook does not mention, and the fold record is lost for good.
2. **A run in progress overwrites the edit.** The poller reads the whole Discovery body at run start (`pipeline.py:473`) and every save writes the whole body back (`save_discovery_state` rewrites all keys, `state.py:725-731`). A run takes about 11 minutes of each hour (08:00:09 start, `Run:` line 08:11:02 in run 44043039789), the hourly dispatch is external, and the writer lease does not stop a hand edit. An edit made in that window is silently replaced by the run's in-memory copy (`record_compact_check` keeps `max(previous_in_memory, current)`), so the owner sees `identity_shrunk` come back and may repeat it.
3. **No verification step.** After the edit the runbook does not say to re-run `storage_parity` and read `mode compact` and `0 counted differences`. Only that run proves both that the key still parses and that the mark equals the figure.
**Fix:** Extend the paragraph, for example: "Edit the cell only between hourly runs (right after one finishes, not within about 15 minutes before an hourly dispatch or while a Job Hunter run is in progress). Copy the whole value into a JSON validator first, change only the number after `"identity_entries":`, and paste it back. If you cannot be sure it is valid JSON, do not edit it. Then run `storage_parity` again: it must print `mode compact` and no `identity_shrunk`. If it prints `mode dual` or the next hourly run notes `storage cutover incomplete`, the key was damaged: run `storage_cutover` once to finish the record (it does not copy) and tell the agent; `fold.first_day` will need to be rebuilt." An optional later fix is a one-shot `--storage-set-identity-mark` that writes the figure under the writer lease (AGENTS rule 7 applies: not a feature to add before an owner decision).

### WR-13: STATUS states the storage-report result without its scope, and two older statements it contradicts were left standing

**File:** `STATUS.md:3` (Last updated line) and `STATUS.md:7` (the "Deployed (live, 2026-11-17)" paragraph), against `STATUS.md:204` (SC3 row), `STATUS.md:207` ("Remaining not-verified items") and the log of run 43990083983
**Issue:**
1. **Headline without scope.** The new text says "storage report 447 cells/day against 35,511" / "79.4x smaller". The figures are the report's, and they are real (log lines: `median daily growth in allocated cells: 35,511 before (Events rows x 7) -> 447 after; 79.4x smaller; 7 complete UTC days ... (2026-11-10 .. 2026-11-16), Identity and Tally growth since the cutover included`). But the before figure is Events rows x 7 only and the after figure is Events plus Identity plus Tally only. The same log shows the total allocated cells across all tabs rose from 2,471,757 before the cutover to 3,008,249 now (30.1% of the 10,000,000-cell limit; 2,689,420 on 2026-11-06 in this file), almost all of it the `Boards` tab (715,520 cells on 2026-11-06, 1,049,696 now: 22,304 to 32,803 rows). So the sheet as a whole grew about 29,000 cells a day over the last 11 days while the ledger tabs shrank. The paragraph, which exists to say what is verified, names only the favourable figure. The earlier section (lines 187-190) was careful to say what the measure does and does not cover; this one dropped that care.
2. **Two statements now contradict it.** The SC3 row still says "the order-of-magnitude drop is **not claimed** (transitional measurement)" and the "Remaining not-verified items" line still lists "a steady-state daily growth figure (re-read `--storage-report` after about 7 more complete UTC days)". The new paragraph supplies exactly that re-read (7 complete days after the first fold, 447) without saying that those two lines are now answered, or by how much. A reader of line 204 and line 7 gets opposite answers.
**Fix:** In the line-7 paragraph add the scope and the total: "447 cells a day is the median over 2026-11-10..16 for Events, Identity and Tally; the total allocated cells across all tabs went 2,471,757 -> 3,008,249 (30.1% of the limit, the growth is the Boards tab, 1,049,696 cells; Events_Legacy, 1,650,502 cells, is kept)". Then update the SC3 row and the "Remaining not-verified items" line to point at run 43990083983: the ledger-tab growth measurement is made (7 days, 79.4x on the report's own basis) and what stays open is the whole-sheet growth, which the report does not measure on a daily basis.

## Info

### IN-01: `parity.py` docstring is wrong about its imports

**File:** `parity.py:3-4` (imports at `:35-39`)
**Issue:** The docstring says the module "imports `compact` and `ledger` only (never state, pipeline or hunter)". It also imports `reporting`, `storage_report` (which imports `state`) and `boards`. No cycle today, but the stated invariant is false. Still open.
**Fix:** State the real constraint (no import of `pipeline` or `hunter`), or move the shared figure code so the claim becomes true.

### IN-02: Removing `Events_Legacy` silently flips a compact system back to dual writing

**File:** `compact.py:604-620` (`effective_mode`, `NOTE_COMPACT_WITHOUT_LEGACY` at `:589`)
**Issue:** If the stored mode is compact and `Events_Legacy` is gone, the poller writes as dual. Baselines go back into Events, and the fold and the check stop. DECISIONS P3-08 describes removing `Events_Legacy` as a later owner decision "with an export plan". As written, that decision cannot be carried out without a code change. `_compact_mode_stored` calls `effective_mode(..., legacy_present=True)`, so the `ensure()` guard also assumes the legacy tab exists. The storage report (run 43990083983) shows `Events_Legacy` at 1,650,502 cells, which is the main reason the owner may want to delete it, so this is more likely to be hit than before. Still open.
**Fix:** Before the owner removes the tab, add a recorded state (for example `storage.legacy_retired_at` or a `--storage-retire-legacy` step) that `effective_mode` and `_compact_mode_stored` honour. Until then, note it in DEPLOY.md.

### IN-03: The workflow lets `storage_cutover` and `storage_restore` run in one job

**File:** `.github/workflows/job_hunter.yml:40-44` and the step guards
**Issue:** The CLI makes the two flags mutually exclusive, but each is a separate workflow step guarded only by its own input. Ticking both runs the cutover and then the restore in the same dispatch. Still open (workflow unchanged; `git diff --stat 68a7253 bc3bea2` shows no `.github` file).
**Fix:** Add a first step that fails when more than one of the owner-step or report inputs is true.

### IN-04: The cutover checksum covers only `key|time|event`

**File:** `compact.py:391-396` (`rows_checksum`)
**Issue:** The comment says the checksum compares "the rows it meant to copy" with the rows read back. It hashes three of the seven columns, so a changed `Freshness`, `Disposition`, `Published` or `Detail` passes. `Events_Legacy` stays whole, so this is not a data-loss path. The cutover is done, so this only matters for a future cutover. Still open.
**Fix:** Hash `"\x1f".join(ev.to_row())` per row.

### IN-05: Dead variable and unused imports

**File:** `reporting.py:492` (`first_event`), `storage_report.py:10,18` (`json`, `fr`)
**Issue:** `first_event` is assigned and never read, and `json` and `fr` are imported and never used. Still open.
**Fix:** Delete them.

### IN-06: Read-only commands read three tabs sequentially without the lease

**File:** `state.py:608` and `state.py:893` (`load_ledger`), `hunter.py` (`run_storage_parity`, `run_storage_report`, `run_pilot_report`), `dashboard.py:594`
**Issue:** `load_ledger` reads Events, then Identity, then Tally with separate calls. A manual `--storage-parity` or `--dashboard` that overlaps a poller run can see Events from before the run and Tally or Identity from after it, which gives counted differences that disappear on the next run. `--storage-parity` also compares the Identity count against `last_check.identity_entries`, which a racing poller run advances. After WR-06 the mark only grows, so a racing read can only produce a false `identity_shrunk` in the direction of an old snapshot against a newer mark. Mitigated by the one-run-at-a-time concurrency group (which does not cover a read-only dispatch of the same workflow only if the group is shared; the runbook's own `storage_parity` pre-check in "Clearing a stuck `identity_shrunk`" is subject to it). Still open.
**Fix:** Document that a parity difference should be re-run before it is trusted, or read all three tabs in one `values_batch_get`.

### IN-07: `first_day` is dated by the fold that ends, not by the one that started

**File:** `compact.py:485` (`fold_record`)
**Issue:** `first = previous.get("first_day") or (_utc_day(now) if rows > 0 or previous.get("started_day") else "")`. When a fold fails after its first delete on day D and finishes on day D+1, `first_day` becomes D+1 although rows went on D. The restore guard is unaffected. `storage_report.py:317` and `:350` read `fold.first_day` as the start of the "after the cutover and first fold" window, so the reported `first_fold_day` is wrong in that case (conservative direction). Still open. (Live: the first fold, run 41549615660, ended cleanly on 2026-11-03, so production is not affected.)
**Fix:** `previous.get("first_day") or previous.get("started_day") or (_utc_day(now) if rows > 0 else "")`.

### IN-08: The Tally carry holds zero-total rows and drops the newest row when full

**File:** `compact.py:726-734` (`keep_tally`), `pipeline.py:371-383` (`carry_tally`)
**Issue:** (1) A run that observed nothing (`total` 0) still takes one of the 20 carry slots and adds a Discovery write per failing run. (2) When the carry is full the newest row is the one left out, and the newest row is the one most likely to hold fresh baseline counts. The cap is deliberate, so this is a robustness note. Still open.
**Fix:** In `carry_tally`, return early when `row.total == 0`; when full, drop the oldest zero-count row first or note `storage tally carry full` in `run.notes`.

### IN-09: The tests do not pin the claim that matters most for the fix, "the fold stays held back"

**File:** `tests/test_storage_parity.py` (the WR-06 loss tests and the WR-08 integration test)
**Issue:** The WR-06 purpose is that an unrepaired loss "holds the fold back" on every later run. None of those tests asserts `storage fold skipped: integrity check counted 1 differences` or that no rows were deleted for `identity_shrunk` specifically (the WR-10 integration test checks the opposite case well). Now that WR-06 is live and DEPLOY.md documents the stuck state as holding the fold back, the unpinned claim is an operator-facing one. Still open.
**Fix:** Assert each degraded run's notes contain `storage fold skipped` when a fold is due, or add a fold test that removes a baseline-only ID and checks the Events row count is unchanged across two runs.

### IN-11: The figure keeps the name "entries" and the Discovery key cannot be renamed lightly

**File:** `compact.py:758-775` (`last_identity_entries`, `identity_entries` parameter), `parity.py:107`, `:329` (`compared["identity_entries"]`), `parity.py:360`
**Issue:** The persisted key, the `compared` key, the parameters and the variables all say "entries" for what is a count of distinct held keys. The runbook now names `last_check.identity_entries` and `compared: identity_entries` as an operator contract, so a rename would break the procedure as well as the persisted state. `check_compact` also reads `compared["identity_entries"]` that `_kept_in_identity` writes, an implicit coupling through a dict. Still open.
**Fix:** Leave the persisted key name alone. Optionally have `_kept_in_identity` return the count instead of reading it back out of `compared`.

### IN-12: The WR-10 fix removes an incidental dual-mode detection of a bare entry, and dual mode has no `identity_entry` check

**File:** `parity.py:82-108` (`_seen_set`), `parity.py:324-327`, `compact.py:188-192`
**Issue:** Before WR-10 a bare `b` entry produced `identity_extra stem|` in the dual-mode check; now `_seen_set` raises nothing, and the `identity_entry` check exists only in `_kept_in_identity` (compact). Production is in compact mode now, so only a restore would put it back in dual mode; low priority. Still open.
**Fix:** Run the `identity_entry` loop from `_identity_invariants` so both modes flag a malformed entry, and add a dual-mode test with a bare `b`.

### IN-13: The runbook documents only half of the repair and only the mild WR-11 case

**File:** `DEPLOY.md:121`, `STATUS.md:24`
**Issue:** (1) The runbook says "restore the missing IDs to `Identity`, for example from `Events_Legacy`" but gives no way to do it: `Identity` is a codec sheet (kind letter plus `%`-escaped ID, chunked, with a `Count` column that the codec checks), no command writes it, and the poller's start-of-run repair rebuilds only Tally groups for an already seeded store (`repair_plan` skips IDs that have a key; it will re-add an Events-held ID but not a baseline-only one, and `Events_Legacy` is not read by it). IDs observed after the cutover exist only in `Identity` and the kept Events rows, so `Events_Legacy` cannot supply them. An owner following the text literally has no safe procedure for the first half; the second half (set the mark) is the only part that is actually executable. (2) The "Known case" sentence and STATUS line 24 describe only a stray or deleted row. The worse case in the review's WR-11 text (a real board's `Board_Key` hand-edited into a non-matching form) leaves `identity_entries` unchanged, so there is no stuck mark to clear; the board's old postings then no longer match the dedupe and can look new (flagged by `identity_missing` only if the board still has kept identity-class Events rows). The runbook's only advice for it is "Do not hand-edit `Board_Key`", with no recovery.
**Fix:** Add: "If a real board's `Board_Key` was edited, set it back to the original lower-case `ats|board` (do not delete the row and do not set the mark); confirm with `storage_parity`." State that the repair of lost IDs is manual and unsupported by tooling today (or give the exact row format), so the owner decides before an incident whether to ask for a repair command.

### IN-14: STATUS labels an inference as a log reading and relies on notes that the public log does not carry

**File:** `STATUS.md:7`
**Issue:** (1) "(the first compact check on the new code recorded the held-key count, so shrink detection starts from the next check)" sits inside the live-evidence parenthesis of the parity run, but no log prints the recorded mark: `Storage:` lines carry only `kept job keys` and `Tally runs`. It follows from the code (`record_compact_check`, mocked-tested) and is probably true; it should be labelled "(by the code, not printed)". (2) Run 44051541803 is said to have "no `storage write failed`, `storage parity:` or `storage fold skipped` note". Those are `Runs.Notes` texts; run notes are not written to the public log (grep of the log for `notes` finds nothing). What the logs do show is the `Storage:` line with 0 counted differences (which excludes `storage parity:`) and no ERROR or WARNING line other than the SmartRecruiters notice (every `storage write failed` path is paired with `log.error`, and the fold skip with `log.warning`, `pipeline.py:990-992`), so the claim is sound by that route. It should say so, or list the `Runs.Notes` check as an owner check as the earlier sections do for sheet-only facts.
**Fix:** Reword both: "not printed; follows from `record_compact_check`" and "no ERROR or WARNING line (every storage-note path logs one); `Runs.Notes` itself is an owner check".

### IN-15: DEPLOY.md still carries statements that are false after the deploy history (pre-existing, outside the diff)

**File:** `DEPLOY.md:3`, `DEPLOY.md:103`, `DEPLOY.md:135`
**Issue:** Line 3 says "Nothing here has been run on GitHub yet: this repository has no remote." The repository is public with an origin and has run for weeks (section 1 of the same file says it is history). Line 103 says the service account writing `Identity` is "not yet verified live ... assumption A2"; STATUS records A2 verified live for the service account's writes (seed run 40924656021; only the Sheet-side confirmation prompt remains an owner check). Line 135 ("Approval needed") is marked done in its own text. The `Compact storage` heading text also describes dual writing only, with the cutover and fold covered further down. None affects behaviour, but a runbook that starts with a false sentence is read less carefully, which matters for the new stuck-mark paragraph in the same file.
**Fix:** Replace line 3 with the current state (repository public, runs hourly via the external dispatcher), update line 103 to "the service account writes it (verified live, STATUS); the confirmation prompt is an owner check", and drop or archive the "Approval needed" section.

---

_Reviewed: 2026-11-17_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
