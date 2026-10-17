"""The storage report measures; it never changes anything. Offline."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import boards as bd  # noqa: E402
import freshness as fr  # noqa: E402
import ledger as lg  # noqa: E402
import state as st_mod  # noqa: E402
import storage_report as sr  # noqa: E402

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
    def build(self) -> dict:
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
        return sr.analyze(ev, recs, runs, NOW, extra_boards=(2,))

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
        self.assertEqual(self.build()["load_seconds_per_100k_ledger_rows"], 100.0)  # 2 s at 1,000 rows -> 7 s at 6,000 rows

    def test_the_report_text_names_its_assumptions_and_changes_nothing(self) -> None:
        text = sr.format_report(self.build())
        for needle in ("read only", "INITIAL ADMISSION GROWTH", "One time per board", "STEADY-STATE GROWTH", "MUST BE PRESERVED", "COMPACT BASELINE"):
            self.assertIn(needle, text)

    def test_an_empty_ledger_does_not_divide_by_zero(self) -> None:
        a = sr.analyze([], {}, [], NOW)
        self.assertEqual((a["events_total"], a["pending_must_be_preserved"]), (0, 0))
        sr.format_report(a)


if __name__ == "__main__":
    unittest.main()
