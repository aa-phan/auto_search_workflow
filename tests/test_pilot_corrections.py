"""Pilot-report corrections: the real elapsed denominator, distinct hourly intervals, workflow success vs board polls,
reconciled counts with explicit populations, latency sample labelling, coverage populations and agreement with the
dashboard's definitions. Offline."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import boards as bd  # noqa: E402
import freshness as fr  # noqa: E402
import hunter as h  # noqa: E402
import ledger as lg  # noqa: E402
import pilot  # noqa: E402
import reporting as rp  # noqa: E402
import state as st_mod  # noqa: E402

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
UTC = timezone.utc
WINDOW = timedelta(hours=12)


def ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def run(at: datetime, outcome: str = "ok", **kw: Any) -> st_mod.RunRecord:
    base: dict[str, Any] = dict(run_id=f"r{ts(at)}", outcome=outcome, finished_at=ts(at + timedelta(minutes=2)), run_kind="production", boards_total=500, boards_ok=499, boards_failed=1)
    base.update(kw)
    return st_mod.RunRecord(ts(at), **base)


def report(runs: list[st_mod.RunRecord], *, days: int = 7, events: list[lg.Event] | None = None, tracker: list[dict[str, str]] | None = None,
           boards: dict[str, bd.BoardRecord] | None = None, now: datetime = NOW) -> dict[str, Any]:
    return pilot.build_report(now=now, days=days, runs=runs, events=events or [], boards=boards or {}, discovery={}, tracker=tracker or [], fresh_window=WINDOW, search_cap=1000, search_reserve=200)


def hourly(start: datetime, count: int, **kw: Any) -> list[st_mod.RunRecord]:
    return [run(start + timedelta(hours=i), **kw) for i in range(count)]


class ElapsedAndIntervalTests(unittest.TestCase):
    def test_a_three_day_old_pilot_is_measured_over_three_days_not_seven(self) -> None:
        start = NOW - timedelta(hours=65)
        p = report(hourly(start, 65))["polling"]
        self.assertEqual((p["elapsed_hours"], p["requested_days"], p["intervals_expected"], p["intervals_with_a_successful_poll"], p["interval_coverage_pct"]), (65.0, 7, 65, 65, 100.0))
        self.assertEqual(p["pilot_started_at"], ts(start))

    def test_extra_runs_in_one_hour_do_not_hide_an_empty_hour(self) -> None:
        start = NOW - timedelta(hours=10)
        runs = [run(start + timedelta(hours=i)) for i in (0, 1, 2, 3, 5, 6, 7, 8, 9)]  # nothing starts in the hour [4, 5)
        runs += [run(start + timedelta(hours=7, minutes=20)), run(start + timedelta(hours=7, minutes=40))]  # two extra runs in one hour
        p = report(runs)["polling"]
        self.assertEqual((p["runs"], p["intervals_expected"], p["intervals_with_a_successful_poll"]), (11, 10, 9))  # 11 runs over 10 hours would have looked like 110%
        self.assertEqual(p["interval_coverage_pct"], 90.0)

    def test_gaps_are_reported_separately_with_their_times(self) -> None:
        start = NOW - timedelta(hours=10)
        runs = [run(start + timedelta(hours=i)) for i in (0, 1, 2, 3, 7, 8, 9)]  # 4 h hole after hour 3
        gaps = report(runs)["polling"]["gaps_between_successful_runs_over_90_min"]
        self.assertEqual([g["minutes"] for g in gaps], [240])  # from the last successful finish (hour 3) to the next one (hour 7)
        self.assertEqual(gaps[0]["from"], ts(start + timedelta(hours=3, minutes=2)))

    def test_failed_and_unfinished_runs_are_not_successful_polls(self) -> None:
        start = NOW - timedelta(hours=6)
        runs = [run(start + timedelta(hours=i)) for i in (0, 1, 4, 5)] + [run(start + timedelta(hours=2), "failed"), st_mod.RunRecord(ts(start + timedelta(hours=3)), run_id="dead", outcome="started")]
        p = report(runs)["polling"]
        self.assertEqual((p["intervals_with_a_successful_poll"], p["intervals_expected"]), (4, 6))
        self.assertEqual((p["workflow_runs_by_outcome"], p["unfinished_run_records"]), ({"failed": 1, "ok": 4}, 1))

    def test_workflow_success_and_board_polls_are_separate_numbers(self) -> None:
        start = NOW - timedelta(hours=4)
        runs = [run(start + timedelta(hours=i), boards_total=500, boards_ok=490, boards_failed=10) for i in range(4)]
        p = report(runs)["polling"]
        self.assertEqual(p["workflow_runs_by_outcome"], {"ok": 4})  # every workflow succeeded ...
        self.assertEqual((p["board_polls_attempted"], p["board_polls_failed"], p["board_poll_failure_pct"]), (2000, 40, 2.0))  # ... while 2% of individual board polls failed

    def test_rehearsal_runs_do_not_start_the_pilot_or_count(self) -> None:
        runs = [run(NOW - timedelta(days=5), run_kind="rehearsal")] + hourly(NOW - timedelta(hours=5), 5)
        p = report(runs)["polling"]
        self.assertEqual((p["elapsed_hours"], p["pilot_started_at"]), (5.0, ts(NOW - timedelta(hours=5))))

    def test_an_empty_state_has_no_elapsed_time_and_no_coverage(self) -> None:
        p = report([])["polling"]
        self.assertEqual((p["pilot_started_at"], p["intervals_expected"], p["interval_coverage_pct"]), (None, 0, None))  # nothing started: nothing was expected


class CodeVersionTests(unittest.TestCase):
    def test_deployments_are_visible_as_code_version_changes(self) -> None:
        start = NOW - timedelta(hours=6)
        runs = [run(start + timedelta(hours=i), code_version="aaaa1111" if i < 3 else "bbbb2222") for i in range(6)] + [run(start - timedelta(hours=1))]
        versions = report(runs)["code_versions"]
        self.assertEqual([(v["version"], v["runs"]) for v in versions], [("untagged", 1), ("aaaa1111", 3), ("bbbb2222", 3)])
        self.assertEqual(versions[2]["first_run_at"], ts(start + timedelta(hours=3)))

    def test_the_run_record_carries_the_version(self) -> None:
        r = run(NOW, code_version="abcd1234")
        self.assertEqual(st_mod.RunRecord.from_row([str(c) for c in r.to_row()]).code_version, "abcd1234")  # type: ignore[union-attr]


def seen(key: str, at: datetime, *, fresh: str = fr.VERIFIED_FRESH, disp: str = lg.PENDING, pub: datetime | None = None, precision: str = "time", pass_kind: str = "") -> lg.Event:
    d: dict[str, Any] = {"source": "poll", "board": "acme", "precision": precision if pub else ""}
    if pass_kind:
        d["pass"] = pass_kind
    return lg.Event(ts(at), key, lg.SEEN, fresh, disp, ts(pub) if pub else "", d)


def scored(key: str, at: datetime, *, status: str = "To Apply", score: int = 88, visible: bool = True, alert: bool = True) -> lg.Event:
    return lg.Event(ts(at), key, lg.EVALUATED, fr.VERIFIED_FRESH, detail={"status": status, "score": score, "visible": visible, "alert": alert, "reject": "" if visible else "score", "verdict": "v"})


def alerted(key: str, at: datetime, channel: str = "telegram") -> lg.Event:
    return lg.Event(ts(at), key, lg.ALERTED, detail={"channel": channel, "lag_min": 5, "late": False})


def url(n: int) -> str:
    return f"https://boards.greenhouse.io/acme/jobs/{n}"


class ReconciliationTests(unittest.TestCase):
    """A scenario shaped like the pilot's headline counts: 30 kept, 24 verified fresh, 25 alerts, 36 tracker rows."""

    def scenario(self) -> tuple[list[lg.Event], list[dict[str, str]], datetime, datetime]:
        start, end = NOW - timedelta(hours=65), NOW
        t = start + timedelta(hours=10)
        ev: list[lg.Event] = []
        n = 0
        for i in range(24):  # 24 verified-fresh kept jobs: 23 alert-eligible, 1 Stretch
            n += 1
            k = f"greenhouse|acme|{n}"
            stretch = i == 23
            ev += [seen(k, t, pub=t - timedelta(minutes=20)), scored(k, t, status="Stretch / Review" if stretch else "To Apply", score=55 if stretch else 88, alert=not stretch)]
            if not stretch:
                ev.append(alerted(k, t + timedelta(minutes=1)))
        for i in range(6):  # 6 kept, not verified fresh: 3 dated older than the window, 3 with no date
            n += 1
            k = f"greenhouse|acme|{n}"
            ev += [seen(k, t, fresh=fr.RECENT if i < 3 else fr.UNCERTAIN, pub=(t - timedelta(days=2)) if i < 3 else None), scored(k, t, status="Stretch / Review", score=60, alert=False)]
        for i in range(2):  # two alerts for jobs first observed BEFORE the window
            n += 1
            k = f"greenhouse|acme|{n}"
            ev += [seen(k, start - timedelta(hours=2), pub=start - timedelta(hours=3)), scored(k, start - timedelta(hours=2)), alerted(k, start + timedelta(hours=1))]
        tracker = [{"Apply_URL": url(i), "Freshness": "Verified fresh", "Source": "Board poll"} for i in range(1, 31)]  # the 30 kept jobs
        tracker += [{"Apply_URL": h.FIXTURE_URL, "Freshness": h.FIXTURE_LABEL, "Source": h.FIXTURE_LABEL}] * 2  # two labelled fixtures
        tracker += [{"Apply_URL": url(900 + i)} for i in range(3)]  # three rows the ledger never saw (older, hand-made)
        tracker += [{"Apply_URL": "https://example.com/careers/12"}]  # a row with no recognizable job URL
        self.assertEqual(len(tracker), 36)
        return ev, tracker, start, end

    def test_every_headline_count_gets_its_own_explicit_population(self) -> None:
        ev, tracker, start, end = self.scenario()
        r = rp.reconcile(runs=[], events=ev, tracker=tracker, start=start, end=end)
        j, a, t = r["jobs_first_observed"], r["alerts_delivered"], r["tracker"]
        self.assertEqual((j["kept_for_tracker"], j["kept_verified_fresh"], j["kept_dated_not_fresh"], j["kept_date_unknown"]), (30, 24, 3, 3))
        self.assertEqual(j["alert_eligible"], 23)  # one verified-fresh kept job is a Stretch: kept and fresh, never alertable
        self.assertEqual((a["delivery_events"], a["unique_jobs"], a["repeat_deliveries"]), (25, 25, 0))
        self.assertEqual(a["matching_alert_eligible_jobs"], 23)
        self.assertEqual(a["alerted_but_not_in_the_alert_eligible_set"], {"first seen outside this window": 2})  # why 25 alerts exceed the 24 fresh kept jobs
        self.assertEqual(a["alert_eligible_but_not_alerted"], {})
        self.assertEqual((t["rows_raw"], t["fixture_rows_excluded"], t["rows_real"], t["rows_without_a_job_identity"], t["distinct_jobs"]), (36, 2, 34, 1, 33))
        self.assertEqual((t["in_ledger_as_kept_any_time"], t["not_in_ledger_as_kept"], t["ledger_kept_in_window"], t["ledger_kept_in_window_and_in_tracker"]), (30, 3, 30, 30))
        self.assertEqual(t["ledger_kept_any_time_but_not_in_tracker"], 2)  # the two pre-window alerted jobs were kept but their rows are not in this synthetic tracker

    def test_the_text_states_the_window_exclusions_and_that_it_is_not_a_funnel(self) -> None:
        ev, tracker, start, end = self.scenario()
        text = "\n".join(rp.format_reconciliation(rp.reconcile(runs=[], events=ev, tracker=tracker, start=start, end=end)))
        for needle in ("window", "excluded", "one cohort", "an event count by delivery time", "all time, not windowed", "labelled test fixture"):
            self.assertIn(needle, text)

    def test_alert_eligible_jobs_that_were_not_alerted_are_named(self) -> None:
        t = NOW - timedelta(hours=3)
        ev = [seen("greenhouse|acme|1", t, pub=t), scored("greenhouse|acme|1", t), seen("greenhouse|acme|2", t, pub=t), scored("greenhouse|acme|2", t), alerted("greenhouse|acme|2", t, channel="none")]
        r = rp.reconcile(runs=[], events=ev, tracker=[], start=NOW - timedelta(days=1), end=NOW)["alerts_delivered"]
        self.assertEqual((r["delivery_events"], r["alert_eligible_but_not_alerted"]), (0, {"alert pending": 1, "alert recorded but not delivered (no channel at the time)": 1}))

    def test_rehearsal_events_and_fixtures_are_excluded_from_every_population(self) -> None:
        t = NOW - timedelta(hours=3)
        rehearsal = run(NOW - timedelta(hours=4), run_id="rh", run_kind="rehearsal")
        ev = [seen("greenhouse|acme|1", t, pub=t), scored("greenhouse|acme|1", t)]
        ev += [lg.Event(ts(t), "greenhouse|acme|2", lg.SEEN, fr.VERIFIED_FRESH, lg.PENDING, ts(t), {"source": "poll", "precision": "time", "run": "rh"})]
        r = rp.reconcile(runs=[rehearsal], events=ev, tracker=[{"Apply_URL": h.FIXTURE_URL, "Freshness": h.FIXTURE_LABEL}], start=NOW - timedelta(days=1), end=NOW)
        self.assertEqual((r["jobs_first_observed"]["total"], r["excluded"]), (1, {"rehearsal_runs": 1, "events_from_rehearsal_runs": 1, "tracker_fixture_rows": 1}))

    def test_the_pilot_report_and_the_dashboard_agree_on_the_same_window(self) -> None:
        ev, tracker, start, end = self.scenario()
        start = datetime(start.year, start.month, start.day, tzinfo=UTC) - timedelta(days=1)  # a whole-day window both can express
        summary = rp.build_summary(now=end, tz=UTC, runs=[], events=ev, boards={}, discovery={}, tracker=tracker)
        r = rp.reconcile(runs=[], events=ev, tracker=tracker, start=end - timedelta(days=6, hours=end.hour, minutes=end.minute), end=end)
        p = summary["periods"]["7d"]["results"]
        j = r["jobs_first_observed"]
        self.assertEqual((j["kept_for_tracker"], j["kept_verified_fresh"], j["kept_date_unknown"]), (p["matches_kept"], p["verified_fresh_matches"], p["matches_date_unknown"]))
        self.assertEqual(r["alerts_delivered"]["delivery_events"], p["alerts_delivered"])
        self.assertEqual(r["jobs_first_observed"]["new_postings"], p["new_postings"])


