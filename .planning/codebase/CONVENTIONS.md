# Coding Conventions

**Analysis Date:** 2026-10-14

## Scope of Analysis

The active code is two Python files:
- `hunter.py` (single-module application, about 1,440 lines)
- `tests/test_hunter.py` (offline unit tests, about 640 lines)

Supporting files: `requirements.txt`, `README.md`, `.github/workflows/job_hunter.yml`, `.gitignore`.
The `legacy/` directory is an archived earlier version and is not a style reference.

No formatter, linter, or type-checker config is present (no `pyproject.toml`, `setup.cfg`, `.flake8`, `ruff.toml`, `.pylintrc`, `mypy.ini`, `.pre-commit-config.yaml`). Conventions below are inferred from the code. The `# fmt: skip` markers (11 occurrences across both files) and the consistent black/ruff-style wrapping indicate an auto-formatter with a line length of about 120 was used at some point. Lines longer than 120 characters exist (21 lines; max 129), so the limit is not enforced.

## Naming Patterns

**Files:**
- Single lowercase module names: `hunter.py`, `tests/test_hunter.py` (`test_` prefix for tests).
- Data files use `snake_case` or dotted names: `tracked_jobs.csv`, `tracked_jobs.gemini-scored.csv`, `seen_archive.csv` (created at runtime).

**Functions:**
- `snake_case` verbs: `build_queries()`, `search_ats()`, `parse_posted()`, `classify_url()`, `hydrate_posting()`, `pending_refs()`, `process()`, `send_alert()`.
- Private helpers are prefixed with a single underscore: `_hydrate_greenhouse()`, `_hydrate_lever()`, `_http_get()`, `_html_to_text()`, `_split_list()`, `_safe_cell()`, `_now()`, `_posted_iso()`, `_page_date_posted()`, `_style()`, `_status_dropdown()`.
- Per-ATS adapters follow `_hydrate_<ats>` naming (`greenhouse`, `lever`, `ashby_api`, `workable`, `smartrecruiters`, `page`). Dispatch lives in `_hydrate()` at `hunter.py` around line 694.
- Store methods are verb-first: `load_settings()`, `seen_urls()`, `append_jobs()`, `append_archive()`, `bootstrap()`.

**Variables:**
- `snake_case`. Short names are used for local, well-scoped values: `ref`, `ev`, `cfg`, `s` (Settings), `h` (module alias in tests), `ws` (worksheet), `sh` (spreadsheet), `resp`, `exc`, `m` (regex match).
- Walrus operator is used for regex matches in conditions: `if m := _GH_PATH.match(path)` (`hunter.py` line 285).

**Constants:**
- `UPPER_SNAKE_CASE` at module level: `TRACKER_COLUMNS`, `ATS_SITES`, `SERPER_URL`, `HTTP_TIMEOUT`, `MIN_JD_CHARS`, `DEFAULT_SEARCH_TBS`, `GROQ_ATTEMPTS`.
- Status strings are named constants, never inline literals: `STATUS_APPLY`, `STATUS_STRETCH`, `STATUS_FILTERED`, `STATUS_CLOSED`, `STATUS_ERROR` (`hunter.py` lines 69-74).
- Sheet tab names are constants: `SETTINGS_TAB`, `TRACKER_TAB`, `ARCHIVE_TAB`.
- Column indexes derived from names, not hard-coded: `URL_COLUMN = TRACKER_COLUMNS.index("Apply_URL") + 1`.
- Private module regexes are `_UPPER_SNAKE` with a leading underscore: `_GH_PATH`, `_UUID_PATH`, `_WORKABLE_PATH`, `_SMARTRECRUITERS_PATH`.

**Types and Classes:**
- `PascalCase` classes: `Settings`, `Config`, `AtsRef`, `Posting`, `SearchHit`, `Evaluation`, `TokenBudget`, `GroqClient`, `JobRow`, `SheetStore`, `CsvStore`.
- Exceptions end in `Error` or name a state: `TransientError`, `GroqAuthError`, `ClosedPosting`.
- Sheet column names in the tracker use `Underscore_Separated_Title_Case` (`Date_Found`, `AI_Score`, `Apply_URL`). These are user-facing and must not be renamed casually; `CsvStore.LEGACY` maps old names to new ones.

## Code Style

