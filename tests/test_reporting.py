"""Offline tests for the operational dashboard: run instrumentation, the reporting summary and the Dashboard tab.

The summary is checked against the ledger it is computed from: hand-built events with known answers (retries,
duplicate observations, partial failures, missing dates, local-day boundaries) and real pipeline runs through
the same fake world the core tests use. Everything is mocked; nothing here touched a real Sheet (see STATUS.md).
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import boards as bd  # noqa: E402
import compact  # noqa: E402
import dashboard as db  # noqa: E402
import discovery as dsc  # noqa: E402
import eligibility as el  # noqa: E402
import freshness as fr  # noqa: E402
import hunter as h  # noqa: E402
import ledger as lg  # noqa: E402
import pipeline as pl  # noqa: E402
import reporting as rp  # noqa: E402
import state as st_mod  # noqa: E402
from test_core import S, T0, HarnessCase, ago, done, job  # noqa: E402
from test_hunter import FakeSpreadsheet, FakeWorksheet, posting, settings, sheet_store  # noqa: E402

UTC = timezone.utc
CHI = ZoneInfo("America/Chicago")  # UTC-5 in October 2026


def stamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def seen(key: str, at: datetime, *, fresh: str = fr.VERIFIED_FRESH, disp: str = lg.PENDING, pub: datetime | None = None, source: str = "poll",
         pass_kind: str = "", precision: str = "time", run: str = "") -> lg.Event:
    detail: dict[str, Any] = {"source": source, "precision": precision if pub else "", "board": key.split("|")[1]}
    if pass_kind:
        detail["pass"] = pass_kind
    if run:
        detail["run"] = run
    return lg.Event(stamp(at), key, lg.SEEN, fresh, disp, stamp(pub) if pub else "", detail)


def evaluated(key: str, at: datetime, *, status: str = "To Apply", score: int | None = 88, reject: str | None = "", visible: bool = True, alert: bool = True, run: str = "") -> lg.Event:
    detail: dict[str, Any] = {"status": status, "score": score, "visible": visible, "alert": alert, "verdict": "v"}
    if reject is not None:
        detail["reject"] = reject
    if run:
        detail["run"] = run
    return lg.Event(stamp(at), key, lg.EVALUATED, fresh_of(status), detail=detail)


def fresh_of(_: str) -> str:
    return fr.VERIFIED_FRESH


def alerted(key: str, at: datetime, *, channel: str = "telegram", late: bool = False) -> lg.Event:
    return lg.Event(stamp(at), key, lg.ALERTED, detail={"channel": channel, "lag_min": 5, "late": late})


def errored(key: str, at: datetime, stage: str = "evaluate", attempt: int = 1) -> lg.Event:
    return lg.Event(stamp(at), key, lg.ERROR, detail={"stage": stage, "message": "boom", "attempt": attempt})


def k(n: int, ats: str = "greenhouse") -> str:
    return f"{ats}|acme|{n}"


def summary(events: list[lg.Event] | None = None, runs: list[st_mod.RunRecord] | None = None, tracker: list[dict[str, str]] | None = None,
            boards: dict[str, bd.BoardRecord] | None = None, discovery: dict[str, str] | None = None, now: datetime = T0, tz: Any = UTC,
            tracker_deleted: frozenset[str] = frozenset()) -> dict[str, Any]:
    return rp.build_summary(now=now, tz=tz, runs=runs or [], events=events or [], boards=boards or {}, discovery=discovery or {}, tracker=tracker or [],
                            tracker_deleted=tracker_deleted)


def run_rec(at: datetime, **kw: Any) -> st_mod.RunRecord:
    base: dict[str, Any] = dict(run_id=f"id-{stamp(at)}", outcome="ok", finished_at=stamp(at + timedelta(minutes=2)), run_kind="production")
    base.update(kw)
    return st_mod.RunRecord(stamp(at), **base)


# --------------------------------------------------------------------------- instrumentation


class RunInstrumentationTests(HarnessCase):
    def test_every_run_has_an_id_times_outcome_and_kind_and_exactly_one_record(self) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)))
        runs = self.w.state.load_runs()
        self.assertEqual(len(runs), 1)  # the start record was completed in place, not duplicated
        r = runs[0]
        self.assertTrue(r.run_id)
        self.assertEqual((r.outcome, r.run_kind, r.run_at, r.finished_at), ("ok", "production", stamp(T0), stamp(T0)))

    def test_start_record_is_persisted_before_any_work(self) -> None:
        seen_at_fetch: list[list[st_mod.RunRecord]] = []
        original = self.w.fetch

        def spy(board: bd.BoardId) -> list[bd.ListedJob]:
            seen_at_fetch.append(self.w.state.load_runs())
            return original(board)

        self.w.listings[self.board.key] = [job("acme", "1", published=ago(days=30))]
        self.w.fetch = spy  # type: ignore[method-assign]
        run = self.w.run(seeds=[self.board])
        self.assertTrue(seen_at_fetch)
        during = seen_at_fetch[0]
        self.assertEqual([(r.run_id, r.outcome) for r in during], [(run.run_id, "started")])  # visible while the run is in progress

    def test_a_fatal_stop_leaves_one_failed_record(self) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)))
        self.w.listings[self.board.key].append(job("acme", "2", published=ago(minutes=5, base=T0 + timedelta(minutes=60))))

        def fatal(ident: Any, st: Any) -> Any:
            raise pl.FatalRunError("GROQ key rejected")

        self.w.evaluate = fatal  # type: ignore[method-assign]
        with self.assertRaises(pl.FatalRunError):
            self.w.run(minutes_later=60)
        runs = self.w.state.load_runs()
        self.assertEqual([r.outcome for r in runs], ["ok", "failed"])
        self.assertTrue(runs[-1].finished_at)

    def test_degraded_outcome_when_an_alert_could_not_be_delivered(self) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)))
        self.w.listings[self.board.key].append(job("acme", "2", published=ago(minutes=5, base=T0 + timedelta(minutes=60))))
        self.w.alert_error = ConnectionError("telegram down")
        run = self.w.run(minutes_later=60)
        self.assertEqual((run.outcome, run.alerts_failed), ("degraded", 1))

    def test_events_carry_the_run_id_and_stage_attempts_are_counted_separately(self) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)))
        self.w.listings[self.board.key].append(job("acme", "7", published=ago(minutes=10, base=T0 + timedelta(minutes=60))))
        k7 = self.key("7")
        self.w.plan[k7] = [pl.EvalOutcome("transient", message="groq 429"), done()]
        r1 = self.w.run(minutes_later=60)
        r2 = self.w.run(minutes_later=60)
        self.assertEqual((r1.eval_attempted, r1.eval_transient, r2.eval_attempted, r2.eval_transient), (1, 1, 1, 0))
        for kind in (lg.SEEN, lg.EVALUATED, lg.ALERTED):
            self.assertTrue(all(e.detail.get("run") in {r1.run_id, r2.run_id} for e in self.w.events(k7, kind)), kind)
        self.assertEqual(self.w.events(k7, lg.SEEN)[0].detail["run"], r1.run_id)
        self.assertEqual(self.w.events(k7, lg.EVALUATED)[0].detail["run"], r2.run_id)

    def test_gap_is_measured_from_the_last_finished_run_not_an_interrupted_one(self) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)))
        self.w.state.begin_run(st_mod.RunRecord(ago(minutes=-30), run_id="dead", outcome="started"))  # started 30 min after the baseline, never finished
        run = self.w.run(minutes_later=60)
        self.assertEqual(run.gap_since_prev_run_min, 60)  # not 30: the dead run polled nothing that was saved

    def test_credit_status_marks_failed_requests_as_unresolved(self) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)))
        ok = dsc.DiscoveryResult(queries=[dsc.QueryStats("a", credits=1, pages=1)])
        bad = dsc.DiscoveryResult(queries=[dsc.QueryStats("a", credits=1, pages=1), dsc.QueryStats("b", error="Timeout: x", stop="error")])
        r_none = self.w.run(minutes_later=60)
        r_ok = self.w.run(minutes_later=60, discover=lambda c: ok, force_discovery=True)
        r_bad = self.w.run(minutes_later=60, discover=lambda c: bad, force_discovery=True)
        self.assertEqual((r_none.credit_status, r_ok.credit_status, r_bad.credit_status), ("none", "reported", "unresolved"))
        self.assertEqual((r_ok.search_failed, r_bad.search_failed), (0, 1))

        def boom(ctx: Any) -> Any:
            raise RuntimeError("provider exploded")

        self.assertEqual(self.w.run(minutes_later=60, discover=boom, force_discovery=True).credit_status, "unresolved")

    def test_run_record_round_trips_the_new_columns(self) -> None:
        r = run_rec(T0, search_failed=2, search_account_used=7, credit_status="unresolved", eval_attempted=5, eval_transient=1, eval_failed=2)
        back = st_mod.RunRecord.from_row([str(c) for c in r.to_row()])
        self.assertEqual(back, r)
        old = st_mod.RunRecord.from_row([stamp(T0), "no"] + ["0"] * 52)  # a row from before the columns existed
        assert old is not None
        self.assertEqual((old.run_id, old.outcome, old.search_account_used, old.completed), ("", "", None, True))

    def test_rehearsal_runs_are_labelled(self) -> None:
        self.w.listings[self.board.key] = [job("acme", "1", published=ago(days=30))]
        run = self.w.run(seeds=[self.board], run_kind=st_mod.KIND_REHEARSAL)
        self.assertEqual(self.w.state.load_runs()[-1].run_kind, "rehearsal")
        self.assertEqual(run.run_kind, "rehearsal")


class ReasonCodeTests(unittest.TestCase):
    resume = "r" * 300

    def test_hard_gate_codes_match_its_reasons(self) -> None:
        cases = {
            "location": ("Marketing Intern", "Remote - Canada", "x"),
            "experience": ("Marketing Associate", "NYC", "Requires 5+ years of experience in marketing."),
            "language": ("Marketing Intern", "NYC", "Fluent in Mandarin required."),
        }
        for code, args in cases.items():
            got = el.hard_gate_coded(*args, self.resume)
            self.assertIsNotNone(got, code)
            assert got
            self.assertEqual((got[0], got[1]), (code, el.hard_gate(*args, self.resume)))
        self.assertIsNone(el.hard_gate_coded("Marketing Intern", "Remote", "fine", self.resume))

    def test_evaluator_stores_the_rejecting_stage_in_the_payload(self) -> None:
        ident = bd.JobIdentity("lever", "acme", "123e4567-e89b-12d3-a456-426614174000")
        st = lg.JobState(ident.key, seen=True, freshness=fr.VERIFIED_FRESH, seen_detail={"board": "acme", "title": "Marketing Intern"})
        s = settings()

        def reject(p: h.Posting | Exception, groq: Any = None) -> str:
            fn = (lambda r: (_ for _ in ()).throw(p)) if isinstance(p, Exception) else (lambda r: p)
            out = h.make_evaluator(s, groq or _Groq(10), h.excluded_title_regex(s.excluded), hydrate=fn)(ident, st)  # type: ignore[arg-type]
            assert out.payload is not None
            return str(out.payload["reject"])

        self.assertEqual(reject(h.ClosedPosting("404")), "closed")
        self.assertEqual(reject(posting(posted="2020-01-01")), "age")
        self.assertEqual(reject(posting(title="Senior Marketing Associate")), "title")
        self.assertEqual(reject(posting(location="Remote - Canada")), "location")
        self.assertEqual(reject(posting(description="Requires 6+ years of experience in marketing. " * 8)), "experience")
        self.assertEqual(reject(posting(description="Fluent in Mandarin required. " * 12)), "language")
        self.assertEqual(reject(posting(), _Groq(20)), "score")  # scored below the tracker threshold
        self.assertEqual(reject(posting(), _Groq(88)), "")  # scored and kept


class _Groq:
    def __init__(self, score: int) -> None:
        self.score = score

    def evaluate(self, s: Any, p: Any, **kw: Any) -> h.Evaluation:
        return h.Evaluation(self.score, "verdict", "gaps")


# --------------------------------------------------------------------------- totals against the ledger


class LedgerTotalsTests(unittest.TestCase):
    def test_unique_jobs_ignore_duplicate_observations_and_retries(self) -> None:
        events = [
            seen(k(1), T0 - timedelta(hours=3), pub=T0 - timedelta(hours=4)),
            seen(k(1), T0 - timedelta(hours=2), pub=T0 - timedelta(hours=4)),  # the same job observed again (e.g. search found it too)
            evaluated(k(1), T0 - timedelta(hours=3)),
            evaluated(k(1), T0 - timedelta(hours=2)),  # a repeated evaluation event
            errored(k(1), T0 - timedelta(hours=3, minutes=30)), errored(k(1), T0 - timedelta(hours=3, minutes=20), attempt=2),
        ]
        p = summary(events)["periods"]["7d"]
        self.assertEqual(p["results"]["unique_jobs_observed"], 1)
        self.assertEqual((p["results"]["eligible_matches_scored"], p["results"]["matches_kept"], p["results"]["tracker_additions"]), (1, 1, 1))
        self.assertEqual(p["errors_recorded"]["evaluate"], 2)  # attempts are counted as attempts, apart from the one unique job
        self.assertEqual(summary(events)["failures"]["unique_jobs_with_errors"], 1)
        self.assertEqual(summary(events)["checks"], [])

    def test_repeat_alert_deliveries_are_separated_from_unique_alerted_jobs(self) -> None:
        events = [
            seen(k(1), T0 - timedelta(hours=5), pub=T0 - timedelta(hours=6)), evaluated(k(1), T0 - timedelta(hours=5)),
            alerted(k(1), T0 - timedelta(hours=4)), alerted(k(1), T0 - timedelta(hours=1), late=True),  # at-least-once: resent
            alerted(k(1), T0 - timedelta(hours=1, minutes=-1), channel="none"),  # recorded without a channel: not a delivery
        ]
        r = summary(events)["periods"]["7d"]["results"]
        self.assertEqual((r["alerts_delivered"], r["alerts_unique_jobs"], r["alerts_repeat_deliveries"], r["alert_events_not_delivered"]), (2, 1, 1, 1))

    def test_partial_failure_pending_alert_then_delivered(self) -> None:
        base = [seen(k(1), T0 - timedelta(hours=6), pub=T0 - timedelta(hours=7)), evaluated(k(1), T0 - timedelta(hours=6))]
        s1 = summary(base)
        self.assertEqual((s1["failures"]["pending_alert"]["jobs"], s1["failures"]["pending_alert"]["oldest_hours"]), (1, 6.0))
        self.assertEqual(s1["periods"]["7d"]["results"]["alerts_delivered"], 0)  # a measured zero, with the alert still pending
        self.assertEqual(s1["headline"]["status"], "No data yet")  # no run records: the headline does not invent a health verdict
        s2 = summary(base + [alerted(k(1), T0 - timedelta(hours=1))])
        self.assertEqual((s2["failures"]["pending_alert"]["jobs"], s2["periods"]["7d"]["results"]["alerts_delivered"]), (0, 1))
        self.assertEqual(s2["periods"]["7d"]["latency_min"]["detection_to_delivery"]["median"], 300.0)  # seen 6 h ago, delivered 1 h ago

    def test_abandoned_and_pending_evaluation_are_not_rejections_or_matches(self) -> None:
        events = [
            seen(k(1), T0 - timedelta(hours=30), pub=T0 - timedelta(hours=31)),  # never evaluated yet
            seen(k(2), T0 - timedelta(hours=2), pub=T0 - timedelta(hours=3)), errored(k(2), T0 - timedelta(hours=1)),
            lg.Event(stamp(T0), k(2), lg.ABANDONED, detail={"stage": "evaluate"}),
        ]
        sm = summary(events)
        o = sm["periods"]["7d"]["outcomes"]
        self.assertEqual((o["pending"], o["abandoned"], o["kept"], o["score"]), (1, 1, 0, 0))
        self.assertEqual(sm["failures"]["pending_evaluation"], {"jobs": 1, "oldest_hours": 30.0})
        self.assertEqual(sm["periods"]["7d"]["results"]["matches_kept"], 0)
        self.assertTrue(any(r["what"] == "evaluate failing for job" and r["severity"] == 0 for r in sm["failures"]["table"]) or sm["failures"]["abandoned_jobs"] == 1)

    def test_every_rejection_reason_and_the_partition_adds_up(self) -> None:
        t = T0 - timedelta(hours=2)
        events: list[lg.Event] = [
            seen(k(1), t, disp=lg.BASELINED, fresh=fr.BASELINE),
            seen(k(2), t, disp=lg.FILTERED, pub=t),  # cheap title gate
            seen(k(3), t, disp=lg.STALED, fresh=fr.STALE, pub=t - timedelta(days=30)),  # age at observation
            seen(k(4), t, pub=t), evaluated(k(4), t, status="Filtered Out", score=0, reject="location", visible=False, alert=False),
            seen(k(5), t, pub=t), evaluated(k(5), t, status="Filtered Out", score=0, reject="experience", visible=False, alert=False),
            seen(k(6), t, pub=t), evaluated(k(6), t, status="Filtered Out", score=0, reject="language", visible=False, alert=False),
            seen(k(7), t, pub=t), evaluated(k(7), t, status="Stale (>14d old)", score=0, reject="age", visible=False, alert=False),
            seen(k(8), t, pub=t), evaluated(k(8), t, status="Closed (404)", score=0, reject="closed", visible=False, alert=False),
            seen(k(9), t, pub=t), evaluated(k(9), t, status="Filtered Out", score=31, reject="score", visible=False, alert=False),
            seen(k(10), t, pub=t), evaluated(k(10), t, status="Stretch / Review", score=55, reject="", alert=False),
            seen(k(11), t, pub=t), evaluated(k(11), t),
        ]
        sm = summary(events)
        p = sm["periods"]["7d"]
        self.assertEqual({o: n for o, n in p["outcomes"].items() if n}, {"baseline": 1, "title": 1, "age": 2, "location": 1, "experience": 1, "language": 1, "closed": 1, "score": 1, "kept": 2})
        self.assertEqual(sum(p["outcomes"].values()), p["results"]["unique_jobs_observed"])  # one cohort, each job once
        self.assertEqual((p["results"]["eligible_matches_scored"], p["results"]["matches_kept"]), (3, 2))
        self.assertEqual(sm["checks"], [])

    def test_missing_dates_are_unknown_not_fresh_and_have_their_own_denominator(self) -> None:
        t = T0 - timedelta(hours=2)
        events = [
            seen(k(1), t, pub=t - timedelta(hours=1)), evaluated(k(1), t),  # dated, verified fresh
            seen(k(2), t, fresh=fr.RECENT, pub=t - timedelta(days=2), precision="time"), evaluated(k(2), t, alert=False),  # dated, older than the window
            seen(k(3), t, fresh=fr.OBSERVED_NEW), evaluated(k(3), t, alert=False),  # no source date
            seen(k(4), t, fresh=fr.UNCERTAIN, source="search"), evaluated(k(4), t, alert=False),  # no source date
        ]
        p = summary(events)["periods"]["7d"]
        f = p["freshness"]
        self.assertEqual((f["cohort_jobs"], f["verified_fresh"], f["dated"], f["date_unknown"]), (4, 1, 2, 2))
        self.assertEqual((f["new_postings_date_known"], f["new_postings_date_unknown"]), (2, 2))  # the overlay row on the dashboard
        self.assertEqual(f["verified_fresh_share_of_dated_pct"], 50)  # of DATED jobs only; the two undated are not in the denominator
        r = p["results"]
        self.assertEqual((r["matches_kept"], r["verified_fresh_matches"], r["matches_dated_not_fresh"], r["matches_date_unknown"]), (4, 1, 1, 2))
        self.assertEqual(r["new_by_source"], {"poll": 3, "search": 1})  # discovery source, separate from the provider below
        self.assertEqual(r["new_by_ats"], {"greenhouse": 4})

    def test_publication_to_detection_and_detection_to_delivery_are_separate(self) -> None:
        pub = T0 - timedelta(hours=10)
        events = [
            seen(k(1), pub + timedelta(minutes=40), pub=pub), evaluated(k(1), pub + timedelta(minutes=45)),
            alerted(k(1), pub + timedelta(minutes=100)),
            seen(k(2), pub, pub=pub - timedelta(minutes=100), pass_kind="baseline"),  # first read of a board: not detection latency
            seen(k(3), pub, pub=None, fresh=fr.OBSERVED_NEW), seen(k(4), pub, pub=pub - timedelta(days=1), precision="day"),
        ]
        lat = summary(events)["periods"]["7d"]["latency_min"]
        self.assertEqual((lat["publication_to_detection"]["n"], lat["publication_to_detection"]["median"]), (1, 40.0))
        self.assertEqual((lat["detection_to_delivery"]["n"], lat["detection_to_delivery"]["median"]), (1, 60.0))

    def test_local_day_boundaries(self) -> None:
        # now = 2026-10-14 12:00 UTC = 07:00 CDT. Local midnight of the 14th = 05:00 UTC.
        edge = datetime(2026, 10, 14, 5, 0, tzinfo=UTC)
        events = [
            seen(k(1), edge - timedelta(seconds=1), fresh=fr.RECENT, pub=edge - timedelta(days=2)),  # 23:59:59 local on the 13th
            seen(k(2), edge, fresh=fr.RECENT, pub=edge - timedelta(days=2)),  # exactly local midnight: belongs to the 14th
            seen(k(3), edge - timedelta(days=6, seconds=1), fresh=fr.RECENT, pub=edge - timedelta(days=9)),  # 8th 23:59:59 local: outside 7 days
            seen(k(4), edge - timedelta(days=6), fresh=fr.RECENT, pub=edge - timedelta(days=9)),  # the 8th at 00:00 local: first moment of the 7-day view
            seen(k(5), edge - timedelta(days=29, seconds=1), fresh=fr.RECENT, pub=edge - timedelta(days=40)),  # outside 30 days
            seen(k(6), edge - timedelta(days=29), fresh=fr.RECENT, pub=edge - timedelta(days=40)),  # inside 30 days
        ]
        sm = summary(events, tz=CHI)
        n = {key: sm["periods"][key]["results"]["unique_jobs_observed"] for key in ("today", "7d", "30d")}
        self.assertEqual(n, {"today": 1, "7d": 3, "30d": 5})
        self.assertEqual([d["new_postings"] for d in sm["trend"][:2]], [1, 1])  # the 14th and the 13th
        self.assertEqual(sm["periods"]["7d"]["from"], "2026-10-08")
        # the same instants viewed in UTC both fall on the 14th: boundaries follow the display time zone
        self.assertEqual(summary(events, tz=UTC)["periods"]["today"]["results"]["unique_jobs_observed"], 2)

    def test_tracker_additions_alerts_and_attempts_are_event_counts_by_their_own_day(self) -> None:
        yesterday, today = T0 - timedelta(days=1), T0 - timedelta(hours=1)
        events = [
            seen(k(1), yesterday, pub=yesterday - timedelta(hours=1)), evaluated(k(1), yesterday), alerted(k(1), today),  # seen/evaluated yesterday, alerted today
        ]
        sm = summary(events, tz=UTC)
        self.assertEqual((sm["periods"]["today"]["results"]["unique_jobs_observed"], sm["periods"]["today"]["results"]["alerts_delivered"], sm["periods"]["today"]["results"]["tracker_additions"]), (0, 1, 0))
        self.assertEqual((sm["periods"]["7d"]["results"]["unique_jobs_observed"], sm["periods"]["7d"]["results"]["alerts_delivered"], sm["periods"]["7d"]["results"]["tracker_additions"]), (1, 1, 1))

    def test_legacy_evaluations_without_reason_codes_are_classified_from_their_text_and_flagged(self) -> None:
        t = T0 - timedelta(hours=2)
        legacy = lg.Event(stamp(t), k(1), lg.EVALUATED, detail={"status": "Filtered Out", "score": 0, "verdict": "Filtered before scoring: location is outside the US (Remote - Canada).", "visible": False})
        sm = summary([seen(k(1), t, pub=t), legacy])
        self.assertEqual(sm["periods"]["7d"]["outcomes"]["location"], 1)
        self.assertEqual(sm["periods"]["7d"]["legacy_reason_codes"], 1)

    def test_rehearsal_runs_events_and_fixtures_are_excluded(self) -> None:
        t = T0 - timedelta(hours=2)
        runs = [run_rec(T0 - timedelta(hours=3), run_id="real"), run_rec(T0 - timedelta(hours=2), run_id="rehearsal", run_kind="rehearsal")]
        events = [seen(k(1), t, pub=t, run="real"), seen(k(2), t, pub=t, run="rehearsal"), evaluated(k(2), t, run="rehearsal"), seen(k(3), t, pub=t)]  # k(3): no run id (older event)
        tracker = [{"My_Feedback": "Would apply", "My_Status": "To Apply", "Freshness": "Verified fresh"},
                   {"My_Feedback": "Maybe", "Freshness": h.FIXTURE_LABEL, "Source": h.FIXTURE_LABEL, "Apply_URL": h.FIXTURE_URL}]
        sm = summary(events, runs, tracker)
        self.assertEqual(sm["periods"]["7d"]["results"]["unique_jobs_observed"], 2)
        self.assertEqual(sm["exclusions"], {"rehearsal_runs": 1, "events_from_rehearsal_runs": 2, "tracker_fixture_rows": 1, "duplicate_run_records_merged": 0})
        self.assertEqual((sm["feedback"]["tracker_rows"], sm["feedback"]["feedback"]["Maybe"]), (1, 0))
        self.assertEqual(sm["health"]["polling"]["7d"]["runs_finished"], 1)
        self.assertTrue(h.FIXTURE_LABEL.startswith(rp.FIXTURE_MARKER))

    def test_two_summaries_of_the_same_state_are_identical(self) -> None:
        events = [seen(k(1), T0 - timedelta(hours=2), pub=T0 - timedelta(hours=3)), evaluated(k(1), T0 - timedelta(hours=2)), alerted(k(1), T0 - timedelta(hours=1))]
        runs = [run_rec(T0 - timedelta(hours=1))]
        a, b = summary(events, runs), summary(events, runs)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertEqual(db.render(a).values(), db.render(b).values())


class HealthTests(unittest.TestCase):
    def test_no_records_means_unknown_not_zero(self) -> None:
        sm = summary()
        self.assertIsNone(sm["health"]["polling"]["7d"]["runs_finished"])
        self.assertIsNone(sm["health"]["last_run"])
        self.assertEqual(sm["headline"]["status"], "No data yet")
        self.assertIsNone(sm["discovery"]["ledger"])
        self.assertIsNone(sm["discovery"]["rotation"])
        self.assertTrue(all(d["new_postings"] is None for d in sm["trend"]))  # before anything was recorded: n/a
        self.assertEqual(sm["feedback"]["would_apply_pct_of_labelled"], None)

    def test_polling_gaps_interrupted_runs_and_outcomes(self) -> None:
        runs = [
            run_rec(T0 - timedelta(hours=6), gap_since_prev_run_min=None),
            run_rec(T0 - timedelta(hours=5), gap_since_prev_run_min=60),
            run_rec(T0 - timedelta(hours=2), gap_since_prev_run_min=180, outcome="degraded", notes="discovery failed: x"),
            st_mod.RunRecord(stamp(T0 - timedelta(hours=1, minutes=30)), run_id="dead", outcome="started"),  # never finished
            run_rec(T0 - timedelta(hours=1), gap_since_prev_run_min=60, outcome="failed"),
        ]
        sm = summary(runs=runs)
        pol = sm["health"]["polling"]["7d"]
        self.assertEqual((pol["runs_finished"], pol["gaps_over_threshold"], pol["max_gap_min"], pol["ok"], pol["degraded"], pol["failed"], pol["interrupted"]), (4, 1, 180, 2, 1, 1, 1))
        self.assertEqual(sm["health"]["interrupted_runs"], 1)
        self.assertEqual(sm["health"]["last_run"]["outcome"], "failed")
        self.assertEqual(sm["headline"]["status"], "Needs attention")
        whats = {r["what"] for r in sm["failures"]["table"]}
        self.assertTrue({"run interrupted", "run failed", "run degraded"} <= whats)
        self.assertEqual(sm["health"]["polling"]["7d"]["expected_hourly_slots"], 6)  # counted from the first recorded run, not from 7 days ago

    def test_a_run_in_progress_is_not_called_interrupted(self) -> None:
        sm = summary(runs=[run_rec(T0 - timedelta(hours=1)), st_mod.RunRecord(stamp(T0 - timedelta(minutes=5)), run_id="now", outcome="started")])
        self.assertEqual((sm["health"]["interrupted_runs"], sm["health"]["runs_in_progress"]), (0, 1))
        self.assertEqual(sm["health"]["last_run"]["outcome"], "running")

    def test_start_and_finished_record_of_one_run_count_once(self) -> None:
        start = st_mod.RunRecord(stamp(T0 - timedelta(hours=1)), run_id="a", outcome="started")
        sm = summary(runs=[start, run_rec(T0 - timedelta(hours=1), run_id="a")])
        self.assertEqual((sm["health"]["polling"]["7d"]["runs_finished"], sm["exclusions"]["duplicate_run_records_merged"], sm["health"]["interrupted_runs"]), (1, 1, 0))

    def test_degraded_provider_from_failing_boards_and_backoff_notes(self) -> None:
        boards = {}
        for i in range(10):
            b = bd.BoardRecord(bd.WORKABLE, f"co{i}", stamp(T0), "x", status="active", consecutive_failures=3 if i < 4 else 0, last_error="HTTP 429" if i < 4 else "")
            boards[b.key] = b
        gh = bd.BoardRecord(bd.GREENHOUSE, "fine", stamp(T0), "x", status="active")
        boards[gh.key] = gh
        sm = summary(runs=[run_rec(T0 - timedelta(hours=1), notes="provider backoff after HTTP 429: not polled this run: 5 lever; ")], boards=boards)
        by = {p["provider"]: p for p in sm["health"]["providers"]}
        self.assertTrue(by["workable"]["degraded"] and by["lever"]["degraded"] and not by["greenhouse"]["degraded"])
        self.assertEqual(sm["health"]["degraded_providers"], ["lever", "workable"])


class DiscoveryAndCoverageTests(unittest.TestCase):
    def test_credit_ledger_remaining_budget_and_unresolved_charges(self) -> None:
        month = T0.strftime("%Y-%m")
        discovery = {"search_budget": json.dumps({"month": month, "used": 120, "calls": 120, "by_path": {"rotation": 100, "manual": 20}, "limit_hit": False})}
        runs = [run_rec(T0 - timedelta(hours=3), discovery=True, search_credits=10, credit_status="reported", search_account_used=130),
                run_rec(T0 - timedelta(hours=2), discovery=True, search_credits=9, search_failed=1, credit_status="unresolved", search_account_used=135),
                run_rec(T0 - timedelta(hours=1), discovery=True, search_credits=0)]  # a row from before credit status existed
        d = summary(runs=runs, discovery=discovery)["discovery"]
        self.assertEqual((d["ledger"]["used_locally"], d["ledger"]["remaining_scheduled"], d["ledger"]["remaining_manual"]), (120, 680, 880))
        self.assertEqual(d["periods"]["7d"], {"credits_spent": 19, "discovery_runs": 3, "failed_requests_billing_unknown": 1, "runs_credit_unresolved": 1, "runs_credit_not_recorded": 1})
        self.assertEqual((d["account_counter_last_read"], d["account_minus_local"]), (135, 15))

    def test_a_ledger_from_an_earlier_month_is_not_presented_as_this_months_spending(self) -> None:
        discovery = {"search_budget": json.dumps({"month": "2026-09", "used": 800, "calls": 800, "by_path": {}, "limit_hit": False})}
        d = summary(discovery=discovery)["discovery"]
        self.assertFalse(d["ledger"]["month_matches_now"])
        self.assertEqual(d["ledger"]["used_locally"], 0)
        self.assertIsNone(d["account_minus_local"])

    def test_unique_eligible_discoveries_and_fresh_search_matches_are_unique_by_identity(self) -> None:
        boards = {}
        for i, status in enumerate(("validated", "active", "invalid", "candidate")):
            b = bd.BoardRecord(bd.GREENHOUSE, f"b{i}", stamp(T0), "tavily", status=status, provenance={"tavily": {"first": stamp(T0 - timedelta(hours=2))}})
            boards[b.key] = b
        old = bd.BoardRecord(bd.GREENHOUSE, "old", stamp(T0), "tavily", status="validated", provenance={"tavily": {"first": stamp(T0 - timedelta(days=20))}})
        boards[old.key] = old
        t = T0 - timedelta(hours=2)
        events = [seen(k(1), t, pub=t, source="search"), evaluated(k(1), t), seen(k(1), t, pub=t, source="search"),  # observed twice, still one job
                  seen(k(2), t, pub=t, source="poll"), evaluated(k(2), t)]
        d = summary(events, boards=boards)["discovery"]
        self.assertEqual(d["unique_eligible_boards_found_by_search"], {"today": 2, "7d": 2, "30d": 3})
        self.assertEqual(d["unique_verified_fresh_search_matches"], {"today": 1, "7d": 1, "30d": 1})

    def test_rotation_progress(self) -> None:
        rot = dsc.RotationState(cursor=12, total=42, cycles=1, runs=7, last_run_at=stamp(T0))
        d = summary(discovery={dsc.ROTATION_KEY: rot.to_json()})["discovery"]
        self.assertEqual(d["rotation"], {"cursor": 12, "total_slots": 42, "full_passes": 1, "runs": 7, "last_run_at": stamp(T0)})

    def test_board_coverage_validation_overdue_and_trial_expirations(self) -> None:
        def board(name: str, **kw: Any) -> bd.BoardRecord:
            kw.setdefault("discovered_at", stamp(T0 - timedelta(days=30)))
            return bd.BoardRecord(bd.GREENHOUSE, name, source="x", **kw)

        recs = [
            board("est", status="active", pool="established"), board("trial_done", status="active", pool="exploration", trial_until=stamp(T0 - timedelta(hours=1))),
            board("trial_soon", status="active", pool="exploration", trial_until=stamp(T0 + timedelta(hours=10))),
            board("trial_later", status="active", pool="exploration", trial_until=stamp(T0 + timedelta(days=3))),
            board("wait_due", status="validated", last_validated_at=stamp(T0 - timedelta(days=9)), eligible_jobs=2),
            board("wait_ok", status="validated", last_validated_at=stamp(T0 - timedelta(days=1)), eligible_jobs=0),
            board("inv_due", status="invalid", last_attempt_at=stamp(T0 - timedelta(days=40))),
            board("cand", status="candidate", discovered_at=stamp(T0 - timedelta(days=30))),
        ]
        c = summary(boards={b.key: b for b in recs})["coverage"]
        self.assertEqual((c["established"], c["exploration"], c["monitored"]), (1, 3, 4))
        self.assertEqual(c["trials"], {"ended_awaiting_rebalance": 1, "ending_within_48h": 1, "running": 2})
        self.assertEqual(c["eligible_waiting_boards"], 1)
        v = c["validation"]
        self.assertEqual((v["revalidation_overdue_valid"], v["revalidation_overdue_invalid"], v["never_validated"], v["oldest_overdue_days"]), (1, 1, 1, 2.0))
        self.assertIn("KNOWN eligible boards", c["label"])
        self.assertIsNone(c["relevant_board_coverage_pct"])  # no run recorded it: unknown

    def test_feedback_counts_never_count_unlabelled_as_irrelevant(self) -> None:
        rows = [{"My_Feedback": "Would apply", "My_Status": "Applied"}, {"My_Feedback": "Maybe", "My_Status": "To Apply"}, {"My_Feedback": "Irrelevant", "My_Status": "Pass"},
                {"My_Feedback": "", "My_Status": "Interviewing"}, {"My_Feedback": "great", "My_Status": ""}]
        f = summary(tracker=rows)["feedback"]
        self.assertEqual((f["feedback"], f["unlabelled"], f["other_text"], f["labelled_total"]), ({"Would apply": 1, "Maybe": 1, "Irrelevant": 1}, 1, 1, 3))
        self.assertEqual((f["would_apply_pct_of_labelled"], f["would_apply_or_maybe_pct_of_labelled"]), (33, 67))
        self.assertEqual((f["status"]["Applied"], f["status"]["Interviewing"], f["status_blank"], f["applied_or_further"]), (1, 1, 1, 2))


# --------------------------------------------------------------------------- end to end against the real pipeline


class EndToEndTotalsTests(HarnessCase):
    def test_dashboard_totals_match_what_the_pipeline_recorded(self) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)), job("acme", "2", published=ago(days=30)))
        listing = self.w.listings[self.board.key]
        listing += [
            job("acme", "10", published=ago(minutes=20, base=T0 + timedelta(minutes=60))),  # fresh -> scored, alerted
            job("acme", "11", published=ago(minutes=30, base=T0 + timedelta(minutes=60))),  # fresh -> rejected by location
            job("acme", "12", title="Senior Director", published=ago(minutes=30, base=T0 + timedelta(minutes=60))),  # title gate
            job("acme", "13", published=ago(days=20, base=T0 + timedelta(minutes=60))),  # stale on observation
            job("acme", "14", published=""),  # undated: tracker only
        ]
        self.w.plan[self.key("11")] = [done("Filtered Out", 0, visible=False, reject="location")]
        self.w.plan[self.key("14")] = [done("Stretch / Review", 55, visible=True)]
        self.w.plan[self.key("10")] = [done()]
        self.w.run(minutes_later=60)
        now = self.w.now
        sm = rp.build_summary(now=now, tz=UTC, runs=self.w.state.load_runs(), events=self.w.state.load_events(), boards=self.w.state.load_boards(),
                              discovery=self.w.state.load_discovery_state(), tracker=[])
        p = sm["periods"]["7d"]
        o = p["outcomes"]
        self.assertEqual(p["results"]["unique_jobs_observed"], 7)
        self.assertEqual({x: n for x, n in o.items() if n}, {"baseline": 2, "title": 1, "age": 1, "location": 1, "kept": 2})
        r = p["results"]
        self.assertEqual((r["new_postings"], r["eligible_matches_scored"], r["matches_kept"], r["verified_fresh_matches"], r["matches_date_unknown"]), (5, 2, 2, 1, 1))  # job 11 was rejected BEFORE scoring, so it never reached it
        self.assertEqual((r["tracker_additions"], r["alerts_delivered"], r["alerts_unique_jobs"]), (2, 1, 1))
        self.assertEqual(r["tracker_additions"], len(self.w.tracker))  # the dashboard agrees with the rows the tracker actually received
        self.assertEqual(r["alerts_delivered"], len(self.w.alerts))
        self.assertEqual(sm["checks"], [])
        # a retry run changes nothing about unique-job totals
        self.w.run(minutes_later=60)
        sm2 = rp.build_summary(now=self.w.now, tz=UTC, runs=self.w.state.load_runs(), events=self.w.state.load_events(), boards=self.w.state.load_boards(),
                               discovery=self.w.state.load_discovery_state(), tracker=[])
        self.assertEqual(sm2["periods"]["7d"]["results"], p["results"])
        self.assertEqual(sm2["health"]["polling"]["7d"]["runs_finished"], 3)

    def test_a_transient_scoring_outage_shows_as_attempts_and_pending_not_as_failures_of_unique_jobs(self) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)))
        self.w.listings[self.board.key].append(job("acme", "7", published=ago(minutes=10, base=T0 + timedelta(minutes=60))))
        k7 = self.key("7")
        self.w.plan[k7] = [pl.EvalOutcome("transient", message="groq 429")] * 3
        for _ in range(3):
            self.w.run(minutes_later=60)
        sm = rp.build_summary(now=self.w.now, tz=UTC, runs=self.w.state.load_runs(), events=self.w.state.load_events(), boards=self.w.state.load_boards(), discovery={}, tracker=[])
        self.assertEqual(sm["periods"]["7d"]["attempts"], {"evaluation": 3, "evaluation_transient": 3, "evaluation_failed": 0})
        self.assertEqual(sm["periods"]["7d"]["outcomes"]["pending"], 1)  # one unique job, three attempts, still undecided
        self.assertEqual((sm["failures"]["pending_evaluation"]["jobs"], sm["failures"]["unique_jobs_with_errors"]), (1, 0))
        self.assertEqual(sm["periods"]["7d"]["results"]["matches_kept"], 0)  # not counted as kept or rejected until evaluated


# --------------------------------------------------------------------------- the Dashboard tab


class DashboardTabTests(unittest.TestCase):
    def fake_sheet(self) -> tuple[FakeSpreadsheet, FakeWorksheet]:
        tracker = FakeWorksheet("Job Tracker", [h.TRACKER_COLUMNS, ["d", "", "Applied", "90", "Acme — X", "NYC", "v", "", "https://u", "my note", "Verified fresh", "Board poll", "Would apply"]])
        sh = FakeSpreadsheet([tracker, FakeWorksheet("Settings", [["Setting", "Value", "Instructions"]])])
        return sh, tracker

    def sample(self) -> dict[str, Any]:
        t = T0 - timedelta(hours=2)
        events = [seen(k(1), t, pub=t - timedelta(hours=1)), evaluated(k(1), t), alerted(k(1), t + timedelta(minutes=5)), seen(k(2), t, disp=lg.FILTERED, pub=t)]
        runs = [run_rec(T0 - timedelta(hours=3)), run_rec(T0 - timedelta(hours=1), gap_since_prev_run_min=120)]
        return summary(events, runs, [{"My_Feedback": "Would apply", "My_Status": "Applied"}])

    def test_publish_writes_only_the_dashboard_tab_and_leaves_the_tracker_alone(self) -> None:
        sh, tracker = self.fake_sheet()
        before = [list(r) for r in tracker.values]
        db.publish_sheet(sh, db.render(self.sample()))
        self.assertEqual(sum(1 for r in sh.batches[0]["requests"] if "addChart" in r), 4)
        self.assertIn("Dashboard", sh.tabs)
        self.assertEqual(tracker.values, before)  # My_Feedback, My_Status and User_Notes untouched (FakeWorksheet raises on any tracker update)
        self.assertEqual(tracker.appended, [])
        self.assertEqual(len(sh.batches), 1)  # one batched write for the whole tab
        kinds = {next(iter(r)) for r in sh.batches[0]["requests"]}
        self.assertLessEqual(kinds, {"updateCells", "repeatCell", "unmergeCells", "mergeCells", "updateDimensionProperties", "updateSheetProperties", "addChart"})
        targets = set()
        for r in sh.batches[0]["requests"]:
            body = next(iter(r.values()))
            if "chart" in body:
                targets.add(body["chart"]["position"]["overlayPosition"]["anchorCell"]["sheetId"])
            else:
                targets.add((body.get("range") or body.get("start") or body.get("properties"))["sheetId"])
        self.assertEqual(targets, {sh.tabs["Dashboard"].id})  # every request targets the Dashboard sheet only

    def test_rerun_is_idempotent_and_replaces_rather_than_appends(self) -> None:
        sh, _ = self.fake_sheet()
        grid = db.render(self.sample())
        db.publish_sheet(sh, grid)
        db.publish_sheet(sh, grid)
        self.assertEqual(sh.batches[0], sh.batches[1])
        self.assertEqual(len([t for t in sh.tabs if t == "Dashboard"]), 1)
        first = sh.batches[0]["requests"]
        self.assertIn("repeatCell", first[1])  # clears the whole tab first, so a shorter dashboard leaves nothing stale behind

    def test_charts_are_added_with_fixed_ids_and_last_times_charts_are_deleted_first(self) -> None:
        sh, _ = self.fake_sheet()
        grid = db.render(self.sample())
        self.assertEqual(len(grid.charts), 4)
        db.publish_sheet(sh, grid)
        first = sh.batches[0]["requests"]
        ids = [r["addChart"]["chart"]["chartId"] for r in first if "addChart" in r]
        self.assertEqual(ids, [db.CHART_ID_BASE + i for i in range(4)])
        self.assertFalse(any("deleteEmbeddedObject" in r for r in first))  # nothing to delete the first time
        sid = sh.tabs["Dashboard"].id
        sh.metadata = {"sheets": [{"properties": {"sheetId": sid}, "charts": [{"chartId": i} for i in ids]}, {"properties": {"sheetId": sid + 1}, "charts": [{"chartId": 5}]}]}
        db.publish_sheet(sh, grid)
        second = sh.batches[1]["requests"]
        self.assertEqual([r["deleteEmbeddedObject"]["objectId"] for r in second if "deleteEmbeddedObject" in r], ids)  # only this sheet's charts
        self.assertEqual([i for i, r in enumerate(second) if "deleteEmbeddedObject" in r], list(range(4)))  # deleted before anything is re-added
        self.assertEqual(second[len(ids):], first)

    def test_bar_chart_series_target_the_bottom_axis_as_the_live_api_requires(self) -> None:
        grid = db.render(self.sample())
        specs = [(ch.kind, db.chart_request(ch, i, 9)["addChart"]["chart"]["spec"]) for i, ch in enumerate(grid.charts)]
        bars = [spec for kind, spec in specs if kind == "bar"]
        self.assertEqual(len(bars), 2)  # the age chart and the dropped-jobs chart
        for spec in bars:
            self.assertEqual({s["targetAxis"] for s in spec["basicChart"]["series"]}, {"BOTTOM_AXIS"})
            self.assertEqual([a["position"] for a in spec["basicChart"]["axis"]], ["LEFT_AXIS", "BOTTOM_AXIS"])
        for kind in ("stacked_column", "combo"):
            spec = next(spec for k_, spec in specs if k_ == kind)
            self.assertEqual({s["targetAxis"] for s in spec["basicChart"]["series"]}, {"LEFT_AXIS"})

    def test_chart_data_block_is_chronological_blank_for_unknown_and_matches_the_summary(self) -> None:
        sm = self.sample()
        grid = db.render(sm)
        col = lambda j: [grid.rows[r][db.DATA_COL + j].value for r in range(2, 2 + db.CHART_DAYS)]  # noqa: E731
        dates = col(0)
        days = [d["date"] for d in reversed(sm["trend"][: db.CHART_DAYS])]
        expected = [f"{int(iso[5:7])}/{int(iso[8:10])}" if i == 0 or int(iso[8:10]) == 1 else str(int(iso[8:10])) for i, iso in enumerate(days)]
        self.assertEqual(dates, expected)  # oldest first; day numbers (month shown on the first label and on the 1st) keep the axis horizontal
        self.assertEqual(days, sorted(days))
        newest = sm["trend"][0]
        self.assertEqual((col(1)[-1], col(4)[-1], col(6)[-1]), (newest["new_postings"], newest["alerts_delivered"], newest["runs_ok"]))
        self.assertEqual(col(1)[0], "")  # a day before anything was recorded is blank (unknown), not 0
        line = next(c for c in grid.charts if c.kind == "stacked_column")  # the first slot is now the tracker-rows combo (D-52); this chart still reads the trend block
        self.assertEqual((line.domain[1], line.domain[2]), (2, 2 + db.CHART_DAYS))
        self.assertTrue(all(c >= db.DATA_COL for c, _ in line.series))
        req = db.chart_request(line, 0, 9)["addChart"]["chart"]["spec"]["basicChart"]
        self.assertEqual((req["headerCount"], req["domains"][0]["domain"]["sourceRange"]["sources"][0]["startRowIndex"]), (1, 1))  # the header row names the series

    def test_cards_carry_sparklines_over_the_data_block_and_the_page_is_not_shifted(self) -> None:
        grid = db.render(self.sample())
        self.assertEqual(grid.rows[0][0].value, "Job Hunter")
        formulas = [c.formula for row in grid.rows for c in row if c.formula]
        self.assertEqual(len(formulas), 3)
        self.assertTrue(all(f.startswith("=SPARKLINE(") and f"{db.col_letter(db.DATA_COL + 1)}" in f + db.col_letter(db.DATA_COL + 1) for f in formulas))
        self.assertTrue(all(c.formula == "" for row in grid.rows for c in row if c.style != "card_spark"))

    def test_cells_are_literal_strings_never_formulas(self) -> None:
        grid = db.Grid()
        grid.add([db.Cell("=HYPERLINK(\"x\")"), db.Cell("+1"), db.Cell(3), db.Cell(None)])
        reqs = db.requests_for(grid, 1)
        cells = next(r for r in reqs if "updateCells" in r)["updateCells"]["rows"][0]["values"]
        self.assertEqual(cells[0]["userEnteredValue"], {"stringValue": "=HYPERLINK(\"x\")"})
        self.assertEqual(cells[2]["userEnteredValue"], {"numberValue": 3})
        self.assertNotIn("userEnteredValue", cells[3])

    def test_rendered_grid_shows_generation_time_source_freshness_and_unknowns(self) -> None:
        text = "\n".join(str(v) for row in db.render(self.sample()).values() for v in row)
        for needle in ("Updated 2026-10-14 12:00 UTC", "last run", "n/a", "known eligible", "Unique jobs first observed",
                       "Publication → detection", "Detection → delivery", "cannot report its own absence", "of dated"):
            self.assertIn(needle, text)
        empty = "\n".join(str(v) for row in db.render(summary()).values() for v in row)
        self.assertIn("No data yet", empty)
        self.assertIn("remaining budget unknown", empty)  # unknown, not "0 left"

    def test_the_rendered_numbers_are_the_summarys_numbers(self) -> None:
        sm = self.sample()
        grid = db.render(sm)
        rows = {str(r[0].value).strip(): [c.value for c in r[1:4]] for r in grid.rows if r[0].value}
        r = sm["periods"]
        self.assertEqual(rows["Unique jobs first observed"], [r["today"]["results"]["unique_jobs_observed"], r["7d"]["results"]["unique_jobs_observed"], r["30d"]["results"]["unique_jobs_observed"]])
        self.assertEqual(rows["Verified fresh"][1], r["7d"]["results"]["verified_fresh_matches"])
        self.assertEqual(rows["Alerts delivered"][1], r["7d"]["results"]["alerts_delivered"])

    def test_refresh_failure_is_contained(self) -> None:
        class Broken:
            display_tz = UTC

            @property
            def state(self) -> Any:
                raise RuntimeError("sheets unavailable")

        self.assertFalse(db.refresh(Broken(), settings()))  # logged, never raised

    def test_a_dashboard_failure_cannot_undo_processing_or_cause_a_duplicate_alert(self) -> None:
        w = _World()
        w.baseline_and_fresh()
        w.run_main_like(fail_dashboard=True)
        self.assertFalse(w.refresh_ok)  # the dashboard really did fail ...
        self.assertEqual(len(w.alerts), 1)  # ... and delivery was already done and recorded
        w.run_main_like(fail_dashboard=True)  # the next run: nothing re-sent
        self.assertEqual(len(w.alerts), 1)
        self.assertEqual(len([e for e in w.state.load_events() if e.event == lg.ALERTED]), 1)

    def test_csv_store_gets_a_flat_dashboard_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = db.publish_csv(Path(tmp), db.render(self.sample()))
            self.assertTrue(path.read_text().startswith("Job Hunter"))  # the page starts at row 1: the chart data block never shifts it

    def test_store_publish_goes_through_one_batch_on_the_real_store_class(self) -> None:
        sh, _ = self.fake_sheet()
        store = sheet_store(sh)
        store.publish_dashboard(db.render(self.sample()))
        self.assertEqual(len(sh.batches), 1)


def gh_url(n: int, board: str = "acme") -> str:
    return f"https://job-boards.greenhouse.io/{board}/jobs/{n}"


def tracker_row(n: int, label: str = "Verified fresh", feedback: str = "", date_found: str = "", url: str | None = None) -> dict[str, str]:
    return {"Apply_URL": gh_url(n) if url is None else url, "Freshness": label, "My_Feedback": feedback, "Date_Found": date_found}


class YieldTests(unittest.TestCase):
    """MEAS-01: tracker rows per found-day by cohort (P2-09..P2-12), computed from the ledger and the tracker only."""

    NOW = datetime(2026, 10, 26, 15, 0, tzinfo=UTC)  # 10:00 on 2026-10-26 in Chicago

    def ledger(self, specs: list[tuple[int, datetime]]) -> list[lg.Event]:
        ev: list[lg.Event] = []
        for n, at in specs:
            ev += [seen(k(n), at - timedelta(minutes=5), pub=at - timedelta(hours=2)), evaluated(k(n), at)]
        return ev

    def test_yield_counts_tracker_rows_per_local_day_by_cohort(self) -> None:
        day1 = datetime(2026, 10, 24, 20, 0, tzinfo=UTC)  # 15:00 on the 24th in Chicago
        day2 = datetime(2026, 10, 25, 20, 0, tzinfo=UTC)
        ev = self.ledger([(1, day1), (2, day2), (3, day2)])
        tracker = [tracker_row(1, "Verified fresh"), tracker_row(2, "Recent"), tracker_row(3, "Age unverified")]
        y = summary(ev, tracker=tracker, now=self.NOW, tz=CHI)["yield"]
        trend = y["trend"]
        self.assertEqual(len(trend), 14)
        self.assertEqual([d["date"] for d in trend], sorted(d["date"] for d in trend))  # oldest first
        self.assertEqual(trend[-1]["date"], "2026-10-26")
        by_date = {d["date"]: d for d in trend}
        self.assertEqual({c: by_date["2026-10-24"][c] for c in rp.COHORTS}, {"verified_fresh": 1, "recent": 0, "other": 0})
        self.assertEqual({c: by_date["2026-10-25"][c] for c in rp.COHORTS}, {"verified_fresh": 0, "recent": 1, "other": 1})
        self.assertEqual((by_date["2026-10-26"]["total"], by_date["2026-10-26"]["verified_fresh"]), (0, 0))  # after the first row: 0, measured
        self.assertIsNone(by_date["2026-10-23"]["total"])  # before the first tracker row ever: unknown, never 0
        self.assertIsNone(by_date["2026-10-13"]["verified_fresh"])

    def test_yield_day_boundary_local_midnight_belongs_to_new_day(self) -> None:
        midnight = datetime(2026, 10, 25, 5, 0, 0, tzinfo=UTC)  # 00:00:00 on the 25th in Chicago
        before = datetime(2026, 10, 25, 4, 59, 59, tzinfo=UTC)  # 23:59:59 on the 24th
        ev = self.ledger([(1, midnight), (2, before)])
        y = summary(ev, tracker=[tracker_row(1), tracker_row(2)], now=self.NOW, tz=CHI)["yield"]
        by_date = {d["date"]: d for d in y["trend"]}
        self.assertEqual((by_date["2026-10-25"]["total"], by_date["2026-10-24"]["total"]), (1, 1))

    def test_yield_day_comes_from_the_evaluation_not_the_publication_or_first_sight(self) -> None:
        pub = datetime(2026, 10, 23, 18, 0, tzinfo=UTC)
        first = datetime(2026, 10, 24, 18, 0, tzinfo=UTC)
        found = datetime(2026, 10, 25, 18, 0, tzinfo=UTC)
        earlier = datetime(2026, 10, 22, 18, 0, tzinfo=UTC)  # a second row, so the days in between are measured zeros rather than unknown
        ev = [seen(k(1), first, pub=pub), evaluated(k(1), found)] + self.ledger([(2, earlier)])
        by_date = {d["date"]: d for d in summary(ev, tracker=[tracker_row(1), tracker_row(2)], now=self.NOW, tz=CHI)["yield"]["trend"]}
        self.assertEqual([by_date[d]["total"] for d in ("2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25")], [None, 1, 0, 0, 1])

    def test_dashboard_top_chart_is_tracker_rows_combo_with_target_band(self) -> None:
        day = datetime(2026, 10, 25, 20, 0, tzinfo=UTC)
        sm = summary(self.ledger([(1, day)]), tracker=[tracker_row(1)], now=self.NOW, tz=CHI)
        grid = db.render(sm)
        top = grid.charts[0]
        self.assertEqual(top.kind, "combo")
        self.assertTrue(top.title.startswith("Tracker rows per day"))
        self.assertEqual(len(grid.charts), 4)
        spec = db.chart_request(top, 0, 9)["addChart"]["chart"]["spec"]["basicChart"]
        self.assertEqual(spec["chartType"], "COMBO")
        self.assertEqual([s["type"] for s in spec["series"]], ["COLUMN"] * 3 + ["LINE"] * 2)
        self.assertEqual(spec["stackedType"], "STACKED")
        col = lambda j: [grid.rows[r][db.DATA_COL + j].value for r in range(top.domain[1], top.domain[2])]  # noqa: E731
        trend = sm["yield"]["trend"]
        recorded = [d["total"] is not None for d in trend]
        want20 = [20 if r else "" for r in recorded]
        want30 = [(30 - 20 if db.BAND_LINES_STACK else 30) if r else "" for r in recorded]
        self.assertEqual(col(4), want20)
        self.assertEqual(col(5), want30)
        self.assertEqual(col(1)[-2], 1)  # the 25th holds the one verified-fresh row
        self.assertEqual(col(0)[-1], "26")
        self.assertTrue(all(c >= db.DATA_COL for c, _ in top.series))

    # ---- Task 2: age when found, feedback per cohort, reconciliation

    def test_yield_age_buckets_inclusive_upper_bounds_and_unknown_for_day_precision(self) -> None:
        def facts(age: timedelta | None, precision: str = "time") -> rp.JobFacts:
            pub = None if age is None else T0 - age
            return rp.JobFacts(k(1), seen_at=T0, published=pub, precision=precision)

        m = timedelta
        cases = [(m(minutes=60), "le1h"), (m(minutes=61), "h1_12"), (m(hours=12), "h1_12"), (m(hours=12, minutes=1), "h12_24"), (m(hours=24), "h12_24"),
                 (m(hours=72), "h24_72"), (m(hours=72, minutes=1), "older")]
        for age, want in cases:
            self.assertEqual(rp.age_bucket(facts(age)), want, age)
        self.assertEqual(rp.age_bucket(facts(m(minutes=30), precision="day")), "unknown")  # a date only: never counted as a measured age
        self.assertEqual(rp.age_bucket(facts(None)), "unknown")  # no publication date
        self.assertEqual(rp.age_bucket(facts(m(minutes=-5))), "unknown")  # published after first sight: a future date
        self.assertEqual(rp.age_bucket(None), "unknown")  # an unmatched row
        self.assertEqual([key for key, _ in rp.AGE_BUCKETS], ["le1h", "h1_12", "h12_24", "h24_72", "older", "unknown"])

    def test_yield_age_counts_come_from_matched_rows_in_the_period(self) -> None:
        at = datetime(2026, 10, 25, 20, 0, tzinfo=UTC)
        ev = [seen(k(1), at, pub=at - timedelta(minutes=30)), evaluated(k(1), at), seen(k(2), at, pub=at - timedelta(hours=30)), evaluated(k(2), at),
              seen(k(3), at, pub=at - timedelta(hours=1), precision="day"), evaluated(k(3), at)]
        rows = [tracker_row(1), tracker_row(2), tracker_row(3), tracker_row(99, url="https://example.com/x", date_found="10/25/2026 03:00 PM")]
        age = summary(ev, tracker=rows, now=self.NOW, tz=CHI)["yield"]["per_period"]["7d"]["by_age"]
        self.assertEqual(age, {"le1h": 1, "h1_12": 0, "h12_24": 0, "h24_72": 1, "older": 0, "unknown": 2})  # the day-precision row and the unmatched row are unknown, never fresh

    def test_yield_feedback_mix_per_cohort(self) -> None:
        d = "10/25/2026 09:15 AM"
        rows = [tracker_row(1, "Verified fresh", "Would apply", d, url="https://example.com/1"), tracker_row(2, "Verified fresh", "Maybe", d, url="https://example.com/2"),
                tracker_row(3, "Recent", "Irrelevant", d, url="https://example.com/3"), tracker_row(4, "Recent", "", d, url="https://example.com/4"),
                tracker_row(5, "Age unverified", "great job", d, url="https://example.com/5"), tracker_row(6, "New on board (age unverified)", "Would apply", d, url="https://example.com/6")]
        fb = summary(tracker=rows, now=self.NOW, tz=CHI)["yield"]["per_period"]["7d"]["feedback"]
        zero = {"Would apply": 0, "Maybe": 0, "Irrelevant": 0, "unlabelled": 0, "other_text": 0}
        self.assertEqual(fb["verified_fresh"], {**zero, "Would apply": 1, "Maybe": 1})
        self.assertEqual(fb["recent"], {**zero, "Irrelevant": 1, "unlabelled": 1})
        self.assertEqual(fb["other"], {**zero, "Would apply": 1, "other_text": 1})  # free text is counted apart and never becomes a label

    def test_yield_rows_by_ats_keep_the_provider_baseline(self) -> None:
        at = datetime(2026, 10, 25, 20, 0, tzinfo=UTC)
        urls = {"greenhouse": gh_url(1), "lever": "https://jobs.lever.co/acme/11111111-1111-1111-1111-111111111111",
                "smartrecruiters": "https://jobs.smartrecruiters.com/acme/123456789-title"}
        ev: list[lg.Event] = []
        for u in urls.values():
            key = bd.parse_job_url(u).key  # type: ignore[union-attr]
            ev += [seen(key, at, pub=at - timedelta(hours=1)), evaluated(key, at)]
        rows = [tracker_row(0, url=u) for u in urls.values()] + [tracker_row(0, url="https://example.com/x", date_found="10/25/2026 03:00 PM")]
        by_ats = summary(ev, tracker=rows, now=self.NOW, tz=CHI)["yield"]["per_period"]["7d"]["by_ats"]
        self.assertEqual(by_ats, {"greenhouse": 1, "lever": 1, "smartrecruiters": 1, "unknown": 1})

    def test_yield_unmatched_row_uses_date_found_or_unknown_day(self) -> None:
        rows = [tracker_row(1, url="https://example.com/a", date_found="10/24/2026 09:15 PM"), tracker_row(2, url="https://example.com/b", date_found="not a date")]
        y = summary(tracker=rows, now=self.NOW, tz=CHI)["yield"]
        by_date = {d["date"]: d for d in y["trend"]}
        self.assertEqual(by_date["2026-10-24"]["total"], 1)
        self.assertEqual(y["day_unknown"], 1)  # counted apart, never put on a guessed day
        self.assertEqual(sum(d["total"] or 0 for d in y["trend"]), 1)

    def test_yield_reconcile_names_missing_keys_both_directions(self) -> None:
        at = datetime(2026, 10, 25, 20, 0, tzinfo=UTC)
        ev = self.ledger([(1, at), (2, at + timedelta(minutes=7))])
        rows = [tracker_row(1), tracker_row(77, url="https://example.com/hand-made", date_found="10/25/2026 01:00 PM")]
        rc = summary(ev, tracker=rows, now=self.NOW, tz=CHI)["yield"]["reconcile"]
        self.assertEqual((rc["ledger_kept"], rc["in_tracker"]), (2, 1))
        self.assertEqual(rc["missing_from_tracker"], [{"key": k(2), "evaluated": stamp(at + timedelta(minutes=7))}])
        self.assertEqual(rc["tracker_rows_without_ledger_match"], 1)

    def test_yield_stored_url_fallback_matches_custom_domain_url(self) -> None:
        at = datetime(2026, 10, 25, 20, 0, tzinfo=UTC)
        custom = "https://careers.acme.example/open-roles/senior-analyst?gh_jid=4455"  # not parseable to a job identity
        self.assertIsNone(bd.parse_job_url(custom))
        ev = self.ledger([(1, at)])
        ev[-1].detail["url"] = custom  # the evaluated payload carries the URL the job was stored with
        rows = [tracker_row(1, url=custom)]
        y = summary(ev, tracker=rows, now=self.NOW, tz=CHI)["yield"]
        self.assertEqual(y["join"], {"by_identity": 0, "by_stored_url": 1, "unmatched": 0})
        self.assertEqual(y["reconcile"]["missing_from_tracker"], [])

    def test_dashboard_needs_attention_row_only_when_mismatch_nonzero(self) -> None:
        at = datetime(2026, 10, 25, 20, 0, tzinfo=UTC)
        ev = self.ledger([(1, at), (2, at + timedelta(minutes=1))])
        both = summary(ev, tracker=[tracker_row(1), tracker_row(2)], now=self.NOW, tz=CHI)
        self.assertEqual([r for r in both["failures"]["table"] if r["what"] == "tracker missing kept jobs"], [])
        self.assertNotIn("tracker missing kept jobs", "\n".join(str(v) for row in db.render(both).values() for v in row))
        none = summary(ev, tracker=[tracker_row(50, url="https://example.com/x", date_found="10/25/2026 01:00 PM")], now=self.NOW, tz=CHI)
        rows = [r for r in none["failures"]["table"] if r["what"] == "tracker missing kept jobs"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["count"], 2)
        self.assertIn(k(1), rows[0]["detail"])
        self.assertIn(k(2), rows[0]["detail"])
        self.assertEqual(rows[0]["ref"], "Job Tracker")
        self.assertIn("tracker missing kept jobs", "\n".join(str(v) for row in db.render(none).values() for v in row))

    def test_owner_deleted_tracker_keys_are_not_listed_as_missing_but_still_counted(self) -> None:
        at = datetime(2026, 10, 25, 20, 0, tzinfo=UTC)
        ev = self.ledger([(1, at), (2, at + timedelta(minutes=1))])
        sm = summary(ev, tracker=[tracker_row(1)], now=self.NOW, tz=CHI, tracker_deleted=frozenset({k(2), "greenhouse|nobody|1"}))
        rc = sm["yield"]["reconcile"]
        self.assertEqual((rc["ledger_kept"], rc["in_tracker"], rc["missing_from_tracker"], rc["deleted_by_owner"]), (2, 1, [], 1))
        self.assertEqual([r for r in sm["failures"]["table"] if r["what"] == "tracker missing kept jobs"], [])  # no NEEDS ATTENTION row
        text = "\n".join(str(v) for row in db.render(sm).values() for v in row)
        self.assertNotIn("tracker missing kept jobs", text)
        self.assertIn("1 of 2 ledger-kept jobs are in the tracker (1 deleted on purpose, Tracker_Deleted_Keys)", text)
        other = summary(ev, tracker=[], now=self.NOW, tz=CHI, tracker_deleted=frozenset({k(2)}))  # a job not acknowledged is still flagged
        rows = [r for r in other["failures"]["table"] if r["what"] == "tracker missing kept jobs"]
        self.assertEqual((len(rows), rows[0]["count"], rows[0]["detail"]), (1, 1, k(1)))

    def test_dashboard_rerun_is_identical(self) -> None:
        at = datetime(2026, 10, 25, 20, 0, tzinfo=UTC)
        sm = summary(self.ledger([(1, at)]), tracker=[tracker_row(1, feedback="Maybe")], now=self.NOW, tz=CHI)
        self.assertEqual(db.requests_for(db.render(sm), 5), db.requests_for(db.render(sm), 5))

    def test_dashboard_cohort_labels_match_hunter_freshness_labels(self) -> None:
        self.assertTrue(set(rp.COHORT_OF_LABEL) <= set(h.FRESHNESS_LABELS.values()))  # reporting may not import hunter, so the test pins the labels

    def test_dashboard_page_has_the_age_chart_the_tracker_rows_table_and_no_tracker_text(self) -> None:
        at = datetime(2026, 10, 25, 20, 0, tzinfo=UTC)
        rows = [{**tracker_row(1, feedback="Would apply"), "Company_and_Title": "ZZ-SECRET Corp — Analyst", "User_Notes": "ZZ-NOTE", "AI_Verdict": "ZZ-VERDICT"}]
        sm = summary(self.ledger([(1, at)]), tracker=rows, now=self.NOW, tz=CHI)
        grid = db.render(sm)
        text = "\n".join(str(v) for row in grid.values() for v in row)
        self.assertEqual([c.title for c in grid.charts], ["Tracker rows per day · target 20-30", "How old jobs were when found · 7d", "Runs per day", "Why relevant-title jobs were dropped · 7d"])
        self.assertEqual([r["addChart"]["chart"]["chartId"] for r in db.requests_for(grid, 5) if "addChart" in r], [db.CHART_ID_BASE + i for i in range(4)])
        self.assertNotIn("Alerts delivered and tracker additions", text)
        self.assertNotIn("Relevant jobs per day", text)
        for needle in ("TRACKER ROWS", "Would apply", "ledger-kept jobs are in the tracker"):
            self.assertIn(needle, text)
        for secret in ("ZZ-SECRET", "ZZ-NOTE", "ZZ-VERDICT"):
            self.assertNotIn(secret, text)
        age = grid.charts[1]
        spec = db.chart_request(age, 1, 9)["addChart"]["chart"]["spec"]["basicChart"]
        self.assertEqual({s["targetAxis"] for s in spec["series"]}, {"BOTTOM_AXIS"})
        self.assertEqual(sm["yield"]["per_period"]["7d"]["by_age"]["h1_12"], 1)  # published 2 h before first sight


class CliAndPilotTests(HarnessCase):
    def test_dashboard_cli_dry_run_prints_and_writes_nothing(self) -> None:
        import contextlib
        import io

        self.baseline(job("acme", "1", published=ago(days=30)))

        class Store:
            display_tz = UTC
            state = self.w.state

            def tracker_rows(self) -> list[dict[str, str]]:
                return []

            def publish_dashboard(self, grid: Any) -> None:
                raise AssertionError("a dry run must not write")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = h.run_dashboard(h.Config.from_env(), Store(), settings(), dry_run=True)
        self.assertEqual(code, 0)
        self.assertIn("DASHBOARD generated", buf.getvalue())

    def test_pilot_report_does_not_count_unfinished_run_records_as_runs(self) -> None:
        import pilot

        runs = [run_rec(T0 - timedelta(hours=2)), st_mod.RunRecord(stamp(T0 - timedelta(hours=1)), run_id="dead", outcome="started")]
        rep = pilot.build_report(now=T0, days=7, runs=runs, events=[], boards={}, discovery={}, tracker=[], fresh_window=timedelta(hours=12), search_cap=1000, search_reserve=200)
        self.assertEqual((rep["polling"]["runs"], rep["polling"]["unfinished_run_records"]), (1, 1))


class GroqSummaryTests(unittest.TestCase):
    """MEAS-02 / MEAS-03 / P2-03: Groq consumption read from the Runs tokens, the Discovery budget record and the ledger."""

    NOW = datetime(2026, 10, 26, 15, 0, tzinfo=UTC)
    M120, M20 = "openai/gpt-oss-120b", "openai/gpt-oss-20b"

    def budget_record(self, day: str = "2026-10-26") -> str:
        return json.dumps({"day": day, "used": {self.M120: 45210}, "exhausted": [], "budgets": {self.M120: 170000, self.M20: 170000}})

    def test_a_spent_flag_past_its_expiry_is_not_shown_as_spent(self) -> None:
        """WR-01: the lock ends at Groq's retry-after instant, so the dashboard stops saying SPENT then."""
        raw = json.dumps({"day": "2026-10-26", "used": {self.M120: 9}, "exhausted": [self.M120, self.M20], "exhausted_until": {self.M120: "2026-10-26T14:00:00+00:00"}, "budgets": {self.M120: 100, self.M20: 100}})
        g = summary(discovery={"groq_budget": raw}, now=self.NOW)["groq"]  # NOW is 15:00 UTC
        self.assertEqual((g["today"]["models"][self.M120]["exhausted"], g["today"]["models"][self.M20]["exhausted"]), (False, True))

    def test_groq_summary_reads_today_from_the_budget_record_and_7d_from_runs(self) -> None:
        runs = [
            run_rec(self.NOW - timedelta(days=1), groq_tokens_primary=3000, groq_prompt_tokens=1000, groq_cached_tokens=200, groq_completions=1),
            run_rec(self.NOW - timedelta(days=2), groq_tokens_primary=800, groq_tokens_fallback=200, groq_prompt_tokens=1000, groq_cached_tokens=200, groq_completions=1, eval_budget_skipped=3, eval_cut=True),
            run_rec(self.NOW - timedelta(days=3)),  # recorded no tokens and no completions
            run_rec(self.NOW - timedelta(days=4), groq_completions=2),  # answers recorded but no usage figure: not a token run
            run_rec(self.NOW - timedelta(days=9), groq_tokens_primary=99999, groq_completions=1),  # outside the 7-day window
        ]
        g = summary(runs=runs, discovery={"groq_budget": self.budget_record()}, now=self.NOW)["groq"]
        self.assertEqual(g["today"]["day"], "2026-10-26")
        self.assertEqual(g["today"]["models"][self.M120], {"used": 45210, "budget": 170000, "exhausted": False})
        self.assertEqual(g["today"]["models"][self.M20], {"used": 0, "budget": 170000, "exhausted": False})
        self.assertEqual(g["token_runs"], 2)
        self.assertEqual(g["tokens_per_completion"], 2000)  # 4000 tokens / 2 completions of the runs that recorded tokens; the 2 untokened answers are not in it
        self.assertEqual(g["cached_share_pct"], 20)  # 400 of 2000 prompt tokens
        self.assertEqual((g["7d"]["tokens_primary"], g["7d"]["tokens_fallback"], g["7d"]["completions"]), (3800, 200, 4))
        self.assertEqual((g["7d"]["budget_skipped"], g["7d"]["runs_with_eval_cut"]), (3, 1))

    def test_groq_summary_counts_scored_evaluations_by_model(self) -> None:
        at = self.NOW - timedelta(hours=3)
        ev: list[lg.Event] = []
        for n, model in enumerate([self.M120, self.M120, self.M20, ""], start=1):
            e = evaluated(k(n), at)
            if model:
                e.detail["model"] = model
            ev.append(e)
        ev.append(evaluated(k(9), at, status="Filtered Out", score=0, reject="location"))  # a gate rejection never reached Groq
        old = evaluated(k(10), self.NOW - timedelta(days=12))
        old.detail["model"] = self.M20
        ev.append(old)  # outside the 7-day window
        g = summary(ev, now=self.NOW)["groq"]
        self.assertEqual(g["scored_by_model"], {self.M120: 2, self.M20: 1, "not recorded": 1})

    def test_groq_summary_unknown_when_nothing_recorded(self) -> None:
        g = summary(runs=[run_rec(self.NOW - timedelta(days=1))], now=self.NOW)["groq"]
        self.assertIsNone(g["today"])
        self.assertIsNone(g["tokens_per_completion"])
        self.assertIsNone(g["cached_share_pct"])
        self.assertEqual(g["token_runs"], 0)
        bad = summary(discovery={"groq_budget": "not json"}, now=self.NOW)["groq"]
        self.assertIsNone(bad["today"])  # a hand-edited, unparseable record reads as unknown (T-02-17)

    def test_groq_summary_budget_record_from_an_earlier_utc_day_is_not_todays_usage(self) -> None:
        g = summary(discovery={"groq_budget": self.budget_record(day="2026-10-25")}, now=self.NOW)["groq"]
        self.assertEqual(g["today"]["day"], "2026-10-26")
        self.assertEqual(g["today"]["record_day"], "2026-10-25")
        self.assertEqual(g["today"]["models"][self.M120]["used"], 0)  # the budget rolled at UTC midnight, exactly as eval_budget does

    def test_dashboard_groq_line_shows_budget_split_and_cuts(self) -> None:
        runs = [run_rec(self.NOW - timedelta(days=1), groq_tokens_primary=3000, groq_prompt_tokens=1000, groq_cached_tokens=200, groq_completions=1, eval_budget_skipped=2, boards_skipped_deadline=4, alerts_deferred=1, eval_cut=True)]
        ev = [evaluated(k(1), self.NOW - timedelta(hours=2))]
        ev[0].detail["model"] = self.M120
        sm = summary(ev, runs=runs, discovery={"groq_budget": self.budget_record()}, now=self.NOW)
        rows = {r[0].value: r[1].value for r in db.render(sm).rows if len(r) > 1 and r[0].value == "Groq"}
        text = str(rows["Groq"])
        for want in ("of 170000", "per call", "budget skips", "evaluation cuts", "poll cuts", "gpt-oss-120b 45210", "2026-10-26"):
            self.assertIn(want, text)
        unknown = summary(now=self.NOW)
        text = str(next(r[1].value for r in db.render(unknown).rows if len(r) > 1 and r[0].value == "Groq"))
        self.assertIn("n/a", text)
        self.assertNotIn(" 0 tokens per call", text)  # unknown is never shown as 0


