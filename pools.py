"""Board evidence and allocation: what each monitored board has actually shown us, and (later in
this module) how monitoring slots are shared between established and exploration boards.

Pure functions, no I/O. All evidence comes from data the hourly poll already fetched (the listing)
and from the append-only ledger. Nothing here calls an LLM, a search engine or a network.
Rules: SPEC.md "Board registry" and DECISIONS.md D-23 (evidence), D-26 (pools), D-30 (open choices).
"""

from __future__ import annotations

import collections
import copy
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

import eligibility
import freshness as fr
import ledger as lg
from boards import (
    MONITORED, POOL_ESTABLISHED, POOL_EXPLORATION, STAMP, STATUS_ACTIVE, STATUS_DEFERRED, STATUS_DISABLED, STATUS_NEW,
    STATUS_VALIDATED, V_DEFERRED, BoardId, BoardRecord, ListedJob, admission_order, is_waiting_candidate, open_jobs as open_jobs_uncapped,
)  # fmt: skip

# A board needs a stint this long before "no new postings" may be read as a real zero. One hour of
# slack, so a 7-day trial that ends one hour early at the weekly check is not read as "too short".
ACTIVITY_MIN_DAYS = 7
MIN_OBSERVED_DAYS = ACTIVITY_MIN_DAYS - 1 / 24
# Two complete polls further apart than this leave a hole in the observation record (an outage, a
# skipped schedule): the hole is not observed time, so it is not part of any rate denominator, and
# a job first seen after it has no evidence of WHEN it appeared unless its own publication time says so.
MAX_COVERED_GAP = timedelta(hours=6)
COVERAGE_MIN = 0.8  # share of the 7-day window that must have been observed for the 7-day count to be known
# Observation passes that must never count as board activity (they are the board's existing
# backlog or jobs that appeared while the board was not watched).
NON_ACTIVITY_PASSES = frozenset({"baseline", "reentry"})


def parse_stamp(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, STAMP).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def counts_as_new_posting(freshness: str, detail: dict[str, Any]) -> bool:
    """Is this first observation evidence that the posting appeared on the board during the stint?

    Yes when the source's own publication time/date says it is fresh (`verified_fresh`): that holds
    for a job first found by search too (deduplicated by posting identity: one ledger key, and the
    `source` stays in its `seen` event as provenance). An undated job counts only when the board was
    polled shortly before (`observed_new`, gap within MAX_COVERED_GAP): after a longer gap we do not
    know when it appeared. Baseline and re-entry passes, dated-but-old jobs (`recent`) and
    `uncertain` ones never count: that would present a discovery as a publication."""
    if detail.get("pass", "") in NON_ACTIVITY_PASSES or detail.get("source") not in ("poll", "search", "serper"):  # "serper": history written before Tavily
        return False
    if freshness == fr.VERIFIED_FRESH:
        return True
    gap = detail.get("gap_min")
    return (
        detail.get("source") == "poll" and freshness == fr.OBSERVED_NEW
        and isinstance(gap, (int, float)) and gap * 60 <= MAX_COVERED_GAP.total_seconds()
    )  # fmt: skip


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
            if not counts_as_new_posting(st.freshness, detail):
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


def _prune_outages(rec: BoardRecord, now: datetime) -> None:
    cutoff = now - timedelta(days=30)
    kept = [o for o in rec.outages if len(o) == 2 and (e := parse_stamp(o[1])) is not None and e >= cutoff]
    rec.outages = kept[-40:]


def refresh_relevance(rec: BoardRecord, jobs: Iterable[ListedJob], title_gate: Callable[[str], str | None], now: datetime) -> None:
    """Refresh a board's open-job counts from a COMPLETE, SUCCESSFUL poll's own listing. The caller
    must not call this for failed, suspicious-empty or truncated listings.

    Also records the observation record: if the previous complete poll of this stint is further back
    than MAX_COVERED_GAP, the time in between was not observed (a failed or incomplete poll, an outage,
    a skipped schedule) and is stored as an outage."""
    prev, since = parse_stamp(rec.relevance_at), parse_stamp(rec.activity_since)
    if prev is not None and since is not None and prev >= since and now - prev > MAX_COVERED_GAP:
        rec.outages.append([lg.stamp(prev), lg.stamp(now)])
    _prune_outages(rec, now)
    rec.relevant_jobs, rec.eligible_jobs = relevance_counts(jobs, title_gate)
    rec.relevance_at = lg.stamp(now)
    rec.complete_polls += 1


