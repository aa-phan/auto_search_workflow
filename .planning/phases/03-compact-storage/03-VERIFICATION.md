---
phase: 03-compact-storage
verified: 2026-11-14T23:30:00Z
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
covered_digest: "v3:sha256:5bc5f9e53a4ca027bc1e9308d5565235f54e9b0cafd7b9c554e6026e2876916d"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: human_needed
  previous_score: 5/6
  gaps_closed: []
  gaps_remaining: []
  regressions: []
unverified_prohibitions:
  - "03-05 / 03-08 / 03-09 (judgment tier): MUST NOT push or dispatch without the owner's explicit choice. NON-AUTHORITATIVE verdict: consistent with the SUMMARYs and STATUS. The fix commits WR-01..WR-06 are on the branch only: `git ls-remote origin main` printed 68a7253 in this session, and the three newest GitHub Actions runs (latest created 2026-11-14 22:34 UTC, all `success`) report headSha 68a7253. That is consistent with 'nothing pushed'. The owner's replies themselves are not in any artifact the verifier can read. unverified-prohibition: human review recommended."
  - "03-05 / 03-09 (judgment tier): MUST NOT call a check live without a run id and log line; MUST NOT present a projection as a measurement or claim the order-of-magnitude drop from fewer than two days. NON-AUTHORITATIVE verdict: honoured. Every live claim in STATUS names a run id; STATUS says the steady-state order-of-magnitude drop is NOT claimed; the review-fix section of STATUS labels WR-01..WR-06 mocked and not deployed. Still flagged because the tier is judgment."
gaps: []
advisory_findings:
  - finding: "WR-07 (open in 03-REVIEW-DISPOSITION.md): the WR-06 high-water mark counts raw Identity entries, duplicates included, and is raised by a check that itself counted identity_duplicate. Removing the duplicate (the correct repair) lowers the count, so the next check reports identity_shrunk on every run until the owner edits the Discovery storage key or puts a junk entry back. The code matches the reviewer's trace (compact.py:753, parity.py `_identity_invariants` sums `len(row.entries())`, `_identity_loss` compares `entries < entries_before`)."
    category: other
    reason: "Defect in undeployed hardening (WR-02 detection plus the WR-06 fix), reachable only after an external event (a bad write or hand edit that duplicates a posting ID in the hidden, warning-protected Identity tab). It fails closed (fold held back, run degraded, Events grows; no alert, no deletion, no data loss) and does not touch the delivered write path, seen-set merge, cutover or fold selection that the live evidence rests on. No success criterion or STOR-01 clause requires detection of hand-made Identity damage. Not a gap in the phase goal; a defect in the new hardening that should be fixed before it is deployed."
    evidence_status: "code read and traced in this verification; no existing test exercises duplicate-then-remove (the review's recommended test is not yet written)"
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
  - test: "Steady-state growth re-read (UAT item 5, pending; the calendar date, about 2026-11-14, is today). With the owner's allowance, dispatch the read-only storage_report input and record the 'median daily growth in allocated cells' line. No storage report newer than 42300947285 (2026-11-06) is recorded in STATUS or PILOT_LOG."
    expected: "A positive or near-zero daily growth in allocated cells at least 10 times below the 35,511 cells/day before figure (3,551 or fewer), over 2 or more complete UTC days NOT dominated by catching up the cutover's retained rows. The report's own projection is about 2,381 cells a day (a model, not a measurement)."
    why_human: "Needs a live dispatch the agent may not make without the owner's choice. The only live after-figure (-2,658 over 2 complete days, both fold days) is transitional and STATUS does not claim the drop at steady state."
  - test: "Fold batch size, research A5 (UAT item 6, pending). Accept A5 as mocked, or confirm on the first large fold that a batch of 500 deleteDimension requests is accepted."
    expected: "Either an explicit owner acceptance that A5 stays mocked, or a log of a fold with at least 500 ranges that did not raise. The four live folds used 94, 131, 88 and 106 ranges."
    why_human: "Cannot be produced on demand; depends on a future fold large enough to hit the batch cap."
  - test: "Deploy decision for the review fixes WR-01..WR-06 (UAT item 7, pending; the UAT text still says WR-01..WR-05 and its 'consider fixing WR-06' sentence is out of date because WR-06 is fixed). The commits are on branch gsd/phase-03-compact-storage only; production runs origin/main 68a7253 without them. Owner decides whether and when to push, and whether to fix the open warning WR-07 first (removing a duplicate Identity entry after the mark was raised leaves a permanent identity_shrunk). After a deploy, read the first two compact poller runs and one --storage-parity run."
    expected: "No 'storage write failed', 'storage parity:' or 'storage fold skipped' note; the first compact check records the Identity entry count (shrink detection starts from the second check); the next fold still runs. Until then every WR-01..WR-06 behaviour is mocked only."
    why_human: "Pushing or dispatching needs the owner's explicit consent (AGENTS rule 5, prohibitions above). 03-REVIEW-FIX.md marks the fixes 'requires human verification'. The WR-07 fix-first-or-accept choice is the owner's."
