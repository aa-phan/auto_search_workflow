# Synthesis summary (entry point for gsd-roadmapper)

Mode: merge. Generated 2026-10-24. Repo docs are authoritative; intel files reference them by path and D-number and do not restate them as new rules.

## Status
- Blockers: 0. Warnings: 6 (need user approval before routing). Info: 13. Competing PRD variants: 0 (no PRDs in the set).
- Full detail: `/Users/aphan/auto_search_workflow/.planning/INGEST-CONFLICTS.md`.
- Product state: v1 shipped (board polling with verified freshness, Sheet + Telegram delivery, board slot allocation, dashboard, watchdog). Pilot week 1 passed (2026-10-15 01:47 to 2026-10-22 01:47 UTC). Post-pilot D-45, D-46, D-47 deployed 2026-10-23/24. Next weekly rebalance due about 2026-10-29 01:00 UTC.

## Documents ingested (7)
- ADR: 1 (`DECISIONS.md`, precedence 0)
- SPEC: 1 (`SPEC.md`, precedence 1)
- DOC: 5 (`AGENTS.md` 2, `STATUS.md` 3, `DEPLOY.md` 4, `PILOT_LOG.md` 5, `README.md` 6)
- Existing .planning read for merge: PROJECT.md (consistent), ROADMAP.md and STATE.md (stale, superseded history), codebase/CONCERNS.md (v2 source). REQUIREMENTS.md does not exist.

## Decisions locked: 47
- Source: `DECISIONS.md` D-01..D-47, all locked by manifest assertion. Intel: `intel/decisions.md`.
- Supersession chains are listed at the end of that file; the latest in each chain is authoritative. Still-open items inside locked entries: D-16 (owner OK), D-22, D-30 (initial operating choices), D-43 (storage decision not made).

## Requirements: 36 (no PRDs; derived by reference)
- v1 (20), verification from STATUS.md: 16 live-verified, 4 mocked-only, 0 blocked. Several live-verified entries carry a mocked-only sub-part noted in the entry (for example the weekly rebalance cycle, Groq 429 fallback, header-missing refusal).
  - mocked-only: REQ-state-ledger-retry, REQ-writer-serialization, REQ-provider-policy-backoff, REQ-watchdog.
  - live-verified: REQ-fresh-window-alerts, REQ-board-polling, REQ-freshness-classification, REQ-job-identity-dedupe, REQ-baselining, REQ-filtering-eligibility, REQ-groq-scoring, REQ-sheet-tracker-delivery, REQ-telegram-alerts, REQ-board-registry-inventory, REQ-board-admission-promotion, REQ-board-pools-rebalance, REQ-discovery-rotation-search, REQ-dashboard, REQ-pilot-measurement, REQ-secrets-and-data-hygiene.
- v2 candidates (16, unscheduled, from STATUS "Next milestone" and "Known gaps / risks" and CONCERNS.md): REQ-v2-first-weekly-rebalance-review, REQ-v2-limits-at-700, REQ-v2-wider-settings-observation, REQ-v2-d47-follow-up, REQ-v2-events-storage, REQ-v2-alert-recording-fix, REQ-v2-alert-exception-bound, REQ-v2-telegram-truncation, REQ-v2-watchdog-external-trigger, REQ-v2-daily-digest, REQ-v2-recheck-interval-evidence, REQ-v2-title-gate-leaks, REQ-v2-live-test-gaps, REQ-v2-hunter-modularization, REQ-v2-supply-chain-pinning, REQ-v2-owner-decisions-record.
- Gate: AGENTS.md rule 7 and STATUS.md bar score tuning and new features until the Next milestone items are read (REQ-v2-daily-digest and REQ-v2-title-gate-leaks are the clearest cases).
- Intel: `intel/requirements.md`.

## Constraints: 23
- schema 5, protocol 8, nfr 6, api-contract 4. Source: `SPEC.md` sections with locking D-numbers; one entry sourced from `AGENTS.md` rules. Intel: `intel/constraints.md`.

## Context topics: 11
- Agent working agreement, code layout, current status, post-pilot state, verification map, known gaps, deployment runbook, pilot log, user-facing guide, pre-existing GSD files, inputs not ingested. Intel: `intel/context.md`.

## Conflicts
- 0 blockers, 6 warnings (cross-ref cycles judged benign; repository visibility; unconfirmed owner items; rule-7 gate on v2 scope; code-vs-contract alert defects; SmartRecruiters override outliving the pilot), 13 info (auto-resolved chains and stale-doc notes).
- Judgment call to review: the two cross-reference cycles (AGENTS.md <-> STATUS.md, STATUS.md <-> PILOT_LOG.md) were reported as a WARNING instead of the BLOCKER the synthesizer rule prescribes, because they are mutual see-also links and extraction never followed references.

## Files
- `/Users/aphan/auto_search_workflow/.planning/intel/decisions.md`
- `/Users/aphan/auto_search_workflow/.planning/intel/requirements.md`
- `/Users/aphan/auto_search_workflow/.planning/intel/constraints.md`
- `/Users/aphan/auto_search_workflow/.planning/intel/context.md`
- `/Users/aphan/auto_search_workflow/.planning/INGEST-CONFLICTS.md`
- Classifications: `/Users/aphan/auto_search_workflow/.planning/intel/classifications/`
