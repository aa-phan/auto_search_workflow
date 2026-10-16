"""Operational summary: one consistent set of numbers computed from the state the system already keeps.

Read-only and pure (no I/O, no LLM, no clock of its own): the caller loads Runs, Boards, Discovery, the Events
ledger and the tracker, and passes `now`. The same inputs always give the same summary, so a re-run is idempotent.
The output never feeds back into polling, admission, scoring or alerts (nothing here is read by the pipeline).

Metric rules this module enforces (see SPEC "Operational dashboard"):
  * unique jobs (ledger keys) are never mixed with attempts (evaluation retries, repeated errors, alert resends);
  * discovery source (poll | search) and ATS provider are separate breakdowns;
  * every freshness percentage carries its denominator and the count of jobs whose publication date is unknown;
  * publication -> detection and detection -> delivery latency are separate figures;
  * coverage is coverage of KNOWN ELIGIBLE boards, never of the job market;
  * runs recorded as rehearsals, the events they made and tracker fixtures are excluded;
  * zero (measured) is told apart from unknown (never measured, field missing, or not recorded at the time):
    unknown values are `None`;
  * counts that belong to different cohorts are not combined into a funnel: the job-outcome table partitions ONE
    cohort (jobs first observed in the period); event counts (alerts delivered, tracker additions) say so.
"""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any

import discovery as dsc
import freshness as fr
import inventory
import ledger as lg
from boards import MONITORED, STATUS_CANDIDATE, STATUS_DISABLED, STATUS_INVALID, STATUS_VALIDATED, BoardRecord
from search import BUDGET_KEY, SearchBudget
from state import CREDIT_UNRESOLVED, KIND_REHEARSAL, OUTCOME_DEGRADED, OUTCOME_FAILED, OUTCOME_OK, OUTCOME_STARTED, RunRecord

STAMP = "%Y-%m-%dT%H:%M:%SZ"
FIXTURE_MARKER = "TEST FIXTURE"  # hunter.FIXTURE_LABEL starts with it (asserted by a test): tracker fixtures never count
LATE_RUN_MIN = 90  # an hourly schedule arriving more than 90 minutes after the previous finished run is a polling gap
FEEDBACK = ("Would apply", "Maybe", "Irrelevant")
USER_STATUSES = ("Applied", "Interviewing", "Offer", "Pass", "Rejected")
APP_STATUSES = ("To Apply", "Stretch / Review")
REJECT_ORDER = ("title", "age", "location", "experience", "language", "closed", "score")  # stage order, earliest first
REJECT_LABELS = {
    "title": "Title (role/level words, excluded words)", "age": "Age (older than the maximum job age)",
    "location": "Location (outside the US)", "experience": "Experience (4+ years required)",
    "language": "Language (a required language is not on the resume)", "closed": "Posting closed or removed",
    "score": "Score (scored below the tracker threshold)",
}  # fmt: skip
MAX_FAILURE_ROWS = 15
DEGRADED_BOARD_SHARE = 0.2  # a provider is "degraded" when this share (and at least 3) of its monitored boards failed their last poll
_BACKOFF_RE = re.compile(r"provider backoff after HTTP 429: not polled this run: ([^;]+)")


# --------------------------------------------------------------------------- time helpers


def parse_stamp(value: Any) -> datetime | None:
    try:
        return datetime.strptime(str(value), STAMP).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _stamp(dt: datetime | None) -> str | None:
    return dt.strftime(STAMP) if dt else None


@dataclass(frozen=True)
class Period:
    key: str  # today | 7d | 30d
    label: str
    first_day: date  # first local calendar day (inclusive)
    last_day: date  # last local calendar day (inclusive; today)

    @property
    def days(self) -> int:
        return (self.last_day - self.first_day).days + 1

    def contains(self, day: date) -> bool:
        return self.first_day <= day <= self.last_day


def make_periods(now: datetime, tz: tzinfo) -> list[Period]:
    """Calendar days in the display time zone: `today` is the local day so far, `7d` today plus the six days before
    it, `30d` today plus the twenty-nine before. A moment at exactly local midnight belongs to the NEW day."""
    today = now.astimezone(tz).date()
    return [Period("today", "Today", today, today), Period("7d", "Last 7 days", today - timedelta(days=6), today),
            Period("30d", "Last 30 days", today - timedelta(days=29), today)]  # fmt: skip


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "median": None, "p90": None, "max": None}
    ordered = sorted(values)
    return {"n": len(values), "median": round(statistics.median(ordered), 1),
            "p90": round(ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))], 1), "max": round(ordered[-1], 1)}  # fmt: skip


def _json_dict(raw: str | None) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _hours(a: datetime, b: datetime) -> float:
    return round((a - b).total_seconds() / 3600, 1)


# --------------------------------------------------------------------------- per-job facts from the ledger


@dataclass
class JobFacts:
    key: str
    ats: str = ""
    seen_at: datetime | None = None
    freshness: str = ""
    disposition: str = ""
    source: str = ""  # discovery source: poll | search
    pass_kind: str = ""  # baseline | reentry | "" (ordinary observation)
    published: datetime | None = None
    precision: str = ""
    eval_at: datetime | None = None
    eval_status: str = ""
    eval_score: int | None = None
    eval_reject: str = ""  # stage that ended the evaluation ("" = scored and kept)
    eval_visible: bool = False
    eval_alert: bool = False
    eval_legacy: bool = False  # the reason was derived from recorded verdict text (written before reason codes existed)
    alert_times: list[datetime] = field(default_factory=list)  # every alerted event
    delivered_times: list[datetime] = field(default_factory=list)  # alerted events whose channel accepted the message
    alert_late: bool = False
    errors: Counter[str] = field(default_factory=Counter)  # stage -> attempts recorded against the job
    error_last: dict[str, tuple[datetime | None, str]] = field(default_factory=dict)
    error_first: dict[str, datetime | None] = field(default_factory=dict)
    abandoned: set[str] = field(default_factory=set)

    @property
    def date_known(self) -> bool:
        return self.published is not None

    def outcome(self) -> str:
        """The ONE state this job is in. Partitions every observed job (see `OUTCOMES`)."""
        if self.disposition == lg.BASELINED:
            return "baseline"
        if self.disposition == lg.STALED:
            return "age"
        if self.disposition == lg.FILTERED:
            return "title"
        if self.eval_at is None:
            return "abandoned" if lg.STAGE_EVALUATE in self.abandoned else "pending"
        return self.eval_reject if self.eval_reject in REJECT_ORDER else "kept"


