"""Offline tests for the board-polling core: freshness, identity, ledger, gates, pipeline failures.

Mocked end to end: fake ATS listings, fake scorer, fake alert channel. Persistence is the real
CSV-backed state in a temp dir. See STATUS.md for what has been verified live.
"""

from __future__ import annotations

import collections
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import boards as bd  # noqa: E402
import discovery as dsc  # noqa: E402
import eligibility as el  # noqa: E402
import freshness as fr  # noqa: E402
import hunter as h  # noqa: E402
import ledger as lg  # noqa: E402
import pipeline as pl  # noqa: E402
import state as st_mod  # noqa: E402

T0 = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


def ago(minutes: int = 0, hours: int = 0, days: int = 0, base: datetime = T0) -> str:
    return (base - timedelta(minutes=minutes, hours=hours, days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_settings() -> h.Settings:
    with mock.patch.dict(os.environ):
        for k in h.SETTING_DEFAULTS:
            os.environ.pop(k.upper(), None)
        return h.Settings.from_values({"Resume_Text": "r" * 300})


S = default_settings()
EXCLUDED = h.excluded_title_regex(S.excluded)


def gate(title: str) -> str | None:
    return el.title_gate(title, S.roles, S.levels, EXCLUDED)


def job(board: str, jid: str, title: str = "Marketing Intern", published: str = "", field: str = "", updated: str = "",
        location: str = "Remote", ats: str = bd.GREENHOUSE) -> bd.ListedJob:
    ident = bd.JobIdentity(ats, board, jid)
    return bd.ListedJob(ident, title, ident.url, location, published, field or ("first_published" if published else ""), updated)


def done(status: str = "To Apply", score: int = 88, visible: bool = True, **kw: Any) -> pl.EvalOutcome:
    payload = {"status": status, "score": score, "company": "Acme", "title": "Marketing Intern", "location": "Remote",
               "verdict": "Good fit.", "gaps": "None", "url": "https://u", "posted": "", "visible": visible}
    return pl.EvalOutcome("done", dict(payload, **kw))


class Harness:
    """A fake world around the real pipeline and the real (CSV) state store."""

    def __init__(self, tmp: str) -> None:
        self.state = st_mod.CsvState(Path(tmp) / "state")
        self.state.ensure()  # the real entry point always creates the state files first
        self.now = T0
        self.listings: dict[str, Any] = {}  # board key -> list[ListedJob] | Exception
        self.tracker: list[dict[str, Any]] = []
        self.tracked_keys: set[str] = set()  # persists across runs, like the real tracker tab
        self.alerts: list[dict[str, Any]] = []
        self.alert_error: Exception | None = None
        self.alert_result: bool = True  # what send_alert returns when no error is set: False = no channel accepted the message
        self.alert_calls = 0
        self.tracker_error: Exception | None = None
        self.plan: dict[str, list[pl.EvalOutcome]] = {}
        self.calls: collections.Counter[str] = collections.Counter()
        self.discover_result: Any = None

    def fetch(self, board: bd.BoardId) -> list[bd.ListedJob]:
        v = self.listings[board.key]
        if isinstance(v, Exception):
            raise v
        return v

    def evaluate(self, ident: bd.JobIdentity, st: lg.JobState) -> pl.EvalOutcome:
        self.calls[st.key] += 1
        seq = self.plan.get(st.key)
        if seq:
            return seq.pop(0) if len(seq) > 1 else seq[0]
        return done()

    def append_tracker(self, payloads: list[dict[str, Any]]) -> None:
        if self.tracker_error:
            raise self.tracker_error
        self.tracker.extend(payloads)

    def send_alert(self, payload: dict[str, Any]) -> bool:
        self.alert_calls += 1
        if self.alert_error:
            raise self.alert_error
        if self.alert_result:
            self.alerts.append(payload)
        return self.alert_result

    def run(self, minutes_later: int = 0, seeds: list[bd.BoardId] | None = None, **kw: Any) -> st_mod.RunRecord:
        self.now = self.now + timedelta(minutes=minutes_later)
        kw.setdefault("sleep", lambda seconds: None)  # no real waiting for validation backoff / per-host spacing
        deps = pl.Deps(
            state=self.state, tracked_keys=self.tracked_keys, append_tracker=self.append_tracker, evaluate=self.evaluate,
            send_alert=self.send_alert, title_gate=gate, fetch=self.fetch, now=lambda: self.now,
            seeds=seeds or [], discover=kw.pop("discover", None), **kw,
        )  # fmt: skip
        return pl.run_cycle(deps)

    def events(self, key: str | None = None, kind: str | None = None) -> list[lg.Event]:
        return [e for e in self.state.load_events() if (key is None or e.key == key) and (kind is None or e.event == kind)]

    def states(self) -> dict[str, lg.JobState]:
        return lg.replay(self.state.load_events())


class HarnessCase(unittest.TestCase):
    board = bd.BoardId(bd.GREENHOUSE, "acme")

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.w = Harness(self._tmp.name)

    def key(self, jid: str, ats: str = bd.GREENHOUSE, board: str = "acme") -> str:
        return bd.JobIdentity(ats, board, jid).key

    def baseline(self, *jobs: bd.ListedJob) -> None:
        """First poll of the board (baselining), then move 60 minutes on."""
        self.w.listings[self.board.key] = list(jobs)
        self.w.run(seeds=[self.board])

    def fresh_setup(self) -> str:
        """Baseline a board, then list one job published 10 minutes before the next run; returns its key."""
        self.baseline(job("acme", "1", published=ago(days=30)))
        self.w.listings[self.board.key].append(job("acme", "7", published=ago(minutes=10, base=T0 + timedelta(minutes=60))))
        return self.key("7")


# --------------------------------------------------------------------------- freshness


class ClassifyTests(unittest.TestCase):
    def cls(self, published: str, *, gap_min: int | None = 60, baselined: bool = True, baseline_pass: bool = False, **kw: Any) -> str:
        dt, prec = fr.parse_instant(published)
        gap = timedelta(minutes=gap_min) if gap_min is not None else None
        return fr.classify(dt, prec, now=kw.pop("now", T0), board_gap=gap, board_baselined=baselined, baseline_pass=baseline_pass, **kw).cls

    def test_time_precision_inside_and_outside_window(self) -> None:
        self.assertEqual(self.cls(ago(minutes=30)), fr.VERIFIED_FRESH)
        self.assertEqual(self.cls(ago(hours=11, minutes=59)), fr.VERIFIED_FRESH)
        noon30 = T0 + timedelta(minutes=90)  # 13:30, so "12 h ago" (01:30) is a real time of day, not midnight
        self.assertEqual(self.cls("2026-10-14T01:30:00Z", now=noon30), fr.VERIFIED_FRESH)  # the boundary itself is inside the window
        self.assertEqual(self.cls("2026-10-14T01:29:59Z", now=noon30), fr.RECENT)  # one second past it is not
        self.assertEqual(self.cls(ago(hours=12, minutes=1)), fr.RECENT)
        self.assertEqual(self.cls(ago(hours=4, minutes=1)), fr.VERIFIED_FRESH)  # the old 4 h boundary no longer matters
        self.assertEqual(self.cls(ago(days=3)), fr.RECENT)
        self.assertEqual(self.cls(ago(days=15)), fr.STALE)

    def test_fresh_by_timestamp_does_not_need_a_board_gap(self) -> None:
        self.assertEqual(self.cls(ago(minutes=10), gap_min=None, baselined=False), fr.VERIFIED_FRESH)

    def test_day_precision_needs_board_gap_evidence(self) -> None:
        self.assertEqual(self.cls("2026-10-14", gap_min=60), fr.VERIFIED_FRESH)  # Workable: today + seen right after the last poll
        self.assertEqual(self.cls("2026-10-14", gap_min=720), fr.VERIFIED_FRESH)  # gap exactly at the window
        self.assertEqual(self.cls("2026-10-14", gap_min=721), fr.RECENT)  # we did not poll recently: cannot claim fresh
        self.assertEqual(self.cls("2026-10-14", gap_min=None, baselined=False), fr.RECENT)
        self.assertEqual(self.cls("2026-10-01", gap_min=60), fr.RECENT)  # old date contradicts "just appeared"

    def test_midnight_utc_timestamps_count_as_day_precision(self) -> None:
        self.assertEqual(fr.parse_instant("2026-10-14T00:00:00.000Z")[1], fr.DAY)

    def test_no_date_is_never_verified(self) -> None:
        self.assertEqual(self.cls("", gap_min=60), fr.OBSERVED_NEW)
        self.assertEqual(self.cls("", gap_min=720), fr.OBSERVED_NEW)
        self.assertEqual(self.cls("", gap_min=721), fr.UNCERTAIN)
        self.assertEqual(self.cls("", gap_min=None, baselined=False), fr.UNCERTAIN)

    def test_baseline_pass_only_trusts_source_timestamps(self) -> None:
        noon30 = T0 + timedelta(minutes=90)
        self.assertEqual(self.cls(ago(days=40), baselined=False, baseline_pass=True), fr.BASELINE)
        self.assertEqual(self.cls("", baselined=False, baseline_pass=True), fr.BASELINE)
        self.assertEqual(self.cls("2026-10-14", baselined=False, baseline_pass=True), fr.BASELINE)  # day precision cannot prove 12h
        self.assertEqual(self.cls(ago(minutes=30), baselined=False, baseline_pass=True), fr.VERIFIED_FRESH)
        self.assertEqual(self.cls("2026-10-14T01:30:00Z", baselined=False, baseline_pass=True, now=noon30), fr.VERIFIED_FRESH)  # baseline exception follows the window
        self.assertEqual(self.cls("2026-10-14T01:29:59Z", baselined=False, baseline_pass=True, now=noon30), fr.BASELINE)
        self.assertEqual(self.cls(ago(hours=11, minutes=59), baselined=False, baseline_pass=True), fr.VERIFIED_FRESH)
        self.assertEqual(self.cls(ago(hours=5), baselined=False, baseline_pass=True, fresh_window=timedelta(hours=4)), fr.BASELINE)  # explicit override honoured

    def test_future_dates_are_not_trusted(self) -> None:
        self.assertEqual(self.cls(ago(hours=-5)), fr.UNCERTAIN)
        self.assertEqual(self.cls(ago(minutes=-30)), fr.UNCERTAIN)  # aggregators stamp postings ahead of real time
        self.assertEqual(self.cls(ago(minutes=-3)), fr.VERIFIED_FRESH)  # within normal clock skew

    def test_update_is_never_publication(self) -> None:
        self.assertEqual(fr.detect_changes(None, "a", None, "b"), ["updated"])
        pub = fr.parse_instant(ago(days=2))[0]
        later = fr.parse_instant(ago(minutes=5))[0]
        self.assertEqual(fr.detect_changes(pub, "x", later, "x"), ["republished"])
        self.assertEqual(fr.detect_changes(pub, "x", pub, "x"), [])

    def test_lever_epoch_string_and_ms(self) -> None:
        self.assertEqual(fr.parse_instant("1791564186023")[1], fr.TIME)
        self.assertEqual(fr.parse_instant(1791564186023)[0], fr.parse_instant("1791564186023")[0])


# --------------------------------------------------------------------------- identity / adapters


class IdentityTests(unittest.TestCase):
    def test_all_url_variants_of_one_job_share_one_key(self) -> None:
        urls = [
            "https://boards.greenhouse.io/acme/jobs/123?gh_src=abc&utm_source=x",
            "https://job-boards.greenhouse.io/ACME/jobs/123",
            "https://boards.greenhouse.io/embed/job_app?for=acme&token=123&utm_campaign=z",
            "https://boards.greenhouse.io/acme?gh_jid=123",
        ]
        self.assertEqual({bd.parse_job_url(u).key for u in urls}, {"greenhouse|acme|123"})  # type: ignore[union-attr]
        sr = ["https://jobs.smartrecruiters.com/Sosemo/744000076124321-a", "https://jobs.smartrecruiters.com/Sosemo/744000076124321-b-renamed"]
        self.assertEqual(len({bd.parse_job_url(u).key for u in sr}), 1)  # type: ignore[union-attr]

    def test_identity_parameters_preserved_tracking_ignored(self) -> None:
        ident = bd.parse_job_url("https://boards.greenhouse.io/embed/job_app?for=acme&token=999&utm_medium=x&gh_src=y")
        self.assertEqual((ident.board, ident.job_id), ("acme", "999"))  # type: ignore[union-attr]
        self.assertIsNone(bd.parse_job_url("https://boards.greenhouse.io/embed/job_app?token=999"))  # board missing: cannot invent one
        self.assertIsNone(bd.parse_job_url("https://careers.example.com/jobs?gh_jid=123"))

    def test_same_id_on_different_ats_or_boards_is_different(self) -> None:
        self.assertNotEqual(bd.JobIdentity("greenhouse", "a", "1").key, bd.JobIdentity("greenhouse", "b", "1").key)
        self.assertNotEqual(bd.JobIdentity("greenhouse", "a", "1").key, bd.JobIdentity("smartrecruiters", "a", "1").key)

    def test_board_urls_and_listing_pages(self) -> None:
        self.assertEqual(bd.parse_board_url("https://jobs.lever.co/acme").key, "lever|acme")  # type: ignore[union-attr]
        self.assertEqual(bd.parse_board_url("https://boards.greenhouse.io/embed/job_board?for=Acme").key, "greenhouse|acme")  # type: ignore[union-attr]
        self.assertIsNone(bd.parse_board_url("https://example.com/careers"))
        self.assertIsNone(bd.parse_job_url("https://jobs.lever.co/acme"))


class AdapterParsingTests(unittest.TestCase):
    def test_greenhouse_uses_first_published_and_keeps_updated_separate(self) -> None:
        jobs = bd.parse_greenhouse("acme", {"jobs": [
            {"id": 1, "title": "A", "first_published": "2026-10-01T10:00:00-04:00", "updated_at": "2026-10-10T10:00:00-04:00", "location": {"name": "NYC"}},
            {"id": 2, "title": "B", "updated_at": "2026-10-10T10:00:00-04:00"},
        ]})  # fmt: skip
        self.assertEqual((jobs[0].published, jobs[0].updated, jobs[0].location), ("2026-10-01T10:00:00-04:00", "2026-10-10T10:00:00-04:00", "NYC"))
        self.assertEqual((jobs[1].published, jobs[1].published_field), ("", ""))  # last-modified is NOT a publication date

    def test_lever_ashby_workable_smartrecruiters_fields(self) -> None:
        lever = bd.parse_lever("acme", [{"id": "123E4567-E89B-12D3-A456-426614174000", "text": "T", "createdAt": 1791564186023, "categories": {"location": "NYC"}, "hostedUrl": "https://jobs.lever.co/acme/x"}])
        self.assertEqual((lever[0].ident.job_id, lever[0].published_field), ("123e4567-e89b-12d3-a456-426614174000", "createdAt"))
        ashby = bd.parse_ashby("acme", {"jobs": [{"id": "A" * 8 + "-bbbb-cccc-dddd-eeeeeeeeeeee", "title": "T", "publishedAt": "2026-10-01T00:00:01Z"}, {"id": "x", "isListed": False}]})
        self.assertEqual(len(ashby), 1)
        wk = bd.parse_workable("acme", {"jobs": [{"shortcode": "ab12", "title": "T", "published_on": "2026-10-08", "telecommuting": True, "country": "United States"}]})
        self.assertEqual((wk[0].ident.job_id, wk[0].published, "Remote" in wk[0].location), ("AB12", "2026-10-08", True))
        sr = bd.parse_smartrecruiters("Acme", [{"id": "744000000000001", "name": "T", "releasedDate": "2026-10-14T08:00:00.000Z", "location": {"fullLocation": "NYC", "remote": True}}])
        self.assertEqual((sr[0].published_field, "Remote" in sr[0].location), ("releasedDate", True))

    def test_http_failures_map_to_gone_or_transient(self) -> None:
        def resp(code: int) -> Any:
            r = mock.Mock(status_code=code)
            r.json.return_value = {}
            return r

        with mock.patch.object(bd.requests, "get", return_value=resp(404)), self.assertRaises(bd.BoardGone):
            bd._get_json("u")
        for code in (429, 500, 503):
            with mock.patch.object(bd.requests, "get", return_value=resp(code)), self.assertRaises(bd.BoardError):
                bd._get_json("u")
        with mock.patch.object(bd.requests, "get", side_effect=bd.requests.Timeout()), self.assertRaises(bd.BoardError):
            bd._get_json("u")

    def test_one_failing_board_does_not_affect_others(self) -> None:
        recs = [bd.BoardRecord("greenhouse", "ok", "t", "seed"), bd.BoardRecord("greenhouse", "bad", "t", "seed")]

        def fetch(b: bd.BoardId) -> list[bd.ListedJob]:
            if b.board == "bad":
                raise ValueError("adapter bug")
            return [job("ok", "1")]

        res = bd.poll_boards(recs, fetch=fetch)
        self.assertEqual([r.ok for r in res], [True, False])
        self.assertIn("adapter bug", res[1].error)


class EligibilityTests(unittest.TestCase):
    def test_title_gate(self) -> None:
        self.assertIsNone(gate("Marketing Intern"))
        self.assertIsNone(gate("Social Media Coordinator"))
        self.assertIn("excluded", gate("Senior Marketing Associate") or "")
        self.assertIn("role", gate("Software Engineering Intern") or "")
        self.assertIn("level", gate("Marketing Strategist") or "")

    def test_title_gate_audit(self) -> None:
        """D-25: suitable titles the old whole-word, single-spelling match rejected now pass; seniority exclusions
        and the requirement for a level signal are unchanged."""
        for t in (
            "Marketing Coordinator", "Marketing Internship", "Social Media Internship - Summer 2027", "Jr. Content Creator",
            "Jr Content Creator", "Marketing - Entry Level", "Entry-Level Social Media", "New Grad Marketing Program",
        ):  # fmt: skip
            self.assertIsNone(gate(t), t)
        for t in (
            "Senior Marketing Internship", "Marketing Lead - Entry Level", "Social Media Marketing", "Marketing Strategist",
            "Content Creator", "International Marketing Manager",
        ):  # fmt: skip
            self.assertIsNotNone(gate(t), t)

    def test_hard_gate_is_conservative(self) -> None:
        resume = "Canva, WordPress"
        self.assertIsNone(el.hard_gate("Marketing Intern", "Remote", "Great role. 1-2 years of experience.", resume))
        self.assertIn("5+ years", el.hard_gate("Marketing Associate", "NYC", "Requires 5+ years of experience in marketing.", resume) or "")
        self.assertIsNone(el.hard_gate("Marketing Associate", "NYC", "We were founded 12 years ago.", resume))  # not a requirement
        self.assertIsNone(el.hard_gate("Marketing Associate", "NYC", "3-5 years of experience.", resume) and None)
        self.assertIn("outside the US", el.hard_gate("Marketing Intern", "Remote - Canada", "x", resume) or "")
        self.assertIsNone(el.hard_gate("Marketing Intern", "New York; London", "x", resume))  # a US office is listed
        self.assertIsNone(el.hard_gate("Marketing Intern", "Remote (US or Canada)", "x", resume))
        self.assertIn("bilingual", el.hard_gate("Bilingual Marketing Assistant", "NYC", "x", resume) or "")
        self.assertIn("mandarin", el.hard_gate("Marketing Intern", "NYC", "Fluent in Mandarin required.", resume) or "")
        self.assertIsNone(el.hard_gate("Marketing Intern", "NYC", "Fluent in Mandarin required.", "Fluent in Mandarin"))  # on the resume


# --------------------------------------------------------------------------- pipeline


class BaselineTests(HarnessCase):
    def test_new_board_backlog_is_baselined_not_alerted(self) -> None:
        old = [job("acme", str(i), published=ago(days=30)) for i in (1, 2)] + [job("acme", "3", published="")]
        self.baseline(*old)
        self.assertEqual({e.disposition for e in self.w.events(kind=lg.SEEN)}, {lg.BASELINED})
        self.assertEqual((self.w.calls, self.w.alerts, self.w.tracker), (collections.Counter(), [], []))
        rec = self.w.state.load_boards()[self.board.key]
        self.assertTrue(rec.baselined_at)
        self.assertEqual((rec.status, rec.last_job_count), ("active", 3))

    def test_verified_fresh_job_on_a_new_board_is_still_alerted(self) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)), job("acme", "2", published=ago(minutes=45)))
        self.assertEqual(self.w.calls[self.key("1")], 0)
        self.assertEqual(self.w.calls[self.key("2")], 1)
        self.assertEqual(len(self.w.alerts), 1)

    def test_new_id_after_baseline_is_detected_exactly_once(self) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)))
        self.w.listings[self.board.key].append(job("acme", "9", published=ago(minutes=20, base=T0 + timedelta(minutes=60)), title="Social Media Intern"))
        self.w.run(minutes_later=60)
        self.assertEqual((self.w.calls[self.key("9")], len(self.w.alerts), len(self.w.tracker)), (1, 1, 1))
        for _ in range(3):  # unchanged listing: nothing new, no repeat alerts, no re-evaluation
            self.w.run(minutes_later=60)
        self.assertEqual((self.w.calls[self.key("9")], len(self.w.alerts), len(self.w.tracker)), (1, 1, 1))
        self.assertEqual(len(self.w.events(self.key("9"), lg.SEEN)), 1)


