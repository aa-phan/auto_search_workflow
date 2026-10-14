# Task 261014-olj: Board slot allocation (verbatim requirements)

Inspect the existing board registry, validation queue, promotion logic, polling pipeline, and repository instructions. Fix the demonstrated allocation problem: the first 500 qualifying boards currently retain their slots indefinitely, while potentially better boards cannot enter.

Implement an incremental, configurable policy:

1. Refresh monitored-board relevance during successful, complete hourly polls using data already fetched. Track current relevant-job count, location eligibility where available, last successful poll, last newly observed relevant posting, and rolling 7-/30-day counts of newly observed relevant postings. Keep open-job counts separate from new-posting activity. Exclude baseline imports from activity counts and distinguish unknown history from zero activity. Do not add LLM calls for board ranking.

2. Inspect the title gate's requirement for an explicit level keyword. Identify suitable titles it might reject, such as "Marketing Coordinator." Document the finding and make only narrowly justified changes that preserve seniority exclusions.

3. Separate never-validated candidates and overdue revalidations into independently budgeted queues. Process overdue revalidations oldest-first so the initial inventory backlog cannot starve waiting boards.

4. Introduce configurable established and exploration pools within Max_Active_Boards. Start with an 80/20 split (400 established and 100 exploration at the default cap) and a seven-day exploration period. Treat these as initial operating choices, not proven optimal values. Boards without observation history must have a fair route into exploration.

5. Rebalance weekly using a transparent policy based on eligible-role availability and observed new relevant activity. Compare candidates with existing monitored boards rather than merely filling vacancies. Bound replacements per cycle, protect trial boards, and avoid favoring boards solely because they have longer monitoring histories. Do not demote boards based on one empty response, partial fetch, or temporary failure.

6. Preserve job IDs, freshness evidence, provenance, and delivery state when boards leave monitoring. On reentry, re-establish a baseline and evaluate jobs added during the gap using source publication evidence; do not treat them all as newly published. Existing pending delivery retries must survive demotion.

7. Apply provider restrictions consistently to existing and newly admitted boards. Existing SmartRecruiters boards must not remain actively polled while that provider is parked. Preserve their history.

Log pool membership, admission/demotion reasons, queue age, relevant waiting candidates, and actual monitoring coverage. Make transitions deterministic and safe against overlapping workflows. Provide a dry-run rebalance report before enabling scheduled rebalancing.

Add meaningful tests for queue fairness, capacity limits, bounded replacement, trial protection, baseline exclusion, incomplete-fetch handling, and state preservation. Update SPEC, DECISIONS, STATUS, and README. Complete the implementation and report what was verified, including any migration requirements. Do not redesign Serper or replace the job scorer in this task.

## Repo rules (AGENTS.md, binding)
Read SPEC.md, DECISIONS.md, STATUS.md first. Flag conflicts with SPEC/DECISIONS before changing behavior and update docs in the same change. Freshness is the product (never use update/crawl time as publication time). Job identity = ATS+board+posting ID. Keep seen/evaluated/alerted separate and retryable. Separate mocked from live verification. Never read/print/commit .env, Resume.pdf, resume.txt, service-account JSON. Do not tune scores. Run `.venv/bin/python -m unittest discover -s tests` (offline) before finishing; currently 201 tests pass.

## Known current code facts (verified by orchestrator)
- boards.py: activate_waiting() fills only vacancies: room=min(per_run, max_monitored - monitored); candidates = status validated, validation==valid, relevant_jobs>0, ordered (-relevant_jobs, last_job_count, key). No demotion except `disabled` after 72 consecutive failures. BoardRecord/BOARD_COLUMNS in state.py (positional rows; widening header is supported in SheetState._widen_header).
- relevant_jobs is only set at validation (inventory.apply_validation); monitored boards' counts are never refreshed by polls.
- inventory.run_validation(): one due list mixing candidates and revalidations sorted by _priority (-n_sources, live, key), truncated to max_boards -> revalidations starve behind the ~18.5k candidate backlog. validation_due(): validated boards due after 7 days.
- pipeline.run_cycle(): admit (inventory.admit_boards) -> activate_waiting -> poll_boards -> classify new IDs (baseline pass when board not baselined) -> hydrate search jobs -> evaluate -> alert. Baseline pass: first successful poll records existing IDs as 'baseline' (lg.observe_new with baseline_pass), except time-precision fresh ones. FLOOD re-baseline exists for >=30 unseen IDs.
- eligibility.title_gate(title, roles, levels, excluded_regex) requires a role keyword AND a level keyword (Settings Target_Levels: Coordinator, Associate, Specialist, Intern, Assistant, Junior) and no excluded word. Audit it for e.g. "Marketing Coordinator" ("Coordinator" is a level word already) vs titles like "Social Media Marketing" with no level word.
- SmartRecruiters is parked via inventory.policy_blocks for candidates/new admissions, but boards already status new/active (previously activated by Serper) stay polled; pipeline only notes their count in Runs.Notes.
- State tabs: Boards (row-level upserts, two writers: importer owns candidate/validated/invalid/deferred; poller owns new/active/disabled — see D-15), Events (append-only ledger), Runs, Discovery (key/value JSON). Workflows: .github/workflows/job_hunter.yml (hourly, concurrency group job-hunter) and inventory.yml (weekly/daily, group job-hunter-inventory).
- Settings live in hunter.DEFAULT_SETTINGS / Settings dataclass; existing Sheets may lack new rows (defaults apply).