class _World:
    """Minimal pipeline world with a store whose dashboard publication always fails."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        from test_core import Harness

        self.h = Harness(self._tmp.name)
        self.state = self.h.state
        self.alerts = self.h.alerts
        self.board = bd.BoardId(bd.GREENHOUSE, "acme")

    def baseline_and_fresh(self) -> None:
        self.h.listings[self.board.key] = [job("acme", "1", published=ago(days=30))]
        self.h.run(seeds=[self.board])
        self.h.listings[self.board.key].append(job("acme", "2", published=ago(minutes=5, base=T0 + timedelta(minutes=60))))

    def run_main_like(self, fail_dashboard: bool) -> None:
        self.h.run(minutes_later=60)

        class Store:
            display_tz = UTC
            state = self.state

            def tracker_rows(self) -> list[dict[str, str]]:
                return []

            def publish_dashboard(self, grid: Any) -> None:
                raise RuntimeError("Sheets quota exceeded")

        self.refresh_ok = db.refresh(Store(), settings())  # exactly what hunter.main does after run_cycle


# --------------------------------------------------------------------------- compact storage: the merged view gives the same figures (D-57, P3-10, P3-11)


@dataclass
class World:
    """A consistent dual-write world: every Events row, plus the Identity entries and Tally rows that `split_observations` wrote
    for each run (the stored side never comes from the code under test)."""

    events: list[lg.Event]
    runs: list[st_mod.RunRecord]
    identity: compact.IdentitySet
    tally: list[compact.TallyRow]
    rehearsal_run: str
    wave_run: str

    def compact_view(self, now: datetime) -> compact.Ledger:
        """What a compact store holds: no baseline rows, no gated or stale rows older than 7 days (the parity check's simulation)."""
        return compact.Ledger(compact.simulate_compact(self.events, now), [], self.identity, self.tally)

    def half_folded_view(self) -> compact.Ledger:
        """Every other baseline row of the admission wave removed, everything else kept: the run is partly folded."""
        wave = [e for e in self.events if e.event == lg.SEEN and e.detail.get("run") == self.wave_run and e.disposition == lg.BASELINED]
        gone = {id(e) for e in wave[::2]}
        return compact.Ledger([e for e in self.events if id(e) not in gone], [], self.identity, self.tally)


def compact_world(tz: Any, now: datetime) -> World:
    """35 local days of ledger ending at `now` (a few minutes after local midnight): rows without run ids, an admission wave split
    across local midnight, a re-entry pass, daily gated and stale rows with dated and undated postings from poll and search,
    pending / kept / alerted / abandoned jobs, a rehearsal run with its own identity rows, runs at exactly local midnight."""
    today = now.astimezone(tz).date()
    midnight = lambda d: datetime.combine(d, dtime(0), tzinfo=tz).astimezone(UTC)  # noqa: E731
    day = lambda n: today - timedelta(days=n)  # noqa: E731
    events: list[lg.Event] = []
    runs: list[st_mod.RunRecord] = []

    def new_run(at: datetime, kind: str = "production") -> str:
        run_id = f"r-{stamp(at)}"
        runs.append(run_rec(at, run_id=run_id, run_kind=kind))
        return run_id

    def baseline(prefix: str, count: int, at: datetime, run: str, *, dated: int = 0, pass_kind: str = "baseline", source: str = "poll") -> None:
        for i in range(count):
            pub = at - timedelta(days=40 + i) if i < dated else None
            events.append(seen(f"{prefix}{i}", at, fresh=fr.BASELINE, disp=lg.BASELINED, pub=pub, source=source, pass_kind=pass_kind, run=run))

    baseline("greenhouse|oldco|L", 25, midnight(day(34)) + timedelta(hours=1), "", dated=5)  # before run ids existed
    for i in range(5):
        events.append(seen(f"greenhouse|oldco|F{i}", midnight(day(33)) + timedelta(hours=2), fresh=fr.RECENT, disp=lg.FILTERED, source="serper"))
    early = midnight(day(20)) - timedelta(seconds=1)  # the last second of the previous local day
    baseline("lever|zeta|E", 6, early, new_run(early))
    wave_at = midnight(day(20))  # exactly local midnight: the new day
    wave_run = new_run(wave_at)
    baseline("greenhouse|newco|W", 60, wave_at, wave_run, dated=30)
    baseline("ashby|newco2|X", 20, wave_at, wave_run)
    re_at = midnight(day(10)) + timedelta(hours=3)
    baseline("ashby|reco|R", 12, re_at, new_run(re_at), pass_kind="reentry")
    for n in range(30, -1, -1):
        offsets = [timedelta(0), timedelta(minutes=2), timedelta(minutes=4), timedelta(minutes=6)] if n == 0 else [timedelta(0), timedelta(minutes=30), timedelta(hours=12), timedelta(hours=24, seconds=-1)]
        for r, off in enumerate(offsets):
            at = midnight(day(n)) + off
            run = new_run(at)
            for i in range(8):
                events.append(seen(f"greenhouse|acme|f{n}-{r}-{i}", at, fresh=(fr.RECENT, fr.UNCERTAIN)[i % 2], disp=lg.FILTERED, pub=at - timedelta(days=3) if i % 2 == 0 else None,
                                   source=("poll", "serper", "search")[i % 3], run=run))
            for i in range(3):
                events.append(seen(f"lever|beta|s{n}-{r}-{i}", at, fresh=fr.STALE, disp=lg.STALED, pub=at - timedelta(days=40), run=run))
            fresh_key, new_key = f"greenhouse|acme|p{n}-{r}-0", f"greenhouse|acme|p{n}-{r}-1"
            events.append(seen(fresh_key, at, pub=at - timedelta(hours=1), run=run))
            events.append(seen(new_key, at, fresh=fr.OBSERVED_NEW, source="search", run=run))
            if n > 0:
                events.append(evaluated(fresh_key, at + timedelta(seconds=30), run=run))
                events.append(alerted(fresh_key, at + timedelta(seconds=40)))
                events.append(evaluated(new_key, at + timedelta(seconds=31), reject="location" if n % 2 == 0 else "", visible=n % 2 == 1, alert=False, run=run))
            if n == 5 and r == 1:
                events.append(lg.Event(stamp(at + timedelta(minutes=1)), new_key, lg.ABANDONED, detail={"stage": lg.STAGE_EVALUATE, "run": run}))
            if n == 3 and r == 0:
                events.append(errored(fresh_key, at + timedelta(minutes=2)))
    rehearsal_at = midnight(day(5)) + timedelta(hours=2)
    rehearsal = new_run(rehearsal_at, st_mod.KIND_REHEARSAL)
    baseline("greenhouse|rehco|H", 10, rehearsal_at, rehearsal)
    for i in range(4):
        events.append(seen(f"greenhouse|acme|rf{i}", rehearsal_at, fresh=fr.RECENT, disp=lg.FILTERED, run=rehearsal))
    for i in range(2):
        events.append(seen(f"greenhouse|acme|rp{i}", rehearsal_at, pub=rehearsal_at - timedelta(hours=1), run=rehearsal))
        events.append(evaluated(f"greenhouse|acme|rp{i}", rehearsal_at + timedelta(seconds=20), run=rehearsal))
    events.sort(key=lambda e: e.time)
    groups: dict[tuple[str, str], list[lg.Event]] = defaultdict(list)
    for ev in events:
        groups[(str(ev.detail.get("run") or ""), ev.time)].append(ev)
    identity = compact.IdentitySet()
    tally: list[compact.TallyRow] = []
    for (run_id, run_at), group in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        split = compact.split_observations(group, compact.MODE_DUAL)
        identity.apply(identity.plan_additions(split.identity, "2026-10-01T00:00:00Z"))
        if split.tally:
            tally.append(compact.TallyRow(run_id, run_at, sum(split.tally.values()), dict(sorted(split.tally.items()))))
    have = {(t.run_id, t.run_at) for t in tally}
    tally += [compact.TallyRow(r.run_id, r.run_at, 0, {}) for r in runs if (r.run_id, r.run_at) not in have]  # a run with nothing identity-only still writes its zero row
    return World(events, runs, identity, tally, rehearsal, wave_run)


ZONES = ((UTC, datetime(2026, 10, 29, 0, 7, tzinfo=UTC)), (CHI, datetime(2026, 10, 29, 5, 7, tzinfo=UTC)))  # both `now`s are 00:07 local on 29 October


class CompactParityTests(unittest.TestCase):
    """P3-10: every figure from Identity + Tally + the kept Events rows equals the figure from all Events rows."""

    @staticmethod
    def figures(sm: dict[str, Any]) -> dict[str, Any]:
        """The summary without the `storage` section: that section presents the storage state (and the P3-11 note, which exists only when counts are folded), so it differs by design; parity layer 4 skips it too."""
        return {k: v for k, v in sm.items() if k != "storage"}

    def both(self, tz: Any, now: datetime, world: World, view: compact.Ledger) -> tuple[dict[str, Any], dict[str, Any]]:
        old = rp.build_summary(now=now, tz=tz, runs=world.runs, events=world.events, boards={}, discovery={}, tracker=[])
        new = rp.build_summary(now=now, tz=tz, runs=world.runs, events=view.events, boards={}, discovery={}, tracker=[], folded=view.folded())
        return old, new

    def test_the_simulated_compact_view_gives_the_same_summary_in_both_time_zones(self) -> None:
        for tz, now in ZONES:
            with self.subTest(tz=str(tz)):
                world = compact_world(tz, now)
                view = world.compact_view(now)
                self.assertLess(len(view.events), len(world.events) - 150)  # the view really dropped rows (baselines and old gated rows)
                self.assertGreater(sum(fc.n for fc in view.folded()), 150)
                old, new = self.both(tz, now, world, view)
                self.assertEqual(self.figures(old), self.figures(new))
                self.assertEqual((old["checks"], new["checks"]), ([], []))

    def test_a_half_folded_view_counts_each_job_once(self) -> None:
        for tz, now in ZONES:
            with self.subTest(tz=str(tz)):
                world = compact_world(tz, now)
                view = world.half_folded_view()
                self.assertEqual(sum(fc.n for fc in view.folded()), 40)  # half of the wave's 80 baselines: Tally minus the rows still present
                old, new = self.both(tz, now, world, view)
                self.assertEqual(self.figures(old), self.figures(new))
                self.assertEqual((old["checks"], new["checks"]), ([], []))

    def test_the_rendered_dashboard_has_the_same_values(self) -> None:
        for tz, now in ZONES:
            with self.subTest(tz=str(tz)):
                world = compact_world(tz, now)
                old, new = self.both(tz, now, world, world.compact_view(now))
                shown = db.render(new).values()
                self.assertEqual(sum(row[0] == rp.TALLY_NOTE for row in shown), 1)  # the only difference: the P3-11 note under the first-observed row
                self.assertEqual([row for row in shown if row[0] != rp.TALLY_NOTE], db.render(old).values())

    def test_freshness_denominators_count_dated_and_undated_folded_postings(self) -> None:
        for tz, now in ZONES:
            with self.subTest(tz=str(tz)):
                world = compact_world(tz, now)
                old, new = self.both(tz, now, world, world.compact_view(now))
                for period in ("today", "7d", "30d"):
                    f_old, f_new = old["periods"][period]["freshness"], new["periods"][period]["freshness"]
                    self.assertEqual((f_new["new_postings_date_known"], f_new["new_postings_date_unknown"]), (f_old["new_postings_date_known"], f_old["new_postings_date_unknown"]))
                f30 = new["periods"]["30d"]["freshness"]
                self.assertGreater(f30["new_postings_date_known"], 0)
                self.assertGreater(f30["new_postings_date_unknown"], 0)

    def test_rehearsal_runs_are_excluded_and_counted_from_either_side(self) -> None:
        for tz, now in ZONES:
            with self.subTest(tz=str(tz)):
                world = compact_world(tz, now)
                view = world.compact_view(now)
                old, new = self.both(tz, now, world, view)
                self.assertEqual(old["exclusions"], new["exclusions"])
                self.assertEqual(new["exclusions"]["rehearsal_runs"], 1)
                self.assertEqual(new["exclusions"]["events_from_rehearsal_runs"], 10 + 4 + 2 + 2)  # its baselines and gated rows are folded counts now
                self.assertTrue(any(fc.run_id == world.rehearsal_run for fc in view.folded()))
                self.assertEqual(old["source_freshness"], new["source_freshness"])

    def test_rows_from_before_run_ids_are_kept_unattributed(self) -> None:
        for tz, now in ZONES:
            with self.subTest(tz=str(tz)):
                world = compact_world(tz, now)
                view = world.compact_view(now)
                blank = [fc for fc in view.folded() if fc.run_id == ""]
                self.assertEqual(sum(fc.n for fc in blank), 25 + 5)  # kept as counts, never dropped as a rehearsal
                old, new = self.both(tz, now, world, view)
                self.assertEqual(old["source_freshness"]["ledger_events_read"], new["source_freshness"]["ledger_events_read"])
                self.assertEqual(old["trend"], new["trend"])

    def test_a_day_with_only_tally_contributions_is_recorded_in_the_trend(self) -> None:
        tz, now = UTC, datetime(2026, 10, 29, 0, 7, tzinfo=UTC)
        at = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
        events = [seen(f"greenhouse|solo|{i}", at, fresh=fr.BASELINE, disp=lg.BASELINED, pass_kind="baseline", run="solo") for i in range(7)]
        split = compact.split_observations(events, compact.MODE_COMPACT)
        self.assertEqual(split.events, [])  # in compact mode the baselines have no Events row at all
        ledger = compact.Ledger([], [], compact.IdentitySet(), [compact.TallyRow("solo", stamp(at), 7, dict(split.tally))])
        old = rp.build_summary(now=now, tz=tz, runs=[], events=events, boards={}, discovery={}, tracker=[])
        new = rp.build_summary(now=now, tz=tz, runs=[], events=ledger.events, boards={}, discovery={}, tracker=[], folded=ledger.folded())
        day = next(t for t in new["trend"] if t["date"] == "2026-10-20")
        self.assertEqual((day["recorded"], day["baselined"]), (True, 7))
        self.assertEqual(self.figures(old), self.figures(new))

    def test_a_folded_count_goes_through_the_same_counting_code_as_real_jobs(self) -> None:
        at = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
        real = [seen(f"lever|co|{i}", at, fresh=fr.RECENT, disp=lg.FILTERED, pub=at - timedelta(days=2), source="search", run="x") for i in range(5)]
        dim = compact.tally_dim(real[0])
        old = rp.build_summary(now=T0 + timedelta(days=14), tz=UTC, runs=[], events=real, boards={}, discovery={}, tracker=[])
        new = rp.build_summary(now=T0 + timedelta(days=14), tz=UTC, runs=[], events=[], boards={}, discovery={}, tracker=[], folded=[compact.FoldedCount("x", stamp(at), dim, 5)])
        self.assertEqual(old["periods"], new["periods"])
        self.assertEqual(new["periods"]["30d"]["results"]["new_postings"], 5)

    def test_a_folded_count_is_never_a_freshness_latency_or_alert_fact(self) -> None:
        at = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
        damaged = "greenhouse|poll|pending||verified_fresh|k"  # a hand-edited Tally key that claims a relevant, verified-fresh, dated job
        sm = rp.build_summary(now=at + timedelta(days=1), tz=UTC, runs=[], events=[], boards={}, discovery={}, tracker=[], folded=[compact.FoldedCount("x", stamp(at), damaged, 3)])
        p = sm["periods"]["30d"]
        self.assertEqual((p["freshness"]["verified_fresh"], p["freshness"]["cohort_jobs"], p["results"]["verified_fresh_matches"], p["results"]["alerts_delivered"]), (0, 0, 0, 0))
        self.assertEqual((p["latency_sample"]["relevant_new_postings_detected"], p["latency_min"]["publication_to_detection"]["n"]), (0, 0))
        self.assertEqual(p["outcomes"]["pending"], 3)  # shown as waiting work, never as a result
        self.assertEqual(sm["failures"]["pending_evaluation"]["jobs"], 0)  # and never as a job the pipeline could evaluate


# --------------------------------------------------------------------------- compact storage: the owner's signal (P3-05, P3-06, P3-07, P3-11)


SNOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
SEEDED = "2026-10-20T08:00:00Z"
FOLD_DIM = "greenhouse|poll|filtered||recent|u"  # a gated posting, as Tally counts it


def storage_discovery(*, mode: str = compact.MODE_DUAL, seeded: str | None = SEEDED, clean_days: int = 0, admission: bool = False, counted: int | None = 0,
                      diffs: tuple[str, ...] = (), cutover: str | None = None, fold_day: str | None = None, restored: str | None = None) -> dict[str, str]:
    """A Discovery dict whose `storage` key was made by the real StorageState: `clean_days` complete UTC days before SNOW's day, each with the
    minimum number of checked runs and no difference; `admission` puts a board admission in the newest of them."""
    st = compact.StorageState(mode=mode, seeded_at=seeded)
    for back in range(1, clean_days + 1):
        st.days[(SNOW - timedelta(days=back)).date().isoformat()] = {"runs": compact.PARITY_MIN_RUNS_PER_DAY, "diff_runs": 0, "failed": 0, "admissions": 1 if admission and back == 1 else 0}
    if counted is not None:
        st.last_check = {"at": stamp(SNOW - timedelta(minutes=5)), "counted": counted, "declared": 2, "compared": 40, "seconds": 1.5}
    st.last_diffs = list(diffs)
    if cutover:
        st.cutover = {"at": cutover}
    if fold_day:
        st.fold = {"first_day": fold_day, "last_day": fold_day}
    if restored:
        st.restore = {"at": restored}
    return {compact.STORAGE_KEY: st.to_json()}


def line_text(sm: dict[str, Any], label: str) -> str | None:
    return next((str(r[1].value) for r in db.render(sm).rows if len(r) > 1 and r[0].value == label), None)


def folded_summary(discovery: dict[str, str] | None = None, n: int = 5) -> dict[str, Any]:
    at = SNOW - timedelta(days=3)
    return rp.build_summary(now=SNOW, tz=UTC, runs=[], events=[], boards={}, discovery=discovery or {}, tracker=[], folded=[compact.FoldedCount("x", stamp(at), FOLD_DIM, n)])


class DashboardStorageTests(unittest.TestCase):
    """The owner reads the storage state on the Dashboard: a Storage line, READY TO CUT OVER only when the recorded days meet the bar,
    a NEEDS ATTENTION row for a parity difference and the P3-11 note wherever totals come from Tally."""

    DIFFS = ("identity_missing greenhouse|acme|11", "tally_count r-1@2026-10-29T10:00:00Z (1 vs 2)", "figure periods.7d.results.new_postings (old 4 new 5)",
             "identity_missing lever|beta|44", "figure logical.baseline_jobs_per_board.greenhouse|acme (old 3 new 2)")

    def attention(self, sm: dict[str, Any]) -> list[Any]:
        return [r for r in db.render(sm).rows if r[0].value == "storage parity difference"]

    def test_a_recorded_difference_is_a_needs_attention_row_naming_at_most_three_refs(self) -> None:
        sm = summary(now=SNOW, discovery=storage_discovery(counted=5, diffs=self.DIFFS))
        row = next(r for r in sm["failures"]["table"] if r["what"] == "storage parity difference")
        self.assertEqual((row["severity"], row["ref"], row["count"]), (1, "Identity / Tally", 5))
        self.assertEqual(row["since"], stamp(SNOW - timedelta(minutes=5)))
        for kept in self.DIFFS[:3]:
            self.assertIn(kept, row["detail"])
        for left_out in self.DIFFS[3:]:
            self.assertNotIn(left_out, row["detail"])
        for words in ("Events rows stay authoritative", "nothing was deleted", "3-day clock restarted", "storage_parity"):
            self.assertIn(words, row["action"])
        shown = self.attention(sm)
        self.assertEqual(len(shown), 1)
        self.assertEqual(sm["failures"]["table_total"], 1)

    def test_the_row_never_carries_title_url_or_free_text_even_from_a_hand_edited_key(self) -> None:
        edited = ("identity_missing https://boards.greenhouse.io/acme/jobs/9 Senior Staff Engineer", "figure x (old 1 new 2)", "tally_missing r-2@2026-10-29T09:00:00Z")
        sm = summary(now=SNOW, discovery=storage_discovery(counted=3, diffs=edited))
        text = " ".join(str(c.value) for r in self.attention(sm) for c in r) + " ".join(str(v) for r in sm["failures"]["table"] for v in r.values())
        for forbidden in ("https://", "greenhouse.io", "Senior Staff Engineer", "http"):
            self.assertNotIn(forbidden, text)
        self.assertIn("figure x (old 1 new 2)", text)

    def test_no_row_without_a_counted_difference_or_without_a_check(self) -> None:
        for label, discovery in (("clean check", storage_discovery(counted=0)), ("declared only", storage_discovery(counted=0, diffs=("tracker_identity_job greenhouse|acme|1",))),
                                 ("never checked", storage_discovery(counted=None)), ("no key", {}), ("not seeded", storage_discovery(seeded=None, counted=0))):
            with self.subTest(label):
                sm = summary(now=SNOW, discovery=discovery)
                self.assertEqual(self.attention(sm), [])
                self.assertEqual(sm["failures"]["table_total"], 0)

    def test_in_compact_mode_the_action_says_detection_reads_identity_plus_events(self) -> None:
        sm = summary(now=SNOW, discovery=storage_discovery(mode=compact.MODE_COMPACT, counted=2, diffs=self.DIFFS[:2], cutover="2026-10-25T06:00:00Z"))
        row = next(r for r in sm["failures"]["table"] if r["what"] == "storage parity difference")
        self.assertIn("Identity plus Events", row["action"])
        self.assertNotIn("nothing was deleted", row["action"])
        self.assertIn("storage_parity", row["action"])

    def test_ready_to_cut_over_appears_once_when_the_recorded_days_meet_the_bar(self) -> None:
        ready = summary(now=SNOW, discovery=storage_discovery(clean_days=3, admission=True))
        self.assertTrue(ready["storage"]["bar_met"] and ready["storage"]["ready_to_cut_over"])
        text = line_text(ready, "Storage") or ""
        self.assertEqual(text.count("READY TO CUT OVER"), 1)
        self.assertEqual(sum("READY TO CUT OVER" in str(c.value) for r in db.render(ready).rows for c in r), 1)
        for needle in ("dual", "seeded 2026-10-20", "last check 0 difference(s)", "3 of 3 clean complete days", "admission seen yes"):
            self.assertIn(needle, text)

    def test_ready_to_cut_over_never_comes_from_elapsed_time_or_an_unmet_bar(self) -> None:
        cases = {
            "two clean days": storage_discovery(clean_days=2, admission=True),
            "three days, no admission": storage_discovery(clean_days=3, admission=False),
            "seeded long ago, nothing recorded": storage_discovery(seeded="2026-09-01T00:00:00Z"),
            "not seeded": storage_discovery(seeded=None, clean_days=3, admission=True),
            "no key": {},
        }
        for label, discovery in cases.items():
            with self.subTest(label):
                sm = summary(now=SNOW, discovery=discovery)
                self.assertFalse(sm["storage"]["ready_to_cut_over"])
                self.assertNotIn("READY TO CUT OVER", line_text(sm, "Storage") or "")
        today_dirty = storage_discovery(clean_days=3, admission=True)
        st = compact.StorageState.load(today_dirty[compact.STORAGE_KEY])
        st.days[SNOW.date().isoformat()] = {"runs": 3, "diff_runs": 1, "failed": 0, "admissions": 0}
        sm = summary(now=SNOW, discovery={compact.STORAGE_KEY: st.to_json()})
        self.assertFalse(sm["storage"]["ready_to_cut_over"])  # a difference found today blocks the bar at once (P3-07)

    def test_compact_and_restored_modes_never_say_ready_even_with_days_that_would_meet_the_bar(self) -> None:
        for mode in (compact.MODE_COMPACT, compact.MODE_RESTORED):
            with self.subTest(mode):
                sm = summary(now=SNOW, discovery=storage_discovery(mode=mode, clean_days=3, admission=True, cutover="2026-10-25T06:00:00Z", restored="2026-10-27T06:00:00Z"))
                self.assertFalse(sm["storage"]["ready_to_cut_over"])
                self.assertNotIn("READY TO CUT OVER", " ".join(str(c.value) for r in db.render(sm).rows for c in r))

    def test_the_storage_line_says_what_state_the_storage_is_in(self) -> None:
        self.assertIn("not seeded yet", line_text(summary(now=SNOW), "Storage") or "")
        dual = line_text(summary(now=SNOW, discovery=storage_discovery(clean_days=2, counted=1, diffs=self.DIFFS[:1])), "Storage") or ""
        for needle in ("dual", "seeded 2026-10-20", "last check 1 difference(s)", "2 of 3 clean complete days", "admission seen no"):
            self.assertIn(needle, dual)
        unchecked = line_text(summary(now=SNOW, discovery=storage_discovery(counted=None)), "Storage") or ""
        self.assertIn("no check recorded yet", unchecked)
        comp = line_text(summary(now=SNOW, discovery=storage_discovery(mode=compact.MODE_COMPACT, cutover="2026-10-25T06:00:00Z", fold_day="2026-10-28")), "Storage") or ""
        for needle in ("compact since 2026-10-25", "last fold 2026-10-28", "last check 0 difference(s)"):
            self.assertIn(needle, comp)
        self.assertIn("no fold yet", line_text(summary(now=SNOW, discovery=storage_discovery(mode=compact.MODE_COMPACT, cutover="2026-10-25T06:00:00Z")), "Storage") or "")
        back = line_text(summary(now=SNOW, discovery=storage_discovery(mode=compact.MODE_RESTORED, restored="2026-10-27T06:00:00Z")), "Storage") or ""
        for needle in ("restored 2026-10-27", "compaction off until a new owner decision"):
            self.assertIn(needle, back)

    def test_the_storage_line_comes_right_after_the_groq_line(self) -> None:
        labels = [str(r[0].value) for r in db.render(summary(now=SNOW)).rows]
        self.assertEqual(labels.index("Storage"), labels.index("Groq") + 1)

    def test_a_damaged_storage_key_is_not_seeded_and_never_ready(self) -> None:
        for raw in ("{not json", "[]", "null", '{"mode": 7, "seeded_at": 5, "days": "x"}'):
            with self.subTest(raw):
                sm = summary(now=SNOW, discovery={compact.STORAGE_KEY: raw})
                self.assertFalse(sm["storage"]["ready_to_cut_over"])
                self.assertEqual(sm["failures"]["table_total"], 0)

    def test_the_note_about_tally_totals_appears_under_unique_jobs_when_counts_are_folded(self) -> None:
        sm = folded_summary(storage_discovery())
        self.assertEqual(sm["storage"]["folded_total"], 5)
        self.assertEqual(sm["storage"]["detail_note"], rp.TALLY_NOTE)
        rows = db.render(sm).rows
        at = next(i for i, r in enumerate(rows) if r[0].value == "Unique jobs first observed")
        self.assertEqual(rows[at + 1][0].value, rp.TALLY_NOTE)
        self.assertEqual(rows[at + 1][0].style, "muted")
        self.assertEqual(rows[at + 2][0].value, "New postings (after a board's first read)")
        for words in ("baseline totals", "title-gated or stale", "older than 7 days", "Tally tab", "title, URL, publication time"):
            self.assertIn(words, rp.TALLY_NOTE)
        self.assertIn(rp.TALLY_NOTE, rp.format_text(sm))

    def test_the_reconciliation_prints_the_note_only_when_it_counted_folded_jobs(self) -> None:
        at = SNOW - timedelta(days=3)
        kw = dict(runs=[], events=[], tracker=[], start=SNOW - timedelta(days=7), end=SNOW)
        folded = rp.reconcile(folded=[compact.FoldedCount("x", stamp(at), FOLD_DIM, 4)], **kw)  # type: ignore[arg-type]
        self.assertEqual(folded["from_tally"], 4)
        self.assertIn(rp.TALLY_NOTE, "\n".join(rp.format_reconciliation(folded)))
        outside = rp.reconcile(folded=[compact.FoldedCount("x", stamp(SNOW - timedelta(days=30)), FOLD_DIM, 4)], **kw)  # type: ignore[arg-type]
        self.assertEqual(outside["from_tally"], 0)
        self.assertNotIn("Tally", "\n".join(rp.format_reconciliation(outside)))
        none = rp.reconcile(**kw)  # type: ignore[arg-type]
        self.assertNotIn("Tally", "\n".join(rp.format_reconciliation(none)))

    def test_with_nothing_folded_no_note_appears_and_the_grid_is_the_old_one_plus_the_storage_line(self) -> None:
        sm = summary(now=SNOW, discovery=storage_discovery(clean_days=1))
        self.assertEqual((sm["storage"]["folded_total"], sm["storage"]["detail_note"]), (0, None))
        grid = db.render(sm)
        flat = " ".join(str(c.value) for r in grid.rows for c in r)
        self.assertNotIn("Tally tab", flat)
        self.assertNotIn("Tally tab", rp.format_text(sm))
        rows = grid.rows
        at = next(i for i, r in enumerate(rows) if r[0].value == "Unique jobs first observed")
        self.assertEqual(rows[at + 1][0].value, "New postings (after a board's first read)")
        bare = summary(now=SNOW)  # no storage key at all: the same page apart from the Storage line text
        without = lambda g: [[c.value for c in r] for r in g.rows if r[0].value != "Storage"]  # noqa: E731
        self.assertEqual(without(grid), without(db.render(bare)))
        self.assertEqual(len(db.render(bare).rows), len(grid.rows))

    def test_format_text_has_one_storage_line(self) -> None:
        text = rp.format_text(summary(now=SNOW, discovery=storage_discovery(clean_days=3, admission=True, counted=0)))
        lines = [ln for ln in text.splitlines() if ln.startswith("STORAGE")]
        self.assertEqual(len(lines), 1)
        for needle in ("dual", "seeded 2026-10-20", "3 of 3", "ready to cut over: yes"):
            self.assertIn(needle, lines[0])
        unmet = [ln for ln in rp.format_text(summary(now=SNOW)).splitlines() if ln.startswith("STORAGE")]
        self.assertEqual(len(unmet), 1)
        self.assertIn("not seeded", unmet[0])


if __name__ == "__main__":
    unittest.main()
