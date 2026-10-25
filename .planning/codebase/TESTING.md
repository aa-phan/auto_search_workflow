---
last_mapped_commit: aa1bab2d3c3e37ac119cd898b2e4f42a50f276fe
last_mapped_at: 2026-10-24
---
# Testing Patterns

**Analysis Date:** 2026-10-24

## Test Framework

**Runner:**
- `unittest` (standard library). No pytest config is committed.
- Config: none. Discovery is set by the command below.

**Assertion Library:**
- `unittest.TestCase` assertions (`assertEqual`, `assertTrue`, `assertIsNone`, `assertRaises`, etc.).

**Mocking:**
- `unittest.mock` (`mock.patch`, `mock.patch.dict(os.environ)`). See Mocking.

**Run Commands:**

```bash
.venv/bin/python -m unittest discover -s tests   # Run all tests (525 offline, all pass as of 2026-10-24)
.venv/bin/python -m unittest tests.test_pools    # Run one module
.venv/bin/python -m unittest tests.test_pools.ReentryTests.test_name   # Run one test
```

- Use `.venv/bin/python` (the project virtualenv). Run from the repo root.
- No watch mode and no coverage tool is configured. Coverage is proven by mutation spot-checks, not a percentage.

## Test File Organization

**Location:** all tests live in `tests/`, separate from the source. Source modules sit at the repo root.

**Naming:**
- Files: `tests/test_<topic>.py`. Current files: `test_core.py`, `test_pools.py`, `test_reporting.py`, `test_hunter.py`, `test_inventory.py`, `test_discovery.py`, `test_search.py`, `test_pilot.py`, `test_pilot_corrections.py`, `test_watchdog.py`, `test_storage_report.py`, `test_deployment.py`, `test_allocation_correctness.py`.
- Classes: `*Tests` (e.g. `ClassifyTests`, `ActivityTests`, `ReentryTests`, `BoardColumnsTests`, `TitleGateVariantTests`) or `*Case` for base classes (`HarnessCase`).
- Methods: `test_<behaviour in words>`, often phrased as the expected outcome: `test_old_18_column_rows_load_with_unknown_evidence`, `test_there_are_32_columns_and_rows_match`.

**Structure:**

```
tests/
├── test_core.py               # Harness + HarnessCase; pipeline end-to-end with fakes
├── test_pools.py              # pure allocation/evidence functions
├── test_reporting.py          # pure summary against hand-built ledgers and real runs
├── test_hunter.py             # hunter.py settings, tracker, gates
├── test_inventory.py          # inventory import and validation
├── test_discovery.py          # discovery + search credit ledger
├── test_search.py             # Tavily search client (mocked HTTP)
├── test_pilot*.py             # pilot report and corrections
├── test_watchdog.py           # missed-run watchdog
├── test_storage_report.py     # read-only storage report
├── test_deployment.py         # workflow and config checks (reads YAML, no secrets)
└── test_allocation_correctness.py
```

**Test-import boilerplate:** every test module starts the same way. Insert the repo root onto `sys.path`, then import project modules with `# noqa: E402`:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import boards as bd  # noqa: E402
import pipeline as pl  # noqa: E402
```

## Test Structure

**Suite Organization:**

```python
class ReentryTests(HarnessCase):
    def test_board_returns_after_leaving_is_reentered(self) -> None:
        self.baseline(job(self.board.board, "1"))
        ...
        self.assertEqual(..., ...)
