---
phase: 03-compact-storage
verified: 2026-11-15T06:40:00Z
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
covered_digest: "v3:sha256:bcd36bf340e8c2c7e287e3ebf3a7354695aebcebe1b6dcc70808c83c43806bbe"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: human_needed
  previous_score: 5/6
  gaps_closed: []
  gaps_remaining: []
  regressions: []
unverified_prohibitions:
  - "03-05 / 03-08 / 03-09 (judgment tier): MUST NOT push or dispatch without the owner's explicit choice. NON-AUTHORITATIVE verdict: consistent with the SUMMARYs and STATUS. `git ls-remote origin main` printed 68a7253 in this session, and the four newest GitHub Actions runs (latest created 2026-11-15 06:17 UTC, all `success`) report headSha 68a7253. That is consistent with 'nothing pushed'. The owner's replies themselves are not in any artifact the verifier can read. unverified-prohibition: human review recommended."
  - "03-05 / 03-09 (judgment tier): MUST NOT call a check live without a run id and log line; MUST NOT present a projection as a measurement or claim the order-of-magnitude drop from fewer than two days. NON-AUTHORITATIVE verdict: honoured. Every live claim in STATUS names a run id; STATUS says the steady-state order-of-magnitude drop is NOT claimed; the review-fix section of STATUS labels WR-01..WR-07 mocked and not deployed. Still flagged because the tier is judgment."
gaps: []
advisory_findings:
  - finding: "WR-08 (open in 03-REVIEW-DISPOSITION.md): IdentitySet.distinct_count() counts every non-empty posting ID that decode_entry yields, including entries that check_compact itself flags as identity_entry (unknown kind letter, non-canonical escape). A malformed entry raises the WR-06 high-water mark; the owner's repair (delete it) lowers the count, so every later check counts identity_shrunk until the Discovery storage key is edited by hand. Reproduced in this session: IdentitySet.from_rows([IdentityRow('g|a', 1, 't', 3, 'bA,xB,b%2c')]).distinct_count() returned 3 for one valid entry plus one unknown-kind entry plus one non-canonical escape."
    category: other
    reason: "Same class as WR-07, one trigger narrower (a corrupt entry rather than a duplicate), in undeployed hardening. Needs an external event (a bad write or hand edit of a hidden, warning-protected tab). Fails closed (run degraded, fold held back, Events grows until repaired; nothing deleted, alerted twice or lost). Does not touch the delivered write path, the seen-set merge, the cutover or the fold selection that the live evidence rests on, and no success criterion or STOR-01 clause requires detection of hand-made Identity damage. Not a gap in the phase goal; a defect in the new hardening to fix before it is deployed (see the judgment section)."
    evidence_status: "code read and the distinct_count behaviour reproduced in this verification; no test exercises add-malformed-then-remove (IN-12 records that the new unit test's comment claims an unparsed-entry case it does not have)"
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
  - test: "Deploy decision for the review fixes WR-01..WR-07 (UAT item 7, pending; the UAT text names WR-01..WR-06 and WR-07 and is current). The commits are on branch gsd/phase-03-compact-storage only; production runs origin/main 68a7253 without them. The owner decides whether and when to push, and whether to fix the open warning WR-08 first (a malformed Identity entry, for example an unknown kind letter, raises the mark and removing it leaves a permanent identity_shrunk, same class as the fixed WR-07). After a deploy, read the first two compact poller runs and one --storage-parity run."
    expected: "No 'storage write failed', 'storage parity:' or 'storage fold skipped' note; the first compact check records the distinct Identity ID count (shrink detection starts from the second check); the next fold still runs. Until then every WR-01..WR-07 behaviour is mocked only."
    why_human: "Pushing or dispatching needs the owner's explicit consent (AGENTS rule 5, prohibitions above). 03-REVIEW-FIX.md marks the fixes 'requires human verification'. The WR-08 fix-first-or-accept choice is the owner's."
---

