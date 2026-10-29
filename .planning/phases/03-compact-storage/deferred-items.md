## Deferred Items

- `python -m unittest tests.test_hunter` (module run on its own) errors in `MovedColumnTests.test_a_missing_tracker_header_is_listed_under_needs_attention`: `from test_core import T0` fails because `tests/` is not on `sys.path` outside `unittest discover`. Pre-existing (found during plan 03-01, untouched by it); `python -m unittest discover -s tests` passes.
  status: open
- `storage_report.py` repeats `COMPACT_CELL_CHARS` and `classify()`, now also defined as `compact.IDENTITY_CELL_CHARS` and `compact.identity_class` (plan 03-01 did not list `storage_report.py`). Make it import them in a later Phase 3 plan.
  status: open
