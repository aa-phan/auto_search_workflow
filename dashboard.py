"""The Dashboard tab: renders a `reporting` summary into a compact grid and publishes it with ONE batched write.

The tab is generated output. Nothing on it is read back by polling, admission, scoring or alerts, so editing it
cannot change what the system does; the next refresh simply rewrites it (idempotent for the same source data).
Failures here are contained by `refresh`: they are logged and returned, never raised into job processing.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from typing import Any

import reporting as rp

log = logging.getLogger("hunter")

DASHBOARD_TAB = "Dashboard"
COLUMNS = 10
WIDTHS = [250, 105, 105, 105, 130, 130, 130, 130, 130, 130]  # pixels, columns A..J
UNKNOWN = "n/a"  # unknown / not recorded: never shown as 0

PALETTE = {  # RGB 0-1
    "ink": (0.13, 0.13, 0.15), "muted": (0.42, 0.44, 0.48), "line": (0.85, 0.86, 0.88), "band": (0.95, 0.96, 0.98),
    "green": (0.80, 0.92, 0.82), "yellow": (1.0, 0.94, 0.70), "red": (0.98, 0.80, 0.80), "grey": (0.90, 0.90, 0.90), "head": (0.88, 0.92, 0.99),
}


@dataclass
class Cell:
    value: Any = ""
    style: str = ""


@dataclass
class Grid:
    rows: list[list[Cell]] = field(default_factory=list)
    merges: list[tuple[int, int, int]] = field(default_factory=list)  # (row index, first col, last col inclusive)
    heights: dict[int, int] = field(default_factory=dict)

    def add(self, cells: list[Cell | Any], height: int | None = None) -> int:
        row = [c if isinstance(c, Cell) else Cell(c) for c in cells]
        row += [Cell()] * (COLUMNS - len(row))
        self.rows.append(row)
        if height:
            self.heights[len(self.rows) - 1] = height
        return len(self.rows) - 1

    def values(self) -> list[list[Any]]:
        return [[c.value for c in row] for row in self.rows]


def fmt(v: Any, suffix: str = "") -> Any:
    if v is None:
        return UNKNOWN
    if isinstance(v, float):
        v = int(v) if v == int(v) else round(v, 1)
    return f"{v}{suffix}" if suffix else v


def _short(stamp: str | None) -> str:
    return UNKNOWN if not stamp else stamp.replace("T", " ").replace("Z", "")


def _stats_cell(s: dict[str, Any]) -> str:
    if not s or not s.get("n"):
        return UNKNOWN
    return f"{s['median']:g} (n={s['n']})"


def render(sm: dict[str, Any]) -> Grid:
    g = Grid()
    P, H, R, D, C, F, FB = sm["periods"], sm["health"], None, sm["discovery"], sm["coverage"], sm["failures"], sm["feedback"]
    head = sm["headline"]
    sf = sm["source_freshness"]

    def section(title: str, sub: str = "") -> None:
        g.add([""])
        i = g.add([Cell(title, "h2"), *([Cell(sub, "note")] if sub else [])])
        if sub:
            g.merges.append((i, 1, COLUMNS - 1))

    def thead(labels: list[str]) -> None:
        g.add([Cell(x, "thead") for x in labels])

    def metric(label: str, vals: list[Any], note: str = "", style: str = "") -> None:
        g.add([Cell(label, "label"), *[Cell(fmt(v), style or "num") for v in vals], Cell(note, "note")])

    def periods3(path: list[str]) -> list[Any]:
        out = []
        for k in ("today", "7d", "30d"):
            v: Any = P[k]
            for part in path:
                v = v[part]
            out.append(v)
        return out

    # ---- title, provenance of the numbers, plain-English summary
    i = g.add([Cell("Job Hunter · Operations dashboard", "title")], 34)
    g.merges.append((i, 0, COLUMNS - 1))
    i = g.add([Cell(
        f"Generated {_short(sm['generated_at'])} UTC · latest run record {_short(sf['latest_run_record'])} · latest ledger event {_short(sf['latest_ledger_event'])} · "
        f"days are calendar days in {sm['timezone']} · default view: last 7 days · maintenance view, separate from the Job Tracker; nothing on this tab affects polling, scoring or alerts",
        "note")], 30)
    g.merges.append((i, 0, COLUMNS - 1))
    color = {"green": "ok", "yellow": "warn", "red": "bad", "grey": "idle"}[head["color"]]
    i = g.add([Cell(head["status"], f"chip_{color}"), Cell(head["lines"][0].split(": ", 1)[-1] if head["status"] != "No data yet" else head["lines"][0], "wrap")], 44)
    g.merges.append((i, 1, COLUMNS - 1))
    for line in head["lines"][1:]:
        i = g.add([Cell(""), Cell(line, "wrap")], 30)
        g.merges.append((i, 1, COLUMNS - 1))

    # ---- status cards (last 7 days unless stated)
    last = H["last_run"]
    r7 = P["7d"]["results"]
    pend = F["pending_evaluation"]["jobs"] + F["pending_alert"]["jobs"] + F["pending_hydration"]["jobs"]
    led = D["ledger"]
    cards = [
        ("Last run", (last or {}).get("outcome", UNKNOWN), f"started {_short((last or {}).get('started_at'))}"),
        ("Verified-fresh matches", r7["verified_fresh_matches"], f"of {r7['matches_kept']} kept · 7 days"),
        ("Alerts delivered", r7["alerts_delivered"], f"{r7['alerts_unique_jobs']} unique jobs · 7 days"),
        ("Waiting to be processed", pend, f"{F['pending_evaluation']['jobs']} eval · {F['pending_alert']['jobs']} alert · {F['pending_hydration']['jobs']} hydrate"),
        ("Search credits left", fmt(led["remaining_scheduled"]) if led else UNKNOWN, "scheduled allowance this month" if led else "ledger not recorded yet"),
    ]
    g.add([""])
    for row_kind, idx in (("card_label", 0), ("card_value", 1), ("card_note", 2)):
        cells: list[Cell] = []
        for c in cards:
            cells += [Cell(c[idx] if row_kind != "card_value" else fmt(c[idx]), row_kind), Cell("", row_kind)]
        j = g.add(cells, 30 if row_kind == "card_value" else None)
        for k in range(5):
            g.merges.append((j, 2 * k, 2 * k + 1))

    # ---- health
    section("HEALTH", "Runs are counted from the Runs record; a run's start is saved first, so an interrupted run shows up here.")
    thead(["", "Today", "7 days", "30 days", "Note"])
    pol = H["polling"]
    metric("Runs finished", [pol[k].get("runs_finished") for k in ("today", "7d", "30d")], "one record per run (start record merged with its finished record)")
    metric("Hourly slots expected", [pol[k].get("expected_hourly_slots") for k in ("today", "7d", "30d")], "whole hours since the period start or the first recorded run (never before it); a slightly low figure, so a miss is never invented")
    metric("Run coverage of expected slots", [None if pol[k].get("coverage_pct") is None else f"{pol[k]['coverage_pct']}%" for k in ("today", "7d", "30d")], "runs / expected; late-starting schedules can miss slots")
    metric(f"Polling gaps > {rp.LATE_RUN_MIN} min", [pol[k].get("gaps_over_threshold") for k in ("today", "7d", "30d")], "gap between two finished runs; an interrupted run does not close a gap")
    metric("Longest gap (min)", [pol[k].get("max_gap_min") for k in ("today", "7d", "30d")], "n/a = fewer than two finished runs in the period")
    metric("Runs ok / degraded / failed", [f"{pol[k]['ok']}/{pol[k]['degraded']}/{pol[k]['failed']}" if pol[k].get("runs_finished") is not None else None for k in ("today", "7d", "30d")], "degraded = discovery or persistence problem, failed alert, scoring outage or >=10% boards failing")
    metric("Interrupted runs", [pol[k].get("interrupted") for k in ("today", "7d", "30d")], "started, never finished (after the workflow timeout)")
    g.add([Cell("Last run", "label"), Cell(f"id {(last or {}).get('run_id') or UNKNOWN} · started {_short((last or {}).get('started_at'))} · finished {_short((last or {}).get('finished_at'))} · outcome {(last or {}).get('outcome', UNKNOWN)}"
                                           f" · duration {fmt((last or {}).get('duration_s'), ' s')} · kind {(last or {}).get('kind', UNKNOWN)}", "note")])
    g.add([Cell("Last finished / last ok run", "label"), Cell(f"{_short(H['last_finished_run_at'])} / {_short(H['last_ok_run_at'])}", "note")])
    if H["providers"]:
        thead(["Provider (monitored boards)", "Boards", "Failing last poll", "429 backoffs", "Status", "Last error"])
        for p in H["providers"]:
            g.add([Cell(p["provider"], "label"), Cell(p["monitored"], "num"), Cell(p["failing_last_poll"], "num"), Cell(p["backoff_in_last_24_runs"], "num"),
                   Cell("degraded" if p["degraded"] else "ok", "chip_warn" if p["degraded"] else "chip_ok"), Cell(p["last_error"], "note")])

    # ---- results
    section("RESULTS", "Unique jobs (ledger keys), counted once per job. Retries and resends are shown separately under Failures. 'First observed' = the day the system first saw the job.")
    thead(["", "Today", "7 days", "30 days", "Note"])
    metric("Unique jobs first observed", periods3(["results", "unique_jobs_observed"]), "all jobs the system saw for the first time")
    metric("  of which existing postings (baseline)", periods3(["results", "existing_postings_baselined"]), "already on a board when it was first read; never scored")
    metric("  of which new postings", periods3(["results", "new_postings"]), "appeared after the board was baselined")
    metric("Reached scoring (eligible)", periods3(["results", "eligible_matches_scored"]), "passed title, age and hard eligibility rules; same cohort")
    metric("Matches kept for the tracker", periods3(["results", "matches_kept"]), "scored at or above the tracker threshold")
    metric("  verified fresh", periods3(["results", "verified_fresh_matches"]), "source publication time inside the freshness window")
    metric("  publication date unknown", periods3(["results", "matches_date_unknown"]), "cannot be verified: never counted as fresh")
    metric("  dated, older than the window", periods3(["results", "matches_dated_not_fresh"]), "")
    metric("Tracker additions (event count)", periods3(["results", "tracker_additions"]), "evaluations kept for the tracker, counted on the day they were evaluated")
    metric("Alerts delivered (event count)", periods3(["results", "alerts_delivered"]), "Telegram accepted the message, counted on the day of delivery")
    metric("  unique jobs alerted", periods3(["results", "alerts_unique_jobs"]), "")
    metric("  repeat deliveries of an alerted job", periods3(["results", "alerts_repeat_deliveries"]), "at-least-once delivery can resend")
    metric("  delivered late (after the window)", periods3(["results", "alerts_late"]), "")
    metric("Alert events not delivered", periods3(["results", "alert_events_not_delivered"]), "no channel configured at the time")
    new_src = P["7d"]["results"]["new_by_source"]
    new_ats = P["7d"]["results"]["new_by_ats"]
    g.add([Cell("New postings by discovery source (7 days)", "label"), Cell("  ·  ".join(f"{k} {v}" for k, v in new_src.items()) or "none", "note")])
    g.add([Cell("New postings by ATS provider (7 days)", "label"), Cell("  ·  ".join(f"{k} {v}" for k, v in new_ats.items()) or "none", "note")])
    section("FRESHNESS AND LATENCY", "Percentages always show their denominator; jobs without a publication date are counted separately, never as fresh or stale.")
    thead(["", "Today", "7 days", "30 days", "Note"])
    metric("New postings that passed the cheap gates", periods3(["freshness", "cohort_jobs"]), "denominator for the lines below")
    metric("  verified fresh", periods3(["freshness", "verified_fresh"]), "")
    metric("  with a publication date", periods3(["freshness", "dated"]), "")
    metric("  publication date unknown", periods3(["freshness", "date_unknown"]), "")
    metric("Verified fresh, share of dated", [None if v is None else f"{v}%" for v in periods3(["freshness", "verified_fresh_share_of_dated_pct"])], "unknown-date jobs are NOT in this denominator")
    metric("Publication -> detection, median min", [_stats_cell(x) for x in periods3(["latency_min", "publication_to_detection"])], "verified-fresh jobs with a time-precise source date, ordinary polls only")
    metric("Detection -> delivery, median min", [_stats_cell(x) for x in periods3(["latency_min", "detection_to_delivery"])], "first detection to first Telegram delivery, by delivery day")

    # ---- rejections
    section("REJECTIONS", "Where each job first observed in the period ended up. One cohort, each job exactly once, so the rows add up to the first line.")
    thead(["", "Today", "7 days", "30 days", "% of 7 days", "Note"])
    n7 = P["7d"]["results"]["unique_jobs_observed"]

    def outcome_row(label: str, key: str, note: str = "") -> None:
        vals = [P[k]["outcomes"][key] for k in ("today", "7d", "30d")]
        pct = f"{round(100 * vals[1] / n7)}%" if n7 else UNKNOWN
        g.add([Cell(label, "label"), *[Cell(v, "num") for v in vals], Cell(pct, "num"), Cell(note, "note")])

    g.add([Cell("Jobs first observed", "label"), *[Cell(P[k]["results"]["unique_jobs_observed"], "num_b") for k in ("today", "7d", "30d")], Cell("100%" if n7 else UNKNOWN, "num_b")])
    outcome_row("Baseline (existing posting, not evaluated)", "baseline", "not a rejection")
    for key in rp.REJECT_ORDER:
        outcome_row(rp.REJECT_LABELS[key], key, "")
    outcome_row("Kept (scored, in the tracker range)", "kept")
    outcome_row("Waiting for evaluation", "pending", "unknown until evaluated: not counted as kept or rejected")
    outcome_row("Evaluation abandoned after repeated failures", "abandoned")
    metric("Unknown publication date (overlay)", periods3(["freshness", "new_postings_date_unknown"]), "new postings with no source date: kept, but never alerted; overlaps the rows above")
    legacy = P["7d"]["legacy_reason_codes"]
    if legacy:
        g.add([Cell(f"{legacy} evaluation(s) in the last 7 days predate reason codes; their reason was derived from the recorded verdict text.", "note")])

    # ---- discovery
    section("DISCOVERY (Tavily)", "Search is candidate retrieval; credits are those recorded from each response. Not the whole market.")
    thead(["", "Today", "7 days", "30 days", "Note"])
    metric("Credits spent", [D["periods"][k]["credits_spent"] for k in ("today", "7d", "30d")], "sum of per-run credits recorded")
    metric("Discovery runs", [D["periods"][k]["discovery_runs"] for k in ("today", "7d", "30d")], "")
    metric("Failed requests, billing unknown", [D["periods"][k]["failed_requests_billing_unknown"] for k in ("today", "7d", "30d")], "unresolved charges: the provider may or may not have billed them")
    metric("Runs with unresolved credit status", [D["periods"][k]["runs_credit_unresolved"] for k in ("today", "7d", "30d")], "")
    metric("Unique eligible boards found by search", [D["unique_eligible_boards_found_by_search"][k] for k in ("today", "7d", "30d")], "boards first named by search in the period, validated or monitored now")
    metric("Verified-fresh job matches from search", [D["unique_verified_fresh_search_matches"][k] for k in ("today", "7d", "30d")], "unique jobs, first seen through search")
    if led:
        g.add([Cell(f"Month {D['month']}", "label"), Cell(
            f"used {led['used_locally']} of {led['cap']} locally · scheduled runs may use {led['cap'] - led['reserve']} · remaining: scheduled {led['remaining_scheduled']}, manual {led['remaining_manual']} · "
            f"by path {led['by_path'] or 'none'}" + (" · LIMIT HIT" if led["limit_hit"] else ""), "note")])
        g.add([Cell("Tavily's own counter", "label"), Cell(
            f"{fmt(D['account_counter_last_read'])} last read" + (f" ({D['account_minus_local']:+d} versus the local ledger: usage this application cannot see, or the counter lags)" if D["account_minus_local"] is not None else ""), "note")])
        if not led["month_matches_now"]:
            g.add([Cell("The stored ledger is from an earlier month; this month's spending has not been recorded yet.", "note")])
    else:
        g.add([Cell("Credit ledger", "label"), Cell("not recorded yet: remaining budget unknown", "note")])
    rot = D["rotation"]
    g.add([Cell("Rotation progress", "label"), Cell(
        UNKNOWN if rot is None else f"next slot {rot['cursor']} of {fmt(rot['total_slots'])} · {rot['full_passes']} full passes · {rot['runs']} runs · last {_short(rot['last_run_at'])}", "note")])
    g.add([Cell("Hydration retry queue", "label"), Cell(f"{D['hydration_retry_queue']} search-found job(s) waiting for an ATS read", "note")])

    # ---- coverage
    section("BOARD COVERAGE", C["label"])
    g.add([Cell("Monitored boards", "label"), Cell(
        f"established {C['established']} of {C['established_target']} · exploration {C['exploration']} of {C['exploration_target']} · total {C['monitored']}"
        + (f" · {C['unpooled_monitored']} without a pool label" if C["unpooled_monitored"] else ""), "note")])
    g.add([Cell("Registry", "label"), Cell(f"{C['registry_boards']} boards · " + " · ".join(f"{k} {v}" for k, v in C["by_status"].items()), "note")])
    g.add([Cell("Eligible boards waiting for a slot", "label"), Cell(
        f"{C['eligible_waiting_boards']} validated boards with an open eligible job · last run recorded {fmt(C['last_run_waiting_relevant'])} (oldest waiting {fmt(C['oldest_waiting_hours'], ' h')})", "note")])
    v = C["validation"]
    g.add([Cell("Validation overdue", "label"), Cell(
        f"{v['revalidation_overdue_valid']} validated boards past the 7-day re-check · {v['revalidation_overdue_invalid']} invalid past 30 days · {v['never_validated']} never validated"
        f" (oldest {fmt(v['oldest_candidate_days'], ' d')}) · oldest re-check overdue {fmt(v['oldest_overdue_days'], ' d')}", "note")])
    t = C["trials"]
    g.add([Cell("Exploration trials", "label"), Cell(f"{t['running']} running · {t['ending_within_48h']} end within 48 h · {t['ended_awaiting_rebalance']} ended, waiting for the next weekly rebalance", "note")])
    g.add([Cell("Relevant-board coverage", "label"), Cell(f"{fmt(C['relevant_board_coverage_pct'], '%')} of the known boards with open relevant jobs are monitored (as of run {_short(C['as_of_run'])})", "note")])

    # ---- failures
    section("FAILURES AND RETRIES", "Jobs are counted once; attempts are counted separately.")
    g.add([Cell("Pending now", "label"), Cell(
        f"evaluation: {F['pending_evaluation']['jobs']} jobs (oldest {fmt(F['pending_evaluation']['oldest_hours'], ' h')}) · alerts: {F['pending_alert']['jobs']} jobs (oldest {fmt(F['pending_alert']['oldest_hours'], ' h')}) · "
        f"hydration: {F['pending_hydration']['jobs']} (oldest {fmt(F['pending_hydration']['oldest_hours'], ' h')})", "note")])
    att = P["7d"]["attempts"]
    g.add([Cell("Attempts, last 7 days", "label"), Cell(
        f"evaluation attempts {att['evaluation']} (temporary failures {att['evaluation_transient']}, recorded failures {att['evaluation_failed']}) vs {P['7d']['outcomes']['kept'] + P['7d']['outcomes']['score']} unique jobs scored"
        + " · attempts include retries; unique jobs do not", "note")])
    g.add([Cell("Errors recorded against jobs", "label"), Cell(f"{F['error_attempts_total']} attempts across {F['unique_jobs_with_errors']} unique jobs ever · {F['abandoned_jobs']} abandoned", "note")])
    if F["table"]:
        i = g.add([Cell("What · reference", "thead"), Cell("Count", "thead"), Cell("Since", "thead"), Cell("Last", "thead"), Cell("Detail", "thead"), Cell("", "thead"), Cell("", "thead"), Cell("What to do", "thead"), Cell("", "thead"), Cell("", "thead")])
        g.merges += [(i, 4, 6), (i, 7, 9)]
        for row in F["table"]:
            sev = {0: "chip_bad", 1: "chip_warn", 2: "chip_warn"}[row["severity"]]
            i = g.add([Cell(f"{row['what']} · {row['ref']}", sev), Cell(row["count"], "num"), Cell(_short(row["since"]), "note"), Cell(_short(row["last"]), "note"),
                       Cell(row["detail"], "wrap"), Cell(""), Cell(""), Cell(row["action"], "wrap")], 44)
            g.merges += [(i, 4, 6), (i, 7, 9)]
        if F["table_total"] > len(F["table"]):
            g.add([Cell(f"{F['table_total'] - len(F['table'])} more item(s) not shown.", "note")])
    else:
        g.add([Cell("Nothing needs action.", "label")])

    # ---- feedback
    section("YOUR FEEDBACK", FB["scope"] + ". Read from your Job Tracker columns; this tab never writes them.")
    g.add([Cell("Rows read", "label"), Cell(f"{FB['tracker_rows']} (test fixtures excluded)", "note")])
    g.add([Cell("My_Feedback", "label"), Cell(
        f"Would apply {FB['feedback']['Would apply']} · Maybe {FB['feedback']['Maybe']} · Irrelevant {FB['feedback']['Irrelevant']} · unlabelled {FB['unlabelled']}"
        + (f" · other text {FB['other_text']}" if FB["other_text"] else ""), "note")])
    g.add([Cell("Share of labelled rows", "label"), Cell(
        f"Would apply {fmt(FB['would_apply_pct_of_labelled'], '%')} · Would apply or Maybe {fmt(FB['would_apply_or_maybe_pct_of_labelled'], '%')} (of {FB['labelled_total']} labelled)" if FB["labelled_total"] else "no labelled rows yet", "note")])
    g.add([Cell("My_Status", "label"), Cell(" · ".join(f"{k} {v}" for k, v in FB["status"].items()) + f" · blank {FB['status_blank']}" + (f" · other {FB['status_other']}" if FB["status_other"] else ""), "note")])

    # ---- daily trend
    section("DAILY TREND", "Newest first. n/a = nothing was recorded that day (before the system started or the field existed); a 0 is a measured zero.")
    thead(["Date", "Runs done", "Runs not ok", "Max gap min", "New postings", "Baselined", "Reached scoring", "Verified fresh", "Tracker +", "Alerts"])
    for k, d in enumerate(sm["trend"]):
        if k == 7:
            g.add([Cell("Days 8 to 30", "note")])
        style = "num" if k < 7 else "num_dim"
        g.add([Cell(d["date"], "label" if k < 7 else "label_dim"), *[Cell(fmt(d[x]), style) for x in ("runs_finished", "runs_not_ok", "max_gap_min", "new_postings", "baselined", "eligible", "verified_fresh_matches", "tracker_additions", "alerts_delivered")]])

    # ---- definitions and checks
    section("HOW TO READ THIS")
    notes = [
        "Source: the Runs record, Boards registry, Events ledger, Discovery state and your Job Tracker, read at generation time. Operational state is authoritative.",
        "Freshness: a job is verified fresh only when the ATS's own publication time is inside the window. Search dates, update times and first observation are never publication.",
        "Two job counts are never combined into a funnel: first-observed jobs (cohort by first-seen day) and events (alerts, tracker additions, by event day) are labelled where they appear.",
        "Excluded: rehearsal runs and the events they wrote, test fixtures in the tracker. Rows written before a field existed show n/a, they are not back-filled.",
        "A stopped workflow cannot report its own absence: this tab shows a gap only after the next run. An independent watchdog and a daily Telegram digest are planned, not built.",
        f"Excluded this time: {sm['exclusions']['rehearsal_runs']} rehearsal run(s), {sm['exclusions']['events_from_rehearsal_runs']} event(s), {sm['exclusions']['tracker_fixture_rows']} fixture row(s); {sm['exclusions']['duplicate_run_records_merged']} duplicate run record(s) merged.",
    ]
    for n in notes:
        i = g.add([Cell(n, "wrap")], 30)
        g.merges.append((i, 0, COLUMNS - 1))
    if sm["checks"]:
        for c in sm["checks"]:
            i = g.add([Cell("Consistency check failed: " + c, "chip_bad")])
            g.merges.append((i, 0, COLUMNS - 1))
    else:
        g.add([Cell("Consistency checks: all passed (outcomes add up to the cohort, alert deliveries to unique + repeats, periods nested).", "note")])
    return g


# --------------------------------------------------------------------------- Sheet publishing


def _rgb(name: str) -> dict[str, float]:
    r, g_, b = PALETTE[name]
    return {"red": r, "green": g_, "blue": b}


def _format(style: str) -> dict[str, Any]:
    base: dict[str, Any] = {"textFormat": {"fontSize": 10, "foregroundColor": _rgb("ink")}, "verticalAlignment": "MIDDLE"}
    tf = base["textFormat"]
    if style == "title":
        tf.update(bold=True, fontSize=16)
    elif style == "h2":
        tf.update(bold=True, fontSize=11)
        base["borders"] = {"bottom": {"style": "SOLID", "color": _rgb("line")}}
    elif style == "thead":
        tf.update(bold=True, fontSize=9, foregroundColor=_rgb("muted"))
        base["backgroundColor"] = _rgb("band")
    elif style in ("note", "label_dim", "num_dim"):
        tf.update(fontSize=9, foregroundColor=_rgb("muted"))
        base["wrapStrategy"] = "OVERFLOW_CELL"
    elif style == "wrap":
        base["wrapStrategy"] = "WRAP"
        base["verticalAlignment"] = "TOP"
    elif style in ("num", "num_b", "num_dim"):
        base["horizontalAlignment"] = "RIGHT"
        if style == "num_b":
            tf["bold"] = True
    elif style.startswith("chip_"):
        tf.update(bold=True)
        base["backgroundColor"] = _rgb({"chip_ok": "green", "chip_warn": "yellow", "chip_bad": "red", "chip_idle": "grey"}[style])
        base["wrapStrategy"] = "WRAP"
    elif style.startswith("card_"):
        base["backgroundColor"] = _rgb("band")
        base["horizontalAlignment"] = "LEFT"
        if style == "card_label":
            tf.update(fontSize=9, foregroundColor=_rgb("muted"))
        elif style == "card_value":
            tf.update(bold=True, fontSize=18)
        else:
            tf.update(fontSize=9, foregroundColor=_rgb("muted"))
    elif style == "label":
        pass
    if style == "num_dim":
        base["horizontalAlignment"] = "RIGHT"
    return base


def _cell_data(c: Cell) -> dict[str, Any]:
    out: dict[str, Any] = {"userEnteredFormat": _format(c.style)}
    v = c.value
    if isinstance(v, bool):
        out["userEnteredValue"] = {"stringValue": "yes" if v else "no"}
    elif isinstance(v, (int, float)):
        out["userEnteredValue"] = {"numberValue": v}
    elif v not in ("", None):
        out["userEnteredValue"] = {"stringValue": str(v)}  # always a literal string, never parsed as a formula
    return out


def requests_for(grid: Grid, sheet_id: int) -> list[dict[str, Any]]:
    """One batch: clear the tab, write every cell with its format, merge, size. Re-running with the same grid
    produces the same sheet."""
    n = len(grid.rows)
    whole = {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": max(n + 60, 400), "startColumnIndex": 0, "endColumnIndex": COLUMNS}
    reqs: list[dict[str, Any]] = [
        {"unmergeCells": {"range": whole}},
        {"repeatCell": {"range": whole, "cell": {}, "fields": "userEnteredValue,userEnteredFormat"}},
        {"updateSheetProperties": {"properties": {"sheetId": sheet_id, "gridProperties": {"hideGridlines": True}}, "fields": "gridProperties.hideGridlines"}},
        {"updateCells": {
            "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": 0},
            "rows": [{"values": [_cell_data(c) for c in row]} for row in grid.rows],
            "fields": "userEnteredValue,userEnteredFormat",
        }},
    ]  # fmt: skip
    for r, c0, c1 in grid.merges:
        reqs.append({"mergeCells": {"range": {"sheetId": sheet_id, "startRowIndex": r, "endRowIndex": r + 1, "startColumnIndex": c0, "endColumnIndex": c1 + 1}, "mergeType": "MERGE_ALL"}})
    for i, px in enumerate(WIDTHS):
        reqs.append({"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1}, "properties": {"pixelSize": px}, "fields": "pixelSize"}})
    for r, px in sorted(grid.heights.items()):
        reqs.append({"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": r, "endIndex": r + 1}, "properties": {"pixelSize": px}, "fields": "pixelSize"}})
    return reqs


def publish_sheet(spreadsheet: Any, grid: Grid) -> None:
    """Create the Dashboard tab if missing, then rewrite it in a single batchUpdate. Touches no other tab."""
    ws = next((w for w in spreadsheet.worksheets() if w.title == DASHBOARD_TAB), None)
    if ws is None:
        ws = spreadsheet.add_worksheet(title=DASHBOARD_TAB, rows=max(len(grid.rows) + 60, 400), cols=COLUMNS)
    spreadsheet.batch_update({"requests": requests_for(grid, ws.id)})


def publish_csv(directory: Path, grid: Grid) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "dashboard.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(grid.values())
    return path


# --------------------------------------------------------------------------- refresh (never raises)


def build(store: Any, settings: Any, *, now: datetime | None = None, tz: tzinfo | None = None, run_timeout_s: int = 25 * 60) -> dict[str, Any]:
    """Load the state with batch reads (one `get_all_values` per tab) and build the summary."""
    from datetime import timedelta

    state = store.state
    now = now or datetime.now(timezone.utc)
    policy = settings.pool_policy
    return rp.build_summary(
        now=now, tz=tz or getattr(store, "display_tz", timezone.utc), runs=state.load_runs(), events=state.load_events(), boards=state.load_boards(),
        discovery=state.load_discovery_state(), tracker=store.tracker_rows(), fresh_window=timedelta(hours=settings.fresh_window_hours),
        search_cap=settings.search_monthly_credits, search_reserve=settings.search_reserve_credits,
        established_target=policy.established_target, exploration_target=policy.exploration_target, run_timeout_s=run_timeout_s, min_alert_score=settings.min_score,
    )  # fmt: skip


def refresh(store: Any, settings: Any, *, now: datetime | None = None) -> bool:
    """Rebuild and publish the dashboard. Any failure is logged and reported as False: reporting must never undo job
    processing, interrupt delivery or cause a duplicate alert, so nothing here can propagate into the run."""
    try:
        grid = render(build(store, settings, now=now))
        store.publish_dashboard(grid)
        log.info("Dashboard refreshed (%d rows)", len(grid.rows))
        return True
    except Exception as exc:  # noqa: BLE001 - containment is the point
        log.error("Dashboard refresh failed (job processing is unaffected): %s", exc)
        return False
