"""Web search for board discovery: the Tavily client and the monthly credit ledger.

Search only RETRIEVES candidates (discovery.py explains why); nothing here classifies freshness.
Everything is injected (`post`, `get`, `sleep`) so request building, response normalisation, error
handling and budget arithmetic are testable offline.

Verified against Tavily's current API reference and against live calls (see DECISIONS.md D-36):
  * POST https://api.tavily.com/search, `Authorization: Bearer <key>`.
  * `include_domains` restricts results to a domain (there is no `site:` operator).
  * `start_date` (YYYY-MM-DD) is the date window. Live over `boards.greenhouse.io`: 95% of the job
    pages it returned were published by the ATS within 72 h, against 19% with no window. `time_range`
    only offers day/week/month/year (66% within 72 h). `search_depth=fast` with a window returned older
    jobs and fewer boards (0% within 72 h), so it is not used even though it costs the same.
  * Search is NOT paginated (no `page`/`offset`): one request returns at most `max_results` (20).
  * Credits: `basic`/`fast`/`ultra-fast` = 1, `advanced` = 2; the response reports the actual number
    when `include_usage` is set. `include_answer`, `include_raw_content` and images stay off.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

import requests

log = logging.getLogger("hunter")

TAVILY_API = "https://api.tavily.com"
PROVIDER = "tavily"
SEARCH_DEPTH = "basic"  # 1 credit; "advanced" costs 2 and adds nothing we use
REQUEST_CREDITS = {"basic": 1, "fast": 1, "ultra-fast": 1, "advanced": 2}  # documented cost per search
MAX_RESULTS = 20  # the API maximum; cost does not depend on it
DEFAULT_WINDOW_DAYS = 3
HTTP_TIMEOUT = 40
BUDGET_KEY = "search_budget"  # Discovery-tab key holding the monthly ledger

DEFAULT_MONTHLY_CREDITS = 1000  # the free ("Researcher") plan's monthly allowance
DEFAULT_RESERVE_CREDITS = 200  # kept back from scheduled discovery for manual tests and backfills


@dataclass(frozen=True)
class SearchHit:
    url: str
    title: str = ""
    date: str = ""  # Tavily's `published_date` when it has one (ATS pages usually have none); NEVER a publication time


class Page(list):
    """The normalised hits of one request plus the credits it cost."""

    def __init__(self, hits: Any = (), *, credits: int = 1) -> None:
        super().__init__(hits)
        self.credits = credits


class SearchError(Exception):
    """A search request failed. `fatal` stops the whole discovery run (every further request would fail too)."""

    fatal = False


class SearchAuthError(SearchError):
    fatal = True


class SearchLimitReached(SearchError):
    """HTTP 432/433: the key's or plan's usage limit is exhausted at Tavily."""

    fatal = True


# --------------------------------------------------------------------------- requests


def request_body(query: str, domain: str, *, window_days: int | None, today: date, depth: str = SEARCH_DEPTH) -> dict[str, Any]:
    """The /search body: one domain, no generated answer, no content extraction, usage reported.

    `window_days` becomes `start_date = today - window_days` (date granularity); None = no window
    (the manual backfill). `chunks_per_source` 1 keeps responses small; it does not change the cost."""
    body: dict[str, Any] = {
        "query": query, "search_depth": depth, "max_results": MAX_RESULTS, "include_domains": [domain],
        "include_answer": False, "include_raw_content": False, "include_images": False, "include_favicon": False,
        "include_usage": True, "chunks_per_source": 1,
    }  # fmt: skip
    if window_days:
        body["start_date"] = (today - timedelta(days=window_days)).isoformat()
    return body


def parse_page(data: Any, depth: str = SEARCH_DEPTH) -> Page:
    """Normalise a /search response into the internal result format (url, title, date).

    Credits are the response's own `usage.credits` when present, else the documented cost of the depth."""
    results = data.get("results") if isinstance(data, dict) else None
    hits = [
        SearchHit(str(r["url"]), str(r.get("title") or ""), str(r.get("published_date") or ""))
        for r in (results if isinstance(results, list) else [])
        if isinstance(r, dict) and r.get("url")
    ]
    usage = data.get("usage") if isinstance(data, dict) else None
    credits = usage.get("credits") if isinstance(usage, dict) else None
    return Page(hits, credits=credits if isinstance(credits, int) and credits >= 0 else REQUEST_CREDITS.get(depth, 1))


