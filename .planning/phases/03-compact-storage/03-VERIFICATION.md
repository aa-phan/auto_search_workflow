---
phase: 03-compact-storage
verified: 2026-11-06T23:10:00Z
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
covered_digest: "v3:sha256:e8325171b2f9b8cd20042a1df20d1bf13ca7f9e55e5fd2a28fa23cffb6782845"
behavior_unverified: 0
overrides_applied: 0
unverified_prohibitions:
  - "03-05 / 03-08 / 03-09 (judgment tier): MUST NOT push or dispatch without the owner's explicit choice. NON-AUTHORITATIVE verdict: consistent with the SUMMARYs and STATUS (owner choices deploy-and-dispatch, deploy, agent-dispatches are recorded), but the owner's replies are not in any artifact the verifier can read. unverified-prohibition: human review recommended."
  - "03-05 / 03-09 (judgment tier): MUST NOT call a check live without a run id and log line; MUST NOT report the order-of-magnitude drop from fewer than two days or present a projection as a measurement. NON-AUTHORITATIVE verdict: honoured. Every live claim in STATUS names a run id (re-read here), and STATUS says the order-of-magnitude drop is not claimed. Still flagged because the tier is judgment."
gaps: []
human_verification:
  - test: "Hidden tabs and protection. In the real Sheet use right-click on a tab name > Show hidden sheets. Confirm Identity, Tally and Events_Legacy exist and are hidden by default. Then, without saving, try to edit one cell in Identity and one in Events_Legacy."
    expected: "All three tabs exist and are hidden. Each edit attempt shows a warning/confirmation prompt (warning-only whole-sheet protection). Cancel the edit."
    why_human: "Sheet-internal facts. The agent has no Sheet credentials (AGENTS rule 5) and the public Actions log cannot show tab visibility or the prompt. Live evidence shows only that the service account's writes succeed."
  - test: "Dashboard Storage line. Open the Dashboard tab SYSTEM section and NEEDS ATTENTION list."
    expected: "Storage line reads compact since 2026-11-02 (mode compact, last check 0 counted differences). No 'storage parity difference' row under NEEDS ATTENTION. The Dashboard figures (tracker rows, new jobs this week, baseline totals) are plausible next to the pre-cutover Dashboard, and the muted P3-11 note says baseline and older gated/stale totals come from the Tally tab."
    why_human: "Rendered Sheet content. The merged-view figures are proven equal to the old-Events figures offline and by the logged layer-4 checks, but the render was never seen by the agent."
  - test: "Discovery key. Open the Discovery tab and find the key 'storage' (read only; do not edit)."
    expected: "mode compact, seeded_at 2026-10-29T17:47:52Z, a cutover record (retained_rows 25531, legacy_rows 235785, the logged checksum 33bdd796...), a fold record (rows_total 16752 or more, first_day 2026-11-03). The key is below the 45,000-character cell cap."
    why_human: "Sheet-internal; the Discovery body is not in the public log."
  - test: "Telegram. Scan the chat from 2026-11-02 01:00 UTC to now for repeated alerts of the same job."
    expected: "No job alerted twice, no flood of old jobs around the cutover (2026-11-02 02:00 UTC) or the folds (00:03 UTC on 11-03, 11-04, 11-05, 11-06)."
    why_human: "Telegram delivery cannot be read without credentials. 'No alert twice' is proven offline (mocked) and the logs show alerts 0 sent at the first compact run, but chat content is an owner fact."
  - test: "Steady-state growth re-read (calendar item, about 2026-11-14). Owner or agent, with the owner's allowance, dispatch the read-only storage_report input after about 7 more complete UTC days of folds, and record the 'median daily growth in allocated cells' line."
    expected: "A positive or near-zero daily growth in allocated cells that is at least 10 times below the 35,511 cells/day before figure (that is, 3,551 or fewer), measured over 2 or more complete UTC days that are NOT dominated by catching up the cutover's retained rows. The report's own projection is about 2,381 cells a day (a model, not a measurement)."
    why_human: "Needs calendar time. The only live after-figure (-2,658 over 2 complete days, both fold days) is transitional and STATUS does not claim the drop at steady state; SC3's order-of-magnitude clause is therefore not yet demonstrated."
  - test: "Fold batch size (research A5). Decide whether to accept A5 as mocked, or to confirm on the first large fold (for example after board growth) that a batch of 500 deleteDimension requests is accepted."
    expected: "Either an explicit owner acceptance that A5 stays mocked, or a log of a fold with at least 500 ranges that did not raise. The four live folds used 94, 131, 88 and 106 ranges, all under 500, so a full-size batch has never been sent live."
    why_human: "Cannot be produced on demand; depends on a future fold large enough to hit the batch cap."
