# Phase 3: Compact storage - Context

**Gathered:** 2026-10-29
**Status:** Ready for planning

<domain>
## Phase Boundary

The Events ledger stops growing toward its limit. Baseline and identity-only postings (title-gated, stale) live in a compact, hidden `Identity` tab, and a per-run `Tally` tab holds the counts that reports need. Both new stores are written alongside the old rows (dual writing) until a read-only `--storage-parity` check shows zero differences. Then, and only when the owner triggers it, the old tab becomes `Events_Legacy`. Requirement: STOR-01. Success criteria: ROADMAP.md Phase 3 (1-4).

In scope: the `Identity` and `Tally` tabs, seeding them from the existing ledger, dual writing, `--storage-parity`, the parity clock and its Dashboard / STATUS signal, the owner-triggered cutover, the rolling 7-day fold of title-gated and stale rows after cutover, the storage report's before / after figures, and the matching SPEC / DECISIONS / STATUS / PILOT_LOG updates (AGENTS rule 1).

Not in scope: archiving terminal operational rows (D-43 step 3, deferred), removing `Events_Legacy` from the Sheet, the 72 h window and backfill (Phase 4), board growth past 700 (Phase 5), new adapters, and any change to scoring, freshness classes or alerts (AGENTS rule 7). Phase 3 never overlaps Phase 4: both touch `ledger.observe_new` and the run-cycle observation block in `pipeline.py`.

Decision IDs below are local to this phase (`P3-xx`) so they do not collide with `DECISIONS.md` (D-01..D-56). This discussion is the owner's **storage design approval** (D-48 row 9). It is recorded as **D-57**, which amends D-43, closes the D-03 200k-row review and annotates D-48 row 9 "decided in D-57", in the same change that implements it.

**Clock:** Events was at 195,793 rows on 2026-10-28, growing about 9,489 rows a day, so it passes the D-03 200k point about 2026-10-29. D-43 treats crossing that point as a recorded review state, not an outage (about 13-14% of the 10M-cell limit, load about 10 s).

</domain>

<decisions>
## Implementation Decisions

### What leaves Events
- **P3-01:** Three kinds of row move to `Identity`: **baselines, title-gated and stale** postings (D-43 as written; dispositions `baseline`, `filtered`, `stale`, from poll or search). Compacting only baselines would not stop growth: after admission, most daily rows are title-gated. Operational rows (disposition `pending` and every later event) stay full rows in Events. — **Reversibility:** costly — reversing it means rebuilding full rows, and the titles, URLs and published times of folded rows are gone (only their IDs and Tally counts remain).
- **P3-02:** **Baselines go straight to Identity.** After cutover a baseline pass writes only IDs (Identity) and counts (Tally), never full Events rows. No report reads baseline titles, and admission waves (about 146 rows per board) are the bursts D-43 set out to stop. Phase 4's 72 h backfill will score recent jobs at baseline time, so those become ordinary operational rows.
- **P3-03:** **Title-gated and stale postings keep their full Events row for 7 days, then fold into Identity.** This replaces an earlier 30-day choice made in the same discussion. At D-43's measured 7.17 identity-only rows per monitored board per day, 30 days would hold about 150k rows at 700 boards and break "well below the 200k point" once Phase 5 grows the board count. 7 days holds about 35k rows at 700 boards (about 50k at 1,000). It keeps the Dashboard's 7-day views per job and gives a week of gate rejections to audit by hand. A fold **really deletes** the full rows from Events once their IDs are durable in Identity and their counts are in Tally. Copying them to `Events_Legacy` would save no cells. Folding starts only after cutover; before cutover nothing is deleted.
- **P3-04:** The `Identity` tab is **hidden and carries a warning-only Sheets protection**, so a hand edit asks for confirmation. A hand edit there could make old jobs look new. The service account still writes normally.