def start_stint(rec: BoardRecord, now: datetime) -> None:
    """A new continuous monitoring stint: first baseline, or a return after leaving monitoring.
    Observation history before it is not carried into the 7/30-day counts."""
    rec.activity_since = lg.stamp(now)
    rec.complete_polls = 0
    rec.new_relevant_7d = rec.new_relevant_30d = None
    rec.outages = []


def stint_days(rec: BoardRecord, now: datetime) -> float | None:
    since = parse_stamp(rec.activity_since)
    return None if since is None else max(0.0, (now - since).total_seconds() / 86400)


def observed_days(rec: BoardRecord, now: datetime, window_days: int) -> tuple[float, float]:
    """(observed days, window days) over the last `window_days` or the stint, whichever is shorter.

    Observed time excludes every outage, including the one that is still going on (no complete poll
    for longer than MAX_COVERED_GAP). This is the rate denominator: a board that could not be read for
    ten days is not a board with ten quiet days."""
    since = parse_stamp(rec.activity_since)
    if since is None:
        return 0.0, 0.0
    start = max(since, now - timedelta(days=window_days))
    span = (now - start).total_seconds()
    if span <= 0:
        return 0.0, 0.0
    holes = [(a, b) for o in rec.outages if len(o) == 2 and (a := parse_stamp(o[0])) and (b := parse_stamp(o[1]))]
    last = parse_stamp(rec.relevance_at)
    if last is not None and last >= since and now - last > MAX_COVERED_GAP:
        holes.append((last, now))
    lost = sum(max(0.0, (min(b, now) - max(a, start)).total_seconds()) for a, b in holes)
    return max(0.0, span - lost) / 86400, span / 86400


def refresh_activity(rec: BoardRecord, index: ActivityIndex, now: datetime) -> None:
    """Recompute the 7/30-day counts of new relevant postings from the ledger index.

    Unknown is not zero. The 7-day count is known only when the stint is old enough AND at least
    COVERAGE_MIN of that week was actually observed; the 30-day count only when at least a week of
    the 30-day window was observed (a partially observed window is allowed, its rate is taken over
    the observed days: see `weekly_rate`). A board that has been unreadable for days therefore
    shows UNKNOWN activity, never a real-looking zero. `last_new_relevant_at` is a plain fact about
    the observation history and is set whenever one exists."""
    times = index.times(rec.key)
    if times:
        rec.last_new_relevant_at = lg.stamp(times[-1])
    since = parse_stamp(rec.activity_since)
    days = stint_days(rec, now)
    if since is None or days is None or days < MIN_OBSERVED_DAYS:
        rec.new_relevant_7d = rec.new_relevant_30d = None
        return
    counted = [t for t in times if t >= since]
    obs7, _ = observed_days(rec, now, 7)
    obs30, _ = observed_days(rec, now, 30)
    rec.new_relevant_7d = sum(1 for t in counted if t >= now - timedelta(days=7)) if obs7 >= COVERAGE_MIN * 7 else None
    rec.new_relevant_30d = sum(1 for t in counted if t >= now - timedelta(days=30)) if obs30 >= MIN_OBSERVED_DAYS else None


# --------------------------------------------------------------------------- policy and score (D-26, D-30)

# Initial operating choices, NOT proven values (DECISIONS.md D-30). Weights are not tuned.
OPEN_CAP = 5  # open eligible jobs counted at most this far, so an aggregator with hundreds cannot dominate
RATE_CAP = 5.0  # new relevant postings per week counted at most this far
RATE_WEIGHT = 2.0  # one new relevant posting per week is worth two open jobs
MARGIN = 1.0  # a trial must beat the weakest established board by MORE than this to displace it
WEAK_CYCLES_TO_DEMOTE = 2  # consecutive rebalance cycles as a replacement target before an established board leaves
EVIDENCE_MAX_AGE = timedelta(hours=24)
SLACK = timedelta(hours=1)  # clock slack for "trial ended" and "rebalance due"
REBALANCE_KEY = "rebalance"  # Discovery-tab key: when the last rebalance ran
REBALANCE_REPORT_KEY = "rebalance_report"  # Discovery-tab key: the last plan as compact JSON
ACTION_ORDER = ("replace", "graduate", "defer", "return", "rotate", "keep", "extend", "shed")