```

- Group by behaviour with a banner comment and one `*Tests` class per behaviour:
  ```python
  # --------------------------------------------------------------------------- freshness
  ```
- Pure-function tests inherit from `unittest.TestCase`. Pipeline tests inherit from `HarnessCase` (in `tests/test_core.py`), which gives each test a fresh temp state directory and a fresh `Harness`.

**Patterns:**
- **Setup:** `setUp` creates a `tempfile.TemporaryDirectory()`, registers `self.addCleanup(self._tmp.cleanup)`, then builds the harness. Never leave files behind; use the temp dir for any state.
- **Teardown:** handled by `addCleanup`. Do not write a `tearDown` that duplicates it.
- **Fixed time:** `T0 = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)` in `tests/test_core.py`. Build past times with `ago(minutes=, hours=, days=)` and advance the clock via the harness rather than calling `datetime.now()`.
- **Assertion:** `assertEqual` on the state the pipeline leaves behind (CSV rows, ledger fields, report text), not on internal call sequences, unless the call count *is* the behaviour (`self.calls[st.key]`).

**Shared helpers in `tests/test_core.py`:**
- `default_settings()` builds `h.Settings` with `mock.patch.dict(os.environ)` so the test never reads the real environment.
- `job(board, jid, title=..., published=..., ...)` builds a `bd.ListedJob` with a valid `bd.JobIdentity`.
- `done(status=..., score=..., ...)` builds a `pl.EvalOutcome` for a successful scorer result.
- `gate(title)` runs the real `el.title_gate` against the default settings.

## Harness (the end-to-end fake world)

`Harness` in `tests/test_core.py` wraps the **real** pipeline and the **real** CSV-backed `state.CsvState`, and replaces every external dependency:

| Dependency | Fake | Where configured |
|---|---|---|
| ATS listings | `Harness.listings: dict[board_key, list[ListedJob] | Exception]` | `fetch(board)` raises if the value is an exception |
| Scorer (LLM) | `Harness.plan: dict[job_key, list[EvalOutcome]]` (sequence per job) | `evaluate(ident, st)` pops the next outcome and counts calls |
| Alerts (Telegram) | `Harness.alerts` list; `alert_error` forces failure | |
| Tracker (Sheet tab) | `Harness.tracker` list; `tracker_error` forces failure | |
| Discovery | `Harness.discover_result` | |
| Clock | `Harness.now` (starts at `T0`) | advanced by `run()` |

Persistence is real: `Harness.tracked_keys` persists across runs, like the real tracker tab. Use the harness to inject a failure at a named stage and then assert that the next run retries that stage (AGENTS rule 4).

**Failure injection pattern:**

```python
self.w.listings[self.board.key] = RuntimeError("boom")   # fetch fails
self.w.alert_error = TransientError("timeout")           # alert stage fails
self.w.plan[self.key("1")] = [done(...), done(...)]      # scorer sequence
```

## Mocking

**Framework:** `unittest.mock`.

**Patterns:**

```python
with mock.patch.dict(os.environ):
    for k in h.SETTING_DEFAULTS:
        os.environ.pop(k.upper(), None)
    return h.Settings.from_values({"Resume_Text": "r" * 300})
```

- Patch environment with `mock.patch.dict(os.environ)` so changes are reverted automatically.
- Patch module attributes for network, sleep or external clients (`mock.patch.object(module, "name", fake)`), and restore them with `addCleanup` or a `with` block.
- Fake HTTP responses at the adapter boundary (e.g. the Tavily client in `search.py`, the ATS adapters in `boards.py`), not deep inside the logic.

**What to Mock:**
- Every network call: ATS list endpoints, Tavily, Groq/LLM scorer, Google Sheets, Telegram.
- Clock-dependent behaviour where needed beyond the harness `now`.
- Environment variables and any file outside the temp directory.
- Sleeps and rate-limit waits (keep the suite fast; the whole suite runs in about 5 seconds).

**What NOT to Mock:**
- The pipeline's own decision logic (`pipeline.py`, `pools.py`, `freshness.py`, `eligibility.py`, `ledger.py`). These are tested for real.
- CSV persistence (`state.CsvState`). The harness uses the real file store in a temp dir so the tests prove the on-disk outcome.
- Pure functions. Call them directly with explicit `now`.

**Live-vs-mock labelling:** a test that could reach a real service must not do so. State in the module docstring which parts are mocked and which hit real services. `tests/test_core.py` states: "Mocked end to end: fake ATS listings, fake scorer, fake alert channel. Persistence is the real CSV-backed state in a temp dir. See STATUS.md for what has been verified live." Report live verification separately in `STATUS.md` and `PILOT_LOG.md` (AGENTS rule 5). Do not claim live Sheets, Groq or Telegram verification from a mocked test.

## Fixtures and Factories

**Test Data:** built inline with factory helpers, not fixture files:

```python
def job(board: str, jid: str, title: str = "Marketing Intern", published: str = "", ...) -> bd.ListedJob:
    ident = bd.JobIdentity(ats, board, jid)
    return bd.ListedJob(ident, title, ident.url, location, published, ..., updated)
