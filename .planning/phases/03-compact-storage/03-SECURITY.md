---
phase: "3"
slug: "compact-storage"
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: "2026-11-06"
---

# Phase 3 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

The register was authored at plan time in the nine `<threat_model>` blocks (03-01..03-09-PLAN.md): 37 distinct IDs plus the T-03-SC row in each plan. Verified at ASVS L1 (read/grep plus the cited offline tests, which are **mocked**). Operational threats (plans 03-05, 03-08, 03-09) are closed on evidence recorded in STATUS.md, PILOT_LOG.md and the SUMMARYs; the live run ids there come from public Actions logs.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Program -> Identity / Tally tabs | Dedupe identity moves from full Events rows to compact IDs and counts | Posting IDs, counts (no job text) |
| Hand edits -> Identity / Events_Legacy | A removed ID can make an old job look new | Warning-only protected tabs |
| Discovery `storage` key -> clock and cutover gate | A hand-edited or truncated key must not unlock the cutover | Mode, seed time, parity days |
| Workflow inputs -> `run:` lines | `storage_parity`, `storage_report`, `storage_cutover`, `storage_restore` | Booleans to fixed commands |
| Owner decision -> production cutover and fold | One-way once the first fold runs | Live ledger rows |
| Public Actions logs -> STATUS.md / PILOT_LOG.md | Log text copied into public documents | Counts, run ids, setting names only |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-03-01 | Tampering | Identity tab hand edit | high | mitigate | Whole-sheet warning-only protection in `state.ensure()` (`state.py:259-265`, `:330-334`); parity layer 1 flags missing/extra IDs (`parity.py:95-97`); `test_compact.py:331`. Live prompt: owner check | closed |
| T-03-02 | Denial of service | Identity cell and request size | medium | mitigate | 40,000-char cells, 1M-char requests (`compact.py:26-27`, `:216-250`; `state.py:587-626`); `test_compact.py:61`, `:251`, `:300` | closed |
| T-03-03 | Tampering | Identity key for case-sensitive ATS | high | mitigate | `compact.stem_and_id` works on the job key (`compact.py:50-57`); `test_compact.py:111`, `:123`, `:128` | closed |
| T-03-04 | Denial of service | Interrupted baseline or seed write | high | mitigate | Events -> Identity -> Tally -> Boards order, compact-mode Identity failure re-raised before `save_boards` (`pipeline.py:336-366`); marker on highest chunk; `InterruptedBaselineTests` | closed |
| T-03-05 | Information disclosure | Job text in Identity, Tally, notes | medium | mitigate | Exception type only in notes (`pipeline.py:356`, `:363`); `test_no_job_text_reaches_identity_or_tally` | closed |
| T-03-06 | Denial of service | `ensure()` recreating Events | high | mitigate | Refuses when Events is missing but Events_Legacy / Events_New exist (`state.py:312-314`, `:703-707`); `test_compact.py:375`, `:379` | closed |
| T-03-07 | Tampering | `storage` key edited or truncated | medium | mitigate | Tolerant `StorageState.load`, pruning and caps (`compact.py:656-705`); `test_storage_parity.py:395-418` | closed |
| T-03-08 | Repudiation | Crashed or skipped check reported clean | medium | mitigate | Exception becomes counted `check_failed`; deadline skip not recorded; 12 runs/day (`pipeline.py:235-239`, `:888-889`; `compact.py:12`); `test_storage_parity.py:309`, `:376`, `:387`, `:487`, `:505` | closed |
| T-03-09 | Tampering | Identity / Tally edited so parity passes | high | mitigate | Layers 1-2 compare both directions, kind, stem, count, marker, Tally recount (`parity.py:82-149`); detection still replays Events in dual mode; `test_storage_parity.py:121-152`, `:459` | closed |
| T-03-10 | Information disclosure | Job text in storage key, notes, log | medium | mitigate | `Diff.text` refs and numbers only (`parity.py:42-51`); counts-only logging; `test_storage_parity.py:194`, `:517`, `:917` | closed |
| T-03-11 | Denial of service | Check time pushes run past timeout | medium | mitigate | Check after alerts, skipped at 22 min (`pipeline.py:55`, `:885-891`); `test_storage_parity.py:505` | closed |
| T-03-12 | Tampering | Double counting misreports Dashboard | medium | mitigate | One counting path (`reporting.py:298-310`, `:458-460`); layer-4 figure comparison (`parity.py:255-284`); `CompactParityTests` | closed |
| T-03-13 | Tampering | Hand-added tracker row flaps the clock | low | mitigate | Declared `tracker_identity_job` (`parity.py:229-252`); `test_storage_parity.py:631` | closed |
| T-03-14 | Information disclosure | Figure differences copy report strings | medium | mitigate | `_segment` / `_number` never copy strings (`parity.py:181-196`); `test_storage_parity.py:608`, `:620` | closed |
| T-03-15 | Elevation of privilege | `storage_parity` input injection | low | mitigate | Boolean input, fixed `run:` (`job_hunter.yml:36-39`, `:163-165`); `test_deployment.py:236-256` | closed |
| T-03-16 | Tampering | Read-only command writes state | medium | mitigate | `run_storage_parity` dispatched before writes and lease (`hunter.py:2010-2039`, `:2410-2417`); `StorageParityCommandTests` snapshot comparison | closed |
| T-03-17 | Spoofing | Hand-edited key shows READY TO CUT OVER | medium | mitigate | Readiness recomputed via `bar(now)` (`reporting.py:321-340`); cutover re-checks bar and fresh parity (`hunter.py:2076-2087`); `DashboardStorageTests`, `test_storage_cutover.py:273` | closed |
| T-03-18 | Information disclosure | NEEDS ATTENTION copies job text | low | mitigate | `_SAFE_DIFF` filter (`reporting.py:313`, `:330`); `test_reporting.py:1357` | closed |
| T-03-19 | Elevation of privilege | Deploy without owner consent | high | mitigate | Owner chose deploy-and-dispatch before the push (03-05-SUMMARY; PILOT_LOG; STATUS) | closed |
| T-03-20 | Information disclosure | Secrets or personal files in pushed diff | high | mitigate | Pre-push secret and file-name scan clean (03-05-SUMMARY); `.gitignore` covers `.env`, Resume.pdf, resume.txt; none tracked | closed |
| T-03-21 | Information disclosure | Log text copied into STATUS / PILOT_LOG | medium | mitigate | Secret scan before quoting, 0 matches (STATUS); counts and run ids only | closed |
| T-03-22 | Repudiation | Claiming Sheet state verified live | low | mitigate | Sheet-only facts labelled owner check pending (STATUS) | closed |
| T-03-23 | Tampering | Cutover twice, on a stale bar, or without parity | high | mitigate | Gate: mode dual, seeded, `bar(now)`, fresh four-layer parity zero (`hunter.py:2062-2087`); `CutoverGateTests`. Interrupted-swap path `_finish_cutover` writes only the record after verifying Events_Legacy is the old ledger (documented recovery design) | closed |
| T-03-24 | Denial of service | Partial swap leaves no Events tab | high | mitigate | Two ordered renames in one `batch_update` (`state.py:517-529`); `test_storage_cutover.py:149`, `:393` | closed |
| T-03-25 | Tampering | Copy differs from source | high | mitigate | Read-back count + SHA-256, would-be parity before rename (`hunter.py:2088-2107`; `compact.py:371-376`); `test_storage_cutover.py:352`, `:365`, `:382` | closed |
| T-03-26 | Denial of service | Hand-rename restore re-observes jobs | medium | mitigate | Restore appends post-cutover rows first; refused after the first fold (`hunter.py:2198-2259`); `test_storage_cutover.py:523`, `:561`, `:582` | closed |
| T-03-27 | Spoofing | Local process writes production Sheet | medium | mitigate | Both commands under `local_write_refusal` and `writer_lease("poller")` (`hunter.py:2417-2431`); `test_storage_cutover.py:1076`, `:1090` | closed |
| T-03-28 | Elevation of privilege | Workflow expression injection via new inputs | low | mitigate | Boolean inputs, fixed `run:` lines (`job_hunter.yml:40-47`, `:169-176`); `test_deployment.py:258-285` | closed |
| T-03-29 | Denial of service | Fold deletes wrong rows | high | mitigate | Start-of-run row numbers, Identity and Tally membership required, highest ranges first, key/kind re-read before the first request (`compact.py:410-454`; `state.py:551-571`); `FoldPlanTests`, `test_storage_cutover.py:748`, `:759` | closed |
| T-03-30 | Tampering | Fold before cutover, on cutover day, twice, or on Events_Legacy | high | mitigate | `fold_due` compact only, day after cutover, once a day (`compact.py:717-724`; `pipeline.py:900`); Events tab only (`state.py:560`); `test_storage_cutover.py:723`, `:829`, `:858`, `:1033`, `:1044` | closed |
| T-03-31 | Denial of service | Fold batches exceed request limit or deadline | medium | mitigate | 500-request batches, 20-min cutoff, `last_day` unset on failure (`compact.py:390`; `state.py:569-570`; `pipeline.py:56`, `:271-277`, `:900-903`); `test_storage_cutover.py:748`, `:1005`, `:1018`. Live A5 batch size not observed | closed |
| T-03-32 | Repudiation | Projected savings presented as measured | low | mitigate | Dual-mode figures labelled projection (`storage_report.py:310-387`); after-figures only from complete days after `fold.first_day`; `test_storage_report.py:243`, `:248`, `:260` | closed |
| T-03-33 | Elevation of privilege | Deploy without consent or agent dispatching the cutover | high | mitigate | Owner chose deploy; nothing dispatched in 03-08 (03-08-SUMMARY; PILOT_LOG; STATUS) | closed |
| T-03-34 | Information disclosure | Secrets or personal files in pushed diff | high | mitigate | Pre-push scans clean (03-08-SUMMARY); as T-03-20 | closed |
| T-03-35 | Elevation of privilege | Cutover without owner decision or before the bar | high | mitigate | Bar read `3 of 3` (run 41364810371); owner chose agent-dispatches; command gate passed (run 41373351559) (03-09-SUMMARY; STATUS; PILOT_LOG) | closed |
| T-03-36 | Repudiation | Live success claimed without evidence | medium | mitigate | Two-day minimum used, ratio labelled transitional, order-of-magnitude drop not claimed; Sheet facts owner checks (STATUS; 03-09-SUMMARY) | closed |
| T-03-37 | Information disclosure | Job text or secrets copied from logs | medium | mitigate | All logs secret-scanned before quoting, 0 matches (STATUS) | closed |
| T-03-SC | Tampering | npm/pip/cargo installs (plans 03-01..03-09) | low | accept | AR-03-01 | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

