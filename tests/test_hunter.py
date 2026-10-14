"""Offline tests: run with `python -m unittest discover -s tests` (no network, no credentials)."""

from __future__ import annotations

import csv
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hunter as h  # noqa: E402


def days_ago(n: int) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=n)).isoformat()


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


LEVER_ID = "{}-e89b-12d3-a456-426614174000"


def lever_url(n: int, suffix: str = "") -> str:
    return f"https://jobs.lever.co/acme/{LEVER_ID.format(str(n) * 8)}{suffix}"


# --------------------------------------------------------------------------- Layer 1


class QueryTests(unittest.TestCase):
    def test_default_settings_fit_google_limit_and_keep_locations(self) -> None:
        s = settings()
        queries = h.build_queries(s)
        self.assertEqual(len(queries), 2)
        for q in queries:
            self.assertLessEqual(h.count_words(q), h.GOOGLE_QUERY_WORD_LIMIT, q)
            for site in h.ATS_SITES:
                self.assertIn(f"site:{site}", q)
            self.assertIn('"San Antonio"', q)
            self.assertIn("Remote", q)
        joined = " ".join(queries)
        for role in s.roles:
            self.assertIn(role.split()[0], joined)

    def test_oversized_settings_never_crash_or_exceed_limit(self) -> None:
        s = settings(locations=[f"City{i} Name" for i in range(30)], roles=["Marketing"])
        for q in h.build_queries(s):
            self.assertLessEqual(h.count_words(q), h.GOOGLE_QUERY_WORD_LIMIT)

    def test_empty_roles_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            h.build_queries(settings(roles=[]))

    def search_bodies(self, **cfg_kw: object) -> list[dict]:
        cfg = h.replace(h.Config.from_env(), search_api_key="k", search_pages=1, **cfg_kw)
        resp = mock.Mock()
        resp.json.return_value = {"organic": []}
        with mock.patch.object(h.requests, "post", return_value=resp) as post:
            h.search_ats(cfg, ["q1", "q2"])
        self.assertEqual(post.call_count, 2)
        return [c.kwargs["json"] for c in post.call_args_list]

    def test_search_tbs_defaults_to_three_day_window(self) -> None:
        with mock.patch.dict(os.environ):
            os.environ.pop("SEARCH_TBS", None)
            self.assertEqual(h.Config.from_env().search_tbs, "qdr:d3")
            self.assertEqual(h.DEFAULT_SEARCH_TBS, "qdr:d3")
            for body in self.search_bodies(search_tbs=h.Config.from_env().search_tbs):
                self.assertEqual(body["tbs"], "qdr:d3")
                self.assertNotIn("num", body)  # free tier rejects num > 10

    def test_search_tbs_env_override_and_disable(self) -> None:
        with mock.patch.dict(os.environ, {"SEARCH_TBS": "qdr:w"}):
            self.assertEqual(h.Config.from_env().search_tbs, "qdr:w")
        with mock.patch.dict(os.environ, {"SEARCH_TBS": ""}):  # blank repository variable = default
            self.assertEqual(h.Config.from_env().search_tbs, "qdr:d3")
        for off in ("none", "off", ""):
            for body in self.search_bodies(search_tbs=off):
                self.assertNotIn("tbs", body)

    def test_no_tbs_cli_flag_disables_the_window(self) -> None:
        seen_cfgs: list[h.Config] = []

        def fake_search(cfg: h.Config, queries: list[str]) -> list[h.SearchHit]:
            seen_cfgs.append(cfg)
            return []

        with tempfile.TemporaryDirectory() as d, \
             mock.patch.dict(os.environ, {"GROQ_API_KEY": "x", "GOOGLE_SHEET_ID": ""}), \
             mock.patch.object(h, "make_store", return_value=h.CsvStore(Path(d) / "t.csv", Path(d) / "a.csv")), \
             mock.patch.object(h, "load_resume_file", return_value="r" * 300), \
             mock.patch.object(h, "search_ats", side_effect=fake_search):  # fmt: skip
            os.environ.pop("SEARCH_TBS", None)
            h.main([])
            h.main(["--no-tbs"])
        self.assertEqual([c.search_tbs for c in seen_cfgs], ["qdr:d3", ""])


