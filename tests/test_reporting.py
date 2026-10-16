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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import boards as bd  # noqa: E402
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
            boards: dict[str, bd.BoardRecord] | None = None, discovery: dict[str, str] | None = None, now: datetime = T0, tz: Any = UTC) -> dict[str, Any]:
    return rp.build_summary(now=now, tz=tz, runs=runs or [], events=events or [], boards=boards or {}, discovery=discovery or {}, tracker=tracker or [])


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

    def evaluate(self, s: Any, p: Any) -> h.Evaluation:
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
        self.assertEqual(len(sh.batches[0]["requests"][-6:]), 6)
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
        self.assertEqual(len(grid.charts), 6)
        db.publish_sheet(sh, grid)
        first = sh.batches[0]["requests"]
        ids = [r["addChart"]["chart"]["chartId"] for r in first if "addChart" in r]
        self.assertEqual(ids, [db.CHART_ID_BASE + i for i in range(6)])
        self.assertFalse(any("deleteEmbeddedObject" in r for r in first))  # nothing to delete the first time
        sid = sh.tabs["Dashboard"].id
        sh.metadata = {"sheets": [{"properties": {"sheetId": sid}, "charts": [{"chartId": i} for i in ids]}, {"properties": {"sheetId": sid + 1}, "charts": [{"chartId": 5}]}]}
        db.publish_sheet(sh, grid)
        second = sh.batches[1]["requests"]
        self.assertEqual([r["deleteEmbeddedObject"]["objectId"] for r in second if "deleteEmbeddedObject" in r], ids)  # only this sheet's charts
        self.assertEqual([i for i, r in enumerate(second) if "deleteEmbeddedObject" in r], list(range(6)))  # deleted before anything is re-added
        self.assertEqual(second[6:], first)

    def test_bar_chart_series_target_the_bottom_axis_as_the_live_api_requires(self) -> None:
        grid = db.render(self.sample())
        specs = {ch.kind: db.chart_request(ch, i, 9)["addChart"]["chart"]["spec"] for i, ch in enumerate(grid.charts)}
        self.assertEqual({s["targetAxis"] for s in specs["bar"]["basicChart"]["series"]}, {"BOTTOM_AXIS"})
        self.assertEqual([a["position"] for a in specs["bar"]["basicChart"]["axis"]], ["LEFT_AXIS", "BOTTOM_AXIS"])
        self.assertEqual({s["targetAxis"] for s in specs["column"]["basicChart"]["series"]}, {"LEFT_AXIS"})

    def test_chart_data_block_is_chronological_blank_for_unknown_and_matches_the_summary(self) -> None:
        sm = self.sample()
        grid = db.render(sm)
        col = lambda j: [grid.rows[r][db.DATA_COL + j].value for r in range(3, 3 + db.CHART_DAYS)]  # noqa: E731
        dates = col(0)
        self.assertEqual(dates, sorted(dates))  # oldest first
        self.assertEqual(dates[-1], sm["trend"][0]["date"][5:])
        newest = sm["trend"][0]
        self.assertEqual((col(1)[-1], col(4)[-1], col(6)[-1]), (newest["new_postings"], newest["alerts_delivered"], newest["runs_ok"]))
        self.assertEqual(col(1)[0], "")  # a day before anything was recorded is blank (unknown), not 0
        line = grid.charts[0]
        self.assertEqual((line.domain[1], line.domain[2]), (3, 3 + db.CHART_DAYS))
        self.assertTrue(all(c >= db.DATA_COL for c, _ in line.series))
        req = db.chart_request(line, 0, 9)["addChart"]["chart"]["spec"]["basicChart"]
        self.assertEqual((req["headerCount"], req["domains"][0]["domain"]["sourceRange"]["sources"][0]["startRowIndex"]), (1, 2))  # the header row names the series

    def test_cards_carry_sparklines_over_the_data_block_and_the_page_is_not_shifted(self) -> None:
        grid = db.render(self.sample())
        self.assertEqual(grid.rows[0][0].value, "Job Hunter · Operations")
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
        for needle in ("Updated 2026-10-14 12:00:00 UTC", "last run record", "last ledger event", "n/a", "KNOWN eligible boards", "Unique jobs first observed",
                       "Publication → detection", "Detection → delivery", "Days 8 to 30", "watchdog", "of dated"):
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
        self.assertEqual(rows["verified fresh"][1], r["7d"]["results"]["verified_fresh_matches"])
        self.assertEqual(rows["Alerts delivered (events)"][1], r["7d"]["results"]["alerts_delivered"])
        self.assertEqual(rows["Jobs first observed"][1], r["7d"]["results"]["unique_jobs_observed"])

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


if __name__ == "__main__":
    unittest.main()
