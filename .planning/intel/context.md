# Context (synthesized intel)

Topic-keyed running notes from the DOC sources, in manifest precedence order (AGENTS.md 2 > STATUS.md 3 > DEPLOY.md 4 > PILOT_LOG.md 5 > README.md 6), plus existing `.planning/` files (merge mode) and CONCERNS.md. Short verbatim quotes are marked with quotation marks; everything else is a pointer. The repo documents stay authoritative. Where a lower-precedence DOC is stale against a higher one, the higher one is used and the staleness is logged as INFO in `.planning/INGEST-CONFLICTS.md`.

## Agent working agreement
- source: AGENTS.md
- Read order before changing behaviour: "`SPEC.md` (the contract), `DECISIONS.md` (why), `STATUS.md` (what is verified and what is blocked)". `.planning/codebase/` holds a generated map of the code.
- Rules 1-8 are summarized in `intel/constraints.md` ("Agent operating rules"). Rule 1: "Flag conflicts first." Rule 7: "Do not tune scores or add features until freshness and delivery are proven (see `STATUS.md`)." Rule 8: run `python -m unittest discover -s tests` before finishing; keep tests offline.

## Code layout
- source: AGENTS.md "Layout"; DECISIONS.md D-02
- `hunter.py` entry/orchestration; `boards.py` (identity, adapters, registry), `inventory.py`, `freshness.py`, `ledger.py`, `eligibility.py`, `state.py`, `pools.py`, `pipeline.py` core; `reporting.py` (pure summary) and `dashboard.py` (render and publish, read-only toward operational state); `tests/` offline; `legacy/` archived earlier version (reference only). CONCERNS.md (2026-10-24) puts `hunter.py` at 1,981 lines.

## Current status (what is verified, shipped)
- source: STATUS.md "Pilot week 1 result", "Blockers"
- v1 is shipped and the seven-day pilot (2026-10-15 01:47 to 2026-10-22 01:47 UTC) passed. Quoted result: "168 of 168 hourly intervals had a successful poll; no gap over 90 min; 207 runs, all `ok`; 0.31% of 103,500 board polls failed"; "20 alerts, 20 unique jobs, 0 duplicates, 0 failed sends, 1 labelled late".
- Funnel (one cohort): 19,380 new postings -> 472 relevant -> 212 rejected after reading -> 260 scored -> 47 kept -> 20 alerted (about 3 a day). Coverage: 500 monitored (all exploration trials), 849 relevant boards waiting, 33% of known relevant boards.
- "Blockers: None." The earlier credential and "never ran on GitHub" blockers were superseded by the 2026-10-15 deployment. Owner setup still open: a second, external trigger for the watchdog.

## Post-pilot state (2026-10-23 to 2026-10-24)
- source: STATUS.md "Changes after the pilot", "Next milestone" item 5; PILOT_LOG.md timeline
- 2026-10-23 20:52 UTC (76726a6): graduation floor (D-45) and tracker header refusal (D-46); user set `Max_Active_Boards` 700 and `Rebalance_Mode` on in Settings. 2026-10-23 21:21 UTC: title and location Settings broadened (Settings only). 2026-10-24 07:42 UTC (b14a1a0): early release and 5,000 re-check budget (D-47).
- Live follow-up quoted: run 40076316737 released 220 ended trials; monitored 700 -> 480, then refilled at 50 a run to 679 of 700; relevant-board coverage 41% -> 53%; inventory run 40078741166 re-checked 5,000 boards in 1,121 s (176 gained relevant jobs, 67 lost).
- Next weekly rebalance due about 2026-10-29 01:00 UTC. STATUS closes: "No score tuning or new features until these are read (AGENTS.md rule 7)."

## Verification map (live vs mocked)
- source: STATUS.md (sections "Verification: mocked vs live", "Operational dashboard (D-40)", "Pilot reliability and reporting fixes", "Search provider migrated to Tavily (D-36)")
- STATUS keeps older per-change tables; some rows say "not verified" or "blocked" because they were written before the 2026-10-15 deployment. The newest sections win (see conflicts INFO). Still mocked-only per STATUS: transient-failure retry against a real outage, Groq 429 fallback and `model_not_found`, watchdog Telegram delivery and real outage, weekly rebalance at 700 boards. Test count history in STATUS: 516, 520, 525 offline tests (CONCERNS.md counts 527 test functions).