# Phase 3: Compact storage Verification Report

**Phase Goal:** The Events ledger stops growing toward its limit: baseline and identity-only postings live in compact Identity and Tally tabs with parity proven against the old rows, so board growth and new adapters can be admitted safely.
**Verified:** 2026-11-15T06:40:00Z
**Status:** human_needed
**Re-verification:** Yes. The report of 2026-11-14 23:30 went stale because review fix WR-07 (9fd3383) changed `compact.py`, `parity.py`, `tests/test_storage_parity.py`, SPEC, D-57 and STATUS. The previous report had `gaps: []`, so nothing was carried forward as failed. I re-checked what WR-07 touched against the current tree and the remaining truths against the current tree, not from the old report.

## What changed since the previous report

- WR-07 (9fd3383) is in the tree. I read the diff and the surrounding code: `IdentitySet.distinct_count()` (`compact.py:217-221`) returns the number of distinct `(stem, posting ID)` pairs from `_kinds`, which `_reindex` builds with `setdefault`, so a posting ID written twice in a stem, in one chunk or across chunks, counts once. `parity._identity_invariants` now returns `ident.distinct_count()` (it feeds `compared["identity_entries"]`), `parity._identity_loss` compares `ledger.identity.distinct_count()` against `entries_before`, and `record_compact_check` keeps `max(previous or 0, identity_entries)` (`compact.py:753`). The mark, the stored figure and the comparison now all use one measure. The previous advisory WR-07 is therefore **closed on the branch for the duplicate case (mocked, not deployed)**.
- A fresh incremental review (`03-REVIEW.md`: 0 critical, 1 warning WR-08, 12 info) and `03-REVIEW-DISPOSITION.md` (WR-01..WR-07 fixed; WR-08 and IN-01..IN-12 open; 13 open of 20) were read.
- Re-validation (`03-VALIDATION.md`, status validated, `nyquist_compliant: true`) and the security re-check (`03-SECURITY.md`, status verified, `threats_open: 0`) were read. I did not re-audit threats; I note the SECURITY ledger carries that result.
- Production is unchanged: `git ls-remote origin main` printed `68a7253c938c...`; `gh run list` shows the four newest runs (created 2026-11-15 05:51, 06:00, 06:00 and 06:17 UTC) `success`, all with headSha 68a7253. `git diff origin/main HEAD -- . ':!.planning'` touches 12 files (753 insertions, 70 deletions). So **the offline tests run the fixed branch; the live evidence comes from the unfixed 68a7253.**

## Mocked versus live (AGENTS rule 5)

- **Mocked / offline, run by the verifier in this session on branch HEAD (e7c99eb):** `.venv/bin/python -m unittest discover -s tests` printed `Ran 937 tests in 15.727s ... OK` (exit 0, from the saved output). Two tests were re-run by name and each printed `Ran 1 test ... OK`: `test_the_recorded_identity_count_is_a_high_water_mark` and `test_an_id_that_only_identity_holds_and_was_removed_is_counted_identity_shrunk_on_the_next_run`. All use `tests/fake_sheets.py`, the CSV store or hand-built ledgers; nothing touched Sheets, Groq or Telegram. The WR-07 tests exist at `tests/test_storage_parity.py:777` (distinct count; duplicate, same ID in two stems, bare kind letter), `:789` (duplicate removal is not a shrink, removing a distinct ID is) and `:960` (integration: duplicate counted `identity_duplicate`, mark does not rise, removal counts 0). I did not run a mutation check against them; the review states the integration test fails against the raw sum.
- **Live, read today by the verifier from the public Actions log (read-only):** run 43683446438 (created 2026-11-15 06:00 UTC, headSha 68a7253), `hunt` job, 06:02:32 UTC: `Storage: mode=compact, 0 counted and 0 declared differences, 21092 kept job keys and 882 Tally runs compared, check took 2.3 s`. This matches the line the orchestrator read via the Sheet. It is produced by 68a7253, **without WR-01..WR-07**, so it proves production compact mode is clean today and says nothing about the fixes.
- **Live, carried from the 2026-11-06 report and STATUS (run ids recorded there; not re-read this session):** cutover run 41373351559 (`25,531 rows now in Events, 235,785 rows kept in Events_Legacy ... nothing was deleted`); bar met before the cutover, run 41364810371 (3 of 3 complete days, 0 counted differences); first compact poller run 41375348321 and parity run 41375689814 (0 counted differences); folds 41549615660, 41743488450, 41938020379, 42133570806 (2,866 / 5,153 / 4,512 / 4,221 rows, 94 / 131 / 88 / 106 ranges, 16,752 rows, each `0 kept`); storage report 42300947285 (Load_S 12.0 s to 5.0 s; daily growth 35,511 to -2,658 cells over 2 complete UTC days; allocated cells over every tab 2,471,757 to 2,689,420). The verifier did not dispatch any workflow.
- **Owner checks, not observable by the verifier:** everything inside the Sheet and the Telegram chat (03-UAT.md items 1-6, all `[pending]`, `status: testing`, 0 passed of 7).
- **Mocked only, never produced live:** SC4 (interrupted baseline), "no alert twice", chunk and request-size limits, research A5, restore, and all of WR-01..WR-07.