---

# Phase 3: Compact storage Verification Report

**Phase Goal:** The Events ledger stops growing toward its limit: baseline and identity-only postings live in compact Identity and Tally tabs with parity proven against the old rows, so board growth and new adapters can be admitted safely.
**Verified:** 2026-11-14T23:30:00Z
**Status:** human_needed
**Re-verification:** Yes. The report of earlier today went stale because review fix WR-06 (e83d563) changed `compact.py`, `tests/test_storage_parity.py`, SPEC, D-57 and STATUS. The previous report had `gaps: []`, so nothing was carried forward as failed. Every truth was re-checked against the current tree, not trusted from the old report.

## What changed since the previous report

- WR-06 (e83d563) is now in the tree. I read the diff and the surrounding code: `record_compact_check` stores `kept = max(previous or 0, identity_entries) if identity_entries is not None else previous` (`compact.py:753`). A lower count no longer replaces the reference, so an unrepaired Identity loss is counted on every compact check and the WR-05 fold gate (`pipeline.py:986`, `check_counted != 0` skips the fold) holds the fold back. The previous report's advisory WR-06 is therefore **closed on the branch (mocked, not deployed)**.
- The fresh incremental review (0 critical, 1 warning WR-07, 10 info) and the disposition (WR-01..WR-06 fixed; WR-07, IN-01..IN-10 open) were read.
- Production is unchanged: `git ls-remote origin main` printed `68a7253c938c...`, and `gh run list` shows the three newest runs (created 2026-11-14 22:00, 22:17 and 22:34 UTC) `success` with headSha 68a7253. `git diff origin/main HEAD` outside `.planning` touches 12 files (703 insertions, 66 deletions). So **the offline tests run the fixed branch, the live evidence comes from the unfixed 68a7253.**

## Mocked versus live (AGENTS rule 5)

- **Mocked / offline, run by the verifier in this session on branch HEAD (3f14471):** `.venv/bin/python -m unittest discover -s tests` printed `Ran 934 tests in 16.404s ... OK` (exit 0; the line is in the saved output). Seven tests were then re-run by name and each printed `Ran 1 test ... OK`: `test_the_recorded_identity_count_is_a_high_water_mark`, `test_an_id_that_only_identity_holds_and_was_removed_is_counted_identity_shrunk_on_the_next_run`, `test_baseline_writes_events_one_identity_chunk_and_one_tally_row`, `test_a_run_whose_events_lost_the_baseline_rows_still_treats_those_ids_as_seen`, `test_a_cut_off_compact_baseline_is_a_baseline_pass_again_with_nothing_alerted`, `test_a_seed_whose_tally_append_fails_is_completed_by_the_next_run_with_nothing_written_twice`, and the growth-simulation test from the earlier run. (The `test_a_loss_nobody_repairs` prefix I also passed matched one test.) All use `tests/fake_sheets.py`, the CSV store or hand-built ledgers; nothing touched Sheets, Groq or Telegram.
- **Live (public GitHub Actions logs; run ids recorded in STATUS.md and PILOT_LOG.md; none dispatched by the verifier), all produced by 68a7253, i.e. WITHOUT the review fixes.** I did not re-read these logs in this session; they are carried from the 2026-11-06 report, where each was read, and from STATUS:
  - Cutover run 41373351559 (2026-11-02): `25,531 rows now in Events, 235,785 rows kept in Events_Legacy ... nothing was deleted`.
  - Bar met before the cutover, run 41364810371: 3 of 3 complete days, 0 counted differences.
  - First compact poller run 41375348321 and parity run 41375689814: 0 counted differences.
  - Folds 41549615660, 41743488450, 41938020379, 42133570806: 2,866 / 5,153 / 4,512 / 4,221 rows (94 / 131 / 88 / 106 ranges), 16,752 rows, each `0 kept`.
  - Storage report 42300947285: Load_S 12.0 s to 5.0 s; daily growth 35,511 to -2,658 cells over 2 complete UTC days; allocated cells over every tab 2,471,757 to 2,689,420.
  - New this session, from `gh run list` only: the poller still succeeds on 68a7253 through 2026-11-14 22:34 UTC. I did not scan the runs since 11-06 for storage notes, so no new "0 counted differences" claim is made for 11-07 to 11-14.
