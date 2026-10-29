"""The storage report measures; it never changes anything. Offline."""

from __future__ import annotations

import contextlib
import io
import statistics
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import boards as bd  # noqa: E402
import compact  # noqa: E402
import freshness as fr  # noqa: E402
import hunter  # noqa: E402
import ledger as lg  # noqa: E402
import pilot  # noqa: E402
import reporting as rp  # noqa: E402
import state as st_mod  # noqa: E402
import storage_report as sr  # noqa: E402
from test_reporting import CHI, UTC, ZONES, compact_world  # noqa: E402

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


def ts(**kw: float) -> str:
    return (NOW - timedelta(**kw)).strftime("%Y-%m-%dT%H:%M:%SZ")


def seen(key: str, when: str, disp: str, **d: object) -> lg.Event:
    return lg.Event(when, key, lg.SEEN, fr.BASELINE if disp == lg.BASELINED else fr.VERIFIED_FRESH, disp, "", {"source": "poll", "title": "t" * 60, "url": "u" * 80, **d})


class ClassificationTests(unittest.TestCase):
    def test_every_row_has_exactly_one_purpose(self) -> None:
        self.assertEqual(sr.classify(seen("a|b|1", ts(days=2), lg.BASELINED)), "baseline")
        self.assertEqual(sr.classify(seen("a|b|2", ts(days=2), lg.FILTERED)), "identity")
        self.assertEqual(sr.classify(seen("a|b|3", ts(days=2), lg.STALED)), "identity")
        self.assertEqual(sr.classify(seen("a|b|4", ts(days=2), lg.PENDING)), "operational")
        for kind in (lg.EVALUATED, lg.ALERTED, lg.ERROR, lg.ABANDONED, lg.UPDATED, lg.REPUBLISHED):
            self.assertEqual(sr.classify(lg.Event(ts(days=1), "a|b|4", kind)), "operational")


class AnalyzeTests(unittest.TestCase):
    def build_world(self) -> tuple:
        ev: list[lg.Event] = []
        for b in range(3):  # three boards baselined two days ago, 40 postings each
            ev += [seen(f"greenhouse|co{b}|{i:06d}", ts(days=2), lg.BASELINED) for i in range(40)]
        for d in (1, 2, 3):  # three complete days of steady state
            ev += [seen(f"greenhouse|co0|n{d}{i}", ts(days=d, hours=-1), lg.FILTERED) for i in range(10)]
            ev += [seen(f"greenhouse|co0|p{d}", ts(days=d, hours=-1), lg.PENDING), lg.Event(ts(days=d, hours=-2), f"greenhouse|co0|p{d}", lg.EVALUATED, detail={"status": "To Apply", "alert": False})]
        ev.append(seen("greenhouse|co0|pending", ts(hours=3), lg.PENDING))  # awaiting evaluation: must be preserved
        recs = {}
        for i in range(3):
            b = bd.BoardRecord(bd.GREENHOUSE, f"co{i}", ts(days=3), "x", status="active")
            recs[b.key] = b
        for i in range(5):  # five relevant boards waiting, 100 jobs each
            b = bd.BoardRecord(bd.GREENHOUSE, f"wait{i}", ts(days=3), "x", status="validated", validation=bd.V_VALID, relevant_jobs=2, last_job_count=100)
            recs[b.key] = b
        runs = [st_mod.RunRecord(ts(days=3 - i * 0.5), events_rows=1000 * (i + 1), load_s=2 + i, outcome="ok") for i in range(6)]
        return ev, recs, runs, NOW

    def build(self) -> dict:
        ev, recs, runs, now = self.build_world()
        return sr.analyze(ev, recs, runs, now, extra_boards=(2,))

    def test_baseline_identity_and_operational_rows_are_counted_apart(self) -> None:
        a = self.build()
        p = a["by_purpose"]
        self.assertEqual((p["baseline"]["rows"], p["identity"]["rows"], a["events_total"]), (120, 30, 120 + 30 + 6 + 1))
        self.assertEqual(a["by_type"]["evaluated"], 3)
        self.assertEqual(sum(v["rows"] for v in p.values()), a["events_total"])  # the three purposes partition the ledger
        self.assertEqual(a["cells_now"], a["events_total"] * 7)

    def test_steady_state_excludes_the_admission_burst(self) -> None:
        s = self.build()["steady_state_rows_per_day"]
        self.assertEqual((s["identity_only_median"], s["operational_median"]), (10, 2))  # per complete day; the baseline burst is reported separately
        self.assertEqual(s["baseline_median"], 0)
        self.assertEqual(self.build()["operational_rows_per_day_per_monitored_board"], round(2 / 3, 3))

    def test_admission_projection_uses_the_next_boards_known_job_counts(self) -> None:
        a = self.build()["admission_projection"]
        self.assertEqual(a["2"]["baseline_rows_one_time"], 200)
        self.assertEqual((a["5"]["boards_added"], a["5"]["baseline_rows_one_time"], a["5"]["cells_one_time_now"]), (5, 500, 3500))
        self.assertLess(a["5"]["compact_cells_one_time"], a["5"]["cells_one_time_now"])

    def test_compact_baseline_is_one_row_per_board_and_reports_the_cell_limit_risk(self) -> None:
        c = self.build()["compact_baseline"]
        self.assertEqual((c["rows_if_one_row_per_board_chunk"], c["cells"]), (3, 15))
        self.assertEqual(c["cells_saved_vs_now"], 120 * 7 - 15)

    def test_pending_work_is_counted_so_a_design_can_prove_it_keeps_it(self) -> None:
        self.assertEqual(self.build()["pending_must_be_preserved"], 1)

    def test_load_time_slope_comes_from_the_runs_log(self) -> None:
        a = self.build()
        self.assertIsNone(a["load_seconds_per_100k_ledger_rows"])  # a 5,000-row spread is too small to claim a per-row slope
        self.assertEqual(a["load_seconds_by_ledger_size"]["largest third"]["median_load_s"], 6.5)  # runs 5-6: loads of 6 s and 7 s

    def test_projection_separates_one_time_admission_from_steady_state(self) -> None:
        p = self.build()["projection"]
        self.assertEqual(sorted(p), ["3", "8"])  # today's 3 monitored boards, and +200 capped by the 5 that actually wait
        self.assertEqual((p["3"]["one_time_admission_rows"], p["8"]["one_time_admission_rows"]), (0, 500))
        self.assertEqual(p["8"]["ledger_rows_after_admission"], p["3"]["ledger_rows_after_admission"] + 500)
        self.assertEqual(p["8"]["steady_rows_per_day_now"], round(12 * 8 / 3))  # 10 identity-only + 2 operational rows a day at 3 boards, scaled to 8
        self.assertLess(p["8"]["steady_cells_per_day_compact"], p["8"]["steady_cells_per_day_now"])


    def test_the_report_text_names_its_assumptions_and_changes_nothing(self) -> None:
        text = sr.format_report(self.build())
        for needle in ("read only", "INITIAL ADMISSION GROWTH", "One time per board", "STEADY-STATE GROWTH", "MUST BE PRESERVED", "COMPACT BASELINE"):
            self.assertIn(needle, text)

    def test_an_empty_ledger_does_not_divide_by_zero(self) -> None:
        a = sr.analyze([], {}, [], NOW)
        self.assertEqual((a["events_total"], a["pending_must_be_preserved"]), (0, 0))
        sr.format_report(a)


