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
COLUMNS = 9  # the visible page, columns A..I
DATA_COL = 10  # chart data block starts at column K (column J is a hidden gap)
TOTAL_COLUMNS = 21  # A..U
WIDTHS = [190] + [100] * 8 + [20] + [74] * 11  # pixels: page columns A..J, a gap, then the hidden data block
UNKNOWN = "n/a"  # unknown / not recorded: never shown as 0
CHART_DAYS = 14
FONT = "Inter"  # one family throughout; Google Sheets falls back to its default if a font is unavailable
CHART_ID_BASE = 7100  # fixed chart ids, so a refresh deletes exactly its own charts and re-adds them
BAND_LINES_STACK = False  # assumption A7 (unverified in a real Sheet): when True, Sheets stacks LINE series, so "Target 30" holds the 10-row difference

PALETTE = {  # RGB 0-1
    "ink": (0.13, 0.13, 0.15), "muted": (0.45, 0.47, 0.51), "line": (0.86, 0.87, 0.89), "band": (0.95, 0.96, 0.98),
    "green": (0.80, 0.92, 0.82), "yellow": (1.0, 0.94, 0.70), "red": (0.98, 0.80, 0.80), "grey": (0.90, 0.90, 0.90),
    "blue": (0.26, 0.52, 0.96), "teal": (0.10, 0.64, 0.60), "amber": (0.96, 0.69, 0.10), "crimson": (0.86, 0.27, 0.22), "slate": (0.55, 0.60, 0.68),
    "deep": (0.11, 0.23, 0.45), "hair": (0.93, 0.94, 0.95), "card": (0.965, 0.972, 0.985),
}


@dataclass
class Cell:
    value: Any = ""
    style: str = ""
    formula: str = ""  # a Sheets formula (sparklines only); `value` is what the text/CSV version shows


@dataclass
class Chart:
    kind: str  # line | column | stacked_column | bar | donut | combo
    title: str
    domain: tuple[int, int, int]  # (column, first row, last row exclusive) of the labels
    series: list[tuple[int, str]]  # (column, colour name) per series; the header row (first row - 1) names the series
    anchor_row: int
    anchor_col: int
    width: int
    height: int = 250
    series_types: list[str] = field(default_factory=list)  # combo only: COLUMN | LINE per series
    stacked: bool = False  # combo only: stackedType STACKED


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
    return f"{round(100 * num / den)}% of {den}" if den else UNKNOWN


def _groq_text(G: dict[str, Any]) -> str:
    """The Groq SYSTEM line: today's tokens per model against its budget (UTC day), then the 7-day split by model, tokens per
    call with its n, cached share and the governor counters. Unknown prints n/a, never 0 (metric rule 7)."""
    t = G["today"]
    if t is None:
        today = f"today: {UNKNOWN} (no budget record yet)"
    else:
        parts = [
            f"{m.rsplit('/', 1)[-1]} {v['used']} of {fmt(v['budget'])} tokens{' SPENT' if v['exhausted'] else ''}"
            for m, v in t["models"].items()
        ]
        today = f"today (UTC {t['day']}): " + (" · ".join(parts) if parts else "no model recorded")
    split = " ".join(f"{m.rsplit('/', 1)[-1]} {n}" for m, n in G["scored_by_model"].items()) or "none"
    per_call = G["tokens_per_completion"]
    calls = f"{UNKNOWN} tokens per call" if per_call is None else f"{per_call} tokens per call (n={G['tokens_per_completion_n']})"
    cached = UNKNOWN if G["cached_share_pct"] is None else f"{G['cached_share_pct']}%"
    w = G["7d"]
    cuts = (
        f"{UNKNOWN} budget skips · {UNKNOWN} evaluation cuts · {UNKNOWN} poll cuts · {UNKNOWN} alerts deferred"
        if not w["runs"]
        else f"{w['budget_skipped']} budget skips · {w['runs_with_eval_cut']} evaluation cuts · {w['boards_skipped_deadline']} poll cuts · {w['alerts_deferred']} alerts deferred"
    )
    return f"{today} · 7d: scored by {split} · {calls} · cached {cached} of prompt · {cuts}"


