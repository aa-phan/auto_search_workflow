---
phase: 03-compact-storage
verified: 2026-11-15T20:16:00Z
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
covered_digest: "v3:sha256:4bf801fbbcae25da89e50d6e4a7f0000fb36860dca6869fb1efce558a65faf4c"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: human_needed
  previous_score: 5/6
  gaps_closed: []
  gaps_remaining: []
  regressions: []
unverified_prohibitions:
  - "03-05 / 03-08 / 03-09 (judgment tier): MUST NOT push or dispatch without the owner's explicit choice. NON-AUTHORITATIVE verdict: consistent with the SUMMARYs and STATUS. `git ls-remote origin main` printed 68a7253 in this session and the four newest GitHub Actions runs (latest created 2026-11-15 20:00 UTC, all `success`) report headSha 68a7253. That is consistent with 'nothing pushed'. The owner's replies themselves are not in any artifact the verifier can read. unverified-prohibition: human review recommended."
  - "03-05 / 03-09 (judgment tier): MUST NOT call a check live without a run id and log line; MUST NOT present a projection as a measurement or claim the order-of-magnitude drop from fewer than two days. NON-AUTHORITATIVE verdict: honoured. Every live claim in STATUS names a run id; STATUS says the steady-state order-of-magnitude drop is NOT claimed; the review-fix section of STATUS labels WR-01..WR-08 mocked and not deployed. Still flagged because the tier is judgment."
gaps: []
advisory_findings:
  - finding: "WR-09 (open in 03-REVIEW-DISPOSITION.md): IdentitySet.distinct_count() counts only posting IDs with a well-formed entry (`_valid`), but IdentitySet.keys(), the dedupe / seen set, still holds every posting ID that any entry carries, malformed or not (`_kinds`). Reproduced in this session: IdentitySet.from_rows([IdentityRow('g|a',1,'t',3,'bA,xB,b%2c')]) gives distinct_count() 1 and keys() {g|a|A, g|a|B, g|a|%2c}; a set holding only 'xB' gives distinct_count() 0, len() 1, keys() {g|a|B}. Deleting a malformed entry whose ID has no well-formed twin therefore drops a held ID from the dedupe with no identity_shrunk (the count is 0 before and after). SPEC.md:111, DECISIONS.md D-57 and the distinct_count docstring (compact.py:231) call the count 'the identity the dedupe uses / can use', which the code contradicts."
    category: other
    reason: "A real defect in undeployed hardening plus a doc/code contradiction, not a gap in the phase goal. Production (68a7253) has no shrink detection and no distinct_count at all, so the branch is strictly stronger than production on this axis and WR-09 cannot have affected any live evidence. The trigger needs an external event (a malformed entry in a hidden, warning-protected tab) AND that the ID has no well-formed twin AND that the entry predates the first recorded mark: the write path only emits well-formed entries (`encode_entry`), so a code-written ID always has a well-formed entry that the mark counted, and its later damage or deletion IS caught as identity_shrunk because the mark is a high-water mark. Today's live check reads 0 counted differences on 68a7253, which includes `identity_entry`, so no malformed Identity entry exists in production now. The residual harm is narrow: an ID held only by an externally introduced malformed entry leaves the dedupe when the owner deletes that entry, which restores the state before the damage. The doc claim is nonetheless false today and should be corrected (or the count made to match) before the owner deploys, because AGENTS rules 2 and 3 are the reason the dedupe matters."
    evidence_status: "code read and reproduced in this verification (not a deployed or live finding); no test covers delete-a-malformed-entry-with-no-well-formed-twin (the WR-08 integration test restores the original cell, whose added IDs were never held before)"
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
  - test: "Deploy decision for the review fixes WR-01..WR-08 and the open warning WR-09 (UAT item 7, pending; the UAT text currently names WR-01..WR-07 and WR-08 and should also name WR-09). The commits are on branch gsd/phase-03-compact-storage only; production runs origin/main 68a7253 without any of them. The owner decides whether and when to push, and whether to resolve WR-09 first: either make the held-ID figure match the dedupe (a second high-water mark over all held IDs, `len(identity)`), or correct the docs and docstring to say that the count covers well-formed IDs only and that deleting a malformed entry with no well-formed twin drops a held ID undetected (repair = correct the entry to canonical form, do not delete it). After a deploy, read the first two compact poller runs and one --storage-parity run."
    expected: "No 'storage write failed', 'storage parity:' or 'storage fold skipped' note; the first compact check records the distinct well-formed Identity ID count (shrink detection starts from the second check); the next fold still runs. Until then every WR-01..WR-08 behaviour is mocked only."
    why_human: "Pushing or dispatching needs the owner's explicit consent (AGENTS rule 5, prohibitions above). 03-REVIEW-FIX.md marks the fixes 'requires human verification'. The WR-09 fix-first-or-accept choice is the owner's."
