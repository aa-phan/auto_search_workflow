"""Pilot measurements: what the system actually did over a window, computed from the state it already keeps.

Read-only and pure (no I/O): the caller loads the Runs log, the Events ledger, the Boards registry, the
Discovery-tab values and the tracker rows. Nothing here adds a score, a gate or a feature to the pipeline.
Every number states what it counts; where a figure cannot be known from the state (for example a run that
never started, or requests made outside this application) the report says so instead of guessing.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta
from typing import Any

import freshness as fr
import ledger as lg
from boards import MONITORED, STATUS_VALIDATED, BoardRecord
from search import BUDGET_KEY, SearchBudget
from state import RunRecord

LATE_RUN_MIN = 90  # an hourly schedule that arrives more than 90 minutes after the previous run counts as a late run
FEEDBACK = ("Would apply", "Maybe", "Irrelevant")


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    p = lambda q: ordered[min(len(ordered) - 1, int(q * len(ordered)))]  # noqa: E731
    return {"n": len(values), "median": round(statistics.median(ordered), 1), "p90": round(p(0.9), 1), "max": round(ordered[-1], 1)}


def _parse(value: str, tz: Any) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=tz)
    except (ValueError, TypeError):
        return None


def build_report(
    *,
    now: datetime,
    days: int,
    runs: list[RunRecord],
    events: list[lg.Event],
    boards: dict[str, BoardRecord],
    discovery: dict[str, str],
    tracker: list[dict[str, str]],
    fresh_window: timedelta,
    search_cap: int,
    search_reserve: int,
    max_active: int = 500,
    run_timeout_s: int = 25 * 60,
) -> dict[str, Any]:  # fmt: skip
    start = now - timedelta(days=days)
    unfinished = [r for r in runs if not r.completed]  # run-start records never completed: shown, never counted as runs
    runs = [r for r in runs if r.completed]
    in_window = [r for r in runs if (t := _parse(r.run_at, now.tzinfo)) and t >= start]
    expected = days * 24

    # ---- polling gaps
    gaps = [float(r.gap_since_prev_run_min) for r in in_window if r.gap_since_prev_run_min is not None]
    board_gaps = [float(r.max_board_gap_min) for r in in_window if r.max_board_gap_min is not None]
    triggers: dict[str, int] = {}
    for r in in_window:
        marker = next((part.split("=", 1)[1] for part in (r.notes or "").split("; ") if part.startswith("trigger=")), "unrecorded")
        triggers[marker] = triggers.get(marker, 0) + 1
    polling = {
        "runs_by_trigger": dict(sorted(triggers.items())),  # `schedule` runs are the proof that the schedule fires; a manual run is not
        "runs": len(in_window), "unfinished_run_records": len(unfinished), "expected_hourly_runs": expected, "run_coverage_pct": round(100 * len(in_window) / expected) if expected else None,
        "gap_minutes": _stats(gaps), "late_runs_over_90_min": sum(1 for g in gaps if g > LATE_RUN_MIN),
        "worst_board_gap_minutes": _stats(board_gaps), "board_poll_failures": sum(r.boards_failed for r in in_window),
        "boards_polled": sum(r.boards_ok for r in in_window),
    }  # fmt: skip

    states = lg.replay(events)
    seen_in_window = {k: s for k, s in states.items() if s.seen and (t := _parse(s.seen_time, now.tzinfo)) and t >= start}

    # ---- relevant fresh jobs by source (title gate passed, verified fresh by the source's own timestamp)
    by_source: dict[str, dict[str, int]] = {}
    discovery_latency: dict[str, list[float]] = {}
    for s in seen_in_window.values():
        if s.freshness != fr.VERIFIED_FRESH or s.disposition != lg.PENDING:
            continue
        d = s.seen_detail or {}
        source = str(d.get("source") or "?")
        source = "search" if source == "serper" else source  # rows written before the provider change
        kind = "baseline_pass" if d.get("pass") == "baseline" else "reentry_pass" if d.get("pass") == "reentry" else "new"
        row = by_source.setdefault(source, {"new": 0, "baseline_pass": 0, "reentry_pass": 0, "evaluated": 0, "to_apply": 0, "alerted": 0})
        row[kind] += 1
        row["evaluated"] += s.evaluated is not None
        row["to_apply"] += bool(s.evaluated and s.evaluated.get("alert"))
        row["alerted"] += s.alerted
        age = d.get("age_min")
        if kind == "new" and isinstance(age, (int, float)) and d.get("precision") == "time" and age >= 0:
            discovery_latency.setdefault(source, []).append(float(age))

    # ---- delivery latency, late and duplicate alerts
    alert_events = [e for e in events if e.event == lg.ALERTED and (t := _parse(e.time, now.tzinfo)) and t >= start]
    publication_to_alert = [float(e.detail["lag_min"]) for e in alert_events if isinstance(e.detail.get("lag_min"), (int, float))]
    seen_to_alert = []
    for e in alert_events:
        st = states.get(e.key)
        a, b = _parse(e.time, now.tzinfo), _parse(st.seen_time, now.tzinfo) if st else None
        if a and b:
            seen_to_alert.append((a - b).total_seconds() / 60)
    all_alert_counts: dict[str, int] = {}
    for e in events:
        if e.event == lg.ALERTED:
            all_alert_counts[e.key] = all_alert_counts.get(e.key, 0) + 1
    window_minutes = fresh_window.total_seconds() / 60
    delivery = {
        "alerts_sent": len(alert_events),
        "publication_to_alert_minutes": _stats(publication_to_alert),
        "first_seen_to_alert_minutes": _stats(seen_to_alert),
        "late_alerts": sum(1 for e in alert_events if e.detail.get("late")),
        "alerts_later_than_the_window": sum(1 for m in publication_to_alert if m > window_minutes),
        "duplicate_alerts": sum(n - 1 for n in all_alert_counts.values() if n > 1),
        "discovery_latency_minutes_by_source": {k: _stats(v) for k, v in sorted(discovery_latency.items())},
    }  # fmt: skip

    # ---- pending failures (now) and errors in the window
    todo = [s for s in states.values() if lg.needs_evaluation(s)]
    pending_alerts = [s for s in states.values() if lg.needs_alert(s, now)]
    oldest = [(now - t).total_seconds() / 3600 for s in todo if (t := _parse(s.seen_time, now.tzinfo))]
    errors: dict[str, int] = {}
    abandoned = 0
    for e in events:
        t = _parse(e.time, now.tzinfo)
        if not t or t < start:
            continue
        if e.event == lg.ERROR:
            errors[str(e.detail.get("stage", "?"))] = errors.get(str(e.detail.get("stage", "?")), 0) + 1
        elif e.event == lg.ABANDONED:
            abandoned += 1
    failures = {
        "awaiting_evaluation_now": len(todo), "oldest_awaiting_evaluation_hours": round(max(oldest), 1) if oldest else None,
        "awaiting_alert_now": len(pending_alerts), "error_events_in_window": errors, "abandoned_in_window": abandoned,
        "failed_alert_attempts_in_window": sum(r.alerts_failed for r in in_window),
        "hydration_retry_queue": len(_json_dict(discovery.get("pending_jobs"))),
    }  # fmt: skip

    # ---- search usage
    budget = SearchBudget.load(discovery.get(BUDGET_KEY), now, cap=search_cap, reserve=search_reserve)
    search = {
        "credits_in_window_from_runs": sum(r.search_credits for r in in_window), "discovery_runs": sum(1 for r in in_window if r.discovery),
        "this_month": {"used": budget.used, "calls": budget.calls, "by_path": budget.by_path, "cap": budget.cap, "reserve": budget.reserve},
        "note": "local counter only: usage outside this application is not visible here (use --search-usage for Tavily's own counter)",
    }  # fmt: skip

    # ---- board coverage
    monitored = [b for b in boards.values() if b.status in MONITORED]
    last = in_window[-1] if in_window else (runs[-1] if runs else None)
    by_ats: dict[str, int] = {}
    for b in monitored:
        by_ats[b.ats] = by_ats.get(b.ats, 0) + 1
    coverage = {
        "registry_boards": len(boards), "monitored": len(monitored), "monitored_by_provider": dict(sorted(by_ats.items())),
        "last_run": None if last is None else {
            "at": last.run_at, "established": last.pool_established, "exploration": last.pool_exploration,
            "relevant_waiting": last.waiting_relevant, "relevant_board_coverage_pct": last.relevant_coverage_pct,
        },
    }  # fmt: skip

    # ---- the user's feedback (the column is theirs; this only reads it)
    labelled = {k: 0 for k in FEEDBACK}
    other = 0
    unlabelled = 0
    by_fresh: dict[str, dict[str, int]] = {}
    for row in tracker:
        label = (row.get("My_Feedback") or "").strip()
        fresh = row.get("Freshness") or "?"
        if not label:
            unlabelled += 1
            continue
        if label in labelled:
            labelled[label] += 1
            by_fresh.setdefault(fresh, {k: 0 for k in FEEDBACK})[label] += 1
        else:
            other += 1
    total_labelled = sum(labelled.values())
    feedback = {
        "tracker_rows": len(tracker), "labelled": labelled, "unlabelled": unlabelled, "other_text": other,
        "would_apply_share_of_labelled_pct": round(100 * labelled["Would apply"] / total_labelled) if total_labelled else None,
        "useful_share_of_labelled_pct": round(100 * (labelled["Would apply"] + labelled["Maybe"]) / total_labelled) if total_labelled else None,
        "by_freshness_label": by_fresh,
    }  # fmt: skip
    # ---- limits audit: measured per run (runs recorded before these columns existed carry no duration and are left out)
    timed = [r for r in in_window if r.duration_s > 0]
    per_board = [r.poll_s / r.boards_total for r in timed if r.boards_total > 0]
    first_state, last_state = (timed[0], timed[-1]) if timed else (None, None)
    span_days = max(1e-9, (_parse(last_state.run_at, now.tzinfo) - _parse(first_state.run_at, now.tzinfo)).total_seconds() / 86400) if timed and len(timed) > 1 else None
    limits = {
        "timed_runs": len(timed),
        "duration_s": _stats([float(r.duration_s) for r in timed]),
        "timeout_s": run_timeout_s,
        "longest_run_pct_of_timeout": round(100 * max(r.duration_s for r in timed) / run_timeout_s, 1) if timed else None,
        "phase_median_s": {k: _stats([float(getattr(r, f"{k}_s")) for r in timed]).get("median") for k in ("load", "discovery", "poll", "evaluate")} if timed else {},
        "poll_seconds_per_monitored_board": _stats(per_board),
        "projected_poll_s_at_max_active_boards": round(statistics.median(per_board) * max_active) if per_board else None,
        "projection_note": "straight-line extrapolation of the median poll time per monitored board; it ignores Sheet and quota effects and is not a measurement at that size",
        "sheets_reads_per_run": _stats([float(r.sheets_reads) for r in timed]),
        "sheets_writes_per_run": _stats([float(r.sheets_writes) for r in timed]),
        "sheets_quota_rejections_retried": sum(r.sheets_429 for r in timed),
        "sheets_reads_per_minute_of_run_max": round(max((r.sheets_reads / max(1.0, r.duration_s / 60) for r in timed), default=0), 1),
        "ats_requests_per_run": _stats([float(r.ats_requests) for r in timed]),
        "ats_429": sum(r.ats_429 for r in timed),
        "ats_request_seconds_per_run": _stats([float(r.ats_seconds) for r in timed]),
        "groq_calls": sum(r.groq_calls for r in timed), "groq_429": sum(r.groq_429 for r in timed),
        "events_rows": None if first_state is None else {"first": first_state.events_rows, "last": last_state.events_rows},
        "boards_rows": None if first_state is None else {"first": first_state.boards_rows, "last": last_state.boards_rows},
        "events_rows_per_day": round((last_state.events_rows - first_state.events_rows) / span_days) if span_days else None,
        "sheet_cell_budget_note": "Google Sheets allows 10,000,000 cells per spreadsheet; Events has 7 columns and Boards 32",
    }  # fmt: skip
    # ---- re-check flips: boards that gained their first relevant open job between two validations
    stats = _json_dict(discovery.get("revalidation_stats"))
    up_events = [e for e in stats.get("events", []) if isinstance(e, dict) and e.get("d") == "up"]
    rechecks = int(stats.get("rechecks") or 0)
    days_up = [float(d) for d in stats.get("days_up", []) if isinstance(d, (int, float))]
    days_down = [float(d) for d in stats.get("days_down", []) if isinstance(d, (int, float))]
    revalidation = {
        "since": stats.get("since"), "rechecks": rechecks, "gained": int(stats.get("up") or 0), "lost": int(stats.get("down") or 0),
        "gained_pct": round(100 * int(stats.get("up") or 0) / rechecks, 1) if rechecks else None,
        "days_unchecked_when_gained": _stats(days_up), "days_unchecked_when_lost": _stats(days_down),
        "recent_gains_now_monitored": sum(1 for e in up_events if (b := boards.get(e.get("k", ""))) and b.status in MONITORED),
        "recent_gains_waiting": sum(1 for e in up_events if (b := boards.get(e.get("k", ""))) and b.status == STATUS_VALIDATED),
        "recent_gains_listed": len(up_events),
    }  # fmt: skip
    return {
        "revalidation": revalidation,
        "limits": limits,
        "window": {"days": days, "from": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "to": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "fresh_window_hours": window_minutes / 60},
        "polling": polling, "relevant_fresh_jobs_by_source": by_source, "delivery": delivery, "failures": failures,
        "search": search, "coverage": coverage, "feedback": feedback,
    }  # fmt: skip


def _json_dict(raw: str | None) -> dict[str, Any]:
    import json

    try:
        data = json.loads(raw or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _revalidation_lines(r: dict[str, Any]) -> list[str]:
    if not r["rechecks"]:
        return ["  no re-checks of validated boards recorded yet (the first re-check of a board happens 7 days after its first validation)"]
    return [
        f"  since {r['since']}: {r['rechecks']} re-checks of boards that were already validated; {r['gained']} gained relevant open jobs ({r['gained_pct']}%), {r['lost']} lost them",
        f"  days since the previous check, boards that gained: {_fmt_stats(r['days_unchecked_when_gained'], 'd')} (the longest a first relevant job could have gone unseen; the weekly cycle caps it at about 7)",
        f"  of the {r['recent_gains_listed']} most recent gains: {r['recent_gains_now_monitored']} are monitored now, {r['recent_gains_waiting']} still wait for a slot",
        "  reading: a high gained share means a shorter interval would bring boards in sooner; a near-zero share means weekly is enough. A gain is only a missed FRESH job if the job was published within the window before the check.",
    ]


def _limits_lines(m: dict[str, Any]) -> list[str]:
    if not m["timed_runs"]:
        return ["  no timed runs yet (runs recorded before the diagnostics columns existed carry no durations)"]
    ph = m["phase_median_s"]
    lines = [
        f"  timed runs {m['timed_runs']}; run duration: {_fmt_stats(m['duration_s'], 's')}; longest = {m['longest_run_pct_of_timeout']}% of the {m['timeout_s']} s timeout",
        f"  median seconds by phase: load {ph.get('load')}, discovery {ph.get('discovery')}, poll {ph.get('poll')}, evaluate+alert {ph.get('evaluate')}",
        f"  poll seconds per monitored board: {_fmt_stats(m['poll_seconds_per_monitored_board'], 's')}"
        + (f" -> projected {m['projected_poll_s_at_max_active_boards']} s at the board cap" if m["projected_poll_s_at_max_active_boards"] is not None else ""),
        f"  ({m['projection_note']})",
        f"  Google Sheets requests per run: reads {_fmt_stats(m['sheets_reads_per_run'], '')}; writes {_fmt_stats(m['sheets_writes_per_run'], '')}; "
        f"highest average reads per minute inside a run {m['sheets_reads_per_minute_of_run_max']} (quota about 60 per minute per user); rejections retried {m['sheets_quota_rejections_retried']}",
        f"  ATS requests per run: {_fmt_stats(m['ats_requests_per_run'], '')}; request seconds per run: {_fmt_stats(m['ats_request_seconds_per_run'], 's')}; HTTP 429 from ATS providers: {m['ats_429']}",
        f"  Groq calls {m['groq_calls']} (HTTP 429: {m['groq_429']})",
    ]
    if m["events_rows"]:
        lines.append(
            f"  state size: Events rows {m['events_rows']['first']} -> {m['events_rows']['last']} (about {m['events_rows_per_day']} a day), "
            f"Boards rows {m['boards_rows']['first']} -> {m['boards_rows']['last']}; {m['sheet_cell_budget_note']}"
        )
    return lines


def _fmt_stats(s: dict[str, Any], unit: str = "min") -> str:
    return "none yet" if not s.get("n") else f"n={s['n']}, median {s['median']} {unit}, p90 {s['p90']}, max {s['max']}"


def format_report(rep: dict[str, Any]) -> str:
    w, p, d, f, s, c, fb = rep["window"], rep["polling"], rep["delivery"], rep["failures"], rep["search"], rep["coverage"], rep["feedback"]
    lines = [
        f"PILOT REPORT: {w['from']} -> {w['to']} ({w['days']} days; freshness window {w['fresh_window_hours']:g} h). Measured from the state; not a verdict.",
        "",
        "POLLING",
        f"  runs recorded {p['runs']} of {p['expected_hourly_runs']} hourly slots ({p['run_coverage_pct']}%); late runs (gap > {LATE_RUN_MIN} min): {p['late_runs_over_90_min']}",
        f"  runs by trigger: {p['runs_by_trigger'] or 'none'}  (only `schedule` shows that the schedule really fires)",
        f"  gap between runs: {_fmt_stats(p['gap_minutes'])}",
        f"  worst board gap per run: {_fmt_stats(p['worst_board_gap_minutes'])}; boards polled {p['boards_polled']}, failed polls {p['board_poll_failures']}",
        f"  run-start records that never finished: {p['unfinished_run_records']} (a run that never started leaves no record: the gap before the next run shows it)",
        "",
        "RELEVANT FRESH JOBS BY SOURCE (title gate passed, source timestamp inside the window)",
    ]
    if rep["relevant_fresh_jobs_by_source"]:
        for src, r in rep["relevant_fresh_jobs_by_source"].items():
            lines.append(f"  {src:7s} new {r['new']} (+{r['baseline_pass']} on a first/re-baseline pass, +{r['reentry_pass']} on re-entry); evaluated {r['evaluated']}, would alert {r['to_apply']}, alerted {r['alerted']}")
    else:
        lines.append("  none yet")
    lines += [
        "",
        "LATENCY",
        f"  publication -> first seen, by source: " + ("; ".join(f"{k}: {_fmt_stats(v)}" for k, v in d["discovery_latency_minutes_by_source"].items()) or "none yet"),
        f"  publication -> alert delivered: {_fmt_stats(d['publication_to_alert_minutes'])}",
        f"  first seen -> alert delivered: {_fmt_stats(d['first_seen_to_alert_minutes'])}",
        "",
        "DELIVERY",
        f"  alerts sent {d['alerts_sent']}; labelled late {d['late_alerts']}; later than the window {d['alerts_later_than_the_window']}; duplicate alerts {d['duplicate_alerts']}",
        "",
        "PENDING FAILURES",
        f"  awaiting evaluation now {f['awaiting_evaluation_now']} (oldest {f['oldest_awaiting_evaluation_hours']} h); awaiting alert now {f['awaiting_alert_now']}; hydration retry queue {f['hydration_retry_queue']}",
        f"  in window: errors {f['error_events_in_window'] or 'none'}; abandoned {f['abandoned_in_window']}; failed alert attempts {f['failed_alert_attempts_in_window']}",
        "",
        "SEARCH USAGE",
        f"  {s['discovery_runs']} discovery runs, {s['credits_in_window_from_runs']} credits in the window; this month {s['this_month']['used']} of {s['this_month']['cap']} "
        f"({s['this_month']['reserve']} reserved) by path {s['this_month']['by_path'] or 'none'}",
        f"  {s['note']}",
        "",
        "BOARD COVERAGE",
        f"  registry {c['registry_boards']} boards, monitored {c['monitored']} {c['monitored_by_provider']}",
    ]
    if c["last_run"]:
        lr = c["last_run"]
        lines.append(f"  last run {lr['at']}: established {lr['established']}, exploration {lr['exploration']}, relevant boards waiting {lr['relevant_waiting']}, relevant-board coverage {lr['relevant_board_coverage_pct']}%")
    lines += [
        "",
        "RE-CHECK FLIPS (does a 7-day re-check interval miss boards?)",
    ] + _revalidation_lines(rep["revalidation"]) + [
        "",
        "LIMITS AUDIT (measured per run; not a verdict)",
    ] + _limits_lines(rep["limits"]) + [
        "",
        "YOUR FEEDBACK (column My_Feedback in Job Tracker; read only)",
        f"  rows {fb['tracker_rows']}: Would apply {fb['labelled']['Would apply']}, Maybe {fb['labelled']['Maybe']}, Irrelevant {fb['labelled']['Irrelevant']}; unlabelled {fb['unlabelled']}, other text {fb['other_text']}",
        "  " + (
            f"of the labelled ones {fb['would_apply_share_of_labelled_pct']}% were 'Would apply' and {fb['useful_share_of_labelled_pct']}% 'Would apply' or 'Maybe'"
            if fb["useful_share_of_labelled_pct"] is not None else "no labelled rows yet"
        ),
    ]
    for label, counts in fb["by_freshness_label"].items():
        lines.append(f"    {label}: {counts}")
    return "\n".join(lines)