GRID = {"Events": (200_001, 7), "Identity": (600, 5), "Tally": (500, 4), "Runs": (2000, 77), "Events_Legacy": (10, 7)}
TABS_HEADER = "TABS (allocated grid cells; the 10,000,000-cell limit counts every tab, blank cells included)"


def run_row(day: str, hour: int, events_rows: int, load_s: int = 5, outcome: str = st_mod.OUTCOME_OK, kind: str = st_mod.KIND_PRODUCTION) -> st_mod.RunRecord:
    return st_mod.RunRecord(f"{day}T{hour:02d}:00:00Z", events_rows=events_rows, load_s=load_s, outcome=outcome, run_kind=kind)


class AllocatedCellsTests(unittest.TestCase):
    """SC3: rows and ALLOCATED grid cells per tab, from the sheet metadata (blank cells count toward the 10,000,000-cell limit)."""

    def test_each_tab_reports_its_rows_columns_and_allocated_cells_and_the_total_with_its_share_of_the_limit(self) -> None:
        a = sr.analyze([], {}, [], NOW, grid=GRID)
        self.assertEqual(a["tabs"]["Events"], {"rows": 200_001, "columns": 7, "cells": 1_400_007})
        self.assertEqual(a["tabs"]["Identity"], {"rows": 600, "columns": 5, "cells": 3000})
        self.assertEqual(a["tabs"]["Tally"], {"rows": 500, "columns": 4, "cells": 2000})
        self.assertEqual(a["tabs"]["Runs"]["cells"], 154_000)
        self.assertEqual(a["allocated_cells"], 1_400_007 + 3000 + 2000 + 154_000 + 70)
        self.assertEqual(a["allocated_share_pct"], 15.6)

    def test_the_text_lists_events_identity_tally_events_legacy_then_every_other_tab_and_the_total(self) -> None:
        text = sr.format_report(sr.analyze([], {}, [], NOW, grid=GRID))
        self.assertIn(TABS_HEADER, text)
        block = text.split(TABS_HEADER)[1].splitlines()[1:7]
        self.assertEqual([line.split()[0] for line in block[:5]], ["Events", "Identity", "Tally", "Events_Legacy", "Runs"])
        self.assertIn("1,400,007 cells", block[0])
        self.assertIn("total", block[5])
        self.assertIn("1,559,077", block[5])
        self.assertIn("15.6% of the 10,000,000-cell limit", block[5])

    def test_without_a_grid_the_report_has_no_tab_section_and_every_older_key_is_unchanged(self) -> None:
        a = sr.analyze([], {}, [], NOW)
        self.assertNotIn("tabs", a)
        self.assertNotIn("TABS (", sr.format_report(a))
        self.assertIn("EVENTS LEDGER NOW", sr.format_report(a))

    def test_the_median_load_is_over_the_last_24_completed_production_runs(self) -> None:
        runs = [run_row("2026-10-01", 0, 100, 500)]  # too old: outside the last 24
        runs += [run_row("2026-10-02", i % 24, 100, 10 + i) for i in range(24)]  # loads 10..33: median 21.5
        runs += [run_row("2026-10-03", 5, 100, 999, outcome=st_mod.OUTCOME_STARTED), run_row("2026-10-03", 6, 100, 999, kind=st_mod.KIND_REHEARSAL)]
        a = sr.analyze([], {}, runs, NOW, grid=GRID)
        self.assertEqual(a["load_s_median_last_24"], 21.5)
        self.assertIsNone(sr.analyze([], {}, [], NOW)["load_s_median_last_24"])

    def test_the_daily_growth_in_cells_is_seven_cells_per_events_row_over_complete_utc_days_and_none_until_two_days_exist(self) -> None:
        runs = [run_row("2026-10-15", 3, 1000), run_row("2026-10-16", 3, 1100), run_row("2026-10-16", 20, 1200), run_row("2026-10-17", 3, 1500), run_row("2026-10-18", 1, 99_999)]
        a = sr.analyze([], {}, runs, NOW, grid=GRID)  # 2026-10-18 is today: never counted. Growth: 10-16: +200, 10-17: +300 -> median 250 rows
        self.assertEqual(a["daily_growth_cells"], 250 * 7)
        self.assertIsNone(sr.analyze([], {}, runs[:1], NOW, grid=GRID)["daily_growth_cells"])  # one complete day is no growth figure
        self.assertEqual(sr.analyze([], {}, runs[:2], NOW, grid=GRID)["daily_growth_cells"], 100 * 7)  # two consecutive complete days are one
        self.assertIsNone(sr.analyze([], {}, [], NOW, grid=GRID)["daily_growth_cells"])