class DedupeTests(unittest.TestCase):
    def test_tracking_params_case_and_suffixes_collapse_to_one_key(self) -> None:
        base = lever_url(1)
        variants = [base, base + "/apply", base + "/", base + "?utm_source=google&ref=abc", base.replace("acme", "ACME"),
                    base.replace("https://", "http://") + "#section"]  # fmt: skip
        self.assertEqual({h.dedupe_key(v) for v in variants}, {h.dedupe_key(base)})

    def test_seen_urls_are_dropped_before_classification_or_any_work(self) -> None:
        seen = {h.dedupe_key(lever_url(1))}
        hits = [h.SearchHit(lever_url(1, "?utm_source=x")), h.SearchHit(lever_url(1, "/apply")), h.SearchHit(lever_url(2))]
        with mock.patch.object(h, "classify_url", wraps=h.classify_url) as spy:
            refs = h.pending_refs(hits, seen, None)
        self.assertEqual([r.url for r in refs], [h.normalize_url(lever_url(2))])
        self.assertEqual(spy.call_count, 1)  # the two seen variants never reached classify_url

    def test_in_run_duplicates_and_title_filter(self) -> None:
        rx = h.excluded_title_regex(settings().excluded)
        hits = [h.SearchHit(lever_url(3), "Marketing Intern"), h.SearchHit(lever_url(3, "?x=1"), "Marketing Intern"),
                h.SearchHit(lever_url(4), "Senior Marketing Manager"), h.SearchHit("https://jobs.lever.co/acme", "listing")]  # fmt: skip
        refs = h.pending_refs(hits, set(), rx)
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].hint_title, "Marketing Intern")

    def test_classify_all_supported_ats(self) -> None:
        cases = {
            "https://boards.greenhouse.io/acme/jobs/123?gh_src=x": ("greenhouse", "acme", "123"),
            lever_url(1, "/apply"): ("lever", "acme", LEVER_ID.format("1" * 8)),
            "https://jobs.ashbyhq.com/Acme/123e4567-e89b-12d3-a456-426614174000/application": ("ashby", "Acme", "123e4567-e89b-12d3-a456-426614174000"),
            "https://apply.workable.com/flosum/j/B6448FD485/": ("workable", "flosum", "B6448FD485"),
            "https://jobs.smartrecruiters.com/Sosemo/744000076124321-digital-marketing-intern": ("smartrecruiters", "Sosemo", "744000076124321"),
        }  # fmt: skip
        for url, (ats, company, jid) in cases.items():
            ref = h.classify_url(url)
            assert ref is not None, url
            self.assertEqual((ref.ats, ref.company, ref.job_id), (ats, company, jid))
            self.assertNotIn("?", ref.url)
        for listing in ["https://jobs.lever.co/acme", "https://apply.workable.com/flosum", "https://boards.greenhouse.io/acme"]:
            self.assertIsNone(h.classify_url(listing))


class SettingsTests(unittest.TestCase):
    def test_excluded_words_are_whole_word_case_insensitive(self) -> None:
        rx = h.excluded_title_regex(settings().excluded)
        assert rx is not None
        for bad in ["Senior Marketing Associate", "Sr. Content Writer", "marketing MANAGER", "Lead Designer"]:
            self.assertTrue(rx.search(bad), bad)
        for ok in ["Marketing Associate", "Leadership Intern", "Content Specialist (Remote)"]:
            self.assertIsNone(rx.search(ok), ok)

    def test_blank_cells_fall_back_to_defaults(self) -> None:
        with mock.patch.dict(os.environ):
            for key in h.SETTING_DEFAULTS:
                os.environ.pop(key.upper(), None)
            s = h.Settings.from_values({"Target_Roles": "  ", "Min_Alert_Score": "abc", "Max_Job_Age_Days": "30"})
        self.assertIn("Marketing", s.roles)
        self.assertEqual((s.min_score, s.max_age_days), (70, 30))


# --------------------------------------------------------------------------- Layer 2


def fake_get(payload: dict) -> mock.Mock:
    resp = mock.Mock()
    resp.json.return_value = payload
    return resp