---

# Phase 3: Compact storage Verification Report

**Phase Goal:** The Events ledger stops growing toward its limit: baseline and identity-only postings live in compact Identity and Tally tabs with parity proven against the old rows, so board growth and new adapters can be admitted safely.
**Verified:** 2026-11-15T20:16:00Z
**Status:** human_needed
**Re-verification:** Yes. The report of 2026-11-15 06:40 went stale because review fix WR-08 (c845065: shared predicate `compact.entry_well_formed` used by `parity.check_compact`, `IdentitySet._reindex` and `IdentitySet.distinct_count`) changed `compact.py`, `parity.py`, `tests/test_storage_parity.py`, SPEC, D-57 and STATUS. The previous report had `gaps: []`, so nothing was carried forward as failed. I re-checked what WR-08 touched against the current tree and the other truths against the current tree, not from the old report.

## What changed since the previous report

- **WR-08 (c845065) is in the tree and fixed for the case it named.** `entry_well_formed` (`compact.py:70-74`) is `kind in DISPOSITION_OF and bool(pid) and encode_entry(kind, pid) == entry`, the test `check_compact` ran inline before. `IdentitySet._reindex` (`compact.py:184-196`) builds `_kinds` and `_valid` together; `copy()` copies `_valid`; `apply` and `from_rows` go through `_reindex`. `distinct_count()` returns `sum(len(valid) ...)` (`compact.py:230-235`). `parity._identity_invariants` returns it into `compared["identity_entries"]` (`parity.py:127`), `_identity_loss` compares it with the mark (`parity.py:365-367`), and `record_compact_check` keeps `max(previous or 0, identity_entries)`. The mark, the stored figure and the comparison use one figure again. The WR-08 unit test (`tests/test_storage_parity.py:789`) and integration test (`:990`) pass when run by name (`Ran 2 tests ... OK`). Mocked, not deployed.
- **A new warning, WR-09, was found by the review and is open.** The fix made the count blind to a class of IDs that the dedupe still holds. I reproduced it (see below).
- `03-REVIEW.md` is 0 critical, 1 warning (WR-09), 11 info; `03-REVIEW-DISPOSITION.md` records WR-01..WR-08 and IN-12 fixed, WR-09 and IN-01..IN-11 open (12 open of 21). `03-VALIDATION.md` (status validated, `nyquist_compliant: true`) and `03-SECURITY.md` (status verified, `threats_open: 0`) were read, not re-audited here.
- Production is unchanged. `git ls-remote origin main` printed `68a7253c938c...`. `gh run list` shows the four newest runs (created 2026-11-15 19:34, 19:51, 20:00 and 20:00 UTC) `success`, all with headSha 68a7253. `git diff --stat 68a7253 HEAD -- . ':!.planning'` touches 12 files (802 insertions, 72 deletions). **The offline tests run the fixed branch; the live evidence comes from the unfixed 68a7253.** At 68a7253, `parity.py` has `identity_entry` but no `identity_shrunk`, and `compact.py` has no `entry_well_formed`, `distinct_count` or `identity_entries`.

## Mocked versus live (AGENTS rule 5)

