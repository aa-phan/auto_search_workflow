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
| (filled per task once plans exist; see 03-RESEARCH.md "Validation Architecture" for the SC1-SC4 test map) | | | STOR-01 | | | | | | ⬜ pending |

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