```

- Defaults make the common case one-liner; override only what the test is about.
- Resume and secret inputs are synthetic (`"r" * 300`). Never load `Resume.pdf`, `resume.txt` or `.env` in tests.

**Location:**
- Helpers live at the top of the test module that needs them, or in `tests/test_core.py` for pipeline-level helpers. There is no shared `conftest.py` or `tests/fixtures/` directory.

## Mutation Spot-Checks (how coverage is proven)

Line coverage is not measured. Each behaviour is proven by **mutation spot-checks** recorded in `DECISIONS.md` and `STATUS.md`:
1. Break one behaviour in source (e.g. remove the floor filter, ignore the mode, never release a trial).
2. Run the suite.
3. Confirm at least one test fails.
4. Restore the code.

Recent examples: "mutation checks (no floor filter, a `rebalance` prefix, ignoring the mode, never releasing) each fail the suite" (`DECISIONS.md` D-47 area). When adding behaviour, add the test, then run this check and record the result in `STATUS.md`. Do not edit a test to swallow a mutation.

## Coverage

**Requirements:** none enforced by tooling. The gate is that the suite passes and each new behaviour has a test that a mutation breaks.

**View Coverage:** not configured. To inspect manually, use `coverage run -m unittest discover -s tests` only if `coverage` is installed locally; it is not a project dependency.

## Test Types

**Unit tests:**
- Pure functions in `pools.py`, `freshness.py`, `eligibility.py`, `reporting.py`, `boards.py` (identity, URL handling), `search.py` (credit ledger).
- Direct calls with explicit `now` and hand-built records.

**Integration tests (offline):**
- `HarnessCase` subclasses in `tests/test_core.py` and `tests/test_pools.py` run the real pipeline over several polls with the harness (baseline, advance time, re-poll, assert on CSV rows and alerts).
- `tests/test_hunter.py` and `tests/test_inventory.py` run the real import and tracker-writing code against fakes.

**Deployment and config tests:**
- `tests/test_deployment.py` checks workflow and configuration files (e.g. `.github/workflows/*.yml`) for required secrets names and the concurrency group. It reads YAML text, never secret values.

**E2E tests:** not used. Live checks are manual and recorded in `STATUS.md` and `PILOT_LOG.md`.

## Common Patterns

**Async testing:** not applicable. The code is synchronous. Threads appear only in `boards.py` adapters; test them through their synchronous return values.

**Error testing:**

```python
with self.assertRaises(FatalRunError):
    ...
```

For retry behaviour, assert the *state after the failure* (row not written, flag still set, next run retries) rather than only the exception type.

**Time-dependent testing:**

```python
self.baseline(job(self.board.board, "1", published=ago(hours=2)))   # first poll, then +60 min
self.w.now = T0 + timedelta(days=8)                                  # age past ACTIVITY_MIN_DAYS
```

**Idempotence:** run the same poll twice with unchanged inputs and assert no duplicate tracker rows or alerts (see `tests/test_reporting.py` for the report-side version).

## Rules for New Tests

1. Keep every test offline. No network, no real Sheets, Groq or Telegram, no reads of `.env`, `Resume.pdf`, `resume.txt` or service-account JSON.
2. Use `tempfile.TemporaryDirectory()` plus `addCleanup` for any file.
3. Pin time with `T0` or explicit `now`; never depend on the wall clock.
4. Add the test to the closest existing `*Tests` class or a new `*Tests` class under the matching banner.
5. Run `.venv/bin/python -m unittest discover -s tests` before finishing. It must print `OK`.
6. Run at least one mutation spot-check on the new behaviour and record it in `STATUS.md` when the change is a deliberate behaviour change.

---

*Testing analysis: 2026-10-24*
