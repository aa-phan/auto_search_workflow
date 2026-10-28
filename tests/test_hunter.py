"""Offline tests for hunter.py: settings, search, hydration, evaluator, Groq client, stores, alerts.

All mocked (no network, no credentials). See tests/test_core.py for the polling/freshness core.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import boards as bd  # noqa: E402
import freshness as fr  # noqa: E402
import discovery as dsc  # noqa: E402
import eval_budget as eb  # noqa: E402
import hunter as h  # noqa: E402
import ledger as lg  # noqa: E402
import pipeline as pl  # noqa: E402
import search  # noqa: E402
from meter import METER  # noqa: E402


def settings(**kw: object) -> h.Settings:
    with mock.patch.dict(os.environ):  # a developer's .env must not leak into the tests
        for key in h.SETTING_DEFAULTS:
            os.environ.pop(key.upper(), None)
        base = h.Settings.from_values({"Resume_Text": "r" * 300})
    return h.replace(base, **kw) if kw else base


def posting(**kw: str) -> h.Posting:
    base = dict(url="https://x", ats="lever", title="Marketing Intern", company="Acme",
                description="d" * 300, location="Remote", posted="")  # fmt: skip
    base.update(kw)
    return h.Posting(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- settings / search


class SettingsTests(unittest.TestCase):
    def test_blank_cells_fall_back_to_defaults(self) -> None:
        with mock.patch.dict(os.environ):
            for key in h.SETTING_DEFAULTS:
                os.environ.pop(key.upper(), None)
            s = h.Settings.from_values({"Target_Roles": "  ", "Min_Alert_Score": "abc", "Max_Job_Age_Days": "30", "Fresh_Window_Hours": "0"})
        self.assertIn("Marketing", s.roles)
        self.assertEqual((s.min_score, s.max_age_days, s.fresh_window_hours, s.discovery_every_hours), (70, 30, 1, 12))

    def test_pool_settings_defaults_clamps_and_mode_note(self) -> None:
        with mock.patch.dict(os.environ):
            for key in h.SETTING_DEFAULTS:
                os.environ.pop(key.upper(), None)
            d = h.Settings.from_values({})
            self.assertEqual((d.exploration_share_percent, d.exploration_days, d.rebalance_every_days, d.max_replacements_per_rebalance, d.rebalance_mode), (20, 7, 7, 20, "report"))
            p = d.pool_policy
            self.assertEqual((p.max_active, p.exploration_target, p.established_target, p.mode), (500, 100, 400, "report"))
            odd = h.Settings.from_values({"Exploration_Share_Percent": "250", "Exploration_Days": "0", "Rebalance_Every_Days": "-3", "Max_Replacements_Per_Rebalance": "-5", "Rebalance_Mode": "ON"})
            self.assertEqual((odd.exploration_share_percent, odd.exploration_days, odd.rebalance_every_days, odd.max_replacements_per_rebalance, odd.rebalance_mode), (100, 1, 1, 0, "on"))
            low = h.Settings.from_values({"Exploration_Share_Percent": "-4", "Max_Replacements_Per_Rebalance": "abc"})
            self.assertEqual((low.exploration_share_percent, low.max_replacements_per_rebalance), (0, 20))
            bad = h.Settings.from_values({"Rebalance_Mode": "yes please"})
            self.assertEqual(bad.rebalance_mode, "report")  # an unknown mode never turns rebalancing on
            self.assertEqual(h.settings_notes({}), [])
            self.assertEqual(h.settings_notes({"Rebalance_Mode": "on"}), [])
            notes = h.settings_notes({"Rebalance_Mode": "yes please"})
            self.assertTrue(notes and "Rebalance_Mode" in notes[0] and "report" in notes[0])
        keys = [k for k, _, note in h.DEFAULT_SETTINGS]
        for k in ("Exploration_Share_Percent", "Exploration_Days", "Rebalance_Every_Days", "Max_Replacements_Per_Rebalance", "Rebalance_Mode"):
            self.assertIn(k, keys)
        notes_text = " ".join(note for key, _, note in h.DEFAULT_SETTINGS if key in ("Exploration_Share_Percent", "Exploration_Days"))
        self.assertIn("not a proven best value", notes_text)

    def test_excluded_words_are_whole_word_case_insensitive(self) -> None:
        rx = h.excluded_title_regex(settings().excluded)
        assert rx is not None
        for bad in ["Senior Marketing Associate", "Sr. Content Writer", "marketing MANAGER", "Lead Designer"]:
            self.assertTrue(rx.search(bad), bad)
        for ok in ["Marketing Associate", "Leadership Intern", "Content Specialist (Remote)"]:
            self.assertIsNone(rx.search(ok), ok)


class QueryTests(unittest.TestCase):
    def test_empty_roles_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            h.rotation_slots(settings(roles=[]))

    def test_rotation_slots_cover_every_site_and_role_and_keep_locations_out_of_the_query(self) -> None:
        s = settings(roles=["Marketing", "Social Media"], locations=["Austin", "US Remote", "Remote"])
        slots = h.rotation_slots(s)
        self.assertEqual(len(slots), len(h.ATS_SITES) * 2)  # site x role
        self.assertEqual(len({sl.id for sl in slots}), len(slots))
        self.assertEqual({sl.site for sl in slots[: len(h.ATS_SITES)]}, set(h.ATS_SITES))  # consecutive slots span providers
        self.assertEqual({sl.location for sl in slots}, {""})
        for sl in slots:
            self.assertNotIn("Austin", h.slot_query(sl, s))

    def test_slot_query_is_the_role_as_a_job_search_and_the_site_is_a_domain_restriction_not_syntax(self) -> None:
        q = h.slot_query(dsc.Slot("jobs.lever.co", "Social Media", ""), settings())
        self.assertEqual(q, "Social Media job")  # no site:, intitle:, OR groups, level or exclusion words
        self.assertEqual(h.slot_query(dsc.Slot("jobs.lever.co", "Marketing", "Austin"), settings()), "Marketing job Austin")

    def test_config_reads_the_tavily_key_and_window_and_nothing_serper(self) -> None:
        with mock.patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-x", "SERPER_API_KEY": "old", "SEARCH_API_KEY": "old", "SEARCH_TBS": "none"}):
            os.environ.pop("SEARCH_WINDOW_DAYS", None)
            cfg = h.Config.from_env()
        self.assertEqual((cfg.tavily_api_key, cfg.search_window_days), ("tvly-x", 3))
        self.assertFalse(any("serper" in f.lower() or "tbs" in f.lower() for f in h.Config.__dataclass_fields__))
        with mock.patch.dict(os.environ, {"SEARCH_WINDOW_DAYS": "0", "TAVILY_API_KEY": ""}):
            self.assertEqual(h.Config.from_env().search_window_days, 1)  # a window can never be switched off for scheduled runs

    def fake_world(self, calls: list[dict[str, Any]], *, pages: dict[str, list[dict[str, Any]]] | None = None):
        def post(url: str, headers: dict, json: dict, timeout: float) -> mock.Mock:
            calls.append(json)
            resp = mock.Mock(status_code=200, headers={})
            resp.json.return_value = {"results": (pages or {}).get(json["query"], []), "usage": {"credits": 1}}
            return resp

        return mock.patch.object(search.requests, "post", side_effect=post)

    def ctx(self, **kw: Any) -> pl.DiscoveryContext:
        base = dict(
            now=datetime(2026, 10, 14, 12, tzinfo=timezone.utc), rotation=dsc.RotationState(), is_new_board=lambda b: True,
            is_unseen_job=lambda i: True, budget=search.SearchBudget("2026-10"),
        )  # fmt: skip
        return pl.DiscoveryContext(**{**base, **kw})

    def test_scheduled_discovery_is_windowed_budgeted_charged_and_backfill_is_the_only_unwindowed_path(self) -> None:
        cfg = h.replace(h.Config.from_env(), tavily_api_key="tvly-k", search_window_days=3)
        s = h.replace(settings(roles=["Marketing"]), discovery_credit_budget=4)
        calls: list[dict[str, Any]] = []
        ctx = self.ctx()
        with self.fake_world(calls):
            scheduled = h.make_discovery(cfg, s)(ctx)
        self.assertEqual((scheduled.kind, scheduled.credits, scheduled.slots_used), ("rotation", 4, 4))
        self.assertTrue(all("start_date" in c and c["include_domains"] and c["search_depth"] == "basic" for c in calls))
        self.assertTrue(all(not c["include_answer"] and not c["include_raw_content"] for c in calls))
        self.assertEqual((ctx.budget.used, ctx.budget.calls, ctx.budget.by_path), (4, 4, {"rotation": 4}))  # every request charged under its path
        calls.clear()
        manual_ctx = self.ctx(scheduled=False)
        with self.fake_world(calls):
            manual = h.make_discovery(cfg, s, backfill=True, backfill_credits=2)(manual_ctx)
        self.assertEqual((manual.kind, manual.credits), ("backfill", 2))
        self.assertTrue(all("start_date" not in c for c in calls))
        self.assertTrue(all(q.id.startswith("backfill:") for q in manual.queries))
        self.assertEqual(manual_ctx.budget.by_path, {"backfill": 2})

    def test_the_run_is_capped_by_what_is_left_in_the_monthly_ledger(self) -> None:
        cfg = h.replace(h.Config.from_env(), tavily_api_key="tvly-k")
        s = h.replace(settings(roles=["Marketing"]), discovery_credit_budget=10)
        budget = search.SearchBudget("2026-10", used=795, cap=1000, reserve=200)  # scheduled limit is 800
        calls: list[dict[str, Any]] = []
        with self.fake_world(calls):
            res = h.make_discovery(cfg, s)(self.ctx(budget=budget))
        self.assertEqual((res.credits, len(calls), budget.used), (5, 5, 800))  # stopped at the scheduled ceiling, not at the per-run budget
        calls.clear()
        with self.fake_world(calls):
            manual = h.make_discovery(cfg, s)(self.ctx(budget=budget, scheduled=False))
        self.assertEqual(manual.credits, 6)  # a manual run is not held at the scheduled ceiling (all 6 slots of the one role)
        self.assertEqual(budget.used, 806)

    def test_hit_limit_stops_the_run_and_blocks_further_spending(self) -> None:
        cfg = h.replace(h.Config.from_env(), tavily_api_key="tvly-k")
        s = h.replace(settings(roles=["Marketing"]), discovery_credit_budget=10)
        resp = mock.Mock(status_code=432, headers={})
        ctx = self.ctx()
        with mock.patch.object(search.requests, "post", return_value=resp) as post:
            res = h.make_discovery(cfg, s)(ctx)
        self.assertEqual((post.call_count, ctx.budget.limit_hit, ctx.budget.used), (1, True, 0))  # the first 432 ends the run; failures are not charged
        self.assertIn("432", res.fatal)
        self.assertEqual(ctx.budget.remaining(scheduled=False), 0)


# --------------------------------------------------------------------------- hydration


def fake_get(payload: dict) -> mock.Mock:
    resp = mock.Mock()
    resp.json.return_value = payload
    return resp


def ref(ats: str = "lever", board: str = "acme", jid: str = "x") -> h.AtsRef:
    return h.AtsRef(ats, f"https://example/{board}/{jid}", board, jid)


class HydrationDateTests(unittest.TestCase):
    def test_greenhouse_prefers_first_published_over_updated_at(self) -> None:
        both = {"title": "t", "content": "", "first_published": "2026-09-16T12:07:31-04:00", "updated_at": "2026-10-10T09:00:00-04:00"}
        with mock.patch.object(h, "_http_get", return_value=fake_get(both)):
            p = h._hydrate_greenhouse(ref("greenhouse"))
        self.assertEqual((p.posted, p.posted_source), ("2026-09-16T16:07:31Z", "first_published"))
        only_updated = {"title": "t", "content": "", "updated_at": "2026-10-10T09:00:00-04:00"}
        with mock.patch.object(h, "_http_get", return_value=fake_get(only_updated)):
            p = h._hydrate_greenhouse(ref("greenhouse"))
        self.assertEqual(p.posted_source, "updated_at")  # a lower bound on age only: can prove stale, never fresh

    def test_lever_created_at_keeps_the_time_of_day(self) -> None:
        with mock.patch.object(h, "_http_get", return_value=fake_get({"text": "t", "createdAt": 1791564186023})):
            p = h._hydrate_lever(ref())
        self.assertTrue(p.posted.startswith("2026-10-09T") and p.posted.endswith("Z"))
        self.assertEqual(p.posted_source, "createdAt")

    def test_ashby_json_ld_fallback_only_when_api_has_no_date(self) -> None:
        r = ref("ashby", "Acme", "123e4567-e89b-12d3-a456-426614174000")
        with mock.patch.object(h, "_hydrate_ashby_api", return_value=posting(ats="ashby", posted="")), \
             mock.patch.object(h, "_page_date_posted", return_value="2026-08-20") as page:  # fmt: skip
            p = h._hydrate(r)
        self.assertEqual((p.posted, p.posted_source), ("2026-08-20", "datePosted"))
        page.assert_called_once()
        with mock.patch.object(h, "_hydrate_ashby_api", return_value=posting(ats="ashby", posted="2026-09-01")), \
             mock.patch.object(h, "_page_date_posted") as page:  # fmt: skip
            self.assertEqual(h._hydrate(r).posted, "2026-09-01")
        page.assert_not_called()

    def test_search_result_date_is_last_resort(self) -> None:
        r = h.replace(ref(), hint_date="3 days ago")
        with mock.patch.object(h, "_hydrate", return_value=posting(posted="")):
            p = h.hydrate_posting(r)
        self.assertEqual(p.posted_source, "search_result")
        with mock.patch.object(h, "_hydrate", return_value=posting(posted="2026-01-01", posted_source="createdAt")):
            self.assertEqual(h.hydrate_posting(r).posted, "2026-01-01")


class HydrationErrorTests(unittest.TestCase):
    def raises(self, exc: BaseException) -> type[BaseException]:
        with mock.patch.object(h, "_hydrate", side_effect=exc):
            try:
                h.hydrate_posting(ref())
            except BaseException as caught:  # noqa: BLE001
                return type(caught)
        raise AssertionError("did not raise")

    @staticmethod
    def http(code: int) -> requests.HTTPError:
        return requests.HTTPError(f"HTTP {code}", response=mock.Mock(status_code=code))

    def test_404_and_410_are_closed(self) -> None:
        self.assertIs(self.raises(self.http(404)), h.ClosedPosting)
        self.assertIs(self.raises(self.http(410)), h.ClosedPosting)

    def test_5xx_429_timeout_and_connection_errors_are_transient(self) -> None:
        for exc in [self.http(500), self.http(503), self.http(429), requests.Timeout(), requests.ConnectionError()]:
            self.assertIs(self.raises(exc), h.TransientError, repr(exc))

    def test_other_4xx_and_thin_text_are_permanent_errors(self) -> None:
        self.assertIs(self.raises(self.http(403)), requests.HTTPError)
        with mock.patch.object(h, "_hydrate", return_value=posting(description="short")), self.assertRaises(ValueError):
            h.hydrate_posting(ref())


# --------------------------------------------------------------------------- evaluator


class EvaluatorTests(unittest.TestCase):
    ident = bd.JobIdentity("lever", "acme", "123e4567-e89b-12d3-a456-426614174000")
    st = lg.JobState(ident.key, seen=True, freshness=fr.VERIFIED_FRESH, seen_detail={"board": "acme", "title": "Marketing Intern"})

    def evaluate(self, hydrate: object, groq: mock.Mock | None = None, s: h.Settings | None = None) -> pl.EvalOutcome:
        s = s or settings()
        fn = (lambda r: (_ for _ in ()).throw(hydrate)) if isinstance(hydrate, BaseException) else (lambda r: hydrate)
        ev = h.make_evaluator(s, groq or mock.Mock(), h.excluded_title_regex(s.excluded), hydrate=fn)  # type: ignore[arg-type]
        return ev(self.ident, self.st)

    def test_closed_posting_is_a_final_outcome_and_skips_groq(self) -> None:
        groq = mock.Mock()
        out = self.evaluate(h.ClosedPosting("404"), groq)
        assert out.payload is not None
        self.assertEqual((out.kind, out.payload["status"], out.payload["score"], out.payload["visible"]), ("done", h.STATUS_CLOSED, 0, False))
        groq.evaluate.assert_not_called()

    def test_transient_and_permanent_failures_are_distinguished(self) -> None:
        self.assertEqual(self.evaluate(h.TransientError("timeout")).kind, "transient")
        self.assertEqual(self.evaluate(ValueError("description too short")).kind, "failed")

    def test_stale_by_authoritative_date_skips_groq(self) -> None:
        groq = mock.Mock()
        out = self.evaluate(posting(posted="2020-01-01"), groq)
        assert out.payload is not None
        self.assertEqual((out.payload["status"], out.payload["score"]), ("Stale (>14d old)", 0))
        groq.evaluate.assert_not_called()

    def test_deterministic_gates_run_before_groq(self) -> None:
        cases = {
            "title": posting(title="Senior Marketing Associate"),
            "years": posting(description="Requires 6+ years of experience in marketing. " * 8),
            "location": posting(location="Remote - Canada"),
            "language": posting(description="Fluent in Mandarin required. " * 12),
        }
        for name, p in cases.items():
            groq = mock.Mock()
            out = self.evaluate(p, groq)
            assert out.payload is not None
            self.assertEqual((out.payload["status"], out.payload["score"], out.payload["visible"]), (h.STATUS_FILTERED, 0, False), name)
            self.assertIn("Filtered before scoring", out.payload["verdict"])
            groq.evaluate.assert_not_called()

    def test_groq_result_sets_status_and_visibility(self) -> None:
        for score, status, visible in [(70, h.STATUS_APPLY, True), (69, h.STATUS_STRETCH, True), (50, h.STATUS_STRETCH, True), (49, h.STATUS_FILTERED, False)]:
            groq = mock.Mock()
            groq.evaluate.return_value = h.Evaluation(score, "v", "g")
            out = self.evaluate(posting(), groq)
            assert out.payload is not None
            self.assertEqual((out.payload["status"], out.payload["visible"]), (status, visible), score)

    def test_groq_failures(self) -> None:
        groq = mock.Mock()
        groq.evaluate.side_effect = h.TransientError("429")
        self.assertEqual(self.evaluate(posting(), groq).kind, "transient")
        groq.evaluate.side_effect = ValueError("no json")
        self.assertEqual(self.evaluate(posting(), groq).kind, "failed")
        groq.evaluate.side_effect = h.GroqAuthError("bad key")
        with self.assertRaises(pl.FatalRunError):
            self.evaluate(posting(), groq)

    def test_search_found_jobs_only_trust_creation_dates(self) -> None:
        sj = pl.SearchJob(self.ident, "Marketing Intern", "https://jobs.lever.co/acme/x")
        hyd = h.make_search_hydrator(hydrate=lambda r: posting(posted="2026-10-14T11:00:00Z", posted_source="createdAt"))
        self.assertEqual(hyd(sj).published_field, "createdAt")  # type: ignore[union-attr]
        hyd = h.make_search_hydrator(hydrate=lambda r: posting(posted="2026-10-14", posted_source="updated_at"))
        listed = hyd(sj)
        assert listed is not None
        self.assertEqual((listed.published, listed.updated), ("", "2026-10-14"))  # last-modified is never publication
        hyd = h.make_search_hydrator(hydrate=lambda r: (_ for _ in ()).throw(h.TransientError("t")))
        with self.assertRaises(pl.RetryableHydration):  # temporary: queued for a retry, not dropped
            hyd(sj)
        hyd = h.make_search_hydrator(hydrate=lambda r: (_ for _ in ()).throw(h.ClosedPosting("gone")))
        self.assertIsNone(hyd(sj))  # closed: nothing to retry


# --------------------------------------------------------------------------- Groq


class FakeResponse:
    def __init__(self, status: int, body: dict | None = None, headers: dict | None = None, text: str = "") -> None:
        self.status_code, self._body, self.headers, self.text = status, body or {}, headers or {}, text

    def json(self) -> dict:
        return self._body


def groq_ok(score: int = 80) -> FakeResponse:
    content = f'{{"score": {score}, "verdict": "ok", "missing_gaps": "None"}}'
    return FakeResponse(200, {"choices": [{"message": {"content": content}}], "usage": {"total_tokens": 900}})


class ParseTests(unittest.TestCase):
    def test_parse_evaluation_is_defensive(self) -> None:
        ev = h.parse_evaluation('```json\n{"score":"85/100","verdict":"Good.\\nfit","missing_gaps":["a","b"]}\n```')
        self.assertEqual((ev.score, ev.verdict, ev.missing_gaps), (85, "Good. fit", "a, b"))
        self.assertEqual(h.parse_evaluation('Sure! {"score": 140, "verdict": "x"}').score, 100)
        for bad in ["", "nope", '{"verdict":"x"}', "[1]", '{"score": null}']:
            with self.assertRaises(ValueError):
                h.parse_evaluation(bad)


class GroqTests(unittest.TestCase):
    def client(self, responses: list[FakeResponse]) -> tuple[h.GroqClient, mock.Mock]:
        cfg = h.replace(h.Config.from_env(), groq_api_key="k", llm_interval=0.0, groq_tpm=10**9, groq_fallback_tpm=10**9)
        c = h.GroqClient(cfg)
        c.http = mock.Mock()
        c.http.post.side_effect = responses
        return c, c.http.post

    def test_429_on_primary_falls_back_to_8b(self) -> None:
        c, post = self.client([FakeResponse(429), groq_ok(77)])
        with mock.patch.object(h.time, "sleep"):
            ev = c.evaluate(settings(), posting())
        self.assertEqual(ev.score, 77)
        self.assertEqual([call.kwargs["json"]["model"] for call in post.call_args_list], [c.cfg.groq_model, c.cfg.groq_fallback_model])
        self.assertEqual(post.call_args.kwargs["json"]["response_format"], {"type": "json_object"})

    def test_fallback_429_backs_off_then_succeeds(self) -> None:
        c, _ = self.client([FakeResponse(429), FakeResponse(429, headers={"retry-after": "3"}), groq_ok()])
        with mock.patch.object(h.time, "sleep") as sleep:
            c.evaluate(settings(), posting())
        self.assertIn(mock.call(3.0), sleep.call_args_list)

    def test_exhausted_retries_raise_transient(self) -> None:
        c, _ = self.client([FakeResponse(429)] * h.GROQ_ATTEMPTS)
        with mock.patch.object(h.time, "sleep"), self.assertRaises(h.TransientError):
            c.evaluate(settings(), posting())

    def test_a_model_the_key_cannot_use_switches_models_without_failing_the_job(self) -> None:
        gone = FakeResponse(404, text='{"error":{"code":"model_not_found"}}')
        c, post = self.client([gone, groq_ok(66)])
        ev = c.evaluate(settings(), posting())
        self.assertEqual(ev.score, 66)
        self.assertEqual([x.kwargs["json"]["model"] for x in post.call_args_list], [c.cfg.groq_model, c.cfg.groq_fallback_model])
        self.assertEqual(c.unavailable, {c.cfg.groq_model})
        c.http.post.side_effect = [groq_ok(70)]
        c.evaluate(settings(), posting())  # next job goes straight to the working model
        self.assertEqual(c.http.post.call_args.kwargs["json"]["model"], c.cfg.groq_fallback_model)

    def test_no_usable_model_is_fatal_not_a_per_job_failure(self) -> None:
        gone = FakeResponse(404, text='{"error":{"code":"model_not_found"}}')
        c, _ = self.client([gone, gone])
        with self.assertRaises(h.GroqAuthError) as ctx:
            c.evaluate(settings(), posting())
        self.assertIn("GROQ_MODEL", str(ctx.exception))

    def test_reported_rate_limit_replaces_the_guessed_budget(self) -> None:
        ok = groq_ok()
        ok.headers = {"x-ratelimit-limit-tokens": "6000"}
        c, _ = self.client([ok])
        c.evaluate(settings(), posting())
        self.assertEqual(c.budgets[c.cfg.groq_model].tpm, 6000)

    def test_bad_key_aborts(self) -> None:
        c, _ = self.client([FakeResponse(401)])
        with self.assertRaises(h.GroqAuthError):
            c.evaluate(settings(), posting())

    def test_unparseable_json_retries_then_value_error(self) -> None:
        bad = FakeResponse(200, {"choices": [{"message": {"content": "not json"}}]})
        c, _ = self.client([bad] * h.GROQ_ATTEMPTS)
        with mock.patch.object(h.time, "sleep"), self.assertRaises(ValueError):
            c.evaluate(settings(), posting())


class GroqDeadlineTests(unittest.TestCase):
    """A Groq call cannot outlive the run's evaluation cutoff (D-51): every wait stops at the deadline."""

    def client(self, responses: list[FakeResponse], deadline: float | None) -> tuple[h.GroqClient, mock.Mock]:
        cfg = h.replace(h.Config.from_env(), groq_api_key="k", llm_interval=0.0, groq_tpm=10**9, groq_fallback_tpm=10**9)
        c = h.GroqClient(cfg)
        c.deadline = deadline
        c.http = mock.Mock()
        c.http.post.side_effect = responses
        return c, c.http.post

    def test_deadline_before_any_request_raises_deferred(self) -> None:
        c, post = self.client([groq_ok()], deadline=500.0)
        with mock.patch.object(h.time, "monotonic", return_value=1000.0), mock.patch.object(h.time, "sleep") as sleep:
            with self.assertRaises(h.GroqDeferred) as ctx:
                c.evaluate(settings(), posting())
        self.assertEqual(ctx.exception.reason, "deadline")
        post.assert_not_called()
        sleep.assert_not_called()

    def test_deadline_stops_token_wait_loop(self) -> None:
        c, post = self.client([groq_ok()], deadline=None)
        clock = {"t": 1000.0}
        sleeps: list[float] = []

        def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            if len(sleeps) > 50:  # a regression must fail here instead of hanging the suite
                raise AssertionError("token wait loop ignored the deadline")
            clock["t"] += seconds

        with mock.patch.object(h.time, "monotonic", side_effect=lambda: clock["t"]), mock.patch.object(h.time, "sleep", side_effect=fake_sleep):
            c.budgets[c.cfg.groq_model].tpm = 10**6
            c.budgets[c.cfg.groq_model].add(10**6)  # the per-minute window is full for the next 60 s
            c.deadline = clock["t"] + 25
            with self.assertRaises(h.GroqDeferred) as ctx:
                c.evaluate(settings(), posting())
        self.assertEqual(ctx.exception.reason, "deadline")
        self.assertLessEqual(len(sleeps), 5)
        post.assert_not_called()

    def test_token_budget_wait_without_deadline_waits_for_the_window(self) -> None:
        clock = {"t": 0.0}
        tb = h.TokenBudget(1000)
        with mock.patch.object(h.time, "monotonic", side_effect=lambda: clock["t"]), mock.patch.object(
            h.time, "sleep", side_effect=lambda s: clock.__setitem__("t", clock["t"] + s)
        ):
            tb.add(1000)
            tb.wait(100)  # no deadline: returns once the 60 s window has passed
        self.assertGreaterEqual(clock["t"], 60)

    def test_deadline_stops_429_backoff_sleep(self) -> None:
        c, post = self.client([FakeResponse(429), FakeResponse(429, headers={"retry-after": "30"}), groq_ok()], deadline=110.0)
        with mock.patch.object(h.time, "monotonic", return_value=100.0), mock.patch.object(h.time, "sleep") as sleep:
            with self.assertRaises(h.GroqDeferred) as ctx:
                c.evaluate(settings(), posting())
        self.assertEqual(ctx.exception.reason, "deadline")
        self.assertNotIn(mock.call(30.0), sleep.call_args_list)
        self.assertEqual(post.call_count, 2)  # the third attempt never started

    def test_deadline_stops_5xx_backoff_sleep(self) -> None:
        c, post = self.client([FakeResponse(503), groq_ok()], deadline=102.0)
        with mock.patch.object(h.time, "monotonic", return_value=100.0), mock.patch.object(h.time, "sleep") as sleep:
            with self.assertRaises(h.GroqDeferred):
                c.evaluate(settings(), posting())  # the 3 s backoff would pass the deadline
        sleep.assert_not_called()
        self.assertEqual(post.call_count, 1)

    def test_deadline_stops_request_error_backoff_sleep(self) -> None:
        c, post = self.client([requests.ConnectionError("boom"), groq_ok()], deadline=102.0)
        with mock.patch.object(h.time, "monotonic", return_value=100.0), mock.patch.object(h.time, "sleep") as sleep:
            with self.assertRaises(h.GroqDeferred):
                c.evaluate(settings(), posting())
        sleep.assert_not_called()
        self.assertEqual(post.call_count, 1)

    def test_no_deadline_keeps_old_behaviour(self) -> None:
        c, _ = self.client([FakeResponse(429), FakeResponse(429, headers={"retry-after": "3"}), groq_ok(71)], deadline=None)
        with mock.patch.object(h.time, "sleep") as sleep:
            ev = c.evaluate(settings(), posting())
        self.assertEqual(ev.score, 71)
        self.assertIn(mock.call(3.0), sleep.call_args_list)

    def test_a_deadline_with_time_left_does_not_change_the_result(self) -> None:
        c, _ = self.client([FakeResponse(429), FakeResponse(429, headers={"retry-after": "3"}), groq_ok(72)], deadline=h.time.monotonic() + 10_000)
        with mock.patch.object(h.time, "sleep") as sleep:
            ev = c.evaluate(settings(), posting())
        self.assertEqual(ev.score, 72)
        self.assertIn(mock.call(3.0), sleep.call_args_list)