---

# Phase 3: Compact storage Verification Report

**Phase Goal:** The Events ledger stops growing toward its limit: baseline and identity-only postings live in compact Identity and Tally tabs with parity proven against the old rows, so board growth and new adapters can be admitted safely.
**Verified:** 2026-11-06T23:10:00Z
**Status:** human_needed
**Re-verification:** No, initial verification

## Mocked versus live (AGENTS rule 5)

- **Mocked / offline, run by the verifier in this session:** `.venv/bin/python -m unittest discover -s tests` gives `Ran 910 tests ... OK` (exit 0). The five storage modules alone (`test_storage_pipeline`, `test_storage_parity`, `test_storage_cutover`, `test_storage_report`, `test_compact`) give `Ran 256 tests ... OK`. Six tests named in STATUS as SC evidence were each re-run by name and pass. All of them use `tests/fake_sheets.py`, an in-memory Sheets fake. The code on `origin/main` (68a7253) is byte-identical to HEAD for every `.py` and workflow file; only STATUS.md and PILOT_LOG.md and planning docs differ, so the tests run the code that is in production.
- **Live (public GitHub Actions logs, re-read read-only by the verifier with `gh run view <id> --log`, nothing dispatched):**
  - Cutover run 41373351559: `STORAGE CUTOVER done ... mode compact`, `25,531 rows now in Events, 235,785 rows kept in Events_Legacy (hidden, warning-protected); nothing was deleted`, checksum line, `before: 235,785 Events rows, 2,471,757 allocated cells in total (1,650,502 in Events), median load 12 s ... daily growth 5073 rows`.
  - Bar met before the cutover, run 41364810371: `3 of 3 complete days toward the bar, admission seen yes`, 0 counted and 0 declared differences, 234,037 job keys.
  - First compact poller run 41375348321 and read-only parity run 41375689814: 0 counted differences, `bar met yes`.
  - Folds: 41549615660 (2,866 rows, 94 ranges), 41743488450 (5,153 / 131), 41938020379 (4,512 / 88), 42133570806 (4,221 / 106), each `0 kept (0 not in Identity, 0 without a Tally count)`; 16,752 rows folded in total.
  - All 111 workflow runs since 2026-11-03 00:00 UTC were fetched in this session (108 poller runs with a `Storage: mode=` line, 1 failed poller run 41669619936, a parity run and a storage-report run): **0** lines with counted differences, **0** occurrences of `storage fold failed`, `storage cutover incomplete`, `storage write failed`, `storage repair failed`, `storage check failed` or `storage parity:`. The one failed run is a transient Sheets 500 in the tracker append (traceback not re-read in full here; its log has no `Storage:` line, consistent with STATUS).
  - Storage report 42300947285 and parity 42301084151: figures below.
- **Owner checks, not observable by the verifier:** everything inside the Sheet (tab visibility, protection prompts, the Dashboard render, the Discovery key) and the Telegram chat. Listed under Human Verification.
- **Not observed live, mocked only:** SC4 (interrupted baseline), "no alert twice", chunk and request-size limits, research A5 (a 500-request `deleteDimension` batch), the restore, the WR-01 path.

## Goal Achievement