class FreshnessRoutingTests(HarnessCase):
    def poll_with(self, *new: bd.ListedJob, minutes: int = 60) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)))
        self.w.listings[self.board.key] = [job("acme", "1", published=ago(days=30)), *new]
        self.w.run(minutes_later=minutes)

    def test_alert_only_for_verified_fresh(self) -> None:
        later = T0 + timedelta(minutes=60)
        self.poll_with(
            job("acme", "fresh", published=ago(minutes=30, base=later)),
            job("acme", "nodate", published=""),
            job("acme", "recent", published=ago(hours=14, base=later)),
            job("acme", "stale", published=ago(days=30, base=later)),
            job("acme", "gated", title="Senior Software Engineer", published=ago(minutes=5, base=later)),
        )  # fmt: skip
        by = {k.split("|")[2]: s for k, s in self.w.states().items()}
        self.assertEqual({k: (s.freshness, s.disposition) for k, s in by.items() if k != "1"}, {
            "fresh": (fr.VERIFIED_FRESH, lg.PENDING), "nodate": (fr.OBSERVED_NEW, lg.PENDING),
            "recent": (fr.RECENT, lg.PENDING), "stale": (fr.STALE, lg.STALED), "gated": (fr.VERIFIED_FRESH, lg.FILTERED),
        })  # fmt: skip
        self.assertEqual([self.w.calls[self.key(k)] for k in ("fresh", "nodate", "recent", "stale", "gated")], [1, 1, 1, 0, 0])
        self.assertEqual([a["freshness"] for a in self.w.alerts], [fr.VERIFIED_FRESH])  # nodate / recent: tracker only
        self.assertEqual(len(self.w.tracker), 3)

    def test_day_precision_workable_needs_a_recent_poll(self) -> None:
        wb = bd.BoardId(bd.WORKABLE, "wk")
        self.w.listings[wb.key] = [job("wk", "AAA", ats=bd.WORKABLE, published="2026-10-14", field="published_on")]
        self.w.run(seeds=[wb])  # baseline poll: a date alone cannot prove 12h
        self.w.listings[wb.key].append(job("wk", "BBB", ats=bd.WORKABLE, published="2026-10-14", field="published_on"))
        self.w.run(minutes_later=60)
        self.assertEqual(self.w.states()[bd.JobIdentity(bd.WORKABLE, "wk", "BBB").key].freshness, fr.VERIFIED_FRESH)
        self.w.listings[wb.key].append(job("wk", "CCC", ats=bd.WORKABLE, published="2026-10-14", field="published_on"))
        self.w.run(minutes_later=60 * 13)  # polling stopped for 13 hours: no claim of freshness
        self.assertEqual(self.w.states()[bd.JobIdentity(bd.WORKABLE, "wk", "CCC").key].freshness, fr.RECENT)