OUTCOMES = ("baseline", *REJECT_ORDER, "kept", "pending", "abandoned")


def _legacy_reject(d: dict[str, Any]) -> str:
    """Reason for an evaluation written before reason codes existed, from the recorded status and verdict text.
    Labelled as derived in the report; nothing is invented when the text says nothing."""
    status, verdict = str(d.get("status", "")), str(d.get("verdict", ""))
    if status.startswith("Closed"):
        return "closed"
    if status.startswith("Stale"):
        return "age"
    if status == "Filtered Out":
        if verdict.startswith("Filtered before scoring:"):
            low = verdict.lower()
            if "outside the us" in low:
                return "location"
            if "years of experience" in low:
                return "experience"
            if "excluded title word" in low or "no target" in low:
                return "title"
            return "language"
        return "score"
    return ""


def job_facts(events: list[lg.Event]) -> dict[str, JobFacts]:
    """One pass over the (already filtered) ledger. First `seen` and first `evaluated` win, like `ledger.replay`."""
    facts: dict[str, JobFacts] = {}
    for ev in events:
        f = facts.get(ev.key)
        if f is None:
            f = facts[ev.key] = JobFacts(ev.key, ats=ev.key.split("|")[0])
        t = parse_stamp(ev.time)
        if ev.event == lg.SEEN and f.seen_at is None:
            d = ev.detail
            f.seen_at, f.freshness, f.disposition = t, ev.freshness, ev.disposition
            source = str(d.get("source") or "")
            f.source = "search" if source in {"serper", "search"} else source or "unknown"
            f.pass_kind = str(d.get("pass") or "")
            f.published, f.precision = fr.parse_instant(ev.published) if ev.published else (None, "")
            f.precision = str(d.get("precision") or f.precision)
        elif ev.event == lg.EVALUATED and f.eval_at is None:
            d = ev.detail
            f.eval_at, f.eval_status = t, str(d.get("status", ""))
            f.eval_score = d.get("score") if isinstance(d.get("score"), int) else None
            f.eval_visible, f.eval_alert = bool(d.get("visible")), bool(d.get("alert"))
            if "reject" in d:
                f.eval_reject = str(d.get("reject") or "")
            else:
                f.eval_reject, f.eval_legacy = _legacy_reject(d), True
        elif ev.event == lg.ALERTED and t:
            f.alert_times.append(t)
            if ev.detail.get("channel") == "telegram":
                f.delivered_times.append(t)
            f.alert_late = f.alert_late or bool(ev.detail.get("late"))
        elif ev.event == lg.ERROR:
            stage = str(ev.detail.get("stage", "?"))
            f.errors[stage] += 1
            f.error_last[stage] = (t, str(ev.detail.get("message", "")))
            f.error_first.setdefault(stage, t)
        elif ev.event == lg.ABANDONED:
            f.abandoned.add(str(ev.detail.get("stage", "")))
    return facts


# --------------------------------------------------------------------------- input cleaning


@dataclass
class Clean:
    runs: list[RunRecord]  # production (or unlabelled) runs, one per Run_ID, finished records preferred
    events: list[lg.Event]
    tracker: list[dict[str, str]]
    excluded_rehearsal_runs: int
    excluded_rehearsal_events: int
    excluded_fixture_rows: int
    duplicate_run_records: int


def clean_inputs(runs: list[RunRecord], events: list[lg.Event], tracker: list[dict[str, str]]) -> Clean:
    """Drop rehearsal runs (and the events they made), collapse a run's start record and finished record into one,
    and drop tracker fixtures."""
    by_id: dict[str, RunRecord] = {}
    ordered: list[RunRecord] = []
    dupes = 0
    for r in runs:
        if not r.run_id:
            ordered.append(r)  # written before run ids existed: kept as is
            continue
        if r.run_id in by_id:
            dupes += 1
            if by_id[r.run_id].completed and not r.completed:
                continue  # a finished record already stands for this run
            ordered[ordered.index(by_id[r.run_id])] = r
        else:
            ordered.append(r)
        by_id[r.run_id] = r
    rehearsal = {r.run_id for r in ordered if r.run_kind == KIND_REHEARSAL and r.run_id}
    kept_runs = [r for r in ordered if r.run_kind != KIND_REHEARSAL]
    kept_events = [e for e in events if str(e.detail.get("run", "")) not in rehearsal] if rehearsal else list(events)
    rows = [row for row in tracker if not _is_fixture(row)]
    return Clean(kept_runs, kept_events, rows, len(ordered) - len(kept_runs), len(events) - len(kept_events), len(tracker) - len(rows), dupes)


def _is_fixture(row: dict[str, str]) -> bool:
    return FIXTURE_MARKER in (row.get("Freshness") or "") or FIXTURE_MARKER in (row.get("Source") or "") or (row.get("Apply_URL") or "").startswith("https://example.invalid")


# --------------------------------------------------------------------------- the summary