def search(
    api_key: str, query: str, domain: str, *, window_days: int | None, today: date | None = None, depth: str = SEARCH_DEPTH,
    post: Callable[..., Any] | None = None, sleep: Callable[[float], None] = time.sleep,
) -> Page:  # fmt: skip
    """One search request. A 429 is retried once after `Retry-After` (at most 30 s). Raises SearchError
    (SearchAuthError / SearchLimitReached are fatal for the run)."""
    if not api_key:
        raise SearchAuthError("TAVILY_API_KEY is not set")
    body = request_body(query, domain, window_days=window_days, today=today or date.today(), depth=depth)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    for attempt in (1, 2):
        try:
            resp = (post or requests.post)(f"{TAVILY_API}/search", headers=headers, json=body, timeout=HTTP_TIMEOUT)
        except requests.RequestException as exc:
            raise SearchError(f"{type(exc).__name__}: {exc}") from exc
        code = resp.status_code
        if code == 429 and attempt == 1:
            try:
                wait = min(30.0, float(resp.headers.get("Retry-After") or 5))
            except (TypeError, ValueError):
                wait = 5.0
            sleep(wait)
            continue
        if code == 401:
            raise SearchAuthError("Tavily rejected the API key (HTTP 401)")
        if code in (432, 433):
            raise SearchLimitReached(f"Tavily usage limit exceeded (HTTP {code})")
        if code >= 400:
            raise SearchError(f"HTTP {code}")
        try:
            return parse_page(resp.json(), depth)
        except ValueError as exc:
            raise SearchError("response was not JSON") from exc
    raise SearchError("rate limited (HTTP 429)")


def account_usage(api_key: str, *, get: Callable[..., Any] | None = None) -> dict[str, Any] | None:
    """Tavily's own view of the plan: `{"plan": str, "used": int, "limit": int | None, "key_used": int}`.
    GET /usage costs no credits (10 requests per 10 minutes). None when it cannot be read."""
    try:
        resp = (get or requests.get)(f"{TAVILY_API}/usage", headers={"Authorization": f"Bearer {api_key}"}, timeout=20)
        if resp.status_code != 200:
            return None
        data = resp.json()
        account, key = data.get("account") or {}, data.get("key") or {}
        used, limit = account.get("plan_usage"), account.get("plan_limit")
        if not isinstance(used, int):
            return None
        return {
            "plan": str(account.get("current_plan") or ""), "used": used, "limit": limit if isinstance(limit, int) else None,
            "key_used": key.get("usage") if isinstance(key.get("usage"), int) else 0,
        }  # fmt: skip
    except (requests.RequestException, ValueError, AttributeError):
        return None


# --------------------------------------------------------------------------- monthly ledger


@dataclass(frozen=True)
class RotationEstimate:
    slots: int
    requests_per_slot: float  # measured from the last discovery's per-query stats (pagination included); 1.0 when nothing is recorded
    credits_per_request: float  # measured from the ledger (credits / calls); the documented price when nothing is recorded
    slots_per_run: int
    runs_per_day: float
    measured: bool  # False: nothing has been spent yet, so these are the documented assumptions

    @property
    def credits_per_slot(self) -> float:
        return self.requests_per_slot * self.credits_per_request

    @property
    def days_per_pass(self) -> float:
        per_day = self.slots_per_run * self.runs_per_day
        return self.slots / per_day if per_day else float("inf")

    @property
    def credits_per_pass(self) -> float:
        return self.slots * self.credits_per_slot

    @property
    def credits_per_month(self) -> float:
        """What the scheduled rotation spends in 30 days at this pace."""
        return self.slots_per_run * self.runs_per_day * 30 * self.credits_per_slot


