## Deferred Items

- `python -m unittest tests.test_hunter` (module run on its own) errors in `MovedColumnTests.test_a_missing_tracker_header_is_listed_under_needs_attention`: `from test_core import T0` fails because `tests/` is not on `sys.path` outside `unittest discover`. Pre-existing (found during plan 03-01, untouched by it); `python -m unittest discover -s tests` passes.
  status: open
- `storage_report.py` repeats `COMPACT_CELL_CHARS` and `classify()`, now also defined as `compact.IDENTITY_CELL_CHARS` and `compact.identity_class` (plan 03-01 did not list `storage_report.py`). Make it import them in a later Phase 3 plan.
  status: resolved (plan 03-03: `COMPACT_CELL_CHARS = compact.IDENTITY_CELL_CHARS`, `classify` calls `compact.identity_class`)
- Compact-mode count loss (from plan 03-01, left by plan 03-02): an interrupted compact-mode Identity write leaves durable IDs with no Tally count, and a compact-mode baseline has no Events row to re-derive it from. The in-run repair and check (plan 03-02) cover dual mode only. Decide in plans 03-06/03-07 how the compact-mode checks use `Ledger.negative()` and how a lost count is reported.
  status: open