def compact_storage(first_fold: str | None, *, mode: str = compact.MODE_COMPACT) -> compact.StorageState:
    before = {
        "events_rows": 195_793, "grid": {"Events": [200_000, 7], "Identity": [1000, 5], "Tally": [1000, 4]}, "cells": {"Events": 1_400_000, "Identity": 5000, "Tally": 4000},
        "cells_total": 4_000_000, "median_load_s": 41.0, "median_daily_events_growth": 9489,
    }  # fmt: skip
    fold = {"first_day": first_fold, "last_day": "2026-10-25", "last_rows": 3, "last_skipped": 0, "rows_total": 30} if first_fold else {}
    return compact.StorageState(mode=mode, cutover={"at": "2026-10-18T09:00:00Z", "before": before}, fold=fold)


AFTER_NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
AFTER_GRID = {"Events": (39_100, 7), "Identity": (1014, 5), "Tally": (1070, 4), "Events_Legacy": (200_000, 7)}  # Identity +14 rows, Tally +70 rows since the cutover


def after_runs() -> list[st_mod.RunRecord]:
    runs = [run_row("2026-10-16", 20, 195_000, 40), run_row("2026-10-17", 20, 200_000, 41)]  # dual: 5,000 rows a day
    runs += [run_row("2026-10-18", 8, 200_500, 41), run_row("2026-10-18", 22, 41_000, 12)]  # the cutover day: the ledger shrinks
    runs += [run_row("2026-10-19", 3, 41_100, 12), run_row("2026-10-19", 22, 38_000, 11)]  # the first fold day: it deletes rows
    for day, last in (("20", 38_200), ("21", 38_500), ("22", 38_650), ("23", 38_900), ("24", 39_000), ("25", 39_100)):
        runs.append(run_row(f"2026-10-{day}", 22, last, 10))
    runs.append(run_row("2026-10-26", 1, 39_150, 10))  # today: incomplete, never counted
    return runs