### Observable Truths (ROADMAP success criteria are the contract)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SC1: hidden Identity tab holds baseline and identity-only IDs in chunks under the cell limit; each run writes a Tally row; a run on the new storage detects no seen job as new and sends no alert twice | ✓ VERIFIED (writes and reads live; "no alert twice" and chunk limits mocked) | Code: `compact.split_observations` (`compact.py:278`), `IDENTITY_CELL_CHARS = 40_000` (`compact.py:26`), write order Events, Identity, Tally, Boards in `pipeline.persist_observations` (`pipeline.py:336-366`), merged seen view from `state.load_ledger` (`pipeline.py:296`). Tests re-run and pass: `test_baseline_writes_events_one_identity_chunk_and_one_tally_row`, `test_a_run_whose_events_lost_the_baseline_rows_still_treats_those_ids_as_seen` (behavioral test for the seen-set invariant), `test_compact_mode_keeps_baselines_out_of_events_but_not_gated_or_stale_rows`. Live: seed run 40924656021 wrote 991 Identity rows and 424 Tally runs; 108 poller logs read 0 counted differences; first compact run found `new jobs 30 (27 verified fresh)`, `alerts 0 sent`, no baseline-pass note. Alertable jobs are `pending` rows that never fold, so a fold or cutover cannot make an alerted job alertable again (code review confirms). Hidden tabs and Telegram are owner checks (human items 1, 4). |
| 2 | SC2: read-only `--storage-parity` reports zero differences (seen set, state counts, Dashboard figures) from old Events rows and from Identity and Tally, on every run for several consecutive days of dual writing | ✓ VERIFIED (live logs; Dashboard render owner check) | `parity.check_dual` (`parity.py:287`) with layers 1-4; `hunter.run_storage_parity` (`hunter.py:2008`). Live: run 41364810371 `3 of 3 complete days toward the bar` (2026-10-30, -10-31, -11-01, each at least 12 checked runs, admission seen) with 0 counted differences; parity runs 40927423338 (dual), 41375689814 and 42301084151 (compact) all `0 counted differences`. `tests.test_storage_parity` read-only tests pass (a read-only run writes nothing). Residual: the bar was read from one run's log line, not re-derived per day by the verifier; the per-day dual-mode logs before 2026-11-03 were not re-fetched. |
| 3 | SC3 (swap and report): only after parity, old rows retired by swapping the old tab to `Events_Legacy` (kept and restorable), Events well below the D-03 review point, storage report shows rows, allocated cells and load time before and after | ✓ VERIFIED (live public log; Sheet-side facts owner checks) | Cutover gated on `bar.met` plus a fresh four-layer parity, one atomic rename batch (`state.swap_events`, `state.py:517`; `hunter.run_storage_cutover`, `hunter.py:2045`). Live: run 41373351559 above. Report 42300947285 (re-read): Events 235,785 rows before, 30,613 rows now (well below 200,000); Events cells 1,650,502 before, 214,298 now; median `Runs.Load_S` 12.0 s before, 5.0 s after; total allocated cells 2,471,757 before, 2,689,420 now (26.9% of the 10,000,000-cell limit). **Honest caveat:** the all-tab total went UP by 217,663 cells because `Events_Legacy` (1,650,502 cells) is deliberately kept; the Events ledger stopped growing toward the limit, the spreadsheet as a whole did not shrink. That matches the ROADMAP note ("Keep `Events_Legacy` until parity holds; nothing is deleted before then") and is not a failure; it is an open owner decision (delete `Events_Legacy` later, which per review IN-02 needs a code change first). |
| 4 | SC3 (growth drop): daily growth in cells falls by an order of magnitude (D-43 estimate 26,200 to 1,300 cells a day) | ? UNCERTAIN (transitional live figure; steady state not demonstrated) | Report 42300947285: median daily growth **35,511 before -> -2,658 after**, over the minimum **2 complete UTC days** (2026-11-04 and -11-05), both fold days (5,153 and 4,512 rows folded). Read literally, -2,658 is below one tenth of 35,511 (3,551), so the threshold is met numerically. It is not an honest demonstration of the criterion: the after figure is negative (the tab shrank), it comes from two days while the fold was still working through the rows retained at the cutover (25,531 retained against about 40,000 planned; four daily folds of 2,866 / 5,153 / 4,512 / 4,221 rows), and the before figure is Events rows x 7 while the after figure is allocated cells over every tab, so the two are not the same measure. The report's steady-state lines (`compact design: ~2,381 cells a day`, old design `~30,366 cells a day`, about 12.8x) are model projections. STATUS states the drop is "not claimed" at steady state, which this verification agrees with. Offline: `test_the_median_daily_growth_in_allocated_cells_after_the_first_folds_is_at_least_ten_times_smaller_than_with_every_row_kept` passes (synthetic data only; it proves the design, not the live system). Not FAILED: the number was measured as the plan required and nothing contradicts it. Routed to the calendar item (human item 5, re-read about 2026-11-14). |
| 5 | SC4: a run interrupted in the middle of a board's baseline never makes that board's old postings look new on the next run (baselined only after the last chunk is written) | ✓ VERIFIED (mocked only; never produced live) | Behavior-dependent truth; behavioral tests re-run and pass: `test_a_cut_off_compact_baseline_is_a_baseline_pass_again_with_nothing_alerted` (cut off after chunk k, zero `pending` events and zero alerts on the next run, each ID exactly once, marker on the highest chunk) and `test_a_seed_whose_tally_append_fails_is_completed_by_the_next_run_with_nothing_written_twice`. Code: in compact mode an Identity failure is re-raised before `save_boards` (`pipeline.py:352-359`), the `Baselined_At` marker is on the highest chunk. Mocked only, labelled so in STATUS. |
| 6 | Plan must-haves: the fold only deletes durable rows, only in compact mode, never on the cutover day; cutover and restore delete nothing; entry gate recorded | ✓ VERIFIED | `compact.fold_plan` requires the posting ID in the Identity set read at run start and a Tally group with at least the retained count (`compact.py:410`); `state.fold_events` re-reads key and event columns and refuses the whole fold if any planned row no longer holds the planned key as a `seen` row (`state.py:551-572`), descending ranges, 500 per batch. Live: four folds, each `0 kept (0 not in Identity, 0 without a Tally count)`, 0 failures. Cutover only adds a tab and renames (no delete; live line `nothing was deleted`). D-57 recorded (`DECISIONS.md:439`) as the entry gate. Workflow inputs and the REQUIRE_TELEGRAM / poller-step exclusions are present for all four storage inputs (`job_hunter.yml:40-44, 119, 136, 170, 175`). No `TBD`, `FIXME` or `XXX` in any phase-touched source file. |

