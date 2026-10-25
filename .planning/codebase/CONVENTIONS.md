---
last_mapped_commit: aa1bab2d3c3e37ac119cd898b2e4f42a50f276fe
last_mapped_at: 2026-10-24
---
# Coding Conventions

**Analysis Date:** 2026-10-24

## Naming Patterns

**Files:**
- Flat, lowercase, single-word module names at the repo root: `hunter.py`, `boards.py`, `pools.py`, `pipeline.py`, `reporting.py`, `dashboard.py`, `ledger.py`, `freshness.py`, `eligibility.py`, `state.py`, `inventory.py`, `search.py`, `discovery.py`, `pilot.py`, `watchdog.py`, `storage_report.py`, `meter.py`.
- No packages; `legacy/` is archived reference only and must not be imported or edited.
- Tests: `tests/test_<module>.py` (e.g. `tests/test_pools.py`, `tests/test_reporting.py`). Cross-cutting suites use descriptive names: `tests/test_allocation_correctness.py`, `tests/test_pilot_corrections.py`, `tests/test_core.py`.

**Functions:**
- `snake_case`. Module-private helpers are prefixed with a single underscore: `_prune_outages` in `pools.py`, `_day` and `_leave_monitoring` in `pools.py`, `_stamp` and `_stats` in `reporting.py`, `_split_list` in `hunter.py`.
- Public, cross-module helpers have no prefix: `parse_stamp` in `reporting.py`, `make_periods` in `reporting.py`, `title_gate` in `eligibility.py`.
- Verb-first names for actions (`refresh_*`, `load_*`, `make_*`, `parse_*`, `classify`, `admission_order`).

**Variables:**
- `snake_case`. Short local names are common for datetimes and records: `now`, `rec`, `ident`, `st`, `dt`, `prec`.
- Abbreviated module aliases at import: `import freshness as fr`, `import ledger as lg`, `import eligibility as el`, `import pipeline as pl`, `import state as st_mod`, `import boards as bd`, `import hunter as h`, `import discovery as dsc`.

**Constants:**
- `UPPER_SNAKE_CASE` at module top: `ACTIVITY_MIN_DAYS`, `MIN_OBSERVED_DAYS`, `T0` (tests), `SETTING_DEFAULTS` and `DEFAULT_SETTINGS` in `hunter.py`.
- Status and pool values are named string constants defined once in `boards.py` and imported by name: `STATUS_ACTIVE`, `STATUS_NEW`, `STATUS_VALIDATED`, `STATUS_DEFERRED`, `STATUS_DISABLED`, `POOL_ESTABLISHED`, `POOL_EXPLORATION`, `MONITORED`, `V_DEFERRED`, `GREENHOUSE`. Compare against the constant, never a retyped literal.

**Types and classes:**
- `PascalCase` classes: `BoardId`, `BoardRecord`, `ListedJob`, `JobIdentity` (`boards.py`), `EvalOutcome` (`pipeline.py`), `Settings` (`hunter.py`), `CsvState` (`state.py`), `Harness` and `HarnessCase` (`tests/test_core.py`).
- Records are `@dataclass` (about 40 uses across the package, e.g. `boards.py` 6, `pools.py` 6, `hunter.py` 6, `reporting.py` 3). Prefer a dataclass over a dict or tuple for any structured record that crosses a function boundary.

## Code Style

**Formatting:**
- No formatter config is committed (no `pyproject.toml`, `ruff.toml`, `setup.cfg` or `.flake8` at the root). Follow the existing hand style.
- Lines are long, commonly 120 characters or more; wrap only when a line becomes hard to read. Multi-line calls put several arguments per line rather than one per line.
- Four-space indentation, double-quoted strings are the common choice in code, single quotes appear in some places; match the surrounding file.
- `# fmt: skip` is used deliberately on multi-line `from ... import (...)` blocks and on dense tables so a formatter would not reflow them. It appears in about 20 files (e.g. `pools.py` 4, `pipeline.py` 12, `hunter.py` 19, `reporting.py` 21). Keep using it on such blocks rather than reflowing them.

**Linting:**
- No linter is configured in the repository. Escape hatches are written inline when needed:
  - `# noqa: E402` on imports that follow a `sys.path.insert(...)` (every test module and `tests/test_core.py`).
  - Other `# noqa` markers appear in `reporting.py` (3), `inventory.py` (2), `watchdog.py` (4), and `tests/test_reporting.py` (13).

