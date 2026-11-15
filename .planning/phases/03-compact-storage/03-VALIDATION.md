---
phase: "3"
slug: "compact-storage"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: true
created: "2026-10-29"
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | unittest (stdlib), Python 3.12 |
| **Config file** | none (`python -m unittest discover -s tests`) |
| **Quick run command** | `.venv/bin/python -m unittest tests.test_compact tests.test_storage_parity -q` |
| **Full suite command** | `.venv/bin/python -m unittest discover -s tests` |
| **Estimated runtime** | ~1 second (quick), ~16 seconds (full suite) |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/python -m unittest tests.test_compact tests.test_storage_parity -q`
- **After every plan wave:** Run `.venv/bin/python -m unittest discover -s tests`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 3 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-T1 | 01 | 1 | STOR-01 (SC1) | T-03-01, T-03-05 | Events -> Identity -> Tally -> Boards; Identity IDs stay seen; both stores create the hidden Identity and Tally tabs (bootstrap tab-set test updated) | tracer (Harness, CSV) | `.venv/bin/python -m unittest tests.test_storage_pipeline -q` | ✅ | ✅ green |
| 03-01-T2 | 01 | 1 | STOR-01 (SC1, SC4) | T-03-01, T-03-02, T-03-03, T-03-04, T-03-06 | 40,000-char cells, 1M-char requests, escaping, stem casing, interrupted baseline; warning-only Identity protection; ensure() refuses to recreate Events (EnsureTests) | unit + integration (shared fake) | `.venv/bin/python -m unittest tests.test_compact tests.test_storage_pipeline -q` | ✅ | ✅ green |
| 03-01-T3 | 01 | 1 | STOR-01 | — | D-57, SPEC subsection and AGENTS layout line describe Tasks 1-2 (documents only, same plan) | grep + suite | `grep -c "^## D-57" DECISIONS.md && grep -c "### Compact storage (D-57)" SPEC.md && .venv/bin/python -m unittest discover -s tests` | ✅ | ✅ green |
| 03-02-T1 | 02 | 2 | STOR-01 (SC2, P3-09) | T-03-07 | seed once, idempotent redo; first check clean | tracer (Harness) | `.venv/bin/python -m unittest tests.test_storage_pipeline -k Seed -q` | ✅ | ✅ green |
| 03-02-T2 | 02 | 2 | STOR-01 (SC2, P3-07) | T-03-09, T-03-10 | every mutation named; degraded; Events authoritative | unit + Harness | `.venv/bin/python -m unittest tests.test_storage_parity -q` | ✅ | ✅ green |
| 03-02-T3 | 02 | 2 | STOR-01 (SC2, P3-05) | T-03-07, T-03-08 | 3 complete UTC days, 12 runs, admission; reset; cap | unit | `.venv/bin/python -m unittest tests.test_storage_parity -k Clock -q` | ✅ | ✅ green |
| 03-03-T1 | 03 | 3 | STOR-01 (P3-10, P3-11) | T-03-12 | Dashboard summary identical in dual / simulated / half-folded views | tracer (pure + render) | `.venv/bin/python -m unittest tests.test_reporting -k CompactParity -q` | ✅ | ✅ green |
| 03-03-T2 | 03 | 3 | STOR-01 (P3-10) | T-03-12 | reconcile, pilot report, logical storage counts identical | unit | `.venv/bin/python -m unittest tests.test_storage_report tests.test_pilot_corrections tests.test_pilot -q` | ✅ | ✅ green |
| 03-03-T3 | 03 | 3 | STOR-01 (SC2) | T-03-13, T-03-14 | figures layer; declared tracker rows; numbers-only details | unit | `.venv/bin/python -m unittest tests.test_storage_parity -q` | ✅ | ✅ green |
| 03-04-T1 | 04 | 4 | STOR-01 (P3-05..07, P3-11) | T-03-17, T-03-18 | READY TO CUT OVER only on a met bar; NEEDS ATTENTION with keys only | tracer (summary + render) | `.venv/bin/python -m unittest tests.test_reporting -k DashboardStorage -q` | ✅ | ✅ green |
| 03-04-T2 | 04 | 4 | STOR-01 (SC2) | T-03-15, T-03-16 | read-only command writes nothing; boolean input | unit + static | `.venv/bin/python -m unittest tests.test_deployment tests.test_hunter -k StorageParity -k storage_parity -k telegram -q` | ✅ | ✅ green |
| 03-04-T3 | 04 | 4 | STOR-01 | — | docs and STATUS labels (mocked) | grep + suite | `grep -c "Phase 3 compact storage (D-57" STATUS.md && .venv/bin/python -m unittest discover -s tests` | ✅ | ✅ green |
| 03-05-T1..T3 | 05 | 5 | STOR-01 (SC2 live start) | T-03-19..22 | consent, secret scan, live evidence from public logs | pre-deploy gate + live | 02-07 gate command (see plan) | ✅ | ✅ green |
| 03-06-T1 | 06 | 6 | STOR-01 (SC3, P3-14) | T-03-23..25 | gate, copy, read back, one ordered rename batch | tracer (shared fake) | `.venv/bin/python -m unittest tests.test_storage_cutover -k CutoverTracer -q` | ✅ | ✅ green |
| 03-06-T2 | 06 | 6 | STOR-01 (P3-06, P3-08) | T-03-23, T-03-26, T-03-27 | refusals, dry run, interruption, restore before the first fold | integration | `.venv/bin/python -m unittest tests.test_storage_cutover -q` | ✅ | ✅ green |
| 03-06-T3 | 06 | 6 | STOR-01 | T-03-28 | boolean owner inputs, fixed commands | static | `.venv/bin/python -m unittest tests.test_deployment -q` | ✅ | ✅ green |
| 03-07-T1 | 07 | 7 | STOR-01 (SC3, P3-03) | T-03-29, T-03-30 | fold only durable rows, descending ranges, once a day, not on the cutover day | tracer (shared fake) | `.venv/bin/python -m unittest tests.test_storage_cutover -k Fold -q` | ✅ | ✅ green |
| 03-07-T2 | 07 | 7 | STOR-01 (SC3) | T-03-32 | allocated cells, before/after, order-of-magnitude simulation | unit + simulation | `.venv/bin/python -m unittest tests.test_storage_report -q` | ✅ | ✅ green |
| 03-07-T3 | 07 | 7 | STOR-01 | T-03-31 | compact-mode integrity check (incl. WR-02 identity_shrunk with the WR-06 high-water mark over WR-07 distinct IDs) | unit | `.venv/bin/python -m unittest tests.test_storage_parity -k Integrity -q` | ✅ | ✅ green |
| 03-08-T1..T3 | 08 | 8 | STOR-01 | T-03-33, T-03-34 | consent; dual mode unchanged live | pre-deploy gate + live | 02-07 gate command (see plan) | ✅ | ✅ green |
| 03-09-T1..T3 | 09 | 9 | STOR-01 (SC2, SC3 live) | T-03-35..37 | owner's one-way decision; live evidence by run id | manual + live | see plan (preconditions are calendar waits) | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/fake_sheets.py` — shared in-memory Spreadsheet/Worksheet fake (values + spreadsheet batch_update, metadata grid sizes, cell/request caps, fault injection)
- [x] `tests/test_compact.py`, `tests/test_storage_parity.py`, `tests/test_storage_pipeline.py`, `tests/test_storage_cutover.py` — STOR-01 (SC1-SC4)
- [x] Synthetic ledger builder shared by parity and report tests
- [x] No framework install needed (stdlib unittest)