class DateExtractionTests(unittest.TestCase):
    def test_greenhouse_prefers_first_published_over_updated_at(self) -> None:
        ref = h.classify_url("https://boards.greenhouse.io/acme/jobs/1")
        both = {"title": "t", "content": "", "first_published": "2026-09-16T12:07:31-04:00", "updated_at": "2026-10-10T09:00:00-04:00"}
        with mock.patch.object(h, "_http_get", return_value=fake_get(both)):
            p = h._hydrate_greenhouse(ref)
        self.assertEqual((p.posted, p.posted_source), ("2026-09-16", "first_published"))
        only_updated = {"title": "t", "content": "", "updated_at": "2026-10-10T09:00:00-04:00"}
        with mock.patch.object(h, "_http_get", return_value=fake_get(only_updated)):
            p = h._hydrate_greenhouse(ref)
        self.assertEqual((p.posted, p.posted_source), ("2026-10-10", "updated_at"))
        with mock.patch.object(h, "_http_get", return_value=fake_get({"title": "t", "content": ""})):
            self.assertEqual(h._hydrate_greenhouse(ref).posted, "")  # no dates at all: graceful

    def test_lever_created_at_epoch_milliseconds(self) -> None:
        ref = h.classify_url(lever_url(1))
        with mock.patch.object(h, "_http_get", return_value=fake_get({"text": "t", "createdAt": 1791564186023})):
            p = h._hydrate_lever(ref)
        self.assertEqual((p.posted, p.posted_source), ("2026-10-09", "createdAt"))

    def test_ashby_falls_back_to_json_ld_date_posted_only_when_api_has_no_date(self) -> None:
        ref = h.classify_url("https://jobs.ashbyhq.com/Acme/123e4567-e89b-12d3-a456-426614174000")
        with mock.patch.object(h, "_hydrate_ashby_api", return_value=posting(ats="ashby", posted="")), \
             mock.patch.object(h, "_page_date_posted", return_value="2026-08-20") as page:  # fmt: skip
            p = h._hydrate(ref)
        self.assertEqual((p.posted, p.posted_source), ("2026-08-20", "datePosted"))
        page.assert_called_once()
        with mock.patch.object(h, "_hydrate_ashby_api", return_value=posting(ats="ashby", posted="2026-09-01")), \
             mock.patch.object(h, "_page_date_posted") as page:  # fmt: skip
            self.assertEqual(h._hydrate(ref).posted, "2026-09-01")
        page.assert_not_called()  # no extra request when the API already had the date

    def test_page_json_ld_date_posted_parsing(self) -> None:
        page = '<script type="application/ld+json">{"@type": "JobPosting", "datePosted": "2026-08-20"}</script>'
        resp = mock.Mock()
        resp.text = page
        with mock.patch.object(h, "_http_get", return_value=resp):
            self.assertEqual(h._page_date_posted(h.classify_url("https://jobs.ashbyhq.com/A/123e4567-e89b-12d3-a456-426614174000")), "2026-08-20")

    def test_search_result_date_is_last_resort(self) -> None:
        ref = h.replace(h.classify_url(lever_url(1)), hint_date="3 days ago")  # type: ignore[arg-type]
        with mock.patch.object(h, "_hydrate", return_value=posting(posted="")):
            p = h.hydrate_posting(ref)
        self.assertEqual((p.posted, p.posted_source), (days_ago(3), "search_result"))
        with mock.patch.object(h, "_hydrate", return_value=posting(posted="2026-01-01", posted_source="createdAt")):
            self.assertEqual(h.hydrate_posting(ref).posted, "2026-01-01")  # the ATS date always wins

    def test_dates_parse(self) -> None:
        self.assertEqual(str(h.parse_posted(1791564186023)), "2026-10-09")
        self.assertEqual(str(h.parse_posted("2026-09-16T12:07:31-04:00")), "2026-09-16")
        self.assertIsNone(h.parse_posted("garbage"))