**Formatting:**
- Four-space indentation, double quotes for strings by default. Single quotes appear only inside f-strings or where the literal contains double quotes.
- Trailing commas on multi-line literals and call arguments.
- Wrapping: multi-line calls put each argument on its own line with a closing paren on its own line (see `requests.post(...)` in `search_ats`, `hunter.py` lines 388-393).
- Explicit `# fmt: skip` is used to keep aligned dict or request blocks on one line (`hunter.py` lines 1091-1095, 1103-1110; tests lines 34-35, 121-123).

**Linting:**
- Not configured. No `# noqa` in `hunter.py`; tests use `# noqa: E402` for the `sys.path` insert before `import hunter` and `# noqa: BLE001` for a broad except in a test helper.
- `# type: ignore[...]` is used sparingly in tests where the fake is intentionally wrong (`tests/test_hunter.py` lines 37, 226, 245, 273).

**Imports:**
- Every module begins with `from __future__ import annotations`. This allows PEP 604 unions (`str | None`) and builtin generics (`list[str]`, `dict[str, str]`) in annotations on Python 3.12 (the version pinned in `.github/workflows/job_hunter.yml`).
- Import order (stdlib, third-party, local), each group separated by a blank line:
  1. Standard library, alphabetized within the import section (`argparse`, `csv`, `html`, `json`, ...).
  2. Third-party: `requests`, `from bs4 import BeautifulSoup`.
  3. Optional third-party inside `try`/`except ImportError`: `from dotenv import load_dotenv` (`hunter.py` lines 34-39).
- `from x import y` is used for names from `datetime`, `collections`, `dataclasses`, `typing`, `pathlib`, `urllib.parse`.
- Heavy or optional imports are deferred: `import gspread` happens inside `SheetStore.__init__` (`hunter.py` line 1038), so the module imports without the Google dependency.
- No path aliases. All imports are absolute from the top-level directory. The test file inserts the repo root into `sys.path` explicitly.

**Section Dividers:**
- Long `# ---...--- name` comment bars divide logical sections in `hunter.py`: `# --- settings`, `# --- URLs`, `# --- search`, `# --- dates`, `# --- hydration`, `# --- Groq scoring`, `# --- tracker`, `# --- alerts`, `# --- pipeline`. Tests use the same style, with `# --- Layer 1` and `# --- Layer 2` to group test classes by pipeline layer.
- Within `SheetStore`, method groups are marked with `# -- bootstrap`, `# -- reads`, `# -- writes`.

## Type Annotations

- Fully annotated function signatures, including return types (`-> None`, `-> list[str]`, `-> Settings`).
- `dataclass(frozen=True)` for value objects: `Settings`, `Config`, `AtsRef`, `SearchHit`, `Posting`, `Evaluation`, `JobRow`. Use `dataclasses.replace()` to derive variants instead of mutation (`hunter.py` lines 733-740, 712, 1288).
- `Any` is used for untrusted JSON payloads and gspread objects (`ws: Any`, `data: Any`).
- `TYPE_CHECKING` is not used; no type-checker is configured.
- Class-level annotated attributes with defaults are used for dataclasses: `hint_title: str = ""`.

## Error Handling

**Strategy: typed exceptions map to pipeline outcomes.** Network and parse errors are translated into one of three buckets, which determines whether a job is recorded or retried:

| Exception | Meaning | Pipeline behavior |
|-----------|---------|-------------------|
| `ClosedPosting` | HTTP 404/410 | Recorded as `STATUS_CLOSED`, score 0 (`hunter.py` line 1298) |
| `TransientError` | timeout, 5xx, 429, connection error | Not recorded; `process()` returns `None`; retried next run |
| `GroqAuthError` | invalid API key | Re-raised; aborts the run with exit code 2 |
| `ValueError` / other | permanent per-job failure | Recorded as `STATUS_ERROR` with the message in `AI_Verdict` |

Source of the translation: `hydrate_posting()` (`hunter.py` lines 717-740) and `GroqClient.evaluate()` (lines 900-956).