**Score:** 5/6 truths verified (0 present-but-behavior-unverified). Truth 4 is UNCERTAIN, not FAILED, and is routed to human verification.

### Open points judged without rounding up

| Point | Judgment |
|-------|----------|
| (a) SC3 order-of-magnitude drop | Not demonstrated. The measured figure meets the threshold only numerically (-2,658 against 3,551) and is transitional (negative, 2 days, both fold days, different measures before and after). Truth 4 is UNCERTAIN; human item 5 re-reads about 2026-11-14. Not a gap because nothing is missing or contradicted and STATUS makes no unearned claim. |
| (b) Sheet-internal facts | `Events_Legacy` hidden and protected, the Dashboard Storage line and the Discovery key are not verifiable by the agent. Human items 1 to 3. |
| (c) SC4 | Mocked only. Behavioral tests pass, so the truth is VERIFIED (mocked) rather than PRESENT_BEHAVIOR_UNVERIFIED, but never produced live; no live claim is made. |
| (d) A5 | Mocked. The live folds used at most 131 ranges per day, so a 500-request batch has not been exercised. Human item 6 (accept or wait). Low operational risk today because daily folds are far below the cap. |
| (e) WR-01 | Confirmed present in code, see Anti-Patterns. Production already has `fold.first_day` set (the first fold, 41549615660, recorded it; later fold lines carry running `rows_total` 8,019, 12,531, 16,752), and `storage_restore` is already refused, so it has no effect on this deployment. It is a real defect for any future cutover. Warning, not a gap, because it falsifies no must-have for this phase's delivered state. |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `compact.py` | Identity codec, Tally, split, merged view, fold, cutover records, effective mode | ✓ VERIFIED | all named symbols present (`identity_class`, `split_observations`, `simulate_compact`, `retained_events`, `fold_plan`, `delete_ranges`, `fold_record`, `effective_mode`) |
| `parity.py` | `check_dual`, `check_compact` | ✓ VERIFIED | `parity.py:287`, `:362`; wired in `pipeline.py:231-234` |
| `state.py` | Identity and Tally tabs, `load_ledger`, `write_identity`, `append_tally`, `swap_events`, `fold_events`, `sheet_grid` (Sheet and CSV) | ✓ VERIFIED | both `SheetState` and `CsvState` implement each |
| `pipeline.py` | observation write order, storage step, fold step, `FOLD_CUTOFF_S` | ✓ VERIFIED | `persist_observations`, `storage_fold`, `repair_plan` at `pipeline.py:431` |
| `hunter.py` | `--storage-parity`, `--storage-report`, `--storage-cutover`, `--storage-restore` | ✓ VERIFIED | `hunter.py:1977, 2008, 2045, 2198` |
| `storage_report.py`, `reporting.py`, `dashboard.py`, `pilot.py` | merged-view reports, before/after, Storage line | ✓ VERIFIED | storage report ran live (42300947285); Dashboard render is an owner check |
| `.github/workflows/job_hunter.yml` | four boolean inputs and fixed steps | ✓ VERIFIED | see truth 6; `tests/test_deployment.py` passes in the full suite |
| `DECISIONS.md` D-57, SPEC, STATUS, PILOT_LOG | decision record, contract, live labels | ✓ VERIFIED | D-57 at `DECISIONS.md:439`; PILOT_LOG rows 2026-10-29 17:46, 10-30 00:59, 11-02 01:36, 11-03 00:03 |

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| `run_cycle` load | `state.load_ledger` | one load of Events, Identity, Tally (`pipeline.py:296`) | WIRED |
| observation write point | `split_observations` -> `write_identity` -> `append_tally` -> `save_boards` | `persist_observations` (`pipeline.py:336-366`) | WIRED |
| storage check | `parity.check_dual` / `check_compact` | `pipeline.py:231-234` | WIRED |
| fold | `compact.fold_plan` -> `state.fold_events` -> Discovery `storage.fold` | `storage_fold` (`pipeline.py:272`) | WIRED |
| owner dispatch `storage_cutover` | `hunter.run_storage_cutover` -> `swap_events` | live run 41373351559 | WIRED (live) |
| `--storage-report` | `state.sheet_grid()` + cutover `before` | live run 42300947285 | WIRED (live) |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| Storage report before/after | allocated cells, `Load_S`, daily growth | sheet metadata and `Runs` tab through `state.sheet_grid` | Yes (live report printed real figures) | FLOWING |
| Dashboard merged view | `folded` counts | `Ledger.folded()` from Identity, Tally and kept Events | Yes in logs (layer 4 compared 981+ figures, 0 differences); render owner check | FLOWING (render unseen) |
| Seen set | Identity keys plus Events `seen` keys | `load_ledger` | Yes (25,970 kept keys, 253,769 Identity entries in the last parity run) | FLOWING |

