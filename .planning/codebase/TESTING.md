# Testing Patterns

**Analysis Date:** 2026-10-14

## Test Framework

**Runner:**
- Python standard library `unittest` (no pytest, no tox, no nox).
- Config: none. Discovery is driven by the command line (`-s tests`). `tests/` has no `__init__.py`.
- Test count: one module, `tests/test_hunter.py`, about 640 lines, with about 15 `TestCase` classes.

**Assertion Library:**
- `unittest.TestCase` assertions: `assertEqual`, `assertIn`, `assertNotIn`, `assertIsNone`, `assertIs`, `assertTrue`, `assertFalse`, `assertRaises`, `assertLessEqual`, `assertIsNone`.
- Occasional bare `assert` for narrowing types (`assert ref is not None`, `assert rx is not None`, `assert row is not None`). These are used so that type checkers accept `ref.url` afterward.

**Mocking:**
- `unittest.mock` only (`mock.patch`, `mock.patch.object`, `mock.patch.dict`, `mock.Mock`, `mock.call`). No third-party mocking.

**Dependencies:** `requests` is imported in the test module only to construct `requests.HTTPError`, `requests.Timeout`, and `requests.ConnectionError`. No network is used.

**Run Commands:**
```bash
python -m unittest discover -s tests          # Run all tests (documented in README.md line 122)
python -m unittest tests.test_hunter -v       # Run one module verbosely (from repo root)
python -m unittest tests.test_hunter.GroqTests.test_429_on_primary_falls_back_to_8b   # Run a single test
python -m unittest discover -s tests -k Dedupe   # Run classes matching a substring
```
- Watch mode: Not available (no watcher configured).
- Coverage: Not configured. No `coverage` in `requirements.txt`. See Coverage below.

**CI:** `.github/workflows/job_hunter.yml` runs only `python hunter.py` on a schedule and does not run the test suite. Tests are a local-only gate today. Any change that affects behavior should be verified by running the commands above before committing.

## Test File Organization

**Location:**
- Separate directory: `tests/test_hunter.py`. Tests are not co-located with `hunter.py`.

**Naming:**
- File: `test_<module>.py`.
- Classes: `<Area>Tests` (`QueryTests`, `DedupeTests`, `SettingsTests`, `DateExtractionTests`, `HydrationErrorTests`, `ProcessTests`, `EndToEndTwoLayerTests`, `ParseTests`, `GroqTests`, `SheetTests`, `CsvTests`, `ServiceAccountTests`, `AlertTests`). Plus `FakeWorksheet`, `FakeSpreadsheet`, `FakeResponse` as fakes (not collected).
- Methods: `test_<behavior_in_snake_case>`, often descriptive sentences: `test_seen_urls_are_dropped_before_classification_or_any_work`, `test_429_on_primary_falls_back_to_8b`, `test_stale_boundary_is_strictly_older_than_max_age`.

**Structure:**
```
tests/
└── test_hunter.py
    ├── helpers (days_ago, settings, posting, lever_url, fake_get, FakeResponse, FakeWorksheet, FakeSpreadsheet, sheet_store, job)
    ├── # --- Layer 1  (search, query building, dedupe, settings)
    ├── # --- Layer 2  (dates, hydration errors, process pipeline, two-run end-to-end)
    ├── # --- Groq      (parsing, client retry/fallback)
    ├── # --- stores    (Google Sheet fake, CSV migration, service account, alerts)
    └── if __name__ == "__main__": unittest.main()
```

Test section markers follow the same `# ---` style used in `hunter.py` (see CONVENTIONS.md).

**Import setup:**
```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import hunter as h  # noqa: E402
```
The alias `h` is used throughout. Any new test must use the same alias.

## Test Structure

**Suite Organization:**
```python
class ProcessTests(unittest.TestCase):
    ref = h.AtsRef("lever", "https://jobs.lever.co/acme/x", "acme", "x", hint_title="Marketing Intern")

    def run_process(self, *, hydrate: object, groq: object = None, s: h.Settings | None = None) -> h.JobRow | None:
        s = s or settings()
        kw = {"side_effect": hydrate} if isinstance(hydrate, BaseException) else {"return_value": hydrate}
        with mock.patch.object(h, "hydrate_posting", **kw):
            return h.process(s, groq or mock.Mock(), self.ref, h.excluded_title_regex(s.excluded))

    def test_closed_is_recorded_with_score_zero_and_skips_groq(self) -> None:
        groq = mock.Mock()
        row = self.run_process(hydrate=h.ClosedPosting("404"), groq=groq)
        assert row is not None
        self.assertEqual((row.status, row.score), (h.STATUS_CLOSED, 0))
        groq.evaluate.assert_not_called()
```