def build_summary(
    *,
    now: datetime,
    tz: tzinfo = timezone.utc,
    runs: list[RunRecord],
    events: list[lg.Event],
    boards: dict[str, BoardRecord],
    discovery: dict[str, str],
    tracker: list[dict[str, str]],
    fresh_window: timedelta = timedelta(hours=fr.DEFAULT_FRESH_WINDOW_HOURS),
    search_cap: int = 1000,
    search_reserve: int = 200,
    established_target: int = 400,
    exploration_target: int = 100,
    run_timeout_s: int = 25 * 60,
    min_alert_score: int = 70,
) -> dict[str, Any]:  # fmt: skip
    """Everything the dashboard shows, as plain data. `now` and `tz` are the only sources of time."""
    clean = clean_inputs(runs, events, tracker)
    facts = job_facts(clean.events)
    periods = make_periods(now, tz)
    local = lambda t: t.astimezone(tz).date()  # noqa: E731
    finished = [r for r in clean.runs if r.completed]
    started_only = [r for r in clean.runs if not r.completed]

    # ---- bucket everything by local calendar day once; periods are sums over days
    day: dict[date, Counter[str]] = defaultdict(Counter)
    lat_pub: dict[date, list[float]] = defaultdict(list)  # publication -> detection, minutes (by day first seen)
    lat_del: dict[date, list[float]] = defaultdict(list)  # detection -> delivery, minutes (by day delivered)
    for f in facts.values():
        if f.seen_at is not None:
            c = day[local(f.seen_at)]
            out = f.outcome()
            c["seen"] += 1
            c[f"out:{out}"] += 1
            c[f"ats:{f.ats}"] += 1
            if out != "baseline":
                c["seen_new"] += 1
                c[f"src:{f.source}"] += 1
                c[f"new_ats:{f.ats}"] += 1
                c["new_date_known" if f.date_known else "new_date_unknown"] += 1
                if f.disposition == lg.PENDING:  # passed the cheap gates and is not stale: the jobs freshness is judged on
                    c["rel"] += 1
                    c[f"rel:{f.freshness}"] += 1
                    c["rel_date_known" if f.date_known else "rel_date_unknown"] += 1
            if out in ("kept", "score"):
                c["eligible"] += 1
            if out == "kept":
                c["match"] += 1
                if f.freshness == fr.VERIFIED_FRESH:
                    c["match_vf"] += 1
                elif f.date_known:
                    c["match_dated_not_fresh"] += 1
                else:
                    c["match_date_unknown"] += 1
                if f.source == "search" and f.freshness == fr.VERIFIED_FRESH:
                    c["search_vf_match"] += 1
            if f.eval_legacy and f.eval_at is not None:
                c["legacy_reason"] += 1
            if (f.freshness == fr.VERIFIED_FRESH and f.disposition == lg.PENDING and f.precision == fr.TIME and f.published is not None and not f.pass_kind and f.seen_at >= f.published):
                lat_pub[local(f.seen_at)].append((f.seen_at - f.published).total_seconds() / 60)
        if f.eval_at is not None:
            day[local(f.eval_at)]["evaluated_events"] += 1
            if f.eval_visible:
                day[local(f.eval_at)]["tracker_added"] += 1
        for i, t in enumerate(f.delivered_times):
            c = day[local(t)]
            c["alert_deliveries"] += 1
            if i == 0:
                c["alert_unique"] += 1
                if f.seen_at is not None and t >= f.seen_at:
                    lat_del[local(t)].append((t - f.seen_at).total_seconds() / 60)
            else:
                c["alert_repeat"] += 1
        for i, t in enumerate(f.alert_times):
            if t not in f.delivered_times:
                day[local(t)]["alert_undelivered"] += 1
        if f.alert_late and f.delivered_times:
            day[local(f.delivered_times[0])]["alert_late"] += 1
        for stage, n in f.errors.items():
            t = f.error_last.get(stage, (None, ""))[0]
            if t:
                day[local(t)][f"errors:{stage}"] += n
    expected_from = parse_stamp(finished[0].run_at) if finished else None
    gaps_by_day: dict[date, list[int]] = defaultdict(list)
    for r in clean.runs:
        t = parse_stamp(r.run_at)
        if t is None:
            continue
        c = day[local(t)]
        c["runs"] += 1
        if r.outcome == OUTCOME_STARTED:
            c["runs_unfinished"] += 1
            continue
        c["runs_finished"] += 1
        c[f"run_{r.outcome or 'unrecorded'}"] += 1
        c["search_credits"] += r.search_credits
        c["search_failed"] += r.search_failed
        c["discovery_runs"] += bool(r.discovery)
        c["eval_attempts"] += r.eval_attempted
        c["eval_transient"] += r.eval_transient
        c["eval_failed"] += r.eval_failed
        c["boards_ok"] += r.boards_ok
        c["boards_failed"] += r.boards_failed
        if r.gap_since_prev_run_min is not None:
            gaps_by_day[local(t)].append(r.gap_since_prev_run_min)

    def total(p: Period, name: str) -> int:
        return sum(c[name] for d_, c in day.items() if p.contains(d_))

    def lat(p: Period, store: dict[date, list[float]]) -> dict[str, Any]:
        return _stats([v for d_, vals in store.items() if p.contains(d_) for v in vals])

    # ---- results / rejections / freshness, per period
    first_event = min((t for f in facts.values() if (t := f.seen_at)), default=None)
    per_period: dict[str, dict[str, Any]] = {}
    for p in periods:
        outcomes = {o: total(p, f"out:{o}") for o in OUTCOMES}
        seen = total(p, "seen")
        rel = total(p, "rel")
        vf = total(p, "rel:" + fr.VERIFIED_FRESH)
        dated = total(p, "rel_date_known")
        per_period[p.key] = {
            "label": p.label, "days": p.days, "from": p.first_day.isoformat(), "to": p.last_day.isoformat(),
            "results": {
                "unique_jobs_observed": seen, "existing_postings_baselined": outcomes["baseline"], "new_postings": total(p, "seen_new"),
                "new_by_source": {s: total(p, f"src:{s}") for s in sorted({k[4:] for c in day.values() for k in c if k.startswith("src:")})},
                "new_by_ats": {a: total(p, f"new_ats:{a}") for a in sorted({k[8:] for c in day.values() for k in c if k.startswith("new_ats:")})},
                "eligible_matches_scored": total(p, "eligible"), "matches_kept": total(p, "match"), "verified_fresh_matches": total(p, "match_vf"),
                "matches_date_unknown": total(p, "match_date_unknown"), "matches_dated_not_fresh": total(p, "match_dated_not_fresh"),
                "tracker_additions": total(p, "tracker_added"),
                "alerts_delivered": total(p, "alert_deliveries"), "alerts_unique_jobs": total(p, "alert_unique"),
                "alerts_repeat_deliveries": total(p, "alert_repeat"), "alert_events_not_delivered": total(p, "alert_undelivered"),
                "alerts_late": total(p, "alert_late"),
            },
            "outcomes": outcomes,
            "freshness": {
                "cohort_jobs": rel, "verified_fresh": vf, "dated": dated, "date_unknown": total(p, "rel_date_unknown"),
                "verified_fresh_share_of_dated_pct": round(100 * vf / dated) if dated else None,
                "new_postings_date_unknown": total(p, "new_date_unknown"), "new_postings_date_known": total(p, "new_date_known"),
                "by_class": {k: total(p, f"rel:{k}") for k in (fr.VERIFIED_FRESH, fr.OBSERVED_NEW, fr.RECENT, fr.UNCERTAIN)},
            },
            "latency_min": {"publication_to_detection": lat(p, lat_pub), "detection_to_delivery": lat(p, lat_del)},
            "legacy_reason_codes": total(p, "legacy_reason"),
            "errors_recorded": {s: total(p, f"errors:{s}") for s in ("evaluate", "alert")},
            "attempts": {"evaluation": total(p, "eval_attempts"), "evaluation_transient": total(p, "eval_transient"), "evaluation_failed": total(p, "eval_failed")},
        }

    # ---- health
    health = _health(now, tz, periods, clean, finished, started_only, boards, day, gaps_by_day, expected_from, run_timeout_s, per_period)
    # ---- discovery
    disc = _discovery(now, tz, periods, clean, finished, boards, facts, discovery, day, search_cap, search_reserve, per_period, local)
    # ---- board coverage
    coverage = _coverage(now, finished, boards, discovery, established_target, exploration_target)
    # ---- failures
    failures = _failures(now, clean, facts, discovery, run_timeout_s, started_only, finished, health)
    # ---- feedback
    feedback = _feedback(clean.tracker, min_alert_score)
    # ---- daily trend (last 30 local days, newest first); None = nothing was recorded that day (unknown, not zero)
    first_any = min([d_ for d_, c in day.items() if c], default=None)
    trend = []
    for i in range(30):
        d_ = periods[-1].last_day - timedelta(days=i)
        c = day.get(d_, Counter())
        known = first_any is not None and d_ >= first_any
        g = gaps_by_day.get(d_, [])
        trend.append({
            "date": d_.isoformat(), "recorded": known,
            "runs_finished": c["runs_finished"] if known else None, "runs_ok": (c["run_ok"] + c["run_unrecorded"]) if known else None, "runs_not_ok": (c["run_degraded"] + c["run_failed"] + c["runs_unfinished"]) if known else None,
            "max_gap_min": max(g) if g else None, "new_postings": c["seen_new"] if known else None, "baselined": c["out:baseline"] if known else None,
            "eligible": c["eligible"] if known else None, "verified_fresh_matches": c["match_vf"] if known else None,
            "tracker_additions": c["tracker_added"] if known else None, "alerts_delivered": c["alert_deliveries"] if known else None,
            "search_credits": c["search_credits"] if known else None,
        })  # fmt: skip

    checks = _checks(per_period, facts, clean, periods)
    newest_event = max((t for e in clean.events if (t := parse_stamp(e.time))), default=None)
    newest_run = max((t for r in clean.runs if (t := parse_stamp(r.run_at))), default=None)
    summary = {
        "generated_at": _stamp(now), "timezone": str(tz), "default_view": "7d", "fresh_window_hours": fresh_window.total_seconds() / 3600,
        "source_freshness": {
            "latest_run_record": _stamp(newest_run), "latest_ledger_event": _stamp(newest_event),
            "latest_run_age_hours": _hours(now, newest_run) if newest_run else None,
            "tracker_rows_read": len(clean.tracker), "boards_read": len(boards), "ledger_events_read": len(clean.events), "run_records_read": len(clean.runs),
        },
        "exclusions": {
            "rehearsal_runs": clean.excluded_rehearsal_runs, "events_from_rehearsal_runs": clean.excluded_rehearsal_events,
            "tracker_fixture_rows": clean.excluded_fixture_rows, "duplicate_run_records_merged": clean.duplicate_run_records,
        },
        "periods": per_period, "health": health, "discovery": disc, "coverage": coverage, "failures": failures, "feedback": feedback,
        "trend": trend, "checks": checks,
    }  # fmt: skip
    summary["headline"] = headline(summary)
    return summary