class BeforeAfterTests(unittest.TestCase):
    """The BEFORE / AFTER section: the cutover's `before` snapshot beside what is measured now (P3-06, SC3)."""

    def analysis(self, storage: compact.StorageState | None, runs: list[st_mod.RunRecord] | None = None) -> dict:
        return sr.analyze([], {}, after_runs() if runs is None else runs, AFTER_NOW, grid=AFTER_GRID, storage=storage)

    def test_after_the_first_fold_both_sides_are_printed_and_only_days_after_the_first_fold_count_for_growth(self) -> None:
        a = self.analysis(compact_storage("2026-10-19"))
        ba = a["before_after"]
        self.assertEqual(ba["mode"], "compact")
        self.assertEqual(ba["after"]["days_used"], [f"2026-10-{d}" for d in range(20, 26)])  # 10-19 (the fold day) and everything earlier are not used
        # growth in rows over 10-20..10-25: 200, 300, 150, 250, 100, 100 -> median 175 rows = 1,225 cells; plus Identity and Tally: (14 x 5 + 70 x 4) cells over the 7 complete days since the cutover day = 50 a day
        self.assertEqual(ba["after"]["daily_growth_cells"], 175 * 7 + 50)
        self.assertEqual(a["daily_growth_cells"], 175 * 7 + 50)
        self.assertEqual(ba["before"]["daily_growth_cells"], 9489 * 7)
        self.assertEqual((ba["before"]["events_rows"], ba["after"]["events_rows"]), (195_793, 0))  # analyze() was given no Events rows; the report passes them
        self.assertEqual(ba["after"]["median_load_s"], 10)  # only runs started at or after the cutover
        self.assertEqual(ba["before"]["median_load_s"], 41.0)
        self.assertTrue(ba["measured"])
        self.assertAlmostEqual(ba["growth_ratio"], 9489 * 7 / (175 * 7 + 50), places=1)

    def test_the_text_prints_the_section_with_before_and_after_figures(self) -> None:
        text = sr.format_report(self.analysis(compact_storage("2026-10-19")))
        self.assertEqual(text.count("BEFORE / AFTER THE CUTOVER"), 1)
        section = text.split("BEFORE / AFTER THE CUTOVER")[1]
        self.assertIn("66,423", section)  # 9,489 rows x 7 cells a day before
        self.assertIn("1,275", section)  # measured after the first fold
        self.assertIn("41.0 s", section)
        self.assertIn("2026-10-20", section)
        self.assertIn("2026-10-25", section)
        self.assertNotIn("projection while dual writing", text)

    def test_between_the_cutover_and_the_first_fold_the_growth_after_is_not_measured_yet(self) -> None:
        a = self.analysis(compact_storage(None))
        ba = a["before_after"]
        self.assertIsNone(ba["after"]["daily_growth_cells"])
        self.assertFalse(ba["measured"])
        self.assertIsNone(a["daily_growth_cells"])
        text = sr.format_report(a)
        self.assertIn("not measured yet", text.split("BEFORE / AFTER THE CUTOVER")[1])

    def test_the_first_fold_day_itself_and_the_days_before_it_never_enter_the_after_figure(self) -> None:
        a = self.analysis(compact_storage("2026-10-22"))  # a later first fold: only 10-23, 10-24 and 10-25 follow it
        self.assertEqual(a["before_after"]["after"]["days_used"], ["2026-10-23", "2026-10-24", "2026-10-25"])
        self.assertEqual(a["before_after"]["after"]["daily_growth_cells"], 100 * 7 + 50)  # growth 250, 100, 100 -> median 100 rows

    def test_in_dual_mode_the_compact_figure_is_a_labelled_projection_and_no_before_after_is_printed(self) -> None:
        build = AnalyzeTests().build()
        text = sr.format_report(sr.analyze([], {}, [], NOW, grid=GRID, storage=compact.StorageState(mode=compact.MODE_DUAL)))
        self.assertIn("COMPACT STORAGE (projection while dual writing; not measured)", text)
        self.assertNotIn("BEFORE / AFTER THE CUTOVER", text)
        self.assertEqual(build["projection"]["3"]["steady_cells_per_day_compact"], 14 + 120)  # the projection exists in the analysis; the section prints it
        world = AnalyzeTests().build_world()
        a = sr.analyze(*world, grid=GRID, storage=compact.StorageState(mode=compact.MODE_DUAL))
        self.assertEqual(a["before_after"]["mode"], "dual")
        self.assertEqual(a["before_after"]["projection"]["steady_cells_per_day_compact"], build["projection"]["3"]["steady_cells_per_day_compact"])
        self.assertIn("not measured", sr.format_report(a).split("COMPACT STORAGE")[1])

    def test_a_restored_state_says_compaction_is_off_and_prints_no_after_figure(self) -> None:
        text = sr.format_report(self.analysis(compact_storage("2026-10-19", mode=compact.MODE_RESTORED)))
        self.assertIn("restored", text.split("COMPACT STORAGE")[1].splitlines()[0])
        self.assertNotIn("BEFORE / AFTER THE CUTOVER", text)

    def test_a_before_snapshot_with_missing_figures_prints_n_a_and_never_zero(self) -> None:
        storage = compact_storage("2026-10-19")
        storage.cutover["before"] = {"events_rows": 10, "cells_total": 0, "median_load_s": None, "median_daily_events_growth": None}
        text = sr.format_report(self.analysis(storage))
        self.assertIn("n/a", text.split("BEFORE / AFTER THE CUTOVER")[1])
        self.assertIsNone(self.analysis(storage)["before_after"]["growth_ratio"])


def _ev(when: datetime, key: str, disposition: str, run: str) -> lg.Event:
    published = ""
    freshness = {lg.BASELINED: fr.BASELINE, lg.STALED: fr.STALE}.get(disposition, fr.RECENT)
    detail: dict[str, object] = {"source": "poll", "run": run}
    if disposition == lg.BASELINED:
        detail["pass"] = "baseline"
    return lg.Event(lg.stamp(when), key, lg.SEEN, freshness, disposition, published, detail)