class RetryTests(HarnessCase):
    def test_transient_scoring_failure_is_retried_without_using_attempts(self) -> None:
        k = self.fresh_setup()
        self.w.plan[k] = [pl.EvalOutcome("transient", message="groq 429")] * 3 + [done()]
        for _ in range(3):
            self.w.run(minutes_later=60)
        self.assertEqual((self.w.events(k, lg.EVALUATED), self.w.events(k, lg.ERROR), self.w.tracker, self.w.alerts), ([], [], [], []))
        self.w.run(minutes_later=60)  # recovers
        self.assertEqual((len(self.w.events(k, lg.EVALUATED)), len(self.w.tracker), len(self.w.alerts), self.w.calls[k]), (1, 1, 1, 4))

    def test_permanent_looking_failures_are_bounded(self) -> None:
        k = self.fresh_setup()
        self.w.plan[k] = [pl.EvalOutcome("failed", message="thin description")]
        for _ in range(lg.MAX_ATTEMPTS + 3):
            self.w.run(minutes_later=60)
        self.assertEqual(self.w.calls[k], lg.MAX_ATTEMPTS)
        self.assertEqual(len(self.w.events(k, lg.ABANDONED)), 1)
        self.assertEqual((self.w.tracker, self.w.alerts), ([], []))

    def test_alert_failure_is_retried_and_sent_exactly_once(self) -> None:
        k = self.fresh_setup()
        self.w.alert_error = ConnectionError("telegram unreachable")
        run = self.w.run(minutes_later=60)
        self.assertEqual((run.alerts_failed, len(self.w.events(k, lg.EVALUATED)), self.w.events(k, lg.ALERTED), len(self.w.tracker)), (1, 1, [], 1))
        self.w.run(minutes_later=60)
        self.assertEqual(self.w.alerts, [])  # still down
        self.w.alert_error = None
        self.w.run(minutes_later=60)
        self.assertEqual(len(self.w.alerts), 1)
        for _ in range(2):
            self.w.run(minutes_later=60)
        self.assertEqual((len(self.w.alerts), self.w.calls[k], len(self.w.tracker)), (1, 1, 1))  # no re-score, no duplicate row

    def test_pending_alert_survives_aging_past_the_window_and_is_labelled_late(self) -> None:
        k = self.fresh_setup()
        self.w.alert_error = ConnectionError("down")
        self.w.run(minutes_later=60)
        self.assertEqual(self.w.events(k, lg.ALERTED), [])
        self.w.alert_error = None
        self.w.run(minutes_later=60 * 13)  # 14 h after publication: outside the 12 h window, but still pending
        self.assertEqual((len(self.w.alerts), self.w.events(k, lg.ABANDONED)), (1, []))
        self.assertIn("delivered late", self.w.alerts[0]["late"])
        self.assertEqual(self.w.alerts[0]["freshness"], fr.VERIFIED_FRESH)  # verified at first observation, not re-judged
        self.assertTrue(self.w.events(k, lg.ALERTED)[0].detail["late"])

    def test_on_time_alert_is_not_labelled_late(self) -> None:
        self.fresh_setup()
        self.w.run(minutes_later=60)
        self.assertNotIn("late", self.w.alerts[0])

    def test_scoring_retry_survives_aging_past_the_window(self) -> None:
        k = self.fresh_setup()
        self.w.plan[k] = [pl.EvalOutcome("transient", message="groq down")] * 14 + [done()]
        for _ in range(14):  # the job is now older than 12 h and still unscored
            self.w.run(minutes_later=60)
        self.assertEqual((self.w.events(k, lg.EVALUATED), self.w.events(k, lg.ABANDONED), self.w.alerts), ([], [], []))
        self.w.run(minutes_later=60)
        self.assertEqual((len(self.w.events(k, lg.EVALUATED)), len(self.w.alerts), len(self.w.tracker)), (1, 1, 1))
        self.assertIn("delivered late", self.w.alerts[0]["late"])

    def test_tracker_write_failure_leaves_the_job_retryable_without_duplicate_rows(self) -> None:
        k = self.fresh_setup()
        self.w.tracker_error = OSError("sheet unavailable")
        with self.assertRaises(OSError):
            self.w.run(minutes_later=60)
        self.assertEqual((self.w.events(k, lg.EVALUATED), self.w.alerts, self.w.tracker), ([], [], []))
        self.assertEqual(len(self.w.events(k, lg.SEEN)), 1)  # first observation is durable regardless
        self.w.tracker_error = None
        self.w.tracked_keys.discard(k)  # the failed run's in-memory marker is gone in a real new process
        self.w.run(minutes_later=60)
        self.assertEqual((len(self.w.tracker), len(self.w.alerts), len(self.w.events(k, lg.EVALUATED))), (1, 1, 1))

    def test_events_write_failure_after_row_append_does_not_duplicate_the_row(self) -> None:
        k = self.fresh_setup()
        real = self.w.state.append_events
        calls = {"n": 0}

        def flaky(events: list[lg.Event]) -> None:
            calls["n"] += 1
            if calls["n"] >= 2:  # 1st = observations; later = evaluation events, written after the tracker append
                raise OSError("events tab write failed")
            real(events)

        self.w.state.append_events = flaky  # type: ignore[method-assign]
        with self.assertRaises(OSError):
            self.w.run(minutes_later=60)
        self.assertEqual((len(self.w.tracker), self.w.events(k, lg.EVALUATED)), (1, []))
        self.w.state.append_events = real  # type: ignore[method-assign]
        self.w.run(minutes_later=60)  # evaluated again (row guarded by the tracker key)
        self.assertEqual((len(self.w.tracker), len(self.w.events(k, lg.EVALUATED)), len(self.w.alerts)), (1, 1, 1))

    def test_failure_in_the_final_flush_is_visible_and_recorded(self) -> None:
        k = self.fresh_setup()
        self.w.tracker_error = OSError("down")
        with self.assertRaises(OSError):
            self.w.run(minutes_later=60)
        self.assertTrue(self.w.state.load_runs()[-1].notes)  # the run record exists and says what happened