@dataclass(frozen=True)
class PoolPolicy:
    """How Max_Active_Boards is shared. Every board admitted to monitoring starts in the exploration
    pool on a trial; a weekly rebalance compares ended trials with the weakest established boards."""

    max_active: int = 500
    exploration_pct: int = 20
    exploration_days: int = 7
    rebalance_every_days: int = 7
    max_replacements: int = 20
    mode: str = "report"  # "report": the weekly rebalance only records a report; "on": it is applied

    @property
    def exploration_target(self) -> int:
        return min(self.max_active, int(self.max_active * max(0, min(100, self.exploration_pct)) / 100 + 0.5))

    @property
    def established_target(self) -> int:
        return self.max_active - self.exploration_target

    @property
    def min_complete_polls(self) -> int:
        """Half of the hourly polls a trial could have had: one outage-ridden trial is not enough evidence."""
        return max(1, self.exploration_days) * 12

    @property
    def interval(self) -> timedelta:
        return timedelta(days=max(1, self.rebalance_every_days))

    @property
    def cooldown(self) -> timedelta:
        """How long a board that left monitoring waits before it can be offered a slot again."""
        return timedelta(days=2 * max(1, self.exploration_days))

    @property
    def max_trial_age(self) -> timedelta:
        """A trial that still cannot be judged this long after it began is rotated out (see plan_rebalance)."""
        return timedelta(days=3 * max(1, self.exploration_days))


def open_jobs(rec: BoardRecord) -> int:
    return min(open_jobs_uncapped(rec), OPEN_CAP)


def weekly_rate(rec: BoardRecord, now: datetime) -> float | None:
    """New relevant postings per week over the OBSERVED part of the last 30 days (outages are not
    observed time), so neither a longer monitoring history nor an outage changes it. None = unknown."""
    observed, _ = observed_days(rec, now, 30)
    if rec.new_relevant_30d is None or observed < MIN_OBSERVED_DAYS:
        return None
    return rec.new_relevant_30d * 7 / observed


def score(rec: BoardRecord, now: datetime) -> float | None:
    """Transparent board score, 0..15: RATE_WEIGHT x min(weekly new relevant postings, RATE_CAP) + min(open eligible jobs, OPEN_CAP).
    None when activity is unknown. No tenure term: age in the registry earns nothing."""
    rate = weekly_rate(rec, now)
    if rate is None:
        return None
    return RATE_WEIGHT * min(rate, RATE_CAP) + open_jobs(rec)


def evidence_problem(rec: BoardRecord, now: datetime, policy: PoolPolicy) -> str | None:
    """Why a board's evidence is too thin to demote, shed or graduate it (None = sufficient). One empty,
    partial or failed fetch can never be enough: complete-poll history and fresh evidence are required."""
    if score(rec, now) is None:
        return f"activity unknown: fewer than {ACTIVITY_MIN_DAYS} observed days (stint too short or outages)"
    if rec.complete_polls < policy.min_complete_polls:
        return f"{rec.complete_polls} complete polls, need {policy.min_complete_polls}"
    if rec.consecutive_failures > 0:
        return "last poll failed"
    seen = parse_stamp(rec.relevance_at)
    if seen is None or now - seen > EVIDENCE_MAX_AGE:
        return "evidence older than 24 h"
    return None


def _day(now: datetime) -> str:
    return now.strftime("%Y-%m-%d")


# --------------------------------------------------------------------------- every-run sync (D7)


@dataclass
class SyncResult:
    changed: dict[str, BoardRecord] = field(default_factory=dict)
    parked: list[str] = field(default_factory=list)  # monitored boards parked by provider policy
    migrated: list[str] = field(default_factory=list)  # monitored boards given an exploration trial (legacy label)
    cleared: list[str] = field(default_factory=list)  # boards whose stale pool label was cleared
    lines: list[str] = field(default_factory=list)  # one log line per transition


def _leave_monitoring(rec: BoardRecord, now: datetime, reason: str) -> None:
    """Fields every exit from monitoring resets. History (baseline, last success, validation, counts,
    provenance, events) is deliberately kept so the board can come back without losing anything."""
    rec.pool, rec.trial_until, rec.weak_streak = "", "", 0
    rec.pool_since, rec.pool_reason = lg.stamp(now), reason[:200]
    rec.activity_since, rec.complete_polls = "", 0
    rec.new_relevant_7d = rec.new_relevant_30d = None