class GrowthSimulationTests(unittest.TestCase):
    """SC3 offline: 28 days at 700 monitored boards through the REAL `split_observations`, `retained_events` and `fold_plan`, counting allocated cells.

    D-43's rates scaled to 700 boards: 0.328 operational rows and 7.17 title-gated or stale rows per board a day, about 146 baseline rows per admitted
    board, 24 runs a day. The cutover is at the start of day 14 and every day from 15 starts with a fold. MOCKED: it is a model of the ledger, not a measurement."""

    BOARDS, DAYS, CUTOVER_DAY, RUNS_PER_DAY = 700, 28, 14, 24
    OPS_PER_DAY = round(164 / 500 * 700)  # 230
    GATED_PER_DAY = round(7.17 * 700)  # 5,019
    WAVE_DAY, WAVE_BOARDS, WAVE_ROWS_PER_BOARD = 3, 140, 146
    START = datetime(2026, 9, 1, tzinfo=timezone.utc)

    @classmethod
    def runs_of(cls, day: int) -> list[list[lg.Event]]:
        """The events of each run of simulated day `day` (1-based): gated rows, operational rows and, on the wave day, the baselines of the admitted boards."""
        out: list[list[lg.Event]] = []
        for r in range(cls.RUNS_PER_DAY):
            when = cls.START + timedelta(days=day - 1, hours=r, minutes=5)
            run = f"d{day}r{r}"
            events: list[lg.Event] = []
            lo, hi = (cls.GATED_PER_DAY * r) // cls.RUNS_PER_DAY, (cls.GATED_PER_DAY * (r + 1)) // cls.RUNS_PER_DAY
            for i in range(lo, hi):
                events.append(_ev(when, f"greenhouse|b{i % cls.BOARDS:03d}|g{day}-{i}", lg.STALED if i % 5 == 0 else lg.FILTERED, run))
            lo, hi = (cls.OPS_PER_DAY * r) // cls.RUNS_PER_DAY, (cls.OPS_PER_DAY * (r + 1)) // cls.RUNS_PER_DAY
            events += [lg.Event(lg.stamp(when), f"greenhouse|b{i % cls.BOARDS:03d}|o{day}-{i}", lg.EVALUATED, fr.VERIFIED_FRESH, detail={"run": run}) for i in range(lo, hi)]
            if r == 0 and day == 1:  # the boards that were already monitored before the simulation start: a short baseline each
                events += [_ev(when, f"greenhouse|b{b:03d}|base{k}", lg.BASELINED, run) for b in range(cls.BOARDS - cls.WAVE_BOARDS) for k in range(20)]
            if r == 6 and day == cls.WAVE_DAY:  # the admission wave of week 1
                first = cls.BOARDS - cls.WAVE_BOARDS
                events += [_ev(when, f"greenhouse|b{b:03d}|wave{k}", lg.BASELINED, run) for b in range(first, cls.BOARDS) for k in range(cls.WAVE_ROWS_PER_BOARD)]
            out.append(events)
        return out

    @classmethod
    def simulate(cls, cutover_day: int | None) -> dict[str, list]:
        """Allocated cells of Events, Identity and Tally at the end of each day, and what the compact world still holds at the end."""
        events: list[lg.Event] = []
        identity = compact.IdentitySet()
        tally: list[compact.TallyRow] = []
        mode = compact.MODE_DUAL
        cells: list[int] = []
        folded_rows = 0
        for day in range(1, cls.DAYS + 1):
            now = cls.START + timedelta(days=day - 1)
            if cutover_day is not None and day == cutover_day:
                ledger = compact.Ledger(events, list(range(2, len(events) + 2)), identity, tally)
                events = compact.retained_events(ledger, now)
                mode = compact.MODE_COMPACT
            elif cutover_day is not None and day > cutover_day:
                plan = compact.fold_plan(compact.Ledger(events, list(range(2, len(events) + 2)), identity, tally), now)
                gone = set(plan.rows)
                events = [ev for n, ev in zip(range(2, len(events) + 2), events) if n not in gone]
                folded_rows += len(gone)
            additions: dict[str, list[str]] = {}
            for r, run_events in enumerate(cls.runs_of(day)):
                split = compact.split_observations(run_events, mode)
                events += split.events
                for stem, entries in split.identity.items():
                    additions.setdefault(stem, []).extend(entries)
                stamp = lg.stamp(cls.START + timedelta(days=day - 1, hours=r, minutes=5))
                tally.append(compact.TallyRow(f"d{day}r{r}", stamp, sum(split.tally.values()), dict(sorted(split.tally.items()))))
            identity.apply(identity.plan_additions(additions, lg.stamp(now)))
            cells.append(len(events) * 7 + len(identity.all_rows()) * 5 + len(tally) * 4)
        return {"cells": cells, "events": events, "folded_rows": [folded_rows], "identity": identity, "tally": tally}

    @classmethod
    def setUpClass(cls) -> None:
        cls.dual = cls.simulate(None)
        cls.compact = cls.simulate(cls.CUTOVER_DAY)

    @staticmethod
    def growth(cells: list[int], first_day: int, last_day: int) -> float:
        return statistics.median(cells[d - 1] - cells[d - 2] for d in range(first_day, last_day + 1))

    def test_the_median_daily_growth_in_allocated_cells_after_the_first_folds_is_at_least_ten_times_smaller_than_with_every_row_kept(self) -> None:
        dual, compacted = self.growth(self.dual["cells"], 22, 28), self.growth(self.compact["cells"], 22, 28)
        self.assertGreater(dual, 25_000)  # D-43: about 26,200 cells a day at 500 boards, more at 700
        self.assertLess(compacted, 4_000)  # D-43: about 1,300 cells a day at 500 boards
        self.assertGreaterEqual(dual / compacted, 10)

    def test_the_admission_wave_is_a_one_time_jump_in_dual_mode_and_leaves_events_at_the_cutover(self) -> None:
        wave = self.dual["cells"][self.WAVE_DAY - 1] - self.dual["cells"][self.WAVE_DAY - 2]
        self.assertGreater(wave, self.WAVE_BOARDS * self.WAVE_ROWS_PER_BOARD * 7)
        events = self.compact["events"]
        self.assertFalse([e for e in events if e.event == lg.SEEN and e.disposition == lg.BASELINED])  # no baseline row is in Events after the cutover (P3-02)
        self.assertEqual(sum(1 for e in self.dual["events"] if e.disposition == lg.BASELINED), 560 * 20 + self.WAVE_BOARDS * self.WAVE_ROWS_PER_BOARD)

    def test_the_fold_keeps_one_week_of_gated_rows_and_every_operational_row(self) -> None:
        events, last = self.compact["events"], self.START + timedelta(days=self.DAYS)
        gated = [e for e in events if compact.identity_class(e)]
        oldest = min(compact.event_time(e) for e in gated)
        self.assertGreater(oldest, last - compact.FOLD_AGE - timedelta(days=1))  # at most about 7 days of title-gated and stale rows
        self.assertLessEqual(len(gated), 8 * self.GATED_PER_DAY)  # the fold runs at the start of a day: up to 8 days of rows are present at its end
        self.assertEqual(sum(1 for e in events if not compact.identity_class(e)), sum(1 for e in self.dual["events"] if not compact.identity_class(e)))  # nothing operational was folded
        self.assertGreater(self.compact["folded_rows"][0], 5 * self.GATED_PER_DAY)

    def test_identity_and_tally_hold_the_same_ids_and_counts_in_both_worlds(self) -> None:
        self.assertEqual(self.compact["identity"].keys(), self.dual["identity"].keys())
        total = lambda world: sum(t.total for t in world["tally"])  # noqa: E731
        self.assertEqual(total(self.compact), total(self.dual))


