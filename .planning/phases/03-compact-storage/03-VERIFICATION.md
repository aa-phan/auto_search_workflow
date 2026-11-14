---
phase: 03-compact-storage
verified: 2026-11-14T22:30:00Z
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
covered_digest: "v3:sha256:be9782523befc383b30aded30fef1d936bf79aa49efe78959703161311734498"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: human_needed
  previous_score: 5/6
  gaps_closed: []
  gaps_remaining: []
  regressions: []
unverified_prohibitions:
  - "03-05 / 03-08 / 03-09 (judgment tier): MUST NOT push or dispatch without the owner's explicit choice. NON-AUTHORITATIVE verdict: consistent with the SUMMARYs and STATUS (owner choices deploy-and-dispatch, deploy, agent-dispatches recorded); the review-fix commits WR-01..WR-05 are on the branch only (origin/main is still 68a7253, and the latest GitHub Actions runs all report headSha 68a7253), which is consistent with 'nothing pushed'. The owner's replies themselves are not in any artifact the verifier can read. unverified-prohibition: human review recommended."
  - "03-05 / 03-09 (judgment tier): MUST NOT call a check live without a run id and log line; MUST NOT report the order-of-magnitude drop from fewer than two days or present a projection as a measurement. NON-AUTHORITATIVE verdict: honoured. Every live claim in STATUS names a run id; STATUS says the steady-state order-of-magnitude drop is not claimed; the review-fix section of STATUS labels all five fixes mocked and not deployed. Still flagged because the tier is judgment."
gaps: []
advisory_findings:
  - finding: "WR-06: identity_shrunk is reported for one run, then the lowered Identity entry count becomes the new reference (compact.py record_compact_check), so the fold can resume on a damaged Identity about one hour later. The code matches the trace in 03-REVIEW.md."
    category: other
    reason: "Hardening gap in the WR-02 detection, which itself post-dates the delivered goal and is not deployed. No success criterion or STOR-01 clause requires detection of hand-made Identity loss. Documented in SPEC, D-57 and STATUS as the chosen design. Recommended fix: a high-water mark with an owner acknowledgement step. Tracked as open in 03-REVIEW-DISPOSITION.md."
    evidence_status: "code read and traced in this verification; the pinning test passes and asserts the one-shot behaviour"
human_verification:
  - test: "Hidden tabs and protection (03-UAT.md item 1, still pending). In the real Sheet use right-click on a tab name > Show hidden sheets. Confirm Identity, Tally and Events_Legacy exist and are hidden by default. Then, without saving, try to edit one cell in Identity and one in Events_Legacy."
    expected: "All three tabs exist and are hidden. Each edit attempt shows a warning/confirmation prompt (warning-only whole-sheet protection). Cancel the edit."
    why_human: "Sheet-internal facts. The agent has no Sheet credentials (AGENTS rule 5) and the public Actions log cannot show tab visibility or the prompt."
  - test: "Dashboard Storage line (UAT item 2, pending). Open the Dashboard tab SYSTEM section and NEEDS ATTENTION list."
    expected: "Storage line reads compact since 2026-11-02 (mode compact, last check 0 counted differences). No 'storage parity difference' row under NEEDS ATTENTION. Dashboard figures are plausible next to the pre-cutover Dashboard, and the muted P3-11 note says baseline and older gated/stale totals come from the Tally tab."
    why_human: "Rendered Sheet content; the merged-view figures are proven equal offline (mocked) and by the logged layer-4 checks, but the render was never seen by the agent."
  - test: "Discovery key (UAT item 3, pending). Open the Discovery tab and find the key 'storage' (read only; do not edit)."
    expected: "mode compact, seeded_at 2026-10-29T17:47:52Z, a cutover record (retained_rows 25531, legacy_rows 235785, checksum 33bdd796...), a fold record (rows_total 16752 or more, first_day 2026-11-03). The key is below the 45,000-character cell cap."
    why_human: "Sheet-internal; the Discovery body is not in the public log."
  - test: "Telegram (UAT item 4, pending). Scan the chat from 2026-11-02 01:00 UTC to now for repeated alerts of the same job."
    expected: "No job alerted twice, no flood of old jobs around the cutover (2026-11-02 02:00 UTC) or the folds (00:03 UTC on 11-03 to 11-06 and later)."
    why_human: "Telegram delivery cannot be read without credentials. 'No alert twice' is proven offline (mocked) and the logs show 0 alerts sent at the first compact run; chat content is an owner fact."
  - test: "Steady-state growth re-read (UAT item 5, pending; calendar date about 2026-11-14 is today). With the owner's allowance, dispatch the read-only storage_report input and record the 'median daily growth in allocated cells' line. No storage report newer than 42300947285 (2026-11-06) is recorded in STATUS or PILOT_LOG."
    expected: "A positive or near-zero daily growth in allocated cells at least 10 times below the 35,511 cells/day before figure (3,551 or fewer), over 2 or more complete UTC days NOT dominated by catching up the cutover's retained rows. The report's own projection is about 2,381 cells a day (a model, not a measurement)."
    why_human: "Needs a live dispatch the agent may not make without the owner's choice. The only live after-figure (-2,658 over 2 complete days, both fold days) is transitional and STATUS does not claim the drop at steady state."
  - test: "Fold batch size, research A5 (UAT item 6, pending). Accept A5 as mocked, or confirm on the first large fold that a batch of 500 deleteDimension requests is accepted."
    expected: "Either an explicit owner acceptance that A5 stays mocked, or a log of a fold with at least 500 ranges that did not raise. The four live folds used 94, 131, 88 and 106 ranges."
    why_human: "Cannot be produced on demand; depends on a future fold large enough to hit the batch cap."
  - test: "Deploy decision for the review fixes WR-01..WR-05 (new, not in 03-UAT.md). The commits are on branch gsd/phase-03-compact-storage only; production runs 68a7253 without them. Owner decides whether and when to push. After a deploy, read the first two compact poller runs and one --storage-parity run."
    expected: "No 'storage write failed', 'storage parity:' or 'storage fold skipped' note; the first compact check records Identity entry counts (shrink detection starts from the second check); the next fold still runs. Until then every WR-01..WR-05 behaviour is mocked only."
    why_human: "Pushing or dispatching needs the owner's explicit consent (AGENTS rule 5, prohibitions above). 03-REVIEW-FIX.md marks all five fixes 'requires human verification'."