## Goal Achievement

### Observable Truths (ROADMAP success criteria are the contract)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SC1: hidden Identity tab holds baseline and identity-only IDs in chunks under the cell limit; each run writes a Tally row; a run on the new storage detects no seen job as new and sends no alert twice | ✓ VERIFIED (writes and reads live; "no alert twice" and chunk limits mocked) | Code present (`compact.IdentitySet`, `IDENTITY_CELL_CHARS`, `plan_additions`, `pipeline.persist_observations`, `state.load_ledger`), covered by the 937-test pass. Live: seed run 40924656021 wrote 991 Identity rows and 424 Tally runs; first compact run 41375348321 `alerts 0 sent`; today's run 43683446438 compares 21,092 kept job keys and 882 Tally runs with 0 differences. WR-07 changed only the count function, not `plan_additions` or `keys()`; the seen set is unchanged. Hidden tabs and Telegram are owner checks. |
| 2 | SC2: read-only `--storage-parity` reports zero differences (seen set, state counts, Dashboard figures) between old Events rows and Identity and Tally, on every run for several consecutive days of dual writing | ✓ VERIFIED (live logs; Dashboard render owner check) | `parity.check_dual` / `check_compact` present and wired from `pipeline.storage_check` (`pipeline.py:225-258`). Live: bar `3 of 3 complete days` (run 41364810371), parity runs 40927423338, 41375689814, 42301084151 all `0 counted differences`, plus today's compact check. WR-02/06/07/08 concern `identity_shrunk` and `identity_entry` on top of this, extra and not live. Residual unchanged: the bar was read from one run's log line, not re-derived per day. |
| 3 | SC3 (swap and report): old rows retired by swapping the old tab to `Events_Legacy` (kept, restorable), Events well below the D-03 review point, storage report shows rows, allocated cells and load time before and after | ✓ VERIFIED (live public log; Sheet-side facts owner checks) | Live run 41373351559 and report 42300947285: Events 235,785 rows before, 30,613 now, far below 200,000; Load_S 12.0 s to 5.0 s. **Caveat unchanged:** the all-tab total rose (2,471,757 to 2,689,420 allocated cells) because `Events_Legacy` is kept by design. The Events ledger stopped growing toward its limit; the spreadsheet total did not shrink. |
| 4 | SC3 (growth drop): daily growth in cells falls by an order of magnitude (D-43 estimate 26,200 to 1,300 cells a day) | ? UNCERTAIN (transitional live figure; steady state not demonstrated) | One live measurement: 35,511 before to -2,658 after, 2 complete UTC days, both fold days, with different measures before and after (Events rows x 7 against allocated cells over every tab). Numerically below 3,551, not an honest demonstration. No storage report newer than 2026-11-06 is recorded. The offline simulation test (synthetic data) passes. Not FAILED: nothing contradicts it and STATUS makes no unearned claim. Routed to human item 5. |
| 5 | SC4: a run interrupted in the middle of a board's baseline never makes that board's old postings look new on the next run | ✓ VERIFIED (mocked only; never produced live) | Behavior-dependent. The behavioral tests (interrupted compact baseline; seed whose Tally append fails) were re-run in the 937-test pass. The previous report re-ran them by name; this session ran the whole suite once and did not re-name them, and WR-07 does not touch the write path (the diff is `distinct_count`, `_identity_invariants`, `_identity_loss` and docs only). Labelled mocked in STATUS. |
| 6 | Plan must-haves: the fold only deletes durable rows, only in compact mode, never on the cutover day; cutover and restore delete nothing; entry gate recorded | ✓ VERIFIED | `fold_due` (`compact.py` after `record_compact_check`) requires stored mode compact and a UTC day after the cutover day; live: four folds each `0 kept`, cutover `nothing was deleted`. On the branch the fold is additionally gated on the same run's check (`pipeline.py:982-991`: `elif check_counted != 0` skips, `None` also skips; mocked) and writes a marker before the first delete (WR-01, mocked). D-57 records the entry gate. Debt-marker grep (`TBD|FIXME|XXX`) over `compact.py parity.py state.py pipeline.py hunter.py dashboard.py reporting.py storage_report.py pilot.py` and the workflow returned no match (re-run this session, exit 1 = no match). |