class AlertRecordingTests(HarnessCase):
    """`alerted` means a channel accepted the message (D-49); failures are recorded, bounded and redacted."""

    def tearDown_harness(self) -> None:
        """A fresh Harness (own state directory) for the next subTest."""
        self._tmp.cleanup()
        self.setUp()

    def test_alert_not_accepted_by_any_channel_is_not_recorded_alerted(self) -> None:
        k = self.fresh_setup()
        self.w.alert_result = False  # no channel configured or accepted the message
        run = self.w.run(minutes_later=60)
        self.assertEqual((run.alerts_failed, run.alerts_sent, run.outcome), (1, 0, "degraded"))
        self.assertIn("no alert channel configured or accepted the message", run.notes)
        self.assertEqual((self.w.events(k, lg.ALERTED), self.w.events(k, lg.ERROR), self.w.alerts), ([], [], []))
        self.w.alert_result = True  # a working channel on the next run delivers it exactly once
        self.w.run(minutes_later=60)
        alerted = self.w.events(k, lg.ALERTED)
        self.assertEqual((len(alerted), alerted[0].detail["channel"], len(self.w.alerts)), (1, "telegram", 1))
        for _ in range(2):
            self.w.run(minutes_later=60)
        self.assertEqual((len(self.w.events(k, lg.ALERTED)), len(self.w.alerts)), (1, 1))

    def test_rejected_alert_requests_are_bounded(self) -> None:
        k = self.fresh_setup()
        err = ValueError("400 chat not found")
        err.response = mock.Mock(status_code=400)  # type: ignore[attr-defined]
        self.w.alert_error = err
        for _ in range(lg.MAX_ATTEMPTS + 2):
            self.w.run(minutes_later=60)
        self.assertEqual(len(self.w.events(k, lg.ABANDONED)), 1)

    def test_alert_without_http_response_is_bounded_at_five_attempts(self) -> None:
        errors: list[Exception] = [ConnectionError("down"), requests.ConnectionError("down"), requests.Timeout("slow"), ValueError("bad row")]
        for err in errors:
            with self.subTest(error=type(err).__module__ + "." + type(err).__name__):
                self.tearDown_harness()
                k = self.fresh_setup()
                self.w.alert_error = err
                for _ in range(lg.MAX_ATTEMPTS):
                    self.w.run(minutes_later=60)
                errs = self.w.events(k, lg.ERROR)
                self.assertEqual([(e.detail["stage"], e.detail["attempt"]) for e in errs], [(lg.STAGE_ALERT, n) for n in range(1, lg.MAX_ATTEMPTS + 1)])
                self.assertEqual(len(self.w.events(k, lg.ABANDONED)), 1)
                calls = self.w.alert_calls
                self.w.run(minutes_later=60)  # run 6 never tries again
                self.assertEqual((self.w.alert_calls, self.w.alerts, self.w.events(k, lg.ALERTED)), (calls, [], []))

    def test_alert_four_failures_then_success_delivers_once_without_abandoning(self) -> None:
        k = self.fresh_setup()
        self.w.alert_error = requests.ConnectionError("down")
        for _ in range(lg.MAX_ATTEMPTS - 1):
            self.w.run(minutes_later=60)
        self.w.alert_error = None
        self.w.run(minutes_later=60)
        self.assertEqual((len(self.w.alerts), len(self.w.events(k, lg.ALERTED)), self.w.events(k, lg.ABANDONED), len(self.w.events(k, lg.ERROR))), (1, 1, [], lg.MAX_ATTEMPTS - 1))

    def test_alert_http_5xx_and_429_stay_transient_and_use_no_attempt(self) -> None:
        for status in (503, 429):
            with self.subTest(status=status):
                self.tearDown_harness()
                k = self.fresh_setup()
                err = requests.HTTPError(f"{status} error")
                err.response = mock.Mock(status_code=status)
                self.w.alert_error = err
                for _ in range(7):
                    run = self.w.run(minutes_later=60)
                self.assertEqual((self.w.events(k, lg.ERROR), self.w.events(k, lg.ABANDONED), run.alerts_failed), ([], [], 1))
                self.w.alert_error = None
                self.w.run(minutes_later=60)
                self.assertEqual((len(self.w.alerts), len(self.w.events(k, lg.ALERTED))), (1, 1))

    def test_alert_failure_text_never_contains_the_bot_token(self) -> None:
        token, chat = "123456:ABCdefGHIjklMNOpqrSTUvwxYZ0123456789", "987654321"
        k = self.fresh_setup()
        self.w.alert_error = requests.ConnectionError(f"HTTPSConnectionPool(host='api.telegram.org'): Max retries exceeded with url: /bot{token}/sendMessage to chat {chat}")
        with self.assertLogs("hunter", "WARNING") as logs:
            run = self.w.run(minutes_later=60, secrets=(token, chat))
        stored = self.w.events(k, lg.ERROR)[0].detail["message"]
        self.assertIn("***", stored)
        self.assertIn("***", "\n".join(logs.output))
        for text in (stored, run.notes, "\n".join(logs.output)):
            self.assertNotIn(token, text)
            self.assertNotIn(chat, text)
        # the pattern fallback also removes a token that was not passed in
        self.w.alert_error = requests.ConnectionError(f"url: /bot{token}/sendMessage")
        self.w.run(minutes_later=60)
        self.assertNotIn(token, self.w.events(k, lg.ERROR)[-1].detail["message"])

    def test_alert_failure_with_empty_message_records_the_exception_type(self) -> None:
        k = self.fresh_setup()
        self.w.alert_error = ConnectionError()
        self.w.run(minutes_later=60)
        self.assertEqual([e.detail["message"] for e in self.w.events(k, lg.ERROR)], ["ConnectionError"])