def render(sm: dict[str, Any]) -> Grid:
    """The page, top to bottom: banner, cards, four charts, one small table, a few key lines, what needs attention.
    Deliberately sparse: detail tables were removed from the page (the numbers behind the charts sit in a hidden
    data block, and `--dashboard --dry-run` prints everything)."""
    g = Grid()
    P, H, D, C, F, FB = sm["periods"], sm["health"], sm["discovery"], sm["coverage"], sm["failures"], sm["feedback"]
    head, sf = sm["headline"], sm["source_freshness"]
    last = H["last_run"]
    r7, f7, o7 = P["7d"]["results"], P["7d"]["freshness"], P["7d"]["outcomes"]
    led = D["ledger"]
    trend = list(reversed(sm["trend"][:CHART_DAYS]))  # oldest first for charts
    stuck = F["pending_evaluation"]["jobs"] + F["pending_alert"]["jobs"] + F["pending_hydration"]["jobs"]

    def spacer(h: int = 14) -> None:
        g.add([""], h)

    def section(title: str) -> None:
        spacer(18)
        i = g.add([Cell(title, "h2")], 26)
        g.merges.append((i, 0, COLUMNS - 1))

    def line(label: str, text: str) -> None:
        i = g.add([Cell(label, "label"), Cell(text, "text")], 26)
        g.merges.append((i, 1, COLUMNS - 1))

    # ---- chart data block (columns L..U, hidden): chronological, blank = unknown (a gap, never a plotted zero).
    # Cells are collected and written after the page is laid out, so they never shift the visible rows.
    deferred: list[tuple[int, int, Cell]] = []

    def put(r: int, c: int, cell: Cell) -> None:
        deferred.append((r, c, cell))

    r0 = 1
    hdr = ["Date", "New postings", "Reached scoring", "Verified-fresh matches", "Alerts delivered", "Tracker additions", "Runs ok", "Runs with a problem", "Search credits"]
    keys = [None, "new_postings", "eligible", "verified_fresh_matches", "alerts_delivered", "tracker_additions", "runs_ok", "runs_not_ok", "search_credits"]
    for j, name in enumerate(hdr):
        put(r0, DATA_COL + j, Cell(name, "data_head"))
    for i, d in enumerate(trend):
        mm, dd = d["date"][5:].split("-")
        put(r0 + 1 + i, DATA_COL, Cell(f"{int(mm)}/{int(dd)}" if i == 0 or int(dd) == 1 else str(int(dd)), "data"))  # day numbers keep the axis horizontal
        for j, key in enumerate(keys[1:], start=1):
            put(r0 + 1 + i, DATA_COL + j, Cell("" if d[key] is None else d[key], "data"))
    d0, d1 = r0 + 1, r0 + 1 + len(trend)
    rej_head = r0 + CHART_DAYS + 3
    short = {"age": "Too old", "location": "Outside US", "experience": "4+ yrs required", "language": "Language", "closed": "Closed", "score": "Low score"}
    rej_rows = [(short[k], o7[k]) for k in rp.REJECT_ORDER if k != "title"] + [("Kept", o7["kept"]), ("Waiting", o7["pending"] + o7["abandoned"])]
    put(rej_head, DATA_COL, Cell("Outcome", "data_head"))
    put(rej_head, DATA_COL + 1, Cell("Jobs", "data_head"))
    for i, (name, n) in enumerate(rej_rows):
        put(rej_head + 1 + i, DATA_COL, Cell(name, "data"))
        put(rej_head + 1 + i, DATA_COL + 1, Cell(n, "data"))

    # tracker rows per found-day (the first chart): blank = unknown day; the two target lines are blank on unknown days too
    Y = sm["yield"]
    yield_head = rej_head + len(rej_rows) + 3
    for j, name in enumerate(["Date", "Verified fresh", "Recent", "Other", "Target 20", "Target 30"]):
        put(yield_head, DATA_COL + j, Cell(name, "data_head"))
    lo, hi = rp.TARGET_ROWS_PER_DAY
    for i, d in enumerate(Y["trend"]):
        mm, dd = d["date"][5:].split("-")
        rec = d["total"] is not None
        row_vals = [f"{int(mm)}/{int(dd)}" if i == 0 or int(dd) == 1 else str(int(dd))] + ["" if d[c] is None else d[c] for c in rp.COHORTS]
        row_vals += [lo, (hi - lo) if BAND_LINES_STACK else hi] if rec else ["", ""]
        for j, v in enumerate(row_vals):
            put(yield_head + 1 + i, DATA_COL + j, Cell(v, "data"))
    y0, y1 = yield_head + 1, yield_head + 1 + len(Y["trend"])
    # age when found, 7 days, every cohort (a bar chart reads this block)
    age_head = yield_head + CHART_DAYS + 3
    put(age_head, DATA_COL, Cell("Age when found", "data_head"))
    put(age_head, DATA_COL + 1, Cell("Rows", "data_head"))
    for i, (key, label) in enumerate(rp.AGE_BUCKETS):
        put(age_head + 1 + i, DATA_COL, Cell(label, "data"))
        put(age_head + 1 + i, DATA_COL + 1, Cell(Y["per_period"]["7d"]["by_age"][key], "data"))
    age0, age1 = age_head + 1, age_head + 1 + len(rp.AGE_BUCKETS)

    def spark(col: int) -> Cell:
        rng = f"{col_letter(DATA_COL + col)}{d0 + 1}:{col_letter(DATA_COL + col)}{d1}"
        return Cell("", "card_spark", formula=f'=SPARKLINE({rng},{{"charttype","column";"color","#5f8df5";"empty","ignore"}})')

    # ---- header: title, one muted line, one status banner
    i = g.add([Cell("Job Hunter", "title")], 44)
    g.merges.append((i, 0, 4))
    i = g.add([Cell(f"Updated {_short(sm['generated_at'])[:16]} UTC  ·  last run {_clock(sf['latest_run_record'])}  ·  last 7 days unless stated", "muted")], 22)
    g.merges.append((i, 0, COLUMNS - 1))
    spacer(10)
    color = {"green": "ok", "yellow": "warn", "red": "bad", "grey": "idle"}[head["color"]]
    text = head["lines"][0] if head["status"] == "No data yet" else head["lines"][0].split(": ", 1)[-1]
    i = g.add([Cell(head["status"], f"chip_{color}"), Cell(text, "banner")], 36)
    g.merges.append((i, 1, COLUMNS - 1))
    spacer(16)

    # ---- cards: label, big number, 14-day sparkline
    cards = [
        ("Last run", (last or {}).get("outcome", UNKNOWN), None, f"card_value_{color}", f"{_clock((last or {}).get('started_at'))} UTC"),
        ("Reached scoring · 7d", r7["eligible_matches_scored"], spark(2), "card_value", f"of {r7['new_postings']} new postings"),
        ("Verified fresh · 7d", r7["verified_fresh_matches"], spark(3), "card_value", f"of {r7['matches_kept']} kept for the tracker"),
        ("Alerts delivered · 7d", r7["alerts_delivered"], spark(4), "card_value", f"{r7['alerts_unique_jobs']} unique jobs"),
        ("Needs attention", F["table_total"], None, "card_value" if not F["table_total"] else "card_value_bad", f"{stuck} waiting" if stuck else "all clear"),
    ]
    for kind in ("label", "value", "spark", "note"):
        cells: list[Cell] = []
        for n_, (title, value, sp, vstyle, note) in enumerate(cards):
            style = {"label": "card_label", "value": vstyle, "spark": "card_note", "note": "card_note"}[kind]
            cell = {"label": Cell(title, style), "value": Cell(fmt(value), style), "spark": sp or Cell("", style), "note": Cell(note, style)}[kind]
            cells += [cell] if n_ == 0 else [cell, Cell("", style)]  # the first card is one column (A); the rest span two
        j = g.add(cells, {"label": 24, "value": 40, "spark": 34, "note": 22}[kind])
        for start in (1, 3, 5, 7):
            g.merges.append((j, start, start + 1))
    spacer(18)

    # ---- charts: two rows of two
    def chart_slot(rows: int = 12) -> int:
        start = len(g.rows)
        for _ in range(rows):
            g.add([""], 22)
        return start

    a, b = chart_slot(), chart_slot()
    g.charts += [
        Chart("combo", "Tracker rows per day · target 20-30", (0, y0, y1), [(1, "teal"), (2, "blue"), (3, "slate"), (4, "amber"), (5, "amber")], a, 0, 490, 258,
              series_types=["COLUMN", "COLUMN", "COLUMN", "LINE", "LINE"], stacked=True),
        Chart("bar", "How old jobs were when found · 7d", (0, age0, age1), [(1, "blue")], a, 4, 500, 258),
        Chart("stacked_column", "Runs per day", (0, d0, d1), [(6, "teal"), (7, "crimson")], b, 0, 490, 258),
        Chart("bar", "Why relevant-title jobs were dropped · 7d", (0, rej_head + 1, rej_head + 1 + len(rej_rows)), [(1, "blue")], b, 4, 500, 258),
    ]
    for ch in g.charts:  # domains/series refer to columns of the data block: shift to absolute columns
        ch.domain = (DATA_COL + ch.domain[0], ch.domain[1], ch.domain[2])
        ch.series = [(DATA_COL + c, colr) for c, colr in ch.series]
    for r_, c_, cell_ in deferred:
        g.put(r_, c_, cell_)

    # ---- tracker rows, 7 days: rows and the My_Feedback mix per cohort (P2-11); counts only, never tracker text
    section("TRACKER ROWS · 7 DAYS")
    g.add([Cell("", "thead"), *[Cell(t_, "thead_r") for t_ in ("Rows", "Would apply", "Maybe", "Irrelevant", "Unlabelled")]], 24)
    y7 = Y["per_period"]["7d"]
    fb_cols = ("Would apply", "Maybe", "Irrelevant", "unlabelled")
    cohort_rows = [("Verified fresh", "verified_fresh"), ("Recent", "recent"), ("Other", "other")]
    for label_, cohort in cohort_rows:
        f_ = y7["feedback"][cohort]
        g.add([Cell(label_, "label"), *[Cell(fmt(v), "num") for v in (y7["by_cohort"][cohort], *(f_[c] for c in fb_cols))]], 26)
    g.add([Cell("All", "label"), *[Cell(fmt(v), "num") for v in (y7["rows"], *(sum(y7["feedback"][c_][c] for _, c_ in cohort_rows) for c in fb_cols))]], 26)
    rc = Y["reconcile"]
    other_text = sum(y7["feedback"][c_]["other_text"] for _, c_ in cohort_rows)
    ats_text = " · ".join(f"{a_} {n_}" for a_, n_ in sorted(y7["by_ats"].items(), key=lambda kv: (-kv[1], kv[0]))) or "none"
    i = g.add([Cell(
        f"Day = the day the job was found ({sm['timezone']}); age = when it was found minus the posting's own publication time; unknown = no time-precise publication time (never counted as fresh). "
        f"{rc['in_tracker']} of {rc['ledger_kept']} ledger-kept jobs are in the tracker"
        + (f" ({rc['deleted_by_owner']} deleted on purpose, Tracker_Deleted_Keys)" if rc.get("deleted_by_owner") else "")
        + f"; {rc['tracker_rows_without_ledger_match']} rows have no ledger match"
        + (f"; {other_text} row(s) carry free-text feedback" if other_text else "") + f". By ATS (7d): {ats_text}.", "muted_wrap")], 48)
    g.merges.append((i, 0, COLUMNS - 1))

    # ---- one small table
    section("THIS WEEK")
    g.add([Cell("", "thead"), Cell("Today", "thead_r"), Cell("7 days", "thead_r"), Cell("30 days", "thead_r")], 24)

    def row(label: str, vals: list[Any], style: str = "num") -> None:
        g.add([Cell(label, "label"), *[Cell(fmt(v), style) for v in vals]], 26)

    def three(path: list[str]) -> list[Any]:
        out = []
        for key in ("today", "7d", "30d"):
            v: Any = P[key]
            for part in path:
                v = v[part]
            out.append(v)
        return out

    row("Unique jobs first observed", three(["results", "unique_jobs_observed"]))
    row("New postings (after a board's first read)", three(["results", "new_postings"]))
    row("Reached scoring", three(["results", "eligible_matches_scored"]))
    row("Kept for the tracker", three(["results", "matches_kept"]))
    row("Verified fresh", three(["results", "verified_fresh_matches"]))
    row("Kept, publication date unknown", three(["results", "matches_date_unknown"]))
    row("Alerts delivered", three(["results", "alerts_delivered"]))
    row("Verified fresh, share of dated jobs", [_share(P[k]["freshness"]["verified_fresh"], P[k]["freshness"]["dated"]) for k in ("today", "7d", "30d")], "num_s")
    row("Publication → detection, median", [_med(P[k]["latency_min"]["publication_to_detection"]) for k in ("today", "7d", "30d")], "num_s")
    ls = P["7d"]["latency_sample"]
    i = g.add([Cell(f"Detection sample (7d): {ls['time_precise_date']} of {ls['relevant_new_postings_detected']} detected relevant postings had a time-precise publication time; {ls['day_precision_date']} a date only, {ls['no_date']} none.", "muted")], 20)
    g.merges.append((i, 0, COLUMNS - 1))
    row("Detection → delivery, median", [_med(P[k]["latency_min"]["detection_to_delivery"]) for k in ("today", "7d", "30d")], "num_s")

    # ---- system, in a few lines
    section("SYSTEM")
    pol = H["polling"]["7d"]
    line("Runs", f"{fmt(pol.get('runs_finished'))} finished · {fmt(pol.get('gaps_over_threshold'))} gap(s) over {rp.LATE_RUN_MIN} min · longest {fmt(pol.get('max_gap_min'), ' min')} · {pol.get('degraded', 0)} degraded · {pol.get('failed', 0)} failed · {pol.get('interrupted', 0)} interrupted")
    line("Providers", "  ·  ".join(f"{p['provider']} {'DEGRADED' if p['degraded'] else 'ok'}" for p in H["providers"]) or "no monitored boards yet")
    if led:
        line("Search credits", f"{led['used_locally']} of {led['cap']} used this month · {led['remaining_scheduled']} left for scheduled runs · {D['periods']['7d']['failed_requests_billing_unknown']} failed request(s) with unknown billing (7d)" + (" · LIMIT HIT" if led["limit_hit"] else ""))
    else:
        line("Search credits", "not recorded yet: remaining budget unknown")
    line("Groq", _groq_text(sm["groq"]))
    rot = D["rotation"]
    line("Discovery", f"{D['unique_eligible_boards_found_by_search']['7d']} eligible boards found (7d) · {D['unique_verified_fresh_search_matches']['7d']} fresh matches via search · " + (UNKNOWN if rot is None else f"rotation at slot {rot['cursor']} of {fmt(rot['total_slots'])}"))
    v_, t_ = C["validation"], C["trials"]
    ck = C["coverage_known_relevant"]
    cover = "coverage not recorded yet" if ck is None else f"{ck['monitored_with_open_relevant_jobs']} of {ck['known_relevant_boards']} known relevant boards have a slot ({fmt(ck['coverage_pct'], '%')}; {ck['monitored_without']} monitored have nothing open, {ck['relevant_waiting']} wait)"
    line("Board coverage", cover + " · of known boards, not the market")
    line("Pools", f"{C['established']} established + {C['exploration']} exploring = {C['monitored']} monitored · {v_['revalidation_overdue_valid']} re-checks overdue · {t_['ended_awaiting_rebalance']} trials ended")
    line("Dropped (7d)", f"title {o7['title']} · age {o7['age']} · location {o7['location']} · experience {o7['experience']} · language {o7['language']} · closed {o7['closed']} · score {o7['score']} · {f7['new_postings_date_unknown']} new posting(s) without a date")
    fb = FB["feedback"]
    line("Your feedback", f"Would apply {fb['Would apply']} · Maybe {fb['Maybe']} · Irrelevant {fb['Irrelevant']} · unlabelled {FB['unlabelled']}" + (f"  ({fmt(FB['would_apply_or_maybe_pct_of_labelled'], '%')} of {FB['labelled_total']} labelled are Would apply or Maybe)" if FB["labelled_total"] else ""))

    # ---- needs attention (only when something does)
    if F["table"]:
        section("NEEDS ATTENTION")
        for r in F["table"]:
            sev = {0: "chip_bad", 1: "chip_warn", 2: "chip_warn"}[r["severity"]]
            i = g.add([Cell(f"{r['what']}", sev), Cell(f"{r['ref']} — {r['detail']}  →  {r['action']}", "wrap")], 40)
            g.merges.append((i, 1, COLUMNS - 1))
        if F["table_total"] > len(F["table"]):
            g.add([Cell(f"{F['table_total'] - len(F['table'])} more not shown.", "muted")])

    # ---- footer
    spacer(20)
    for n in (
        "Fresh = the ATS's own publication time is inside the window; search dates, update times and first sight never count. n/a = not recorded, never zero. First-seen jobs and event counts are separate groups.",
        f"Excluded: {sm['exclusions']['rehearsal_runs']} rehearsal run(s), {sm['exclusions']['tracker_fixture_rows']} test fixture(s). A stopped workflow cannot report its own absence: check the Updated time. Coverage is of known eligible boards, not the market.",
    ):
        i = g.add([Cell(n, "muted_wrap")], 32)
        g.merges.append((i, 0, COLUMNS - 1))
    if sm["checks"]:
        for c_ in sm["checks"]:
            i = g.add([Cell("Consistency check failed: " + c_, "chip_bad")])
            g.merges.append((i, 0, COLUMNS - 1))
    return g


