"""Pilot instrumentation and the user's feedback column. Offline."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import boards as bd  # noqa: E402
import freshness as fr  # noqa: E402
import hunter as h  # noqa: E402
import ledger as lg  # noqa: E402
import pilot  # noqa: E402
import search  # noqa: E402
import state as st_mod  # noqa: E402
from test_hunter import FakeSpreadsheet, FakeWorksheet, sheet_store  # noqa: E402

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


def ts(**kw: float) -> str:
    return (NOW - timedelta(**kw)).strftime("%Y-%m-%dT%H:%M:%SZ")


def seen(key: str, when: str, source: str = "poll", fresh: str = fr.VERIFIED_FRESH, **detail: object) -> lg.Event:
    return lg.Event(when, key, lg.SEEN, fresh, lg.PENDING, when, {"source": source, "board": "acme", "precision": "time", **detail})


class FeedbackColumnTests(unittest.TestCase):
    def test_the_script_never_writes_the_feedback_cell(self) -> None:
        row = h.JobRow("To Apply", 80, "Acme", "Intern", "Remote", "v", "g", "https://u", "2026-10-21T10:00:00Z").cells()
        self.assertEqual(len(row), len(h.TRACKER_COLUMNS))
        self.assertEqual((h.TRACKER_COLUMNS[-1], row[-1]), ("My_Feedback", ""))
        self.assertEqual(h.FEEDBACK_CHOICES, ["Would apply", "Maybe", "Irrelevant"])

    def test_an_older_tracker_gets_only_the_header_cell_and_every_row_and_label_survives(self) -> None:
        old_header = h.TRACKER_COLUMNS[:-1]
        rows = [old_header, ["d", "p", "To Apply", 88, "Acme — Intern", "NYC", "v", "g", "https://boards.greenhouse.io/acme/jobs/1", "my note", "Verified fresh", "Board poll"]]
        tracker = FakeWorksheet("Job Tracker", [list(r) for r in rows])
        sheet_store(FakeSpreadsheet([FakeWorksheet("Settings", [["Setting", "Value", "Instructions"]]), tracker])).bootstrap("R")
        self.assertEqual(tracker.values[0], h.TRACKER_COLUMNS)
        self.assertEqual(tracker.values[1], rows[1])  # the data row is untouched
        again = FakeWorksheet("Job Tracker", [list(h.TRACKER_COLUMNS), rows[1] + ["Would apply"]])
        sheet_store(FakeSpreadsheet([FakeWorksheet("Settings", [["Setting", "Value", "Instructions"]]), again])).bootstrap("R")
        self.assertEqual(again.values[1][-1], "Would apply")  # a complete header is never rewritten; the user's label stays

    def test_the_tracker_creation_message_appears_only_when_the_tab_is_really_created(self) -> None:
        existing = FakeWorksheet("Job Tracker", [list(h.TRACKER_COLUMNS)])
        with self.assertNoLogs("hunter", level="INFO") as _:
            pass
        import logging

        with self.assertLogs("hunter", level="INFO") as made:
            sheet_store(FakeSpreadsheet([FakeWorksheet("Settings", [["Setting", "Value", "Instructions"]])])).bootstrap("R")
            logging.getLogger("hunter").info("sentinel")
        self.assertTrue(any("Created the Job Tracker tab" in m for m in made.output))
        with self.assertLogs("hunter", level="INFO") as kept:
            sheet_store(FakeSpreadsheet([FakeWorksheet("Settings", [["Setting", "Value", "Instructions"]]), existing])).bootstrap("R")
            logging.getLogger("hunter").info("sentinel")
        self.assertFalse(any("Created the Job Tracker tab" in m for m in kept.output))

    def test_csv_tracker_migration_keeps_existing_values_and_adds_the_column(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "t.csv"
            old = h.TRACKER_COLUMNS[:-1]
            path.write_text(",".join(old) + "\n" + ",".join(["x"] * len(old)) + "\n")
            store = h.CsvStore(path, Path(d) / "state")
            store.bootstrap("R")
            rows = store.tracker_rows()
            self.assertEqual((list(rows[0]), rows[0]["User_Notes"], rows[0]["My_Feedback"]), (h.TRACKER_COLUMNS, "x", ""))

    def test_sheet_store_reads_rows_for_the_report_without_writing(self) -> None:
        ws = FakeWorksheet("Job Tracker", [list(h.TRACKER_COLUMNS), ["a"] * 12 + ["Maybe"], ["b"] * 12])
        rows = sheet_store(FakeSpreadsheet([ws])).tracker_rows()
        self.assertEqual([r["My_Feedback"] for r in rows], ["Maybe", ""])
        self.assertEqual(ws.appended, [])


class ReportTests(unittest.TestCase):
    def build(self, **over):
        runs = [st_mod.RunRecord(ts(hours=i), discovery=(i % 12 == 0), boards_total=20, boards_ok=19, boards_failed=1, gap_since_prev_run_min=(60 if i != 5 else 200),
                                 max_board_gap_min=60, search_credits=(10 if i % 12 == 0 else 0), pool_established=2, pool_exploration=18, waiting_relevant=4,
                                 relevant_coverage_pct=83, alerts_failed=(1 if i == 3 else 0)) for i in range(48, 0, -1)]
        key = lambda n: f"greenhouse|acme|{n}"  # noqa: E731
        ev = [
            seen(key(1), ts(hours=30), age_min=40),
            seen(key(2), ts(hours=20), source="search", age_min=300),
            seen(key(3), ts(hours=10), source="poll", age_min=20, **{"pass": "baseline"}),
            lg.Event(ts(hours=30), key(1), lg.EVALUATED, fr.VERIFIED_FRESH, "", "", {"status": "To Apply", "alert": True}),
            lg.Event(ts(hours=29, minutes=30), key(1), lg.ALERTED, "", "", "", {"channel": "telegram", "lag_min": 70, "late": False}),
            lg.Event(ts(hours=19), key(2), lg.ALERTED, "", "", "", {"channel": "telegram", "lag_min": 800, "late": True}),
            lg.Event(ts(hours=18), key(2), lg.ALERTED, "", "", "", {"channel": "telegram", "lag_min": 900, "late": True}),
            lg.Event(ts(hours=9), key(4), lg.ERROR, "", "", "", {"stage": "evaluate", "message": "groq 429", "attempt": 1}),
            seen(key(4), ts(hours=9), age_min=30),
        ]  # fmt: skip
        tracker = [{"My_Feedback": "Would apply", "Freshness": "Verified fresh"}, {"My_Feedback": "Maybe", "Freshness": "Verified fresh"}, {"My_Feedback": "Irrelevant", "Freshness": "Recent"}, {"My_Feedback": ""}, {"My_Feedback": "n/a"}]
        boards = {"greenhouse|a": bd.BoardRecord("greenhouse", "a", "t", "s", bd.STATUS_ACTIVE), "lever|b": bd.BoardRecord("lever", "b", "t", "s", bd.STATUS_VALIDATED)}
        budget = search.SearchBudget.load(None, NOW)
        budget.charge(40, "rotation")
        kw = dict(now=NOW, days=2, runs=runs, events=ev, boards=boards, discovery={search.BUDGET_KEY: budget.to_json(), "pending_jobs": '{"k": {}}'}, tracker=tracker,
                  fresh_window=timedelta(hours=12), search_cap=1000, search_reserve=200)  # fmt: skip
        kw.update(over)
        return pilot.build_report(**kw)

    def test_every_measure_is_computed_from_the_state(self) -> None:
        r = self.build()
        p = r["polling"]
        self.assertEqual((p["runs"], p["expected_hourly_runs"], p["late_runs_over_90_min"], p["board_poll_failures"]), (48, 48, 1, 48))
        self.assertEqual(p["gap_minutes"]["max"], 200.0)
        src = r["relevant_fresh_jobs_by_source"]
        self.assertEqual((src["poll"]["new"], src["poll"]["baseline_pass"], src["search"]["new"]), (2, 1, 1))  # the baseline-pass job is not "new"
        self.assertEqual((src["poll"]["evaluated"], src["poll"]["to_apply"], src["poll"]["alerted"]), (1, 1, 1))
        d = r["delivery"]
        self.assertEqual((d["alerts_sent"], d["late_alerts"], d["alerts_later_than_the_window"], d["duplicate_alerts"]), (3, 2, 2, 1))
        self.assertEqual(d["publication_to_alert_minutes"]["max"], 900.0)
        self.assertEqual(d["discovery_latency_minutes_by_source"]["poll"]["n"], 2)  # baseline-pass observation excluded
        self.assertEqual(d["discovery_latency_minutes_by_source"]["search"]["median"], 300.0)
        f = r["failures"]
        self.assertEqual((f["error_events_in_window"], f["awaiting_evaluation_now"], f["hydration_retry_queue"], f["failed_alert_attempts_in_window"]), ({"evaluate": 1}, 3, 1, 1))  # keys 2, 3 and 4 are still unevaluated pending jobs
        self.assertEqual((r["search"]["this_month"]["used"], r["search"]["credits_in_window_from_runs"]), (40, 40))
        c = r["coverage"]
        self.assertEqual((c["monitored"], c["monitored_by_provider"], c["last_run"]["relevant_board_coverage_pct"]), (1, {"greenhouse": 1}, 83))

    def test_feedback_is_counted_and_never_altered(self) -> None:
        fb = self.build()["feedback"]
        self.assertEqual((fb["labelled"], fb["unlabelled"], fb["other_text"]), ({"Would apply": 1, "Maybe": 1, "Irrelevant": 1}, 1, 1))
        self.assertEqual((fb["would_apply_share_of_labelled_pct"], fb["useful_share_of_labelled_pct"]), (33, 67))
        self.assertEqual(fb["by_freshness_label"]["Recent"]["Irrelevant"], 1)

    def test_an_empty_state_reports_nothing_rather_than_inventing_numbers(self) -> None:
        r = pilot.build_report(now=NOW, days=7, runs=[], events=[], boards={}, discovery={}, tracker=[], fresh_window=timedelta(hours=12), search_cap=1000, search_reserve=200)
        self.assertEqual((r["polling"]["runs"], r["polling"]["gap_minutes"], r["relevant_fresh_jobs_by_source"], r["feedback"]["useful_share_of_labelled_pct"]), (0, {"n": 0}, {}, None))
        text = pilot.format_report(r)
        self.assertIn("none yet", text)
        self.assertIn("no labelled rows yet", text)

    def test_the_legacy_provider_label_is_reported_as_search(self) -> None:
        ev = [seen("greenhouse|acme|9", ts(hours=3), source="serper", age_min=10)]
        r = pilot.build_report(now=NOW, days=1, runs=[], events=ev, boards={}, discovery={}, tracker=[], fresh_window=timedelta(hours=12), search_cap=1000, search_reserve=200)
        self.assertEqual(list(r["relevant_fresh_jobs_by_source"]), ["search"])

    def test_the_report_text_names_what_it_counts(self) -> None:
        text = pilot.format_report(self.build())
        for needle in ("POLLING", "RELEVANT FRESH JOBS BY SOURCE", "LATENCY", "DELIVERY", "PENDING FAILURES", "SEARCH USAGE", "BOARD COVERAGE", "YOUR FEEDBACK", "duplicate alerts 1", "late runs"):
            self.assertIn(needle, text)

    def test_the_command_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = h.CsvStore(Path(d) / "t.csv", Path(d) / "state")
            store.bootstrap("R")
            before = {p.name: p.read_bytes() for p in Path(d).rglob("*") if p.is_file()}
            self.assertEqual(h.run_pilot_report(store, h.Settings.from_values({"Resume_Text": "r" * 300}), 7), 0)
            self.assertEqual(before, {p.name: p.read_bytes() for p in Path(d).rglob("*") if p.is_file()})


if __name__ == "__main__":
    unittest.main()


class DeliveryFixtureTests(unittest.TestCase):
    def cfg(self, **kw):
        return h.replace(h.Config.from_env(), telegram_token="tok", telegram_chat_id="123", **kw)

    def fake_groq(self):
        from unittest import mock

        g = mock.Mock()
        g.evaluate.return_value = h.Evaluation(score=82, verdict="Looks like a fit.", missing_gaps="none") if hasattr(h, "Evaluation") else None
        return g

    def test_refuses_without_the_authorized_recipient(self) -> None:
        from unittest import mock

        store = mock.Mock()
        for to in ("", "999"):
            self.assertEqual(h.run_delivery_test(self.cfg(), store, h.Settings.from_values({"Resume_Text": "r" * 300}), self.fake_groq(), to), 2)
        self.assertEqual(h.run_delivery_test(h.replace(self.cfg(), telegram_chat_id=""), store, h.Settings.from_values({}), self.fake_groq(), "123"), 2)
        store.append_jobs.assert_not_called()

    def test_the_fixture_is_isolated_labelled_and_exercises_scoring_tracker_and_telegram(self) -> None:
        from unittest import mock

        store = mock.Mock(sheet_url="https://sheet")
        groq = self.fake_groq()
        with mock.patch.object(h, "send_alert", return_value=True) as send, mock.patch("builtins.print") as out:
            rc = h.run_delivery_test(self.cfg(), store, h.Settings.from_values({"Resume_Text": "r" * 300}), groq, "123")
        self.assertEqual(rc, 0)
        groq.evaluate.assert_called_once()  # the real scoring call (mocked here; run live in STATUS.md)
        (row,) = store.append_jobs.call_args.args[0]
        self.assertEqual((row.freshness, row.source, row.url), (h.FIXTURE_LABEL, h.FIXTURE_LABEL, h.FIXTURE_URL))
        self.assertIn("TEST FIXTURE", row.title)
        self.assertIn("TEST FIXTURE", row.verdict)
        self.assertIsNone(bd.parse_job_url(h.FIXTURE_URL))  # can never dedupe against, or shadow, a real posting
        self.assertEqual(h.tracker_keys_from_urls([h.FIXTURE_URL]), set())
        send.assert_called_once()
        cells = row.cells()
        self.assertEqual((cells[10], cells[11], cells[12]), (h.FIXTURE_LABEL, h.FIXTURE_LABEL, ""))
        self.assertIn('"telegram_sent": true', out.call_args.args[0])
        store.state.append_events.assert_not_called()  # no ledger event, so no evidence or counter is touched
        store.state.save_boards.assert_not_called()

    def test_a_failed_send_is_reported_not_hidden(self) -> None:
        from unittest import mock

        store = mock.Mock(sheet_url="")
        with mock.patch.object(h, "send_alert", return_value=False):
            self.assertEqual(h.run_delivery_test(self.cfg(), store, h.Settings.from_values({"Resume_Text": "r" * 300}), self.fake_groq(), "123"), 1)


class TriggerRecordingTests(unittest.TestCase):
    def test_runs_record_what_started_them_and_the_report_counts_by_trigger(self) -> None:
        runs = [st_mod.RunRecord(ts(hours=i), notes=f"trigger={t}; ") for i, t in ((3, "schedule"), (2, "schedule"), (1, "workflow_dispatch"))] + [st_mod.RunRecord(ts(hours=4), notes="")]
        rep = pilot.build_report(now=NOW, days=1, runs=runs, events=[], boards={}, discovery={}, tracker=[], fresh_window=timedelta(hours=12), search_cap=1000, search_reserve=200)
        self.assertEqual(rep["polling"]["runs_by_trigger"], {"schedule": 2, "unrecorded": 1, "workflow_dispatch": 1})


class DiagnosticsTests(unittest.TestCase):
    def test_meter_counts_and_reports_only_what_happened_since_a_snapshot(self) -> None:
        from meter import Meter

        m = Meter()
        m.add("a")
        before = m.snapshot()
        m.add("a", 2)
        m.add("b", 0.5)
        self.assertEqual(m.since(before), {"a": 2, "b": 0.5})
        self.assertEqual(m.since(m.snapshot()), {})

    def test_quota_wrapper_counts_reads_writes_and_rejections(self) -> None:
        from unittest import mock

        import gspread

        from meter import METER

        before = METER.snapshot()
        resp = mock.Mock(status_code=429, text="x")
        resp.json.return_value = {"error": {"code": 429, "message": "q", "status": "RESOURCE_EXHAUSTED"}}
        calls = mock.Mock(side_effect=[gspread.exceptions.APIError(resp), "ok", "ok"])
        wrapped = h.quota_retrying(calls, sleep=lambda s: None)
        wrapped("GET", "u")
        wrapped("POST", "u")
        used = METER.since(before)
        self.assertEqual((used["sheets_reads"], used["sheets_writes"], used["sheets_429"]), (2, 1, 1))  # the retried read counts as a request

    def test_ats_requests_are_counted_with_their_seconds_and_429s(self) -> None:
        from unittest import mock

        from meter import METER

        before = METER.snapshot()
        with mock.patch.object(bd.requests, "get", return_value=mock.Mock(status_code=429, headers={})):
            with self.assertRaises(bd.BoardRateLimited):
                bd._get_json("https://x")
        used = METER.since(before)
        self.assertEqual((used["ats_requests"], used["ats_429"]), (1, 1))

    def test_a_run_records_its_duration_phases_sizes_and_request_counts(self) -> None:
        import tempfile as tf

        from meter import METER
        from test_core import HarnessCase, ago, job

        class Case(HarnessCase):
            def runTest(self) -> None:  # pragma: no cover
                pass

        case = Case()
        case.setUp()
        try:
            def counting_fetch(b: bd.BoardId) -> list:
                METER.add("ats_requests")
                METER.add("ats_seconds", 2.4)
                return case.w.listings[b.key]

            case.w.fetch = counting_fetch  # type: ignore[method-assign]
            case.w.listings[case.board.key] = [job("acme", "1", published=ago(days=30))]
            case.w.run(seeds=[case.board])
            run = case.w.run(minutes_later=60)
            stored = case.w.state.load_runs()[-1]
            self.assertEqual((stored.boards_rows, stored.events_rows), (1, 1))  # sizes loaded at the start of the second run
            self.assertEqual((stored.ats_requests, stored.ats_seconds), (1, 2))
            for name in ("duration_s", "load_s", "discovery_s", "poll_s", "evaluate_s"):
                self.assertGreaterEqual(getattr(stored, name), 0)
            self.assertEqual(stored, run)
        finally:
            case.tearDown() if hasattr(case, "tearDown") else None

    def test_the_run_row_round_trips_the_diagnostic_columns_and_old_rows_read_as_zero(self) -> None:
        rec = st_mod.RunRecord("2026-10-14T12:00:00Z", duration_s=95, poll_s=40, events_rows=900, sheets_reads=33, sheets_429=1, groq_calls=12, ats_seconds=70)
        again = st_mod.RunRecord.from_row([str(c) for c in rec.to_row()])
        self.assertEqual(again, rec)
        self.assertEqual(len(st_mod.RUN_COLUMNS), len(rec.to_row()))
        old = st_mod.RunRecord.from_row(["2026-10-14T12:00:00Z", "no", "3"])
        self.assertEqual((old.duration_s, old.sheets_reads, old.groq_calls), (0, 0, 0))

    def test_the_report_audits_limits_from_measured_runs_only(self) -> None:
        runs = [
            st_mod.RunRecord(ts(hours=h_), boards_total=10 + h_, duration_s=100 + 10 * h_, load_s=8, discovery_s=0, poll_s=20 + h_, evaluate_s=60, events_rows=1000 + 300 * (24 - h_), boards_rows=50,
                             sheets_reads=30 + h_, sheets_writes=12, sheets_429=1 if h_ == 5 else 0, ats_requests=10, ats_seconds=15, groq_calls=20, groq_429=1 if h_ == 3 else 0)
            for h_ in range(24, 0, -1)
        ] + [st_mod.RunRecord(ts(hours=30), duration_s=0)]  # a run from before the diagnostics: left out
        rep = pilot.build_report(now=NOW, days=2, runs=runs, events=[], boards={}, discovery={}, tracker=[], fresh_window=timedelta(hours=12), search_cap=1000, search_reserve=200, max_active=500)
        m = rep["limits"]
        self.assertEqual(m["timed_runs"], 24)
        self.assertEqual(m["duration_s"]["max"], 340.0)
        self.assertEqual(m["longest_run_pct_of_timeout"], round(100 * 340 / 1500, 1))
        self.assertEqual((m["sheets_quota_rejections_retried"], m["groq_429"], m["ats_429"]), (1, 1, 0))
        self.assertEqual(m["events_rows"], {"first": 1000 + 300 * 0, "last": 1000 + 300 * 23})
        self.assertGreater(m["events_rows_per_day"], 0)
        self.assertIsNotNone(m["projected_poll_s_at_max_active_boards"])
        text = pilot.format_report(rep)
        for needle in ("LIMITS AUDIT", "of the 1500 s timeout", "median seconds by phase", "Google Sheets requests per run", "quota about 60 per minute", "state size: Events rows", "not a measurement at that size"):
            self.assertIn(needle, text)

    def test_without_timed_runs_the_report_says_so(self) -> None:
        text = pilot.format_report(pilot.build_report(now=NOW, days=1, runs=[], events=[], boards={}, discovery={}, tracker=[], fresh_window=timedelta(hours=12), search_cap=1000, search_reserve=200))
        self.assertIn("no timed runs yet", text)


class RevalidationFlipTests(unittest.TestCase):
    NOW = datetime(2026, 10, 22, 6, 0, tzinfo=timezone.utc)

    def board(self, name: str, *, open_: int, days_ago: float, status: str = bd.STATUS_VALIDATED, ats: str = bd.GREENHOUSE) -> bd.BoardRecord:
        prev = (self.NOW - timedelta(days=days_ago)).strftime(bd.STAMP)
        return bd.BoardRecord(ats, name, prev, "s", status, validation=bd.V_VALID, last_validated_at=prev, relevant_jobs=open_, eligible_jobs=open_, last_attempt_at=prev)

    def validate(self, registry: dict, listings: dict):
        import inventory as inv

        def fetch(b: bd.BoardId) -> list:
            v = listings[b.board]
            if isinstance(v, Exception):
                raise v
            return v

        gate = lambda t: None if "Marketing" in t else "no role"  # noqa: E731
        return inv.run_validation(registry, save=lambda recs: None, now=self.NOW, fetch=fetch, title_gate=gate, limiter=inv.HostLimiter(intervals={}, sleep=lambda s: None, clock=lambda: 0.0), sleep=lambda s: None)

    def jobs(self, board: str, *titles: str) -> list:
        return [bd.ListedJob(bd.JobIdentity(bd.GREENHOUSE, board, str(i)), t, "u", "Remote") for i, t in enumerate(titles)]

    def test_gains_and_losses_are_recorded_with_the_days_each_board_went_unchecked(self) -> None:
        reg = {b.key: b for b in (
            self.board("gained", open_=0, days_ago=8), self.board("lost", open_=2, days_ago=7.5),
            self.board("steady_zero", open_=0, days_ago=9), self.board("steady_some", open_=1, days_ago=9),
            self.board("flaky", open_=0, days_ago=9), self.board("gone", open_=0, days_ago=9),
        )}  # fmt: skip
        listings = {
            "gained": self.jobs("gained", "Marketing Intern"), "lost": self.jobs("lost", "Engineer"), "steady_zero": self.jobs("steady_zero", "Engineer"),
            "steady_some": self.jobs("steady_some", "Marketing Associate"), "flaky": bd.BoardError("HTTP 503"), "gone": bd.BoardGone("HTTP 404"),
        }  # fmt: skip
        summary = self.validate(reg, listings)
        flips = {f["k"]: f for f in summary.flips}
        self.assertEqual(set(flips), {"greenhouse|gained", "greenhouse|lost"})  # steady boards, a transient failure and a 404 are not events
        self.assertEqual((flips["greenhouse|gained"]["d"], flips["greenhouse|gained"]["days"], flips["greenhouse|gained"]["was"], flips["greenhouse|gained"]["now"]), ("up", 8.0, 0, 1))
        self.assertEqual((flips["greenhouse|lost"]["d"], flips["greenhouse|lost"]["days"]), ("down", 7.5))
        self.assertEqual(summary.rechecked_validated, 4)  # gained, lost and the two steady boards: definite answers only

    def test_a_first_validation_is_never_a_flip(self) -> None:
        cand = bd.BoardRecord(bd.GREENHOUSE, "new", "t", "s", bd.STATUS_CANDIDATE)
        summary = self.validate({cand.key: cand}, {"new": self.jobs("new", "Marketing Intern")})
        self.assertEqual((summary.flips, summary.rechecked_validated), ([], 0))  # there is no previous check to compare with

    def test_statistics_accumulate_across_runs_and_are_capped(self) -> None:
        import inventory as inv

        s1 = inv.ValidationSummary(rechecked_validated=10, flips=[{"k": "a", "d": "up", "days": 8.0, "was": 0, "now": 1, "at": "t"}, {"k": "b", "d": "down", "days": 7.0, "was": 1, "now": 0, "at": "t"}])
        first = inv.merge_flip_stats(None, s1, self.NOW)
        s2 = inv.ValidationSummary(rechecked_validated=5, flips=[{"k": "c", "d": "up", "days": 9.5, "was": 0, "now": 2, "at": "t"}])
        data = json.loads(inv.merge_flip_stats(first, s2, self.NOW + timedelta(days=1)))
        self.assertEqual((data["rechecks"], data["up"], data["down"], data["days_up"], data["days_down"]), (15, 2, 1, [8.0, 9.5], [7.0]))
        big = inv.ValidationSummary(rechecked_validated=1, flips=[{"k": f"x{i}", "d": "up", "days": 7.0, "was": 0, "now": 1, "at": "t"} for i in range(500)])
        capped = json.loads(inv.merge_flip_stats(None, big, self.NOW))
        self.assertEqual((capped["up"], len(capped["events"]), len(capped["days_up"])), (500, inv.MAX_FLIP_SAMPLES, inv.MAX_FLIP_SAMPLES))  # the count stays exact, the samples are bounded
        self.assertEqual(json.loads(inv.merge_flip_stats("not json", inv.ValidationSummary(), self.NOW))["rechecks"], 0)

    def test_the_pilot_report_shows_the_flip_section(self) -> None:
        import inventory as inv

        stats = inv.merge_flip_stats(None, inv.ValidationSummary(rechecked_validated=200, flips=[
            {"k": "greenhouse|a", "d": "up", "days": 8.0, "was": 0, "now": 1, "at": "t"}, {"k": "greenhouse|b", "d": "up", "days": 6.0, "was": 0, "now": 1, "at": "t"},
            {"k": "greenhouse|c", "d": "down", "days": 7.0, "was": 1, "now": 0, "at": "t"}]), NOW)  # fmt: skip
        boards = {"greenhouse|a": bd.BoardRecord("greenhouse", "a", "t", "s", bd.STATUS_ACTIVE), "greenhouse|b": bd.BoardRecord("greenhouse", "b", "t", "s", bd.STATUS_VALIDATED)}
        rep = pilot.build_report(now=NOW, days=7, runs=[], events=[], boards=boards, discovery={"revalidation_stats": stats}, tracker=[], fresh_window=timedelta(hours=12), search_cap=1000, search_reserve=200)
        r = rep["revalidation"]
        self.assertEqual((r["rechecks"], r["gained"], r["lost"], r["gained_pct"]), (200, 2, 1, 1.0))
        self.assertEqual((r["recent_gains_now_monitored"], r["recent_gains_waiting"]), (1, 1))
        self.assertEqual(r["days_unchecked_when_gained"]["max"], 8.0)
        text = pilot.format_report(rep)
        self.assertIn("RE-CHECK FLIPS", text)
        self.assertIn("200 re-checks", text)
        empty = pilot.format_report(pilot.build_report(now=NOW, days=7, runs=[], events=[], boards={}, discovery={}, tracker=[], fresh_window=timedelta(hours=12), search_cap=1000, search_reserve=200))
        self.assertIn("no re-checks of validated boards recorded yet", empty)

    def test_the_validation_command_records_the_statistics_without_ever_failing_the_run(self) -> None:
        import argparse
        from unittest import mock

        import inventory as inv

        state = mock.Mock()
        state.load_boards.return_value = {}
        state.load_discovery_state.return_value = {}
        store = mock.Mock(state=state)
        args = argparse.Namespace(dry_run=False, import_inventory=False, validate=True, allow_smartrecruiters=False, max_validations=1, max_seconds=1.0, max_revalidations=1,
                                  source="all", inventory_cache=None, offline=False, inventory_report=False)  # fmt: skip
        summary = inv.ValidationSummary(rechecked_validated=3, flips=[{"k": "k", "d": "up", "days": 8.0, "was": 0, "now": 1, "at": "t"}])
        settings = h.Settings.from_values({"Resume_Text": "r" * 300})
        with mock.patch.object(h.inventory, "run_validation", return_value=summary):
            self.assertEqual(h.run_inventory(args, store, settings, None), 0)
        saved = state.save_discovery_state.call_args.args[0]
        self.assertEqual(json.loads(saved["revalidation_stats"])["up"], 1)
        state.save_discovery_state.side_effect = RuntimeError("sheet down")
        with mock.patch.object(h.inventory, "run_validation", return_value=summary):
            self.assertEqual(h.run_inventory(args, store, settings, None), 0)  # a statistics failure is logged, not raised
        state.save_discovery_state.reset_mock()
        args.dry_run = True
        with mock.patch.object(h.inventory, "run_validation", return_value=summary):
            h.run_inventory(args, store, settings, None)
        state.save_discovery_state.assert_not_called()  # a dry run writes nothing


class StatusColorsTests(unittest.TestCase):
    def requests_of(self, sh: FakeSpreadsheet) -> list[dict]:
        return [r for body in getattr(sh, "batches", []) for r in body["requests"]]

    def rules(self, sh: FakeSpreadsheet) -> dict[str, dict]:
        return {r["addConditionalFormatRule"]["rule"]["booleanRule"]["condition"]["values"][0]["userEnteredValue"]: r["addConditionalFormatRule"]["rule"]
                for r in self.requests_of(sh) if "addConditionalFormatRule" in r}  # fmt: skip

    def test_a_rejected_status_exists_and_only_user_set_statuses_get_a_colour(self) -> None:
        self.assertEqual(h.STATUS_CHOICES, ["To Apply", "Stretch / Review", "Applied", "Interviewing", "Offer", "Pass", "Rejected"])
        self.assertEqual(set(h.STATUS_ROW_COLORS), {"Applied", "Interviewing", "Offer", "Pass", "Rejected"})  # the two the app writes keep the default look
        self.assertEqual(len(set(h.STATUS_ROW_COLORS.values())), 5)  # five distinguishable colours

    def test_a_new_tracker_gets_the_dropdown_and_one_row_rule_per_status(self) -> None:
        sh = FakeSpreadsheet([FakeWorksheet("Sheet1", [])])
        sheet_store(sh).bootstrap("R")
        rules = self.rules(sh)
        self.assertEqual(set(rules), {f'=$C2="{s}"' for s in h.STATUS_ROW_COLORS})
        for formula, rule in rules.items():
            rng = rule["ranges"][0]
            self.assertEqual((rng["startRowIndex"], rng["startColumnIndex"], rng["endColumnIndex"]), (1, 0, len(h.TRACKER_COLUMNS)))  # the whole row, header excluded
            self.assertEqual(rule["booleanRule"]["condition"]["type"], "CUSTOM_FORMULA")
        self.assertEqual(rules['=$C2="Rejected"']["booleanRule"]["format"]["backgroundColor"], {"red": 0.98, "green": 0.8, "blue": 0.8})
        status_dropdowns = [r["setDataValidation"] for r in self.requests_of(sh) if "setDataValidation" in r and r["setDataValidation"]["range"]["startColumnIndex"] == 2]
        values = [v["userEnteredValue"] for v in status_dropdowns[0]["rule"]["condition"]["values"]]
        self.assertIn("Rejected", values)

    def test_an_existing_tracker_gets_the_new_status_and_only_the_missing_rules_without_touching_a_cell(self) -> None:
        rows = [list(h.TRACKER_COLUMNS), ["d", "p", "Applied", 80, "Acme", "NYC", "v", "g", "https://boards.greenhouse.io/acme/jobs/1", "note", "Verified fresh", "Board poll", "Maybe"]]
        tracker = FakeWorksheet("Job Tracker", [list(r) for r in rows])
        sh = FakeSpreadsheet([FakeWorksheet("Settings", [["Setting", "Value", "Instructions"]]), tracker])
        sh.metadata = {"sheets": [{"properties": {"sheetId": tracker.id}, "conditionalFormats": [
            {"booleanRule": {"condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": '=$C2="Applied"'}]}}},
            {"booleanRule": {"condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": '=$C2="Offer"'}]}}}]}]}  # fmt: skip
        sheet_store(sh).bootstrap("R")
        self.assertEqual(set(self.rules(sh)), {'=$C2="Interviewing"', '=$C2="Pass"', '=$C2="Rejected"'})  # Applied and Offer already had theirs
        self.assertEqual((tracker.values, tracker.appended), (rows, []))  # no cell was written: the user's status, notes and feedback are intact
        full = FakeSpreadsheet([FakeWorksheet("Settings", [["Setting", "Value", "Instructions"]]), tracker])
        full.metadata = {"sheets": [{"properties": {"sheetId": tracker.id}, "conditionalFormats": [
            {"booleanRule": {"condition": {"values": [{"userEnteredValue": f'=$C2="{s}"'}]}}} for s in h.STATUS_ROW_COLORS]}]}  # fmt: skip
        sheet_store(full).bootstrap("R")
        self.assertEqual(self.rules(full), {})  # idempotent: nothing is added twice

    def test_a_formatting_failure_never_breaks_startup(self) -> None:
        class Boom(FakeSpreadsheet):
            def batch_update(self, body: dict) -> None:
                raise RuntimeError("quota")

        sheet_store(Boom([FakeWorksheet("Sheet1", [])])).bootstrap("R")  # cosmetic: logged and skipped
