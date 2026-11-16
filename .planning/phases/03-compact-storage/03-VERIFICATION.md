---
phase: 03-compact-storage
verified: 2026-11-16T08:00:00Z
status: human_needed
score: 5/6 must-haves verified
covered_files:
  - ".github/workflows/job_hunter.yml"
  - ".planning/phases/03-compact-storage/03-01-PLAN.md"
  - ".planning/phases/03-compact-storage/03-01-SUMMARY.md"
  - ".planning/phases/03-compact-storage/03-02-PLAN.md"
  - ".planning/phases/03-compact-storage/03-02-SUMMARY.md"
  - ".planning/phases/03-compact-storage/03-03-PLAN.md"
  - ".planning/phases/03-compact-storage/03-03-SUMMARY.md"
  - ".planning/phases/03-compact-storage/03-04-PLAN.md"
  - ".planning/phases/03-compact-storage/03-04-SUMMARY.md"
  - ".planning/phases/03-compact-storage/03-05-PLAN.md"
  - ".planning/phases/03-compact-storage/03-05-SUMMARY.md"
  - ".planning/phases/03-compact-storage/03-06-PLAN.md"
  - ".planning/phases/03-compact-storage/03-06-SUMMARY.md"
  - ".planning/phases/03-compact-storage/03-07-PLAN.md"
  - ".planning/phases/03-compact-storage/03-07-SUMMARY.md"
  - ".planning/phases/03-compact-storage/03-08-PLAN.md"
  - ".planning/phases/03-compact-storage/03-08-SUMMARY.md"
  - ".planning/phases/03-compact-storage/03-09-PLAN.md"
  - ".planning/phases/03-compact-storage/03-09-SUMMARY.md"
  - "DECISIONS.md"
  - "PILOT_LOG.md"
  - "SPEC.md"
  - "STATUS.md"
  - "compact.py"
  - "dashboard.py"
  - "hunter.py"
  - "parity.py"
  - "pilot.py"
  - "pipeline.py"
  - "reporting.py"
  - "state.py"
  - "storage_report.py"
  - "tests/fake_sheets.py"
  - "tests/test_compact.py"
  - "tests/test_deployment.py"
  - "tests/test_hunter.py"
  - "tests/test_reporting.py"
  - "tests/test_storage_cutover.py"
  - "tests/test_storage_parity.py"
  - "tests/test_storage_pipeline.py"
  - "tests/test_storage_report.py"
covered_digest: "v3:sha256:243406ab7412cbb6a478dd98f07445510238b04cfe71a93a11474d827410f1e3"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: human_needed
  previous_score: 5/6
  gaps_closed: []
  gaps_remaining: []
  regressions: []
unverified_prohibitions:
  - "03-05 / 03-08 / 03-09 (judgment tier): MUST NOT push or dispatch without the owner's explicit choice. NON-AUTHORITATIVE verdict: consistent with the SUMMARYs and STATUS. `git ls-remote origin main` printed 68a7253 in this session and the four newest GitHub Actions runs (latest created 2026-11-16 07:17 UTC, all `success`) report headSha 68a7253. That is consistent with 'nothing pushed'. The owner's replies themselves are not in any artifact the verifier can read. unverified-prohibition: human review recommended."
  - "03-05 / 03-09 (judgment tier): MUST NOT call a check live without a run id and log line; MUST NOT present a projection as a measurement or claim the order-of-magnitude drop from fewer than two days. NON-AUTHORITATIVE verdict: honoured. Every live claim in STATUS names a run id; STATUS says the steady-state order-of-magnitude drop is NOT claimed; the review-fix section of STATUS labels WR-01..WR-09 mocked and not deployed. Still flagged because the tier is judgment."