def sync_pools(registry: dict[str, BoardRecord], policy: PoolPolicy, now: datetime, blocked: Callable[[str], Any] | None = None) -> SyncResult:
    """Every run, in every mode, before activation: apply provider policy to monitored boards, drop
    stale pool labels and label boards that were monitored before pools existed. Board-key order."""
    res = SyncResult()
    day = _day(now)
    for key in sorted(registry):
        rec = registry[key]
        why = blocked(rec.ats) if blocked else None
        before = rec.pool or "-"
        if why and rec.status in (STATUS_NEW, STATUS_ACTIVE, STATUS_DISABLED):
            was = rec.status
            rec.status, rec.validation = STATUS_DEFERRED, V_DEFERRED
            rec.last_error = (why if isinstance(why, str) else "provider policy")[:200]
            _leave_monitoring(rec, now, f"parked {day}: provider policy (SmartRecruiters robots.txt); history kept")
            if was in MONITORED:
                res.parked.append(key)
            res.changed[key] = rec
            res.lines.append(f"Pool {key}: {before} -> parked ({rec.pool_reason})")
        elif rec.status not in MONITORED and rec.pool:
            _leave_monitoring_hygiene(rec, now, f"left monitoring {day}: {rec.status}")
            res.cleared.append(key)
            res.changed[key] = rec
            res.lines.append(f"Pool {key}: {before} -> - ({rec.pool_reason})")
        elif rec.status in MONITORED and not rec.pool:
            until = now + timedelta(days=policy.exploration_days)
            rec.pool, rec.weak_streak = POOL_EXPLORATION, 0
            rec.trials += 1
            rec.pool_since, rec.trial_until = lg.stamp(now), lg.stamp(until)
            rec.pool_reason = (
                f"migrated {day}: monitored before pools existed; trial until {until:%Y-%m-%d}" if rec.trials == 1
                else f"resumed {day}: monitoring without a pool label; trial until {until:%Y-%m-%d}"
            )[:200]
            res.migrated.append(key)
            res.changed[key] = rec
            res.lines.append(f"Pool {key}: - -> exploration ({rec.pool_reason})")
    return res


def _leave_monitoring_hygiene(rec: BoardRecord, now: datetime, reason: str) -> None:
    """A board that is no longer monitored but still carries a pool label (e.g. it was disabled after
    sustained failures): clear the label. Evidence counters are left alone (they restart on re-entry)."""
    rec.pool, rec.trial_until, rec.weak_streak = "", "", 0
    rec.pool_since, rec.pool_reason = lg.stamp(now), reason[:200]


# --------------------------------------------------------------------------- weekly rebalance (D8, D9)


@dataclass
class Decision:
    key: str
    action: str  # replace | graduate | defer | return | rotate | keep | extend | shed
    score: float | None = None
    partner: str = ""  # replace: the established board that leaves; defer: the board it would replace
    reason: str = ""


@dataclass
class RebalancePlan:
    decisions: list[Decision] = field(default_factory=list)
    streaks: dict[str, int] = field(default_factory=dict)  # new Weak_Streak of established boards whose streak changes
    exploration_target: int = 0
    established_target: int = 0
    established: int = 0
    exploration: int = 0
    monitored: int = 0
    max_active: int = 0
    waiting: int = 0
    protected_trials: int = 0  # exploration boards still inside their trial: never touched
    unevidenced_established: int = 0  # established boards with thin evidence: never demoted
    replacements: int = 0  # established boards leaving this cycle (replacements + capacity cuts)
    bound: int = 0
    trial_days: int = 7  # how long an extended or kept trial runs

    def count(self, action: str) -> int:
        return sum(1 for d in self.decisions if d.action == action)

    def summary(self) -> str:
        return (
            f"would graduate {self.count('graduate') + self.count('replace')}, replace {self.count('replace')} (bound {self.bound}), "
            f"defer {self.count('defer')}, extend {self.count('extend')}, return {self.count('return')}, rotate {self.count('rotate')}, keep {self.count('keep')}, "
            f"shed {self.count('shed')}"
        )