def rotation_estimate(
    slots: int, per_run_credits: int, runs_per_day: float, ledger: "SearchBudget", last_queries: list[dict[str, Any]] | None
) -> RotationEstimate:  # fmt: skip
    """How long one pass over every slot takes, from requests actually consumed (not from an assumed
    one request per slot): requests per slot come from the last discovery's per-query stats (every page
    counted), credits per request from the ledger. A run can start `per_run_credits / credits_per_slot` slots."""
    queries = [q for q in (last_queries or []) if isinstance(q, dict) and isinstance(q.get("pages"), int) and q["pages"] > 0]
    rps = sum(q["pages"] for q in queries) / len(queries) if queries else 1.0
    cpr = ledger.used / ledger.calls if ledger.calls else float(REQUEST_CREDITS[SEARCH_DEPTH])
    per_slot = max(rps * cpr, 0.001)
    return RotationEstimate(slots, rps, cpr, max(1, int(per_run_credits // per_slot)), runs_per_day, bool(queries and ledger.calls))


def month_of(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m")


@dataclass
class SearchBudget:
    """Credits spent on search this calendar month (UTC), shared by EVERY search path that goes through
    the pipeline (scheduled rotation, `--discover`, `--backfill`).

    Scheduled runs may use `cap - reserve`; manual runs may use up to `cap`. The local counter only sees
    requests made by this application. Tavily's own account counter (`/usage`, read when available) also
    sees other keys, projects and hand-made requests: the larger of the two wins, and the plan's own limit
    lowers the cap if it is smaller. Reset policy: the local count restarts when the UTC calendar month
    changes; Tavily's billing-cycle start is not documented in its API reference, so a different cycle
    day is covered only by the account counter."""

    month: str
    used: int = 0
    calls: int = 0
    by_path: dict[str, int] = field(default_factory=dict)
    cap: int = DEFAULT_MONTHLY_CREDITS
    reserve: int = DEFAULT_RESERVE_CREDITS
    account_used: int | None = None  # observed this run, not persisted
    account_limit: int | None = None
    limit_hit: bool = False  # Tavily answered 432/433 this month: nothing more is spent until the month rolls over
    rolled_from: str = ""  # previous month's label when this run found the ledger from an earlier month (not persisted)

    @classmethod
    def load(cls, raw: str | None, now: datetime, *, cap: int = DEFAULT_MONTHLY_CREDITS, reserve: int = DEFAULT_RESERVE_CREDITS) -> "SearchBudget":
        month = month_of(now)
        cap, reserve = max(0, cap), max(0, min(reserve, cap))
        try:
            data = json.loads(raw) if raw else {}
        except ValueError:
            data = {}
        if not isinstance(data, dict) or data.get("month") != month:
            old = data.get("month", "") if isinstance(data, dict) else ""
            return cls(month, cap=cap, reserve=reserve, rolled_from=str(old))
        by_path = data.get("by_path") if isinstance(data.get("by_path"), dict) else {}
        return cls(
            month, used=int(data.get("used") or 0), calls=int(data.get("calls") or 0),
            by_path={str(k): int(v) for k, v in by_path.items() if isinstance(v, int)}, cap=cap, reserve=reserve,
            limit_hit=bool(data.get("limit_hit")),
        )  # fmt: skip

    def to_json(self) -> str:
        return json.dumps(
            {"month": self.month, "used": self.used, "calls": self.calls, "by_path": self.by_path, "limit_hit": self.limit_hit},
            separators=(",", ":"),
        )

    @property
    def effective_cap(self) -> int:
        return min(self.cap, self.account_limit) if self.account_limit else self.cap

    @property
    def effective_used(self) -> int:
        return max(self.used, self.account_used or 0)

    def remaining(self, *, scheduled: bool) -> int:
        if self.limit_hit:
            return 0
        limit = self.effective_cap - (min(self.reserve, self.effective_cap) if scheduled else 0)
        return max(0, limit - self.effective_used)

    def charge(self, credits: int, path: str) -> None:
        self.used += credits
        self.calls += 1
        self.by_path[path] = self.by_path.get(path, 0) + credits

    def observe_account(self, usage: dict[str, Any] | None) -> None:
        """Fold in Tavily's own counter. A usage below the plan limit clears an earlier limit_hit."""
        if not usage:
            return
        self.account_used, self.account_limit = usage.get("used"), usage.get("limit")
        if self.limit_hit and self.account_used is not None and (self.account_limit is None or self.account_used < self.account_limit):
            self.limit_hit = False

    def summary(self) -> str:
        acct = "" if self.account_used is None else f"; Tavily account counter {self.account_used}/{self.account_limit if self.account_limit is not None else 'no limit'}"
        paths = ", ".join(f"{k} {v}" for k, v in sorted(self.by_path.items())) or "none"
        return (
            f"search credits {self.month}: {self.used} used locally of {self.cap} (scheduled runs stop at {self.cap - min(self.reserve, self.cap)}, "
            f"{self.reserve} reserved for manual runs); by path: {paths}{acct}"
        )
