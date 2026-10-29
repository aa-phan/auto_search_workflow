# Phase 3: Compact storage - Research

**Researched:** 2026-10-29
**Domain:** Google Sheets-backed append-only ledger compaction (Python 3.12, gspread 6.2.1), dual-write migration with parity proof, reporting parity
**Confidence:** HIGH on how the code reads and writes Events today and on the Sheets API surface; MEDIUM on live Sheets behavior that cannot be exercised without credentials (see Assumptions Log)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

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

### Deferred Ideas (OUT OF SCOPE)
- Archiving terminal operational rows older than 90 days into `Events_Archive_YYYY_MM` tabs (D-43 step 3): a later phase, if operational rows ever matter for size.
- Removing `Events_Legacy` from the Sheet (export target, timing; a service account cannot own personal Drive files): a later owner decision.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| STOR-01 | Baseline and identity-only rows are stored compactly (Identity and Tally tabs, D-43 amended), parity is proven before old rows retire, and Events stays below the D-03 review point | Identity codec and write order (Patterns 2, 5); Tally encoding and subtract-the-retained rule (Pattern 3); merged ledger view (Pattern 4); four-layer parity and clock (Pattern 6); tab-swap cutover (Pattern 7); fold (Pattern 8); storage report with allocated cells (Pattern 9); Validation Architecture maps SC1-4 to offline tests |
</phase_requirements>

## Summary

Phase 3 is a **migration of persisted state, not a feature**. Today every observed posting is one 7-column Events row; `ledger.replay` derives `seen` from them; every reader (`pipeline.run_cycle`, `reporting.build_summary`, `reporting.reconcile`, `pilot.build_report`, `storage_report.analyze`, `hunter` rebalance report) calls `state.load_events()` and gets the whole list. Identity-class rows (disposition `baseline`, `filtered`, `stale`) are ~99% of rows and have exactly one event each (the `seen` row); nothing downstream ever reads their detail except as **counts** (Dashboard day buckets, pilot reconciliation). So the design is: store their IDs in a hidden `Identity` tab (set semantics, `seen` only) and their counts in a one-row-per-run `Tally` tab, and make every reader go through one **merged ledger view** (kept Events rows + Identity + Tally). Parity is then provable by computing every figure twice (from the full old Events rows, and from a *simulated* post-cutover view of the same rows) and requiring identical output.

Three findings change the plan relative to CONTEXT and D-43 and must be carried into the plans:
1. **Tally needs a `date known` dimension that P3-10 does not list.** The Dashboard splits new postings into `new_date_known` / `new_date_unknown` for every non-baseline job including title-gated and stale ones (`reporting.py:326`). Without it the "Dropped (7d)" line and `freshness.new_postings_date_*` cannot reach parity.
2. **The job key's board segment is lowercased, the registry's board key is not** (`boards.py:84-85` vs `boards.py:62-65`; Lever and Workable boards keep their case). Identity must be keyed by the *job-key stem* `ats|board_lower` (first two `|` segments of the key), never by `BoardRecord.key`, or `stem|id` will not reconstruct the key and every such job will look new.
3. **Cell payload and the "10M cells" limit are measured differently than the code assumes.** `state._chunks`/`APPEND_CHUNK = 2000` rows per request would send up to 80 MB for 40,000-character Identity rows (Google recommends ≤ 2 MB per request); and the 10M limit counts **allocated** grid cells (rows × columns of every tab, blanks included), while `storage_report` computes `rows × 7`. Success criterion 3 asks for "allocated cells", so the report must read sheet grid properties.

**Primary recommendation:** Build a pure `compact.py` (Identity codec, Tally encoding, `Ledger` merged view, parity) first as a tracer, wire dual writing into the single observation write point in `pipeline.py` (~L595-599) by deriving identity-class rows from the *produced events* (do not touch `ledger.observe_new`, which Phase 4 edits), route every `load_events()` consumer through `state.load_ledger()` from the first deploy, and keep `Events` untouched until an owner-triggered, atomic (single `spreadsheets.batchUpdate`) tab swap.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Identity-class extraction, Identity chunk codec, Tally encoding, subtraction, parity comparison | Pure domain module (`compact.py`) | — | Must be offline-testable without a Sheet; AGENTS layout keeps pure logic out of persistence |
| `seen` derivation (set of keys) for dedupe | Pure domain (`ledger`/`compact`) | Pipeline | `pipeline.py` only needs membership; Events-derived `JobState` stays for pending/evaluated jobs |
| Persisting Identity/Tally, tab create/hide/protect, seed, fold deletes, tab swap | Persistence (`state.py`: `SheetState` + `CsvState`) | — | The only module that talks to gspread; CSV twin keeps offline tests real |
| Dual-write ordering and degraded marking | Pipeline (`pipeline.py` observation write block) | State | Ordering rules (rule 1) live in the pipeline header |
| Figures identical across storage modes | Reporting (`reporting.py`, `pilot.py`, `storage_report.py`) | Dashboard | Counting logic must not fork: feed pseudo-facts from Tally through the same code path |
| "Ready to cut over", NEEDS ATTENTION on a difference | Dashboard render (`dashboard.py`) | Reporting summary dict | Dashboard stays read-only toward operational state; it reads the `storage` Discovery key |
| `--storage-parity`, `--storage-cutover` entry points and refusal gate | CLI (`hunter.py`) | Workflow YAML | Read-only vs writing split already modelled by `--storage-report` vs `--import-inventory` |
| Cutover and parity inputs | GitHub Actions workflow (`job_hunter.yml`) | `tests/test_deployment.py` | D-56 pattern: boolean dispatch input, guarded `if:` expressions, asserted by a test |
| Row/cell/char limits, quota | Google Sheets (external) | `storage_report` (measurement) | Limits are external facts; the report measures, never assumes |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| gspread | 6.2.1 installed; `requirements.txt` pins `gspread>=6.0,<7` | Sheets client (already the only client) | Already used by `SheetState`; exposes `update_title`, `hide`, `add_protected_range`, `Spreadsheet.batch_update`, `fetch_sheet_metadata`, `list_protected_ranges` [VERIFIED: `.venv/bin/python` introspection of gspread 6.2.1 this session] |
| Python stdlib (`json`, `dataclasses`, `csv`, `unittest`) | Python 3.12.13 | Everything else | The project has zero other runtime dependencies for state; tests are `unittest` [VERIFIED: `.venv/bin/python --version`, `requirements.txt`] |

### Supporting
None. No new packages are needed (see Package Legitimacy Audit).

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `Tally` as one wide row per run with a JSON counts cell | One row per run × dimension (long format) | Long format is greppable by hand but costs ~5-20x the cells (a run touches ~20 dimension combos); D-43 allows about 1,300 cells/day total, and operational rows already take ~1,150 of that (164 rows × 7). One row/run × 4 columns = ~96 cells/day fits |
| Subtract-retained merge (Tally written at observation) | Tally written only at fold time | Fold-time Tally is empty during dual writing, so Tally correctness could not be proven by the parity days. Observation-time Tally is exercised on every run |
| Keep the `JobState` stub per Identity ID in `states` | Separate `identity_seen: set[str]` | Stubs add ~190k dataclass objects with three empty containers each; a set is smaller and `pipeline.py` has only four membership sites |
| Scattered `deleteDimension` per row run | Rewrite Events in place (clear + write) | `clear` followed by a crash loses the ledger; the existing fakes also assert `clear()` is never called. Descending `deleteDimension` batches are atomic per request |