def plan_rebalance(registry: dict[str, BoardRecord], policy: PoolPolicy, now: datetime, blocked: Callable[[str], Any] | None = None) -> RebalancePlan:
    """The weekly decision, as a pure function of the registry's recorded fields (no I/O, no clock
    beyond `now`). Ended trials are compared with the weakest evidence-backed established boards;
    trials still running are never touched; established boards leave only after two consecutive
    weak cycles, never on thin evidence, and at most `max_replacements` per cycle."""
    recs = [registry[k] for k in sorted(registry)]
    monitored = [r for r in recs if r.status in MONITORED]
    established = [r for r in monitored if r.pool == POOL_ESTABLISHED]
    exploring = [r for r in monitored if r.pool == POOL_EXPLORATION]
    waiting = sum(1 for r in recs if is_waiting_candidate(r, blocked, now=now, cooldown=policy.cooldown))
    plan = RebalancePlan(
        exploration_target=policy.exploration_target, established_target=policy.established_target,
        established=len(established), exploration=len(exploring), monitored=len(monitored), max_active=policy.max_active,
        waiting=waiting, bound=policy.max_replacements, trial_days=policy.exploration_days,
    )  # fmt: skip

    def sc(r: BoardRecord) -> float:
        value = score(r, now)
        return 0.0 if value is None else value

    def overdue(r: BoardRecord) -> bool:
        since = parse_stamp(r.pool_since)
        return since is None or now - since > policy.max_trial_age

    # 2. Trials that ended (a trial with no parsable end counts as ended: nothing protects it forever).
    # A trial whose evidence stays too thin is extended, but only until it is `max_trial_age` old: then it
    # is "unjudged" and rotated out to make room (history kept, nothing said about its hiring activity).
    ended: list[BoardRecord] = []
    unjudged: list[tuple[BoardRecord, str]] = []
    for r in exploring:
        until = parse_stamp(r.trial_until)
        if until is not None and until > now + SLACK:
            plan.protected_trials += 1
        elif problem := evidence_problem(r, now, policy):
            if overdue(r):
                unjudged.append((r, problem))
            else:
                plan.decisions.append(Decision(r.key, "extend", score(r, now), reason=f"trial extended ({problem})"))
        else:
            ended.append(r)
    # 3. Established boards with sufficient evidence can be compared; the rest are protected this cycle.
    victims: list[BoardRecord] = []
    for r in established:
        if evidence_problem(r, now, policy):
            plan.unevidenced_established += 1
            if r.weak_streak:
                plan.streaks[r.key] = 0
        else:
            victims.append(r)
    ended.sort(key=lambda r: (-sc(r), r.key))
    victims.sort(key=lambda r: (sc(r), r.key))

    # 4. Capacity cut (only when the cap was lowered below what is monitored).
    replacements = 0
    excess = len(monitored) - policy.max_active
    shed_established = 0
    while excess > 0 and ended:
        g = ended.pop()
        plan.decisions.append(Decision(g.key, "shed", sc(g), reason=f"capacity cut to Max_Active_Boards={policy.max_active} (score {sc(g):.1f})"))
        excess -= 1
    while excess > 0 and victims and replacements < policy.max_replacements:
        v = victims.pop(0)
        plan.decisions.append(Decision(v.key, "shed", sc(v), reason=f"capacity cut to Max_Active_Boards={policy.max_active} (score {sc(v):.1f})"))
        plan.streaks.pop(v.key, None)
        replacements += 1
        shed_established += 1
        excess -= 1

    # 5. Pairing.
    vacancies = max(0, policy.established_target - (len(established) - shed_established))
    weak: set[str] = set()
    losers: list[BoardRecord] = []
    vi = 0
    for g in ended:
        sg = sc(g)
        if vacancies > 0:
            vacancies -= 1
            plan.decisions.append(Decision(g.key, "graduate", sg, reason=f"graduated: trial ended with score {sg:.1f}; established has a free slot"))
            continue
        if vi < len(victims):
            v = victims[vi]
            if sc(v) + MARGIN < sg:
                vi += 1
                weak.add(v.key)
                streak = v.weak_streak + 1
                plan.streaks[v.key] = streak
                if streak >= WEAK_CYCLES_TO_DEMOTE and replacements < policy.max_replacements:
                    replacements += 1
                    plan.decisions.append(Decision(g.key, "replace", sg, v.key, f"replaces {v.key} (score {sg:.1f} vs {sc(v):.1f}; weak {streak} cycles in a row)"))
                else:
                    why = (
                        f"{v.key} is weak for the first time (needs {WEAK_CYCLES_TO_DEMOTE} consecutive cycles)"
                        if streak < WEAK_CYCLES_TO_DEMOTE else f"the replacement bound of {policy.max_replacements} is reached"
                    )
                    plan.decisions.append(Decision(g.key, "defer", sg, v.key, f"keeps its trial slot: score {sg:.1f} beats {v.key} ({sc(v):.1f}) but {why}"))
                continue
            losers.append(g)
        elif not victims and plan.unevidenced_established:
            # Every established board lacks the evidence to be compared: do not lose a good trial over that,
            # but not forever either: an overdue trial is rotated out like any other unjudged one.
            if overdue(g):
                unjudged.append((g, "no established board could be compared"))
            else:
                plan.decisions.append(Decision(g.key, "defer", sg, reason="keeps its trial slot: no evidence-backed established board to compare with"))
        else:
            losers.append(g)
    plan.replacements = replacements

    # 6. Boards that were not weak this cycle start over.
    for v in victims:
        if v.key not in weak and v.weak_streak:
            plan.streaks[v.key] = 0

    # Trials that lost: free at most as many slots as there are boards waiting, weakest first.
    losers.sort(key=lambda r: (sc(r), r.key))
    for i, g in enumerate(losers):
        sg = sc(g)
        if i < waiting:
            plan.decisions.append(Decision(g.key, "return", sg, reason=f"trial lost: score {sg:.1f} does not beat the weakest established board by more than {MARGIN:g}; returned to the waiting list"))
        else:
            plan.decisions.append(Decision(g.key, "keep", sg, reason="trial ended, kept (no relevant board waiting)"))
    # Unjudged trials share what is left of the waiting list, oldest trial first. They were never
    # shown to be weak: the reason says the evidence was missing, and their counts are left as recorded.
    room = max(0, waiting - len(losers))
    unjudged.sort(key=lambda t: (parse_stamp(t[0].pool_since) or now, t[0].key))
    for i, (g, why) in enumerate(unjudged):
        age = "unknown" if parse_stamp(g.pool_since) is None else f"{(now - parse_stamp(g.pool_since)).days} days"  # type: ignore[operator]
        if i < room:
            plan.decisions.append(Decision(g.key, "rotate", score(g, now), reason=f"rotated out: trial still unjudged after {age} ({why}); returned to the waiting list, no verdict on its hiring activity"))
        else:
            plan.decisions.append(Decision(g.key, "extend", score(g, now), reason=f"trial extended ({why}); unjudged after {age} but no relevant board is waiting for its slot"))
    return plan


