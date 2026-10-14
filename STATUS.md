# STATUS

Last updated 2026-10-14. Read `SPEC.md` (contract) and `DECISIONS.md` (why) first.

## State

The smallest complete path is implemented: **board polling -> new-ID detection -> freshness classification -> filters/scoring -> Google Sheet -> Telegram**, with Serper-driven board discovery growing a persistent registry. The previous search-first pipeline was refactored in place (see D-01). Baseline commit `affaaa4` preserves the old behavior.

## Verification: mocked vs live

| Area | Result | How |
|---|---|---|
| Freshness classes (time/day precision, baseline, gaps, future dates) | pass | **Mocked**: unit tests (`tests/test_core.py`) |
| Identity: GH host variants, embed `for`/`token`, `gh_jid`, SR slugs collapse to one key | pass | **Mocked** tests + checked on live URLs |
| Baselining a new board; no alert on backlog | pass | **Mocked** scenario; **Live**: 335 IDs on 5 real boards recorded as baseline, 0 alerts |
| Second poll is idempotent (no new IDs, no re-eval) | pass | **Live**: same boards polled twice; **Mocked** |
| List adapters: Greenhouse, Lever, Ashby, Workable, SmartRecruiters | pass | **Live** public endpoints (7 boards: discovery + first poll 17.0 s, poll-only 4.4 s; 7 boards listed concurrently in 1.5 s) |
| Serper discovery + 3-day window payload | pass | **Live** Serper: 7 and 17 boards found in two runs (varies) |
| Failure cases: transient scoring (no attempt used), bounded permanent failures, alert outage, rejected alert (4xx) bounded, late alert abandoned, tracker write failure, events write failure after row append (no duplicate row), board outage gap, suspicious empty listing, ID flood re-baseline, board auto-disable, update/republication logging, dry-run writes/sends nothing | pass | **Mocked** (82 offline tests) |
| `main()` wiring: seed, two polls, runs log, exit codes | pass | **Live** ATS, local CSV state, no credentials |
| Groq invalid key -> fatal, clear error | pass | **Live** Groq API (401 with a dummy key) |
| Groq success path (JSON scoring, 429 fallback) | not verified live | **Mocked** only: no Groq key available |
| Google Sheets (tab creation, hidden tabs, append-only tracker, atomic Boards rewrite, dropdown) | not verified live | **Mocked** only (fake gspread): no service account / Sheet ID available |
| Telegram delivery and message format | not verified live | **Mocked** only (captured request): no bot token available |
| GitHub Actions hourly schedule, delays, skipped runs | not verified | Workflow YAML parses; never run on GitHub |

## Findings from live runs

- Coverage is small and uneven: one discovery pass found 7 boards, another 17. Discovery quality depends on Serper results; there is no curated list. Growth over days is unmeasured.
- Aggregator boards exist (one Lever board lists 3,599 jobs): they inflate baseline writes and pass through the same filters.
- Workable lists the same shortcode multiple times (once per location); keys collapse these.
- Workable has day-precision dates only; a Workable job can be `verified_fresh` only via the board-gap rule.
- In earlier unfiltered search, ~29 of 30 hits were stale: direct polling is what makes freshness measurable.

## Known gaps / risks

- Alerts are at-least-once; a crash between sending and recording could duplicate one.
- `Events` grows with every observed ID (baselines included); revisit pruning near ~200k rows.
- Existing sheets created before this refactor will not gain the new `Settings` rows (defaults apply) and have the old 10-column tracker header; a fresh Sheet is recommended.
- `.env.example` cannot be written in this environment (permission rule); the template is in the README.
- No latency metric from real data yet: `Runs.Max_Alert_Lag_Min` will fill once real alerts are sent.

## Blockers

Credentials for a live end-to-end run: `GROQ_API_KEY`, `GOOGLE_SHEET_ID` + `GOOGLE_SERVICE_ACCOUNT_JSON` (Sheet shared with the service account), `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`.

## Next milestone

One real end-to-end run with credentials: bootstrap a blank Sheet, discover and baseline boards, score at least one job with Groq, append a tracker row, and deliver one Telegram message; then watch 48 hours of hourly runs and read the `Runs` tab for actual poll gaps and alert lag before tuning anything.