---

# Phase 3: Compact storage Verification Report

**Phase Goal:** The Events ledger stops growing toward its limit: baseline and identity-only postings live in compact Identity and Tally tabs with parity proven against the old rows, so board growth and new adapters can be admitted safely.
**Verified:** 2026-11-14T22:30:00Z
**Status:** human_needed
**Re-verification:** Yes. The 2026-11-06 report went stale because the review fixes WR-01..WR-05 (a2247a9, 58d9ec2, 024319f, 6648949, 8b02697, docs 60786e7) changed covered files. The previous report had `gaps: []`, so nothing was carried forward as failed. Every truth was re-checked against the current tree, not trusted from the old report.

## What changed since the last report

- Code on the branch now differs from production. `git diff origin/main HEAD` touches `compact.py`, `hunter.py`, `parity.py`, `pipeline.py`, `state.py` and three test files (562 insertions, 56 deletions). `origin/main` is 68a7253, and the newest GitHub Actions runs I listed (the latest created 2026-11-14 22:00 UTC, all `success`) report `headSha` 68a7253. The earlier report's statement that tests run the same code as production no longer holds: **the offline tests now run the fixed branch, the live evidence comes from the unfixed 68a7253.** Both facts are used below with their own labels.
- The fixes are an improvement in defence in depth; none of them touches the delivered write path, seen-set merge, cutover, or fold selection rule that the live evidence rests on (read in `pipeline.py`, `state.py`, `compact.py`).

## Mocked versus live (AGENTS rule 5)