**Score:** 5/6 truths verified (0 present-but-behavior-unverified). Truth 4 is UNCERTAIN, not FAILED, and is routed to human verification.

### WR-07: now fixed on the branch (mocked)

Verified in code (above) and by the three WR-07 tests. Spot trace: a duplicate adds nothing to `_kinds`, so the mark does not rise; removing it leaves the distinct count at the mark, so no `identity_shrunk`; removing a distinct ID still falls below the mark, so the genuine loss is still counted. The migration point in the review holds: `last_check.identity_entries` was added on this branch, production never wrote the raw figure, so no stored raw value can disagree with the distinct count. Mocked, not deployed.

### WR-08: gap in the goal, or advisory finding?

**Judgment: advisory, not a gap. It is a real defect in the new hardening and should be fixed before WR-02, WR-06 and WR-07 are deployed.**

- *Verified in code and reproduced.* `distinct_count` counts every non-empty posting ID `decode_entry` yields, whatever its kind letter or escaping (`compact.py:221`: `for pid in kinds if pid`). `check_compact` counts entries with an unknown kind letter, an empty ID or a non-canonical escape as `identity_entry` (`parity.py:333-338`). I ran `IdentitySet.from_rows([IdentityRow("g|a", 1, "t", 3, "bA,xB,b%2c")]).distinct_count()` and it returned 3, so the malformed entries are in the figure. The mark then follows from `record_compact_check` (`max`): a check that counted `identity_entry` raises the mark; deleting the malformed entry, the repair for that difference, lowers the count below the mark; every later check counts `identity_shrunk`. No test covers it (IN-12: the WR-07 unit test comment promises an "unparsed entry" case that the fixture does not contain). The doc text (`distinct_count` docstring: "an entry with no posting ID counts not at all") describes a stricter rule than the code applies for unknown kinds and bad escapes.
- *Why it does not fail the goal.* The goal is that Events stops growing toward its limit and that parity was proven against the old rows before the swap. Both rest on live evidence from 68a7253, which has no Identity-loss detection at all, so WR-08 cannot have affected them; today's production check is clean (0 counted differences) on that code. The trigger needs an external event outside every success criterion and outside STOR-01's wording: a corrupt entry in a hidden, warning-protected tab, written by a bad write or a hand edit. The failure mode fails closed: run degraded (NEEDS ATTENTION), fold held back, Events grows until repaired; nothing is deleted, alerted twice or lost. The code writes entries only through `encode_entry`, so the normal write path cannot produce an unknown kind letter or a non-canonical escape.
- *Why it still matters.* Same shape as WR-07: the owner who does the right thing (removes the flagged entry) has no right way out, and the false positive holds every later fold back until the Discovery `storage` key is edited by hand (IN-10). Because the mark only rises, IN-10 also says a transient over-read sticks it high. Recommendation: count only entries that `check_compact` would accept (skip them in `_reindex`, or add a `valid_distinct_count()` used only by the mark and `_identity_loss`) and add the add-malformed-then-remove test, before the owner deploys. It is a narrow, mocked-testable fix, but it is the owner's call; AGENTS rule 7 does not forbid it because it is a defect in delivered hardening, not a new feature. If the owner deploys first, the cost is the manual Discovery edit in IN-10.
- *Why advisory and not a warning-level gap.* I weighed whether "permanent false-positive that blocks the fold" reverses the phase outcome. It does only after an external corruption event, and it fails visibly (NEEDS ATTENTION on every run), not silently. A gap would require a success criterion or a STOR-01 clause that detection of Identity damage serves; none does. I have not rounded this down: it stays recorded under `advisory_findings` and in the deploy decision (human item 7), and I would treat it as a blocker for the deploy of the hardening, not for the phase goal.

