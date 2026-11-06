---
phase: 03
review: 03-REVIEW.md
titles: json
findings:
  - id: WR-01
    severity: warning
    disposition: open
    title: "A fold that deleted rows but did not record `first_day` leaves the restore guard open (and under-counts `rows_total`)"
  - id: WR-02
    severity: warning
    disposition: open
    title: "The compact integrity check cannot detect Identity loss, and `ensure()` quietly recreates a deleted Identity tab"
  - id: WR-03
    severity: warning
    disposition: open
    title: "A Tally write failure in compact mode becomes a permanent undercount (AGENTS rule 4)"
  - id: WR-04
    severity: warning
    disposition: open
    title: "`write_identity` rewrites rows from its in-memory cache without checking the sheet"
  - id: WR-05
    severity: warning
    disposition: open
    title: "The fold does not consult the integrity check the same run just ran"
  - id: IN-01
    severity: info
    disposition: open
    title: "`parity.py` docstring is wrong about its imports"
  - id: IN-02
    severity: info
    disposition: open
    title: "Removing `Events_Legacy` silently flips a compact system back to dual writing"
  - id: IN-03
    severity: info
    disposition: open
    title: "The workflow lets `storage_cutover` and `storage_restore` run in one job"
  - id: IN-04
    severity: info
    disposition: open
    title: "The cutover checksum covers only `key|time|event`"
  - id: IN-05
    severity: info
    disposition: open
    title: "Dead variable and unused imports"
  - id: IN-06
    severity: info
    disposition: open
    title: "Read-only commands read three tabs sequentially without the lease"
open: 11
total: 11
recorded: 2026-11-06T22:18:51.756Z
---

# Phase 03: Code Review Disposition

| Finding | Severity | Disposition | Source |
|---------|----------|-------------|--------|
| WR-01 | warning | open | - |
| WR-02 | warning | open | - |
| WR-03 | warning | open | - |
| WR-04 | warning | open | - |
| WR-05 | warning | open | - |
| IN-01 | info | open | - |
| IN-02 | info | open | - |
| IN-03 | info | open | - |
| IN-04 | info | open | - |
| IN-05 | info | open | - |
| IN-06 | info | open | - |

Dispositions: `open` (recorded, not yet triaged), `fixed`, `skipped`, `deferred`.
Set `deferred` by hand and put the reason in the Source cell; both are preserved. A `|` in the reason is kept as prose and escaped on the next run.
Re-running the gate keeps every row it can. A row the current review no longer reports is kept and its Source cell flagged, so a finding does not leave this record silently. ONE exception: when a finding id is REUSED by a different finding, the earlier decision cannot keep a row — the id is taken — and it is dropped. A RECORDED decision (anything but `open`) is named on the console when that happens; a row still at `open` is replaced silently, because `open` records no decision to lose.