PURPOSE_OF = {lg.BASELINED: "baseline", lg.FILTERED: "identity", lg.STALED: "identity"}


class ClassifyDelegationTests(unittest.TestCase):
    def test_classify_follows_the_one_definition_of_identity_class_in_compact(self) -> None:
        events = compact_world(UTC, ZONES[0][1]).events
        self.assertGreater(len(events), 1000)
        for ev in events:
            expected = PURPOSE_OF[compact.identity_class(ev)] if compact.identity_class(ev) else "operational"
            self.assertEqual(sr.classify(ev), expected, ev.key)
        self.assertEqual(sr.COMPACT_CELL_CHARS, compact.IDENTITY_CELL_CHARS)

    def test_classify_asks_compact_for_the_identity_class_instead_of_deciding_itself(self) -> None:
        ev = seen("a|b|1", ts(days=2), lg.BASELINED)
        with mock.patch.object(compact, "identity_class", return_value=lg.FILTERED):
            self.assertEqual(sr.classify(ev), "identity")  # one definition of identity-class (D-57): change it there and the report follows
        with mock.patch.object(compact, "identity_class", return_value=None):
            self.assertEqual(sr.classify(ev), "operational")


class LogicalCountsTests(unittest.TestCase):
    """The counts that must be the same whether the identity-only rows are Events rows or Identity entries and Tally counts."""

    def pair(self, tz: object, now: datetime, half: bool = False) -> tuple[dict, dict]:
        world = compact_world(tz, now)
        view = world.half_folded_view() if half else world.compact_view(now)
        return sr.logical_counts(world.events), sr.logical_counts(view.events, folded=view.folded(), identity=view.identity)

    def test_the_merged_view_has_the_same_logical_counts_as_all_rows(self) -> None:
        for tz, now in ZONES:
            for half in (False, True):
                with self.subTest(tz=str(tz), half=half):
                    old, new = self.pair(tz, now, half)
                    self.assertEqual(old, new)

    def test_counts_by_purpose_disposition_day_and_board(self) -> None:
        old, _ = self.pair(UTC, ZONES[0][1])
        self.assertEqual(old["jobs_by_purpose"]["baseline"], 25 + 6 + 80 + 12 + 10)  # legacy, the early lever wave, the main wave, the re-entry pass, the rehearsal run
        self.assertEqual(old["jobs_by_disposition"][lg.FILTERED], 5 + 124 * 8 + 4)
        self.assertEqual(old["jobs_by_disposition"][lg.STALED], 124 * 3)
        self.assertEqual(sum(old["jobs_by_purpose"].values()), sum(old["jobs_by_disposition"].values()))
        self.assertEqual(old["baseline_jobs_per_board"]["greenhouse|newco"], 60)
        self.assertEqual(old["boards_with_baselines"], len(old["baseline_jobs_per_board"]))
        self.assertEqual(old["jobs_per_day_by_purpose"]["2026-10-09"]["baseline"], 80)  # the wave's UTC day: the run that started at 00:00:00 belongs to the new day
        self.assertEqual(sum(sum(v.values()) for v in old["jobs_per_day_by_purpose"].values()), sum(old["jobs_by_purpose"].values()))

    def test_a_duplicate_seen_row_changes_neither_sides_job_counts(self) -> None:
        for tz, now in ZONES[:1]:
            world = compact_world(tz, now)
            dup_baseline = next(e for e in world.events if e.key == "greenhouse|newco|W3" and e.event == lg.SEEN)
            dup_pending = next(e for e in world.events if e.key == "greenhouse|acme|p3-1-0" and e.event == lg.SEEN)
            events = sorted([*world.events, lg.Event("2026-10-28T10:00:00Z", dup_baseline.key, lg.SEEN, fr.RECENT, lg.FILTERED, "", {"source": "poll"}),
                             lg.Event("2026-10-28T10:00:00Z", dup_pending.key, lg.SEEN, fr.RECENT, lg.FILTERED, "", {"source": "poll"})], key=lambda e: e.time)
            view = compact.Ledger(compact.simulate_compact(events, now), [], world.identity, world.tally)
            clean = sr.logical_counts(world.events)
            self.assertEqual(sr.logical_counts(events), clean)
            self.assertEqual(sr.logical_counts(view.events, folded=view.folded(), identity=view.identity), clean)

    def test_work_that_must_be_preserved_is_counted_from_the_operational_rows(self) -> None:
        old, new = self.pair(UTC, ZONES[0][1])
        self.assertGreater(old["must_be_preserved"], 0)  # the 29 October jobs are still waiting for evaluation
        self.assertEqual(old["must_be_preserved"], new["must_be_preserved"])

    def test_baselines_per_board_come_from_identity_when_the_rows_are_gone(self) -> None:
        now = ZONES[0][1]
        world = compact_world(UTC, now)
        view = world.compact_view(now)
        self.assertFalse([e for e in view.events if e.disposition == lg.BASELINED])  # no baseline rows are left in Events
        new = sr.logical_counts(view.events, folded=view.folded(), identity=view.identity)
        self.assertEqual(new["baseline_jobs_per_board"]["ashby|newco2"], 20)
        without = sr.logical_counts(view.events, folded=view.folded())
        self.assertEqual(without["baseline_jobs_per_board"], {})  # the Events baseline rows are the only source when no Identity is given

    def test_analyze_reports_the_logical_counts_only_when_given_a_ledger(self) -> None:
        now = ZONES[0][1]
        world = compact_world(UTC, now)
        view = world.compact_view(now)
        plain = sr.analyze(view.events, {}, world.runs, now)
        self.assertNotIn("logical", plain)
        merged = sr.analyze(view.events, {}, world.runs, now, ledger=view)
        self.assertEqual(merged["logical"], sr.logical_counts(world.events))
        text = sr.format_report(merged)
        self.assertEqual(sum(1 for line in text.splitlines() if line.startswith("JOBS RECORDED (Events rows plus Identity and Tally)")), 1)
        self.assertNotIn("JOBS RECORDED", sr.format_report(plain))