### Behavioral Spot-Checks (all mocked)

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full offline suite | `.venv/bin/python -m unittest discover -s tests` | Ran 910 tests OK | PASS |
| Storage modules | `-m unittest tests.test_storage_pipeline tests.test_storage_parity tests.test_storage_cutover tests.test_storage_report tests.test_compact` | Ran 256 tests OK | PASS |
| SC1 writes and seen set (3 named tests) | `discover -s tests -k <name>` | 1 test each, OK | PASS |
| SC4 interrupted baseline and interrupted seed (2 named tests) | `discover -s tests -k <name>` | OK | PASS |
| SC3 offline 10x simulation | `discover -s tests -k test_the_median_daily_growth...` | OK (4.0 s) | PASS |

### Probe Execution

Step 7c: SKIPPED. No probes declared in the phase plans and no `scripts/*/tests/probe-*.sh`.

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|--------------|-------------|--------|----------|
| STOR-01 | 03-01 through 03-09 (all nine list `requirements: [STOR-01]`) | Baseline and identity-only rows stored compactly (Identity and Tally, D-43 amended), parity proven before old rows retire, Events stays below the D-03 review point | ✓ SATISFIED in code and live operation; pending owner Sheet checks and the steady-state re-read | Truths 1-3, 5, 6. Events at 30,613 rows against the 200,000 point. `.planning/REQUIREMENTS.md` still shows STOR-01 unticked (line 80) and `Pending` (line 145); 03-09-SUMMARY deliberately sets `requirements-completed: []`. The orchestrator should tick it only after the human items are closed. |