def demote(rec: BoardRecord, now: datetime, reason: str) -> None:
    """Return a board to the waiting list without losing anything: validation, last success, counts,
    baseline, provenance and every ledger event stay, so a later re-entry re-establishes the baseline."""
    rec.status = STATUS_VALIDATED
    _leave_monitoring(rec, now, reason)


def apply_plan(registry: dict[str, BoardRecord], plan: RebalancePlan, now: datetime) -> list[BoardRecord]:
    """Apply a plan (mode "on"). Returns the changed records. Idempotent per decision set."""
    prefix = f"rebalance {_day(now)}: "
    changed: dict[str, BoardRecord] = {}
    for key, streak in sorted(plan.streaks.items()):
        rec = registry.get(key)
        if rec and rec.status in MONITORED and rec.weak_streak != streak:
            rec.weak_streak = streak
            changed[key] = rec

    def promote(rec: BoardRecord, reason: str) -> None:
        rec.pool, rec.pool_since, rec.trial_until, rec.weak_streak = POOL_ESTABLISHED, lg.stamp(now), "", 0
        rec.pool_reason = (prefix + reason)[:200]

    for d in plan.decisions:
        rec = registry.get(d.key)
        if rec is None or rec.status not in MONITORED:
            continue
        if d.action == "graduate":
            promote(rec, d.reason)
        elif d.action == "replace":
            promote(rec, d.reason)
            if (out := registry.get(d.partner)) is not None:
                demote(out, now, f"{prefix}replaced by {d.key} (score {score_or_zero(rec, now):.1f} vs {score_or_zero(out, now):.1f})")
                changed[out.key] = out
        elif d.action in ("return", "shed", "rotate"):
            demote(rec, now, prefix + d.reason)
        elif d.action in ("extend", "keep"):
            rec.trial_until = lg.stamp(now + timedelta(days=plan.trial_days))
            rec.pool_reason = (prefix + d.reason)[:200]
        elif d.action == "defer":
            rec.pool_reason = (prefix + d.reason)[:200]
        changed[rec.key] = rec
    return list(changed.values())


def score_or_zero(rec: BoardRecord, now: datetime) -> float:
    value = score(rec, now)
    return 0.0 if value is None else value


