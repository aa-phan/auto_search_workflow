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

GROQ_BUDGET_KEY = "groq_budget"
FRESH_RESERVE_PCT = 20  # P2-04: the last 20% of each model's budget is for verified-fresh jobs only


def day_of(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _clean(budgets: dict[str, int], reserve_pct: int) -> tuple[dict[str, int], int]:
    return {str(k): max(0, int(v)) for k, v in budgets.items()}, max(0, min(100, int(reserve_pct)))


def _parse(raw: str | None, day: str) -> tuple[dict[str, int], set[str], str]:
    """(used, exhausted, rolled_from) from persisted JSON; anything unreadable is a fresh budget."""
    try:
        data = json.loads(raw) if raw and raw.strip() else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        return {}, set(), ""
    stored = data.get("day")
    if not isinstance(stored, str):
        return {}, set(), ""
    if stored != day:
        return {}, set(), stored
    used_raw = data.get("used") if isinstance(data.get("used"), dict) else {}
    used = {k: v for k, v in used_raw.items() if isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) and v >= 0}
    ex_raw = data.get("exhausted") if isinstance(data.get("exhausted"), list) else []
    return used, {m for m in ex_raw if isinstance(m, str)}, ""


@dataclass
class GroqBudget:
    day: str
    budgets: dict[str, int]  # model -> tokens per UTC day (from Settings; never read back from the persisted JSON)
    reserve_pct: int = FRESH_RESERVE_PCT
    used: dict[str, int] = field(default_factory=dict)
    exhausted: set[str] = field(default_factory=set)  # models Groq itself said are spent for the day (daily-limit 429)
    rolled_from: str = ""  # previous day's label when the persisted budget was from an earlier day (not persisted)

    @classmethod
    def load(cls, raw: str | None, now: datetime, *, budgets: dict[str, int], reserve_pct: int = FRESH_RESERVE_PCT) -> "GroqBudget":
        budgets, reserve_pct = _clean(budgets, reserve_pct)
        day = day_of(now)
        used, exhausted, rolled = _parse(raw, day)
        return cls(day, budgets, reserve_pct, used, exhausted, rolled)

    def restore(self, raw: str | None, now: datetime) -> None:
        """In place: the client and the pipeline share this one object, so `budgets` and `reserve_pct` are kept."""
        self.budgets, self.reserve_pct = _clean(self.budgets, self.reserve_pct)
        self.day = day_of(now)
        self.used, self.exhausted, self.rolled_from = _parse(raw, self.day)

    def cap(self, model: str, *, fresh: bool) -> int:
        b = self.budgets.get(model, 0)
        return b if fresh else b * (100 - self.reserve_pct) // 100

    def can_spend(self, model: str, *, fresh: bool) -> bool:
        """Strict `<`: one answer may overshoot the cap, which the 15% headroom of the default budget absorbs (P2-02)."""
        return model not in self.exhausted and self.used.get(model, 0) < self.cap(model, fresh=fresh)

    def pick_model(self, order: list[str], *, fresh: bool, unavailable: set[str] | frozenset[str] = frozenset()) -> str | None:
        for model in order:
            if model not in unavailable and self.can_spend(model, fresh=fresh):
                return model
        return None

    def charge(self, model: str, tokens: int) -> None:
        self.used[model] = self.used.get(model, 0) + max(0, int(tokens))

    def exhaust(self, model: str) -> None:
        self.exhausted.add(model)

    def to_json(self) -> str:
        return json.dumps(
            {"day": self.day, "used": dict(sorted(self.used.items())), "exhausted": sorted(self.exhausted), "budgets": dict(sorted(self.budgets.items()))},
            separators=(",", ":"),
        )

    def summary(self) -> str:
        models = sorted(set(self.budgets) | set(self.used))
        parts = ", ".join(
            f"{m} {self.used.get(m, 0)}/{self.budgets.get(m, 0)}{' (spent per Groq)' if m in self.exhausted else ''}" for m in models
        )
        return f"groq budget {self.day} UTC: {parts} (last {self.reserve_pct}% for verified-fresh jobs)"