STOR-01 is the only ID mapped to Phase 3 in REQUIREMENTS.md (traceability line 145) and the only ID in any plan frontmatter. No orphaned requirements.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `pipeline.py` / `compact.py` | 272-278 / 457-466 | WR-01 (re-confirmed): `storage_fold` calls `state.fold_events` before any `fold.first_day` is recorded; `fold_record` sets `first_day` only afterward and only when rows were deleted. A failure after batch 1, or a failed Discovery save, leaves deleted rows with the restore guard open | Warning | No effect on this deployment (first_day already set, restore already refused). For any future cutover, `--storage-restore` could be allowed after rows were folded, losing per-job rows (IDs survive, so no duplicate alert). Fix: record `first_day` and save before the first delete |
| `parity.py` / `state.py` | 301-332 / 315-335 | WR-02: the compact integrity check cannot detect Identity loss; `ensure()` recreates a deleted Identity tab silently | Warning | Silent re-evaluation and tracker clutter if Identity were lost; mitigated by warning-only protection (owner check 1) |
| `pipeline.py` | 358-364 | WR-03: a Tally write failure in compact mode becomes a permanent undercount (AGENTS rule 4) | Warning | Baseline totals on the Dashboard could be understated for good after one transient Sheets error. None seen in 108 live runs |
| `state.py` | 629-633 | WR-04: `write_identity` rewrites rows from a possibly stale cache | Warning | Narrow failure window; none observed live |
| `pipeline.py` | 885-909 | WR-05: the fold does not consult the integrity check that ran in the same run | Warning | Irreversible delete does not gate on `report.counted`; 0 counted differences in every live run so far |
| various | | IN-01 to IN-06 | Info | Documentation drift, workflow input combinations, checksum scope, dead code |

All of WR-01 to WR-05 and IN-01 to IN-06 are `open` in 03-REVIEW-DISPOSITION.md (advisory, 0 critical). None falsifies a success criterion as delivered; WR-01 to WR-05 weaken defence in depth for the live compact mode and for any future cutover. The ROADMAP-gated work that follows (board growth, new adapters) relies on this storage, so the owner should triage WR-02, WR-03 and WR-05 before the first large admission wave. No `TBD`, `FIXME` or `XXX` markers in phase-touched sources.

### Human Verification Required

Six items, detailed in the frontmatter `human_verification` list:

1. **Hidden tabs and protection** (Identity, Tally, Events_Legacy hidden; edit prompt appears).
2. **Dashboard Storage line** (compact since 2026-11-02; no NEEDS ATTENTION row; figures plausible; P3-11 note).
3. **Discovery `storage` key** (mode compact, cutover and fold records).
4. **Telegram chat** (no duplicate alert, no flood around the cutover and folds).
5. **Steady-state growth re-read about 2026-11-14** (calendar; closes truth 4).
6. **A5 acceptance** (500-request batch never sent live; accept as mocked or confirm on a large fold).

### Gates already run this session

| Gate | Result | Source |
|------|--------|--------|
| Validation | 15 automated commands green, `nyquist_compliant: true` | 03-VALIDATION.md |
| Security | 46/46 threats closed, `threats_open: 0` | 03-SECURITY.md |
| Code review | 0 critical, 5 warnings, 6 info, all open and advisory | 03-REVIEW.md, 03-REVIEW-DISPOSITION.md |
| Regression | 910 tests OK (re-run here) | this report |

### Gaps Summary

No failed truth, no missing or stubbed artifact, no broken link and no blocker anti-pattern. The storage design is built, deployed, cut over and folding in production, and the live logs the verifier re-read back the central claims: parity read zero differences across the dual-write days and the bar was met before the swap, the swap kept `Events_Legacy` and deleted nothing, Events fell from 235,785 to 30,613 rows, and 108 poller runs since the first fold read zero counted differences and no storage note. The phase is `human_needed`, not `passed`, for three reasons that are not rounded away. First, the order-of-magnitude growth drop (SC3) has one transitional live reading (two fold days, negative, mixed measures) and needs a steady-state re-read around 2026-11-14. Second, the Sheet-internal facts and the Telegram chat are owner checks the agent cannot see. Third, SC4 and "no alert twice" are mocked only. Separately, the all-tab cell total rose to 26.9% of the limit because `Events_Legacy` is kept; that is by design, but it means "stops growing toward the limit" holds for the Events ledger, not for the spreadsheet total, until the owner decides about `Events_Legacy`. STOR-01 stays unticked in REQUIREMENTS.md until the human items close.

---

_Verified: 2026-11-06T23:10:00Z_
_Verifier: Claude (gsd-verifier)_