class ReconcileParityTests(unittest.TestCase):
    """The pilot report's funnel is the same whether the baseline and old gated rows are Events rows or Tally counts."""

    def test_reconcile_gives_every_figure_for_a_seven_day_and_an_all_time_window(self) -> None:
        for tz, now in ZONES:
            world = compact_world(tz, now)
            for label, view in (("simulated", world.compact_view(now)), ("half folded", world.half_folded_view())):
                for start in (now - timedelta(days=7), datetime(2020, 1, 1, tzinfo=timezone.utc)):
                    with self.subTest(tz=str(tz), view=label, start=start.isoformat()):
                        old = rp.reconcile(runs=world.runs, events=world.events, tracker=[], start=start, end=now)
                        new = rp.reconcile(runs=world.runs, events=view.events, tracker=[], start=start, end=now, folded=view.folded())
                        self.assertEqual({k: v for k, v in old.items() if k != "from_tally"}, {k: v for k, v in new.items() if k != "from_tally"})  # from_tally only drives the P3-11 note
                        self.assertEqual(old["jobs_first_observed"]["total"], new["jobs_first_observed"]["total"])
                        self.assertEqual(old["from_tally"], 0)
                        self.assertEqual(new["from_tally"] > 0, bool(view.folded()) and start.year == 2020)

    def test_the_all_time_window_counts_baselines_gated_and_stale_from_the_tally(self) -> None:
        now = ZONES[0][1]
        world = compact_world(UTC, now)
        view = world.compact_view(now)
        j = rp.reconcile(runs=world.runs, events=view.events, tracker=[], start=datetime(2020, 1, 1, tzinfo=timezone.utc), end=now, folded=view.folded())["jobs_first_observed"]
        self.assertEqual(j["baseline_existing_postings"], 25 + 6 + 80 + 12)  # the rehearsal run's 10 are excluded
        self.assertEqual(j["stopped_by_title_gate"], 5 + 124 * 8)
        self.assertEqual(j["stale_at_observation"], 124 * 3)
        self.assertEqual(j["total"], j["baseline_existing_postings"] + j["new_postings"])

    def test_a_folded_count_outside_the_window_is_not_counted(self) -> None:
        now = ZONES[0][1]
        at = "2026-10-01T00:00:00Z"
        dim = "greenhouse|poll|filtered||recent|u"
        start = datetime(2026, 10, 2, tzinfo=timezone.utc)
        j = rp.reconcile(runs=[], events=[], tracker=[], start=start, end=now, folded=[compact.FoldedCount("x", at, dim, 4)])["jobs_first_observed"]
        self.assertEqual((j["total"], j["stopped_by_title_gate"]), (0, 0))
        j = rp.reconcile(runs=[], events=[], tracker=[], start=datetime(2026, 9, 30, tzinfo=timezone.utc), end=now, folded=[compact.FoldedCount("x", at, dim, 4)])["jobs_first_observed"]
        self.assertEqual((j["total"], j["stopped_by_title_gate"], j["new_postings"]), (4, 4, 4))

    def test_the_pilot_report_is_the_same_from_the_merged_view(self) -> None:
        for tz, now in ZONES:
            with self.subTest(tz=str(tz)):
                world = compact_world(tz, now)
                view = world.compact_view(now)
                kw = dict(now=now, days=7, runs=world.runs, boards={}, discovery={}, tracker=[], fresh_window=timedelta(hours=12), search_cap=1000, search_reserve=200)
                old = pilot.build_report(events=world.events, **kw)  # type: ignore[arg-type]
                new = pilot.build_report(events=view.events, folded=view.folded(), **kw)  # type: ignore[arg-type]
                self.assertEqual(old["reconciliation"], new["reconciliation"])
                self.assertEqual(old["detection_sample"], new["detection_sample"])  # latency samples read pending jobs only: unchanged
                self.assertEqual(old, new)