class GroqBudgetTests(unittest.TestCase):
    """The daily token governor inside the Groq client (D-50): per-model spending, metering, daily-limit 429s, limits headers."""

    API_KEY = "gsk_test_key_do_not_leak"

    def client(self, responses: list[FakeResponse], budgets: dict[str, int] | None = None, *, daily: bool = True) -> tuple[h.GroqClient, mock.Mock, eb.GroqBudget | None]:
        cfg = h.replace(h.Config.from_env(), groq_api_key=self.API_KEY, llm_interval=0.0, groq_tpm=10**9, groq_fallback_tpm=10**9)
        budget = eb.GroqBudget(day="", budgets=budgets or {cfg.groq_model: 10000, cfg.groq_fallback_model: 10000}) if daily else None
        c = h.GroqClient(cfg, budget=budget) if daily else h.GroqClient(cfg)
        c.http = mock.Mock()
        c.http.post.side_effect = responses
        return c, c.http.post, budget

    def metered(self, fn: Any) -> dict[str, float]:
        before = METER.snapshot()
        fn()
        return METER.since(before)

    def models(self, post: mock.Mock) -> list[str]:
        return [call.kwargs["json"]["model"] for call in post.call_args_list]

    def usage_response(self, usage: Any, score: int = 80, headers: dict | None = None) -> FakeResponse:
        content = f'{{"score": {score}, "verdict": "ok", "missing_gaps": "None"}}'
        body: dict[str, Any] = {"choices": [{"message": {"content": content}}]}
        if usage is not None:
            body["usage"] = usage
        return FakeResponse(200, body, headers=headers)

    def estimate(self) -> int:
        messages = h.build_messages(settings(), posting())
        return sum(len(m["content"]) for m in messages) // 3 + h.MAX_OUTPUT_TOKENS

    def test_charges_usage_tokens_to_the_answering_model_and_meters_cached(self) -> None:
        full = {"total_tokens": 900, "prompt_tokens": 700, "prompt_tokens_details": {"cached_tokens": 400}}
        c, _, budget = self.client([self.usage_response(full)])
        assert budget is not None
        delta = self.metered(lambda: c.evaluate(settings(), posting()))
        self.assertEqual(budget.used, {c.cfg.groq_model: 900})
        self.assertEqual(
            (delta.get("groq_tokens_primary"), delta.get("groq_prompt_tokens"), delta.get("groq_cached_tokens"), delta.get("groq_completions"), delta.get("groq_tokens_fallback")),
            (900, 700, 400, 1, None),
        )
        # an answer from the fallback model is charged to the fallback, not to the primary
        c2, post2, budget2 = self.client([FakeResponse(429), self.usage_response({"total_tokens": 500, "prompt_tokens": 450})])
        assert budget2 is not None
        with mock.patch.object(h.time, "sleep"):
            delta2 = self.metered(lambda: c2.evaluate(settings(), posting()))
        self.assertEqual(budget2.used, {c2.cfg.groq_fallback_model: 500})
        self.assertEqual((delta2.get("groq_tokens_fallback"), delta2.get("groq_tokens_primary")), (500, None))

    def test_missing_usage_charges_the_estimate(self) -> None:
        c, _, budget = self.client([self.usage_response(None)])
        assert budget is not None
        delta = self.metered(lambda: c.evaluate(settings(), posting()))
        self.assertEqual(budget.used, {c.cfg.groq_model: self.estimate()})
        self.assertEqual(delta.get("groq_tokens_primary"), self.estimate())

    def test_non_numeric_usage_is_ignored_not_raised(self) -> None:
        weird = [{"total_tokens": "abc", "prompt_tokens": [1], "prompt_tokens_details": "x"}, {"total_tokens": None, "prompt_tokens_details": {"cached_tokens": "many"}}, ["not", "a", "dict"], {"total_tokens": True}]
        for usage in weird:
            with self.subTest(usage=usage):
                c, _, budget = self.client([self.usage_response(usage, headers={"x-ratelimit-limit-tokens": "lots", "x-ratelimit-remaining-tokens": None})])  # type: ignore[dict-item]
                assert budget is not None
                ev = c.evaluate(settings(), posting())
                self.assertEqual(ev.score, 80)
                self.assertEqual(budget.used, {c.cfg.groq_model: self.estimate()})

    def test_daily_limit_429_by_retry_after_marks_model_spent_without_sleeping(self) -> None:
        c, post, budget = self.client([FakeResponse(429, headers={"retry-after": "3600"}), groq_ok(71)])
        assert budget is not None
        with mock.patch.object(h.time, "sleep") as sleep:
            ev = c.evaluate(settings(), posting())
        self.assertEqual(ev.score, 71)
        self.assertEqual(budget.exhausted, {c.cfg.groq_model})
        self.assertEqual(self.models(post), [c.cfg.groq_model, c.cfg.groq_fallback_model])
        self.assertEqual([x for x in sleep.call_args_list if x.args and x.args[0] >= 60], [])
        self.assertEqual(sleep.call_args_list, [])  # not even a short backoff
        c.http.post.side_effect = [groq_ok(72)]  # the next job: the primary stays spent for the day
        c.evaluate(settings(), posting())
        self.assertEqual(c.http.post.call_args.kwargs["json"]["model"], c.cfg.groq_fallback_model)

    def test_daily_limit_429_by_body_text_marks_model_spent(self) -> None:
        text = '{"error":{"message":"Rate limit reached for model in organization on tokens per day (TPD): Limit 200000, Used 199990"}}'
        c, post, budget = self.client([FakeResponse(429, text=text), groq_ok(60)])
        assert budget is not None
        with mock.patch.object(h.time, "sleep") as sleep:
            c.evaluate(settings(), posting())
        self.assertEqual(budget.exhausted, {c.cfg.groq_model})
        self.assertEqual(sleep.call_args_list, [])
        self.assertEqual(self.models(post), [c.cfg.groq_model, c.cfg.groq_fallback_model])

    def test_daily_limit_lock_lasts_as_long_as_retry_after_or_an_hour(self) -> None:
        """WR-01: the persisted lock follows Groq's own wait (capped at a day); with none given it is an hour, not the rest of the UTC day."""
        now = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
        cases = [({"retry-after": "5400"}, 5400), ({"retry-after": "999999"}, 86400), ({}, 3600), ({"retry-after": "nan"}, 3600), ({"retry-after": "7"}, 3600)]
        for headers, seconds in cases:
            with self.subTest(headers=headers):
                self.assertEqual(h._daily_lock_until(FakeResponse(429, headers=headers), now), now + timedelta(seconds=seconds))

    def test_daily_limit_429_records_when_the_model_may_be_tried_again(self) -> None:
        c, _, budget = self.client([FakeResponse(429, headers={"retry-after": "5400"}), groq_ok(71)])
        assert budget is not None
        with mock.patch.object(h.time, "sleep"):
            c.evaluate(settings(), posting())
        until = datetime.fromisoformat(budget.exhausted_until[c.cfg.groq_model])
        self.assertAlmostEqual((until - datetime.now(timezone.utc)).total_seconds(), 5400, delta=120)

    def test_model_output_in_groq_errors_never_reaches_the_log(self) -> None:
        """WR-04: the log of a public repository must not carry job or resume content (a json_validate_failed body quotes the model's answer)."""
        secret = "CANDIDATE-PRIVATE-DETAIL-xyz"
        invalid = FakeResponse(400, text='{"error":{"code":"json_validate_failed","failed_generation":"' + secret + '"}}')
        unusable = FakeResponse(200, {"choices": [{"message": {"content": secret + " no braces here"}}], "usage": {"total_tokens": 900}})
        c, _, _ = self.client([invalid, unusable, groq_ok(70)])
        with self.assertLogs(h.log, level="WARNING") as logs, mock.patch.object(h.time, "sleep"):
            c.evaluate(settings(), posting())
        text = "\n".join(logs.output)
        self.assertNotIn(secret, text)
        self.assertIn("produced invalid JSON", text)
        self.assertIn("Unusable Groq response", text)

    def test_a_per_minute_429_is_not_a_daily_limit(self) -> None:
        text = '{"error":{"message":"Rate limit reached on tokens per minute (TPM): Limit 8000"}}'
        c, _, budget = self.client([FakeResponse(429, headers={"retry-after": "7"}, text=text), groq_ok(60)])
        assert budget is not None
        with mock.patch.object(h.time, "sleep"):
            c.evaluate(settings(), posting())
        self.assertEqual(budget.exhausted, set())  # only the 90 s hold applies

    def test_primary_budget_spent_uses_fallback(self) -> None:
        c, post, budget = self.client([groq_ok(66)])
        assert budget is not None
        budget.used[c.cfg.groq_model] = 8000  # the non-fresh share (80% of 10000) is spent
        c.evaluate(settings(), posting())
        self.assertEqual(self.models(post), [c.cfg.groq_fallback_model])

    def test_both_budgets_spent_raises_deferred_without_a_request(self) -> None:
        c, post, budget = self.client([groq_ok()])
        assert budget is not None
        budget.used.update({c.cfg.groq_model: 10000, c.cfg.groq_fallback_model: 10000})
        with self.assertRaises(h.GroqDeferred) as ctx:
            c.evaluate(settings(), posting(), fresh=True)
        self.assertEqual((ctx.exception.reason, str(ctx.exception)), ("budget", "budget"))
        self.assertNotIsInstance(ctx.exception, h.TransientError)  # a deferral is not a scoring outage
        post.assert_not_called()

    def test_a_model_spent_during_the_call_is_not_retried(self) -> None:
        c, post, budget = self.client([FakeResponse(429, headers={"retry-after": "7200"}), FakeResponse(429, headers={"retry-after": "7200"})])
        assert budget is not None
        with mock.patch.object(h.time, "sleep"), self.assertRaises(h.GroqDeferred):
            c.evaluate(settings(), posting())
        self.assertEqual(len(post.call_args_list), 2)  # one request per model, then deferred
        self.assertEqual(budget.exhausted, {c.cfg.groq_model, c.cfg.groq_fallback_model})

    def test_reserve_lets_only_fresh_jobs_use_the_last_share(self) -> None:
        c, post, budget = self.client([groq_ok(81)])
        assert budget is not None
        budget.used.update({c.cfg.groq_model: 8000, c.cfg.groq_fallback_model: 8000})  # both at 80%
        with self.assertRaises(h.GroqDeferred):
            c.evaluate(settings(), posting(), fresh=False)
        post.assert_not_called()
        ev = c.evaluate(settings(), posting(), fresh=True)
        self.assertEqual(ev.score, 81)
        self.assertEqual(self.models(post), [c.cfg.groq_model])

    def test_records_rate_limit_headers_per_model_without_request_headers(self) -> None:
        wanted = {
            "x-ratelimit-limit-requests": "1000", "x-ratelimit-remaining-requests": "999", "x-ratelimit-reset-requests": "1m26.4s",
            "x-ratelimit-limit-tokens": "8000", "x-ratelimit-remaining-tokens": "7100", "x-ratelimit-reset-tokens": "6.75s",
        }  # fmt: skip
        long_value = "z" * 90
        ok = self.usage_response({"total_tokens": 900}, headers=dict(wanted, **{"x-request-id": "abc", "set-cookie": "s", "x-ratelimit-reset-tokens": long_value}))
        c, post, _ = self.client([FakeResponse(429, headers={"x-ratelimit-limit-requests": "1000", "authorization": f"Bearer {self.API_KEY}"}), ok])
        with mock.patch.object(h.time, "sleep"):
            c.evaluate(settings(), posting())
        raw = c.limits_json()
        data = json.loads(raw)
        primary, fallback = c.cfg.groq_model, c.cfg.groq_fallback_model
        self.assertEqual({k: v for k, v in data[fallback].items() if k not in {"at", "x-ratelimit-reset-tokens"}}, {k: v for k, v in wanted.items() if k != "x-ratelimit-reset-tokens"})
        self.assertEqual(data[fallback]["x-ratelimit-reset-tokens"], long_value[:40])  # cut at 40 characters
        self.assertEqual(set(data[primary]), {"x-ratelimit-limit-requests", "at"})  # the 429 answer's headers count too
        self.assertRegex(data[fallback]["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        for secret in (self.API_KEY, "Bearer", "authorization", "set-cookie", "x-request-id"):
            self.assertNotIn(secret.lower(), raw.lower())
        self.assertLessEqual(len(raw), 1000)
        self.assertEqual(post.call_args.kwargs["headers"], {"Authorization": f"Bearer {self.API_KEY}"})  # the key is sent, never stored

    def test_limits_json_is_bounded_and_empty_without_answers(self) -> None:
        c, _, _ = self.client([])
        self.assertEqual(json.loads(c.limits_json()), {})
        for i in range(60):
            c.limits[f"model-{i}"] = {"x-ratelimit-limit-requests": "9" * 40, "at": "2026-10-26T00:00:00Z"}
        self.assertLessEqual(len(c.limits_json()), 1000)

    def test_evaluator_maps_deferral_to_deferred_outcome_without_failure(self) -> None:
        s = settings()
        groq = mock.Mock()
        groq.evaluate.side_effect = h.GroqDeferred("budget")
        ev = h.make_evaluator(s, groq, h.excluded_title_regex(s.excluded), hydrate=lambda r: posting())
        ident = bd.JobIdentity("lever", "acme", "123e4567-e89b-12d3-a456-426614174000")
        st = lg.JobState(ident.key, seen=True, freshness=fr.VERIFIED_FRESH, seen_detail={"board": "acme", "title": "Marketing Intern"})
        out = ev(ident, st)
        self.assertEqual((out.kind, out.message, out.payload), ("deferred", "budget", None))
        self.assertEqual(groq.evaluate.call_args.kwargs.get("fresh"), True)  # verified-fresh jobs may use the reserve
        stale = lg.JobState(ident.key, seen=True, freshness=fr.RECENT, seen_detail={"board": "acme"})
        ev(ident, stale)
        self.assertEqual(groq.evaluate.call_args.kwargs.get("fresh"), False)

    def test_scored_payload_records_the_model(self) -> None:
        s = settings()
        ident = bd.JobIdentity("lever", "acme", "123e4567-e89b-12d3-a456-426614174000")
        st = lg.JobState(ident.key, seen=True, freshness=fr.VERIFIED_FRESH, seen_detail={"board": "acme", "title": "Marketing Intern"})
        groq = mock.Mock()
        groq.evaluate.return_value = h.Evaluation(88, "v", "g", model="the-backup-model")
        out = h.make_evaluator(s, groq, h.excluded_title_regex(s.excluded), hydrate=lambda r: posting())(ident, st)
        assert out.payload is not None
        self.assertEqual((out.kind, out.payload["model"], out.payload["score"]), ("done", "the-backup-model", 88))
        groq.evaluate.return_value = h.Evaluation(88, "v", "g")  # no model reported: the key is left out
        again = h.make_evaluator(s, groq, h.excluded_title_regex(s.excluded), hydrate=lambda r: posting())(ident, st)
        assert again.payload is not None
        self.assertNotIn("model", again.payload)
        closed = h.make_evaluator(s, groq, None, hydrate=lambda r: (_ for _ in ()).throw(h.ClosedPosting("404")))(ident, st)
        assert closed.payload is not None
        self.assertNotIn("model", closed.payload)  # only scored evaluations name a model

    def test_no_daily_budget_keeps_old_behaviour(self) -> None:
        c, post, _ = self.client(
            [FakeResponse(429, headers={"retry-after": "3600"}), FakeResponse(429, headers={"retry-after": "3600"}), groq_ok(75)], daily=False
        )
        self.assertIsNone(c.daily)
        with mock.patch.object(h.time, "sleep") as sleep:
            ev = c.evaluate(settings(), posting())
        self.assertEqual(ev.score, 75)
        self.assertEqual(self.models(post), [c.cfg.groq_model, c.cfg.groq_fallback_model, c.cfg.groq_fallback_model])
        self.assertIn(mock.call(60.0), sleep.call_args_list)  # the old capped backoff on the fallback, not "model spent"
        self.assertEqual(ev.model, c.cfg.groq_fallback_model)


class GroqSettingsTests(unittest.TestCase):
    """Settings rows and entry-point wiring for the daily Groq token budget (D-50)."""

    def parse(self, raw: dict[str, str], env: dict[str, str] | None = None) -> h.Settings:
        with mock.patch.dict(os.environ):
            for key in h.SETTING_DEFAULTS:
                os.environ.pop(key.upper(), None)
            os.environ.update(env or {})
            return h.Settings.from_values(dict(raw, Resume_Text="r" * 300))

    def test_groq_budget_settings_default_parse_and_fallback_blank_means_same(self) -> None:
        def pair(raw: dict[str, str], env: dict[str, str] | None = None) -> tuple[int, int]:
            s = self.parse(raw, env)
            return s.groq_daily_token_budget, s.groq_fallback_daily_token_budget

        self.assertEqual(pair({}), (100000, 100000))
        self.assertEqual(pair({"Groq_Daily_Token_Budget": "200000", "Groq_Fallback_Daily_Token_Budget": ""}), (200000, 200000))
        self.assertEqual(pair({"Groq_Daily_Token_Budget": "200000", "Groq_Fallback_Daily_Token_Budget": "500000"}), (200000, 500000))
        self.assertEqual(pair({"Groq_Daily_Token_Budget": "-5"}), (0, 0))  # a negative value never spends
        self.assertEqual(pair({"Groq_Daily_Token_Budget": "1.9e5"}), (190000, 190000))  # a float string truncates through _int_or
        self.assertEqual(pair({"Groq_Daily_Token_Budget": "0", "Groq_Fallback_Daily_Token_Budget": "300"}), (0, 300))
        self.assertEqual(pair({"Groq_Daily_Token_Budget": "abc"}), (100000, 100000))  # unreadable: the default, never a crash
        self.assertEqual(pair({"Groq_Fallback_Daily_Token_Budget": "xyz"}), (100000, 100000))
        self.assertEqual(pair({}, {"GROQ_DAILY_TOKEN_BUDGET": "90000", "GROQ_FALLBACK_DAILY_TOKEN_BUDGET": "40000"}), (90000, 40000))

    def test_groq_budget_default_is_half_of_the_recorded_daily_limit_because_the_window_rolls(self) -> None:
        """D-53: the owner read 200,000 tokens/day per model from the account's limits page (2026-10-26); the daily request
        window was measured as rolling (reset 86.4 s per request), so the default is half the limit (two consecutive UTC-day
        budgets stay below a rolling 24-hour limit), not 85%. The two limits are equal, so the fallback row stays blank."""
        self.assertEqual(h.GROQ_TPD_PRIMARY, 200000)
        self.assertEqual(h.GROQ_TPD_FALLBACK, 200000)
        self.assertEqual(h.SETTING_DEFAULTS["Groq_Daily_Token_Budget"], str(h.GROQ_TPD_PRIMARY // 2))
        self.assertEqual(h.DEFAULT_GROQ_DAILY_TOKENS, h.GROQ_TPD_PRIMARY // 2)
        self.assertEqual(h.SETTING_DEFAULTS["Groq_Fallback_Daily_Token_Budget"], "")  # same limit: blank = same
        s = self.parse({})
        self.assertLess(s.groq_daily_token_budget * 2, h.GROQ_TPD_PRIMARY + 1)  # two budget days fit in one rolling 24 h
        self.assertEqual((s.groq_daily_token_budget, s.groq_fallback_daily_token_budget), (h.GROQ_TPD_PRIMARY // 2, h.GROQ_TPD_FALLBACK // 2))

    def test_groq_budget_rows_exist_and_say_what_they_limit_and_where_the_figure_came_from(self) -> None:
        rows = {key: (default, note) for key, default, note in h.DEFAULT_SETTINGS}
        self.assertEqual(h.SETTING_DEFAULTS["Groq_Daily_Token_Budget"], "100000")
        self.assertEqual(h.SETTING_DEFAULTS["Groq_Fallback_Daily_Token_Budget"], "")
        primary, fallback = rows["Groq_Daily_Token_Budget"][1], rows["Groq_Fallback_Daily_Token_Budget"][1]
        for text in ("per model per UTC day", "50%", "200,000", "2026-10-26", "limits page", "rolling", "D-53"):
            self.assertIn(text, primary)
        self.assertNotIn("provisional", primary)  # the figure now rests on the account's limits page, not the public table
        self.assertIn("Blank = same", fallback)
        keys = [k for k, _, _ in h.DEFAULT_SETTINGS]
        self.assertEqual(keys[keys.index("Max_New_Boards_Per_Run") + 1 : keys.index("Max_New_Boards_Per_Run") + 3], ["Groq_Daily_Token_Budget", "Groq_Fallback_Daily_Token_Budget"])

    def test_groq_budget_source_note_names_settings_environment_or_default(self) -> None:
        def note(raw: dict[str, str], env: dict[str, str] | None = None) -> str:
            s = self.parse(raw, env)
            with mock.patch.dict(os.environ, env or {}):
                if not env:
                    os.environ.pop("GROQ_DAILY_TOKEN_BUDGET", None)
                return h.groq_budget_note(raw, s)

        self.assertEqual(note({"Groq_Daily_Token_Budget": "200000"}), "Groq daily token budget 200000 / 200000 per UTC day from Settings tab")
        self.assertEqual(note({}, {"GROQ_DAILY_TOKEN_BUDGET": "90000"}), "Groq daily token budget 90000 / 90000 per UTC day from environment")
        self.assertEqual(
            note({}), "Groq daily token budget 100000 / 100000 per UTC day from default (50% of this account's 200,000 tokens/day per model, D-53)"
        )
        self.assertIn("from Settings tab", note({"Groq_Daily_Token_Budget": " 5 "}, {"GROQ_DAILY_TOKEN_BUDGET": "90000"}))  # the Sheet wins over the environment
        self.assertIn("from default", note({"Groq_Daily_Token_Budget": "   "}))  # a blank cell is not a setting

    def test_groq_budget_accepts_thousands_separators_and_the_note_names_an_unreadable_value(self) -> None:
        """WR-03: "150,000" is how the owner writes the figure; a value that is still not a number must not look like it came from the sheet."""

        def note(raw: dict[str, str]) -> tuple[tuple[int, int], str]:
            s = self.parse(raw)
            with mock.patch.dict(os.environ):
                os.environ.pop("GROQ_DAILY_TOKEN_BUDGET", None)
                os.environ.pop("GROQ_FALLBACK_DAILY_TOKEN_BUDGET", None)
                return (s.groq_daily_token_budget, s.groq_fallback_daily_token_budget), h.groq_budget_note(raw, s)

        self.assertEqual(note({"Groq_Daily_Token_Budget": "150,000"}), ((150000, 150000), "Groq daily token budget 150000 / 150000 per UTC day from Settings tab"))
        self.assertEqual(note({"Groq_Daily_Token_Budget": "100,000", "Groq_Fallback_Daily_Token_Budget": "50,000"})[0], (100000, 50000))
        self.assertEqual(note({"Groq_Daily_Token_Budget": "1,5"})[0], (100000, 100000))  # not a thousands pattern: unreadable, so the default
        for bad in ("100k", "inf", "-inf", "nan", "lots"):
            with self.subTest(bad=bad):
                budgets, text = note({"Groq_Daily_Token_Budget": bad})  # "inf" used to raise OverflowError out of Settings.from_values
                self.assertEqual(budgets, (100000, 100000))
                self.assertIn(f"Settings tab value '{bad}' is not a number, default 100000 in force", text)
                self.assertNotIn("from Settings tab", text)
        self.assertIn("fallback value 'xyz' is not a number", note({"Groq_Daily_Token_Budget": "5000", "Groq_Fallback_Daily_Token_Budget": "xyz"})[1])
        self.assertEqual(h._int_or("inf", 7), 7)

    def test_main_runs_with_a_per_model_budget_wired_into_client_and_pipeline(self) -> None:
        fake = mock.Mock()
        fake.state = mock.Mock()
        fake.load_settings.return_value = {"Groq_Daily_Token_Budget": "5000", "Groq_Fallback_Daily_Token_Budget": "3000"}
        fake.sheet_timezone.return_value = None
        fake.state.acquire_lease.return_value = mock.Mock(ok=True, token="t")
        fake.state.holds_lease.return_value = True
        env = {"GOOGLE_SHEET_ID": "sheet", "GOOGLE_SERVICE_ACCOUNT_JSON": "{}", "GROQ_API_KEY": "k", "GITHUB_ACTIONS": "true", "TAVILY_API_KEY": ""}
        made: list[h.GroqClient] = []

        class Spy(h.GroqClient):
            def __init__(self, *a: Any, **k: Any) -> None:
                super().__init__(*a, **k)
                made.append(self)

        with mock.patch.dict("os.environ", env), mock.patch.object(h, "make_store", return_value=fake), mock.patch.object(h, "load_resume_file", return_value="r" * 300), \
                mock.patch.object(h, "GroqClient", Spy), mock.patch.object(h.dashboard, "refresh"), mock.patch.object(h.pl, "run_cycle") as run_cycle:  # fmt: skip
            run_cycle.return_value = mock.Mock(boards_ok=0, boards_failed=0, boards_total=0, boards_added=0, new_jobs=0, verified_fresh=0, evaluated=0, alerts_sent=0, alerts_failed=0, gap_since_prev_run_min=None, max_board_gap_min=None)
            self.assertEqual(h.main([]), 0)
        deps = run_cycle.call_args.args[0]
        client = made[0]
        self.assertIsNotNone(deps.groq_budget)
        self.assertIs(client.daily, deps.groq_budget)  # one shared object: the client charges what the pipeline persists
        self.assertEqual(deps.groq_budget.budgets, {client.cfg.groq_model: 5000, client.cfg.groq_fallback_model: 3000})
        self.assertEqual(deps.groq_limits(), "{}")
        fresh = lg.JobState("k", seen=True, freshness=fr.VERIFIED_FRESH)
        recent = lg.JobState("k2", seen=True, freshness=fr.RECENT)
        self.assertTrue(deps.can_score(fresh) and deps.can_score(recent))
        deps.groq_budget.used.update({client.cfg.groq_model: 4000, client.cfg.groq_fallback_model: 2400})  # both at 80%: only the reserve is left
        self.assertTrue(deps.can_score(fresh))
        self.assertFalse(deps.can_score(recent))
        deps.groq_budget.used.update({client.cfg.groq_model: 5000, client.cfg.groq_fallback_model: 3000})
        self.assertFalse(deps.can_score(fresh))
        self.assertIn("Groq daily token budget 5000 / 3000 per UTC day from Settings tab", deps.config_notes)


class ConfigDeadlineTests(unittest.TestCase):
    """Run cutoffs: configuration and the process-start anchor in main (D-51)."""

    def cfg(self, **env: str) -> h.Config:
        with mock.patch.dict("os.environ", env):
            for name in ("POLL_CUTOFF_MINUTES", "EVAL_CUTOFF_MINUTES"):
                if name not in env:
                    os.environ.pop(name, None)
            return h.Config.from_env()

    def test_deadline_cutoff_minutes_from_environment(self) -> None:
        c = self.cfg()
        self.assertEqual((c.poll_cutoff_s, c.eval_cutoff_s), (900, 1200))
        self.assertEqual((pl.POLL_CUTOFF_S, pl.EVAL_CUTOFF_S, pl.ALERT_CUTOFF_S), (900, 1200, 1320))
        c = self.cfg(POLL_CUTOFF_MINUTES="10", EVAL_CUTOFF_MINUTES="18")
        self.assertEqual((c.poll_cutoff_s, c.eval_cutoff_s), (600, 1080))
        c = self.cfg(POLL_CUTOFF_MINUTES="soon", EVAL_CUTOFF_MINUTES="")
        self.assertEqual((c.poll_cutoff_s, c.eval_cutoff_s), (900, 1200))  # non-numeric or blank: the default
        c = self.cfg(POLL_CUTOFF_MINUTES="0", EVAL_CUTOFF_MINUTES="-5")
        self.assertEqual((c.poll_cutoff_s, c.eval_cutoff_s), (60, 60))  # at least one minute

    def run_main(self, argv: list[str], env: dict[str, str]) -> tuple[Any, list[h.GroqClient]]:
        fake = mock.Mock()
        fake.state = mock.Mock()
        fake.load_settings.return_value = {}
        fake.sheet_timezone.return_value = None
        fake.state.acquire_lease.return_value = mock.Mock(ok=True, token="t")
        fake.state.holds_lease.return_value = True
        base = {"GOOGLE_SHEET_ID": "sheet", "GOOGLE_SERVICE_ACCOUNT_JSON": "{}", "GROQ_API_KEY": "k", "GITHUB_ACTIONS": "true", "TAVILY_API_KEY": ""}
        made: list[h.GroqClient] = []

        class Spy(h.GroqClient):
            def __init__(self, *a: Any, **k: Any) -> None:
                super().__init__(*a, **k)
                made.append(self)

        ticks = iter(5000.0 + i for i in range(10_000))  # the first reading is the process start
        with mock.patch.dict("os.environ", {**base, **env}), mock.patch.object(h, "make_store", return_value=fake), mock.patch.object(h, "load_resume_file", return_value="r" * 300), \
                mock.patch.object(h, "GroqClient", Spy), mock.patch.object(h.dashboard, "refresh"), mock.patch.object(h.pl, "run_cycle") as run_cycle, \
                mock.patch.object(h.time, "monotonic", side_effect=lambda: next(ticks)):  # fmt: skip
            run_cycle.return_value = mock.Mock(boards_ok=0, boards_failed=0, boards_total=0, boards_added=0, new_jobs=0, verified_fresh=0, evaluated=0, alerts_sent=0, alerts_failed=0, gap_since_prev_run_min=None, max_board_gap_min=None)
            self.assertEqual(h.main(argv), 0)
        return run_cycle, made

    def test_deadline_main_anchors_process_start_and_wires_the_cutoffs(self) -> None:
        run_cycle, made = self.run_main([], {"POLL_CUTOFF_MINUTES": "10", "EVAL_CUTOFF_MINUTES": "18"})
        deps = run_cycle.call_args.args[0]
        self.assertEqual(deps.process_t0, 5000.0)  # read at the top of main, before the Sheet connection and the writer lease
        self.assertTrue(callable(deps.clock))
        self.assertEqual((deps.poll_cutoff_s, deps.eval_cutoff_s, deps.alert_cutoff_s), (600, 1080, pl.ALERT_CUTOFF_S))
        self.assertEqual(made[0].deadline, 5000.0 + 1080)  # the Groq client stops at the evaluation cutoff

    def test_deadline_single_job_check_keeps_the_client_unbounded(self) -> None:
        fake_out = pl.EvalOutcome("transient", message="x")
        with mock.patch.object(h, "make_evaluator", return_value=lambda ident, st: fake_out):
            _, made = self.run_main_url()
        self.assertIsNone(made[0].deadline)

    def run_main_url(self) -> tuple[None, list[h.GroqClient]]:
        fake = mock.Mock()
        fake.load_settings.return_value = {}
        fake.sheet_timezone.return_value = None
        made: list[h.GroqClient] = []

        class Spy(h.GroqClient):
            def __init__(self, *a: Any, **k: Any) -> None:
                super().__init__(*a, **k)
                made.append(self)

        env = {"GOOGLE_SHEET_ID": "sheet", "GOOGLE_SERVICE_ACCOUNT_JSON": "{}", "GROQ_API_KEY": "k", "GITHUB_ACTIONS": "true", "TAVILY_API_KEY": ""}
        with mock.patch.dict("os.environ", env), mock.patch.object(h, "make_store", return_value=fake), mock.patch.object(h, "load_resume_file", return_value="r" * 300), \
                mock.patch.object(h, "GroqClient", Spy), mock.patch("builtins.print"):  # fmt: skip
            self.assertEqual(h.main(["--url", "https://boards.greenhouse.io/acme/jobs/123"]), 0)
        return None, made


# --------------------------------------------------------------------------- stores


class FakeWorksheet:
    def __init__(self, title: str, values: list[list[str]] | None = None) -> None:
        self.title, self.values, self.id = title, values or [], hash(title) % 1000
        self.appended: list[tuple[list, dict]] = []
        self.hidden = False
        self.row_count = 1000

    def get_all_values(self) -> list[list[str]]:
        return self.values

    def col_values(self, col: int) -> list[str]:
        return [r[col - 1] if len(r) >= col else "" for r in self.values]

    def append_rows(self, rows: list, **kw: object) -> None:
        self.appended.append((rows, kw))
        self.values.extend(rows)

    def row_values(self, n: int) -> list[str]:
        return list(self.values[n - 1]) if len(self.values) >= n else []

    def update(self, values: list, range_name: str, **kw: object) -> None:
        if self.title == h.TRACKER_TAB:
            if range_name == "M1":  # the one allowed edit: the My_Feedback header cell of an older tracker
                self.values[0] = list(self.values[0]) + [str(values[0][0])]
                return
            raise AssertionError("the user-facing tracker must be append-only, but update() was called")
        self.values = self.values[:1] + [list(map(str, r)) for r in values]

    def hide(self) -> None:
        self.hidden = True

    def add_rows(self, n: int) -> None:
        self.row_count += n

    def __getattr__(self, name: str):  # freeze / format etc. are cosmetic no-ops
        if name in {"clear", "delete_rows", "update_cell", "batch_clear"}:
            raise AssertionError(f"unexpected destructive call {name}()")
        return lambda *a, **k: None


class FakeSpreadsheet:
    def __init__(self, tabs: list[FakeWorksheet]) -> None:
        self.tabs = {t.title: t for t in tabs}
        self.deleted: list[str] = []

    def worksheets(self) -> list[FakeWorksheet]:
        return list(self.tabs.values())

    def worksheet(self, title: str) -> FakeWorksheet:
        return self.tabs[title]

    def add_worksheet(self, title: str, rows: int, cols: int) -> FakeWorksheet:
        self.tabs[title] = FakeWorksheet(title)
        return self.tabs[title]

    def del_worksheet(self, ws: FakeWorksheet) -> None:
        self.deleted.append(ws.title)
        del self.tabs[ws.title]

    def batch_update(self, body: dict) -> None:
        self.batches = getattr(self, "batches", []) + [body]

    def fetch_sheet_metadata(self) -> dict:
        return getattr(self, "metadata", {"sheets": []})


def sheet_store(sh: FakeSpreadsheet) -> h.SheetStore:
    store = h.SheetStore.__new__(h.SheetStore)
    store.sh = sh
    store.sheet_url = "https://docs.google.com/spreadsheets/d/FAKE"
    store.state = h.SheetState(sh)
    return store


def job(status: str = h.STATUS_APPLY, score: int | None = 88, url: str = "https://u", **kw: str) -> h.JobRow:
    return h.JobRow(status, score, kw.get("company", "Acme"), kw.get("title", "Marketing Intern"), "Remote", "good", "None", url, "2026-10-12T10:00:00Z", fr.VERIFIED_FRESH, "poll")


class SheetTests(unittest.TestCase):
    def test_bootstrap_creates_user_tabs_and_hidden_state_tabs(self) -> None:
        sh = FakeSpreadsheet([FakeWorksheet("Sheet1", [])])
        sheet_store(sh).bootstrap("MY RESUME")
        self.assertEqual(set(sh.tabs), {"Settings", "Job Tracker", "Boards", "Events", "Runs", "Inventory", "Discovery", "Lock"})
        self.assertEqual(sh.deleted, ["Sheet1"])
        by_key = {r[0]: r[1] for r in sh.tabs["Settings"].values[1:]}
        self.assertEqual((by_key["Resume_Text"], by_key["Min_Alert_Score"], by_key["Fresh_Window_Hours"], by_key["Discovery_Every_Hours"]), ("MY RESUME", "70", "12", "12"))
        self.assertEqual(sh.tabs["Job Tracker"].values[0], h.TRACKER_COLUMNS)
        self.assertEqual(h.TRACKER_COLUMNS[8], "Apply_URL")  # column I
        self.assertEqual(h.TRACKER_COLUMNS[-3:], ["Freshness", "Source", "My_Feedback"])
        for hidden in ("Boards", "Events", "Runs", "Inventory", "Discovery", "Lock"):
            self.assertTrue(sh.tabs[hidden].hidden, hidden)
        self.assertFalse(sh.tabs["Job Tracker"].hidden or sh.tabs["Settings"].hidden)

    def test_bootstrap_never_touches_existing_tabs(self) -> None:
        settings_ws = FakeWorksheet("Settings", [["Setting", "Value", "Instructions"], ["Min_Alert_Score", "55", ""]])
        tracker_ws = FakeWorksheet("Job Tracker", [h.TRACKER_COLUMNS, ["d"] * 12])
        sheet_store(FakeSpreadsheet([settings_ws, tracker_ws])).bootstrap("RESUME")
        self.assertEqual((settings_ws.appended, tracker_ws.appended), ([], []))

    def test_tracked_keys_use_identity_not_url_strings(self) -> None:
        tracked = ["2026-10-01", "", "Applied", 90, "Acme — X", "NYC", "v", "", "https://boards.greenhouse.io/acme/jobs/123?gh_src=x", "my note", "", ""]
        tracker = FakeWorksheet("Job Tracker", [h.TRACKER_COLUMNS, tracked, ["x"] * 8 + ["https://example.com/not-an-ats"]])
        store = sheet_store(FakeSpreadsheet([FakeWorksheet("Settings"), tracker]))
        self.assertEqual(h.URL_COLUMN, 9)
        self.assertEqual(store.tracked_keys(), {"greenhouse|acme|123"})
        self.assertIn(bd.parse_job_url("https://job-boards.greenhouse.io/acme/jobs/123").key, store.tracked_keys())  # type: ignore[union-attr]

    def test_tracker_append_is_append_only_and_neutralizes_formulas(self) -> None:
        tracker = FakeWorksheet("Job Tracker", [h.TRACKER_COLUMNS, ["2026-10-01", "", "Applied", 90, "Edited by me", "", "", "", "https://old", "my note", "", ""]])
        store = sheet_store(FakeSpreadsheet([tracker]))
        before = list(tracker.values[1])
        store.append_jobs([job(company="=HYPERLINK(x)")])
        rows, kw = tracker.appended[0]
        self.assertEqual(kw["value_input_option"], "USER_ENTERED")
        self.assertEqual(len(rows[0]), len(h.TRACKER_COLUMNS))
        self.assertEqual(rows[0][2:4], ["To Apply", 88])
        self.assertTrue(rows[0][4].startswith("'="))
        self.assertEqual((rows[0][9], rows[0][10], rows[0][11]), ("", "Verified fresh", "Board poll"))  # notes untouched
        self.assertEqual(tracker.values[1], before)

    def test_state_tabs_round_trip_through_the_sheet(self) -> None:
        sh = FakeSpreadsheet([])
        store = sheet_store(sh)
        store.bootstrap("R")
        rec = bd.BoardRecord("lever", "acme", "2026-10-14T00:00:00Z", "serper")
        store.state.save_boards([rec])
        self.assertEqual(store.state.load_boards()[rec.key], rec)
        ev = lg.Event("2026-10-14T00:00:00Z", "lever|acme|1", lg.SEEN, fr.RECENT, lg.PENDING, "", {"a": 1})
        store.state.append_events([ev])
        self.assertEqual(store.state.load_events(), [ev])


class MovedColumnTests(unittest.TestCase):
    """The user may reorder tracker columns (for example move My_Feedback next to My_Status). The app writes and reads by
    HEADER NAME, so a moved column never shifts values into the wrong place."""

    MOVED = ["Date_Found", "Date_Posted", "My_Status", "My_Feedback", "AI_Score", "Company_and_Title", "Location", "AI_Verdict", "Missing_Gaps", "Apply_URL", "User_Notes", "Freshness", "Source"]

    def store(self, header: list[str], rows: list[list[str]] | None = None) -> tuple[h.SheetStore, FakeWorksheet]:
        tracker = FakeWorksheet("Job Tracker", [header] + (rows or []))
        return sheet_store(FakeSpreadsheet([FakeWorksheet("Settings"), tracker])), tracker

    def test_a_new_row_lands_under_its_own_headers_when_a_column_was_moved(self) -> None:
        store, tracker = self.store(self.MOVED)
        store.append_jobs([job(score=88, url="https://boards.greenhouse.io/acme/jobs/9")])
        written = dict(zip(self.MOVED, tracker.appended[0][0][0]))
        self.assertEqual((written["My_Status"], written["AI_Score"], written["My_Feedback"], written["User_Notes"]), ("To Apply", 88, "", ""))
        self.assertEqual((written["Apply_URL"], written["Freshness"], written["Source"]), ("https://boards.greenhouse.io/acme/jobs/9", "Verified fresh", "Board poll"))
        self.assertIn("Acme", written["Company_and_Title"])
        self.assertEqual(len(tracker.appended[0][0][0]), len(self.MOVED))

    def test_an_unmoved_tracker_is_written_exactly_as_before(self) -> None:
        store, tracker = self.store(list(h.TRACKER_COLUMNS))
        r = job()
        store.append_jobs([r])
        self.assertEqual(tracker.appended[0][0][0], r.cells(tz=store.display_tz))

    def test_the_users_own_extra_columns_stay_blank(self) -> None:
        header = ["My_Notes_Mine", *self.MOVED, "Interview_Date"]
        store, tracker = self.store(header)
        store.append_jobs([job()])
        written = dict(zip(header, tracker.appended[0][0][0]))
        self.assertEqual((written["My_Notes_Mine"], written["Interview_Date"], written["My_Status"]), ("", "", "To Apply"))

    def test_a_header_without_apply_url_is_refused_not_filled_by_position(self) -> None:
        store, tracker = self.store(["a", "b", "c"])
        with self.assertRaises(h.TrackerLayoutError):
            store.append_jobs([job()])
        self.assertEqual(tracker.appended, [])

    def test_a_cleared_header_row_is_refused_and_the_row_waits(self) -> None:
        # D-46, found live: row 1 was cleared, Sheets' append filled the empty row 1, and rows went in by fixed position
        old = ["d", "", "Applied", "Would apply", 90, "Acme — X", "NYC", "v", "gap", "https://boards.greenhouse.io/acme/jobs/123", "", "Verified fresh", "Board poll"]
        store, tracker = self.store([""] * 13, [old])
        with self.assertRaises(h.TrackerLayoutError):
            store.append_jobs([job()])
        self.assertEqual(tracker.appended, [])
        self.assertEqual(store.tracked_keys(), {"greenhouse|acme|123"})  # duplicate protection still finds every job URL
        self.assertEqual(store.tracker_rows()[0].get("Apply_URL"), None)  # no header: the report cannot key the rows

    def test_header_names_are_matched_ignoring_stray_spaces_in_reports(self) -> None:
        row = ["d", "", "Applied", "Maybe", 90, "Acme — X", "NYC", "v", "gap", "https://boards.greenhouse.io/acme/jobs/123", "", "Verified fresh", "Board poll"]
        store, _ = self.store([c + " " if c in ("Apply_URL", "My_Feedback") else c for c in self.MOVED], [row])
        got = store.tracker_rows()[0]
        self.assertEqual((got["Apply_URL"], got["My_Feedback"]), ("https://boards.greenhouse.io/acme/jobs/123", "Maybe"))

    def test_a_missing_tracker_header_is_listed_under_needs_attention(self) -> None:
        import reporting
        from test_core import T0
        clean = reporting.clean_inputs([], [], [{"10/22/2026 10:03 PM": "x", "To Apply": "y"}])
        health = {"providers": []}
        out = reporting._failures(T0, clean, {}, {}, 1500, [], [], health)
        self.assertIn("tracker header missing", [r["what"] for r in out["table"]])
        clean = reporting.clean_inputs([], [], [{"Apply_URL": "https://boards.greenhouse.io/acme/jobs/1"}])
        self.assertNotIn("tracker header missing", [r["what"] for r in reporting._failures(T0, clean, {}, {}, 1500, [], [], health)["table"]])

    def test_tracked_keys_find_the_url_column_by_name_after_the_move(self) -> None:
        row = ["d", "", "Applied", "Would apply", 90, "Acme — X", "NYC", "v", "gap", "https://boards.greenhouse.io/acme/jobs/123?gh_src=x", "note", "Verified fresh", "Board poll"]
        store, _ = self.store(self.MOVED, [row, ["d"] * 9 + ["https://example.com/not-an-ats"]])
        self.assertEqual(store.tracked_keys(), {"greenhouse|acme|123"})  # column I is Missing_Gaps now: reading it by position would find nothing

    def test_row_colours_and_dropdowns_follow_the_moved_status_column(self) -> None:
        header = ["Date_Found", "My_Feedback", "My_Status", *[c for c in self.MOVED if c not in ("Date_Found", "My_Feedback", "My_Status")]]
        store, tracker = self.store(header)
        store._status_row_colors(tracker)
        formulas = [v["userEnteredValue"] for b in store.sh.batches for r in b["requests"] for v in r["addConditionalFormatRule"]["rule"]["booleanRule"]["condition"]["values"]]
        self.assertIn('=$C2="Applied"', formulas)  # My_Status is column C in this order
        header2 = ["My_Status", *[c for c in self.MOVED if c != "My_Status"]]
        store2, tracker2 = self.store(header2)
        store2._status_row_colors(tracker2)
        formulas2 = [v["userEnteredValue"] for b in store2.sh.batches for r in b["requests"] for v in r["addConditionalFormatRule"]["rule"]["booleanRule"]["condition"]["values"]]
        self.assertIn('=$A2="Applied"', formulas2)
        store2._status_dropdown(tracker2)
        self.assertEqual(store2.sh.batches[-1]["requests"][0]["setDataValidation"]["range"]["startColumnIndex"], 0)

    def test_helpers(self) -> None:
        self.assertEqual([h.column_letter(i) for i in (0, 2, 25, 26, 27)], ["A", "C", "Z", "AA", "AB"])
        self.assertEqual(h.header_index(["x", " My_Status "], "My_Status", 9), 1)
        self.assertEqual(h.header_index(["x"], "My_Status", 9), 9)

    def test_csv_tracker_follows_its_header_too(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "t.csv"
            path.write_text(",".join(self.MOVED) + "\n")
            store = h.CsvStore(path, Path(d) / "state")
            store.append_jobs([job(score=77)])
            row = store.tracker_rows()[0]
            self.assertEqual((row["AI_Score"], row["My_Feedback"], row["Source"]), ("77", "", "Board poll"))


class CsvTests(unittest.TestCase):
    def test_migrates_legacy_header_keeping_history(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "t.csv"
            path.write_text("Date_Found_UTC,Score,Status,Company_or_Title,Verdict,Missing_Gaps,URL,Date_Posted\n2026-10-01,80,To Apply,Acme,good,,https://boards.greenhouse.io/acme/jobs/7,2026-09-30\n")
            store = h.CsvStore(path, Path(d) / "state")
            store.bootstrap("")
            rows = list(csv.DictReader(path.open()))
            self.assertEqual((rows[0]["AI_Score"], rows[0]["Apply_URL"]), ("80", "https://boards.greenhouse.io/acme/jobs/7"))
            self.assertEqual(store.tracked_keys(), {"greenhouse|acme|7"})
            store.append_jobs([job(url="https://jobs.lever.co/acme/123e4567-e89b-12d3-a456-426614174000")])
            self.assertEqual(len(store.tracked_keys()), 2)
            self.assertTrue((Path(d) / "state" / "boards.csv").exists())


class RowTests(unittest.TestCase):
    def test_payload_round_trip_preserves_everything_needed_to_resend_an_alert(self) -> None:
        row = job()
        again = h.JobRow.from_payload(row.payload(True))
        self.assertEqual(again, row)


class ServiceAccountTests(unittest.TestCase):
    def test_accepts_raw_json_or_path(self) -> None:
        self.assertEqual(h.load_service_account('{"a": "line1\nline2"}')["a"], "line1\nline2")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sa.json"
            p.write_text('{"client_email": "x@y"}')
            self.assertEqual(h.load_service_account(str(p))["client_email"], "x@y")
        with self.assertRaises(RuntimeError):
            h.load_service_account("/no/such/file.json")


class AlertTests(unittest.TestCase):
    def test_telegram_message_has_all_fields_freshness_and_sheet_link(self) -> None:
        cfg = h.replace(h.Config.from_env(), telegram_token="t", telegram_chat_id="1", webhook_url="")
        with mock.patch.object(h.requests, "post", return_value=mock.Mock()) as post:
            self.assertTrue(h.send_alert(cfg, job(company="A&B", title="<Intern>"), "https://docs.google.com/spreadsheets/d/FAKE"))
        text = post.call_args.kwargs["json"]["text"]
        for needle in ["&lt;Intern&gt;", "A&amp;B", "88/100", "good", "Gaps: None", "Remote", "Verified fresh", 'href="https://u"', "spreadsheets/d/FAKE"]:
            self.assertIn(needle, text)

    def _posted_text(self, row: h.JobRow) -> str:
        cfg = h.replace(h.Config.from_env(), telegram_token="t", telegram_chat_id="1", webhook_url="")
        with mock.patch.object(h.requests, "post", return_value=mock.Mock()) as post:
            self.assertTrue(h.send_alert(cfg, row, "https://docs.google.com/spreadsheets/d/FAKE"))
        return post.call_args.kwargs["json"]["text"]

    def test_alert_message_caps_free_text_before_escaping_and_keeps_tags_whole(self) -> None:
        row = h.JobRow("To Apply", 88, "Acme", "&<>" * 3334, "&<>" * 1667, "&<>" * 3334, "&<>" * 3334, "https://u", "2026-10-12T10:00:00Z", fr.VERIFIED_FRESH, "poll", "&<>" * 3334)
        text = self._posted_text(row)
        self.assertIn("Apply here</a>", text)
        self.assertEqual(text.count("<b>"), text.count("</b>"))
        self.assertEqual(text.count("<a "), text.count("</a>"))
        import re

        self.assertEqual(re.findall(r"&(?!amp;|lt;|gt;|quot;|#x27;)", text), [])  # every ampersand starts a whole entity
        lines = text.split("\n")
        self.assertTrue(lines[0].endswith("…</b>"))  # title capped
        self.assertTrue(lines[2].endswith("…"))  # location capped
        self.assertTrue(any(line.startswith("💬") and line.endswith("…") for line in lines))  # verdict capped
        self.assertTrue(any(line.startswith("⚠️ Gaps:") and line.endswith("…") for line in lines))  # gaps capped
        self.assertTrue(any(line.startswith("⏱") and line.endswith("…") for line in lines))  # late note capped

    def test_alert_message_fits_telegram_limit_in_utf16_units(self) -> None:
        import html
        import re

        x = "\U0001d4b3"  # a 4-byte character: 2 UTF-16 code units
        row = h.JobRow("To Apply", 88, x * 10000, x * 10000, x * 10000, x * 10000, x * 10000, "https://u", "2026-10-12T10:00:00Z", fr.VERIFIED_FRESH, "poll", x * 10000)
        text = self._posted_text(row)
        plain = html.unescape(re.sub(r"<[^>]+>", "", text))
        self.assertLessEqual(len(plain.encode("utf-16-le")) // 2, 4096)
        self.assertIn("Apply here", text)  # the link line survives: nothing was sliced off the end

    def test_no_channels_means_no_alert(self) -> None:
        cfg = h.replace(h.Config.from_env(), telegram_token="", telegram_chat_id="", webhook_url="")
        self.assertFalse(h.send_alert(cfg, job()))


class DisplayTimeTests(unittest.TestCase):
    def test_tracker_times_are_central_12_hour(self) -> None:
        self.assertEqual(h.display_time("2026-10-14T21:13:28Z"), "10/14/2026 04:13 PM")  # CDT in October
        self.assertEqual(h.display_time("2026-01-15T18:05:00Z"), "01/15/2026 12:05 PM")  # CST in winter
        self.assertEqual(h.display_time("2026-10-14 21:25"), "10/14/2026 04:25 PM")  # legacy Date_Found (UTC)
        self.assertEqual(h.display_time("2026-10-14"), "10/14/2026")  # day precision: no invented time
        self.assertEqual((h.display_time(""), h.display_time("n/a")), ("", "n/a"))


if __name__ == "__main__":
    unittest.main()

    def test_timezone_resolution_prefers_the_user_then_the_sheet_then_the_default(self) -> None:
        tz, source, warn = h.resolve_timezone("America/New_York", "America/Los_Angeles")
        self.assertEq(str(tz), "America/New_York") if False else None
        self.assertEqual((str(tz), warn), ("America/New_York", ""))
        self.assertIn("Settings", source)
        tz, source, warn = h.resolve_timezone("", "America/Los_Angeles")  # blank setting: detect from the Sheet
        self.assertEqual((str(tz), warn), ("America/Los_Angeles", ""))
        self.assertIn("Sheet", source)
        tz, _, warn = h.resolve_timezone("Mars/Base", "Europe/London")  # bad name: reported, falls through to the Sheet
        self.assertEqual(str(tz), "Europe/London")
        self.assertIn("Mars/Base", warn)
        self.assertEqual(str(h.resolve_timezone("", None)[0]), "America/Chicago")
        self.assertEqual(h.display_time("2026-10-14T21:13:28Z", h.resolve_timezone("America/Los_Angeles", None)[0]), "10/14/2026 02:13 PM")

    def test_tracker_rows_use_the_stores_zone_and_unreadable_sheet_zone_is_not_fatal(self) -> None:
        sh = FakeSpreadsheet([])
        store = sheet_store(sh)
        store.display_tz = h.ZoneInfo("America/New_York")
        row = h.JobRow("To Apply", 80, "Acme", "Intern", "Remote", "v", "", "https://u", "2026-10-14T21:13:28Z")
        self.assertEqual(row.cells(tz=store.display_tz)[1], "10/14/2026 05:13 PM")
        sh.timezone = "Asia/Tokyo"  # type: ignore[attr-defined]
        self.assertEqual(h.SheetStore.sheet_timezone(store), "Asia/Tokyo")
        del sh.timezone
        self.assertIsNone(h.SheetStore.sheet_timezone(store))  # FakeSpreadsheet has no attribute: handled