- **Mocked / offline, run by the verifier in this session on branch HEAD (2c19ed8):** `.venv/bin/python -m unittest discover -s tests` printed `Ran 931 tests in 16.784s ... OK` (exit 0). Six tests were then re-run by name and each printed `Ran 1 test ... OK`: `test_baseline_writes_events_one_identity_chunk_and_one_tally_row`, `test_a_run_whose_events_lost_the_baseline_rows_still_treats_those_ids_as_seen`, `test_a_cut_off_compact_baseline_is_a_baseline_pass_again_with_nothing_alerted`, `test_a_seed_whose_tally_append_fails_is_completed_by_the_next_run_with_nothing_written_twice`, `test_the_median_daily_growth_in_allocated_cells_after_the_first_folds_is_at_least_ten_times_smaller_than_with_every_row_kept`, `test_an_id_that_only_identity_holds_and_was_removed_is_counted_identity_shrunk_on_the_next_run`. All use `tests/fake_sheets.py`, the CSV store or hand-built ledgers; nothing touched Sheets, Groq or Telegram.
- **Live (public GitHub Actions logs; run ids recorded in STATUS.md and PILOT_LOG.md; none dispatched by the verifier), all produced by commit 68a7253, i.e. WITHOUT the review fixes:**
  - Cutover run 41373351559 (2026-11-02 01:36 UTC): `25,531 rows now in Events, 235,785 rows kept in Events_Legacy ... nothing was deleted`, checksum `33bdd796...`.
  - Bar met before the cutover, run 41364810371: `3 of 3 complete days toward the bar, admission seen yes`, 0 counted and 0 declared differences.
  - First compact poller run 41375348321 and read-only parity run 41375689814: 0 counted differences.
  - Folds 41549615660, 41743488450, 41938020379 and 42133570806: 2,866 / 5,153 / 4,512 / 4,221 rows (94 / 131 / 88 / 106 ranges); 16,752 rows folded; each `0 kept`.
  - Storage report 42300947285, re-read in this session: `median Runs.Load_S: 12.0 s before ... -> 5.0 s after`, `median daily growth in allocated cells: 35,511 before ... -> -2,658 after; 2 complete UTC days`, `allocated cells, every tab: 2,471,757 before -> 2,689,420 now`.
  - New in this session: `gh run list` shows the poller still succeeding on 68a7253 on 2026-11-14 (four newest runs listed, all `success`). I did not re-scan all runs since 11-06 for storage notes, so no new "0 counted differences" claim is made for 11-07 to 11-14; the 11-06 scan of 108 runs stands as the last full read.
- **Owner checks, not observable by the verifier:** everything inside the Sheet and the Telegram chat (all six items in 03-UAT.md, still `[pending]`, `status: testing`).
- **Mocked only, never produced live:** SC4 (interrupted baseline), "no alert twice", chunk and request-size limits, research A5, restore, and all of WR-01..WR-05.

## Goal Achievement

### Observable Truths (ROADMAP success criteria are the contract)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SC1: hidden Identity tab holds baseline and identity-only IDs in chunks under the cell limit; each run writes a Tally row; a run on the new storage detects no seen job as new and sends no alert twice | ✓ VERIFIED (writes and reads live; "no alert twice" and chunk limits mocked) | Code present (`compact.split_observations`, `IDENTITY_CELL_CHARS`, `pipeline.persist_observations`, `state.load_ledger`). Named behavioral tests re-run and pass (the second is the seen-set invariant). Live: seed run 40924656021 wrote 991 Identity rows and 424 Tally runs; first compact run 41375348321 `alerts 0 sent`, no baseline-pass note. After the review fixes, the Tally write path gained a carry (`pending_tally`, `pipeline.py:488-504`) that retries a failed append instead of leaving an undercount: strengthens, does not alter, the delivered path (mocked). Hidden tabs and Telegram are owner checks. |
| 2 | SC2: read-only `--storage-parity` reports zero differences (seen set, state counts, Dashboard figures) between old Events rows and Identity and Tally, on every run for several consecutive days of dual writing | ✓ VERIFIED (live logs; Dashboard render owner check) | `parity.check_dual` / `check_compact`; live bar `3 of 3 complete days` (run 41364810371, 0 counted differences) and parity runs 40927423338, 41375689814, 42301084151 all `0 counted differences`. Review fix WR-02 adds `identity_shrunk` and `identity_unreadable` to the compact check (`parity.py:_identity_loss`); that is extra and not live. Residual unchanged: the bar was read from one run's log line, not re-derived per day. |
| 3 | SC3 (swap and report): old rows retired by swapping the old tab to `Events_Legacy` (kept, restorable), Events well below the D-03 review point, storage report shows rows, allocated cells and load time before and after | ✓ VERIFIED (live public log; Sheet-side facts owner checks) | Live run 41373351559 and report 42300947285 (re-read above): Events 235,785 rows before, 30,613 now, far below 200,000; Load_S 12.0 s to 5.0 s. WR-01 hardened the restore guard (`pipeline.py:293`, `hunter.py:2225`: refuses on `first_day` or `started_day`) (mocked). **Honest caveat unchanged:** the all-tab total went up (2,471,757 to 2,689,420 allocated cells, 26.9% of 10,000,000) because `Events_Legacy` is kept by design; the Events ledger stopped growing toward its limit, the spreadsheet total did not shrink. |
| 4 | SC3 (growth drop): daily growth in cells falls by an order of magnitude (D-43 estimate 26,200 to 1,300 cells a day) | ? UNCERTAIN (transitional live figure; steady state still not demonstrated) | Same single live measurement as before: 35,511 before to -2,658 after, 2 complete UTC days, both fold days, different measures before and after (Events rows x 7 against allocated cells over every tab). Numerically below 3,551; not an honest demonstration. No storage report after 2026-11-06 is recorded, so the calendar re-read (about 2026-11-14) has not happened. Offline simulation test passes (design proof, synthetic data). Not FAILED: nothing contradicts it and STATUS makes no unearned claim. Routed to human item 5. |
| 5 | SC4: a run interrupted in the middle of a board's baseline never makes that board's old postings look new on the next run | ✓ VERIFIED (mocked only; never produced live) | Behavior-dependent. The two behavioral tests (interrupted compact baseline; seed whose Tally append fails) were re-run and pass on the fixed branch. Code: Identity failure re-raised before `save_boards` in compact mode; `Baselined_At` on the highest chunk. Labelled mocked in STATUS. |
| 6 | Plan must-haves: the fold only deletes durable rows, only in compact mode, never on the cutover day; cutover and restore delete nothing; entry gate recorded | ✓ VERIFIED | `compact.fold_plan` and `state.fold_events` durability checks unchanged in intent; live: four folds each `0 kept`, 0 failures, cutover `nothing was deleted`. Review fixes tighten it: WR-05 skips the fold unless the same run's integrity check counted 0 (`pipeline.py:969-991`, `None` also skips; mocked); WR-01 marker before the first delete (`pipeline.py:293`) (mocked). D-57 recorded as entry gate. No `TBD`, `FIXME` or `XXX` in any phase-touched source or the workflow (grep re-run). |

