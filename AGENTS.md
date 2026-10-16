# Agent instructions

Before changing any behavior, read in this order: `SPEC.md` (the contract), `DECISIONS.md` (why), `STATUS.md` (what is verified and what is blocked). `.planning/codebase/` holds a generated map of the code.

## Rules

1. **Flag conflicts first.** If a request, a bug fix or your own idea conflicts with `SPEC.md` or `DECISIONS.md`, stop and tell the user what conflicts and why before changing behavior. When behavior changes deliberately, update the affected docs in the same change.
2. **Freshness is the product.** Never use update time, crawl time or search-engine dates as publication time. Keep source publication, first observation, update and republication distinct. Never present unverified age as fresh.
3. **Identity is ATS + board + posting ID.** Never dedupe on URL strings. Preserve identity-bearing URL parameters; ignore tracking parameters.
4. **Keep seen / evaluated / alerted separate.** A failure must leave later stages undone and retryable. Do not turn transient errors into permanent records.
5. **Separate mocked from live.** Say which checks were mocked and which hit real services. Do not claim live verification of Sheets, Groq or Telegram without credentials.
6. **Secrets and personal data.** Never read, print or commit `.env`, `Resume.pdf`, `resume.txt` or service-account JSON. Do not edit `.env`.
7. **Do not tune scores or add features** until freshness and delivery are proven (see `STATUS.md`).
8. **Run `python -m unittest discover -s tests`** before finishing; keep tests offline.

## Layout

`hunter.py` entry/orchestration; `boards.py` (identity, adapters, registry), `inventory.py` (inventory import + validation), `freshness.py`, `ledger.py`, `eligibility.py`, `state.py`, `pools.py` (board evidence, pools, rebalance), `pipeline.py` core; `reporting.py` (pure operational summary) and `dashboard.py` (renders and publishes the Dashboard tab, read-only toward operational state); `tests/` offline tests; `legacy/` archived earlier version (reference only).
