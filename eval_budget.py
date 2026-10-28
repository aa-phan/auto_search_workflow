"""Daily Groq token budget per model (D-50, MEAS-03). Pure: no I/O, no network.

The budget day is the UTC calendar day (a stand-in until a recorded `x-ratelimit-reset-requests` confirms
Groq's own reset). Counting basis is the `usage.total_tokens` Groq returns for each answer. Each model has its
own budget because Groq counts each model's tokens separately. The last `reserve_pct` percent of every budget
is spent only on verified-fresh jobs (P2-04). All arithmetic is integer.

The object is shared by the pipeline (restore at load, save at flush) and the Groq client (charge per answer),
and persisted as one JSON value in the hidden Discovery tab under `GROQ_BUDGET_KEY`."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

GROQ_BUDGET_KEY = "groq_budget"
FRESH_RESERVE_PCT = 20  # P2-04: the last 20% of each model's budget is for verified-fresh jobs only


def day_of(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _clean(budgets: dict[str, int], reserve_pct: int) -> tuple[dict[str, int], int]:
    return {str(k): max(0, int(v)) for k, v in budgets.items()}, max(0, min(100, int(reserve_pct)))


def still_spent(exhausted: Any, until: Any, now: datetime) -> set[str]:
    """Models still marked spent at `now` (WR-01). A model with a recorded expiry is spent only until that instant (Groq's
    window is rolling, D-53, so its own `retry-after` says when it is usable again). A model without a readable expiry
    (an older record, or a 429 that gave no wait) stays spent until the UTC day rolls, which `_parse` enforces."""
    spent = {m for m in exhausted if isinstance(m, str)} if isinstance(exhausted, list) else set()
    until = until if isinstance(until, dict) else {}
    out = set()
    for m in spent:
        try:
            expiry = datetime.fromisoformat(until[m]) if isinstance(until.get(m), str) else None
        except ValueError:
            expiry = None
        if expiry is None or expiry.tzinfo is None or expiry > now:
            out.add(m)
    return out


def _parse(raw: str | None, day: str, now: datetime) -> tuple[dict[str, int], set[str], dict[str, str], str]:
    """(used, exhausted, exhausted_until, rolled_from) from persisted JSON; anything unreadable is a fresh budget."""
    try:
        data = json.loads(raw) if raw and raw.strip() else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        return {}, set(), {}, ""
    stored = data.get("day")
    if not isinstance(stored, str):
        return {}, set(), {}, ""
    if stored != day:
        return {}, set(), {}, stored
    used_raw = data.get("used") if isinstance(data.get("used"), dict) else {}
    used = {k: v for k, v in used_raw.items() if isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) and v >= 0}
    spent = still_spent(data.get("exhausted"), data.get("exhausted_until"), now)
    until_raw = data.get("exhausted_until") if isinstance(data.get("exhausted_until"), dict) else {}
    until = {m: v for m, v in until_raw.items() if m in spent and isinstance(v, str)}
    return used, spent, until, ""


@dataclass
class GroqBudget:
    day: str
    budgets: dict[str, int]  # model -> tokens per UTC day (from Settings; never read back from the persisted JSON)
    reserve_pct: int = FRESH_RESERVE_PCT
    used: dict[str, int] = field(default_factory=dict)
    exhausted: set[str] = field(default_factory=set)  # models Groq itself said are spent (daily-limit 429), until the expiry below or the UTC day's end
    exhausted_until: dict[str, str] = field(default_factory=dict)  # model -> ISO instant Groq's retry-after says it is usable again (WR-01)
    rolled_from: str = ""  # previous day's label when the persisted budget was from an earlier day (not persisted)

    @classmethod
    def load(cls, raw: str | None, now: datetime, *, budgets: dict[str, int], reserve_pct: int = FRESH_RESERVE_PCT) -> "GroqBudget":
        budgets, reserve_pct = _clean(budgets, reserve_pct)
        day = day_of(now)
        used, exhausted, until, rolled = _parse(raw, day, now)
        return cls(day, budgets, reserve_pct, used, exhausted, until, rolled)

    def restore(self, raw: str | None, now: datetime) -> None:
        """In place: the client and the pipeline share this one object, so `budgets` and `reserve_pct` are kept."""
        self.budgets, self.reserve_pct = _clean(self.budgets, self.reserve_pct)
        self.day = day_of(now)
        self.used, self.exhausted, self.exhausted_until, self.rolled_from = _parse(raw, self.day, now)

    def cap(self, model: str, *, fresh: bool) -> int:
        b = self.budgets.get(model, 0)
        return b if fresh else b * (100 - self.reserve_pct) // 100

    def can_spend(self, model: str, *, fresh: bool) -> bool:
        """Strict `<`: one answer may overshoot the cap, which the headroom between the default budget and Groq's limit absorbs (P2-02, D-53)."""
        return model not in self.exhausted and self.used.get(model, 0) < self.cap(model, fresh=fresh)

    def pick_model(self, order: list[str], *, fresh: bool, unavailable: set[str] | frozenset[str] = frozenset()) -> str | None:
        for model in order:
            if model not in unavailable and self.can_spend(model, fresh=fresh):
                return model
        return None

    def charge(self, model: str, tokens: int) -> None:
        self.used[model] = self.used.get(model, 0) + max(0, int(tokens))

    def exhaust(self, model: str, until: datetime | None = None) -> None:
        """Mark `model` spent per Groq. With `until` (a timezone-aware instant from Groq's retry-after) the lock ends then
        (checked when the next run restores the budget); without it, at the end of the UTC day (WR-01)."""
        self.exhausted.add(model)
        if until is not None and until.tzinfo is not None:
            self.exhausted_until[model] = until.astimezone(timezone.utc).isoformat(timespec="seconds")
        else:
            self.exhausted_until.pop(model, None)

    def to_json(self) -> str:
        data: dict[str, Any] = {"day": self.day, "used": dict(sorted(self.used.items())), "exhausted": sorted(self.exhausted), "budgets": dict(sorted(self.budgets.items()))}
        until = {m: v for m, v in sorted(self.exhausted_until.items()) if m in self.exhausted}
        if until:
            data["exhausted_until"] = until
        return json.dumps(data, separators=(",", ":"))

    def summary(self) -> str:
        models = sorted(set(self.budgets) | set(self.used))
        parts = ", ".join(
            f"{m} {self.used.get(m, 0)}/{self.budgets.get(m, 0)}{' (spent per Groq)' if m in self.exhausted else ''}" for m in models
        )
        return f"groq budget {self.day} UTC: {parts} (last {self.reserve_pct}% for verified-fresh jobs)"