# --------------------------------------------------------------------------- Sheet publishing


def _rgb(name: str) -> dict[str, float]:
    r, g_, b = PALETTE[name]
    return {"red": r, "green": g_, "blue": b}


def _format(style: str) -> dict[str, Any]:
    """One family (Inter), a quiet palette: ink for numbers, grey for everything secondary, one blue accent."""
    tf: dict[str, Any] = {"fontFamily": FONT, "fontSize": 10, "foregroundColor": _rgb("ink")}
    base: dict[str, Any] = {"textFormat": tf, "verticalAlignment": "MIDDLE", "padding": {"left": 6, "right": 6}}
    if style == "title":
        tf.update(bold=True, fontSize=22, foregroundColor=_rgb("deep"))
        base["padding"] = {"left": 2}
    elif style in ("muted", "muted_wrap"):
        tf.update(fontSize=9, foregroundColor=_rgb("muted"))
        base["padding"] = {"left": 2}
        if style == "muted_wrap":
            base["wrapStrategy"] = "WRAP"
            base["verticalAlignment"] = "TOP"
    elif style == "banner":
        tf.update(fontSize=11)
        base["backgroundColor"] = _rgb("band")
        base["padding"] = {"left": 12}
    elif style == "h2":
        tf.update(bold=True, fontSize=9, foregroundColor=_rgb("muted"))
        base["verticalAlignment"] = "BOTTOM"
        base["padding"] = {"left": 2, "bottom": 4}
        base["borders"] = {"bottom": {"style": "SOLID", "color": _rgb("line")}}
    elif style in ("thead", "thead_r"):
        tf.update(fontSize=9, foregroundColor=_rgb("muted"))
        base["padding"] = {"left": 2, "right": 8}
        if style == "thead_r":
            base["horizontalAlignment"] = "RIGHT"
    elif style == "label":
        base["padding"] = {"left": 2}
        base["borders"] = {"bottom": {"style": "SOLID", "color": _rgb("hair")}}
    elif style == "text":
        tf.update(foregroundColor=_rgb("muted"), fontSize=10)
        base["borders"] = {"bottom": {"style": "SOLID", "color": _rgb("hair")}}
        base["wrapStrategy"] = "OVERFLOW_CELL"
    elif style == "wrap":
        base["wrapStrategy"] = "WRAP"
        base["borders"] = {"bottom": {"style": "SOLID", "color": _rgb("hair")}}
    elif style in ("num", "num_s"):
        base["horizontalAlignment"] = "RIGHT"
        base["padding"] = {"right": 8}
        base["borders"] = {"bottom": {"style": "SOLID", "color": _rgb("hair")}}
        if style == "num_s":
            tf.update(fontSize=9, foregroundColor=_rgb("muted"))
    elif style.startswith("chip_"):
        tf.update(bold=True, fontSize=10)
        base["backgroundColor"] = _rgb({"chip_ok": "green", "chip_warn": "yellow", "chip_bad": "red", "chip_idle": "grey"}[style])
        base["wrapStrategy"] = "WRAP"
        base["padding"] = {"left": 12, "right": 8}
    elif style.startswith("card_"):
        base["backgroundColor"] = _rgb("card")
        base["horizontalAlignment"] = "LEFT"
        base["padding"] = {"left": 14, "right": 6}
        if style == "card_label":
            tf.update(fontSize=9, foregroundColor=_rgb("muted"))
            base["verticalAlignment"] = "BOTTOM"
        elif style.startswith("card_value"):
            tf.update(bold=True, fontSize=26, foregroundColor=_rgb("deep"))
            tone = style.rsplit("_", 1)[-1]
            if tone in ("ok", "warn", "bad", "idle"):
                base["backgroundColor"] = _rgb({"ok": "green", "warn": "yellow", "bad": "red", "idle": "grey"}[tone])
                tf["foregroundColor"] = _rgb("ink")
        else:  # card_note / card_spark
            tf.update(fontSize=8, foregroundColor=_rgb("muted"))
            base["verticalAlignment"] = "TOP"
    elif style in ("data", "data_head"):
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
    series = [{"series": {"sourceRange": {"sources": [_range(sheet_id, c, r0, r1)]}}, "targetAxis": "BOTTOM_AXIS" if ch.kind == "bar" else "LEFT_AXIS", "color": _rgb(colr)} for c, colr in ch.series]  # the live API: bar-chart series may only target the bottom axis
    if ch.kind == "donut":
        spec: dict[str, Any] = {"pieChart": {"legendPosition": "RIGHT_LEGEND", "domain": domain["domain"], "series": series[0]["series"], "pieHole": 0.55}}
    else:
        basic: dict[str, Any] = {
            "chartType": {"line": "LINE", "column": "COLUMN", "stacked_column": "COLUMN", "bar": "BAR", "combo": "COMBO"}[ch.kind],
            "legendPosition": "NO_LEGEND" if len(series) == 1 else "BOTTOM_LEGEND",
            "axis": [{"position": "BOTTOM_AXIS" if ch.kind != "bar" else "LEFT_AXIS"}, {"position": "LEFT_AXIS" if ch.kind != "bar" else "BOTTOM_AXIS"}],
            "domains": [domain], "series": series, "headerCount": 1,
        }  # fmt: skip
        if ch.kind == "line":
            for s_ in series:
                s_["lineStyle"] = {"width": 2}
        if ch.kind == "stacked_column" or (ch.kind == "combo" and ch.stacked):
            basic["stackedType"] = "STACKED"
        if ch.kind == "combo":
            for s_, typ in zip(series, ch.series_types):
                s_["type"] = typ
                if typ == "LINE":
                    s_["lineStyle"] = {"width": 2, "type": "MEDIUM_DASHED"}
        if ch.kind == "bar":
            for s_ in series:
                s_["dataLabel"] = {"type": "DATA", "placement": "OUTSIDE_END", "textFormat": {"fontFamily": FONT, "fontSize": 9, "foregroundColor": _rgb("muted")}}
        spec = {"basicChart": basic}
    spec["title"] = ch.title
    spec["titleTextFormat"] = {"fontFamily": FONT, "fontSize": 11, "bold": True, "foregroundColor": _rgb("deep")}
    spec["fontName"] = FONT
    spec["hiddenDimensionStrategy"] = "SHOW_ALL"  # the data block's columns are hidden; the charts must still read them
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
    reqs.append({"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": DATA_COL - 1, "endIndex": TOTAL_COLUMNS}, "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}})
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
    """Load the state with batch reads (one `get_all_values` per tab) and build the summary from the merged ledger view."""
    from datetime import timedelta

    state = store.state
    now = now or datetime.now(timezone.utc)
    policy = settings.pool_policy
    ledger = state.load_ledger()  # the merged view (D-57): Events rows plus Identity and Tally; `folded()` is empty while Events holds every row
    return rp.build_summary(
        now=now, tz=tz or getattr(store, "display_tz", timezone.utc), runs=state.load_runs(), events=ledger.events, folded=ledger.folded(), boards=state.load_boards(),
        discovery=state.load_discovery_state(), tracker=store.tracker_rows(), fresh_window=timedelta(hours=settings.fresh_window_hours),
        search_cap=settings.search_monthly_credits, search_reserve=settings.search_reserve_credits,
        established_target=policy.established_target, exploration_target=policy.exploration_target, run_timeout_s=run_timeout_s, min_alert_score=settings.min_score,
        tracker_deleted=frozenset(getattr(settings, "tracker_deleted_keys", ())),
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