- **Mocked / offline, run by the verifier in this session on branch HEAD (eb2d1a1):** `.venv/bin/python -m unittest discover -s tests` printed `Ran 939 tests in 20.228s ... OK` (exit 0, from the saved output). `python -m unittest tests.test_storage_parity -k test_a_malformed` printed `Ran 2 tests ... OK`. The WR-09 reproduction is an in-process call on hand-built rows. Nothing touched Sheets, Groq or Telegram. I did not run a mutation check against the WR-08 tests.
- **Live, read today by the verifier from the public Actions log (read-only):** run 43755525979 (created 2026-11-15 20:00 UTC, headSha 68a7253), `hunt` job, 20:02:24 UTC: `Storage: mode=compact, 0 counted and 0 declared differences, 21735 kept job keys and 898 Tally runs compared, check took 1.6 s`. It is produced by 68a7253, **without WR-01..WR-08**, so it proves production compact mode is clean today and says nothing about the fixes.
- **Live, carried from the 2026-11-06 report and STATUS (run ids recorded there; not re-read this session):** cutover run 41373351559 (`25,531 rows now in Events, 235,785 rows kept in Events_Legacy ... nothing was deleted`); bar met before the cutover, run 41364810371 (3 of 3 complete days, 0 counted differences); first compact poller run 41375348321 and parity run 41375689814 (0 counted differences); folds 41549615660, 41743488450, 41938020379, 42133570806 (2,866 / 5,153 / 4,512 / 4,221 rows, 94 / 131 / 88 / 106 ranges, 16,752 rows, each `0 kept`); storage report 42300947285 (Load_S 12.0 s to 5.0 s; daily growth 35,511 to -2,658 cells over 2 complete UTC days; allocated cells over every tab 2,471,757 to 2,689,420). The verifier dispatched no workflow.
- **Owner checks, not observable by the verifier:** everything inside the Sheet and the Telegram chat (03-UAT.md items 1-6, all `[pending]`, `status: testing`, 0 passed of 7).
- **Mocked only, never produced live:** SC4 (interrupted baseline), "no alert twice", chunk and request-size limits, research A5, restore, and all of WR-01..WR-08.

## Goal Achievement

### Observable Truths (ROADMAP success criteria are the contract)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SC1: hidden Identity tab holds baseline and identity-only IDs in chunks under the cell limit; each run writes a Tally row; a run on the new storage detects no seen job as new and sends no alert twice | ✓ VERIFIED (writes and reads live; "no alert twice" and chunk limits mocked) | Code present (`compact.IdentitySet`, `IDENTITY_CELL_CHARS`, `plan_additions`, `pipeline.persist_observations`, `state.load_ledger`), covered by the 939-test pass. Live: seed run 40924656021 wrote 991 Identity rows and 424 Tally runs; first compact run 41375348321 `alerts 0 sent`; today's run 43755525979 compares 21,735 kept job keys and 898 Tally runs with 0 differences. WR-08 changed only the count (`_valid`, `distinct_count`); `keys()` and `plan_additions` still read `_kinds`, so the seen set is unchanged. Hidden tabs and Telegram are owner checks. |
| 2 | SC2: read-only `--storage-parity` reports zero differences (seen set, state counts, Dashboard figures) between old Events rows and Identity and Tally, on every run for several consecutive days of dual writing | ✓ VERIFIED (live logs; Dashboard render owner check) | `parity.check_dual` / `check_compact` present and wired from `pipeline.storage_check`. Live: bar `3 of 3 complete days` (run 41364810371), parity runs 40927423338, 41375689814, 42301084151 all `0 counted differences`, plus today's compact check. WR-02/06/07/08/09 concern `identity_shrunk` and `identity_entry` on top of this: extra and not live. Residual unchanged: the bar was read from one run's log line, not re-derived per day. |
| 3 | SC3 (swap and report): old rows retired by swapping the old tab to `Events_Legacy` (kept, restorable), Events well below the D-03 review point, storage report shows rows, allocated cells and load time before and after | ✓ VERIFIED (live public log; Sheet-side facts owner checks) | Live run 41373351559 and report 42300947285: Events 235,785 rows before, 30,613 now, far below 200,000; Load_S 12.0 s to 5.0 s. **Caveat unchanged:** the all-tab total rose (2,471,757 to 2,689,420 allocated cells) because `Events_Legacy` is kept by design. The Events ledger stopped growing toward its limit; the spreadsheet total did not shrink. |
| 4 | SC3 (growth drop): daily growth in cells falls by an order of magnitude (D-43 estimate 26,200 to 1,300 cells a day) | ? UNCERTAIN (transitional live figure; steady state not demonstrated) | One live measurement: 35,511 before to -2,658 after, 2 complete UTC days, both fold days, with different measures before and after (Events rows x 7 against allocated cells over every tab). Numerically below 3,551, not an honest demonstration. No storage report newer than 2026-11-06 is recorded. The offline simulation test (synthetic data) passes. Not FAILED: nothing contradicts it and STATUS makes no unearned claim. Routed to human item 5. |
| 5 | SC4: a run interrupted in the middle of a board's baseline never makes that board's old postings look new on the next run | ✓ VERIFIED (mocked only; never produced live) | Behavior-dependent. The behavioral tests (interrupted compact baseline; seed whose Tally append fails) ran in the 939-test pass; I did not re-run them by name this session. WR-08 does not touch the write path or `plan_additions` (diff: `compact.py` predicate and `_valid`, `parity.py`, one test file, docs). Labelled mocked in STATUS. |
| 6 | Plan must-haves: the fold only deletes durable rows, only in compact mode, never on the cutover day; cutover and restore delete nothing; entry gate recorded | ✓ VERIFIED | `fold_due` (`compact.py:782`) requires stored mode compact and a UTC day after the cutover day; live: four folds each `0 kept`, cutover `nothing was deleted`. On the branch the fold is additionally gated on the same run's check (WR-05) and writes a marker before the first delete (WR-01), both mocked. Debt-marker grep (`TBD\|FIXME\|XXX`) over `compact.py parity.py state.py pipeline.py hunter.py dashboard.py reporting.py storage_report.py pilot.py` and the workflow returned no match (re-run this session, exit 1 = no match). |

