---
phase: 02
review: 02-REVIEW.md
titles: json
findings:
  - id: WR-01
    severity: warning
    disposition: fixed
    title: "Persisted \"spent per Groq\" flag outlasts Groq's rolling window, so a model can stay locked for up to a day"
  - id: WR-02
    severity: warning
    disposition: fixed
    title: "Bot token can reach the log through the uncaught exception in `--delivery-test`; the redaction in D-49 does not cover this path"
  - id: WR-03
    severity: warning
    disposition: fixed
    title: "A mistyped or unparseable budget silently becomes the default while `Runs.Notes` claims it came from the Settings tab"
  - id: WR-04
    severity: warning
    disposition: fixed
    title: "Groq `json_validate_failed` response body is logged (240 characters) in a now-public repository"
  - id: IN-01
    severity: info
    disposition: open
    title: "Stale \"15% headroom\" wording after the D-53 amendment"
  - id: IN-02
    severity: info
    disposition: open
    title: "SPEC layout claim is stronger than the evidence for the new dashboard content"
  - id: IN-03
    severity: info
    disposition: open
    title: "Alerted events always carry `channel: \"telegram\"`, including webhook-only deliveries"
  - id: IN-04
    severity: info
    disposition: open
    title: "Startup reads the Settings tab three times"
  - id: IN-05
    severity: info
    disposition: open
    title: "Alert cutoff is a constant with no ordering check against the configurable eval cutoff"
  - id: IN-06
    severity: info
    disposition: open
    title: "Stored-URL fallback in `tracker_join` can pair two distinct ledger jobs with the same tracker row"
open: 6
total: 10
recorded: 2026-10-28T22:15:07.293Z
---

# Phase 02: Code Review Disposition

| Finding | Severity | Disposition | Source |
|---------|----------|-------------|--------|
| WR-01 | warning | fixed | 02-REVIEW-FIX.md |
| WR-02 | warning | fixed | 02-REVIEW-FIX.md |
| WR-03 | warning | fixed | 02-REVIEW-FIX.md |
| WR-04 | warning | fixed | 02-REVIEW-FIX.md |
| IN-01 | info | open | - |
| IN-02 | info | open | - |
| IN-03 | info | open | - |
| IN-04 | info | open | - |
| IN-05 | info | open | - |
| IN-06 | info | open | - |

Dispositions: `open` (recorded, not yet triaged), `fixed`, `skipped`, `deferred`.
Set `deferred` by hand and put the reason in the Source cell; both are preserved. A `|` in the reason is kept as prose and escaped on the next run.
Re-running the gate keeps every row it can. A row the current review no longer reports is kept and its Source cell flagged, so a finding does not leave this record silently. ONE exception: when a finding id is REUSED by a different finding, the earlier decision cannot keep a row — the id is taken — and it is dropped. A RECORDED decision (anything but `open`) is named on the console when that happens; a row still at `open` is replaced silently, because `open` records no decision to lose.