**Score:** 5/6 truths verified (0 present-but-behavior-unverified). Truth 4 is UNCERTAIN, not FAILED, and is routed to human verification.

### WR-06: gap in the goal, or advisory finding?

**Judgment: advisory, not a gap.** Reasoning, kept apart from what is proven:

- *Verified in code.* `record_compact_check` stores `kept = identity_entries if identity_entries is not None else previous` (`compact.py:753`), so a lowered count replaces the reference. `check_compact` then compares equal counts and reports 0 on the next run, and the fold gate (`check_counted == 0`) reopens. The reviewer's trace is accurate, and the test `test_an_id_that_only_identity_holds_and_was_removed_is_counted_identity_shrunk_on_the_next_run` pins exactly this one-shot behaviour. SPEC, D-57 and STATUS document it. So this is a genuine weakness in the fix, not a mis-description.
- *Why it does not fail the goal.* The goal is that Events stops growing toward its limit and that parity was proven against the old rows before the swap. Both are shown by the live evidence above, which came from 68a7253 **before** any Identity-loss detection existed. The WR-06 scenario needs an external event (a hand edit or bad sort of the hidden, warning-protected tab) that is outside every success criterion and outside STOR-01's wording. Before WR-02 there was no detection at all, so WR-06 leaves the delivered state no worse than the state the goal was demonstrated in; it only means the new detection is weaker than its purpose.
- *Why it still matters.* If that external damage happens, baseline-only IDs vanish permanently (Identity is append-only and nothing re-adds them), boards below `FLOOD_MIN_JOBS` would re-evaluate and re-add old postings, and the signal lasts about one hourly run. That is the exact class of damage the later phases (board growth, new adapters) will amplify. Recommendation for the owner: fix WR-06 with a high-water mark and an acknowledgement step before the first large admission wave (Phase 5), and before deploying the WR-02 change, rather than deploying a detection that clears itself. It stays `open` in 03-REVIEW-DISPOSITION.md.
- Other open items: IN-01 to IN-08 are advisory; IN-02 (removing `Events_Legacy` silently flips a compact system back to dual writing, so the owner cannot delete the tab without a code change) is the one the owner should know before deciding about the 217,663 extra cells.

### Open points judged without rounding up