class BoardHealthTests(HarnessCase):
    def test_outage_gap_is_measured_from_last_success_and_downgrades_claims(self) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)))
        self.w.listings[self.board.key] = bd.BoardError("HTTP 503")
        r2 = self.w.run(minutes_later=60)
        self.assertEqual((r2.boards_failed, self.w.state.load_boards()[self.board.key].consecutive_failures), (1, 1))
        t_back = T0 + timedelta(minutes=60 + 780)
        self.w.listings[self.board.key] = [
            job("acme", "1", published=ago(days=30)),
            job("acme", "undated", published=""),
            job("acme", "stamped", published=ago(minutes=20, base=t_back)),
        ]
        r3 = self.w.run(minutes_later=780)
        self.assertEqual(r3.max_board_gap_min, 840)  # 14 hours since the last SUCCESSFUL poll
        by = {k.split("|")[2]: s.freshness for k, s in self.w.states().items()}
        self.assertEqual((by["undated"], by["stamped"]), (fr.UNCERTAIN, fr.VERIFIED_FRESH))  # gap > window: no "observed new" claim
        self.assertEqual(self.w.state.load_boards()[self.board.key].consecutive_failures, 0)

    def test_suspicious_empty_listing_is_a_failure_not_a_deletion(self) -> None:
        jobs = [job("acme", str(i), published=ago(days=30)) for i in range(10)]
        self.baseline(*jobs)
        self.w.listings[self.board.key] = []
        run = self.w.run(minutes_later=60)
        self.assertEqual(run.boards_failed, 1)
        self.w.listings[self.board.key] = jobs
        self.w.run(minutes_later=60)
        self.assertEqual(len(self.w.events(kind=lg.SEEN)), 10)  # nothing was treated as new

    def test_id_flood_on_a_known_board_is_rebaselined(self) -> None:
        self.baseline(*[job("acme", str(i), published=ago(days=30)) for i in range(5)])
        flood = [job("acme", str(i), published=ago(days=30)) for i in range(5)] + [job("acme", f"n{i}", published=ago(days=20, base=T0 + timedelta(minutes=60))) for i in range(40)]
        self.w.listings[self.board.key] = flood
        run = self.w.run(minutes_later=60)
        self.assertIn("re-baselined", run.notes)
        self.assertEqual(sum(c for k, c in self.w.calls.items()), 0)
        self.assertEqual(len(self.w.alerts), 0)

    def test_board_is_disabled_after_sustained_failure_and_recovers(self) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)))
        self.w.listings[self.board.key] = bd.BoardError("HTTP 500")
        for _ in range(bd.DISABLE_AFTER_FAILURES):
            self.w.run(minutes_later=60)
        self.assertEqual(self.w.state.load_boards()[self.board.key].status, bd.STATUS_DISABLED)
        self.assertEqual(self.w.run(minutes_later=60).boards_total, 0)  # no longer polled


