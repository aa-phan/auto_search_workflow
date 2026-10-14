# Auto Search Workflow

Fresh-job alerts for a non-technical user: poll public ATS boards (Greenhouse, Lever, Ashby, Workable, SmartRecruiters), detect new postings, verify freshness from source publication evidence, score against a resume, deliver via Google Sheets + Telegram.

Contract and rationale live outside `.planning/`: `SPEC.md` (contract), `DECISIONS.md` (why), `STATUS.md` (verified vs blocked), `AGENTS.md` (agent rules). Those win over anything here. Code map: `.planning/codebase/`.

## Constraints
- Freshness is the product; never use update/crawl time as publication time (AGENTS.md rule 2).
- Never read, print or commit `.env`, `Resume.pdf`, `resume.txt`, service-account JSON.
- Keep tests offline: `python -m unittest discover -s tests` (use `.venv/bin/python`).
- Do not tune scores or add features beyond the stated task.