class CommandsReadTheMergedViewTests(unittest.TestCase):
    """`--pilot-report` and `--storage-report` load the merged ledger (Events plus Identity and Tally); only the rebalance report keeps reading pending jobs."""

    def store(self, ledger: compact.Ledger, runs: list, *, grid: dict | None = None, discovery: dict | None = None) -> types.SimpleNamespace:
        state = types.SimpleNamespace(
            load_ledger=lambda: ledger, load_runs=lambda: runs, load_boards=lambda: {}, load_discovery_state=lambda: discovery or {}, sheet_grid=lambda: grid or {},
        )  # fmt: skip
        return types.SimpleNamespace(state=state, tracker_rows=lambda: [])

    def run_command(self, name: str, ledger: compact.Ledger, world, now: datetime) -> str:
        settings = types.SimpleNamespace(fresh_window_hours=12, search_monthly_credits=1000, search_reserve_credits=200, max_active_boards=500, tracker_deleted_keys=())
        out = io.StringIO()
        with mock.patch.object(hunter.fr, "utcnow", return_value=now), contextlib.redirect_stdout(out):
            if name == "pilot":
                self.assertEqual(hunter.run_pilot_report(self.store(ledger, world.runs), settings, 7), 0)
            else:
                self.assertEqual(hunter.run_storage_report(self.store(ledger, world.runs)), 0)
        return out.getvalue()

    def test_the_pilot_report_prints_the_same_funnel_from_either_storage_mode(self) -> None:
        now = ZONES[0][1]
        world = compact_world(UTC, now)
        everything = compact.Ledger(world.events, [], compact.IdentitySet(), [])
        text_old = self.run_command("pilot", everything, world, now)
        text_new = self.run_command("pilot", world.compact_view(now), world, now)
        self.assertIn("JOBS FIRST OBSERVED IN THE WINDOW", text_new)
        self.assertEqual(text_old, text_new)

    def test_the_storage_report_command_passes_the_sheet_grid_and_the_storage_key(self) -> None:
        now = ZONES[0][1]
        world = compact_world(UTC, now)
        full = compact.Ledger(world.events, [], world.identity, world.tally)
        key = compact.StorageState(mode=compact.MODE_DUAL, seeded_at="2026-10-01T00:00:00Z").to_json()
        out = io.StringIO()
        with mock.patch.object(hunter.fr, "utcnow", return_value=now), contextlib.redirect_stdout(out):
            self.assertEqual(hunter.run_storage_report(self.store(full, world.runs, grid=GRID, discovery={compact.STORAGE_KEY: key})), 0)
        text = out.getvalue()
        self.assertIn(TABS_HEADER, text)
        self.assertIn("1,400,007 cells", text)
        self.assertIn("COMPACT STORAGE (projection while dual writing; not measured)", text)

    def test_an_unreadable_sheet_metadata_leaves_the_cell_sections_out_and_prints_the_rest(self) -> None:
        now = ZONES[0][1]
        world = compact_world(UTC, now)
        full = compact.Ledger(world.events, [], world.identity, world.tally)
        store = self.store(full, world.runs)

        def broken() -> dict:
            raise RuntimeError("metadata unavailable")

        store.state.sheet_grid = broken
        out = io.StringIO()
        with mock.patch.object(hunter.fr, "utcnow", return_value=now), contextlib.redirect_stdout(out), self.assertLogs("hunter", level="WARNING") as logs:
            self.assertEqual(hunter.run_storage_report(store), 0)
        self.assertNotIn("TABS (", out.getvalue())
        self.assertIn("JOBS RECORDED", out.getvalue())
        self.assertNotIn("metadata unavailable", "\n".join(logs.output))  # the exception type only

    def test_the_storage_report_prints_one_logical_line_that_does_not_depend_on_the_mode(self) -> None:
        now = ZONES[0][1]
        world = compact_world(UTC, now)
        full = compact.Ledger(world.events, [], world.identity, world.tally)  # dual mode: every row is still in Events, so nothing is folded
        self.assertEqual(full.folded(), [])
        lines = [next(line for line in self.run_command("storage", ledger, world, now).splitlines() if line.startswith("JOBS RECORDED")) for ledger in (full, world.compact_view(now))]
        self.assertEqual(lines[0], lines[1])


if __name__ == "__main__":
    unittest.main()