### Open points judged without rounding up

| Point | Judgment |
|-------|----------|
| (a) SC3 order-of-magnitude drop | Not demonstrated; one transitional reading; the calendar re-read (about 2026-11-14) is now past and has not happened. Not a gap: nothing missing or contradicted. |
| (b) Sheet-internal facts | Not verifiable by the agent. UAT items 1-6 pending. |
| (c) SC4 | Mocked only. VERIFIED by behavioral tests, no live claim. |
| (d) A5 | Mocked; live folds peaked at 131 ranges against a 500 cap. |
| (e) Production vs branch | The fixes WR-01..WR-07 are not deployed. Everything said about them is mocked. The phase goal as delivered in production does not depend on them. |
| (f) WR-08 | Advisory, see above. Open in the disposition. |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `compact.py` | Identity codec, Tally, split, merged view, fold, cutover records, effective mode | ✓ VERIFIED | `IdentitySet.distinct_count` at `compact.py:217`; `record_compact_check` high-water mark at `:753` |
| `parity.py` | `check_dual`, `check_compact` | ✓ VERIFIED | `_identity_invariants`, `_identity_loss` (`parity.py:361-372`), `check_compact` read; wired from `pipeline.storage_check` |
| `state.py` | Identity and Tally tabs, `load_ledger`, `write_identity`, `append_tally`, `swap_events`, `fold_events` | ✓ VERIFIED | Covered by the 937-test run; unchanged by WR-07; not re-read line by line this session |
| `pipeline.py` | observation write order, storage step, fold step | ✓ VERIFIED | storage check and fold gate read at `pipeline.py:225-258` and `:975-991` |
| `hunter.py` | `--storage-parity`, `--storage-report`, `--storage-cutover`, `--storage-restore` | ✓ VERIFIED | Suite passes; unchanged by WR-07 |
| `storage_report.py`, `reporting.py`, `dashboard.py`, `pilot.py` | merged-view reports, before/after, Storage line | ✓ VERIFIED | storage report ran live (42300947285); Dashboard render is an owner check |
| `.github/workflows/job_hunter.yml` | four boolean inputs and fixed steps | ✓ VERIFIED (IN-03 open) | `tests/test_deployment.py` passes in the 937-test run |
| `DECISIONS.md` D-57, `SPEC.md`, `STATUS.md`, `PILOT_LOG.md` | decision record, contract, live labels | ✓ VERIFIED | STATUS section "Phase 3 code-review fixes (WR-01..WR-07)" labels each fix mocked, not deployed, and states the WR-06 operational cost and the WR-07 no-migration reasoning |

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| `run_cycle` load | `state.load_ledger` | one load of Events, Identity, Tally | WIRED |
| observation write point | `split_observations` to `write_identity` to `append_tally` to `save_boards` | `persist_observations`; failed Tally row carried | WIRED |
| storage check | `parity.check_dual` / `check_compact` | `pipeline.storage_check`, returns `report.counted` (`pipeline.py:225-258`) | WIRED |
| `check_compact` | `IdentitySet.distinct_count` | `_identity_invariants` and `_identity_loss` (`parity.py:128`, `:366`) | WIRED (mocked) |
| storage check | `record_compact_check` | `identity_entries=None if failed else report.compared.get("identity_entries")` | WIRED (mocked) |
| storage check | fold | `check_counted != 0` skips the fold (`pipeline.py:982-991`) | WIRED (mocked) |
| owner dispatch `storage_cutover` | `hunter.run_storage_cutover` to `swap_events` | live run 41373351559 | WIRED (live) |
| `--storage-report` | `state.sheet_grid()` and cutover `before` | live run 42300947285 | WIRED (live) |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| Storage report before/after | allocated cells, `Load_S`, daily growth | sheet metadata and `Runs` tab | Yes (live report) | FLOWING |
| Dashboard merged view | `folded` counts | `Ledger.folded()` from Identity, Tally, kept Events | Yes in logs (0 differences, 21,092 keys and 882 Tally runs today); render owner check | FLOWING (render unseen) |
| Seen set | Identity keys plus Events `seen` keys | `load_ledger` | Yes (live parity compared 22,426 kept and 232,680 Identity entries on 11-02; 21,092 kept keys today) | FLOWING |
| Identity mark (WR-02/06/07/08) | `last_check.identity_entries` | `IdentitySet.distinct_count()` via `compared["identity_entries"]` | Mocked only; distinct pairs, high-water mark; counts malformed-but-non-empty IDs (WR-08) | FLOWING (mocked; WR-08 caveat) |