**Patterns:**
- Raise specific exceptions from low-level helpers; catch broadly only at the job boundary. `process()` and the main loop (`hunter.py` lines 1292-1331, 1406-1426) catch `Exception`, log, and continue so that "a failure on one job never aborts the run".
- Re-raise the fatal exception before the broad catch: `except GroqAuthError: raise` precedes `except Exception` (lines 1327-1329, 1411-1412).
- Startup failures return an exit code instead of raising: `main()` returns `2` on configuration or startup errors (`hunter.py` lines 1370-1372).
- Cosmetic operations never fail a run. Sheet formatting and dropdowns are wrapped in `try/except Exception` and logged as warnings (`_style`, `_status_dropdown`, hiding the archive tab).
- Notifications are fire-and-log: `counts["alerts"] += send_alert(...)` is inside a `try` that logs `"Alert failed for %s"` (lines 1400-1404).
- `raise_for_status()` is used on every outbound HTTP call; `_http_get()` implements up to 3 attempts with linear backoff for 429/5xx and aborts immediately on other 4xx (lines 490-506).
- Use `raise ... from exc` or `from None` when translating exceptions (`hunter.py` lines 725, 730, 709).
- Validation errors use `RuntimeError` for configuration problems ("GOOGLE_SHEET_ID is set but GOOGLE_SERVICE_ACCOUNT_JSON is empty") and `ValueError` for bad data.
- `assert` is used only for internal invariants, not user input (`hunter.py` line 505).

**Tolerant parsing:**
- External JSON is parsed defensively with `.get()` chains and `or ""` defaults (`data.get("title") or ""`). Parsing functions return an empty string or `None` instead of raising where a missing field is acceptable (`parse_posted()` returns `None`).
- `parse_evaluation()` strips code fences and falls back to slicing the first `{` to the last `}` before raising.

## Logging

**Framework:** standard library `logging`.

- Module logger: `log = logging.getLogger("hunter")` (`hunter.py` line 41). Use `log`, never `print`, inside library code.
- Configured only in `main()` with `logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")`.
- `log.info` for normal progress and per-job outcome. `log.warning` for recoverable failures that will be retried or skipped. `log.error` for fatal startup/auth failures. `log.exception` for unexpected errors inside the job loop, which includes the traceback.
- Use `%`-style lazy arguments, not f-strings, in log calls: `log.info("Search: %s", query)`.
- Log the URL with each per-job message so failures can be traced: `log.warning("Hydration failed for %s: %s", ref.url, exc)`.
- The pipeline's final summary uses a named-placeholder format string with a counts dict (`hunter.py` lines 1428-1432).
- Do not log secrets. Keys are read from the environment and sent in headers only; they never appear in log messages.

## Comments

**When to Comment:**
- Comments explain *why* a non-obvious choice exists, usually with a concrete external constraint. Examples:
  - `# Serper's free tier rejects num > 10; 0 = omit and use pages instead.`
  - `# Google ignores terms past ~32 words; keep a margin`
  - `# free tier tokens-per-minute budgets; a 429 from Groq still wins over these.`
  - `# Rows first, so a failed alert can never cause a duplicate row on the next run.`
- Inline trailing comments are common on config constants and dict entries (`MIN_JD_CHARS = 200`-style lines, `"tbs"` notes).
- Do not restate what the code does.

**Docstrings:**
- Triple-double-quoted docstrings on modules, public classes, and most public functions. Format is a short imperative or descriptive first line; longer detail follows after a blank line.
- Module docstring describes the pipeline stages with `->` arrows (`hunter.py` lines 2-11). Keep that pattern when extending the pipeline.
- Tests have a one-line module docstring stating how to run them (`tests/test_hunter.py` line 1).
- No JSDoc/Sphinx-style `:param:` or `Args:` blocks are used.

**Inline Markers:**
- No `TODO`/`FIXME` comments were found in either file.

## Function Design

**Size:** Most functions are under 40 lines. `main()` (about 90 lines) and `build_queries()` are the largest; `main()` is organized as numbered phases (startup, search, pending, process loop, flush).

**Parameters:**
- Keyword-only arguments are used to make boolean flags explicit: `build_queries(s, *, limit=..., max_queries=...)`, `_http_get(url, *, accept=...)`, `Config` built via `from_env()`.
- Pass dependencies explicitly rather than reaching for globals: `process(s, groq, ref, excluded)`, `send_alert(cfg, row, sheet_url)`.
- Default parameters for paths enable tests to inject temporary files: `CsvStore(path=TRACKER_PATH, archive=ARCHIVE_PATH)`.

**Return Values:**
- Return `None` to mean "skip, do not record" (`process()` for transient failures) and a populated object otherwise. Callers check `if row is None` explicitly.
- Factory classmethods for configuration: `Settings.from_values(raw, resume_fallback=...)` and `Config.from_env()`.
- Collections are returned as concrete types (`list`, `set`, `dict`), and dedupe preserves order with `dict.fromkeys(...)` (`_split_list`, `_join_places`).