## Known gaps and risks (candidate v2 scope)
- source: STATUS.md "Known gaps / risks"; .planning/codebase/CONCERNS.md
- STATUS: "Initial operating choices are unproven" (D-30); search "cannot promise full coverage"; validation backlog; waiting board relevance is a snapshot re-checked on the validation cycle; baseline jobs never scored; Events grows with every observed ID; alerts at-least-once.
- CONCERNS.md priority summary (12 items): 1 alert marked `alerted` with no channel; 2 non-HTTP alert exceptions retry forever; 3 Events ledger growth with D-43 unbuilt; 4 SmartRecruiters against `robots.txt` (D-38); 5 unproven operating choices acting live; 6 `hunter.py` monolith; 7 Sheet lease not atomic; 8 validation backlog; 9 resume text sent to Groq with no recorded decision; 10 Telegram text truncation; 11 external triggers outside the repo; 12 coverage limits by design. CONCERNS.md marks items "verified in code" or "from docs"; the orchestrator check there says item 1 matters only for a deployment without any channel (production has Telegram).
- These map to the `REQ-v2-*` entries in `intel/requirements.md`.

## Deployment runbook
- source: DEPLOY.md
- Private GitHub repository, Google Sheet with service account (Editor), Telegram bot and chat id, repository secrets `TAVILY_API_KEY`, `GROQ_API_KEY`, `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_SHEET_ID`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (`ALERT_WEBHOOK_URL` optional, leave unset); values never pasted into chat or commits. Steps: configuration check via `pilot_report`, `delivery_test`, two manual runs, schedule proof by `trigger=schedule` rows, seven-day pilot protocol (section 9), Watchdog section.
- DEPLOY.md is partly historical: its opening line says "Nothing here has been run on GitHub yet: this repository has no remote", and section 9 says to keep `Rebalance_Mode=report` for seven days. STATUS.md and PILOT_LOG.md (higher precedence) record the deployment, pilot completion and the post-pilot Settings changes.
- Watchdog second-trigger recommendation (separate scheduler job calling the dispatch API for `watchdog.yml` every 10-15 minutes, token in the scheduler's secret store) is the owner's to create.

## Pilot log and measurement corrections
- source: PILOT_LOG.md
- Timeline of deployments with the periods each affects (first production run 2026-10-15 01:47 UTC; SmartRecruiters unparked 02:12; per-run diagnostics; dashboard 2026-10-16; watchdog and pilot-report corrections 2026-10-17 19:30; tracker by header name 2026-10-19 02:45; pilot end 2026-10-22 01:47; post-pilot changes above). "Commits are deployed by pushing to `main`."
- Material corrections (reporting only): pilot-report denominator, coverage populations (34.7% headline vs 37.5% counting every monitored board), detection latency definition, fixture exclusion, reconciled headline counts. Two data-placement incidents (tracker column move 2026-10-18; header cleared 2026-10-22 to 2026-10-23) with their affected periods.
- Rule for contributors: "Update this file in the same change as any deployment that could affect a measurement."

## User-facing guide
- source: README.md
- Describes what the app watches, freshness labels (Verified fresh, New on board (age unverified), Recent, Age unverified), board sources (Tavily rotation, manual seeds, two public inventories about 21,900 boards), Settings rows and defaults, Job Tracker columns, Dashboard tab, scoring bands (80-100 strong, 65-79 stretch, 26-64 partial, 0-25 hard no), troubleshooting, local-run commands (`--dry-run`, `--url`, `--discover`, `--backfill`, `--search-usage`, `--import-inventory`, `--validate`, `--rebalance-report`, `--inventory-report`, `--pilot-report`, `--dashboard`, `--delivery-test`).
- README is the lowest-precedence DOC and lags in places (first-run step still says "search Google"; watchdog "planned, not built"; Telegram "optional"; unconditional "detected within one successful hourly poll"). See conflicts INFO.

## Pre-existing GSD planning files (merge mode)
- source: .planning/PROJECT.md, .planning/ROADMAP.md, .planning/STATE.md
- PROJECT.md: one-paragraph product statement and four constraints (freshness is the product; never read or commit secrets; keep tests offline; no score tuning or extra features); it states that SPEC/DECISIONS/STATUS/AGENTS "win over anything here". Consistent with the ingested docs.
- ROADMAP.md: stale minimal bootstrap, one phase "Board slot allocation (in progress)", describes work as D-01..D-22. STATE.md: last updated 2026-10-14, quick task 261014-olj completed (commit f5d9fda), current focus "Board slot allocation". Treated as superseded history, not a locked source: the work is described by D-23..D-30 and everything since (D-31..D-47) is absent from both. ROADMAP.md says "in progress" while STATE.md says completed; STATE.md is the later record.
- `.planning/REQUIREMENTS.md` does not exist. No CONTEXT.md files exist, so there are no existing locked decisions to check ingested decisions against.

## Inputs not ingested
- source: ingest-manifest.yaml
- `NOTICE.md` (inventory attribution, referenced by D-11) and `CLAUDE.md` (imports AGENTS.md) are not in the manifest and were not ingested. `legacy/` is archived reference only (AGENTS.md).