### Behavioral Spot-Checks (all mocked unless stated)

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full offline suite | `.venv/bin/python -m unittest discover -s tests` | Ran 937 tests OK, exit 0 | PASS |
| WR-06 high-water mark | `discover -s tests -k test_the_recorded_identity_count_is_a_high_water_mark` | Ran 1 test OK | PASS |
| Removal of an Identity-only ID is counted | `-k test_an_id_that_only_identity_holds_and_was_removed_is_counted_identity_shrunk_on_the_next_run` | Ran 1 test OK | PASS |
| WR-08 reproduction | `IdentitySet.from_rows([IdentityRow("g\|a",1,"t",3,"bA,xB,b%2c")]).distinct_count()` | 3 (the malformed entries count) | CONFIRMS the advisory |
| Production check today (live, read-only log) | `gh run view 43683446438 --log` grep `Storage:` | `0 counted and 0 declared differences, 21092 kept job keys and 882 Tally runs compared` | PASS (live, 68a7253) |

### Probe Execution

Step 7c: SKIPPED. No probes declared in the phase plans and no `scripts/*/tests/probe-*.sh`.

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|--------------|-------------|--------|----------|
| STOR-01 | 03-01 to 03-09 (all nine PLAN frontmatters list `requirements: [STOR-01]`, confirmed by grep this session) | Baseline and identity-only rows stored compactly (Identity and Tally), parity proven before old rows retire, Events stays below the D-03 review point | ✓ SATISFIED in code and live operation; pending owner Sheet checks and the steady-state re-read | Truths 1-3, 5, 6; Events 30,613 rows against 200,000; today's check 0 differences. REQUIREMENTS.md still shows STOR-01 unticked (line 80) and `Pending` (line 145). The orchestrator should tick STOR-01 only after the human items close. |

