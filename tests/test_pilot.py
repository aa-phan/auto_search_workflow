"""Pilot instrumentation and the user's feedback column. Offline."""

from __future__ import annotations

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