class LatencyLabellingTests(unittest.TestCase):
    def test_sample_sizes_and_unknown_dates_travel_with_the_latency(self) -> None:
        start = NOW - timedelta(hours=30)
        t = NOW - timedelta(hours=5)
        ev = [seen("greenhouse|acme|1", t, pub=t - timedelta(minutes=30)), seen("greenhouse|acme|2", t, pub=t - timedelta(hours=20), fresh=fr.RECENT),  # time-precise (one detected late)
              seen("greenhouse|acme|3", t, pub=t - timedelta(days=1), precision="day", fresh=fr.RECENT), seen("greenhouse|acme|4", t, fresh=fr.OBSERVED_NEW), seen("greenhouse|acme|5", t, fresh=fr.UNCERTAIN),
              seen("greenhouse|acme|6", t, pub=t - timedelta(minutes=5), pass_kind="baseline")]  # a first-read pass: not detection latency
        d = report(hourly(start, 30), events=ev)["detection_sample"]
        self.assertEqual((d["detected"], d["time_precise_publication"], d["day_precision_publication"], d["no_publication_date"]), (5, 2, 1, 2))
        self.assertEqual((d["publication_to_detection_minutes"]["n"], d["detected_within_window_pct_of_time_precise"]), (2, 50))  # the late detection is in the sample: no survivorship filter
        self.assertIn("relevant new postings", d["population"])
        text = pilot.format_report(report(hourly(start, 30), events=ev))
        self.assertIn("measured only among detected jobs with usable publication evidence", text)
        self.assertIn("none (not measurable)", text)