**Patterns:**
- Class-level shared fixtures for immutable values (`ref = h.classify_url(...)` on the class body).
- A per-class helper method wraps the call under test with the patch setup (`run_process`, `client`, `search_bodies`, `raises`, `http`).
- Every test method has `-> None` annotation and a single behavior focus. Multiple related boundary cases in one test are acceptable when they form a table (see `test_status_by_threshold`, `test_stale_boundary_is_strictly_older_than_max_age`).
- Assertions compare tuples when checking several fields at once: `self.assertEqual((p.posted, p.posted_source), ("2026-09-16", "first_published"))`.
- Use `self.addCleanup(...)` when patches are started manually (`EndToEndTwoLayerTests.test_two_runs`).
- Nested `with` statements are combined with backslash continuation when many context managers are used (`test_no_tbs_cli_flag_disables_the_window`).

**Setup/Teardown:**
- No `setUp`/`tearDown` methods are used. Setup is done inline or by helper functions.
- Temporary files: `with tempfile.TemporaryDirectory() as d:` inside the test, so cleanup is automatic. Paths are passed into `h.CsvStore(Path(d) / "t.csv", Path(d) / "a.csv")` to isolate from the real `tracked_jobs.csv`.
- Environment isolation: `with mock.patch.dict(os.environ):` followed by popping the variables under test. The helper `settings()` pops every `SETTING_DEFAULTS` key so a developer's `.env` cannot leak in (`tests/test_hunter.py` lines 25-30). Repeat this pattern when a test depends on env defaults.

**Assertion Patterns:**
- Equality on whole structures: `self.assertEqual(sorted(set(calls)), sorted(...))`.
- Membership for queries: `self.assertIn(f"site:{site}", q)`.
- Boundary tables: `for age, stale in [(13, False), (14, False), (15, True), (200, True)]:` with the loop value passed as the `msg` argument to make failures identifiable.
- Negative assertions to prove skips: `groq.evaluate.assert_not_called()`, `page.assert_not_called()`, `self.assertNotIn("tbs", body)`.
- Exception type checks: `with self.assertRaises(ValueError):` for direct calls; `self.raises(exc)` helper returns the caught type for mapping tests.
- Count checks for side-effect proof: `self.assertEqual(spy.call_count, 1)` after `mock.patch.object(h, "classify_url", wraps=h.classify_url)`.

## Mocking

**Framework:** `unittest.mock`.

**Patterns:**

Patch a module-level function that performs I/O:
```python
with mock.patch.object(h, "_http_get", return_value=fake_get(both)):
    p = h._hydrate_greenhouse(ref)
```

Patch a class method for a whole test:
```python
mock.patch.object(h.GroqClient, "evaluate", lambda self, s, p: h.Evaluation(88, "Great fit.", "None"))
```

Patch time to make retry loops instant:
```python
with mock.patch.object(h.time, "sleep"):
    ev = c.evaluate(settings(), posting())
```
Always patch `time.sleep` in any test that exercises `_http_get`, `GroqClient.evaluate`, or `TokenBudget.wait`. Otherwise the backoff delays make the test slow.

Fake HTTP responses with a status code and optional body/headers:
```python
class FakeResponse:
    def __init__(self, status: int, body: dict | None = None, headers: dict | None = None, text: str = "") -> None:
        self.status_code, self._body, self.headers, self.text = status, body or {}, headers or {}, text

    def json(self) -> dict:
        return self._body
```
Use `FakeResponse` for `GroqClient` tests and `mock.Mock()` with `.json.return_value` for `requests` calls.

Sequence of responses for retry tests:
```python
c.http.post.side_effect = responses   # list of FakeResponse, consumed in order
```

Fake Google Sheet objects:
- `FakeWorksheet` holds `values` as a list of rows and records `append_rows` calls in `appended`. Its `__getattr__` makes cosmetic methods (`freeze`, `format`) no-ops and raises `AssertionError` for destructive methods (`update`, `clear`, `delete_rows`, `update_cell`, `batch_clear`). This enforces the append-only contract.
- `FakeSpreadsheet` holds tabs in a dict and records `deleted`.
- `sheet_store(sh)` builds a `SheetStore` without calling `__init__`, using `SheetStore.__new__` and setting `sh` and `sheet_url` directly. This avoids needing `gspread` or credentials.

