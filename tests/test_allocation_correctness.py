"""Targeted tests for the allocation correctness pass (D-31 .. D-35).

Each test pins one transition or failure case found by tracing the allocation over several weekly
cycles: oscillating returns, trials that can never be judged, activity read from an outage as
"no hiring", gap discoveries read as publications, and overlapping writers. Everything is mocked.
"""

from __future__ import annotations

import random
import sys
import tempfile
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
import pools  # noqa: E402
import state as st_mod  # noqa: E402
from test_core import T0, ago  # noqa: E402
from test_inventory import FakeSh  # noqa: E402
from test_pools import EST, EXP, mk, policy, reg, wait  # noqa: E402

DAY = timedelta(days=1)


# --------------------------------------------------------------------------- allocation over weeks


def simulate(n_legacy: int, n_waiting: int, weeks: int, *, mode: str = "on", max_active: int = 100, open_of_losers: tuple[int, ...] = (1, 2, 5)) -> tuple[dict[str, bd.BoardRecord], list[dict[str, Any]]]:
    """Hourly activation + polling and a weekly rebalance over an in-memory registry (no ledger):
    `n_legacy` boards monitored before pools existed, `n_waiting` never-tried validated boards."""
    rnd = random.Random(1)
    quality: dict[str, tuple[int, int]] = {}
    registry: dict[str, bd.BoardRecord] = {}
    start = datetime(2026, 10, 14, 12, 17, tzinfo=timezone.utc)
    for i in range(n_legacy):
        name = f"leg{i:03d}"
        quality[name] = (rnd.choice([0, 0, 1, 2, 3]), rnd.choice(open_of_losers))
        registry[f"greenhouse|{name}"] = bd.BoardRecord(
            "greenhouse", name, "2026-01-01T00:00:00Z", "seed", bd.STATUS_ACTIVE, baselined_at="2026-09-01T00:00:00Z", validation=bd.V_VALID,
            activity_since="2026-09-01T00:00:00Z", complete_polls=500, relevance_at="2026-10-14T11:17:00Z",
        )  # fmt: skip
    for i in range(n_waiting):
        name = f"wait{i:03d}"
        quality[name] = (rnd.choice([0, 1, 2, 4]), 1)
        registry[f"greenhouse|{name}"] = bd.BoardRecord(
            "greenhouse", name, "2026-01-01T00:00:00Z", "seed", bd.STATUS_VALIDATED, validation=bd.V_VALID, relevant_jobs=1, eligible_jobs=1,
            last_validated_at="2026-10-10T00:00:00Z",
        )  # fmt: skip
    pol = pools.PoolPolicy(max_active=max_active, mode=mode)
    last = start
    history: list[dict[str, Any]] = []
    for hour in range(24 * 7 * weeks + 1):
        now = start + timedelta(hours=hour)
        pools.sync_pools(registry, pol, now)
        for r in bd.activate_waiting(registry, max_monitored=max_active, per_run=10, now=now, trial_days=7, cooldown=pol.cooldown):
            r.baselined_at, r.status = lg.stamp(now), bd.STATUS_ACTIVE
            pools.start_stint(r, now)
        for r in registry.values():
            if r.status in bd.MONITORED:
                activity, open_jobs = quality[r.board]
                r.relevance_at, r.complete_polls, r.consecutive_failures = lg.stamp(now), r.complete_polls + 1, 0
                r.relevant_jobs = r.eligible_jobs = open_jobs
                stint = pools.stint_days(r, now) or 0
                known = stint >= pools.MIN_OBSERVED_DAYS
                r.new_relevant_7d = activity if known else None
                r.new_relevant_30d = int(activity * min(30, stint) / 7) if known else None
        if now - last >= timedelta(days=7) - timedelta(hours=1):
            plan = pools.plan_rebalance(registry, pol, now)
            before = {k: (r.pool, r.weak_streak) for k, r in registry.items()}
            if mode == "on":
                pools.apply_plan(registry, plan, now)
            else:
                assert before == {k: (r.pool, r.weak_streak) for k, r in registry.items()}
            last = now
            history.append({"day": hour // 24, "plan": plan, "cov": pools.coverage(registry, now, None, pol.cooldown)})
    return registry, history


class AllocationProgressTests(unittest.TestCase):
    def test_migration_graduation_return_and_admission_make_progress(self) -> None:
        registry, hist = simulate(100, 60, 5)
        first = hist[0]
        self.assertEqual((first["plan"].count("graduate"), first["plan"].count("return"), first["plan"].count("replace")), (80, 20, 0))
        self.assertEqual((first["cov"]["established"], first["cov"]["exploration"]), (80, 0))  # trials left, slots free for waiting boards
        self.assertEqual(hist[1]["cov"]["exploration"], 20)  # ... and were refilled with boards never tried before
        tried = [r for r in registry.values() if r.board.startswith("wait") and r.trials > 0]
        self.assertGreaterEqual(len(tried), 20)  # waiting candidates really entered
        for h_ in hist:
            self.assertLessEqual(h_["plan"].replacements, 20)

    def test_graduation_into_a_vacancy_is_not_a_replacement_and_the_cap_does_not_limit_exploration_turnover(self) -> None:
        trials = [mk(f"t{i:02d}", EXP, n30=0, open_=1) for i in range(30)]
        registry = reg(*trials, *[wait(f"w{i:02d}") for i in range(30)])
        plan = pools.plan_rebalance(registry, policy(max_active=100, exploration_pct=50, max_replacements=2), T0)
        self.assertEqual((plan.count("graduate"), plan.replacements), (30, 0))  # 50 vacancies in established: no victims needed
        # with the established pool full, losing trials are returned freely: the replacement cap only bounds established boards
        full = [mk(f"e{i:02d}", EST, n30=30, open_=5) for i in range(50)]
        losers = [mk(f"l{i:02d}", EXP, n30=0, open_=1) for i in range(10)]
        registry = reg(*full, *losers, *[wait(f"w{i:02d}") for i in range(10)])
        plan = pools.plan_rebalance(registry, policy(max_active=60, exploration_pct=17, max_replacements=2), T0)
        self.assertEqual((plan.count("return"), plan.replacements), (10, 0))

    def test_returned_boards_cool_down_instead_of_oscillating_back_in(self) -> None:
        registry, hist = simulate(100, 5, 6)
        self.assertLessEqual(max(r.trials for r in registry.values()), 3)  # was 4+ boards re-baselined EVERY week before the cool-down
        returned_at = {}
        for r in registry.values():
            if r.status == bd.STATUS_VALIDATED and r.trials > 0 and r.pool_since:
                returned_at[r.key] = r.pool_since
        for key, since in returned_at.items():  # nobody sits in the waiting list inside its cool-down window
            rec = registry[key]
            end = datetime.strptime(since, bd.STAMP).replace(tzinfo=timezone.utc) + pools.PoolPolicy().cooldown
            now = datetime(2026, 10, 14, 12, 17, tzinfo=timezone.utc) + timedelta(days=42)
            self.assertEqual(bd.is_waiting_candidate(rec, now=now, cooldown=pools.PoolPolicy().cooldown), now >= end, key)

    def test_cooldown_applies_only_to_boards_that_already_had_a_stint(self) -> None:
        fresh, tried = wait("never", trials=0), wait("tried", trials=1)
        tried.pool_since = ago(days=2)
        fresh.pool_since = ago(minutes=5)
        cd = timedelta(days=14)
        self.assertTrue(bd.is_waiting_candidate(fresh, now=T0, cooldown=cd))
        self.assertFalse(bd.is_waiting_candidate(tried, now=T0, cooldown=cd))
        self.assertTrue(bd.is_waiting_candidate(tried, now=T0 + timedelta(days=13), cooldown=cd))
        self.assertTrue(bd.is_waiting_candidate(tried))  # no clock: no cool-down (callers that do not ask)

    def test_report_mode_changes_neither_allocation_nor_weak_streaks(self) -> None:
        simulate(100, 20, 3, mode="report")  # asserts inside: pool and streak of every board are unchanged after each plan
        registry = reg(mk("e1", EST, streak=0, n30=0, open_=1), mk("t1", EXP, n30=30, open_=5))
        plan = pools.plan_rebalance(registry, policy(max_active=2), T0)
        self.assertEqual(plan.streaks, {"greenhouse|e1": 1})  # the plan says what WOULD change ...
        self.assertEqual(registry["greenhouse|e1"].weak_streak, 0)  # ... planning itself never writes it

    def test_the_two_check_rule_cannot_deadlock_when_no_replacement_happens(self) -> None:
        registry = reg(mk("e1", EST, streak=0, n30=0, open_=1), mk("t1", EXP, n30=30, open_=5))
        pol = policy(max_active=2)
        first = pools.plan_rebalance(registry, pol, T0)
        self.assertEqual(first.count("replace"), 0)
        pools.apply_plan(registry, first, T0)
        self.assertEqual(registry["greenhouse|e1"].weak_streak, 1)  # recorded although nobody left
        later = T0 + 7 * DAY
        for rec in registry.values():  # a week of healthy hourly polls
            rec.relevance_at, rec.complete_polls = lg.stamp(later - timedelta(hours=1)), rec.complete_polls + 168
        second = pools.plan_rebalance(registry, pol, later)
        self.assertEqual(second.count("replace"), 1)


class UnjudgedTrialTests(unittest.TestCase):
    def thin(self, name: str, age_days: int, **kw: Any) -> bd.BoardRecord:
        rec = mk(name, EXP, polls=10, **kw)  # 10 complete polls: never enough evidence
        rec.pool_since = ago(days=age_days)
        return rec

    def test_thin_evidence_extends_a_young_trial_but_never_forever(self) -> None:
        pol = policy(max_active=10, exploration_pct=50)
        young = reg(self.thin("a", 8), wait("w1"))
        self.assertEqual(pools.plan_rebalance(young, pol, T0).decisions[0].action, "extend")
        old = reg(self.thin("a", 22), wait("w1"))
        plan = pools.plan_rebalance(old, pol, T0)
        d = [x for x in plan.decisions if x.key == "greenhouse|a"][0]
        self.assertEqual(d.action, "rotate")
        self.assertIn("no verdict on its hiring activity", d.reason)  # missing evidence is not reported as poor activity
        self.assertNotIn("score", d.reason)

    def test_rotation_keeps_history_and_the_board_cools_down_before_returning(self) -> None:
        pol = policy(max_active=10, exploration_pct=50)
        registry = reg(self.thin("a", 22, n30=None), wait("w1"))
        before = registry["greenhouse|a"]
        counts = (before.relevant_jobs, before.eligible_jobs, before.baselined_at, before.last_success_at, before.validation)
        pools.apply_plan(registry, pools.plan_rebalance(registry, pol, T0), T0)
        a = registry["greenhouse|a"]
        self.assertEqual((a.status, a.pool), (bd.STATUS_VALIDATED, ""))
        self.assertEqual((a.relevant_jobs, a.eligible_jobs, a.baselined_at, a.last_success_at, a.validation), counts)
        self.assertFalse(bd.is_waiting_candidate(a, now=T0 + timedelta(days=1), cooldown=pol.cooldown))
        self.assertTrue(bd.is_waiting_candidate(a, now=T0 + timedelta(days=15), cooldown=pol.cooldown))

    def test_unjudged_trial_is_kept_extended_when_nothing_is_waiting_for_its_slot(self) -> None:
        pol = policy(max_active=10, exploration_pct=50)
        plan = pools.plan_rebalance(reg(self.thin("a", 30)), pol, T0)
        self.assertEqual([d.action for d in plan.decisions], ["extend"])
        self.assertIn("no relevant board is waiting", plan.decisions[0].reason)

    def test_deferral_for_lack_of_a_comparable_established_board_is_also_bounded(self) -> None:
        pol = policy(max_active=2, exploration_pct=50)  # one established slot, held by a board without evidence
        for age, expected in ((8, "defer"), (25, "rotate")):
            good = mk("t1", EXP, **{"n30": 30, "open_": 5})
            good.pool_since = ago(days=age)
            unproven = mk("e1", EST, polls=3)  # established board without evidence: nothing to compare with
            plan = pools.plan_rebalance(reg(good, unproven, wait("w1")), pol, T0)
            self.assertEqual({d.key: d.action for d in plan.decisions}["greenhouse|t1"], expected, age)

    def test_a_trial_that_ends_one_hour_early_is_judged_not_extended_for_a_short_stint(self) -> None:
        rec = mk("t1", EXP, stint_days=7, n30=None, polls=100)
        rec.activity_since = lg.stamp(T0 - timedelta(days=7) + timedelta(minutes=50))  # 6.96 days of stint at the weekly check
        pools.refresh_activity(rec, pools.ActivityIndex(), T0)
        self.assertEqual((rec.new_relevant_7d, rec.new_relevant_30d), (0, 0))  # a real zero, not "unknown"
        rec.activity_since = lg.stamp(T0 - timedelta(days=6))
        pools.refresh_activity(rec, pools.ActivityIndex(), T0)
        self.assertEqual((rec.new_relevant_7d, rec.new_relevant_30d), (None, None))


# --------------------------------------------------------------------------- evidence semantics


def board_with(**kw: Any) -> bd.BoardRecord:
    base = dict(activity_since=ago(days=20), relevance_at=ago(minutes=30), complete_polls=400, new_relevant_30d=3, new_relevant_7d=1)
    base.update(kw)
    return bd.BoardRecord("greenhouse", "acme", ago(days=90), "s", bd.STATUS_ACTIVE, baselined_at=ago(days=20), **base)


class ObservationSpanTests(unittest.TestCase):
    def test_an_outage_is_not_observed_time_and_does_not_lower_the_rate(self) -> None:
        clean = board_with(activity_since=ago(days=10))
        outage = board_with(activity_since=ago(days=20), outages=[[ago(days=18), ago(days=8)]])  # 10 of its 20 days were not observed
        self.assertAlmostEqual(pools.observed_days(clean, T0, 30)[0], 10, places=1)
        self.assertAlmostEqual(pools.observed_days(outage, T0, 30)[0], 10, places=1)
        self.assertAlmostEqual(pools.weekly_rate(outage, T0) or 0, pools.weekly_rate(clean, T0) or 0, places=2)  # same 3 postings per 10 observed days
        naive = 3 * 7 / 20  # what the denominator would be if the outage counted as quiet days
        self.assertGreater(pools.weekly_rate(outage, T0) or 0, naive)

    def test_complete_polls_further_apart_than_the_covered_gap_record_an_outage(self) -> None:
        rec = board_with(relevance_at=ago(days=3), outages=[])
        pools.refresh_relevance(rec, [], lambda t: None, T0)
        self.assertEqual(rec.outages, [[ago(days=3), lg.stamp(T0)]])
        steady = board_with(relevance_at=ago(minutes=60 * 5), outages=[])  # a 5 h gap is still covered
        pools.refresh_relevance(steady, [], lambda t: None, T0)
        self.assertEqual(steady.outages, [])

    def test_a_new_stint_does_not_inherit_the_previous_stints_outages_or_relevance_time(self) -> None:
        rec = board_with(relevance_at=ago(days=30), outages=[[ago(days=40), ago(days=35)]])
        pools.start_stint(rec, T0)
        pools.refresh_relevance(rec, [], lambda t: None, T0)
        self.assertEqual(rec.outages, [])

    def test_old_outages_are_pruned(self) -> None:
        rec = board_with(outages=[[ago(days=60), ago(days=50)], [ago(days=5), ago(days=4)]])
        pools.refresh_relevance(rec, [], lambda t: None, T0)
        self.assertEqual(rec.outages, [[ago(days=5), ago(days=4)]])

    def test_a_board_that_could_not_be_read_for_days_has_unknown_activity_not_zero(self) -> None:
        rec = board_with(activity_since=ago(days=20), relevance_at=ago(days=6))  # last complete poll 6 days ago: still in an outage
        pools.refresh_activity(rec, pools.ActivityIndex(), T0)
        self.assertIsNone(rec.new_relevant_7d)  # only ~1 day of the last week was observed
        self.assertIsNotNone(rec.new_relevant_30d)  # the 30-day window still has 14 observed days: a partially observed window
        self.assertAlmostEqual(pools.observed_days(rec, T0, 30)[0], 14, places=1)
        healthy = board_with(activity_since=ago(days=20), relevance_at=ago(minutes=30))
        pools.refresh_activity(healthy, pools.ActivityIndex(), T0)
        self.assertEqual(healthy.new_relevant_7d, 0)  # observed all week: a real zero

    def test_too_little_observed_time_makes_the_score_unknown_and_blocks_decisions(self) -> None:
        rec = board_with(activity_since=ago(days=20), relevance_at=ago(days=16), complete_polls=400)
        pools.refresh_activity(rec, pools.ActivityIndex(), T0)
        self.assertIsNone(pools.score(rec, T0))
        self.assertIn("observed days", pools.evidence_problem(rec, T0, policy()) or "")


class CountsAsNewPostingTests(unittest.TestCase):
    def test_only_evidence_of_recency_counts(self) -> None:
        f = pools.counts_as_new_posting
        self.assertTrue(f(fr.VERIFIED_FRESH, {"source": "poll"}))
        self.assertTrue(f(fr.OBSERVED_NEW, {"source": "poll", "gap_min": 60}))
        self.assertTrue(f(fr.OBSERVED_NEW, {"source": "poll", "gap_min": 360}))
        self.assertFalse(f(fr.OBSERVED_NEW, {"source": "poll", "gap_min": 600}))  # a gap discovery: we do not know when it appeared
        self.assertFalse(f(fr.OBSERVED_NEW, {"source": "poll"}))  # no gap recorded
        self.assertFalse(f(fr.UNCERTAIN, {"source": "poll", "gap_min": 60}))
        self.assertFalse(f(fr.RECENT, {"source": "poll", "gap_min": 60}))  # dated before the window: listed late, not published now
        self.assertFalse(f(fr.VERIFIED_FRESH, {"source": "poll", "pass": "baseline"}))
        self.assertFalse(f(fr.VERIFIED_FRESH, {"source": "poll", "pass": "reentry"}))
        self.assertFalse(f(fr.VERIFIED_FRESH, {"source": "other"}))

    def test_a_search_found_job_counts_once_when_its_source_time_proves_it_fresh(self) -> None:
        states: dict[str, lg.JobState] = {}
        for kind, source, fresh in (("a", "search", fr.VERIFIED_FRESH), ("b", "search", fr.UNCERTAIN), ("c", "poll", fr.VERIFIED_FRESH)):
            ev = lg.Event(ago(hours=1), f"greenhouse|acme|{kind}", lg.SEEN, fresh, lg.PENDING, "", {"source": source, "board": "acme", "gap_min": 60})
            states.update(lg.replay([ev, ev]))  # a repeated event still replays to one posting
        times = pools.ActivityIndex.from_states(states).times("greenhouse|acme")
        self.assertEqual(len(times), 2)  # a (provenance: serper) and c; b is only a discovery


class ListingCompletenessTests(unittest.TestCase):
    def fetch(self, payload: dict[str, Any]) -> Any:
        from unittest import mock

        with mock.patch.object(bd, "_get_json", return_value=payload):
            return bd.fetch_board(bd.BoardId(bd.GREENHOUSE, "acme"))

    def test_greenhouse_listing_shorter_than_its_reported_total_is_incomplete(self) -> None:
        jobs = [{"id": i, "title": "x", "absolute_url": "u"} for i in range(3)]
        self.assertFalse(getattr(self.fetch({"jobs": jobs, "meta": {"total": 5}}), "complete", True))
        self.assertTrue(getattr(self.fetch({"jobs": jobs, "meta": {"total": 3}}), "complete", True))
        self.assertTrue(getattr(self.fetch({"jobs": jobs}), "complete", True))  # no total reported: nothing to compare with

    def test_an_incomplete_poll_does_not_refresh_evidence_or_count_as_an_observed_poll(self) -> None:
        rec = board_with(relevance_at=ago(minutes=30), complete_polls=10)
        # the pipeline only calls refresh_relevance for complete listings; the evidence timestamp therefore ages
        # and the hole is recorded when the next complete poll arrives
        later = T0 + timedelta(hours=10)
        pools.refresh_relevance(rec, [], lambda t: None, later)
        self.assertEqual(len(rec.outages), 1)


# --------------------------------------------------------------------------- serialized writers


class LeaseTests(unittest.TestCase):
    def check(self, state: Any, *, expires: bool = True) -> None:
        ttl = timedelta(minutes=30)
        first = state.acquire_lease("poller", ttl, T0, settle=0, sleep=lambda s: None)
        self.assertTrue(first.ok)
        second = state.acquire_lease("inventory", ttl, T0 + timedelta(minutes=5), settle=0, sleep=lambda s: None)
        self.assertFalse(second.ok)
        self.assertIn("poller", second.held_by)  # the holder is named and is never cancelled
        state.release_lease("someone-else")  # a stranger's token releases nothing
        self.assertFalse(state.acquire_lease("inventory", ttl, T0 + timedelta(minutes=6), settle=0, sleep=lambda s: None).ok)
        state.release_lease(first.token)
        third = state.acquire_lease("inventory", ttl, T0 + timedelta(minutes=7), settle=0, sleep=lambda s: None)
        self.assertTrue(third.ok)
        if expires:  # a crashed holder cannot block forever: the Sheet lease expires (the file lease dies with its process instead)
            self.assertTrue(state.acquire_lease("poller", ttl, T0 + timedelta(minutes=7) + ttl + timedelta(seconds=1), settle=0, sleep=lambda s: None).ok)

    def test_csv_state_lease(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.check(st_mod.CsvState(Path(d)), expires=False)

    def test_sheet_state_lease(self) -> None:
        state = st_mod.SheetState(FakeSh())
        state.ensure()
        self.check(state)

    def test_sheet_lease_lost_to_a_concurrent_writer_is_detected_by_the_read_back(self) -> None:
        state = st_mod.SheetState(FakeSh())
        state.ensure()
        ws = state.sh.worksheet(st_mod.LOCK_TAB)

        def rival(_: float) -> None:  # another process overwrites the row during the settle delay
            ws.update(values=[["rival:1", "poller", lg.stamp(T0), lg.stamp(T0 + timedelta(minutes=30))]], range_name="A2")

        lease = state.acquire_lease("inventory", timedelta(minutes=30), T0, settle=1, sleep=rival)
        self.assertFalse(lease.ok)

    def test_hunter_waits_then_reports_busy_instead_of_overlapping(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = type("S", (), {})()
            store.state = st_mod.CsvState(Path(d))
            held = store.state.acquire_lease("inventory", timedelta(minutes=45), datetime.now(timezone.utc))
            self.assertTrue(held.ok)
            slept: list[float] = []
            with self.assertRaises(h.WriterBusy):
                with h.writer_lease(store, "poller", wait_seconds=0, sleep=slept.append):
                    self.fail("must not run while another writer holds the lease")
            with h.writer_lease(store, "poller", enabled=False):  # dry runs and read-only commands never take it
                pass
            store.state.release_lease(held.token)
            with h.writer_lease(store, "poller", wait_seconds=0):
                self.assertFalse(store.state.acquire_lease("inventory", timedelta(minutes=1), datetime.now(timezone.utc)).ok)
            self.assertTrue(store.state.acquire_lease("inventory", timedelta(minutes=1), datetime.now(timezone.utc)).ok)  # released on exit


class ReconcileTests(unittest.TestCase):
    def rows(self) -> tuple[bd.BoardRecord, bd.BoardRecord]:
        stored = bd.BoardRecord("greenhouse", "acme", "2026-10-01T00:00:00Z", "search", bd.STATUS_ACTIVE, provenance={"search": {"first": "2026-10-01T00:00:00Z"}})
        incoming = bd.BoardRecord(
            "greenhouse", "acme", "2026-10-01T00:00:00Z", "search", bd.STATUS_VALIDATED, name="Acme Inc",
            provenance={"search": {"first": "2026-10-01T00:00:00Z"}, "open-ats-feed": {"first": "2026-10-14T00:00:00Z", "state": "live"}},
        )  # fmt: skip
        return stored, incoming

    def test_skipped_row_keeps_the_stored_state_and_gains_the_provenance(self) -> None:
        stored, incoming = self.rows()
        with tempfile.TemporaryDirectory() as d:
            state = st_mod.CsvState(Path(d))
            state.ensure()
            state.save_boards([stored])
            skipped = state.save_boards([incoming], skip_if_status=frozenset({bd.STATUS_NEW, bd.STATUS_ACTIVE}))
            self.assertEqual(skipped, [stored.key])
            back = state.load_boards()[stored.key]
            self.assertEqual((back.status, back.name), (bd.STATUS_ACTIVE, "Acme Inc"))  # the poller's status survives
            self.assertIn("open-ats-feed", back.provenance)  # the importer's discovery is not lost

    def test_sheet_store_reconciles_skipped_rows_too(self) -> None:
        stored, incoming = self.rows()
        state = st_mod.SheetState(FakeSh())
        state.ensure()
        state.save_boards([stored])
        state.load_boards()
        skipped = state.save_boards([incoming], skip_if_status=frozenset({bd.STATUS_NEW, bd.STATUS_ACTIVE}))
        self.assertEqual(skipped, [stored.key])
        back = state.load_boards()[stored.key]
        self.assertEqual(back.status, bd.STATUS_ACTIVE)
        self.assertEqual(set(back.provenance), {"search", "open-ats-feed"})

    def test_merge_never_overwrites_existing_provenance_values(self) -> None:
        stored, incoming = self.rows()
        stored.provenance["open-ats-feed"] = {"first": "2026-09-01T00:00:00Z"}
        self.assertTrue(bd.merge_provenance(stored, incoming))  # gains "state"
        self.assertEqual(stored.provenance["open-ats-feed"], {"first": "2026-09-01T00:00:00Z", "state": "live"})
        self.assertFalse(bd.merge_provenance(stored, incoming))  # idempotent


if __name__ == "__main__":
    unittest.main()