| Point | Judgment |
|-------|----------|
| (a) SC3 order-of-magnitude drop | Not demonstrated; transitional single reading; calendar re-read still outstanding. Not a gap: nothing missing or contradicted. |
| (b) Sheet-internal facts | Not verifiable by the agent. All six UAT items remain pending. |
| (c) SC4 | Mocked only. VERIFIED by behavioral tests, no live claim. |
| (d) A5 | Mocked; live folds peaked at 131 ranges. |
| (e) Production vs branch | The fixes are not deployed. Everything said about WR-01..WR-05 is mocked. The phase goal as delivered in production does not depend on them. |
| (f) WR-01 from the earlier report | Now fixed on the branch (marker before the first delete). It was already moot in production (`first_day` set 2026-11-03). |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `compact.py` | Identity codec, Tally, split, merged view, fold, cutover records, effective mode | ✓ VERIFIED | Previously named symbols present; new `pending_tally`, `started_day`, `last_identity_entries` also present |
| `parity.py` | `check_dual`, `check_compact` | ✓ VERIFIED | `_identity_loss` added; wired from `pipeline.storage_check` |
| `state.py` | Identity and Tally tabs, `load_ledger`, `write_identity`, `append_tally`, `swap_events`, `fold_events` | ✓ VERIFIED | `fold_touched` in both `SheetState` and `CsvState`; `ensure()` guard in both |
| `pipeline.py` | observation write order, storage step, fold step | ✓ VERIFIED | fold gated on `check_counted` (`pipeline.py:969-991`) |
| `hunter.py` | `--storage-parity`, `--storage-report`, `--storage-cutover`, `--storage-restore` | ✓ VERIFIED | restore guard reads `first_day` or `started_day` (`hunter.py:2225`) |
| `storage_report.py`, `reporting.py`, `dashboard.py`, `pilot.py` | merged-view reports, before/after, Storage line | ✓ VERIFIED | storage report ran live (42300947285); Dashboard render is an owner check |
| `.github/workflows/job_hunter.yml` | four boolean inputs and fixed steps | ✓ VERIFIED (IN-03 open) | `tests/test_deployment.py` passes in the 931-test run; two owner inputs can still be ticked together (IN-03, advisory) |
| `DECISIONS.md` D-57, SPEC, STATUS, PILOT_LOG | decision record, contract, live labels | ✓ VERIFIED | STATUS has a dated fix section labelling all five fixes mocked and not deployed |

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| `run_cycle` load | `state.load_ledger` | one load of Events, Identity, Tally | WIRED |
| observation write point | `split_observations` to `write_identity` to `append_tally` to `save_boards` | `persist_observations`; failed Tally row now carried | WIRED |
| storage check | `parity.check_dual` / `check_compact` | `pipeline.storage_check`, returns `report.counted` | WIRED |
| storage check | fold | `check_counted == 0` required (`pipeline.py:986`) | WIRED (mocked) |
| fold | `compact.fold_plan` to `state.fold_events` to Discovery `storage.fold` | `storage_fold`, marker saved first | WIRED (live for the pre-fix path) |
| owner dispatch `storage_cutover` | `hunter.run_storage_cutover` to `swap_events` | live run 41373351559 | WIRED (live) |
| `--storage-report` | `state.sheet_grid()` and cutover `before` | live run 42300947285 | WIRED (live) |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| Storage report before/after | allocated cells, `Load_S`, daily growth | sheet metadata and `Runs` tab | Yes (live report) | FLOWING |
| Dashboard merged view | `folded` counts | `Ledger.folded()` from Identity, Tally, kept Events | Yes in logs (layer 4 0 differences); render owner check | FLOWING (render unseen) |
| Seen set | Identity keys plus Events `seen` keys | `load_ledger` | Yes (live parity compared 22,426 kept and 232,680 Identity entries on 11-02) | FLOWING |
| Identity entry reference (WR-02/06) | `last_check.identity_entries` | `report.compared["identity_entries"]` | Mocked only; resets downward (WR-06) | FLOWING (mocked; reference ratchets down) |

### Behavioral Spot-Checks (all mocked)

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full offline suite | `.venv/bin/python -m unittest discover -s tests` | Ran 931 tests OK | PASS |
| SC1 writes and seen set (2 named tests) | `discover -s tests -k <name>` | 1 test each, OK | PASS |
| SC4 interrupted baseline and seed (2 named tests) | same | OK | PASS |
| SC3 offline 10x simulation | same | OK (4.4 s; synthetic) | PASS |
| WR-06 pinning test | same | OK (asserts the one-shot behaviour, i.e. confirms WR-06) | PASS |

