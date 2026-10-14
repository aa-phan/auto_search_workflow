"""Freshness: what we know about *when* a job became public, and how sure we are.

Pure functions only (no I/O). Vocabulary and rules: SPEC.md. Key distinctions:

- source publication time: the ATS's creation/publish timestamp (with a precision)
- first observation: when this system first saw the ID
- update: the source's last-modified field (never a publication time)
- board gap: time since the board's previous successful poll
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

# Freshness classes (SPEC.md)
VERIFIED_FRESH = "verified_fresh"
OBSERVED_NEW = "observed_new"
RECENT = "recent"
UNCERTAIN = "uncertain"
STALE = "stale"
BASELINE = "baseline"

# Classes that go on to hydration, gates and scoring.
EVALUABLE = {VERIFIED_FRESH, OBSERVED_NEW, RECENT, UNCERTAIN}
# Only this class may trigger a push alert.
ALERTABLE = {VERIFIED_FRESH}

DEFAULT_FRESH_WINDOW_HOURS = 12
DEFAULT_MAX_AGE_DAYS = 14
CLOCK_SKEW = timedelta(minutes=5)

TIME = "time"
DAY = "day"
NONE = ""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_instant(value: Any) -> tuple[datetime | None, str]:
    """Parse a publication value into (UTC datetime, precision).

    Precision is "time" for real timestamps (epoch, ISO with a time of day) and "day" for
    date-only values, relative text ("3 days ago"), and ISO timestamps at exactly 00:00:00Z
    (Workable returns midnight for a date). Unparseable input gives (None, "").
    """
    if value is None or isinstance(value, bool) or value == "":
        return None, NONE
    if isinstance(value, (int, float)):
        secs = value / 1000 if value > 1e11 else value
        try:
            return datetime.fromtimestamp(secs, timezone.utc), TIME
        except (OverflowError, OSError, ValueError):
            return None, NONE
    text = str(value).strip()
    if re.fullmatch(r"\d{9,13}", text):  # epoch seconds / milliseconds stored as a string
        return parse_instant(int(text))
    now = utcnow()
    low = text.lower()
    if low in {"today", "just now"}:
        return datetime.combine(now.date(), datetime.min.time(), timezone.utc), DAY
    if low == "yesterday":
        return datetime.combine(now.date() - timedelta(days=1), datetime.min.time(), timezone.utc), DAY
    if m := re.fullmatch(r"(?i)(\d+)\+?\s*(minute|hour|day|week|month)s?\s+ago", text):
        n, unit = int(m.group(1)), m.group(2).lower()
        days = {"minute": 0, "hour": 0, "day": n, "week": 7 * n, "month": 30 * n}[unit]
        return datetime.combine(now.date() - timedelta(days=days), datetime.min.time(), timezone.utc), DAY
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return datetime.fromisoformat(text).replace(tzinfo=timezone.utc), DAY
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%b %d, %Y", "%B %d, %Y"):
            try:
                return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc), DAY
            except ValueError:
                continue
        return None, NONE
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    if dt.hour == dt.minute == dt.second == dt.microsecond == 0:
        return dt, DAY
    return dt, TIME


def parse_posted(value: Any) -> date | None:
    """Date-only view of parse_instant (kept for callers that only need the day)."""
    dt, _ = parse_instant(value)
    return dt.date() if dt else None


def iso(dt: datetime | None, precision: str) -> str:
    """Stable string for storage: full timestamp for time precision, date for day precision."""
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if precision == TIME else dt.date().isoformat()


@dataclass(frozen=True)
class Freshness:
    cls: str
    reason: str  # one human-readable line stating the evidence
    age_minutes: int | None = None  # source age at first observation, when known
    gap_minutes: int | None = None  # board gap used as evidence, when relevant


def classify(
    published: datetime | None,
    precision: str,
    *,
    now: datetime,
    board_gap: timedelta | None,
    board_baselined: bool,
    baseline_pass: bool = False,
    fresh_window: timedelta = timedelta(hours=DEFAULT_FRESH_WINDOW_HOURS),
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
) -> Freshness:
    """Classify a job at its first observation from the best available evidence."""
    age = (now - published) if published else None
    age_min = int(age.total_seconds() // 60) if age is not None else None
    gap_min = int(board_gap.total_seconds() // 60) if board_gap is not None else None
    gap_ok = board_baselined and board_gap is not None and board_gap <= fresh_window

    time_fresh = precision == TIME and age is not None and -CLOCK_SKEW <= age <= fresh_window
    if baseline_pass:
        if time_fresh:
            return Freshness(VERIFIED_FRESH, f"published {age_min} min ago (source timestamp) on a board being baselined", age_min)
        return Freshness(BASELINE, "already on the board when it was first polled", age_min)

    if published is not None:
        if time_fresh:
            return Freshness(VERIFIED_FRESH, f"published {age_min} min ago (source timestamp)", age_min, gap_min)
        if precision == DAY and gap_ok and published.date() >= (now - timedelta(days=1)).date():
            return Freshness(
                VERIFIED_FRESH,
                f"source date {published.date()} (day precision) and first seen {gap_min} min after the previous successful poll",
                age_min, gap_min,
            )  # fmt: skip
        if age is not None and age < -CLOCK_SKEW:
            # Seen on real data: aggregator boards stamp postings tens of minutes in the future.
            return Freshness(UNCERTAIN, f"source timestamp is {-age_min} min in the future; not trusted", age_min, gap_min)
        if age is not None and age > timedelta(days=max_age_days):
            return Freshness(STALE, f"published {age.days} days ago", age_min, gap_min)
        return Freshness(RECENT, f"published {age_min // 60 if age_min is not None else '?'} h ago, outside the {int(fresh_window.total_seconds() // 3600)} h window", age_min, gap_min)

    if gap_ok:
        return Freshness(OBSERVED_NEW, f"no source date; not on the board {gap_min} min ago, listed now", None, gap_min)
    return Freshness(UNCERTAIN, "no source date and no recent successful poll of this board", None, gap_min)


def detect_changes(
    prev_published: datetime | None, prev_updated: str, cur_published: datetime | None, cur_updated: str
) -> list[str]:
    """Events for a job we already know: 'republished' (publication moved later) and 'updated'."""
    events: list[str] = []
    if prev_published and cur_published and cur_published - prev_published > timedelta(hours=1):
        events.append("republished")
    if cur_updated and prev_updated and cur_updated != prev_updated:
        events.append("updated")
    return events