class ChangeTrackingTests(HarnessCase):
    def test_update_and_republication_are_logged_never_re_alerted(self) -> None:
        j = job("acme", "5", published=ago(minutes=30), updated="2026-10-14T11:00:00Z")
        self.baseline(job("acme", "1", published=ago(days=30)), j)
        self.assertEqual(len(self.w.alerts), 1)
        k = self.key("5")
        moved = job("acme", "5", published=ago(minutes=5, base=T0 + timedelta(hours=26)), updated="2026-10-15T13:00:00Z")
        self.w.listings[self.board.key] = [job("acme", "1", published=ago(days=30)), moved]
        self.w.run(minutes_later=60 * 26)
        self.assertEqual((len(self.w.events(k, lg.UPDATED)), len(self.w.events(k, lg.REPUBLISHED))), (1, 1))
        self.assertEqual((len(self.w.alerts), self.w.calls[k], len(self.w.events(k, lg.SEEN))), (1, 1, 1))


class DiscoveryTests(HarnessCase):
    def test_discovered_boards_are_baselined_in_the_same_run(self) -> None:
        nb = bd.BoardId(bd.LEVER, "newco")
        self.w.listings[nb.key] = [job("newco", f"{i:08x}-e89b-12d3-a456-426614174000", ats=bd.LEVER, published=ago(days=60)) for i in range(5)]
        run = self.w.run(discover=lambda ctx: dsc.DiscoveryResult(boards=[nb]), discovery_every_hours=12)
        self.assertEqual((run.discovery, run.boards_added, run.evaluated, len(self.w.alerts)), (True, 1, 0, 0))
        self.assertTrue(self.w.state.load_boards()[nb.key].baselined_at)

    def test_discovery_schedule_and_failure_isolation(self) -> None:
        runs = [st_mod.RunRecord(ago(hours=5), discovery=True)]
        self.assertFalse(pl.discovery_due(runs, T0, 12))
        self.assertTrue(pl.discovery_due(runs, T0 + timedelta(hours=8), 12))
        self.assertTrue(pl.discovery_due([], T0, 12))
        self.assertTrue(pl.discovery_due([st_mod.RunRecord(ago(hours=1))], T0, 12))  # a poll-only run is not a discovery

        self.baseline(job("acme", "1", published=ago(days=30)))

        def boom(ctx: Any) -> Any:
            raise RuntimeError("serper credits exhausted")

        self.w.listings[self.board.key].append(job("acme", "2", published=ago(minutes=5, base=T0 + timedelta(minutes=60))))
        run = self.w.run(minutes_later=60, discover=boom, force_discovery=True)
        self.assertIn("discovery failed", run.notes)
        self.assertEqual(len(self.w.alerts), 1)  # polling still happened

    def test_search_found_job_gets_an_authoritative_date_and_never_double_counts(self) -> None:
        listed = job("acme", "88", published=ago(minutes=40))
        self.baseline(job("acme", "1", published=ago(days=30)))
        sj = pl.SearchJob(listed.ident, listed.title, listed.url)
        self.w.listings[self.board.key].append(listed)  # on the board AND found by search
        self.w.run(minutes_later=60, discover=lambda ctx: dsc.DiscoveryResult(jobs=[sj]), hydrate_listed=lambda s: listed, force_discovery=True)
        self.assertEqual(len(self.w.events(self.key("88"), lg.SEEN)), 1)
        off_board = job("acme", "89", published=ago(minutes=30, base=T0 + timedelta(minutes=120)))
        sj2 = pl.SearchJob(off_board.ident, off_board.title, off_board.url)
        self.w.run(minutes_later=60, discover=lambda ctx: dsc.DiscoveryResult(jobs=[sj2]), hydrate_listed=lambda s: off_board, force_discovery=True)
        self.assertEqual(self.w.states()[self.key("89")].seen_detail["source"], "search")
        self.assertEqual(self.w.states()[self.key("89")].freshness, fr.VERIFIED_FRESH)