**Type hints:**
- Every module starts with `from __future__ import annotations` (17 files), then uses PEP 604 unions and builtin generics: `str | None`, `list[str]`, `dict[str, Any]`.
- `typing` is used for `Any`, `Callable`, `Iterable` and `Optional`-free signatures. Annotate public function parameters and return values.

## Import Organization

**Order (observed):**
1. Module docstring (required, see Comments).
2. `from __future__ import annotations`
3. Standard library (`collections`, `copy`, `json`, `os`, `re`, `threading`, `time`, `logging`, `datetime`).
4. `from dataclasses import dataclass, field`, `from typing import ...`.
5. Local project modules, alphabetical-ish, as short aliases: `import eligibility as el`, `import freshness as fr`, `import ledger as lg`.
6. Named imports from one module grouped in a parenthesised block, often wrapped with `# fmt: skip`:
   ```python
   from boards import (
       MONITORED, POOL_ESTABLISHED, POOL_EXPLORATION, STAMP, STATUS_ACTIVE, ...
   )  # fmt: skip
   ```

**Path aliases:** None. The project runs flat from the repo root (or `tests/` via `sys.path.insert`).

**Circular imports:** avoided by keeping pure modules (`boards.py`, `freshness.py`, `ledger.py`, `eligibility.py`, `pools.py`) free of imports from the orchestrators (`hunter.py`, `pipeline.py`). Do not add an import from a lower module back up into `hunter.py`.

## Module Docstrings

Every module opens with a docstring that states its role and cites the governing rule by ID:

- `pools.py`: "Pure functions, no I/O ... Rules: SPEC.md 'Board registry' and DECISIONS.md D-23 (evidence), D-26 (pools), D-30 (open choices)."
- `boards.py`: "Identity is ATS + board + posting ID (SPEC.md). URLs are only a way to *find* an identity."
- `tests/test_core.py`: states what is mocked and what persists for real.

Follow this pattern for any new module: one paragraph of purpose, then the SPEC/DECISIONS references it implements.

## Error Handling

**Classify failures as transient or permanent. This is a core rule.**

- `pipeline.py` `EvalOutcome.kind` takes one of three values, documented in the dataclass docstring:
  - `"done"`: evaluated, record it.
  - `"transient"`: temporary failure (timeout, 5xx, rate limit). Retry next run. Do not write a permanent record.
  - `"failed"`: permanent-looking failure. Retry a bounded number of times, then abandon.
- A failure must leave later stages undone and retryable (AGENTS.md rule 4). Do not turn a transient error into a permanent "seen" or "evaluated" record.

**Exception hierarchy (define new ones beside the code that raises them):**
- `boards.py`: `BoardError(Exception)`, `BoardRateLimited(BoardError)`, `BoardGone(Exception)`.
- `hunter.py`: `TransientError(Exception)`, `ClosedPosting(Exception)`, `GroqAuthError(RuntimeError)`, `TrackerLayoutError(RuntimeError)`, `WriterBusy(Exception)`.
- `pipeline.py`: `FatalRunError(Exception)` (stops the run), `RetryableHydration(Exception)`.
- `search.py`: `SearchError` with subclasses `SearchAuthError` and `SearchLimitReached`.
- `inventory.py`: `InventoryError(Exception)`. `watchdog.py`: `UnreadableHealth(Exception)`.

**Best-effort blocks:** non-essential side work catches broadly and continues, with a comment saying so:

```python
except Exception as exc:  # best effort: the local ledger still applies
except Exception as exc:  # discovery is best-effort; polling must still happen
```

Use a broad `except Exception` only for these best-effort or top-level boundaries, and always say why in the comment. Otherwise catch the specific class.

**Crash marker:** `pipeline.py` sets `crashed = True` before a run body and clears it only when the body completes, so an exception or fatal stop leaves the flag set for the next run to see.

**Validation:** parsing functions return `None` for unusable input rather than raising in pure helpers (`parse_stamp` in `reporting.py`, `parse_instant` in `freshness.py`). Callers decide whether `None` is an error.

## Logging

**Framework:** standard library `logging`, module logger named after the module.
- `hunter.py`: `log = logging.getLogger("hunter")` (line 60).

**Operational output:** the CLI writes human reports and JSON with `print(...)`. `hunter.py` uses about 58 `print` or `log` calls, mostly for run summaries and `--report`/`--dashboard` output (e.g. `print(json.dumps({...}))` for one-off fixtures). Keep report text stable: the pilot and watchdog tooling read it.

