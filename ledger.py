"""Append-only event ledger and the job state derived from it (SPEC.md "State model").

Seen, evaluated and alerted are separate facts. Each is written only after that stage really
completed, so a failure can never mark a later stage done and every stage is retryable.
Pure functions: persistence lives in state.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Iterable

import freshness as fr
from boards import ListedJob

SEEN, EVALUATED, ALERTED, ERROR, ABANDONED, UPDATED, REPUBLISHED = (
    "seen", "evaluated", "alerted", "error", "abandoned", "updated", "republished",
)  # fmt: skip

# Disposition decided at first observation.
PENDING, BASELINED, FILTERED, STALED = "pending", "baseline", "filtered", "stale"

STAGE_EVALUATE, STAGE_ALERT = "evaluate", "alert"
MAX_ATTEMPTS = 5
EVENT_COLUMNS = ["Time", "Job_Key", "Event", "Freshness", "Disposition", "Published", "Detail"]
_DETAIL_LIMIT = 45000  # Google Sheets caps a cell at 50,000 characters
ALERT_RETRY_WINDOW = timedelta(hours=12)  # a retried alert older than this is no longer "fresh news"


def stamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Event:
    time: str
    key: str
    event: str
    freshness: str = ""
    disposition: str = ""
    published: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> list[str]:
        detail = json.dumps(self.detail, separators=(",", ":"), ensure_ascii=False)
        return [self.time, self.key, self.event, self.freshness, self.disposition, self.published, detail[:_DETAIL_LIMIT]]

    @classmethod
    def from_row(cls, row: list[str]) -> "Event | None":
        if len(row) < 3 or not row[1] or not row[2]:
            return None
        row = list(row) + [""] * (7 - len(row))
        try:
            detail = json.loads(row[6]) if row[6] else {}
        except ValueError:
            detail = {}
        return cls(row[0], row[1], row[2], row[3], row[4], row[5], detail if isinstance(detail, dict) else {})


@dataclass
class JobState:
    key: str
    seen: bool = False
    freshness: str = ""
    disposition: str = ""
    seen_time: str = ""
    seen_detail: dict[str, Any] = field(default_factory=dict)
    evaluated: dict[str, Any] | None = None
    evaluated_time: str = ""
    alerted: bool = False
    errors: dict[str, int] = field(default_factory=dict)
    abandoned: set[str] = field(default_factory=set)
    last_published: str = ""
    last_updated: str = ""


def replay(events: Iterable[Event]) -> dict[str, JobState]:
    """Derive per-job state from the ledger (first `seen` wins; later events add facts)."""
    states: dict[str, JobState] = {}
    for ev in events:
        st = states.setdefault(ev.key, JobState(ev.key))
        if ev.event == SEEN and not st.seen:
            st.seen, st.freshness, st.disposition = True, ev.freshness, ev.disposition
            st.seen_time, st.seen_detail, st.last_published = ev.time, ev.detail, ev.published
            st.last_updated = str(ev.detail.get("updated", ""))
        elif ev.event == EVALUATED and st.evaluated is None:
            st.evaluated, st.evaluated_time = ev.detail, ev.time
        elif ev.event == ALERTED:
            st.alerted = True
        elif ev.event == ERROR:
            stage = str(ev.detail.get("stage", ""))
            st.errors[stage] = st.errors.get(stage, 0) + 1
        elif ev.event == ABANDONED:
            st.abandoned.add(str(ev.detail.get("stage", "")))
        elif ev.event == UPDATED:
            st.last_updated = str(ev.detail.get("updated", st.last_updated))
        elif ev.event == REPUBLISHED:
            st.last_published = ev.published or st.last_published
    return states


def needs_evaluation(st: JobState) -> bool:
    return st.seen and st.disposition == PENDING and st.evaluated is None and STAGE_EVALUATE not in st.abandoned


def needs_alert(st: JobState, now: datetime) -> bool:
    if not (st.evaluated and st.evaluated.get("alert")) or st.alerted or STAGE_ALERT in st.abandoned:
        return False
    return True


def alert_too_late(st: JobState, now: datetime) -> bool:
    try:
        done = datetime.strptime(st.evaluated_time, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=now.tzinfo)
    except ValueError:
        return False
    return now - done > ALERT_RETRY_WINDOW


_PRIORITY = {fr.VERIFIED_FRESH: 0, fr.OBSERVED_NEW: 1, fr.RECENT: 2, fr.UNCERTAIN: 3}


def priority(st: JobState) -> tuple[int, float]:
    """Evaluate verified-fresh jobs first (they are the product); newest first within a class."""
    published, _ = fr.parse_instant(st.last_published)
    return _PRIORITY.get(st.freshness, 9), -(published.timestamp() if published else 0.0)


# --------------------------------------------------------------------------- observation


@dataclass(frozen=True)
class Observation:
    """Context shared by every job found in one board poll (or one search)."""

    now: datetime
    board_gap: timedelta | None
    board_baselined: bool
    baseline_pass: bool
    source: str  # "poll" | "serper"
    fresh_window: timedelta = timedelta(hours=fr.DEFAULT_FRESH_WINDOW_HOURS)
    max_age_days: int = fr.DEFAULT_MAX_AGE_DAYS


def observe_new(job: ListedJob, obs: Observation, title_gate: Callable[[str], str | None]) -> Event:
    """First observation of an unseen ID: classify freshness and decide its disposition."""
    published, precision = fr.parse_instant(job.published)
    f = fr.classify(
        published, precision, now=obs.now, board_gap=obs.board_gap, board_baselined=obs.board_baselined,
        baseline_pass=obs.baseline_pass, fresh_window=obs.fresh_window, max_age_days=obs.max_age_days,
    )  # fmt: skip
    gate = ""
    if f.cls == fr.BASELINE:
        disposition = BASELINED
    elif f.cls == fr.STALE:
        disposition = STALED
    else:
        gate = title_gate(job.title) or ""
        disposition = FILTERED if gate else PENDING
    detail = {
        "source": obs.source, "board": job.ident.board, "title": job.title[:200], "url": job.url,
        "location": job.location[:200], "published_field": job.published_field, "precision": precision,
        "evidence": f.reason, "gate": gate, "age_min": f.age_minutes, "gap_min": f.gap_minutes, "updated": job.updated,
    }  # fmt: skip
    return Event(stamp(obs.now), job.ident.key, SEEN, f.cls, disposition, fr.iso(published, precision), detail)


def observe_known(job: ListedJob, st: JobState, now: datetime) -> list[Event]:
    """Update / republication of an ID we already track. Logged only; never re-alerts."""
    prev_pub, _ = fr.parse_instant(st.last_published)
    cur_pub, precision = fr.parse_instant(job.published)
    events = []
    for kind in fr.detect_changes(prev_pub, st.last_updated, cur_pub, job.updated):
        if kind == "republished":
            events.append(Event(stamp(now), job.ident.key, REPUBLISHED, published=fr.iso(cur_pub, precision), detail={"previous": st.last_published}))
        else:
            events.append(Event(stamp(now), job.ident.key, UPDATED, detail={"updated": job.updated, "previous": st.last_updated}))
    return events


def failure_events(key: str, stage: str, message: str, st: JobState | None, now: datetime) -> list[Event]:
    """Record a failed attempt; abandon the stage after MAX_ATTEMPTS so it cannot loop forever."""
    attempt = (st.errors.get(stage, 0) if st else 0) + 1
    events = [Event(stamp(now), key, ERROR, detail={"stage": stage, "message": message[:300], "attempt": attempt})]
    if attempt >= MAX_ATTEMPTS:
        events.append(Event(stamp(now), key, ABANDONED, detail={"stage": stage, "reason": message[:200]}))
    return events