class OperationsTests(HarnessCase):
    def test_polling_intervals_are_recorded(self) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)))
        self.w.run(minutes_later=60)
        self.w.run(minutes_later=185)  # a delayed schedule
        runs = self.w.state.load_runs()
        self.assertEqual([r.gap_since_prev_run_min for r in runs], [None, 60, 185])
        self.assertEqual(runs[-1].max_board_gap_min, 185)

    def test_priority_puts_fresh_jobs_first_when_capped(self) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)))
        t = T0 + timedelta(minutes=60)
        self.w.listings[self.board.key] += [job("acme", "recent", published=ago(hours=9, base=t)), job("acme", "fresh", published=ago(minutes=5, base=t)), job("acme", "nodate", published="")]
        self.w.run(minutes_later=60, max_jobs=1)
        self.assertEqual([k for k, c in self.w.calls.items() if c], [self.key("fresh")])
        self.w.run(minutes_later=60, max_jobs=1)  # backlog drains over later runs
        self.assertEqual(len([k for k, c in self.w.calls.items() if c]), 2)

    def test_dry_run_writes_nothing(self) -> None:
        self.w.listings[self.board.key] = [job("acme", "1", published=ago(minutes=5))]
        self.w.run(seeds=[self.board], dry_run=True)
        self.assertEqual((self.w.state.load_events(), self.w.state.load_boards(), self.w.state.load_runs(), self.w.tracker, self.w.alerts), ([], {}, [], [], []))

    def test_invisible_results_are_recorded_but_not_added_to_the_tracker(self) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)))
        self.w.listings[self.board.key].append(job("acme", "2", published=ago(minutes=5, base=T0 + timedelta(minutes=60))))
        self.w.plan[self.key("2")] = [done("Filtered Out", 12, visible=False)]
        self.w.run(minutes_later=60)
        self.assertEqual((self.w.tracker, self.w.alerts, len(self.w.events(self.key("2"), lg.EVALUATED))), ([], [], 1))


class StatePersistenceTests(unittest.TestCase):
    def test_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            s = st_mod.CsvState(Path(d))
            s.ensure()
            rec = bd.BoardRecord("lever", "acme", "2026-10-14T00:00:00Z", "search", "active", "2026-10-14T01:00:00Z", "t", "t2", 2, 7, "x")
            s.save_boards([rec])
            self.assertEqual(s.load_boards()[rec.key], rec)
            ev = lg.Event(ago(), "lever|acme|1", lg.SEEN, fr.VERIFIED_FRESH, lg.PENDING, ago(minutes=5), {"title": "Café ☕", "n": 1})
            s.append_events([ev])
            self.assertEqual(s.load_events(), [ev])
            run = st_mod.RunRecord(ago(), True, 3, 2, 1, 1, 4, 2, 2, 1, 0, 60, 90, 30, "n")
            s.append_run(run)
            self.assertEqual(s.load_runs(), [run])

    def test_malformed_ledger_rows_are_skipped(self) -> None:
        self.assertIsNone(lg.Event.from_row(["only", "two"]))
        self.assertEqual(lg.Event.from_row(["t", "k", "seen", "", "", "", "{not json"]).detail, {})  # type: ignore[union-attr]


if __name__ == "__main__":
    unittest.main()