**Score:** 5/6 truths verified (0 present-but-behavior-unverified). Truth 4 is UNCERTAIN, not FAILED, and is routed to human verification.

### WR-08: now fixed on the branch (mocked)

Verified in code and by the two WR-08 tests. A malformed entry no longer raises the mark, and removing one that has no effect on the figure is not a shrink. The review's mixed-entry traces (`bA,xB,b%2c` counts 1; `xB,bB` counts 1; `bA,xB,b%2c,b%2C` counts 2) agree with `_reindex`, which adds a posting ID to `_valid` when any of its entries is well formed. Mocked, not deployed.

### WR-09: gap in the goal, or advisory finding?

**Judgment: advisory (warning severity), not a gap. It is a real defect in undeployed hardening and a false documentation claim, and both should be settled before the owner deploys WR-02, WR-06, WR-07 and WR-08.**

- *Verified in code and reproduced.* `distinct_count` counts `_valid`; `keys()` (`compact.py:217-218`), `plan_additions` (`known = self._kinds...`), the `retained_events` and `repair_plan` callers (`compact.py:381`, `:441`, `:574`), `hunter.py:2145` and `storage_report.py:81` read `_kinds`. I ran `IdentitySet.from_rows([IdentityRow("g|a", 1, "t", 3, "bA,xB,b%2c")])`: `distinct_count()` returned 1 and `keys()` returned `{g|a|%2c, g|a|A, g|a|B}`. A set holding only `xB` gave `distinct_count()` 0, `len()` 1, `keys()` `{g|a|B}`; deleting that entry gave 0 and an empty `keys()`. So deleting a malformed entry whose ID has no well-formed twin removes a held ID from the dedupe and the count does not move: no `identity_shrunk`, and `identity_missing` cannot see it once the Events row is folded. The docs say otherwise: `SPEC.md:111` ("the identity the dedupe uses, counted over well-formed entries only"), D-57 ("the identity the dedupe uses (AGENTS rule 3)") and the docstring at `compact.py:231` ("the identity the dedupe can use"). The code contradicts all three. The code and doc claim is false today; I recommend settling it by one of the two fixes in the review.
- *Why it does not fail the goal.* The goal is that Events stops growing and that parity was proven against the old rows before the swap. Both rest on live evidence from 68a7253, which has no Identity-loss detection at all, so WR-09 cannot have affected them. On this axis the branch is strictly stronger than production: production notices no Identity loss; the branch notices the loss of every ID that has a well-formed entry, and misses only one class of ID. No success criterion and no STOR-01 clause requires detection of hand-made Identity damage.
- *How narrow the silent loss actually is (my trace, beyond the review text).* The write path emits only well-formed entries (`encode_entry`), so every ID the code ever baselined has a well-formed entry that the high-water mark counted. If such an entry is later damaged to a malformed form (`bB` to `xB`), the count falls below the mark and `identity_shrunk` is counted, and deleting the damaged entry keeps the count below the mark, so it is still counted. The silent drop therefore needs a malformed entry that was never well formed and was present when the mark was first recorded (or added by hand and never counted), with no well-formed twin. Deleting it returns the dedupe to the state before the damage. Today's live compact check reads 0 counted differences on 68a7253, which includes `identity_entry`, so no malformed Identity entry exists in production now. The reverse effect also exists: while such an entry is present, a posting whose ID it carries counts as already seen (suppressed rather than alerted), but the run is degraded with `identity_entry` the whole time, so it fails visibly.
- *Why it still matters, not rounded down.* AGENTS rules 2 and 3 are why the dedupe matters, the review is right that the figure now claims to describe the dedupe and does not, and the one repair the check invites (delete the flagged entry) is the wrong one for an ID with no twin. The asymmetry the review names is also real: rewriting `bB` to `xB` lowers the figure by one and counts `identity_shrunk` although the ID is still held (a false positive in that direction). No test covers add-malformed-then-delete for an ID that no well-formed entry holds: the WR-08 integration test restores the original cell, and the IDs it adds were never held before. A gap would need a success criterion that Identity-damage detection serves; none does. I treat WR-09 as a deploy decision for the owner (human item 7), not as a failure of the phase goal.
- *Fix options (owner's call; not a new feature, a defect in delivered hardening).* (1) Add a second high-water mark over `len(identity)` (all held IDs) next to `identity_entries`, compared in `_identity_loss` as its own difference. (2) Keep the code and correct SPEC, D-57, STATUS and the docstring to say the count covers well-formed IDs only and that the repair is to correct the entry to canonical form, not delete it. Either way, add the delete test.

### Open points judged without rounding up

| Point | Judgment |
|-------|----------|
| (a) SC3 order-of-magnitude drop | Not demonstrated; one transitional reading; the calendar re-read (about 2026-11-14) is past and has not happened. Not a gap: nothing missing or contradicted. |
| (b) Sheet-internal facts | Not verifiable by the agent. UAT items 1-6 pending. |
| (c) SC4 | Mocked only. VERIFIED by behavioral tests, no live claim. |
| (d) A5 | Mocked; live folds peaked at 131 ranges against a 500 cap. |
| (e) Production vs branch | The fixes WR-01..WR-08 are not deployed. Everything said about them is mocked. The phase goal as delivered in production does not depend on them. |
| (f) WR-09 | Advisory (warning severity), see above. Open in the disposition. |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `compact.py` | Identity codec, Tally, split, merged view, fold, cutover records, effective mode | ✓ VERIFIED | `entry_well_formed` `:70`, `IdentitySet._reindex`/`_valid` `:184-196`, `distinct_count` `:230`, `record_compact_check` high-water mark, `fold_due` `:782` |
| `parity.py` | `check_dual`, `check_compact` | ✓ VERIFIED | `_identity_invariants` `:108-127`, `_identity_loss` `:360-370`, `check_compact` read; wired from `pipeline.storage_check` |
| `state.py` | Identity and Tally tabs, `load_ledger`, `write_identity`, `append_tally`, `swap_events`, `fold_events` | ✓ VERIFIED | Covered by the 939-test run; unchanged by WR-08; not re-read line by line |
| `pipeline.py` | observation write order, storage step, fold step | ✓ VERIFIED | Covered by the suite; unchanged by WR-08 |
| `hunter.py` | `--storage-parity`, `--storage-report`, `--storage-cutover`, `--storage-restore` | ✓ VERIFIED | Suite passes; `hunter.py:2145` still reads `keys()` for the seen set |
| `storage_report.py`, `reporting.py`, `dashboard.py`, `pilot.py` | merged-view reports, before/after, Storage line | ✓ VERIFIED | storage report ran live (42300947285); Dashboard render is an owner check |
| `.github/workflows/job_hunter.yml` | four boolean inputs and fixed steps | ✓ VERIFIED (IN-03 open) | `tests/test_deployment.py` passes in the 939-test run |
| `DECISIONS.md` D-57, `SPEC.md`, `STATUS.md`, `PILOT_LOG.md` | decision record, contract, live labels | ⚠️ VERIFIED WITH ONE FALSE CLAIM | STATUS labels WR-01..WR-08 mocked, not deployed. SPEC.md:111 and D-57 describe the count as "the identity the dedupe uses", which the code does not do (WR-09) |

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| `run_cycle` load | `state.load_ledger` | one load of Events, Identity, Tally | WIRED |
| observation write point | `split_observations` to `write_identity` to `append_tally` to `save_boards` | `persist_observations`; failed Tally row carried | WIRED |
| storage check | `parity.check_dual` / `check_compact` | `pipeline.storage_check`, returns `report.counted` | WIRED |
| `check_compact` | `IdentitySet.distinct_count` | `_identity_invariants` and `_identity_loss` (`parity.py:127`, `:365`) | WIRED (mocked) |
| `check_compact` / `IdentitySet._reindex` | `compact.entry_well_formed` | `parity.py:325`, `compact.py:193` | WIRED (mocked); one predicate, as intended |
| storage check | `record_compact_check` | `identity_entries` from `compared["identity_entries"]` | WIRED (mocked) |
| `IdentitySet.keys()` (dedupe) | `distinct_count` (mark) | none: `keys()` reads `_kinds`, the count reads `_valid` | NOT THE SAME SET (WR-09; docs claim they are) |
| storage check | fold | `check_counted != 0` skips the fold | WIRED (mocked) |
| owner dispatch `storage_cutover` | `hunter.run_storage_cutover` to `swap_events` | live run 41373351559 | WIRED (live) |
| `--storage-report` | `state.sheet_grid()` and cutover `before` | live run 42300947285 | WIRED (live) |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| Storage report before/after | allocated cells, `Load_S`, daily growth | sheet metadata and `Runs` tab | Yes (live report) | FLOWING |
| Dashboard merged view | `folded` counts | `Ledger.folded()` from Identity, Tally, kept Events | Yes in logs (0 differences, 21,735 keys and 898 Tally runs today); render owner check | FLOWING (render unseen) |
| Seen set | Identity keys plus Events `seen` keys | `load_ledger`, `IdentitySet.keys()` | Yes (21,735 kept keys compared today) | FLOWING |
| Identity mark (WR-02/06/07/08/09) | `last_check.identity_entries` | `IdentitySet.distinct_count()` via `compared["identity_entries"]` | Mocked only; distinct well-formed IDs, high-water mark; does not cover IDs held only by malformed entries (WR-09) | FLOWING (mocked; WR-09 caveat) |

### Behavioral Spot-Checks (all mocked unless stated)

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full offline suite | `.venv/bin/python -m unittest discover -s tests` | Ran 939 tests OK, exit 0 | PASS |
| WR-08 tests | `-m unittest tests.test_storage_parity -k test_a_malformed` | Ran 2 tests OK | PASS |
| WR-09 reproduction: count against dedupe | `IdentitySet.from_rows([IdentityRow("g\|a",1,"t",3,"bA,xB,b%2c")])` | `distinct_count()` 1; `keys()` has A, B and %2c | CONFIRMS the advisory |
| WR-09 reproduction: delete a malformed-only entry | set holding only `xB`, then empty | `distinct_count()` 0 and 0; `keys()` `{g\|a\|B}` then empty | CONFIRMS the silent drop (count unchanged) |
| Production check today (live, read-only log) | `gh run view 43755525979 --log` grep `Storage:` | `0 counted and 0 declared differences, 21735 kept job keys and 898 Tally runs compared` | PASS (live, 68a7253) |

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
| `compact.py` / `SPEC.md` / `DECISIONS.md` | 217-235, 231 / 111 / D-57 | WR-09: count over `_valid`, dedupe over `_kinds`; docs claim they are the same | Warning (advisory, see above) | Deleting a malformed entry with no well-formed twin drops a held ID with no `identity_shrunk`; the doc claim is false; undeployed |
| `compact.py` | 585-600 | IN-02: removing `Events_Legacy` flips compact to dual | Info | Blocks the owner's later decision to delete the legacy tab until code changes |
| `.github/workflows/job_hunter.yml` | 170-175 | IN-03: cutover and restore can run in one dispatch | Info | Owner error path only |
| `compact.py` | 372-377 | IN-04: checksum covers three of seven columns | Info | `Events_Legacy` stays whole; no data-loss path |
| `tests/test_storage_parity.py` | 777-822, 927-958, 990-1010 | IN-09: no test names "fold held back" for `identity_shrunk` or `identity_entry` | Info | Claims rest on the WR-05 gate tests plus code reading |
| various | | IN-01, IN-05..IN-08, IN-10, IN-11 | Info | Doc drift, dead code, read race, `first_day` dating, Tally carry quality, no repair tooling, figure still named "entries" |

WR-01 to WR-08 are fixed (commits a2247a9, 58d9ec2, 024319f, 6648949, 8b02697, e83d563, 9fd3383, c845065). No `TBD`, `FIXME` or `XXX` marker in any phase-touched source file.

### Human Verification Required

Seven items, listed in the frontmatter. Six come from 03-UAT.md (`status: testing`, all `result: [pending]`, 0 passed); the seventh is UAT item 7, the deploy decision. Item 7's text names WR-01..WR-07 and WR-08 but not WR-09, so it is current only up to WR-08; this report extends it to WR-01..WR-08 and WR-09 and adds the WR-09 fix-first-or-accept choice. 03-UAT.md is accounted for: none of its items is closed by this verification, and none has been marked passed or failed. Item 5's calendar date has passed without a re-read.

### Gates run

| Gate | Result | Source |
|------|--------|--------|
| Validation | 939 offline tests OK (re-validated after WR-08); status validated | 03-VALIDATION.md; suite re-run here |
| Security | `threats_open: 0` | 03-SECURITY.md (read; not re-audited here) |
| Code review | 0 critical, 1 warning (WR-09), 11 info; WR-01..WR-08 fixed | 03-REVIEW.md, 03-REVIEW-DISPOSITION.md (read) |
| Regression | 939 tests OK (re-run here, exit 0) | this report |

### Gaps Summary

No failed truth, no missing or stubbed artifact, no broken link, no blocker anti-pattern and no debt marker. The storage design is built, deployed (68a7253), cut over and folding in production. The live logs recorded in STATUS and PILOT_LOG back parity at zero differences before the swap, a swap that deleted nothing, Events falling from 235,785 to 30,613 rows and four clean folds, and today's production compact check (run 43755525979) again reads 0 counted and 0 declared differences. The phase stays `human_needed` for the same reasons as before, none rounded away: the order-of-magnitude growth drop (SC3) has one transitional reading and no steady-state re-read yet; the Sheet-internal facts and the Telegram chat are owner checks (UAT 1-4) and A5 is an owner acceptance (UAT 6); SC4 and "no alert twice" are mocked only. Two points are specific to this round. The review fixes WR-01..WR-08 are branch-only, so their effect is unverified live and they need the owner's deploy decision. WR-08 is now fixed for malformed entries, and the new open warning WR-09 is the mirror image: the count is blind to IDs that only a malformed entry holds, while the dedupe is not, and SPEC, D-57 and the docstring say they are the same. That is a defect in undeployed hardening that production does not have in any form (production has no shrink detection), with a narrow trigger and a visible failure mode; the owner should fix it or consciously accept it, and at minimum correct the false claim, before deploying. Separately, "stops growing toward the limit" holds for the Events ledger, not for the spreadsheet total, while `Events_Legacy` is kept. STOR-01 stays unticked in REQUIREMENTS.md until the human items close.

---

_Verified: 2026-11-15T20:16:00Z_
_Verifier: Claude (gsd-verifier)_