**Unregistered flag (warning, non-blocking):** 03-06-SUMMARY notes the restore-only tab `Events_Failed`, a copy of rows already in the Sheet; the restore deletes nothing (`state.py:268-274`; `test_storage_cutover.py:523`). 03-01-SUMMARY has no `## Threat Flags` section (documentation gap only).

**Residual notes (non-blocking):**
- T-03-01: the warning-only prompt on Identity and Events_Legacy has not been seen live (owner check). A failed protection call at tab creation is logged and not retried; parity layer 1 is the backstop.
- T-03-31: four live folds succeeded (16,752 rows, 0 `storage fold failed`), but the logs print ranges, not batch sizes, so research assumption A5 stays mocked.

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-03-01 | T-03-SC (all nine plans) | No package installed in Phase 3; `requirements.txt` unchanged since before the phase; only new import is stdlib `hashlib` (03-RESEARCH "Package Legitimacy Audit") | Plan authors (plan-time `accept`) | 2026-11-06 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-11-06 | 46 | 46 | 0 | gsd-security-auditor (L1; 487 offline tests re-run, mocked) |
| 2026-11-14 | 46 | 46 | 0 | secure-phase short-circuit (L1, threats_open 0, register at plan time) after review fixes WR-01..WR-05; no new surface; full suite 931 offline tests OK (mocked) |
| 2026-11-14 | 46 | 46 | 0 | secure-phase short-circuit (L1) after review fix WR-06 (Identity count high-water mark); no new surface; full suite 934 offline tests OK (mocked) |
| 2026-11-15 | 46 | 46 | 0 | secure-phase short-circuit (L1) after review fix WR-07 (distinct Identity IDs for the mark); no new surface; full suite 937 offline tests OK (mocked) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-11-06; re-checked 2026-11-15 after WR-01..WR-07

## Security Audit 2026-11-06

| Metric | Count |
|---|---|
| Threats found | 46 |
| Closed | 46 |
| Open | 0 |

## Security Audit 2026-11-14

| Metric | Count |
|---|---|
| Threats found | 46 |
| Closed | 46 |
| Open | 0 |