- **Owner checks, not observable by the verifier:** everything inside the Sheet and the Telegram chat (03-UAT.md items 1-6, all `[pending]`, `status: testing`, 0 passed).
- **Mocked only, never produced live:** SC4 (interrupted baseline), "no alert twice", chunk and request-size limits, research A5, restore, and all of WR-01..WR-06.

## Goal Achievement

### Observable Truths (ROADMAP success criteria are the contract)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SC1: hidden Identity tab holds baseline and identity-only IDs in chunks under the cell limit; each run writes a Tally row; a run on the new storage detects no seen job as new and sends no alert twice | ✓ VERIFIED (writes and reads live; "no alert twice" and chunk limits mocked) | Code present (`compact.split_observations`, `IDENTITY_CELL_CHARS`, `pipeline.persist_observations`, `state.load_ledger`). The baseline-write and seen-set tests re-run and pass on current HEAD. Live: seed run 40924656021 wrote 991 Identity rows and 424 Tally runs; first compact run 41375348321 `alerts 0 sent`. The WR-03 Tally carry (`pending_tally`) retries a failed append: strengthens, does not alter, the delivered path (mocked). Hidden tabs and Telegram are owner checks. |
| 2 | SC2: read-only `--storage-parity` reports zero differences (seen set, state counts, Dashboard figures) between old Events rows and Identity and Tally, on every run for several consecutive days of dual writing | ✓ VERIFIED (live logs; Dashboard render owner check) | `parity.check_dual` / `check_compact` present and wired from `pipeline.storage_check` (read at `pipeline.py:225-256`). Live: bar `3 of 3 complete days` (run 41364810371), parity runs 40927423338, 41375689814, 42301084151 all `0 counted differences`. WR-02/WR-06 add `identity_shrunk` and `identity_unreadable` on top (`parity._identity_loss`, `parity.py:362-372`), extra and not live. Residual unchanged: the bar was read from one run's log line, not re-derived per day. |
| 3 | SC3 (swap and report): old rows retired by swapping the old tab to `Events_Legacy` (kept, restorable), Events well below the D-03 review point, storage report shows rows, allocated cells and load time before and after | ✓ VERIFIED (live public log; Sheet-side facts owner checks) | Live run 41373351559 and report 42300947285: Events 235,785 rows before, 30,613 now, far below 200,000; Load_S 12.0 s to 5.0 s. **Caveat unchanged:** the all-tab total rose (2,471,757 to 2,689,420 allocated cells) because `Events_Legacy` is kept by design. The Events ledger stopped growing toward its limit; the spreadsheet total did not shrink. |
| 4 | SC3 (growth drop): daily growth in cells falls by an order of magnitude (D-43 estimate 26,200 to 1,300 cells a day) | ? UNCERTAIN (transitional live figure; steady state not demonstrated) | One live measurement: 35,511 before to -2,658 after, 2 complete UTC days, both fold days, with different measures before and after (Events rows x 7 against allocated cells over every tab). Numerically below 3,551, not an honest demonstration. No storage report newer than 2026-11-06 is recorded, so the calendar re-read (today) has not happened. The offline simulation test (synthetic data) passes. Not FAILED: nothing contradicts it and STATUS makes no unearned claim. Routed to human item 5. |
| 5 | SC4: a run interrupted in the middle of a board's baseline never makes that board's old postings look new on the next run | ✓ VERIFIED (mocked only; never produced live) | Behavior-dependent. The two behavioral tests (interrupted compact baseline; seed whose Tally append fails) re-run and pass on current HEAD, so the transition is exercised, not just present. Labelled mocked in STATUS. |
| 6 | Plan must-haves: the fold only deletes durable rows, only in compact mode, never on the cutover day; cutover and restore delete nothing; entry gate recorded | ✓ VERIFIED | `state.py` / `compact.fold_plan` durability checks unchanged in intent; live: four folds each `0 kept`, cutover `nothing was deleted`. On the branch the fold is additionally gated on the same run's check (`pipeline.py:975-991`: `elif check_counted != 0` skips, `None` also skips; mocked) and writes a marker before the first delete (WR-01, mocked). D-57 records the entry gate. Debt-marker grep (`TBD|FIXME|XXX`) over `compact.py parity.py state.py pipeline.py hunter.py dashboard.py reporting.py storage_report.py pilot.py` and the workflow returned no match (re-run this session). |

