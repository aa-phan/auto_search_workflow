"""Read-only measurement of what the Events ledger is made of and what a compact design would save.

Nothing here prunes, compacts, archives or migrates anything: it only reads the ledger, the board registry and the Runs
log and prints measurements, with the assumptions behind every projection stated next to it. It exists to scope
a storage change (SPEC / DECISIONS D-43) without touching production data.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import compact
import freshness as fr
import ledger as lg
from boards import MONITORED, STATUS_VALIDATED, BoardRecord, admission_order
from state import RunRecord

EVENT_COLUMNS = 7
SHEET_CELL_LIMIT = 10_000_000
CELL_CHAR_LIMIT = 50_000
COMPACT_CELL_CHARS = compact.IDENTITY_CELL_CHARS  # one Identity cell (headroom under the 50,000-character cell limit); defined once, in compact
COMPACT_COLUMNS = 5  # Board_Key, Chunk, Baselined_At, Count, IDs


def _stamp(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _row_chars(ev: lg.Event) -> int:
    return sum(len(c) for c in ev.to_row())


def classify(ev: lg.Event) -> str:
    """The purpose a ledger row serves.
    baseline    a `seen` row written when a board was first read (or re-read after re-entry): identity for dedupe only
    identity    a `seen` row for a job that is never evaluated (title gate, stale): identity for dedupe only
    operational a `seen` row for a job that enters the pipeline, and every evaluated / alerted / error / abandoned /
                updated / republished row: needed for retries, alerts and reporting"""
    disposition = compact.identity_class(ev)  # the one definition of identity-class (D-57)
    if disposition == lg.BASELINED:
        return "baseline"
    return "identity" if disposition else "operational"


_PURPOSE_OF_DISPOSITION = {lg.BASELINED: "baseline", lg.FILTERED: "identity", lg.STALED: "identity"}
_NEVER = datetime(1970, 1, 1, tzinfo=timezone.utc)  # `needs_alert` takes a clock it does not read


def _stem(key: str) -> str:
    return "|".join(key.split("|", 2)[:2])


def logical_counts(events: list[lg.Event], *, folded: Iterable[compact.FoldedCount] = (), identity: compact.IdentitySet | None = None) -> dict[str, Any]:
    """The counts that must not depend on where the identity-only observations are stored (P3-10), one job once: first-seen jobs
    by purpose, by disposition and per UTC day of first observation by purpose; the boards with baselines and the baseline jobs
    per board (`ats|board`); and the jobs that must be preserved (awaiting evaluation or alert). Physical figures (rows,
    characters, cells, load time) are not logical and are reported, never compared.

    Events rows count each key once, at its first `seen` row (a duplicate row changes nothing). `folded` adds the Tally counts whose
    Events rows are gone, by their recorded disposition and the UTC day of the run. With `identity`, a board's baseline jobs are the
    `b` entries of its Identity set plus the baseline rows in Events that Identity does not hold (an unkeyable key); without it they
    are the Events baseline rows."""
    first: dict[str, lg.Event] = {}
    for ev in events:
        if ev.event == lg.SEEN and ev.key not in first:
            first[ev.key] = ev
    purpose: Counter[str] = Counter()
    disposition: Counter[str] = Counter()
    per_day: dict[str, Counter[str]] = defaultdict(Counter)
    baseline_by_board: Counter[str] = Counter()
    held = identity.keys() if identity is not None else set()
    for ev in first.values():
        kind = classify(ev)
        purpose[kind] += 1
        disposition[ev.disposition] += 1
        if t := _stamp(ev.time):
            per_day[t.strftime("%Y-%m-%d")][kind] += 1
        if kind == "baseline" and ev.key not in held:
            baseline_by_board[_stem(ev.key)] += 1
    for fc in folded:
        dim = compact.parse_dim(fc.dim)
        kind = _PURPOSE_OF_DISPOSITION.get(dim["disposition"], "operational")
        purpose[kind] += fc.n
        disposition[dim["disposition"]] += fc.n
        if t := _stamp(fc.run_at):
            per_day[t.strftime("%Y-%m-%d")][kind] += fc.n
    if identity is not None:  # a Tally count has no board: the baselines per board come from Identity
        for stem in identity.stems():
            kinds: dict[str, str] = {}
            for row in identity.rows(stem):
                for entry in row.entries():
                    letter, pid = compact.decode_entry(entry)
                    kinds.setdefault(pid, letter)  # the first entry for an ID wins, as in IdentitySet
            if n := sum(1 for letter in kinds.values() if letter == compact.KIND_OF[lg.BASELINED]):
                baseline_by_board[stem] += n
    pending = sum(1 for s in lg.replay(events).values() if lg.needs_evaluation(s) or lg.needs_alert(s, _NEVER))
    return {
        "jobs_by_purpose": {k: purpose[k] for k in ("baseline", "identity", "operational")},
        "jobs_by_disposition": dict(sorted(disposition.items())),
        "jobs_per_day_by_purpose": {day: {k: c[k] for k in ("baseline", "identity", "operational")} for day, c in sorted(per_day.items())},
        "boards_with_baselines": len(baseline_by_board), "baseline_jobs_per_board": dict(sorted(baseline_by_board.items())),
        "must_be_preserved": pending,
    }  # fmt: skip


def analyze(
    events: list[lg.Event], boards: dict[str, BoardRecord], runs: list[RunRecord], now: datetime, *, extra_boards: tuple[int, ...] = (200,), ledger: compact.Ledger | None = None
) -> dict[str, Any]:  # fmt: skip
    """`events` are the Events rows (the physical figures read them). With `ledger` (the merged view: Events rows plus Identity and Tally)
    the report also carries `logical`, the counts that do not depend on where an observation is stored."""
    kinds: Counter[str] = Counter()
    chars: Counter[str] = Counter()
    by_type: Counter[str] = Counter()
    per_day: dict[str, Counter[str]] = defaultdict(Counter)
    baseline_by_board: Counter[str] = Counter()
    baseline_id_chars: Counter[str] = Counter()
    baseline_first: dict[str, datetime] = {}
    seen_disp: Counter[str] = Counter()
    for ev in events:
        k = classify(ev)
        kinds[k] += 1
        n = _row_chars(ev)
        chars[k] += n
        by_type[ev.event] += 1
        t = _stamp(ev.time)
        if t:
            per_day[t.strftime("%Y-%m-%d")][k] += 1
        if ev.event == lg.SEEN:
            seen_disp[ev.disposition] += 1
        if k == "baseline":
            parts = ev.key.split("|", 2)
            board = "|".join(parts[:2])
            baseline_by_board[board] += 1
            baseline_id_chars[board] += len(parts[2]) + 1 if len(parts) == 3 else 0
            if t and (board not in baseline_first or t < baseline_first[board]):
                baseline_first[board] = t
    total = len(events)
    total_chars = sum(chars.values())
    # ---- admission vs steady state
    days = sorted(per_day)
    full_days = [d for d in days if d != now.strftime("%Y-%m-%d")][-7:]  # complete days only, last 7 at most
    ops_per_day = [per_day[d]["operational"] for d in full_days]
    ident_per_day = [per_day[d]["identity"] for d in full_days]
    base_per_day = [per_day[d]["baseline"] for d in full_days]
    monitored = [b for b in boards.values() if b.status in MONITORED]
    n_mon = max(1, len(monitored))
    ops_day = statistics.median(ops_per_day) if ops_per_day else None
    ident_day = statistics.median(ident_per_day) if ident_per_day else None
    boards_with_baseline = len(baseline_by_board)
    per_board = sorted(baseline_by_board.values())
    avg_rows = statistics.mean(per_board) if per_board else None
    id_chars = sum(baseline_id_chars.values())
    # ---- initial admission growth of adding boards: the NEXT boards in admission order, from their last known job counts
    waiting = [b for b in admission_order(boards, now=now)]
    admission: dict[str, Any] = {}
    for add in extra_boards + (len(waiting),):
        nxt = waiting[:add]
        jobs = sum(max(0, b.last_job_count) for b in nxt)
        admission[str(len(nxt))] = {
            "boards_added": len(nxt), "baseline_rows_one_time": jobs,
            "cells_one_time_now": jobs * EVENT_COLUMNS, "chars_one_time_now": int(jobs * (chars["baseline"] / max(1, kinds["baseline"]))),
            "mean_jobs_per_board": round(jobs / len(nxt), 1) if nxt else None,
            "compact_cells_one_time": len(nxt) * COMPACT_COLUMNS * max(1, math.ceil((jobs / max(1, len(nxt))) * (id_chars / max(1, sum(baseline_by_board.values()))) / COMPACT_CELL_CHARS)),
        }
    # ---- compact baseline design: one row per board (and per 40k-character chunk)
    compact_rows = sum(max(1, math.ceil(c / COMPACT_CELL_CHARS)) for c in baseline_id_chars.values())
    operational_cells = kinds["operational"] * EVENT_COLUMNS
    compact_cells_now = compact_rows * COMPACT_COLUMNS
    # ---- load time per ledger row, from the Runs log (a measured slope, not a promise)
    pts = sorted((r.events_rows, r.load_s) for r in runs if r.events_rows and r.completed)
    load_by_size: dict[str, Any] = {}
    if len(pts) >= 6:
        third = len(pts) // 3
        for label, chunk in (("smallest third of ledger sizes", pts[:third]), ("middle third", pts[third : 2 * third]), ("largest third", pts[2 * third :])):
            load_by_size[label] = {"ledger_rows": f"{chunk[0][0]:,}-{chunk[-1][0]:,}", "median_load_s": statistics.median(p[1] for p in chunk), "runs": len(chunk)}
    slope = None  # whole-second resolution and a registry of ~22k rows dominate: a per-row slope is only reported when it is real
    if len(pts) >= 6 and pts[-1][0] - pts[0][0] > 20_000:
        n = len(pts)
        mx, my = sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n
        var = sum((p[0] - mx) ** 2 for p in pts)
        slope = round(100_000 * sum((p[0] - mx) * (p[1] - my) for p in pts) / var, 2) if var else None
    # ---- 500 vs 700 boards: one-time admission growth kept apart from steady-state growth (linear in boards: an ASSUMPTION)
    projection: dict[str, Any] = {}
    nb = len(monitored)
    for target in sorted({nb, nb + min(200, len(waiting))}):  # today's size, and +200 (fewer when fewer relevant boards wait)
        if not nb or ops_day is None or ident_day is None:
            break
        scale = target / nb
        adm_rows = 0 if target == nb else sum(max(0, b.last_job_count) for b in waiting[: target - nb])
        ops_r, ident_r = ops_day * scale, ident_day * scale
        rows_now = total + adm_rows
        projection[str(target)] = {
            "boards": target, "one_time_admission_rows": adm_rows, "ledger_rows_after_admission": rows_now,
            "steady_rows_per_day_now": round(ops_r + ident_r), "steady_cells_per_day_now": round((ops_r + ident_r) * EVENT_COLUMNS),
            "days_until_200k_rows_now": round((200_000 - rows_now) / (ops_r + ident_r)) if rows_now < 200_000 else 0,
            "days_until_10M_cells_now": round((SHEET_CELL_LIMIT - rows_now * EVENT_COLUMNS) / ((ops_r + ident_r) * EVENT_COLUMNS)),
            "steady_cells_per_day_compact": round(ops_r * EVENT_COLUMNS + 20 * 6),  # operational rows stay as they are; identity-only becomes ID chunks plus ~20 daily counter rows
            "cells_after_admission_compact": round(operational_cells + compact_cells_now + (target - nb) * COMPACT_COLUMNS),
        }  # fmt: skip
    pending = [s for s in lg.replay(events).values() if lg.needs_evaluation(s) or lg.needs_alert(s, now)]
    return {
        "events_total": total, "cells_now": total * EVENT_COLUMNS, "chars_now": total_chars, "by_type": dict(by_type), "seen_by_disposition": dict(seen_disp),
        "by_purpose": {k: {"rows": kinds[k], "share_pct": round(100 * kinds[k] / total, 1) if total else None, "chars": chars[k],
                           "mean_chars_per_row": round(chars[k] / kinds[k]) if kinds[k] else None} for k in ("baseline", "identity", "operational")},
        "per_day": {d: dict(per_day[d]) for d in days[-10:]},
        "steady_state_rows_per_day": {"days_used": full_days, "operational_median": ops_day, "identity_only_median": ident_day, "baseline_median": statistics.median(base_per_day) if base_per_day else None},
        "monitored_boards": len(monitored), "boards_with_baseline_rows": boards_with_baseline,
        "baseline_rows_per_board": {"mean": round(avg_rows, 1) if avg_rows else None, "median": per_board[len(per_board) // 2] if per_board else None, "p90": per_board[int(0.9 * len(per_board))] if per_board else None, "max": per_board[-1] if per_board else None},
        "operational_rows_per_day_per_monitored_board": round(ops_day / n_mon, 3) if ops_day is not None else None,
        "identity_only_rows_per_day_per_monitored_board": round(ident_day / n_mon, 3) if ident_day is not None else None,
        "admission_projection": admission,
        "waiting_boards": len(waiting), "validated_total": sum(1 for b in boards.values() if b.status == STATUS_VALIDATED),
        "compact_baseline": {"rows_if_one_row_per_board_chunk": compact_rows, "cells": compact_rows * COMPACT_COLUMNS, "id_chars": id_chars,
                             "cells_saved_vs_now": kinds["baseline"] * EVENT_COLUMNS - compact_rows * COMPACT_COLUMNS,
                             "max_ids_chars_for_one_board": max(baseline_id_chars.values(), default=0),
                             "mean_id_chars": round(id_chars / max(1, sum(baseline_by_board.values())), 1)},
        "pending_must_be_preserved": len(pending),
        "load_seconds_per_100k_ledger_rows": slope, "load_seconds_by_ledger_size": load_by_size,
        "projection": projection,
        "ledger_rows_logged_in_runs": (runs[0].events_rows, runs[-1].events_rows) if runs else None,
        **({"logical": logical_counts(ledger.events, folded=ledger.folded(), identity=ledger.identity)} if ledger is not None else {}),
    }  # fmt: skip


def format_report(a: dict[str, Any]) -> str:
    p = a["by_purpose"]
    L = [
        "STORAGE REPORT (read only; nothing was pruned, compacted, archived or migrated)",
        "",
        f"EVENTS LEDGER NOW: {a['events_total']:,} rows = {a['cells_now']:,} cells ({100 * a['cells_now'] / SHEET_CELL_LIMIT:.1f}% of the {SHEET_CELL_LIMIT:,}-cell spreadsheet limit), {a['chars_now']:,} characters",
        "  by event type: " + ", ".join(f"{k} {v:,}" for k, v in sorted(a["by_type"].items(), key=lambda kv: -kv[1])),
        "  `seen` rows by disposition: " + ", ".join(f"{k or '?'} {v:,}" for k, v in sorted(a["seen_by_disposition"].items(), key=lambda kv: -kv[1])),
        "",
        "WHAT THE ROWS ARE FOR",
    ]
    for k, label in (("baseline", "baseline identities (a board's existing postings, recorded at its first read)"), ("identity", "other identity-only rows (title-gated or stale postings: dedupe, never evaluated)"), ("operational", "operational (pipeline jobs and every evaluated / alerted / error / update event)")):
        L.append(f"  {p[k]['rows']:>9,} rows {p[k]['share_pct']}%  {label}; mean {p[k]['mean_chars_per_row']} characters per row")
    s = a["steady_state_rows_per_day"]
    L += [
        "",
        f"STEADY-STATE GROWTH (median of complete days {', '.join(s['days_used']) or 'none'})",
        f"  operational {s['operational_median']} rows/day, identity-only {s['identity_only_median']} rows/day, baseline {s['baseline_median']} rows/day (the baseline figure reflects admissions, not steady state)",
        f"  per monitored board per day ({a['monitored_boards']} monitored): operational {a['operational_rows_per_day_per_monitored_board']}, identity-only {a['identity_only_rows_per_day_per_monitored_board']}",
        f"  baseline rows per board that has them ({a['boards_with_baseline_rows']} boards): {a['baseline_rows_per_board']}",
        "",
        f"INITIAL ADMISSION GROWTH OF ADDING BOARDS ({a['waiting_boards']} relevant boards wait; sized from their last known job counts, in admission order). One time per board, not per day.",
    ]
    for k, v in a["admission_projection"].items():
        L.append(f"  +{v['boards_added']} boards: ~{v['baseline_rows_one_time']:,} baseline rows ({v['mean_jobs_per_board']} per board) = {v['cells_one_time_now']:,} cells now; compact design ~{v['compact_cells_one_time']:,} cells")
    c = a["compact_baseline"]
    L += [
        "",
        f"COMPACT BASELINE (one row per board per {COMPACT_CELL_CHARS:,}-character chunk of posting IDs): {c['rows_if_one_row_per_board_chunk']:,} rows = {c['cells']:,} cells for today's baselines "
        f"(saves {c['cells_saved_vs_now']:,} cells); the largest single board needs {c['max_ids_chars_for_one_board']:,} characters of IDs (cell limit {CELL_CHAR_LIMIT:,})",
        f"MUST BE PRESERVED: {a['pending_must_be_preserved']} jobs currently awaiting evaluation or alert delivery",
    ]
    if "logical" in a:
        g = a["logical"]
        p_ = g["jobs_by_purpose"]
        L.append(
            f"JOBS RECORDED (Events rows plus Identity and Tally): {sum(p_.values()):,} first-seen jobs = {p_['baseline']:,} baseline + {p_['identity']:,} title-gated or stale + {p_['operational']:,} operational; "
            f"baselines on {g['boards_with_baselines']:,} boards; {g['must_be_preserved']:,} jobs awaiting evaluation or alert"
        )
    L += [
        "LOAD TIME (Runs.Load_S, whole seconds, includes the ~22k-row Boards registry): " + (
            "; ".join(f"{k}: {v['median_load_s']} s at {v['ledger_rows']} rows ({v['runs']} runs)" for k, v in a["load_seconds_by_ledger_size"].items()) or "not enough runs with ledger sizes")
        + (f"; fitted slope {a['load_seconds_per_100k_ledger_rows']} s per 100,000 rows" if a["load_seconds_per_100k_ledger_rows"] is not None else "; no per-row slope is measurable yet"),
        "",
        "500 vs 700 BOARDS (steady state scales linearly with monitored boards: an assumption; one-time admission is sized from the waiting boards' last job counts)",
    ]
    for k, v in a["projection"].items():
        L.append(
            f"  {v['boards']} boards: one-time admission {v['one_time_admission_rows']:,} rows -> ledger {v['ledger_rows_after_admission']:,} rows; steady growth now ~{v['steady_rows_per_day_now']:,} rows "
            f"({v['steady_cells_per_day_now']:,} cells) a day -> 200k rows in ~{v['days_until_200k_rows_now']} days, 10M cells in ~{v['days_until_10M_cells_now']} days; "
            f"compact design: ~{v['steady_cells_per_day_compact']:,} cells a day, {v['cells_after_admission_compact']:,} cells total after admission"
        )
    return "\n".join(L)