**Local helpers:**
- Inner functions for scoped logic are normal: `core()` and `with_exclusions()` inside `build_queries()`, `row()` inside `process()`, `flush()` inside `main()`, `pick()` inside `Settings.from_values()`, `env()` inside `Config.from_env()`.

## Module Design

**Exports:**
- Single-module design. No `__all__`. Everything public is importable as `hunter.<name>`; tests rely on this (`import hunter as h`).
- Entry point is `if __name__ == "__main__": sys.exit(main())`.
- CLI flags are declared with `argparse` inside `main()`, with `help=` strings for each flag (`--url`, `--dry-run`, `--no-tbs`).

**Barrel Files:** Not applicable. No package `__init__.py`.

**Layering inside the module (by section comment, not by package):**
1. Settings and config dataclasses
2. URL classification and normalization
3. Search (Serper)
4. Date parsing
5. Hydration (one function per ATS)
6. Groq scoring (`GroqClient`, `TokenBudget`, prompt)
7. Tracker stores (`SheetStore` for Google Sheets, `CsvStore` for local fallback)
8. Alerts
9. Pipeline and `main()`

Keep new code within the matching section. Adding a new ATS means a new `_hydrate_<name>` function, a regex in the URL section, an entry in `ATS_SITES`, and a case in `_hydrate()`.

**Dual backends:** Every store operation exists on both `SheetStore` and `CsvStore` with the same signature. Any new persistence method must be implemented on both.

## Data Handling Rules

- **Append-only tracker:** the script never calls update/clear on the tracker sheet. The test `FakeWorksheet.__getattr__` raises `AssertionError` if `update`, `clear`, `delete_rows`, `update_cell`, or `batch_clear` is called. Preserve this so user edits to `My_Status` and `User_Notes` survive.
- **Formula injection:** all user-visible text cells go through `_safe_cell()`, which prefixes `=`, `+`, `-`, `@`, tab, or CR with `'`.
- **Untrusted content:** job descriptions and resumes are treated as data. The system prompt explicitly tells the model not to follow instructions inside them (`SYSTEM_PROMPT`, `hunter.py` line 780). Wrap such content in XML-like tags as `build_messages()` does (`<resume>`, `<job>`).
- **HTML escaping:** Telegram messages escape every interpolated value with `html.escape` (`send_alert`, `hunter.py` lines 1215-1230). Values from the ATS are also unescaped with `html.unescape` before stripping tags.
- **Secrets:** read only via `os.getenv` in `Config.from_env()`. `.env` is loaded by `python-dotenv` when present (`hunter.py` lines 34-39). Never print or log values.

## Example: Canonical Shapes

Settings-style dataclass with derived variant:
```python
@dataclass(frozen=True)
class Settings:
    resume: str
    roles: list[str]
    ...

    @property
    def stale_status(self) -> str:
        return f"Stale (>{self.max_age_days}d old)"
```

Per-ATS adapter returning a normalized value object:
```python
def _hydrate_lever(ref: AtsRef) -> Posting:
    data = _http_get(LEVER_API.format(company=ref.company, posting_id=ref.job_id), accept="application/json").json()
    return Posting(
        url=ref.url,
        ats="lever",
        title=data.get("text") or "",
        ...
    )
```

Error translation at the boundary:
```python
try:
    posting = hydrate_posting(ref)
except ClosedPosting:
    log.info("Closed (404/410): %s", ref.url)
    return JobRow(STATUS_CLOSED, 0, ref.company, ref.hint_title, "", "Posting is closed or removed.", "", ref.url)
except TransientError as exc:
    log.warning("Transient hydration failure (will retry next run) for %s: %s", ref.url, exc)
    return None
```

## Guidance for New Code

- Put new constants at module level in the matching section, in `UPPER_SNAKE_CASE`, with a trailing comment for units or external limits.
- Use the existing exception types; do not introduce bare `except:`.
- Use `log` with `%`-style arguments; do not add `print`.
- Keep the dataclass style: `frozen=True`, typed fields, defaults only for optional values.
- Add type annotations to every new function.
- Run the offline test suite after changes (see `TESTING.md`).

---

*Convention analysis: 2026-10-14*