*If none: "Existing infrastructure covers all phase requirements."*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Warning-only protection on `Identity` does not block service-account writes | STOR-01 | Live Sheets behavior (A2) | **Live (public logs):** every run since the seed wrote Identity with no permission error; compact runs compare 232k+ Identity entries (parity run 41375689814). The protection prompt itself is an owner check |
| Cutover rename swap on the real Sheet | STOR-01 | Live Sheets batchUpdate | **Live (public log):** run 41373351559 `STORAGE CUTOVER done ... mode compact`, 25,531 rows in Events, 235,785 in Events_Legacy; later runs load the new Events. Events_Legacy hidden and protected: owner check |
| Large `deleteDimension` fold batches | STOR-01 | Live quota/latency (A5) | **Partly live:** folds 41549615660, 41743488450, 41938020379, 42133570806 (2,866 / 5,153 / 4,512 / 4,221 rows, 94 / 131 / 88 / 106 ranges, no `storage fold failed`). Whether a single 500-request batch occurred is not logged: A5 stays mocked |
| 3 consecutive UTC days of zero parity differences | STOR-01 | Needs real calendar time | **Live (public log):** run 41364810371 `3 of 3 complete days toward the bar, admission seen yes` (2026-10-30, 10-31, 11-01). Dashboard READY TO CUT OVER: owner check |

*If none: "All phase behaviors have automated verification."*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 3s (quick run command)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** re-validated 2026-11-15 after the review fixes WR-01..WR-07 (every automated command above re-run green, full suite `Ran 937 tests ... OK`; the fixes' tests sit in the mapped files test_compact, test_storage_parity and test_storage_cutover, WR-06/WR-07 in test_storage_parity; live and owner-check items labelled in Manual-Only). First validated 2026-11-06 (910 tests).

## Validation Audit 2026-11-06

| Metric | Count |
|---|---|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |
