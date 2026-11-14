---
phase: 03
review: 03-REVIEW.md
titles: json
findings:
  - id: WR-07
    severity: warning
    disposition: open
    title: "The high-water mark counts duplicate Identity entries, so repairing `identity_duplicate` becomes a permanent `identity_shrunk`"
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
  - id: IN-07
    severity: info
    disposition: open
    title: "`first_day` is dated by the fold that ends, not by the one that started"
  - id: IN-08
    severity: info
    disposition: open
    title: "The Tally carry holds zero-total rows and drops the newest row when full"
  - id: IN-09
    severity: info
    disposition: open
    title: "The new tests do not pin the claim that matters most for the fix, \"the fold stays held back\""
  - id: IN-10
    severity: info
    disposition: open
    title: "The documented repair path has no tooling and the mark can be stuck high by a transient over-read"
  - id: WR-06
    severity: warning
    disposition: fixed
    title: "`identity_shrunk` is reported once, then the lowered count becomes the new reference"
  - id: WR-01
    severity: warning
    disposition: fixed
    title: "A fold that deleted rows but did not record `first_day` leaves the restore guard open"
  - id: WR-02
    severity: warning
    disposition: fixed
    title: "The compact integrity check cannot detect Identity loss, and `ensure()` quietly recreates a deleted Identity tab"
  - id: WR-03
    severity: warning
    disposition: fixed
    title: "A Tally write failure in compact mode becomes a permanent undercount (AGENTS rule 4)"
  - id: WR-04
    severity: warning
    disposition: fixed
    title: "`write_identity` rewrites rows from its in-memory cache without checking the sheet"
  - id: WR-05
    severity: warning
    disposition: fixed
    title: "The fold does not consult the integrity check the same run just ran"
open: 11
total: 17
recorded: 2026-11-14T22:46:27.098Z
---

# Phase 03: Code Review Disposition

| Finding | Severity | Disposition | Source |
|---------|----------|-------------|--------|
| WR-07 | warning | open | - |
| IN-01 | info | open | - |
| IN-02 | info | open | - |
| IN-03 | info | open | - |
| IN-04 | info | open | - |
| IN-05 | info | open | - |
| IN-06 | info | open | - |
| IN-07 | info | open | - |
| IN-08 | info | open | - |
| IN-09 | info | open | - |
| IN-10 | info | open | - |
| WR-06 | warning | fixed | 03-REVIEW-FIX.md (not in the current review) |
| WR-01 | warning | fixed | 03-REVIEW-FIX.md (not in the current review) |
| WR-02 | warning | fixed | 03-REVIEW-FIX.md (not in the current review) |
| WR-03 | warning | fixed | 03-REVIEW-FIX.md (not in the current review) |
| WR-04 | warning | fixed | 03-REVIEW-FIX.md (not in the current review) |
| WR-05 | warning | fixed | 03-REVIEW-FIX.md (not in the current review) |

Dispositions: `open` (recorded, not yet triaged), `fixed`, `skipped`, `deferred`.
Set `deferred` by hand and put the reason in the Source cell; both are preserved. A `|` in the reason is kept as prose and escaped on the next run.
Re-running the gate keeps every row it can. A row the current review no longer reports is kept and its Source cell flagged, so a finding does not leave this record silently. ONE exception: when a finding id is REUSED by a different finding, the earlier decision cannot keep a row — the id is taken — and it is dropped. A RECORDED decision (anything but `open`) is named on the console when that happens; a row still at `open` is replaced silently, because `open` records no decision to lose.
