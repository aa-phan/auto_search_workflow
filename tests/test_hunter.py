"""Offline tests for hunter.py: settings, search, hydration, evaluator, Groq client, stores, alerts.

All mocked (no network, no credentials). See tests/test_core.py for the polling/freshness core.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
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
import hunter as h  # noqa: E402
import ledger as lg  # noqa: E402
import pipeline as pl  # noqa: E402
import search  # noqa: E402


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
        pass


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