**Never log secrets:** no keys, tokens or resume text. Settings are referenced by name only.

## Comments

**When to comment:**
- Explain *why* a rule exists and cite it: `# D-47: a pass over the ~21,000 validated boards`, `# AGENTS rule 4`-style references are used in docs and occasionally in code.
- Mark deliberate exceptions to a general rule. Example from `.github/workflows/inventory.yml`: `ALLOW_SMARTRECRUITERS_BULK: "1" # explicit user decision for the pilot (DECISIONS D-38)`.
- Mark time-sensitive or safety-relevant constants with their rationale (e.g. the one-hour slack on `ACTIVITY_MIN_DAYS`).

**Section banners:** long test modules use dashed banner comments to separate groups:

```python

# --------------------------------------------------------------------------- freshness

```

**Docstrings:** triple-quoted, describing behaviour and the contract. Test classes and helper functions usually carry a one-line docstring when the name alone is not enough.

## Function Design

**Size:** most helpers are short pure functions; orchestration lives in `hunter.py` (about 1,980 lines) and `pipeline.py` (about 630 lines). Prefer adding a pure function to `pools.py`, `reporting.py`, `freshness.py` or `eligibility.py` over growing the orchestrator.

**Parameters:**
- Keyword-only arguments for flags and time: `classify(dt, prec, *, now, board_gap, board_baselined, baseline_pass, ...)`.
- Time is always passed in (`now: datetime`), never read from the clock inside pure logic. Tests pin `T0` and advance it.

**Return values:**
- Structured results are dataclasses (`classify(...).cls` in tests), not bare tuples, when more than two values are returned.
- Pure evaluators return a new value; `pools.py` copies records with `copy` before modifying rather than mutating inputs.

## Module Design

**Purity boundary:**
- `pools.py` and `reporting.py` are pure: "Pure functions, no I/O", no network, no LLM, no search. `reporting.py` is read-only with respect to operational state.
- `dashboard.py` is read-only toward operational state; it renders and publishes the Dashboard tab only.
- I/O lives in `state.py` (CSV and Sheets adapters), `boards.py` adapters, `search.py`, and `hunter.py`.

**Exports:** no `__all__`. Modules are imported whole and accessed with their alias.

**Barrel files:** none. `hunter.py` re-exports nothing; tests import the module they test.

**Settings:** runtime knobs live in the Google Sheet Settings tab with defaults in `hunter.py` (`DEFAULT_SETTINGS`, `SETTING_DEFAULTS`). Add a new knob by adding a default there and a `Settings.from_values` read, and document it in `SPEC.md`.

## Change Discipline (project rules)

Sourced from `AGENTS.md` and `CLAUDE.md`. These are enforced by convention and review, not by tooling.

1. **Read first.** Before changing behaviour, read `SPEC.md` (contract), `DECISIONS.md` (why), `STATUS.md` (verified vs blocked).
2. **Flag conflicts before coding.** If a change conflicts with `SPEC.md` or `DECISIONS.md`, stop and say so.
3. **Docs in the same change.** When behaviour changes deliberately, update the affected `SPEC.md`, `DECISIONS.md` and `STATUS.md` entries in the same commit.
4. **Identity is ATS + board + posting ID.** Never dedupe on URL strings. Preserve identity-bearing URL parameters; drop tracking parameters.
5. **Keep seen / evaluated / alerted separate.** A failure leaves later stages undone and retryable.
6. **Freshness uses source publication time.** Never substitute update time, crawl time or search-engine dates. Keep publication, first observation, update and republication as separate fields.
7. **No score tuning or new features** until freshness and delivery are proven (`STATUS.md`).
8. **Tests stay offline** and must pass with `python -m unittest discover -s tests`.
9. **Secrets:** never read, print or commit `.env`, `Resume.pdf`, `resume.txt` or service-account JSON. Do not edit `.env`.

## Examples to Copy

**Pure helper with explicit time and a rule citation** (`pools.py` style):

```python
def _day(now: datetime) -> str:
    ...
```

**Record type** (`boards.py` style): frozen-by-convention dataclass with typed fields and defaults; construct with keywords.

**Fail-safe side effect:**

```python
try:
    ledger_update(...)
except Exception as exc:  # best effort: the local ledger still applies
    run.notes += f"..."
```