class HydrationErrorTests(unittest.TestCase):
    ref = h.classify_url(lever_url(1))

    def raises(self, exc: BaseException) -> type[BaseException]:
        with mock.patch.object(h, "_hydrate", side_effect=exc):
            try:
                h.hydrate_posting(self.ref)  # type: ignore[arg-type]
            except BaseException as caught:  # noqa: BLE001
                return type(caught)
        raise AssertionError("did not raise")

    def http(self, code: int) -> requests.HTTPError:
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
            h.hydrate_posting(self.ref)  # type: ignore[arg-type]


class ProcessTests(unittest.TestCase):
    ref = h.AtsRef("lever", "https://jobs.lever.co/acme/x", "acme", "x", hint_title="Marketing Intern")

    def run_process(self, *, hydrate: object, groq: object = None, s: h.Settings | None = None) -> h.JobRow | None:
        s = s or settings()
        kw = {"side_effect": hydrate} if isinstance(hydrate, BaseException) else {"return_value": hydrate}
        with mock.patch.object(h, "hydrate_posting", **kw):  # type: ignore[arg-type]
            return h.process(s, groq or mock.Mock(), self.ref, h.excluded_title_regex(s.excluded))

    def test_closed_is_recorded_with_score_zero_and_skips_groq(self) -> None:
        groq = mock.Mock()
        row = self.run_process(hydrate=h.ClosedPosting("404"), groq=groq)
        assert row is not None
        self.assertEqual((row.status, row.score), (h.STATUS_CLOSED, 0))
        groq.evaluate.assert_not_called()

    def test_transient_hydration_is_not_recorded(self) -> None:
        self.assertIsNone(self.run_process(hydrate=h.TransientError("timeout")))

    def test_permanent_hydration_error_is_recorded(self) -> None:
        row = self.run_process(hydrate=ValueError("description too short"))
        assert row is not None
        self.assertEqual(row.status, h.STATUS_ERROR)

    def test_stale_boundary_is_strictly_older_than_max_age(self) -> None:
        for age, stale in [(13, False), (14, False), (15, True), (200, True)]:
            groq = mock.Mock()
            groq.evaluate.return_value = h.Evaluation(90, "v", "None")
            row = self.run_process(hydrate=posting(posted=days_ago(age)), groq=groq)
            assert row is not None
            self.assertEqual(row.status.startswith("Stale"), stale, age)
            if stale:
                self.assertEqual((row.status, row.score), ("Stale (>14d old)", 0))
                groq.evaluate.assert_not_called()  # no tokens spent on stale jobs
            else:
                groq.evaluate.assert_called_once()

    def test_updated_at_fallback_is_used_and_labelled(self) -> None:
        row = self.run_process(hydrate=posting(posted=days_ago(40), posted_source="updated_at"))
        assert row is not None
        self.assertTrue(row.status.startswith("Stale"))
        self.assertIn("Last updated", row.verdict)

    def test_unknown_date_is_not_blocked(self) -> None:
        groq = mock.Mock()
        groq.evaluate.return_value = h.Evaluation(75, "v", "None")
        row = self.run_process(hydrate=posting(posted=""), groq=groq)
        assert row is not None
        self.assertEqual(row.status, h.STATUS_APPLY)

    def test_excluded_full_title_skips_groq(self) -> None:
        groq = mock.Mock()
        row = self.run_process(hydrate=posting(title="Senior Marketing Associate"), groq=groq)
        assert row is not None
        self.assertEqual((row.status, row.score), (h.STATUS_FILTERED, 0))
        groq.evaluate.assert_not_called()

    def test_status_by_threshold(self) -> None:
        for score, status in [(70, h.STATUS_APPLY), (69, h.STATUS_STRETCH), (50, h.STATUS_STRETCH), (49, h.STATUS_FILTERED)]:
            groq = mock.Mock()
            groq.evaluate.return_value = h.Evaluation(score, "v", "g")
            row = self.run_process(hydrate=posting(), groq=groq)
            assert row is not None
            self.assertEqual(row.status, status, score)

    def test_groq_transient_not_recorded_but_bad_json_recorded(self) -> None:
        groq = mock.Mock()
        groq.evaluate.side_effect = h.TransientError("429")
        self.assertIsNone(self.run_process(hydrate=posting(), groq=groq))
        groq.evaluate.side_effect = ValueError("no json")
        row = self.run_process(hydrate=posting(), groq=groq)
        assert row is not None
        self.assertEqual(row.status, h.STATUS_ERROR)


