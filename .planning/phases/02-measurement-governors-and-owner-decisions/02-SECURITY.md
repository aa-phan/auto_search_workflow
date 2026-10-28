---
phase: "02"
slug: "measurement-governors-and-owner-decisions"
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: "2026-10-28"
---

# Phase 02 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

Register authored at plan time (`<threat_model>` in 02-01 .. 02-09 PLAN.md). ASVS level 1: grep-depth evidence, no auditor pass (short-circuit rule). Evidence is offline code and tests (`.venv/bin/python -m unittest discover -s tests`: 629 tests OK on 2026-10-28) plus the recorded procedure in the plan SUMMARYs; nothing in this audit hit a live service.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| repository → public internet | Committed documents and `.planning/` are world-readable | Decision IDs, setting names, counts (public) |
| Telegram / webhook API → pipeline | HTTP exception text may embed the request URL with the bot token | Bot token (secret) |
| Events ledger → Dashboard / public Actions log | Stored failure messages and log lines are shown | Failure text (may carry secrets if unredacted) |
| Job posting text → Telegram HTML | Untrusted titles, locations, verdicts rendered with parse_mode HTML | Untrusted text |
| Groq API → GroqClient | `usage`, `x-ratelimit-*` headers, 429 bodies | Untrusted numbers / headers |
| Discovery / Runs tabs → run_cycle, reporting | Hand-editable `groq_budget` / `groq_limits` JSON and counters | Untrusted JSON |
| Runs tab / Actions log → public | Runs.Notes, pilot report and logs | Counts, model ids, header values |
| GitHub Actions runner → run lifetime | Job killed at 25 minutes | Unsaved run state |
| ATS / Groq / Telegram latency → pipeline | Slow answers consume the run's time | Time budget |
| Job Tracker (user-edited) → reporting | Cells may be edited or deleted by hand | Untrusted cells |
| local repository → public GitHub `main` | Push deploys and publishes the diff | Code, docs |
| agent → production workflows | `gh workflow run` can write runs or send Telegram | Production actions |
| owner's Groq console → chat → repository | Owner-typed figures end in public docs | Plan figures (no keys) |
| resume text → Groq | Personal data sent on every scoring call | Resume text (personal) |
| poller → SmartRecruiters API | robots.txt `Disallow: /` for generic agents | Provider policy |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-02-01 | Information disclosure | DECISIONS / DEPLOY / STATUS edits | medium | mitigate | Edits name keys, decision IDs, counts only; no forbidden file opened or staged (02-01-SUMMARY Threat Flags) | closed |
| T-02-02 | Repudiation | D-48 decision table | medium | mitigate | Each row cites P2-xx source and date; undecided rows labelled pending (DECISIONS.md D-48) | closed |
| T-02-03 | Information disclosure | stage 4 failure_events / log.warning | high | mitigate | `redact(...)` before failure events and logs; `test_alert_failure_text_never_contains_the_bot_token` | closed |
| T-02-04 | Repudiation | `alerted` event | high | mitigate | `alerted` written only when `send_alert` returns True (tracer test, 02-02-SUMMARY) | closed |
| T-02-05 | Denial of service | alert-channel outage over 5 runs | medium | accept | Owner decision P2-18, D-49 | closed |
| T-02-06 | Tampering | `send_alert` HTML | medium | mitigate | `html.escape` after `_cap` on every free-text field; final HTML not sliced (test) | closed |
| T-02-07 | Tampering | manual `--url` / `--delivery-test` on the same key | low | accept | Unbudgeted, persist nothing; 15% headroom (D-50) | closed |
| T-02-08 | Tampering | usage / header / persisted JSON parsing | medium | mitigate | Tolerant `_int` and `GroqBudget.load`; `test_non_numeric_usage_is_ignored_not_raised`, `test_budget_tolerates_blank_invalid_and_foreign_json` | closed |
| T-02-09 | Denial of service | daily-limit 429 loop | medium | mitigate | `_is_daily_limit` marks model spent without sleeping (tests) | closed |
| T-02-10 | Information disclosure | `Groq_Limits` / logs | high | mitigate | Only listed `x-ratelimit-*` response values stored; test asserts key absent from `limits_json()` | closed |
| T-02-11 | Denial of service | run_cycle exceeding 25-minute timeout | high | mitigate | Process-anchored 15 / 20 / 22 minute cutoffs and Groq client deadline (fake-clock and late-start tests; `skipped_deadline`) | closed |
| T-02-12 | Tampering | board state after a cut | medium | mitigate | `skipped_deadline` distinct from 429 `skipped`; skipped boards never reach `apply_poll_result` (keeps-state test) | closed |
| T-02-13 | Information disclosure | Needs-attention detail / dry-run text | low | mitigate | Job keys and stamps only; Dashboard in owner's private Sheet | closed |
| T-02-14 | Tampering | user-edited tracker cells → summary | medium | mitigate | Tracker text only counted/parsed, never copied; `_safe_cell` and one-batch publish | closed |
| T-02-15 | Repudiation | presenting unknown age as fresh | high | mitigate | `age_bucket` returns `unknown` for day precision, missing, future and unmatched; cohort from stored label / ledger class (tests) | closed |
| T-02-16 | Information disclosure | `_limits_lines` in public log | medium | mitigate | Counts, model ids, stored header values only; test asserts no `Bearer` / `Authorization` | closed |
| T-02-17 | Tampering | malformed `groq_budget` / `groq_limits` JSON | low | mitigate | Tolerant parsing; unparseable renders `n/a` (test) | closed |
| T-02-18 | Elevation of privilege | `git push origin main` (02-07) | high | mitigate | Pushed only after owner's "deploy-with-delivery-test" checkpoint (02-07-SUMMARY) | closed |
| T-02-19 | Information disclosure | outgoing diff (02-07) | high | mitigate | Secret-pattern scan of `git diff origin/main..HEAD` (0 real matches) and forbidden-file check before push (02-07-SUMMARY) | closed |
| T-02-20 | Spoofing | `delivery_test` dispatch | medium | mitigate | Dispatched only on explicit owner choice; sends to configured TELEGRAM_CHAT_ID only (02-07-SUMMARY; UAT test 4) | closed |
| T-02-21 | Information disclosure | log excerpts in STATUS.md | medium | mitigate | Only run ids, counts, job keys, setting names; full-log secret scan 0 matches (02-07-SUMMARY) | closed |
| T-02-22 | Information disclosure | owner's Groq figures reply (02-08) | high | mitigate | Figures only, no key or screenshot copied (02-08-SUMMARY) | closed |
| T-02-23 | Information disclosure | resume text sent to Groq | medium | transfer | Owner decision D-53 (D-48 row 11); zero data retention not enabled, recorded | closed |
| T-02-24 | Tampering | SmartRecruiters rows rewritten to `deferred` | medium | mitigate | Not applicable: 02-09 superseded by D-54, no parking deployed, no rows rewritten | closed |
| T-02-25 | Repudiation | provider compliance (robots.txt) | medium | mitigate → accept | Plan mitigation (remove override) reversed by owner decision D-54; override kept with 1.0 s spacing and parked code default (`test_smartrecruiters_override_is_explicit_in_both_workflows_slowed_and_announced`). See AR-02-03 | closed |
| T-02-26 | Elevation of privilege | push to main (02-09) | high | mitigate | Not applicable: 02-09 superseded, no push made by that plan | closed |
| T-02-SC | Tampering | npm/pip/cargo installs | low | accept | No package installed in any plan | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-02-01 | T-02-05 | Alert sends failing without an HTTP response are bounded at 5; a 5-run channel outage abandons pending alerts with a recorded reason (P2-18, D-49) | Owner | 2026-10-26 |
| AR-02-02 | T-02-07 | Manual `--url` / `--delivery-test` calls are unbudgeted; 15% headroom absorbs them (D-50) | Owner | 2026-10-26 |
| AR-02-03 | T-02-25 | SmartRecruiters stays polled despite robots.txt `Disallow: /`; risks as in D-38, reverse at once if SmartRecruiters objects (D-54) | Owner | 2026-10-28 |
| AR-02-04 | T-02-23 | Resume text sent to Groq on every scoring call, zero data retention not enabled ("resume to Groq: ok", D-53) | Owner | 2026-10-28 |
| AR-02-05 | T-02-SC | No package installed in this phase | Plan authors | 2026-10-26 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-10-28 | 27 | 27 | 0 | /gsd-secure-phase 02 (orchestrator, ASVS L1 short-circuit, no auditor) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-10-28
