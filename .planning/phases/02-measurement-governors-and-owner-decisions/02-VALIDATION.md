---
phase: "2"
slug: "measurement-governors-and-owner-decisions"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-10-26"
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | `unittest` (stdlib), Python 3.12 |
| **Config file** | none (discovery by directory) |
| **Quick run command** | `.venv/bin/python -m unittest tests.test_governors tests.test_core tests.test_hunter tests.test_reporting -q` |
| **Full suite command** | `.venv/bin/python -m unittest discover -s tests` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run the quick run command
- **After every plan wave:** Run the full suite command
- **Before `/gsd-verify-work`:** Full suite must be green, plus the labelled live checks below
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

Filled in from the PLAN.md task IDs once plans exist. Requirement-level map (from 02-RESEARCH.md § Validation Architecture):

| Requirement | Behavior | Test Type | Automated Command | File Exists | Status |
|-------------|----------|-----------|-------------------|-------------|--------|
| MEAS-05 | `send_alert` returning `False` records no `alerted` event; job stays pending; no attempt used | unit (Harness) | `.venv/bin/python -m unittest tests.test_core -k alert -q` | extend | ⬜ pending |
| MEAS-05 | Failure without HTTP response: 5 failure events then `abandoned`; run 6 does not send | unit | same | extend | ⬜ pending |
| MEAS-05 | Stored and logged error text never contains the bot token | unit | same | extend | ⬜ pending |
| MEAS-03 | Budget: UTC-day rollover, per-model counters, verified-fresh reserve, JSON round trip | unit (pure) | `.venv/bin/python -m unittest tests.test_governors -q` | ❌ W0 | ⬜ pending |
| MEAS-03 | `GroqClient` records total and cached tokens and limit headers; daily-limit 429 marks the model spent | unit | `.venv/bin/python -m unittest tests.test_hunter -k Groq -q` | extend | ⬜ pending |
| MEAS-03 | Forced limit: budget 0 leaves jobs pending with no events; next day they are scored | unit (Harness) | `.venv/bin/python -m unittest tests.test_governors -k forced -q` | ❌ W0 | ⬜ pending |
| MEAS-03 | New `Runs` columns round-trip; old short rows still load | unit | `.venv/bin/python -m unittest tests.test_pools tests.test_pilot tests.test_discovery -q` | extend | ⬜ pending |
| MEAS-04 | `poll_boards` past the deadline marks the rest `skipped_deadline`, never fetches them; longest-unpolled first | unit | `.venv/bin/python -m unittest tests.test_governors -k poll -q` | ❌ W0 | ⬜ pending |
| MEAS-04 | Deadline anchored at process start; verified-fresh scored first; outcome split (poll cut = degraded) | unit | `.venv/bin/python -m unittest tests.test_governors -k outcome -q` | ❌ W0 | ⬜ pending |
| MEAS-04 | Client deadline bounds `TokenBudget.wait` and 429 loops | unit | `.venv/bin/python -m unittest tests.test_hunter -k deadline -q` | extend | ⬜ pending |
| MEAS-01 | Yield: per-day counts by cohort, age buckets, feedback mix, unmatched rows | unit | `.venv/bin/python -m unittest tests.test_reporting -k yield -q` | extend | ⬜ pending |
| MEAS-01 | Reconcile names missing keys; Dashboard chart and band; idempotent rerun | unit | `.venv/bin/python -m unittest tests.test_reporting -k dashboard -q` | extend | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_governors.py` — budget, forced-limit, poll deadline and order, outcome split, process-start anchoring
- [ ] Fake monotonic clock helper shared by `poll_boards`, `Deps` and `GroqClient` tests
- [ ] `Harness` in `tests/test_core.py` — `send_alert` can return `False` and raise typed exceptions
- [ ] No framework install needed

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Groq account limits (tier, RPM, TPM, RPD, TPD) and plan decision | MEAS-02 | Only visible on the Groq console; no credentials here (rule 5) | Owner reads the console limits page; figures written to STATUS.md with source and date |
| Token columns and cut/skip counters in real `Runs` rows; one UTC-day total vs Groq console | MEAS-03, MEAS-04 | Needs production runs | Read `Runs` after deployment via the Sheets connector |
| Dashboard chart and band render; row count reconciles with ledger | MEAS-01 | Needs the real Sheet | Look at the Dashboard tab in the real Sheet |
| One `delivery_test` run if the alert path changed materially | MEAS-05 | Needs Telegram credentials and the owner's tick | Owner triggers the workflow run |
| Every owner decision has an entry with needed-by phase and default | GOV-01 | Documentation check | `grep -n "needed by" DECISIONS.md` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