### Probe Execution

Step 7c: SKIPPED. No probes declared in the phase plans and no `scripts/*/tests/probe-*.sh`.

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|--------------|-------------|--------|----------|
| STOR-01 | 03-01 to 03-09 (all nine PLAN frontmatters list `requirements: [STOR-01]`) | Baseline and identity-only rows stored compactly (Identity and Tally), parity proven before old rows retire, Events stays below the D-03 review point | ✓ SATISFIED in code and live operation; pending owner Sheet checks and the steady-state re-read | Truths 1-3, 5, 6; Events 30,613 rows against 200,000. REQUIREMENTS.md still shows STOR-01 unticked (line 80) and `Pending` (line 145). 03-08 and 03-09 SUMMARYs deliberately leave `requirements-completed: []`; 03-01 to 03-07 list `[STOR-01]`. The orchestrator should tick STOR-01 only after the human items close. |

STOR-01 is the only ID mapped to Phase 3 in REQUIREMENTS.md (traceability line 145) and the only ID in any plan; every ID is accounted for. No orphaned requirements.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `compact.py` | 753 | WR-06: lowered Identity count becomes the reference | Warning (advisory, see above) | Identity-loss signal lasts one run; fold can resume on a damaged Identity |
| `compact.py` | 585-600 | IN-02: removing `Events_Legacy` flips compact to dual | Info | Blocks the owner's later decision to delete the legacy tab until code changes |
| `.github/workflows/job_hunter.yml` | 170-175 | IN-03: cutover and restore can run in one dispatch | Info | Owner error path only |
| `compact.py` | 372-377 | IN-04: checksum covers three of seven columns | Info | `Events_Legacy` stays whole, no data-loss path |
| `reporting.py`, `storage_report.py`, `parity.py`, `state.py`, `compact.py`, `pipeline.py` | various | IN-01, IN-05 to IN-08 | Info | Doc drift, dead code, read race, `first_day` dating, Tally carry quality |

WR-01 to WR-05 from the earlier report are fixed (commits above, each traced in 03-REVIEW.md with 0 critical). No `TBD`, `FIXME` or `XXX` marker in any phase-touched source file (grep re-run this session).

### Human Verification Required

Seven items, listed in the frontmatter. Six come from 03-UAT.md (`status: testing`, all `result: [pending]`, 0 passed); the seventh is new (deploy decision for WR-01..WR-05). 03-UAT.md is accounted for: none of its items is closed by this verification, and none has been marked passed or failed.

### Gates run

| Gate | Result | Source |
|------|--------|--------|
| Validation | 931 offline tests OK, `nyquist_compliant: true` | 03-VALIDATION.md; test run repeated here |
| Security | `threats_open: 0` | 03-SECURITY.md (not re-audited here; read only the header) |
| Code review | 0 critical, 1 warning (WR-06), 8 info; WR-01..WR-05 fixed | 03-REVIEW.md, 03-REVIEW-DISPOSITION.md |
| Regression | 931 tests OK (re-run here, exit 0) | this report |

### Gaps Summary

No failed truth, no missing or stubbed artifact, no broken link, no blocker anti-pattern and no debt marker. The storage design is built, deployed (68a7253), cut over and folding in production; the live logs recorded in STATUS and PILOT_LOG back parity at zero differences before the swap, the swap that deleted nothing, Events falling from 235,785 to 30,613 rows, and four clean folds. The phase stays `human_needed` for the same three reasons as before, none rounded away: the order-of-magnitude growth drop (SC3) has one transitional reading and no steady-state re-read yet; the Sheet-internal facts and the Telegram chat are owner checks (UAT 1-4) and A5 is an owner acceptance (UAT 6); SC4 and "no alert twice" are mocked only. Two things are new. The review fixes are branch-only, so their effect is unverified live and they need the owner's deploy decision. WR-06 is an advisory hardening point that the owner should close before the first large board-admission wave. Separately, "stops growing toward the limit" holds for the Events ledger, not for the spreadsheet total, while `Events_Legacy` is kept. STOR-01 stays unticked in REQUIREMENTS.md until the human items close.

---

_Verified: 2026-11-14T22:30:00Z_
_Verifier: Claude (gsd-verifier)_