**Score:** 5/6 truths verified (0 present-but-behavior-unverified). Truth 4 is UNCERTAIN, not FAILED, and is routed to human verification.

### WR-06 (previous advisory): now fixed on the branch

Verified in code and by the pinning test `test_the_recorded_identity_count_is_a_high_water_mark` (record, fall, repeated fall, None, return to the mark, growth) and the integration test of the unrepaired loss across three runs. The one-shot behaviour that the previous report flagged is gone. Mocked, not deployed.

### WR-07: gap in the goal, or advisory finding?

**Judgment: advisory, not a gap. It is, however, a real defect that should be fixed before WR-02/WR-06 are deployed.**

- *Verified in code.* The mark is the raw entry sum, duplicates included (`parity._identity_invariants`, `entries += len(found)`; stored via `compared["identity_entries"]`). `record_compact_check` raises the mark on every check, including a check that counted `identity_duplicate`. Removing the duplicate lowers the count below the mark, so every later check counts `identity_shrunk`. Nothing re-adds a removed ID, so nothing clears it except editing `last_check.identity_entries` in the Discovery `storage` key or putting a junk entry back. I found no test covering duplicate-then-remove (the reviewer's suggested test does not exist yet).
- *Why it does not fail the goal.* The goal is that Events stops growing toward its limit and that parity was proven against the old rows before the swap. Both are shown by live evidence from 68a7253, which has no Identity-loss detection at all, so no WR-0x defect can have affected them. The trigger needs an external event outside every success criterion and outside STOR-01's wording (a bad write or hand edit of a hidden, warning-protected tab, which then duplicates an ID). The failure mode fails closed: the run is degraded, the fold is held back (Events grows until repaired), and nothing is deleted, alerted twice or lost.
- *Why it still matters.* It is a defect in the new semantics, not just the already-documented "no acknowledgement step" cost: the owner who does the right thing (removes the duplicate) has no right way out. A permanent false positive holds every later fold back, which over time reverses the phase's own outcome (Events growing) until someone edits Discovery state by hand. That is the situation Phase 5 board growth would amplify. Recommendation: fix WR-07 (distinct posting IDs, or skip raising the mark on a check that counted an Identity-level difference, plus the duplicate-then-remove test) before the owner deploys WR-02 and WR-06. If the owner deploys first, the cost is the manual Discovery edit described in IN-10.
- Open INFO items: IN-01 to IN-10. IN-02 (removing `Events_Legacy` flips a compact system back to dual writing) is the one the owner should know before deciding about the 217,663 extra cells; IN-09 (no test names "fold stays held back" for `identity_shrunk`) is relevant to trusting the WR-06 claim; IN-10 (no repair tooling, mark can stick high) is the operational cost.

### Open points judged without rounding up

| Point | Judgment |
|-------|----------|
| (a) SC3 order-of-magnitude drop | Not demonstrated; one transitional reading; the calendar re-read is due today and has not happened. Not a gap: nothing missing or contradicted. |
| (b) Sheet-internal facts | Not verifiable by the agent. UAT items 1-6 pending. |
| (c) SC4 | Mocked only. VERIFIED by behavioral tests, no live claim. |
| (d) A5 | Mocked; live folds peaked at 131 ranges against a 500 cap. |
| (e) Production vs branch | The fixes are not deployed. Everything said about WR-01..WR-06 is mocked. The phase goal as delivered in production does not depend on them. |
| (f) WR-07 | Advisory, see above. Open in the disposition. |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `compact.py` | Identity codec, Tally, split, merged view, fold, cutover records, effective mode | ✓ VERIFIED | `record_compact_check` high-water mark read at `compact.py:741-757`; `last_identity_entries` present |
| `parity.py` | `check_dual`, `check_compact` | ✓ VERIFIED | `_identity_invariants`, `_identity_loss`, `check_compact` read; wired from `pipeline.storage_check` |
| `state.py` | Identity and Tally tabs, `load_ledger`, `write_identity`, `append_tally`, `swap_events`, `fold_events` | ✓ VERIFIED | Covered by the 934-test run; not re-read line by line this session beyond the pipeline callers |
| `pipeline.py` | observation write order, storage step, fold step | ✓ VERIFIED | storage check and fold gate read at `pipeline.py:225-256` and `:965-991` |
| `hunter.py` | `--storage-parity`, `--storage-report`, `--storage-cutover`, `--storage-restore` | ✓ VERIFIED | `run_storage_parity` reads `last_identity_entries()` (per 03-REVIEW.md); suite passes |
| `storage_report.py`, `reporting.py`, `dashboard.py`, `pilot.py` | merged-view reports, before/after, Storage line | ✓ VERIFIED | storage report ran live (42300947285); Dashboard render is an owner check |
| `.github/workflows/job_hunter.yml` | four boolean inputs and fixed steps | ✓ VERIFIED (IN-03 open) | `tests/test_deployment.py` passes in the 934-test run |
| `DECISIONS.md` D-57, `SPEC.md`, `STATUS.md`, `PILOT_LOG.md` | decision record, contract, live labels | ✓ VERIFIED | STATUS line 5 section labels WR-01..WR-06 "mocked, not deployed" and states the WR-06 operational cost |

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| `run_cycle` load | `state.load_ledger` | one load of Events, Identity, Tally | WIRED |
| observation write point | `split_observations` to `write_identity` to `append_tally` to `save_boards` | `persist_observations`; failed Tally row carried | WIRED |
| storage check | `parity.check_dual` / `check_compact` | `pipeline.storage_check`, returns `report.counted` (`pipeline.py:225-256`) | WIRED |
| storage check | `record_compact_check` | `identity_entries=None if failed else report.compared.get("identity_entries")` (`pipeline.py:244-249`) | WIRED (mocked) |
| storage check | fold | `check_counted != 0` skips the fold (`pipeline.py:975-991`) | WIRED (mocked) |
| owner dispatch `storage_cutover` | `hunter.run_storage_cutover` to `swap_events` | live run 41373351559 | WIRED (live) |
| `--storage-report` | `state.sheet_grid()` and cutover `before` | live run 42300947285 | WIRED (live) |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| Storage report before/after | allocated cells, `Load_S`, daily growth | sheet metadata and `Runs` tab | Yes (live report) | FLOWING |
| Dashboard merged view | `folded` counts | `Ledger.folded()` from Identity, Tally, kept Events | Yes in logs (0 differences); render owner check | FLOWING (render unseen) |
| Seen set | Identity keys plus Events `seen` keys | `load_ledger` | Yes (live parity compared 22,426 kept and 232,680 Identity entries on 11-02) | FLOWING |
| Identity entry reference (WR-02/06/07) | `last_check.identity_entries` | `report.compared["identity_entries"]`, raw entry sum | Mocked only; now a high-water mark; raw count includes duplicates (WR-07) | FLOWING (mocked; WR-07 caveat) |

### Behavioral Spot-Checks (all mocked)

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full offline suite | `.venv/bin/python -m unittest discover -s tests` | Ran 934 tests OK, exit 0 | PASS |
| WR-06 high-water mark | `discover -s tests -k test_the_recorded_identity_count_is_a_high_water_mark` | Ran 1 test OK | PASS |
| WR-07 / one-shot test | `-k test_an_id_that_only_identity_holds_and_was_removed_is_counted_identity_shrunk_on_the_next_run` | Ran 1 test OK (pins removal of an ID that only Identity holds; does not cover duplicate-then-remove) | PASS |
| SC1 writes and seen set | two named tests | Ran 1 test each, OK | PASS |
| SC4 interrupted baseline and seed | two named tests | Ran 1 test each, OK | PASS |

### Probe Execution

Step 7c: SKIPPED. No probes declared in the phase plans and no `scripts/*/tests/probe-*.sh`.

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|--------------|-------------|--------|----------|
| STOR-01 | 03-01 to 03-09 (all nine PLAN frontmatters list `requirements: [STOR-01]`, per the previous report; REQUIREMENTS.md re-read this session) | Baseline and identity-only rows stored compactly (Identity and Tally), parity proven before old rows retire, Events stays below the D-03 review point | ✓ SATISFIED in code and live operation; pending owner Sheet checks and the steady-state re-read | Truths 1-3, 5, 6; Events 30,613 rows against 200,000. REQUIREMENTS.md still shows STOR-01 unticked (line 80) and `Pending` (line 145). The orchestrator should tick STOR-01 only after the human items close. |

STOR-01 is the only ID mapped to Phase 3 in REQUIREMENTS.md (traceability line 145) and the only ID in any plan; every ID is accounted for. No orphaned requirements.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `compact.py` / `parity.py` | 753 / 111-128 | WR-07: mark counts duplicate entries; repair of `identity_duplicate` becomes permanent `identity_shrunk` | Warning (advisory, see above) | Fail-closed false positive holds the fold back until a manual Discovery edit; undeployed |
| `compact.py` | 585-600 | IN-02: removing `Events_Legacy` flips compact to dual | Info | Blocks the owner's later decision to delete the legacy tab until code changes |
| `.github/workflows/job_hunter.yml` | 170-175 | IN-03: cutover and restore can run in one dispatch | Info | Owner error path only |
| `compact.py` | 372-377 | IN-04: checksum covers three of seven columns | Info | `Events_Legacy` stays whole; no data-loss path |
| `tests/test_storage_parity.py` | 777-801, 906-937 | IN-09: no test names "fold held back" for `identity_shrunk` | Info | Claim rests on the WR-05 gate tests plus code reading |
| various | | IN-01, IN-05..IN-08, IN-10 | Info | Doc drift, dead code, read race, `first_day` dating, Tally carry quality, no repair tooling |

WR-01 to WR-06 are fixed (commits a2247a9, 58d9ec2, 024319f, 6648949, 8b02697, e83d563). No `TBD`, `FIXME` or `XXX` marker in any phase-touched source file.

### Human Verification Required

Seven items, listed in the frontmatter. Six come from 03-UAT.md (`status: testing`, all `result: [pending]`, 0 passed); the seventh is UAT item 7, whose text should be updated to name WR-01..WR-06 and to drop its now-outdated "consider fixing WR-06" sentence in favour of the WR-07 decision. 03-UAT.md is accounted for: none of its items is closed by this verification, and none has been marked passed or failed.

### Gates run

| Gate | Result | Source |
|------|--------|--------|
| Validation | 934 offline tests OK (re-validated after WR-06) | 03-VALIDATION.md; suite re-run here |
| Security | `threats_open: 0` | 03-SECURITY.md (reported by the orchestrator; not re-audited here) |
| Code review | 0 critical, 1 warning (WR-07), 10 info; WR-01..WR-06 fixed | 03-REVIEW.md, 03-REVIEW-DISPOSITION.md (read) |
| Regression | 934 tests OK (re-run here, exit 0) | this report |

### Gaps Summary

No failed truth, no missing or stubbed artifact, no broken link, no blocker anti-pattern and no debt marker. The storage design is built, deployed (68a7253), cut over and folding in production; the live logs recorded in STATUS and PILOT_LOG back parity at zero differences before the swap, a swap that deleted nothing, Events falling from 235,785 to 30,613 rows, and four clean folds. The phase stays `human_needed` for the same reasons as before, none rounded away: the order-of-magnitude growth drop (SC3) has one transitional reading and no steady-state re-read yet; the Sheet-internal facts and the Telegram chat are owner checks (UAT 1-4) and A5 is an owner acceptance (UAT 6); SC4 and "no alert twice" are mocked only. Two points are specific to this round. The review fixes WR-01..WR-06 are branch-only, so their effect is unverified live and they need the owner's deploy decision. WR-06 is now fixed; the new open warning WR-07 is an advisory defect in the undeployed Identity-loss hardening that the owner should fix before deploying it. Separately, "stops growing toward the limit" holds for the Events ledger, not for the spreadsheet total, while `Events_Legacy` is kept. STOR-01 stays unticked in REQUIREMENTS.md until the human items close.

---

_Verified: 2026-11-14T23:30:00Z_
_Verifier: Claude (gsd-verifier)_
