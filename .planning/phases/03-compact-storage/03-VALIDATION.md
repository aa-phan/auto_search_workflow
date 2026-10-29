---
phase: "3"
slug: "compact-storage"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
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
| **Estimated runtime** | ~3 seconds |

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
| 03-01-T1 | 01 | 1 | STOR-01 (SC1) | T-03-01, T-03-05 | Events -> Identity -> Tally -> Boards; Identity IDs stay seen; both stores create the hidden Identity and Tally tabs (bootstrap tab-set test updated) | tracer (Harness, CSV) | `.venv/bin/python -m unittest tests.test_storage_pipeline -q` | ❌ W0 (created by the task) | ⬜ pending |
| 03-01-T2 | 01 | 1 | STOR-01 (SC1, SC4) | T-03-01, T-03-02, T-03-03, T-03-04, T-03-06 | 40,000-char cells, 1M-char requests, escaping, stem casing, interrupted baseline; warning-only Identity protection; ensure() refuses to recreate Events (EnsureTests) | unit + integration (shared fake) | `.venv/bin/python -m unittest tests.test_compact tests.test_storage_pipeline -q` | ❌ W0 (tests/fake_sheets.py, tests/test_compact.py) | ⬜ pending |
| 03-01-T3 | 01 | 1 | STOR-01 | — | D-57, SPEC subsection and AGENTS layout line describe Tasks 1-2 (documents only, same plan) | grep + suite | `grep -c "^## D-57" DECISIONS.md && grep -c "### Compact storage (D-57)" SPEC.md && .venv/bin/python -m unittest discover -s tests` | ✅ | ⬜ pending |
| 03-02-T1 | 02 | 2 | STOR-01 (SC2, P3-09) | T-03-07 | seed once, idempotent redo; first check clean | tracer (Harness) | `.venv/bin/python -m unittest tests.test_storage_pipeline -k Seed -q` | ✅ (from 03-01) | ⬜ pending |
| 03-02-T2 | 02 | 2 | STOR-01 (SC2, P3-07) | T-03-09, T-03-10 | every mutation named; degraded; Events authoritative | unit + Harness | `.venv/bin/python -m unittest tests.test_storage_parity -q` | ❌ W0 (created by the task) | ⬜ pending |
| 03-02-T3 | 02 | 2 | STOR-01 (SC2, P3-05) | T-03-07, T-03-08 | 3 complete UTC days, 12 runs, admission; reset; cap | unit | `.venv/bin/python -m unittest tests.test_storage_parity -k Clock -q` | ✅ (from T2) | ⬜ pending |
| 03-03-T1 | 03 | 3 | STOR-01 (P3-10, P3-11) | T-03-12 | Dashboard summary identical in dual / simulated / half-folded views | tracer (pure + render) | `.venv/bin/python -m unittest tests.test_reporting -k CompactParity -q` | ✅ extend | ⬜ pending |
| 03-03-T2 | 03 | 3 | STOR-01 (P3-10) | T-03-12 | reconcile, pilot report, logical storage counts identical | unit | `.venv/bin/python -m unittest tests.test_storage_report tests.test_pilot_corrections tests.test_pilot -q` | ✅ extend | ⬜ pending |
| 03-03-T3 | 03 | 3 | STOR-01 (SC2) | T-03-13, T-03-14 | figures layer; declared tracker rows; numbers-only details | unit | `.venv/bin/python -m unittest tests.test_storage_parity -q` | ✅ extend | ⬜ pending |
| 03-04-T1 | 04 | 4 | STOR-01 (P3-05..07, P3-11) | T-03-17, T-03-18 | READY TO CUT OVER only on a met bar; NEEDS ATTENTION with keys only | tracer (summary + render) | `.venv/bin/python -m unittest tests.test_reporting -k DashboardStorage -q` | ✅ extend | ⬜ pending |
| 03-04-T2 | 04 | 4 | STOR-01 (SC2) | T-03-15, T-03-16 | read-only command writes nothing; boolean input | unit + static | `.venv/bin/python -m unittest tests.test_deployment tests.test_hunter -k StorageParity -k storage_parity -k telegram -q` | ✅ extend | ⬜ pending |
| 03-04-T3 | 04 | 4 | STOR-01 | — | docs and STATUS labels (mocked) | grep + suite | `grep -c "Phase 3 compact storage (D-57" STATUS.md && .venv/bin/python -m unittest discover -s tests` | ✅ | ⬜ pending |
| 03-05-T1..T3 | 05 | 5 | STOR-01 (SC2 live start) | T-03-19..22 | consent, secret scan, live evidence from public logs | pre-deploy gate + live | 02-07 gate command (see plan) | ✅ | ⬜ pending |
| 03-06-T1 | 06 | 6 | STOR-01 (SC3, P3-14) | T-03-23..25 | gate, copy, read back, one ordered rename batch | tracer (shared fake) | `.venv/bin/python -m unittest tests.test_storage_cutover -k CutoverTracer -q` | ❌ W0 (created by the task) | ⬜ pending |
| 03-06-T2 | 06 | 6 | STOR-01 (P3-06, P3-08) | T-03-23, T-03-26, T-03-27 | refusals, dry run, interruption, restore before the first fold | integration | `.venv/bin/python -m unittest tests.test_storage_cutover -q` | ✅ (from T1) | ⬜ pending |
| 03-06-T3 | 06 | 6 | STOR-01 | T-03-28 | boolean owner inputs, fixed commands | static | `.venv/bin/python -m unittest tests.test_deployment -q` | ✅ extend | ⬜ pending |
| 03-07-T1 | 07 | 7 | STOR-01 (SC3, P3-03) | T-03-29, T-03-30 | fold only durable rows, descending ranges, once a day, not on the cutover day | tracer (shared fake) | `.venv/bin/python -m unittest tests.test_storage_cutover -k Fold -q` | ✅ (from 03-06) | ⬜ pending |
| 03-07-T2 | 07 | 7 | STOR-01 (SC3) | T-03-32 | allocated cells, before/after, order-of-magnitude simulation | unit + simulation | `.venv/bin/python -m unittest tests.test_storage_report -q` | ✅ extend | ⬜ pending |
| 03-07-T3 | 07 | 7 | STOR-01 | T-03-31 | compact-mode integrity check | unit | `.venv/bin/python -m unittest tests.test_storage_parity -k Integrity -q` | ✅ extend | ⬜ pending |
| 03-08-T1..T3 | 08 | 8 | STOR-01 | T-03-33, T-03-34 | consent; dual mode unchanged live | pre-deploy gate + live | 02-07 gate command (see plan) | ✅ | ⬜ pending |
| 03-09-T1..T3 | 09 | 9 | STOR-01 (SC2, SC3 live) | T-03-35..37 | owner's one-way decision; live evidence by run id | manual + live | see plan (preconditions are calendar waits) | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/fake_sheets.py` — shared in-memory Spreadsheet/Worksheet fake (values + spreadsheet batch_update, metadata grid sizes, cell/request caps, fault injection)
- [ ] `tests/test_compact.py`, `tests/test_storage_parity.py`, `tests/test_storage_pipeline.py`, `tests/test_storage_cutover.py` — STOR-01 (SC1-SC4)
- [ ] Synthetic ledger builder shared by parity and report tests
- [ ] No framework install needed (stdlib unittest)

*If none: "Existing infrastructure covers all phase requirements."*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Warning-only protection on `Identity` does not block service-account writes | STOR-01 | Live Sheets behavior (A2) | First production run after deploy: Identity rows written, no permission error in the run log |
| Cutover rename swap on the real Sheet | STOR-01 | Live Sheets batchUpdate | Owner dispatches `storage_cutover`; confirm `Events_Legacy` hidden and new `Events` loads |
| Large `deleteDimension` fold batches | STOR-01 | Live quota/latency (A5) | First post-cutover fold run: Runs row clean, storage report shows the drop |
| 3 consecutive UTC days of zero parity differences | STOR-01 | Needs real calendar time | Dashboard/STATUS show "ready to cut over"; PILOT_LOG row |

*If none: "All phase behaviors have automated verification."*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 3s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