gaps: []
advisory_findings:
  - finding: "WR-10 (open in 03-REVIEW-DISPOSITION.md): an Identity entry with no posting ID (a bare kind letter such as `b` or `x`) counts as a held key (`stem|`), so deleting it, the only possible repair for it, raises a permanent `identity_shrunk`. Reproduced in this session: IdentitySet.from_rows([IdentityRow('g|a',1,'t',2,'bA,b')]) gives distinct_count() 2 and keys() {g|a|, g|a|A}; the same set without the bare `b` gives 1. `stem_and_id` (compact.py:51-57) returns None for an empty posting ID, so no job key can ever equal `stem|`, and the writer never emits such an entry."
    category: other
    reason: "A false permanent alarm in undeployed hardening, not a gap in the phase goal and not a lost ID. Production (68a7253) has no shrink detection and no distinct_count, so WR-10 cannot have affected any live evidence. The trigger is an external event (a hand edit or a cell cut mid-entry leaves a bare kind letter in a hidden, warning-protected tab), the owner then deleting it, and the mark having been recorded while it was present. Failure mode is loud, not silent: every later run is degraded, NEEDS ATTENTION, and the WR-05 gate holds the fold back so Events keeps growing until the owner edits `storage.last_check.identity_entries` in Discovery by hand (undocumented, IN-10). No ID is lost and the dedupe is unaffected (the empty key matches nothing). The docs (SPEC.md, D-57, STATUS) now match the code and say a bare kind letter holds the empty key and counts like any held key, so the behaviour is documented, but the reviewer asks the owner to confirm it was meant."
    evidence_status: "code read and reproduced in this verification (mocked, in-process, not a deployed or live finding); the WR-09 tests pin the empty key as intended (`(3, 3)` in the bare-kind case), no test deletes a bare entry after the mark was recorded"
human_verification:
  - test: "Hidden tabs and protection (03-UAT.md item 1, pending). In the real Sheet use right-click on a tab name > Show hidden sheets. Confirm Identity, Tally and Events_Legacy exist and are hidden by default. Then, without saving, try to edit one cell in Identity and one in Events_Legacy."
    expected: "All three tabs exist and are hidden. Each edit attempt shows a warning/confirmation prompt (warning-only whole-sheet protection). Cancel the edit."
    why_human: "Sheet-internal facts. The agent has no Sheet credentials (AGENTS rule 5) and the public Actions log cannot show tab visibility or the prompt."
  - test: "Dashboard Storage line (UAT item 2, pending). Open the Dashboard tab SYSTEM section and NEEDS ATTENTION list."
    expected: "Storage line reads compact since 2026-11-02 (mode compact, last check 0 counted differences). No 'storage parity difference' row under NEEDS ATTENTION. Dashboard figures are plausible next to the pre-cutover Dashboard, and the muted P3-11 note says baseline and older gated/stale totals come from the Tally tab."
    why_human: "Rendered Sheet content; merged-view figures are proven equal offline (mocked) and by the logged layer-4 checks, but the render was never seen by the agent."
  - test: "Discovery key (UAT item 3, pending). Open the Discovery tab and find the key 'storage' (read only; do not edit)."
    expected: "mode compact, seeded_at 2026-10-29T17:47:52Z, a cutover record (retained_rows 25531, legacy_rows 235785, checksum 33bdd796...), a fold record (rows_total 16752 or more, first_day 2026-11-03). The key is below the 45,000-character cell cap."
    why_human: "Sheet-internal; the Discovery body is not in the public log."
  - test: "Telegram (UAT item 4, pending). Scan the chat from 2026-11-02 01:00 UTC to now for repeated alerts of the same job."
    expected: "No job alerted twice, no flood of old jobs around the cutover (2026-11-02 02:00 UTC) or the folds (00:03 UTC on 11-03 to 11-06 and later)."
    why_human: "Telegram delivery cannot be read without credentials. 'No alert twice' is proven offline (mocked); the logs show 0 alerts sent at the first compact run; chat content is an owner fact."
  - test: "Steady-state growth re-read (UAT item 5, pending; the calendar date, about 2026-11-14, has passed). With the owner's allowance, dispatch the read-only storage_report input and record the 'median daily growth in allocated cells' line. No storage report newer than 42300947285 (2026-11-06) is recorded in STATUS or PILOT_LOG."
    expected: "A positive or near-zero daily growth in allocated cells at least 10 times below the 35,511 cells/day before figure (3,551 or fewer), over 2 or more complete UTC days NOT dominated by catching up the cutover's retained rows. The report's own projection is about 2,381 cells a day (a model, not a measurement)."
    why_human: "Needs a live dispatch the agent may not make without the owner's choice. The only live after-figure (-2,658 over 2 complete days, both fold days) is transitional and STATUS does not claim the drop at steady state."
  - test: "Fold batch size, research A5 (UAT item 6, pending). Accept A5 as mocked, or confirm on the first large fold that a batch of 500 deleteDimension requests is accepted."
    expected: "Either an explicit owner acceptance that A5 stays mocked, or a log of a fold with at least 500 ranges that did not raise. The four live folds used 94, 131, 88 and 106 ranges."
    why_human: "Cannot be produced on demand; depends on a future fold large enough to hit the batch cap."
  - test: "Deploy decision for the review fixes WR-01..WR-09 and the open warning WR-10 (UAT item 7, pending; the UAT text is stale: it names WR-01..WR-08, calls WR-09 open and describes the WR-08 predicate design, whereas WR-09 is now fixed by e86993e and WR-10 is the open one). The commits are on branch gsd/phase-03-compact-storage only; production runs origin/main 68a7253 without any of them. The owner decides whether and when to push, and whether to resolve WR-10 first (the reviewer's fix: skip the empty posting ID in `IdentitySet._reindex`, `if pid: kinds.setdefault(pid, kind)`, so a bare kind letter is flagged `identity_entry`, counts for nothing and deleting it is not a shrink; or confirm that a bare entry counting as a held key is intended and add a runbook line for clearing a stuck mark, IN-10). After a deploy, read the first two compact poller runs and one --storage-parity run."
    expected: "No 'storage write failed', 'storage parity:' or 'storage fold skipped' note; the first compact check records the distinct held-key count (shrink detection starts from the second check); the next fold still runs. Until then every WR-01..WR-09 behaviour is mocked only."
    why_human: "Pushing or dispatching needs the owner's explicit consent (AGENTS rule 5, prohibitions above). 03-REVIEW-FIX.md marks the fixes 'requires human verification'. The WR-10 fix-first-or-accept choice is the owner's."
---

# Phase 3: Compact storage Verification Report

**Phase Goal:** The Events ledger stops growing toward its limit: baseline and identity-only postings live in compact Identity and Tally tabs with parity proven against the old rows, so board growth and new adapters can be admitted safely.
**Verified:** 2026-11-16T08:00:00Z
**Status:** human_needed
**Re-verification:** Yes. The report of 2026-11-15 20:16 went stale because fix commit e86993e (review finding WR-09) changed `compact.py`, `parity.py`, `tests/test_storage_parity.py`, SPEC, D-57 and STATUS. The previous report had `gaps: []`, so nothing was carried forward as failed. I re-checked what WR-09 touched against the current tree, and the other truths against the current tree, not from the old report.

## What changed since the previous report

- **WR-09 (e86993e) is in the tree and resolved.** `IdentitySet.distinct_count()` is now `sum(len(kinds) for kinds in self._kinds.values())` (`compact.py:225-232`), exactly `len(keys())` (`:215-216`). `_valid` and its upkeep are gone: `_reindex` (`:183-190`) and `copy` (`:192-197`) keep only `_kinds`. `entry_well_formed` (`compact.py:70-75`) survives only as the `identity_entry` predicate in `parity.check_compact`. The mark, the stored figure, the `identity_shrunk` comparison and the dedupe now read one set by construction. I reproduced the old defect's inputs on the current code: a mixed entry `bA,xB,b%2c` gives `distinct_count() 3` and `keys() {g|a|A, g|a|B, g|a|%2c}`; a lone `xB` gives `distinct_count() 1`, `len() 1`, `keys() {g|a|B}`. The count and the dedupe agree. The four tests that pin this (`test_the_identity_count_is_exactly_the_set_of_keys...`, `test_deleting_a_malformed_entry_whose_id_the_dedupe_holds_is_counted_identity_shrunk`, and the two `test_a_malformed_identity_entry...` / `test_deleting_a_malformed_identity_entry...` integration tests) ran by name: `Ran 4 tests ... OK`. Mocked, not deployed.
- **A new warning, WR-10, is open** (see its section below). `03-REVIEW.md` is 0 critical, 1 warning (WR-10), 11 info; `03-REVIEW-DISPOSITION.md` records WR-01..WR-09 and IN-12 fixed, WR-10 and IN-01..IN-11 open. `03-VALIDATION.md` (nyquist compliant) and `03-SECURITY.md` (`threats_open: 0`) were read as re-run clean, not re-audited here.
- **Production is unchanged.** `git ls-remote origin main` printed `68a7253c938c...`. `gh run list` shows the four newest runs (latest created 2026-11-16 07:17 UTC) `success`, all with headSha 68a7253. **The offline tests run the fixed branch; the live evidence comes from the unfixed 68a7253.** At 68a7253 `compact.py` has no `entry_well_formed`, `distinct_count` or `identity_entries`, and `parity.py` has no `identity_shrunk`.

## Mocked versus live (AGENTS rule 5)

- **Mocked / offline, run by the verifier in this session on branch HEAD (6009cdc):** `.venv/bin/python -m unittest discover -s tests` printed `Ran 942 tests in 15.762s` (exit 0, from the saved output). `-m unittest tests.test_storage_parity -k test_the_identity_count_is_exactly -k test_deleting_a_malformed -k test_a_malformed` printed `Ran 4 tests ... OK`. The WR-09 and WR-10 reproductions are in-process calls on hand-built `IdentityRow`s. Nothing touched Sheets, Groq or Telegram. I did not run a mutation check against the WR-09 tests.
- **Live, read today by the verifier from the public Actions log (read-only):** run 43820674982 (headSha 68a7253), `hunt` job, 2026-11-16 07:03:11 UTC: `Storage: mode=compact, 0 counted and 0 declared differences, 21954 kept job keys and 911 Tally runs compared, check took 2.1 s`. (Runs 43822715466 and 43820680369 printed no `Storage:` line to my grep; I did not investigate why, and one clean read is what I rely on.) Produced by 68a7253, **without WR-01..WR-09**, so it proves production compact mode is clean today and says nothing about the fixes.
- **Live, carried from the earlier reports and STATUS (run ids recorded there; not re-read this session):** cutover run 41373351559 (`25,531 rows now in Events, 235,785 rows kept in Events_Legacy ... nothing was deleted`); bar met before the cutover, run 41364810371 (3 of 3 complete days, 0 counted differences); first compact poller run 41375348321 and parity run 41375689814 (0 counted differences); folds 41549615660, 41743488450, 41938020379, 42133570806 (2,866 / 5,153 / 4,512 / 4,221 rows, 94 / 131 / 88 / 106 ranges, 16,752 rows, each `0 kept`); storage report 42300947285 (Load_S 12.0 s to 5.0 s; daily growth 35,511 to -2,658 cells over 2 complete UTC days; allocated cells over every tab 2,471,757 to 2,689,420). The verifier dispatched no workflow.
- **Owner checks, not observable by the verifier:** everything inside the Sheet and the Telegram chat (03-UAT.md items 1-6, all `[pending]`, `status: testing`, 0 passed of 7).
- **Mocked only, never produced live:** SC4 (interrupted baseline), "no alert twice", chunk and request-size limits, research A5, restore, and all of WR-01..WR-09.

## Goal Achievement

### Observable Truths (ROADMAP success criteria are the contract)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SC1: hidden Identity tab holds baseline and identity-only IDs in chunks under the cell limit; each run writes a Tally row; a run on the new storage detects no seen job as new and sends no alert twice | ✓ VERIFIED (writes and reads live; "no alert twice" and chunk limits mocked) | Code present (`compact.IdentitySet`, `IDENTITY_CELL_CHARS`, `plan_additions`, `pipeline.persist_observations`, `state.load_ledger`), covered by the 942-test pass. Live: seed run 40924656021 wrote 991 Identity rows and 424 Tally runs; first compact run 41375348321 `alerts 0 sent`; today's run 43820674982 compares 21,954 kept job keys and 911 Tally runs with 0 differences. WR-09 simplified the count to `len(keys())` and did not change `keys()` or `plan_additions` (both still read `_kinds`), so the seen set is unchanged. Hidden tabs and Telegram are owner checks. |
| 2 | SC2: read-only `--storage-parity` reports zero differences (seen set, state counts, Dashboard figures) between old Events rows and Identity and Tally, on every run for several consecutive days of dual writing | ✓ VERIFIED (live logs; Dashboard render owner check) | `parity.check_dual` / `check_compact` present and wired from `pipeline.storage_check`. Live: bar `3 of 3 complete days` (run 41364810371), parity runs 40927423338, 41375689814, 42301084151 all `0 counted differences`, plus today's compact check. WR-02/06/07/08/09/10 concern `identity_shrunk` and `identity_entry` on top of this: extra and not live. Residual unchanged: the bar was read from one run's log line, not re-derived per day. |
| 3 | SC3 (swap and report): old rows retired by swapping the old tab to `Events_Legacy` (kept, restorable), Events well below the D-03 review point, storage report shows rows, allocated cells and load time before and after | ✓ VERIFIED (live public log; Sheet-side facts owner checks) | Live run 41373351559 and report 42300947285: Events 235,785 rows before, 30,613 now, far below 200,000; Load_S 12.0 s to 5.0 s. **Caveat unchanged:** the all-tab total rose (2,471,757 to 2,689,420 allocated cells) because `Events_Legacy` is kept by design. The Events ledger stopped growing toward its limit; the spreadsheet total did not shrink. |
| 4 | SC3 (growth drop): daily growth in cells falls by an order of magnitude (D-43 estimate 26,200 to 1,300 cells a day) | ? UNCERTAIN (transitional live figure; steady state not demonstrated) | One live measurement: 35,511 before to -2,658 after, 2 complete UTC days, both fold days, with different measures before and after (Events rows x 7 against allocated cells over every tab). Numerically below 3,551, not an honest demonstration. No storage report newer than 2026-11-06 is recorded. The offline simulation test (synthetic data) passes. Not FAILED: nothing contradicts it and STATUS makes no unearned claim. Routed to human item 5. |
| 5 | SC4: a run interrupted in the middle of a board's baseline never makes that board's old postings look new on the next run | ✓ VERIFIED (mocked only; never produced live) | Behavior-dependent. The behavioral tests (interrupted compact baseline; seed whose Tally append fails) ran in the 942-test pass; I did not re-run them by name this session. WR-09 does not touch the write path or `plan_additions` (diff: `compact.py` count and `_reindex`/`copy`, `parity.py`, one test file, docs). Labelled mocked in STATUS. |
| 6 | Plan must-haves: the fold only deletes durable rows, only in compact mode, never on the cutover day; cutover and restore delete nothing; entry gate recorded | ✓ VERIFIED | `fold_due` requires stored mode compact and a UTC day after the cutover day; live: four folds each `0 kept`, cutover `nothing was deleted`. On the branch the fold is additionally gated on the same run's check (WR-05) and writes a marker before the first delete (WR-01), both mocked. Debt-marker grep (`TBD\|FIXME\|XXX`) over `compact.py parity.py state.py pipeline.py hunter.py dashboard.py reporting.py storage_report.py pilot.py` and the workflow returned no match (re-run this session, exit 1 = no match). |

**Score:** 5/6 truths verified (0 present-but-behavior-unverified). Truth 4 is UNCERTAIN, not FAILED, and is routed to human verification.

### WR-09: resolved on the branch (mocked)

Verified in code (above), by reproduction, and by four named tests. The previous report's advisory finding (count over `_valid`, dedupe over `_kinds`, docs claiming they are the same) is closed: the code now makes the claim in SPEC.md, D-57 and the `distinct_count` docstring true. I read DECISIONS.md:511 and STATUS.md:18-21: both describe WR-09 as fixed, mocked and not deployed, and make no live claim. Mocked, not deployed.

### WR-10: does it affect goal achievement? No. Advisory, with a deploy-time owner decision.

**Judgment: advisory (warning severity), not a gap. The phase goal is achieved without regard to WR-10.**

