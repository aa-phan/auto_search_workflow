---
phase: 02-measurement-governors-and-owner-decisions
plan: 09
subsystem: provider-policy
tags: [smartrecruiters, gov-01, d-54, owner-decision, superseded]

requires:
  - phase: 02-measurement-governors-and-owner-decisions
    provides: "D-48 owner-decision inventory (plan 02-01)"
provides:
  - "DECISIONS D-54: SmartRecruiters stays polled after the pilot (reverses P2-14 / D-48 row 3; extends D-38)"
  - "Workflow comments in job_hunter.yml and inventory.yml cite D-54; SPEC, STATUS and ROADMAP point at D-54"
affects: [phase-05-board-growth, provider-policy]

actuals:
  tasks: 0
  commits: 1
outcome: superseded
plan_head_before: 1d63416
plan_head_after: 7907e70

requirements-completed: []
---

# Plan 02-09 Summary: superseded by owner decision D-54

**Outcome:** not executed as planned. On 2026-10-28, before Task 1 could run (its precondition, the first weekly rebalance read, was still pending), the owner reversed P2-14: "i want to keep smartrecruiters". The plan's goal was to deploy the parking decision, so there is nothing to deploy.

## What was done instead (orchestrator, inline)

- Recorded **D-54** in DECISIONS.md: SmartRecruiters stays polled; risks accepted as in D-38 (robots.txt disallow, existence unverifiable, unverified Alphabe Insight Inc rows); mitigations kept; "if SmartRecruiters objects, reverse at once" carried over.
- Amended D-48 row 3 ("Superseded by D-54"), the D-38 heading, SPEC "Provider limits honoured", STATUS, and the ROADMAP owner table.
- Workflow comments in `.github/workflows/job_hunter.yml` and `inventory.yml` now cite D-54 instead of "for the pilot". The `ALLOW_SMARTRECRUITERS_BULK: "1"` lines are unchanged.
- Commit: `7907e70`.

## Not done (by design)

- Tasks 1-3 (remove override, deployment test change, push, PILOT_LOG row, live read of the parking run): no longer applicable.
- No push. The comment-only workflow change reaches GitHub with the next push the owner approves.

## Verification

- `.venv/bin/python -m unittest discover -s tests`: 621 tests OK (offline, mocked). `tests/test_deployment.py::test_smartrecruiters_override_is_explicit_in_both_workflows_slowed_and_announced` already asserts the kept override, the 1.0 s spacing and the parked code default.
- Nothing live: production behaviour is unchanged.

## Requirements

GOV-01 is not marked here: the remaining D-48 pending owner decisions (D-05 amendment, rule-7 lift, per-ATS policy, storage approval) are needed by later phases, so whether GOV-01 counts as complete for Phase 2 is left to phase verification.

## Self-Check: PASSED