def rebalance_due(stamp_json: str | None, registry: dict[str, BoardRecord], now: datetime, policy: PoolPolicy) -> bool:
    """Due when no rebalance is recorded, or the last one was at least the interval (minus an hour of
    slack) ago. "Last" is the later of the Discovery-tab record and the newest row marked by a
    rebalance, so a crash between saving the boards and saving the record cannot repeat a cycle."""
    last: datetime | None = None
    try:
        at = json.loads(stamp_json).get("at") if stamp_json else None
        last = parse_stamp(str(at)) if at else None
    except (ValueError, AttributeError):
        last = None
    for rec in registry.values():
        if not rec.pool_reason.startswith("rebalance "):
            continue
        day = rec.pool_reason[len("rebalance "):len("rebalance ") + 10]
        marked = parse_stamp(rec.pool_since) if rec.pool_since[:10] == day else None
        if marked is None:
            marked = parse_stamp(f"{day}T00:00:00Z")
        if marked is not None and (last is None or marked > last):
            last = marked
    return last is None or now - last >= policy.interval - SLACK


# --------------------------------------------------------------------------- coverage and reporting (D12)


def coverage(
    registry: dict[str, BoardRecord], now: datetime, blocked: Callable[[str], Any] | None = None, cooldown: timedelta | None = None
) -> dict[str, Any]:
    """Pool membership, the relevant waiting list and how much of the relevant boards are actually polled."""
    monitored = [r for r in registry.values() if r.status in MONITORED]
    waiting = [r for r in registry.values() if is_waiting_candidate(r, blocked, now=now, cooldown=cooldown)]
    open_monitored = sum(1 for r in monitored if open_jobs_uncapped(r) > 0)
    oldest: float | None = None
    for r in waiting:
        since = parse_stamp(r.pool_since) or parse_stamp(r.last_validated_at)
        if since is not None:
            hours = (now - since).total_seconds() / 3600
            oldest = hours if oldest is None else max(oldest, hours)
    denominator = open_monitored + len(waiting)
    return {
        "established": sum(1 for r in monitored if r.pool == POOL_ESTABLISHED),
        "exploration": sum(1 for r in monitored if r.pool == POOL_EXPLORATION),
        "monitored": len(monitored),
        "waiting": len(waiting),
        "oldest_waiting_hours": None if oldest is None else int(oldest),
        "open_monitored": open_monitored,
        "coverage_pct": round(100 * open_monitored / denominator) if denominator else None,
    }


def format_plan(plan: RebalancePlan, cov: dict[str, Any], policy: PoolPolicy) -> list[str]:
    lines = [
        f"pools: established {plan.established}/{plan.established_target}, exploration {plan.exploration}/{plan.exploration_target}, "
        f"monitored {plan.monitored}/{plan.max_active}; {plan.waiting} relevant boards waiting"
        + (f" (oldest {cov['oldest_waiting_hours']} h)" if cov.get("oldest_waiting_hours") is not None else ""),
        f"protected: {plan.protected_trials} trials still running, {plan.unevidenced_established} established boards without enough evidence",
        f"replacements this cycle: {plan.replacements} of {plan.bound} allowed",
    ]
    for d in plan.decisions:
        who = f"{d.key} (score {d.score:.1f})" if d.score is not None else d.key
        lines.append(f"  {d.action:<9} {who}: {d.reason}")
    if not plan.decisions:
        lines.append("  no decisions: nothing is due")
    return lines


MAX_REPORT_JSON = 45000


def plan_json(plan: RebalancePlan, now: datetime, mode: str) -> str:
    """The plan as compact JSON for the Discovery tab (a cell holds at most 50,000 characters)."""
    decisions = [
        {"k": d.key, "a": d.action, **({"s": round(d.score, 2)} if d.score is not None else {}), **({"p": d.partner} if d.partner else {}), "r": d.reason}
        for d in plan.decisions
    ]
    body: dict[str, Any] = {
        "at": lg.stamp(now), "mode": mode,
        "targets": {"established": plan.established_target, "exploration": plan.exploration_target, "max_active": plan.max_active},
        "counts": {"established": plan.established, "exploration": plan.exploration, "waiting": plan.waiting,
                   "protected_trials": plan.protected_trials, "unevidenced_established": plan.unevidenced_established,
                   "replacements": plan.replacements, "bound": plan.bound},
        "decisions": decisions,
    }  # fmt: skip
    text = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    omitted = 0
    while len(text) > MAX_REPORT_JSON and decisions:
        decisions.pop()
        omitted += 1
        body["omitted_decisions"] = omitted
        text = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    return text


