---
phase: 03
review: 03-REVIEW.md
titles: json
findings:
  - id: WR-11
    severity: warning
    disposition: skipped
    title: "An Identity stem no job key can produce holds keys that match nothing, is not flagged, raises the mark, and deleting it is a permanent `identity_shrunk`"
  - id: WR-12
    severity: warning
    disposition: fixed
    title: "The documented hand edit of the `storage` key has no safe-edit protocol: a syntax slip flips a compact system to dual and erases its records, a run in progress discards the edit, and nothing checks the result"
  - id: WR-13
    severity: warning
    disposition: fixed
    title: "STATUS states the storage-report result without its scope, and two older statements it contradicts were left standing"
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
    title: "The tests do not pin the claim that matters most for the fix, \"the fold stays held back\""
  - id: IN-11
    severity: info
    disposition: open
    title: "The figure keeps the name \"entries\" and the Discovery key cannot be renamed lightly"
  - id: IN-12
    severity: info
    disposition: open
    title: "The WR-10 fix removes an incidental dual-mode detection of a bare entry, and dual mode has no `identity_entry` check"
  - id: IN-13
    severity: info
    disposition: fixed
    title: "The runbook documents only half of the repair and only the mild WR-11 case"
  - id: IN-14
    severity: info
    disposition: fixed
    title: "STATUS labels an inference as a log reading and relies on notes that the public log does not carry"
  - id: IN-15
    severity: info
    disposition: open
    title: "DEPLOY.md still carries statements that are false after the deploy history (pre-existing, outside the diff)"
  - id: IN-10
    severity: info
    disposition: fixed
    title: "The documented repair path has no tooling and the mark can be stuck high by a transient over-read"
  - id: WR-10
    severity: warning
    disposition: fixed
    title: "An entry with no posting ID counts as a held key, and the only repair for it, deletion, is a permanent `identity_shrunk`"
  - id: WR-09
    severity: warning
    disposition: fixed
    title: "The count excludes malformed entries that the dedupe still uses, so deleting one loses a held posting ID with no `identity_shrunk`"
  - id: WR-08
    severity: warning
    disposition: fixed
    title: "A malformed Identity entry still raises the mark, so removing it is a permanent `identity_shrunk` (WR-07 only fixed duplicates)"
  - id: WR-07
    severity: warning
    disposition: fixed
    title: "The high-water mark counts duplicate Identity entries, so repairing `identity_duplicate` becomes a permanent `identity_shrunk`"
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
open: 16
total: 28
recorded: 2026-11-17T09:12:46.256Z
---

# Phase 03: Code Review Disposition

| Finding | Severity | Disposition | Source |
|---------|----------|-------------|--------|
| WR-11 | warning | skipped | accepted by the owner 2026-11-17 (UAT 8, option b); known limit in STATUS.md, clearing steps in DEPLOY.md |
| WR-12 | warning | fixed | docs fix 0a8a972 (DEPLOY.md runbook / STATUS.md wording), 2026-11-17 |
| WR-13 | warning | fixed | docs fix 0a8a972 (DEPLOY.md runbook / STATUS.md wording), 2026-11-17 |
| IN-01 | info | open | - |
| IN-02 | info | open | - |
| IN-03 | info | open | - |
| IN-04 | info | open | - |
| IN-05 | info | open | - |
| IN-06 | info | open | - |
| IN-07 | info | open | - |
| IN-08 | info | open | - |
| IN-09 | info | open | - |
| IN-11 | info | open | - |
| IN-12 | info | open | - |
| IN-13 | info | fixed | docs fix 0a8a972 (DEPLOY.md runbook / STATUS.md wording), 2026-11-17 |
| IN-14 | info | fixed | docs fix 0a8a972 (DEPLOY.md runbook / STATUS.md wording), 2026-11-17 |
| IN-15 | info | open | - |
| IN-10 | info | fixed | runbook note "Clearing a stuck `identity_shrunk`" added to DEPLOY.md 2026-11-17 (no tooling added) (not in the current review) |
| WR-10 | warning | fixed | plan 03-10 (389789a, de57002); resolved per 03-REVIEW.md re-review 98c19d8 (not in the current review) |
| WR-09 | warning | fixed | 03-REVIEW-FIX.md (not in the current review) |
| WR-08 | warning | fixed | 03-REVIEW-FIX.md (not in the current review) |
| WR-07 | warning | fixed | 03-REVIEW-FIX.md (not in the current review) |
| WR-06 | warning | fixed | 03-REVIEW-FIX.md (not in the current review) |
| WR-01 | warning | fixed | 03-REVIEW-FIX.md (not in the current review) |
| WR-02 | warning | fixed | 03-REVIEW-FIX.md (not in the current review) |
| WR-03 | warning | fixed | 03-REVIEW-FIX.md (not in the current review) |
| WR-04 | warning | fixed | 03-REVIEW-FIX.md (not in the current review) |
| WR-05 | warning | fixed | 03-REVIEW-FIX.md (not in the current review) |

Dispositions: `open` (recorded, not yet triaged), `fixed`, `skipped`, `deferred`.
Set `deferred` by hand and put the reason in the Source cell; both are preserved. A `|` in the reason is kept as prose and escaped on the next run.
Re-running the gate keeps every row it can. A row the current review no longer reports is kept and its Source cell flagged, so a finding does not leave this record silently. ONE exception: when a finding id is REUSED by a different finding, the earlier decision cannot keep a row — the id is taken — and it is dropped. A RECORDED decision (anything but `open`) is named on the console when that happens; a row still at `open` is replaced silently, because `open` records no decision to lose.