### Parity and cutover
- **P3-05:** **Parity bar: 3 full consecutive UTC days in which every run reports zero differences**, covering at least one board admission or refill. The check is the read-only `--storage-parity`, and it also runs inside every poller run during dual writing.
- **P3-06:** **The owner triggers the cutover.** When the bar is met, the Dashboard and STATUS say "ready to cut over". The owner then starts a workflow input (for example `storage_cutover`), which refuses unless the bar is met. The cutover is its own deployment row in `PILOT_LOG.md`. Nothing retires automatically. — **Reversibility:** reversible until the first post-cutover fold (restore by renaming `Events_Legacy` back); after folds begin, restoring means replaying `Events_Legacy` plus the post-cutover Events and Identity.
- **P3-07:** **On a parity difference during dual writing:** the old Events rows stay authoritative, so detection, evaluation and alerts are unaffected. The run is marked `degraded` (via `pipeline.degraded_reason`), the Dashboard shows NEEDS ATTENTION with the differing keys or figures, and the 3-day clock starts again.
- **P3-08:** **`Events_Legacy` is kept hidden and restorable for as long as the owner wants.** It still counts toward the 10M cells (about 1.4M). Removing it is a separate, later owner decision with an export plan.
- **P3-09:** **Seeding:** the first poller run after deploy builds `Identity`, and the historical `Tally` rows, from the ledger it already loads, under the existing lease. From then on both stores are written. There is no extra owner step. An interrupted seed is safe to redo because a board counts as seeded or baselined only after its last chunk is written (success criterion 4).

### What reports must keep
- **P3-10:** **Parity covers every reported number:** the derived `seen` set, state counts (pending evaluations and alerts, attempts, abandoned), every Dashboard figure (including the 14-day charts and the today / 7d / 30d periods in the Settings time zone), the pilot report's funnel and latency samples, and the storage report's counts. Each is computed once from the old Events rows and once from Identity + Tally + the kept Events rows, and they must be identical. So Tally must carry at least: the run id (rehearsal-run exclusion by `detail.run`), the run time (day bucketing in the display time zone), ATS, source (`poll` / `search`, legacy `serper` mapped as today), outcome / disposition (`baseline` / `age` / `title`), pass kind (`baseline` / `reentry` / ordinary) and freshness class. Historical ledger rows written before run ids existed are tallied so the existing reports' treatment (kept, not attributed) is unchanged.
- **P3-11:** **Windows longer than the kept detail** (gated and stale rows older than 7 days, all baselines) take their **totals exactly from Tally**. Per-job detail (titles, URLs, publication times of non-scored jobs) is unavailable there, and the report says so on that line, never silently.