# --------------------------------------------------------------------------- dry run (D-30)


@dataclass
class Preview:
    sync: SyncResult
    plan: RebalancePlan
    cov: dict[str, Any]
    due: bool
    admission: list[BoardRecord]
    last_rebalance: str = ""


def preview(registry: dict[str, BoardRecord], states: dict[str, lg.JobState], policy: PoolPolicy, now: datetime,
            blocked: Callable[[str], Any] | None, stamp_json: str | None) -> Preview:
    """What the next run would do, computed on a deep copy: nothing in `registry` is changed and
    nothing is written. The plan is computed as if a rebalance were due right now."""
    work = copy.deepcopy(registry)
    sync = sync_pools(work, policy, now, blocked)
    index = ActivityIndex.from_states(states)
    for rec in work.values():
        if rec.status in MONITORED:
            refresh_activity(rec, index, now)
    plan = plan_rebalance(work, policy, now, blocked)
    last = ""
    try:
        last = str(json.loads(stamp_json).get("at", "")) if stamp_json else ""
    except (ValueError, AttributeError):
        last = ""
    return Preview(sync, plan, coverage(work, now, blocked, policy.cooldown), rebalance_due(stamp_json, registry, now, policy), admission_order(work, blocked, now=now, cooldown=policy.cooldown), last)


def format_report(pv: Preview, policy: PoolPolicy, now: datetime) -> str:
    """The dry-run board rebalance report (hunter.py --rebalance-report). Read-only."""
    p, cov = pv.plan, pv.cov
    lines = [
        "BOARD REBALANCE REPORT (dry run)", "",
        f"mode: {policy.mode} ({'the weekly rebalance is applied' if policy.mode == 'on' else 'the weekly rebalance only records a report; nobody moves'})",
        f"policy: Max_Active_Boards {policy.max_active} = established {policy.established_target} + exploration {policy.exploration_target} "
        f"({policy.exploration_pct}% exploration, initial choices, not proven values) | trial {policy.exploration_days} days | "
        f"rebalance every {policy.rebalance_every_days} days | at most {policy.max_replacements} established boards replaced per cycle",
        f"score = {RATE_WEIGHT:g} x min(new relevant postings per week, {RATE_CAP:g}) + min(open eligible jobs, {OPEN_CAP}); a trial must beat an "
        f"established board by more than {MARGIN:g}, which must be weak in {WEAK_CYCLES_TO_DEMOTE} consecutive cycles; decisions need "
        f"{policy.min_complete_polls} complete polls, a good last poll and evidence under 24 h old",
        "",
        "COVERAGE",
        f"  monitored {cov['monitored']}/{policy.max_active}: established {cov['established']}/{policy.established_target}, exploration {cov['exploration']}/{policy.exploration_target}",
        f"  relevant boards waiting for a slot: {cov['waiting']}"
        + (f" (oldest has waited {cov['oldest_waiting_hours']} h)" if cov["oldest_waiting_hours"] is not None else ""),
        f"  monitored boards with open relevant jobs: {cov['open_monitored']} -> relevant-board coverage "
        + (f"{cov['coverage_pct']}%" if cov["coverage_pct"] is not None else "n/a"),
        "",
        "WHAT THE NEXT RUN WOULD CHANGE BEFORE ANY REBALANCE",
        f"  monitored SmartRecruiters boards parked by provider policy: {len(pv.sync.parked)}",
        f"  boards monitored before pools existed that would start an exploration trial: {len(pv.sync.migrated)}",
        f"  stale pool labels that would be cleared: {len(pv.sync.cleared)}",
        "",
        "REBALANCE PLAN (as if run now)",
    ]
    lines += [f"  {ln}" for ln in format_plan(p, pv.cov, policy)]
    lines += ["", f"NEXT BOARDS TO ENTER A FREE SLOT (never-tried boards first; {len(pv.admission)} waiting in all)"]
    for r in pv.admission[:20]:
        lines.append(f"  {r.key}: {open_jobs_uncapped(r)} open eligible, {r.relevant_jobs} relevant jobs, {'trial ' + str(r.trials + 1) if r.trials else 'never tried'}")
    if not pv.admission:
        lines.append("  none")
    lines += [
        "",
        f"scheduled rebalance: {'due at the next run' if pv.due else 'not due yet'}"
        + (f" (last recorded {pv.last_rebalance})" if pv.last_rebalance else " (none recorded)"),
        "dry run: nothing was written",
    ]
    return "\n".join(lines)