- *What it is, verified.* `decode_entry("b")` returns `("b", "")`, `_reindex` does `kinds.setdefault("", "b")`, so a bare kind letter adds `stem|` to `keys()` and to `distinct_count()`. Reproduced: `bA,b` gives 2 and `{g|a|, g|a|A}`; `bA` gives 1. The empty key cannot match any posting (`stem_and_id` returns None for an empty ID, `compact.py:51-57`) and the writer never emits it. The reviewer's trace holds: a stray `b` or `x` entry is flagged `identity_entry` and raises the mark by one; deleting it, the only possible repair for an entry with no ID, falls the count below the mark, so `identity_shrunk` is counted on every later check. The docs say a bare kind letter "holds the empty key `stem|` ... counts like any held key" (D-57, STATUS), so the code matches the docs; what remains is that the repair rule "rewrite, never delete" has no canonical form to rewrite to for this entry.
- *Why it does not fail the goal.* The goal is that Events stops growing and that parity was proven against the old rows before the swap. Both rest on live evidence from 68a7253, which has no Identity-loss detection of any kind, so WR-10 cannot have affected them. On this axis the branch is strictly stronger than production: it detects the loss of every held ID. No success criterion and no STOR-01 clause requires detection of hand-made Identity damage, and no ID is lost or made falsely new by WR-10 (the dedupe is unchanged; the empty key matches nothing).
- *How narrow the harm is.* Needs (1) an external event that leaves a bare kind letter in a hidden, warning-protected tab (the live check reads 0 counted differences today, which includes `identity_entry`, so none exists in production now), (2) the mark recorded while it was present, and (3) the owner deleting it. Failure mode is loud, not silent: runs degrade, NEEDS ATTENTION shows, and the WR-05 gate holds the fold back. The one cost that bears on the goal's wording is that a held-back fold lets Events grow until the owner edits `storage.last_check.identity_entries` in Discovery by hand, which STATUS does not document (IN-10). That is a hardening-ergonomics cost conditioned on three unlikely events in an undeployed change, not a failure of "Events stops growing toward its limit", which production demonstrates (235,785 to 30,613 rows, four clean folds).
- *Not rounded down.* The branch should not be deployed while this false permanent alarm stands unless the owner accepts it. No test deletes a bare entry after the mark was recorded; the test comment and assertion pin the empty key as intended, so the reviewer rightly asks the owner to confirm. Fix options: (1) in `_reindex`, `if pid: kinds.setdefault(pid, kind)`, so check and dedupe still agree and a bare entry counts for nothing (change the `(3, 3)` bare-kind case to `(2, 2)`, add the delete test); or (2) confirm the behaviour as intended and add the runbook line from IN-10.

### Open points judged without rounding up

| Point | Judgment |
|-------|----------|
| (a) SC3 order-of-magnitude drop | Not demonstrated; one transitional reading; the calendar re-read (about 2026-11-14) is past and has not happened. Not a gap: nothing missing or contradicted. |
| (b) Sheet-internal facts | Not verifiable by the agent. UAT items 1-6 pending. |
| (c) SC4 | Mocked only. VERIFIED by behavioral tests, no live claim. |
| (d) A5 | Mocked; live folds peaked at 131 ranges against a 500 cap. |
| (e) Production vs branch | The fixes WR-01..WR-09 are not deployed. Everything said about them is mocked. The phase goal as delivered in production does not depend on them. |
| (f) WR-10 | Advisory (warning severity), see above. Open in the disposition. |
| (g) 03-UAT.md item 7 is stale | It still names WR-01..WR-08 and calls WR-09 open. This report's human item 7 replaces it (WR-01..WR-09 fixed, WR-10 open). 03-UAT.md was not edited by the verifier. |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `compact.py` | Identity codec, Tally, split, merged view, fold, cutover records, effective mode | ✓ VERIFIED | `entry_well_formed` `:70`, `IdentitySet._reindex` `:183`, `keys` `:215`, `distinct_count` `:225`, `record_compact_check` high-water mark, `fold_due` |
| `parity.py` | `check_dual`, `check_compact` | ✓ VERIFIED | `_identity_invariants`, `_identity_loss` takes the figure computed once; wired from `pipeline.storage_check` |
| `state.py` | Identity and Tally tabs, `load_ledger`, `write_identity`, `append_tally`, `swap_events`, `fold_events` | ✓ VERIFIED | Covered by the 942-test run; unchanged by WR-09; not re-read line by line |
| `pipeline.py` | observation write order, storage step, fold step | ✓ VERIFIED | Covered by the suite; unchanged by WR-09 |
| `hunter.py` | `--storage-parity`, `--storage-report`, `--storage-cutover`, `--storage-restore` | ✓ VERIFIED | Suite passes |
| `storage_report.py`, `reporting.py`, `dashboard.py`, `pilot.py` | merged-view reports, before/after, Storage line | ✓ VERIFIED | storage report ran live (42300947285); Dashboard render is an owner check |
| `.github/workflows/job_hunter.yml` | four boolean inputs and fixed steps | ✓ VERIFIED (IN-03 open) | `tests/test_deployment.py` passes in the 942-test run |
| `DECISIONS.md` D-57, `SPEC.md`, `STATUS.md`, `PILOT_LOG.md` | decision record, contract, live labels | ✓ VERIFIED | STATUS labels WR-01..WR-09 mocked, not deployed; D-57 and STATUS describe the count as `len(keys())`, which the code now is; the bare-kind empty key is documented. STATUS does not yet mention WR-10 (the review that found it is later) |

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| `run_cycle` load | `state.load_ledger` | one load of Events, Identity, Tally | WIRED |
| observation write point | `split_observations` to `write_identity` to `append_tally` to `save_boards` | `persist_observations`; failed Tally row carried | WIRED |
| storage check | `parity.check_dual` / `check_compact` | `pipeline.storage_check`, returns `report.counted` | WIRED |
| `check_compact` | `IdentitySet.distinct_count` | `_identity_invariants` returns it once; `_identity_loss` takes it | WIRED (mocked) |
| `IdentitySet.keys()` (dedupe) | `distinct_count` (mark) | `distinct_count` is `sum(len(kinds))` over the same `_kinds` that `keys()` expands | SAME SET (WR-09 closed); WR-10 notes `stem|` is in that set |
| storage check | `record_compact_check` | `identity_entries` from `compared["identity_entries"]`, high-water mark | WIRED (mocked) |
| storage check | fold | `check_counted != 0` skips the fold | WIRED (mocked) |
| owner dispatch `storage_cutover` | `hunter.run_storage_cutover` to `swap_events` | live run 41373351559 | WIRED (live) |
| `--storage-report` | `state.sheet_grid()` and cutover `before` | live run 42300947285 | WIRED (live) |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| Storage report before/after | allocated cells, `Load_S`, daily growth | sheet metadata and `Runs` tab | Yes (live report) | FLOWING |
| Dashboard merged view | `folded` counts | `Ledger.folded()` from Identity, Tally, kept Events | Yes in logs (0 differences, 21,954 keys and 911 Tally runs today); render owner check | FLOWING (render unseen) |
| Seen set | Identity keys plus Events `seen` keys | `load_ledger`, `IdentitySet.keys()` | Yes (21,954 kept keys compared today) | FLOWING |
| Identity mark (WR-02/06/07/09) | `last_check.identity_entries` | `IdentitySet.distinct_count()` via `compared["identity_entries"]` | Mocked only; count of held keys, high-water mark; includes the empty key for a bare kind letter (WR-10) | FLOWING (mocked; WR-10 caveat) |