class CoveragePopulationTests(unittest.TestCase):
    def test_coverage_names_its_populations_and_both_percentages(self) -> None:
        boards = {}
        for i in range(500):
            b = bd.BoardRecord(bd.GREENHOUSE, f"b{i}", ts(NOW), "x", status="active", relevant_jobs=2 if i < 448 else 0, eligible_jobs=2 if i < 448 else 0, pool="exploration")
            boards[b.key] = b
        runs = [run(NOW - timedelta(hours=1), waiting_relevant=832, pool_exploration=500, relevant_coverage_pct=35)]
        c = report(runs, boards=boards)["coverage"]["populations"]
        self.assertEqual((c["monitored"], c["monitored_with_open_relevant_jobs"], c["monitored_with_nothing_open"], c["relevant_boards_waiting_for_a_slot"]), (500, 448, 52, 832))
        self.assertEqual((c["coverage_of_known_relevant_boards_pct"], c["monitored_share_of_monitored_plus_waiting_pct"]), (35.0, 37.5))
        text = pilot.format_report(report(runs, boards=boards))
        self.assertIn("448 of 1280 = 35.0%", text)
        self.assertIn("500 of 1332 = 37.5%", text)
        self.assertIn("not of the market", text)

    def test_the_dashboard_uses_the_same_populations(self) -> None:
        boards = {}
        for i in range(10):
            b = bd.BoardRecord(bd.GREENHOUSE, f"b{i}", ts(NOW), "x", status="active", relevant_jobs=1 if i < 8 else 0, eligible_jobs=1 if i < 8 else 0, pool="exploration")
            boards[b.key] = b
        sm = rp.build_summary(now=NOW, tz=UTC, runs=[run(NOW - timedelta(hours=1), waiting_relevant=22)], events=[], boards=boards, discovery={}, tracker=[])
        ck = sm["coverage"]["coverage_known_relevant"]
        self.assertEqual((ck["monitored_with_open_relevant_jobs"], ck["relevant_waiting"], ck["known_relevant_boards"], ck["coverage_pct"], ck["slots_share_pct"]), (8, 22, 30, 26.7, 31.2))
        import dashboard as db

        text = "\n".join(str(v) for row in db.render(sm).values() for v in row)
        self.assertIn("8 of 30 known relevant boards have a slot (26.7%", text)


if __name__ == "__main__":
    unittest.main()