### D-43 scope
- **P3-12:** **Archiving terminal operational rows (D-43 step 3) is out of Phase 3 (deferred).** Operational rows grow by about 164 a day, archiving would be a second migration with its own parity, and the success criteria don't need it.
- **P3-13:** **The counter tab is `Tally`, one row per run** (not D-43's `Daily`, one row per day), so a rehearsal run's counts can be excluded and per-run parity holds. Days are derived from the rows. D-57 amends D-43 to say so.
- **P3-14:** D-43's "delete baseline and identity-only rows in batches with an export kept" is replaced by the **tab swap** (P3-06, P3-08): the pre-cutover history is kept whole as `Events_Legacy`, not deleted.

### Claude's Discretion
- Tally's exact column set and encoding (wide counter columns vs one row per run × dimension), as long as P3-10 parity holds and Tally's growth stays small (D-43 target: about 1,300 cells a day overall).
- The `Identity` row layout (D-43: `Board_Key, Chunk, Baselined_At, Count, IDs`, at most 40,000 characters per cell) and how search-found identity-only jobs with no monitored board are keyed, as long as identity stays ATS + board + posting ID (AGENTS rule 3) and is never URL-based.
- How "baselined only after the last chunk" is enforced (for example, a completion marker on the last chunk, with `Boards.Baselined_At` saved after the Identity write, extending pipeline rule 1).
- How the fold is batched and ordered (Identity and Tally durable and read back before any Events row is deleted), and how it stays inside the run deadlines (D-51) and the Sheets quota.
- The `--storage-parity` output format and where the 3-day clock is stored (for example, the Discovery key/value tab).
- How the cutover input is wired into `.github/workflows/` (following D-56's dispatch-input pattern).
- How `replay` and the reporting readers merge Identity (as `seen`, with disposition) with the kept Events rows.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Contract and decisions
- `AGENTS.md` — rules 1-8 (flag conflicts, freshness, identity, separate stages, mocked vs live, secrets, rule 7, offline tests)
- `SPEC.md` — "State model", "Baselining", hidden tabs (~L108), "Operational dashboard" (~L116-131), pilot report and limits audit (~L151)
- `DECISIONS.md` D-03 — Events append-only ledger; the 200k-row review point this phase closes
- `DECISIONS.md` D-43 — the measured storage design, sizing, migration order and risks (amended by D-57)
- `DECISIONS.md` D-48 row 9 — storage design approval pending; becomes "decided in D-57"
- `DECISIONS.md` D-05, D-24 — baseline and re-entry semantics that Identity must preserve (re-entry compares IDs against the set and `Baselined_At`)
- `DECISIONS.md` D-33 — evidence semantics (observed time; search-found jobs)
- `DECISIONS.md` D-40, D-41, D-52, D-55 — dashboard and reporting definitions that parity must keep identical
- `DECISIONS.md` D-51, D-56 — run deadlines, and the workflow dispatch-input pattern for the cutover input
- `STATUS.md` — live Events row counts and growth (~L61, ~L84); the place the "ready to cut over" status and the mocked vs live labels go
- `PILOT_LOG.md` — deployments that affect measurements; dual-write deploy and cutover each need a row

### Planning
- `.planning/ROADMAP.md` — Phase 3 goal, entry gates, notes and success criteria 1-4
- `.planning/REQUIREMENTS.md` — STOR-01
- `.planning/codebase/CONCERNS.md` — "Events growth" (~L120-125), non-atomic Sheet lease
- `.planning/phases/02-measurement-governors-and-owner-decisions/02-CONTEXT.md` — P2 decisions on degraded runs, deadlines and the Dashboard yield view

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `storage_report.py` — `classify()` already splits rows into baseline / identity / operational. `COMPACT_CELL_CHARS = 40_000` and `COMPACT_COLUMNS` already size the Identity chunks. `analyze()` gives the before / after figures for success criterion 3.
- `ledger.replay` / `JobState` — the single place `seen` is derived. Identity must feed it so `pipeline.py`'s `unseen` check, `observe_known` (evaluated jobs only) and the FLOOD_MIN_JOBS re-baseline guard keep working.
- `state.SheetStore` / `CsvState` — the tab create / widen pattern (`ensure`, `_widen_header`), `_chunks` / `APPEND_CHUNK` for batched appends, and the CSV fallback that offline tests use.
- `reporting.job_facts` / `JobFacts.outcome()` — the per-job partition (`baseline`, `age`, `title`, ...) that Tally must reproduce in count form.
- `Runs.Events_Rows` / `Load_S` columns and the pilot-report limits audit — existing growth and load-time measurement.

### Established Patterns
- Pipeline rule 1 (`pipeline.py` header, ~L595): observations are durable before the registry says "baselined". Identity writes extend this rule (Identity chunks, then `Boards.Baselined_At`).
- Readers of non-pending rows: only reporting (funnel counts), `storage_report` and `pilot.py` samples. `pools.ActivityIndex` and board evidence read only `pending` rows, so they are unaffected by compaction.
- `seen_detail` is read at runtime only for pending or evaluated jobs (`hunter.py` ~L1710, `pipeline.py` ~L633), never for identity-only jobs.
- Degraded-run signalling through `pipeline.degraded_reason` and the Dashboard NEEDS ATTENTION row (D-52 pattern).
- One writer at a time under the Lock-tab lease (STATE-02); seeding and folds run under it.

### Integration Points
- `pipeline.py` ~L207 (`load_events` + `replay`), ~L395-450 (poll observation loop), ~L560-585 (search observations), ~L595 (durable write order).
- `state.py` ~L424-431 (`load_events`, `append_events`) and `ensure()` tab list.
- `reporting.py`, `dashboard.py` ~L585, `pilot.py` ~L134 / ~L310, `hunter.py` ~L1965 / ~L1994 / ~L2079: every `load_events()` consumer must read through the merged view.
- `hunter.py` argparse (~L2043): `--storage-parity`, and the cutover input.
- Tests: `tests/test_storage_report.py`, `tests/test_allocation_correctness.py` (multi-week simulation), and the pipeline tests for interrupted runs (success criterion 4).

</code_context>

<specifics>
## Specific Ideas

- The owner wants to see the cutover coming: "ready to cut over" on the Dashboard and in STATUS, then a deliberate workflow input. No silent storage change.
- A week of title-gate rejections stays readable by hand in Events after cutover.
- Every number the owner already reads (Dashboard, pilot report, storage report) must come out the same. Where per-job detail is gone, the line says so.

</specifics>

<deferred>
## Deferred Ideas

- Archiving terminal operational rows older than 90 days into `Events_Archive_YYYY_MM` tabs (D-43 step 3): a later phase, if operational rows ever matter for size.
- Removing `Events_Legacy` from the Sheet (export target, timing; a service account cannot own personal Drive files): a later owner decision.

</deferred>

---

*Phase: 03-compact-storage*
*Context gathered: 2026-10-29*