### Behavioral Spot-Checks (all mocked unless stated)

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full offline suite | `.venv/bin/python -m unittest discover -s tests` | Ran 942 tests OK, exit 0 | PASS (mocked) |
| WR-09 tests | `-m unittest tests.test_storage_parity -k test_the_identity_count_is_exactly -k test_deleting_a_malformed -k test_a_malformed` | Ran 4 tests OK | PASS (mocked) |
| WR-09 closed: count equals dedupe | `IdentitySet.from_rows([IdentityRow("g\|a",1,"t",3,"bA,xB,b%2c")])` | `distinct_count()` 3; `keys()` A, B, %2c | PASS (mocked) |
| WR-09 closed: lone malformed entry | set holding only `xB` | `distinct_count()` 1, `len()` 1, `keys()` `{g\|a\|B}` | PASS (mocked) |
| WR-10 reproduction: bare kind letter | `IdentityRow("g\|a",1,"t",2,"bA,b")` | `distinct_count()` 2; `keys()` `{g\|a\|, g\|a\|A}` | CONFIRMS the advisory |
| Production check today (live, read-only log) | `gh run view 43820674982 --log` grep `Storage:` | `0 counted and 0 declared differences, 21954 kept job keys and 911 Tally runs compared` | PASS (live, 68a7253) |

### Probe Execution

Step 7c: SKIPPED. No probes declared in the phase plans and no `scripts/*/tests/probe-*.sh`.

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|--------------|-------------|--------|----------|
| STOR-01 | 03-01 to 03-09 (all nine PLAN frontmatters list `requirements: [STOR-01]`, confirmed in the earlier verification and not changed since) | Baseline and identity-only rows stored compactly (Identity and Tally), parity proven before old rows retire, Events stays below the D-03 review point | ✓ SATISFIED in code and live operation; pending owner Sheet checks and the steady-state re-read | Truths 1-3, 5, 6; Events 30,613 rows against 200,000; today's check 0 differences. REQUIREMENTS.md still shows STOR-01 unticked (line 80) and `Pending` (line 145). The orchestrator should tick STOR-01 only after the human items close. |