**Installation:** none (`gspread` already in `requirements.txt`).

**Version verification:** `gspread.__version__` printed `6.2.1` from the project venv [VERIFIED: this session]; `requirements.txt` bounds `>=6.0,<7`.

## Package Legitimacy Audit

No external packages are added by this phase; `gspread` is already a pinned dependency and was not newly introduced. The `gsd-tools package-legitimacy` seam was not run because there is nothing to check.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| (none new) | — | — | — | — | — | — |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
 hourly poller run (under the Lock-tab lease, one writer)
 ┌─────────────────────────────────────────────────────────────────────────┐
 │ LOAD  Events rows (with sheet row numbers) + Identity + Tally + Boards  │
 │        └─> Ledger(events, identity_ids, tally)  == state.load_ledger()  │
 │ PARITY(snapshot)  old-figures  vs  simulated-compact-figures  -> diffs  │
 │ REPAIR  identity-class ids present in Events but missing in Identity    │
 └──────────────┬──────────────────────────────────────────────────────────┘
                │ seen(key) = key in identity_ids  OR  states[key].seen
                v
 ┌──────────────────────────┐   per job: seen? ──yes──> observe_known (evaluated only)
 │ poll boards / search jobs│   ──no──> lg.observe_new() -> Event (unchanged)
 └──────────────┬───────────┘
                v  pending_events (seen/updated/republished of this run)
 ┌─────────────────────────────────────────────────────────────────────────┐
 │ OBSERVATION WRITE (pipeline ~L595):  split each seen event by            │
 │   compact.identity_class(ev): baseline | filtered | stale | None         │
 │  mode=dual:    Events <- ALL rows ;  Identity += ids ; Tally += counts   │
 │  mode=compact: Events <- all but baseline rows ; Identity ; Tally        │
 │  order: Events -> Identity (final chunk carries the marker) -> Tally     │
 │         -> save_boards (Baselined_At)            [rule 1 extended]       │
 └──────────────┬──────────────────────────────────────────────────────────┘
                v
 evaluate -> tracker -> evaluated event -> alert (unchanged, operational rows)
                v
 FOLD (compact mode only, <= once per UTC day, after alerts, deadline-guarded)
   rows: seen & disposition in {filtered, stale} & Time <= now-7d & id in Identity
   -> ONE spreadsheets.batchUpdate of descending deleteDimension ranges
                v
 dashboard.refresh(): Ledger -> reporting.build_summary (+ pseudo-facts from Tally)
 storage state (Discovery key `storage`): mode, parity clock, cutover record

 owner cutover (workflow input, own run, under the lease):
   gate: parity bar met AND a fresh parity pass now == 0 diffs
   Events_New <- retained rows -> read back -> ONE batchUpdate:
        rename Events->Events_Legacy, Events_New->Events (atomic, ordered)
   -> Discovery `storage`.mode = "compact" -> PILOT_LOG row