Patch the entire pipeline's external dependencies for end-to-end tests:
```python
patches = [
    mock.patch.dict(os.environ, {"GROQ_API_KEY": "x", "GOOGLE_SHEET_ID": ""}),
    mock.patch.object(h, "make_store", return_value=store),
    mock.patch.object(h, "load_resume_file", return_value="r" * 300),
    mock.patch.object(h, "search_ats", return_value=hits),
    mock.patch.object(h, "hydrate_posting", side_effect=fake_hydrate),
    mock.patch.object(h.GroqClient, "evaluate", lambda self, s, p: h.Evaluation(88, "Great fit.", "None")),
]
for p in patches:
    p.start()
self.addCleanup(lambda: [p.stop() for p in patches])
```

**What to Mock:**
- Network calls: `requests.post` (Serper, Telegram, webhook), `requests.get` via `h._http_get`, `GroqClient.http`.
- Time: `time.sleep` on retry paths.
- Google Sheets: replace `make_store` with `CsvStore` pointing at temp files, or use `FakeSpreadsheet`.
- Resume file loading: patch `load_resume_file`.
- Expensive or external LLM calls: patch `GroqClient.evaluate` at the class level in pipeline tests.
- Per-ATS hydration in pipeline tests: patch `hydrate_posting`, not individual `_hydrate_*` functions.

**What NOT to Mock:**
- Pure parsing and normalization: `normalize_url`, `classify_url`, `parse_posted`, `parse_evaluation`, `build_queries`, `excluded_title_regex`, `_safe_cell`. Test these directly with real inputs.
- `CsvStore` in pipeline tests. It uses real files in a temp directory, so the migration, append, and dedupe behavior is exercised for real.
- `Settings` and `Config` construction. Use `settings()` and `Config.from_env()` with env isolation.
- `classify_url` in `test_seen_urls_are_dropped_before_classification_or_any_work`: it is wrapped with `wraps=` rather than replaced, so the real behavior still runs and the call count is observed.

## Fixtures and Factories

**Test Data Factories (module-level helpers):**
```python
def settings(**kw: object) -> h.Settings:
    with mock.patch.dict(os.environ):
        for key in h.SETTING_DEFAULTS:
            os.environ.pop(key.upper(), None)
        base = h.Settings.from_values({"Resume_Text": "r" * 300})
    return h.replace(base, **kw) if kw else base

def posting(**kw: str) -> h.Posting:
    base = dict(url="https://x", ats="lever", title="Marketing Intern", company="Acme",
                description="d" * 300, location="Remote", posted="")  # fmt: skip
    base.update(kw)
    return h.Posting(**base)  # type: ignore[arg-type]

LEVER_ID = "{}-e89b-12d3-a456-426614174000"

def lever_url(n: int, suffix: str = "") -> str:
    return f"https://jobs.lever.co/acme/{LEVER_ID.format(str(n) * 8)}{suffix}"

def days_ago(n: int) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=n)).isoformat()

def job(status: str = h.STATUS_APPLY, score: int | None = 88, url: str = "https://u", **kw: str) -> h.JobRow:
    return h.JobRow(status, score, kw.get("company", "Acme"), kw.get("title", "Marketing Intern"), "Remote", "good", "None", url, "2026-10-12")
```

Conventions for factories:
- Factories take `**kw` overrides and merge onto a valid default. A default must always be a valid, accepted record (for example, `posting()` has a 300-character description, above `MIN_JD_CHARS = 200`).
- Use `days_ago(n)` for any date-dependent assertion. Do not hard-code dates for staleness checks; the stale window is relative to `datetime.now()`.
- Use `lever_url(n)` to generate distinct, valid, stable URLs. Its UUID-shaped identifier uses repeated digits so it is readable in failures.

**Inline data:** Fixture payloads are inline dicts and strings, not separate files. There is no `fixtures/` or `conftest.py`. Example payloads are kept short and only include fields the test reads.

**Location:** All fixtures and factories live at the top of `tests/test_hunter.py`. If a new test file is added, either duplicate the small helpers or move them into a shared `tests/helpers.py` (not yet present).

## Coverage

**Requirements:** None enforced. No threshold, no coverage tool in `requirements.txt`.

**View Coverage (optional, not installed):**
```bash
python -m pip install coverage
python -m coverage run -m unittest discover -s tests
python -m coverage report -m --include=hunter.py
```