STOR-01 is the only ID mapped to Phase 3 in REQUIREMENTS.md (traceability line 145) and the only ID in any plan; every ID is accounted for. No orphaned requirements.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `compact.py` | 183-190, 225-232 | WR-10: bare kind letter holds the empty key `stem|`, counts as a held key; its only repair, deletion, is a permanent `identity_shrunk` | Warning (advisory, see above) | False permanent alarm and a held-back fold until a manual Discovery edit; no ID lost; undeployed |
| `compact.py` | 585-600 | IN-02: removing `Events_Legacy` flips compact to dual | Info | Blocks the owner's later decision to delete the legacy tab until code changes |
| `.github/workflows/job_hunter.yml` | 170-175 | IN-03: cutover and restore can run in one dispatch | Info | Owner error path only |
| `compact.py` | 372-377 | IN-04: checksum covers three of seven columns | Info | `Events_Legacy` stays whole; no data-loss path |
| `tests/test_storage_parity.py` | 777-822, 927-958, 990-1010 | IN-09: no test names "fold held back" for `identity_shrunk` or `identity_entry` | Info | Claims rest on the WR-05 gate tests plus code reading |
| various | | IN-01, IN-05..IN-08, IN-10, IN-11 | Info | Doc drift, dead code, read race, `first_day` dating, Tally carry quality, no repair tooling or runbook for a stuck mark, figure still named "entries" |

WR-01 to WR-09 are fixed (commits a2247a9, 58d9ec2, 024319f, 6648949, 8b02697, e83d563, 9fd3383, c845065, e86993e). No `TBD`, `FIXME` or `XXX` marker in any phase-touched source file (grep re-run, exit 1).

### Human Verification Required

Seven items, listed in the frontmatter. Six come from 03-UAT.md (`status: testing`, all `result: [pending]`, 0 passed); the seventh is UAT item 7, the deploy decision, rewritten here because the UAT text is stale (see point (g)). None of the UAT items is closed by this verification, and none has been marked passed or failed. Item 5's calendar date has passed without a re-read.

### Gates run

| Gate | Result | Source |
|------|--------|--------|
| Validation | 942 offline tests OK; nyquist compliant, re-run clean after WR-09 | 03-VALIDATION.md; suite re-run here |
| Security | `threats_open: 0` | 03-SECURITY.md (read; not re-audited here) |
| Code review | 0 critical, 1 warning (WR-10), 11 info; WR-01..WR-09 fixed | 03-REVIEW.md, 03-REVIEW-DISPOSITION.md (read) |
| Regression | 942 tests OK (re-run here, exit 0) | this report |

### Gaps Summary

No failed truth, no missing or stubbed artifact, no broken link, no blocker anti-pattern and no debt marker. The storage design is built, deployed (68a7253), cut over and folding in production. The live logs recorded in STATUS and PILOT_LOG back parity at zero differences before the swap, a swap that deleted nothing, Events falling from 235,785 to 30,613 rows and four clean folds, and today's production compact check (run 43820674982) again reads 0 counted and 0 declared differences. The phase stays `human_needed` for the same reasons as before, none rounded away: the order-of-magnitude growth drop (SC3) has one transitional reading and no steady-state re-read yet; the Sheet-internal facts and the Telegram chat are owner checks (UAT 1-4) and A5 is an owner acceptance (UAT 6); SC4 and "no alert twice" are mocked only. Two points are specific to this round. WR-09 is closed: the previous report's advisory finding no longer holds and the docs now match the code. The new open warning WR-10 does not affect goal achievement: it is a false permanent alarm for a stray entry with no posting ID, in hardening that production does not have in any form, with a narrow trigger, a loud failure mode and no lost ID. The owner should fix it or consciously accept it before deploying the branch, and UAT item 7 should be updated to name WR-01..WR-09 fixed and WR-10 open. Separately, "stops growing toward the limit" holds for the Events ledger, not for the spreadsheet total, while `Events_Legacy` is kept. STOR-01 stays unticked in REQUIREMENTS.md until the human items close.

---

_Verified: 2026-11-16T08:00:00Z_
_Verifier: Claude (gsd-verifier)_
