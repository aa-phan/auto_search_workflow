"""The storage report measures; it never changes anything. Offline."""

from __future__ import annotations

import contextlib
import io
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

    def store(self, ledger: compact.Ledger, runs: list) -> types.SimpleNamespace:
        state = types.SimpleNamespace(load_ledger=lambda: ledger, load_runs=lambda: runs, load_boards=lambda: {}, load_discovery_state=lambda: {})
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

    def test_the_storage_report_prints_one_logical_line_that_does_not_depend_on_the_mode(self) -> None:
        now = ZONES[0][1]
        world = compact_world(UTC, now)
        full = compact.Ledger(world.events, [], world.identity, world.tally)  # dual mode: every row is still in Events, so nothing is folded
        self.assertEqual(full.folded(), [])
        lines = [next(line for line in self.run_command("storage", ledger, world, now).splitlines() if line.startswith("JOBS RECORDED")) for ledger in (full, world.compact_view(now))]
        self.assertEqual(lines[0], lines[1])


if __name__ == "__main__":
    unittest.main()
