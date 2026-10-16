"""The Dashboard tab: renders a `reporting` summary into a compact grid with native Sheets charts and sparklines,
and publishes it with ONE batched write (plus one metadata read to replace last time's charts).

The tab is generated output. Nothing on it is read back by polling, admission, scoring or alerts, so editing it
cannot change what the system does; the next refresh simply rewrites it (idempotent for the same source data).
Charts and sparklines are Google Sheets built-ins reading a small generated data block to the right of the page
(columns L onward), so no external service, library or website is involved.
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
COLUMNS = 10  # the visible page, columns A..J
DATA_COL = 11  # chart data block starts at column L
TOTAL_COLUMNS = 21  # A..U
WIDTHS = [230, 100, 100, 100, 100, 100, 100, 100, 100, 100] + [26] + [74] * 10  # pixels
UNKNOWN = "n/a"  # unknown / not recorded: never shown as 0
CHART_DAYS = 14
CHART_ID_BASE = 7100  # fixed chart ids, so a refresh deletes exactly its own charts and re-adds them

PALETTE = {  # RGB 0-1
    "ink": (0.13, 0.13, 0.15), "muted": (0.45, 0.47, 0.51), "line": (0.86, 0.87, 0.89), "band": (0.95, 0.96, 0.98),
    "green": (0.80, 0.92, 0.82), "yellow": (1.0, 0.94, 0.70), "red": (0.98, 0.80, 0.80), "grey": (0.90, 0.90, 0.90),
    "blue": (0.26, 0.52, 0.96), "teal": (0.10, 0.64, 0.60), "amber": (0.96, 0.69, 0.10), "crimson": (0.86, 0.27, 0.22), "slate": (0.55, 0.60, 0.68),
    "deep": (0.11, 0.23, 0.45),
}


@dataclass
class Cell:
    value: Any = ""
    style: str = ""
    formula: str = ""  # a Sheets formula (sparklines only); `value` is what the text/CSV version shows


@dataclass
class Chart:
    kind: str  # line | column | stacked_column | bar | donut
    title: str
    domain: tuple[int, int, int]  # (column, first row, last row exclusive) of the labels
    series: list[tuple[int, str]]  # (column, colour name) per series; the header row (first row - 1) names the series
    anchor_row: int
    anchor_col: int
    width: int
    height: int = 250


@dataclass
class Grid:
    rows: list[list[Cell]] = field(default_factory=list)
    merges: list[tuple[int, int, int]] = field(default_factory=list)  # (row index, first col, last col inclusive)
    heights: dict[int, int] = field(default_factory=dict)
    charts: list[Chart] = field(default_factory=list)

    def add(self, cells: list[Cell | Any], height: int | None = None) -> int:
        row = [c if isinstance(c, Cell) else Cell(c) for c in cells]
        row += [Cell()] * (COLUMNS - len(row))
        self.rows.append(row)
        if height:
            self.heights[len(self.rows) - 1] = height
        return len(self.rows) - 1

    def put(self, row: int, col: int, cell: Cell) -> None:
        """Set one cell anywhere (used for the chart data block); rows are extended as needed."""
        while len(self.rows) <= row:
            self.rows.append([Cell()] * COLUMNS)
        r = self.rows[row]
        r += [Cell()] * (col + 1 - len(r))
        r[col] = cell

    def values(self) -> list[list[Any]]:
        return [[c.value for c in row[:COLUMNS]] for row in self.rows]


def col_letter(i: int) -> str:
    out = ""
    i += 1
    while i:
        i, rem = divmod(i - 1, 26)
        out = chr(65 + rem) + out
    return out


def fmt(v: Any, suffix: str = "") -> Any:
    if v is None:
        return UNKNOWN
    if isinstance(v, float):
        v = int(v) if v == int(v) else round(v, 1)
    return f"{v}{suffix}" if suffix else v


def _short(stamp: str | None) -> str:
    return UNKNOWN if not stamp else stamp.replace("T", " ").replace("Z", "")


def _clock(stamp: str | None) -> str:
    """MM-DD HH:MM from a stamp: compact enough for a status line."""
    return UNKNOWN if not stamp else stamp[5:16].replace("T", " ")


def _med(s: dict[str, Any]) -> str:
    return UNKNOWN if not s or not s.get("n") else f"{s['median']:g} min (n={s['n']})"


def _share(num: int, den: int) -> str:
    return f"{num} of {den} ({round(100 * num / den)}%)" if den else UNKNOWN


def render(sm: dict[str, Any]) -> Grid:
    g = Grid()
    P, H, D, C, F, FB = sm["periods"], sm["health"], sm["discovery"], sm["coverage"], sm["failures"], sm["feedback"]
    head, sf = sm["headline"], sm["source_freshness"]
    last = H["last_run"]
    r7, f7 = P["7d"]["results"], P["7d"]["freshness"]
    led = D["ledger"]
    trend = list(reversed(sm["trend"][:CHART_DAYS]))  # oldest first for charts

    def section(title: str, sub: str = "") -> None:
        g.add([""])
        i = g.add([Cell(title, "h2"), *([Cell(sub, "note")] if sub else [])])
        if sub:
            g.merges.append((i, 1, COLUMNS - 1))

    def thead(labels: list[str]) -> None:
        g.add([Cell(x, "thead") for x in labels])

    def metric(label: str, vals: list[Any], note: str = "") -> None:
        g.add([Cell(label, "label"), *[Cell(fmt(v), "num") for v in vals], Cell(note, "note")])

    def three(path: list[str]) -> list[Any]:
        out = []
        for key in ("today", "7d", "30d"):
            v: Any = P[key]
            for part in path:
                v = v[part]
            out.append(v)
        return out

    def line(label: str, text: str) -> None:
        i = g.add([Cell(label, "label"), Cell(text, "note")])
        g.merges.append((i, 1, COLUMNS - 1))

    # ---- chart data block (columns L..U): chronological, blank = unknown (charts skip it, they do not plot a zero).
    # Cells are collected here and written after the page is laid out, so they never shift the visible rows.
    deferred: list[tuple[int, int, Cell]] = []

    def put(r: int, c: int, cell: Cell) -> None:
        deferred.append((r, c, cell))

    r0 = 2
    hdr = ["Date", "New postings", "Reached scoring", "Verified-fresh matches", "Alerts delivered", "Tracker additions", "Runs ok", "Runs with a problem", "Search credits"]
    keys = [None, "new_postings", "eligible", "verified_fresh_matches", "alerts_delivered", "tracker_additions", "runs_ok", "runs_not_ok", "search_credits"]
    put(r0 - 1, DATA_COL, Cell("Chart data (generated; the charts and sparklines read this block)", "data_note"))
    for j, name in enumerate(hdr):
        put(r0, DATA_COL + j, Cell(name, "data_head"))
    for i, d in enumerate(trend):
        put(r0 + 1 + i, DATA_COL, Cell(d["date"][5:], "data"))
        for j, key in enumerate(keys[1:], start=1):
            put(r0 + 1 + i, DATA_COL + j, Cell("" if d[key] is None else d[key], "data"))
    d0, d1 = r0 + 1, r0 + 1 + len(trend)  # data rows [d0, d1)
    rej_head = r0 + CHART_DAYS + 3
    out7 = P["7d"]["outcomes"]
    rej_rows = [(rp.REJECT_LABELS[k].split(" (")[0], out7[k]) for k in rp.REJECT_ORDER] + [("Kept", out7["kept"]), ("Waiting", out7["pending"] + out7["abandoned"])]
    put(rej_head, DATA_COL, Cell("Where jobs ended up (7 days)", "data_head"))
    put(rej_head, DATA_COL + 1, Cell("Jobs", "data_head"))
    for i, (name, n) in enumerate(rej_rows):
        put(rej_head + 1 + i, DATA_COL, Cell(name, "data"))
        put(rej_head + 1 + i, DATA_COL + 1, Cell(n, "data"))
    fr_head = rej_head + len(rej_rows) + 2
    older = max(0, f7["dated"] - f7["verified_fresh"])
    put(fr_head, DATA_COL, Cell("New postings by date evidence (7 days)", "data_head"))
    put(fr_head, DATA_COL + 1, Cell("Jobs", "data_head"))
    for i, (name, n) in enumerate([("Verified fresh", f7["verified_fresh"]), ("Dated, older", older), ("Date unknown", f7["date_unknown"])]):
        put(fr_head + 1 + i, DATA_COL, Cell(name, "data"))
        put(fr_head + 1 + i, DATA_COL + 1, Cell(n, "data"))

    def spark(col: int, kind: str = "column") -> Cell:
        rng = f"{col_letter(DATA_COL + col)}{d0 + 1}:{col_letter(DATA_COL + col)}{d1}"
        return Cell(f"last {CHART_DAYS} days", "card_spark", formula=f'=SPARKLINE({rng},{{"charttype","{kind}";"color","#4285f4"}})')

    # ---- title, status banner
    i = g.add([Cell("Job Hunter · Operations", "title")], 36)
    g.merges.append((i, 0, 5))
    i = g.add([Cell(f"Updated {_short(sm['generated_at'])} UTC · last run record {_clock(sf['latest_run_record'])} · last ledger event {_clock(sf['latest_ledger_event'])} · default view 7 days · generated, read-only", "note")], 22)
    g.merges.append((i, 0, COLUMNS - 1))
    color = {"green": "ok", "yellow": "warn", "red": "bad", "grey": "idle"}[head["color"]]
    text = head["lines"][0] if head["status"] == "No data yet" else head["lines"][0].split(": ", 1)[-1]
    i = g.add([Cell(head["status"], f"chip_{color}"), Cell(text, "wrap")], 34)
    g.merges.append((i, 1, COLUMNS - 1))
    g.add([""])

    # ---- cards with sparklines
    cards = [
        ("Last run", (last or {}).get("outcome", UNKNOWN), f"{_clock((last or {}).get('started_at'))} UTC", None, f"card_value_{color}"),
        ("New postings · 7d", r7["new_postings"], f"{r7['existing_postings_baselined']} existing recorded", spark(1), "card_value"),
        ("Verified-fresh matches · 7d", r7["verified_fresh_matches"], f"of {r7['matches_kept']} kept", spark(3), "card_value"),
        ("Alerts delivered · 7d", r7["alerts_delivered"], f"{r7['alerts_unique_jobs']} unique jobs", spark(4), "card_value"),
        ("Waiting / stuck", F["pending_evaluation"]["jobs"] + F["pending_alert"]["jobs"] + F["pending_hydration"]["jobs"], f"{F['table_total']} item(s) need a look" if F["table_total"] else "nothing needs action", None, "card_value"),
    ]
    rows_for = ("label", "value", "spark")
    base_row = len(g.rows)
    for kind in rows_for:
        cells: list[Cell] = []
        for title, value, note, sp, vstyle in cards:
            if kind == "label":
                cells += [Cell(title, "card_label"), Cell("", "card_label")]
            elif kind == "value":
                cells += [Cell(fmt(value), vstyle), Cell("", vstyle)]
            else:
                cells += [sp if sp else Cell(note, "card_note"), Cell("", "card_note")]
        j = g.add(cells, 30 if kind == "value" else None)
        for k_ in range(5):
            g.merges.append((j, 2 * k_, 2 * k_ + 1))
    # a second line of small print under the sparklines for the cards that have one
    cells = []
    for title, value, note, sp, vstyle in cards:
        cells += [Cell(note, "card_note"), Cell("", "card_note")]
    j = g.add(cells)
    for k_ in range(5):
        g.merges.append((j, 2 * k_, 2 * k_ + 1))
    del base_row

    # ---- charts: three rows of two
    def chart_slot(rows: int = 13) -> int:
        start = len(g.rows)
        for _ in range(rows):
            g.add([""])
        return start

    g.add([""])
    a = chart_slot()
    b = chart_slot()
    c3 = chart_slot()
    left_w, right_w = 560, 560
    g.charts += [
        Chart("line", "Jobs per day (by the day first seen)", (0, d0, d1), [(1, "slate"), (2, "blue"), (3, "teal")], a, 0, left_w),
        Chart("column", "Alerts delivered and tracker additions per day", (0, d0, d1), [(4, "teal"), (5, "blue")], a, 5, right_w),
        Chart("stacked_column", "Runs per day", (0, d0, d1), [(6, "teal"), (7, "crimson")], b, 0, left_w),
        Chart("bar", "Where jobs ended up (first seen in the last 7 days)", (0, rej_head + 1, rej_head + 1 + len(rej_rows)), [(1, "blue")], b, 5, right_w),
        Chart("column", "Search credits spent per day", (0, d0, d1), [(8, "amber")], c3, 0, left_w),
        Chart("donut", "New postings: how sure is the date? (7 days)", (0, fr_head + 1, fr_head + 4), [(1, "teal")], c3, 5, right_w),
    ]
    for ch in g.charts:  # domains/series refer to columns of the data block: shift to absolute columns
        ch.domain = (DATA_COL + ch.domain[0], ch.domain[1], ch.domain[2])
        ch.series = [(DATA_COL + c, colr) for c, colr in ch.series]
    for r_, c_, cell_ in deferred:
        g.put(r_, c_, cell_)

    # ---- at a glance
    section("LAST 7 DAYS AT A GLANCE", "Jobs are counted once. Today | 7 days | 30 days are calendar days in " + sm["timezone"] + ".")
    thead(["", "Today", "7 days", "30 days", "Note"])
    metric("Unique jobs first observed", three(["results", "unique_jobs_observed"]), "new postings + existing ones recorded at a board's first read")
    metric("  new postings", three(["results", "new_postings"]))
    metric("Reached scoring", three(["results", "eligible_matches_scored"]), "passed title, age and hard rules")
    metric("Matches kept for the tracker", three(["results", "matches_kept"]), "scored above the tracker threshold")
    metric("  verified fresh", three(["results", "verified_fresh_matches"]), "source time inside the window")
    metric("  date unknown", three(["results", "matches_date_unknown"]), "never counted as fresh")
    metric("Tracker additions (events)", three(["results", "tracker_additions"]), "counted on the day evaluated")
    metric("Alerts delivered (events)", three(["results", "alerts_delivered"]), "counted on the day delivered")
    metric("  repeat deliveries", three(["results", "alerts_repeat_deliveries"]), "at-least-once resends")
    g.add([Cell("Verified fresh, of dated", "label"), *[Cell(_share(P[k]["freshness"]["verified_fresh"], P[k]["freshness"]["dated"]), "num") for k in ("today", "7d", "30d")],
           Cell("undated jobs are outside this share", "note")])
    g.add([Cell("  undated new postings", "label"), *[Cell(P[k]["freshness"]["date_unknown"], "num") for k in ("today", "7d", "30d")], Cell("the denominator excludes them", "note")])
    g.add([Cell("Publication → detection", "label"), *[Cell(_med(P[k]["latency_min"]["publication_to_detection"]), "num_s") for k in ("today", "7d", "30d")]])
    g.add([Cell("Detection → delivery", "label"), *[Cell(_med(P[k]["latency_min"]["detection_to_delivery"]), "num_s") for k in ("today", "7d", "30d")]])
    line("By source (7d)", "  ·  ".join(f"{k} {v}" for k, v in r7["new_by_source"].items()) or "none")
    line("By ATS provider (7d)", "  ·  ".join(f"{k} {v}" for k, v in r7["new_by_ats"].items()) or "none")

    # ---- rejections
    n7 = r7["unique_jobs_observed"]
    section("WHERE JOBS ENDED UP", "One cohort: jobs first observed in the period, each exactly once; rows add up to the first line.")
    thead(["", "Today", "7 days", "30 days", "Share of 7d"])
    g.add([Cell("Jobs first observed", "label"), *[Cell(P[k]["results"]["unique_jobs_observed"], "num_b") for k in ("today", "7d", "30d")], Cell("100%" if n7 else UNKNOWN, "num_b")])
    for key, label in [("baseline", "Baseline (existing, not scored)"), *[(k_, rp.REJECT_LABELS[k_]) for k_ in rp.REJECT_ORDER], ("kept", "Kept (scored)"), ("pending", "Waiting for evaluation"), ("abandoned", "Abandoned after failures")]:
        vals = [P[k]["outcomes"][key] for k in ("today", "7d", "30d")]
        g.add([Cell(label, "label"), *[Cell(v, "num") for v in vals], Cell(f"{round(100 * vals[1] / n7)}%" if n7 else UNKNOWN, "num")])
    if P["7d"]["legacy_reason_codes"]:
        g.add([Cell(f"{P['7d']['legacy_reason_codes']} older evaluation(s) were classified from their recorded verdict text.", "note")])

    # ---- health
    section("HEALTH")
    thead(["", "Today", "7 days", "30 days", "Note"])
    pol = H["polling"]
    metric("Runs finished", [pol[k].get("runs_finished") for k in ("today", "7d", "30d")], "of whole hours elapsed: " + " / ".join(str(fmt(pol[k].get("expected_hourly_slots"))) for k in ("today", "7d", "30d")))
    metric(f"Polling gaps > {rp.LATE_RUN_MIN} min", [pol[k].get("gaps_over_threshold") for k in ("today", "7d", "30d")], "between two finished runs")
    metric("Longest gap (min)", [pol[k].get("max_gap_min") for k in ("today", "7d", "30d")])
    metric("Runs ok / degraded / failed", [f"{pol[k]['ok']}/{pol[k]['degraded']}/{pol[k]['failed']}" if pol[k].get("runs_finished") is not None else None for k in ("today", "7d", "30d")])
    metric("Interrupted runs", [pol[k].get("interrupted") for k in ("today", "7d", "30d")], "started, never finished")
    line("Last run", f"{(last or {}).get('outcome', UNKNOWN)} · started {_short((last or {}).get('started_at'))} · finished {_short((last or {}).get('finished_at'))} · {fmt((last or {}).get('duration_s'), ' s')} · {(last or {}).get('kind', UNKNOWN)}")
    line("Providers", "  ·  ".join(f"{p['provider']} {'DEGRADED' if p['degraded'] else 'ok'} ({p['failing_last_poll']}/{p['monitored']} failing)" for p in H["providers"]) or "no monitored boards yet")

    # ---- discovery
    section("DISCOVERY (Tavily)")
    thead(["", "Today", "7 days", "30 days", "Note"])
    metric("Credits spent", [D["periods"][k]["credits_spent"] for k in ("today", "7d", "30d")])
    metric("Failed requests, billing unknown", [D["periods"][k]["failed_requests_billing_unknown"] for k in ("today", "7d", "30d")], "unresolved charges")
    metric("Unique eligible boards found", [D["unique_eligible_boards_found_by_search"][k] for k in ("today", "7d", "30d")], "validated or monitored now")
    metric("Verified-fresh job matches", [D["unique_verified_fresh_search_matches"][k] for k in ("today", "7d", "30d")], "unique jobs first seen via search")
    if led:
        line(f"Credits · {D['month']}", f"{led['used_locally']} of {led['cap']} used · left: {led['remaining_scheduled']} scheduled, {led['remaining_manual']} manual" + (" · LIMIT HIT" if led["limit_hit"] else "") + ("" if led["month_matches_now"] else " · ledger is from an earlier month"))
    else:
        line("Credits", "ledger not recorded yet: remaining budget unknown")
    if D["account_counter_last_read"] is not None:
        line("Tavily's counter", f"{D['account_counter_last_read']} last read" + (f" ({D['account_minus_local']:+d} vs the local ledger)" if D["account_minus_local"] is not None else ""))
    rot = D["rotation"]
    line("Rotation", UNKNOWN if rot is None else f"slot {rot['cursor']} of {fmt(rot['total_slots'])} · {rot['full_passes']} full passes · last {_clock(rot['last_run_at'])} · {D['hydration_retry_queue']} job(s) awaiting an ATS read")

    # ---- coverage
    section("BOARD COVERAGE", "Of KNOWN eligible boards (found and validated by this system), not of the job market.")
    line("Monitored", f"established {C['established']}/{C['established_target']} · exploration {C['exploration']}/{C['exploration_target']} · total {C['monitored']} of {C['registry_boards']} known")
    line("Waiting for a slot", f"{C['eligible_waiting_boards']} validated boards with an open eligible job · relevant-board coverage {fmt(C['relevant_board_coverage_pct'], '%')} (run {_clock(C['as_of_run'])})")
    v, t = C["validation"], C["trials"]
    line("Validation overdue", f"{v['revalidation_overdue_valid']} re-checks past 7 days · {v['revalidation_overdue_invalid']} invalid past 30 days · {v['never_validated']} never validated")
    line("Trials", f"{t['running']} running · {t['ending_within_48h']} end within 48 h · {t['ended_awaiting_rebalance']} ended, awaiting the weekly rebalance")

    # ---- failures
    section("FAILURES AND RETRIES", "Jobs counted once; attempts apart.")
    att = P["7d"]["attempts"]
    line("Pending now", f"evaluation {F['pending_evaluation']['jobs']} (oldest {fmt(F['pending_evaluation']['oldest_hours'], ' h')}) · alerts {F['pending_alert']['jobs']} (oldest {fmt(F['pending_alert']['oldest_hours'], ' h')}) · hydration {F['pending_hydration']['jobs']}")
    line("Attempts (7d)", f"{att['evaluation']} evaluation attempts ({att['evaluation_transient']} temporary, {att['evaluation_failed']} failed) for {r7['eligible_matches_scored']} jobs scored · {F['error_attempts_total']} error attempts on {F['unique_jobs_with_errors']} jobs ever")
    if F["table"]:
        i = g.add([Cell("What", "thead"), Cell("Count", "thead"), Cell("Since", "thead"), Cell("Detail", "thead"), Cell("", "thead"), Cell("", "thead"), Cell("What to do", "thead"), Cell("", "thead"), Cell("", "thead"), Cell("", "thead")])
        g.merges += [(i, 3, 5), (i, 6, 9)]
        for row in F["table"]:
            sev = {0: "chip_bad", 1: "chip_warn", 2: "chip_warn"}[row["severity"]]
            i = g.add([Cell(f"{row['what']} · {row['ref']}", sev), Cell(row["count"], "num"), Cell(_clock(row["since"]), "note"), Cell(row["detail"], "wrap"), Cell(""), Cell(""), Cell(row["action"], "wrap")], 44)
            g.merges += [(i, 3, 5), (i, 6, 9)]
        if F["table_total"] > len(F["table"]):
            g.add([Cell(f"{F['table_total'] - len(F['table'])} more not shown.", "note")])
    else:
        g.add([Cell("Nothing needs action.", "label")])

    # ---- feedback
    section("YOUR FEEDBACK", "All tracker rows; this tab never writes your columns.")
    fb = FB["feedback"]
    line("My_Feedback", f"Would apply {fb['Would apply']} · Maybe {fb['Maybe']} · Irrelevant {fb['Irrelevant']} · unlabelled {FB['unlabelled']}" + (f" · other {FB['other_text']}" if FB["other_text"] else "")
         + (f"  —  {fmt(FB['would_apply_or_maybe_pct_of_labelled'], '%')} of {FB['labelled_total']} labelled are Would apply or Maybe" if FB["labelled_total"] else ""))
    line("My_Status", " · ".join(f"{k} {v_}" for k, v_ in FB["status"].items() if v_) + (f" · blank {FB['status_blank']}" if FB["status_blank"] else "") or "no rows yet")

    # ---- daily trend (30 days)
    section("DAILY TREND", "Newest first. n/a = nothing recorded that day; 0 is a measured zero.")
    thead(["Date", "Runs done", "With a problem", "Max gap min", "New postings", "Baselined", "Reached scoring", "Verified fresh", "Tracker +", "Alerts"])
    for k_, d in enumerate(sm["trend"]):
        if k_ == 7:
            g.add([Cell("Days 8 to 30", "note")])
        st = "num" if k_ < 7 else "num_dim"
        g.add([Cell(d["date"], "label" if k_ < 7 else "label_dim"), *[Cell(fmt(d[x]), st) for x in ("runs_finished", "runs_not_ok", "max_gap_min", "new_postings", "baselined", "eligible", "verified_fresh_matches", "tracker_additions", "alerts_delivered")]])

    # ---- definitions
    section("READING THIS PAGE")
    for n in (
        f"Fresh = the ATS's own publication time is inside the window; search dates, update times and first sight never count. Excluded: {sm['exclusions']['rehearsal_runs']} rehearsal run(s), {sm['exclusions']['tracker_fixture_rows']} test fixture(s). Rows from before a field existed show n/a.",
        "First-seen jobs and event counts (alerts, tracker additions) are different groups and are never combined into a funnel.",
        "A stopped workflow cannot report its own absence: check the Updated time above. A watchdog and a daily Telegram digest are planned, not built.",
    ):
        i = g.add([Cell(n, "wrap")], 30)
        g.merges.append((i, 0, COLUMNS - 1))
    if sm["checks"]:
        for c_ in sm["checks"]:
            i = g.add([Cell("Consistency check failed: " + c_, "chip_bad")])
            g.merges.append((i, 0, COLUMNS - 1))
    else:
        g.add([Cell("Consistency checks passed.", "note")])
    return g


# --------------------------------------------------------------------------- Sheet publishing


def _rgb(name: str) -> dict[str, float]:
    r, g_, b = PALETTE[name]
    return {"red": r, "green": g_, "blue": b}


def _format(style: str) -> dict[str, Any]:
    base: dict[str, Any] = {"textFormat": {"fontSize": 10, "foregroundColor": _rgb("ink")}, "verticalAlignment": "MIDDLE"}
    tf = base["textFormat"]
    if style == "title":
        tf.update(bold=True, fontSize=18, foregroundColor=_rgb("deep"))
    elif style == "h2":
        tf.update(bold=True, fontSize=11, foregroundColor=_rgb("deep"))
        base["borders"] = {"bottom": {"style": "SOLID", "color": _rgb("line")}}
    elif style == "thead":
        tf.update(bold=True, fontSize=9, foregroundColor=_rgb("muted"))
        base["backgroundColor"] = _rgb("band")
    elif style in ("note", "label_dim"):
        tf.update(fontSize=9, foregroundColor=_rgb("muted"))
        base["wrapStrategy"] = "OVERFLOW_CELL"
    elif style == "wrap":
        base["wrapStrategy"] = "WRAP"
        base["verticalAlignment"] = "TOP"
    elif style in ("num", "num_b", "num_dim", "num_s"):
        base["horizontalAlignment"] = "RIGHT"
        if style == "num_b":
            tf["bold"] = True
        if style == "num_dim":
            tf.update(fontSize=9, foregroundColor=_rgb("muted"))
        if style == "num_s":
            tf["fontSize"] = 9
    elif style.startswith("chip_"):
        tf.update(bold=True)
        base["backgroundColor"] = _rgb({"chip_ok": "green", "chip_warn": "yellow", "chip_bad": "red", "chip_idle": "grey"}[style])
        base["wrapStrategy"] = "WRAP"
    elif style.startswith("card_"):
        base["backgroundColor"] = _rgb("band")
        base["horizontalAlignment"] = "LEFT"
        if style == "card_label":
            tf.update(fontSize=9, foregroundColor=_rgb("muted"))
        elif style.startswith("card_value"):
            tf.update(bold=True, fontSize=22)
            tone = style.rsplit("_", 1)[-1]
            if tone in ("ok", "warn", "bad", "idle"):
                base["backgroundColor"] = _rgb({"ok": "green", "warn": "yellow", "bad": "red", "idle": "grey"}[tone])
        else:  # card_note / card_spark
            tf.update(fontSize=8, foregroundColor=_rgb("muted"))
    elif style in ("data", "data_head", "data_note"):
        tf.update(fontSize=8, foregroundColor=_rgb("muted"), bold=style == "data_head")
    return base


def _cell_data(c: Cell) -> dict[str, Any]:
    out: dict[str, Any] = {"userEnteredFormat": _format(c.style)}
    v = c.value
    if c.formula:
        out["userEnteredValue"] = {"formulaValue": c.formula}  # only sparklines over the generated data block
    elif isinstance(v, bool):
        out["userEnteredValue"] = {"stringValue": "yes" if v else "no"}
    elif isinstance(v, (int, float)):
        out["userEnteredValue"] = {"numberValue": v}
    elif v not in ("", None):
        out["userEnteredValue"] = {"stringValue": str(v)}  # always a literal string, never parsed as a formula
    return out


def _range(sheet_id: int, col: int, r0: int, r1: int) -> dict[str, Any]:
    return {"sheetId": sheet_id, "startRowIndex": r0, "endRowIndex": r1, "startColumnIndex": col, "endColumnIndex": col + 1}


def chart_request(ch: Chart, idx: int, sheet_id: int) -> dict[str, Any]:
    col, r0, r1 = ch.domain
    if ch.kind != "donut":
        r0 -= 1  # include the header row: it names each series in the legend (headerCount 1)
    domain = {"domain": {"sourceRange": {"sources": [_range(sheet_id, col, r0, r1)]}}}
    series = [{"series": {"sourceRange": {"sources": [_range(sheet_id, c, r0, r1)]}}, "targetAxis": "LEFT_AXIS", "color": _rgb(colr)} for c, colr in ch.series]
    if ch.kind == "donut":
        spec: dict[str, Any] = {"pieChart": {"legendPosition": "RIGHT_LEGEND", "domain": domain["domain"], "series": series[0]["series"], "pieHole": 0.55}}
    else:
        basic: dict[str, Any] = {
            "chartType": {"line": "LINE", "column": "COLUMN", "stacked_column": "COLUMN", "bar": "BAR"}[ch.kind],
            "legendPosition": "NO_LEGEND" if len(series) == 1 else "BOTTOM_LEGEND",
            "axis": [{"position": "BOTTOM_AXIS" if ch.kind != "bar" else "LEFT_AXIS"}, {"position": "LEFT_AXIS" if ch.kind != "bar" else "BOTTOM_AXIS"}],
            "domains": [domain], "series": series, "headerCount": 1,
        }  # fmt: skip
        if ch.kind == "line":
            for s_ in series:
                s_["lineStyle"] = {"width": 2}
        if ch.kind == "stacked_column":
            basic["stackedType"] = "STACKED"
        spec = {"basicChart": basic}
    spec["title"] = ch.title
    spec["titleTextFormat"] = {"fontSize": 11, "bold": True, "foregroundColor": _rgb("deep")}
    spec["fontName"] = "Roboto"
    spec["backgroundColor"] = {"red": 1.0, "green": 1.0, "blue": 1.0}
    return {"addChart": {"chart": {
        "chartId": CHART_ID_BASE + idx, "spec": spec,
        "position": {"overlayPosition": {"anchorCell": {"sheetId": sheet_id, "rowIndex": ch.anchor_row, "columnIndex": ch.anchor_col},
                                         "offsetXPixels": 4, "offsetYPixels": 4, "widthPixels": ch.width - 8, "heightPixels": ch.height}},
    }}}  # fmt: skip


def requests_for(grid: Grid, sheet_id: int, existing_chart_ids: list[int] | None = None) -> list[dict[str, Any]]:
    """One batch: delete last time's charts, clear the tab, write every cell with its format, merge, size, add the
    charts. Re-running with the same grid produces the same sheet."""
    n = len(grid.rows)
    whole = {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": max(n + 60, 400), "startColumnIndex": 0, "endColumnIndex": TOTAL_COLUMNS}
    reqs: list[dict[str, Any]] = [{"deleteEmbeddedObject": {"objectId": cid}} for cid in (existing_chart_ids or [])]
    reqs += [
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
    reqs += [chart_request(ch, i, sheet_id) for i, ch in enumerate(grid.charts)]
    return reqs


def _existing_chart_ids(spreadsheet: Any, sheet_id: int) -> list[int]:
    """Charts already on the Dashboard sheet (one metadata read); a failure to read means 'assume none' is NOT safe,
    so it propagates and the refresh is simply skipped this time."""
    meta = spreadsheet.fetch_sheet_metadata() if hasattr(spreadsheet, "fetch_sheet_metadata") else {}
    ids: list[int] = []
    for sheet in (meta or {}).get("sheets", []):
        if (sheet.get("properties") or {}).get("sheetId") == sheet_id:
            ids += [int(c["chartId"]) for c in sheet.get("charts", []) or [] if "chartId" in c]
    return ids


def publish_sheet(spreadsheet: Any, grid: Grid) -> None:
    """Create the Dashboard tab if missing, then rewrite it in a single batchUpdate. Touches no other tab."""
    ws = next((w for w in spreadsheet.worksheets() if w.title == DASHBOARD_TAB), None)
    existing: list[int] = []
    if ws is None:
        ws = spreadsheet.add_worksheet(title=DASHBOARD_TAB, rows=max(len(grid.rows) + 60, 400), cols=TOTAL_COLUMNS)
    else:
        existing = _existing_chart_ids(spreadsheet, ws.id)
        have = getattr(ws, "col_count", None)
        if isinstance(have, int) and have < TOTAL_COLUMNS:
            ws.add_cols(TOTAL_COLUMNS - have)  # the data block lives in columns L..U
    spreadsheet.batch_update({"requests": requests_for(grid, ws.id, existing)})


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