# --------------------------------------------------------------------------- sections


def _health(now, tz, periods, clean, finished, started_only, boards, day, gaps_by_day, expected_from, run_timeout_s, per_period) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    last_any = max(clean.runs, key=lambda r: r.run_at, default=None)
    last_finished = max(finished, key=lambda r: r.run_at, default=None)
    last_ok = max((r for r in finished if r.outcome in (OUTCOME_OK, "")), key=lambda r: r.run_at, default=None)

    def unfinished(r: RunRecord) -> str:
        t = parse_stamp(r.run_at)
        return "running" if t and (now - t).total_seconds() <= run_timeout_s + 600 else "interrupted"

    interrupted = [r for r in started_only if unfinished(r) == "interrupted"]
    running = [r for r in started_only if unfinished(r) == "running"]
    last = None
    if last_any:
        st = parse_stamp(last_any.run_at)
        last = {
            "run_id": last_any.run_id or None, "started_at": last_any.run_at, "finished_at": last_any.finished_at or None,
            "outcome": (unfinished(last_any) if not last_any.completed else last_any.outcome or "unrecorded"),
            "duration_s": last_any.duration_s if last_any.completed and last_any.duration_s else None,
            "notes": last_any.notes[:300], "kind": last_any.run_kind or "unrecorded",
            "hours_since_start": _hours(now, st) if st else None,
        }
    polling: dict[str, Any] = {}
    for p in periods:
        if not clean.runs and not finished:
            polling[p.key] = {"runs_finished": None}
            continue
        start = datetime.combine(p.first_day, datetime.min.time(), tz).astimezone(timezone.utc)
        begin = max(start, expected_from) if expected_from else None
        expected = int((now - begin).total_seconds() // 3600) if begin and now > begin else 0
        n_fin = sum(c["runs_finished"] for d_, c in day.items() if p.contains(d_))
        gaps = [g for d_, gs in gaps_by_day.items() if p.contains(d_) for g in gs]
        polling[p.key] = {
            "runs_finished": n_fin, "expected_hourly_slots": expected,
            "coverage_pct": round(100 * min(n_fin, expected) / expected) if expected else None,
            "gaps_over_threshold": sum(1 for g in gaps if g > LATE_RUN_MIN), "max_gap_min": max(gaps) if gaps else None, "gaps_known": len(gaps),
            "ok": sum(c["run_ok"] + c["run_unrecorded"] for d_, c in day.items() if p.contains(d_)),
            "degraded": sum(c["run_degraded"] for d_, c in day.items() if p.contains(d_)),
            "failed": sum(c["run_failed"] for d_, c in day.items() if p.contains(d_)),
            "interrupted": sum(1 for r in interrupted if (t := parse_stamp(r.run_at)) and p.contains(t.astimezone(tz).date())),
        }  # fmt: skip
    # degraded providers: boards whose last poll failed, per ATS, plus the latest run's 429 backoff note
    mon: Counter[str] = Counter()
    bad: Counter[str] = Counter()
    errors: dict[str, str] = {}
    for b in boards.values():
        if b.status in MONITORED or b.status == STATUS_DISABLED:
            mon[b.ats] += 1
            if b.consecutive_failures > 0 or b.status == STATUS_DISABLED:
                bad[b.ats] += 1
                errors.setdefault(b.ats, b.last_error[:120])
    backoff: Counter[str] = Counter()
    for r in finished[-24:]:
        for m in _BACKOFF_RE.finditer(r.notes):
            for part in m.group(1).split(","):
                bits = part.strip().split(" ", 1)
                if len(bits) == 2 and bits[0].isdigit():
                    backoff[bits[1].strip()] += 1
    providers = []
    for ats in sorted(set(mon) | set(backoff)):
        share = bad[ats] / mon[ats] if mon[ats] else 0
        degraded = (bad[ats] >= 3 and share >= DEGRADED_BOARD_SHARE) or backoff[ats] > 0
        providers.append({
            "provider": ats, "monitored": mon[ats], "failing_last_poll": bad[ats], "backoff_in_last_24_runs": backoff[ats],
            "degraded": degraded, "last_error": errors.get(ats, ""),
        })  # fmt: skip
    return {
        "last_run": last, "last_finished_run_at": last_finished.run_at if last_finished else None,
        "last_ok_run_at": last_ok.run_at if last_ok else None, "interrupted_runs": len(interrupted), "runs_in_progress": len(running),
        "polling": polling, "providers": providers, "degraded_providers": [p_["provider"] for p_ in providers if p_["degraded"]],
        "total_run_records": len(clean.runs),
    }  # fmt: skip


def _discovery(now, tz, periods, clean, finished, boards, facts, discovery, day, cap, reserve, per_period, local) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    raw = discovery.get(BUDGET_KEY)
    budget = SearchBudget.load(raw, now, cap=cap, reserve=reserve) if raw else None
    last_search_run = max((r for r in finished if r.discovery), key=lambda r: r.run_at, default=None)
    account = next((r.search_account_used for r in reversed(finished) if r.search_account_used is not None), None)
    credits: dict[str, Any] = {}
    for p in periods:
        runs_in = [r for r in finished if (t := parse_stamp(r.run_at)) and p.contains(local(t))]
        credits[p.key] = {
            "credits_spent": sum(r.search_credits for r in runs_in), "discovery_runs": sum(1 for r in runs_in if r.discovery),
            "failed_requests_billing_unknown": sum(r.search_failed for r in runs_in),
            "runs_credit_unresolved": sum(1 for r in runs_in if r.credit_status == CREDIT_UNRESOLVED),
            "runs_credit_not_recorded": sum(1 for r in runs_in if r.discovery and not r.credit_status),
        }
    rot_raw = discovery.get(dsc.ROTATION_KEY)
    rot = _json_dict(rot_raw) if rot_raw else {}
    rotation = None
    if rot:
        total_slots = int(rot.get("total") or 0)
        rotation = {
            "cursor": int(rot.get("cursor") or 0), "total_slots": total_slots or None, "full_passes": int(rot.get("cycles") or 0),
            "runs": int(rot.get("runs") or 0), "last_run_at": rot.get("last_run_at") or None,
        }
    # unique boards first found by search in each period that are eligible (validated or monitored) NOW
    search_sources = ("tavily", "serper")
    eligible_found: dict[str, int] = {}
    for p in periods:
        n = 0
        for b in boards.values():
            firsts = [parse_stamp(b.provenance[s].get("first")) for s in search_sources if isinstance(b.provenance.get(s), dict)]
            firsts = [t for t in firsts if t]
            if firsts and p.contains(local(min(firsts))) and (b.status == STATUS_VALIDATED or b.status in MONITORED):
                n += 1
        eligible_found[p.key] = n
    pending = dsc.load_pending(discovery.get(dsc.PENDING_KEY))
    month_used = budget.effective_used if budget else None
    return {
        "month": budget.month if budget else None,
        "ledger": None if budget is None else {
            "used_locally": budget.used, "calls": budget.calls, "by_path": budget.by_path, "cap": budget.cap, "reserve": budget.reserve,
            "remaining_scheduled": budget.remaining(scheduled=True), "remaining_manual": budget.remaining(scheduled=False),
            "limit_hit": budget.limit_hit, "month_matches_now": budget.rolled_from == "",
        },
        "account_counter_last_read": account, "account_minus_local": (account - budget.used) if (account is not None and budget and budget.rolled_from == "") else None,
        "month_used_effective": month_used, "periods": credits, "last_discovery_run_at": last_search_run.run_at if last_search_run else None,
        "unique_eligible_boards_found_by_search": eligible_found,
        "unique_verified_fresh_search_matches": {p.key: sum(c["search_vf_match"] for d_, c in day.items() if p.contains(d_)) for p in periods},
        "rotation": rotation, "hydration_retry_queue": len(pending),
        "note": "Credits are what the application recorded from each response; requests that failed before a response may have been billed (unresolved) and use outside this application is invisible here.",
    }  # fmt: skip


def _coverage(now, finished, boards, discovery, established_target, exploration_target) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    status: Counter[str] = Counter(b.status for b in boards.values())
    last = max(finished, key=lambda r: r.run_at, default=None)
    overdue_valid = overdue_invalid = never = 0
    oldest_overdue_days: float | None = None
    oldest_candidate_days: float | None = None
    for b in boards.values():
        if b.status == STATUS_VALIDATED:
            t = parse_stamp(b.last_validated_at)
            if t is None or now - t >= inventory.REVALIDATE_VALID_AFTER:
                overdue_valid += 1
                if t is not None:
                    oldest_overdue_days = max(oldest_overdue_days or 0, round((now - t - inventory.REVALIDATE_VALID_AFTER).total_seconds() / 86400, 1))
        elif b.status == STATUS_INVALID:
            t = parse_stamp(b.last_attempt_at) or parse_stamp(b.last_validated_at)
            if t is None or now - t >= inventory.REVALIDATE_INVALID_AFTER:
                overdue_invalid += 1
        elif b.status == STATUS_CANDIDATE:
            never += 1
            t = parse_stamp(b.discovered_at)
            if t:
                oldest_candidate_days = max(oldest_candidate_days or 0, round((now - t).total_seconds() / 86400, 1))
    monitored = [b for b in boards.values() if b.status in MONITORED]
    trials = [b for b in monitored if b.pool == "exploration"]
    ended = [b for b in trials if (t := parse_stamp(b.trial_until)) and t <= now]
    soon = [b for b in trials if (t := parse_stamp(b.trial_until)) and now < t <= now + timedelta(hours=48)]
    waiting_with_jobs = sum(1 for b in boards.values() if b.status == STATUS_VALIDATED and (b.eligible_jobs or 0) > 0)
    rebalance = _json_dict(discovery.get("rebalance"))
    return {
        "label": "Coverage of KNOWN eligible boards (the boards this system has found and validated), not of the job market.",
        "registry_boards": len(boards), "by_status": dict(sorted(status.items())),
        "established": sum(1 for b in monitored if b.pool == "established"), "exploration": len(trials), "monitored": len(monitored),
        "established_target": established_target, "exploration_target": exploration_target,
        "unpooled_monitored": sum(1 for b in monitored if b.pool not in ("established", "exploration")),
        "eligible_waiting_boards": waiting_with_jobs,
        "last_run_waiting_relevant": last.waiting_relevant if last and last.run_at else None,
        "oldest_waiting_hours": last.oldest_waiting_hours if last else None,
        "relevant_board_coverage_pct": last.relevant_coverage_pct if last else None, "as_of_run": last.run_at if last else None,
        "validation": {
            "revalidation_overdue_valid": overdue_valid, "revalidation_overdue_invalid": overdue_invalid, "never_validated": never,
            "oldest_overdue_days": oldest_overdue_days, "oldest_candidate_days": oldest_candidate_days,
        },
        "trials": {"ended_awaiting_rebalance": len(ended), "ending_within_48h": len(soon), "running": len(trials) - len(ended)},
        "last_rebalance": rebalance or None,
    }  # fmt: skip


def _failures(now, clean, facts, discovery, run_timeout_s, started_only, finished, health) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    pend_eval = [f for f in facts.values() if f.seen_at and f.disposition == lg.PENDING and f.eval_at is None and lg.STAGE_EVALUATE not in f.abandoned]
    pend_alert = [f for f in facts.values() if f.eval_at and f.eval_alert and not f.alert_times and lg.STAGE_ALERT not in f.abandoned]
    pending_hyd = dsc.load_pending(discovery.get(dsc.PENDING_KEY))
    hyd_ages = [(now - t).total_seconds() / 3600 for e in pending_hyd.values() if (t := parse_stamp(e.get("first_at")))]
    rows: list[dict[str, Any]] = []
    for f in facts.values():
        for stage, n in f.errors.items():
            ab = stage in f.abandoned
            last_t, msg = f.error_last.get(stage, (None, ""))
            if n >= 2 or ab:
                rows.append({
                    "severity": 0 if ab else 1, "what": f"{stage} failing for job", "ref": f.key, "count": n, "since": _stamp(f.error_first.get(stage)),
                    "last": _stamp(last_t), "detail": msg[:160],
                    "action": ("Abandoned after repeated failures: open the posting and check it, or ignore." if ab else "Retrying automatically on later runs."),
                })  # fmt: skip
    for f in pend_eval:
        age = _hours(now, f.seen_at) if f.seen_at else None
        if age is not None and age >= 24:
            rows.append({"severity": 1, "what": "awaiting evaluation", "ref": f.key, "count": 1, "since": _stamp(f.seen_at), "last": None,
                         "detail": f"pending {age:g} h", "action": "Check Groq availability or the run's evaluation limit; it retries automatically."})  # fmt: skip
    for f in pend_alert:
        age = _hours(now, f.eval_at) if f.eval_at else None
        if age is not None and age >= 2:
            rows.append({"severity": 0, "what": "alert not delivered", "ref": f.key, "count": 1, "since": _stamp(f.eval_at), "last": None,
                         "detail": f"pending {age:g} h", "action": "Check Telegram credentials and chat; it retries every run."})  # fmt: skip
    for r in clean.runs:
        if r.outcome in (OUTCOME_FAILED, OUTCOME_DEGRADED):
            rows.append({"severity": 0 if r.outcome == OUTCOME_FAILED else 2, "what": f"run {r.outcome}", "ref": r.run_id or r.run_at, "count": 1, "since": r.run_at,
                         "last": r.finished_at or None, "detail": r.notes[:160], "action": "Read the run's log in GitHub Actions."})  # fmt: skip
    for r in started_only:
        t = parse_stamp(r.run_at)
        if t and (now - t).total_seconds() > run_timeout_s + 600:
            rows.append({"severity": 0, "what": "run interrupted", "ref": r.run_id or r.run_at, "count": 1, "since": r.run_at, "last": None,
                         "detail": "started, never finished", "action": "Check the Actions run (timeout, cancel or runner loss); state of that run was not saved."})  # fmt: skip
    for p in health["providers"]:
        if p["degraded"]:
            rows.append({"severity": 1, "what": "provider degraded", "ref": p["provider"], "count": p["failing_last_poll"], "since": None, "last": None,
                         "detail": f"{p['failing_last_poll']} of {p['monitored']} monitored boards failed their last poll; 429 backoffs {p['backoff_in_last_24_runs']}; {p['last_error']}",
                         "action": "Usually transient; persistent 429s mean lowering that provider's rate."})  # fmt: skip
    rows.sort(key=lambda x: (x["severity"], -(x["count"] or 0), str(x["ref"])))
    unique_failing = {f.key for f in facts.values() if f.errors}
    return {
        "pending_evaluation": {"jobs": len(pend_eval), "oldest_hours": max((_hours(now, f.seen_at) for f in pend_eval if f.seen_at), default=None)},
        "pending_alert": {"jobs": len(pend_alert), "oldest_hours": max((_hours(now, f.eval_at) for f in pend_alert if f.eval_at), default=None)},
        "pending_hydration": {"jobs": len(pending_hyd), "oldest_hours": round(max(hyd_ages), 1) if hyd_ages else None},
        "unique_jobs_with_errors": len(unique_failing), "error_attempts_total": sum(sum(f.errors.values()) for f in facts.values()),
        "abandoned_jobs": sum(1 for f in facts.values() if f.abandoned),
        "table": rows[:MAX_FAILURE_ROWS], "table_total": len(rows),
    }  # fmt: skip


def _feedback(tracker: list[dict[str, str]], min_alert_score: int) -> dict[str, Any]:
    labelled = Counter({k: 0 for k in FEEDBACK})
    other = unlabelled = 0
    status: Counter[str] = Counter()
    for row in tracker:
        label = (row.get("My_Feedback") or "").strip()
        if not label:
            unlabelled += 1
        elif label in labelled:
            labelled[label] += 1
        else:
            other += 1
        status[(row.get("My_Status") or "").strip() or "(blank)"] += 1
    n = sum(labelled.values())
    return {
        "scope": "all tracker rows (the tracker is the user's record; rows carry no reliable period)",
        "tracker_rows": len(tracker), "feedback": dict(labelled), "unlabelled": unlabelled, "other_text": other, "labelled_total": n,
        "would_apply_pct_of_labelled": round(100 * labelled["Would apply"] / n) if n else None,
        "would_apply_or_maybe_pct_of_labelled": round(100 * (labelled["Would apply"] + labelled["Maybe"]) / n) if n else None,
        "status": {s: status.get(s, 0) for s in (*APP_STATUSES, *USER_STATUSES)},
        "status_other": sum(v for k, v in status.items() if k not in (*APP_STATUSES, *USER_STATUSES, "(blank)")),
        "status_blank": status.get("(blank)", 0),
        "applied_or_further": sum(status.get(s, 0) for s in ("Applied", "Interviewing", "Offer", "Rejected")),
    }  # fmt: skip


def _checks(per_period: dict[str, Any], facts: dict[str, JobFacts], clean: Clean, periods: list[Period]) -> list[str]:
    """Internal consistency checks; an empty list means every one passed. Shown on the dashboard when not."""
    problems = []
    for key, p in per_period.items():
        if sum(p["outcomes"].values()) != p["results"]["unique_jobs_observed"]:
            problems.append(f"{key}: job outcomes do not add up to the unique jobs observed")
        if p["results"]["matches_kept"] != p["results"]["verified_fresh_matches"] + p["results"]["matches_date_unknown"] + p["results"]["matches_dated_not_fresh"]:
            problems.append(f"{key}: match freshness split does not add up")
        if p["results"]["eligible_matches_scored"] != p["outcomes"]["kept"] + p["outcomes"]["score"]:
            problems.append(f"{key}: eligible matches differ from kept + score-rejected")
        if p["results"]["alerts_delivered"] != p["results"]["alerts_unique_jobs"] + p["results"]["alerts_repeat_deliveries"]:
            problems.append(f"{key}: alert deliveries differ from unique + repeats")
    seen = [per_period[k]["results"]["unique_jobs_observed"] for k in ("today", "7d", "30d")]
    if not seen[0] <= seen[1] <= seen[2]:
        problems.append("periods are not nested")
    return problems


# --------------------------------------------------------------------------- plain-English summary (deterministic)


def headline(s: dict[str, Any]) -> dict[str, Any]:
    """A status word and plain sentences chosen by fixed rules (no model involved)."""
    h, p7 = s["health"], s["periods"]["7d"]
    pol = h["polling"]["7d"]
    last = h["last_run"]
    problems: list[str] = []
    warnings: list[str] = []
    if last is None:
        return {"status": "No data yet", "color": "grey", "lines": ["No run has been recorded yet. The dashboard fills in after the first scheduled run."]}
    age = last["hours_since_start"]
    if h["interrupted_runs"]:
        problems.append(f"{h['interrupted_runs']} run(s) started and never finished")
    if last["outcome"] == "failed":
        problems.append("the latest run failed")
    if age is not None and age > 3:
        problems.append(f"no run has started for {age:g} hours (hourly expected)")
    if last["outcome"] == "degraded":
        warnings.append("the latest run finished with problems")
    if pol.get("gaps_over_threshold"):
        warnings.append(f"{pol['gaps_over_threshold']} polling gap(s) over {LATE_RUN_MIN} minutes in the last 7 days")
    if h["degraded_providers"]:
        warnings.append("degraded provider(s): " + ", ".join(h["degraded_providers"]))
    f = s["failures"]
    if f["pending_alert"]["jobs"]:
        problems.append(f"{f['pending_alert']['jobs']} alert(s) waiting to be delivered")
    if f["pending_evaluation"]["oldest_hours"] is not None and f["pending_evaluation"]["oldest_hours"] > 24:
        warnings.append(f"a job has waited {f['pending_evaluation']['oldest_hours']:g} hours for evaluation")
    if s["checks"]:
        warnings.append("dashboard consistency checks failed (see the bottom of this tab)")
    status, color = ("Needs attention", "red") if problems else ("Watch", "yellow") if warnings else ("Healthy", "green")
    lines = []
    lines.append(f"{status}: " + ("; ".join(problems + warnings) + "." if problems or warnings else "the latest run finished normally and nothing is waiting."))
    when = last["started_at"].replace("T", " ").replace("Z", "")
    lines.append(f"Last run started {when} UTC ({last['outcome']}){'' if age is None else f', {age:g} h ago'}.")
    r = p7["results"]
    lines.append(
        f"Last 7 days: {r['new_postings']} new postings and {r['existing_postings_baselined']} existing ones recorded; {r['eligible_matches_scored']} reached scoring, "
        f"{r['matches_kept']} kept for the tracker ({r['verified_fresh_matches']} verified fresh, {r['matches_date_unknown']} with an unknown posting date); "
        f"{r['alerts_delivered']} alert(s) delivered."
    )
    return {"status": status, "color": color, "lines": lines}


# --------------------------------------------------------------------------- plain-text rendering (CLI / tests)


def format_text(s: dict[str, Any]) -> str:
    h, p7 = s["headline"], s["periods"]["7d"]
    out = [f"DASHBOARD generated {s['generated_at']} (latest run record {s['source_freshness']['latest_run_record']}, latest ledger event {s['source_freshness']['latest_ledger_event']})", ""]
    out += h["lines"] + ["", "RESULTS (jobs first observed in the period unless stated)"]
    for key in ("today", "7d", "30d"):
        r = s["periods"][key]["results"]
        out.append(
            f"  {s['periods'][key]['label']:13s} observed {r['unique_jobs_observed']} (new {r['new_postings']}, baseline {r['existing_postings_baselined']}) | scored {r['eligible_matches_scored']} | "
            f"kept {r['matches_kept']} (fresh {r['verified_fresh_matches']}, date unknown {r['matches_date_unknown']}) | tracker +{r['tracker_additions']} | alerts delivered {r['alerts_delivered']} "
            f"({r['alerts_unique_jobs']} unique jobs, {r['alerts_repeat_deliveries']} repeats)"
        )
    out += ["", "OUTCOME OF JOBS FIRST OBSERVED IN THE LAST 7 DAYS (one cohort, each job once)"]
    n = p7["results"]["unique_jobs_observed"]
    for o in OUTCOMES:
        out.append(f"  {o:10s} {p7['outcomes'][o]:6d}" + (f"  ({round(100 * p7['outcomes'][o] / n)}% of {n})" if n else ""))
    fr7 = p7["freshness"]
    out.append(f"  freshness of new postings that passed the cheap gates: {fr7['verified_fresh']} verified fresh of {fr7['dated']} dated ({fr7['verified_fresh_share_of_dated_pct']}%); {fr7['date_unknown']} have no date")
    return "\n".join(out)