class EndToEndTwoLayerTests(unittest.TestCase):
    """Two scheduled runs over the same search results."""

    def test_two_runs(self) -> None:
        fresh, stale, closed, flaky = (lever_url(i) for i in (1, 2, 3, 4))
        hits = [h.SearchHit(fresh + "?utm_source=google", "Marketing Intern"), h.SearchHit(stale, "Marketing Intern"),
                h.SearchHit(closed, "Marketing Intern"), h.SearchHit(flaky, "Marketing Intern"),
                h.SearchHit(fresh + "/apply", "Marketing Intern")]  # fmt: skip
        calls: list[str] = []
        flaky_ok = {"value": False}

        def fake_hydrate(ref: h.AtsRef) -> h.Posting:
            calls.append(ref.url)
            if ref.url == h.normalize_url(closed):
                raise h.ClosedPosting("404")
            if ref.url == h.normalize_url(flaky) and not flaky_ok["value"]:
                raise h.TransientError("timeout")
            posted = days_ago(30) if ref.url == h.normalize_url(stale) else days_ago(3)
            return posting(url=ref.url, posted=posted, title="Marketing Intern", company="Acme")

        with tempfile.TemporaryDirectory() as d:
            store = h.CsvStore(Path(d) / "t.csv", Path(d) / "a.csv")
            patches = [
                mock.patch.dict(os.environ, {"GROQ_API_KEY": "x", "GOOGLE_SHEET_ID": ""}),
                mock.patch.object(h, "make_store", return_value=store),
                mock.patch.object(h, "load_resume_file", return_value="r" * 300),
                mock.patch.object(h, "search_ats", return_value=hits),
                mock.patch.object(h, "hydrate_posting", side_effect=fake_hydrate),
                mock.patch.object(h.GroqClient, "evaluate", lambda self, s, p: h.Evaluation(88, "Great fit.", "None")),
            ]
            for p in patches:
                p.start()
            self.addCleanup(lambda: [p.stop() for p in patches])

            # ---- run 1
            self.assertEqual(h.main([]), 0)
            self.assertEqual(sorted(set(calls)), sorted(h.normalize_url(u) for u in (fresh, stale, closed, flaky)))
            self.assertEqual(calls.count(h.normalize_url(fresh)), 1)  # the /apply + utm variants collapsed
            tracker = list(csv.DictReader((Path(d) / "t.csv").open()))
            archive = list(csv.DictReader((Path(d) / "a.csv").open()))
            self.assertEqual([r["My_Status"] for r in tracker], ["To Apply"])
            self.assertEqual({r["URL"] for r in archive}, {h.normalize_url(stale), h.normalize_url(closed)})
            reasons = {r["URL"]: r["Reason"] for r in archive}
            self.assertTrue(reasons[h.normalize_url(stale)].startswith("Stale (>14d old)"))
            self.assertEqual(reasons[h.normalize_url(closed)], "Closed (404)")
            seen = store.seen_urls()
            self.assertIn(h.dedupe_key(fresh), seen)
            self.assertIn(h.dedupe_key(stale), seen)
            self.assertIn(h.dedupe_key(closed), seen)
            self.assertNotIn(h.dedupe_key(flaky), seen)  # transient failure: will be retried

            # ---- run 2: only the flaky URL is touched again
            calls.clear()
            flaky_ok["value"] = True
            self.assertEqual(h.main([]), 0)
            self.assertEqual(calls, [h.normalize_url(flaky)])
            tracker = list(csv.DictReader((Path(d) / "t.csv").open()))
            self.assertEqual(len(tracker), 2)
            self.assertIn(h.dedupe_key(flaky), store.seen_urls())

            # ---- run 3: nothing left to do
            calls.clear()
            self.assertEqual(h.main([]), 0)
            self.assertEqual(calls, [])


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
        cfg = h.replace(h.Config.from_env(), groq_api_key="k", llm_interval=0.0)
        c = h.GroqClient(cfg)
        c.http = mock.Mock()
        c.http.post.side_effect = responses
        return c, c.http.post

    def test_429_on_primary_falls_back_to_8b(self) -> None:
        c, post = self.client([FakeResponse(429), groq_ok(77)])
        with mock.patch.object(h.time, "sleep"):
            ev = c.evaluate(settings(), posting())
        self.assertEqual(ev.score, 77)
        models = [call.kwargs["json"]["model"] for call in post.call_args_list]
        self.assertEqual(models, ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"])
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

    def get_all_values(self) -> list[list[str]]:
        return self.values

    def col_values(self, col: int) -> list[str]:
        return [r[col - 1] if len(r) >= col else "" for r in self.values]

    def append_rows(self, rows: list, **kw: object) -> None:
        self.appended.append((rows, kw))
        self.values.extend(rows)

    def hide(self) -> None:
        self.hidden = True

    def __getattr__(self, name: str):  # freeze / format etc. are cosmetic no-ops
        if name in {"update", "clear", "delete_rows", "update_cell", "batch_clear"}:
            raise AssertionError(f"tracker must be append-only, but {name}() was called")
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
    return store


def job(status: str = h.STATUS_APPLY, score: int | None = 88, url: str = "https://u", **kw: str) -> h.JobRow:
    return h.JobRow(status, score, kw.get("company", "Acme"), kw.get("title", "Marketing Intern"), "Remote", "good", "None", url, "2026-10-12")


class SheetTests(unittest.TestCase):
    def test_bootstrap_creates_three_tabs_with_defaults_and_hides_archive(self) -> None:
        sh = FakeSpreadsheet([FakeWorksheet("Sheet1", [])])
        sheet_store(sh).bootstrap("MY RESUME")
        self.assertEqual(set(sh.tabs), {"Settings", "Job Tracker", "Seen_Archive"})
        self.assertEqual(sh.deleted, ["Sheet1"])
        by_key = {r[0]: r[1] for r in sh.tabs["Settings"].values[1:]}
        self.assertEqual((by_key["Resume_Text"], by_key["Min_Alert_Score"], by_key["Max_Job_Age_Days"]), ("MY RESUME", "70", "14"))
        self.assertEqual(sh.tabs["Job Tracker"].values[0], h.TRACKER_COLUMNS)
        self.assertEqual(sh.tabs["Seen_Archive"].values[0], ["Date_Found", "Reason", "URL"])
        self.assertTrue(sh.tabs["Seen_Archive"].hidden)
        self.assertFalse(sh.tabs["Job Tracker"].hidden)
        with mock.patch.dict(os.environ):
            for key in h.SETTING_DEFAULTS:
                os.environ.pop(key.upper(), None)
            self.assertIn("Web Designer", h.Settings.from_values(sheet_store(sh).load_settings()).roles)

    def test_bootstrap_never_touches_existing_tabs_but_adds_missing_archive(self) -> None:
        settings_ws = FakeWorksheet("Settings", [["Setting", "Value", "Instructions"], ["Min_Alert_Score", "55", ""]])
        tracker_ws = FakeWorksheet("Job Tracker", [h.TRACKER_COLUMNS, ["d"] * 10])
        sh = FakeSpreadsheet([settings_ws, tracker_ws])
        sheet_store(sh).bootstrap("RESUME")
        self.assertEqual((settings_ws.appended, tracker_ws.appended), ([], []))
        self.assertIn("Seen_Archive", sh.tabs)

    def test_dedupe_reads_tracker_column_i_and_archive_url_column(self) -> None:
        url = lever_url(1)
        tracked = ["2026-10-01", "2026-09-30", "Applied", 90, "Acme — X", "NYC", "v", "", url + "?utm_source=g", "my note"]
        tracker = FakeWorksheet("Job Tracker", [h.TRACKER_COLUMNS, tracked])
        archive = FakeWorksheet("Seen_Archive", [h.ARCHIVE_COLUMNS, ["2026-10-02", "Closed (404)", lever_url(2).upper().replace("HTTPS", "https")]])
        store = sheet_store(FakeSpreadsheet([FakeWorksheet("Settings"), tracker, archive]))
        self.assertEqual(h.URL_COLUMN, 9)
        self.assertEqual(store.seen_urls(), {h.dedupe_key(url), h.dedupe_key(lever_url(2))})

    def test_appends_are_append_only_and_split_by_visibility(self) -> None:
        tracker = FakeWorksheet("Job Tracker", [h.TRACKER_COLUMNS, ["2026-10-01", "", "Applied", 90, "Edited by me", "", "", "", "https://old", "my note"]])
        archive = FakeWorksheet("Seen_Archive", [h.ARCHIVE_COLUMNS])
        store = sheet_store(FakeSpreadsheet([tracker, archive]))
        before = list(tracker.values[1])
        store.append_jobs([job(company="=HYPERLINK(x)")])
        store.append_archive([job(h.STATUS_CLOSED, 0), job("Stale (>14d old)", 0, "https://s")])
        rows, kw = tracker.appended[0]
        self.assertEqual(kw["value_input_option"], "USER_ENTERED")
        self.assertEqual(len(rows[0]), 10)
        self.assertEqual(rows[0][2:4], ["To Apply", 88])
        self.assertTrue(rows[0][4].startswith("'="))  # formula neutralized
        self.assertEqual(rows[0][9], "")  # User_Notes untouched
        self.assertEqual(tracker.values[1], before)  # the user's edited row is intact
        arows, akw = archive.appended[0]
        self.assertEqual([r[1][:12] for r in arows], ["Closed (404)", "Stale (>14d "])
        self.assertEqual(akw["value_input_option"], "RAW")

    def test_visibility_rule(self) -> None:
        self.assertTrue(h.is_visible(job(score=50), 70))
        self.assertFalse(h.is_visible(job(score=49), 70))
        self.assertFalse(h.is_visible(job(h.STATUS_ERROR, None), 70))
        self.assertTrue(h.is_visible(job(score=40), 40))  # a low Min_Alert_Score still shows its matches


class CsvTests(unittest.TestCase):
    def test_migrates_legacy_header_moving_low_scorers_to_archive(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path, arch = Path(d) / "t.csv", Path(d) / "a.csv"
            path.write_text(
                "Date_Found_UTC,Score,Status,Company_or_Title,Verdict,Missing_Gaps,URL,Date_Posted\n"
                "2026-10-01,80,To Apply,Acme,good,,https://u,2026-09-30\n"
                "2026-10-01,10,Filtered Out,Beta,bad,,https://v,\n"
            )
            store = h.CsvStore(path, arch)
            store.bootstrap("")
            kept = list(csv.DictReader(path.open()))
            self.assertEqual([r["Apply_URL"] for r in kept], ["https://u"])
            self.assertEqual([r["URL"] for r in csv.DictReader(arch.open())], ["https://v"])
            self.assertEqual(store.seen_urls(), {"https://u", "https://v"})
            store.append_jobs([job(url="https://w")])
            store.append_archive([job(h.STATUS_FILTERED, 5, "https://x")])
            self.assertEqual(len(store.seen_urls()), 4)


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
    def test_telegram_message_has_all_fields_and_sheet_link(self) -> None:
        cfg = h.replace(h.Config.from_env(), telegram_token="t", telegram_chat_id="1", webhook_url="")
        resp = mock.Mock()
        with mock.patch.object(h.requests, "post", return_value=resp) as post:
            self.assertTrue(h.send_alert(cfg, job(company="A&B", title="<Intern>"), "https://docs.google.com/spreadsheets/d/FAKE"))
        text = post.call_args.kwargs["json"]["text"]
        for needle in ["&lt;Intern&gt;", "A&amp;B", "88/100", "good", "Gaps: None", "Remote", 'href="https://u"', "spreadsheets/d/FAKE"]:
            self.assertIn(needle, text)

    def test_no_channels_means_no_alert(self) -> None:
        cfg = h.replace(h.Config.from_env(), telegram_token="", telegram_chat_id="", webhook_url="")
        self.assertFalse(h.send_alert(cfg, job()))


if __name__ == "__main__":
    unittest.main()
