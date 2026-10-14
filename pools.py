"""Board evidence and allocation: what each monitored board has actually shown us, and (later in
this module) how monitoring slots are shared between established and exploration boards.

Pure functions, no I/O. All evidence comes from data the hourly poll already fetched (the listing)
and from the append-only ledger. Nothing here calls an LLM, a search engine or a network.
Rules: SPEC.md "Board registry" and DECISIONS.md D-23 (evidence), D-26 (pools), D-30 (open choices).
"""

from __future__ import annotations

import collections
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

import eligibility
import ledger as lg
from boards import STAMP, BoardId, BoardRecord, ListedJob

# A board needs a stint this long before "no new postings" may be read as a real zero.
ACTIVITY_MIN_DAYS = 7
# Observation passes that must never count as board activity (they are the board's existing
# backlog or jobs that appeared while the board was not watched).
NON_ACTIVITY_PASSES = frozenset({"baseline", "reentry"})


def parse_stamp(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, STAMP).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def board_key_for_job(job_key: str, board_spelling: str = "") -> str:
    """The registry key of the board a job key belongs to. Job keys lower-case the board, board
    keys keep Lever/Workable case, so the spelling stored in the `seen` event is used when known."""
    prefix, _, rest = job_key.partition("|")
    ats, _, region = prefix.partition("@")
    board = board_spelling or rest.split("|", 1)[0]
    return BoardId(ats, board, region).key


# --------------------------------------------------------------------------- activity (D-23)


@dataclass
class ActivityIndex:
    """First-observation times of NEW RELEVANT postings per board, derived from the ledger.

    A new relevant posting is a `seen` job whose first observation came from a board poll, that
    passed the title gate and was not stale (disposition `pending`), and that was not part of a
    baseline or re-entry pass. Search-found jobs are not counted (documented limitation), and
    neither is anything keyed to a source date: the time is when WE first saw the ID."""

    by_board: dict[str, list[datetime]] = field(default_factory=dict)

    @classmethod
    def from_states(cls, states: dict[str, lg.JobState]) -> "ActivityIndex":
        out: dict[str, list[datetime]] = collections.defaultdict(list)
        for key, st in states.items():
            if not st.seen or st.disposition != lg.PENDING:
                continue
            detail = st.seen_detail or {}
            if detail.get("source") != "poll" or detail.get("pass", "") in NON_ACTIVITY_PASSES:
                continue
            seen_at = parse_stamp(st.seen_time)
            if seen_at is None:
                continue
            out[board_key_for_job(key, str(detail.get("board") or ""))].append(seen_at)
        for times in out.values():
            times.sort()
        return cls(dict(out))

    def times(self, board_key: str) -> list[datetime]:
        return list(self.by_board.get(board_key, []))


# --------------------------------------------------------------------------- evidence refresh


def relevance_counts(jobs: Iterable[ListedJob], title_gate: Callable[[str], str | None]) -> tuple[int, int]:
    """(relevant, eligible) over UNIQUE posting IDs. Relevant = passes the title gate; eligible =
    relevant and the listing location is not excluded by the US location rule (an empty location is
    not excluded)."""
    unique: dict[str, ListedJob] = {}
    for j in jobs:
        unique.setdefault(j.ident.key, j)
    relevant = [j for j in unique.values() if title_gate(j.title) is None]
    eligible = [j for j in relevant if eligibility.location_blocks(j.location) is None]
    return len(relevant), len(eligible)


def refresh_relevance(rec: BoardRecord, jobs: Iterable[ListedJob], title_gate: Callable[[str], str | None], now: datetime) -> None:
    """Refresh a board's open-job counts from a COMPLETE, SUCCESSFUL poll's own listing. The caller
    must not call this for failed, suspicious-empty or truncated listings."""
    rec.relevant_jobs, rec.eligible_jobs = relevance_counts(jobs, title_gate)
    rec.relevance_at = lg.stamp(now)
    rec.complete_polls += 1


def start_stint(rec: BoardRecord, now: datetime) -> None:
    """A new continuous monitoring stint: first baseline, or a return after leaving monitoring.
    Observation history before it is not carried into the 7/30-day counts."""
    rec.activity_since = lg.stamp(now)
    rec.complete_polls = 0
    rec.new_relevant_7d = rec.new_relevant_30d = None


def stint_days(rec: BoardRecord, now: datetime) -> float | None:
    since = parse_stamp(rec.activity_since)
    return None if since is None else max(0.0, (now - since).total_seconds() / 86400)


def refresh_activity(rec: BoardRecord, index: ActivityIndex, now: datetime) -> None:
    """Recompute the 7/30-day counts of new relevant postings from the ledger index.

    Unknown is not zero: both counts stay None until the stint is ACTIVITY_MIN_DAYS old. Only
    observations at or after Activity_Since count. `last_new_relevant_at` is a plain fact about
    the observation history and is set whenever one exists."""
    times = index.times(rec.key)
    if times:
        rec.last_new_relevant_at = lg.stamp(times[-1])
    since = parse_stamp(rec.activity_since)
    days = stint_days(rec, now)
    if since is None or days is None or days < ACTIVITY_MIN_DAYS:
        rec.new_relevant_7d = rec.new_relevant_30d = None
        return
    counted = [t for t in times if t >= since]
    rec.new_relevant_7d = sum(1 for t in counted if t >= now - timedelta(days=7))
    rec.new_relevant_30d = sum(1 for t in counted if t >= now - timedelta(days=30))