```

### Recommended Project Structure
```
compact.py              # NEW pure core: identity_class, Identity codec, Tally, Ledger view, parity, fold selection
state.py                # + IDENTITY_TAB, TALLY_TAB; load_ledger/load_identity/write_identity/append_tally/fold_rows/swap
pipeline.py             # observation write block (~L595-599) + seen checks (L320, L419, L429, L532)
reporting.py            # build_summary / reconcile accept folded pseudo-facts (counting code reused)
pilot.py, dashboard.py  # call state.load_ledger(); dashboard renders storage signal
storage_report.py       # allocated cells from sheet metadata, before/after
hunter.py               # --storage-parity, --storage-cutover; inventory_mode list; writes expression
.github/workflows/job_hunter.yml   # storage_parity (read-only) and storage_cutover inputs
tests/fake_sheets.py    # NEW shared in-memory Sheets fake (see Validation Architecture)
tests/test_compact.py, tests/test_storage_parity.py, tests/test_storage_cutover.py  # NEW
```
Add `compact.py` to the AGENTS.md "Layout" line in the same change (AGENTS rule 1).

### Pattern 1: Derive identity-class rows from the produced Event, not from `observe_new`
**What:** `compact.identity_class(ev) -> "baseline" | "filtered" | "stale" | None` returns a class only for `ev.event == SEEN` with disposition in the three identity dispositions. The pipeline splits `pending_events` once, at the single write point, so `ledger.observe_new` keeps its signature.
**When to use:** always. Phase 4 also edits `observe_new` and the observation block; keeping Phase 3's footprint to one block plus the four `seen` checks keeps the merge small (and the roadmap forbids overlapping the two phases anyway).
**Evidence:** values from `ledger.py:23` `PENDING, BASELINED, FILTERED, STALED = "pending", "baseline", "filtered", "stale"`; `storage_report.classify` already encodes the same split (`storage_report.py:40-52`). Do not import from `storage_report` into the pipeline; move the rule to `compact.py` and have `storage_report.classify` call it so there is one definition.

### Pattern 2: Identity rows (layout, codec, write rules)
**Layout (recommended, within discretion):** columns `Board_Key, Chunk, Baselined_At, Count, IDs` (D-43 / `storage_report.COMPACT_COLUMNS = 5` with `COMPACT_CELL_CHARS = 40_000` [VERIFIED: `storage_report.py:25-26`]).
- `Board_Key` = the **job-key stem**: `"|".join(key.split("|", 2)[:2])`, e.g. `greenhouse|acme` or `lever|foo` (lowercased board). Reconstruct a key as `f"{stem}|{id}"`. Never use `BoardRecord.key` (case-preserved for Lever/Workable) and never a URL. This also keys search-found identity-only jobs of boards that are not in the registry (the stem comes from the job key itself).
- `IDs` = comma-joined entries, each **prefixed by a one-letter kind**: `b` baseline, `f` filtered, `s` stale (e.g. `b4459849009,f5551112,s77`). This keeps disposition (CONTEXT: "as `seen`, with disposition") without extra rows, and guarantees every cell is text, so Sheets cannot reinterpret a bare numeric ID as a number (scientific notation on long numeric IDs) [ASSUMED: RAW input of an all-digit string is stored as text; the prefix removes the question].
- **Escaping:** IDs come from ATS payloads (`str(j["id"])`, lowercased or, for Workable, uppercased, `boards.py:84`). Percent-encode `%` and `,` in an ID (`%25`, `%2C`) and decode on read; a test must round-trip awkward IDs. Keys with fewer than three `|` segments (malformed rows) cannot be stemmed: leave such rows in Events, never fold them, and report them as a parity difference class `unkeyable` [ASSUMED: none exist in production].
- `Count` = number of entries in that cell; parity checks `Count == len(IDs)` and `len(IDs) <= 40_000`.
- **Completion marker:** `Baselined_At` is written **only on the highest-numbered chunk** a write produced; a board's Identity set is complete iff its highest-numbered chunk row has it. A multi-chunk first write puts the marker on the last chunk only, in ascending chunk order, so an interrupted write leaves the highest chunk unmarked (= incomplete). Redo is idempotent: re-derive the same chunks and overwrite rows by `(Board_Key, Chunk)`.
- **Growth in steady state is in place:** D-43's ~1,300 cells/day target allows no per-run per-board row appends (700 boards × 5 cells would be 3,500). New IDs are appended into the board's *last* chunk cell (read-modify-write of one cell, same-content-superset so a repeat is idempotent); a new row is added only when the last chunk would exceed 40,000 characters. Update touched boards with `ws.batch_update([{"range": f"E{row}", ...}])`-style writes.
- **Payload-bounded requests:** never reuse `APPEND_CHUNK = 2000` rows (`state.py:66`) for Identity. Chunk requests by total characters (recommend ≤ ~1,000,000 characters per request; Google recommends ≤ 2 MB [CITED: developers.google.com/workspace/sheets/api/limits]) and never split one board across requests unless that board alone exceeds the budget.
- Read: one `get_all_values()` of the tab per run (about one request); keep the row numbers for in-place updates.

### Pattern 3: Tally (one row per run, counts in a JSON cell) and the subtract-the-retained rule
**Layout (recommended):** `Run_ID, Run_At, Total, Counts`. `Counts` is a JSON object `{ "<dim key>": n }` where `dim key` = `ats|source|disposition|pass|freshness|date` with `source` already mapped (`serper` to `search`, blank to `unknown`, exactly as `reporting.job_facts` does at `reporting.py:205-206`), `disposition` in `baseline|filtered|stale`, `pass` in `baseline|reentry|""`, `date` in `k|u` (publication date known or unknown).
- **`date` is required beyond P3-10's list** [VERIFIED: `reporting.py:326` `c["new_date_known" if f.date_known else "new_date_unknown"] += 1`, executed for every `out != "baseline"` job including title-gated (`out == "title"`) and stale (`out == "age"`) ones; `date_known` is `published is not None`, `reporting.py:153-154`]. `ats` is `key.split("|")[0]` (so a region prefix such as `ats@eu` stays distinct), identical to `JobFacts.ats` (`reporting.py:200`).
- `Run_At` equals the event `Time` of that run's `seen` rows: the pipeline stamps every observation with the run's single `now` (`pipeline.py:200`, `lg.Observation(now, ...)`, `observe_new` returns `Event(stamp(obs.now), ...)`). Day bucketing, the pilot's exact-timestamp windows and rehearsal exclusion (`detail.run` ∈ rehearsal run ids, `reporting.py:270-272`) therefore work from the Tally row alone. Historical rows without a run id are tallied by `(Run_ID="", Run_At=Time)`.
- Always write one row per run that reaches the observation write point (SC1: "each run writes a `Tally` row"), including a zero-count row; about 24 rows/day × 4 cells ≈ 96 cells/day.
- **Subtraction (the core merge rule):** for each `(Run_ID, Run_At, dim key)` the *folded* count is `max(0, tally_count - retained_count)` where `retained_count` is the same dimension count recomputed from the **Events rows still present** for that run. Tally is written at observation time; rows later fold-deleted (or never written, such as post-cutover baselines) are exactly the difference. A negative difference (`tally < retained`) is a parity difference (Tally write lost).
- **Feeding the reports without forking counting code:** `compact.folded_facts(ledger)` yields synthetic `reporting.JobFacts` (unique synthetic key such as `ats|~tally|<run>|<i>`, `seen_at` = `Run_At`, disposition, `freshness`, `source`, `pass_kind`, `published` = a sentinel instant if `date == "k"` else `None`). Merge them into the **seen-only** paths: the per-day counter block of `build_summary` (`reporting.py:315-353`; refactor the body into `_count_seen(c, f)` and call it for real and synthetic facts) and `reconcile`'s `seen` list (`reporting.py:1053`). Do not put synthetic facts in `facts` used by `_yield`, `_groq`, `_failures`, `tracker_join` (they are keyed to real operational jobs). Figures that count ledger rows (`ledger_events_read`, `events_from_rehearsal_runs`, `latest_ledger_event`, `reporting.py:477-488`) add the folded total and folded run times so they stay identical (P3-10: "every reported number").
- `reporting._checks` (job outcomes sum to unique jobs, periods nested, `reporting.py:951-966`) is a free internal oracle: it must still pass in compact mode.

### Pattern 4: One merged ledger view; `seen` becomes a set
- Add `state.load_ledger() -> compact.Ledger(events, event_rows, identity, tally)` to both `SheetState` and `CsvState`. Keep `load_events()` returning raw Events rows for the few callers that want only operational history. Route **every** consumer through the merged view from the first deploy, including in dual mode, where `folded == 0` and results are identical by construction: `pipeline.py:207-208`, `dashboard.py:585`, `hunter.py:1965` (pilot report), `hunter.py:1994` (rebalance report, PENDING-only, fine on raw events), `hunter.py:2081` (storage report), `tests/test_core.py` Harness `events()`/`states()` (`test_core.py:121-125`).
- In `pipeline.py` replace the four `states.get(k) and states[k].seen` tests (L320, L419, L429, L532) and the in-run additions (L435, L567) with one helper `seen(key) = key in identity_seen or (key in states and states[key].seen)`; add newly observed identity-class keys to `identity_seen` in-run. A job in both stores is taken from Events (richer detail), Identity only adds membership. Pending/evaluated jobs never appear in Identity, so `needs_evaluation` (`ledger.py:104`, requires `disposition == PENDING`), `observe_known` (only if `st.evaluated is not None`, `pipeline.py:430`) and `pools.ActivityIndex` (skips non-PENDING, `pools.py:94`) are unaffected [VERIFIED: read this session].
- `hunter.py` ~L1710 `seen_detail` is read only for jobs that reached evaluation; Identity jobs never do.
- Local benchmark: on 190,000 synthetic events `replay` took 0.24 s and `reporting.job_facts` 1.17 s, peak RSS about 456 MB [VERIFIED: local run this session, synthetic data], so computing parity in every run (two extra passes) is affordable against a 25-minute budget.

### Pattern 5: Write order and failure analysis (extends pipeline rule 1)
Order at the observation write point: **(1) Events append, (2) Identity write (final chunk carries the marker), (3) Tally append, (4) `save_boards`.** (Today: `append_events` then `save_boards`, `pipeline.py:597-599`.)
- Crash after (1) before (2): in dual mode Events is authoritative so nothing looks new; the next run's REPAIR step finds Events identity-class IDs missing from Identity and adds them (this also covers seeding). In compact mode, baseline jobs have no Events row, so their only record is step (2); (1) contains only gated/stale/operational rows, which the repair step can re-derive.
- Crash after (2) before (3): counts are lost (reports undercount) but the IDs are safe. It is detectable pre-cutover (`tally < retained`), and post-cutover it is visible only as a degraded-run note; accept (rule 4: stages stay separate, a count is not a seen fact).
- Crash during (2) in the middle of a board: that board has no marker and `Boards.Baselined_At` is not saved, so the next run is again `baseline_pass`; IDs already in Identity are `seen`, the rest are re-baselined, none is classed fresh or alerted (SC4).
- Never reorder so that Tally is written before Events: a crashed run would leave counts for rows that never existed, and the next run re-observes the jobs under a new run id (double count).
- Do not claim atomicity for `ws.batch_update` (values.batchUpdate): Google documents atomicity for `spreadsheets.batchUpdate` only [CITED: developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/batchUpdate: "it is guaranteed that the updates in the request will be applied together atomically", "Requests will be applied in the order they are specified"]; the guide page makes no values.batchUpdate statement [CITED: developers.google.com/workspace/sheets/api/guides/batchupdate]. Every Identity write must therefore be idempotent (cumulative set content).

### Pattern 6: Parity (four layers) and the parity clock
`compact.parity(ledger_old_events, identity, tally, now, ...) -> ParityReport(diffs: list[Diff])`, used by `--storage-parity` (fresh load, read-only, no lease) and inside every poller run (on the start-of-run snapshot, so it verifies the previous run's writes; one-run lag is acceptable and must be documented). Layers:
1. **Seen set:** `{k for k, s in replay(events).items() if s.seen}` equals `identity_keys ∪ {seen keys of the retained rows}`, both directions, plus `Count == len(IDs)`, no chunk over 40,000 characters, stem round trip (`f"{stem}|{id}" == key` for every identity-class Events row), disposition kind of each Identity ID equals the Events disposition, every board with identity-class rows has a complete (marked) set.
2. **Tally recount:** for every `(Run_ID, Run_At, dim key)`, Tally count equals the count recomputed from Events identity-class rows (dual mode, nothing deleted yet). Name differing run ids and keys.
3. **State counts:** pending evaluations, pending alerts, attempts, abandoned computed from `replay(events)` and from the merged view are equal (they read only operational rows, so this guards against a merge bug that drops one).
4. **Figures:** `reporting.build_summary`, `reporting.reconcile` and `storage_report.analyze` computed from the old rows (as today) and from a **simulated compact view of the same rows** (`simulated_kept = events minus baseline rows minus filtered/stale rows with Time <= now - 7 days`, plus folded pseudo-facts from Tally minus retained) must be deeply equal. Declare exactly one allowed difference class per figure up front (for example `storage_report` "by purpose" row counts, which differ by design after a real cutover, are compared as category totals), and list in the output any figure compared. Use the same `now` and `tz` for both sides.

**Clock:** store in the Discovery tab under one key, e.g. `storage` (the tab holds 8 keys today and was created with 20 rows: `ensure()` creates `Discovery` with `rows=20`, `state.py:277`; `ws.update` beyond the grid fails, so add at most one or two keys). JSON like `{"mode":"dual","since":"2026-10-30","days":{"2026-10-30":{"runs":22,"diffs":0,"admissions":3}},"bar_met_at":null,"last_diffs":[...],"cutover":{...}}`; prune days older than 14. A UTC day counts only if it is complete (fully elapsed), has at least a minimum number of parity-checked runs (an open choice, see Open Questions), has zero differences in every run, and the 3-day streak contains at least one day with an admission (`run.boards_activated > 0` or a board whose `baselined_at` was newly set). Any difference resets `since` (P3-07). The poller marks the run degraded: add a `"storage"` reason to `pipeline.degraded_reason` keyed off the run note (e.g. `"storage parity"` in `run.notes`), the same notes-based mechanism as `persistence` (`pipeline.py:182-183`); this avoids adding a Runs column, which would require changes to `RunRecord.from_row` positional indexes (`state.py:177-184`) and update existing tests that pin `RUN_COLUMNS[-4:]` (`tests/test_governors.py:269`). The parity code itself must be contained (try/except): a crash in the check is "parity not evaluated" (clock resets, note added) and never stops job processing.
**Dashboard:** `dashboard.build` passes the `storage` key into `build_summary(..., storage=...)`; `render` adds a SYSTEM line ("Storage: dual write, parity day 2 of 3, ready to cut over") and `reporting._failures` adds a NEEDS ATTENTION row (keys or figures, ≤ 3 named, no titles) when `last_diffs` is non-empty. The existing "run degraded" row already carries `notes[:160]` (`reporting.py:765-768`).

### Pattern 7: Owner-triggered cutover (tab swap)
Command `--storage-cutover` (supports `--dry-run` printing the plan; refuses unless mode is `dual`, the clock bar is met, and a fresh `--storage-parity` pass in the same run has zero differences). Runs under the existing `poller` lease label (same workflow, same 25-minute timeout; no new `LEASE_TTL` entry, which `tests/test_deployment.py:125-129` ties to workflow timeouts). Procedure:
1. Build `retained` = all Events rows except baseline `seen` rows and filtered/stale `seen` rows with `Time <= now - 7d`. Record the "before" snapshot (Events rows, allocated cells, median `Runs.Load_S`, daily cell growth) into the `storage` key.
2. Create `Events_New` (`add_worksheet(rows=len(retained)+headroom, cols=7)`), append `retained` with the existing `_chunks` (rows are ~486 characters; the 2000-row chunk is fine for Events), **read back** and verify row count and a checksum of keys against `retained`.
3. **One** `sh.batch_update({"requests": [...]})` with, in order: `updateSheetProperties(sheetId=Events, title="Events_Legacy", fields="title")`, `updateSheetProperties(sheetId=Events_New, title="Events", fields="title")`. Because the whole batch is atomic and ordered [CITED: batchUpdate reference above], the spreadsheet is never left without an `Events` tab. (gspread's `update_title` is a separate request per tab and would not be atomic; build the raw body, shape shown in Code Examples.) Keep `Events_Legacy` hidden (it was hidden already; renaming keeps the hidden flag) and consider the same warning-only protection.
4. Write `storage.mode = "compact"`, `cutover_at`, counts, then a PILOT_LOG row (documentation step, own deployment row per P3-06).
5. **Guard `ensure()`:** it currently creates a missing `Events` tab silently (`state.py:275-288`). If `Events` is missing while `Events_New` or `Events_Legacy` exists, `ensure()` must raise (refuse the run) instead of creating an empty ledger: an empty Events plus no baseline rows would make every job look new, the flood this whole design exists to prevent.
Restore before the first fold: one batch renaming `Events` to `Events_Failed` and `Events_Legacy` to `Events`, set mode `dual`. After folds begin, restore means replaying (P3-06).

### Pattern 8: The 7-day fold (compact mode only)
- At most once per UTC day, after the alert stage, skipped when the run clock is past a conservative deadline (the budget is 25 min total, alerts stop starting at 22 min, `pipeline.py:48-50`, `.github/workflows/job_hunter.yml:69`). Use the Events rows loaded at run start **with their sheet row numbers** (`state.load_events` currently drops invalid rows via `Event.from_row` returning `None`, which would shift the index; the new loader must return `(row_no, Event)` pairs). Appends made later in this run land after the loaded rows, so the snapshot's indexes stay valid under the lease.
- Select rows: `event == seen`, disposition in `{filtered, stale}`, `Time <= now - 7 days`, and the key's ID is present in the **Identity set loaded from the Sheet at run start** (the durable-and-read-back precondition). A row whose ID is not in Identity is skipped, counted, and surfaces in the next REPAIR step; never delete first and repair later.
- Compress selected row numbers into contiguous runs, emit `deleteDimension` requests **descending by row** (so earlier indexes stay valid), at most ~500 requests per `sh.batch_update` call (each call is atomic; the per-call request cap is not documented, see Assumptions). gspread's own `delete_dimension` uses `startIndex = row - 1`, `endIndex = last row` [VERIFIED: gspread 6.2.1 source `Worksheet.delete_dimension`]. Do not call `ws.delete_rows` per run: existing test fakes assert `delete_rows`/`clear` are never called (`tests/test_hunter.py` FakeWorksheet `__getattr__`) and each call spends a write request.
- Deleting is safe for counts because Tally was written at observation: after a fold, `folded = tally - retained` simply grows. No Tally write happens at fold time.
- Expected volume: ~7.17 identity-only rows per monitored board per day (D-43), so ~5,000 rows/day at 700 boards, interleaved with ~164 operational rows/day, so a few hundred contiguous ranges per fold.

### Pattern 9: Storage report before/after (SC3)
`storage_report.analyze` computes `cells_now = rows * 7` (`storage_report.py`), but Sheets counts allocated grid cells. Add `allocated_cells` and a per-tab table from `sh.fetch_sheet_metadata(params={"fields": "sheets.properties"})` (`gridProperties.rowCount`, `columnCount`; this is the call gspread itself uses in `list_protected_ranges`, and `dashboard._existing_chart_ids` already uses `fetch_sheet_metadata`) [VERIFIED: gspread 6.2.1 source; Google's help says the 10M limit counts blank cells and all tabs [CITED: workspaceupdates.googleblog.com/2022/03/ten-million-cells-google-sheets.html via search result]]. The report must print rows, allocated cells and median load time for Events, Identity, Tally, `Events_Legacy` and the spreadsheet total, the cutover "before" snapshot beside "after", and the measured post-cutover daily growth in cells over complete days (compare with D-43's 26,200 to about 1,300). `Events_Legacy` still counts (about 1.4M cells, P3-08). Provide the dual-period figure as a projection, labelled so.

### Pattern 10: Workflow inputs (D-56 pattern)
Add boolean `storage_parity` (read-only, like `storage_report`) and `storage_cutover` (writes). Update all four places together: the `inputs:` block, `REQUIRE_TELEGRAM` expression (`job_hunter.yml:107`; neither command delivers, so Telegram is not required), the poller step's `if:` exclusion list (`job_hunter.yml:124`), and one new step each. Asserted today by `tests/test_deployment.py:233` (the literal expression), so that test must be updated in the same change. Use booleans, not free-text inputs (no expression-injection surface). `hunter.py`: add both flags to `inventory_mode` (so no `GROQ_API_KEY` is demanded) and add `--storage-cutover` to the `writes` expression (`hunter.py:2047` and `hunter.py:2088`) so `local_write_refusal` applies.

### Anti-Patterns to Avoid
- **Keying Identity by `BoardRecord.key`:** drops Lever/Workable case equivalence (see Finding 2).
- **Tally written at fold time or after deletion:** untestable during dual writing and loses counts on a crash.
- **Counting folded jobs from both Tally and retained rows:** double counts for the 7 days both exist; always subtract.
- **`ws.clear()` / rewrite-the-whole-Events:** a crash mid-way destroys the ledger; the swap and descending deletes are the only mutations.
- **Deleting before the Identity set is read back:** a lost ID makes an old job look new and alert (rule 4).
- **Reusing `APPEND_CHUNK` rows for Identity:** payload size (see Finding 3).
- **Altering `observe_new`, scoring, freshness classes or alerts:** out of scope (AGENTS rule 7; Phase 4 owns `observe_new`).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Counting jobs per day/outcome/source for folded rows | A second implementation of the Dashboard counters over Tally | Synthetic `JobFacts` through the same `_count_seen` code (Pattern 3) | Parity by construction; a forked counter is the main way "every number identical" fails |
| Atomic two-tab swap | Two `update_title` calls, or copy-then-delete | One `spreadsheets.batchUpdate` with two `updateSheetProperties` requests | Documented atomic and ordered; no window without an `Events` tab |
| Row deletion | Row-by-row `delete_rows`, or clear-and-rewrite | One batch of descending `deleteDimension` ranges | One write request per batch, atomic per batch, restorable by version history |
| Whole-sheet warning protection | Hand-built A1 range with guessed bounds | `addProtectedRange` with `{"sheetId": id}` only, `warningOnly: true` | "The range may be fully unbounded, in which case this is considered a protected sheet" [CITED: sheets REST reference, ProtectedRange]; covers appended rows |
| Rate/quota handling | New retry loops | The existing `quota_retrying` wrapper on the gspread client (`hunter.py` ~L1341) and `METER` | Already counts reads/writes/429 into `Runs` |
| Safe row-level locking | A new lock | The Lock-tab lease via `writer_lease` | Seeding, folds and cutover are writers; same concurrency group `job-hunter-state` |
| Sheet fakes | Per-test ad hoc fakes | One shared `tests/fake_sheets.py` that interprets `batchUpdate` requests | The three existing fakes cannot represent renames, deleteDimension, protection or limits |

**Key insight:** every report already reduces non-operational jobs to a handful of counters. Preserve that structure (counts in Tally, membership in Identity) rather than trying to preserve rows.

## Runtime State Inventory

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | Events tab, 195,793 rows on 2026-10-28, ~9,489 rows/day (STATUS L84); new tabs `Identity`, `Tally`, later `Events_Legacy`; Discovery key `storage` | Data migration (seed Identity/Tally from loaded ledger) AND code edits (dual write); fold is a second data change after cutover |
| Live service config | Hidden tabs exist only in the Google Sheet (not in git): protection settings on `Identity` live in the Sheet; the owner's Settings tab is never auto-widened (D-50/D-53 pattern) | Create tabs and protection via `ensure()`; no new Settings rows needed (parity constants live in code) |
| OS-registered state | GitHub Actions `workflow_dispatch` inputs in `job_hunter.yml`; the external hourly trigger (`trigger_source`) | Add two boolean inputs; no schedule change; cutover is a manual dispatch |
| Secrets/env vars | None new. Cutover and parity need `GOOGLE_*` only; Telegram not required for them | None; keep `REQUIRE_TELEGRAM` expression in sync |
| Build artifacts / installed packages | Local fallback `state/*.csv` (ignored by git; CI force-adds it when Sheets is not configured per `.gitignore`); `.planning/codebase/*` map is stale (22 files changed since mapping) | `CsvState.ensure()` must also create `identity.csv`/`tally.csv`; do not rely on the code map, verify against source |

**After every file is updated, what still holds the old shape:** the live Events tab (until cutover), `Runs.Events_Rows` history (keeps meaning "Events rows loaded"), and `Events_Legacy`. Nothing else caches the old structure.

## Common Pitfalls

### Pitfall 1: A bare `Identity` board key breaks lookups for case-sensitive ATS
**What goes wrong:** Lever/Workable boards are stored case-preserved in the registry (`lever|Foo`) but job keys use `board.lower()`; an Identity keyed from the registry never matches `lever|foo|<id>`, so the whole board looks new (flood alerts, wrong re-baseline).
**How to avoid:** key by the job-key stem; parity layer 1 asserts stem round trip for every Events identity-class row; a unit test uses a mixed-case Lever board.
**Warning signs:** `unseen` count equals the listing size on a baselined board; `FLOOD_MIN_JOBS` (30, `pipeline.py:44`) re-baseline note in `Runs.Notes`.

### Pitfall 2: Tally without `date known` (and other dimensions)
**What goes wrong:** the parity run fails on `new_postings_date_known/unknown` and the "Dropped (7d)" line, or, worse, parity passes only because the simulated side shares the omission.
**How to avoid:** derive the dimension list from what `build_summary` and `reconcile` read for non-pending jobs (listed in Pattern 3), and add a test that mutates each dimension in Tally and expects a parity difference (mutation check).

### Pitfall 3: Double counting during the 7 days both stores hold a job
**What goes wrong:** counts doubled in the 7-day window after cutover.
**How to avoid:** the subtract rule (`max(0, tally - retained)`) and a test with a half-folded run (some rows deleted).

### Pitfall 4: Payload and cell limits
**What goes wrong:** a 2,000-row append of 40,000-character cells (~80 MB) times out or errors; a cell above 50,000 characters is rejected. `_DETAIL_LIMIT = 45000` (`ledger.py:28`) already truncates Event details; Identity has no such guard.
**How to avoid:** character-budgeted request splitting; hard cap each cell at 40,000 characters in the codec; the shared fake raises on a cell over 50,000 characters and on an oversized request body so tests catch it.

### Pitfall 5: `ensure()` recreating `Events` after a rename
See Pattern 7 step 5. Also `bootstrap()` calls `state.ensure()` on every start (`hunter.py` ~L1418), including the read-only reports, so the guard must live in `ensure()`.

### Pitfall 6: Existing tests that encode the tab list and run columns
`tests/test_hunter.py` `test_bootstrap_creates_user_tabs_and_hidden_state_tabs` asserts the exact tab set and that each hidden tab is hidden: it must gain `Identity` and `Tally`. `tests/test_deployment.py:233` pins the `REQUIRE_TELEGRAM` expression. `tests/test_governors.py:269` pins the last four `RUN_COLUMNS` (avoided if no Runs column is added). `tests/test_inventory.py` `FakeSh` has no `batch_update` and `FakeWs` no `__getattr__`: the protection call in `ensure()` must be inside the same cosmetic `try/except` as `freeze`/`hide` (`state.py:283-287`) or those tests raise `AttributeError`.

### Pitfall 7: Parity must compare like with like in time
The in-run check uses the start-of-run snapshot and the run's `now`; the CLI uses a fresh load. Use one `now` and one display time zone for both sides of every figure, otherwise 7d/30d day buckets differ by a boundary run.

### Pitfall 8: Dedupe keys with unusual shapes
Keys with fewer than three `|` segments, IDs with `,` or `%`, or an ID equal to `""`. Handle by keeping such rows in Events (never fold) and reporting them in parity.

### Pitfall 9: Manual tracker rows that match a baseline job
`reporting.tracker_join` matches tracker rows to `facts` by key (`reporting.py:825-842`). A hand-added tracker row for a job that is now only in Identity changes `join_counts` between old and new. Low probability; name it as a declared parity difference class rather than let it flap the clock.

### Pitfall 10: Quota
Documented limits: 300 read and 300 write requests per minute per project, 60 per minute per user per project; 2 MB recommended payload; requests over 180 s time out [CITED: developers.google.com/workspace/sheets/api/limits]. The phase adds about 2 reads (Identity, Tally) and a few writes per run on top of the measured peak of 12.4 reads/min (STATUS L138 note, "quota ~60"), so quota is not the constraint; payload size is.

## Code Examples

### Atomic tab swap (raw body; gspread `Spreadsheet.batch_update(body)`)
```python
# Source: Google Sheets API spreadsheets.batchUpdate (atomic, ordered) + updateSheetProperties as built in gspread Worksheet.update_title
body = {"requests": [
    {"updateSheetProperties": {"properties": {"sheetId": events_id, "title": "Events_Legacy"}, "fields": "title"}},
    {"updateSheetProperties": {"properties": {"sheetId": new_id, "title": "Events"}, "fields": "title"}},
]}
sh.batch_update(body)
```

### Whole-sheet warning-only protection (creation time, inside the cosmetic try/except)
```python
# Source: ProtectedRange reference (unbounded range = protected sheet; editors ignored with warningOnly)
sh.batch_update({"requests": [{"addProtectedRange": {"protectedRange": {
    "range": {"sheetId": ws.id}, "warningOnly": True,
    "description": "Identity: posting IDs used for dedupe. A hand edit can make old jobs look new.",
}}}]})
```

### Descending contiguous deleteDimension requests
```python
# Source: gspread Worksheet.delete_dimension (startIndex = row - 1, endIndex = last row); rows are 1-based sheet rows
def delete_requests(sheet_id: int, rows: list[int]) -> list[dict]:
    runs, start = [], None
    for r in sorted(rows):
        if start is None or r != prev + 1:
            if start is not None: runs.append((start, prev))
            start = r
        prev = r
    if start is not None: runs.append((start, prev))
    return [{"deleteDimension": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": a - 1, "endIndex": b}}}
            for a, b in reversed(runs)]  # bottom first so earlier indexes stay valid
```

### Identity chunking (shape; cap and escaping are the testable parts)
```python
CELL_CHARS = 40_000  # storage_report.COMPACT_CELL_CHARS
def enc(kind: str, id_: str) -> str: return kind + id_.replace("%", "%25").replace(",", "%2C")
def chunks(entries: list[str]) -> list[list[str]]:
    out, cur, n = [], [], 0
    for e in entries:
        if cur and n + len(e) + 1 > CELL_CHARS: out.append(cur); cur, n = [], 0
        cur.append(e); n += len(e) + 1
    return out + ([cur] if cur else [])
```

### Subtract-the-retained merge (core of parity and reporting)
```python
folded = {k: max(0, tally[k] - retained.get(k, 0)) for k in tally}   # k = (run_id, run_at, dim_key)
negative = {k for k in tally if tally[k] < retained.get(k, 0)}        # a Tally write was lost: parity difference
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| D-43: `Daily` counters, delete baseline rows with an export | `Tally` per run, `Events_Legacy` tab swap, 7-day fold (D-57 amends) | CONTEXT 2026-10-29 | Parity per run, nothing deleted before the owner triggers it |
| D-03: revisit pruning at ~200k rows | Compaction closes the review | this phase | Events about 195,793 rows on 2026-10-28, passes 200k about 2026-10-29 (STATUS) |

**Deprecated/outdated:** the D-43 Daily-tab design and `.planning/codebase/*` details (stale by 22 files).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `values.batchUpdate` (gspread `ws.batch_update`) is not documented as atomic; design treats it as non-atomic | Pattern 5 | If it is atomic, the design is merely over-careful; if non-atomic and assumed atomic, a partial write could corrupt a chunk |
| A2 | A warning-only whole-sheet protection does not block service-account API writes (Google says warning-based protection lets every user edit after a prompt) | P3-04 / Pattern 2 | If writes fail, every poller run fails after deploy. Must be confirmed live on the first deploy (create the tab, write one row, read back) |
| A3 | The 50,000-character single-cell cap applies to API writes; documentation found only confirms it for Excel conversion, the 10M-cell limit is well sourced | Pitfall 4 | Cap stays 40,000 regardless, so low risk; the fake enforces 50,000 |
| A4 | Production posting IDs contain no `,` or `%` and no malformed (<3 segment) keys exist in Events | Pattern 2 | Escaping and the `unkeyable` class cover it; unknown real counts |
| A5 | A single `spreadsheets.batchUpdate` accepts a few hundred `deleteDimension` requests (no documented per-call request cap) | Pattern 8 | Fold fails; chunk smaller (the plan caps at ~500 and should make the cap a constant) |
| A6 | Sheets refuses to delete all non-frozen rows of a sheet (training memory); an Events tab always keeps operational rows, so not expected to bind | Pattern 8 | Edge case on a test Sheet with no operational rows |
| A7 | Minimum parity-checked runs per UTC day for a day to count (suggest 12 of 24) | Pattern 6 | Too low lets a day with outages count; too high may never reach the bar. Owner/planner choice |
| A8 | Identity growth about 5,000 IDs/day (about 70,000 characters/day, about two new chunk rows/day) is derived from D-43's 7.17 rows/board/day × 700 boards and an assumed ~14-character ID | Pattern 2 | Cell growth slightly different; the storage report measures it |
| A9 | RAW input of an all-digit string would be stored as text; the kind prefix makes the question moot | Pattern 2 | None if the prefix is used |
| A10 | 7 days means `Time <= now - 7 * 24 h` at fold time, not seven calendar days | Pattern 8 | Off-by-a-day detail retention; parity unaffected because reports use counts only |

## Open Questions

1. **Disposition in Identity (kind prefix) vs ID-only cells.**
   - What we know: CONTEXT says merge "as `seen`, with disposition"; D-43's layout has no disposition column.
   - What's unclear: whether the owner accepts the `b/f/s` prefix (about +1 character per ID, about +190k characters total) over three rows per board.
   - Recommendation: use the prefix; it also lets parity cross-check Identity against Tally.
2. **Meaning of "every run reports zero differences" when runs are missing.** Hourly schedule can skip runs. Recommend a minimum count per day (A7) and recording `runs` per day in the clock; record the chosen constant in D-57.
3. **Where the parity check's `Runs` footprint lives.** Recommended: run note + Discovery `storage` key (no new Runs columns). If the planner prefers a numeric `Storage_Diffs` column, update `RunRecord.from_row` and `tests/test_governors.py:269`.
4. **Protect `Events_Legacy` too?** Cheap (same request body) and prevents accidental edits of the restore source; not required by CONTEXT.
5. **Does the first poller run after deploy seed in one run?** About 190k IDs is about 2.7M characters (estimate A8) at about 1M characters per request: about 3-5 writes, well inside a run. Confirm with the largest board (the D-43 largest board needed 5 chunks).
6. **Dashboard 14-day chart / trend `first_any`** (`reporting.py:460`) uses days that have any counter; Tally contributions make baseline-only days "recorded". This matches today's behavior (baseline rows already create days) but should be pinned by a test.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python venv (`.venv/bin/python`) | tests, tooling | yes | 3.12.13 | none needed |
| gspread | Sheets client | yes | 6.2.1 | none needed |
| `python -m unittest discover -s tests` | verification | yes | 633 tests, OK, 5.3 s [VERIFIED: ran this session] | none needed |
| Google Sheets credentials (service account, Sheet ID) | live verification of tabs, protection, swap, fold | no (not available to agents; AGENTS rule 6) | none | All Phase 3 live checks are owner-run or deferred; label mocked vs live (AGENTS rule 5) |
| GitHub Actions dispatch | cutover and parity runs | not probed | none | Owner dispatches the workflow input |

**Missing dependencies with no fallback:** none for planning or offline execution.
**Missing dependencies with fallback:** live Sheets/Actions checks (the plan must include owner checkpoints and STATUS labels "mocked" until observed).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `unittest` (stdlib), Python 3.12.13 |
| Config file | none (`python -m unittest discover -s tests`) |
| Quick run command | `.venv/bin/python -m unittest tests.test_compact tests.test_storage_parity -q` |
| Full suite command | `.venv/bin/python -m unittest discover -s tests` (633 tests today, about 5 s) |

### Phase Requirements to Test Map (success criteria)
| Criterion | Behavior | Test Type | Automated Command | File Exists? |
|-----------|----------|-----------|-------------------|-------------|
| SC1a | Identity round trip: chunks stay under 40,000 characters (largest-board case, 5,050 IDs), escaping, stem round trip incl. mixed-case Lever, count column | unit | `python -m unittest tests.test_compact.IdentityCodecTests` | Wave 0 |
| SC1b | Each run writes exactly one Tally row with the dims; poller on compact storage (Events without baseline rows) detects no seen job as new and sends no alert twice across two runs | integration (Harness + CsvState) | `python -m unittest tests.test_storage_pipeline` | Wave 0 |
| SC1c | `ensure()` creates `Identity`/`Tally` hidden and issues one `addProtectedRange` with `warningOnly: true` and an unbounded range; tolerant of fakes without `batch_update` | unit (shared fake) | `python -m unittest tests.test_hunter.SheetTests tests.test_compact.EnsureTests` | extend existing |
| SC2a | `--storage-parity` reports zero differences on a consistent synthetic ledger (seen set, state counts, Dashboard summary, pilot reconcile, storage counts) | unit | `python -m unittest tests.test_storage_parity.CleanLedgerTests` | Wave 0 |
| SC2b | Mutation checks: drop an ID, drop `date` from Tally, wrong run id, lost Tally row, extra Identity ID each produce a named difference | unit | `python -m unittest tests.test_storage_parity.MutationTests` | Wave 0 |
| SC2c | Parity clock: three complete UTC days, admission required, a difference resets, missing-run day does not count; run marked degraded (`degraded_reason` contains `storage`); Dashboard "ready to cut over" and NEEDS ATTENTION row | unit | `python -m unittest tests.test_storage_parity.ClockTests tests.test_reporting` | Wave 0 + extend |
| SC3a | Cutover refuses unless the bar is met and a fresh parity is clean; swap body is one `batchUpdate` with the two ordered renames; `Events_Legacy` retained hidden; `ensure()` refuses to recreate a missing `Events` | integration (shared fake) | `python -m unittest tests.test_storage_cutover` | Wave 0 |
| SC3b | After cutover every figure equals the pre-cutover figure (parity run on the swapped state); fold deletes only filtered/stale rows older than 7 days whose ID is in Identity, descending `deleteDimension`, nothing else; half-folded run counts once | integration | `python -m unittest tests.test_storage_cutover.FoldTests` | Wave 0 |
| SC3c | Storage report prints rows, allocated cells (from metadata), load time before/after and daily cell growth; growth falls by about an order of magnitude on the multi-week simulation | unit/simulation | `python -m unittest tests.test_storage_report tests.test_allocation_correctness` | extend |
| SC4 | Interrupted baseline: inject a failure after chunk k of a multi-chunk board; next run has zero `pending`/alert events for that board and the board ends baselined; seed redo is idempotent | integration | `python -m unittest tests.test_storage_pipeline.InterruptedBaselineTests` | Wave 0 |
| P3-10/11 | Dashboard summary equal in dual, simulated-compact and post-cutover modes, including 14-day trend and rehearsal exclusion; per-job-detail-unavailable line present | unit | `python -m unittest tests.test_reporting.CompactParityTests` | extend |
| Deploy | Workflow inputs, `REQUIRE_TELEGRAM` expression, poller `if:` list | static | `python -m unittest tests.test_deployment` | extend |

### Sampling Rate
- **Per task commit:** the quick command plus the touched module's test file (seconds).
- **Per wave merge:** full suite (`python -m unittest discover -s tests`), all offline.
- **Phase gate:** full suite green; mutation checks for the five parity mutations listed above; STATUS labels live items "mocked" until the owner runs them.

### Wave 0 Gaps
- [ ] `tests/fake_sheets.py` — in-memory Spreadsheet/Worksheet implementing `worksheets/worksheet/add_worksheet`, `get_all_values`, `append_rows`, `batch_update` (values), `update`, spreadsheet `batch_update` for `deleteDimension`/`updateSheetProperties`/`addProtectedRange`, `fetch_sheet_metadata` (grid sizes), 50,000-character cell and ~2 MB request caps, 10M allocated-cell cap, fault injection ("fail the Nth write")
- [ ] `tests/test_compact.py`, `tests/test_storage_parity.py`, `tests/test_storage_pipeline.py`, `tests/test_storage_cutover.py`
- [ ] A synthetic ledger builder (admission wave, steady days, rehearsal run, pre-run-id rows) shared by parity and report tests
- [ ] Harness change in `tests/test_core.py`: `events()`/`states()` read through `load_ledger()`; no framework install needed

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Service account only (existing) |
| V3 Session Management | no | — |
| V4 Access Control | yes | Warning-only whole-sheet protection on `Identity`; hidden tabs; writer lease; cutover is an owner-dispatched workflow input that refuses unless the bar is met |
| V5 Input Validation | yes | Identity codec escapes `,` and `%`, caps cells at 40,000 characters, rejects malformed keys; workflow inputs are booleans (no string interpolation into `run:`) |
| V6 Cryptography | no | No secrets stored; Identity holds posting IDs only. A checksum for read-back is integrity, not security (use `hashlib` if needed) |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Hand edit of Identity makes old jobs look new (alert flood) | Tampering | Warning-only protection (P3-04), parity layer 1 (set equality and counts), degraded run on difference |
| Cutover run twice or on a stale parity | Tampering | Gate re-checks bar and runs a fresh parity in the same run; mode flag in `storage` key; swap refuses if `Events_Legacy` already exists |
| Ledger loss by a partial swap/fold | Denial of service | Atomic `spreadsheets.batchUpdate`; `ensure()` refuses to recreate `Events`; verify-before-delete; `Events_Legacy` kept |
| Secrets or personal data leaking into new tabs | Information disclosure | Identity/Tally carry IDs and counts only; no titles, URLs, resume text; the NEEDS ATTENTION row names keys, never tracker text (existing T-02-13 rule) |
| Workflow expression injection through a new input | Elevation of privilege | Boolean inputs only; same `${{ inputs.x && '--flag' || '' }}` shape as existing steps |

## Sources

### Primary (HIGH confidence)
- Local source, read this session: `ledger.py`, `state.py`, `pipeline.py`, `reporting.py` (L1-1157 relevant regions), `pilot.py`, `dashboard.py`, `storage_report.py`, `hunter.py` (L1335-1380, 1817-1870, 1940-2204), `boards.py` (identity), `.github/workflows/job_hunter.yml`, tests (`test_core.py` Harness, `test_hunter.py` fakes, `test_inventory.py` fakes, `test_deployment.py`, `test_storage_report.py`)
- Project docs: AGENTS.md, CONTEXT.md, DECISIONS.md (D-02, D-03, D-43, D-48, D-51, D-56), STATUS.md, PILOT_LOG.md
- gspread 6.2.1 source via `.venv/bin/python` introspection (`delete_dimension`, `update_title`, `add_protected_range`, `list_protected_ranges`, `batch_update`)
- Google Sheets API reference: spreadsheets.batchUpdate (atomic, ordered), `ProtectedRange` (unbounded range, warningOnly) — developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/batchUpdate and .../spreadsheets/sheets
- Google Sheets API usage limits — developers.google.com/workspace/sheets/api/limits (300/min per project, 60/min per user per project, 2 MB payload, 180 s timeout)

### Secondary (MEDIUM confidence)
- Google Workspace Updates, 10 million cell limit (2022), plus search results confirming blank cells and all tabs count — workspaceupdates.googleblog.com/2022/03/ten-million-cells-google-sheets.html
- Sheets guide page for batchUpdate (no values.batchUpdate atomicity statement) — developers.google.com/workspace/sheets/api/guides/batchupdate

### Tertiary (LOW confidence)
- 50,000-character per-cell figure: only a conversion-time statement was found; treated as a hard cap by the project (D-43, `storage_report.CELL_CHAR_LIMIT`)
- "Cannot delete all non-frozen rows" restriction: training memory

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; gspread surface verified from installed source
- Architecture: HIGH on the code integration points (read in full this session); MEDIUM on Sheets runtime behavior under warning-only protection and large batches (assumptions A1, A2, A5)
- Pitfalls: HIGH for those derived from code (key casing, `date` dimension, payload, `ensure()`), MEDIUM for Sheets edge cases

**Research date:** 2026-10-29
**Valid until:** 30 days for the design; the Events row count and growth figures go stale within days (re-run `--storage-report` before cutover)