**Observed coverage of behavior (from reading the tests, not measured):**
- Well covered: URL normalization and dedupe, search query construction and word limits, date parsing and freshness boundaries, hydration error mapping (404/410, 429/5xx, timeouts), Groq 429 fallback and retry, JSON parse tolerance, Google Sheet bootstrap/dedupe/append-only behavior, CSV migration, Telegram message escaping, and an end-to-end two-run scenario.
- Not covered by tests:
  - The live HTTP paths of each ATS hydrator (`_hydrate_workable`, `_hydrate_smartrecruiters`, `_hydrate_page`) and their field mappings beyond the Greenhouse and Lever date cases.
  - `_hydrate_page` JSON-LD parsing and the meta-description fallback.
  - `SheetStore.append_jobs` against a real `gspread` client (only the fake is used).
  - `GroqClient` pacing (`_pace`) and the `FALLBACK_HOLD_SECONDS` window expiry.
  - `TokenBudget.wait` sleeping behavior.
  - `search_ats` paging beyond the first page and the all-queries-failed `RuntimeError`.
  - `send_alert` webhook path (only Telegram is tested).
  - `Config.from_env` for `SEARCH_PAGES`, `SERPER_NUM`, `MAX_JOBS_PER_RUN`, and `LLM_MIN_INTERVAL_SECONDS`.
  - `_ld_location`, `_join_places` with mixed inputs, `load_resume_file`.
  - The `main()` `--url` flag and `--dry-run` flag.

## Test Types

**Unit Tests:**
- The majority of the file. Each test targets one pure function or one method with its external calls mocked.
- Input shapes are realistic (real ATS JSON field names, real Google query strings, real date formats such as `"2026-09-16T12:07:31-04:00"` and epoch milliseconds).

**Integration Tests:**
- `EndToEndTwoLayerTests.test_two_runs` runs `h.main([])` twice over a temporary CSV store with the network and LLM patched. It asserts on the tracker file, the archive file, the dedupe set, and the second run touching only the transiently failed URL. This is the only test that exercises the full pipeline.
- `SheetTests` exercises `SheetStore` methods against `FakeSpreadsheet`, which is an integration of store logic with a fake transport, not a live Sheet.

**E2E Tests:** Not used. No test calls Serper, Groq, Telegram, Google Sheets, or any ATS. Live verification is done by running `python hunter.py` or `python hunter.py --url <job-url> --dry-run` manually (the `--dry-run` flag suppresses tracker writes and alerts).

## Common Patterns

**Async Testing:** Not applicable. The code is synchronous.

**Error Testing:**
```python
def http(self, code: int) -> requests.HTTPError:
    return requests.HTTPError(f"HTTP {code}", response=mock.Mock(status_code=code))

def test_404_and_410_are_closed(self) -> None:
    self.assertIs(self.raises(self.http(404)), h.ClosedPosting)
    self.assertIs(self.raises(self.http(410)), h.ClosedPosting)
```
Use `self.raises(exc)` to test exception translation through `hydrate_posting`. Use `assertRaises` for direct calls where the exception is the expected output.

**Negative and boundary tests:**
```python
for bad in ["", "nope", '{"verdict":"x"}', "[1]", '{"score": null}']:
    with self.assertRaises(ValueError):
        h.parse_evaluation(bad)
```
Pair every positive behavior test with a negative case that shows the guard works (for example, `test_unknown_date_is_not_blocked` alongside the stale tests).

**Idempotence and deduplication:** Test by running the same input twice (`test_two_runs`) and asserting that the second run makes no calls. Use `calls.clear()` between runs.

**Environment-sensitive tests:** Always wrap in `mock.patch.dict(os.environ)` and pop the relevant keys. Example: `test_search_tbs_defaults_to_three_day_window` pops `SEARCH_TBS` before reading `Config.from_env()`.

**Log/formatting checks:** Check user-visible strings by substring: `self.assertIn("&lt;Intern&gt;", text)`, `self.assertTrue(row.status.startswith("Stale"))`.

## Writing New Tests

1. Add the test to the class that matches the behavior's layer. If none fits, add a new `XxxTests(unittest.TestCase)` class under the matching `# ---` section marker.
2. Use `h.` for everything from `hunter`. Use the factories `settings()`, `posting()`, `job()`, `lever_url()`, `days_ago()`.
3. Isolate environment with `mock.patch.dict(os.environ)` and filesystem with `tempfile.TemporaryDirectory()`.
4. Patch `time.sleep` for any retry path.
5. Patch `_http_get` for per-ATS hydrators and `GroqClient.evaluate` for pipeline tests; never make a real network call.
6. Annotate the method `-> None`.
7. Run the full suite: `python -m unittest discover -s tests`.
8. For a new ATS adapter, add: a classify case in `test_classify_all_supported_ats`, a field-mapping test patterned on `test_greenhouse_prefers_first_published_over_updated_at`, and a closed-posting case in `HydrationErrorTests` if the API returns 404 differently.

---

*Testing analysis: 2026-10-14*
