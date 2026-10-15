"""Offline tests for the Tavily migration: request mapping, response normalisation, credit accounting,
the shared monthly ledger, exhaustion, and the migration of the persisted rotation state.

Nothing here calls Tavily (live results are in STATUS.md); the HTTP layer is a fake.
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import boards as bd  # noqa: E402
import discovery as dsc  # noqa: E402
import pipeline as pl  # noqa: E402
import search  # noqa: E402
from test_core import T0, HarnessCase, ago, job  # noqa: E402

TODAY = date(2026, 10, 14)


def resp(status: int = 200, body: Any = None, headers: dict | None = None) -> mock.Mock:
    r = mock.Mock(status_code=status, headers=headers or {})
    r.json.return_value = body if body is not None else {}
    return r


# --------------------------------------------------------------------------- request mapping


class RequestMappingTests(unittest.TestCase):
    def test_domain_restriction_and_three_day_window_use_tavily_parameters_not_google_syntax(self) -> None:
        body = search.request_body("Marketing job", "jobs.lever.co", window_days=3, today=TODAY)
        self.assertEqual(body["include_domains"], ["jobs.lever.co"])
        self.assertEqual(body["start_date"], "2026-10-11")  # today - 3 days
        self.assertNotIn("end_date", body)
        self.assertNotIn("site:", body["query"])
        for google_only in ("tbs", "num", "page", "gl", "hl"):
            self.assertNotIn(google_only, body)

    def test_cheapest_suitable_mode_and_nothing_extra_is_requested(self) -> None:
        body = search.request_body("x", "jobs.lever.co", window_days=3, today=TODAY)
        self.assertEqual(body["search_depth"], "basic")
        self.assertEqual(search.REQUEST_CREDITS["basic"], 1)
        self.assertFalse(any(body[k] for k in ("include_answer", "include_raw_content", "include_images", "include_favicon")))
        self.assertTrue(body["include_usage"])  # the real credit cost comes back with every response
        self.assertEqual(body["max_results"], 20)
        self.assertNotIn("auto_parameters", body)  # it would cost 2 credits

    def test_no_window_means_no_start_date_and_only_the_manual_backfill_asks_for_it(self) -> None:
        self.assertNotIn("start_date", search.request_body("x", "jobs.lever.co", window_days=None, today=TODAY))


# --------------------------------------------------------------------------- normalisation and cost


class NormalisationTests(unittest.TestCase):
    def test_results_become_internal_hits_and_a_published_date_is_kept_but_never_trusted(self) -> None:
        page = search.parse_page({
            "results": [
                {"url": "https://boards.greenhouse.io/acme/jobs/1", "title": "Marketing Intern", "content": "...", "score": 0.9, "published_date": None},
                {"url": "https://jobs.lever.co/acme", "title": "", "published_date": "2026-10-13"},
                {"title": "no url"},
                "junk",
            ],
            "usage": {"credits": 1},
        })  # fmt: skip
        self.assertEqual([(h.url, h.title, h.date) for h in page], [("https://boards.greenhouse.io/acme/jobs/1", "Marketing Intern", ""), ("https://jobs.lever.co/acme", "", "2026-10-13")])
        self.assertEqual(page.credits, 1)

    def test_credits_come_from_the_response_else_from_the_documented_price(self) -> None:
        self.assertEqual(search.parse_page({"results": [], "usage": {"credits": 2}}).credits, 2)
        self.assertEqual(search.parse_page({"results": []}).credits, 1)  # basic
        self.assertEqual(search.parse_page({"results": []}, "advanced").credits, 2)
        self.assertEqual(search.parse_page({"results": [], "usage": {"credits": "x"}}, "advanced").credits, 2)
        self.assertEqual(search.parse_page("not a dict").credits, 1)
        self.assertEqual(list(search.parse_page({"results": None})), [])


# --------------------------------------------------------------------------- errors


class ErrorTests(unittest.TestCase):
    def go(self, *responses: Any, sleep: Any = None) -> search.Page:
        post = mock.Mock(side_effect=list(responses))
        return search.search("k", "q", "jobs.lever.co", window_days=3, today=TODAY, post=post, sleep=sleep or (lambda s: None))

    def test_success(self) -> None:
        self.assertEqual(len(self.go(resp(body={"results": [{"url": "https://jobs.lever.co/a"}], "usage": {"credits": 1}}))), 1)

    def test_bad_key_and_exhausted_plan_are_fatal_for_the_run(self) -> None:
        with self.assertRaises(search.SearchAuthError) as c:
            self.go(resp(401))
        self.assertTrue(c.exception.fatal)
        for code in (432, 433):
            with self.assertRaises(search.SearchLimitReached) as c:
                self.go(resp(code))
            self.assertTrue(c.exception.fatal)
        with self.assertRaises(search.SearchAuthError):
            search.search("", "q", "d", window_days=3)  # no key: nothing is sent

    def test_rate_limit_is_retried_once_after_retry_after(self) -> None:
        slept: list[float] = []
        page = self.go(resp(429, headers={"Retry-After": "7"}), resp(body={"results": []}), sleep=slept.append)
        self.assertEqual((slept, len(page)), ([7.0], 0))
        with self.assertRaises(search.SearchError):
            self.go(resp(429), resp(429), sleep=slept.append)
        self.assertEqual(self.go(resp(429, headers={"Retry-After": "900"}), resp(body={"results": []}), sleep=slept.append).credits, 1)
        self.assertEqual(slept[-1], 30.0)  # capped

    def test_other_failures_are_isolated_not_fatal(self) -> None:
        for code in (400, 422, 500):
            with self.assertRaises(search.SearchError) as c:
                self.go(resp(code))
            self.assertFalse(c.exception.fatal)
        import requests

        with self.assertRaises(search.SearchError) as c:
            self.go(requests.ConnectionError("down"))
        self.assertFalse(c.exception.fatal)
        bad = resp()
        bad.json.side_effect = ValueError("no json")
        with self.assertRaises(search.SearchError):
            self.go(bad)


class UsageEndpointTests(unittest.TestCase):
    def test_account_usage_is_read_without_cost_and_failures_return_none(self) -> None:
        data = {"key": {"usage": 12}, "account": {"current_plan": "Researcher", "plan_usage": 40, "plan_limit": 1000}}
        self.assertEqual(
            search.account_usage("k", get=lambda *a, **k: resp(body=data)), {"plan": "Researcher", "used": 40, "limit": 1000, "key_used": 12}
        )
        self.assertIsNone(search.account_usage("k", get=lambda *a, **k: resp(429)))
        self.assertIsNone(search.account_usage("k", get=lambda *a, **k: resp(body={"account": {}})))
        self.assertEqual(search.account_usage("k", get=lambda *a, **k: resp(body={"account": {"plan_usage": 1, "plan_limit": None}}))["limit"], None)


# --------------------------------------------------------------------------- the monthly ledger


NOW = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)


class BudgetTests(unittest.TestCase):
    def test_default_cap_is_1000_with_headroom_for_manual_runs(self) -> None:
        b = search.SearchBudget.load(None, NOW)
        self.assertEqual((b.cap, b.reserve, b.remaining(scheduled=True), b.remaining(scheduled=False)), (1000, 200, 800, 1000))

    def test_every_path_charges_one_ledger_and_scheduled_runs_stop_before_the_reserve(self) -> None:
        b = search.SearchBudget.load(None, NOW)
        b.charge(700, "rotation")
        b.charge(50, "manual")
        b.charge(40, "backfill")
        self.assertEqual((b.used, b.calls, b.by_path), (790, 3, {"rotation": 700, "manual": 50, "backfill": 40}))
        self.assertEqual((b.remaining(scheduled=True), b.remaining(scheduled=False)), (10, 210))
        b.charge(10, "rotation")
        self.assertEqual(b.remaining(scheduled=True), 0)
        self.assertGreater(b.remaining(scheduled=False), 0)  # the reserve is still there for a manual test
        b.charge(200, "backfill")
        self.assertEqual(b.remaining(scheduled=False), 0)

    def test_round_trip_and_unreadable_state(self) -> None:
        b = search.SearchBudget.load(None, NOW)
        b.charge(7, "rotation")
        again = search.SearchBudget.load(b.to_json(), NOW)
        self.assertEqual((again.used, again.calls, again.by_path, again.rolled_from), (7, 1, {"rotation": 7}, ""))
        for junk in ("", "nope", "[]", '{"month": 5}'):
            self.assertEqual(search.SearchBudget.load(junk, NOW).used, 0)

    def test_the_ledger_restarts_when_the_utc_month_changes(self) -> None:
        b = search.SearchBudget.load(None, NOW)
        b.charge(900, "rotation")
        b.limit_hit = True
        nxt = search.SearchBudget.load(b.to_json(), datetime(2026, 11, 1, 0, 0, 1, tzinfo=timezone.utc))
        self.assertEqual((nxt.month, nxt.used, nxt.limit_hit, nxt.rolled_from), ("2026-11", 0, False, "2026-10"))
        same = search.SearchBudget.load(b.to_json(), datetime(2026, 10, 31, 23, 59, tzinfo=timezone.utc))
        self.assertEqual((same.used, same.limit_hit), (900, True))

    def test_the_providers_own_counter_wins_when_it_is_higher_and_its_limit_lowers_the_cap(self) -> None:
        b = search.SearchBudget.load(None, NOW)
        b.charge(100, "rotation")
        b.observe_account({"plan": "Researcher", "used": 450, "limit": 1000, "key_used": 100})  # 350 credits used elsewhere
        self.assertEqual((b.effective_used, b.remaining(scheduled=True)), (450, 350))
        b.observe_account({"plan": "Researcher", "used": 20, "limit": 500, "key_used": 20})  # a smaller plan limit
        self.assertEqual((b.effective_cap, b.effective_used, b.remaining(scheduled=False)), (500, 100, 400))
        b.observe_account(None)  # unreadable: the previous observation stands, the local counter still applies
        self.assertEqual(b.effective_cap, 500)

    def test_a_provider_limit_hit_blocks_everything_until_the_month_or_the_account_says_otherwise(self) -> None:
        b = search.SearchBudget.load(None, NOW)
        b.limit_hit = True
        self.assertEqual((b.remaining(scheduled=True), b.remaining(scheduled=False)), (0, 0))
        b.observe_account({"plan": "p", "used": 1000, "limit": 1000, "key_used": 0})
        self.assertTrue(b.limit_hit)  # still at the limit
        b.observe_account({"plan": "p", "used": 10, "limit": 1000, "key_used": 0})  # a new billing cycle
        self.assertFalse(b.limit_hit)

    def test_summary_names_the_counters_it_cannot_see(self) -> None:
        text = search.SearchBudget.load(None, NOW).summary()
        self.assertIn("used locally", text)
        self.assertIn("reserved for manual runs", text)


# --------------------------------------------------------------------------- pipeline behaviour


class PipelineBudgetTests(HarnessCase):
    def run_with(self, found: dsc.DiscoveryResult | None = None, **kw: Any):
        calls: list[pl.DiscoveryContext] = []

        def discover(ctx: pl.DiscoveryContext) -> dsc.DiscoveryResult:
            calls.append(ctx)
            ctx.budget.charge(3, "rotation")
            return found or dsc.DiscoveryResult(slots_used=3)

        run = self.w.run(discover=discover, **kw)
        return run, calls

    def stored_budget(self) -> search.SearchBudget:
        return search.SearchBudget.load(self.w.state.load_discovery_state().get(search.BUDGET_KEY), self.w.now)

    def test_credits_are_persisted_and_shared_by_the_next_run(self) -> None:
        self.run_with(force_discovery=True)
        self.assertEqual(self.stored_budget().used, 3)
        self.run_with(minutes_later=60, force_discovery=True)
        self.assertEqual((self.stored_budget().used, self.stored_budget().calls), (6, 2))

    def test_credits_are_recorded_even_when_discovery_fails_or_it_is_a_dry_run(self) -> None:
        def boom(ctx: pl.DiscoveryContext) -> dsc.DiscoveryResult:
            ctx.budget.charge(2, "rotation")
            raise RuntimeError("after spending")

        run = self.w.run(discover=boom, force_discovery=True)
        self.assertIn("discovery failed", run.notes)
        self.assertEqual(self.stored_budget().used, 2)
        self.w.run(minutes_later=60, discover=lambda ctx: (ctx.budget.charge(1, "manual"), dsc.DiscoveryResult())[1], force_discovery=True, dry_run=True)
        self.assertEqual(self.stored_budget().used, 3)  # a dry run that searched still spent a credit

    def test_exhausted_budget_skips_discovery_but_hourly_polling_continues(self) -> None:
        self.baseline(job("acme", "1", published=ago(days=30)))
        self.w.state.save_discovery_state({search.BUDGET_KEY: json.dumps({"month": "2026-10", "used": 800, "calls": 90, "by_path": {}, "limit_hit": False})}, "t")
        self.w.listings[self.board.key].append(job("acme", "2", published=ago(minutes=5, base=self.w.now + timedelta(minutes=60))))
        run, calls = self.run_with(minutes_later=60, discovery_every_hours=1)  # scheduled: the 800 ceiling is reached
        self.assertEqual(calls, [])
        self.assertFalse(run.discovery)  # not marked as a discovery run: the next hourly run asks again
        self.assertIn("budget exhausted", run.notes)
        self.assertEqual((run.boards_ok, len(self.w.alerts)), (1, 1))  # the poll still happened and alerted
        run2, calls2 = self.run_with(minutes_later=60, force_discovery=True)  # a manual run may use the reserve
        self.assertEqual(len(calls2), 1)
        self.assertFalse(calls2[0].scheduled)

    def test_the_next_month_resumes_scheduled_discovery_by_itself(self) -> None:
        self.w.state.save_discovery_state({search.BUDGET_KEY: json.dumps({"month": "2026-10", "used": 1000, "calls": 1, "by_path": {}, "limit_hit": True})}, "t")
        _, calls = self.run_with(discovery_every_hours=1)
        self.assertEqual(calls, [])
        self.w.now = datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc)
        run, calls = self.run_with(discovery_every_hours=1)
        self.assertEqual(len(calls), 1)
        self.assertTrue(run.discovery)
        self.assertEqual(self.stored_budget().month, "2026-11")

    def test_the_providers_counter_is_read_before_deciding(self) -> None:
        seen: list[int] = []
        _, calls = self.run_with(force_discovery=True, search_sync=lambda b: (b.observe_account({"plan": "p", "used": 990, "limit": 1000, "key_used": 0}), seen.append(1)))
        self.assertEqual(seen, [1])
        self.assertEqual(len(calls), 1)  # manual: 10 credits remain
        _, calls = self.run_with(minutes_later=60, search_sync=lambda b: b.observe_account({"plan": "p", "used": 990, "limit": 1000, "key_used": 0}), discovery_every_hours=1)
        self.assertEqual(calls, [])  # scheduled: past its ceiling

    def test_a_failing_usage_endpoint_never_stops_discovery(self) -> None:
        def broken(b: search.SearchBudget) -> None:
            raise RuntimeError("usage endpoint down")

        _, calls = self.run_with(force_discovery=True, search_sync=broken)
        self.assertEqual(len(calls), 1)

    def test_a_fatal_provider_stop_is_reported_and_polling_continues(self) -> None:
        run, _ = self.run_with(found=dsc.DiscoveryResult(fatal="SearchLimitReached: HTTP 432", stopped="provider"), force_discovery=True)
        self.assertIn("search stopped: SearchLimitReached", run.notes)


class RotationMigrationTests(HarnessCase):
    slots = dsc.make_slots(["boards.greenhouse.io", "jobs.lever.co"], ["Marketing", "Design"], [])

    def test_a_cursor_saved_for_the_previous_provider_is_discarded_and_said_so(self) -> None:
        legacy = json.dumps({"cursor": 30, "fingerprint": dsc.fingerprint(self.slots), "total": 4, "cycles": 2, "runs": 9, "last_run_at": "2026-10-14T00:00:00Z"})
        self.assertEqual(dsc.RotationState.from_json(legacy).cursor, 0)
        self.assertEqual(dsc.RotationState.from_json(legacy).migrated_from, "serper")
        self.w.state.save_discovery_state({dsc.ROTATION_KEY: legacy}, "t")
        searched: list[str] = []

        def discover(ctx: pl.DiscoveryContext) -> dsc.DiscoveryResult:
            chosen = dsc.plan_slots(ctx.rotation, self.slots, 2)
            searched.extend(s.id for s in chosen)
            return dsc.DiscoveryResult(slots_used=len(chosen))

        run = self.w.run(discover=discover, rotation_slots=self.slots, force_discovery=True)
        self.assertEqual(searched, [self.slots[0].id, self.slots[1].id])  # restarted at slot 0, not at the old cursor
        self.assertIn("rotation reset", run.notes)
        stored = json.loads(self.w.state.load_discovery_state()[dsc.ROTATION_KEY])
        self.assertEqual((stored["provider"], stored["cursor"]), ("tavily", 2))
        again = self.w.run(minutes_later=60, discover=discover, rotation_slots=self.slots, force_discovery=True)
        self.assertNotIn("rotation reset", again.notes)  # reset once

    def test_a_tavily_cursor_survives_and_registry_and_history_are_untouched(self) -> None:
        state = dsc.advance(dsc.RotationState(), self.slots, 3, T0)
        self.assertEqual(dsc.RotationState.from_json(state.to_json()), state)
        self.baseline(job("acme", "1", published=ago(days=30)))
        before = self.w.state.load_boards()
        legacy = json.dumps({"cursor": 5, "fingerprint": "x", "total": 9, "cycles": 0, "runs": 1, "last_run_at": ""})
        self.w.state.save_discovery_state({dsc.ROTATION_KEY: legacy}, "t")
        self.w.run(minutes_later=60, discover=lambda ctx: dsc.DiscoveryResult(), rotation_slots=self.slots, force_discovery=True)
        after = self.w.state.load_boards()
        self.assertEqual({k: (r.status, r.provenance, r.baselined_at) for k, r in before.items()}, {k: (r.status, r.provenance, r.baselined_at) for k, r in after.items()})

    def test_backfill_walks_its_own_cursor_and_never_moves_the_scheduled_one(self) -> None:
        base = dsc.advance(dsc.RotationState(), self.slots, 1, T0)
        moved = dsc.advance_backfill(base, self.slots, 3)
        self.assertEqual((moved.cursor, moved.backfill_cursor), (base.cursor, 3))
        self.assertEqual(dsc.plan_slots(moved, self.slots, 1, backfill=True)[0], self.slots[3])
        self.assertEqual(dsc.plan_slots(moved, self.slots, 1)[0], self.slots[1])
        later = dsc.advance(moved, self.slots, 1, T0)
        self.assertEqual(later.backfill_cursor, 3)  # a scheduled run keeps the backfill's place


class BackfillPipelineTests(HarnessCase):
    slots = dsc.make_slots(["boards.greenhouse.io", "jobs.lever.co"], ["Marketing", "Design"], [])

    def test_a_backfill_run_moves_only_its_own_cursor_in_the_persisted_state(self) -> None:
        self.w.state.save_discovery_state({dsc.ROTATION_KEY: dsc.advance(dsc.RotationState(), self.slots, 1, T0).to_json()}, "t")
        self.w.run(discover=lambda ctx: dsc.DiscoveryResult(kind=dsc.KIND_BACKFILL, slots_used=2), rotation_slots=self.slots, force_discovery=True)
        stored = json.loads(self.w.state.load_discovery_state()[dsc.ROTATION_KEY])
        self.assertEqual((stored["cursor"], stored["backfill_cursor"]), (1, 2))


class NoLeftoversTests(unittest.TestCase):
    def test_no_serper_or_google_syntax_remains_in_the_code(self) -> None:
        root = Path(__file__).resolve().parent.parent
        offenders = []
        for f in ("hunter.py", "pipeline.py", "discovery.py", "search.py", "boards.py", "inventory.py", "pools.py", "state.py", "ledger.py"):
            for n, line in enumerate((root / f).read_text().splitlines(), 1):
                low = line.lower()
                legacy_ok = "written before" in low or "serper:" in low or '"serper"' in low or "previous search provider" in low or "(serper" in low
                if ("serper" in low or "tbs" in low or "google.serper" in low or "x-api-key" in low) and not legacy_ok:
                    offenders.append(f"{f}:{n}: {line.strip()[:90]}")
        self.assertEqual(offenders, [])
        for f in (root / ".github" / "workflows").glob("*.yml"):
            text = f.read_text()
            self.assertNotIn("SERPER", text)
            self.assertNotIn("SEARCH_TBS", text)

    def test_workflows_pass_the_tavily_key(self) -> None:
        text = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "job_hunter.yml").read_text()
        self.assertIn("TAVILY_API_KEY: ${{ secrets.TAVILY_API_KEY }}", text)


if __name__ == "__main__":
    unittest.main()