STOR-01 is the only ID mapped to Phase 3 in REQUIREMENTS.md (traceability line 145) and the only ID in any plan; every ID is accounted for. No orphaned requirements.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `compact.py` / `parity.py` | 221 / 333-338 | WR-08: malformed non-empty Identity entries raise the mark; removing one is a permanent `identity_shrunk` | Warning (advisory, see above) | Fail-closed false positive holds the fold back until a manual Discovery edit; undeployed |
| `compact.py` | 585-600 | IN-02: removing `Events_Legacy` flips compact to dual | Info | Blocks the owner's later decision to delete the legacy tab until code changes |
| `.github/workflows/job_hunter.yml` | 170-175 | IN-03: cutover and restore can run in one dispatch | Info | Owner error path only |
| `compact.py` | 372-377 | IN-04: checksum covers three of seven columns | Info | `Events_Legacy` stays whole; no data-loss path |
| `tests/test_storage_parity.py` | 777-791, 906-958 | IN-09 / IN-12: no test names "fold held back" for `identity_shrunk`; the WR-07 unit test comment claims an unparsed-entry case it lacks | Info | Claims rest on the WR-05 gate tests plus code reading |
| various | | IN-01, IN-05..IN-08, IN-10, IN-11 | Info | Doc drift, dead code, read race, `first_day` dating, Tally carry quality, no repair tooling, figure still named "entries" |

WR-01 to WR-07 are fixed (commits a2247a9, 58d9ec2, 024319f, 6648949, 8b02697, e83d563, 9fd3383). No `TBD`, `FIXME` or `XXX` marker in any phase-touched source file.

### Human Verification Required

Seven items, listed in the frontmatter. Six come from 03-UAT.md (`status: testing`, all `result: [pending]`, 0 passed); the seventh is UAT item 7, whose text now names WR-01..WR-06 and WR-07 and is current; this report adds the WR-08 fix-first-or-accept decision to it. 03-UAT.md is accounted for: none of its items is closed by this verification, and none has been marked passed or failed. Item 5's calendar date has passed without a re-read.

### Gates run

| Gate | Result | Source |
|------|--------|--------|
| Validation | 937 offline tests OK (re-validated after WR-07); status validated | 03-VALIDATION.md; suite re-run here |
| Security | `threats_open: 0` | 03-SECURITY.md (read; not re-audited here) |
| Code review | 0 critical, 1 warning (WR-08), 12 info; WR-01..WR-07 fixed | 03-REVIEW.md, 03-REVIEW-DISPOSITION.md (read) |
| Regression | 937 tests OK (re-run here, exit 0) | this report |

### Gaps Summary

No failed truth, no missing or stubbed artifact, no broken link, no blocker anti-pattern and no debt marker. The storage design is built, deployed (68a7253), cut over and folding in production; the live logs recorded in STATUS and PILOT_LOG back parity at zero differences before the swap, a swap that deleted nothing, Events falling from 235,785 to 30,613 rows and four clean folds, and today's production compact check (run 43683446438) again reads 0 counted and 0 declared differences. The phase stays `human_needed` for the same reasons as before, none rounded away: the order-of-magnitude growth drop (SC3) has one transitional reading and no steady-state re-read yet; the Sheet-internal facts and the Telegram chat are owner checks (UAT 1-4) and A5 is an owner acceptance (UAT 6); SC4 and "no alert twice" are mocked only. Two points are specific to this round. The review fixes WR-01..WR-07 are branch-only, so their effect is unverified live and they need the owner's deploy decision. WR-07 is now fixed for duplicates; the open warning WR-08 (same failure for malformed entries) is an advisory defect in the undeployed Identity-loss hardening that the owner should fix or consciously accept before deploying it. Separately, "stops growing toward the limit" holds for the Events ledger, not for the spreadsheet total, while `Events_Legacy` is kept. STOR-01 stays unticked in REQUIREMENTS.md until the human items close.

---

_Verified: 2026-11-15T06:40:00Z_
_Verifier: Claude (gsd-verifier)_
